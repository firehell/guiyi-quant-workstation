from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from guiyi_quant.newow_futures.contracts import Bar, Feature, Position, Profile, Variant
from guiyi_quant.newow_futures.strategy import evaluate

T = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)


def feature(*, side=1, close="101", frequency="5m", minute=30, **changes):
    c = D(close)
    at = T + timedelta(minutes=minute)
    b = Bar("jm", "JM2605", frequency, at, date(2026, 1, 5), c - side,
            c + 2, c - 2, c, D(10), f"{frequency}:{minute}", at,
            owner_segment_id="a", calculation_segment_id="a")
    f = Feature(b, D(100 + side), D(100), D(100 - side), D(2), D(110), D(90),
                D(100), D(100), D(100), D(100), D(100 + side), D(100),
                D(100 - side), side, D(100), D(100))
    return replace(f, **changes)


def position(*, side=1, **changes):
    p = Position(side, D(100), D(96 if side == 1 else 104), D(96 if side == 1 else 104),
                 D(4), T, T, "5m", "trend", favorable_close=D(100))
    return replace(p, **changes)


def run(variant=Variant.TREND, base=None, higher=None, pos=None, **kwargs):
    return evaluate(Profile(variant, "5m"), base or feature(), higher or {}, pos, tick=D("0.5"), **kwargs)


@pytest.mark.parametrize("side,close,stop", [(1,"101","97"), (-1,"99","103")])
def test_trend_entry_is_symmetric_with_signal_close_anchor(side, close, stop):
    d = run(base=feature(side=side, close=close))
    assert d.action == "ENTER" and d.side == side
    assert d.position.entry == D(close)
    assert d.position.stop == D(stop)
    assert d.position.r == D(4)
    assert d.position.branch == "trend"


def test_unknown_never_enters_and_neutral_does_not_select_trend():
    assert run(base=feature(regime=None)).reason == "INPUT_UNAVAILABLE"
    assert run(base=feature(regime=0)).action == "WAIT"


def test_nonpositive_protective_price_is_not_a_valid_reference_entry():
    decision = run(base=feature(atr=D(100)))
    assert decision.action == 'WAIT' and decision.position is None
    assert decision.reason == 'INVALID_PROTECTIVE_PRICE'


@pytest.mark.parametrize("variant", [Variant.OSCILLATION, Variant.TEST1, Variant.TEST2, Variant.TEST3, Variant.TEST4])
@pytest.mark.parametrize("side,close", [(1,"91"),(-1,"109")])
def test_oscillation_variants_require_neutral_rejection_inside_channel(variant, side, close):
    f = feature(side=side, close=close, regime=0)
    h = {"30m": feature(side=side, frequency="30m", minute=25)}
    d = run(variant, f, h)
    assert d.action == "ENTER" and d.side == side
    assert d.position.entry_target == (D(110) if side == 1 else D(90))
    assert d.position.r == (D(3) if variant == Variant.TEST1 else D(4))
    assert run(variant, replace(f, regime=side), h).action == "WAIT"


def test_test3_requires_known_same_direction_next_level_not_equal_time():
    f = feature(close="91", regime=0)
    assert run(Variant.TEST3, f).action == "WAIT"
    assert run(Variant.TEST3, f, {"30m":feature(frequency="30m", minute=30)}).action == "WAIT"
    assert run(Variant.TEST3, f, {"30m":feature(frequency="30m", minute=25, regime=0)}).action == "WAIT"


def test_dual_fusion_freezes_entry_branch_and_main_rise_has_independent_gate():
    assert run(Variant.DUAL).position.branch == "trend"
    assert run(Variant.DUAL, feature(close="91", regime=0)).position.branch == "oscillation"
    assert run(Variant.MAIN_RISE).position.branch == "main_rise"
    assert run(Variant.MAIN_RISE, feature(ma35=None)).action == "WAIT"


def test_core_exit_counts_new_holding_bars_once_and_two_consecutive_wrong_closes():
    p = position(upgrades=1, holding_frequency="30m", stage_at=T+timedelta(minutes=5))
    h = feature(frequency="30m", minute=20, close="99")
    a = run(base=feature(minute=30), higher={"30m":h}, pos=p)
    assert a.action == "WAIT" and a.position.invalid_closes == 1
    b = run(base=feature(minute=35), higher={"30m":h}, pos=a.position)
    assert b.position.invalid_closes == 1
    c = run(base=feature(minute=40), higher={"30m":feature(frequency="30m", minute=39, close="99")}, pos=b.position)
    assert c.action == "CLOSE" and c.reason == "HOLDING_TREND_EXIT"


def test_ordinary_target_uses_rolling_or_frozen_edge_and_upgrade_has_priority():
    p = position(branch="oscillation", entry_target=D(110), earned_r=True)
    f = feature(close="111", upper=D(120))
    assert run(Variant.OSCILLATION, f, pos=p).action == "WAIT"
    assert run(Variant.TEST2, f, pos=p).action == "CLOSE"
    d = run(Variant.TEST2, f, {"30m":feature(frequency="30m", minute=25)}, p)
    assert d.upgraded and d.action == "ADD"
    assert d.position.holding_frequency == "30m"


def test_upgrade_requires_fresh_snapshot_after_stage_and_only_one_level_per_base():
    p = position(earned_r=True)
    f = feature(close="109")
    stale = feature(frequency="30m", minute=0)
    assert not run(base=f, higher={"30m":stale}, pos=p).upgraded
    d = run(base=f, higher={"30m":feature(frequency="30m",minute=10),
                           "60m":feature(frequency="60m",minute=20)}, pos=p)
    assert d.position.holding_frequency == "30m" and d.position.upgrades == 1
    assert d.position.stage_at == f.bar.bar_end
    assert d.position.adds == 0


def test_earned_one_r_latches_and_tick_rounded_stop_never_widens():
    d = run(base=feature(close="104.1"), pos=position(), close_cost_per_unit=D("0.2"))
    assert d.position.earned_r and d.position.stop == D("100.5")
    later = run(base=feature(close="102", minute=35, atr=D(10)), pos=d.position)
    assert later.position.earned_r and later.position.stop >= d.position.stop
    short = run(base=feature(side=-1, close="95.9"), pos=position(side=-1), close_cost_per_unit=D("0.2"))
    assert short.position.stop == D("99.5")


def test_promotion_resets_favorable_close_and_reduced_position_cannot_add():
    p = position(favorable_close=D(150), earned_r=True, reduced=True)
    d = run(base=feature(close="105"), higher={"30m":feature(frequency="30m",minute=25, atr=D(20))},pos=p)
    assert d.upgraded and d.action == "WAIT"
    assert d.position.favorable_close == D(105)
    assert d.position.stop >= p.stop


def test_reduce_has_priority_over_add_and_does_not_fake_completed_reduction():
    p = position(earned_r=True, upgrades=1, holding_frequency="30m")
    f = feature(close="99", previous_close=D(101), previous_slow=D(100))
    d = run(base=f, higher={"30m":feature(frequency="30m",minute=20),
                           "60m":feature(frequency="60m",minute=25)},pos=p)
    assert d.action == "REDUCE" and not d.position.reduced


def test_test4_confirms_target_then_uses_later_favorable_close_and_reversal():
    p = position(branch="oscillation", entry_target=D(110))
    a = run(Variant.TEST4, feature(close="111"), pos=p)
    assert a.action == "WAIT" and a.position.confirm_reference == D(111)
    b = run(Variant.TEST4, feature(close="113", minute=35), pos=a.position)
    assert b.position.confirm_reference == D(113)
    c = run(Variant.TEST4, feature(close="112", minute=40),pos=b.position)
    assert c.action == "CLOSE" and c.reason == "OSC_CONFIRM_REVERSAL"


def test_missing_holding_input_and_owner_mismatch_fail_closed():
    p = position(holding_frequency="30m", upgrades=1)
    assert run(pos=p).reason == "INPUT_UNAVAILABLE"
    h = feature(frequency="30m",minute=25)
    h = replace(h, bar=replace(h.bar, owner_segment_id="other"))
    assert run(higher={"30m":h},pos=p).reason == "INPUT_UNAVAILABLE"


def test_overnight_eligibility_needs_known_nonopposite_daily_and_latched_r():
    p = position(holding_frequency="60m", earned_r=True, upgrades=2)
    h = {"60m":feature(frequency="60m",minute=20),"1d":feature(frequency="1d", minute=25,regime=0)}
    assert run(higher=h,pos=p).position.overnight_eligible
    h.pop("1d")
    assert not run(higher=h,pos=p).position.overnight_eligible


@pytest.mark.parametrize("side", [-1, 1])
def test_main_rise_and_oscillation_exits_are_direction_symmetric(side):
    close = "101" if side == 1 else "99"
    assert run(Variant.MAIN_RISE, feature(side=side, close=close)).side == side
    opposite = "111" if side == 1 else "89"
    p = position(side=side, branch="oscillation", entry_target=D(110 if side == 1 else 90))
    assert run(Variant.OSCILLATION, feature(side=side, close=opposite), pos=p).action == "CLOSE"


def test_future_and_other_owner_snapshots_cannot_promote_or_change_state():
    p = position(earned_r=True)
    base = feature(close="109")
    expected = run(base=base, pos=p)
    future = feature(frequency="30m", minute=35)
    wrong_owner = replace(future, bar=replace(future.bar, bar_end=T+timedelta(minutes=25),
                                             confirmed_at=T+timedelta(minutes=25),
                                             calculation_segment_id="wrong"))
    assert run(base=base, higher={"30m":future},pos=p) == expected
    assert run(base=base, higher={"30m":wrong_owner},pos=p) == expected


def test_second_add_requires_two_r_and_maximum_two_actual_layers():
    p = position(earned_r=True, adds=1)
    h = {"30m":feature(frequency="30m",minute=25)}
    assert run(base=feature(close="107"), higher=h, pos=p).action == "WAIT"
    assert run(base=feature(close="108"), higher=h, pos=p).action == "ADD"
    assert run(base=feature(close="112"), higher=h, pos=replace(p, adds=2)).action == "WAIT"


def test_invalid_close_counter_resets_on_a_known_neutral_price_side():
    p = position(invalid_closes=1,last_holding_bar=T+timedelta(minutes=5))
    d = run(base=feature(close="100"),pos=p)
    assert d.action == "WAIT" and d.position.invalid_closes == 0


def test_ineligible_warmup_bar_can_update_existing_position_but_cannot_enter():
    f = feature()
    f = replace(f, bar=replace(f.bar, observation_eligible=False))
    assert run(base=f).reason == "OBSERVATION_INELIGIBLE"
    assert run(base=f, pos=position()).position.last_holding_bar == f.bar.bar_end


def test_delayed_entry_confirmation_is_the_stage_anchor_for_later_upgrade():
    signal = feature(minute=30)
    signal = replace(signal, bar=replace(signal.bar, confirmed_at=T+timedelta(minutes=50)))
    entered = run(base=signal)
    assert entered.position.entry_at == signal.bar.confirmed_at
    assert entered.position.stage_at == signal.bar.confirmed_at
    earlier_higher = feature(frequency="30m", minute=45)
    later = run(base=feature(close="109", minute=55), higher={"30m":earlier_higher}, pos=entered.position)
    assert not later.upgraded


def test_delayed_upgrade_confirmation_is_the_next_stage_anchor():
    signal = feature(close="109", minute=30)
    signal = replace(signal, bar=replace(signal.bar, confirmed_at=T+timedelta(minutes=50)))
    upgraded = run(base=signal, higher={"30m":feature(frequency="30m", minute=25)},
                   pos=position(earned_r=True))
    assert upgraded.upgraded and upgraded.position.stage_at == signal.bar.confirmed_at
    later = run(base=feature(close="109", minute=55), higher={
        "30m":feature(frequency="30m",minute=45),"60m":feature(frequency="60m",minute=45)},
        pos=upgraded.position)
    assert not later.upgraded


def test_mapping_frequency_mismatch_cannot_jump_holding_levels():
    mismatched = {"30m":feature(frequency="1w", minute=25)}
    assert not run(base=feature(close="109"), higher=mismatched, pos=position(earned_r=True)).upgraded
    assert run(higher=mismatched,pos=position(holding_frequency="30m",upgrades=1)).reason == "INPUT_UNAVAILABLE"
    assert run(Variant.TEST3, feature(close="91",regime=0), mismatched).reason == "INPUT_UNAVAILABLE"


def test_daily_mapping_frequency_mismatch_cannot_qualify_overnight():
    p = position(holding_frequency="60m",earned_r=True,upgrades=2)
    higher = {"60m":feature(frequency="60m",minute=20),
              "1d":feature(frequency="1w",minute=25,regime=0)}
    assert not run(higher=higher,pos=p).position.overnight_eligible


@pytest.mark.parametrize("missing", ["ma35","ma45","ma45_prev3","high11","low11"])
def test_main_rise_missing_required_window_is_unavailable_not_flat(missing):
    assert run(Variant.MAIN_RISE,feature(**{missing:None})).reason == "INPUT_UNAVAILABLE"


def test_test3_missing_next_level_is_unavailable_but_neutral_and_opposite_are_known():
    f = feature(close="91",regime=0)
    assert run(Variant.TEST3,f).reason == "INPUT_UNAVAILABLE"
    for regime in (0,-1):
        assert run(Variant.TEST3,f,{"30m":feature(frequency="30m",minute=25,regime=regime)}).reason == "NO_ENTRY"


def test_weekly_test3_is_explicitly_not_applicable():
    f = feature(close="91",regime=0,frequency="1w")
    result = evaluate(Profile(Variant.TEST3,"1w"),f,{},None,tick=D("0.5"))
    assert result.action == "WAIT" and result.reason == "NOT_APPLICABLE"


def test_weekly_test3_stays_not_applicable_during_indicator_warmup():
    f = feature(frequency="1w",regime=None,atr=None)
    result = evaluate(Profile(Variant.TEST3,"1w"),f,{},None,tick=D("0.5"))
    assert result.reason == "NOT_APPLICABLE"


def test_decision_is_independent_of_callers_decimal_context():
    from decimal import Inexact, ROUND_DOWN, Rounded, localcontext

    f = feature(atr=D("2.123456789123456789"))
    expected = run(base=f)
    with localcontext() as caller:
        caller.prec = 5
        caller.rounding = ROUND_DOWN
        caller.traps[Inexact] = True
        caller.traps[Rounded] = True
        actual = run(base=f)
        assert caller.prec == 5 and caller.rounding == ROUND_DOWN
        assert caller.traps[Inexact] and caller.traps[Rounded]
    assert actual == expected
