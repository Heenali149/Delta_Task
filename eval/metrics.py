"""Delta and chat metrics. See README "Evaluation approach" for methodology
and why precision is sample-based rather than computed against a fully
hand-labeled prediction set.
"""
from __future__ import annotations

from dataclasses import dataclass


def _contains(haystack: str | None, needle: str | None) -> bool:
    if needle is None:
        return True
    if haystack is None:
        return False
    return needle.upper() in haystack.upper()


def _gt_matches(gt: dict, pred: dict) -> bool:
    if gt["change_type"] != pred["change_type"]:
        return False
    if not _contains(pred.get("before_text"), gt.get("before_contains")):
        return False
    if not _contains(pred.get("after_text"), gt.get("after_contains")):
        return False
    return True


@dataclass
class DeltaEvalResult:
    recall: float
    matched: list[str]
    missed: list[str]
    precision: float
    precision_sample_size: int
    precision_correct: int
    f1: float


def evaluate_delta(predicted_items: list[dict], ground_truth: dict, sample_review: dict) -> DeltaEvalResult:
    matched, missed = [], []
    for gt in ground_truth["items"]:
        found = any(_gt_matches(gt, pred) for pred in predicted_items)
        (matched if found else missed).append(gt["id"])
    recall = len(matched) / len(ground_truth["items"]) if ground_truth["items"] else 0.0

    judgements = sample_review["judgements"]
    correct = sum(1 for j in judgements if j["correct"])
    precision = correct / len(judgements) if judgements else 0.0

    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return DeltaEvalResult(
        recall=round(recall, 3), matched=matched, missed=missed,
        precision=round(precision, 3), precision_sample_size=len(judgements),
        precision_correct=correct, f1=round(f1, 3),
    )


@dataclass
class ChatEvalResult:
    answer_correctness: float
    groundedness: float
    per_question: list[dict]


def evaluate_chat(qa_items: list[dict], run_fn) -> ChatEvalResult:
    """`run_fn(question) -> AnswerResult` (src.chat.answer.AnswerResult)."""
    per_question = []
    correct_count = 0
    total_grounded_ratio = 0.0

    for qa in qa_items:
        result = run_fn(qa["question"])
        answer_upper = result.answer.upper()
        is_correct = any(term.upper() in answer_upper for term in qa["expect_answer_contains"])
        correct_count += int(is_correct)

        n_claimed = len(result.citations_claimed)
        n_valid = len(result.citations_valid)
        grounded_ratio = (n_valid / n_claimed) if n_claimed else (1.0 if not result.retrieved else 0.0)
        total_grounded_ratio += grounded_ratio

        per_question.append(
            {
                "id": qa["id"], "question": qa["question"], "correct": is_correct,
                "answer": result.answer, "citations_valid": result.citations_valid,
                "citations_invalid": result.citations_invalid, "grounded_ratio": round(grounded_ratio, 3),
            }
        )

    n = len(qa_items) or 1
    return ChatEvalResult(
        answer_correctness=round(correct_count / n, 3),
        groundedness=round(total_grounded_ratio / n, 3),
        per_question=per_question,
    )
