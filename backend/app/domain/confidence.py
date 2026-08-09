from dataclasses import dataclass, field
from typing import Any, Literal

ValidationSignalStatus = Literal["passed", "warning", "failed", "unavailable", "not_applicable"]


@dataclass(frozen=True)
class ValidationSignal:
    """Explainable deterministic validation signal for a generated query."""

    code: str
    status: ValidationSignalStatus
    score: float
    explanation: str
    evidence: dict[str, Any] = field(default_factory=dict)
