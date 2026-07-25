import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.canonical.model import CanonicalDocument, Page, TextLine
from src.chat.index import RetrievalIndex
from src.chat.llm import MockClient
from src.chat.answer import answer_question
from src.delta.engine import compute_delta


def make_doc(pid: str, lines_spec) -> CanonicalDocument:
    lines = [TextLine(line_id=f"{pid}:{i}", text=t, bbox=b, page_index=0) for i, (t, b) in enumerate(lines_spec)]
    return CanonicalDocument(pid=pid, source_format="pdf_native", revision_label=pid,
                              pages=[Page(index=0, width=1000, height=800, lines=lines)])


def test_retrieval_finds_relevant_chunk():
    doc_a = make_doc("A", [("TAG", (10, 10, 30, 20)), ("NUMBER 26-KA-901", (32, 10, 100, 20)),
                           ("DUTY", (10, 30, 30, 40)), ("kW 776", (32, 30, 100, 40))])
    doc_b = make_doc("B", [("TAG", (10, 10, 30, 20)), ("NUMBER 26-KA-902", (32, 10, 100, 20)),
                           ("DUTY", (10, 30, 30, 40)), ("kW 1835", (32, 30, 100, 40))])
    delta = compute_delta(doc_a, doc_b)
    index = RetrievalIndex(doc_a, doc_b, delta)
    results = index.retrieve("what is the duty in kW", k=3)
    assert results, "expected at least one retrieved chunk"
    top_texts = " ".join(c.text for c, _ in results)
    assert "776" in top_texts or "1835" in top_texts


def test_mock_client_never_fabricates_citation_outside_context():
    doc_a = make_doc("A", [("TAG NUMBER 26-KA-901", (10, 10, 100, 20))])
    doc_b = make_doc("B", [("TAG NUMBER 26-KA-902", (10, 10, 100, 20))])
    delta = compute_delta(doc_a, doc_b)
    index = RetrievalIndex(doc_a, doc_b, delta)
    result = answer_question("what is the tag number?", index, MockClient(), k=5)
    assert not result.citations_invalid
