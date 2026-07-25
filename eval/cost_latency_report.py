"""Cost & latency budget report.

Runs the QA eval set through the live grounded-chat path with per-question
tracing (unlike eval/run_eval.py's single span wrapping the whole set), then
aggregates latency and LLM cost to answer the operational question a real
deployment needs answered: what does this cost, and where does the time go.

Runnable: `python -m eval.cost_latency_report` (or `make budget`). Each
question also gets its own trace file in traces/, same as `make chat`.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.chat.answer import answer_question
from src.chat.index import RetrievalIndex
from src.chat.llm import get_llm_client
from src.delta.engine import compute_delta
from src.ingest.base import detect_and_load
from src.observability.logging import get_logger
from src.observability.tracing import Trace

logger = get_logger("cost_latency")

PAIR_DIR = ROOT / "eval" / "datasets" / "pair_001"
PID_A_PATH = ROOT / "data" / "samples" / "pair_001_lift_gas_KA901_A.pdf"
PID_B_PATH = ROOT / "data" / "samples" / "pair_001_export_gas_KA902_B.pdf"
REPORT_PATH = Path(__file__).resolve().parent / "cost_latency_report.md"

# Illustrative volume assumption for the monthly projection below -- swap for
# real traffic once this sits behind an actual endpoint.
ASSUMED_QUESTIONS_PER_MONTH = 10_000


def main():
    doc_a = detect_and_load(PID_A_PATH, "pair_001:lift_gas:A", "Lift Gas KA-901")
    doc_b = detect_and_load(PID_B_PATH, "pair_001:export_gas:B", "Export Gas KA-902")
    delta = compute_delta(doc_a, doc_b)
    index = RetrievalIndex(doc_a, doc_b, delta)
    llm = get_llm_client(logger=logger)

    qa_items = json.loads((PAIR_DIR / "qa_ground_truth.json").read_text(encoding="utf-8"))["items"]

    rows = []
    for qa in qa_items:
        trace = Trace(request_type="chat")

        with trace.span("retrieval", question=qa["question"]) as s:
            retrieved = index.retrieve(qa["question"], k=12)
            s.attributes["retrieved_count"] = len(retrieved)
        retrieval_ms = trace.spans[-1].duration_ms

        with trace.span("llm_call", model=llm.model) as s:
            result = answer_question(qa["question"], index, llm, k=12)
            trace.record_llm_call(
                s, model=result.llm_response.model, prompt=result.prompt, response=result.answer,
                input_tokens=result.llm_response.input_tokens, output_tokens=result.llm_response.output_tokens,
                fallback_used=result.llm_response.fallback_used,
            )
        llm_ms = trace.spans[-1].duration_ms
        cost = trace.spans[-1].attributes["llm_cost_usd"]

        trace.finish(question=qa["question"], cost_usd=cost)

        rows.append({
            "id": qa["id"], "retrieval_ms": retrieval_ms, "llm_ms": llm_ms,
            "total_ms": retrieval_ms + llm_ms,
            "input_tokens": result.llm_response.input_tokens,
            "output_tokens": result.llm_response.output_tokens,
            "cost_usd": cost, "model": result.llm_response.model,
        })

    print_and_write_report(rows)


def print_and_write_report(rows: list[dict]):
    model = rows[0]["model"] if rows else "unknown"
    n = len(rows) or 1
    total_ms = [r["total_ms"] for r in rows]
    llm_ms = [r["llm_ms"] for r in rows]
    retrieval_ms = [r["retrieval_ms"] for r in rows]
    costs = [r["cost_usd"] for r in rows]

    avg_total = statistics.mean(total_ms)
    avg_llm = statistics.mean(llm_ms)
    avg_retrieval = statistics.mean(retrieval_ms)
    avg_cost = statistics.mean(costs)
    total_cost = sum(costs)
    projected_monthly = avg_cost * ASSUMED_QUESTIONS_PER_MONTH

    lines = [
        "# Cost & latency budget -- pair_001 QA set",
        "",
        f"Model: `{model}` &middot; {n} questions, one live LLM call each (no caching).",
        "",
        "| Question | retrieval (ms) | LLM call (ms) | total (ms) | in tok | out tok | cost (USD) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['retrieval_ms']:.1f} | {r['llm_ms']:.1f} | {r['total_ms']:.1f} | "
            f"{r['input_tokens']} | {r['output_tokens']} | {r['cost_usd']:.6f} |"
        )
    lines += [
        "",
        "## Summary",
        "",
        f"- Avg retrieval latency: **{avg_retrieval:.1f} ms** (TF-IDF over ~1,500 chunks -- not the bottleneck)",
        f"- Avg LLM call latency: **{avg_llm:.1f} ms** ({avg_llm / avg_total * 100:.0f}% of total request time)",
        f"- Avg total latency per question: **{avg_total:.1f} ms**",
        f"- Avg cost per question: **${avg_cost:.6f}**",
        f"- This run's total cost ({n} questions): **${total_cost:.6f}**",
        f"- Projected cost at {ASSUMED_QUESTIONS_PER_MONTH:,} questions/month: **${projected_monthly:.2f}/month**",
        "",
        "Retrieval is effectively free and fast; nearly all latency and 100% of "
        "marginal cost is the LLM call, which is exactly why the LLM boundary in "
        "this system is drawn where it is (see README \"Design decisions\") -- "
        "everything upstream (ingest, align, delta, retrieval) is deterministic "
        "and free to re-run. A cache on repeated/near-duplicate questions would "
        "cut the monthly figure in direct proportion to the repeat rate.",
        "",
    ]
    report = "\n".join(lines)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n(Written to {REPORT_PATH.relative_to(ROOT)}; per-question traces in traces/.)")


if __name__ == "__main__":
    main()
