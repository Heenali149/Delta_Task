"""Proves the FormatAdapter seam: adding a 4th ingestion format (plain text)
required exactly one new adapter class + a one-line registration, and zero
changes to the delta engine or canonical model beyond the Literal type.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.delta.engine import compute_delta
from src.ingest.base import detect_and_load
from src.ingest.plaintext import PlainTextAdapter


def test_plaintext_adapter_can_handle_txt(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    assert PlainTextAdapter().can_handle(p) is True
    assert PlainTextAdapter().can_handle(tmp_path / "a.pdf") is False


def test_plaintext_adapter_loads_lines_with_synthetic_bbox():
    doc = PlainTextAdapter().load  # bound method, path built below
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "rev_a.txt"
        p.write_text("TAG NUMBER 26-KA-901\n\nDUTY kW 776\n", encoding="utf-8")
        result = doc(p, pid="demo:A", revision_label="A")

    assert result.source_format == "text"
    assert [ln.text for ln in result.all_lines()] == ["TAG NUMBER 26-KA-901", "DUTY kW 776"]


def test_detect_and_load_routes_txt_to_plaintext_adapter(tmp_path):
    p = tmp_path / "rev_a.txt"
    p.write_text("TAG NUMBER 26-KA-901\n", encoding="utf-8")
    result = detect_and_load(p, pid="demo:A", revision_label="A")
    assert result.source_format == "text"


def test_delta_engine_works_unmodified_on_a_new_format(tmp_path):
    a = tmp_path / "rev_a.txt"
    b = tmp_path / "rev_b.txt"
    a.write_text("TAG NUMBER 26-KA-901\nDUTY kW 776\nFLANGE RATING 300#\n", encoding="utf-8")
    b.write_text("TAG NUMBER 26-KA-902\nDUTY kW 1835\n", encoding="utf-8")

    doc_a = detect_and_load(a, pid="demo:A", revision_label="A")
    doc_b = detect_and_load(b, pid="demo:B", revision_label="B")
    result = compute_delta(doc_a, doc_b)

    change_types = {(it.change_type, it.before_text, it.after_text) for it in result.items}
    assert ("modified", "TAG NUMBER 26-KA-901", "TAG NUMBER 26-KA-902") in change_types
    assert ("modified", "DUTY kW 776", "DUTY kW 1835") in change_types
    assert ("removed", "FLANGE RATING 300#", None) in change_types
