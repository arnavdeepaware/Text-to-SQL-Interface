import json
from importlib import resources
from typing import Any

from app.domain.prompt import FewShotExample

FEW_SHOT_RESOURCE_PACKAGE = "app.resources"
FEW_SHOT_RESOURCE_NAME = "few_shot_examples.json"


class FewShotLoadError(ValueError):
    """Raised when bundled few-shot examples are malformed."""


class FewShotExampleLoader:
    """Load schema-specific few-shot examples from a JSON resource."""

    def __init__(
        self,
        resource_package: str = FEW_SHOT_RESOURCE_PACKAGE,
        resource_name: str = FEW_SHOT_RESOURCE_NAME,
    ) -> None:
        self._resource_package = resource_package
        self._resource_name = resource_name

    def load(self) -> tuple[FewShotExample, ...]:
        resource = resources.files(self._resource_package).joinpath(self._resource_name)
        return parse_few_shot_examples(resource.read_text(encoding="utf-8"))


def parse_few_shot_examples(content: str) -> tuple[FewShotExample, ...]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise FewShotLoadError("Few-shot resource is not valid JSON") from exc

    if payload.get("version") != 1:
        raise FewShotLoadError("Few-shot resource version must be 1")

    examples_payload = payload.get("examples")
    if not isinstance(examples_payload, list) or not examples_payload:
        raise FewShotLoadError("Few-shot resource requires a non-empty examples list")

    examples = tuple(parse_example(example) for example in examples_payload)
    ids = [example.example_id for example in examples]
    if len(ids) != len(set(ids)):
        raise FewShotLoadError("Few-shot example ids must be unique")

    return tuple(sorted(examples, key=lambda example: example.example_id))


def parse_example(value: object) -> FewShotExample:
    if not isinstance(value, dict):
        raise FewShotLoadError("Few-shot example must be an object")

    required_fields = ("id", "question", "sql", "required_tables")
    missing = [field for field in required_fields if not value.get(field)]
    if missing:
        raise FewShotLoadError(f"Few-shot example missing fields: {', '.join(missing)}")

    return FewShotExample(
        example_id=str(value["id"]),
        question=str(value["question"]),
        sql=str(value["sql"]),
        required_tables=string_tuple(value["required_tables"], "required_tables"),
        required_columns=string_tuple(value.get("required_columns", []), "required_columns"),
        glossary_terms=string_tuple(value.get("glossary_terms", []), "glossary_terms"),
        tags=string_tuple(value.get("tags", []), "tags"),
    )


def string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FewShotLoadError(f"{field_name} must be a list")
    return tuple(str(item) for item in value)
