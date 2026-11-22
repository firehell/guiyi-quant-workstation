from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D

import pytest

from guiyi_quant.subing_decision import REGIME_PROFILE
from guiyi_quant.subing_one_lot import HOUR_EXIT, build_engine
from guiyi_quant.subing_one_lot.portfolio import replay
from tests.unit.subing_one_lot.test_policy import fixture
from tests.unit.subing_one_lot.test_portfolio import segment


def sample(*, priority=None, short=False):
    first = dict(near_zero_golden=not short, near_zero_death=short,
                 minute_angle="-2" if short else "2",
                 above_ema=not short, below_ema=short)
    prices = [100, 101, 117, 118, 117, 116, 114, 115]
    if short:
        prices = [200 - p for p in prices]
    breaks = "above_previous_high" if short else "below_previous_low"
    xs, obs, cal, structures = fixture(prices, {0: first, 3: {breaks: True}})
    if short:
        for e in obs.values():
            e["daily_direction"] = "DOWN"
            if e["m30"]:
                e["m30"].update(above_ema=False, below_ema=True, minute_angle="-2",
                                regime="TREND_DOWN", ema21=str(D(e["close"]) + 2))
    for i, favorable in ((1, True), (2, True), (5, False)):
        bar = xs[i].bar
        sign = -1 if short else 1
        ema = bar.close - sign * (1 if favorable else -1)
        structures[bar.bar_end.isoformat()]["hourly"] = dict(
            at=bar.bar_end.isoformat(), direction="DOWN" if short else "UP",
            close=str(bar.close), ema21=str(ema),
        )
    if priority == "earlier_gross_threshold":
        at = xs[2].bar.bar_end
        price = D(118) if not short else D(82)
        # Actual entry is 101.5/98.5. Gross reaches the 16.5-point risk;
        # the paid and estimated fees keep net below it.
        xs[2] = replace(xs[2], bar=replace(xs[2].bar, close=price))
        obs[at]["close"] = str(price)
        structures[at.isoformat()]["hourly"]["close"] = str(price)
    else:
        at = xs[2].bar.bar_end
        price = D(119) if not short else D(81)
        xs[2] = replace(xs[2], bar=replace(xs[2].bar, close=price,
                                           high=max(price, xs[2].bar.high),
                                           low=min(price, xs[2].bar.low)))
        obs[at]["close"] = str(price)
        structures[at.isoformat()]["hourly"]["close"] = str(price)
    if priority == "tier1":
        obs[xs[0].bar.bar_end]["m30"]["volume_tier"] = "TIER_1"
    if priority == "same_moment":
        row = deepcopy(obs[xs[3].bar.bar_end]["m30"])
        obs[xs[2].bar.bar_end]["m30"] = row
    if priority == "macd":
        obs[xs[3].bar.bar_end]["m30"]["high_death"] = True
    return xs, obs, cal, structures


def run_profile(data, profile, cutoff=None):
    xs, obs, cal, structures = data
    module, _, _ = build_engine(xs, cal, structures=structures,
                                execution_model="completed_close", exit_profile=profile)
    account = module.AccountEngine("JM2609", "jm", D(60), "h1-witness",
                                   regime_research_profile=REGIME_PROFILE)
    for x in xs[:cutoff]:
        account.step(x, obs[x.bar.bar_end])
    return module, account


@pytest.mark.parametrize("short", [False, True])
def test_handoff_once_and_suppresses_only_ordinary_m30(short):
    data = sample(short=short)
    xs = data[0]
    _, a = run_profile(data, None)
    module, b = run_profile(data, HOUR_EXIT, cutoff=4)
    assert b.model.state()["hour_exit_since"] == xs[2].bar.bar_end.isoformat()
    assert len(b.fills) == 1
    restored = module.AccountEngine.restore(b.checkpoint())
    for x in xs[4:]:
        restored.step(x, data[1][x.bar.bar_end])
    _, full = run_profile(data, HOUR_EXIT)
    assert restored.snapshot() == full.snapshot()
    assert a.fills[-1]["fill_at"] == xs[4].bar.bar_end
    assert full.fills[-1]["reasons"] == ["H1_EMA21_CLEAR"]
    assert full.fills[-1]["decision_at"] == xs[5].bar.bar_end
    assert full.fills[-1]["fill_at"] == xs[6].bar.bar_end
    assert full.model.hour_exit_since is None


@pytest.mark.parametrize("priority,reason", [
    ("same_moment", "ONE_LOT_ORDINARY_EXIT"),
    ("earlier_gross_threshold", "ONE_LOT_ORDINARY_EXIT"),
    ("tier1", "PROFIT_1R_TIER1_CLEAR"),
    ("macd", "ONE_LOT_ORDINARY_EXIT"),
])
def test_minute_exit_priority(priority, reason):
    data = sample(priority=priority)
    _, before_exit = run_profile(data, HOUR_EXIT, cutoff=3)
    assert (before_exit.model.hour_exit_since is not None) == (priority == "macd")
    _, account = run_profile(data, HOUR_EXIT)
    assert reason in account.fills[-1]["reasons"]
    assert account.model.hour_exit_since is None


def test_shared_profile_identity_and_strict_next_minute():
    xs, obs, cal, structures = sample()
    data = replace(segment("jm", [100]), executions=tuple(xs), schedule=cal,
                   observations=obs, structures=structures)
    a = replay([data], "a")
    b = replay([data], "b", exit_profile=HOUR_EXIT)
    assert "exit_profile" not in a["policy"]
    assert b["policy"]["exit_profile"] == HOUR_EXIT
    fill = b["accounts"]["JM2609"]["fills"][-1]
    assert fill["decision_at"] < fill["fill_bar_end"] == fill["fill_at"]


def test_handoff_prefix_is_independent_of_later_h1_values():
    data = sample()
    xs, obs, cal, structures = data
    _, whole = run_profile(data, HOUR_EXIT, cutoff=5)
    prefix = xs[:5]
    _, shortened = run_profile(
        (prefix, obs, cal, {x.bar.bar_end.isoformat(): structures[x.bar.bar_end.isoformat()]
                            for x in prefix}),
        HOUR_EXIT,
    )
    assert whole.model.state() == shortened.model.state()
    assert whole.fills == shortened.fills


def test_explicit_range_candidate_commits_first_transition_only():
    from guiyi_quant.subing_one_lot import RANGE_EXIT

    data = sample()
    xs, obs, _, _ = data
    frame = deepcopy(obs[xs[3].bar.bar_end]["m30"])
    frame.update(regime="RANGE", below_previous_low=False)
    obs[xs[3].bar.bar_end]["m30"] = frame
    _, a = run_profile(data, None)
    _, b = run_profile(data, RANGE_EXIT)
    assert len(a.fills) == 1
    assert b.fills[-1]["reasons"] == ["M30_TREND_TO_RANGE_CLEAR"]
    assert b.fills[-1]["fill_at"] == xs[4].bar.bar_end


def test_range_transition_on_entry_fill_creates_later_exit_obligation():
    from guiyi_quant.subing_one_lot import RANGE_EXIT

    data = sample()
    xs, obs, _, _ = data
    frame = deepcopy(obs[xs[0].bar.bar_end]["m30"])
    frame.update(regime="RANGE", near_zero_golden=False)
    obs[xs[1].bar.bar_end]["m30"] = frame
    _, b = run_profile(data, RANGE_EXIT)
    assert [fill["action"] for fill in b.fills] == ["OPEN", "CLOSE"]
    assert b.fills[-1]["decision_at"] == b.fills[0]["fill_at"] == xs[1].bar.bar_end
    assert b.fills[-1]["fill_at"] == xs[2].bar.bar_end


def test_hour_equality_while_held_does_not_trigger_exit():
    data = sample()
    xs, _, _, structures = data
    hour = structures[xs[5].bar.bar_end.isoformat()]["hourly"]
    hour["ema21"] = hour["close"]
    _, b = run_profile(data, HOUR_EXIT)
    assert len(b.fills) == 1
    assert b.model.hour_exit_since == xs[2].bar.bar_end


def test_hour_from_future_is_rejected():
    data = sample()
    xs, _, _, structures = data
    structures[xs[1].bar.bar_end.isoformat()]["hourly"]["at"] = xs[2].bar.bar_end.isoformat()
    with pytest.raises(ValueError, match="H1_TIME_CONFLICT"):
        run_profile(data, HOUR_EXIT)


def test_shared_handoff_replays_same_prefix_before_resuming():
    from guiyi_quant.subing_one_lot.portfolio import Portfolio, Segment

    xs, obs, cal, structures = sample()
    seg = Segment("jm", tuple(xs), obs, structures, cal)
    restarted = Portfolio([seg], "cold-restart", exit_profile=HOUR_EXIT)
    cutoff = xs[4].bar.bar_end
    restored = None
    for x in xs:
        restarted.step_batch([(x, obs[x.bar.bar_end])])
        if x.bar.bar_end == cutoff:
            restored = restarted.snapshot()
            break
    assert restored["accounts"]["JM2609"]["decision_state"]["hour_exit_since"]
    for x in xs[5:]:
        restarted.step_batch([(x, obs[x.bar.bar_end])])
    assert restarted.snapshot() == replay([seg], "cold-restart", exit_profile=HOUR_EXIT)
