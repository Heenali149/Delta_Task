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
- Answer ONLY using the context passages below. Do not use outside knowledge.
- Every factual claim you make must end with a citation in square brackets, containing ONLY the \
value that follows "tag:" on that passage's line -- do not include the word "tag:" itself, quotes, \
or any other words inside the brackets. Never reuse a tag from a different passage, never invent \
one, and never copy an example tag from these instructions.
- Only say the context is insufficient if, after checking every passage, none of them actually \
relate to what's being asked. If a passage does relate to the question, answer directly from it -- \
do not hedge just because it doesn't spell out the answer in those exact words. Never invent a \
citation.
- Be concise."""

# Citation tags (src/chat/index.py:Chunk.citation) are deliberately free of
# brackets/parens/commas so they never nest with the "(...)" build_prompt() wraps
# them in or the "[...]" the LLM wraps its own citations in -- an earlier
# "pid_a:p1@[27,539]" format did exactly this and broke a naive non-recursive
# parser. Parsing here is deliberately lenient (match anything up to the next
# "]", then strip an optional "tag:" prefix) rather than a strict character
# class, because real models don't follow bracket-content instructions to the
# letter -- e.g. gpt-4o-mini/llama-3.3-70b will sometimes write "[tag: pid_a:...]"
# despite being told not to. All caught by testing against real LLMs, not mocks.
RAW_CITATION_RE = re.compile(r"\[([^\]]+)\]")


def _normalize_citation(raw: str) -> str:
    c = raw.strip()
    if c.lower().startswith("tag:"):
        c = c[len("tag:"):].strip()
    return c


@dataclass
class AnswerResult:
    question: str
    answer: str
    citations_claimed: list[str]
    citations_valid: list[str]
    citations_invalid: list[str]
    retrieved: list[tuple[str, float]]
    llm_response: LLMResponse
    prompt: str


def build_prompt(question: str, retrieved: list) -> str:
    # Deliberately no "[1] [2] ..." index numbering here: an earlier version
    # numbered passages with the same bracket style the model was told to use
    # for citations, and the model would sometimes cite the passage's position
    # ("[5]") instead of its actual tag. Using "tag: ... | text: ..." lines
    # with no brackets at all removes that ambiguity. Caught via real LLM testing.
    lines = [f"tag: {chunk.citation()} | text: {chunk.text}" for chunk, _score in retrieved]
    context = "\n".join(lines) if lines else "(no relevant context retrieved)"
    return f"Context passages:\n{context}\n\nQuestion: {question}"


def answer_question(question: str, index: RetrievalIndex, llm: LLMClient, k: int = 8) -> AnswerResult:
    retrieved = index.retrieve(question, k=k)
    valid_citations = {chunk.citation() for chunk, _ in retrieved} | {chunk.chunk_id for chunk, _ in retrieved}
    prompt = build_prompt(question, retrieved)
    resp = llm.chat(SYSTEM_PROMPT, prompt)

    claimed = [_normalize_citation(m) for m in RAW_CITATION_RE.findall(resp.text)]
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
        prompt=prompt,
    )
