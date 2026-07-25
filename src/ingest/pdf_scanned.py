"""Scanned/raster PDF adapter.

Real seam, degraded gracefully: it rasterizes each page with PyMuPDF (no
extra dependency needed for that part) and then requires `pytesseract` +
a working Tesseract binary on PATH to recover text + bounding boxes. Neither
is available in this build environment (no system package install in the
time window), so `load()` raises `AdapterUnavailableError` with a clear
message instead of pretending to produce output.

To make this real end-to-end elsewhere: `pip install pytesseract`, install
the Tesseract binary, and this adapter runs unchanged. Nothing about the
canonical model or anything downstream needs to change.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from src.canonical.model import CanonicalDocument, Page, TextLine
from src.ingest.base import AdapterUnavailableError, FormatAdapter
from src.ingest.pdf_native import MIN_TEXT_LAYER_CHARS

RASTER_DPI = 300


class PdfScannedAdapter(FormatAdapter):
    format_name = "pdf_scanned"

    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        try:
            doc = fitz.open(path)
        except Exception:
            return False
        total_chars = sum(len(p.get_text("text")) for p in doc)
        doc.close()
        # Only claims PDFs that the native adapter would refuse (no/weak text layer).
        return total_chars < MIN_TEXT_LAYER_CHARS

    def load(self, path: Path, pid: str, revision_label: str) -> CanonicalDocument:
        try:
            import pytesseract  # noqa: F401
        except ImportError as e:
            raise AdapterUnavailableError(
                "pdf_scanned adapter: 'pytesseract' is not installed in this environment. "
                "Install it (and a Tesseract binary) to enable OCR ingestion."
            ) from e

        doc = fitz.open(path)
        pages: list[Page] = []
        for page_index, pmupage in enumerate(doc):
            pix = pmupage.get_pixmap(dpi=RASTER_DPI)
            img_bytes = pix.tobytes("png")
            page = Page(index=page_index, width=pmupage.rect.width, height=pmupage.rect.height)
            try:
                from PIL import Image
                import io

                image = Image.open(io.BytesIO(img_bytes))
                ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            except Exception as e:
                doc.close()
                raise AdapterUnavailableError(
                    f"pdf_scanned adapter: OCR run failed ({e}). Likely missing Tesseract binary on PATH."
                ) from e

            scale = RASTER_DPI / 72.0
            line_no = 0
            for i, text in enumerate(ocr_data["text"]):
                text = text.strip()
                if not text:
                    continue
                x, y, w, h = (
                    ocr_data["left"][i],
                    ocr_data["top"][i],
                    ocr_data["width"][i],
                    ocr_data["height"][i],
                )
                conf = float(ocr_data.get("conf", [-1])[i])
                line_no += 1
                page.lines.append(
                    TextLine(
                        line_id=f"{pid}:p{page_index}:ocr{line_no}",
                        text=text,
                        bbox=(x / scale, y / scale, (x + w) / scale, (y + h) / scale),
                        page_index=page_index,
                        source="ocr",
                        ocr_confidence=conf / 100.0 if conf >= 0 else None,
                    )
                )
            pages.append(page)
        doc.close()
        return CanonicalDocument(
            pid=pid, source_format="pdf_scanned", revision_label=revision_label, pages=pages
        )
