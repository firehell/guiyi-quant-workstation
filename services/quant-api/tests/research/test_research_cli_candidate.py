from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from decimal import Decimal
import io
import json

import pytest

from app.guiyi_cli.main import build_parser
from app.guiyi_cli.main import main
from app.guiyi_cli.data_parser import CliUsageError
from app.research.subing.candidate_validation import (
    CandidateValidationReport,
    CandidateWindowKind,
    ProspectiveOosResult,
    ProspectiveOosStatus,
    RollingCandidateFold,
    project_lifecycle_window,
    summarize_rolling_stability,
)
from app.research.n_structure.n_candidate_validation import (
    NCandidateWindowKind,
    NProspectiveOosResult,
    NProspectiveOosStatus,
    NRollingCandidateFold,
    NStructureCandidateValidationReport,
    project_n_structure_window,
    summarize_n_rolling_stability,
)
from app.research.n_structure.n_structure_research_service import (
    NStructureResearchResult,
)
from app.market_data.price_outcome import PriceHorizonEvaluation
from app.research.subing.subing_lifecycle_research_service import (
    SubingLifecycleResearchResult,
)
from app.research.subing.subing_candidate_validation_service import (
    CandidateValidationRequest,
)
from research.research_cli_fixtures import _JDJ_CANDIDATES, _horizon, _request


def _candidate_arguments(*, through: str = "2026-08-19") -> list[str]:
    return [
        "research",
        "candidate-validation",
        "--candidate",
        "subing_lifecycle_v2_candidate_v1",
        "--protocol",
        "candidate_validation_v1",
        "--symbol",
        "jm",
        "--through",
        through,
    ]


def _candidate_source() -> SubingLifecycleResearchResult:
    return SubingLifecycleResearchResult(
        products=("jm",),
        segment_count=2,
        evaluable_boundary_count=10,
        funnel_counts={
            "DATA_READY": 10,
            "DIRECTION_CONTEXT_ALIGNED": 6,
            "SETUP_ARMED": 4,
            "TRIGGER_OBSERVED": 3,
            "ENTRY_CONFIRMED": 2,
        },
        funnel_count_units={
            "DATA_READY": "boundary_occupancy",
            "DIRECTION_CONTEXT_ALIGNED": "boundary_occupancy",
            "SETUP_ARMED": "boundary_event",
            "TRIGGER_OBSERVED": "boundary_event",
            "ENTRY_CONFIRMED": "boundary_event",
        },
        confirmation_source_counts={
            "FORMAL_V1": 1,
            "MOMENTUM_HOLD": 1,
            "PIVOT_BREAK_HOLD": 0,
            "PIVOT_RETEST_REBREAK": 0,
        },
        v1_v2_overlap_counts={"V1_AND_V2": 1, "V2_ONLY": 1, "V1_ONLY": 0},
        v2_to_v1_lead_bars=(2, 5),
        confirmed_trading_day_span_counts={"SAME_DAY": 1, "CROSS_DAY": 1},
        risk_reason_counts={"ANCHOR_EMA21_BREACH": 1},
        recovery_reason_counts={"ANCHOR_RECOVERY_CONFIRMED": 1},
        close_reason_counts={"ANCHOR_TREND_BROKEN": 1},
        horizon_summary={3: _horizon(), 5: _horizon(), 8: _horizon()},
    )


def _candidate_report() -> CandidateValidationReport:
    source = _candidate_source()
    retrospective = project_lifecycle_window(
        window_id="retrospective",
        window_kind=CandidateWindowKind.RETROSPECTIVE,
        since=date(2023, 1, 1),
        through=date(2026, 8, 18),
        source=source,
    )
    fold = RollingCandidateFold(
        fold_id="fold_01",
        reference=project_lifecycle_window(
            window_id="fold_01_reference",
            window_kind=CandidateWindowKind.ROLLING_REFERENCE,
            since=date(2023, 1, 1),
            through=date(2023, 12, 31),
            source=source,
        ),
        test=project_lifecycle_window(
            window_id="fold_01_test",
            window_kind=CandidateWindowKind.ROLLING_TEST,
            since=date(2024, 1, 1),
            through=date(2024, 3, 31),
            source=source,
        ),
    )
    folds = (fold,)
    return CandidateValidationReport(
        schema_version=1,
        candidate_id="subing_lifecycle_v2_candidate_v1",
        policy_id="subing_lifecycle_v2_research_v1",
        formula_version="subing_lifecycle_v2",
        protocol_id="candidate_validation_v1",
        research_only=True,
        symbol="jm",
        retrospective=retrospective,
        rolling_folds=folds,
        rolling_stability=summarize_rolling_stability(folds),
        prospective_oos=ProspectiveOosResult(
            status=ProspectiveOosStatus.PENDING,
            first_trading_day=date(2026, 8, 20),
            through=date(2026, 8, 19),
            result=None,
        ),
        quality_flags=("PROSPECTIVE_OOS_PENDING",),
    )


class _FakeCandidateValidationService:
    def __init__(self, report: CandidateValidationReport) -> None:
        self.report = report
        self.requests: list[CandidateValidationRequest] = []

    def run(self, request: CandidateValidationRequest) -> CandidateValidationReport:
        self.requests.append(request)
        return self.report


class _FakeNCandidateValidationService:
    def __init__(self, report: NStructureCandidateValidationReport) -> None:
        self.report = report
        self.requests: list[CandidateValidationRequest] = []

    def run(
        self,
        request: CandidateValidationRequest,
    ) -> NStructureCandidateValidationReport:
        self.requests.append(request)
        return self.report


def test_candidate_parser_uses_exact_frozen_choices() -> None:
    request = _request(_candidate_arguments(through="2026-08-17"))

    assert request == CandidateValidationRequest(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        protocol_id="candidate_validation_v1",
        symbol="jm",
        through=date(2026, 8, 17),
    )
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                *_candidate_arguments(),
                "--candidate",
                "other_candidate",
            ]
        )


def test_candidate_cli_dispatches_explicit_service_and_serializes_report() -> None:
    service = _FakeCandidateValidationService(_candidate_report())
    calibration_calls: list[object] = []
    lifecycle_calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        _candidate_arguments(),
        session_factory=lambda: nullcontext(object()),
        research_service_factory=lambda session: calibration_calls.append(session),
        lifecycle_research_service_factory=lambda session: lifecycle_calls.append(
            session
        ),
        candidate_validation_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert calibration_calls == []
    assert lifecycle_calls == []
    assert service.requests == [
        CandidateValidationRequest(
            candidate_id="subing_lifecycle_v2_candidate_v1",
            protocol_id="candidate_validation_v1",
            symbol="jm",
            through=date(2026, 8, 19),
        )
    ]
    payload = json.loads(stdout.getvalue())
    assert set(payload) == {
        "schema_version",
        "command",
        "status",
        "readonly",
        "candidate_id",
        "policy_id",
        "formula_version",
        "protocol_id",
        "research_only",
        "symbol",
        "retrospective",
        "rolling_folds",
        "rolling_stability",
        "prospective_oos",
        "quality_flags",
    }
    assert payload["command"] == "research.candidate-validation"
    assert payload["readonly"] is True
    assert payload["research_only"] is True
    assert payload["retrospective"]["window_kind"] == "retrospective"
    assert payload["rolling_folds"][0]["fold_id"] == "fold_01"
    assert payload["rolling_stability"] == {
        "fold_count": 1,
        "folds_with_entries": 1,
        "entry_count_min": 2,
        "entry_count_max": 2,
        "entry_count_median": "2",
    }
    assert payload["prospective_oos"] == {
        "status": "pending",
        "first_trading_day": "2026-08-20",
        "through": "2026-08-19",
        "result": None,
    }
    assert (
        payload["retrospective"]["horizon_summary"]["3"][
            "median_directional_return_bps"
        ]
        == "12.3400"
    )


def _n_candidate_arguments(
    *,
    candidate: str = "n_structure_5m_candidate_v1",
    protocol: str = "n_structure_validation_v1",
    through: str = "2026-08-20",
) -> list[str]:
    return [
        "research",
        "candidate-validation",
        "--candidate",
        candidate,
        "--protocol",
        protocol,
        "--symbol",
        "jm",
        "--through",
        through,
    ]


def _n_candidate_horizon() -> PriceHorizonEvaluation:
    return PriceHorizonEvaluation(
        3,
        Decimal("1.2"),
        Decimal("2.3"),
        Decimal("-0.4"),
    )


def _n_candidate_source() -> NStructureResearchResult:
    return NStructureResearchResult(
        products=("jm",),
        segment_count=2,
        evaluable_bar_count=10,
        confirmed_pivot_count=4,
        ambiguous_outside_reset_count=1,
        incomplete_attempt_replaced_count=2,
        completed_n_counts={"up": 2, "down": 1},
        n_break_counts={"n2_origin_broken": 1, "origin_broken": 1},
        range_band_reentry_count=2,
        structure_established_counts={"bull": 1, "bear": 1, "range": 1},
        structure_break_counts={"bull": 1, "bear": 0},
        horizon_summary={
            3: _n_candidate_horizon(),
            5: _n_candidate_horizon(),
            8: _n_candidate_horizon(),
        },
    )


def _n_candidate_report() -> NStructureCandidateValidationReport:
    source = _n_candidate_source()
    retrospective = project_n_structure_window(
        window_id="retrospective",
        window_kind=NCandidateWindowKind.RETROSPECTIVE,
        since=date(2023, 1, 1),
        through=date(2026, 8, 19),
        source=source,
    )
    fold = NRollingCandidateFold(
        fold_id="fold_01",
        reference=project_n_structure_window(
            window_id="fold_01_reference",
            window_kind=NCandidateWindowKind.ROLLING_REFERENCE,
            since=date(2023, 1, 1),
            through=date(2023, 12, 31),
            source=source,
        ),
        test=project_n_structure_window(
            window_id="fold_01_test",
            window_kind=NCandidateWindowKind.ROLLING_TEST,
            since=date(2024, 1, 1),
            through=date(2024, 3, 31),
            source=source,
        ),
    )
    folds = (fold,)
    return NStructureCandidateValidationReport(
        schema_version=1,
        candidate_id="n_structure_5m_candidate_v1",
        policy_id="n_structure_5m_v1",
        formula_version="n_structure_v1",
        protocol_id="n_structure_validation_v1",
        research_only=True,
        symbol="jm",
        retrospective=retrospective,
        rolling_folds=folds,
        rolling_stability=summarize_n_rolling_stability(folds),
        prospective_oos=NProspectiveOosResult(
            status=NProspectiveOosStatus.PENDING,
            first_trading_day=date(2026, 8, 21),
            through=date(2026, 8, 20),
            result=None,
        ),
        quality_flags=("PROSPECTIVE_OOS_PENDING",),
    )


def test_candidate_parser_accepts_exactly_five_candidate_and_three_protocol_ids() -> (
    None
):
    request = _request(_n_candidate_arguments())

    assert request == CandidateValidationRequest(
        candidate_id="n_structure_5m_candidate_v1",
        protocol_id="n_structure_validation_v1",
        symbol="jm",
        through=date(2026, 8, 20),
    )
    cross_pair = _request(_n_candidate_arguments(protocol="candidate_validation_v1"))
    assert cross_pair.protocol_id == "candidate_validation_v1"
    for candidate_id in _JDJ_CANDIDATES:
        request = _request(
            [
                "research",
                "candidate-validation",
                "--candidate",
                candidate_id,
                "--protocol",
                "jdj_candidate_validation_v1",
                "--symbol",
                "jm",
                "--through",
                "2026-08-21",
            ]
        )
        assert request.candidate_id == candidate_id
        assert request.protocol_id == "jdj_candidate_validation_v1"
    for arguments in (
        _n_candidate_arguments(candidate="other_candidate"),
        _n_candidate_arguments(protocol="other_protocol"),
    ):
        with pytest.raises(CliUsageError):
            build_parser().parse_args(arguments)


def test_n_candidate_cli_uses_explicit_n_service_and_source_specific_payload() -> None:
    n_service = _FakeNCandidateValidationService(_n_candidate_report())
    subing_calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        _n_candidate_arguments(),
        session_factory=lambda: nullcontext(object()),
        candidate_validation_service_factory=lambda session: subing_calls.append(
            session
        ),
        n_candidate_validation_service_factory=lambda _session: n_service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert subing_calls == []
    assert n_service.requests == [
        CandidateValidationRequest(
            candidate_id="n_structure_5m_candidate_v1",
            protocol_id="n_structure_validation_v1",
            symbol="jm",
            through=date(2026, 8, 20),
        )
    ]
    payload = json.loads(stdout.getvalue())
    assert payload["retrospective"] == {
        "window_id": "retrospective",
        "window_kind": "retrospective",
        "since": "2023-01-01",
        "through": "2026-08-19",
        "products": ["jm"],
        "segment_count": 2,
        "evaluable_bar_count": 10,
        "confirmed_pivot_count": 4,
        "ambiguous_outside_reset_count": 1,
        "incomplete_attempt_replaced_count": 2,
        "completed_n_counts": {"up": 2, "down": 1},
        "n_break_counts": {"n2_origin_broken": 1, "origin_broken": 1},
        "range_band_reentry_count": 2,
        "structure_established_counts": {"bull": 1, "bear": 1, "range": 1},
        "structure_break_counts": {"bull": 1, "bear": 0},
        "horizon_summary": {
            "3": {
                "sample_count": 3,
                "median_directional_return_bps": "1.2",
                "median_mfe_bps": "2.3",
                "median_mae_bps": "-0.4",
            },
            "5": {
                "sample_count": 3,
                "median_directional_return_bps": "1.2",
                "median_mfe_bps": "2.3",
                "median_mae_bps": "-0.4",
            },
            "8": {
                "sample_count": 3,
                "median_directional_return_bps": "1.2",
                "median_mfe_bps": "2.3",
                "median_mae_bps": "-0.4",
            },
        },
    }
    assert payload["rolling_stability"] == {
        "fold_count": 1,
        "folds_with_completed_n": 1,
        "completed_n_min": 3,
        "completed_n_max": 3,
        "completed_n_median": "3",
    }
    assert payload["prospective_oos"] == {
        "status": "pending",
        "first_trading_day": "2026-08-21",
        "through": "2026-08-20",
        "result": None,
    }
