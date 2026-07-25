# delta-chat

Ingests two P&ID document revisions ("PIDs"), computes a structured delta,
renders a delta report, and answers grounded chat questions over both
documents plus the delta report.

Built as a take-home under a tight same-day deadline — scope was cut
deliberately (see "What we cut and why"). This README tells you exactly
what works, what's stubbed, and what's honestly still broken.

## Quick start

```bash
python -m pip install -r requirements.txt
cp .env.example .env        # optionally add an API key; runs fine without one (mock LLM fallback)

make run     # ingest data/samples pair -> output/pair_001/{delta.json, delta_report.md}
make chat    # interactive grounded chat over that pair
make eval    # prints the eval scorecard
```

`LLM_PROVIDER` in `.env` selects the chat backend: `openai`, `groq`, or `mock`
(the default when no key is set for the selected provider). Groq's API is
OpenAI-wire-compatible, so `GroqClient` just points the `openai` SDK at a
different `base_url` — see `src/chat/llm.py`. This repo was actually
exercised end-to-end against real Groq (`llama-3.3-70b-versatile`) calls, not
just the mock fallback; see "Known limitations" for the real numbers and two
genuine bugs that only a real model surfaced.

No `make`? The Makefile targets are one-liners — run the `python -m src.cli ...` /
`python -m eval.run_eval` commands directly (see `Makefile`).

Every `run` and `chat` invocation writes a full JSON trace to `traces/`
(one file per request, keyed by `request_id`, plus an append-only
`traces/traces.jsonl`).

## What's real vs. stubbed

| Capability | Status |
|---|---|
| Native PDF ingestion | **Real.** PyMuPDF structured text extraction, spatially grouped into lines with bounding boxes. |
| Scanned PDF ingestion | **Real interface, stubbed body.** Rasterizes via PyMuPDF and calls `pytesseract` if installed + a Tesseract binary is on `PATH`; neither is available in the environment this was built in, so it raises a clear `AdapterUnavailableError` instead of pretending to work. See `src/ingest/pdf_scanned.py`. |
| DWG ingestion | **Stub.** Same `FormatAdapter` interface, no sample file and no time to stand up an ODA/`ezdxf` conversion path. See `src/ingest/dwg.py` docstring for the intended design. |
| Delta engine | **Real, deterministic**, no LLM. |
| Delta report | **Real.** Markdown + JSON. |
| Grounded chat | **Real, tested against a live LLM.** TF-IDF retrieval (scikit-learn) + swappable LLM client (OpenAI, Groq, or a labeled mock fallback). |
| Observability | **Real.** Homegrown JSON tracer + structured JSON logs (see below for why homegrown). |
| Eval harness | **Real**, runnable, self-contained. |
| Delta markup (bonus) | **Not built.** `make markup` prints the reason and the intended design instead of pretending. |

## The sample pair

`data/samples/pair_001_lift_gas_KA901_A.pdf` (PID A) and
`pair_001_export_gas_KA902_B.pdf` (PID B) are two real P&IDs provided directly
for this task: the 3rd Stage HP Gas **Lift** Compressor (26-KA-901) and 3rd
Stage HP Gas **Export** Compressor (26-KA-902). They share the same drawing
template (note numbering, tag conventions, equipment-data-table layout) but
describe two different compressor trains — see `data/samples/PROVENANCE.md`
for why that's actually a *better* stress test for the delta engine than a
trivial two-revision edit would be: a raw text diff would flag nearly the
whole page as "changed" (every tag number differs), so alignment quality is
what separates a real delta engine from a diff tool.

## Architecture

```
src/
  ingest/        FormatAdapter interface + pdf_native / pdf_scanned / dwg adapters
  canonical/      format-agnostic CanonicalDocument (pages -> lines -> bbox)
  delta/          align.py (matching) -> engine.py (classify+confidence) -> report.py (render)
  chat/           index.py (retrieval) -> llm.py (provider-agnostic) -> answer.py (grounded answer)
  observability/  tracing.py, logging.py
  cli.py          `run` and `chat` commands, wires everything with tracing
eval/
  datasets/pair_001/   hand-labeled ground truth + sample-precision review + QA set
  metrics.py, run_eval.py
```

Adding a 4th ingestion format means writing one new `FormatAdapter` subclass
and registering it in `src/ingest/base.py:detect_and_load` — nothing else
changes, because delta/chat/eval only ever depend on `CanonicalDocument`.

## Design decisions and trade-offs

**Alignment is deterministic and LLM-free.** The delta engine (`src/delta/align.py`,
`engine.py`) matches content between two revisions using a blend of text
similarity (difflib) and spatial similarity (bbox-center distance), not an
LLM. Two reasons: (1) it needs to be reproducible byte-for-byte for the
"determinism" requirement, and (2) for this document type, position is a
*stronger* signal than text for "is this the same slot in the drawing" —
tag numbers change entirely between revisions/trains but stay in the same
table cell. The one place an LLM genuinely earns its keep is chat answer
generation, where the question isn't fixed and synthesis actually matters.

**Chunking for retrieval groups lines into row bands** (`src/chat/index.py`),
because P&ID text extracts as many short, scattered fragments (a label, a
unit, a number, each its own "line") — a lone `"776"` doesn't look like a
"compressor duty" to a retriever. Grouping same-page lines within a small
y-tolerance reconstructs table rows like `"DUTY kW 776"` before indexing.

**Retrieval is TF-IDF, not embeddings.** Simpler, no API dependency, and it
works well for tag/value lookups. It has a real, evidenced weakness: see
"Known limitations" below — this was the right initial call given the time
box, but embeddings are the clear next step.

**Observability is a homegrown JSON tracer**, not OpenTelemetry/Langfuse/etc.
This is a single-process, offline-runnable take-home; a dependency-free
tracer that a reviewer can `cat traces/*.json` with zero setup felt more
honest than wiring a hosted tool for a few-hour build. The `Trace`/`Span`
shape (name, start/end, attributes) maps directly onto OTel spans if this
were promoted to a real service.

**Precision is measured on a fixed-seed random sample, not the full
prediction set.** With ~430 predicted delta items and a few hours, hand-labeling
every one isn't feasible. `eval/datasets/pair_001/predicted_sample_review.json`
documents the exact sampling method (`random.seed(42)`, stratified across
modified/removed/added) and a manually-verified correct/incorrect judgment
per sampled item, each with a one-line reason. Recall is measured against a
separate, fully hand-labeled ground-truth set of 15 real changes
(`ground_truth_deltas.json`).

## What we cut, and why

- **Scanned PDF / DWG made "real but stubbed"** instead of fully implemented:
  no Tesseract binary or DWG sample was available in the time box. The
  adapter seam is real (same interface, would work unchanged if the runtime
  dependency were present) — see the table above.
- **No embeddings-based retrieval**: TF-IDF was faster to ship correctly and
  is fully offline; the eval scorecard's own chat failures are the evidence
  for why this is the first thing to upgrade (see below).
- **No delta markup (bonus)**: correctly detecting and reporting the delta
  was prioritized over drawing boxes on top of it. `make markup` explains
  the intended design (draw `delta.json` bboxes back onto PID B via PyMuPDF
  annotations) rather than shipping a half-working overlay.
- **LLM-based description enrichment** (rewriting `DeltaItem.description`
  into friendlier prose) was designed for but not built — template
  descriptions are used instead, keeping the delta report fully
  reproducible without an API key.

## Known limitations (candid, from the eval run)

Run `make eval` (or `python -m eval.run_eval`) to reproduce these numbers.

**Delta engine: recall 0.867 (13/15), sample-precision 0.721 (31/43), F1 0.787.**

- Two ground-truth items are *known misses*: the compressor `DUTY` and `FLOW RATE`
  values sit in adjacent table rows whose relative vertical spacing shifts
  slightly between the two PDF exports. The alignment algorithm's blended
  text+position score cross-matches them (duty→flow-rate, flow-rate→duty)
  instead of duty→duty. This is a real, reproducible alignment bug in dense
  data tables, not a hidden failure — it's exactly what recall is supposed
  to catch, and it does.
- The single largest source of *false* positives (~7 of 12 sampled
  precision errors) is enumerated-note prefix fragmentation: `"11. COMPRESSOR
  MOTOR..."` sometimes extracts as two separate line fragments (`"11."` +
  `"COMPRESSOR MOTOR..."`) in one PDF export but as one fragment in the
  other, purely from kerning/line-break differences at export time — not a
  real content edit. A fix would need to merge adjacent same-row fragments
  before diffing rather than after (i.e. push the row-chunking logic
  currently only used for chat retrieval into the delta engine itself).
- A handful of precision errors are genuine cross-alignment mistakes in
  dense, generic-token regions (the fitting/valve-code legend grid, trailing
  words of adjacent notes) where several short, similarly-positioned
  fragments compete for the same match.

**Grounded chat, real LLM (Groq `llama-3.3-70b-versatile`, stable across 3
runs): answer correctness 0.667 (4/6), groundedness 0.83–1.0 (varies slightly
run to run).** With the no-key mock fallback, answer correctness was 0.5 (3/6)
for a *different* reason (see below) — the real-LLM number is the one that
matters and is the one to reproduce (`LLM_PROVIDER=groq` + `GROQ_API_KEY` in
`.env`).

- The 2 consistent misses (QA05, QA06) are the model *hedging* — it retrieves
  the correct supporting chunk (visible in the trace: e.g. `[D0329]` for the
  balance-line-cooler question) but answers "the context does not contain
  enough information" anyway rather than committing. This is arguably the
  system erring in the safe direction for a grounded-chat requirement
  (under-claiming, not hallucinating) — but it does cost answer-correctness
  points. Lowering temperature further or tightening the system prompt's
  "say so if unsupported" wording would likely help; not tuned further given
  the time box.
- Groundedness dips to 0.83 on some runs because the model occasionally
  writes its own hedge phrase inside brackets, e.g. `[No citation available]`
  — technically not a tag copied from context, so the citation-validator
  correctly flags it as unverifiable. Not a fabricated citation to real
  content, just the model's hedge language landing inside the same bracket
  syntax real citations use.
- **Two real bugs were only caught by testing against a live model, not the
  mock:** (1) an earlier citation format used square brackets inside the tag
  itself (`pid_a:p1@[27,539]`), which nested with the `[...]` wrapper the LLM
  was told to use and broke a non-recursive parser on real model output —
  fixed by making the tag delimiter-free (`pid_a:p1@27x539`, see
  `src/chat/index.py:Chunk.citation`). (2) the system prompt's own worked
  example (`"the duty is 776 kW [pid_a:p1@164x551]"`) happened to describe
  the *actual* real duty value in the sample pair, so the model copied that
  literal example into its answer instead of the real retrieved citation —
  fixed by removing the concrete example from the prompt entirely. Neither
  bug was visible with the mock LLM, since the mock never generates novel
  text — a concrete argument for why "tested against mock only" is not the
  same as "tested."

With the **mock fallback** (no key / `LLM_PROVIDER=mock`), the 3 misses (QA01–03)
are a retrieval-quality issue instead: TF-IDF ranks a few short, generic-word
delta-report chunks (containing words like "COMPRESSOR" or "VENDOR") above
the actual data-table row that answers the question, so the correct row falls
outside the top-k retrieved context — and the mock's naive "quote the top-N
literally" strategy can't recover from that the way a real LLM reading the
full context window can (and does, per above).

## What we'd do next with more time

1. **Fix the table cross-alignment bug** (GT01/GT02 above) by widening the
   matching to consider row-order, not just raw pixel distance, within
   detected table regions.
2. **Move row-chunking into the delta engine**, not just retrieval, to
   collapse the note-prefix-fragmentation false positives.
3. **Swap TF-IDF for an embeddings retriever** (or at minimum: boost chunks
   containing recognized field labels like `TAG NUMBER`, `VENDOR`, `DUTY`,
   `SERVICE`) — directly motivated by the chat eval failures above.
4. **Real scanned-PDF and DWG adapters** — install Tesseract, wire up
   `pytesseract`; add `ezdxf` + an ODA DWG→DXF conversion step.
5. **Delta markup overlay** (bonus): draw `delta.json` bboxes back onto PID B.
6. **LLM-based delta description enrichment**, behind a flag, for a more
   readable report — keeping the current template output as the
   reproducible default.

## Environment notes

Built and tested on Windows with Python 3.14, no `tesseract`/`ezdxf` binaries
available. Both real LLM providers were actually exercised: `OpenAIClient`
authenticates correctly but the available OpenAI key has no billing/quota
(`429 insufficient_quota`) — that failure is what led to hardening the error
handling in `src/cli.py` and `eval/metrics.py` (an LLM call failing now
produces a finished trace with `had_error: true` and a clear message, not a
crash). `GroqClient` (`llama-3.3-70b-versatile`, OpenAI-wire-compatible API)
worked end-to-end and is what the real numbers in "Known limitations" above
come from. Both clients share the same `_OpenAICompatibleClient` base in
`src/chat/llm.py` — only the API key env var, default model, and base URL
differ.
