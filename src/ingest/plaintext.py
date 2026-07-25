"""Plain-text adapter.

Added after the initial three-format build specifically to prove the
`FormatAdapter` seam scales to a 4th format without touching the delta
engine, chat, or observability layers -- see tests/test_ingest_plaintext.py,
which runs a real compute_delta() over two ingested .txt revisions with zero
changes to src/delta/*.

Each non-blank line becomes one TextLine; line order drives a synthetic
y-coordinate so the delta engine's position-similarity term still means
something ("same slot" == "same line number") even though there's no real
page geometry to recover from a text file.
"""
from __future__ import annotations

from pathlib import Path

from src.canonical.model import CanonicalDocument, Page, TextLine
from src.ingest.base import FormatAdapter

LINE_HEIGHT = 14.0


class PlainTextAdapter(FormatAdapter):
    format_name = "text"

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in (".txt", ".text")

    def load(self, path: Path, pid: str, revision_label: str) -> CanonicalDocument:
        lines: list[TextLine] = []
        line_no = 0
        for row in path.read_text(encoding="utf-8").splitlines():
            text = row.strip()
            if not text:
                continue
            y = line_no * LINE_HEIGHT
            lines.append(
                TextLine(
                    line_id=f"{pid}:p0:l{line_no}",
                    text=text,
                    bbox=(0.0, y, float(len(text) * 6), y + LINE_HEIGHT),
                    page_index=0,
                    source="vector_text",
                )
            )
            line_no += 1
        page = Page(index=0, width=800.0, height=max(line_no * LINE_HEIGHT, LINE_HEIGHT), lines=lines)
        return CanonicalDocument(pid=pid, source_format="text", revision_label=revision_label, pages=[page])
