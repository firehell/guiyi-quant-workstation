from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.live_review_loop.contracts import (
    StrategyInputSchema,
    canonical_digest,
)
from app.live_review_loop.decisions import DecisionConflictError, SignalDecisionStore
from app.live_review_loop.live import (
    LiveObservationConflictError,
    LiveObservationInput,
    LiveObservationStore,
    aggregate_confirmed_15m,
    aggregate_trading_day_15m,
)
from app.models.live_review_loop import LiveObservationBar, SignalDecision
from app.services.trading_session_clock import SessionWindow


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _minute(
    index: int,
    *,
    close: str | None = None,
    revision: int = 0,
) -> LiveObservationInput:
    end = datetime(2026, 8, 2, 13, 1, tzinfo=UTC) + timedelta(minutes=index)
    value = Decimal(close or str(100 + index))
    return LiveObservationInput(
        provider="rqdata",
        source_mode="rqdata_live_1m_v2",
        product="jm",
        actual_contract="JM2609",
        trading_day=date(2026, 8, 3),
        period="1m",
        bar_end=end,
        revision=revision,
        confirmed=True,
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=Decimal("10"),
        open_interest=Decimal("20"),
        turnover=Decimal("1000"),
        source_start=end - timedelta(minutes=1),
        source_end=end,
        source_bar_count=1,
        expected_bar_count=1,
    )


def _historical_input() -> dict[str, object]:
    decision_start = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)
    start = decision_start - timedelta(minutes=15 * 128)
    bars = []
    for index in range(128):
        value = Decimal(100 + index)
        bars.append(
            {
                "period": "15m",
                "bar_end": start + timedelta(minutes=15 * (index + 1)),
                "open": value,
                "high": value + 1,
                "low": value - 1,
                "close": value,
                "volume": Decimal("10"),
            }
        )
    return {
        "manifest_digest": "b" * 64,
        "data_role": "primary",
        "quality_status": "passed",
        "aggregation_recipe": "trading_session_15m_v1",
        "bars": bars,
        "dataset_key": {
            "provider": "rqdata",
            "dataset_kind": "actual_dominant",
            "symbol": "jm",
            "contract_or_series": "JM2609",
            "frequency": "1m",
            "adjustment": "none",
            "schema_version": "canonical-bar-v1",
        },
    }


def test_canonical_digest_is_stable_for_order_decimal_and_utc() -> None:
    first = canonical_digest(
        {
            "price": Decimal("1.2300"),
            "at": datetime(2026, 8, 2, 1, tzinfo=UTC),
            "side": "long",
        }
    )
    second = canonical_digest(
        {
            "side": "long",
            "at": datetime(2026, 8, 2, 1, tzinfo=UTC),
            "price": Decimal("1.2300"),
        }
    )
    changed = canonical_digest(
        {
            "side": "long",
            "at": datetime(2026, 8, 2, 1, tzinfo=UTC),
            "price": Decimal("1.2301"),
        }
    )

    assert first == second
    assert first != changed
    assert len(first) == 64


def test_strategy_input_golden_vector_and_fingerprint_are_deterministic() -> None:
    minutes = [_minute(index) for index in range(15)]
    decision_bar = aggregate_confirmed_15m(
        minutes,
        session_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
    )
    schema = StrategyInputSchema.build(
        strategy_code="task06_causal_test_observation",
        strategy_version="v1.0",
        policy_id="task06_causal_confirmed_close_test_v1",
        indicator_code="causal_close_change_test",
        indicator_version="test-v1",
        parameters={"comparison": "close_above_previous_close", "lookback": 2},
        recipe_version="task06_causal_confirmed_close_test_recipe_v1",
        trading_day=date(2026, 8, 3),
        actual_contract="JM2609",
        decision_bar=decision_bar.to_payload(),
        historical_input=_historical_input(),
        live_inputs=[item.to_payload() for item in minutes],
    )

    assert schema.parameter_digest == (
        "ed886fb5e9e7624b511cc1042d50dbf6a36b90722f1ec3466c1043d03c83aef5"
    )
    assert schema.input_digest == "1253b73e42f0e5d3f1d55a93e1f480e9449be179824bfbd8066ca28c8b02be76"
    assert schema.fingerprint == "bb3dd9d5e2d813cc9d895b34bea1051ab76f262e238cb63390f3e81cc1fdfe6a"


def test_strategy_input_rejects_non_confirmed_15m_decision_bar() -> None:
    with pytest.raises(
        ValueError, match="STRATEGY_DECISION_BAR_CONFIRMED_15M_REQUIRED"
    ):
        StrategyInputSchema.build(
            strategy_code="task06_causal_test_observation",
            strategy_version="v1.0",
            policy_id="task06_causal_confirmed_close_test_v1",
            indicator_code="causal_close_change_test",
            indicator_version="test-v1",
            parameters={"comparison": "close_above_previous_close", "lookback": 2},
            recipe_version="task06_causal_confirmed_close_test_recipe_v1",
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            decision_bar=_minute(14).to_payload(),
            historical_input=_historical_input(),
            live_inputs=[_minute(index).to_payload() for index in range(15)],
        )


def test_strategy_input_rejects_the_frozen_future_looking_policy() -> None:
    minutes = [_minute(index) for index in range(15)]
    decision_bar = aggregate_confirmed_15m(
        minutes,
        session_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="STRATEGY_POLICY_CONTRACT_INVALID"):
        StrategyInputSchema.build(
            strategy_code="task06_causal_test_observation",
            strategy_version="v1.0",
            policy_id="htdy_original_xma_15m_first_seen_v1",
            indicator_code="causal_close_change_test",
            indicator_version="test-v1",
            parameters={"comparison": "close_above_previous_close", "lookback": 2},
            recipe_version="task06_causal_confirmed_close_test_recipe_v1",
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            decision_bar=decision_bar.to_payload(),
            historical_input=_historical_input(),
            live_inputs=[item.to_payload() for item in minutes],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "historical_canonical"),
        ("confirmed", False),
        ("actual_contract", "JM9999"),
        ("source_bar_count", 999),
    ],
)
def test_strategy_input_rejects_non_contract_live_inputs(
    field: str, value: object
) -> None:
    minutes = [_minute(index) for index in range(15)]
    decision_bar = aggregate_confirmed_15m(
        minutes,
        session_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
    )
    payloads = [item.to_payload() for item in minutes]
    payloads[-1][field] = value

    with pytest.raises(ValueError, match="STRATEGY_LIVE_INPUTS_CONFIRMED_1M_REQUIRED"):
        StrategyInputSchema.build(
            strategy_code="task06_causal_test_observation",
            strategy_version="v1.0",
            policy_id="task06_causal_confirmed_close_test_v1",
            indicator_code="causal_close_change_test",
            indicator_version="test-v1",
            parameters={"comparison": "close_above_previous_close", "lookback": 2},
            recipe_version="task06_causal_confirmed_close_test_recipe_v1",
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            decision_bar=decision_bar.to_payload(),
            historical_input=_historical_input(),
            live_inputs=payloads,
        )


def test_strategy_input_rejects_future_or_unordered_live_inputs() -> None:
    minutes = [_minute(index) for index in range(15)]
    decision_bar = aggregate_confirmed_15m(
        minutes,
        session_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
    )
    payloads = [item.to_payload() for item in minutes]
    payloads[-1]["bar_end"] = decision_bar.bar_end + timedelta(minutes=1)
    payloads[-1]["source_end"] = payloads[-1]["bar_end"]
    payloads[-1]["source_start"] = decision_bar.bar_end

    with pytest.raises(ValueError, match="STRATEGY_LIVE_INPUTS_CONFIRMED_1M_REQUIRED"):
        StrategyInputSchema.build(
            strategy_code="task06_causal_test_observation",
            strategy_version="v1.0",
            policy_id="task06_causal_confirmed_close_test_v1",
            indicator_code="causal_close_change_test",
            indicator_version="test-v1",
            parameters={"comparison": "close_above_previous_close", "lookback": 2},
            recipe_version="task06_causal_confirmed_close_test_recipe_v1",
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            decision_bar=decision_bar.to_payload(),
            historical_input=_historical_input(),
            live_inputs=payloads,
        )


def test_live_store_reuses_identical_row_and_rejects_changed_payload() -> None:
    with _session() as session:
        store = LiveObservationStore(session)
        first = store.put(_minute(0))
        second = store.put(_minute(0))
        assert first.id == second.id
        assert len(list(session.scalars(select(LiveObservationBar)))) == 1

        with pytest.raises(
            LiveObservationConflictError, match="LIVE_OBSERVATION_CONFLICT"
        ):
            store.put(_minute(0, close="999"))


def test_aggregate_confirmed_15m_requires_complete_single_session_bucket() -> None:
    rows = [_minute(index) for index in range(15)]
    aggregate = aggregate_confirmed_15m(
        rows,
        session_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
    )

    assert aggregate.period == "15m"
    assert aggregate.bar_end == datetime(2026, 8, 2, 13, 15, tzinfo=UTC)
    assert aggregate.source_bar_count == 15
    assert aggregate.open == Decimal("100")
    assert aggregate.close == Decimal("114")
    assert aggregate.volume == Decimal("150")

    with pytest.raises(ValueError, match="LIVE_15M_SOURCE_INCOMPLETE"):
        aggregate_confirmed_15m(
            rows[:-1],
            session_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
            session_end=datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
        )

    invalid_source = list(rows)
    invalid_source[0] = replace(
        invalid_source[0],
        source_mode="historical_canonical",
        source_bar_count=999,
        expected_bar_count=999,
    )
    with pytest.raises(ValueError, match="LIVE_15M_SOURCE_IDENTITY_INVALID"):
        aggregate_confirmed_15m(
            invalid_source,
            session_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
            session_end=datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
        )


def test_trading_day_aggregation_uses_clock_windows_and_persists_only_complete_buckets() -> (
    None
):
    class Clock:
        def windows_for_trading_day(self, trading_day, *, product, exchange):
            assert (trading_day, product, exchange) == (date(2026, 8, 3), "jm", "DCE")
            return [
                SessionWindow(
                    trading_day=trading_day,
                    name="night",
                    start=datetime(2026, 8, 2, 21, 0),
                    end=datetime(2026, 8, 2, 23, 0),
                )
            ]

    with _session() as session:
        store = LiveObservationStore(session)
        for index in range(15):
            store.put(_minute(index))

        aggregates = aggregate_trading_day_15m(
            session,
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            trading_clock=Clock(),
        )

        assert [row.bar_end for row in aggregates] == [
            datetime(2026, 8, 2, 13, 15, tzinfo=UTC)
        ]
        assert aggregates[0].period == "15m"


def test_trading_day_aggregation_assigns_monotonic_revision_for_changed_source_vector() -> (
    None
):
    class Clock:
        def windows_for_trading_day(self, *_args, **_kwargs):
            return [
                SessionWindow(
                    trading_day=date(2026, 8, 3),
                    name="night",
                    start=datetime(2026, 8, 2, 21, 0),
                    end=datetime(2026, 8, 2, 23, 0),
                )
            ]

    with _session() as session:
        store = LiveObservationStore(session)
        for index in range(15):
            store.put(_minute(index))
        first = aggregate_trading_day_15m(
            session,
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            trading_clock=Clock(),
        )[0]

        store.put(_minute(0, close="200", revision=1))
        second = aggregate_trading_day_15m(
            session,
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            trading_clock=Clock(),
        )[0]
        repeated = aggregate_trading_day_15m(
            session,
            trading_day=date(2026, 8, 3),
            actual_contract="JM2609",
            trading_clock=Clock(),
        )[0]

        assert (first.revision, second.revision, repeated.revision) == (0, 1, 1)
        revisions = list(
            session.scalars(
                select(LiveObservationBar.revision)
                .where(LiveObservationBar.period == "15m")
                .order_by(LiveObservationBar.revision)
            )
        )
        assert revisions == [0, 1]


def test_signal_decision_store_is_create_only_and_conflict_visible() -> None:
    minutes = [_minute(index) for index in range(15)]
    decision_bar = aggregate_confirmed_15m(
        minutes,
        session_start=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 8, 2, 15, 30, tzinfo=UTC),
    )
    schema = StrategyInputSchema.build(
        strategy_code="task06_causal_test_observation",
        strategy_version="v1.0",
        policy_id="task06_causal_confirmed_close_test_v1",
        indicator_code="causal_close_change_test",
        indicator_version="test-v1",
        parameters={"comparison": "close_above_previous_close", "lookback": 2},
        recipe_version="task06_causal_confirmed_close_test_recipe_v1",
        trading_day=date(2026, 8, 3),
        actual_contract="JM2609",
        decision_bar=decision_bar.to_payload(),
        historical_input=_historical_input(),
        live_inputs=[item.to_payload() for item in minutes],
    )
    with _session() as session:
        store = SignalDecisionStore(session)
        first = store.create(
            schema,
            result_kind="no_signal",
            direction=None,
            result_payload={"candidates": []},
            decision_at=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
        )
        second = store.create(
            schema,
            result_kind="no_signal",
            direction=None,
            result_payload={"candidates": []},
            decision_at=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
        )
        assert first.id == second.id
        assert len(list(session.scalars(select(SignalDecision)))) == 1

        with pytest.raises(DecisionConflictError, match="SIGNAL_DECISION_CONFLICT"):
            store.create(
                schema,
                result_kind="signal",
                direction="long",
                result_payload={"candidates": ["long"]},
                decision_at=datetime(2026, 8, 2, 13, 15, tzinfo=UTC),
            )
