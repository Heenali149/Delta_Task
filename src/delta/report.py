"""Renders a DeltaResult as both a human-readable Markdown report and a
machine-parseable JSON file. The Markdown report is itself chunked and
indexed as a retrievable source for chat (src/chat/index.py).
"""
from __future__ import annotations

import json
from pathlib import Path

from src.delta.engine import DeltaResult

ITEM_TYPE_ORDER = ["tag", "spec_value", "setpoint", "note", "text"]
CHANGE_TYPE_ORDER = ["modified", "added", "removed"]


def render_markdown(result: DeltaResult) -> str:
    s = result.summary()
    lines = [
        f"# Delta Report: `{result.pid_a}` -> `{result.pid_b}`",
        "",
        f"**Total changes detected:** {s['total']}",
        "",
        "| Change type | Count |",
        "|---|---|",
    ]
    for ct in CHANGE_TYPE_ORDER:
        lines.append(f"| {ct} | {s['by_change_type'].get(ct, 0)} |")
    lines += ["", "| Item type | Count |", "|---|---|"]
    for it in ITEM_TYPE_ORDER:
        if it in s["by_item_type"]:
            lines.append(f"| {it} | {s['by_item_type'][it]} |")
    lines.append("")

    by_page: dict[int, list] = {}
    for item in result.items:
        by_page.setdefault(item.page_index, []).append(item)

    for page_idx in sorted(by_page):
        lines.append(f"## Page {page_idx + 1}")
        lines.append("")
        for ct in CHANGE_TYPE_ORDER:
            group = [i for i in by_page[page_idx] if i.change_type == ct]
            if not group:
                continue
            group.sort(key=lambda i: -i.confidence)
            lines.append(f"### {ct.capitalize()} ({len(group)})")
            lines.append("")
            for item in group:
                loc = f"[{item.location[0]:.0f},{item.location[1]:.0f}]"
                lines.append(
                    f"- **`{item.id}`** ({item.item_type}, conf {item.confidence:.2f}, loc {loc}): "
                    f"{item.description}"
                )
            lines.append("")

    return "\n".join(lines)


def write_report(result: DeltaResult, out_dir: str | Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "delta.json"
    md_path = out_dir / "delta_report.md"
    json_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, md_path
