from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.alerts.evaluators import AlertEvaluation
from app.alerts.composition import RedisAlertHeartbeatStore
from app.alerts.models import AlertEvent, AlertRule
from app.alerts.runtime import AlertRuntime
from app.db.base import Base
from app.market_data.domain import CanonicalBar
from app.market_data.market_read_service import MarketReadWindow
from app.market_data.product_taxonomy import ProductTaxonomyEntry


BAR_END = datetime(2026, 8, 13, 2, 45, tzinfo=UTC)
DAY = date(2026, 8, 13)
CHANNEL = "live:bar:ag:15m"


def _payload(*, bar_end: datetime = BAR_END, trading_day: date = DAY) -> str:
    return json.dumps(
        {
            "bar_end": bar_end.isoformat(),
            "trading_day": trading_day.isoformat(),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "10",
            "turnover": "1000",
            "open_interest": "20",
        }
    )


def _bar() -> CanonicalBar:
    return CanonicalBar(
        bar_end=BAR_END,
        trading_day=DAY,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("10"),
        turnover=Decimal("1000"),
        open_interest=Decimal("20"),
    )


def _window(*, contract: str = "AG2610", cutoff: datetime = BAR_END) -> MarketReadWindow:
    bars = tuple(_bar() for _ in range(32))
    return MarketReadWindow(
        symbol="ag",
        series_kind="actual_dominant",
        frequency="15m",
        trading_day=DAY,
        contract=contract,
        cutoff=cutoff,
        bars=bars,
    )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as active:
        active.add(
            AlertRule(
                rule_code="htdy_original_15m",
                indicator_code="huotian_dayou_original_v0",
                frequency="15m",
                enabled=True,
                scope_mode="watchlist",
                scope_products=["ag"],
            )
        )
        active.commit()
        yield active


class FakeRead:
    def __init__(self, result: MarketReadWindow | Exception | None = None) -> None:
        self.result = result or _window()
        self.calls = 0

    def bars_until(self, *_args, **_kwargs) -> MarketReadWindow:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeEvaluator:
    indicator_code = "huotian_dayou_original_v0"
    frequency = "15m"

    def __init__(self, result: AlertEvaluation | Exception | None = None) -> None:
        self.result = result or AlertEvaluation(("buy",))
        self.calls = 0

    def evaluate(self, _window: MarketReadWindow) -> AlertEvaluation:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeSender:
    def __init__(self) -> None:
        self.messages = []

    def send(self, event) -> None:
        self.messages.append(event)


def _runtime(
    session: Session,
    *,
    read: FakeRead | None = None,
    evaluator: FakeEvaluator | None = None,
    sender: FakeSender | None = None,
    operational_products: tuple[str, ...] = ("ag",),
) -> tuple[AlertRuntime, FakeRead, FakeEvaluator, FakeSender]:
    active_read = read or FakeRead()
    active_evaluator = evaluator or FakeEvaluator()
    active_sender = sender or FakeSender()
    runtime = AlertRuntime(
        session=session,
        market_read=active_read,
        evaluator=active_evaluator,
        sender=active_sender,
        operational_products=operational_products,
        taxonomy={"ag": ProductTaxonomyEntry(name="白银", sector="precious")},
        clock=lambda: datetime(2026, 8, 13, 2, 45, 1, tzinfo=UTC),
    )
    return runtime, active_read, active_evaluator, active_sender


def test_happy_path_commits_once_sends_once_and_duplicate_stops(session: Session) -> None:
    runtime, _read, _evaluator, sender = _runtime(session)

    runtime.process_message(CHANNEL, _payload())
    runtime.process_message(CHANNEL, _payload())

    events = session.scalars(select(AlertEvent)).all()
    assert len(events) == 1
    assert events[0].contract == "AG2610"
    assert events[0].observation_types == ["buy"]
    assert len(sender.messages) == 1
    assert sender.messages[0].product_name == "白银"


@pytest.mark.parametrize(
    ("channel", "payload"),
    (
        ("bad", _payload()),
        ("live:bar:ag:5m", _payload()),
        (CHANNEL, "not-json"),
        (CHANNEL, json.dumps({"bar_end": BAR_END.isoformat()})),
    ),
)
def test_malformed_or_wrong_frequency_skips_before_market_read(
    session: Session,
    channel: str,
    payload: object,
) -> None:
    runtime, read, evaluator, sender = _runtime(session)

    runtime.process_message(channel, payload)

    assert read.calls == evaluator.calls == 0
    assert sender.messages == []


def test_disabled_out_of_scope_or_non_operational_stops_before_market_read(session: Session) -> None:
    rule = session.scalar(select(AlertRule))
    assert rule is not None
    runtime, read, _evaluator, sender = _runtime(session)

    rule.enabled = False
    session.commit()
    runtime.process_message(CHANNEL, _payload())
    rule.enabled = True
    rule.scope_products = []
    session.commit()
    runtime.process_message(CHANNEL, _payload())
    rule.scope_products = ["ag"]
    session.commit()
    outside, outside_read, _outside_eval, outside_sender = _runtime(
        session, operational_products=("j",)
    )
    outside.process_message(CHANNEL, _payload())

    assert read.calls == 0
    assert outside_read.calls == 0
    assert sender.messages == outside_sender.messages == []


@pytest.mark.parametrize("revocation", ("disable", "scope_remove"))
def test_runtime_refreshes_rule_truth_after_another_session_revokes_authorization(
    revocation: str,
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'alerts.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as runtime_session:
        runtime_session.add(
            AlertRule(
                rule_code="htdy_original_15m",
                indicator_code="huotian_dayou_original_v0",
                frequency="15m",
                enabled=True,
                scope_mode="watchlist",
                scope_products=["ag"],
            )
        )
        runtime_session.commit()
        runtime, read, _evaluator, sender = _runtime(runtime_session)
        cached_rule = runtime._enabled_rule("ag")
        assert cached_rule is not None

        with Session(engine) as writer:
            rule = writer.scalar(select(AlertRule))
            assert rule is not None
            if revocation == "disable":
                rule.enabled = False
            else:
                rule.scope_products = []
            writer.commit()

        assert cached_rule.enabled is True
        assert cached_rule.scope_products == ["ag"]

        runtime.process_message(CHANNEL, _payload())

        assert read.calls == 0
        assert sender.messages == []


@pytest.mark.parametrize(
    ("read_result", "evaluation"),
    (
        (RuntimeError("read failed"), None),
        (_window(cutoff=BAR_END - timedelta(minutes=15)), None),
        (_window(contract="J2609"), None),
        (_window(), RuntimeError("kernel failed")),
        (_window(), AlertEvaluation(())),
    ),
)
def test_read_identity_evaluator_or_empty_observation_failure_never_sends(
    session: Session,
    read_result: MarketReadWindow | Exception,
    evaluation: AlertEvaluation | Exception | None,
) -> None:
    runtime, _read, _evaluator, sender = _runtime(
        session,
        read=FakeRead(read_result),
        evaluator=FakeEvaluator(evaluation) if evaluation is not None else None,
    )

    runtime.process_message(CHANNEL, _payload())

    assert session.scalars(select(AlertEvent)).all() == []
    assert sender.messages == []


def test_database_create_failure_rolls_back_and_never_sends(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _read, _evaluator, sender = _runtime(session)

    def fail_create(*_args, **_kwargs):
        raise RuntimeError("database failed")

    monkeypatch.setattr("app.alerts.runtime.AlertService.create_event", fail_create)

    runtime.process_message(CHANNEL, _payload())

    assert session.in_transaction() is False
    assert sender.messages == []


@pytest.mark.parametrize("numeric", ("not-a-number", "NaN", "Infinity"))
def test_malformed_or_nonfinite_numeric_payload_is_a_no_send_skip(
    session: Session,
    numeric: str,
) -> None:
    payload = json.loads(_payload())
    payload["close"] = numeric
    runtime, read, evaluator, sender = _runtime(session)

    runtime.process_message(CHANNEL, json.dumps(payload))

    assert read.calls == evaluator.calls == 0
    assert sender.messages == []


class FakeMessageSource:
    def __init__(self, stop_states: list[bool]) -> None:
        self.patterns: list[str] = []
        self.stop_states = stop_states

    def subscribe(self, pattern: str) -> None:
        self.patterns.append(pattern)

    def get_message(self, *, timeout_seconds: float):
        assert timeout_seconds == 1.0
        return None

    def close(self) -> None:
        return None


class FakeHeartbeatStore:
    def __init__(self) -> None:
        self.writes: list[tuple[dict[str, object], int]] = []

    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None:
        self.writes.append((payload, ttl_seconds))


def test_redis_heartbeat_store_sets_value_and_ttl_atomically() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.calls = []

        def set(self, *args, **kwargs):
            self.calls.append((args, kwargs))

        def expire(self, *_args, **_kwargs):
            raise AssertionError("heartbeat TTL must be atomic with SET")

    redis = FakeRedis()

    RedisAlertHeartbeatStore(redis).write({"available": True}, ttl_seconds=30)

    assert len(redis.calls) == 1
    assert redis.calls[0][0][0] == "alert:heartbeat"
    assert json.loads(redis.calls[0][0][1]) == {"available": True}
    assert redis.calls[0][1] == {"ex": 30}


def test_run_forever_heartbeat_has_fixed_fields_10s_cadence_and_30s_ttl(session: Session) -> None:
    moments = iter(
        datetime(2026, 8, 13, 0, 0, second, tzinfo=UTC)
        for second in (0, 0, 5, 10, 10, 15, 20, 20)
    )
    checks = iter((False, False, False, False, False, False, True))
    source = FakeMessageSource([])
    heartbeats = FakeHeartbeatStore()
    runtime, *_ = _runtime(session)
    runtime.message_source = source
    runtime.heartbeat_store = heartbeats
    runtime.clock = lambda: next(moments)
    runtime.stop_requested = lambda: next(checks)

    runtime.run_forever()

    assert source.patterns == ["live:bar:*:15m"]
    assert [ttl for _payload, ttl in heartbeats.writes] == [30, 30, 30]
    assert [set(payload) for payload, _ttl in heartbeats.writes] == [
        {"generated_at", "available", "enabled_rule_count", "scope_product_count"}
    ] * 3
    assert [payload["generated_at"] for payload, _ttl in heartbeats.writes] == [
        "2026-08-13T00:00:00+00:00",
        "2026-08-13T00:00:10+00:00",
        "2026-08-13T00:00:20+00:00",
    ]
