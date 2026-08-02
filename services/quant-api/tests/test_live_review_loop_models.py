from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.live_review_loop import LiveObservationBar, SignalDecision


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _live_bar(*, close: str = "100", revision: int = 0) -> LiveObservationBar:
    return LiveObservationBar(
        provider="rqdata",
        source_mode="rqdata_live_1m_v2",
        product="jm",
        actual_contract="JM2609",
        trading_day=date(2026, 8, 3),
        period="1m",
        bar_end=datetime(2026, 8, 2, 13, 1, tzinfo=UTC),
        revision=revision,
        confirmed=True,
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        close=Decimal(close),
        volume=Decimal("10"),
        open_interest=Decimal("20"),
        turnover=Decimal("1000"),
        source_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        source_end=datetime(2026, 8, 2, 13, 1, tzinfo=UTC),
        source_bar_count=1,
        expected_bar_count=1,
        identity_digest="a" * 64,
        payload_digest="b" * 64,
    )


def _decision() -> SignalDecision:
    return SignalDecision(
        decision_key="3" * 64,
        decision_at=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
        trading_day=date(2026, 8, 3),
        bar_end=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
        provider="rqdata",
        source_mode="session_aggregate_15m_v2",
        actual_contract="JM2609",
        strategy_code="task06_causal_test_observation",
        strategy_version="v1.0",
        policy_id="task06_causal_confirmed_close_test_v1",
        parameter_digest="4" * 64,
        input_schema_version="strategy_input_v1",
        input_window_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        input_window_end=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
        dataset_key={"provider": "rqdata"},
        manifest_digest="5" * 64,
        input_snapshot={},
        input_digest="6" * 64,
        fingerprint_recipe_version="strategy_fingerprint_v1",
        fingerprint="7" * 64,
        result_kind="no_signal",
        direction=None,
        result_payload={"candidates": []},
        result_digest="8" * 64,
    )


def test_live_observation_identity_preserves_second_revision() -> None:
    with _session() as session:
        session.add(_live_bar())
        session.commit()
        session.add(_live_bar(close="101", revision=1))
        session.commit()

        assert session.scalar(select(func.count()).select_from(LiveObservationBar)) == 2


def test_live_observation_database_rejects_non_contract_source_mode() -> None:
    with _session() as session:
        row = _live_bar()
        row.source_mode = "historical_canonical"
        session.add(row)
        with pytest.raises(IntegrityError):
            session.commit()


def test_signal_decision_requires_direction_only_for_signal() -> None:
    with _session() as session:
        session.add(
            SignalDecision(
                decision_key="c" * 64,
                decision_at=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
                trading_day=date(2026, 8, 3),
                bar_end=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
                provider="rqdata",
                source_mode="session_aggregate_15m_v2",
                actual_contract="JM2609",
                strategy_code="task06_causal_test_observation",
                strategy_version="v1.0",
                policy_id="task06_causal_confirmed_close_test_v1",
                parameter_digest="d" * 64,
                input_schema_version="strategy_input_v1",
                input_window_start=datetime(2026, 8, 1, tzinfo=UTC),
                input_window_end=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
                dataset_key={"provider": "rqdata"},
                manifest_digest="e" * 64,
                input_snapshot={},
                input_digest="f" * 64,
                fingerprint_recipe_version="strategy_fingerprint_v1",
                fingerprint="1" * 64,
                result_kind="signal",
                direction=None,
                result_payload={},
                result_digest="2" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_signal_decision_rejects_orm_update_after_insert() -> None:
    with _session() as session:
        decision = _decision()
        session.add(decision)
        session.commit()

        decision.result_kind = "signal"
        decision.direction = "long"
        decision.result_payload = {"candidates": ["long"]}
        with pytest.raises(RuntimeError, match="SIGNAL_DECISION_IMMUTABLE"):
            session.commit()
