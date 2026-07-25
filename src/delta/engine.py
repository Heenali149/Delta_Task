"""Delta engine: turns an alignment result into a typed, located, confident
list of added/removed/modified items.

LLM boundary: none. This module is 100% deterministic — same two canonical
documents always produce the same delta.json byte-for-byte (module the
run's ISO timestamp). Where an LLM *is* used in this system is downstream,
in chat answer generation (src/chat/answer.py) and optionally to rewrite a
delta item's `description` into friendlier prose (off by default — see
`enrich.py`... not built in this cut, template descriptions are used
instead, which keeps the report reproducible without an API key).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.canonical.model import CanonicalDocument, TextLine
from src.delta.align import align_pages, normalize

PUNCT_WS_RE = re.compile(r"[\s.,;:]+")


def _strict_normalize(text: str) -> str:
    """Collapses whitespace/punctuation-only formatting differences (e.g. a
    trailing space before a period, or "NOTE 3, 8,14" vs "NOTE 3,8,14") so
    they register as unchanged. These are PDF-export/kerning artifacts, not
    meaningful engineering changes, and reporting them as deltas is exactly
    the "thin wrapper over a raw text diff" failure mode this assignment
    warns against.
    """
    return PUNCT_WS_RE.sub("", text).upper()


TAG_RE = re.compile(r"^\d{1,3}[\s\-]?[A-Z]{1,5}[\s\-]?\d{3,6}[A-Z]?$")
SETPOINT_RE = re.compile(r"^(HH|LL|H|L|SD|SP)\s*[:=]?\s*-?\d")
UNIT_RE = re.compile(r"\d+(\.\d+)?\s*(KW|BARG|BAR|°C|KG/H|MM|MMSCFD|MSM3/D|%)\b", re.I)
NOTE_NUM_RE = re.compile(r"^\d{1,2}\.\s")


def classify_type(text: str) -> str:
    t = normalize(text)
    if SETPOINT_RE.match(t):
        return "setpoint"
    if UNIT_RE.search(t):
        return "spec_value"
    if NOTE_NUM_RE.match(t):
        return "note"
    if TAG_RE.match(t):
        return "tag"
    return "text"


@dataclass
class DeltaItem:
    id: str
    change_type: str  # added | removed | modified
    item_type: str  # tag | spec_value | setpoint | note | text
    page_index: int
    location: tuple
    before_text: str | None
    after_text: str | None
    description: str
    confidence: float

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["location"] = list(self.location)
        return d


@dataclass
class DeltaResult:
    pid_a: str
    pid_b: str
    items: list[DeltaItem] = field(default_factory=list)

    def summary(self) -> dict:
        by_change = {}
        by_type = {}
        for it in self.items:
            by_change[it.change_type] = by_change.get(it.change_type, 0) + 1
            by_type[it.item_type] = by_type.get(it.item_type, 0) + 1
        return {"total": len(self.items), "by_change_type": by_change, "by_item_type": by_type}

    def to_dict(self) -> dict:
        return {
            "pid_a": self.pid_a,
            "pid_b": self.pid_b,
            "summary": self.summary(),
            "items": [it.to_dict() for it in self.items],
        }


def _describe(change_type: str, item_type: str, before: str | None, after: str | None) -> str:
    if change_type == "added":
        return f"New {item_type} appeared: \"{after}\"."
    if change_type == "removed":
        return f"{item_type.capitalize()} \"{before}\" was removed."
    return f"{item_type.capitalize()} changed from \"{before}\" to \"{after}\"."


def compute_delta(doc_a: CanonicalDocument, doc_b: CanonicalDocument) -> DeltaResult:
    result = DeltaResult(pid_a=doc_a.pid, pid_b=doc_b.pid)
    item_no = 0

    pages_a = {p.index: p for p in doc_a.pages}
    pages_b = {p.index: p for p in doc_b.pages}
    all_page_idx = sorted(set(pages_a) | set(pages_b))

    for pidx in all_page_idx:
        pa = pages_a.get(pidx)
        pb = pages_b.get(pidx)

        if pa is None:
            for ln in pb.lines:
                if len(ln.text.strip()) < 2:
                    continue
                item_no += 1
                result.items.append(
                    DeltaItem(
                        id=f"D{item_no:04d}", change_type="added", item_type=classify_type(ln.text),
                        page_index=pidx, location=ln.bbox, before_text=None, after_text=ln.text,
                        description=_describe("added", classify_type(ln.text), None, ln.text),
                        confidence=1.0,
                    )
                )
            continue
        if pb is None:
            for ln in pa.lines:
                if len(ln.text.strip()) < 2:
                    continue
                item_no += 1
                result.items.append(
                    DeltaItem(
                        id=f"D{item_no:04d}", change_type="removed", item_type=classify_type(ln.text),
                        page_index=pidx, location=ln.bbox, before_text=ln.text, after_text=None,
                        description=_describe("removed", classify_type(ln.text), ln.text, None),
                        confidence=1.0,
                    )
                )
            continue

        alignment = align_pages(pa.lines, pb.lines, pa.width, pa.height)

        for m in alignment.matches:
            a_line: TextLine = pa.lines[m.a_index]
            b_line: TextLine = pb.lines[m.b_index]
            if _strict_normalize(a_line.text) == _strict_normalize(b_line.text):
                continue  # unchanged (formatting-only) -- not part of the delta
            item_no += 1
            item_type = classify_type(b_line.text) if classify_type(b_line.text) != "text" else classify_type(a_line.text)
            result.items.append(
                DeltaItem(
                    id=f"D{item_no:04d}", change_type="modified", item_type=item_type,
                    page_index=pidx, location=b_line.bbox,
                    before_text=a_line.text, after_text=b_line.text,
                    description=_describe("modified", item_type, a_line.text, b_line.text),
                    confidence=round(m.combined, 3),
                )
            )

        for ai in alignment.unmatched_a:
            ln = pa.lines[ai]
            item_no += 1
            result.items.append(
                DeltaItem(
                    id=f"D{item_no:04d}", change_type="removed", item_type=classify_type(ln.text),
                    page_index=pidx, location=ln.bbox, before_text=ln.text, after_text=None,
                    description=_describe("removed", classify_type(ln.text), ln.text, None),
                    confidence=1.0,
                )
            )
        for bi in alignment.unmatched_b:
            ln = pb.lines[bi]
            item_no += 1
            result.items.append(
                DeltaItem(
                    id=f"D{item_no:04d}", change_type="added", item_type=classify_type(ln.text),
                    page_index=pidx, location=ln.bbox, before_text=None, after_text=ln.text,
                    description=_describe("added", classify_type(ln.text), None, ln.text),
                    confidence=1.0,
                )
            )

    return result
