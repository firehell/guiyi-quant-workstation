"""Versioned chart initial CLEAR remains display-only under replay validation."""
from copy import copy
from dataclasses import replace
from decimal import Decimal

import pytest

from guiyi_quant.newow.product_adapters import build_product_identity, replay_strategy
from guiyi_quant.newow.product_contracts import TradeEligibility
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector


def trend_case(product_cases, frequency="1d"):
    case = product_cases.main_rise_lifecycle_input((Decimal("100"), Decimal("100"), Decimal("90")), frequency)
    return replace(case, identity=build_product_identity("rb", "trend", frequency))


@pytest.mark.parametrize("frequency", ["1d", "1w", "60m"])
def test_trend_initial_clear_has_no_trade_and_preserves_prefix(product_cases, frequency):
    case = trend_case(product_cases, frequency)
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(case.identity, case.bars, lifecycle_evidence=(evidence,))
    assert len(replay.actions) == 1
    clear = replay.actions[0]
    assert clear.trade_eligibility is TradeEligibility.INITIAL_CLEAR_NO_ENTRY
    assert clear.source_marker_id and clear.related_build_id is None
    assert clear.source_related_marker_ids == ()
    assert clear.reference_price == dict(replay.frames[-1].main_values)["b"]
    assert replay_strategy(case.identity, case.bars[:2]).frames == replay.frames[:2]
    projected = ReferenceTradeProjector().project(replay, (), case.bars[-1].bar.bar_end)
    assert projected.trades == ()
    assert projected.diagnostics == ("INITIAL_CLEAR_NO_ENTRY",)


def test_trend_prewarm_initial_clear_is_consumed_and_not_reintroduced(product_cases):
    case = trend_case(product_cases)
    bars = tuple(replace(bar, bar=replace(bar.bar, observation_eligible=index == 2))
                 for index, bar in enumerate(case.bars))
    replay = replay_strategy(case.identity, bars)
    assert replay.actions[0].trade_eligibility is TradeEligibility.INITIAL_CLEAR_NO_ENTRY
    all_warmup = tuple(replace(bar, bar=replace(bar.bar, observation_eligible=False)) for bar in case.bars)
    assert replay_strategy(case.identity, all_warmup).actions == ()


@pytest.mark.parametrize("damage", ["missing_prefix", "replaced_input", "forged_evidence", "wrong_price"])
def test_trend_initial_clear_rejects_damaged_proof(product_cases, damage):
    case = trend_case(product_cases)
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(case.identity, case.bars, lifecycle_evidence=(evidence,))
    damaged = copy(replay)
    if damage == "missing_prefix":
        object.__setattr__(damaged, "frames", replay.frames[-1:])
    elif damage == "replaced_input":
        first = replay.frames[0]
        changed = replace(first.bar, bar=replace(first.bar.bar, source_identity="replaced"))
        object.__setattr__(damaged, "frames", (replace(first, bar=changed), *replay.frames[1:]))
    elif damage == "forged_evidence":
        object.__setattr__(damaged, "lifecycle_evidence", (replace(evidence, input_sha256="f" * 64),))
    else:
        action = replace(replay.actions[0], reference_price=Decimal("50"))
        object.__setattr__(damaged, "actions", (action,))
        object.__setattr__(damaged, "frames", (*replay.frames[:-1], replace(replay.frames[-1], actions=(action,))))
    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(damaged, (), case.bars[-1].bar.bar_end)
