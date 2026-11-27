from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.tick_market import MarketTick, TickMinuteBuilder, decode_rqdata_tick


DAY = date(2026, 11, 26)
OPEN = datetime(2026, 11, 25, 13, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


def tick(offset, volume, last="100", *, connection=1, turnover=None, high=None, low=None):
    observed_at = OPEN + timedelta(seconds=offset)
    return MarketTick(
        contract="AU2612",
        trading_day=DAY,
        observed_at=observed_at,
        received_at=observed_at + timedelta(milliseconds=100),
        last=Decimal(last),
        volume=Decimal(volume),
        turnover=None if turnover is None else Decimal(turnover),
        open_interest=Decimal("23"),
        connection=connection,
        cumulative_high=None if high is None else Decimal(high),
        cumulative_low=None if low is None else Decimal(low),
    )


def test_tick_decode_uses_session_trading_day_and_preserves_subsecond_order():
    payload = {
        "action": "feed", "channel": "tick_AU2612", "order_book_id": "AU2612",
        "datetime": 20261125210000671, "last": 100.01, "volume": 23,
        "total_turnover": 201.25, "open_interest": 9, "high": 103, "low": 98,
        "bid": [100, 0], "bid_vol": [2, 0], "ask": [100.02], "ask_vol": [3],
    }
    received = OPEN + timedelta(seconds=1)
    result = decode_rqdata_tick(payload, trading_day=DAY, received_at=received, connection=1)
    assert result.observed_at == OPEN + timedelta(milliseconds=671)
    assert result.trading_day == DAY
    assert result.last == Decimal("100.01")
    assert result.cumulative_high == Decimal("103") and result.cumulative_low == Decimal("98")
    assert result.bid == ((Decimal("100"), Decimal("2")),)
    assert decode_rqdata_tick({**payload, "trading_date": 20261125}, trading_day=DAY,
                              received_at=received, connection=1) is None
    invalid_extrema = decode_rqdata_tick({**payload, "high": "NaN", "low": 101}, trading_day=DAY,
                                       received_at=received, connection=1)
    assert invalid_extrema is not None
    assert invalid_extrema.cumulative_high is None and invalid_extrema.cumulative_low is None


def test_open_baselines_amount_and_quote_only_ticks_do_not_change_trade_extrema():
    builder = TickMinuteBuilder((SessionWindow(OPEN, OPEN + 3 * MINUTE),))
    assert builder.ingest(tick(0, 0, "90", turnover="0")).completed is None
    builder.ingest(tick(3, 2, "101", turnover="201.25"))
    builder.ingest(tick(20, 3, "103", turnover="304.25"))
    builder.ingest(tick(21, 3, "103", turnover="304.25"))
    result = builder.ingest(tick(60, 4, "102", turnover="406.25"))
    assert result.completed.bar_end == OPEN + MINUTE
    assert (result.completed.open, result.completed.high, result.completed.low, result.completed.close) == (
        Decimal("101"), Decimal("103"), Decimal("101"), Decimal("103"),
    )
    assert result.completed.volume == 3
    assert result.completed.turnover == Decimal("304.25")
    assert result.completed.open_interest == 23
    assert result.active.bar_end == OPEN + 2 * MINUTE
    assert result.active.volume == 1


def test_daily_extrema_witness_needs_same_minute_trade_and_previous_value():
    builder = TickMinuteBuilder((SessionWindow(OPEN, OPEN + 3 * MINUTE),))
    builder.ingest(tick(0, 0, high=100, low=100, turnover=0))
    builder.ingest(tick(1, 1, high=100, low=100, turnover=100))
    builder.ingest(tick(20, 4, high=106, low=94, turnover=400))
    first = builder.ingest(tick(60, 6, high=110, low=91, turnover=600)).completed
    assert (first.open, first.high, first.low, first.close) == (100, 106, 94, 100)
    assert (first.volume, first.turnover, first.open_interest) == (4, 400, 23)

    # A stale retreat/rebound is not a fresh extreme, nor is an update without a trade.
    builder.ingest(tick(61, 7, high=105, low=93, turnover=700))
    builder.ingest(tick(65, 9, high=110, low=91, turnover=900))
    builder.ingest(tick(70, 9, high=115, low=91, turnover=900))
    builder.ingest(tick(85, 10, high=116, low=91, turnover=1000))
    second = builder.ingest(tick(120, 11, high=116, low=91, turnover=1100)).completed
    assert (second.high, second.low) == (100, 100)
    assert builder.ingest(tick(170, 14, high=120, low=90, turnover=1400)).active.high == 120
    end = builder.ingest(tick(180, 17, high=130, low=80, turnover=1700)).completed
    assert (end.high, end.low) == (120, 90)


def test_extrema_ignore_missing_previous_value_and_cross_connection_gap():
    builder = TickMinuteBuilder((SessionWindow(OPEN, OPEN + 4 * MINUTE),))
    builder.ingest(tick(0, 0))
    builder.ingest(tick(5, 2, high=120, low=80))
    first = builder.ingest(tick(60, 4, high=120, low=80)).completed
    assert (first.high, first.low) == (100, 100)

    # Across a source gap there is no completed minute, even if extrema are present.
    builder.ingest(tick(70, 6, high=130, low=70, connection=2))
    assert builder.ingest(tick(80, 9, high=140, low=60, connection=2)).issue == "TICK_MINUTE_UNPROVED"
    assert builder.ingest(tick(120, 11, high=140, low=60, connection=2)).completed is None
    assert builder.ingest(tick(135, 13, high=145, low=60, connection=2)).active.high == 145
    duplicate = builder.ingest(tick(135, 13, high=146, low=60, connection=2))
    assert duplicate.issue == "TICK_DUPLICATE"
    builder.ingest(tick(140, 15, high=146, low=60, connection=2))
    completed = builder.ingest(tick(180, 16, high=146, low=60, connection=2)).completed
    assert (completed.high, completed.volume) == (145, 6)


@pytest.mark.parametrize("interruption", ("counter_reset", "connection_gap", "missing_extremum", "late"))
def test_old_day_extremum_cannot_be_assigned_to_a_later_minute(interruption):
    builder = TickMinuteBuilder((SessionWindow(OPEN, OPEN + 4 * MINUTE),))
    builder.ingest(tick(0, 0, high=100, low=100))
    if interruption == "missing_extremum":
        builder.ingest(tick(20, 10, last=120, low=100))
    elif interruption != "late":
        builder.ingest(tick(20, 10, last=120, high=120, low=100))
    builder.ingest(tick(60, 11, high=100, low=100))
    if interruption == "late":
        assert builder.ingest(tick(59, 10, high=120, low=100)).issue == "TICK_LATE"
    connection = 1
    if interruption == "connection_gap":
        builder.gap()
        connection = 2
    volume = 4 if interruption == "counter_reset" else 12
    builder.ingest(tick(70, volume, high=100, low=100, connection=connection))
    builder.ingest(tick(120, volume + 1, high=100, low=100, connection=connection))
    builder.ingest(tick(125, volume + 3, high=120, low=100, connection=connection))
    result = builder.ingest(tick(180, volume + 4, high=120, low=100, connection=connection))
    assert result.completed.bar_end == OPEN + 3 * MINUTE
    assert result.completed.high == 100


def test_reconnect_gap_or_lateness_cannot_complete_or_rewrite_a_minute():
    builder = TickMinuteBuilder((SessionWindow(OPEN, OPEN + 5 * MINUTE),))
    builder.ingest(tick(0, 0))
    builder.ingest(tick(15, 3))
    assert builder.ingest(tick(61, 8, connection=2)).completed is None
    assert builder.ingest(tick(62, 9, connection=2)).completed is None
    assert builder.ingest(tick(121, 10, connection=2)).completed is None
    late = builder.ingest(tick(100, 9, connection=2))
    assert late.completed is None
    assert late.issue == "TICK_LATE"
    assert builder.ingest(tick(181, 11, connection=2)).completed.bar_end == OPEN + 3 * MINUTE
    assert builder.ingest(tick(181, 11, connection=2)).issue == "TICK_DUPLICATE"
    assert builder.ingest(tick(300, 14, connection=2)).completed is None


def test_short_break_retains_proved_counter_and_tail_requires_an_endpoint_tick():
    builder = TickMinuteBuilder((
        SessionWindow(OPEN, OPEN + MINUTE),
        SessionWindow(OPEN + 3 * MINUTE, OPEN + 4 * MINUTE),
    ))
    builder.ingest(tick(0, 0, turnover="0"))
    builder.ingest(tick(59, 2, turnover="200"))
    tail = builder.ingest(tick(60, 3, turnover="300"))
    assert tail.completed.volume == 3
    assert tail.active is None
    assert builder.ingest(tick(180, 4, turnover="400")).active.volume == 1
    last_quote = builder.ingest(tick(239, 5, turnover="500"))
    assert last_quote.completed is None
    assert builder.ingest(tick(240, 8, turnover="800")).completed.volume == 5


def test_provider_subscribes_only_tick_and_emits_minute_with_source_proof():
    from app.market_data.domain import BarFrequency
    from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore

    class Client:
        def subscribe(self, channels):
            assert channels == ["tick_AU2612"]

        def listen(self, *, handler):
            self.handler = handler

        def close(self):
            pass

    client = Client()
    preview = TickPreviewStore()
    clock = iter(OPEN + timedelta(seconds=offset) for offset in (1, 2, 61))
    provider = TickMarketDataProvider(client, connection_identity=lambda: client, preview=preview,
                                      clock=lambda: next(clock))
    provider.configure(DAY, {"au": ("AU2612", (SessionWindow(OPEN, OPEN + 6 * MINUTE),))})
    provider.subscribe(("bar_AU2612",))
    assert provider.poll() == ()
    for elapsed, volume, last in ((0, 0, 100), (1, 2, 101), (60, 3, 102)):
        client.handler({
            "channel": "tick_AU2612", "action": "feed", "order_book_id": "AU2612",
            "datetime": OPEN + timedelta(seconds=elapsed), "last": last, "volume": volume,
        })
    ((contract, bar),) = provider.poll_buffered()
    assert contract == "AU2612"
    assert bar.bar_end == OPEN + MINUTE
    source = provider.source_proof(contract, bar)
    assert source.observed_at == OPEN + MINUTE
    assert source.received_at == OPEN + timedelta(seconds=61)
    snapshot = preview.snapshot(trading_day=DAY, symbol="au", contract="AU2612",
                                frequency=BarFrequency.M5)
    assert snapshot.quote.generation == source.generation
    assert snapshot.quote.last_price == Decimal(102)
    assert snapshot.activity.bar.volume == 3
    assert snapshot.activity.bar.bar_end == OPEN + 5 * MINUTE


def test_provider_overflow_does_not_release_partial_batch():
    import pytest

    from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore

    client = object()
    provider = TickMarketDataProvider(client, connection_identity=lambda: client, preview=TickPreviewStore(),
                                      clock=lambda: OPEN, capacity=1)
    provider._buffer_message({"channel": "tick_AU2612"})
    provider._buffer_message({"channel": "tick_AU2612"})
    with pytest.raises(ConnectionError, match="TICK_BUFFER_OVERFLOW"):
        provider.poll_buffered()


def test_pinned_veighna_dispatch_is_headless_and_preserves_batch_order():
    import os
    from threading import get_ident

    import pytest

    from app.market_data.tick_veighna import VeighNaTickDispatch

    if os.getenv("GUIYI_TEST_VEIGHNA_DISPATCH") != "1":
        pytest.skip("requires locked VeighNa 4.4.0")

    dispatch = VeighNaTickDispatch()
    callers = []
    try:
        assert dispatch(lambda values: (callers.append(get_ident()), tuple(reversed(values)))[1],
                        (3, 2, 1)) == (1, 2, 3)

        def failure(_items):
            raise ValueError("bad batch")

        with pytest.raises(ValueError, match="bad batch"):
            dispatch(failure, ())
        assert dispatch(sum, (1, 2, 3)) == 6
        assert len(callers) == 1 and callers[0] != get_ident()
    finally:
        dispatch.close()


def test_bad_known_owner_tick_invalidates_an_unfinished_minute():
    from app.market_data.domain import BarFrequency
    from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore

    connection = object()
    preview = TickPreviewStore()
    current = [OPEN]
    provider = TickMarketDataProvider(object(), connection_identity=lambda: connection,
                                      preview=preview, clock=lambda: current[0])
    provider.configure(DAY, {"au": ("AU2612", (SessionWindow(OPEN, OPEN + 6 * MINUTE),))})

    def push(offset, count, price, interest=51):
        observed = OPEN + timedelta(seconds=offset)
        current[0] = observed + timedelta(milliseconds=100)
        provider._buffer_message({
            "action": "feed", "channel": "tick_AU2612", "order_book_id": "AU2612",
            "datetime": observed, "last": price, "volume": count, "open_interest": interest,
        })
        return provider.poll_buffered()

    assert push(0, 0, 100) == ()
    assert push(2, 1, 200, "NaN") == ()
    last = preview.snapshot(trading_day=DAY, symbol="au", contract="AU2612", frequency=BarFrequency.M1)
    assert last.quote.stale and last.activity is None
    assert push(3, 2, 100) == ()
    assert push(60, 3, 100) == ()
    ((contract, only_proved_bar),) = push(120, 4, 101)
    assert contract == "AU2612" and only_proved_bar.bar_end == OPEN + 2 * MINUTE
    assert only_proved_bar.volume == 1 and only_proved_bar.high == 100
    assert provider.diagnostics["TICK_INVALID"] == 1
