import pytest

from app.services.glossary_loader import BusinessGlossaryLoader, GlossaryLoadError


def test_business_glossary_loader_reads_bundled_terms() -> None:
    glossary = BusinessGlossaryLoader().load()

    assert glossary.version == 1
    assert [term.name for term in glossary.terms] == [
        "completed order",
        "delivery time",
        "gross revenue",
        "net revenue",
        "refunded order",
    ]


def test_business_glossary_loader_rejects_missing_required_term_fields() -> None:
    with pytest.raises(GlossaryLoadError):
        from app.services.glossary_loader import parse_business_glossary

        parse_business_glossary(
            """
version: 1
terms:
  - name: broken
    definition: Missing expression.
"""
        )
