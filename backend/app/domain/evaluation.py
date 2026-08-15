from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.sql_generation import SQLGenerationResult

EvaluationOutcome = Literal["execute", "clarify", "block"]
AnswerabilityExpectation = Literal["answerable", "ambiguous", "unsupported"]
GuardrailExpectation = Literal[
    "allow",
    "reject_request",
    "reject_malformed",
    "block_generated_sql",
]
HallucinationExpectation = Literal[
    "none",
    "semantic_mismatch",
    "schema_reference",
    "not_assessed",
]


class ExpectedResult(BaseModel):
    """Canonical result expected from the deterministic seeded database."""

    columns: list[str]
    rows: list[dict[str, Any]]
    ordered: bool = False

    model_config = ConfigDict(extra="forbid")


class RegressionThresholds(BaseModel):
    """Stable safety and infrastructure limits for deterministic regression runs."""

    minimum_cases: int = Field(ge=1)
    max_infrastructure_failures: int = Field(ge=0)
    max_unsafe_query_escapes: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class EvaluationCase(BaseModel):
    """A versioned Text-to-SQL evaluation fixture and deterministic fake response."""

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    question: str
    tags: list[str] = Field(min_length=1)
    expected_outcome: EvaluationOutcome
    expected_sql: str | None = None
    expected_result: ExpectedResult | None = None
    expected_result_match: bool | None = None
    expected_tables: list[str] = Field(default_factory=list)
    expected_columns: list[str] = Field(default_factory=list)
    ambiguity: bool
    answerability: AnswerabilityExpectation
    guardrail: GuardrailExpectation
    hallucination: HallucinationExpectation
    fake_response: SQLGenerationResult | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_expectations(self) -> EvaluationCase:
        if self.expected_outcome == "execute":
            if self.expected_sql is None or self.expected_result is None:
                raise ValueError("executed cases require expected_sql and expected_result")
            if self.expected_result_match is None:
                raise ValueError("executed cases require expected_result_match")
            if self.guardrail != "allow" or self.answerability != "answerable":
                raise ValueError("executed cases must be answerable and guardrail-allowed")
            if self.fake_response is None:
                raise ValueError("executed cases require a fake_response")
        elif self.expected_sql is not None or self.expected_result is not None:
            raise ValueError("non-executed cases must not declare expected SQL or results")

        if (
            self.expected_outcome == "clarify"
            and not self.ambiguity
            and self.answerability == "answerable"
        ):
            raise ValueError("clarification cases must be ambiguous or unsupported")
        if self.guardrail == "block_generated_sql" and self.expected_outcome != "block":
            raise ValueError("generated unsafe SQL must expect a block")
        if self.guardrail == "reject_request" and self.expected_outcome != "clarify":
            raise ValueError("unsafe requests must expect clarification")
        if self.guardrail == "reject_malformed" and self.expected_outcome != "block":
            raise ValueError("malformed requests must expect a block")
        if self.hallucination == "semantic_mismatch" and self.expected_result_match is not False:
            raise ValueError("semantic mismatch cases must expect a result mismatch")
        return self


class EvaluationDataset(BaseModel):
    """Root document for a checked-in evaluation suite."""

    version: Literal[1]
    name: str
    cases: list[EvaluationCase] = Field(min_length=1)
    regression_thresholds: RegressionThresholds

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_unique_cases(self) -> EvaluationDataset:
        ids = [case.id for case in self.cases]
        questions = [case.question.casefold().strip() for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case IDs must be unique")
        if len(questions) != len(set(questions)):
            raise ValueError("evaluation case questions must be unique")
        return self


def load_evaluation_dataset(path: Path) -> EvaluationDataset:
    """Load and strictly validate a versioned JSON evaluation dataset."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    case_files = payload.pop("case_files", [])
    if not isinstance(case_files, list) or not all(isinstance(item, str) for item in case_files):
        raise ValueError("case_files must be a list of relative JSON filenames")
    for filename in case_files:
        candidate = path.parent / filename
        if candidate.parent != path.parent or candidate.suffix != ".json":
            raise ValueError("case_files entries must be JSON files in the dataset directory")
        additional_payload = json.loads(candidate.read_text(encoding="utf-8"))
        additional_cases = additional_payload.get("cases")
        if not isinstance(additional_cases, list):
            raise ValueError("additional case files must contain a cases list")
        payload["cases"].extend(additional_cases)
    return EvaluationDataset.model_validate(payload)
