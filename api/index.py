"""Vercel entrypoint: a thin Flask UI over the existing delta-chat pipeline.

Reuses `src/` untouched. No PDF ingestion happens here -- it serves the
precomputed `pair_001` session (canonical docs + delta.json, checked into
`api/data/pair_001/`) so the deployed function never needs PyMuPDF, only the
downstream deterministic delta model + TF-IDF retrieval + LLM client.
Regenerate that session locally with `make run` if the sample pair changes.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

from flask import Flask, jsonify, render_template, request

from src.canonical.model import CanonicalDocument
from src.chat.answer import answer_question
from src.chat.index import RetrievalIndex
from src.chat.llm import get_llm_client
from src.delta.engine import DeltaItem, DeltaResult

DATA_DIR = Path(__file__).resolve().parent / "data" / "pair_001"

app = Flask(__name__)

_cache: dict = {}


def _load_session():
    if "index" not in _cache:
        doc_a = CanonicalDocument.from_dict(json.loads((DATA_DIR / "canonical_a.json").read_text(encoding="utf-8")))
        doc_b = CanonicalDocument.from_dict(json.loads((DATA_DIR / "canonical_b.json").read_text(encoding="utf-8")))
        delta_dict = json.loads((DATA_DIR / "delta.json").read_text(encoding="utf-8"))
        items = [DeltaItem(**{**it, "location": tuple(it["location"])}) for it in delta_dict["items"]]
        delta = DeltaResult(pid_a=delta_dict["pid_a"], pid_b=delta_dict["pid_b"], items=items)
        _cache["doc_a"], _cache["doc_b"], _cache["delta"] = doc_a, doc_b, delta
        _cache["index"] = RetrievalIndex(doc_a, doc_b, delta)
    return _cache["index"], _cache["delta"], _cache["doc_a"], _cache["doc_b"]


@app.route("/")
def home():
    index, delta, doc_a, doc_b = _load_session()
    report_md = (DATA_DIR / "delta_report.md").read_text(encoding="utf-8")
    llm = get_llm_client()
    return render_template(
        "index.html",
        pid_a=delta.pid_a,
        pid_b=delta.pid_b,
        summary=delta.summary(),
        report_md=report_md,
        llm_model=llm.model,
        llm_is_mock=llm.model == "mock",
    )


@app.route("/api/summary")
def api_summary():
    index, delta, doc_a, doc_b = _load_session()
    llm = get_llm_client()
    return jsonify(
        pid_a=delta.pid_a, pid_b=delta.pid_b, summary=delta.summary(),
        llm_model=llm.model, llm_is_mock=llm.model == "mock",
    )


@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json(force=True, silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify(error="question is required"), 400

    index, delta, doc_a, doc_b = _load_session()
    llm = get_llm_client()
    try:
        result = answer_question(question, index, llm, k=12)
    except Exception as e:  # a live LLM call can fail (rate limit, bad key, timeout, ...)
        return jsonify(error=f"{type(e).__name__}: {e}"), 502

    return jsonify(
        question=question,
        answer=result.answer,
        citations_valid=result.citations_valid,
        citations_invalid=result.citations_invalid,
        retrieved=[{"citation": c, "score": round(s, 4)} for c, s in result.retrieved],
        model=result.llm_response.model,
        fallback_used=result.llm_response.fallback_used,
    )


# Local dev: `python api/index.py` (Vercel imports `app` directly, doesn't run this).
if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
