from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.market_data.candidate_validation import ProspectiveOosStatus
from app.market_data.candidate_validation_policy import (
    load_candidate_manifest,
    load_candidate_validation_protocol,
)
from app.market_data.subing_calibration import HorizonEvaluation
from app.market_data.subing_candidate_validation_service import (
    CandidateValidationIdentityError,
    CandidateValidationRequest,
    CandidateValidationSourceError,
    CandidateValidationWindowError,
    SubingCandidateValidationService,
)
from app.market_data.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)


def _horizon(sample_count: int = 1) -> HorizonEvaluation:
    value = Decimal("1") if sample_count else None
    return HorizonEvaluation(
        sample_count=sample_count,
        ema21_sample_count=sample_count,
        median_directional_return_bps=value,
        median_mfe_bps=value,
        median_mae_bps=value,
        ema21_failure_rate=value,
    )


def _result(*, entries: int = 1, horizon_samples: int = 1) -> SubingLifecycleResearchResult:
    return SubingLifecycleResearchResult(
        products=("jm",),
        segment_count=1,
        evaluable_boundary_count=2,
        funnel_counts={
            "DATA_READY": 2,
            "DIRECTION_CONTEXT_ALIGNED": 2,
            "SETUP_ARMED": 1,
            "TRIGGER_OBSERVED": 1,
            "ENTRY_CONFIRMED": entries,
        },
        funnel_count_units={
            "DATA_READY": "boundary_occupancy",
            "DIRECTION_CONTEXT_ALIGNED": "boundary_occupancy",
            "SETUP_ARMED": "boundary_event",
            "TRIGGER_OBSERVED": "boundary_event",
            "ENTRY_CONFIRMED": "boundary_event",
        },
        confirmation_source_counts={
            "FORMAL_V1": entries,
            "MOMENTUM_HOLD": 0,
            "PIVOT_BREAK_HOLD": 0,
            "PIVOT_RETEST_REBREAK": 0,
        },
        v1_v2_overlap_counts={"V1_AND_V2": entries, "V2_ONLY": 0, "V1_ONLY": 0},
        v2_to_v1_lead_bars=(),
        confirmed_trading_day_span_counts={"SAME_DAY": entries, "CROSS_DAY": 0},
        risk_reason_counts={},
        recovery_reason_counts={},
        close_reason_counts={},
        horizon_summary={
            3: _horizon(horizon_samples),
            5: _horizon(horizon_samples),
            8: _horizon(horizon_samples),
        },
    )


class _Runner:
    def __init__(
        self,
        *,
        results: list[SubingLifecycleResearchResult] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.requests: list[LifecycleResearchRequest] = []
        self._results = list(results or [])
        self._failure = failure

    def run(self, request: LifecycleResearchRequest) -> SubingLifecycleResearchResult:
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        return self._results.pop(0) if self._results else _result()


def _service(runner: _Runner) -> SubingCandidateValidationService:
    return SubingCandidateValidationService(
        runner,
        manifest=load_candidate_manifest(),
        protocol=load_candidate_validation_protocol(),
    )


def _request(*, through: date = date(2026, 8, 19)) -> CandidateValidationRequest:
    return CandidateValidationRequest(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        protocol_id="candidate_validation_v1",
        symbol="jm",
        through=through,
    )


def test_request_normalizes_symbol_without_embedding_protocol_semantics() -> None:
    request = CandidateValidationRequest(
        candidate_id="anything-syntactically-valid",
        protocol_id="anything-syntactically-valid",
        symbol=" JM ",
        through=date(2026, 8, 17),
    )

    assert request.symbol == "jm"
    assert request.through == date(2026, 8, 17)


@pytest.mark.parametrize(
    "changes",
    (
        {"candidate_id": ""},
        {"protocol_id": "bad id"},
        {"symbol": "jm2609"},
        {"through": "2026-08-19"},
    ),
)
def test_request_rejects_invalid_syntax(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "candidate_id": "candidate",
        "protocol_id": "protocol",
        "symbol": "jm",
        "through": date(2026, 8, 19),
    }
    values.update(changes)

    with pytest.raises(ValueError, match="CANDIDATE_VALIDATION_REQUEST_INVALID"):
        CandidateValidationRequest(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("candidate_id", "other_candidate"),
        ("candidate_id", "SUBING_LIFECYCLE_V2_CANDIDATE_V1"),
        ("protocol_id", "other_protocol"),
    ),
)
def test_service_rejects_identity_mismatch(field: str, value: str) -> None:
    runner = _Runner()
    request = replace(_request(), **{field: value})

    with pytest.raises(
        CandidateValidationIdentityError,
        match="CANDIDATE_VALIDATION_IDENTITY_MISMATCH",
    ):
        _service(runner).run(request)

    assert runner.requests == []


def test_service_rejects_through_before_frozen_retrospective() -> None:
    runner = _Runner()

    with pytest.raises(
        CandidateValidationWindowError,
        match="CANDIDATE_VALIDATION_WINDOW_INVALID",
    ):
        _service(runner).run(_request(through=date(2026, 8, 17)))

    assert runner.requests == []


def test_service_emits_exact_retrospective_and_ten_rolling_folds() -> None:
    runner = _Runner()
    report = _service(runner).run(_request())

    assert runner.requests[0] == LifecycleResearchRequest(
        since=date(2023, 1, 1),
        through=date(2026, 8, 18),
        symbol="jm",
    )
    expected_tests = (
        (date(2024, 1, 1), date(2024, 3, 31)),
        (date(2024, 4, 1), date(2024, 6, 30)),
        (date(2024, 7, 1), date(2024, 9, 30)),
        (date(2024, 10, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 3, 31)),
        (date(2025, 4, 1), date(2025, 6, 30)),
        (date(2025, 7, 1), date(2025, 9, 30)),
        (date(2025, 10, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 3, 31)),
        (date(2026, 4, 1), date(2026, 6, 30)),
    )
    assert len(report.rolling_folds) == 10
    assert tuple(fold.fold_id for fold in report.rolling_folds) == tuple(
        f"fold_{index:02d}" for index in range(1, 11)
    )
    assert len(runner.requests) == 21
    for index, (test_since, test_through) in enumerate(expected_tests):
        reference_request = runner.requests[1 + index * 2]
        test_request = runner.requests[2 + index * 2]
        assert reference_request == LifecycleResearchRequest(
            since=date(test_since.year - 1, test_since.month, 1),
            through=test_since.replace(day=1) - timedelta(days=1),
            symbol="jm",
        )
        assert test_request == LifecycleResearchRequest(
            since=test_since,
            through=test_through,
            symbol="jm",
        )


@pytest.mark.parametrize("through", (date(2026, 8, 18), date(2026, 8, 19)))
def test_pre_prospective_through_is_pending_without_source_call(through: date) -> None:
    runner = _Runner()
    report = _service(runner).run(_request(through=through))

    assert report.prospective_oos.status is ProspectiveOosStatus.PENDING
    assert report.prospective_oos.result is None
    assert report.prospective_oos.through == through
    assert report.quality_flags == ("PROSPECTIVE_OOS_PENDING",)
    assert len(runner.requests) == 21


def test_first_prospective_day_emits_exact_bounded_source_request() -> None:
    runner = _Runner()
    report = _service(runner).run(_request(through=date(2026, 8, 20)))

    assert report.prospective_oos.status is ProspectiveOosStatus.EVALUATED
    assert runner.requests[-1] == LifecycleResearchRequest(
        since=date(2026, 8, 20),
        through=date(2026, 8, 20),
        symbol="jm",
    )
    assert len(runner.requests) == 22


def test_quality_flags_are_factual_and_threshold_free() -> None:
    results = [_result(), *[_result() for _ in range(20)]]
    results[2] = _result(entries=0)
    results[4] = _result(horizon_samples=0)
    report = _service(_Runner(results=results)).run(_request())

    assert report.quality_flags == (
        "PROSPECTIVE_OOS_PENDING",
        "ROLLING_FOLD_WITHOUT_ENTRY",
        "HORIZON_WITHOUT_SAMPLE",
    )


def test_horizon_quality_flag_also_covers_retrospective() -> None:
    results = [_result(horizon_samples=0), *[_result() for _ in range(20)]]
    report = _service(_Runner(results=results)).run(_request())

    assert report.quality_flags == (
        "PROSPECTIVE_OOS_PENDING",
        "HORIZON_WITHOUT_SAMPLE",
    )


def test_source_failure_is_wrapped_and_never_returns_partial_report() -> None:
    runner = _Runner(failure=ValueError("CATALOG_SOURCE_FAILED"))

    with pytest.raises(
        CandidateValidationSourceError,
        match="CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE",
    ) as raised:
        _service(runner).run(_request())

    assert isinstance(raised.value.__cause__, ValueError)
    assert len(runner.requests) == 1
