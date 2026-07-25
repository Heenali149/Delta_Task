"""Provider-agnostic LLM client. Swap providers via env var, never code.

`LLM_PROVIDER` = openai | mock (default: openai, auto-falls-back to mock if
no OPENAI_API_KEY is set so the rest of the system stays runnable without a
key — the fallback is logged, never silent).

This is the only place in the system where model non-determinism lives: the
delta engine (src/delta/engine.py) and retrieval (src/chat/index.py) are
both deterministic. Chat answers are not reproducible byte-for-byte across
runs with a real provider; that's expected and documented.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    fallback_used: bool = False


class LLMClient(ABC):
    model: str

    @abstractmethod
    def chat(self, system: str, user: str) -> LLMResponse: ...


class OpenAIClient(LLMClient):
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("LLM_MODEL", "gpt-4o-mini")
        api_key = os.environ["OPENAI_API_KEY"]  # raises if unset; caller decides fallback
        from openai import OpenAI  # lazy import: don't require the package unless used

        self._client = OpenAI(api_key=api_key)

    def chat(self, system: str, user: str) -> LLMResponse:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
        )
        choice = resp.choices[0].message.content or ""
        usage = resp.usage
        return LLMResponse(
            text=choice,
            model=self.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


class MockClient(LLMClient):
    """Deterministic, extractive fallback used when no provider/key is
    configured. Not a "fake LLM pretending to be smart" — it explicitly
    labels itself so eval output and traces are honest about degraded mode.
    """

    model = "mock"

    def chat(self, system: str, user: str) -> LLMResponse:
        # `user` is the rendered prompt built by src/chat/answer.py, which
        # embeds numbered context chunks as "[n] (citation) text". Extract the
        # single highest-numbered... actually just the first (highest-scored)
        # chunk and answer from it, quoting its citation verbatim.
        import re

        chunk_pattern = re.compile(r"^\[(\d+)\]\s*\(([^)]+)\)\s*(.+)$", re.M)
        matches = chunk_pattern.findall(user)
        question_match = re.search(r"Question:\s*(.+)", user)
        question = question_match.group(1).strip() if question_match else ""

        if not matches:
            text = "I don't have enough retrieved context to answer that from the provided documents."
        else:
            top = matches[:6]
            bullet_lines = [f"- {text.strip()} [{citation}]" for _, citation, text in top]
            text = (
                f"[mock-llm fallback - no LLM API key configured]\n"
                f"Based on the most relevant retrieved passages for \"{question}\":\n"
                + "\n".join(bullet_lines)
            )
        return LLMResponse(
            text=text, model=self.model, input_tokens=0, output_tokens=0, fallback_used=True
        )


def get_llm_client(logger=None) -> LLMClient:
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    if provider == "mock":
        return MockClient()
    if provider == "openai":
        if os.environ.get("OPENAI_API_KEY"):
            try:
                return OpenAIClient()
            except Exception as e:  # ImportError (no `openai` pkg) or API init failure
                if logger:
                    logger.warning(f"OpenAI client unavailable ({e}); falling back to mock LLM.")
                return MockClient()
        if logger:
            logger.warning("OPENAI_API_KEY not set; falling back to mock LLM.")
        return MockClient()
    raise ValueError(f"Unknown LLM_PROVIDER={provider!r}")
