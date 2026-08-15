from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.alerts.models import AlertEvent, AlertRule
from app.api import execution_review as execution_review_api
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.execution_review.service import ExecutionReviewDomainError


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
    assert executed.status_code == 200
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
    assert close.status_code == 200
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

    review = client.post(
        f"/api/execution-review/episodes/{episode_id}/review",
        json=_review_json(),
    )
    assert review.status_code == 200
    review_id = review.json()["id"]
    assert "submitted_at" in review.json()

    review_update = client.put(
        f"/api/execution-review/reviews/{review_id}",
        json={**_review_json(), "summary": "updated"},
    )
    assert review_update.status_code == 200
    assert review_update.json()["submitted_at"] == review.json()["submitted_at"]

    items = client.get("/api/execution-review/items", params={"state": "done"})
    states = client.get("/api/execution-review/event-states")
    detail = client.get(f"/api/execution-review/episodes/{episode_id}")
    stats = client.get("/api/execution-review/stats")
    assert items.status_code == states.status_code == detail.status_code == 200
    assert stats.status_code == 200
    assert items.json()["items"][0]["item_kind"] == "episode"
    assert states.json()["items"][0]["state"] == "done"
    assert detail.json()["position"]["remaining_quantity"] == 0
    assert stats.json()["opportunities"]["processed_events"] == 1
    assert stats.json()["episode_states"]["done_episodes"] == 1


def test_not_executed_and_disposition_correction_routes(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api
    event_id = _seed_event(factory)
    created = client.post(
        f"/api/execution-review/events/{event_id}/not-executed",
        json={"primary_reason": "TOO_LATE"},
    )
    assert created.status_code == 200
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
    assert response.json() == {
        "detail": {"code": "INVALID_EXECUTION_REVIEW_REQUEST"}
    }


def test_execution_review_domain_errors_use_stable_envelope(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api
    event_id = _seed_event(factory, result_codes=["buy"])
    first = client.post(
        f"/api/execution-review/events/{event_id}/executed",
        json=_executed_json(),
    )
    assert first.status_code == 200
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
    assert opposite.json() == {"detail": {"code": "OPPOSITE_EPISODE_OPEN"}}
    assert missing.status_code == 404
    assert missing.json() == {
        "detail": {"code": "TRADE_EPISODE_NOT_FOUND"}
    }


def test_non_execution_review_validation_keeps_fastapi_default_handler(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api

    response = client.get("/api/alerts/events")

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_unknown_persistence_failure_uses_redacted_503_envelope(
    api: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api

    class FailingService:
        def list_items(self, *, state: str | None = None) -> tuple[object, ...]:
            del state
            raise ExecutionReviewDomainError(
                "EXECUTION_REVIEW_PERSIST_FAILED",
                status_code=503,
            )

    monkeypatch.setattr(
        execution_review_api,
        "_service",
        lambda _: FailingService(),
    )

    response = client.get("/api/execution-review/items")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "EXECUTION_REVIEW_PERSIST_FAILED"}
    }


def _seed_event(
    factory: sessionmaker[Session],
    *,
    result_codes: list[str] | None = None,
    bar_end: datetime = BAR_END,
) -> int:
    with factory() as session:
        rule = session.query(AlertRule).filter_by(
            rule_code="subing_entry_signal_v1"
        ).one_or_none()
        if rule is None:
            rule = AlertRule(
                rule_code="subing_entry_signal_v1",
                enabled=True,
                scope_products=["jm"],
                created_at=BAR_END,
                updated_at=BAR_END,
            )
        event = AlertEvent(
            rule=rule,
            symbol="jm",
            contract="JM2609",
            trading_day=date(2026, 8, 15),
            frequency="15m",
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
