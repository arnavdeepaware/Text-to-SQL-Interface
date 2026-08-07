import logging
from collections.abc import Callable
from typing import Any, Literal, Protocol, cast

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from app.api.schema import SchemaCatalogFactory, get_schema_catalog_service
from app.core.config import Settings
from app.core.exceptions import PublicAPIError
from app.core.request_id import request_id
from app.db.lifecycle import get_database_engine
from app.domain.query_execution import QueryExecutionResult
from app.domain.schema_catalog import SchemaCatalog
from app.domain.sql_generation import SQLGenerationDraft, SQLGenerationResult
from app.providers.fake_sql_generation import FakeSQLGenerator
from app.providers.openai_sql_generation import OpenAISQLGenerator
from app.providers.sql_generation import (
    SQLGenerationCredentialsUnavailableError,
    SQLGenerationError,
    SQLGenerationMalformedOutputError,
    SQLGenerationProviderTimeoutError,
    SQLGenerationProviderUnavailableError,
    SQLGenerationRateLimitError,
    SQLGenerator,
)
from app.services.query_draft import (
    ClarificationRequired,
    QueryDraftService,
    normalize_question,
)
from app.services.query_execution import (
    QueryExecutionDatabaseUnavailableError,
    QueryExecutionError,
    QueryExecutionService,
    QueryExecutionTimeoutError,
    QueryPlanInspectionError,
    QueryPlanReferenceMismatchError,
    QueryPlanThresholdExceededError,
    QueryPlanTimeoutError,
)
from app.services.schema_catalog import SchemaCatalogService
from app.services.sql_guardrails import SQLGuardrailValidationError


class SQLGeneratorProvider(Protocol):
    def generate(self, prompt: object) -> SQLGenerationDraft: ...


class QueryExecutor(Protocol):
    def execute(self, sql: str, catalog: SchemaCatalog) -> QueryExecutionResult: ...


SQLGeneratorFactory = Callable[[Settings], SQLGenerator]
QueryExecutorFactory = Callable[[Engine, Settings], QueryExecutor]


class QueryDraftRequest(BaseModel):
    question: str = Field(description="Natural-language question to draft SQL for.")
    refresh_schema: bool = False


class SQLGenerationTelemetryResponse(BaseModel):
    provider_name: str
    model_name: str
    provider_latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    retry_count: int


class SQLDraftMetadataResponse(BaseModel):
    model_confidence: float
    tables_used: list[str]
    columns_used: list[str]
    assumptions: list[str]
    telemetry: SQLGenerationTelemetryResponse


class SQLDraftResponse(BaseModel):
    result_type: Literal["sql_draft"]
    request_id: str
    question: str
    sql: str
    explanation: str
    metadata: SQLDraftMetadataResponse


class ClarificationOptionResponse(BaseModel):
    interpretation: str
    example: str


class ClarificationRequiredResponse(BaseModel):
    result_type: Literal["clarification_required"]
    request_id: str
    question: str
    message: str
    clarification_options: list[ClarificationOptionResponse]


class QueryResultColumnResponse(BaseModel):
    name: str
    type_code: str | None


class QueryPlanSummaryResponse(BaseModel):
    estimated_rows: int
    total_cost: float
    plan_nodes: list[str]
    referenced_relations: list[str]


class QueryExecutionResponse(BaseModel):
    result_type: Literal["query_result"]
    request_id: str
    question: str
    sql: str
    explanation: str
    columns: list[QueryResultColumnResponse]
    rows: list[dict[str, Any]]
    row_count: int
    execution_duration_ms: int
    truncated: bool
    plan: QueryPlanSummaryResponse
    metadata: SQLDraftMetadataResponse


QueryDraftResponse = SQLDraftResponse | ClarificationRequiredResponse
QueryResponse = QueryExecutionResponse | ClarificationRequiredResponse
logger = logging.getLogger(__name__)


def create_query_router(
    settings: Settings,
    schema_catalog_factory: SchemaCatalogFactory = SchemaCatalogService,
    sql_generator_factory: SQLGeneratorFactory | None = None,
    query_executor_factory: QueryExecutorFactory = QueryExecutionService,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["query"])

    @router.post("/query/draft", response_model=QueryDraftResponse)
    async def draft_query(
        payload: QueryDraftRequest,
        request: Request,
    ) -> QueryDraftResponse:
        normalized_question = validate_question(payload.question, settings)
        catalog_service = get_schema_catalog_service(request, settings, schema_catalog_factory)
        catalog = catalog_service.get_schema(refresh=payload.refresh_schema)
        generator = get_sql_generator(request, settings, sql_generator_factory)
        service = QueryDraftService(settings, generator)

        try:
            result = service.draft(normalized_question, catalog)
        except SQLGenerationError as exc:
            logger.warning(
                "Query draft provider error",
                extra={"request_id": request_id(request), "error_code": exc.public_code},
            )
            raise public_error_from_generation_error(exc) from exc
        except SQLGuardrailValidationError as exc:
            logger.warning(
                "Query draft SQL validation failed",
                extra={
                    "request_id": request_id(request),
                    "finding_codes": [finding.code for finding in exc.result.findings],
                },
            )
            raise public_error_from_sql_validation_error(exc) from exc

        current_request_id = request_id(request)
        if result.clarification is not None:
            logger.info(
                "Query draft clarification required",
                extra={"request_id": current_request_id},
            )
            return clarification_response(
                current_request_id,
                normalized_question,
                result.clarification,
            )
        if result.draft is None:
            raise PublicAPIError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "query_draft_missing_result",
                "Query draft generation did not produce a result.",
            )
        logger.info("Query draft generated", extra={"request_id": current_request_id})
        return sql_draft_response(current_request_id, normalized_question, result.draft)

    @router.post("/query", response_model=QueryResponse)
    async def run_query(
        payload: QueryDraftRequest,
        request: Request,
    ) -> QueryResponse:
        normalized_question = validate_question(payload.question, settings)
        catalog_service = get_schema_catalog_service(request, settings, schema_catalog_factory)
        catalog = catalog_service.get_schema(refresh=payload.refresh_schema)
        generator = get_sql_generator(request, settings, sql_generator_factory)
        draft_service = QueryDraftService(settings, generator)

        try:
            result = draft_service.draft(normalized_question, catalog)
        except SQLGenerationError as exc:
            logger.warning(
                "Query execution provider error",
                extra={"request_id": request_id(request), "error_code": exc.public_code},
            )
            raise public_error_from_generation_error(exc) from exc
        except SQLGuardrailValidationError as exc:
            logger.warning(
                "Query execution SQL validation failed",
                extra={
                    "request_id": request_id(request),
                    "finding_codes": [finding.code for finding in exc.result.findings],
                },
            )
            raise public_error_from_sql_validation_error(exc) from exc

        current_request_id = request_id(request)
        if result.clarification is not None:
            logger.info(
                "Query execution clarification required",
                extra={"request_id": current_request_id},
            )
            return clarification_response(
                current_request_id,
                normalized_question,
                result.clarification,
            )
        if result.draft is None:
            raise PublicAPIError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "query_execution_missing_result",
                "Query generation did not produce a result.",
            )
        if result.draft.result.sql is None:
            raise PublicAPIError(
                status.HTTP_502_BAD_GATEWAY,
                "sql_generation_missing_sql",
                "The SQL provider did not return a SQL draft.",
            )

        executor = get_query_executor(request, settings, query_executor_factory)
        try:
            execution = executor.execute(result.draft.result.sql, catalog)
        except SQLGuardrailValidationError as exc:
            logger.warning(
                "Query execution SQL validation failed",
                extra={
                    "request_id": current_request_id,
                    "finding_codes": [finding.code for finding in exc.result.findings],
                },
            )
            raise public_error_from_sql_validation_error(exc) from exc
        except QueryPlanInspectionError as exc:
            logger.warning(
                "Query execution plan blocked",
                extra={
                    "request_id": current_request_id,
                    "error_code": exc.public_code,
                },
            )
            raise public_error_from_query_plan_error(exc) from exc
        except QueryExecutionError as exc:
            logger.warning(
                "Query execution failed",
                extra={
                    "request_id": current_request_id,
                    "error_code": exc.public_code,
                },
            )
            raise public_error_from_query_execution_error(exc) from exc

        logger.info("Query executed", extra={"request_id": current_request_id})
        return query_execution_response(
            current_request_id,
            normalized_question,
            result.draft,
            execution,
        )

    return router


def validate_question(question: str, settings: Settings) -> str:
    normalized = normalize_question(question)
    if not normalized:
        raise PublicAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "empty_question",
            "Question must not be empty.",
        )
    if len(normalized) > settings.query_max_question_chars:
        raise PublicAPIError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "question_too_long",
            f"Question must be at most {settings.query_max_question_chars} characters.",
        )
    return normalized


def get_sql_generator(
    request: Request,
    settings: Settings,
    sql_generator_factory: SQLGeneratorFactory | None,
) -> SQLGenerator:
    cached_generator = getattr(request.app.state, "sql_generator", None)
    if cached_generator is not None:
        return cast(SQLGenerator, cached_generator)

    factory = sql_generator_factory or default_sql_generator_factory
    generator = factory(settings)
    request.app.state.sql_generator = generator
    return generator


def default_sql_generator_factory(settings: Settings) -> SQLGenerator:
    if settings.sql_generation_provider == "fake":
        return FakeSQLGenerator()
    return OpenAISQLGenerator(settings)


def get_query_executor(
    request: Request,
    settings: Settings,
    query_executor_factory: QueryExecutorFactory,
) -> QueryExecutor:
    cached_executor = getattr(request.app.state, "query_executor", None)
    if cached_executor is not None:
        return cast(QueryExecutor, cached_executor)

    executor = query_executor_factory(get_database_engine(request.app), settings)
    request.app.state.query_executor = executor
    return executor


def public_error_from_generation_error(error: SQLGenerationError) -> PublicAPIError:
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    if isinstance(error, SQLGenerationMalformedOutputError):
        status_code = status.HTTP_502_BAD_GATEWAY
    elif isinstance(error, SQLGenerationProviderTimeoutError):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    elif isinstance(error, SQLGenerationRateLimitError):
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(error, SQLGenerationCredentialsUnavailableError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(error, SQLGenerationProviderUnavailableError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return PublicAPIError(status_code, error.public_code, error.public_message)


def public_error_from_sql_validation_error(
    error: SQLGuardrailValidationError,
) -> PublicAPIError:
    return PublicAPIError(
        status.HTTP_502_BAD_GATEWAY,
        error.public_code,
        error.public_message,
    )


def public_error_from_query_plan_error(error: QueryPlanInspectionError) -> PublicAPIError:
    status_code = status.HTTP_502_BAD_GATEWAY
    if isinstance(error, (QueryPlanThresholdExceededError, QueryPlanReferenceMismatchError)):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif isinstance(error, QueryPlanTimeoutError):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    return PublicAPIError(status_code, error.public_code, error.public_message)


def public_error_from_query_execution_error(error: QueryExecutionError) -> PublicAPIError:
    status_code = status.HTTP_502_BAD_GATEWAY
    if isinstance(error, QueryExecutionTimeoutError):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    elif isinstance(error, QueryExecutionDatabaseUnavailableError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return PublicAPIError(status_code, error.public_code, error.public_message)


def sql_draft_response(
    current_request_id: str,
    question: str,
    draft: SQLGenerationDraft,
) -> SQLDraftResponse:
    result: SQLGenerationResult = draft.result
    if result.sql is None:
        raise PublicAPIError(
            status.HTTP_502_BAD_GATEWAY,
            "sql_generation_missing_sql",
            "The SQL provider did not return a SQL draft.",
        )
    return SQLDraftResponse(
        result_type="sql_draft",
        request_id=current_request_id,
        question=question,
        sql=result.sql,
        explanation=result.explanation,
        metadata=SQLDraftMetadataResponse(
            model_confidence=result.model_confidence,
            tables_used=result.tables_used,
            columns_used=result.columns_used,
            assumptions=result.assumptions,
            telemetry=SQLGenerationTelemetryResponse(
                provider_name=draft.telemetry.provider_name,
                model_name=draft.telemetry.model_name,
                provider_latency_ms=draft.telemetry.provider_latency_ms,
                input_tokens=draft.telemetry.input_tokens,
                output_tokens=draft.telemetry.output_tokens,
                total_tokens=draft.telemetry.total_tokens,
                retry_count=draft.telemetry.retry_count,
            ),
        ),
    )


def query_execution_response(
    current_request_id: str,
    question: str,
    draft: SQLGenerationDraft,
    execution: QueryExecutionResult,
) -> QueryExecutionResponse:
    draft_response = sql_draft_response(current_request_id, question, draft)
    return QueryExecutionResponse(
        result_type="query_result",
        request_id=current_request_id,
        question=question,
        sql=draft_response.sql,
        explanation=draft_response.explanation,
        columns=[
            QueryResultColumnResponse(name=column.name, type_code=column.type_code)
            for column in execution.columns
        ],
        rows=list(execution.rows),
        row_count=execution.row_count,
        execution_duration_ms=execution.execution_duration_ms,
        truncated=execution.truncated,
        plan=QueryPlanSummaryResponse(
            estimated_rows=execution.plan.estimated_rows,
            total_cost=execution.plan.total_cost,
            plan_nodes=list(execution.plan.plan_nodes),
            referenced_relations=list(execution.plan.referenced_relations),
        ),
        metadata=draft_response.metadata,
    )


def clarification_response(
    current_request_id: str,
    question: str,
    clarification: ClarificationRequired,
) -> ClarificationRequiredResponse:
    return ClarificationRequiredResponse(
        result_type="clarification_required",
        request_id=current_request_id,
        question=question,
        message=clarification.message,
        clarification_options=[
            ClarificationOptionResponse(
                interpretation=option.interpretation,
                example=option.example,
            )
            for option in clarification.options
        ],
    )
