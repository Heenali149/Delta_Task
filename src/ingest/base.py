"""The one interface every format adapter implements.

Design intent: the delta engine, chat/retrieval, and observability layers
only ever depend on `CanonicalDocument`. Adding a 4th format (e.g. IFC, DXF,
a different CAD export) means writing one new adapter class here and
registering it in `detect_and_load` — nothing else in the system changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.canonical.model import CanonicalDocument


class AdapterUnavailableError(RuntimeError):
    """Raised when an adapter's format is recognized but its runtime
    dependency (an OCR binary, a DWG converter, ...) isn't available in the
    current environment. This is a *real, logged* failure mode — not a
    silent stub — so observability can surface it instead of swallowing it.
    """


class FormatAdapter(ABC):
    format_name: str

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Cheap format sniff (extension + light header check)."""

    @abstractmethod
    def load(self, path: Path, pid: str, revision_label: str) -> CanonicalDocument:
        """Parse `path` into the canonical representation."""


def detect_and_load(path: str | Path, pid: str, revision_label: str) -> CanonicalDocument:
    from src.ingest.pdf_native import PdfNativeAdapter
    from src.ingest.pdf_scanned import PdfScannedAdapter
    from src.ingest.dwg import DwgAdapter

    path = Path(path)
    adapters: list[FormatAdapter] = [PdfNativeAdapter(), PdfScannedAdapter(), DwgAdapter()]

    candidates = [a for a in adapters if a.can_handle(path)]
    if not candidates:
        raise ValueError(f"No adapter recognizes format of {path}")

    # Native-PDF wins over scanned-PDF when both claim a .pdf (native check is
    # a real "does it have a text layer" probe, scanned is the raster fallback).
    candidates.sort(key=lambda a: 0 if a.format_name == "pdf_native" else 1)
    last_err: Exception | None = None
    for adapter in candidates:
        try:
            return adapter.load(path, pid, revision_label)
        except AdapterUnavailableError as e:
            last_err = e
            continue
    raise last_err or RuntimeError(f"All adapters failed for {path}")
