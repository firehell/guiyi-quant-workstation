from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from guiyi_quant import subing_account
from guiyi_quant.paper import FeeSchedule
from guiyi_quant.subing_decision import REGIME_PROFILE
from guiyi_quant.subing_one_lot import POLICY, build_engine, planned_loss
from tests.unit.subing_account.test_account import inputs


def fixture(prices, frames, *, next_day_at=None):
    adjusted = {
        i: dict(
            ema21=str(D(str(prices[i])) - 2),
            low=str(D(str(prices[i])) - 2),
            high=str(D(str(prices[i])) + 2),
            regime="TREND_UP",
            **changes,
        )
        for i, changes in frames.items()
    }
    xs, original = inputs(prices, frames=adjusted)
    observations = {}
    for i, x in enumerate(xs):
        shift = (
            timedelta(days=1)
            if next_day_at is not None and i >= next_day_at
            else timedelta(0)
        )
        end = x.bar.bar_end + shift
        xs[i] = replace(
            x,
            bar=replace(
                x.bar,
                bar_end=end,
                trading_day=end.date(),
                confirmed_at=end,
                session_open_at=x.bar.session_open_at + shift,
                session_close_at=x.bar.session_close_at + shift,
            ),
            facts=replace(x.facts, trading_day=end.date()),
        )
        e = deepcopy(original[x.bar.bar_end])
        e.update(at=end.isoformat(), trading_day=end.date().isoformat())
        observations[end] = e
    schedule = {}
    if next_day_at is not None:
        for first, last in ((0, next_day_at - 1), (next_day_at, len(xs) - 1)):
            opening = xs[first].bar.bar_end - timedelta(minutes=1)
            closing = xs[last].bar.bar_end
            for i in range(first, last + 1):
                xs[i] = replace(
                    xs[i],
                    bar=replace(
                        xs[i].bar, session_open_at=opening, session_close_at=closing
                    ),
                )
            observations[closing]["day_end_window"] = True
    for i, x in enumerate(xs):
        b = x.bar
        next_open = (
            xs[next_day_at].bar.session_open_at
            if next_day_at is not None and i < next_day_at
            else b.session_open_at + timedelta(days=1)
        )
        schedule[str(b.trading_day)] = dict(
            previous=str(b.trading_day - timedelta(days=1)),
            first_open=b.session_open_at.isoformat(),
            day_end=b.session_close_at.isoformat(),
            next_open=next_open.isoformat(),
        )
    structures = {
        x.bar.bar_end.isoformat(): dict(
            base_regime="TREND_UP", phase="STRUCTURE_ENVELOPE", structure_direction="UP"
        )
        for x in xs
    }
    return xs, observations, schedule, structures


def setup(prices, frames, **kwargs):
    xs, obs, cal, structures = fixture(prices, frames, **kwargs)
    eng, model, _ = build_engine(xs, cal, structures=structures)
    return xs, obs, eng, model, cal, structures


def run(xs, obs, eng):
    return eng.replay(
        xs,
        obs,
        "one-lot",
        execution_model="theoretical_open",
        regime_research_profile=REGIME_PROFILE,
    )


def test_policy_isolated_capital_and_original_globals_unchanged():
    original = subing_account.AccountEngine
    xs, obs, eng, _, _, _ = setup([100, 101, 102], {0: dict(near_zero_golden=True)})
    r = run(xs, obs, eng)
    assert r["initial_cash"] == "1000000" and r["research_policy"] == POLICY
    assert r["fills"][0]["quantity"] == 1
    assert (
        subing_account.INITIAL_CASH == D("100000")
        and subing_account.AccountEngine is original
    )
    assert "up to 1 lot" in r["assumptions"]


@pytest.mark.parametrize(
    "short,trigger",
    [
        (False, "below_previous_low"),
        (False, "high_death"),
        (True, "above_previous_high"),
        (True, "low_golden"),
    ],
)
def test_ordinary_signal_closes_only_lot_mirrored(short, trigger):
    first = dict(
        near_zero_golden=not short,
        near_zero_death=short,
        minute_angle="-2" if short else "2",
        above_ema=not short,
        below_ema=short,
    )
    xs, obs, eng, _, _, _ = setup([100] * 5, {0: first, 2: {trigger: True}})
    if short:
        for o in obs.values():
            o["daily_direction"] = "DOWN"
        for o in obs.values():
            if o["m30"]:
                o["m30"].update(
                    minute_angle="-2",
                    above_ema=False,
                    below_ema=True,
                    high="102",
                    ema21="102",
                )
        # The short policy mirror maps below_ema from above_ema, so it is not an EMA exit.
    r = run(xs, obs, eng)
    assert [f["action"] for f in r["fills"]] == ["OPEN", "CLOSE"]
    assert r["fills"][-1]["reasons"] == ["ONE_LOT_ORDINARY_EXIT"]
    assert r["summary"]["open_quantity"] == 0


def test_no_add_even_with_profitable_base_and_fresh_breakout():
    xs, obs, eng, _, _, _ = setup(
        [100, 101, 110, 112, 113, 114],
        {
            0: dict(near_zero_golden=True),
            2: dict(qualified_pullback=True, pullback_high="111"),
        },
    )
    r = run(xs, obs, eng)
    assert [f["action"] for f in r["fills"]] == ["OPEN"]
    assert max(t["after"]["quantity"] for t in r["trace"]) == 1


def test_planned_stop_budget_rejects_without_tightening_stop_or_replaying_cross():
    xs, obs, eng, _, _, _ = setup([100] * 4, {0: dict(near_zero_golden=True), 1: {}})
    obs[xs[0].bar.bar_end]["m30"].update(ema21="60", low="60")
    r = run(xs, obs, eng)
    assert not r["fills"]
    assert "PLANNED_STOP_RISK_OVER_BUDGET" in r["trace"][0]["actions"][0]["reasons"]
    assert r["decision_state"]["entry_windows"]["LONG"]["source_end"] is None


def test_execution_gap_rechecks_actual_entry_risk_and_cancels():
    xs, obs, eng, _, _, _ = setup([100, 100, 140], {0: dict(near_zero_golden=True)})
    r = run(xs, obs, eng)
    assert not r["fills"] and r["pending"] is None
    assert r["execution_events"][0]["reason"] == "OPENING_FINANCIAL_RECHECK"


def test_planned_loss_includes_both_fees_and_exit_slippage_exact_boundary():
    xs, _ = inputs([100])
    facts = replace(
        xs[0].facts, fees=FeeSchedule(D(0), D(10), D(0), D(20), D(0), D(30), "boundary")
    )
    assert planned_loss(D("100"), D("68.5"), "LONG", facts, 1) == D("1960")
    assert planned_loss(D("100"), D("68"), "LONG", facts, 1) == D("1990")
    assert planned_loss(D("100"), D("67.5"), "LONG", facts, 1) == D("2020")
    assert planned_loss(D("100"), D("100"), "LONG", facts, 1) is None


def losing_fixture(*, next_day=True):
    prices = [100, 101, 100, 99] * 3 + [100] * 6
    frames = {i: dict(near_zero_golden=True) for i in (0, 4, 8, 12)}
    frames.update({i: dict(below_previous_low=True) for i in (2, 6, 10)})
    return setup(prices, frames, next_day_at=13 if next_day else None)


def test_three_actual_net_losses_halt_same_day_before_any_new_entry():
    xs, obs, eng, C, _, _ = losing_fixture(next_day=False)
    r = run(xs, obs, eng)
    assert len(r["closed_rounds"]) == 3 and len(r["fills"]) == 6
    m = C.restore(r["decision_checkpoint"])
    assert m.loss_streak == 3 and m.loss_pause_day == str(xs[0].bar.trading_day)
    assert all(D(t["net_pnl"]) < 0 for t in r["closed_rounds"])
    assert any(
        "CONSECUTIVE_LOSS_PAUSE" in a.get("reasons", [])
        for t in r["trace"]
        for a in t["actions"]
    )


def test_next_day_does_not_resume_without_fresh_signal():
    xs, obs, eng, C, _, _ = losing_fixture()
    r = run(xs, obs, eng)
    assert len(r["fills"]) == 6
    assert C.restore(r["decision_checkpoint"]).loss_pause_day is not None


def test_later_day_fresh_signal_resumes_only_with_clear_same_direction_trend():
    xs, obs, _, _, cal, structures = losing_fixture()
    for i, regime in ((13, "RANGE"), (14, "TREND_UP")):
        obs[xs[i].bar.bar_end]["m30"] = dict(
            obs[xs[12].bar.bar_end]["m30"], near_zero_golden=i == 13, regime=regime
        )
    eng, C, _ = build_engine(xs, cal, structures=structures)
    r = run(xs, obs, eng)
    assert (
        len(r["fills"]) == 7
        and r["fills"][-1]["decision_at"] == xs[14].bar.bar_end.isoformat()
    )
    m = C.restore(r["decision_checkpoint"])
    assert m.loss_streak == 0 and m.loss_pause_day is None


def test_account_restart_and_exact_duplicates_preserve_cash_fills_and_streak():
    xs, obs, eng, _, _, _ = losing_fixture(next_day=False)
    a = eng.AccountEngine(
        "JM2609",
        "jm",
        D("60"),
        "one-lot",
        1,
        "theoretical_open",
        regime_research_profile=REGIME_PROFILE,
    )
    for x in xs[:11]:
        a.step(x, obs[x.bar.bar_end])
    checkpoint = a.checkpoint()
    restored = eng.AccountEngine.restore(checkpoint)
    before = restored.snapshot()
    assert restored.step(xs[10], obs[xs[10].bar.bar_end]) is False
    assert restored.snapshot() == before
    for x in xs[11:]:
        a.step(x, obs[x.bar.bar_end])
        restored.step(x, obs[x.bar.bar_end])
    assert a.snapshot() == restored.snapshot() == run(xs, obs, eng)
    assert restored.model.loss_streak == 3
    changed = deepcopy(obs[xs[10].bar.bar_end])
    changed["close"] = "999"
    with pytest.raises(ValueError, match="INPUT_CONFLICT"):
        restored.step(xs[10], changed)


def test_changed_input_context_rejects_checkpoint_and_failure_latches_until_restore():
    xs, obs, eng, _, cal, structures = setup(
        [100] * 3, {0: dict(near_zero_golden=True)}
    )
    a = eng.AccountEngine(
        "JM2609",
        "jm",
        D("60"),
        "one-lot",
        1,
        "theoretical_open",
        regime_research_profile=REGIME_PROFILE,
    )
    a.step(xs[0], obs[xs[0].bar.bar_end])
    c = a.checkpoint()
    changed = list(xs)
    changed[1] = replace(xs[1], facts=replace(xs[1].facts, tick_size=D("1")))
    other, _, _ = build_engine(changed, cal, structures=structures)
    with pytest.raises(ValueError, match="CHECKPOINT_INVALID"):
        other.AccountEngine.restore(c)
    bad = deepcopy(obs[xs[1].bar.bar_end])
    bad["close"] = "999"
    with pytest.raises(ValueError):
        a.step(xs[1], bad)
    with pytest.raises(ValueError, match="RESTORE_REQUIRED"):
        a.step(xs[1], obs[xs[1].bar.bar_end])
    assert eng.AccountEngine.restore(c).snapshot()["summary"]["fill_count"] == 0


def test_single_trade_budget_includes_estimated_close_fee_and_daily_limit_is_fixed():
    xs, obs, eng, _, _, _ = setup(
        [100, 101, 102, 103], {0: dict(near_zero_golden=True)}
    )
    a = eng.AccountEngine(
        "JM2609",
        "jm",
        D("60"),
        "one-lot",
        1,
        "theoretical_open",
        regime_research_profile=REGIME_PROFILE,
    )
    for x in xs[:3]:
        a.step(x, obs[x.bar.bar_end])
    price = next(iter(a.layers.values()))["price"] - D("1995") / D("60")
    f = a.finance(price, xs[1].facts, "LONG")
    assert (
        f["round_net"] > D("-2000")
        and f["remaining_net"] <= D("-2000")
        and f["round_loss"]
    )
    a.cash -= D("5001")
    assert a.finance(D("101"), xs[1].facts, "LONG")["day_loss"]


def test_completed_close_mode_and_full_account_restore():
    xs, obs, _, _, cal, structures = setup(
        [100, 101, 102, 101, 100],
        {0: dict(near_zero_golden=True), 2: dict(below_previous_low=True)},
    )
    eng, _, _ = build_engine(
        xs, cal, structures=structures, execution_model="completed_close"
    )
    a = eng.AccountEngine(
        "JM2609",
        "jm",
        D(60),
        "close-mode",
        1,
        "completed_close",
        regime_research_profile=REGIME_PROFILE,
    )
    for x in xs:
        a.step(x, obs[x.bar.bar_end])
    assert len(a.closed_rounds) == 1
    assert eng.AccountEngine.restore(a.checkpoint()).snapshot() == a.snapshot()
    assert all(f["fill_at"] > f["decision_at"] for f in a.snapshot()["fills"])


def test_future_prices_cannot_change_previous_fills_or_decisions():
    xs, obs, eng, _, cal, structures = setup(
        [100, 101, 102, 101, 100, 100],
        {0: dict(near_zero_golden=True), 2: dict(below_previous_low=True)},
    )
    original = run(xs, obs, eng)
    changed = list(xs)
    changed[-1] = replace(
        xs[-1],
        bar=replace(xs[-1].bar, open=D(200), high=D(201), low=D(199), close=D(200)),
    )
    other_obs = deepcopy(obs)
    other_obs[xs[-1].bar.bar_end]["close"] = "200"
    other, _, _ = build_engine(changed, cal, structures=structures)
    future = run(changed, other_obs, other)
    cutoff = xs[-2].bar.bar_end.isoformat()
    assert [f for f in original["fills"] if f["fill_at"] <= cutoff] == [
        f for f in future["fills"] if f["fill_at"] <= cutoff
    ]
    assert [t for t in original["trace"] if t["facts"]["at"] <= cutoff] == [
        t for t in future["trace"] if t["facts"]["at"] <= cutoff
    ]


def test_nonnegative_closed_trade_resets_streak_and_exact_budget_comparison():
    xs, obs, _, _, cal, structures = setup(
        [100, 100, 100, 101, 101],
        {0: dict(near_zero_golden=True), 2: dict(below_previous_low=True)},
    )
    zero = FeeSchedule(*[D(0)] * 6, "zero-engineering-fees")
    xs = [replace(x, facts=replace(x.facts, fees=zero)) for x in xs]
    eng, C, _ = build_engine(xs, cal, structures=structures)
    result = run(xs, obs, eng)
    assert D(result["closed_rounds"][0]["net_pnl"]) == 0
    assert C.restore(result["decision_checkpoint"]).loss_streak == 0
    # Budget uses <=, not a rounded currency or chart value.
    stop = D(100) - (D(2000) - D(30)) / D(60)
    assert planned_loss(D(100), stop, "LONG", xs[0].facts, 1) == D(2000)


def test_unsupported_physical_mix_and_missing_structure_fail_closed():
    xs, _, _, _, cal, structures = setup([100, 100], {})
    changed = list(xs)
    changed[1] = replace(
        xs[1],
        bar=replace(xs[1].bar, physical_contract="JM2701"),
        facts=replace(xs[1].facts, physical_contract="JM2701"),
    )
    with pytest.raises(ValueError, match="JM_ONLY"):
        build_engine(changed, cal, structures=structures)
    with pytest.raises(ValueError, match="STRUCTURE_COVERAGE"):
        build_engine(xs, cal, structures={})


@pytest.mark.parametrize(
    "missing", [{"high_death": None}, {"volume_tier": "ZERO_BASELINE"}]
)
def test_original_admission_rejection_cannot_clear_loss_pause(missing):
    xs, obs, _, _, cal, structures = losing_fixture()
    frame = obs[xs[12].bar.bar_end]["m30"]
    obs[xs[13].bar.bar_end]["m30"] = dict(
        frame, near_zero_golden=True, regime="TREND_UP", **missing
    )
    obs[xs[14].bar.bar_end]["m30"] = dict(
        frame, near_zero_golden=True, regime="TREND_DOWN"
    )
    eng, C, _ = build_engine(xs, cal, structures=structures)
    result = run(xs, obs, eng)
    assert len(result["fills"]) == 6
    model = C.restore(result["decision_checkpoint"])
    assert model.loss_pause_day is not None and model.loss_streak == 3


def test_changed_source_is_rejected_before_account_mutation():
    xs, obs, eng, _, _, _ = setup([100, 101, 102], {0: dict(near_zero_golden=True)})
    account = eng.AccountEngine(
        "JM2609",
        "jm",
        D(60),
        "bound-source",
        1,
        "theoretical_open",
        regime_research_profile=REGIME_PROFILE,
    )
    changed = replace(xs[0], bar=replace(xs[0].bar, open=D("100.5"), close=D("100.5")))
    technical = deepcopy(obs[xs[0].bar.bar_end])
    technical["close"] = "100.5"
    with pytest.raises(ValueError, match="INPUT_CHANGED"):
        account.step(changed, technical)
    assert account.cash == D(1000000) and not account.inputs and not account.failed
    for x in xs:
        account.step(x, obs[x.bar.bar_end])
    assert (
        eng.AccountEngine.restore(account.checkpoint()).snapshot() == account.snapshot()
    )


@pytest.mark.parametrize(
    "missing", [{"high_death": None}, {"volume_tier": "ZERO_BASELINE"}]
)
def test_non_environment_rejection_consumes_resume_cross(missing):
    xs, obs, _, _, cal, structures = losing_fixture()
    frame = obs[xs[12].bar.bar_end]["m30"]
    obs[xs[13].bar.bar_end]["m30"] = dict(
        frame, near_zero_golden=True, regime="TREND_UP", **missing
    )
    obs[xs[14].bar.bar_end]["m30"] = dict(
        frame, near_zero_golden=False, regime="TREND_UP"
    )
    eng, C, _ = build_engine(xs, cal, structures=structures)
    result = run(xs, obs, eng)
    assert len(result["fills"]) == 6
    model = C.restore(result["decision_checkpoint"])
    assert model.loss_pause_day is not None and model.loss_streak == 3
