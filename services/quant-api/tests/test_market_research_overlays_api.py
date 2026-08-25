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
from app.market_data.subing_historical_signal_service import (
    SubingHistoricalSignalDirection,
    SubingHistoricalSignalEvent,
    SubingHistoricalSignalRequest,
    SubingHistoricalSignalResult,
    SubingHistoricalSignalSegmentIdentityError,
    SubingHistoricalSignalSourceUnavailableError,
)
from app.research.jdj.jdj_events import JdjDirection
from app.research.jdj_strategy.engine import JdjAction, JdjActionKind
from app.research.jdj_strategy.service import (
    JdjStrategyContextInvalidError,
    JdjStrategyProfileUnavailableError,
    JdjStrategySegmentIdentityError,
    JdjStrategySessionIdentityError,
)


def test_subing_historical_overlay_route_exposes_exact_read_only_query_contract() -> None:
    path = "/api/v1/market/research/subing/history"

    assert path in app.openapi()["paths"]
    operation = app.openapi()["paths"][path]["get"]
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "series_kind",
        "symbol",
        "frequency",
        "since",
        "through",
    ]


class _Service:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    def history(self, request: SubingHistoricalSignalRequest):
        if self.failure is not None:
            raise self.failure
        return SubingHistoricalSignalResult(
            request=request,
            events=(
                SubingHistoricalSignalEvent(
                    event_id=(
                        "subing_entry_signal_v1|jm|JM2609|2026-08-03|"
                        "2026-08-03T02:15:00+00:00|15m|buy"
                    ),
                    bar_end=datetime(2026, 8, 3, 2, 15, tzinfo=UTC),
                    trading_day=date(2026, 8, 3),
                    contract="JM2609",
                    segment_start_trading_day=date(2026, 8, 3),
                    direction=SubingHistoricalSignalDirection.BUY,
                    trigger_timeframe=BarFrequency.M15,
                    lower_tf_confirmation=True,
                ),
            ),
        )


def test_subing_historical_overlay_returns_normalized_request_and_source_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        lambda _session: _Service(),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "JM",
            "frequency": "15m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "request": {
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "15m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
        "events": [
            {
                "event_id": (
                    "subing_entry_signal_v1|jm|JM2609|2026-08-03|"
                    "2026-08-03T02:15:00+00:00|15m|buy"
                ),
                "bar_end": "2026-08-03T02:15:00Z",
                "trading_day": "2026-08-03",
                "contract": "JM2609",
                "segment_start_trading_day": "2026-08-03",
                "direction": "buy",
                "trigger_timeframe": "15m",
                "lower_tf_confirmation": True,
            }
        ],
    }


@pytest.mark.parametrize(
    "params",
    (
        {"series_kind": "continuous", "frequency": "5m"},
        {"series_kind": "contract", "frequency": "15m"},
        {"series_kind": "actual_dominant", "frequency": "1m"},
    ),
)
def test_subing_historical_overlay_rejects_unsupported_identity(
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, str],
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        lambda _session: pytest.fail("invalid request must not execute service"),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
        params={
            **params,
            "symbol": "jm",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "INVALID_SUBING_HISTORICAL_REQUEST"}
    }


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (
            SubingHistoricalSignalSegmentIdentityError(),
            "SUBING_HISTORICAL_SEGMENT_IDENTITY_INVALID",
        ),
        (
            SubingHistoricalSignalSourceUnavailableError(),
            "SUBING_HISTORICAL_SOURCE_UNAVAILABLE",
        ),
    ),
)
def test_subing_historical_overlay_maps_source_identity_failures_to_409(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        lambda _session: _Service(failure),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
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


def test_subing_historical_overlay_maps_invalid_calibration_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        lambda _session: (_ for _ in ()).throw(SubingCalibrationError()),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
        params={
            "series_kind": SeriesKind.ACTUAL_DOMINANT.value,
            "symbol": "jm",
            "frequency": BarFrequency.M5.value,
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "SUBING_CALIBRATION_INVALID"}}


def test_subing_historical_overlay_maps_invalid_active_universe_to_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_session: object):
        raise ActiveUniverseError()

    monkeypatch.setattr(
        "app.api.market_research_overlays.build_subing_historical_signal_service",
        fail,
    )

    response = TestClient(app).get(
        "/api/v1/market/research/subing/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "ACTIVE_UNIVERSE_INVALID"}}


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


def test_public_overlay_schemas_keep_only_subing_and_jdj_strategy_families() -> None:
    for name in (
        "NStructureHistoricalRequestOut",
        "NStructureHistoricalEventOut",
        "NStructureHistoricalResponse",
        "JdjHistoricalRequestOut",
        "JdjHistoricalEventOut",
        "JdjHistoricalResponse",
    ):
        assert not hasattr(research_overlay_schemas, name)

    assert hasattr(research_overlay_schemas, "SubingHistoricalSignalResponse")
    assert hasattr(research_overlay_schemas, "JdjStrategyHistoricalResponse")


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
    assert response.json() == {
        "detail": {"code": "JDJ_STRATEGY_PROFILE_UNAVAILABLE"}
    }


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
    assert response.json() == {
        "detail": {"code": "JDJ_STRATEGY_PROFILE_UNAVAILABLE"}
    }


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
