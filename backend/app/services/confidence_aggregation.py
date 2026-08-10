from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.core.config import Settings, confidence_weights
from app.domain.confidence import (
    ConfidenceBand,
    ConfidenceComponent,
    ConfidenceStatus,
    ConfidenceSummary,
    ValidationSignal,
    ValidationSignalStatus,
)


@dataclass(frozen=True)
class ConfidenceScoringRequest:
    """Inputs for deterministic confidence aggregation after safe query execution."""

    validation_signals: tuple[ValidationSignal, ...]
    model_confidence: float
    sql_executed: bool = True
    guardrail_approved: bool = True


class ConfidenceScoringService:
    """Calculate an explainable confidence score from validation signals."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def score(self, request: ConfidenceScoringRequest) -> ConfidenceSummary:
        if request.validation_signals and all(
            signal.status == "not_applicable" for signal in request.validation_signals
        ):
            return ConfidenceSummary(
                status="not_applicable",
                score=None,
                confidence_band="not_applicable",
                rationale="Confidence scoring was not applicable for this response.",
                warnings=tuple(signal.explanation for signal in request.validation_signals),
                components=(),
                signals=request.validation_signals,
            )

        components = tuple(self._components(request))
        applicable_components = tuple(
            component for component in components if component.weight > 0
        )
        denominator = sum(component.weight for component in applicable_components)
        if denominator <= 0:
            return ConfidenceSummary(
                status="unavailable",
                score=None,
                confidence_band="not_applicable",
                rationale="Confidence scoring has no positive configured weights.",
                warnings=("Confidence scoring weights are unavailable.",),
                components=components,
                signals=request.validation_signals,
            )

        score = round(
            sum(component.contribution for component in applicable_components) / denominator,
            4,
        )
        band = confidence_band(score, self._settings)
        hard_blockers = tuple(
            component
            for component in applicable_components
            if component.status == "failed" and component.name in BLOCKING_COMPONENTS
        )
        if hard_blockers:
            band = "blocked"

        status = confidence_status(band, components)
        warnings = confidence_warnings(components)
        return ConfidenceSummary(
            status=status,
            score=score,
            confidence_band=band,
            rationale=rationale(score, band, components),
            warnings=warnings,
            components=components,
            signals=request.validation_signals,
        )

    def _components(
        self,
        request: ConfidenceScoringRequest,
    ) -> Iterable[ConfidenceComponent]:
        weights = confidence_weights(self._settings)
        yield implicit_component(
            "sql_syntax_validity",
            request.sql_executed,
            weights["sql_syntax_validity"],
            "SQL parsed and executed through the approved query path.",
            "SQL did not reach successful execution.",
        )
        yield implicit_component(
            "guardrail_approval",
            request.guardrail_approved,
            weights["guardrail_approval"],
            "Generated SQL passed static guardrails and EXPLAIN inspection.",
            "Generated SQL did not pass guardrail approval.",
        )
        yield grouped_component(
            "schema_coverage",
            schema_signals(request.validation_signals),
            weights["schema_coverage"],
            self._settings,
            critical=True,
            missing_explanation="Schema coverage signals were unavailable.",
        )
        yield grouped_component(
            "result_sanity",
            result_sanity_signals(request.validation_signals),
            weights["result_sanity"],
            self._settings,
            critical=True,
            missing_explanation="Result sanity signals were unavailable.",
        )
        yield grouped_component(
            "semantic_alignment",
            semantic_signals(request.validation_signals),
            weights["semantic_alignment"],
            self._settings,
            critical=False,
            missing_explanation="Question back-translation alignment was not run.",
        )
        yield grouped_component(
            "multi_query_agreement",
            multi_query_signals(request.validation_signals),
            weights["multi_query_agreement"],
            self._settings,
            critical=False,
            missing_explanation="Multi-query agreement was not run.",
        )
        model_score = bounded_score(request.model_confidence)
        yield ConfidenceComponent(
            name="model_reported_confidence",
            status="passed",
            score=model_score,
            weight=weights["model_reported_confidence"],
            contribution=model_score * weights["model_reported_confidence"],
            explanation=(
                "Provider-reported confidence is included as a small bounded auxiliary signal."
            ),
            evidence={"configured_max_weight": 0.05},
        )


def implicit_component(
    name: str,
    passed: bool,
    weight: float,
    passed_explanation: str,
    failed_explanation: str,
) -> ConfidenceComponent:
    status: ValidationSignalStatus = "passed" if passed else "failed"
    score = 1.0 if passed else 0.0
    return ConfidenceComponent(
        name=name,
        status=status,
        score=score,
        weight=weight,
        contribution=score * weight,
        explanation=passed_explanation if passed else failed_explanation,
    )


def grouped_component(
    name: str,
    signals: tuple[ValidationSignal, ...],
    weight: float,
    settings: Settings,
    critical: bool,
    missing_explanation: str,
) -> ConfidenceComponent:
    if not signals:
        status: ValidationSignalStatus = "unavailable" if critical else "not_applicable"
        score = settings.confidence_unavailable_score if critical else 0.0
        component_weight = weight if critical else 0.0
        return ConfidenceComponent(
            name=name,
            status=status,
            score=score,
            weight=component_weight,
            contribution=score * component_weight,
            explanation=missing_explanation,
            evidence={"missing": True, "critical": critical},
        )

    if all(signal.status == "not_applicable" for signal in signals):
        if critical:
            score = settings.confidence_not_applicable_score
            return ConfidenceComponent(
                name=name,
                status="not_applicable",
                score=score,
                weight=weight,
                contribution=score * weight,
                explanation=missing_explanation,
                signal_codes=tuple(signal.code for signal in signals),
                evidence={"critical": True},
            )
        return ConfidenceComponent(
            name=name,
            status="not_applicable",
            score=0.0,
            weight=0.0,
            contribution=0.0,
            explanation=missing_explanation,
            signal_codes=tuple(signal.code for signal in signals),
            evidence={"critical": False},
        )

    status = grouped_status(signals)
    score = grouped_score(signals, settings)
    return ConfidenceComponent(
        name=name,
        status=status,
        score=score,
        weight=weight,
        contribution=score * weight,
        explanation=component_explanation(name, status, signals),
        signal_codes=tuple(signal.code for signal in signals),
        evidence={
            "signal_statuses": {signal.code: signal.status for signal in signals},
            "signal_scores": {signal.code: signal.score for signal in signals},
        },
    )


def grouped_status(signals: tuple[ValidationSignal, ...]) -> ValidationSignalStatus:
    statuses = {signal.status for signal in signals}
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    if "unavailable" in statuses:
        return "unavailable"
    if statuses == {"not_applicable"}:
        return "not_applicable"
    return "passed"


def grouped_score(signals: tuple[ValidationSignal, ...], settings: Settings) -> float:
    scores: list[float] = []
    for signal in signals:
        if signal.status == "passed":
            scores.append(bounded_score(signal.score))
        elif signal.status == "warning":
            scores.append(min(bounded_score(signal.score), 0.75))
        elif signal.status == "failed":
            scores.append(0.0)
        elif signal.status == "unavailable":
            scores.append(settings.confidence_unavailable_score)
    if not scores:
        return settings.confidence_not_applicable_score
    return round(sum(scores) / len(scores), 4)


def component_explanation(
    name: str,
    status: ValidationSignalStatus,
    signals: tuple[ValidationSignal, ...],
) -> str:
    if status == "passed":
        return f"{display_name(name)} passed all applicable checks."
    if status == "failed":
        failed = ", ".join(signal.code for signal in signals if signal.status == "failed")
        return f"{display_name(name)} failed: {failed}."
    if status == "warning":
        warned = ", ".join(signal.code for signal in signals if signal.status == "warning")
        return f"{display_name(name)} produced warnings: {warned}."
    if status == "unavailable":
        unavailable = ", ".join(
            signal.code for signal in signals if signal.status == "unavailable"
        )
        return f"{display_name(name)} was unavailable: {unavailable}."
    return f"{display_name(name)} was not applicable."


def confidence_band(score: float, settings: Settings) -> ConfidenceBand:
    if score >= settings.confidence_high_threshold:
        return "high"
    if score >= settings.confidence_medium_threshold:
        return "medium"
    if score >= settings.confidence_low_threshold:
        return "low"
    return "blocked"


def confidence_status(
    band: ConfidenceBand,
    components: tuple[ConfidenceComponent, ...],
) -> ConfidenceStatus:
    if band == "blocked":
        return "failed"
    if all(component.status == "not_applicable" for component in components):
        return "not_applicable"
    if any(component.status == "unavailable" for component in components):
        return "unavailable"
    return "passed"


def confidence_warnings(components: tuple[ConfidenceComponent, ...]) -> tuple[str, ...]:
    return tuple(
        component.explanation
        for component in components
        if component.status in {"warning", "failed", "unavailable"}
    )


def rationale(
    score: float,
    band: ConfidenceBand,
    components: tuple[ConfidenceComponent, ...],
) -> str:
    failed = tuple(component.name for component in components if component.status == "failed")
    unavailable = tuple(
        component.name for component in components if component.status == "unavailable"
    )
    warning = tuple(component.name for component in components if component.status == "warning")
    if band == "blocked":
        if failed:
            return (
                f"Confidence is blocked at {score:.2f} because critical components failed: "
                f"{', '.join(display_name(name) for name in failed)}."
            )
        return f"Confidence is blocked at {score:.2f} because the weighted score is too low."
    if failed:
        return (
            f"Confidence is {band} at {score:.2f}; failed components prevent stronger confidence: "
            f"{', '.join(display_name(name) for name in failed)}."
        )
    if unavailable:
        return (
            f"Confidence is {band} at {score:.2f}; unavailable evidence lowers certainty: "
            f"{', '.join(display_name(name) for name in unavailable)}."
        )
    if warning:
        return (
            f"Confidence is {band} at {score:.2f}; warnings remain in "
            f"{', '.join(display_name(name) for name in warning)}."
        )
    return f"Confidence is {band} at {score:.2f}; all applicable checks passed."


def schema_signals(signals: tuple[ValidationSignal, ...]) -> tuple[ValidationSignal, ...]:
    return tuple(
        signal
        for signal in signals
        if signal.code.startswith("schema_coverage")
        or signal.code.startswith("generated_metadata")
    )


def result_sanity_signals(signals: tuple[ValidationSignal, ...]) -> tuple[ValidationSignal, ...]:
    return tuple(
        signal
        for signal in signals
        if signal.code.startswith(RESULT_SANITY_PREFIXES)
        or signal.code in RESULT_SANITY_CODES
    )


def semantic_signals(signals: tuple[ValidationSignal, ...]) -> tuple[ValidationSignal, ...]:
    return tuple(
        signal
        for signal in signals
        if signal.code.startswith("semantic_alignment")
        or signal.code.startswith("back_translation")
    )


def multi_query_signals(signals: tuple[ValidationSignal, ...]) -> tuple[ValidationSignal, ...]:
    return tuple(signal for signal in signals if signal.code.startswith("multi_query"))


def bounded_score(score: float) -> float:
    return max(0.0, min(1.0, score))


def display_name(name: str) -> str:
    return name.replace("_", " ")


RESULT_SANITY_PREFIXES = (
    "negative_count",
    "percentage_",
    "date_",
    "null_heavy",
    "duplicate_amplification",
    "empty_result",
    "aggregation_shape",
)
RESULT_SANITY_CODES = frozenset(
    {
        "possible_duplicate_amplification",
        "unexpected_empty_result",
    }
)
BLOCKING_COMPONENTS = frozenset(
    {
        "sql_syntax_validity",
        "guardrail_approval",
        "schema_coverage",
        "result_sanity",
        "semantic_alignment",
        "multi_query_agreement",
    }
)
