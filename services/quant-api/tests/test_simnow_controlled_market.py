"""Read-only natural-source and authoritative session fences, no production reads."""

from contextlib import contextmanager
from datetime import datetime, UTC, timedelta, date
from types import SimpleNamespace as NS
import pytest
from app import simnow_controlled_market as m
from app.market_data.domain import SeriesPageQuery, SeriesKind, BarFrequency

T = datetime(2026, 10, 27, 1, tzinfo=UTC)


class PubSub:
    def get_message(self, timeout=0):
        return dict(type="message", channel="live:bar:rb:60m", data="fixture")


def bridge(monkeypatch, source="realtime", latest_matches=True):
    b = object.__new__(m.MarketBridge)
    b.product = "RB"
    b.started = T
    b.pubsub = PubSub()
    b.identity = SeriesPageQuery(SeriesKind.ACTUAL_DOMINANT, "rb", BarFrequency.H1)
    bar = NS(bar_end=T + timedelta(hours=1), trading_day=date(2026, 10, 27))
    monkeypatch.setattr(
        m,
        "_parse_live_bar_trigger",
        lambda *_: NS(symbol="rb", frequency=BarFrequency.H1, bar=bar),
    )
    window = NS(qualified=True)
    reader = NS(
        observation_snapshot=lambda *_: NS(
            source=source,
            bars=(bar if latest_matches else NS(other=True),),
            contract="RB2701",
        ),
        bars_until=lambda *_a, **_k: window,
    )

    @contextmanager
    def read():
        yield NS(), reader

    b.reader = read
    monkeypatch.setattr(
        m,
        "signal_from_window",
        lambda r, w, **kwargs: ("qualified-signal", kwargs["observed_at"]),
    )
    return b, bar, reader


def test_only_new_latest_native_completed_observation_enters_signal(monkeypatch):
    b, bar, _ = bridge(monkeypatch)
    now = bar.bar_end + timedelta(seconds=2)
    assert b.poll(now, T) == ("qualified-signal", now)


@pytest.mark.parametrize(
    "source,matches", [("unavailable", True), ("none", True), ("realtime", False)]
)
def test_unproven_or_revised_observation_does_not_create_signal(
    monkeypatch, source, matches
):
    b, bar, _ = bridge(monkeypatch, source, matches)
    with pytest.raises(ValueError):
        b.poll(bar.bar_end + timedelta(seconds=2), T)


def test_startup_historical_bar_is_ignored(monkeypatch):
    b, bar, _ = bridge(monkeypatch)
    b.started = bar.bar_end
    assert b.poll(bar.bar_end + timedelta(seconds=2), T) is None


def test_recovery_unavailable_does_not_invent_direction(monkeypatch):
    b, bar, reader = bridge(monkeypatch, "none")
    state = NS(
        products=(NS(product="RB", last_bar=T, desired=1, signal_id="old"),),
        activated_at=T,
        positions=(),
    )
    assert b.recovery(state, bar.bar_end + timedelta(seconds=2)) == ()


def test_lunch_is_not_final_close_and_uses_same_session_authority(monkeypatch):
    b = object.__new__(m.MarketBridge)
    b.product = "RB"
    # UTC 01:00/03:30/05:30/07:00 = Shanghai 09/11:30/13:30/15.
    rows = tuple(
        NS(
            name=name,
            is_night=False,
            window=NS(start=T + timedelta(hours=start), end=T + timedelta(hours=end)),
        )
        for name, start, end in (("am", 0, 2.5), ("pm", 4.5, 6))
    )
    monkeypatch.setattr(
        m, "resolved_session_windows_for_trading_day", lambda *_a, **_k: rows
    )
    monkeypatch.setattr(
        m,
        "build_market_data_service",
        lambda _: NS(dominant_segment_for_day=lambda *_: NS(contract="RB2701")),
    )
    db = NS(scalar=lambda _: NS(exchange_code="SHFE"))

    @contextmanager
    def read():
        yield db, NS()

    b.reader = read
    authority = b.authority(date(2026, 10, 27), T + timedelta(hours=3))
    assert (
        not authority.session.can_trade
        and authority.session.final_close_at == T + timedelta(hours=6)
    )
    assert authority.contiguous_session_end is None
    morning = b.authority(date(2026, 10, 27), T + timedelta(hours=2))
    assert morning.session.can_trade
    assert morning.session.final_close_at == T + timedelta(hours=6)
    assert morning.contiguous_session_end == T + timedelta(hours=2.5)
    imminent_break = b.authority(date(2026, 10, 27), T + timedelta(hours=2, minutes=20))
    assert (
        imminent_break.contiguous_session_end - (T + timedelta(hours=2, minutes=20))
    ).total_seconds() == 600
    at_break = b.authority(date(2026, 10, 27), T + timedelta(hours=2.5))
    assert not at_break.session.can_trade and at_break.contiguous_session_end is None
    afternoon = b.authority(date(2026, 10, 27), T + timedelta(hours=5))
    assert (
        afternoon.session.can_trade
        and afternoon.session.final_close_at == T + timedelta(hours=6)
    )
    assert afternoon.contiguous_session_end == T + timedelta(hours=6)
    closed = b.authority(date(2026, 10, 27), T + timedelta(hours=6))
    assert not closed.session.can_trade and closed.contiguous_session_end is None


def test_adjacent_resolved_windows_share_one_contiguous_end(monkeypatch):
    b = object.__new__(m.MarketBridge)
    b.product = "RB"
    rows = tuple(
        NS(
            name=name,
            is_night=False,
            window=NS(start=T + timedelta(hours=start), end=T + timedelta(hours=end)),
        )
        for name, start, end in (
            ("first", 0, 1),
            ("adjacent", 1, 2),
            ("after-break", 3, 4),
        )
    )
    monkeypatch.setattr(
        m, "resolved_session_windows_for_trading_day", lambda *_a, **_k: rows
    )
    monkeypatch.setattr(
        m,
        "build_market_data_service",
        lambda _: NS(dominant_segment_for_day=lambda *_: NS(contract="RB2701")),
    )
    db = NS(scalar=lambda _: NS(exchange_code="SHFE"))

    @contextmanager
    def read():
        yield db, NS()

    b.reader = read
    authority = b.authority(date(2026, 10, 27), T + timedelta(minutes=30))
    assert authority.session.final_close_at == T + timedelta(hours=4)
    assert authority.contiguous_session_end == T + timedelta(hours=2)


def test_recovery_validates_whole_gap_and_replays_only_after_frozen_bar(monkeypatch):
    from app.market_data.market_read_service import MarketReadWindow

    b = object.__new__(m.MarketBridge)
    b.product = "RB"
    b.identity = SeriesPageQuery(SeriesKind.ACTUAL_DOMINANT, "rb", BarFrequency.H1)
    bars = tuple(
        NS(bar_end=T + timedelta(hours=i), trading_day=date(2026, 10, 27))
        for i in range(40)
    )
    window = MarketReadWindow(
        "rb",
        "actual_dominant",
        "60m",
        date(2026, 10, 27),
        "RB2701",
        bars[-1].bar_end,
        bars,
        ("RB2701",) * 40,
    )
    checked = []
    evaluated = []
    reader = NS(
        observation_snapshot=lambda *_: NS(
            source="realtime", bars=(bars[-1],), trading_day=date(2026, 10, 27)
        ),
        bars_until=lambda *_a, **_k: window,
        validate_alert_window=lambda w, **kw: checked.append(kw["context_bars"]),
    )

    @contextmanager
    def read():
        yield NS(), reader

    b.reader = read

    class Evaluator:
        def evaluate(self, frame):
            assert len(frame.bars) == 32 and frame.bars[-1].bar_end == frame.cutoff
            evaluated.append(frame.cutoff)
            return NS(
                observation_types=("sell",) if frame.cutoff == bars[-1].bar_end else ()
            )

    monkeypatch.setattr(m, "HtdyOriginalEvaluator", Evaluator)
    state = NS(
        products=(
            NS(product="RB", last_bar=bars[31].bar_end, desired=1, signal_id="frozen"),
        ),
        activated_at=T,
        positions=(),
    )
    proofs = b.recovery(state, bars[-1].bar_end + timedelta(seconds=2))
    assert proofs[0].latest_direction == -1
    assert checked == [40] and evaluated == [bar.bar_end for bar in bars[32:]]


@pytest.mark.parametrize('end_hours', [1.25, 2.5, 6])
def test_active_authority_expires_at_break_or_close(monkeypatch, end_hours):
    bridge = object.__new__(m.MarketBridge)
    bridge.product = 'RB'
    rows = tuple(NS(name=str(i), is_night=False,
                    window=NS(start=T + timedelta(hours=start), end=T + timedelta(hours=end)))
                 for i, (start, end) in enumerate(((0, 1.25), (1.5, 2.5), (4.5, 6))))
    monkeypatch.setattr(m, 'resolved_session_windows_for_trading_day', lambda *_a, **_k: rows)
    monkeypatch.setattr(m, 'build_market_data_service',
        lambda _: NS(dominant_segment_for_day=lambda *_: NS(contract='RB2701')))
    @contextmanager
    def read():
        yield NS(scalar=lambda _: NS(exchange_code='SHFE')), NS()
    bridge.reader = read
    boundary = T + timedelta(hours=end_hours)
    authority = bridge.authority(date(2026, 10, 27), boundary - timedelta(milliseconds=500))
    assert authority.session.can_trade and authority.session.can_cancel
    assert authority.contiguous_session_end == boundary
    assert authority.session.valid_until == boundary
