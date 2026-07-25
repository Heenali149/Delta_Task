"""Homegrown tracer: one JSON trace per request, spanning
ingest -> delta -> retrieval -> LLM call -> answer, with per-stage timing,
LLM token/cost telemetry, and error capture.

Chosen over a hosted tool (Langfuse/Phoenix/otel-collector) deliberately:
this is a single-process, offline-runnable take-home, and a dependency-free
JSON tracer is something a reviewer can open in a text editor with zero
setup. The `Trace`/`span` shape below maps directly onto OpenTelemetry spans
(name, start, end, attributes) if this were promoted to a real service —
swapping the sink for an OTLP exporter would not require touching call sites.
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

TRACE_DIR = Path(__file__).resolve().parents[2] / "traces"
TRACE_DIR.mkdir(exist_ok=True)

# Rough public per-1K-token list prices, USD, for cost estimation only.
# Configurable / overridable — not meant to be billing-accurate.
MODEL_PRICING_PER_1K = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "mock": {"input": 0.0, "output": 0.0},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = MODEL_PRICING_PER_1K.get(model, MODEL_PRICING_PER_1K["mock"])
    return round(input_tokens / 1000 * rates["input"] + output_tokens / 1000 * rates["output"], 6)


@dataclass
class Span:
    name: str
    start: float
    end: float | None = None
    attributes: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.end is None:
            return None
        return round((self.end - self.start) * 1000, 2)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "error": self.error,
        }


class Trace:
    def __init__(self, request_type: str, request_id: str | None = None):
        self.request_id = request_id or str(uuid.uuid4())
        self.request_type = request_type
        self.started_at = time.time()
        self.spans: list[Span] = []

    @contextmanager
    def span(self, name: str, **attributes):
        s = Span(name=name, start=time.time(), attributes=attributes)
        try:
            yield s
        except Exception as e:
            s.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            s.end = time.time()
            self.spans.append(s)

    def record_llm_call(self, span: Span, model: str, prompt: str, response: str,
                         input_tokens: int, output_tokens: int, fallback_used: bool = False):
        span.attributes.update(
            {
                "llm_model": model,
                "llm_prompt_preview": prompt[:2000],
                "llm_response_preview": response[:2000],
                "llm_input_tokens": input_tokens,
                "llm_output_tokens": output_tokens,
                "llm_cost_usd": estimate_cost(model, input_tokens, output_tokens),
                "llm_fallback_used": fallback_used,
            }
        )

    def finish(self, **result_attributes) -> dict:
        record = {
            "request_id": self.request_id,
            "request_type": self.request_type,
            "started_at": self.started_at,
            "total_duration_ms": round((time.time() - self.started_at) * 1000, 2),
            "spans": [s.to_dict() for s in self.spans],
            "result": result_attributes,
            "had_error": any(s.error for s in self.spans),
        }
        out_path = TRACE_DIR / f"{self.request_id}.json"
        out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        with open(TRACE_DIR / "traces.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        return record
