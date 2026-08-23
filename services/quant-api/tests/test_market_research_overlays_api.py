from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
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
from app.research.n_structure.n_structure_pattern import NDirection
from app.research.n_structure.n_structure_research_service import (
    NStructureCompletionResearchEvent,
    NStructureResearchRequest,
    NStructureSegmentIdentityError,
    NStructureSourceUnavailableError,
)
from app.research.jdj.jdj_context import JdjContextError
from app.research.jdj.jdj_events import JdjDirection
from app.research.jdj.jdj_research import JdjSourceUnavailableError
from app.research.jdj_strategy.engine import JdjAction, JdjActionKind
from app.research.jdj_strategy.service import (
    JdjStrategyContextInvalidError,
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


def test_n_structure_historical_overlay_route_exposes_exact_read_only_query_contract() -> None:
    path = "/api/v1/market/research/n-structure/history"

    assert path in app.openapi()["paths"]
    operation = app.openapi()["paths"][path]["get"]
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "series_kind",
        "symbol",
        "frequency",
        "since",
        "through",
    ]


class _NStructureService:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    def completion_events(
        self,
        request: NStructureResearchRequest,
    ) -> tuple[NStructureCompletionResearchEvent, ...]:
        if self.failure is not None:
            raise self.failure
        return (
            NStructureCompletionResearchEvent(
                event_id="n_structure_5m_v1|jm|JM2609|2026-08-03|up|7",
                symbol=request.symbol or "",
                contract="JM2609",
                segment_start_trading_day=date(2026, 8, 3),
                observed_at=datetime(2026, 8, 3, 2, 15, tzinfo=UTC),
                trading_day=date(2026, 8, 3),
                segment_bar_index=7,
                direction=NDirection.UP,
            ),
        )


def test_n_structure_historical_overlay_projects_observed_at_without_backpainting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_n_structure_research_service",
        lambda _session: _NStructureService(),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/n-structure/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "JM",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "request": {
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
        "events": [
            {
                "event_id": "n_structure_5m_v1|jm|JM2609|2026-08-03|up|7",
                "observed_at": "2026-08-03T02:15:00Z",
                "trading_day": "2026-08-03",
                "contract": "JM2609",
                "segment_start_trading_day": "2026-08-03",
                "direction": "up",
            }
        ],
    }


@pytest.mark.parametrize(
    ("series_kind", "frequency"),
    (
        ("continuous", "5m"),
        ("contract", "5m"),
        ("actual_dominant", "1m"),
        ("actual_dominant", "15m"),
        ("actual_dominant", "30m"),
        ("actual_dominant", "60m"),
        ("actual_dominant", "1d"),
        ("actual_dominant", "1w"),
    ),
)
def test_n_structure_historical_overlay_rejects_unsupported_identity_before_builder(
    monkeypatch: pytest.MonkeyPatch,
    series_kind: str,
    frequency: str,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_n_structure_research_service",
        lambda _session: pytest.fail("invalid request must not execute service"),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/n-structure/history",
        params={
            "series_kind": series_kind,
            "symbol": "jm",
            "frequency": frequency,
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "INVALID_N_STRUCTURE_HISTORICAL_REQUEST"}
    }


@pytest.mark.parametrize(
    "params",
    (
        {"symbol": "jm1"},
        {"symbol": "中"},
        {"since": "2026-08-05", "through": "2026-08-04"},
    ),
)
def test_n_structure_historical_overlay_rejects_invalid_symbol_or_window_before_builder(
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, str],
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_n_structure_research_service",
        lambda _session: pytest.fail("invalid request must not execute service"),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/n-structure/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "5m",
            "since": "2026-08-03",
            "through": "2026-08-04",
            **params,
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "INVALID_N_STRUCTURE_HISTORICAL_REQUEST"}
    }


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
    ),
)
def test_n_structure_historical_overlay_maps_source_failures_to_409(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_n_structure_research_service",
        lambda _session: _NStructureService(failure),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/n-structure/history",
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


def test_jdj_historical_overlay_route_exposes_exact_read_only_query_contract() -> None:
    path = "/api/v1/market/research/jdj/history"

    assert path in app.openapi()["paths"]
    operation = app.openapi()["paths"][path]["get"]
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "series_kind",
        "symbol",
        "frequency",
        "since",
        "through",
    ]


_JDJ_CANDIDATES = (
    (
        "jdj_trend_follow_1m_candidate_v1",
        "jdj_trend_follow_triggered",
        "long",
    ),
    (
        "jdj_trend_reentry_6_1m_candidate_v1",
        "jdj_trend_reentry_6_triggered",
        "short",
    ),
    (
        "jdj_key_level_breakout_1m_candidate_v1",
        "jdj_key_level_breakout_triggered",
        "long",
    ),
)


class _JdjService:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    def run_batch(self, **kwargs: object) -> SimpleNamespace:
        if self.failure is not None:
            raise self.failure
        symbol = str(kwargs["symbol"])
        candidates = tuple(
            SimpleNamespace(
                result=SimpleNamespace(
                    candidate_id=candidate_id,
                    source_event_kind=source_event_kind,
                    events=(
                        SimpleNamespace(
                            event_id=f"{candidate_id}|event-1",
                            candidate_id=candidate_id,
                            source_event_kind=source_event_kind,
                            observed_at=datetime(
                                2026,
                                8,
                                3,
                                2,
                                15 + index,
                                tzinfo=UTC,
                            ),
                            trading_day=date(2026, 8, 3),
                            contract="JM2609",
                            segment_start_trading_day=date(2026, 8, 3),
                            direction=SimpleNamespace(value=direction),
                            trigger_level=Decimal("101.5") + index,
                        ),
                    ),
                )
            )
            for index, (candidate_id, source_event_kind, direction) in enumerate(
                _JDJ_CANDIDATES
            )
        )
        return SimpleNamespace(
            symbol=symbol,
            observed_since=kwargs["since"],
            observed_through=kwargs["through"],
            candidates=candidates,
        )


def test_jdj_historical_overlay_returns_three_unmerged_candidate_events_at_observed_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_jdj_research_service",
        lambda _session: _JdjService(),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/jdj/history",
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
    assert [
        (event["candidate_id"], event["source_event_kind"])
        for event in payload["events"]
    ] == [(candidate_id, source_kind) for candidate_id, source_kind, _ in _JDJ_CANDIDATES]
    assert [event["observed_at"] for event in payload["events"]] == [
        "2026-08-03T02:15:00Z",
        "2026-08-03T02:16:00Z",
        "2026-08-03T02:17:00Z",
    ]
    assert [event["direction"] for event in payload["events"]] == [
        "long",
        "short",
        "long",
    ]
    assert [event["trigger_level"] for event in payload["events"]] == [
        "101.5",
        "102.5",
        "103.5",
    ]
    assert all(
        set(event) == {
            "event_id",
            "candidate_id",
            "source_event_kind",
            "observed_at",
            "trading_day",
            "contract",
            "segment_start_trading_day",
            "direction",
            "trigger_level",
        }
        for event in payload["events"]
    )


@pytest.mark.parametrize(
    ("series_kind", "frequency"),
    (
        ("continuous", "1m"),
        ("contract", "1m"),
        ("actual_dominant", "5m"),
        ("actual_dominant", "15m"),
        ("actual_dominant", "30m"),
        ("actual_dominant", "60m"),
        ("actual_dominant", "1d"),
        ("actual_dominant", "1w"),
    ),
)
def test_jdj_historical_overlay_rejects_unsupported_identity_before_builder(
    monkeypatch: pytest.MonkeyPatch,
    series_kind: str,
    frequency: str,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_jdj_research_service",
        lambda _session: pytest.fail("invalid request must not execute service"),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/jdj/history",
        params={
            "series_kind": series_kind,
            "symbol": "jm",
            "frequency": frequency,
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "INVALID_JDJ_HISTORICAL_REQUEST"}
    }


@pytest.mark.parametrize(
    ("failure", "status_code", "expected_code"),
    (
        (JdjSourceUnavailableError(), 409, "JDJ_SOURCE_UNAVAILABLE"),
        (JdjContextError(), 422, "INVALID_JDJ_HISTORICAL_REQUEST"),
    ),
)
def test_jdj_historical_overlay_maps_source_and_request_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    status_code: int,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        "app.research.historical_overlay_api.build_jdj_research_service",
        lambda _session: _JdjService(failure),
    )

    response = TestClient(app).get(
        "/api/v1/market/research/jdj/history",
        params={
            "series_kind": "actual_dominant",
            "symbol": "jm",
            "frequency": "1m",
            "since": "2026-08-03",
            "through": "2026-08-04",
        },
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": {"code": expected_code}}


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

    def history(self, request: object) -> SimpleNamespace:
        if self.failure is not None:
            raise self.failure
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
                    contract="JM2701",
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
                    contract="JM2701",
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


@pytest.mark.parametrize(
    ("series_kind", "symbol", "frequency"),
    (
        ("actual_dominant", "jm", "5m"),
        ("actual_dominant", "rb", "1m"),
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
