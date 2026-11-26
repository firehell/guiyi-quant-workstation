from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.market_data.aggregation import SessionWindow
from app.market_data.tick_market import MarketTick, TickMinuteBuilder, decode_rqdata_tick


DAY = date(2026, 11, 26)
OPEN = datetime(2026, 11, 25, 13, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


def tick(offset, volume, last="100", *, connection=1, turnover=None):
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
    )


def test_tick_decode_uses_session_trading_day_and_preserves_subsecond_order():
    payload = {
        "action": "feed", "channel": "tick_AU2612", "order_book_id": "AU2612",
        "datetime": 20261125210000671, "last": 100.01, "volume": 23,
        "total_turnover": 201.25, "open_interest": 9,
        "bid": [100, 0], "bid_vol": [2, 0], "ask": [100.02], "ask_vol": [3],
    }
    received = OPEN + timedelta(seconds=1)
    result = decode_rqdata_tick(payload, trading_day=DAY, received_at=received, connection=1)
    assert result.observed_at == OPEN + timedelta(milliseconds=671)
    assert result.trading_day == DAY
    assert result.last == Decimal("100.01")
    assert result.bid == ((Decimal("100"), Decimal("2")),)
    assert decode_rqdata_tick({**payload, "trading_date": 20261125}, trading_day=DAY,
                              received_at=received, connection=1) is None


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
