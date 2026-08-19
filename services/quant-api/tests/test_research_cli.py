from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from decimal import Decimal
import io
import json

import pytest

from app.market_data import composition as market_data_composition
from app.guiyi_cli.main import build_parser
from app.guiyi_cli.main import main
from app.guiyi_cli.data_parser import CliUsageError
from app.guiyi_cli.research_commands import build_research_request
from app.market_data.candidate_validation import (
    CandidateValidationReport,
    CandidateWindowKind,
    ProspectiveOosResult,
    ProspectiveOosStatus,
    RollingCandidateFold,
    project_lifecycle_window,
    summarize_rolling_stability,
)
from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.main_force_mirror_futures_research_service import (
    MainForceMirrorFuturesHorizonSummary,
    MainForceMirrorFuturesResearchRequest,
    MainForceMirrorFuturesResearchResult,
    MainForceMirrorFuturesResearchService,
)
from app.market_data.subing_calibration_service import (
    CalibrationMode,
    CalibrationPhase,
    SlopeThresholds,
    CalibrationResearchResult,
)
from app.market_data.subing_calibration import (
    CalibrationReport,
    HorizonEvaluation,
    ThresholdEvaluation,
)
from app.market_data.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)
from app.market_data.subing_candidate_validation_service import (
    CandidateValidationRequest,
    SubingCandidateValidationService,
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


def _lifecycle_arguments() -> list[str]:
    return [
        "research",
        "subing-lifecycle",
        "--since",
        "2026-01-01",
        "--through",
        "2026-03-31",
    ]


def test_research_parser_exposes_only_the_four_readonly_commands() -> None:
    parser = build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")
    research_parser = domain_action.choices["research"]
    command_action = next(
        action
        for action in research_parser._actions
        if action.dest == "research_command"
    )

    assert set(command_action.choices) == {
        "candidate-validation",
        "main-force-mirror-futures",
        "subing-calibration",
        "subing-lifecycle",
    }


def test_lifecycle_request_parses_dates_and_normalizes_optional_symbol() -> None:
    request = _request([*_lifecycle_arguments(), "--symbol", " JM "])

    assert request == LifecycleResearchRequest(
        since=date(2026, 1, 1),
        through=date(2026, 3, 31),
        symbol="jm",
    )


@pytest.mark.parametrize(
    "arguments",
    (
        [
            "research",
            "subing-lifecycle",
            "--since",
            "2026-04-01",
            "--through",
            "2026-03-31",
        ],
        [*_lifecycle_arguments(), "--policy-id", "anything"],
    ),
)
def test_invalid_lifecycle_input_exits_two_before_either_service_construction(
    arguments: list[str],
) -> None:
    calibration_calls: list[object] = []
    lifecycle_calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        arguments,
        session_factory=lambda: nullcontext(object()),
        research_service_factory=lambda session: calibration_calls.append(session),
        lifecycle_research_service_factory=lambda session: lifecycle_calls.append(
            session
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.subing-lifecycle",
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_ARGUMENT_INVALID", "type": "CliUsageError"},
    }
    assert calibration_calls == []
    assert lifecycle_calls == []


def test_research_parser_accepts_the_supported_frequency_set() -> None:
    parser = build_parser()

    for frequency in ("5m", "15m", "1d"):
        args = parser.parse_args(
            [
                "research",
                "subing-calibration",
                "--phase",
                "slope",
                "--mode",
                "discovery",
                "--frequency",
                frequency,
                "--since",
                "2026-01-01",
                "--through",
                "2026-03-31",
            ]
        )
        assert args.frequency == frequency


@pytest.mark.parametrize(
    ("arguments", "expected_slope", "expected_pair", "expected_zero"),
    (
        (_arguments(), None, None, None),
        (
            _arguments(mode="validation") + ["--slope-threshold-bps", "1.250"],
            Decimal("1.250"),
            None,
            None,
        ),
        (
            _arguments(phase="zero-band")
            + [
                "--slope-threshold-5m-bps",
                "1.1",
                "--slope-threshold-15m-bps",
                "2.2",
            ],
            None,
            SlopeThresholds(Decimal("1.1"), Decimal("2.2")),
            None,
        ),
        (
            _arguments(phase="zero-band", mode="validation", frequency="15m")
            + [
                "--slope-threshold-5m-bps",
                "1.1",
                "--slope-threshold-15m-bps",
                "2.2",
                "--zero-band-bps",
                "3.3",
            ],
            None,
            SlopeThresholds(Decimal("1.1"), Decimal("2.2")),
            Decimal("3.3"),
        ),
        (
            _arguments(phase="zero-band", frequency="1d")
            + ["--slope-threshold-bps", "4.4"],
            Decimal("4.4"),
            None,
            None,
        ),
        (
            _arguments(phase="zero-band", mode="validation", frequency="1d")
            + [
                "--slope-threshold-bps",
                "4.4",
                "--zero-band-bps",
                "5.5",
            ],
            Decimal("4.4"),
            None,
            Decimal("5.5"),
        ),
    ),
)
def test_research_request_accepts_only_the_six_supported_matrix_shapes(
    arguments: list[str],
    expected_slope: Decimal | None,
    expected_pair: SlopeThresholds | None,
    expected_zero: Decimal | None,
) -> None:
    request = _request(arguments)

    assert request.slope_threshold_bps == expected_slope
    assert request.slope_thresholds == expected_pair
    assert request.zero_band_bps == expected_zero


@pytest.mark.parametrize(
    "arguments",
    (
        _arguments() + ["--slope-threshold-bps", "1"],
        _arguments() + ["--zero-band-bps", "1"],
        _arguments()
        + [
            "--slope-threshold-5m-bps",
            "1",
            "--slope-threshold-15m-bps",
            "1",
        ],
        _arguments(mode="validation"),
        _arguments(mode="validation")
        + [
            "--slope-threshold-bps",
            "1",
            "--slope-threshold-5m-bps",
            "1",
            "--slope-threshold-15m-bps",
            "1",
        ],
        _arguments(phase="zero-band"),
        _arguments(phase="zero-band") + ["--slope-threshold-5m-bps", "1"],
        _arguments(phase="zero-band")
        + ["--slope-threshold-bps", "1", "--slope-threshold-15m-bps", "1"],
        _arguments(phase="zero-band")
        + [
            "--slope-threshold-5m-bps",
            "1",
            "--slope-threshold-15m-bps",
            "1",
            "--zero-band-bps",
            "1",
        ],
        _arguments(phase="zero-band", mode="validation")
        + ["--slope-threshold-5m-bps", "1", "--slope-threshold-15m-bps", "1"],
        _arguments(phase="zero-band", mode="validation")
        + ["--slope-threshold-5m-bps", "1", "--zero-band-bps", "1"],
        _arguments(phase="zero-band", frequency="1d"),
        _arguments(phase="zero-band", frequency="1d")
        + [
            "--slope-threshold-5m-bps",
            "1",
            "--slope-threshold-15m-bps",
            "1",
        ],
        _arguments(phase="zero-band", frequency="1d")
        + ["--slope-threshold-bps", "1", "--zero-band-bps", "1"],
        _arguments(phase="zero-band", mode="validation", frequency="1d")
        + ["--slope-threshold-bps", "1"],
        _arguments(phase="zero-band", mode="validation", frequency="1d")
        + ["--zero-band-bps", "1"],
        _arguments(phase="zero-band", mode="validation", frequency="1d")
        + [
            "--slope-threshold-5m-bps",
            "1",
            "--slope-threshold-15m-bps",
            "1",
            "--zero-band-bps",
            "1",
        ],
    ),
)
def test_research_request_rejects_every_unsupported_matrix_shape(
    arguments: list[str],
) -> None:
    with pytest.raises(ValueError):
        _request(arguments)


@pytest.mark.parametrize("invalid_date", ("2026-02-30", "01-01-2026", ""))
def test_research_request_rejects_invalid_iso_dates(invalid_date: str) -> None:
    arguments = _arguments()
    arguments[arguments.index("2026-01-01")] = invalid_date

    with pytest.raises(ValueError):
        _request(arguments)


def test_research_request_rejects_a_reversed_window() -> None:
    arguments = _arguments()
    arguments[arguments.index("2026-01-01")] = "2026-04-01"

    with pytest.raises(ValueError):
        _request(arguments)


@pytest.mark.parametrize("invalid", ("NaN", "Infinity", "-0.0001", "not-decimal"))
@pytest.mark.parametrize(
    "arguments,flag",
    (
        (_arguments(mode="validation"), "--slope-threshold-bps"),
        (
            _arguments(phase="zero-band")
            + ["--slope-threshold-15m-bps", "1"],
            "--slope-threshold-5m-bps",
        ),
        (
            _arguments(phase="zero-band") + ["--slope-threshold-5m-bps", "1"],
            "--slope-threshold-15m-bps",
        ),
        (
            _arguments(phase="zero-band", mode="validation", frequency="1d")
            + ["--slope-threshold-bps", "1"],
            "--zero-band-bps",
        ),
    ),
)
def test_research_request_rejects_non_finite_or_negative_thresholds(
    arguments: list[str], flag: str, invalid: str
) -> None:
    invalid_arguments = [*arguments, flag, invalid]
    with pytest.raises(ValueError):
        _request(invalid_arguments)

    calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        invalid_arguments,
        session_factory=lambda: nullcontext(object()),
        research_service_factory=lambda session: calls.append(session),
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 2
    assert json.loads(stderr.getvalue())["error"] == {
        "code": "CLI_ARGUMENT_INVALID",
        "type": "CliUsageError",
    }
    assert calls == []


def test_research_request_parses_dates_decimals_and_normalizes_symbol() -> None:
    request = _request(
        _arguments(mode="validation")
        + ["--symbol", " JM ", "--slope-threshold-bps", "1.2300"]
    )

    assert request.phase is CalibrationPhase.SLOPE
    assert request.mode is CalibrationMode.VALIDATION
    assert request.frequency is BarFrequency.M5
    assert request.since == date(2026, 1, 1)
    assert request.through == date(2026, 3, 31)
    assert request.symbol == "jm"
    assert request.slope_threshold_bps == Decimal("1.2300")


def test_invalid_research_request_exits_two_before_service_construction() -> None:
    calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        _arguments(mode="validation"),
        session_factory=lambda: nullcontext(object()),
        research_service_factory=lambda session: calls.append(session),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.subing-calibration",
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_ARGUMENT_INVALID", "type": "CliUsageError"},
    }
    assert calls == []


def test_invalid_frequency_exits_two_before_service_construction() -> None:
    calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        _arguments(frequency="30m"),
        session_factory=lambda: nullcontext(object()),
        research_service_factory=lambda session: calls.append(session),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"] == {
        "code": "CLI_ARGUMENT_INVALID",
        "type": "CliUsageError",
    }
    assert calls == []


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


def _validation_report(
    *, sample_count: int, product_counts: dict[str, int]
) -> CalibrationReport:
    return CalibrationReport(
        sample_count=sample_count,
        product_sample_counts=product_counts,
        threshold_evaluation=_evaluation("2.7500", sample_count=sample_count),
    )


class _FakeResearchService:
    def __init__(self, result: CalibrationResearchResult) -> None:
        self.result = result
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.result


class _FakeLifecycleResearchService:
    def __init__(self, result: SubingLifecycleResearchResult) -> None:
        self.result = result
        self.requests: list[LifecycleResearchRequest] = []

    def run(self, request: LifecycleResearchRequest) -> SubingLifecycleResearchResult:
        self.requests.append(request)
        return self.result


def _run_research(arguments: list[str], service: object):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        arguments,
        session_factory=lambda: nullcontext(object()),
        research_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )
    stream = stdout if code == 0 else stderr
    return code, json.loads(stream.getvalue())


def test_lifecycle_shadow_outputs_readonly_research_observations_as_json() -> None:
    service = _FakeLifecycleResearchService(
        SubingLifecycleResearchResult(
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
            v1_v2_overlap_counts={
                "V1_AND_V2": 1,
                "V2_ONLY": 1,
                "V1_ONLY": 0,
            },
            v2_to_v1_lead_bars=(2, 5),
            confirmed_trading_day_span_counts={"SAME_DAY": 1, "CROSS_DAY": 1},
            risk_reason_counts={"ANCHOR_EMA21_BREACH": 1},
            recovery_reason_counts={"ANCHOR_RECOVERY_CONFIRMED": 1},
            close_reason_counts={"ANCHOR_TREND_BROKEN": 1},
            horizon_summary={3: _horizon(), 5: _horizon(sample_count=1), 8: _horizon()},
        )
    )
    calibration_calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [*_lifecycle_arguments(), "--symbol", "jm"],
        session_factory=lambda: nullcontext(object()),
        research_service_factory=lambda session: calibration_calls.append(session),
        lifecycle_research_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert service.requests == [
        LifecycleResearchRequest(date(2026, 1, 1), date(2026, 3, 31), "jm")
    ]
    assert calibration_calls == []
    payload = json.loads(stdout.getvalue())
    assert payload == {
        "schema_version": 1,
        "command": "research.subing-lifecycle",
        "status": "ok",
        "readonly": True,
        "policy_id": "subing_lifecycle_v2_research_v1",
        "since": "2026-01-01",
        "through": "2026-03-31",
        "products": ["jm"],
        "segment_count": 2,
        "evaluable_boundary_count": 10,
        "funnel_counts": {
            "DATA_READY": 10,
            "DIRECTION_CONTEXT_ALIGNED": 6,
            "SETUP_ARMED": 4,
            "TRIGGER_OBSERVED": 3,
            "ENTRY_CONFIRMED": 2,
        },
        "funnel_count_units": {
            "DATA_READY": "boundary_occupancy",
            "DIRECTION_CONTEXT_ALIGNED": "boundary_occupancy",
            "SETUP_ARMED": "boundary_event",
            "TRIGGER_OBSERVED": "boundary_event",
            "ENTRY_CONFIRMED": "boundary_event",
        },
        "confirmation_source_counts": {
            "FORMAL_V1": 1,
            "MOMENTUM_HOLD": 1,
            "PIVOT_BREAK_HOLD": 0,
            "PIVOT_RETEST_REBREAK": 0,
        },
        "v1_v2_overlap_counts": {
            "V1_AND_V2": 1,
            "V2_ONLY": 1,
            "V1_ONLY": 0,
        },
        "v2_to_v1_lead_bars": [2, 5],
        "confirmed_trading_day_span_counts": {"SAME_DAY": 1, "CROSS_DAY": 1},
        "risk_reason_counts": {"ANCHOR_EMA21_BREACH": 1},
        "recovery_reason_counts": {"ANCHOR_RECOVERY_CONFIRMED": 1},
        "close_reason_counts": {"ANCHOR_TREND_BROKEN": 1},
        "horizon_summary": {
            "3": {
                "sample_count": 2,
                "ema21_sample_count": 2,
                "median_directional_return_bps": "12.3400",
                "median_mfe_bps": "18.500",
                "median_mae_bps": "-3.250",
                "ema21_failure_rate": "0.1250",
            },
            "5": {
                "sample_count": 1,
                "ema21_sample_count": 1,
                "median_directional_return_bps": "12.3400",
                "median_mfe_bps": "18.500",
                "median_mae_bps": "-3.250",
                "ema21_failure_rate": "0.1250",
            },
            "8": {
                "sample_count": 2,
                "ema21_sample_count": 2,
                "median_directional_return_bps": "12.3400",
                "median_mfe_bps": "18.500",
                "median_mae_bps": "-3.250",
                "ema21_failure_rate": "0.1250",
            },
        },
    }
    rendered = stdout.getvalue().lower()
    for forbidden in ("backtest", "pnl", "profitability", "readiness", "promotion"):
        assert forbidden not in rendered


def test_slope_discovery_outputs_json_safe_decimal_strings_and_active_60() -> None:
    products = tuple(f"p{index:02d}" for index in range(60))
    counts = {product: index % 3 for index, product in enumerate(products)}
    report = _discovery_report(sample_count=sum(counts.values()), product_counts=counts)
    service = _FakeResearchService(CalibrationResearchResult(products, report, {}))

    code, payload = _run_research(_arguments(), service)

    assert code == 0
    assert service.requests[0].symbol is None
    assert payload["schema_version"] == 1
    assert payload["command"] == "research.subing-calibration"
    assert payload["status"] == "ok"
    assert payload["readonly"] is True
    assert payload["phase"] == "slope"
    assert payload["mode"] == "discovery"
    assert payload["frequency"] == "5m"
    assert payload["since"] == "2026-01-01"
    assert payload["through"] == "2026-03-31"
    assert payload["products"] == list(products)
    assert len(payload["products"]) == 60
    assert payload["sample_count"] == sum(counts.values())
    assert payload["product_sample_counts"] == counts
    assert payload["candidate_thresholds"] == ["1.2300", "2.500", "4"]
    assert payload["candidate_evaluations"][0] == {
        "threshold": "1.2300",
        "sample_count": 2,
        "horizons": {
            "3": {
                "sample_count": 2,
                "ema21_sample_count": 2,
                "median_directional_return_bps": "12.3400",
                "median_mfe_bps": "18.500",
                "median_mae_bps": "-3.250",
                "ema21_failure_rate": "0.1250",
            }
        },
    }
    assert "threshold_evaluation" not in payload
    assert "cohorts" not in payload


def test_slope_validation_outputs_only_the_explicit_threshold_evaluation() -> None:
    report = _validation_report(sample_count=2, product_counts={"jm": 2})
    service = _FakeResearchService(
        CalibrationResearchResult(("jm",), report, {})
    )

    code, payload = _run_research(
        _arguments(mode="validation")
        + ["--symbol", "jm", "--slope-threshold-bps", "2.7500"],
        service,
    )

    assert code == 0
    assert payload["products"] == ["jm"]
    assert payload["threshold_evaluation"]["threshold"] == "2.7500"
    assert "candidate_thresholds" not in payload
    assert "candidate_evaluations" not in payload


@pytest.mark.parametrize("mode", ("discovery", "validation"))
def test_zero_band_outputs_both_named_cohorts(mode: str) -> None:
    report_factory = (
        _discovery_report if mode == "discovery" else _validation_report
    )
    cohort_a = report_factory(sample_count=3, product_counts={"jm": 3})
    cohort_b = report_factory(sample_count=1, product_counts={"jm": 1})
    service = _FakeResearchService(
        CalibrationResearchResult(
            ("jm",),
            cohort_b,
            {"A": cohort_a, "B": cohort_b},
        )
    )
    arguments = _arguments(phase="zero-band", mode=mode)
    arguments.extend(
        [
            "--symbol",
            "jm",
            "--slope-threshold-5m-bps",
            "1",
            "--slope-threshold-15m-bps",
            "2",
        ]
    )
    if mode == "validation":
        arguments.extend(["--zero-band-bps", "2.7500"])

    code, payload = _run_research(arguments, service)

    assert code == 0
    assert set(payload["cohorts"]) == {"A", "B"}
    assert payload["cohorts"]["A"]["sample_count"] == 3
    assert payload["cohorts"]["B"]["sample_count"] == 1
    if mode == "discovery":
        assert payload["cohorts"]["A"]["candidate_thresholds"] == [
            "1.2300",
            "2.500",
            "4",
        ]
        assert payload["cohorts"]["B"]["candidate_evaluations"][0][
            "threshold"
        ] == "1.2300"
    else:
        assert payload["cohorts"]["A"]["threshold_evaluation"][
            "threshold"
        ] == "2.7500"
        assert payload["cohorts"]["B"]["threshold_evaluation"][
            "threshold"
        ] == "2.7500"


def test_research_payload_contains_no_selection_approval_or_trade_claims() -> None:
    report = _discovery_report(sample_count=1, product_counts={"jm": 1})
    service = _FakeResearchService(CalibrationResearchResult(("jm",), report, {}))

    code, payload = _run_research(
        [*_arguments(), "--symbol", "jm"],
        service,
    )

    assert code == 0
    rendered = json.dumps(payload, sort_keys=True).lower()
    for forbidden in ("best", "approved", "trade", "performance"):
        assert forbidden not in rendered


def test_research_execution_error_is_redacted_and_always_readonly() -> None:
    class ResearchReadError(RuntimeError):
        code = "RESEARCH_READ_FAILED"

    class FailingService:
        def run(self, _request):
            raise ResearchReadError("do not expose /private/catalog or SQL")

    code, payload = _run_research(_arguments(), FailingService())

    assert code == 1
    assert payload == {
        "schema_version": 1,
        "command": "research.subing-calibration",
        "status": "error",
        "readonly": True,
        "error": {"code": "RESEARCH_READ_FAILED", "type": "ResearchReadError"},
    }


def test_research_service_construction_error_is_always_readonly() -> None:
    class ResearchConstructionError(RuntimeError):
        code = "RESEARCH_CONSTRUCTION_FAILED"

    stdout = io.StringIO()
    stderr = io.StringIO()

    def fail_construction(_session):
        raise ResearchConstructionError("do not expose connection details")

    code = main(
        _arguments(),
        session_factory=lambda: nullcontext(object()),
        research_service_factory=fail_construction,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.subing-calibration",
        "status": "error",
        "readonly": True,
        "error": {
            "code": "RESEARCH_CONSTRUCTION_FAILED",
            "type": "ResearchConstructionError",
        },
    }


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
    assert payload["retrospective"]["horizon_summary"]["3"][
        "median_directional_return_bps"
    ] == "12.3400"


def test_candidate_composition_reuses_the_lifecycle_research_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = object()
    sessions: list[object] = []

    def build_lifecycle(session: object) -> object:
        sessions.append(session)
        return lifecycle

    monkeypatch.setattr(
        market_data_composition,
        "build_subing_lifecycle_research_service",
        build_lifecycle,
    )
    session = object()

    service = market_data_composition.build_subing_candidate_validation_service(
        session  # type: ignore[arg-type]
    )

    assert isinstance(service, SubingCandidateValidationService)
    assert service._lifecycle_research is lifecycle
    assert sessions == [session]


def test_candidate_payload_contains_no_automatic_decision_or_profit_fields() -> None:
    service = _FakeCandidateValidationService(_candidate_report())
    stdout = io.StringIO()
    code = main(
        _candidate_arguments(),
        session_factory=lambda: nullcontext(object()),
        candidate_validation_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert code == 0
    payload = json.loads(stdout.getvalue())

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert keys(payload).isdisjoint(
        {
            "keep",
            "drop",
            "promote",
            "pass_strategy",
            "expected_profit",
            "account_return",
        }
    )


def _mirror_arguments(
    *,
    series_kind: str = "actual_dominant",
    contract: str | None = None,
) -> list[str]:
    arguments = [
        "research",
        "main-force-mirror-futures",
        "--symbol",
        "jm",
        "--series-kind",
        series_kind,
        "--frequency",
        "60m",
        "--since",
        "2023-01-01",
        "--through",
        "2026-08-18",
    ]
    if contract is not None:
        arguments.extend(("--contract", contract))
    return arguments


class _FakeMirrorResearchService:
    def __init__(self, result: MainForceMirrorFuturesResearchResult) -> None:
        self.result = result
        self.requests: list[MainForceMirrorFuturesResearchRequest] = []

    def run(
        self,
        request: MainForceMirrorFuturesResearchRequest,
    ) -> MainForceMirrorFuturesResearchResult:
        self.requests.append(request)
        return self.result


def _mirror_result() -> MainForceMirrorFuturesResearchResult:
    return MainForceMirrorFuturesResearchResult(
        products=("jm",),
        bars_valid_count=120,
        bars_state_ready_count=100,
        bars_caution_ready_count=90,
        event_count_long=2,
        event_count_short=1,
        conflict_count=1,
        missing_oi_count=3,
        segment_reset_count=2,
        timestamp_invalid_count=1,
        state_distribution={"long_build": 40, "turnover": 60},
        reason_code_distribution={"LONG_UPPER_EXTREME": 2},
        score_distribution=(70, 85, 100),
        horizon_summary={
            horizon: MainForceMirrorFuturesHorizonSummary(
                horizon_bars=horizon,
                sample_count=1 if horizon < 10 else 0,
                reversal_returns=(0.1,) if horizon < 10 else (),
                warning_mfe=(0.2,) if horizon < 10 else (),
                warning_mae=(0.05,) if horizon < 10 else (),
            )
            for horizon in (1, 3, 5, 10)
        },
    )


def test_mirror_request_parses_exact_actual_dominant_and_contract_modes() -> None:
    dominant = _request(_mirror_arguments())
    contract = _request(
        _mirror_arguments(series_kind="contract", contract="jm2609")
    )

    assert dominant == MainForceMirrorFuturesResearchRequest(
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        contract=None,
        frequency=BarFrequency.H1,
        since=date(2023, 1, 1),
        through=date(2026, 8, 18),
    )
    assert contract == MainForceMirrorFuturesResearchRequest(
        symbol="jm",
        series_kind=SeriesKind.CONTRACT,
        contract="JM2609",
        frequency=BarFrequency.H1,
        since=date(2023, 1, 1),
        through=date(2026, 8, 18),
    )


@pytest.mark.parametrize(
    "arguments",
    (
        _mirror_arguments(series_kind="contract"),
        _mirror_arguments(contract="JM2609"),
    ),
)
def test_invalid_mirror_identity_exits_two_before_any_service_construction(
    arguments: list[str],
) -> None:
    calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        arguments,
        session_factory=lambda: nullcontext(object()),
        main_force_mirror_futures_research_service_factory=lambda session: (
            calls.append(session)
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.main-force-mirror-futures",
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_ARGUMENT_INVALID", "type": "CliUsageError"},
    }
    assert calls == []


def test_mirror_cli_uses_dedicated_factory_and_stable_readonly_json() -> None:
    service = _FakeMirrorResearchService(_mirror_result())
    unrelated_calls: list[str] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        _mirror_arguments(),
        session_factory=lambda: nullcontext(object()),
        research_service_factory=lambda _session: unrelated_calls.append(
            "calibration"
        ),
        lifecycle_research_service_factory=lambda _session: unrelated_calls.append(
            "lifecycle"
        ),
        candidate_validation_service_factory=lambda _session: unrelated_calls.append(
            "candidate"
        ),
        main_force_mirror_futures_research_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert unrelated_calls == []
    assert service.requests == [
        MainForceMirrorFuturesResearchRequest(
            symbol="jm",
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            contract=None,
            frequency=BarFrequency.H1,
            since=date(2023, 1, 1),
            through=date(2026, 8, 18),
        )
    ]
    payload = json.loads(stdout.getvalue())
    assert set(payload) == {
        "schema_version",
        "command",
        "status",
        "readonly",
        "symbol",
        "series_kind",
        "contract",
        "frequency",
        "since",
        "through",
        "products",
        "bars_valid_count",
        "bars_state_ready_count",
        "bars_caution_ready_count",
        "event_count_long",
        "event_count_short",
        "conflict_count",
        "missing_oi_count",
        "segment_reset_count",
        "timestamp_invalid_count",
        "state_distribution",
        "reason_code_distribution",
        "score_distribution",
        "horizon_summary",
    }
    assert payload["command"] == "research.main-force-mirror-futures"
    assert payload["status"] == "ok"
    assert payload["readonly"] is True
    assert payload["series_kind"] == "actual_dominant"
    assert payload["contract"] is None
    assert payload["score_distribution"] == [70, 85, 100]
    assert payload["horizon_summary"] == {
        "1": {
            "horizon_bars": 1,
            "sample_count": 1,
            "reversal_returns": [0.1],
            "warning_mfe": [0.2],
            "warning_mae": [0.05],
        },
        "3": {
            "horizon_bars": 3,
            "sample_count": 1,
            "reversal_returns": [0.1],
            "warning_mfe": [0.2],
            "warning_mae": [0.05],
        },
        "5": {
            "horizon_bars": 5,
            "sample_count": 1,
            "reversal_returns": [0.1],
            "warning_mfe": [0.2],
            "warning_mae": [0.05],
        },
        "10": {
            "horizon_bars": 10,
            "sample_count": 0,
            "reversal_returns": [],
            "warning_mfe": [],
            "warning_mae": [],
        },
    }
    rendered = stdout.getvalue().lower()
    for forbidden in ("promotion", "recommendation", "profitability"):
        assert forbidden not in rendered


def test_mirror_composition_wraps_only_the_market_data_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_data = type(
        "MarketDataReader",
        (),
        {
            "query": lambda self, request: request,
            "query_actual_dominant_trading_days": lambda self, request: request,
            "query_contract_trading_days": lambda self, request: request,
        },
    )()
    sessions: list[object] = []

    def build_market_data(session: object) -> object:
        sessions.append(session)
        return market_data

    monkeypatch.setattr(
        market_data_composition,
        "build_market_data_service",
        build_market_data,
    )
    session = object()

    service = (
        market_data_composition.build_main_force_mirror_futures_research_service(
            session  # type: ignore[arg-type]
        )
    )

    assert isinstance(service, MainForceMirrorFuturesResearchService)
    assert service._market_data is market_data
    assert sessions == [session]
