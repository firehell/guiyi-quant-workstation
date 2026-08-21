from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.research.jdj.jdj_candidate_validation import JdjProspectiveOosStatus
from app.research.jdj.jdj_candidate_validation_policy import (
    load_jdj_candidate_manifest,
    load_jdj_candidate_validation_protocol,
)
from app.research.jdj.jdj_candidate_validation_service import (
    CandidateValidationIdentityError,
    CandidateValidationRequest,
    CandidateValidationSourceError,
    CandidateValidationWindowError,
    JdjCandidateValidationService,
)
from app.research.jdj.jdj_context import JdjContextError
from app.research.jdj.jdj_research import (
    JdjResearchRequest,
    JdjResearchResult,
    JdjSourceUnavailableError,
)
from app.market_data.price_outcome import PriceHorizonEvaluation


_CANDIDATES = (
    (
        "jdj_trend_follow_1m_candidate_v1",
        "jdj_trend_follow_triggered",
    ),
    (
        "jdj_trend_reentry_6_1m_candidate_v1",
        "jdj_trend_reentry_6_triggered",
    ),
    (
        "jdj_key_level_breakout_1m_candidate_v1",
        "jdj_key_level_breakout_triggered",
    ),
)
_PROTOCOL = "jdj_candidate_validation_v1"


def _horizon(sample_count: int = 1) -> PriceHorizonEvaluation:
    value = Decimal("1") if sample_count else None
    return PriceHorizonEvaluation(sample_count, value, value, value)


def _result(
    candidate_id: str,
    source_event_kind: str,
    *,
    horizon_samples: int = 1,
    products: tuple[str, ...] = ("jm",),
) -> JdjResearchResult:
    return JdjResearchResult(
        candidate_id=candidate_id,
        source_event_kind=source_event_kind,
        products=products,
        segment_count=1,
        evaluable_bar_count=100,
        trigger_count_long=0,
        trigger_count_short=0,
        horizon_summary={
            3: _horizon(horizon_samples),
            5: _horizon(horizon_samples),
            8: _horizon(horizon_samples),
            20: _horizon(horizon_samples),
        },
        events=(),
    )


class _Runner:
    def __init__(
        self,
        candidate_id: str,
        source_event_kind: str,
        *,
        results: list[JdjResearchResult] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.candidate_id = candidate_id
        self.source_event_kind = source_event_kind
        self.requests: list[JdjResearchRequest] = []
        self._results = list(results or [])
        self._failure = failure

    def run(self, request: JdjResearchRequest) -> JdjResearchResult:
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        if self._results:
            return self._results.pop(0)
        return _result(self.candidate_id, self.source_event_kind)


def _service(
    runner: _Runner,
    *,
    candidate_id: str,
) -> JdjCandidateValidationService:
    return JdjCandidateValidationService(
        runner,
        manifest=load_jdj_candidate_manifest(candidate_id),
        protocol=load_jdj_candidate_validation_protocol(),
    )


def _request(
    candidate_id: str,
    *,
    through: date = date(2026, 8, 21),
) -> CandidateValidationRequest:
    return CandidateValidationRequest(
        candidate_id=candidate_id,
        protocol_id=_PROTOCOL,
        symbol="jm",
        through=through,
    )




@pytest.mark.parametrize(("candidate_id", "source_event_kind"), _CANDIDATES)
def test_baseline_calls_exact_retrospective_and_ten_shared_folds(
    candidate_id: str,
    source_event_kind: str,
) -> None:
    runner = _Runner(candidate_id, source_event_kind)

    report = _service(runner, candidate_id=candidate_id).run(
        _request(candidate_id)
    )

    assert runner.requests[0] == JdjResearchRequest(
        since=date(2023, 1, 1),
        through=date(2026, 8, 20),
        symbol="jm",
        candidate_id=candidate_id,
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
    assert len(runner.requests) == 21
    assert tuple(fold.fold_id for fold in report.rolling_folds) == tuple(
        f"fold_{index:02d}" for index in range(1, 11)
    )
    for index, (test_since, test_through) in enumerate(expected_tests):
        assert runner.requests[1 + index * 2] == JdjResearchRequest(
            since=date(test_since.year - 1, test_since.month, 1),
            through=test_since - timedelta(days=1),
            symbol="jm",
            candidate_id=candidate_id,
        )
        assert runner.requests[2 + index * 2] == JdjResearchRequest(
            since=test_since,
            through=test_through,
            symbol="jm",
            candidate_id=candidate_id,
        )
    assert report.candidate_id == candidate_id
    assert report.source_event_kind == source_event_kind
    assert report.prospective_oos.status is JdjProspectiveOosStatus.PENDING
    assert report.prospective_oos.first_trading_day == date(2026, 8, 24)
    assert report.prospective_oos.through == date(2026, 8, 21)
    assert report.prospective_oos.result is None


def test_wrong_candidate_or_protocol_pair_fails_before_source_call() -> None:
    candidate_id, source_event_kind = _CANDIDATES[0]
    runner = _Runner(candidate_id, source_event_kind)
    service = _service(runner, candidate_id=candidate_id)

    for request in (
        replace(_request(candidate_id), candidate_id=_CANDIDATES[1][0]),
        replace(_request(candidate_id), protocol_id="candidate_validation_v1"),
    ):
        with pytest.raises(
            CandidateValidationIdentityError,
            match="^CANDIDATE_VALIDATION_IDENTITY_MISMATCH$",
        ):
            service.run(request)

    assert runner.requests == []


def test_non_anchor_symbol_fails_before_source_call() -> None:
    candidate_id, source_event_kind = _CANDIDATES[0]
    runner = _Runner(candidate_id, source_event_kind)

    with pytest.raises(
        CandidateValidationIdentityError,
        match="^CANDIDATE_VALIDATION_IDENTITY_MISMATCH$",
    ):
        _service(runner, candidate_id=candidate_id).run(
            replace(_request(candidate_id), symbol="ag")
        )

    assert runner.requests == []


def test_request_before_baseline_freeze_fails_before_source_call() -> None:
    candidate_id, source_event_kind = _CANDIDATES[0]
    runner = _Runner(candidate_id, source_event_kind)

    with pytest.raises(
        CandidateValidationWindowError,
        match="^CANDIDATE_VALIDATION_WINDOW_INVALID$",
    ):
        _service(runner, candidate_id=candidate_id).run(
            _request(candidate_id, through=date(2026, 8, 20))
        )

    assert runner.requests == []


def test_prospective_starts_only_at_frozen_first_trading_day() -> None:
    candidate_id, source_event_kind = _CANDIDATES[0]
    runner = _Runner(candidate_id, source_event_kind)

    report = _service(runner, candidate_id=candidate_id).run(
        _request(candidate_id, through=date(2026, 8, 25))
    )

    assert len(runner.requests) == 22
    assert runner.requests[-1] == JdjResearchRequest(
        since=date(2026, 8, 24),
        through=date(2026, 8, 25),
        symbol="jm",
        candidate_id=candidate_id,
    )
    assert report.prospective_oos.status is JdjProspectiveOosStatus.EVALUATED
    assert report.prospective_oos.first_trading_day == date(2026, 8, 24)
    assert report.prospective_oos.result is not None
    assert report.prospective_oos.result.since == date(2026, 8, 24)
    assert report.prospective_oos.result.through == date(2026, 8, 25)


@pytest.mark.parametrize(
    "source_error",
    (JdjSourceUnavailableError(), JdjContextError()),
)
def test_only_typed_jdj_source_errors_convert_to_shared_source_error(
    source_error: Exception,
) -> None:
    candidate_id, source_event_kind = _CANDIDATES[0]
    runner = _Runner(
        candidate_id,
        source_event_kind,
        failure=source_error,
    )

    with pytest.raises(
        CandidateValidationSourceError,
        match="^CANDIDATE_VALIDATION_SOURCE_UNAVAILABLE$",
    ) as captured:
        _service(runner, candidate_id=candidate_id).run(_request(candidate_id))

    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    "programming_error",
    (
        TypeError("bug"),
        AssertionError("bug"),
        ValueError("bug"),
        RuntimeError("bug"),
        KeyError("bug"),
    ),
)
def test_programming_source_errors_propagate_unchanged(
    programming_error: Exception,
) -> None:
    candidate_id, source_event_kind = _CANDIDATES[0]
    runner = _Runner(
        candidate_id,
        source_event_kind,
        failure=programming_error,
    )

    with pytest.raises(type(programming_error)) as captured:
        _service(runner, candidate_id=candidate_id).run(_request(candidate_id))

    assert captured.value is programming_error


def test_result_identity_drift_propagates_as_programming_failure() -> None:
    candidate_id, source_event_kind = _CANDIDATES[0]
    wrong_candidate, wrong_source_kind = _CANDIDATES[1]
    runner = _Runner(
        candidate_id,
        source_event_kind,
        results=[_result(wrong_candidate, wrong_source_kind)],
    )

    with pytest.raises(ValueError, match="JDJ research result identity is invalid"):
        _service(runner, candidate_id=candidate_id).run(_request(candidate_id))


def test_quality_flags_are_structural_and_threshold_free() -> None:
    candidate_id, source_event_kind = _CANDIDATES[0]
    results = [
        _result(candidate_id, source_event_kind),
        *[
            _result(candidate_id, source_event_kind)
            for _ in range(20)
        ],
    ]
    results[4] = _result(
        candidate_id,
        source_event_kind,
        horizon_samples=0,
    )

    report = _service(
        _Runner(candidate_id, source_event_kind, results=results),
        candidate_id=candidate_id,
    ).run(_request(candidate_id))

    assert report.quality_flags == (
        "PROSPECTIVE_OOS_PENDING",
        "ROLLING_FOLD_WITHOUT_EVENT",
        "HORIZON_WITHOUT_SAMPLE",
    )
