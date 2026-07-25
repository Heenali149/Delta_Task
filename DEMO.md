# Demo walkthrough

No screen recording — real terminal transcripts from this repo instead,
reproducible with `pip install -r requirements.txt` and a Groq key (Groq has
a free tier; get one at console.groq.com). Set `LLM_PROVIDER=groq` and
`GROQ_API_KEY` in `.env`. Without a key at all, everything still runs via the
mock LLM fallback — see README "Known limitations" for how those numbers
differ and why.

## 1. Ingest + delta + report (`make run`)

```
$ python -m src.cli run --a data/samples/pair_001_lift_gas_KA901_A.pdf \
    --b data/samples/pair_001_export_gas_KA902_B.pdf \
    --pid-a pair_001:lift_gas:A --pid-b pair_001:export_gas:B \
    --rev-a "Lift Gas KA-901" --rev-b "Export Gas KA-902" --out output/pair_001

{"ts": ..., "level": "INFO", "logger": "delta_chat", "msg": "run started", "request_id": "29cd83f2-...", ...}
{"ts": ..., "level": "INFO", "logger": "delta_chat", "msg": "run finished", "request_id": "29cd83f2-...",
 "total": 432, "by_change_type": {"modified": 298, "removed": 123, "added": 11},
 "by_item_type": {"text": 321, "note": 15, "spec_value": 8, "tag": 72, "setpoint": 16}}
{
  "total": 432,
  "by_change_type": {"modified": 298, "removed": 123, "added": 11},
  "by_item_type": {"text": 321, "note": 15, "spec_value": 8, "tag": 72, "setpoint": 16}
}

Wrote: output/pair_001/delta.json, output/pair_001/delta_report.md
Trace: traces/29cd83f2-1299-49f6-9375-10a9ab6dab2a.json
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

## 2. Grounded chat (`make chat`) — real LLM (Groq, `llama-3.3-70b-versatile`)

```
$ python -m src.cli chat --session output/pair_001 \
    --ask "What changed in the seal gas system between the two compressors?"

{"ts": ..., "level": "INFO", "logger": "delta_chat", "msg": "chat question received", "request_id": "8bea86e5-...", ...}
{"ts": ..., "level": "INFO", "logger": "delta_chat", "msg": "chat answered", "request_id": "8bea86e5-...",
 "citations_valid": 1, "citations_invalid": 0, "fallback_used": false}

> What changed in the seal gas system between the two compressors?

The change in the seal gas system between the two compressors is that the
primary seal gas is now taken downstream from the last compressing stage
(4th stage) instead of the 8th stage [D0231].

(trace: traces/8bea86e5-725f-4d88-b5dd-e30aa618b8b4.json)
```

`D0231` is checked against what was actually retrieved before being trusted
(`citations_valid`/`citations_invalid` in the trace) — it's a real,
correctly-classified `modified`/`note` delta item, not a fabricated
reference. This exact exchange only works cleanly because two real bugs got
fixed along the way (a citation-format nesting bug and a system-prompt
example that collided with the real answer) — both documented in README
"Known limitations", both only found by testing against a live model instead
of the mock.

With no key configured (`LLM_PROVIDER=mock`), the same command instead
returns a bulleted quote-list of the top retrieved passages rather than a
synthesized sentence — still cited, still grounded, just visibly less fluent:

```
(mock-llm fallback - no LLM API key configured)
Based on the most relevant retrieved passages for "What changed in the seal
gas system between the two compressors?":
- SEAL GAS SECONDARY [pid_b:p1@478x300]
- Note changed from "17.     SECONDARY SEAL GAS AND SEPARATION GAS." to
  "SECONDARY SEAL GAS AND SEPARATION GAS.". [D0126]
- ...
```

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

[Grounded chat]  LLM: llama-3.3-70b-versatile
  Answer correctness: 0.667
  Groundedness (valid citations / claimed citations): 1.000
    [OK] QA01: What is the compressor duty in kW for the Lift Gas compressor, 26-KA-901?
    [OK] QA02: What is the compressor duty in kW for the Export Gas compressor, 26-KA-902?
    [OK] QA03: Who is the vendor for both compressors?
    [OK] QA04: What changed in the primary seal gas take-off point between the two P&IDs?
    [MISS] QA05: Does the Export Gas compressor P&ID have a balance line cooler?
    [MISS] QA06: What is the main equipment tag number change between the two compressors?
```

The delta-engine numbers are exactly reproducible (fully deterministic, no
LLM in that path). The chat numbers above are stable across repeated runs at
temperature 0.1 but not byte-identical — see README "Known limitations" for
why QA05/QA06 miss (the model hedges despite retrieving the right citation)
and why groundedness itself ranges 0.83–1.0 run to run. None of this is
hidden: every miss above has a documented, evidenced root cause, not a
hand-wave.
