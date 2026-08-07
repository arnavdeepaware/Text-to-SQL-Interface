import logging
from collections.abc import Callable
from typing import Literal, Protocol, cast

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from app.api.schema import SchemaCatalogFactory, get_schema_catalog_service
from app.core.config import Settings
from app.core.exceptions import PublicAPIError
from app.core.request_id import request_id
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
from app.services.schema_catalog import SchemaCatalogService
from app.services.sql_guardrails import SQLGuardrailValidationError


class SQLGeneratorProvider(Protocol):
    def generate(self, prompt: object) -> SQLGenerationDraft: ...


SQLGeneratorFactory = Callable[[Settings], SQLGenerator]


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


QueryDraftResponse = SQLDraftResponse | ClarificationRequiredResponse
logger = logging.getLogger(__name__)


def create_query_router(
    settings: Settings,
    schema_catalog_factory: SchemaCatalogFactory = SchemaCatalogService,
    sql_generator_factory: SQLGeneratorFactory | None = None,
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
