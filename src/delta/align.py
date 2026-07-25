"""Content alignment between two canonical documents.

This is the hard part the assignment calls out explicitly: matching, not
diffing. A raw text/pixel diff on these two P&IDs would report ~90% of the
page as "changed" because every tag number differs between the two
compressor trains (26-KA-901 vs 26-KA-902, PSV-9066A vs PSV-9027A, ...).
What actually matters is: same slot in the drawing, different value ->
*modified*; slot exists in one doc and not the other -> *added*/*removed*.

Alignment score is a deterministic blend of:
  - text similarity (difflib ratio on normalized text)
  - spatial similarity (bbox-center distance, normalized by page diagonal)

Text similarity alone would mis-align "9066A" -> whichever other short tag
happens to look similar. Position similarity alone would mis-align content
that moved. Combining both is what lets e.g. "776" (kW) at a given table
cell match "1835" at the same cell as a *modified* value instead of being
reported as an unrelated remove+add pair.

Fully deterministic and reproducible: no LLM in this path.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from src.canonical.model import TextLine

MIN_TEXT_LEN = 3
TEXT_WEIGHT = 0.55
POS_WEIGHT = 0.45
MATCH_THRESHOLD = 0.40
SPATIAL_WINDOW = 260  # points; candidate search radius on the page


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).upper()


def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def _center(bbox) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def position_similarity(a_bbox, b_bbox, page_diag: float) -> float:
    ax, ay = _center(a_bbox)
    bx, by = _center(b_bbox)
    dist = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
    return max(0.0, 1.0 - dist / page_diag)


@dataclass
class Match:
    a_index: int
    b_index: int
    text_sim: float
    pos_sim: float
    combined: float


@dataclass
class AlignmentResult:
    matches: list[Match]
    unmatched_a: list[int]
    unmatched_b: list[int]


def align_pages(lines_a: list[TextLine], lines_b: list[TextLine], page_width: float, page_height: float) -> AlignmentResult:
    """Greedy best-first matching within one page pair."""
    page_diag = (page_width**2 + page_height**2) ** 0.5

    a_idxs = [i for i, ln in enumerate(lines_a) if len(ln.text.strip()) >= MIN_TEXT_LEN]
    b_idxs = [i for i, ln in enumerate(lines_b) if len(ln.text.strip()) >= MIN_TEXT_LEN]

    # Bucket B lines by rounded grid cell so each A line only scores nearby
    # candidates -- O(n) candidate lookup instead of O(n*m) full cross product.
    grid = {}
    cell = SPATIAL_WINDOW
    for bi in b_idxs:
        bx, by = _center(lines_b[bi].bbox)
        key = (int(bx // cell), int(by // cell))
        grid.setdefault(key, []).append(bi)

    candidates: list[Match] = []
    for ai in a_idxs:
        a_line = lines_a[ai]
        ax, ay = _center(a_line.bbox)
        cx, cy = int(ax // cell), int(ay // cell)
        near_b = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                near_b.update(grid.get((cx + dx, cy + dy), []))
        for bi in near_b:
            b_line = lines_b[bi]
            t_sim = text_similarity(a_line.text, b_line.text)
            p_sim = position_similarity(a_line.bbox, b_line.bbox, page_diag)
            combined = TEXT_WEIGHT * t_sim + POS_WEIGHT * p_sim
            if combined >= MATCH_THRESHOLD:
                candidates.append(Match(ai, bi, t_sim, p_sim, combined))

    candidates.sort(key=lambda m: m.combined, reverse=True)
    matched_a, matched_b = set(), set()
    matches: list[Match] = []
    for m in candidates:
        if m.a_index in matched_a or m.b_index in matched_b:
            continue
        matched_a.add(m.a_index)
        matched_b.add(m.b_index)
        matches.append(m)

    unmatched_a = [i for i in a_idxs if i not in matched_a]
    unmatched_b = [i for i in b_idxs if i not in matched_b]
    return AlignmentResult(matches=matches, unmatched_a=unmatched_a, unmatched_b=unmatched_b)
