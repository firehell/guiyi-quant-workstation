from __future__ import annotations

import importlib
import json
from collections import deque
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fnmatch import fnmatch
from typing import Any

import pytest

from app.market_data.aggregation import SessionWindow, aggregate_from_1m
from app.market_data.domain import CanonicalBar
from app.market_data.live_market import LIVE_SESSION_END_ARRIVAL_GRACE
from app.market_data.market_phase import MarketPhase, ProductMarketPhase


class FakeRedis:
    """Small in-memory Redis boundary fake; no configured Redis is ever touched."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.zsets: dict[str, dict[str, int]] = {}
        self.ttls: dict[str, int] = {}
        self.published: list[tuple[str, str]] = []
        self.fail_zadd = 0
        self.fail_heartbeat_set = 0
        self.fail_live_bar_publish_at: int | None = None
        self.live_bar_publish_attempts = 0

    def zadd(self, key: str, mapping: dict[str, int]) -> int:
        if self.fail_zadd:
            self.fail_zadd -= 1
            raise ConnectionError("fake redis unavailable")
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)

    def zremrangebyscore(self, key: str, minimum: int, maximum: int) -> int:
        values = self.zsets.get(key, {})
        members = [member for member, score in values.items() if minimum <= score <= maximum]
        for member in members:
            del values[member]
        return len(members)

    def zrangebyscore(self, key: str, minimum: str | int, maximum: str | int) -> list[str]:
        lower_exclusive = isinstance(minimum, str) and minimum.startswith("(")
        lower = float("-inf") if minimum == "-inf" else int(str(minimum).lstrip("("))
        upper = float("inf") if maximum == "+inf" else int(maximum)
        return [
            member
            for member, score in sorted(self.zsets.get(key, {}).items(), key=lambda item: (item[1], item[0]))
            if (score > lower if lower_exclusive else score >= lower) and score <= upper
        ]

    def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        if key == "live:heartbeat" and self.fail_heartbeat_set:
            self.fail_heartbeat_set -= 1
            return False
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True

    def scan_iter(self, match: str) -> list[str]:
        return [key for key in (*self.values, *self.zsets) if fnmatch(key, match)]

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            existed = key in self.values or key in self.zsets
            self.values.pop(key, None)
            self.zsets.pop(key, None)
            self.ttls.pop(key, None)
            deleted += int(existed)
        return deleted

    def publish(self, channel: str, message: str) -> int:
        if channel.startswith("live:bar:"):
            self.live_bar_publish_attempts += 1
            if self.fail_live_bar_publish_at == self.live_bar_publish_attempts:
                raise ConnectionError("fake redis unavailable")
        self.published.append((channel, message))
        return 1


def _bar(minute: int, *, price: str = "100.1250") -> CanonicalBar:
    return CanonicalBar(
        bar_end=datetime(2025, 1, 2, 1, minute, tzinfo=UTC),
        trading_day=date(2025, 1, 2),
        open=Decimal(price),
        high=Decimal("101.0000"),
        low=Decimal("99.0000"),
        close=Decimal("100.7500"),
        volume=Decimal("12.500"),
        turnover=Decimal("1253.125000"),
        open_interest=Decimal("70.000"),
    )


def _raw_payload(contract: str, bar: CanonicalBar) -> dict[str, Any]:
    return {
        "action": "feed",
        "channel": f"bar_{contract}",
        "order_book_id": contract,
        "datetime": bar.bar_end.isoformat(),
        "trading_date": bar.trading_day.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "total_turnover": None if bar.turnover is None else str(bar.turnover),
        "open_interest": None if bar.open_interest is None else str(bar.open_interest),
    }


def _bar_payload(bar: CanonicalBar) -> dict[str, str | None]:
    return {
        "bar_end": bar.bar_end.isoformat(),
        "trading_day": bar.trading_day.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "turnover": None if bar.turnover is None else str(bar.turnover),
        "open_interest": None if bar.open_interest is None else str(bar.open_interest),
    }


def _store(fake: FakeRedis) -> Any:
    module = importlib.import_module("app.market_data.live_market")
    return module.RedisLiveStore(fake)


def test_live_bars_are_score_ordered_after_exclusive_and_decimal_lossless() -> None:
    """Catches score rounding, inclusive cursors, and JSON number coercion."""
    fake = FakeRedis()
    store = _store(fake)
    day = date(2025, 1, 2)
    later, earlier = _bar(2), _bar(1)

    store.put_bar(day, "RB", "1m", later, contract="RB2505")
    store.put_bar(day, "RB", "1m", earlier, contract="RB2505")

    assert store.bars_after(day, "RB", "1m", None) == (earlier, later)
    assert store.bars_after(day, "RB", "1m", earlier.bar_end) == (later,)
    assert store.bars_between(day, "RB", "1m", earlier.bar_end, later.bar_end) == (earlier, later)
    assert fake.ttls["live:bars:2025-01-02:RB:1m"] == timedelta(days=3).total_seconds()
    member = next(
        member
        for member in fake.zsets["live:bars:2025-01-02:RB:1m"]
        if json.loads(member)["bar_end"] == "2025-01-02T01:01:00+00:00"
    )
    assert fake.zsets["live:bars:2025-01-02:RB:1m"][member] == 1735779660000
    payload = json.loads(member)
    assert payload["open"] == "100.1250"
    assert payload["volume"] == "12.500"


def test_live_bar_provenance_is_normalized_without_changing_generic_reads() -> None:
    fake = FakeRedis()
    store = _store(fake)
    day = date(2025, 1, 2)
    bar = _bar(1)

    store.put_bar(day, "j", "1m", bar, contract="j2505")

    assert store.bars_after(day, "j", "1m", None) == (bar,)
    observations = store.bar_observations(
        day,
        "j",
        "1m",
        None,
        bar.bar_end,
        inclusive_after=False,
        expected_contract="J2505",
    )
    assert tuple(item.bar for item in observations) == (bar,)
    assert tuple(item.contract for item in observations) == ("J2505",)
    member = next(iter(fake.zsets["live:bars:2025-01-02:j:1m"]))
    assert json.loads(member)["contract"] == "J2505"


@pytest.mark.parametrize("provenance", [None, "invalid", "J2509"], ids=("missing", "invalid", "mismatch"))
def test_provenance_read_rejects_legacy_invalid_or_mismatched_rows(
    provenance: str | None,
) -> None:
    fake = FakeRedis()
    store = _store(fake)
    day = date(2025, 1, 2)
    bar = _bar(1)
    payload = _bar_payload(bar)
    if provenance is not None:
        payload["contract"] = provenance
    key = "live:bars:2025-01-02:j:1m"
    fake.zadd(
        key,
        {json.dumps(payload, separators=(",", ":")): int(bar.bar_end.timestamp() * 1000)},
    )

    with pytest.raises(ValueError, match="LIVE_BAR_PROVENANCE_INVALID"):
        store.bar_observations(
            day,
            "j",
            "1m",
            None,
            bar.bar_end,
            inclusive_after=False,
            expected_contract="J2505",
        )


def test_subscriptions_are_trading_day_isolated_and_expire() -> None:
    """Catches subscription state leaking across trading days or losing its TTL."""
    fake = FakeRedis()
    store = _store(fake)
    first_day = date(2025, 1, 2)
    next_day = date(2025, 1, 3)
    mapping = {"RB": ["1m", "5m"]}

    store.set_subscriptions(first_day, mapping)

    assert store.subscriptions(first_day) == mapping
    assert store.subscriptions(next_day) is None
    assert fake.ttls["live:subscription:2025-01-02"] == timedelta(days=3).total_seconds()


def test_cleanup_removes_only_requested_trading_day() -> None:
    """Catches cleanup deleting another day's transient observation state."""
    fake = FakeRedis()
    store = _store(fake)
    first_day = date(2025, 1, 2)
    next_day = date(2025, 1, 3)
    store.put_bar(first_day, "RB", "1m", _bar(1), contract="RB2505")
    store.set_subscriptions(first_day, {"RB": ["1m"]})
    store.put_bar(next_day, "RB", "1m", _bar(1), contract="RB2505")
    store.set_subscriptions(next_day, {"RB": ["1m"]})

    store.cleanup_trading_day(first_day)

    assert store.bars_after(first_day, "RB", "1m", _bar(1).bar_end) == ()
    assert store.subscriptions(first_day) is None
    assert store.bars_after(next_day, "RB", "1m", _bar(1).bar_end - timedelta(minutes=1)) == (_bar(1),)
    assert store.subscriptions(next_day) == {"RB": ["1m"]}


def test_public_pubsub_channel_contract_and_compact_payloads() -> None:
    """Catches publish methods drifting from the public WebSocket channel contract."""
    fake = FakeRedis()
    module = importlib.import_module("app.market_data.live_market")
    store = _store(fake)
    bar = _bar(1)

    store.set_heartbeat({"state": "healthy"})
    store.publish_bar("RB", "1m", bar)
    store.publish_state({"state": "healthy"})

    assert module.live_bar_channel("RB", "1m") == "live:bar:RB:1m"
    assert module.LIVE_STATE_CHANNEL == "market:state"
    assert store.heartbeat() == {"state": "healthy"}
    assert fake.ttls["live:heartbeat"] == 30
    assert fake.published == [
        (
            "live:bar:RB:1m",
            '{"bar_end":"2025-01-02T01:01:00+00:00","trading_day":"2025-01-02","open":"100.1250","high":"101.0000","low":"99.0000","close":"100.7500","volume":"12.500","turnover":"1253.125000","open_interest":"70.000"}',
        ),
        ("market:state", '{"state":"healthy"}'),
    ]


class FakeListener:
    def __init__(self) -> None:
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive


class FakeLiveClient:
    """Injectable provider fake; it never contacts RQData."""

    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.payloads: list[dict[str, Any]] = []
        self.fail_listen = False
        self.fail_unsubscribe = False
        self.listen_calls = 0
        self.handler = None
        self.listener = FakeListener()
        self.closed = False

    def subscribe(self, channels: tuple[str, ...]) -> None:
        self.subscribed.extend(channels)

    def unsubscribe(self, channels: tuple[str, ...]) -> None:
        if self.fail_unsubscribe:
            raise ConnectionError("provider unavailable")
        self.unsubscribed.extend(channels)

    def listen(self, *, handler) -> FakeListener:
        self.listen_calls += 1
        if self.fail_listen:
            raise ConnectionError("provider unavailable")
        self.handler = handler
        payloads = tuple(self.payloads)
        self.payloads.clear()
        for payload in payloads:
            handler(payload)
        return self.listener

    def close(self) -> None:
        self.closed = True

    def emit(self, payload: dict[str, Any]) -> None:
        if self.handler is None:
            self.payloads.append(payload)
        else:
            self.handler(payload)


class FakeDominants:
    def __init__(self, mapping: dict[tuple[str, date], str]) -> None:
        self.mapping = mapping
        self.calls: list[tuple[str, date]] = []

    def dominant_for_day(self, symbol: str, trading_day: date) -> str:
        self.calls.append((symbol, trading_day))
        return self.mapping[(symbol, trading_day)]


class FakePhases:
    def __init__(self, phases: dict[str, ProductMarketPhase]) -> None:
        self.phases = phases

    def resolve(self, symbol: str, _now: datetime) -> ProductMarketPhase:
        return self.phases[symbol]


def _phase(
    symbol: str,
    trading_day: date,
    session: SessionWindow | None,
    state: MarketPhase = MarketPhase.TRADING,
) -> ProductMarketPhase:
    return ProductMarketPhase(symbol, state, trading_day, session, None)


def _live_service(
    *,
    client: FakeLiveClient,
    dominants: FakeDominants,
    phases: FakePhases,
    store: Any,
    products: tuple[str, ...] = ("j", "jm"),
) -> Any:
    module = importlib.import_module("app.market_data.live_market")
    return module.LiveMarketService(
        provider_factory=lambda: module.RQDataLiveProvider(client),
        dominant_source=dominants,
        phase_resolver=phases,
        store=store,
        operational_products=products,
    )


def test_rank1_subscription_lifecycle_is_once_per_trading_day_and_never_continuous() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    next_day = date(2025, 1, 3)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    dominants = FakeDominants(
        {("j", day): "J2505", ("jm", day): "JM2505", ("j", next_day): "J2509", ("jm", next_day): "JM2509"}
    )
    phases = FakePhases({"j": _phase("j", day, window), "jm": _phase("jm", day, window)})
    service = _live_service(client=client, dominants=dominants, phases=phases, store=module.RedisLiveStore(fake))

    service.reconcile(datetime(2025, 1, 2, 1, 1, tzinfo=UTC))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)
    service.reconcile(datetime(2025, 1, 2, 1, 30, tzinfo=UTC))
    phases.phases = {"j": _phase("j", next_day, window), "jm": _phase("jm", next_day, window)}
    service.reconcile(datetime(2025, 1, 3, 1, 1, tzinfo=UTC))

    assert dominants.calls == [("j", day), ("jm", day), ("j", next_day), ("jm", next_day)]
    assert client.subscribed == ["bar_J2505", "bar_JM2505", "bar_J2509", "bar_JM2509"]
    assert client.unsubscribed == ["bar_J2505", "bar_JM2505"]
    assert all("88" not in channel for channel in (*client.subscribed, *client.unsubscribed))
    assert fake.values["live:subscription:2025-01-03"] == '{"j":"J2509","jm":"JM2509"}'
    state_events = [json.loads(payload) for channel, payload in fake.published if channel == "market:state"]
    assert state_events == [
        {"trading_day": "2025-01-02"},
        {"trading_day": "2025-01-03"},
    ]


def test_restart_restores_frozen_rank1_snapshot_without_resolving_again() -> None:
    """Catches a same-trading-day restart replacing the already frozen rank1 contract."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    store = module.RedisLiveStore(fake)
    store.set_subscriptions(day, {"j": "J2505"})
    client = FakeLiveClient()
    dominants = FakeDominants({("j", day): "J2509"})
    service = _live_service(
        client=client,
        dominants=dominants,
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=store,
        products=("j",),
    )

    assert service.reconcile(datetime(2025, 1, 2, 1, 1, tzinfo=UTC)) is None
    assert dominants.calls == []
    assert client.subscribed == ["bar_J2505"]
    assert store.subscriptions(day) == {"j": "J2505"}


def test_rank1_snapshot_covers_the_universe_without_subscribing_closed_products() -> None:
    """The day snapshot is complete while provider channels remain phase-scoped."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    dominants = FakeDominants({("j", day): "J2505", ("ap", day): "AP2505"})
    phases = FakePhases(
        {
            "j": _phase("j", day, window),
            "ap": _phase("ap", day, None, MarketPhase.CLOSED),
        }
    )
    service = _live_service(
        client=client,
        dominants=dominants,
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j", "ap"),
    )

    assert service.reconcile(datetime(2025, 1, 2, 1, 1, tzinfo=UTC)) is None
    assert dominants.calls == [("j", day), ("ap", day)]
    assert client.subscribed == ["bar_J2505"]
    assert json.loads(fake.values["live:subscription:2025-01-02"]) == {
        "ap": "AP2505",
        "j": "J2505",
    }

    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)
    phases.phases["ap"] = _phase("ap", day, window)

    assert service.reconcile(datetime(2025, 1, 2, 1, 30, tzinfo=UTC)) is None
    assert dominants.calls == [("j", day), ("ap", day)]
    assert client.subscribed == ["bar_J2505", "bar_AP2505"]
    assert json.loads(fake.values["live:subscription:2025-01-02"]) == {
        "ap": "AP2505",
        "j": "J2505",
    }


def test_completed_1m_bar_is_pending_then_immutable_and_outside_session_is_rejected() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.reconcile(datetime(2025, 1, 2, 1, 1, tzinfo=UTC))
    first = _bar(1, price="100")
    replacement = _bar(1, price="101")

    assert service.ingest("J2505", first, now=datetime(2025, 1, 2, 1, 1, 1, tzinfo=UTC)) is None
    assert service.ingest("J2505", replacement, now=datetime(2025, 1, 2, 1, 1, 1, tzinfo=UTC)) is None
    assert service.flush_due(datetime(2025, 1, 2, 1, 1, 1, tzinfo=UTC)) == ()
    assert service.flush_due(datetime(2025, 1, 2, 1, 1, 2, tzinfo=UTC)) == (replacement,)
    assert service.ingest("J2505", first, now=datetime(2025, 1, 2, 1, 1, 3, tzinfo=UTC)) == "LIVE_BAR_FINALIZED"
    outside = CanonicalBar(
        bar_end=datetime(2025, 1, 2, 1, 6, tzinfo=UTC), trading_day=day,
        open=Decimal("1"), high=Decimal("1"), low=Decimal("1"), close=Decimal("1"), volume=Decimal("1"),
        turnover=None, open_interest=None,
    )
    assert service.ingest("J2505", outside, now=datetime(2025, 1, 2, 1, 6, 2, tzinfo=UTC)) == "LIVE_BAR_OUTSIDE_SESSION"
    assert service.rejections == ["LIVE_BAR_FINALIZED", "LIVE_BAR_OUTSIDE_SESSION"]
    assert module.RedisLiveStore(fake).bars_after(day, "j", "1m", None) == (replacement,)


def test_raw_rqdata_bar_feeds_buffer_and_latest_payload_wins_through_poll() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    first = _bar(1, price="100")
    replacement = _bar(1, price="101")
    client.payloads = [_raw_payload("J2505", first), _raw_payload("J2505", replacement)]

    assert service.poll(datetime(2025, 1, 2, 1, 1, 1, tzinfo=UTC)) is None
    assert service.poll(datetime(2025, 1, 2, 1, 1, 2, tzinfo=UTC)) is None

    assert client.listen_calls == 1
    assert module.RedisLiveStore(fake).bars_after(day, "j", "1m", None) == (replacement,)


def test_raw_tick_partial_and_unknown_feeds_are_dropped_before_service_ingest() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    complete = _raw_payload("J2505", _bar(1))
    client.payloads = [
        {**complete, "channel": "tick_J2505"},
        {key: value for key, value in complete.items() if key != "close"},
        {**complete, "action": "snapshot"},
    ]

    assert service.poll(datetime(2025, 1, 2, 1, 1, 2, tzinfo=UTC)) is None
    assert module.RedisLiveStore(fake).bars_after(day, "j", "1m", None) == ()


def test_adapter_atomic_drain_keeps_callback_message_arriving_after_snapshot() -> None:
    module = importlib.import_module("app.market_data.live_market")
    client = FakeLiveClient()
    provider = module.RQDataLiveProvider(client)
    first = _raw_payload("J2505", _bar(1))
    second = _raw_payload("J2505", _bar(2))

    class SnapshotThenCallbackDeque(deque):
        def __iter__(self):
            snapshot = tuple(super().__iter__())
            provider._buffer_message(second)
            return iter(snapshot)

    provider._messages = SnapshotThenCallbackDeque((first,))
    provider._listener = client.listener

    assert tuple(bar for _contract, bar in provider.poll()) == (_bar(1),)
    assert tuple(bar for _contract, bar in provider.poll()) == (_bar(2),)


def test_adapter_keeps_callback_arriving_between_queue_swap_and_listener_stop() -> None:
    """Catches a callback entering the new queue just before its listener exits."""
    module = importlib.import_module("app.market_data.live_market")
    client = FakeLiveClient()
    provider = module.RQDataLiveProvider(client)
    final = _raw_payload("J2505", _bar(5))

    class EmptySnapshotThenFinalCallbackDeque(deque):
        def __iter__(self):
            snapshot = tuple(super().__iter__())
            provider._buffer_message(final)
            client.listener.alive = False
            return iter(snapshot)

    provider._messages = EmptySnapshotThenFinalCallbackDeque()
    provider._listener = client.listener

    assert provider.poll_buffered() == ()
    assert tuple(bar for _contract, bar in provider.poll_buffered()) == (_bar(5),)
    with pytest.raises(ConnectionError, match="LIVE_PROVIDER_LISTENER_STOPPED"):
        provider.poll_buffered()


def test_adapter_dead_listener_closes_client_and_surfaces_provider_failure() -> None:
    """Catches a dead handler thread degrading into an endless empty queue."""
    module = importlib.import_module("app.market_data.live_market")
    client = FakeLiveClient()
    provider = module.RQDataLiveProvider(client)

    assert provider.poll() == ()
    client.listener.alive = False

    with pytest.raises(ConnectionError, match="LIVE_PROVIDER_LISTENER_STOPPED"):
        provider.poll()
    assert client.closed is True


def test_trading_heartbeat_becomes_unavailable_when_completed_bars_are_stale() -> None:
    """Catches a fresh process heartbeat masking a silent live feed."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    service = _live_service(
        client=FakeLiveClient(),
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    bar = _bar(1)

    service.reconcile(bar.bar_end)
    assert json.loads(fake.values["live:heartbeat"])["available"] is False
    assert service.ingest("J2505", bar, now=bar.bar_end + timedelta(seconds=2)) is None
    assert service.flush_due(bar.bar_end + timedelta(seconds=2)) == (bar,)

    service.reconcile(bar.bar_end + timedelta(minutes=4, seconds=59))
    assert json.loads(fake.values["live:heartbeat"])["available"] is True

    service.reconcile(bar.bar_end + timedelta(minutes=5))
    assert json.loads(fake.values["live:heartbeat"])["available"] is True

    service.reconcile(bar.bar_end + timedelta(minutes=5, seconds=1))
    assert json.loads(fake.values["live:heartbeat"])["available"] is False


def test_first_completed_bar_is_published_only_after_live_heartbeat_is_ready() -> None:
    """The Alert consumer must never observe a completed Bar before readiness."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )

    class HeartbeatObservingRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.heartbeat_at_completed_bar_publish: list[dict[str, Any]] = []

        def publish(self, channel: str, message: str) -> int:
            if channel == module.live_bar_channel("j", "1m"):
                self.heartbeat_at_completed_bar_publish.append(
                    json.loads(self.values["live:heartbeat"])
                )
            return super().publish(channel, message)

    fake = HeartbeatObservingRedis()
    client = FakeLiveClient()
    bar = _bar(1)
    client.payloads = [_raw_payload("J2505", bar)]
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )

    assert service.poll(bar.bar_end + timedelta(seconds=1)) is None
    assert service.poll(bar.bar_end + timedelta(seconds=2)) is None

    assert fake.heartbeat_at_completed_bar_publish == [
        {
            "generated_at": (bar.bar_end + timedelta(seconds=2)).isoformat(),
            "operational_count": 1,
            "subscribed_count": 1,
            "last_bar_at": bar.bar_end.isoformat(),
            "phase_counts": {"TRADING": 1},
            "available": True,
        }
    ]


def test_break_resume_first_completed_bar_is_published_after_heartbeat_recovers() -> None:
    """Catches the first post-break Bar being published against a stale heartbeat."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    morning = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    afternoon = SessionWindow(
        datetime(2025, 1, 2, 3, tzinfo=UTC), datetime(2025, 1, 2, 4, tzinfo=UTC)
    )

    class HeartbeatObservingRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.heartbeat_at_completed_bar_publish: list[dict[str, Any]] = []

        def publish(self, channel: str, message: str) -> int:
            if channel == module.live_bar_channel("j", "1m"):
                self.heartbeat_at_completed_bar_publish.append(
                    json.loads(self.values["live:heartbeat"])
                )
            return super().publish(channel, message)

    fake = HeartbeatObservingRedis()
    phases = FakePhases({"j": _phase("j", day, morning)})
    service = _live_service(
        client=FakeLiveClient(),
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    first = _bar(1)
    service.reconcile(first.bar_end)
    assert service.ingest("J2505", first, now=first.bar_end + timedelta(seconds=1)) is None
    assert service.flush_due(first.bar_end + timedelta(seconds=2)) == (first,)

    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)
    service.reconcile(datetime(2025, 1, 2, 2, 30, tzinfo=UTC))
    phases.phases["j"] = _phase("j", day, afternoon)
    resumed = replace(first, bar_end=datetime(2025, 1, 2, 3, 1, tzinfo=UTC))
    service.reconcile(resumed.bar_end + timedelta(seconds=1))
    assert json.loads(fake.values["live:heartbeat"])["available"] is False
    assert service.ingest("J2505", resumed, now=resumed.bar_end + timedelta(seconds=1)) is None

    assert service.flush_due(resumed.bar_end + timedelta(seconds=2)) == (resumed,)
    assert fake.heartbeat_at_completed_bar_publish[-1]["available"] is True
    assert fake.heartbeat_at_completed_bar_publish[-1]["last_bar_at"] == resumed.bar_end.isoformat()


def test_heartbeat_write_failure_blocks_completed_and_derived_bar_publication() -> None:
    """Catches an unconfirmed readiness write being treated as safe to publish."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    service = _live_service(
        client=FakeLiveClient(),
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    bar = _bar(1)
    service.reconcile(bar.bar_end)
    assert service.ingest("J2505", bar, now=bar.bar_end + timedelta(seconds=1)) is None
    fake.fail_heartbeat_set = 1

    assert service.flush_due(bar.bar_end + timedelta(seconds=2)) == ()
    assert [event for event in fake.published if event[0].startswith("live:bar:")] == []
    store = module.RedisLiveStore(fake)
    assert store.bars_after(day, "j", "5m", None) == ()
    assert store.bars_after(day, "j", "15m", None) == ()
    assert json.loads(fake.values["live:heartbeat"])["available"] is False


def test_batch_persistence_failure_blocks_every_due_bar_until_a_later_retry() -> None:
    """Catches a failed due Bar being masked by a later successful Bar in the same flush."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    service = _live_service(
        client=FakeLiveClient(),
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    first, second = _bar(1), _bar(2)
    service.reconcile(first.bar_end)
    assert service.ingest("J2505", first, now=first.bar_end + timedelta(seconds=1)) is None
    assert service.ingest("J2505", second, now=second.bar_end + timedelta(seconds=1)) is None
    fake.fail_zadd = 1

    assert service.flush_due(second.bar_end + timedelta(seconds=2)) == ()
    assert [event for event in fake.published if event[0].startswith("live:bar:")] == []
    assert len(service._pending) == 2
    assert json.loads(fake.values["live:heartbeat"])["available"] is False


def test_poll_does_not_retry_failed_due_bar_within_the_same_cycle() -> None:
    """Catches poll's second flush making a transient Redis failure visible to Alert."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    service = _live_service(
        client=FakeLiveClient(),
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    bar = _bar(1)
    service.reconcile(bar.bar_end)
    assert service.ingest("J2505", bar, now=bar.bar_end + timedelta(seconds=1)) is None
    fake.fail_zadd = 1

    assert service.poll(bar.bar_end + timedelta(seconds=2)) == "LIVE_REDIS_UNAVAILABLE"
    assert [event for event in fake.published if event[0].startswith("live:bar:")] == []
    assert len(service._pending) == 1


def test_mid_batch_publish_failure_stops_later_due_bar_publication() -> None:
    """Catches a failed PubSub write being masked by a later Bar in the same flush."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    service = _live_service(
        client=FakeLiveClient(),
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    first, second, third = _bar(1), _bar(2), _bar(3)
    service.reconcile(first.bar_end)
    assert service.ingest("J2505", first, now=first.bar_end + timedelta(seconds=1)) is None
    assert service.ingest("J2505", second, now=second.bar_end + timedelta(seconds=1)) is None
    assert service.ingest("J2505", third, now=third.bar_end + timedelta(seconds=1)) is None
    fake.fail_live_bar_publish_at = 2

    assert service.flush_due(third.bar_end + timedelta(seconds=2)) == (first,)
    assert [event for event in fake.published if event[0].startswith("live:bar:")] == [
        ("live:bar:j:1m", json.dumps(_bar_payload(first), separators=(",", ":")))
    ]
    assert len(service._pending) == 2
    assert json.loads(fake.values["live:heartbeat"])["available"] is False


def test_idle_heartbeat_does_not_require_new_completed_bars() -> None:
    """Catches scheduled breaks being mislabeled unavailable only because bars stop."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=FakeLiveClient(),
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    bar = _bar(1)
    service.reconcile(bar.bar_end)
    assert service.ingest("J2505", bar, now=bar.bar_end + timedelta(seconds=2)) is None
    assert service.flush_due(bar.bar_end + timedelta(seconds=2)) == (bar,)
    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)

    service.reconcile(bar.bar_end + timedelta(minutes=30))

    assert json.loads(fake.values["live:heartbeat"])["available"] is True


def test_break_detects_dead_started_listener_without_reconnecting() -> None:
    """Catches session-grace draining a dead listener while still claiming availability."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    started = window.start + timedelta(minutes=1)
    assert service.poll(started) is None
    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)
    client.listener.alive = False

    assert service.poll(started + timedelta(seconds=1)) == "LIVE_PROVIDER_UNAVAILABLE"
    assert client.closed is True
    assert client.listen_calls == 1
    heartbeat = json.loads(fake.values["live:heartbeat"])
    assert heartbeat["available"] is False
    assert heartbeat["subscribed_count"] == 0
    assert service._provider is None
    assert service._channels == set()

    assert (
        service.poll(window.end + LIVE_SESSION_END_ARRIVAL_GRACE + timedelta(seconds=1))
        is None
    )
    heartbeat = json.loads(fake.values["live:heartbeat"])
    assert heartbeat["available"] is False
    assert heartbeat["subscribed_count"] == 0
    assert client.unsubscribed == []


def test_latest_completed_bar_time_never_moves_backwards() -> None:
    """Catches a delayed older product Bar making a healthy global feed look stale."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    service = _live_service(
        client=FakeLiveClient(),
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    newer = _bar(2)
    older = _bar(1)
    service.reconcile(newer.bar_end)
    assert service.ingest("J2505", newer, now=newer.bar_end + timedelta(seconds=2)) is None
    assert service.flush_due(newer.bar_end + timedelta(seconds=2)) == (newer,)
    assert service.ingest("J2505", older, now=newer.bar_end + timedelta(seconds=3)) is None
    assert service.flush_due(newer.bar_end + timedelta(seconds=3)) == (older,)

    service.reconcile(newer.bar_end + timedelta(minutes=5))

    heartbeat = json.loads(fake.values["live:heartbeat"])
    assert heartbeat["last_bar_at"] == newer.bar_end.isoformat()
    assert heartbeat["available"] is True


def test_session_final_bar_is_accepted_during_break_and_finalizes_after_grace() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.reconcile(datetime(2025, 1, 2, 1, 1, tzinfo=UTC))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)
    final = _bar(5)

    assert service.ingest("J2505", final, now=datetime(2025, 1, 2, 1, 5, 1, tzinfo=UTC)) is None
    assert service.flush_due(datetime(2025, 1, 2, 1, 5, 1, tzinfo=UTC)) == ()
    assert service.flush_due(datetime(2025, 1, 2, 1, 5, 2, tzinfo=UTC)) == (final,)


def test_started_provider_drains_buffered_final_raw_bar_during_break_grace() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.poll(datetime(2025, 1, 2, 1, 1, tzinfo=UTC))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)
    client.emit(_raw_payload("J2505", _bar(5)))

    assert service.poll(datetime(2025, 1, 2, 1, 5, 1, tzinfo=UTC)) is None
    assert service.poll(datetime(2025, 1, 2, 1, 5, 2, tzinfo=UTC)) is None
    assert module.RedisLiveStore(fake).bars_after(day, "j", "1m", None) == (_bar(5),)
    assert client.listen_calls == 1 and client.subscribed == ["bar_J2505"]


def test_dead_listener_delivers_buffered_final_bar_before_provider_is_discarded() -> None:
    """Catches listener death dropping a final Bar already accepted by its handler."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.poll(window.start + timedelta(minutes=1))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)
    final = _bar(5)
    client.emit(_raw_payload("J2505", final))
    client.listener.alive = False

    assert service.poll(window.end + timedelta(seconds=2)) is None
    assert module.RedisLiveStore(fake).bars_after(day, "j", "1m", None) == (final,)

    assert service.poll(window.end + timedelta(seconds=3)) == "LIVE_PROVIDER_UNAVAILABLE"
    assert client.closed is True
    assert service._provider is None
    assert service._channels == set()


def test_all_idle_keeps_final_bar_through_grace_then_unsubscribes_once() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.poll(window.start + timedelta(minutes=1))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.CLOSED)
    final = _bar(5)
    client.emit(_raw_payload("J2505", final))

    assert service.poll(window.end + timedelta(seconds=60)) is None
    assert client.unsubscribed == []
    heartbeat = json.loads(fake.values["live:heartbeat"])
    assert heartbeat["subscribed_count"] == 1
    assert module.RedisLiveStore(fake).bars_after(day, "j", "1m", None) == (final,)

    assert LIVE_SESSION_END_ARRIVAL_GRACE == timedelta(seconds=60)
    assert (
        service.poll(
            window.end + LIVE_SESSION_END_ARRIVAL_GRACE + timedelta(seconds=1)
        )
        is None
    )
    assert client.unsubscribed == ["bar_J2505"]
    heartbeat = json.loads(fake.values["live:heartbeat"])
    assert heartbeat["subscribed_count"] == 0

    assert service.poll(window.end + timedelta(seconds=62)) is None
    assert client.unsubscribed == ["bar_J2505"]


def test_direct_reconcile_tears_down_all_idle_channel_after_grace() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.reconcile(window.start + timedelta(minutes=1))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.CLOSED)

    assert (
        service.reconcile(
            window.end + LIVE_SESSION_END_ARRIVAL_GRACE + timedelta(seconds=1)
        )
        is None
    )
    assert client.unsubscribed == ["bar_J2505"]
    assert json.loads(fake.values["live:heartbeat"])["subscribed_count"] == 0


def test_mixed_phase_keeps_closed_channel_through_grace_then_removes_only_it() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    j_window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    ag_window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 3, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases(
        {"j": _phase("j", day, j_window), "ag": _phase("ag", day, ag_window)}
    )
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505", ("ag", day): "AG2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j", "ag"),
    )
    service.poll(j_window.start + timedelta(minutes=1))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.CLOSED)

    assert service.poll(j_window.end + timedelta(seconds=10)) is None
    assert client.unsubscribed == []
    assert json.loads(fake.values["live:heartbeat"])["subscribed_count"] == 2

    assert (
        service.poll(
            j_window.end + LIVE_SESSION_END_ARRIVAL_GRACE + timedelta(seconds=1)
        )
        is None
    )
    assert client.unsubscribed == ["bar_J2505"]
    assert json.loads(fake.values["live:heartbeat"])["subscribed_count"] == 1


def test_idle_poll_does_not_create_provider() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    fake = FakeRedis()
    created: list[FakeLiveClient] = []

    def factory():
        client = FakeLiveClient()
        created.append(client)
        return module.RQDataLiveProvider(client)

    service = module.LiveMarketService(
        provider_factory=factory,
        dominant_source=FakeDominants({}),
        phase_resolver=FakePhases({"j": _phase("j", day, None, MarketPhase.CLOSED)}),
        store=module.RedisLiveStore(fake),
        operational_products=("j",),
    )

    assert service.poll(datetime(2025, 1, 2, 1, tzinfo=UTC)) is None
    assert created == []
    assert json.loads(fake.values["live:heartbeat"])["subscribed_count"] == 0


def test_idle_unsubscribe_failure_discards_provider_without_reconnecting() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.poll(window.start + timedelta(minutes=1))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.CLOSED)
    client.fail_unsubscribe = True

    assert (
        service.poll(
            window.end + LIVE_SESSION_END_ARRIVAL_GRACE + timedelta(seconds=1)
        )
        == "LIVE_PROVIDER_UNAVAILABLE"
    )
    assert client.closed is True
    assert service._provider is None
    assert service._channels == set()
    heartbeat = json.loads(fake.values["live:heartbeat"])
    assert heartbeat["subscribed_count"] == 0
    assert heartbeat["available"] is False

    client.fail_unsubscribe = False
    assert service.poll(window.end + timedelta(seconds=62)) is None
    assert service._channels == set()
    heartbeat = json.loads(fake.values["live:heartbeat"])
    assert heartbeat["subscribed_count"] == 0
    assert heartbeat["available"] is False


def test_session_final_bar_arriving_after_finalization_delay_is_still_accepted() -> None:
    """Catches the two-second finalization delay also truncating provider arrival grace."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.poll(datetime(2025, 1, 2, 1, 1, tzinfo=UTC))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)
    client.emit(_raw_payload("J2505", _bar(5)))

    assert service.poll(datetime(2025, 1, 2, 1, 5, 10, tzinfo=UTC)) is None
    assert module.RedisLiveStore(fake).bars_after(day, "j", "1m", None) == (_bar(5),)


def test_closed_product_final_bar_completes_all_derived_while_another_product_trades() -> None:
    """Catches a shorter-session product losing its close while another feed remains active."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    j_window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    ag_window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 3, tzinfo=UTC)
    )
    source = tuple(
        CanonicalBar(
            bar_end=j_window.start + timedelta(minutes=index),
            trading_day=day,
            open=Decimal(index),
            high=Decimal(index + 2),
            low=Decimal(index - 1),
            close=Decimal(index + 1),
            volume=Decimal(index),
            turnover=Decimal(index * 10),
            open_interest=Decimal(index * 100),
        )
        for index in range(1, 61)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases(
        {
            "j": _phase("j", day, j_window),
            "ag": _phase("ag", day, ag_window),
        }
    )
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505", ("ag", day): "AG2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j", "ag"),
    )
    service.poll(j_window.start)
    for bar in source[:-1]:
        service.ingest("J2505", bar, now=bar.bar_end + timedelta(seconds=2))
        service.flush_due(bar.bar_end + timedelta(seconds=2))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.CLOSED)
    client.emit(_raw_payload("J2505", source[-1]))

    assert service.poll(j_window.end + timedelta(seconds=10)) is None
    store = module.RedisLiveStore(fake)
    assert store.bars_after(day, "j", "1m", None) == source
    for frequency in ("5m", "15m", "30m", "60m"):
        assert store.bars_after(day, "j", frequency, None) == aggregate_from_1m(
            source, target_frequency=frequency, sessions=(j_window,)
        )
    assert json.loads(fake.values["live:heartbeat"])["phase_counts"] == {
        "CLOSED": 1,
        "TRADING": 1,
    }


def test_post_session_grace_rejects_nonfinal_and_overdue_final_bars() -> None:
    """Catches the close grace becoming an unbounded replay path for stale session bars."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.poll(datetime(2025, 1, 2, 1, 1, tzinfo=UTC))
    phases.phases["j"] = _phase("j", day, None, MarketPhase.CLOSED)
    client.emit(_raw_payload("J2505", _bar(4)))
    service.poll(window.end + timedelta(seconds=10))
    client.emit(_raw_payload("J2505", _bar(5)))
    service.poll(
        window.end + LIVE_SESSION_END_ARRIVAL_GRACE + timedelta(seconds=1)
    )

    assert module.RedisLiveStore(fake).bars_after(day, "j", "1m", None) == ()
    assert service.rejections == ["LIVE_BAR_OUTSIDE_SESSION", "LIVE_BAR_OUTSIDE_SESSION"]


@pytest.mark.parametrize("rank1", ("J88", "J888", "J2505.CONT", "JM2505"))
def test_invalid_rank1_never_creates_snapshot_or_subscription(rank1: str) -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): rank1}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )

    assert service.reconcile(datetime(2025, 1, 2, 1, 1, tzinfo=UTC)) == "LIVE_RANK1_CONTRACT_INVALID"
    assert fake.values == {}
    assert client.subscribed == []


def test_redis_failure_keeps_due_bar_pending_for_exact_recovery_retry() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 1, 5, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=phases,
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.reconcile(datetime(2025, 1, 2, 1, 1, tzinfo=UTC))
    bar = _bar(1)
    service.ingest("J2505", bar, now=datetime(2025, 1, 2, 1, 1, 1, tzinfo=UTC))
    fake.fail_zadd = 1

    assert service.flush_due(datetime(2025, 1, 2, 1, 1, 2, tzinfo=UTC)) == ()
    assert service.flush_due(datetime(2025, 1, 2, 1, 1, 2, tzinfo=UTC)) == (bar,)
    assert module.RedisLiveStore(fake).bars_after(day, "j", "1m", None) == (bar,)
    live_events = [item for item in fake.published if item[0] == "live:bar:j:1m"]
    assert live_events == [("live:bar:j:1m", json.dumps(_bar_payload(bar), separators=(",", ":")))]


def test_due_bar_retains_ingested_contract_if_mapping_changes_before_flush() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    service = _live_service(
        client=FakeLiveClient(),
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.reconcile(window.start + timedelta(minutes=1))
    bar = _bar(1)
    service.ingest("J2505", bar, now=bar.bar_end + timedelta(seconds=1))
    service._contracts["j"] = "J2509"

    assert service.flush_due(bar.bar_end + timedelta(seconds=2)) == (bar,)
    member = next(iter(fake.zsets["live:bars:2025-01-02:j:1m"]))
    assert json.loads(member)["contract"] == "J2505"
    observations = module.RedisLiveStore(fake).bar_observations(
        day,
        "j",
        "1m",
        None,
        bar.bar_end,
        inclusive_after=False,
        expected_contract="J2505",
    )
    assert tuple(item.bar for item in observations) == (bar,)


def test_live_derived_buckets_match_shared_historical_aggregation_exactly() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    source = tuple(
        CanonicalBar(
            bar_end=window.start + timedelta(minutes=index), trading_day=day,
            open=Decimal(index), high=Decimal(index + 2), low=Decimal(index - 1), close=Decimal(index + 1),
            volume=Decimal(index), turnover=Decimal(index * 10), open_interest=Decimal(index * 100),
        )
        for index in range(1, 61)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client, dominants=FakeDominants({("j", day): "J2505"}), phases=phases,
        store=module.RedisLiveStore(fake), products=("j",),
    )
    service.reconcile(datetime(2025, 1, 2, 1, 1, tzinfo=UTC))
    for bar in source:
        service.ingest("J2505", bar, now=bar.bar_end + timedelta(seconds=2))
        service.flush_due(bar.bar_end + timedelta(seconds=2))

    store = module.RedisLiveStore(fake)
    for frequency in ("5m", "15m", "30m", "60m"):
        assert store.bars_after(day, "j", frequency, None) == aggregate_from_1m(
            source, target_frequency=frequency, sessions=(window,)
        )
    observations = store.bar_observations(
        day,
        "j",
        "15m",
        None,
        source[-1].bar_end,
        inclusive_after=False,
        expected_contract="J2505",
    )
    assert tuple(item.contract for item in observations) == ("J2505",) * 4
    assert tuple(item.bar for item in observations) == aggregate_from_1m(
        source,
        target_frequency="15m",
        sessions=(window,),
    )


def test_live_derived_bucket_rejects_legacy_source_without_provenance() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    source = tuple(
        CanonicalBar(
            bar_end=window.start + timedelta(minutes=index),
            trading_day=day,
            open=Decimal(index),
            high=Decimal(index + 2),
            low=Decimal(index - 1),
            close=Decimal(index + 1),
            volume=Decimal(index),
            turnover=Decimal(index * 10),
            open_interest=Decimal(index * 100),
        )
        for index in range(1, 16)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    service = _live_service(
        client=client,
        dominants=FakeDominants({("j", day): "J2505"}),
        phases=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        products=("j",),
    )
    service.reconcile(window.start + timedelta(minutes=1))
    key = "live:bars:2025-01-02:j:1m"
    for bar in source[:-1]:
        fake.zadd(
            key,
            {
                json.dumps(_bar_payload(bar), separators=(",", ":")): int(
                    bar.bar_end.timestamp() * 1000
                )
            },
        )
    final = source[-1]
    service.ingest("J2505", final, now=final.bar_end + timedelta(seconds=2))
    service.flush_due(final.bar_end + timedelta(seconds=2))

    store = module.RedisLiveStore(fake)
    assert store.bars_after(day, "j", "5m", None) == ()
    assert store.bars_after(day, "j", "15m", None) == ()


def test_trading_provider_failure_retries_after_ten_seconds_but_break_staleness_does_not() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    fake = FakeRedis()
    client = FakeLiveClient()
    client.fail_listen = True
    phases = FakePhases({"j": _phase("j", day, window)})
    service = _live_service(
        client=client, dominants=FakeDominants({("j", day): "J2505"}), phases=phases,
        store=module.RedisLiveStore(fake), products=("j",),
    )

    assert service.poll(datetime(2025, 1, 2, 1, 1, tzinfo=UTC)) == "LIVE_PROVIDER_RETRY_SCHEDULED"
    assert service.next_provider_retry_at == datetime(2025, 1, 2, 1, 1, 10, tzinfo=UTC)
    phases.phases["j"] = _phase("j", day, None, MarketPhase.BREAK)
    assert service.poll(datetime(2025, 1, 2, 1, 1, 1, tzinfo=UTC)) is None
    assert service.next_provider_retry_at is None


def test_provider_failure_immediately_publishes_unavailable_and_first_recovery_bar_restores_it() -> None:
    """A recovered completed Bar must restore readiness before its PubSub visibility."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    first = FakeLiveClient()
    first.fail_listen = True
    replacement = FakeLiveClient()
    replacement.payloads = [_raw_payload("J2505", _bar(1))]
    created: list[FakeLiveClient] = []
    fake = FakeRedis()

    def factory():
        client = (first, replacement)[len(created)]
        created.append(client)
        return module.RQDataLiveProvider(client)

    service = module.LiveMarketService(
        provider_factory=factory,
        dominant_source=FakeDominants({("j", day): "J2505"}),
        phase_resolver=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        operational_products=("j",),
    )
    started = datetime(2025, 1, 2, 1, 1, tzinfo=UTC)

    assert service.poll(started) == "LIVE_PROVIDER_RETRY_SCHEDULED"
    assert json.loads(fake.values["live:heartbeat"])["available"] is False

    assert service.poll(started + timedelta(seconds=10)) is None
    assert json.loads(fake.values["live:heartbeat"])["available"] is True


def test_dead_started_listener_retries_and_recovers_with_a_fresh_bar() -> None:
    """Catches listener liveness errors bypassing the service retry state machine."""
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    first = FakeLiveClient()
    first.payloads = [_raw_payload("J2505", _bar(1))]
    replacement = FakeLiveClient()
    replacement.payloads = [_raw_payload("J2505", _bar(2))]
    clients = (first, replacement)
    created: list[FakeLiveClient] = []
    fake = FakeRedis()

    def factory():
        client = clients[len(created)]
        created.append(client)
        return module.RQDataLiveProvider(client)

    service = module.LiveMarketService(
        provider_factory=factory,
        dominant_source=FakeDominants({("j", day): "J2505"}),
        phase_resolver=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(fake),
        operational_products=("j",),
    )
    started = datetime(2025, 1, 2, 1, 1, 2, tzinfo=UTC)
    assert service.poll(started) is None
    assert service.poll(started + timedelta(seconds=1)) is None
    assert json.loads(fake.values["live:heartbeat"])["available"] is True
    first.listener.alive = False
    detected_at = datetime(2025, 1, 2, 1, 2, 3, tzinfo=UTC)

    assert service.poll(detected_at) == "LIVE_PROVIDER_RETRY_SCHEDULED"
    assert first.closed is True
    assert service.next_provider_retry_at == detected_at + timedelta(seconds=10)
    assert json.loads(fake.values["live:heartbeat"])["available"] is False

    assert service.poll(detected_at + timedelta(seconds=9)) is None
    assert json.loads(fake.values["live:heartbeat"])["available"] is False
    assert service.poll(detected_at + timedelta(seconds=10)) is None
    assert service.poll(detected_at + timedelta(seconds=11)) is None
    heartbeat = json.loads(fake.values["live:heartbeat"])
    assert heartbeat["available"] is True
    assert heartbeat["last_bar_at"] == _bar(2).bar_end.isoformat()
    assert created == [first, replacement]
    assert replacement.subscribed == ["bar_J2505"]
    assert replacement.listen_calls == 1


def test_provider_retry_deadline_prevents_factory_subscribe_and_listen_before_ten_seconds() -> None:
    module = importlib.import_module("app.market_data.live_market")
    day = date(2025, 1, 2)
    window = SessionWindow(
        datetime(2025, 1, 2, 1, tzinfo=UTC), datetime(2025, 1, 2, 2, tzinfo=UTC)
    )
    first = FakeLiveClient()
    first.fail_listen = True
    replacement = FakeLiveClient()
    created: list[FakeLiveClient] = []

    def factory():
        client = (first, replacement)[len(created)]
        created.append(client)
        return module.RQDataLiveProvider(client)

    service = module.LiveMarketService(
        provider_factory=factory,
        dominant_source=FakeDominants({("j", day): "J2505"}),
        phase_resolver=FakePhases({"j": _phase("j", day, window)}),
        store=module.RedisLiveStore(FakeRedis()),
        operational_products=("j",),
    )
    started = datetime(2025, 1, 2, 1, 1, tzinfo=UTC)

    assert service.poll(started) == "LIVE_PROVIDER_RETRY_SCHEDULED"
    assert created == [first]
    assert service.poll(started + timedelta(seconds=9)) is None
    assert created == [first]
    assert replacement.subscribed == [] and replacement.listen_calls == 0
    assert service.poll(started + timedelta(seconds=10)) is None
    assert created == [first, replacement]
    assert replacement.subscribed == ["bar_J2505"] and replacement.listen_calls == 1
