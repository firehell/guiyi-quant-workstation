"""Offline multi-product natural-source and Calendar/session boundaries."""

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

from app import simnow_controlled_market as single
from app import simnow_portfolio_market as market
from app.market_data.domain import BarFrequency
from app.market_data.market_phase import MarketPhase, ProductMarketPhase


T = datetime(2026, 10, 27, 1, tzinfo=UTC)


class PubSub:
    def __init__(self):
        self.messages = []
        self.subscriptions = []
        self.closed = False

    def subscribe(self, *channels):
        self.subscriptions.append(channels)

    def get_message(self, timeout=0):
        return self.messages.pop(0) if self.messages else None

    def close(self):
        self.closed = True


class Redis:
    def __init__(self):
        self.pub = PubSub()
        self.pubsub_calls = 0
        self.closed = False

    def pubsub(self, **kwargs):
        self.pubsub_calls += 1
        assert kwargs == {"ignore_subscribe_messages": True}
        return self.pub

    def close(self):
        self.closed = True


class Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, _):
        pass


def make_inlet(monkeypatch, *, receipts=None):
    monkeypatch.setattr(market, "load_operational_products", lambda: ("rb", "ag"))
    redis = Redis()
    instants = iter(receipts or (T + timedelta(hours=2),) * 8)
    inlet = market.PortfolioMarket(
        ("RB", "AG"),
        redis=redis,
        session_factory=Session,
        receipt_clock=lambda: next(instants),
    )
    return inlet, redis


def event(product, end, *, valid=True):
    return {
        "type": "message",
        "channel": f"live:bar:{product.lower()}:60m",
        "data": (product, end, valid),
    }


def parse(_channel, data):
    product, end, valid = data
    return (
        NS(
            symbol=product.lower(),
            frequency=BarFrequency.H1,
            bar=NS(bar_end=end, trading_day=date(2026, 10, 27)),
        )
        if valid
        else None
    )


def test_one_pubsub_latest_completed_bar_and_receipt_order(monkeypatch):
    receipts = (
        T + timedelta(hours=2, seconds=3),
        T + timedelta(hours=2, seconds=1),
        T + timedelta(hours=2, seconds=2),
    )
    inlet, redis = make_inlet(monkeypatch, receipts=receipts)
    monkeypatch.setattr(market, "_parse_live_bar_trigger", parse)
    seen = []

    def signal(self, trigger, observed_at, after):
        seen.append((self.product, trigger.bar.bar_end, after))
        return NS(
            product=self.product,
            source_id=self.product,
            observed_at=observed_at,
            bar_end=trigger.bar.bar_end,
        )

    monkeypatch.setattr(single.MarketBridge, "signal_from_trigger", signal)
    assert redis.pubsub_calls == 1
    assert redis.pub.subscriptions == [("live:bar:rb:60m", "live:bar:ag:60m")]
    redis.pub.messages.append(event("RB", T))
    inlet.activate(T)
    redis.pub.messages.extend(
        (
            event("RB", T + timedelta(hours=1)),
            event("AG", T + timedelta(hours=1)),
            event("RB", T + timedelta(hours=2)),
        )
    )
    result = inlet.poll(T + timedelta(hours=2, seconds=4), {"RB": T, "AG": T})
    assert [(item.product, item.bar_end) for item in result] == [
        ("AG", T + timedelta(hours=1)),
        ("RB", T + timedelta(hours=2)),
    ]
    assert seen == [
        ("RB", T + timedelta(hours=2), T),
        ("AG", T + timedelta(hours=1), T),
    ]
    inlet.close()
    assert redis.pub.closed and redis.closed


def test_invalid_product_message_does_not_poison_valid_product(monkeypatch):
    inlet, redis = make_inlet(monkeypatch)
    monkeypatch.setattr(market, "_parse_live_bar_trigger", parse)
    monkeypatch.setattr(
        single.MarketBridge,
        "signal_from_trigger",
        lambda self, trigger, observed_at, after: NS(
            product=self.product, source_id=self.product, observed_at=observed_at
        ),
    )
    inlet.activate(T)
    redis.pub.messages.extend(
        (
            event("AG", T + timedelta(hours=1), valid=False),
            event("RB", T + timedelta(hours=1)),
        )
    )
    result = inlet.poll(T + timedelta(hours=2), T)
    assert tuple(item.product for item in result) == ("RB",)
    assert inlet.issues == {"AG": "NATURAL_TRIGGER_INVALID"}
    redis.pub.messages.extend(
        (
            event("RB", T + timedelta(hours=1)),
            event("RB", T + timedelta(hours=2), valid=False),
        )
    )
    assert inlet.poll(T + timedelta(hours=2), T) == ()
    assert inlet.issues["RB"] == "NATURAL_TRIGGER_INVALID"


def test_shared_signal_proof_rejects_recovered_and_unproven_bars(monkeypatch):
    inlet, redis = make_inlet(monkeypatch)
    monkeypatch.setattr(market, "_parse_live_bar_trigger", parse)
    checked = []
    bar = NS(bar_end=T + timedelta(hours=1), trading_day=date(2026, 10, 27))
    trigger = NS(symbol="rb", frequency=BarFrequency.H1, bar=bar)

    @contextmanager
    def read():
        yield (
            NS(),
            NS(
                observation_snapshot=lambda *_: NS(source="historical", bars=(bar,)),
                bars_until=lambda *_a, **_k: checked.append("bars"),
            ),
        )

    inlet.reader = read
    for view in inlet._views.values():
        view.reader = read
    inlet.activate(T)
    # Recovery/activation has no first-seen and never reaches the reader.
    assert (
        inlet._views["RB"].signal_from_trigger(
            trigger, T + timedelta(hours=2), T + timedelta(hours=1)
        )
        is None
    )
    redis.pub.messages.append(event("RB", bar.bar_end))
    assert inlet.poll(T + timedelta(hours=2), T) == ()
    assert inlet.issues["RB"] == "LATEST_NATURAL_OBSERVATION_UNPROVEN"
    assert not checked


def phase(product, state, day, next_start=None):
    return ProductMarketPhase(product.lower(), state, day, None, next_start)


def test_friday_night_plan_uses_next_trading_day_and_preopen_120_seconds(monkeypatch):
    inlet, _ = make_inlet(monkeypatch)
    friday = datetime(2026, 10, 30, 20, 58, tzinfo=ZoneInfo("Asia/Shanghai"))
    open_at = friday + timedelta(minutes=2)
    monday = date(2026, 11, 2)

    class Resolver:
        def __init__(self, _):
            pass

        def resolve(self, product, at):
            if product == "ag":
                return phase(product, MarketPhase.UNKNOWN, None)
            if at >= open_at:
                return phase(product, MarketPhase.TRADING, monday)
            return phase(product, MarketPhase.CLOSED, friday.date(), open_at)

    monkeypatch.setattr(market, "MarketPhaseResolver", Resolver)
    result = inlet.plan(friday)
    assert result == market.SessionPlan(monday, False, True, open_at)
    assert inlet.issues == {"AG": "MARKET_PHASE_UNKNOWN"}
    assert inlet.plan(open_at).trading_day == monday
    assert inlet.plan(open_at).active


def test_lunch_is_planned_break_and_calendar_unknown_blocks_globally(monkeypatch):
    inlet, _ = make_inlet(monkeypatch)
    noon = T + timedelta(hours=2, minutes=45)
    afternoon = T + timedelta(hours=4, minutes=30)

    class Resolver:
        unknown = False

        def __init__(self, _):
            pass

        def resolve(self, product, at):
            if self.unknown:
                return phase(product, MarketPhase.UNKNOWN, None)
            return phase(product, MarketPhase.BREAK, date(2026, 10, 27), afternoon)

    monkeypatch.setattr(market, "MarketPhaseResolver", Resolver)
    assert inlet.plan(noon) == market.SessionPlan(
        date(2026, 10, 27), False, False, afternoon
    )
    assert inlet.plan(afternoon - timedelta(seconds=119)).connect_allowed
    Resolver.unknown = True
    assert inlet.plan(noon) == market.SessionPlan(None, False, False, None)
    assert inlet.issues == {"RB": "MARKET_PHASE_UNKNOWN", "AG": "MARKET_PHASE_UNKNOWN"}


def test_unprovable_next_open_product_does_not_block_healthy_product(monkeypatch):
    inlet, _ = make_inlet(monkeypatch)
    now = T
    open_at = now + timedelta(seconds=90)

    class Resolver:
        def __init__(self, _):
            pass

        def resolve(self, product, at):
            if product == "ag" and at == open_at:
                raise ValueError("TRADING_SESSION_MISSING")
            if at == open_at:
                return phase(product, MarketPhase.TRADING, date(2026, 10, 27))
            return phase(product, MarketPhase.CLOSED, date(2026, 10, 26), open_at)

    monkeypatch.setattr(market, "MarketPhaseResolver", Resolver)
    assert inlet.plan(now) == market.SessionPlan(
        date(2026, 10, 27), False, True, open_at
    )
    assert inlet.issues == {"AG": "MARKET_PHASE_UNKNOWN"}


def test_authority_and_recovery_delegate_without_other_subscriptions(monkeypatch):
    inlet, redis = make_inlet(monkeypatch)
    monkeypatch.setattr(
        single.MarketBridge,
        "authority",
        lambda self, day, now, contract=None: (self.product, day, contract),
    )
    monkeypatch.setattr(
        single.MarketBridge,
        "recovery",
        lambda self, state, now: (NS(product=self.product),),
    )
    assert inlet.authority("rb", date(2026, 10, 27), T, "RB2701") == (
        "RB",
        date(2026, 10, 27),
        "RB2701",
    )
    state = NS(products=(NS(product="RB"), NS(product="AG")))
    assert tuple(item.product for item in inlet.recovery(state, T)) == ("RB", "AG")
    assert redis.pubsub_calls == 1
