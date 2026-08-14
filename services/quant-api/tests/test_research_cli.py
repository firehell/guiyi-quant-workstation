from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from decimal import Decimal
import io
import json

import pytest

from app.guiyi_cli.main import build_parser
from app.guiyi_cli.main import main
from app.guiyi_cli.research_commands import build_research_request
from app.market_data.domain import BarFrequency
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


def test_research_parser_exposes_only_subing_calibration() -> None:
    parser = build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")
    research_parser = domain_action.choices["research"]
    command_action = next(
        action
        for action in research_parser._actions
        if action.dest == "research_command"
    )

    assert set(command_action.choices) == {"subing-calibration"}


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
