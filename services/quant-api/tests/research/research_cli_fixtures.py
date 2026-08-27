from __future__ import annotations

from datetime import date
from decimal import Decimal


from app.guiyi_cli.main import build_parser
from app.guiyi_cli.research_requests import build_research_request
from app.research.subing.candidate_validation import (
    CandidateValidationReport,
    CandidateWindowKind,
    ProspectiveOosResult,
    ProspectiveOosStatus,
    RollingCandidateFold,
    project_lifecycle_window,
    summarize_rolling_stability,
)
from app.research.subing.subing_calibration_service import (
    CalibrationResearchResult,
)
from app.market_data.subing_calibration import (
    CalibrationReport,
    HorizonEvaluation,
    ThresholdEvaluation,
)
from app.research.subing.subing_lifecycle_research_service import (
    SubingLifecycleResearchResult,
)
from app.research.subing.subing_candidate_validation_service import (
    CandidateValidationRequest,
)


def _arguments(
    *,
    phase: str = "slope",
    mode: str = "discovery",
    frequency: str = "5m",
) -> list[str]:
    return [
        "research",
        "subing-calibration",
        "--phase",
        phase,
        "--mode",
        mode,
        "--frequency",
        frequency,
        "--since",
        "2026-01-01",
        "--through",
        "2026-03-31",
    ]


def _request(arguments: list[str]):
    return build_research_request(build_parser().parse_args(arguments))




def _horizon(*, sample_count: int = 2) -> HorizonEvaluation:
    return HorizonEvaluation(
        sample_count=sample_count,
        ema21_sample_count=sample_count,
        median_directional_return_bps=Decimal("12.3400"),
        median_mfe_bps=Decimal("18.500"),
        median_mae_bps=Decimal("-3.250"),
        ema21_failure_rate=Decimal("0.1250"),
    )


def _evaluation(threshold: str, *, sample_count: int = 2) -> ThresholdEvaluation:
    return ThresholdEvaluation(
        threshold=Decimal(threshold),
        sample_count=sample_count,
        horizons={3: _horizon(sample_count=sample_count)},
    )


def _discovery_report(
    *, sample_count: int, product_counts: dict[str, int]
) -> CalibrationReport:
    candidates = (Decimal("1.2300"), Decimal("2.500"), Decimal("4"))
    return CalibrationReport(
        sample_count=sample_count,
        product_sample_counts=product_counts,
        candidate_thresholds=candidates,
        candidate_evaluations=tuple(_evaluation(str(value)) for value in candidates),
    )


class _FakeResearchService:
    def __init__(self, result: CalibrationResearchResult) -> None:
        self.result = result
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.result


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
