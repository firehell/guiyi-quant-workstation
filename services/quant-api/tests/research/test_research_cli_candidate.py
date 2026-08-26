from __future__ import annotations

from contextlib import nullcontext
from datetime import date
import io
import json

import pytest

from app.guiyi_cli.main import build_parser
from app.guiyi_cli.main import main
from app.guiyi_cli.data_parser import CliUsageError
from app.research import composition as research_composition
from app.research.subing.subing_candidate_validation_service import (
    CandidateValidationRequest,
    SubingCandidateValidationService,
)
from research.research_cli_fixtures import (
    _FakeCandidateValidationService,
    _FakeNCandidateValidationService,
    _JDJ_CANDIDATES,
    _candidate_report,
    _n_candidate_report,
    _request,
)


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


def test_candidate_cli_real_composition_accepts_current_lifecycle_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        research_composition,
        "build_market_data_service",
        lambda _session: object(),
    )
    monkeypatch.setattr(
        SubingCandidateValidationService,
        "run",
        lambda _service, _request: _candidate_report(),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        _candidate_arguments(),
        session_factory=lambda: nullcontext(object()),
        candidate_validation_service_factory=(
            research_composition.build_subing_candidate_validation_service
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["formula_version"] == "subing_lifecycle_v2"


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
