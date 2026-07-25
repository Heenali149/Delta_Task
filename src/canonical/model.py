"""Format-agnostic canonical representation.

Every ingestion adapter (native PDF, scanned PDF, DWG, ...) must normalize its
source into this model. Nothing downstream (delta engine, retrieval, chat)
ever looks at the original file format again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BBox = tuple[float, float, float, float]  # (x0, y0, x1, y1) in PDF points


@dataclass
class TextLine:
    """A single line of recovered text with its location on a page/sheet."""

    line_id: str
    text: str
    bbox: BBox
    page_index: int
    source: Literal["vector_text", "ocr"] = "vector_text"
    ocr_confidence: float | None = None  # only set when source == "ocr"


@dataclass
class Page:
    index: int
    width: float
    height: float
    lines: list[TextLine] = field(default_factory=list)


@dataclass
class CanonicalDocument:
    pid: str
    """Resolvable document identifier (here: the sample file path/name)."""
    source_format: Literal["pdf_native", "pdf_scanned", "dwg"]
    revision_label: str
    pages: list[Page] = field(default_factory=list)

    def all_lines(self) -> list[TextLine]:
        return [ln for pg in self.pages for ln in pg.lines]

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "source_format": self.source_format,
            "revision_label": self.revision_label,
            "pages": [
                {
                    "index": pg.index,
                    "width": pg.width,
                    "height": pg.height,
                    "lines": [
                        {
                            "line_id": ln.line_id,
                            "text": ln.text,
                            "bbox": list(ln.bbox),
                            "page_index": ln.page_index,
                            "source": ln.source,
                            "ocr_confidence": ln.ocr_confidence,
                        }
                        for ln in pg.lines
                    ],
                }
                for pg in self.pages
            ],
        }

    @staticmethod
    def from_dict(d: dict) -> "CanonicalDocument":
        pages = []
        for pg in d["pages"]:
            lines = [
                TextLine(
                    line_id=ln["line_id"],
                    text=ln["text"],
                    bbox=tuple(ln["bbox"]),
                    page_index=ln["page_index"],
                    source=ln.get("source", "vector_text"),
                    ocr_confidence=ln.get("ocr_confidence"),
                )
                for ln in pg["lines"]
            ]
            pages.append(Page(index=pg["index"], width=pg["width"], height=pg["height"], lines=lines))
        return CanonicalDocument(
            pid=d["pid"],
            source_format=d["source_format"],
            revision_label=d["revision_label"],
            pages=pages,
        )
