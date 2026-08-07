from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import Settings
from app.domain.glossary import BusinessGlossary
from app.domain.schema_catalog import SchemaCatalog
from app.domain.sql_generation import SQLGenerationDraft
from app.providers.sql_generation import SQLGenerator
from app.services.prompt_engine import SchemaAwarePromptEngine
from app.services.schema_retrieval import LexicalSchemaRetriever


@dataclass(frozen=True)
class ClarificationOption:
    """A distinct interpretation users can choose when a question is ambiguous."""

    interpretation: str
    example: str


@dataclass(frozen=True)
class ClarificationRequired:
    """Clarification response created before or after provider generation."""

    message: str
    options: tuple[ClarificationOption, ...]


@dataclass(frozen=True)
class QueryDraftResult:
    """Generation-only query draft service result."""

    draft: SQLGenerationDraft | None = None
    clarification: ClarificationRequired | None = None

    @property
    def clarification_required(self) -> bool:
        return self.clarification is not None


class QueryDraftService:
    """Retrieve schema, detect ambiguity, build prompt, and request a SQL draft."""

    def __init__(
        self,
        settings: Settings,
        sql_generator: SQLGenerator,
        retriever: LexicalSchemaRetriever | None = None,
        prompt_engine: SchemaAwarePromptEngine | None = None,
    ) -> None:
        self._settings = settings
        self._sql_generator = sql_generator
        self._retriever = retriever or LexicalSchemaRetriever(settings)
        self._prompt_engine = prompt_engine or SchemaAwarePromptEngine(settings)

    def draft(self, question: str, catalog: SchemaCatalog) -> QueryDraftResult:
        normalized_question = normalize_question(question)
        retrieval = self._retriever.retrieve(
            normalized_question,
            catalog.database_schema,
            catalog.glossary,
        )

        ambiguity = detect_business_ambiguity(
            normalized_question,
            catalog.glossary,
        )
        if ambiguity is not None:
            return QueryDraftResult(clarification=ambiguity)

        if not retrieval.selected_tables:
            return QueryDraftResult(clarification=unanswerable_clarification())

        prompt = self._prompt_engine.build_prompt(normalized_question, catalog, retrieval)
        draft = self._sql_generator.generate(prompt)
        if draft.result.clarification_needed:
            return QueryDraftResult(
                clarification=provider_clarification(draft.result.clarification_options)
            )
        return QueryDraftResult(draft=draft)


def normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question).strip()


def detect_business_ambiguity(
    question: str,
    glossary: BusinessGlossary,
) -> ClarificationRequired | None:
    normalized = question.casefold()

    injection_clarification = detect_prompt_injection_attempt(normalized)
    if injection_clarification is not None:
        return injection_clarification

    options: list[ClarificationOption] = []

    if contains_any(normalized, ("revenue", "sales")):
        if not contains_any(normalized, ("gross revenue", "net revenue", "gross", "net")):
            options.extend(revenue_options(glossary))

    if contains_any(normalized, (" by date", " by month", " by quarter", " by year")):
        if not contains_any(normalized, ("ordered", "paid", "refunded", "shipped", "delivered")):
            options.extend(date_basis_options())

    if contains_any(normalized, ("customer location", "customer geography", "customer area")):
        options.extend(customer_location_options())

    if contains_any(normalized, ("refund", "refunded")) and contains_any(
        normalized,
        ("order", "orders", "revenue", "sales"),
    ):
        if not contains_any(normalized, ("include refund", "exclude refund", "net", "gross")):
            options.extend(refund_handling_options())

    if contains_any(normalized, ("orders", "order count", "count orders")):
        if not contains_any(
            normalized,
            ("all orders", "completed", "delivered", "cancelled", "pending", "shipped"),
        ):
            options.extend(order_status_options())

    if not options:
        return None

    return ClarificationRequired(
        message=(
            "The question is materially ambiguous. "
            "Choose an interpretation before SQL is generated."
        ),
        options=deduplicate_options(options),
    )


def detect_prompt_injection_attempt(question: str) -> ClarificationRequired | None:
    if not contains_any(
        question,
        (
            "ignore previous",
            "ignore the previous",
            "ignore your instructions",
            "ignore your rules",
            "ignore the rules",
            "system prompt",
            "developer message",
            "drop table",
            "delete from",
            "insert into",
            "update ",
            "alter table",
            "truncate ",
        ),
    ):
        return None

    return ClarificationRequired(
        message=(
            "The request appears to conflict with the read-only SQL drafting rules. "
            "Ask a business question that can be answered from the available commerce schema."
        ),
        options=(
            ClarificationOption(
                "Ask a read-only revenue question",
                "Show gross revenue by ordered month",
            ),
            ClarificationOption(
                "Ask a read-only product question",
                "Which customers bought products in a category?",
            ),
            ClarificationOption(
                "Ask a read-only delivery question",
                "Show average delivery time by carrier",
            ),
        ),
    )


def contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def revenue_options(glossary: BusinessGlossary) -> list[ClarificationOption]:
    glossary_names = {term.name for term in glossary.terms}
    options = [
        ClarificationOption(
            "Gross revenue before refunds",
            "Show gross revenue by ordered month",
        ),
        ClarificationOption(
            "Net revenue after succeeded refunds",
            "Show net revenue by ordered month",
        ),
    ]
    if not {"gross revenue", "net revenue"} <= glossary_names:
        return options
    return options


def date_basis_options() -> list[ClarificationOption]:
    return [
        ClarificationOption("Order date basis", "Show gross revenue by ordered month"),
        ClarificationOption("Payment date basis", "Show captured payments by paid month"),
        ClarificationOption("Shipment date basis", "Show deliveries by delivered month"),
    ]


def customer_location_options() -> list[ClarificationOption]:
    return [
        ClarificationOption("Customer profile region", "Show orders by customer region"),
        ClarificationOption("Customer country code", "Show orders by customer country_code"),
        ClarificationOption("Order billing region", "Show orders by billing region"),
    ]


def refund_handling_options() -> list[ClarificationOption]:
    return [
        ClarificationOption(
            "Include refunded orders",
            "Count all orders including refunded orders",
        ),
        ClarificationOption("Exclude refunded orders", "Count orders without succeeded refunds"),
        ClarificationOption("Report refund amounts separately", "Show refund amount by reason"),
    ]


def order_status_options() -> list[ClarificationOption]:
    return [
        ClarificationOption("All orders regardless of status", "Count all orders"),
        ClarificationOption("Completed delivered orders only", "Count completed orders"),
        ClarificationOption("Open orders only", "Count pending and shipped orders"),
    ]


def unanswerable_clarification() -> ClarificationRequired:
    return ClarificationRequired(
        message="The question does not match the available commerce schema context.",
        options=(
            ClarificationOption("Ask about orders", "Show gross revenue by ordered month"),
            ClarificationOption("Ask about products", "Show active products by category"),
            ClarificationOption("Ask about shipments", "Show average delivery time by carrier"),
        ),
    )


def provider_clarification(options: list[str]) -> ClarificationRequired:
    return ClarificationRequired(
        message="The SQL generator needs clarification before producing a draft.",
        options=tuple(
            ClarificationOption(option, option)
            for option in dict.fromkeys(options)
        ),
    )


def deduplicate_options(options: list[ClarificationOption]) -> tuple[ClarificationOption, ...]:
    deduplicated: dict[str, ClarificationOption] = {}
    for option in options:
        deduplicated.setdefault(option.interpretation, option)
    return tuple(deduplicated.values())
