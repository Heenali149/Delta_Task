"""Grounded answer assembly: retrieve -> prompt -> LLM -> cited answer.

Groundedness is enforced two ways: (1) the prompt instructs the model to
answer only from the numbered context and to say so plainly if the context
doesn't support an answer, and (2) post-hoc, every citation token in the
response is checked against the citations that were actually retrieved —
a citation to something not in context is flagged rather than trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.chat.index import RetrievalIndex
from src.chat.llm import LLMClient, LLMResponse

SYSTEM_PROMPT = """You are a grounded assistant answering questions about two engineering P&ID \
documents (PID A and PID B) and a delta report describing what changed between them.

Rules:
- Answer ONLY using the numbered context passages below. Do not use outside knowledge.
- Every factual claim you make must end with a citation in square brackets copied exactly \
from the passage's citation tag, e.g. "the duty is 776 kW [pid_a:p1@[164,551]]".
- If the context does not contain enough information to answer, say so explicitly instead of \
guessing. Never invent a citation.
- Be concise."""

CITATION_RE = re.compile(r"\[([\w:@,\.\[\]\->]+)\]")


@dataclass
class AnswerResult:
    question: str
    answer: str
    citations_claimed: list[str]
    citations_valid: list[str]
    citations_invalid: list[str]
    retrieved: list[tuple[str, float]]
    llm_response: LLMResponse


def build_prompt(question: str, retrieved: list) -> str:
    lines = []
    for i, (chunk, score) in enumerate(retrieved, start=1):
        lines.append(f"[{i}] ({chunk.citation()}) {chunk.text}")
    context = "\n".join(lines) if lines else "(no relevant context retrieved)"
    return f"Context passages:\n{context}\n\nQuestion: {question}"


def answer_question(question: str, index: RetrievalIndex, llm: LLMClient, k: int = 8) -> AnswerResult:
    retrieved = index.retrieve(question, k=k)
    valid_citations = {chunk.citation() for chunk, _ in retrieved} | {chunk.chunk_id for chunk, _ in retrieved}
    prompt = build_prompt(question, retrieved)
    resp = llm.chat(SYSTEM_PROMPT, prompt)

    claimed = CITATION_RE.findall(resp.text)
    valid = [c for c in claimed if c in valid_citations]
    invalid = [c for c in claimed if c not in valid_citations]

    return AnswerResult(
        question=question,
        answer=resp.text,
        citations_claimed=claimed,
        citations_valid=valid,
        citations_invalid=invalid,
        retrieved=[(c.citation(), s) for c, s in retrieved],
        llm_response=resp,
    )
