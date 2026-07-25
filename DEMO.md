# Demo walkthrough

No screen recording — real terminal transcripts from this repo instead, run
with no `OPENAI_API_KEY` set (mock LLM fallback), so anyone can reproduce
these exact numbers with just `pip install -r requirements.txt`.

## 1. Ingest + delta + report (`make run`)

```
$ python -m src.cli run --a data/samples/pair_001_lift_gas_KA901_A.pdf \
    --b data/samples/pair_001_export_gas_KA902_B.pdf \
    --pid-a pair_001:lift_gas:A --pid-b pair_001:export_gas:B \
    --rev-a "Lift Gas KA-901" --rev-b "Export Gas KA-902" --out output/pair_001

{"ts": ..., "level": "INFO", "logger": "delta_chat", "msg": "run started", "request_id": "85f5a9d8-...", ...}
{"ts": ..., "level": "INFO", "logger": "delta_chat", "msg": "run finished", "request_id": "85f5a9d8-...",
 "total": 432, "by_change_type": {"modified": 298, "removed": 123, "added": 11},
 "by_item_type": {"text": 321, "note": 15, "spec_value": 8, "tag": 72, "setpoint": 16}}
{
  "total": 432,
  "by_change_type": {"modified": 298, "removed": 123, "added": 11},
  "by_item_type": {"text": 321, "note": 15, "spec_value": 8, "tag": 72, "setpoint": 16}
}

Wrote: output/pair_001/delta.json, output/pair_001/delta_report.md
Trace: traces/85f5a9d8-292e-40df-9917-fbcabc1572a3.json
```

An excerpt of `output/pair_001/delta_report.md` (real, meaningful changes the
engine found between the two compressor trains — see README for how
alignment avoids reporting every tag-number difference as unrelated noise):

```
- D0092 (text, conf 0.93): Text changed from "3RD STAGE HP GAS LIFT COMPRESSOR"
  to "3RD STAGE HP GAS EXPORT COMPRESSOR".
- D0058 (tag, conf 0.93): Tag changed from "26-CX-9011" to "26-CX-9021".
- removed: "BALANCE LINE" / "TIT-9211" / "TUBE RUPTURE" -- balance-line cooler
  subsystem exists only in the Lift Gas train, not Export.
- added: "OVERRIDE" / "SP 108.5" / "27-PIT-0001B" -- discharge-pressure
  override control concept exists only in the Export train.
```

## 2. Grounded chat (`make chat`)

```
$ python -m src.cli chat --session output/pair_001 \
    --ask "What changed in the seal gas system between the two compressors?"

> What changed in the seal gas system between the two compressors?

[mock-llm fallback - no LLM API key configured]
Based on the most relevant retrieved passages for "What changed in the seal
gas system between the two compressors?":
- SEAL GAS SECONDARY [pid_b:p1@[478,300]]
- Note changed from "17.     SECONDARY SEAL GAS AND SEPARATION GAS." to
  "SECONDARY SEAL GAS AND SEPARATION GAS.". [D0126]
- Text changed from "SEAL GAS SYSTEM (HC PRIMARY & N2 GAS" to "SEAL GAS
  SYSTEM (HC GAS PRIMARY & N2". [D0070]
- Note changed from "23.     FROM SEAL GAS SYSTEM RUPTURE DISCS." to "FROM
  SEAL GAS SYSTEM RUPTURE DISCS.". [D0022]
- 63BL9020 SEAL GAS SYSTEM (HC GAS PRIMARY & N2 [pid_b:p1@[278,348]]
- 23.     FROM SEAL GAS SYSTEM RUPTURE DISCS. [pid_a:p1@[253,739]]

(trace: traces/1a61acf0-a119-4fd8-94a0-a6f547553856.json)
```

Every citation (`[D0126]`, `[pid_b:p1@[...]]`) is checked against what was
actually retrieved before being trusted — see `citations_valid` /
`citations_invalid` in the trace file. Note this example also honestly
surfaces two of the engine's own known false positives (D0126, D0022 are
note-number-fragmentation artifacts, not real content changes — see README
"Known limitations") rather than a cherry-picked clean example.

With a real `OPENAI_API_KEY` set, the same command sends the same retrieved
context to GPT instead of the extractive mock, and would produce a
synthesized paragraph instead of a bulleted quote-list — the retrieval and
grounding-check logic is identical either way (`src/chat/answer.py`).

## 3. Eval scorecard (`make eval`)

```
$ python -m eval.run_eval

DELTA-CHAT EVAL SCORECARD - pair_001 (Lift Gas 26-KA-901 vs Export Gas 26-KA-902)
========================================================================

[Delta engine]  total predicted changes: 432  {'modified': 298, 'removed': 123, 'added': 11}
  Recall    (hand-labeled ground truth, n=15):  0.867  (13/15 found)
    MISSED: ['GT01', 'GT02']  <- see README known limitations
  Precision (stratified random sample, n=43): 0.721  (31/43 correct)
  F1 (recall x sample-precision): 0.787

[Grounded chat]  LLM: mock (fallback -- no API key set)
  Answer correctness: 0.500
  Groundedness (valid citations / claimed citations): 1.000
    [MISS] QA01: What is the compressor duty in kW for the Lift Gas compressor, 26-KA-901?
    [MISS] QA02: What is the compressor duty in kW for the Export Gas compressor, 26-KA-902?
    [MISS] QA03: Who is the vendor for both compressors?
    [OK] QA04: What changed in the primary seal gas take-off point between the two P&IDs?
    [OK] QA05: Does the Export Gas compressor P&ID have a balance line cooler?
    [OK] QA06: What is the main equipment tag number change between the two compressors?
```

See README "Known limitations" for the root cause of every miss above —
none of them are swallowed or hand-waved.
