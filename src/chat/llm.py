"""Provider-agnostic LLM client. Swap providers via env var, never code.

`LLM_PROVIDER` = openai | groq | mock (default: openai, auto-falls-back to
mock if the selected provider's API key isn't set so the rest of the system
stays runnable without a key — the fallback is logged, never silent).

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


class _OpenAICompatibleClient(LLMClient):
    """Base for any provider that speaks the OpenAI chat-completions wire
    format (OpenAI itself, Groq, and most other inference hosts). Only the
    API key env var, default model, and base_url differ.
    """

    def __init__(self, api_key_env: str, default_model: str, base_url: str | None = None):
        self.model = os.environ.get("LLM_MODEL") or default_model
        api_key = os.environ[api_key_env]  # raises if unset; caller decides fallback
        from openai import OpenAI  # lazy import: don't require the package unless used

        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

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


class OpenAIClient(_OpenAICompatibleClient):
    def __init__(self, model: str | None = None):
        super().__init__("OPENAI_API_KEY", model or "gpt-4o-mini")


class GroqClient(_OpenAICompatibleClient):
    """Groq's API is OpenAI-wire-compatible, so this reuses the `openai`
    SDK pointed at Groq's base_url instead of a separate client library.
    """

    def __init__(self, model: str | None = None):
        super().__init__("GROQ_API_KEY", model or "llama-3.3-70b-versatile", base_url="https://api.groq.com/openai/v1")


class MockClient(LLMClient):
    """Deterministic, extractive fallback used when no provider/key is
    configured. Not a "fake LLM pretending to be smart" — it explicitly
    labels itself so eval output and traces are honest about degraded mode.
    """

    model = "mock"

    def chat(self, system: str, user: str) -> LLMResponse:
        # `user` is the rendered prompt built by src/chat/answer.py, which embeds
        # context chunks as "tag: <citation> | text: <text>" lines (in retrieval-rank
        # order). Quote the top few verbatim with their citation tags.
        import re

        chunk_pattern = re.compile(r"^tag:\s*(\S+)\s*\|\s*text:\s*(.+)$", re.M)
        matches = chunk_pattern.findall(user)
        question_match = re.search(r"Question:\s*(.+)", user)
        question = question_match.group(1).strip() if question_match else ""

        if not matches:
            text = "I don't have enough retrieved context to answer that from the provided documents."
        else:
            top = matches[:6]
            bullet_lines = [f"- {text.strip()} [{citation}]" for citation, text in top]
            text = (
                f"(mock-llm fallback - no LLM API key configured)\n"
                f"Based on the most relevant retrieved passages for \"{question}\":\n"
                + "\n".join(bullet_lines)
            )
        return LLMResponse(
            text=text, model=self.model, input_tokens=0, output_tokens=0, fallback_used=True
        )


_PROVIDERS = {
    "openai": ("OPENAI_API_KEY", OpenAIClient),
    "groq": ("GROQ_API_KEY", GroqClient),
}


def get_llm_client(logger=None) -> LLMClient:
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    if provider == "mock":
        return MockClient()
    if provider in _PROVIDERS:
        key_env, client_cls = _PROVIDERS[provider]
        if os.environ.get(key_env):
            try:
                return client_cls()
            except Exception as e:  # ImportError (no `openai` pkg) or API init failure
                if logger:
                    logger.warning(f"{provider} client unavailable ({e}); falling back to mock LLM.")
                return MockClient()
        if logger:
            logger.warning(f"{key_env} not set; falling back to mock LLM.")
        return MockClient()
    raise ValueError(f"Unknown LLM_PROVIDER={provider!r}")
