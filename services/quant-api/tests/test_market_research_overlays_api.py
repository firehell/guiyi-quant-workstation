from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
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
