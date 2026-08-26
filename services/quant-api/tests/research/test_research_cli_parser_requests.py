from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from decimal import Decimal
import io
import json

import pytest

from app.guiyi_cli.main import build_parser
from app.guiyi_cli.main import main
from app.guiyi_cli.research_payloads import _optional_decimal
from app.market_data.domain import BarFrequency
from app.research.n_structure.n_structure_research_service import (
    NStructureSegmentIdentityError,
    NStructureResearchRequest,
    NStructureResearchResult,
    NStructureSourceUnavailableError,
)
from app.market_data.price_outcome import PriceHorizonEvaluation
from app.research.subing.subing_calibration_service import (
    CalibrationMode,
    CalibrationPhase,
    SlopeThresholds,
    CalibrationResearchResult,
)
from app.market_data.subing_calibration import (
    CalibrationReport,
)
from app.research.subing.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)
from research.research_cli_fixtures import (
    _FakeResearchService,
    _arguments,
    _discovery_report,
    _evaluation,
    _horizon,
    _request,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, None),
        (Decimal("-0"), "0"),
        (Decimal("-0.000"), "0"),
        (Decimal("0.000"), "0"),
        (Decimal("12.3400"), "12.3400"),
    ),
)
def test_optional_decimal_canonicalizes_zero_without_changing_nonzero_scale(
    value: Decimal | None,
    expected: str | None,
) -> None:
    assert _optional_decimal(value) == expected


def _lifecycle_arguments() -> list[str]:
    return [
        "research",
        "subing-lifecycle",
        "--since",
        "2026-01-01",
        "--through",
        "2026-03-31",
    ]


def test_research_parser_exposes_only_the_retained_readonly_commands() -> None:
    parser = build_parser()
    domain_action = next(
        action for action in parser._actions if action.dest == "domain"
    )
    research_subparser = domain_action.choices["research"]
    command_action = next(
        action
        for action in research_subparser._actions
        if action.dest == "research_command"
    )

    assert tuple(command_action.choices) == (
        "subing-calibration",
        "subing-lifecycle",
        "n-structure",
    )


def _n_arguments() -> list[str]:
    return [
        "research",
        "n-structure",
        "--since",
        "2026-01-01",
        "--through",
        "2026-03-31",
    ]


def test_n_structure_request_parses_dates_and_normalizes_optional_symbol() -> None:
    request = _request([*_n_arguments(), "--symbol", " JM "])

    assert request == NStructureResearchRequest(
        since=date(2026, 1, 1),
        through=date(2026, 3, 31),
        symbol="jm",
    )


@pytest.mark.parametrize(
    "arguments",
    (
        [
            "research",
            "n-structure",
            "--since",
            "2026-04-01",
            "--through",
            "2026-03-31",
        ],
        [*_n_arguments(), "--policy-id", "anything"],
        [*_n_arguments(), "--symbol", "../jm"],
    ),
)
def test_invalid_n_structure_input_fails_closed_before_service_construction(
    arguments: list[str],
) -> None:
    calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        arguments,
        session_factory=lambda: nullcontext(object()),
        n_structure_research_service_factory=lambda session: calls.append(session),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.n-structure",
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_ARGUMENT_INVALID", "type": "CliUsageError"},
    }
    assert calls == []


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
            _arguments(phase="zero-band") + ["--slope-threshold-15m-bps", "1"],
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


def _validation_report(
    *, sample_count: int, product_counts: dict[str, int]
) -> CalibrationReport:
    return CalibrationReport(
        sample_count=sample_count,
        product_sample_counts=product_counts,
        threshold_evaluation=_evaluation("2.7500", sample_count=sample_count),
    )


class _FakeLifecycleResearchService:
    def __init__(self, result: SubingLifecycleResearchResult) -> None:
        self.result = result
        self.requests: list[LifecycleResearchRequest] = []

    def run(self, request: LifecycleResearchRequest) -> SubingLifecycleResearchResult:
        self.requests.append(request)
        return self.result


class _FakeNStructureResearchService:
    def __init__(self, result: NStructureResearchResult) -> None:
        self.result = result
        self.requests: list[NStructureResearchRequest] = []

    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult:
        self.requests.append(request)
        return self.result


class _FailingNStructureResearchService:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult:
        raise self.error


@pytest.mark.parametrize(
    "error",
    (NStructureSourceUnavailableError(), NStructureSegmentIdentityError()),
)
def test_n_structure_cli_preserves_stable_public_failure_code(
    error: Exception,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        _n_arguments(),
        session_factory=lambda: nullcontext(object()),
        n_structure_research_service_factory=lambda _session: (
            _FailingNStructureResearchService(error)
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.n-structure",
        "status": "error",
        "readonly": True,
        "error": {"code": error.code, "type": type(error).__name__},  # type: ignore[attr-defined]
    }


def test_n_structure_outputs_exact_readonly_price_only_payload() -> None:
    service = _FakeNStructureResearchService(
        NStructureResearchResult(
            products=("jm",),
            segment_count=2,
            evaluable_bar_count=20,
            confirmed_pivot_count=8,
            ambiguous_outside_reset_count=1,
            incomplete_attempt_replaced_count=2,
            completed_n_counts={"up": 3, "down": 2},
            n_break_counts={"n2_origin_broken": 2, "origin_broken": 1},
            range_band_reentry_count=2,
            structure_established_counts={"bull": 1, "bear": 1, "range": 1},
            structure_break_counts={"bull": 1, "bear": 0},
            horizon_summary={
                3: PriceHorizonEvaluation(
                    2,
                    Decimal("12.5"),
                    Decimal("25"),
                    Decimal("-5"),
                ),
                5: PriceHorizonEvaluation(0, None, None, None),
                8: PriceHorizonEvaluation(
                    1,
                    Decimal("30"),
                    Decimal("40"),
                    Decimal("-10"),
                ),
            },
        )
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [*_n_arguments(), "--symbol", "jm"],
        session_factory=lambda: nullcontext(object()),
        n_structure_research_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert service.requests == [
        NStructureResearchRequest(date(2026, 1, 1), date(2026, 3, 31), "jm")
    ]
    payload = json.loads(stdout.getvalue())
    assert payload == {
        "schema_version": 1,
        "command": "research.n-structure",
        "status": "ok",
        "readonly": True,
        "policy_id": "n_structure_5m_v1",
        "formula_version": "n_structure_v1",
        "research_only": True,
        "since": "2026-01-01",
        "through": "2026-03-31",
        "products": ["jm"],
        "segment_count": 2,
        "evaluable_bar_count": 20,
        "confirmed_pivot_count": 8,
        "ambiguous_outside_reset_count": 1,
        "incomplete_attempt_replaced_count": 2,
        "completed_n_counts": {"up": 3, "down": 2},
        "n_break_counts": {"n2_origin_broken": 2, "origin_broken": 1},
        "range_band_reentry_count": 2,
        "structure_established_counts": {"bull": 1, "bear": 1, "range": 1},
        "structure_break_counts": {"bull": 1, "bear": 0},
        "horizon_summary": {
            "3": {
                "sample_count": 2,
                "median_directional_return_bps": "12.5",
                "median_mfe_bps": "25",
                "median_mae_bps": "-5",
            },
            "5": {
                "sample_count": 0,
                "median_directional_return_bps": None,
                "median_mfe_bps": None,
                "median_mae_bps": None,
            },
            "8": {
                "sample_count": 1,
                "median_directional_return_bps": "30",
                "median_mfe_bps": "40",
                "median_mae_bps": "-10",
            },
        },
    }
    serialized = json.dumps(payload).lower()
    assert "ema21" not in serialized
    assert "profit" not in serialized
    assert "promotion" not in serialized


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
    service = _FakeResearchService(CalibrationResearchResult(("jm",), report, {}))

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
    report_factory = _discovery_report if mode == "discovery" else _validation_report
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
        assert (
            payload["cohorts"]["B"]["candidate_evaluations"][0]["threshold"] == "1.2300"
        )
    else:
        assert payload["cohorts"]["A"]["threshold_evaluation"]["threshold"] == "2.7500"
        assert payload["cohorts"]["B"]["threshold_evaluation"]["threshold"] == "2.7500"


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
