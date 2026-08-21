from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.research.common import candidate_validation_schedule as shared_schedule
from app.research.n_structure.n_candidate_validation import NProspectiveOosStatus
from app.research.n_structure.n_candidate_validation_policy import (
    load_n_candidate_manifest,
    load_n_candidate_validation_protocol,
)
from app.research.n_structure.n_candidate_validation_service import (
    CandidateValidationIdentityError,
    CandidateValidationRequest,
    CandidateValidationSourceError,
    CandidateValidationWindowError,
    NStructureCandidateValidationService,
)
from app.research.n_structure.n_structure_research_service import (
    NStructureResearchRequest,
    NStructureResearchResult,
)
from app.market_data.price_outcome import PriceHorizonEvaluation


def _horizon(sample_count: int = 1) -> PriceHorizonEvaluation:
    value = Decimal("1") if sample_count else None
    return PriceHorizonEvaluation(sample_count, value, value, value)


def _result(
    *,
    completed: int = 1,
    horizon_samples: int = 1,
    products: tuple[str, ...] = ("jm",),
) -> NStructureResearchResult:
    return NStructureResearchResult(
        products=products,
        segment_count=1,
        evaluable_bar_count=2,
        confirmed_pivot_count=2,
        ambiguous_outside_reset_count=0,
        incomplete_attempt_replaced_count=0,
        completed_n_counts={"up": completed, "down": 0},
        n_break_counts={"n2_origin_broken": 0, "origin_broken": 0},
        range_band_reentry_count=0,
        structure_established_counts={"bull": 0, "bear": 0, "range": 0},
        structure_break_counts={"bull": 0, "bear": 0},
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
        results: list[NStructureResearchResult] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.requests: list[NStructureResearchRequest] = []
        self._results = list(results or [])
        self._failure = failure

    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult:
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        return self._results.pop(0) if self._results else _result()


def _service(runner: _Runner) -> NStructureCandidateValidationService:
    return NStructureCandidateValidationService(
        runner,
        manifest=load_n_candidate_manifest(),
        protocol=load_n_candidate_validation_protocol(),
    )


def _request(*, through: date = date(2026, 8, 20)) -> CandidateValidationRequest:
    return CandidateValidationRequest(
        candidate_id="n_structure_5m_candidate_v1",
        protocol_id="n_structure_validation_v1",
        symbol="jm",
        through=through,
    )


def test_n_service_reexports_shared_request_and_stable_errors() -> None:
    assert CandidateValidationRequest is shared_schedule.CandidateValidationRequest
    assert (
        CandidateValidationIdentityError
        is shared_schedule.CandidateValidationIdentityError
    )
    assert (
        CandidateValidationWindowError is shared_schedule.CandidateValidationWindowError
    )
    assert (
        CandidateValidationSourceError is shared_schedule.CandidateValidationSourceError
    )


@pytest.mark.parametrize(
    ("candidate_id", "protocol_id"),
    (
        ("n_structure_5m_candidate_v1", "candidate_validation_v1"),
        ("subing_lifecycle_v2_candidate_v1", "n_structure_validation_v1"),
        ("N_STRUCTURE_5M_CANDIDATE_V1", "n_structure_validation_v1"),
    ),
)
def test_n_service_rejects_wrong_or_cross_paired_identity_before_source_call(
    candidate_id: str,
    protocol_id: str,
) -> None:
    runner = _Runner()
    request = replace(
        _request(),
        candidate_id=candidate_id,
        protocol_id=protocol_id,
    )

    with pytest.raises(
        CandidateValidationIdentityError,
        match="CANDIDATE_VALIDATION_IDENTITY_MISMATCH",
    ):
        _service(runner).run(request)

    assert runner.requests == []


def test_n_service_rejects_through_before_frozen_retrospective() -> None:
    runner = _Runner()

    with pytest.raises(
        CandidateValidationWindowError,
        match="CANDIDATE_VALIDATION_WINDOW_INVALID",
    ):
        _service(runner).run(_request(through=date(2026, 8, 18)))

    assert runner.requests == []


def test_n_service_emits_exact_retrospective_and_ten_frozen_rolling_folds() -> None:
    runner = _Runner()
    report = _service(runner).run(_request())

    assert runner.requests[0] == NStructureResearchRequest(
        since=date(2023, 1, 1),
        through=date(2026, 8, 19),
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
        assert runner.requests[1 + index * 2] == NStructureResearchRequest(
            since=date(test_since.year - 1, test_since.month, 1),
            through=test_since - timedelta(days=1),
            symbol="jm",
        )
        assert runner.requests[2 + index * 2] == NStructureResearchRequest(
            since=test_since,
            through=test_through,
            symbol="jm",
        )


@pytest.mark.parametrize("through", (date(2026, 8, 19), date(2026, 8, 20)))
def test_n_pre_prospective_through_is_pending_without_source_call(
    through: date,
) -> None:
    runner = _Runner()

    report = _service(runner).run(_request(through=through))

    assert report.prospective_oos.status is NProspectiveOosStatus.PENDING
    assert report.prospective_oos.first_trading_day == date(2026, 8, 21)
    assert report.prospective_oos.through == through
    assert report.prospective_oos.result is None
    assert len(runner.requests) == 21


@pytest.mark.parametrize("through", (date(2026, 8, 21), date(2026, 8, 25)))
def test_n_prospective_calls_source_only_since_2026_08_21(through: date) -> None:
    runner = _Runner()

    report = _service(runner).run(_request(through=through))

    assert report.prospective_oos.status is NProspectiveOosStatus.EVALUATED
    assert runner.requests[-1] == NStructureResearchRequest(
        since=date(2026, 8, 21),
        through=through,
        symbol="jm",
    )
    assert len(runner.requests) == 22


@pytest.mark.parametrize(
    "through",
    (date(2026, 8, 19), date(2026, 8, 20), date(2026, 8, 21)),
)
def test_n_no_evidence_source_window_contains_embargo_day(through: date) -> None:
    runner = _Runner()

    _service(runner).run(_request(through=through))

    embargo = date(2026, 8, 20)
    assert all(
        not (request.since <= embargo <= request.through) for request in runner.requests
    )


def test_n_quality_flags_are_factual_threshold_free() -> None:
    results = [_result(), *[_result() for _ in range(20)]]
    results[2] = _result(completed=0)
    results[4] = _result(horizon_samples=0)

    report = _service(_Runner(results=results)).run(_request())

    assert report.quality_flags == (
        "PROSPECTIVE_OOS_PENDING",
        "ROLLING_FOLD_WITHOUT_COMPLETED_N",
        "HORIZON_WITHOUT_SAMPLE",
    )


def test_n_source_failure_or_identity_drift_never_returns_partial_report() -> None:
    failing = _Runner(failure=ValueError("CATALOG_SOURCE_FAILED"))
    with pytest.raises(
        CandidateValidationSourceError,
        match="CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE",
    ):
        _service(failing).run(_request())
    assert len(failing.requests) == 1

    wrong_identity = _Runner(results=[_result(products=("ag",))])
    with pytest.raises(
        CandidateValidationSourceError,
        match="CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE",
    ):
        _service(wrong_identity).run(_request())
    assert len(wrong_identity.requests) == 1


def test_n_same_requested_prefix_is_deterministic_despite_later_fake_data() -> None:
    first_runner = _Runner()
    later_runner = _Runner()
    later_runner.observations_after_through = (date(2026, 8, 21),)  # type: ignore[attr-defined]

    first = _service(first_runner).run(_request())
    with_later_data = _service(later_runner).run(_request())

    assert first == with_later_data
    assert first_runner.requests == later_runner.requests
