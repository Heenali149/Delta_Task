"""Runnable eval harness: `python -m eval.run_eval` (or `make eval`).

Self-contained: ingests the sample pair fresh, computes delta, builds the
retrieval index, runs the chat QA set, and prints a scorecard. Every run
also writes a full trace (src/observability/tracing.py), so a regression can
be pinpointed to a specific stage.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from eval.metrics import evaluate_chat, evaluate_delta
from src.chat.answer import answer_question
from src.chat.index import RetrievalIndex
from src.chat.llm import get_llm_client
from src.delta.engine import compute_delta
from src.ingest.base import detect_and_load
from src.observability.logging import get_logger
from src.observability.tracing import Trace

logger = get_logger("eval")

PAIR_DIR = ROOT / "eval" / "datasets" / "pair_001"
PID_A_PATH = ROOT / "data" / "samples" / "pair_001_lift_gas_KA901_A.pdf"
PID_B_PATH = ROOT / "data" / "samples" / "pair_001_export_gas_KA902_B.pdf"


def main():
    trace = Trace(request_type="eval")

    with trace.span("ingest"):
        doc_a = detect_and_load(PID_A_PATH, "pair_001:lift_gas:A", "Lift Gas KA-901")
        doc_b = detect_and_load(PID_B_PATH, "pair_001:export_gas:B", "Export Gas KA-902")

    with trace.span("delta"):
        delta = compute_delta(doc_a, doc_b)

    ground_truth = json.loads((PAIR_DIR / "ground_truth_deltas.json").read_text(encoding="utf-8"))
    sample_review = json.loads((PAIR_DIR / "predicted_sample_review.json").read_text(encoding="utf-8"))
    predicted_items = [it.to_dict() for it in delta.items]

    with trace.span("delta_eval"):
        delta_eval = evaluate_delta(predicted_items, ground_truth, sample_review)

    index = RetrievalIndex(doc_a, doc_b, delta)
    llm = get_llm_client(logger=logger)
    qa_items = json.loads((PAIR_DIR / "qa_ground_truth.json").read_text(encoding="utf-8"))["items"]

    def run_fn(question: str):
        return answer_question(question, index, llm, k=12)

    with trace.span("chat_eval", model=llm.model):
        chat_eval = evaluate_chat(qa_items, run_fn)

    trace.finish(
        delta_recall=delta_eval.recall, delta_precision=delta_eval.precision,
        chat_correctness=chat_eval.answer_correctness, chat_groundedness=chat_eval.groundedness,
    )

    print_scorecard(delta, delta_eval, chat_eval, llm.model)


def print_scorecard(delta, delta_eval, chat_eval, model_name):
    print("=" * 72)
    print("DELTA-CHAT EVAL SCORECARD - pair_001 (Lift Gas 26-KA-901 vs Export Gas 26-KA-902)")
    print("=" * 72)

    print(f"\n[Delta engine]  total predicted changes: {len(delta.items)}  {delta.summary()['by_change_type']}")
    print(f"  Recall    (hand-labeled ground truth, n={15}):  {delta_eval.recall:.3f}  "
          f"({len(delta_eval.matched)}/{len(delta_eval.matched) + len(delta_eval.missed)} found)")
    if delta_eval.missed:
        print(f"    MISSED: {delta_eval.missed}  <- see README known limitations")
    print(f"  Precision (stratified random sample, n={delta_eval.precision_sample_size}): "
          f"{delta_eval.precision:.3f}  ({delta_eval.precision_correct}/{delta_eval.precision_sample_size} correct)")
    print(f"  F1 (recall x sample-precision): {delta_eval.f1:.3f}")

    print(f"\n[Grounded chat]  LLM: {model_name}{' (fallback -- no API key set)' if model_name == 'mock' else ''}")
    print(f"  Answer correctness: {chat_eval.answer_correctness:.3f}")
    print(f"  Groundedness (valid citations / claimed citations): {chat_eval.groundedness:.3f}")
    for q in chat_eval.per_question:
        if q.get("error"):
            print(f"    [ERROR] {q['id']}: {q['question']}\n         {q['error']}")
            continue
        mark = "OK" if q["correct"] else "MISS"
        print(f"    [{mark}] {q['id']}: {q['question']}")
        if q["citations_invalid"]:
            print(f"         unverifiable citations: {q['citations_invalid']}")

    print("\n(Full trace written to traces/. See README for methodology and known limitations.)")


if __name__ == "__main__":
    main()
