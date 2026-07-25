"""DWG (AutoCAD) adapter — real interface, stubbed body.

A production version would either shell out to ODA File Converter / a
licensed AutoCAD API to get DXF, then walk entities with `ezdxf`
(TEXT/MTEXT -> TextLine, INSERT/block bbox -> geometry lines), or call a
cloud conversion API. Neither is wired up in this time-boxed build — no DWG
sample was available and standing up an ODA converter is not a "few hours"
task. The seam is real (same `FormatAdapter` ABC, same `can_handle`/`load`
signature); only the body is a documented stub.
"""
from __future__ import annotations

from pathlib import Path

from src.canonical.model import CanonicalDocument
from src.ingest.base import AdapterUnavailableError, FormatAdapter


class DwgAdapter(FormatAdapter):
    format_name = "dwg"

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() == ".dwg"

    def load(self, path: Path, pid: str, revision_label: str) -> CanonicalDocument:
        raise AdapterUnavailableError(
            "dwg adapter: not implemented in this build. Would require ezdxf + an ODA/AutoCAD "
            "DWG->DXF conversion step; see src/ingest/dwg.py docstring for the intended design."
        )
