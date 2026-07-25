"""Native (born-digital) PDF adapter.

Uses PyMuPDF's structured text extraction, which already spatially groups
glyphs into spans -> lines -> blocks, so we get real bounding boxes for free
instead of re-deriving layout from a flat text dump.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from src.canonical.model import CanonicalDocument, Page, TextLine
from src.ingest.base import FormatAdapter

MIN_TEXT_LAYER_CHARS = 20  # below this, treat the PDF as scanned/raster


class PdfNativeAdapter(FormatAdapter):
    format_name = "pdf_native"

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        try:
            doc = fitz.open(path)
        except Exception:
            return False
        total_chars = sum(len(p.get_text("text")) for p in doc)
        doc.close()
        return total_chars >= MIN_TEXT_LAYER_CHARS

    def load(self, path: Path, pid: str, revision_label: str) -> CanonicalDocument:
        doc = fitz.open(path)
        pages: list[Page] = []
        for page_index, pmupage in enumerate(doc):
            rect = pmupage.rect
            page = Page(index=page_index, width=rect.width, height=rect.height)
            raw = pmupage.get_text("dict")
            line_no = 0
            for block in raw.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = "".join(s.get("text", "") for s in spans).strip()
                    if not text:
                        continue
                    xs0 = min(s["bbox"][0] for s in spans)
                    ys0 = min(s["bbox"][1] for s in spans)
                    xs1 = max(s["bbox"][2] for s in spans)
                    ys1 = max(s["bbox"][3] for s in spans)
                    line_no += 1
                    page.lines.append(
                        TextLine(
                            line_id=f"{pid}:p{page_index}:l{line_no}",
                            text=text,
                            bbox=(round(xs0, 1), round(ys0, 1), round(xs1, 1), round(ys1, 1)),
                            page_index=page_index,
                            source="vector_text",
                        )
                    )
            pages.append(page)
        doc.close()
        return CanonicalDocument(
            pid=pid, source_format="pdf_native", revision_label=revision_label, pages=pages
        )
