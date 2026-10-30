"""Fixed-window admission keeps authoritative physical-day validation intact."""
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import random

import pytest

from app.market_data.domain import BarFrequency
from app.market_data.subing_reference import SubingReferenceService, SubingReferenceError
from app.reference_trading.htdy_history import HtdyReplaySegment, history_identity, replay_htdy
from test_subing_reference_service import Coverage, FrequencyMarket


def make(context=None):
    market = FrequencyMarket()
    rng = random.Random(7)
    price = Decimal(100)
    bars = []
    for bar in market.bars:
        close = price + Decimal(rng.choice((-5, -3, -1, 1, 3, 5)))
        bars.append(replace(bar, open=price, close=close, high=max(price, close)+1, low=min(price, close)-1))
        price = close
    market.bars = tuple(bars)
    market.physical = market.bars
    market.owner = replace(market.owner, start_trading_day=market.days[10])
    service = SubingReferenceService(
        market, coverage=Coverage(), active_products={"rb"}, physical_context_bars=context,
    )
    return service, market


def load(service, market):
    return service.load_historical_inputs(
        symbol="rb", frequency=BarFrequency.H1, since=market.days[10],
        through=market.days[-1], as_of=datetime(2026, 7, 25, 7, tzinfo=UTC),
    )


def test_admission_bound_and_default_reader_match():
    full, market = make()
    bounded, limited_market = make(32)
    full_segments, _, _, _ = load(full, market)
    limited_segments, _, _, _ = load(bounded, limited_market)
    assert len(full_segments[0].bars) == 500
    # First owned index 200 needs index 169; whole-day reader starts at 160.
    assert len(limited_segments[0].bars) == 340
    assert limited_segments[0].bars == full_segments[0].bars[160:]
    for service, source, segments in ((full, market, full_segments), (bounded, limited_market, limited_segments)):
        events, bytes_bound = service.historical_input_bound(
            symbol="rb", frequency="60m", since=source.days[10],
            through=source.days[-1], as_of=datetime(2026, 7, 25, 7, tzinfo=UTC),
        )
        assert events == 2 * sum(len(s.bars) for s in segments) + len(segments)
        assert bytes_bound == events * 4096


def test_actual_htdy_kernel_signals_and_trades_unchanged():
    outputs = []
    for context in (None, 32):
        service, market = make(context)
        segments, _, _, _ = load(service, market)
        selected = {b.bar_end: b for b in market.bars}
        replay_segments = tuple(HtdyReplaySegment(
            s.physical_contract, s.segment_id, s.segment_id, s.owner_since, s.owner_through,
            tuple(selected[b.bar_end] for b in s.bars),
        ) for s in segments)
        outputs.append(replay_htdy(history_identity("rb", "60m"), replay_segments))
    assert outputs[0][1]  # Exercise genuine kernel actions, not empty equality.
    assert outputs[0] == outputs[1]


def test_missing_expected_warmup_fails_closed():
    service, market = make(32)
    market.physical = tuple(b for i, b in enumerate(market.bars) if i != 169)
    with pytest.raises(SubingReferenceError, match="DATA_UNAVAILABLE"):
        load(service, market)


@pytest.mark.parametrize("context", [True, 31, 33, "32"])
def test_invalid_context_policy(context):
    with pytest.raises(ValueError, match="PHYSICAL_CONTEXT_POLICY_INVALID"):
        make(context)


def test_quality_failure_not_bypassed_by_context_admission():
    from app.market_data.market_data_service import MarketDataError
    service, market = make(32)
    def fail(_request):
        raise MarketDataError("DATASET_OR_PARTITION_MISSING")
    market.query_contract_trading_days = fail
    with pytest.raises(SubingReferenceError) as caught:
        load(service, market)
    assert caught.value.diagnostic["reason"] == "DATASET_OR_PARTITION_MISSING"
    assert caught.value.diagnostic["context"]["expected_count"] == 340


def test_context_policy_does_not_apply_to_other_frequencies():
    service, market = make(32)
    with pytest.raises(SubingReferenceError, match="INVALID_QUERY"):
        service.historical_input_bound(
            symbol="rb", frequency="15m", since=market.days[10],
            through=market.days[-1], as_of=datetime(2026, 7, 25, 7, tzinfo=UTC),
        )
