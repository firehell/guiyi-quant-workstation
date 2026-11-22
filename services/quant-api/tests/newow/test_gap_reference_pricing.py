from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy
from guiyi_quant.newow.product_contracts import ProductBar, ProductFrequency
from guiyi_quant.newow.product_identity import GAP_FILL_REFERENCE_MODEL_VERSION
from guiyi_quant.newow.reference_pricing import GAP_FILL_PRICE_POLICY, adjust_reference_price
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector, ReferenceTradeStatus


@pytest.mark.parametrize(("opening", "buy", "price", "gap"), [
    ("110", True, "110", True),
    ("90", False, "90", True),
    ("100", True, "100", False),
    ("100", False, "100", False),
    ("90", True, "100", False),
    ("110", False, "100", False),
    (None, True, "100", False),
    ("0", False, "100", False),
    ("-1", False, "100", False),
    ("NaN", False, "100", False),
    ("Infinity", True, "100", False),
])
def test_gap_price_matches_public_boundary_cases(opening, buy, price, gap):
    opening_price = None if opening is None else Decimal(opening)
    threshold = Decimal("100")
    result = adjust_reference_price(threshold, opening_price, buy=buy)
    assert result == Decimal(price)
    assert (result != threshold) is gap


@pytest.mark.parametrize("strategy", ["trend", "main_rise"])
def test_candidate_replay_changes_pair_prices_and_preserves_action_timing(strategy):
    first = datetime(2026, 1, 1, 7, tzinfo=UTC)
    ohlc_rows = [(100, 100, 100, 100)] * 50 + [
        (75, 83, 72, 80), (145, 147, 126, 140), (45, 57, 44, 50),
    ]
    bars = []
    for index, ohlc in enumerate(ohlc_rows):
        at = first + timedelta(days=index)
        bar = NewowDailyBar(
            "rb", "RB2701", "rb-owner", at.date(), at,
            *map(Decimal, ohlc), 100, 500, "test", True, True,
        )
        bars.append(ProductBar(bar, ProductFrequency.DAILY))
    bars = tuple(bars)
    legacy_identity = build_product_identity("rb", strategy, "1d")
    gap_identity = build_product_identity("rb", strategy, "1d", reference_price_policy=GAP_FILL_PRICE_POLICY)
    legacy = replay_strategy(legacy_identity, bars)
    candidate = replay_strategy(gap_identity, bars)
    def action_timing(replay):
        return [(action.bar_end, action.kind, action.trade_eligibility) for action in replay.actions]

    assert action_timing(candidate) == action_timing(legacy)
    assert [action.anchor_price for action in candidate.actions] == [action.reference_price for action in legacy.actions]
    assert [action.reference_price for action in candidate.actions] == [Decimal("75"), Decimal("145"), Decimal("45")]
    assert {action.signal_id for action in candidate.actions}.isdisjoint(action.signal_id for action in legacy.actions)

    projector = ReferenceTradeProjector()
    closed, = projector.project(candidate, (), bars[-1].bar.bar_end).trades
    legacy_trade, = projector.project(legacy, (), bars[-1].bar.bar_end).trades
    assert closed.status is ReferenceTradeStatus.CLOSED
    assert (closed.entry_reference_price, closed.exit_reference_price) == (Decimal("145"), Decimal("45"))
    assert closed.reference_model_version == GAP_FILL_REFERENCE_MODEL_VERSION
    assert closed.reference_trade_id != legacy_trade.reference_trade_id

    prefix = replay_strategy(gap_identity, bars[:-1])
    opened, = projector.project(prefix, (), bars[-2].bar.bar_end).trades
    assert prefix.actions == candidate.actions[:-1]
    assert opened.status is ReferenceTradeStatus.OPEN
    assert opened.entry_reference_price == Decimal("145")
    assert opened.exit_reference_price is None
    assert opened.mark_reference_price == Decimal("140")
