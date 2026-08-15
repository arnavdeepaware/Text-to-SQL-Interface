from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.evaluation import EvaluationDataset, load_evaluation_dataset

DATASET_PATH = Path(__file__).resolve().parents[3] / "evals/cases/text_to_sql_v1.json"


def test_versioned_evaluation_dataset_contains_twenty_unique_cases() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)

    assert dataset.version == 1
    assert len(dataset.cases) == 20
    assert len({case.id for case in dataset.cases}) == 20
    assert {case.expected_outcome for case in dataset.cases} == {"execute", "clarify", "block"}


def test_dataset_rejects_duplicate_case_ids() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    payload = dataset.model_dump(mode="json")
    payload["cases"].append(payload["cases"][0])

    with pytest.raises(ValidationError, match="case IDs must be unique"):
        EvaluationDataset.model_validate(payload)


def test_dataset_rejects_semantic_mismatch_without_expected_result_mismatch() -> None:
    dataset = load_evaluation_dataset(DATASET_PATH)
    payload = dataset.model_dump(mode="json")
    case = next(
        item
        for item in payload["cases"]
        if item["id"] == "semantic_mismatch_delivered_orders"
    )
    case["expected_result_match"] = True

    with pytest.raises(ValidationError, match="semantic mismatch"):
        EvaluationDataset.model_validate(payload)
