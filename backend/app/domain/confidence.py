from dataclasses import dataclass, field
from typing import Any, Literal

ValidationSignalStatus = Literal["passed", "warning", "failed", "unavailable", "not_applicable"]
ConfidenceStatus = Literal["passed", "failed", "unavailable", "not_applicable"]
ConfidenceBand = Literal["high", "medium", "low", "blocked", "not_applicable"]


@dataclass(frozen=True)
class ValidationSignal:
    """Explainable deterministic validation signal for a generated query."""

    code: str
    status: ValidationSignalStatus
    score: float
    explanation: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfidenceComponent:
    """Weighted contribution used to calculate the overall confidence score."""

    name: str
    status: ValidationSignalStatus
    score: float
    weight: float
    contribution: float
    explanation: str
    signal_codes: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfidenceSummary:
    """Explainable confidence score for an executed Text-to-SQL answer."""

    status: ConfidenceStatus
    score: float | None
    confidence_band: ConfidenceBand
    rationale: str
    warnings: tuple[str, ...] = ()
    components: tuple[ConfidenceComponent, ...] = ()
    signals: tuple[ValidationSignal, ...] = ()
