import pytest

from app.services.few_shot_loader import (
    FewShotExampleLoader,
    FewShotLoadError,
    parse_few_shot_examples,
)


def test_few_shot_loader_loads_bundled_examples_in_stable_order() -> None:
    examples = FewShotExampleLoader().load()

    assert len(examples) == 6
    assert [example.example_id for example in examples] == sorted(
        example.example_id for example in examples
    )
    assert {example.example_id for example in examples} >= {
        "gross_revenue_by_month",
        "net_revenue",
        "delivery_time_by_carrier",
    }


def test_few_shot_loader_rejects_duplicate_ids() -> None:
    content = """
    {
      "version": 1,
      "examples": [
        {
          "id": "duplicate",
          "question": "Question one",
          "sql": "SELECT 1;",
          "required_tables": ["orders"]
        },
        {
          "id": "duplicate",
          "question": "Question two",
          "sql": "SELECT 2;",
          "required_tables": ["orders"]
        }
      ]
    }
    """

    with pytest.raises(FewShotLoadError, match="unique"):
        parse_few_shot_examples(content)


def test_few_shot_loader_rejects_missing_required_fields() -> None:
    content = """
    {
      "version": 1,
      "examples": [
        {
          "id": "broken",
          "question": "Question one",
          "required_tables": ["orders"]
        }
      ]
    }
    """

    with pytest.raises(FewShotLoadError, match="missing fields"):
        parse_few_shot_examples(content)
