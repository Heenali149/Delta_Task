import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.canonical.model import CanonicalDocument, Page, TextLine
from src.delta.align import position_similarity, text_similarity
from src.delta.engine import classify_type, compute_delta


def make_doc(pid: str, lines_spec: list[tuple[str, tuple]]) -> CanonicalDocument:
    lines = [
        TextLine(line_id=f"{pid}:{i}", text=text, bbox=bbox, page_index=0)
        for i, (text, bbox) in enumerate(lines_spec)
    ]
    return CanonicalDocument(
        pid=pid, source_format="pdf_native", revision_label=pid,
        pages=[Page(index=0, width=1000, height=800, lines=lines)],
    )


def test_text_similarity_identical_is_one():
    assert text_similarity("26-KA-901", "26-KA-901") == 1.0


def test_text_similarity_different_is_partial():
    assert 0 < text_similarity("COMPRESSOR STOP", "COMPRESSOR START") < 1.0


def test_text_similarity_disjoint_is_zero():
    assert text_similarity("776", "1835") == 0.0


def test_position_similarity_same_point_is_one():
    assert position_similarity((10, 10, 20, 20), (10, 10, 20, 20), page_diag=1000) == 1.0


def test_classify_type_tag():
    assert classify_type("26-KA-901") == "tag"


def test_classify_type_spec_value():
    assert classify_type("776 kW") == "spec_value"


def test_classify_type_note():
    assert classify_type("16. PRIMARY SEAL GAS TAKEN DOWNSTREAM") == "note"


def test_compute_delta_detects_modified_added_removed():
    doc_a = make_doc(
        "A",
        [
            ("TAG NUMBER 26-KA-901", (10, 10, 100, 20)),
            ("DUTY kW 776", (10, 30, 100, 40)),
            ("FLANGE RATING 300#", (500, 500, 600, 510)),
        ],
    )
    doc_b = make_doc(
        "B",
        [
            ("TAG NUMBER 26-KA-902", (10, 10, 100, 20)),  # modified, same slot
            ("DUTY kW 1835", (10, 30, 100, 40)),  # modified, same slot
            ("MOTOR VIBRATION HIGH TRIP", (10, 700, 200, 710)),  # unrelated text, far away -> no match
        ],
    )
    result = compute_delta(doc_a, doc_b)
    change_types = {(it.change_type, it.before_text, it.after_text) for it in result.items}

    assert ("modified", "TAG NUMBER 26-KA-901", "TAG NUMBER 26-KA-902") in change_types
    assert ("modified", "DUTY kW 776", "DUTY kW 1835") in change_types
    assert ("removed", "FLANGE RATING 300#", None) in change_types
    assert ("added", None, "MOTOR VIBRATION HIGH TRIP") in change_types


def test_compute_delta_ignores_punctuation_only_differences():
    doc_a = make_doc("A", [("NOTE 3, 8,14", (10, 10, 100, 20))])
    doc_b = make_doc("B", [("NOTE 3,8,14", (10, 10, 100, 20))])
    result = compute_delta(doc_a, doc_b)
    assert result.items == []


def test_compute_delta_is_deterministic():
    doc_a = make_doc("A", [("TAG NUMBER 26-KA-901", (10, 10, 100, 20)), ("DUTY kW 776", (10, 30, 100, 40))])
    doc_b = make_doc("B", [("TAG NUMBER 26-KA-902", (10, 10, 100, 20)), ("DUTY kW 1835", (10, 30, 100, 40))])
    r1 = compute_delta(doc_a, doc_b).to_dict()
    r2 = compute_delta(doc_a, doc_b).to_dict()
    assert r1 == r2
