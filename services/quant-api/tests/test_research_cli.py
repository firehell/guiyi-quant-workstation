from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import io
import json
from types import MappingProxyType
from types import SimpleNamespace

import pytest

from app.guiyi_cli.main import build_parser
from app.guiyi_cli.main import main
from app.guiyi_cli.data_parser import CliUsageError
from app.guiyi_cli.research_commands import run_research_command
from app.guiyi_cli.research_payloads import _optional_decimal
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
from app.market_data.domain import BarFrequency, SeriesKind
from guiyi_quant.indicators.main_force_mirror_v2 import MainForceMirrorV2Point
from app.research.main_force.main_force_mirror_v2_research_service import (
    MainForceMirrorV2ForensicPoint,
    MainForceMirrorV2GroupSpread,
    MainForceMirrorV2HorizonSummary,
    MainForceMirrorV2ResearchRequest,
    MainForceMirrorV2ResearchResult,
    MainForceMirrorV2SequenceFact,
    MainForceMirrorV2SequenceProfileSummary,
    MainForceMirrorV2SensitivitySummary,
)
from app.research.jdj.jdj_events import (
    JdjDirection,
    JdjSetupKind,
    JdjTrendFollowTriggerEvent,
    _canonical_trend_follow_event_id,
)
from app.research.jdj.jdj_research import JdjResearchRequest, JdjResearchResult
from app.research.jdj.jdj_candidate_validation import (
    JdjCandidateValidationReport,
    JdjCandidateWindowKind,
    JdjProspectiveOosResult,
    JdjProspectiveOosStatus,
    JdjRollingCandidateFold,
    project_jdj_window,
    summarize_jdj_rolling_stability,
)
from app.research.robustness.multi_candidate_robustness_policy import (
    MultiCandidateRobustnessRequest,
)
from app.research.robustness.jdj_robustness import (
    JdjActive60RobustnessRequest,
    JdjRobustnessStatus,
    load_jdj_active60_robustness_protocol,
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
    HorizonEvaluation,
    ThresholdEvaluation,
)
from app.research.subing.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)
from app.research.subing.subing_candidate_validation_service import (
    CandidateValidationRequest,
)
from app.research.candidate_convergence.artifact_source import (
    FiveCandidateDossierSourceError,
)
from app.research.candidate_convergence.five_candidate_dossier import (
    FiveCandidateDossierRequest,
    load_five_candidate_dossier_protocol,
)
from app.research.candidate_convergence.five_candidate_dossier_service import (
    FiveCandidateResearchDossierService,
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


def test_research_parser_exposes_only_the_eight_readonly_commands() -> None:
    parser = build_parser()
    domain_action = next(
        action for action in parser._actions if action.dest == "domain"
    )
    research_parser = domain_action.choices["research"]
    command_action = next(
        action
        for action in research_parser._actions
        if action.dest == "research_command"
    )

    assert set(command_action.choices) == {
        "candidate-dossier",
        "candidate-robustness",
        "candidate-validation",
        "jdj-1m",
        "main-force-mirror-v2",
        "n-structure",
        "subing-calibration",
        "subing-lifecycle",
    }
    assert "main-force-mirror-v2" in command_action.choices


_JDJ_CANDIDATES = (
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)


def _jdj_arguments(
    *,
    candidate: str = _JDJ_CANDIDATES[0],
) -> list[str]:
    return [
        "research",
        "jdj-1m",
        "--candidate",
        candidate,
        "--symbol",
        " JM ",
        "--since",
        "2026-01-01",
        "--through",
        "2026-03-31",
    ]


@pytest.mark.parametrize("candidate_id", _JDJ_CANDIDATES)
def test_jdj_parser_builds_exact_frozen_request(candidate_id: str) -> None:
    request = _request(_jdj_arguments(candidate=candidate_id))

    assert request == JdjResearchRequest(
        since=date(2026, 1, 1),
        through=date(2026, 3, 31),
        symbol="jm",
        candidate_id=candidate_id,
    )


@pytest.mark.parametrize(
    "flag",
    (
        "--ema-period",
        "--volume-multiple",
        "--timeout-bars",
        "--trend-method",
        "--key-level-distance",
    ),
)
def test_jdj_parser_rejects_runtime_formula_flags(flag: str) -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args([*_jdj_arguments(), flag, "1"])


def test_jdj_parser_rejects_non_candidate_identity() -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(_jdj_arguments(candidate="other_candidate"))


def _jdj_horizon() -> PriceHorizonEvaluation:
    return PriceHorizonEvaluation(
        1,
        Decimal("1.2500"),
        Decimal("2.500"),
        Decimal("-0.750"),
    )


def _jdj_event() -> JdjTrendFollowTriggerEvent:
    segment_start = date(2026, 1, 1)
    reaction_at = datetime(2026, 1, 5, 1, 1, tzinfo=UTC)
    observed_at = reaction_at + timedelta(minutes=1)
    trigger_level = Decimal("105.00")
    return JdjTrendFollowTriggerEvent(
        event_id=_canonical_trend_follow_event_id(
            candidate_id=_JDJ_CANDIDATES[0],
            symbol="jm",
            contract="JM2605",
            segment_start_trading_day=segment_start,
            direction=JdjDirection.LONG,
            reaction_at=reaction_at,
            observed_at=observed_at,
            trigger_level=trigger_level,
        ),
        source_kind="jdj_1m",
        setup_kind=JdjSetupKind.TREND_FOLLOW,
        candidate_id=_JDJ_CANDIDATES[0],
        source_event_kind="jdj_trend_follow_triggered",
        direction=JdjDirection.LONG,
        symbol="jm",
        contract="JM2605",
        segment_start_trading_day=segment_start,
        trading_day=date(2026, 1, 5),
        observed_at=observed_at,
        segment_bar_index=2,
        trend_snapshot_observed_at=reaction_at - timedelta(minutes=1),
        reaction_at=reaction_at,
        ema20_at_reaction=Decimal("100.00"),
        trigger_level=trigger_level,
        observation_close=Decimal("106.00"),
    )


def _jdj_result(*, events: bool = True) -> JdjResearchResult:
    event_values = (_jdj_event(),) if events else ()
    return JdjResearchResult(
        candidate_id=_JDJ_CANDIDATES[0],
        source_event_kind="jdj_trend_follow_triggered",
        products=("jm",),
        segment_count=1,
        evaluable_bar_count=100,
        trigger_count_long=len(event_values),
        trigger_count_short=0,
        horizon_summary={
            3: _jdj_horizon(),
            5: _jdj_horizon(),
            8: _jdj_horizon(),
            20: _jdj_horizon(),
        },
        events=event_values,
    )


class _FakeJdjResearchService:
    def __init__(self, result: JdjResearchResult) -> None:
        self.result = result
        self.requests: list[JdjResearchRequest] = []

    def run(self, request: JdjResearchRequest) -> JdjResearchResult:
        self.requests.append(request)
        return self.result


def test_jdj_source_renderer_is_readonly_deterministic_and_decimal_safe() -> None:
    request = _request(_jdj_arguments())
    payload = run_research_command(
        request,
        _FakeJdjResearchService(_jdj_result()),
    )

    assert payload["command"] == "research.jdj-1m"
    assert payload["readonly"] is True
    assert payload["research_only"] is True
    assert payload["policy_id"] == "jdj_1m_policy_v1"
    assert payload["formula_version"] == "jdj_1m_v1"
    assert tuple(payload["horizon_summary"]) == ("3", "5", "8", "20")
    assert payload["horizon_summary"]["20"] == {
        "sample_count": 1,
        "median_directional_return_bps": "1.2500",
        "median_mfe_bps": "2.500",
        "median_mae_bps": "-0.750",
    }
    assert payload["events"] == [
        {
            "event_id": _jdj_event().event_id,
            "source_kind": "jdj_1m",
            "setup_kind": "trend_follow",
            "candidate_id": _JDJ_CANDIDATES[0],
            "source_event_kind": "jdj_trend_follow_triggered",
            "direction": "long",
            "symbol": "jm",
            "contract": "JM2605",
            "segment_start_trading_day": "2026-01-01",
            "trading_day": "2026-01-05",
            "observed_at": "2026-01-05T01:02:00+00:00",
            "segment_bar_index": 2,
            "trend_snapshot_observed_at": "2026-01-05T01:00:00+00:00",
            "reaction_at": "2026-01-05T01:01:00+00:00",
            "ema20_at_reaction": "100.00",
            "trigger_level": "105.00",
            "observation_close": "106.00",
        }
    ]
    json.dumps(payload)


def test_jdj_source_cli_uses_only_dedicated_readonly_factory() -> None:
    service = _FakeJdjResearchService(_jdj_result())
    unrelated_calls: list[str] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        _jdj_arguments(),
        session_factory=lambda: nullcontext(object()),
        manager_factory=lambda _session: unrelated_calls.append("manager"),
        live_service_factory=lambda _session: unrelated_calls.append("live"),
        alert_runtime_factory=lambda: unrelated_calls.append("alert"),
        alert_canary_sender_factory=lambda: unrelated_calls.append(
            "notification"
        ),
        research_service_factory=lambda _session: unrelated_calls.append(
            "calibration"
        ),
        lifecycle_research_service_factory=lambda _session: unrelated_calls.append(
            "lifecycle"
        ),
        candidate_validation_service_factory=lambda _session: unrelated_calls.append(
            "subing_candidate"
        ),
        n_candidate_validation_service_factory=lambda _session: unrelated_calls.append(
            "n_candidate"
        ),
        jdj_research_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert unrelated_calls == []
    assert service.requests == [_request(_jdj_arguments())]
    assert json.loads(stdout.getvalue())["command"] == "research.jdj-1m"


def _jdj_candidate_report() -> JdjCandidateValidationReport:
    source = _jdj_result(events=False)
    retrospective = project_jdj_window(
        window_id="retrospective",
        window_kind=JdjCandidateWindowKind.RETROSPECTIVE,
        since=date(2023, 1, 1),
        through=date(2026, 8, 20),
        source=source,
    )
    fold = JdjRollingCandidateFold(
        fold_id="fold_01",
        reference=project_jdj_window(
            window_id="fold_01_reference",
            window_kind=JdjCandidateWindowKind.ROLLING_REFERENCE,
            since=date(2023, 1, 1),
            through=date(2023, 12, 31),
            source=source,
        ),
        test=project_jdj_window(
            window_id="fold_01_test",
            window_kind=JdjCandidateWindowKind.ROLLING_TEST,
            since=date(2024, 1, 1),
            through=date(2024, 3, 31),
            source=source,
        ),
    )
    folds = (fold,)
    return JdjCandidateValidationReport(
        schema_version=1,
        candidate_id=_JDJ_CANDIDATES[0],
        source_event_kind="jdj_trend_follow_triggered",
        policy_id="jdj_1m_policy_v1",
        formula_version="jdj_1m_v1",
        protocol_id="jdj_candidate_validation_v1",
        research_only=True,
        symbol="jm",
        retrospective=retrospective,
        rolling_folds=folds,
        rolling_stability=summarize_jdj_rolling_stability(folds),
        prospective_oos=JdjProspectiveOosResult(
            status=JdjProspectiveOosStatus.PENDING,
            first_trading_day=date(2026, 8, 24),
            through=date(2026, 8, 21),
            result=None,
        ),
        quality_flags=(
            "PROSPECTIVE_OOS_PENDING",
            "ROLLING_FOLD_WITHOUT_EVENT",
        ),
    )


class _FakeJdjCandidateValidationService:
    def __init__(self, report: JdjCandidateValidationReport) -> None:
        self.report = report
        self.requests: list[CandidateValidationRequest] = []

    def run(
        self,
        request: CandidateValidationRequest,
    ) -> JdjCandidateValidationReport:
        self.requests.append(request)
        return self.report


def test_jdj_candidate_renderer_precedes_generic_candidate_fallback() -> None:
    request = CandidateValidationRequest(
        candidate_id=_JDJ_CANDIDATES[0],
        protocol_id="jdj_candidate_validation_v1",
        symbol="jm",
        through=date(2026, 8, 21),
    )
    payload = run_research_command(
        request,
        _FakeJdjCandidateValidationService(_jdj_candidate_report()),
    )

    assert payload["command"] == "research.candidate-validation"
    assert payload["readonly"] is True
    assert payload["research_only"] is True
    assert payload["source_event_kind"] == "jdj_trend_follow_triggered"
    assert payload["rolling_stability"] == {
        "fold_count": 1,
        "folds_with_events": 0,
        "event_count_min": 0,
        "event_count_max": 0,
        "event_count_median": "0",
    }
    assert tuple(payload["retrospective"]["horizon_summary"]) == (
        "3",
        "5",
        "8",
        "20",
    )
    assert payload["retrospective"]["horizon_summary"]["20"][
        "median_directional_return_bps"
    ] == "1.2500"
    assert payload["prospective_oos"] == {
        "status": "pending",
        "first_trading_day": "2026-08-24",
        "through": "2026-08-21",
        "result": None,
    }
    json.dumps(payload)


def test_jdj_candidate_cli_routes_all_exact_ids_to_typed_factory() -> None:
    for candidate_id in _JDJ_CANDIDATES:
        report = _jdj_candidate_report()
        if candidate_id != _JDJ_CANDIDATES[0]:
            report = replace(
                report,
                candidate_id=candidate_id,
                source_event_kind={
                    _JDJ_CANDIDATES[1]: "jdj_trend_reentry_6_triggered",
                    _JDJ_CANDIDATES[2]: "jdj_key_level_breakout_triggered",
                }[candidate_id],
            )
        service = _FakeJdjCandidateValidationService(report)
        factory_calls: list[tuple[object, str]] = []
        stdout = io.StringIO()

        code = main(
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
            ],
            session_factory=lambda: nullcontext(object()),
            jdj_candidate_validation_service_factory=(
                lambda session, selected: (
                    factory_calls.append((session, selected)) or service
                )
            ),
            stdout=stdout,
            stderr=io.StringIO(),
        )

        assert code == 0
        assert len(factory_calls) == 1
        assert factory_calls[0][1] == candidate_id
        assert service.requests[0].candidate_id == candidate_id
        assert json.loads(stdout.getvalue())["candidate_id"] == candidate_id


def test_jdj_candidate_cross_pair_reaches_identity_error_before_source_run() -> None:
    factory_calls: list[tuple[object, str]] = []
    stderr = io.StringIO()

    code = main(
        [
            "research",
            "candidate-validation",
            "--candidate",
            _JDJ_CANDIDATES[0],
            "--protocol",
            "candidate_validation_v1",
            "--symbol",
            "jm",
            "--through",
            "2026-08-21",
        ],
        session_factory=lambda: nullcontext(object()),
        jdj_candidate_validation_service_factory=lambda session, candidate: (
            factory_calls.append((session, candidate))
        ),
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert factory_calls == []
    assert json.loads(stderr.getvalue())["error"] == {
        "code": "CANDIDATE_VALIDATION_IDENTITY_MISMATCH",
        "type": "CandidateValidationIdentityError",
    }


@pytest.mark.parametrize(
    ("protocol_id", "expected"),
    (
        (
            "multi_candidate_robustness_v1",
            MultiCandidateRobustnessRequest(
                protocol_id="multi_candidate_robustness_v1"
            ),
        ),
        (
            "jdj_active60_robustness_v1",
            JdjActive60RobustnessRequest(
                protocol_id="jdj_active60_robustness_v1"
            ),
        ),
    ),
)
def test_candidate_robustness_parser_builds_concrete_protocol_request(
    protocol_id: str,
    expected: MultiCandidateRobustnessRequest | JdjActive60RobustnessRequest,
) -> None:
    request = _request(
        [
            "research",
            "candidate-robustness",
            "--protocol",
            protocol_id,
        ]
    )

    assert request == expected


@pytest.mark.parametrize(
    "flag", ("--since", "--through", "--symbol", "--candidate", "--products")
)
def test_candidate_robustness_parser_rejects_runtime_selection_flags(flag: str) -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                "research",
                "candidate-robustness",
                "--protocol",
                "multi_candidate_robustness_v1",
                flag,
                "value",
            ]
        )


@pytest.mark.parametrize(
    "flag",
    ("--since", "--through", "--symbols", "--threshold", "--score", "--rank"),
)
def test_jdj_active60_robustness_parser_rejects_runtime_selection_flags(
    flag: str,
) -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                "research",
                "candidate-robustness",
                "--protocol",
                "jdj_active60_robustness_v1",
                flag,
                "value",
            ]
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


def test_candidate_parser_accepts_exactly_five_candidate_and_three_protocol_ids() -> None:
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




def _mirror_arguments(
    *,
    series_kind: str = "actual_dominant",
    contract: str | None = None,
    forensic: bool = False,
) -> list[str]:
    arguments = [
        "research",
        "main-force-mirror-v2",
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
    if forensic:
        arguments.append("--forensic")
    return arguments


class _FakeMirrorResearchService:
    def __init__(self, result: MainForceMirrorV2ResearchResult) -> None:
        self.result = result
        self.requests: list[MainForceMirrorV2ResearchRequest] = []

    def run(
        self,
        request: MainForceMirrorV2ResearchRequest,
    ) -> MainForceMirrorV2ResearchResult:
        self.requests.append(request)
        return self.result


def _mirror_result() -> MainForceMirrorV2ResearchResult:
    summary = MainForceMirrorV2HorizonSummary(
        horizon_bars=5,
        sample_count=2,
        median_directional_return=Decimal("0.1"),
        median_reversal_return=Decimal("-0.1"),
        hit_rate=Decimal("1"),
        median_mfe=Decimal("0.12"),
        median_mae=Decimal("0.02"),
    )
    spread = MainForceMirrorV2GroupSpread(
        horizon_bars=5,
        top_group="member_strong_aligned",
        bottom_group="member_divergent",
        directional_return_spread=Decimal("0.15"),
        top_sample_count=2,
        bottom_sample_count=1,
    )
    empty_profiles = {
        profile_id: MainForceMirrorV2SequenceProfileSummary(
            profile_id=profile_id,  # type: ignore[arg-type]
            yearly={},
            by_side={"long": {}, "short": {}},
            pooled={},
        )
        for profile_id in ("balanced", "fast", "slow", "loose", "strict")
    }
    return MainForceMirrorV2ResearchResult(
        indicator_code="main_force_mirror_v2",
        indicator_version="futures-member-research-v2",
        parameters_hash="fixture-parameters",
        research_protocol="main_force_mirror_v2_retrospective_v1",
        evaluation_classification="retrospective_walk_forward_diagnostic",
        requested_since=date(2023, 1, 1),
        requested_through=date(2026, 8, 18),
        prospective_oos_starts_after=date(2026, 8, 20),
        member_dataset_id="fixture-member-v1",
        products=("jm",),
        member_coverage=Decimal("0.75"),
        caution_ready_bars=40,
        caution_events=2,
        caution_events_per_1000_ready_bars=Decimal("50"),
        yearly={
            2026: {"jm": {"long_build": {"instant_pressure": {5: summary}}}}
        },
        by_product={
            "jm": {"long_build": {"instant_pressure": {5: summary}}}
        },
        pooled={"instant_pressure": {5: summary}},
        top_bottom_spreads={5: spread},
        sensitivity={
            Decimal("2.0"): MainForceMirrorV2SensitivitySummary(
                member_strength_threshold=Decimal("2.0"),
                by_product={"jm": {5: summary}},
                pooled={5: summary},
            )
        },
        sequence_profiles=empty_profiles,
        forensic_points=None,
    )


def _mirror_forensic_fixture() -> MainForceMirrorV2ForensicPoint:
    point = MainForceMirrorV2Point(
        bar_end=datetime(2026, 3, 23, 7, tzinfo=UTC),
        trading_day=date(2026, 3, 23),
        physical_contract="JM2609",
        pressure_ready=True,
        pressure_state="short_build",
        instant_pressure=-95.0,
        accumulated_ready=True,
        accumulated_pressure=-70.0,
        caution_ready=True,
        caution="long_chase_caution",
        caution_conflict=False,
        long_caution_score=70.0,
        short_caution_score=0.0,
        caution_reason_codes=("LONG_UPPER_EXTREME",),
        member=None,
        unavailable_reason=None,
        price_impulse=-2.0,
        clv=0.2,
        volume_ratio=2.1,
        delta_oi=1000.0,
        oi_impulse=2.5,
        range_position=0.05,
    )
    fact = MainForceMirrorV2SequenceFact(
        index=0,
        current_side="short",
        pressure_state="short_build",
        instant_pressure=-95.0,
        accumulated_pressure=-70.0,
        active_peak_index=10,
        active_peak_side="long",
        active_peak_instant_pressure=100.0,
        active_peak_accumulated_pressure=80.0,
        bars_since_active_peak=2,
        decay_ratio=Decimal("1.875"),
        installed_peak_index=12,
        installed_peak_side="short",
        installed_peak_instant_pressure=-95.0,
        installed_peak_accumulated_pressure=-70.0,
        peak_seen=True,
        decay_seen=True,
        liquidation_seen=False,
        opposite_build_seen=True,
        accumulated_reversal_seen=True,
        state_transition="long_liquidation->short_build",
    )
    return MainForceMirrorV2ForensicPoint(point=point, sequence=fact)


def test_mirror_forensic_flag_is_explicit_and_defaults_off() -> None:
    normal = _request(_mirror_arguments())
    forensic = _request(_mirror_arguments(forensic=True))

    assert normal.forensic is False
    assert forensic.forensic is True


def test_mirror_request_rejects_non_boolean_forensic() -> None:
    with pytest.raises(ValueError, match="forensic must be boolean"):
        MainForceMirrorV2ResearchRequest(
            symbol="jm",
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            contract=None,
            frequency=BarFrequency.H1,
            since=date(2023, 1, 1),
            through=date(2026, 8, 18),
            forensic="yes",  # type: ignore[arg-type]
        )


def test_mirror_default_payload_adds_profiles_without_forensic_points() -> None:
    request = _request(_mirror_arguments())
    payload = run_research_command(
        request, _FakeMirrorResearchService(_mirror_result())
    )

    assert tuple(payload["sequence_profiles"]) == (
        "balanced",
        "fast",
        "slow",
        "loose",
        "strict",
    )
    assert "forensic_points" not in payload


def test_mirror_forensic_payload_is_balanced_readonly_dual_fact_detail() -> None:
    request = _request(_mirror_arguments(forensic=True))
    result = replace(
        _mirror_result(), forensic_points=(_mirror_forensic_fixture(),)
    )
    payload = run_research_command(request, _FakeMirrorResearchService(result))

    assert len(payload["forensic_points"]) == 1
    rendered = payload["forensic_points"][0]
    assert rendered["physical_contract"] == "JM2609"
    assert rendered["pressure_state"] == "short_build"
    assert rendered["sequence"]["profile_id"] == "balanced"
    assert rendered["sequence"]["active_peak_side"] == "long"
    assert rendered["sequence"]["installed_peak_side"] == "short"
    assert rendered["sequence"]["peak_seen"] is True
    assert rendered["member_status"] == "unavailable"


def test_mirror_request_parses_exact_actual_dominant_and_contract_modes() -> None:
    dominant = _request(_mirror_arguments())
    contract = _request(_mirror_arguments(series_kind="contract", contract="jm2609"))

    assert dominant == MainForceMirrorV2ResearchRequest(
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        contract=None,
        frequency=BarFrequency.H1,
        since=date(2023, 1, 1),
        through=date(2026, 8, 18),
    )
    assert contract == MainForceMirrorV2ResearchRequest(
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
        main_force_mirror_v2_research_service_factory=lambda session: calls.append(
            session
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.main-force-mirror-v2",
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
        research_service_factory=lambda _session: unrelated_calls.append("calibration"),
        lifecycle_research_service_factory=lambda _session: unrelated_calls.append(
            "lifecycle"
        ),
        candidate_validation_service_factory=lambda _session: unrelated_calls.append(
            "candidate"
        ),
        main_force_mirror_v2_research_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert unrelated_calls == []
    assert service.requests == [
        MainForceMirrorV2ResearchRequest(
            symbol="jm",
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            contract=None,
            frequency=BarFrequency.H1,
            since=date(2023, 1, 1),
            through=date(2026, 8, 18),
        )
    ]
    payload = json.loads(stdout.getvalue())
    assert payload["command"] == "research.main-force-mirror-v2"
    assert payload["status"] == "ok"
    assert payload["readonly"] is True
    assert payload["research_only"] is True
    assert payload["series_kind"] == "actual_dominant"
    assert payload["contract"] is None
    assert payload["research_protocol"] == "main_force_mirror_v2_retrospective_v1"
    assert payload["evaluation_classification"] == (
        "retrospective_walk_forward_diagnostic"
    )
    assert payload["member_coverage"] == "0.75"
    assert payload["caution_events_per_1000_ready_bars"] == "50"
    assert payload["yearly"] == {
        "2026": {
            "jm": {
                "long_build": {
                    "instant_pressure": {
                        "5": {
                            "horizon_bars": 5,
                            "sample_count": 2,
                            "median_directional_return": "0.1",
                            "median_reversal_return": "-0.1",
                            "hit_rate": "1",
                            "median_mfe": "0.12",
                            "median_mae": "0.02",
                        }
                    }
                }
            }
        }
    }
    assert payload["sensitivity"]["2.0"]["member_strength_threshold"] == "2.0"
    rendered = stdout.getvalue().lower()
    for forbidden in (
        "promotion",
        "recommendation",
        "profitability",
        "sharpe",
        "equity",
    ):
        assert forbidden not in rendered


def test_mirror_cli_renders_undefined_event_rate_as_json_null() -> None:
    result = replace(
        _mirror_result(),
        caution_ready_bars=0,
        caution_events=0,
        caution_events_per_1000_ready_bars=None,
    )
    request = MainForceMirrorV2ResearchRequest(
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        contract=None,
        frequency=BarFrequency.H1,
        since=date(2023, 1, 1),
        through=date(2026, 8, 18),
    )

    payload = run_research_command(request, _FakeMirrorResearchService(result))

    assert payload["caution_events_per_1000_ready_bars"] is None




def _robustness_report() -> SimpleNamespace:
    horizon = SimpleNamespace(
        sample_count=2,
        median_directional_return_bps=Decimal("1.25"),
        median_mfe_bps=Decimal("2.5"),
        median_mae_bps=Decimal("-0.5"),
    )
    temporal = SimpleNamespace(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        candidate_protocol_id="candidate_validation_v1",
        source_kind="subing_lifecycle",
        anchor_symbol="jm",
        retrospective_since=date(2023, 1, 1),
        retrospective_through=date(2026, 8, 18),
        event_unit="entry_confirmed",
        retrospective_event_count=11,
        rolling_fold_count=10,
        folds_with_events=9,
        test_event_count_min=0,
        test_event_count_median=Decimal("4.5"),
        test_event_count_max=9,
        prospective_status="pending",
        prospective_first_trading_day=date(2026, 8, 20),
        prospective_through=date(2026, 8, 19),
        horizon_semantics="same_trading_day_only",
        horizon_summary={3: horizon, 5: horizon, 8: horizon},
        source_quality_flags=("PROSPECTIVE_OOS_PENDING",),
    )
    row = SimpleNamespace(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        source_kind="subing_lifecycle",
        symbol="jm",
        status=SimpleNamespace(value="available"),
        reason_code=None,
        event_count=1,
        evaluable_count=2,
        evaluable_unit="5m_ready_boundary",
        event_rate_per_1000_evaluable=Decimal("500"),
        horizon_semantics="same_trading_day_only",
        horizon_summary={3: horizon, 5: horizon, 8: horizon},
    )
    sign = SimpleNamespace(
        symbols_with_samples=1,
        positive_median_return_symbols=1,
        zero_median_return_symbols=0,
        negative_median_return_symbols=0,
    )
    summary = SimpleNamespace(
        candidate_id="subing_lifecycle_v2_candidate_v1",
        product_count=60,
        available_product_count=60,
        unavailable_product_count=0,
        symbols_with_events=1,
        symbols_without_events=59,
        event_rate_available_count=60,
        event_rate_min=Decimal("0"),
        event_rate_median=Decimal("0"),
        event_rate_max=Decimal("500"),
        horizon_sign_summary={3: sign, 5: sign, 8: sign},
    )
    relationship = SimpleNamespace(
        source_candidate_id="subing_lifecycle_v2_candidate_v1",
        target_candidate_id="n_structure_5m_candidate_v1",
        source_event_count=1,
        target_event_count=1,
        exact_same_direction_count=0,
        exact_opposite_direction_count=0,
        within_3_same_direction_source_count=1,
        within_5_same_direction_source_count=1,
        within_8_same_direction_source_count=1,
        nearest_match_count_within_8=1,
        signed_distance_min=1,
        signed_distance_median=Decimal("1"),
        signed_distance_max=1,
        target_earlier_count=0,
        target_same_boundary_count=0,
        target_later_count=1,
        same_trading_day_count=1,
        cross_trading_day_count=0,
    )
    return SimpleNamespace(
        schema_version=1,
        protocol_id="multi_candidate_robustness_v1",
        frozen_at=datetime.fromisoformat("2026-08-20T21:33:00+08:00"),
        readonly=True,
        research_only=True,
        anchor_symbol="jm",
        common_since=date(2023, 1, 1),
        common_through=date(2026, 8, 18),
        temporal_dossiers=(temporal,),
        cross_symbol_results=(row,),
        cross_symbol_summaries=(summary,),
        relationships=(relationship,),
        metric_compatibility_flags=("EVALUABLE_UNIT_DIFFERS",),
        quality_flags=("SYMBOL_WITHOUT_EVENT",),
    )


class _FakeRobustnessService:
    def __init__(self) -> None:
        self.requests: list[object] = []

    def run(self, request: object) -> SimpleNamespace:
        self.requests.append(request)
        return _robustness_report()


def _jdj_robustness_report() -> SimpleNamespace:
    protocol = load_jdj_active60_robustness_protocol()
    horizon = SimpleNamespace(
        sample_count=2,
        historical_positive_outcome_rate=Decimal("0.5"),
        median_directional_return_bps=Decimal("1.2500"),
        median_mfe_bps=Decimal("2.500"),
        median_mae_bps=Decimal("-0.750"),
    )
    yearly = {
        year: SimpleNamespace(
            event_count=2,
            horizon_sample_count={value: 2 for value in (3, 5, 8, 20)},
            horizon_positive_outcome_rate={
                value: Decimal("0.5") for value in (3, 5, 8, 20)
            },
            horizon_median_directional_return_bps={
                value: Decimal("1.2500") for value in (3, 5, 8, 20)
            },
        )
        for year in (2023, 2024, 2025, 2026)
    }
    rows = tuple(
        SimpleNamespace(
            candidate_id=candidate_id,
            symbol=symbol,
            sector=next(
                sector
                for sector, symbols in protocol.sector_groups.items()
                if symbol in symbols
            ),
            status=JdjRobustnessStatus.AVAILABLE,
            reason_code=None,
            observed_since=date(2023, 1, 1),
            observed_through=date(2026, 8, 20),
            evaluable_bar_count=4,
            event_count=2,
            long_event_count=1,
            short_event_count=1,
            event_rate_per_1000_evaluable=Decimal("500.00"),
            horizon_summary={value: horizon for value in (3, 5, 8, 20)},
            yearly=yearly,
        )
        for candidate_id in _JDJ_CANDIDATES
        for symbol in protocol.cross_symbol_products
    )
    sector_horizon = SimpleNamespace(
        symbols_with_samples=1,
        positive_median_symbol_count=1,
        zero_median_symbol_count=0,
        negative_median_symbol_count=0,
        median_of_symbol_median_return_bps=Decimal("1.2500"),
    )
    sectors = tuple(
        SimpleNamespace(
            candidate_id=candidate_id,
            sector=sector,
            symbol_count=len(symbols),
            available_symbol_count=len(symbols),
            symbols_with_events=len(symbols),
            horizon_summary={
                value: sector_horizon for value in (3, 5, 8, 20)
            },
        )
        for candidate_id in _JDJ_CANDIDATES
        for sector, symbols in protocol.sector_groups.items()
    )
    return SimpleNamespace(
        schema_version=1,
        command=(
            "guiyi research candidate-robustness "
            "--protocol jdj_active60_robustness_v1"
        ),
        protocol_id="jdj_active60_robustness_v1",
        frozen_at=datetime.fromisoformat("2026-08-21T20:34:00+08:00"),
        research_only=True,
        readonly=True,
        common_since=date(2023, 1, 1),
        common_through=date(2026, 8, 20),
        embargo_trading_days=(date(2026, 8, 21),),
        prospective_first_trading_day=date(2026, 8, 24),
        prospective_consumed=False,
        candidate_ids=_JDJ_CANDIDATES,
        cross_symbol_results=rows,
        sector_summaries=sectors,
        quality_flags=("SHORT_HISTORY_PRESENT",),
    )


class _FakeJdjRobustnessService:
    def __init__(self) -> None:
        self.requests: list[JdjActive60RobustnessRequest] = []

    def run(
        self,
        request: JdjActive60RobustnessRequest,
    ) -> SimpleNamespace:
        self.requests.append(request)
        return _jdj_robustness_report()


def test_jdj_robustness_cli_selects_its_concrete_factory() -> None:
    service = _FakeJdjRobustnessService()
    old_factory_calls: list[object] = []
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "research",
            "candidate-robustness",
            "--protocol",
            "jdj_active60_robustness_v1",
        ],
        session_factory=lambda: nullcontext(object()),
        multi_candidate_robustness_service_factory=lambda session: (
            old_factory_calls.append(session)
        ),
        jdj_active60_robustness_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert old_factory_calls == []
    assert service.requests == [
        JdjActive60RobustnessRequest("jdj_active60_robustness_v1")
    ]
    assert json.loads(stdout.getvalue())["protocol_id"] == (
        "jdj_active60_robustness_v1"
    )


def test_jdj_robustness_renderer_preserves_exact_matrix_and_decimal_strings() -> None:
    payload = run_research_command(
        JdjActive60RobustnessRequest("jdj_active60_robustness_v1"),
        _FakeJdjRobustnessService(),
    )

    assert tuple(payload) == (
        "schema_version",
        "command",
        "protocol_id",
        "frozen_at",
        "research_only",
        "readonly",
        "common_retrospective",
        "embargo_trading_days",
        "prospective_oos",
        "prospective_consumed",
        "candidate_ids",
        "cross_symbol_results",
        "sector_summaries",
        "quality_flags",
    )
    assert payload["command"] == (
        "guiyi research candidate-robustness "
        "--protocol jdj_active60_robustness_v1"
    )
    assert payload["common_retrospective"] == {
        "since": "2023-01-01",
        "through": "2026-08-20",
    }
    assert payload["embargo_trading_days"] == ["2026-08-21"]
    assert payload["prospective_oos"] == {
        "first_trading_day": "2026-08-24"
    }
    assert payload["prospective_consumed"] is False
    assert payload["candidate_ids"] == list(_JDJ_CANDIDATES)
    rows = payload["cross_symbol_results"]
    assert isinstance(rows, list)
    assert len(rows) == 180
    assert rows[0]["event_rate_per_1000_evaluable"] == "500.00"
    assert rows[0]["horizon_summary"]["20"] == {
        "sample_count": 2,
        "historical_positive_outcome_rate": "0.5",
        "median_directional_return_bps": "1.2500",
        "median_mfe_bps": "2.500",
        "median_mae_bps": "-0.750",
    }
    assert rows[0]["yearly"]["2026"]["horizon_summary"]["20"] == {
        "sample_count": 2,
        "historical_positive_outcome_rate": "0.5",
        "median_directional_return_bps": "1.2500",
    }
    sectors = payload["sector_summaries"]
    assert isinstance(sectors, list)
    assert sectors[0]["horizon_summary"]["20"] == {
        "symbols_with_samples": 1,
        "positive_median_symbol_count": 1,
        "zero_median_symbol_count": 0,
        "negative_median_symbol_count": 0,
        "median_of_symbol_median_return_bps": "1.2500",
    }
    assert payload["quality_flags"] == ["SHORT_HISTORY_PRESENT"]
    json.dumps(payload)


def test_jdj_robustness_payload_recursively_excludes_forbidden_keys() -> None:
    payload = run_research_command(
        JdjActive60RobustnessRequest("jdj_active60_robustness_v1"),
        _FakeJdjRobustnessService(),
    )
    forbidden = {
        "score",
        "rank",
        "winner",
        "decision",
        "pnl",
        "order",
        "fill",
        "position",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {str(key).lower() for key in value} | set().union(
                *(keys(item) for item in value.values())
            )
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert keys(payload).isdisjoint(forbidden)


def _calibration_contract_payload() -> dict[str, object]:
    request = _request([*_arguments(), "--symbol", "jm"])
    report = _discovery_report(sample_count=1, product_counts={"jm": 1})
    return run_research_command(
        request,
        _FakeResearchService(CalibrationResearchResult(("jm",), report, {})),
    )


def _subing_candidate_contract_payload() -> dict[str, object]:
    return run_research_command(
        CandidateValidationRequest(
            candidate_id="subing_lifecycle_v2_candidate_v1",
            protocol_id="candidate_validation_v1",
            symbol="jm",
            through=date(2026, 8, 19),
        ),
        _FakeCandidateValidationService(_candidate_report()),
    )


def _n_candidate_contract_payload() -> dict[str, object]:
    return run_research_command(
        CandidateValidationRequest(
            candidate_id="n_structure_5m_candidate_v1",
            protocol_id="n_structure_validation_v1",
            symbol="jm",
            through=date(2026, 8, 20),
        ),
        _FakeNCandidateValidationService(_n_candidate_report()),
    )


def _robustness_contract_payload() -> dict[str, object]:
    return run_research_command(
        MultiCandidateRobustnessRequest("multi_candidate_robustness_v1"),
        _FakeRobustnessService(),
    )


def _payload_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(
            *(_payload_keys(item) for item in value.values())
        )
    if isinstance(value, list):
        return set().union(*(_payload_keys(item) for item in value))
    return set()


@pytest.mark.parametrize(
    "payload_factory",
    (
        _calibration_contract_payload,
        _subing_candidate_contract_payload,
        _n_candidate_contract_payload,
        _robustness_contract_payload,
    ),
)
def test_research_payloads_exclude_automatic_promotion_profit_and_ranking_fields(
    payload_factory,
) -> None:
    forbidden = {
        "approved",
        "best",
        "better_candidate",
        "account_return",
        "drop",
        "expected_profit",
        "keep",
        "pass_strategy",
        "performance",
        "profitability",
        "promote",
        "rank",
        "score",
        "trade",
        "winner",
    }

    assert _payload_keys(payload_factory()).isdisjoint(forbidden)


def test_robustness_renderer_uses_canonical_fields_and_is_byte_deterministic() -> None:
    encoded_once = json.dumps(
        _robustness_contract_payload(),
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded_twice = json.dumps(
        _robustness_contract_payload(),
        sort_keys=True,
        separators=(",", ":"),
    )

    assert encoded_once == encoded_twice
    payload = _robustness_contract_payload()
    assert payload["cross_symbol_summaries"][0]["symbols_with_events"] == 1
    assert payload["cross_symbol_summaries"][0]["symbols_without_events"] == 59
    assert (
        payload["cross_symbol_summaries"][0]["horizon_sign_summary"]["3"]
        ["symbols_with_samples"]
        == 1
    )


def test_candidate_robustness_cli_dispatches_readonly_deterministic_json() -> None:
    service = _FakeRobustnessService()
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        [
            "research",
            "candidate-robustness",
            "--protocol",
            "multi_candidate_robustness_v1",
        ],
        session_factory=lambda: nullcontext(object()),
        multi_candidate_robustness_service_factory=lambda _session: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert service.requests == [
        MultiCandidateRobustnessRequest("multi_candidate_robustness_v1")
    ]
    payload = json.loads(stdout.getvalue())
    direct_payload = run_research_command(
        MultiCandidateRobustnessRequest("multi_candidate_robustness_v1"),
        _FakeRobustnessService(),
    )
    assert tuple(direct_payload) == (
        "schema_version",
        "command",
        "status",
        "readonly",
        "research_only",
        "protocol_id",
        "frozen_at",
        "anchor_symbol",
        "common_retrospective",
        "temporal_dossiers",
        "cross_symbol_results",
        "cross_symbol_summaries",
        "relationships",
        "metric_compatibility_flags",
        "quality_flags",
    )
    assert payload["command"] == "research.candidate-robustness"
    assert payload["readonly"] is payload["research_only"] is True
    assert payload["cross_symbol_results"][0]["event_rate_per_1000_evaluable"] == "500"
    assert payload["relationships"][0]["signed_distance_median"] == "1"


def test_candidate_dossier_parser_builds_exact_request() -> None:
    args = build_parser().parse_args(
        [
            "research",
            "candidate-dossier",
            "--protocol",
            "five_candidate_research_dossier_v1",
        ]
    )

    request = build_research_request(args)

    assert request == FiveCandidateDossierRequest(
        "five_candidate_research_dossier_v1"
    )


@pytest.mark.parametrize(
    "extra_arguments",
    (
        ("--since", "2023-01-01"),
        ("--through", "2026-08-20"),
        ("--symbol", "jm"),
        ("--candidate", "subing_lifecycle_v2_candidate_v1"),
        ("--products", "jm"),
        ("--threshold", "1"),
        ("--score", "1"),
        ("--rank", "1"),
    ),
)
def test_candidate_dossier_parser_rejects_out_of_contract_flags(
    extra_arguments: tuple[str, str],
) -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                "research",
                "candidate-dossier",
                "--protocol",
                "five_candidate_research_dossier_v1",
                *extra_arguments,
            ]
        )


def test_candidate_dossier_parser_rejects_unknown_protocol() -> None:
    with pytest.raises(CliUsageError):
        build_parser().parse_args(
            [
                "research",
                "candidate-dossier",
                "--protocol",
                "five_candidate_research_dossier_v2",
            ]
        )


def _five_candidate_dossier_report():
    return FiveCandidateResearchDossierService(
        load_five_candidate_dossier_protocol()
    ).run(FiveCandidateDossierRequest("five_candidate_research_dossier_v1"))


class _FakeFiveCandidateDossierService:
    def __init__(self, report=None, error: Exception | None = None) -> None:
        self.report = report
        self.error = error
        self.requests: list[FiveCandidateDossierRequest] = []

    def run(self, request: FiveCandidateDossierRequest):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.report


def test_candidate_dossier_cli_never_enters_session_context() -> None:
    service = _FakeFiveCandidateDossierService(_five_candidate_dossier_report())
    stdout = io.StringIO()
    stderr = io.StringIO()

    def fail_session_factory():
        pytest.fail("candidate-dossier must not construct a Session")

    code = main(
        [
            "research",
            "candidate-dossier",
            "--protocol",
            "five_candidate_research_dossier_v1",
        ],
        session_factory=fail_session_factory,
        candidate_dossier_service_factory=lambda: service,
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert service.requests == [
        FiveCandidateDossierRequest("five_candidate_research_dossier_v1")
    ]
    assert json.loads(stdout.getvalue())["command"] == (
        "guiyi research candidate-dossier "
        "--protocol five_candidate_research_dossier_v1"
    )


def _contains_matrix_sized_list(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_matrix_sized_list(item) for item in value.values())
    if isinstance(value, list):
        return len(value) in {60, 120, 180, 300} or any(
            _contains_matrix_sized_list(item) for item in value
        )
    return False


def test_candidate_dossier_payload_is_compact_ordered_and_byte_deterministic() -> None:
    report = _five_candidate_dossier_report()
    first_relationship = dict(
        report.comparability_pairs[0].existing_relationship_reference or {}
    )
    relationships = list(first_relationship["relationships"])
    first_row = dict(relationships[0])
    first_row["signed_distance_median"] = Decimal("-0.000")
    relationships[0] = MappingProxyType(first_row)
    first_relationship["relationships"] = tuple(relationships)
    object.__setattr__(
        report.comparability_pairs[0],
        "existing_relationship_reference",
        MappingProxyType(first_relationship),
    )
    service = _FakeFiveCandidateDossierService(report)
    request = FiveCandidateDossierRequest("five_candidate_research_dossier_v1")

    first = run_research_command(request, service)
    second = run_research_command(request, service)
    first_bytes = json.dumps(first, separators=(",", ":"), ensure_ascii=False)
    second_bytes = json.dumps(second, separators=(",", ":"), ensure_ascii=False)

    assert first_bytes == second_bytes
    assert first["command"] == (
        "guiyi research candidate-dossier "
        "--protocol five_candidate_research_dossier_v1"
    )
    assert first["candidate_order"] == list(report.candidate_order)
    assert first["source_artifacts"] == [
        {"artifact_id": artifact.artifact_id}
        for artifact in report.source_artifacts
    ]
    assert [
        dossier["candidate_id"] for dossier in first["candidate_dossiers"]
    ] == list(report.candidate_order)
    assert [
        (pair["left_candidate_id"], pair["right_candidate_id"])
        for pair in first["comparability_pairs"]
    ] == [
        (pair.left_candidate_id, pair.right_candidate_id)
        for pair in report.comparability_pairs
    ]
    assert (
        first["comparability_pairs"][0]["existing_relationship_reference"]
        ["relationships"][0]["signed_distance_median"]
        == "0"
    )
    assert not _contains_matrix_sized_list(first)
    assert "expected_sha256" not in first_bytes
    assert '"path"' not in first_bytes


def test_candidate_dossier_payload_preserves_required_non_matrix_evidence() -> None:
    report = _five_candidate_dossier_report()
    payload = run_research_command(
        FiveCandidateDossierRequest("five_candidate_research_dossier_v1"),
        _FakeFiveCandidateDossierService(report),
    )
    dossier = payload["candidate_dossiers"][2]

    assert tuple(dossier) == (
        "candidate_id",
        "identity",
        "baseline",
        "robustness",
        "evidence_references",
    )
    assert tuple(dossier["robustness"]) == (
        "artifact_id",
        "protocol_id",
        "retrospective",
        "matrix_cell_count",
        "available_symbol_count",
        "unavailable_symbol_count",
        "unavailable_reason_counts",
        "zero_event_symbol_count",
        "zero_sample_symbol_count_by_horizon",
        "sector_evidence",
        "yearly_evidence",
        "quality_flags",
    )
    assert len(dossier["robustness"]["sector_evidence"]) == 10
    assert dossier["robustness"]["sector_evidence"][0]["sector"] == (
        "agriculture"
    )
    assert dossier["robustness"]["sector_evidence"][0]["candidate_id"] == (
        "jdj_trend_follow_1m_candidate_v1"
    )
    assert len(dossier["robustness"]["yearly_evidence"]) == 49
    assert dossier["robustness"]["yearly_evidence"][0]["symbol"] == "a"
    assert dossier["robustness"]["yearly_evidence"][0]["yearly"]["2023"][
        "event_count"
    ] == 1843

    references = dossier["evidence_references"]
    assert tuple(references) == (
        "temporal",
        "cross_symbol",
        "sector",
        "yearly",
        "horizon",
        "quality",
    )
    assert references["temporal"]["window_id"] == "retrospective"
    assert references["temporal"]["evaluable_bar_count"] == 297224
    assert references["cross_symbol"] == {
        "artifact_id": "jdj_active60_robustness_v1",
        "matrix_cell_count": 60,
        "omitted": True,
    }
    assert len(references["sector"]) == 10
    assert len(references["yearly"]) == 49
    assert tuple(references["horizon"]) == ("20", "3", "5", "8")
    assert references["horizon"]["3"] == {
        "median_directional_return_bps": "0",
        "median_mae_bps": "-11.08442675923552062198930752",
        "median_mfe_bps": "9.025270758122743682310469315",
        "sample_count": 7534,
    }
    assert references["quality"] == [
        "PROSPECTIVE_OOS_PENDING",
        "SOURCE_UNAVAILABLE_PRESENT",
        "SHORT_HISTORY_PRESENT",
    ]
    assert not _contains_matrix_sized_list(payload)


def test_candidate_dossier_source_error_is_stable_and_redacted() -> None:
    error = FiveCandidateDossierSourceError()
    error.args = (
        "/private/tmp/source.json "
        '{"source":"secret"} '
        + "a" * 64,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "research",
            "candidate-dossier",
            "--protocol",
            "five_candidate_research_dossier_v1",
        ],
        session_factory=lambda: pytest.fail("Session construction is forbidden"),
        candidate_dossier_service_factory=lambda: (
            _FakeFiveCandidateDossierService(error=error)
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "research.candidate-dossier",
        "status": "error",
        "readonly": True,
        "error": {
            "code": "FIVE_CANDIDATE_DOSSIER_SOURCE_INVALID",
            "type": "FiveCandidateDossierSourceError",
        },
    }
    assert "/private/tmp/source.json" not in stderr.getvalue()
    assert '"source":"secret"' not in stderr.getvalue()
    assert "a" * 64 not in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()
