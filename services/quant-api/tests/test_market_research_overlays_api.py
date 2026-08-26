from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import research_overlays as research_overlay_schemas
from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.operational_universe import ActiveUniverseError
from app.market_data.subing_calibration import SubingCalibrationError
from app.market_data.subing_lifecycle import ConfirmationSource
from app.market_data.subing_lifecycle_policy import SubingLifecyclePolicyError
from app.market_data.subing_strategy.contracts import SubingStrategyDirection
from app.market_data.subing_strategy.current_service import (
    SubingStrategyCurrentSourceIdentityError,
)
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyContextIdentityError,
)
from app.market_data.subing_strategy.policy import SubingStrategyPolicyError
from app.market_data.subing_strategy.service import (
    SubingStrategyActiveProductError,
    SubingStrategySegmentIdentityError,
    SubingStrategySourceUnavailableError,
)
from app.research.jdj.jdj_events import JdjDirection
from app.research.jdj_strategy.engine import JdjAction, JdjActionKind
from app.research.jdj_strategy.service import (
    JdjStrategyContextInvalidError,
    JdjStrategyProfileUnavailableError,
    JdjStrategySegmentIdentityError,
    JdjStrategySessionIdentityError,
)
from app.research.n_structure.n_structure_pattern import (
    NDirection,
    NRangeBandRole,
)
from app.research.n_structure.n_structure_research_service import (
    NStructureProductScopeError,
    NStructureRangeBandResearchFact,
    NStructureSegmentIdentityError,
    NStructureSourceUnavailableError,
)
from app.research.n_structure.n_structure_policy import (
    NStructurePolicyError,
    load_n_structure_policy,
)


class _StrategyService:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    def history(self, request: object):
        if self.failure is not None:
            raise self.failure
        action = SimpleNamespace(
            action_id="subing-action:open",
            episode_id="subing-episode:one",
            strategy_id="subing_strategy_v1",
            formula_version="subing_strategy_15m_v1",
            kind=SimpleNamespace(value="open_long"),
            symbol="jm",
            contract="JM2609",
            trading_day=date(2026, 8, 3),
            segment_start_trading_day=date(2026, 8, 3),
            opportunity_id="subing-opportunity:one",
            decision_at=datetime(2026, 8, 3, 2, 15, tzinfo=UTC),
            effective_open_at=datetime(2026, 8, 3, 2, 15, tzinfo=UTC),
            effective_bar_end=datetime(2026, 8, 3, 2, 30, tzinfo=UTC),
            reference_price=Decimal("100.5"),
            fill_basis=SimpleNamespace(value="next_bar_open"),
            confirmation_source=ConfirmationSource.FORMAL_V1,
            reason_codes=(),
            direction_context_source_day=date(2026, 7, 31),
            direction_context_target_day=date(2026, 8, 3),
            bound_reference_pivot=None,
        )
        return SimpleNamespace(
            request=request,
            policy=SimpleNamespace(
                strategy_id="subing_strategy_v1",
                formula_version="subing_strategy_15m_v1",
                research_only=True,
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                decision_frequency=BarFrequency.M15,
                lifecycle_policy_id="subing_lifecycle_v2_research_v1",
                allowed_confirmation_sources=(ConfirmationSource.FORMAL_V1,),
            ),
            resolved_cutoff=datetime(2026, 8, 3, 2, 30, tzinfo=UTC),
            segment_summaries=(
                SimpleNamespace(
                    contract="JM2609",
                    start_trading_day=date(2026, 8, 3),
                    end_trading_day=date(2026, 8, 20),
                    loaded_through=date(2026, 8, 3),
                    bar_count_1m=15,
                    bar_count_5m=3,
                    bar_count_15m=1,
                    initial_position=SimpleNamespace(value="flat"),
                    final_position=SimpleNamespace(value="long"),
                    terminal_bar_end=None,
                    pending_action=False,
                ),
            ),
            actions=(action,),
            episodes=(
                SimpleNamespace(
                    episode_id="subing-episode:one",
                    direction=SimpleNamespace(value="long"),
                    entry_action=action,
                    exit_action=None,
                    state=SimpleNamespace(value="open"),
                    holding_bar_count=1,
                    reference_change_percent=None,
                    current_reference_change_percent=Decimal("1.25"),
                    latest_reference_price=Decimal("101.75625"),
                    exit_reason_codes=(),
                    structure_exit_available=False,
                ),
            ),
            context_unavailable=(
                SimpleNamespace(
                    symbol="jm",
                    target_trading_day=date(2026, 8, 4),
                    source_trading_day=date(2026, 8, 3),
                    direction=SubingStrategyDirection.UNAVAILABLE,
                    reason_codes=("D1_UNAVAILABLE",),
                    daily_bar_end=None,
                    hourly_bar_end=None,
                    physical_contract="JM2609",
                ),
            ),
            cache_state="miss",
        )


class _CurrentStrategyService:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    def current(self, request: object, _now: datetime):
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(
            policy=SimpleNamespace(
                strategy_id="subing_strategy_v1",
                formula_version="subing_strategy_15m_v1",
            ),
            request=request,
            contract="JM2605",
            segment_start_trading_day=date(2026, 8, 1),
            source_mode="canonical_live",
            cutoff=datetime(2026, 8, 4, 2, 30, tzinfo=UTC),
            position_state=SimpleNamespace(value="flat"),
            pending_action=SimpleNamespace(
                kind=SimpleNamespace(value="open_long"),
                decision_at=datetime(2026, 8, 4, 2, 15, tzinfo=UTC),
                opportunity_id="subing-opportunity:one",
                reason_codes=(),
            ),
            current_episode=None,
            latest_completed_episode=None,
            direction_context=SimpleNamespace(
                symbol="jm",
                target_trading_day=date(2026, 8, 4),
                source_trading_day=date(2026, 8, 3),
                direction=SubingStrategyDirection.LONG_ONLY,
                reason_codes=("D1_H1_LONG_ALIGNED",),
                daily_bar_end=datetime(2026, 8, 3, 7, 0, tzinfo=UTC),
                hourly_bar_end=datetime(2026, 8, 3, 7, 0, tzinfo=UTC),
                physical_contract="JM2605",
            ),
        )


def test_subing_strategy_current_returns_public_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_current_service",
        lambda _session: _CurrentStrategyService(),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/current",
        params={
            "series_kind": "actual_dominant",
            "symbol": "JM",
            "frequency": "15m",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "strategy_id": "subing_strategy_v1",
        "formula_version": "subing_strategy_15m_v1",
        "series_kind": "actual_dominant",
        "symbol": "jm",
        "frequency": "15m",
        "contract": "JM2605",
        "segment_start_trading_day": "2026-08-01",
        "source_mode": "canonical_live",
        "cutoff": "2026-08-04T02:30:00Z",
        "position_state": "flat",
        "pending_action": {
            "kind": "open_long",
            "decision_at": "2026-08-04T02:15:00Z",
            "opportunity_id": "subing-opportunity:one",
            "reason_codes": [],
        },
        "current_episode": None,
        "latest_completed_episode": None,
        "direction_context": {
            "symbol": "jm",
            "target_trading_day": "2026-08-04",
            "source_trading_day": "2026-08-03",
            "direction": "long_only",
            "reason_codes": ["D1_H1_LONG_ALIGNED"],
            "daily_bar_end": "2026-08-03T07:00:00Z",
            "hourly_bar_end": "2026-08-03T07:00:00Z",
            "physical_contract": "JM2605",
        },
    }


def test_subing_strategy_current_rejects_unsupported_frequency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_current_service",
        lambda _session: pytest.fail("invalid request must not execute service"),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/current",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "INVALID_SUBING_STRATEGY_CURRENT_REQUEST"}
    }


def test_subing_strategy_current_maps_source_identity_failure_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_current_service",
        lambda _session: _CurrentStrategyService(
            SubingStrategyCurrentSourceIdentityError()
        ),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/current",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "15m",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "SUBING_STRATEGY_CURRENT_SOURCE_IDENTITY_INVALID"}
    }


def test_subing_strategy_current_maps_composition_source_failure_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.market_data.operational_universe import OperationalUniverseError

    def fail_build(_session):
        raise OperationalUniverseError()

    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_current_service",
        fail_build,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/current",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "15m",
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "OPERATIONAL_UNIVERSE_INVALID"}
    }


def test_subing_strategy_history_returns_actions_complete_episodes_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_historical_service",
        lambda _session: _StrategyService(),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "JM",
            "frequency": "15m",
            "since": "2026-08-03",
            "through": "2026-08-20",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["symbol"] == "jm"
    assert payload["policy"]["strategy_id"] == "subing_strategy_v1"
    assert payload["resolved_cutoff"] == "2026-08-03T02:30:00Z"
    assert payload["actions"][0]["kind"] == "open_long"
    assert payload["actions"][0]["effective_open_at"] == "2026-08-03T02:15:00Z"
    assert payload["actions"][0]["reference_price"] == "100.5"
    assert payload["segment_summaries"][0]["bar_count_1m"] == 15
    assert payload["episodes"][0]["entry_action"]["action_id"] == ("subing-action:open")
    assert payload["episodes"][0]["state"] == "open"
    assert payload["context_unavailable"][0]["direction"] == "unavailable"
    assert payload["cache_state"] == "miss"


def test_old_subing_historical_signal_route_is_retired() -> None:
    path = "/api/v1/market/research/" + "subing/history"

    assert path not in app.openapi()["paths"]
    assert TestClient(app).get(path).status_code == 404


@pytest.mark.parametrize(
    "params",
    (
        {"series_kind": "continuous", "frequency": "15m"},
        {"series_kind": "actual_dominant", "frequency": "5m"},
        {"series_kind": "actual_dominant", "frequency": "15m", "symbol": "1"},
        {
            "series_kind": "actual_dominant",
            "frequency": "15m",
            "since": "2026-08-21",
            "through": "2026-08-20",
        },
    ),
)
def test_subing_strategy_history_rejects_invalid_request(
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, str],
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_historical_service",
        lambda _session: pytest.fail("invalid request must not execute service"),
        raising=False,
    )
    request_params = {
        "series_kind": "actual_dominant",
        "symbol": "jm",
        "frequency": "15m",
        "since": "2026-08-03",
        "through": "2026-08-20",
        **params,
    }

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/history",
        params=request_params,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "INVALID_SUBING_STRATEGY_REQUEST"}}


@pytest.mark.parametrize(
    "failure",
    (
        SubingStrategyPolicyError(),
        SubingCalibrationError(),
        SubingLifecyclePolicyError(),
        ActiveUniverseError(),
        SubingStrategyActiveProductError(),
        SubingStrategySourceUnavailableError(),
        SubingStrategySegmentIdentityError(),
        SubingStrategyContextIdentityError(),
    ),
)
def test_subing_strategy_history_maps_typed_failures_before_value_error(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_strategy_historical_service",
        lambda _session: _StrategyService(failure),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "15m",
            "since": "2026-08-03",
            "through": "2026-08-20",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": failure.code}}


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/market/research/n-structure/history",
        "/api/v1/market/research/jdj/history",
    ),
)
def test_internal_n_and_raw_jdj_have_no_public_historical_route(path: str) -> None:
    assert path not in app.openapi()["paths"]

    response = TestClient(app).get(
        path,
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "1m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 404


def test_n_structure_bands_route_exposes_exact_read_only_query_contract() -> None:
    path = "/api/v1/market/research/n-structure/bands"

    assert path in app.openapi()["paths"]
    operation = app.openapi()["paths"][path]["get"]
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "series_kind",
        "symbol",
        "frequency",
        "since",
        "through",
    ]


class _NStructureBandService:
    def range_bands(self, request: object):
        assert getattr(request, "symbol") == "jm"
        return (
            NStructureRangeBandResearchFact(
                band_id="n-1",
                symbol="jm",
                contract="JM2609",
                segment_start_trading_day=date(2026, 8, 3),
                completion_trading_day=date(2026, 8, 4),
                direction=NDirection.UP,
                role=NRangeBandRole.SUPPORT_REFERENCE,
                n1_at=datetime(2026, 8, 4, 1, 30, tzinfo=UTC),
                completed_at=datetime(2026, 8, 4, 2, 15, tzinfo=UTC),
                completion_level=Decimal("101.5"),
                lower=Decimal("99.5"),
                upper=Decimal("101.5"),
                first_reentered_at=datetime(2026, 8, 4, 2, 30, tzinfo=UTC),
                invalidated_at=datetime(2026, 8, 4, 3, 0, tzinfo=UTC),
                expanded_until=datetime(2026, 8, 4, 3, 0, tzinfo=UTC),
            ),
        )


def test_n_structure_bands_returns_policy_lineage_and_exact_decimal_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = load_n_structure_policy()
    injected: list[object] = []
    monkeypatch.setattr(
        "app.research.historical_overlay_api.load_n_structure_policy",
        lambda: policy,
    )
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_n_structure_research_service",
        lambda _session, **kwargs: (
            injected.append(kwargs["policy"]) or _NStructureBandService()
        ),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/n-structure/bands",
        params={
            "series_kind": "actual_dominant",
            "symbol": "JM",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 200
    assert injected == [policy]
    assert response.json() == {
        "request": {
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
        "policy": {
            "policy_id": "n_structure_5m_v1",
            "formula_version": "n_structure_v1",
            "source_timeframe": "5m",
            "research_only": True,
        },
        "bands": [
            {
                "band_id": "n-1",
                "contract": "JM2609",
                "segment_start_trading_day": "2026-08-03",
                "completion_trading_day": "2026-08-04",
                "direction": "up",
                "role": "support_reference",
                "n1_at": "2026-08-04T01:30:00Z",
                "completed_at": "2026-08-04T02:15:00Z",
                "completion_level": "101.5",
                "lower": "99.5",
                "upper": "101.5",
                "first_reentered_at": "2026-08-04T02:30:00Z",
                "invalidated_at": "2026-08-04T03:00:00Z",
                "expanded_until": "2026-08-04T03:00:00Z",
            }
        ],
    }


@pytest.mark.parametrize(
    ("series_kind", "frequency"),
    (
        ("continuous", "5m"),
        ("contract", "5m"),
        ("actual_dominant", "15m"),
        ("actual_dominant", "1m"),
    ),
)
def test_n_structure_bands_reject_unsupported_identity_before_service(
    monkeypatch: pytest.MonkeyPatch,
    series_kind: str,
    frequency: str,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_n_structure_research_service",
        lambda _session, **_kwargs: pytest.fail(
            "unsupported identity must not build service"
        ),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/n-structure/bands",
        params={
            "series_kind": series_kind,
            "symbol": "jm",
            "frequency": frequency,
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "INVALID_N_STRUCTURE_BAND_REQUEST"}}


def test_n_structure_bands_reject_invalid_request_window_as_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_n_structure_research_service",
        lambda *_args, **_kwargs: pytest.fail("invalid request must not build service"),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/n-structure/bands",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
            "since": "2026-08-04",
            "through": "2026-08-03",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "INVALID_N_STRUCTURE_BAND_REQUEST"}}


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (
            NStructureSegmentIdentityError(),
            "N_STRUCTURE_SEGMENT_IDENTITY_INVALID",
        ),
        (
            NStructureSourceUnavailableError(),
            "N_STRUCTURE_SOURCE_UNAVAILABLE",
        ),
        (
            NStructureProductScopeError(),
            "N_STRUCTURE_PRODUCT_NOT_ACTIVE",
        ),
    ),
)
def test_n_structure_bands_map_source_identity_failures_to_409(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: str,
) -> None:
    class _FailingService:
        def range_bands(self, _request: object):
            raise failure

    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_n_structure_research_service",
        lambda _session, **_kwargs: _FailingService(),
    )
    response = TestClient(app).get(
        "/api/v1/market/research/n-structure/bands",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": expected_code}}


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (ActiveUniverseError(), "ACTIVE_UNIVERSE_INVALID"),
        (NStructurePolicyError(), "N_STRUCTURE_POLICY_INVALID"),
    ),
)
def test_n_structure_bands_map_builder_or_policy_failures_to_409(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: str,
) -> None:
    if isinstance(failure, NStructurePolicyError):
        monkeypatch.setattr(
            "app.research.historical_overlay_api.load_n_structure_policy",
            lambda: (_ for _ in ()).throw(failure),
        )
    else:
        monkeypatch.setattr(
            "app.research.historical_overlay_api.build_n_structure_research_service",
            lambda _session, **_kwargs: (_ for _ in ()).throw(failure),
        )
    response = TestClient(app).get(
        "/api/v1/market/research/n-structure/bands",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": expected_code}}


def test_public_overlay_schemas_keep_only_retained_projection_families() -> None:
    for name in (
        "NStructureHistoricalRequestOut",
        "NStructureHistoricalEventOut",
        "NStructureHistoricalResponse",
        "JdjHistoricalRequestOut",
        "JdjHistoricalEventOut",
        "JdjHistoricalResponse",
    ):
        assert not hasattr(research_overlay_schemas, name)

    assert hasattr(research_overlay_schemas, "SubingStrategyHistoricalResponse")
    assert hasattr(research_overlay_schemas, "SubingStrategyCurrentResponse")
    assert hasattr(research_overlay_schemas, "JdjStrategyHistoricalResponse")
    assert hasattr(research_overlay_schemas, "NStructureBandResponse")


def test_jdj_strategy_history_route_exposes_exact_read_only_query_contract() -> None:
    path = "/api/v1/market/research/jdj-strategy/history"

    assert path in app.openapi()["paths"]
    operation = app.openapi()["paths"][path]["get"]
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "series_kind",
        "symbol",
        "frequency",
        "since",
        "through",
    ]


class _JdjStrategyService:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.requests: list[object] = []

    def history(self, request: object) -> SimpleNamespace:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        contract = f"{getattr(request, 'symbol', 'jm').upper()}2701"
        return SimpleNamespace(
            request=request,
            reference_execution=True,
            actions=(
                JdjAction(
                    event_id="jdj-action-entry-1",
                    episode_id="jdj-episode-1",
                    kind=JdjActionKind.ENTRY,
                    source_event_ids=("candidate-1", "candidate-2"),
                    primary_setup="key_level_breakout",
                    supporting_setups=("trend_follow",),
                    direction=JdjDirection.LONG,
                    contract=contract,
                    trading_day=date(2026, 8, 3),
                    segment_start_trading_day=date(2026, 8, 1),
                    decision_at=datetime(2026, 8, 3, 2, 15, tzinfo=UTC),
                    effective_bar_end=datetime(2026, 8, 3, 2, 16, tzinfo=UTC),
                    reference_price=Decimal("101.5"),
                    quantity=8,
                    position_quantity_after=8,
                    stop_price=Decimal("99.5"),
                    target_price=Decimal("106"),
                    reward_risk=Decimal("2.25"),
                    reason="ENTRY_FILLED",
                    fill_basis="limit_touch",
                ),
                JdjAction(
                    event_id="jdj-action-rejected-1",
                    episode_id=None,
                    kind=JdjActionKind.REJECTED,
                    source_event_ids=("candidate-3",),
                    primary_setup="trend_follow",
                    supporting_setups=(),
                    direction=JdjDirection.SHORT,
                    contract=contract,
                    trading_day=date(2026, 8, 3),
                    segment_start_trading_day=date(2026, 8, 1),
                    decision_at=datetime(2026, 8, 3, 2, 20, tzinfo=UTC),
                    effective_bar_end=None,
                    reference_price=None,
                    quantity=0,
                    position_quantity_after=8,
                    stop_price=Decimal("103"),
                    target_price=None,
                    reward_risk=None,
                    reason="OPEN_EPISODE_EVENT_REJECTED",
                    fill_basis=None,
                ),
            ),
        )


def test_jdj_strategy_history_returns_complete_reference_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_jdj_strategy_replay_service",
        lambda _session: _JdjStrategyService(),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/jdj-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "JM",
            "frequency": "1m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"] == {
        "series_kind": "actual_dominant",
        "symbol": "jm",
        "frequency": "1m",
        "since": "2026-08-03",
        "through": "2026-08-04",
    }
    assert payload["reference_execution"] is True
    assert [action["kind"] for action in payload["actions"]] == [
        "entry",
        "rejected",
    ]
    assert payload["actions"][0] == {
        "event_id": "jdj-action-entry-1",
        "episode_id": "jdj-episode-1",
        "kind": "entry",
        "source_event_ids": ["candidate-1", "candidate-2"],
        "primary_setup": "key_level_breakout",
        "supporting_setups": ["trend_follow"],
        "direction": "long",
        "contract": "JM2701",
        "trading_day": "2026-08-03",
        "segment_start_trading_day": "2026-08-01",
        "decision_at": "2026-08-03T02:15:00Z",
        "effective_bar_end": "2026-08-03T02:16:00Z",
        "reference_price": "101.5",
        "quantity": 8,
        "position_quantity_after": 8,
        "stop_price": "99.5",
        "target_price": "106",
        "reward_risk": "2.25",
        "reason": "ENTRY_FILLED",
        "fill_basis": "limit_touch",
    }
    assert payload["actions"][1]["effective_bar_end"] is None
    assert payload["actions"][1]["reference_price"] is None


def test_jdj_strategy_history_accepts_active_non_jm_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _JdjStrategyService()
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_jdj_strategy_replay_service",
        lambda _session: service,
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/jdj-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "RB",
            "frequency": "1m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 200
    assert response.json()["request"]["symbol"] == "rb"
    assert len(service.requests) == 1
    assert getattr(service.requests[0], "symbol") == "rb"


@pytest.mark.parametrize(
    ("series_kind", "symbol", "frequency"),
    (
        ("actual_dominant", "jm", "5m"),
        ("continuous", "jm", "1m"),
    ),
)
def test_jdj_strategy_history_rejects_unfrozen_profile_before_builder(
    monkeypatch: pytest.MonkeyPatch,
    series_kind: str,
    symbol: str,
    frequency: str,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_jdj_strategy_replay_service",
        lambda _session: pytest.fail("invalid profile must not build service"),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/jdj-strategy/history",
        params={
            "series_kind": series_kind,
            "symbol": symbol,
            "frequency": frequency,
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "JDJ_STRATEGY_PROFILE_UNAVAILABLE"}}


def test_jdj_strategy_history_maps_service_profile_unavailable_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _JdjStrategyService(JdjStrategyProfileUnavailableError())
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_jdj_strategy_replay_service",
        lambda _session: service,
        raising=False,
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/market/research/jdj-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "not_active",
            "frequency": "1m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert len(service.requests) == 1
    assert getattr(service.requests[0], "symbol") == "not_active"
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "JDJ_STRATEGY_PROFILE_UNAVAILABLE"}}


def test_jdj_strategy_history_maps_invalid_active_universe_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_session: object) -> None:
        raise ActiveUniverseError()

    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_jdj_strategy_replay_service",
        fail,
        raising=False,
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/market/research/jdj-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "rb",
            "frequency": "1m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "ACTIVE_UNIVERSE_INVALID"}}


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (
            JdjStrategyContextInvalidError(),
            "JDJ_STRATEGY_CONTEXT_INVALID",
        ),
        (
            JdjStrategySegmentIdentityError(),
            "JDJ_STRATEGY_SEGMENT_IDENTITY_INVALID",
        ),
        (
            JdjStrategySessionIdentityError(),
            "JDJ_STRATEGY_SESSION_IDENTITY_INVALID",
        ),
    ),
)
def test_jdj_strategy_history_maps_assembly_failures_to_typed_409(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_jdj_strategy_replay_service",
        lambda _session: _JdjStrategyService(failure),
        raising=False,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/jdj-strategy/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "1m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": expected_code}}
