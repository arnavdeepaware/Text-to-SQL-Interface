from __future__ import annotations

import math
import re
import unicodedata
from collections import deque
from collections.abc import Iterable
from typing import Protocol

from app.core.config import Settings
from app.domain.glossary import BusinessGlossary, GlossaryTerm
from app.domain.schema import ColumnSchema, DatabaseSchema, TableSchema
from app.domain.schema_retrieval import (
    RankedColumn,
    RankedTable,
    RelationshipPath,
    RelationshipPathStep,
    RetrievalReason,
    RetrievalStrategy,
    SchemaRetrievalResult,
)
from app.providers.embeddings import EmbeddingProvider, EmbeddingProviderError


class SchemaRetriever(Protocol):
    """Select schema objects relevant to a natural-language question."""

    def retrieve(
        self,
        question: str,
        database_schema: DatabaseSchema,
        glossary: BusinessGlossary,
    ) -> SchemaRetrievalResult: ...


TABLE_DESCRIPTIONS = {
    "categories": "Product category hierarchy, parent category, merchandise grouping.",
    "customers": "Customer profile, region, country, signup date.",
    "order_items": "Line items connecting orders to products, quantity, item totals.",
    "orders": "Customer orders, order status, billing region, revenue, totals, tax, discounts.",
    "payments": "Payment transactions for orders, payment method, captured or refunded status.",
    "products": "Product catalog, category, price, active flag, launch dates.",
    "refunds": "Refund transactions for payments, refund reason, refund status, refunded amount.",
    "shipments": (
        "Shipments and delivery lifecycle for orders, carrier, shipped and delivered times."
    ),
}

COLUMN_DESCRIPTIONS = {
    "billing_region": "Order billing region or sales region.",
    "country_code": "Customer country code.",
    "customer_id": "Customer primary or foreign key.",
    "delivered_at": "Shipment delivery timestamp.",
    "discount_cents": "Discount amount in cents.",
    "line_total_cents": "Line item total amount in cents.",
    "ordered_at": "Order timestamp.",
    "parent_category_id": "Parent category relationship.",
    "payment_id": "Payment primary or foreign key.",
    "payment_method": "Payment method category.",
    "quantity": "Purchased item quantity.",
    "reason": "Refund reason category.",
    "refunded_at": "Refund timestamp.",
    "region": "Customer geographic region.",
    "shipped_at": "Shipment shipped timestamp.",
    "status": "Business lifecycle status.",
    "subtotal_cents": "Order subtotal amount in cents.",
    "tax_cents": "Tax amount in cents.",
    "total_cents": "Order total amount in cents, used for gross revenue.",
    "unit_price_cents": "Unit price amount in cents.",
}

TOKEN_SYNONYMS = {
    "buyer": ("customer",),
    "buyers": ("customer",),
    "bought": ("order", "orders", "purchase", "purchased", "product", "products"),
    "buy": ("order", "orders", "purchase", "purchased", "product", "products"),
    "category": ("categories", "group", "department"),
    "completed": ("complete", "delivered"),
    "customer": ("buyer", "client", "region"),
    "customers": ("customer", "buyers", "clients"),
    "deliver": ("delivery", "shipment", "delivered"),
    "delivered": ("delivery", "shipment", "completed"),
    "delivery": ("deliver", "delivered", "shipment", "shipping"),
    "electronics": ("categories", "category", "products", "product"),
    "income": ("revenue", "sales"),
    "item": ("product", "line"),
    "items": ("item", "products", "line"),
    "merchandise": ("product", "category"),
    "product": ("item", "merchandise", "category"),
    "products": ("product", "items", "merchandise"),
    "purchase": ("bought", "buy", "order", "orders"),
    "purchased": ("bought", "buy", "order", "orders"),
    "refund": ("refunded", "return"),
    "refunded": ("refund", "return"),
    "region": ("regional", "billing_region"),
    "return": ("refund", "refunded"),
    "revenue": ("sales", "income"),
    "sale": ("sales", "revenue"),
    "sales": ("sale", "revenue"),
    "shipping": ("shipment", "delivery"),
    "time": ("timestamp", "duration"),
}

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "for",
        "from",
        "how",
        "is",
        "of",
        "on",
        "or",
        "show",
        "the",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
)


class LexicalSchemaRetriever:
    """Deterministic lexical schema retriever with optional embedding boost."""

    def __init__(
        self,
        settings: Settings,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._settings = settings
        self._embedding_provider = embedding_provider

    def retrieve(
        self,
        question: str,
        database_schema: DatabaseSchema,
        glossary: BusinessGlossary,
    ) -> SchemaRetrievalResult:
        query_tokens = expand_tokens(tokenize(question) - QUERY_STOPWORDS)
        glossary_matches = matching_glossary_terms(question, query_tokens, glossary)
        table_scores = self._score_tables(database_schema, glossary_matches, query_tokens)
        column_scores = self._score_columns(database_schema, glossary_matches, query_tokens)

        fallback_reason = self._apply_embedding_scores(question, table_scores, column_scores)
        ranked_tables = rank_table_scores(table_scores)
        ranked_columns = rank_column_scores(column_scores)

        selected_table_ids = tuple(
            table.identifier
            for table in ranked_tables
            if table.score >= self._settings.schema_retrieval_min_table_score
        )[: self._settings.schema_retrieval_max_tables]

        relationship_paths, bridge_table_ids = select_relationship_paths(
            database_schema,
            selected_table_ids,
            self._settings.schema_retrieval_max_bridge_hops,
            self._settings.schema_retrieval_max_tables,
        )
        final_table_ids = set(selected_table_ids) | set(bridge_table_ids)

        selected_column_ids = select_columns(
            ranked_columns,
            final_table_ids,
            self._settings.schema_retrieval_min_column_score,
            self._settings.schema_retrieval_max_columns_per_table,
        )

        final_ranked_tables = tuple(
            RankedTable(
                identifier=table.identifier,
                schema_name=table.schema_name,
                table_name=table.table_name,
                score=table.score,
                reasons=table.reasons,
                selected=table.identifier in final_table_ids,
                bridge=table.identifier in bridge_table_ids,
            )
            for table in ranked_tables
        )
        final_ranked_columns = tuple(
            RankedColumn(
                table_identifier=column.table_identifier,
                column_name=column.column_name,
                score=column.score,
                reasons=column.reasons,
                selected=column.identifier in selected_column_ids,
            )
            for column in ranked_columns
        )

        strategy: RetrievalStrategy = "lexical"
        if self._settings.schema_retrieval_use_embeddings and self._embedding_provider is not None:
            strategy = "embedding_fallback" if fallback_reason else "embedding"

        return SchemaRetrievalResult(
            question=question,
            strategy=strategy,
            ranked_tables=final_ranked_tables,
            ranked_columns=final_ranked_columns,
            relationship_paths=relationship_paths,
            glossary_terms=tuple(term.name for term in glossary_matches),
            fallback_reason=fallback_reason,
        )

    def _score_tables(
        self,
        database_schema: DatabaseSchema,
        glossary_matches: tuple[GlossaryTerm, ...],
        query_tokens: set[str],
    ) -> dict[str, ScoredTable]:
        scores: dict[str, ScoredTable] = {}
        for table in database_schema.tables:
            reasons: list[RetrievalReason] = []
            table_tokens = expand_tokens(
                tokenize(f"{table.name} {TABLE_DESCRIPTIONS.get(table.name, '')}")
            )
            add_token_reason(reasons, "table", table.name, query_tokens, table_tokens, 8.0)
            add_phrase_reason(
                reasons,
                "table",
                table.name,
                TABLE_DESCRIPTIONS.get(table.name, table.name),
                query_tokens,
                12.0,
            )

            related_terms = related_glossary_terms_for_table(table, glossary_matches)
            for term in related_terms:
                reasons.append(RetrievalReason("glossary", term.name, 18.0))

            scores[table.identifier] = ScoredTable(
                table=table,
                score=sum(reason.score for reason in reasons),
                reasons=tuple(sorted(reasons, key=reason_sort_key)),
            )
        return scores

    def _score_columns(
        self,
        database_schema: DatabaseSchema,
        glossary_matches: tuple[GlossaryTerm, ...],
        query_tokens: set[str],
    ) -> dict[str, ScoredColumn]:
        scores: dict[str, ScoredColumn] = {}
        for table in database_schema.tables:
            for column in table.columns:
                reasons: list[RetrievalReason] = []
                column_text = f"{column.name} {COLUMN_DESCRIPTIONS.get(column.name, '')}"
                column_tokens = expand_tokens(tokenize(column_text))
                add_token_reason(reasons, "column", column.name, query_tokens, column_tokens, 6.0)
                add_phrase_reason(
                    reasons,
                    "column",
                    column.name,
                    COLUMN_DESCRIPTIONS.get(column.name, column.name),
                    query_tokens,
                    8.0,
                )

                for term in related_glossary_terms_for_column(table, column, glossary_matches):
                    reasons.append(RetrievalReason("glossary", term.name, 14.0))

                identifier = f"{table.identifier}.{column.name}"
                scores[identifier] = ScoredColumn(
                    table=table,
                    column=column,
                    score=sum(reason.score for reason in reasons),
                    reasons=tuple(sorted(reasons, key=reason_sort_key)),
                )
        return scores

    def _apply_embedding_scores(
        self,
        question: str,
        table_scores: dict[str, ScoredTable],
        column_scores: dict[str, ScoredColumn],
    ) -> str | None:
        if not self._settings.schema_retrieval_use_embeddings:
            return None
        if self._embedding_provider is None or not self._embedding_provider.is_configured:
            return "embedding provider is not configured"

        candidate_ids = list(table_scores) + list(column_scores)
        candidate_texts = [
            candidate_text(table_scores, column_scores, candidate_id)
            for candidate_id in candidate_ids
        ]
        try:
            vectors = self._embedding_provider.embed((question, *candidate_texts))
        except EmbeddingProviderError as exc:
            return str(exc)
        except Exception:
            return "embedding provider failed"

        if len(vectors) != len(candidate_ids) + 1:
            return "embedding provider returned an unexpected number of vectors"

        question_vector = vectors[0]
        try:
            for candidate_id, vector in zip(candidate_ids, vectors[1:], strict=True):
                similarity = cosine_similarity(question_vector, vector)
                if similarity <= 0:
                    continue
                score = similarity * self._settings.schema_retrieval_embedding_weight
                reason = RetrievalReason("embedding", f"cosine={similarity:.3f}", score)
                if candidate_id in table_scores:
                    scored = table_scores[candidate_id]
                    table_scores[candidate_id] = scored.with_reason(reason)
                else:
                    scored_column = column_scores[candidate_id]
                    column_scores[candidate_id] = scored_column.with_reason(reason)
        except EmbeddingProviderError as exc:
            return str(exc)
        return None


class EmbeddingSchemaRetriever(LexicalSchemaRetriever):
    """Embedding-enabled retriever that reuses lexical scoring as fallback."""

    def __init__(self, settings: Settings, embedding_provider: EmbeddingProvider) -> None:
        super().__init__(
            settings.model_copy(update={"schema_retrieval_use_embeddings": True}),
            embedding_provider=embedding_provider,
        )


class ScoredTable:
    def __init__(
        self,
        table: TableSchema,
        score: float,
        reasons: tuple[RetrievalReason, ...],
    ) -> None:
        self.table = table
        self.score = score
        self.reasons = reasons

    def with_reason(self, reason: RetrievalReason) -> ScoredTable:
        return ScoredTable(
            self.table,
            self.score + reason.score,
            tuple(sorted((*self.reasons, reason), key=reason_sort_key)),
        )


class ScoredColumn:
    def __init__(
        self,
        table: TableSchema,
        column: ColumnSchema,
        score: float,
        reasons: tuple[RetrievalReason, ...],
    ) -> None:
        self.table = table
        self.column = column
        self.score = score
        self.reasons = reasons

    def with_reason(self, reason: RetrievalReason) -> ScoredColumn:
        return ScoredColumn(
            self.table,
            self.column,
            self.score + reason.score,
            tuple(sorted((*self.reasons, reason), key=reason_sort_key)),
        )


def tokenize(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold().replace("_", " ")
    return set(TOKEN_PATTERN.findall(normalized))


def expand_tokens(tokens: Iterable[str]) -> set[str]:
    expanded = set(tokens)
    for token in tuple(expanded):
        if token.endswith("s") and len(token) > 3:
            expanded.add(token[:-1])
        expanded.update(TOKEN_SYNONYMS.get(token, ()))
    return expanded


def matching_glossary_terms(
    question: str,
    query_tokens: set[str],
    glossary: BusinessGlossary,
) -> tuple[GlossaryTerm, ...]:
    matches: list[tuple[str, GlossaryTerm]] = []
    for term in glossary.terms:
        term_name_tokens = expand_tokens(tokenize(term.name) - QUERY_STOPWORDS)
        if term.name.casefold() in question.casefold() or term_name_tokens <= query_tokens:
            matches.append((term.name, term))
    return tuple(term for _, term in sorted(matches, key=lambda item: item[0]))


def related_glossary_terms_for_table(
    table: TableSchema,
    terms: tuple[GlossaryTerm, ...],
) -> tuple[GlossaryTerm, ...]:
    return tuple(
        term
        for term in terms
        if table.name in term.related_tables or table.identifier in term.related_tables
    )


def related_glossary_terms_for_column(
    table: TableSchema,
    column: ColumnSchema,
    terms: tuple[GlossaryTerm, ...],
) -> tuple[GlossaryTerm, ...]:
    column_names = {
        column.name,
        f"{table.name}.{column.name}",
        f"{table.identifier}.{column.name}",
    }
    return tuple(
        term
        for term in terms
        if column_names & set(term.related_columns)
    )


def add_token_reason(
    reasons: list[RetrievalReason],
    source: str,
    detail: str,
    query_tokens: set[str],
    candidate_tokens: set[str],
    weight: float,
) -> None:
    overlap = sorted(query_tokens & candidate_tokens)
    for token in overlap:
        reasons.append(RetrievalReason(source, f"{detail} token '{token}'", weight))


def add_phrase_reason(
    reasons: list[RetrievalReason],
    source: str,
    detail: str,
    text: str,
    query_tokens: set[str],
    weight: float,
) -> None:
    text_tokens = tokenize(text)
    for token in sorted(query_tokens & text_tokens):
        if len(token) >= 4:
            reasons.append(RetrievalReason(source, f"{detail} description '{token}'", weight))


def reason_sort_key(reason: RetrievalReason) -> tuple[str, str, float]:
    return (reason.source, reason.detail, reason.score)


def rank_table_scores(scores: dict[str, ScoredTable]) -> tuple[RankedTable, ...]:
    ranked = [
        RankedTable(
            identifier=scored.table.identifier,
            schema_name=scored.table.schema_name,
            table_name=scored.table.name,
            score=round(scored.score, 6),
            reasons=scored.reasons,
            selected=False,
        )
        for scored in scores.values()
    ]
    return tuple(sorted(ranked, key=lambda table: (-table.score, table.identifier)))


def rank_column_scores(scores: dict[str, ScoredColumn]) -> tuple[RankedColumn, ...]:
    ranked = [
        RankedColumn(
            table_identifier=scored.table.identifier,
            column_name=scored.column.name,
            score=round(scored.score, 6),
            reasons=scored.reasons,
            selected=False,
        )
        for scored in scores.values()
    ]
    return tuple(sorted(ranked, key=lambda column: (-column.score, column.identifier)))


def select_columns(
    ranked_columns: tuple[RankedColumn, ...],
    selected_table_ids: set[str],
    min_score: float,
    max_columns_per_table: int,
) -> set[str]:
    selected: set[str] = set()
    counts_by_table = dict.fromkeys(selected_table_ids, 0)
    for column in ranked_columns:
        if column.table_identifier not in selected_table_ids:
            continue
        if column.score < min_score and not is_key_column(column.column_name):
            continue
        if counts_by_table[column.table_identifier] >= max_columns_per_table:
            continue
        selected.add(column.identifier)
        counts_by_table[column.table_identifier] += 1
    return selected


def is_key_column(column_name: str) -> bool:
    return column_name.endswith("_id") or column_name == "id"


def select_relationship_paths(
    database_schema: DatabaseSchema,
    selected_table_ids: tuple[str, ...],
    max_hops: int,
    max_tables: int,
) -> tuple[tuple[RelationshipPath, ...], tuple[str, ...]]:
    if len(selected_table_ids) < 2 or max_hops == 0:
        return (), ()

    graph = relationship_graph(database_schema)
    included = {selected_table_ids[0]}
    bridge_tables: set[str] = set()
    paths: list[RelationshipPath] = []

    for target_table_id in selected_table_ids[1:]:
        if target_table_id in included:
            continue
        path = shortest_path(graph, included, target_table_id, max_hops)
        if path is None:
            continue
        new_tables = set(path.table_identifiers) - included
        if len(included | new_tables) > max_tables:
            continue
        paths.append(path)
        bridge_tables.update(
            table_id for table_id in path.table_identifiers if table_id not in selected_table_ids
        )
        included.update(path.table_identifiers)

    return tuple(paths), tuple(sorted(bridge_tables))


def relationship_graph(
    database_schema: DatabaseSchema,
) -> dict[str, tuple[RelationshipPathStep, ...]]:
    adjacency: dict[str, list[RelationshipPathStep]] = {
        table.identifier: []
        for table in database_schema.tables
    }
    for table in database_schema.tables:
        for foreign_key in table.foreign_keys:
            source = foreign_key.source_table_identifier
            referred = foreign_key.referred_table_identifier
            adjacency.setdefault(source, []).append(
                RelationshipPathStep(foreign_key, source, referred)
            )
            adjacency.setdefault(referred, []).append(
                RelationshipPathStep(foreign_key, referred, source)
            )
    return {
        table_id: tuple(sorted(steps, key=relationship_step_sort_key))
        for table_id, steps in adjacency.items()
    }


def shortest_path(
    graph: dict[str, tuple[RelationshipPathStep, ...]],
    start_table_ids: set[str],
    target_table_id: str,
    max_hops: int,
) -> RelationshipPath | None:
    queue: deque[tuple[str, tuple[str, ...], tuple[RelationshipPathStep, ...]]] = deque(
        (table_id, (table_id,), ())
        for table_id in sorted(start_table_ids)
    )
    visited = set(start_table_ids)

    while queue:
        current, table_path, steps = queue.popleft()
        if len(steps) >= max_hops:
            continue

        for step in graph.get(current, ()):
            next_table = step.to_table_identifier
            if next_table in visited and next_table != target_table_id:
                continue
            next_table_path = (*table_path, next_table)
            next_steps = (*steps, step)
            if next_table == target_table_id:
                return RelationshipPath(next_table_path, next_steps)
            visited.add(next_table)
            queue.append((next_table, next_table_path, next_steps))
    return None


def relationship_step_sort_key(step: RelationshipPathStep) -> tuple[str, str, str]:
    return (step.to_table_identifier, step.from_table_identifier, step.foreign_key.display_path)


def candidate_text(
    table_scores: dict[str, ScoredTable],
    column_scores: dict[str, ScoredColumn],
    candidate_id: str,
) -> str:
    if candidate_id in table_scores:
        table = table_scores[candidate_id].table
        return f"{table.name} {TABLE_DESCRIPTIONS.get(table.name, '')}"
    scored_column = column_scores[candidate_id]
    return (
        f"{scored_column.table.name}.{scored_column.column.name} "
        f"{COLUMN_DESCRIPTIONS.get(scored_column.column.name, '')}"
    )


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        raise EmbeddingProviderError("embedding vectors have incompatible dimensions")
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
