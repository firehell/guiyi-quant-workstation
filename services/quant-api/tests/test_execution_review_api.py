from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.models import AlertEvent, AlertRule
from app.api import execution_review as execution_review_api
from app.db.base import Base
from app.db.session import get_db
from app.execution_review.contracts import ExecutionReviewContractError
from app.main import app
from app.execution_review.errors import ExecutionReviewDomainError


BAR_END = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)


@pytest.fixture
def api() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_http_full_execution_review_flow_and_read_models(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api
    event_id = _seed_event(factory)

    executed = client.post(
        f"/api/execution-review/events/{event_id}/executed",
        json={
            "executed_at": "2026-08-15T01:03:00Z",
            "price": "1268.5",
            "quantity": 2,
            "execution_reason_tags": ["KEY_LEVEL_BREAKOUT"],
        },
    )
    assert executed.status_code == 201
    payload = executed.json()
    assert payload["decision"]["disposition"] == "EXECUTED"
    assert payload["episode"]["direction"] == "SHORT"
    assert payload["execution"]["sequence_no"] == 1
    assert payload["position"]["remaining_quantity"] == 2
    decision_id = payload["decision"]["id"]
    episode_id = payload["episode"]["id"]
    open_execution_id = payload["execution"]["id"]

    decision_update = client.put(
        f"/api/execution-review/decisions/{decision_id}",
        json={
            "first_viewed_at": "2026-08-15T04:00:00Z",
            "decided_at": "2026-08-15T01:02:00Z",
            "primary_not_execute_reason": None,
            "secondary_not_execute_reasons": [],
            "note": "confirmed",
            "execution_reason_tags": ["PULLBACK_RECONFIRMED"],
            "planned_stop_price": "1300",
            "stop_basis": "EMA",
        },
    )
    assert decision_update.status_code == 200
    assert decision_update.json()["disposition"] == "EXECUTED"

    corrected_execution = client.put(
        f"/api/execution-review/executions/{open_execution_id}",
        json={
            "executed_at": "2026-08-15T01:04:00Z",
            "price": "1267.5",
            "note": "corrected",
        },
    )
    assert corrected_execution.status_code == 200
    assert corrected_execution.json()["execution"]["sequence_no"] == 1

    close = client.post(
        f"/api/execution-review/episodes/{episode_id}/executions",
        json={
            "execution_type": "CLOSE",
            "executed_at": "2026-08-15T01:05:00Z",
            "price": "1260",
            "quantity": 2,
        },
    )
    assert close.status_code == 201
    assert close.json()["episode"]["close_reason"] == "EXECUTION_NET_ZERO"
    close_execution_id = close.json()["execution"]["id"]

    timeline = client.put(
        f"/api/execution-review/episodes/{episode_id}/execution-timeline",
        json={
            "items": [
                {
                    "execution_id": open_execution_id,
                    "execution_type": "OPEN",
                    "executed_at": "2026-08-15T01:04:00Z",
                    "price": "1267.5",
                    "quantity": 2,
                    "note": "corrected",
                },
                {
                    "execution_id": close_execution_id,
                    "execution_type": "CLOSE",
                    "executed_at": "2026-08-15T01:05:00Z",
                    "price": "1260",
                    "quantity": 2,
                },
            ]
        },
    )
    assert timeline.status_code == 200
    assert [row["sequence_no"] for row in timeline.json()["executions"]] == [1, 2]

    review_payload = {
        **_review_json(),
        "entry_tags": ["TOO_LATE"],
        "holding_tags": ["COULD_NOT_HOLD"],
        "exit_tags": ["STOP_DELAYED"],
        "psychology_tags": ["HESITATION"],
    }
    review = client.post(
        f"/api/execution-review/episodes/{episode_id}/review",
        json=review_payload,
    )
    assert review.status_code == 201
    review_id = review.json()["id"]
    assert "submitted_at" in review.json()

    review_update = client.put(
        f"/api/execution-review/reviews/{review_id}",
        json={**review_payload, "summary": "updated"},
    )
    assert review_update.status_code == 200
    assert review_update.json()["submitted_at"] == review.json()["submitted_at"]

    items = client.get(
        "/api/execution-review/items",
        params={
            "state": "done",
            "symbol": " JM ",
            "direction": "SHORT",
            "frequency": "15m",
            "start_trading_day": "2026-08-15",
            "end_trading_day": "2026-08-15",
        },
    )
    states = client.get(
        "/api/execution-review/event-states",
        params=[("event_ids", str(event_id))],
    )
    detail = client.get(f"/api/execution-review/episodes/{episode_id}")
    stats = client.get("/api/execution-review/stats")
    assert items.status_code == states.status_code == detail.status_code == 200
    assert stats.status_code == 200
    assert items.json()["items"][0]["item_kind"] == "episode"
    assert states.json()["items"][0]["state"] == "done"
    assert detail.json()["position"]["remaining_quantity"] == 0
    assert detail.json()["origin_event"] == {
        "id": event_id,
        "rule_code": "subing_entry_signal_v1",
        "symbol": "jm",
        "contract": "JM2609",
        "trading_day": "2026-08-15",
        "frequency": "15m",
        "bar_end": "2026-08-15T01:00:00Z",
        "result_codes": ["sell"],
        "lower_tf_confirmation": False,
        "detected_at": "2026-08-15T01:00:01Z",
        "notification_attempted_at": None,
    }
    assert [row["id"] for row in detail.json()["decisions"]] == [decision_id]
    assert stats.json()["opportunities"]["processed_events"] == 1
    assert stats.json()["episode_states"]["done_episodes"] == 1
    assert stats.json()["review_issue_top"] == {
        "entry": {"TOO_LATE": 1},
        "holding": {"COULD_NOT_HOLD": 1},
        "exit_risk": {"STOP_DELAYED": 1},
        "psychology": {"HESITATION": 1},
    }


def test_not_executed_and_disposition_correction_routes(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api
    event_id = _seed_event(factory)
    created = client.post(
        f"/api/execution-review/events/{event_id}/not-executed",
        json={"primary_reason": "TOO_LATE"},
    )
    assert created.status_code == 201
    decision_id = created.json()["id"]

    corrected = client.post(
        f"/api/execution-review/decisions/{decision_id}/correct-disposition",
        json={
            "target_disposition": "EXECUTED",
            "executed_at": "2026-08-15T01:03:00Z",
            "price": "1268.5",
            "quantity": 1,
            "execution_reason_tags": ["KEY_LEVEL_BREAKOUT"],
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["decision"]["id"] == decision_id
    assert corrected.json()["decision"]["disposition"] == "EXECUTED"


def test_reconstruction_route_defaults_to_signal_and_serializes_canonical_bars(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    calls: list[tuple[int, str]] = []
    event = SimpleNamespace(
        id=17,
        rule_code="subing_entry_signal_v1",
        symbol="jm",
        contract="JM2609",
        trading_day=date(2026, 8, 15),
        frequency="5m",
        bar_end=BAR_END,
        result_codes=("buy",),
        lower_tf_confirmation=False,
        detected_at=BAR_END + timedelta(seconds=1),
        notification_attempted_at=None,
    )
    segment = SimpleNamespace(
        contract="JM2609",
        start_trading_day=date(2026, 8, 14),
        end_trading_day=date(2026, 8, 18),
    )
    window = SimpleNamespace(
        start_trading_day=date(2026, 8, 15),
        end_trading_day=date(2026, 8, 15),
        bar_end_cutoff=BAR_END,
    )
    bar = SimpleNamespace(
        bar_end=BAR_END,
        trading_day=date(2026, 8, 15),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        open_interest=Decimal("20"),
    )

    class FakeService:
        def reconstruct_event(self, event_id: int, *, mode: str):
            calls.append((event_id, mode))
            return SimpleNamespace(
                status="READY",
                reason=None,
                mode=mode,
                post_hoc_reconstruction=True,
                event=event,
                segment=segment,
                window=window,
                bars_5m=(bar,),
                bars_15m=(),
            )

    monkeypatch.setattr(
        execution_review_api,
        "_reconstruction_service",
        lambda _session: FakeService(),
    )

    response = client.get("/api/execution-review/events/17/reconstruction")

    assert response.status_code == 200
    assert calls == [(17, "signal")]
    assert response.json() == {
        "status": "READY",
        "reason": None,
        "mode": "signal",
        "post_hoc_reconstruction": True,
        "event": {
            "id": 17,
            "rule_code": "subing_entry_signal_v1",
            "symbol": "jm",
            "contract": "JM2609",
            "trading_day": "2026-08-15",
            "frequency": "5m",
            "bar_end": "2026-08-15T01:00:00Z",
            "result_codes": ["buy"],
            "lower_tf_confirmation": False,
            "detected_at": "2026-08-15T01:00:01Z",
            "notification_attempted_at": None,
        },
        "segment": {
            "contract": "JM2609",
            "start_trading_day": "2026-08-14",
            "end_trading_day": "2026-08-18",
        },
        "window": {
            "start_trading_day": "2026-08-15",
            "end_trading_day": "2026-08-15",
            "bar_end_cutoff": "2026-08-15T01:00:00Z",
        },
        "bars_5m": [
            {
                "bar_end": "2026-08-15T01:00:00Z",
                "trading_day": "2026-08-15",
                "open": "100",
                "high": "101",
                "low": "99",
                "close": "100.5",
                "volume": "10",
                "turnover": "1000",
                "open_interest": "20",
            }
        ],
        "bars_15m": [],
    }


def test_reconstruction_unavailable_is_http_200(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api

    class FakeService:
        def reconstruct_event(self, _event_id: int, *, mode: str):
            return SimpleNamespace(
                status="UNAVAILABLE",
                reason="MARKET_PARTITION_UNAVAILABLE",
                mode=mode,
                post_hoc_reconstruction=True,
                event=SimpleNamespace(
                    id=17,
                    rule_code="subing_entry_signal_v1",
                    symbol="jm",
                    contract="JM2609",
                    trading_day=date(2026, 8, 15),
                    frequency="15m",
                    bar_end=BAR_END,
                    result_codes=("sell",),
                    lower_tf_confirmation=False,
                    detected_at=BAR_END + timedelta(seconds=1),
                    notification_attempted_at=None,
                ),
                segment=None,
                window=None,
                bars_5m=(),
                bars_15m=(),
            )

    monkeypatch.setattr(
        execution_review_api,
        "_reconstruction_service",
        lambda _session: FakeService(),
    )

    response = client.get("/api/execution-review/events/17/reconstruction?mode=full")

    assert response.status_code == 200
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["reason"] == "MARKET_PARTITION_UNAVAILABLE"
    assert response.json()["segment"] is None
    assert response.json()["window"] is None


def test_event_states_require_bounded_ids_and_fail_closed(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api
    first_id = _seed_event(factory)
    second_id = _seed_event(
        factory,
        symbol="a",
        contract="A2609",
        bar_end=BAR_END + timedelta(minutes=1),
    )
    unrequested_id = _seed_event(
        factory,
        symbol="b",
        contract="B2609",
        bar_end=BAR_END + timedelta(minutes=2),
    )

    missing_parameter = client.get("/api/execution-review/event-states")
    bounded = client.get(
        "/api/execution-review/event-states",
        params=[
            ("event_ids", str(second_id)),
            ("event_ids", str(first_id)),
            ("event_ids", str(second_id)),
        ],
    )
    missing_event = client.get(
        "/api/execution-review/event-states",
        params=[("event_ids", str(first_id)), ("event_ids", "999999")],
    )
    non_positive = client.get(
        "/api/execution-review/event-states",
        params={"event_ids": 0},
    )

    assert missing_parameter.status_code == 422
    assert missing_parameter.json() == {
        "detail": {"code": "INVALID_EXECUTION_REVIEW_REQUEST"}
    }
    assert bounded.status_code == 200
    assert [row["event_id"] for row in bounded.json()["items"]] == [
        second_id,
        first_id,
    ]
    assert unrequested_id not in {row["event_id"] for row in bounded.json()["items"]}
    assert missing_event.status_code == 404
    assert missing_event.json() == {
        "detail": {"code": "EXECUTION_REVIEW_EVENT_NOT_FOUND"}
    }
    assert non_positive.status_code == 422
    assert non_positive.json() == {
        "detail": {"code": "EXECUTION_REVIEW_EVENT_IDS_INVALID"}
    }


def test_event_states_reject_ineligible_event(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api
    event_id = _seed_event(factory, rule_code="htdy_original_15m")

    response = client.get(
        "/api/execution-review/event-states",
        params={"event_ids": event_id},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "EVENT_NOT_EXECUTION_REVIEW_ELIGIBLE"}
    }


def test_items_require_state_and_active_states_ignore_historical_range(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api
    event_id = _seed_event(factory)

    missing_state = client.get("/api/execution-review/items")
    pending = client.get(
        "/api/execution-review/items",
        params={
            "state": "pending_decision",
            "symbol": "JM",
            "direction": "SHORT",
            "frequency": "15m",
            "start_trading_day": "2099-01-02",
            "end_trading_day": "2099-01-01",
        },
    )

    assert missing_state.status_code == 422
    assert missing_state.json() == {
        "detail": {"code": "INVALID_EXECUTION_REVIEW_REQUEST"}
    }
    assert pending.status_code == 200
    assert [row["event_id"] for row in pending.json()["items"]] == [event_id]


def test_stats_zero_denominators_are_json_null(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api

    empty = client.get("/api/execution-review/stats")
    _seed_event(factory)
    pending = client.get("/api/execution-review/stats")

    assert empty.status_code == pending.status_code == 200
    assert empty.json()["opportunities"]["decision_completion_rate"] is None
    assert empty.json()["opportunities"]["execution_rate"] is None
    assert pending.json()["opportunities"]["decision_completion_rate"] == "0"
    assert pending.json()["opportunities"]["execution_rate"] is None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "POST",
            "/api/execution-review/events/1/executed",
            {
                "executed_at": "2026-08-15T01:03:00Z",
                "price": "1268.5",
                "quantity": 1,
                "execution_reason_tags": ["KEY_LEVEL_BREAKOUT"],
                "direction": "LONG",
            },
        ),
        (
            "POST",
            "/api/execution-review/episodes/1/executions",
            {
                "execution_type": "ADD",
                "executed_at": "2026-08-15T01:03:00Z",
                "price": "1268.5",
                "quantity": 1,
                "sequence_no": 99,
                "trigger_decision_id": 1,
            },
        ),
        (
            "POST",
            "/api/execution-review/episodes/1/review",
            {
                "signal_execution_adherence": "ALIGNED",
                "entry_tags": ["REASONABLE"],
                "holding_tags": ["NORMAL"],
                "exit_tags": ["NORMAL"],
                "market_context_tags": ["TREND"],
                "psychology_tags": ["NONE"],
                "summary": "reviewed",
                "submitted_at": "2026-08-15T01:03:00Z",
            },
        ),
        (
            "PUT",
            "/api/execution-review/decisions/1",
            {
                "first_viewed_at": None,
                "decided_at": "2026-08-15T01:03:00Z",
                "primary_not_execute_reason": "TOO_LATE",
                "secondary_not_execute_reasons": [],
                "note": None,
                "execution_reason_tags": [],
                "planned_stop_price": None,
                "stop_basis": None,
                "disposition": "EXECUTED",
            },
        ),
        (
            "PUT",
            "/api/execution-review/episodes/1/execution-timeline",
            {
                "items": [
                    {
                        "execution_id": 1,
                        "execution_type": "OPEN",
                        "executed_at": "2026-08-15T01:03:00Z",
                        "price": "1268.5",
                        "quantity": 1,
                        "trigger_decision_id": 1,
                        "sequence_no": 1,
                    }
                ]
            },
        ),
        (
            "POST",
            "/api/execution-review/events/1/executed",
            {
                "executed_at": "2026-08-15T01:03:00Z",
                "price": "1268.5",
                "quantity": True,
                "execution_reason_tags": ["KEY_LEVEL_BREAKOUT"],
            },
        ),
        (
            "POST",
            "/api/execution-review/events/1/executed",
            {
                "executed_at": "2026-08-15T01:03:00Z",
                "price": "1268.5",
                "quantity": 2147483648,
                "execution_reason_tags": ["KEY_LEVEL_BREAKOUT"],
            },
        ),
        (
            "POST",
            "/api/execution-review/events/1/executed",
            {
                "executed_at": "2026-08-15T01:03:00Z",
                "price": "1.123456789",
                "quantity": 1,
                "execution_reason_tags": ["KEY_LEVEL_BREAKOUT"],
            },
        ),
        (
            "POST",
            "/api/execution-review/events/1/executed",
            {
                "executed_at": "2026-08-15T01:03:00Z",
                "price": "10000000000000000",
                "quantity": 1,
                "execution_reason_tags": ["KEY_LEVEL_BREAKOUT"],
            },
        ),
    ],
)
def test_request_contract_rejects_client_owned_fields_with_stable_code(
    api: tuple[TestClient, sessionmaker[Session]],
    method: str,
    path: str,
    body: dict[str, object],
) -> None:
    client, _ = api
    response = client.request(method, path, json=body)

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "INVALID_EXECUTION_REVIEW_REQUEST"}}


def test_execution_review_domain_errors_use_stable_envelope(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api
    event_id = _seed_event(factory, result_codes=["buy"])
    first = client.post(
        f"/api/execution-review/events/{event_id}/executed",
        json=_executed_json(),
    )
    assert first.status_code == 201
    opposite_id = _seed_event(
        factory,
        result_codes=["sell"],
        bar_end=BAR_END + timedelta(minutes=15),
    )

    opposite = client.post(
        f"/api/execution-review/events/{opposite_id}/executed",
        json={**_executed_json(), "executed_at": "2026-08-15T01:18:00Z"},
    )
    missing = client.get("/api/execution-review/episodes/999")

    assert opposite.status_code == 409
    assert opposite.json() == {"detail": {"code": "ROLL_RECONCILIATION_REQUIRED"}}
    assert missing.status_code == 404
    assert missing.json() == {"detail": {"code": "TRADE_EPISODE_NOT_FOUND"}}


@pytest.mark.parametrize(
    "path",
    ["/api/alerts/events", "/api/v1/market/bars/page"],
)
def test_non_execution_review_validation_keeps_fastapi_default_handler(
    api: tuple[TestClient, sessionmaker[Session]],
    path: str,
) -> None:
    client, _ = api

    response = client.get(path)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_unknown_persistence_failure_uses_redacted_503_envelope(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api

    class FailingService:
        def list_items(
            self,
            *,
            state: str,
            symbol: str | None = None,
            direction: str | None = None,
            frequency: str | None = None,
            start_trading_day: date | None = None,
            end_trading_day: date | None = None,
        ) -> tuple[object, ...]:
            del (
                state,
                symbol,
                direction,
                frequency,
                start_trading_day,
                end_trading_day,
            )
            raise ExecutionReviewDomainError(
                "EXECUTION_REVIEW_PERSIST_FAILED",
                status_code=503,
            )

    monkeypatch.setattr(
        execution_review_api,
        "_query_service",
        lambda _: FailingService(),
    )

    response = client.get(
        "/api/execution-review/items",
        params={"state": "done"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "EXECUTION_REVIEW_PERSIST_FAILED"}}


def test_multiplier_reference_failure_uses_redacted_503_envelope(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _ = api

    def fail_builder(_: object) -> object:
        raise ExecutionReviewContractError("MULTIPLIER_REFERENCE_INVALID")

    monkeypatch.setattr(
        execution_review_api,
        "build_execution_review_query_service",
        fail_builder,
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/execution-review/items?state=done"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "EXECUTION_REVIEW_PERSIST_FAILED"}}


def _seed_event(
    factory: sessionmaker[Session],
    *,
    result_codes: list[str] | None = None,
    bar_end: datetime = BAR_END,
    rule_code: str = "subing_entry_signal_v1",
    symbol: str = "jm",
    contract: str = "JM2609",
    trading_day: date = date(2026, 8, 15),
    frequency: str = "15m",
) -> int:
    with factory() as session:
        rule = session.query(AlertRule).filter_by(rule_code=rule_code).one_or_none()
        if rule is None:
            rule = AlertRule(
                rule_code=rule_code,
                enabled=True,
                scope_products=[symbol],
                created_at=BAR_END,
                updated_at=BAR_END,
            )
        event = AlertEvent(
            rule=rule,
            symbol=symbol,
            contract=contract,
            trading_day=trading_day,
            frequency=frequency,
            bar_end=bar_end,
            result_codes=result_codes or ["sell"],
            lower_tf_confirmation=False,
            detected_at=bar_end + timedelta(seconds=1),
        )
        session.add(event)
        session.commit()
        return event.id


def _executed_json() -> dict[str, object]:
    return {
        "executed_at": "2026-08-15T01:03:00Z",
        "price": "1268.5",
        "quantity": 1,
        "execution_reason_tags": ["KEY_LEVEL_BREAKOUT"],
    }


def _review_json() -> dict[str, object]:
    return {
        "signal_execution_adherence": "ALIGNED",
        "entry_tags": ["REASONABLE"],
        "holding_tags": ["NORMAL"],
        "exit_tags": ["NORMAL"],
        "market_context_tags": ["TREND"],
        "psychology_tags": ["NONE"],
        "summary": "reviewed",
    }
