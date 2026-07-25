"""Single CLI entrypoint: `run` (ingest -> delta -> report) and `chat`
(retrieval -> LLM -> grounded answer), each producing a full trace.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.canonical.model import CanonicalDocument
from src.chat.answer import answer_question
from src.chat.index import RetrievalIndex
from src.chat.llm import get_llm_client
from src.delta.engine import compute_delta
from src.delta.report import write_report
from src.ingest.base import detect_and_load
from src.observability.logging import get_logger, log
from src.observability.tracing import Trace

logger = get_logger("delta_chat")


def cmd_run(args):
    trace = Trace(request_type="run")
    log(logger, "info", "run started", request_id=trace.request_id, pid_a=args.pid_a, pid_b=args.pid_b)

    with trace.span("ingest_a", path=args.a) as s:
        doc_a = detect_and_load(args.a, args.pid_a, args.rev_a)
        s.attributes["lines"] = len(doc_a.all_lines())

    with trace.span("ingest_b", path=args.b) as s:
        doc_b = detect_and_load(args.b, args.pid_b, args.rev_b)
        s.attributes["lines"] = len(doc_b.all_lines())

    with trace.span("delta") as s:
        result = compute_delta(doc_a, doc_b)
        s.attributes["summary"] = result.summary()

    out_dir = Path(args.out)
    with trace.span("report", out_dir=str(out_dir)):
        write_report(result, out_dir)
        out_dir.joinpath("canonical_a.json").write_text(json.dumps(doc_a.to_dict()), encoding="utf-8")
        out_dir.joinpath("canonical_b.json").write_text(json.dumps(doc_b.to_dict()), encoding="utf-8")

    record = trace.finish(delta_summary=result.summary(), out_dir=str(out_dir))
    log(logger, "info", "run finished", request_id=trace.request_id, **result.summary())
    print(json.dumps(result.summary(), indent=2))
    print(f"\nWrote: {out_dir}/delta.json, {out_dir}/delta_report.md")
    print(f"Trace: traces/{trace.request_id}.json")
    return record


def _load_session(session_dir: Path):
    doc_a = CanonicalDocument.from_dict(json.loads((session_dir / "canonical_a.json").read_text(encoding="utf-8")))
    doc_b = CanonicalDocument.from_dict(json.loads((session_dir / "canonical_b.json").read_text(encoding="utf-8")))
    delta_dict = json.loads((session_dir / "delta.json").read_text(encoding="utf-8"))
    from src.delta.engine import DeltaItem, DeltaResult

    items = [DeltaItem(**{**it, "location": tuple(it["location"])}) for it in delta_dict["items"]]
    delta = DeltaResult(pid_a=delta_dict["pid_a"], pid_b=delta_dict["pid_b"], items=items)
    return doc_a, doc_b, delta


def _ask_one(question: str, index: RetrievalIndex, trace: Trace):
    with trace.span("retrieval", question=question) as s:
        retrieved = index.retrieve(question, k=12)
        s.attributes["retrieved_count"] = len(retrieved)
        s.attributes["top_citations"] = [c.citation() for c, _ in retrieved]

    llm = get_llm_client(logger=logger)
    with trace.span("llm_call", model=llm.model) as s:
        result = answer_question(question, index, llm, k=12)
        trace.record_llm_call(
            s, model=result.llm_response.model, prompt=result.prompt,
            response=result.answer, input_tokens=result.llm_response.input_tokens,
            output_tokens=result.llm_response.output_tokens, fallback_used=result.llm_response.fallback_used,
        )
        s.attributes["citations_valid"] = result.citations_valid
        s.attributes["citations_invalid"] = result.citations_invalid
    return result


def cmd_chat(args):
    session_dir = Path(args.session)
    doc_a, doc_b, delta = _load_session(session_dir)
    index = RetrievalIndex(doc_a, doc_b, delta)

    def ask(question: str):
        trace = Trace(request_type="chat")
        log(logger, "info", "chat question received", request_id=trace.request_id, question=question)
        try:
            result = _ask_one(question, index, trace)
        except Exception as e:
            # A failed LLM call (rate limit, timeout, bad key, ...) must not crash the
            # session or vanish silently -- it gets its own finished trace with the
            # error attached, and a clear message instead of a raw traceback.
            trace.finish(question=question, error=f"{type(e).__name__}: {e}")
            log(logger, "error", "chat request failed", request_id=trace.request_id, error=str(e))
            print(f"\n> {question}\n")
            print(f"[request failed: {type(e).__name__}: {e}]")
            print(f"(trace: traces/{trace.request_id}.json -- see 'had_error' / span 'error' fields)")
            return None

        trace.finish(
            question=question, answer_preview=result.answer[:300],
            citations_valid=result.citations_valid, citations_invalid=result.citations_invalid,
        )
        log(
            logger, "info", "chat answered", request_id=trace.request_id,
            citations_valid=len(result.citations_valid), citations_invalid=len(result.citations_invalid),
            fallback_used=result.llm_response.fallback_used,
        )
        print(f"\n> {question}\n")
        print(result.answer)
        if result.citations_invalid:
            print(f"\n[warning: unverifiable citations: {result.citations_invalid}]")
        print(f"\n(trace: traces/{trace.request_id}.json)")
        return result

    if args.ask:
        ask(args.ask)
        return

    print(f"Grounded chat over {doc_a.pid} + {doc_b.pid} + delta report. Ctrl+C to exit.")
    while True:
        try:
            q = input("\nask> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        ask(q)


def main():
    parser = argparse.ArgumentParser(prog="delta-chat")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="ingest two PIDs, compute delta, write report")
    p_run.add_argument("--a", required=True, help="path to PID A")
    p_run.add_argument("--b", required=True, help="path to PID B")
    p_run.add_argument("--pid-a", required=True)
    p_run.add_argument("--pid-b", required=True)
    p_run.add_argument("--rev-a", default="A")
    p_run.add_argument("--rev-b", default="B")
    p_run.add_argument("--out", required=True)
    p_run.set_defaults(func=cmd_run)

    p_chat = sub.add_parser("chat", help="grounded chat over a run's session directory")
    p_chat.add_argument("--session", required=True)
    p_chat.add_argument("--ask", help="one-shot question (non-interactive)")
    p_chat.set_defaults(func=cmd_chat)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
