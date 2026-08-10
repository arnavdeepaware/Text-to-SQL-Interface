from __future__ import annotations

from typing import cast

from pytest import raises

from app.core.config import Settings
from app.domain.confidence import (
    ConfidenceComponent,
    ConfidenceSummary,
    ValidationSignal,
    ValidationSignalStatus,
)
from app.services.confidence_aggregation import (
    ConfidenceScoringRequest,
    ConfidenceScoringService,
)


def test_confidence_score_is_deterministic_for_fixed_signals() -> None:
    service = ConfidenceScoringService(Settings(environment="test"))
    request = ConfidenceScoringRequest(
        validation_signals=(
            signal("schema_coverage_passed", "passed", 1.0),
            signal("generated_metadata_matches_ast", "passed", 1.0),
            signal("negative_count_passed", "passed", 1.0),
            signal("percentage_bounds_not_applicable", "not_applicable", 0.0),
            signal("date_range_not_applicable", "not_applicable", 0.0),
            signal("null_heavy_passed", "passed", 1.0),
            signal("duplicate_amplification_not_applicable", "not_applicable", 0.0),
            signal("empty_result_passed", "passed", 1.0),
            signal("aggregation_shape_not_applicable", "not_applicable", 0.0),
            signal("semantic_alignment_passed", "passed", 0.95),
            signal("multi_query_result_agreement", "passed", 1.0),
        ),
        model_confidence=0.99,
    )

    first = service.score(request)
    second = service.score(request)

    assert first == second
    assert first.score == 0.9923
    assert first.confidence_band == "high"
    assert first.status == "passed"
    assert first.warnings == ()
    assert "all applicable checks passed" in first.rationale


def test_failed_critical_signal_blocks_confidence() -> None:
    summary = ConfidenceScoringService(Settings(environment="test")).score(
        ConfidenceScoringRequest(
            validation_signals=(
                signal("schema_coverage_passed", "passed", 1.0),
                signal("generated_metadata_matches_ast", "passed", 1.0),
                signal("negative_count_detected", "failed", 0.0),
                signal("semantic_alignment_passed", "passed", 0.9),
            ),
            model_confidence=1.0,
        )
    )

    assert summary.status == "failed"
    assert summary.confidence_band == "blocked"
    assert summary.score is not None and summary.score < 0.85
    assert any("result sanity failed" in warning for warning in summary.warnings)


def test_unavailable_critical_signal_lowers_confidence_without_failed_status() -> None:
    summary = ConfidenceScoringService(Settings(environment="test")).score(
        ConfidenceScoringRequest(
            validation_signals=(
                signal("schema_coverage_unavailable", "unavailable", 0.0),
                signal("generated_metadata_unavailable", "unavailable", 0.0),
                signal("negative_count_passed", "passed", 1.0),
                signal("empty_result_passed", "passed", 1.0),
            ),
            model_confidence=0.8,
        )
    )

    assert summary.status == "unavailable"
    assert summary.confidence_band == "medium"
    assert summary.score == 0.8
    assert any("schema coverage was unavailable" in warning for warning in summary.warnings)


def test_missing_critical_signal_is_penalized_without_calling_it_failed() -> None:
    summary = ConfidenceScoringService(Settings(environment="test")).score(
        ConfidenceScoringRequest(
            validation_signals=(
                signal("schema_coverage_passed", "passed", 1.0),
                signal("generated_metadata_matches_ast", "passed", 1.0),
                signal("semantic_alignment_passed", "passed", 0.9),
            ),
            model_confidence=0.8,
        )
    )

    result_component = component(summary, "result_sanity")
    assert result_component.status == "unavailable"
    assert result_component.score == 0.35
    assert summary.status == "unavailable"
    assert summary.score == 0.8183


def test_optional_not_applicable_multi_query_is_omitted_from_denominator() -> None:
    summary = ConfidenceScoringService(Settings(environment="test")).score(
        ConfidenceScoringRequest(
            validation_signals=(
                signal("schema_coverage_passed", "passed", 1.0),
                signal("generated_metadata_matches_ast", "passed", 1.0),
                signal("negative_count_passed", "passed", 1.0),
                signal("empty_result_passed", "passed", 1.0),
                signal("multi_query_not_applicable_simple_lookup", "not_applicable", 0.0),
            ),
            model_confidence=0.8,
        )
    )

    multi = component(summary, "multi_query_agreement")
    assert multi.status == "not_applicable"
    assert multi.weight == 0.0
    assert summary.score == 0.994


def test_model_reported_confidence_cannot_dominate_final_score() -> None:
    high_model = ConfidenceScoringService(
        Settings(
            environment="test",
            confidence_weight_model_reported=0.05,
        )
    ).score(
        ConfidenceScoringRequest(
            validation_signals=(
                signal("schema_coverage_gap", "warning", 0.5),
                signal("negative_count_detected", "failed", 0.0),
                signal("semantic_alignment_mismatch", "failed", 0.0),
            ),
            model_confidence=1.0,
        )
    )

    assert high_model.confidence_band == "blocked"
    assert high_model.status == "failed"
    assert component(high_model, "model_reported_confidence").weight == 0.05


def test_all_not_applicable_signals_return_not_applicable_summary() -> None:
    summary = ConfidenceScoringService(Settings(environment="test")).score(
        ConfidenceScoringRequest(
            validation_signals=(
                signal("deterministic_validation_disabled", "not_applicable", 0.0),
            ),
            model_confidence=0.9,
        )
    )

    assert summary.status == "not_applicable"
    assert summary.score is None
    assert summary.confidence_band == "not_applicable"
    assert summary.components == ()


def test_confidence_threshold_configuration_is_validated() -> None:
    with raises(ValueError, match="confidence thresholds"):
        Settings(
            environment="test",
            confidence_high_threshold=0.5,
            confidence_medium_threshold=0.7,
        )


def test_model_reported_weight_has_hard_upper_bound() -> None:
    with raises(ValueError):
        Settings(environment="test", confidence_weight_model_reported=0.5)


def signal(code: str, status: str, score: float) -> ValidationSignal:
    return ValidationSignal(
        code=code,
        status=cast(ValidationSignalStatus, status),
        score=score,
        explanation=f"{code} explanation",
    )


def component(summary: ConfidenceSummary, name: str) -> ConfidenceComponent:
    for item in summary.components:
        if item.name == name:
            return item
    raise AssertionError(f"missing component {name}")
