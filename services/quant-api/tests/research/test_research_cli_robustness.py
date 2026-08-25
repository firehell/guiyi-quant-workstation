from __future__ import annotations

from contextlib import nullcontext
from datetime import date, datetime
from decimal import Decimal
import io
import json
from types import SimpleNamespace

import pytest

from app.guiyi_cli.main import main
from app.guiyi_cli.research_commands import run_research_command
from app.research.robustness.multi_candidate_robustness_policy import (
    MultiCandidateRobustnessRequest,
)
from app.research.robustness.jdj_robustness import (
    JdjActive60RobustnessRequest,
    JdjRobustnessStatus,
    load_jdj_active60_robustness_protocol,
)
from app.research.subing.subing_calibration_service import (
    CalibrationResearchResult,
)
from app.research.subing.subing_candidate_validation_service import (
    CandidateValidationRequest,
)
from research.research_cli_fixtures import (
    _FakeCandidateValidationService,
    _FakeNCandidateValidationService,
    _FakeResearchService,
    _JDJ_CANDIDATES,
    _arguments,
    _candidate_report,
    _discovery_report,
    _n_candidate_report,
    _request,
)

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
            horizon_summary={value: sector_horizon for value in (3, 5, 8, 20)},
        )
        for candidate_id in _JDJ_CANDIDATES
        for sector, symbols in protocol.sector_groups.items()
    )
    return SimpleNamespace(
        schema_version=1,
        command=(
            "guiyi research candidate-robustness --protocol jdj_active60_robustness_v1"
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
        "guiyi research candidate-robustness --protocol jdj_active60_robustness_v1"
    )
    assert payload["common_retrospective"] == {
        "since": "2023-01-01",
        "through": "2026-08-20",
    }
    assert payload["embargo_trading_days"] == ["2026-08-21"]
    assert payload["prospective_oos"] == {"first_trading_day": "2026-08-24"}
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
        payload["cross_symbol_summaries"][0]["horizon_sign_summary"]["3"][
            "symbols_with_samples"
        ]
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
