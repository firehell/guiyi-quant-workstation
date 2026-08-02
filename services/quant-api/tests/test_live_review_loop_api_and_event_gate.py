from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.live_review_loop.decisions import SignalDecisionStore
from app.live_review_loop.eod import EodReconciliationService
from app.live_review_loop.contracts import StrategyInputSchema
from app.live_review_loop.gates import LiveReviewFeatureDisabledError
from app.live_review_loop.provider_final import ProviderFinalSnapshot
from app.live_review_loop.runtime import (
    LiveReviewRuntime,
)
from app.main import app
from app.models.live_review_loop import ResearchSample, SignalDecision
from app.models.signal import SignalEvent, SignalNotification


def _database():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    return SessionLocal


def _historical_bars() -> list[dict[str, object]]:
    decision_start = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)
    start = decision_start - timedelta(minutes=15 * 128)
    return [
        {
            "period": "15m",
            "bar_end": start + timedelta(minutes=15 * (index + 1)),
            "open": Decimal(100 + index),
            "high": Decimal(101 + index),
            "low": Decimal(99 + index),
            "close": Decimal(100 + index),
            "volume": Decimal("10"),
        }
        for index in range(128)
    ]


def _strategy_input() -> StrategyInputSchema:
    bar_end = datetime(2026, 8, 2, 13, 15, tzinfo=UTC)
    decision_bar = {
        "provider": "rqdata",
        "source_mode": "session_aggregate_15m_v2",
        "product": "jm",
        "actual_contract": "JM2609",
        "trading_day": date(2026, 8, 3),
        "bar_end": bar_end,
        "source_start": datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        "source_end": bar_end,
        "confirmed": True,
        "period": "15m",
        "revision": 0,
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100"),
        "volume": Decimal("10"),
        "open_interest": Decimal("20"),
        "turnover": Decimal("1000"),
        "source_bar_count": 15,
        "expected_bar_count": 15,
    }
    live_inputs = []
    for index in range(15):
        minute_end = datetime(2026, 8, 2, 13, 1, tzinfo=UTC) + timedelta(minutes=index)
        live_inputs.append(
            {
                **decision_bar,
                "source_mode": "rqdata_live_1m_v2",
                "period": "1m",
                "bar_end": minute_end,
                "source_start": minute_end - timedelta(minutes=1),
                "source_end": minute_end,
                "source_bar_count": 1,
                "expected_bar_count": 1,
            }
        )
    return StrategyInputSchema.build(
        trading_day=date(2026, 8, 3),
        actual_contract="JM2609",
        decision_bar=decision_bar,
        historical_input={
            "manifest_digest": "b" * 64,
            "data_role": "primary",
            "quality_status": "passed",
            "aggregation_recipe": "trading_session_15m_v1",
            "bars": _historical_bars(),
            "dataset_key": {
                "provider": "rqdata",
                "dataset_kind": "actual_dominant",
                "symbol": "jm",
                "contract_or_series": "JM2609",
                "frequency": "1m",
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
            },
        },
        live_inputs=live_inputs,
    )


def _create_decision(session, *, result_kind: str = "signal") -> SignalDecision:
    schema = _strategy_input()
    return SignalDecisionStore(session).create(
        schema,
        result_kind=result_kind,
        direction="long" if result_kind == "signal" else None,
        result_payload={"candidates": ["long"] if result_kind == "signal" else []},
        decision_at=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
    )


def test_review_api_lists_decisions_and_extracts_sample_after_complete_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    SessionLocal = _database()
    with SessionLocal() as session:
        decision = _create_decision(session)
        EodReconciliationService(session).complete(
            decision,
            recipe_version="jm_ema21_confirmed_close_direction_v1",
            provider_final_snapshot=decision.input_snapshot,
            provider_data_version="rqdata-test-final-v1",
            provider_request_digest="c" * 64,
            recomputed_result={
                "result_kind": decision.result_kind,
                "direction": decision.direction,
                "payload": decision.result_payload,
            },
        )
        session.commit()
        decision_id = decision.id

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        sources = client.get("/api/reviews/sources/signal-decisions")
        assert sources.status_code == 200
        assert sources.json()[0]["decision_key"]
        assert sources.json()[0]["reviewed"] is False

        monkeypatch.delenv("GUIYI_DATA_CORE_V2_REVIEW_ENABLED", raising=False)
        blocked = client.post(f"/api/reviews/from-signal-decision/{decision_id}")
        assert blocked.status_code == 503

        monkeypatch.setenv("GUIYI_DATA_CORE_V2_REVIEW_ENABLED", "true")
        created = client.post(f"/api/reviews/from-signal-decision/{decision_id}")
        assert created.status_code == 200
        review_id = created.json()["id"]

        incomplete = client.post(f"/api/reviews/{review_id}/research-sample")
        assert incomplete.status_code == 422

        monkeypatch.setenv("GUIYI_DATA_CORE_V2_REVIEW_ENABLED", "false")
        blocked_update = client.put(
            f"/api/reviews/{review_id}",
            json={"market_phase": "trend"},
        )
        assert blocked_update.status_code == 503
        blocked_attachment = client.post(
            f"/api/reviews/{review_id}/attachments",
            json={"file_path": "/tmp/task06-review.png", "file_type": "image"},
        )
        assert blocked_attachment.status_code == 503

        monkeypatch.setenv("GUIYI_DATA_CORE_V2_REVIEW_ENABLED", "true")
        updated = client.put(
            f"/api/reviews/{review_id}",
            json={
                "market_phase": "trend",
                "is_system_compliant": True,
                "rule_tags": ["confirmed-close"],
                "lesson": "wait for close",
            },
        )
        assert updated.status_code == 200
        sample = client.post(f"/api/reviews/{review_id}/research-sample")
        assert sample.status_code == 200
        assert sample.json()["decision_key"]

        with SessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(ResearchSample)) == 1
            assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
    finally:
        app.dependency_overrides.clear()


def test_runtime_execution_facade_fails_closed_when_flags_are_absent() -> None:
    SessionLocal = _database()
    with SessionLocal() as session:
        decision = _create_decision(session)
        runtime = LiveReviewRuntime(session, environ={})

        with pytest.raises(
            LiveReviewFeatureDisabledError, match="LIVE_REVIEW_EOD_DISABLED"
        ):
            runtime.reconcile_eod(
                decision,
                recipe_version="jm_ema21_confirmed_close_direction_v1",
                provider_final_loader=lambda _: {},
                gap_recorder=lambda *_: None,
            )
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0


def test_runtime_binds_the_approved_evaluator_when_live_gate_is_enabled() -> None:
    SessionLocal = _database()
    with SessionLocal() as session:
        schema = _strategy_input()
        runtime = LiveReviewRuntime(
            session,
            environ={"GUIYI_DATA_CORE_V2_LIVE_DECISION_ENABLED": "true"},
        )

        created = runtime.create_decision(
            schema,
            decision_at=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
        )
        assert created.result_kind in {"signal", "no_signal"}


def test_runtime_does_not_accept_an_injected_evaluator() -> None:
    SessionLocal = _database()
    with SessionLocal() as session:
        with pytest.raises(TypeError, match="unexpected keyword argument 'evaluator'"):
            LiveReviewRuntime(
                session,
                environ={},
                evaluator=lambda *_: {},  # type: ignore[call-arg]
            )

        runtime = LiveReviewRuntime(session, environ={})
        with pytest.raises(AttributeError):
            runtime.evaluator = lambda *_: {}  # type: ignore[attr-defined]


def test_runtime_eod_reuses_the_approved_ema21_evaluator() -> None:
    SessionLocal = _database()
    with SessionLocal() as session:
        decision = _create_decision(session)
        runtime = LiveReviewRuntime(
            session,
            environ={"GUIYI_DATA_CORE_V2_EOD_ENABLED": "true"},
        )

        reconciliation = runtime.reconcile_eod(
            decision,
            recipe_version="jm_ema21_confirmed_close_direction_v1",
            provider_final_loader=lambda _: ProviderFinalSnapshot(
                strategy_input=decision.input_snapshot,
                data_version="rqdata-test-final-v1",
                request_digest="d" * 64,
            ),
            gap_recorder=lambda *_: None,
        )

        assert reconciliation.status == "completed"
        assert reconciliation.recomputed_result["payload"]["indicator_code"] == "ema21"
        assert reconciliation.recomputed_result["payload"]["auto_order"] is False
        assert session.scalar(select(func.count()).select_from(SignalEvent)) == 0
        assert session.scalar(select(func.count()).select_from(SignalNotification)) == 0
