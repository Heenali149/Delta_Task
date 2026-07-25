"""Retrieval index over PID A, PID B, and the delta report.

Chunking strategy: P&ID text extracts as many short, spatially-scattered
fragments (a tag label, a unit, a setpoint, each its own "line"). A single
fragment is rarely enough context for retrieval ("776" alone doesn't look
like a "compressor duty"), so lines on the same page within a small
vertical band are grouped into row chunks (reconstructs table rows like
"DUTY kW 776") before indexing. Delta items are indexed individually, one
chunk per change, since each is already a self-contained claim.

Retrieval itself is TF-IDF + cosine similarity (scikit-learn) — no LLM
involved, deterministic, no API key required. This is a deliberate
simplicity choice given the time box; an embeddings-based retriever is the
natural upgrade (see README "what we'd do next").
"""
from __future__ import annotations

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.canonical.model import CanonicalDocument
from src.delta.engine import DeltaResult

ROW_TOLERANCE = 4.0  # points; lines within this y-distance are one row chunk


@dataclass
class Chunk:
    chunk_id: str
    source: str  # pid_a | pid_b | delta_report
    pid: str
    page_index: int
    bbox: tuple | None
    text: str

    def citation(self) -> str:
        if self.source == "delta_report":
            return self.chunk_id
        loc = f"p{self.page_index + 1}" if self.bbox is None else f"p{self.page_index + 1}@[{self.bbox[0]:.0f},{self.bbox[1]:.0f}]"
        return f"{self.source}:{loc}"


def _row_chunks(doc: CanonicalDocument, source: str) -> list[Chunk]:
    chunks = []
    for page in doc.pages:
        lines = sorted(page.lines, key=lambda ln: (round(ln.bbox[1] / ROW_TOLERANCE), ln.bbox[0]))
        current_y = None
        buf = []
        buf_bbox = None

        def flush():
            if not buf:
                return
            text = " ".join(t for t in buf if t.strip())
            if text.strip():
                chunks.append(
                    Chunk(
                        chunk_id=f"{source}:p{page.index}:row{len(chunks)}",
                        source=source,
                        pid=doc.pid,
                        page_index=page.index,
                        bbox=buf_bbox,
                        text=text,
                    )
                )

        for ln in lines:
            y_bucket = round(ln.bbox[1] / ROW_TOLERANCE)
            if current_y is None or y_bucket != current_y:
                flush()
                buf, buf_bbox, current_y = [], list(ln.bbox), y_bucket
            buf.append(ln.text)
            buf_bbox[0] = min(buf_bbox[0], ln.bbox[0])
            buf_bbox[1] = min(buf_bbox[1], ln.bbox[1])
            buf_bbox[2] = max(buf_bbox[2], ln.bbox[2])
            buf_bbox[3] = max(buf_bbox[3], ln.bbox[3])
        flush()
    return chunks


def _delta_chunks(delta: DeltaResult) -> list[Chunk]:
    chunks = []
    for item in delta.items:
        chunks.append(
            Chunk(
                chunk_id=item.id,
                source="delta_report",
                pid=f"{delta.pid_a}->{delta.pid_b}",
                page_index=item.page_index,
                bbox=item.location,
                text=f"{item.description} (change_type={item.change_type}, item_type={item.item_type})",
            )
        )
    return chunks


class RetrievalIndex:
    def __init__(self, doc_a: CanonicalDocument, doc_b: CanonicalDocument, delta: DeltaResult):
        self.chunks: list[Chunk] = (
            _row_chunks(doc_a, "pid_a") + _row_chunks(doc_b, "pid_b") + _delta_chunks(delta)
        )
        texts = [c.text for c in self.chunks] or [""]
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.matrix = self.vectorizer.fit_transform(texts)

    def retrieve(self, query: str, k: int = 8) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        q_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(q_vec, self.matrix)[0]
        ranked = sorted(zip(self.chunks, scores), key=lambda cs: cs[1], reverse=True)
        return [(c, float(s)) for c, s in ranked[:k] if s > 0]
