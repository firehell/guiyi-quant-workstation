from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from guiyi_quant.newow_futures.contracts import Bar
from guiyi_quant.newow_futures.features import prepare_features

T = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)


def bar(i, *, owner="a", close=None, frequency="5m"):
    c = D(close) if close is not None else D(100 + i)
    at = T + timedelta(minutes=5 * i)
    return Bar("jm", "JM2605", frequency, at, date(2026, 1, 5), c, c + 1, c - 1,
               c, D(10), f"{owner}:{i}", at, owner_segment_id=owner,
               calculation_segment_id=owner)


def test_complete_windows_exclude_current_breakout_and_channel_bar():
    rows = [bar(i) for i in range(50)]
    fs = prepare_features({"5m": rows}).series("5m", "JM2605")
    assert fs[19].atr is None
    assert fs[20].atr == D(2)
    assert fs[20].fast == D(117)
    assert fs[20].slow == D("115.5")
    assert fs[20].slow_prev3 == D("112.5")
    assert fs[20].upper == D(120)
    assert fs[20].lower == D(109)
    assert fs[20].high3 == D(120)
    assert fs[20].low3 == D(116)
    assert fs[20].regime == 1
    assert fs[47].ma45_prev3 == sum(D(100 + i) for i in range(45)) / 45


def test_prefix_invariance_and_short_symmetry():
    rows = [bar(i, close=200 - i) for i in range(60)]
    full = prepare_features({"5m": rows}).series("5m", "JM2605")
    for n in (21, 30, 48):
        assert prepare_features({"5m": rows[:n]}).series("5m", "JM2605") == full[:n]
    assert full[-1].regime == -1


def test_owner_boundaries_restart_warmup_and_ambiguous_lookup_is_explicit():
    rows = [bar(i) for i in range(25)] + [bar(i, owner="b") for i in range(25, 50)]
    prepared = prepare_features({"5m": rows})
    assert prepared.series("5m", "JM2605")[25].atr is None
    with pytest.raises(ValueError, match="FUTURES_OWNER_AMBIGUOUS"):
        prepared.at("5m", "JM2605", rows[-1].bar_end + timedelta(seconds=1))
    f = prepared.at("5m", "JM2605", rows[-1].bar_end + timedelta(seconds=1), owner=rows[-1].owner)
    assert f.bar == rows[-1]


def test_lookup_requires_both_bar_end_and_confirmation_strictly_before():
    rows = [bar(i) for i in range(22)]
    rows[-1] = replace(rows[-1], confirmed_at=rows[-1].bar_end + timedelta(seconds=10))
    prepared = prepare_features({"5m": rows})
    assert prepared.at("5m", "JM2605", rows[-1].bar_end + timedelta(seconds=5)).bar == rows[-2]
    assert prepared.at("5m", "JM2605", rows[-1].confirmed_at).bar == rows[-2]
    assert prepared.at("5m", "JM2605", rows[-1].confirmed_at, strict=False).bar == rows[-1]


def test_unknown_is_distinct_from_neutral_and_flat_atr_is_unavailable():
    rows = [bar(i, close=100) for i in range(25)]
    fs = prepare_features({"5m": rows}).series("5m", "JM2605")
    assert fs[0].regime is None
    assert fs[-1].regime == 0
    zero = [replace(x, high=x.close, low=x.close) for x in rows]
    assert prepare_features({"5m": zero}).series("5m", "JM2605")[-1].regime is None


def test_inconsistent_frequency_and_duplicate_identity_fail_closed():
    with pytest.raises(ValueError, match="FUTURES_FEATURE_FREQUENCY_MISMATCH"):
        prepare_features({"30m": [bar(0)]})
    with pytest.raises(ValueError, match="FUTURES_FEATURE_DUPLICATE_BAR"):
        prepare_features({"5m": [bar(0), bar(0)]})


def test_all_moving_averages_use_typical_price_not_close():
    rows = [replace(bar(i, close=100), high=D(106), low=D(99)) for i in range(50)]
    f = prepare_features({"5m": rows}).series("5m", "JM2605")[-1]
    expected = D(305) / 3
    assert f.fast == sum([expected] * 7) / 7
    assert f.slow == sum([expected] * 10) / 10
    assert f.ma35 == sum([expected] * 35) / 35
    assert f.ma45 == sum([expected] * 45) / 45


def test_lookup_matches_each_historical_prefix_with_future_suffix_present():
    rows = [bar(i) for i in range(100)]
    prepared = prepare_features({"5m": rows})
    for i in range(1, len(rows)):
        full = prepared.at("5m", "JM2605", rows[i].bar_end)
        prefix = prepare_features({"5m": rows[:i]}).series("5m", "JM2605")[-1]
        assert full == prefix


@pytest.mark.parametrize("field", ["owner_segment_id", "calculation_segment_id"])
@pytest.mark.parametrize("invalid", ["", " "])
def test_bar_rejects_missing_owner_or_calculation_segment_before_features(field, invalid):
    with pytest.raises(ValueError, match="FUTURES_BAR_IDENTITY_INVALID"):
        replace(bar(0), **{field: invalid})


def test_feature_result_is_independent_of_callers_decimal_context():
    from decimal import Inexact, ROUND_DOWN, Rounded, localcontext

    rows = [replace(bar(i, close=100), high=D(106), low=D(99)) for i in range(50)]
    expected = prepare_features({"5m":rows}).series("5m", "JM2605")
    with localcontext() as caller:
        caller.prec = 5
        caller.rounding = ROUND_DOWN
        caller.traps[Inexact] = True
        caller.traps[Rounded] = True
        actual = prepare_features({"5m":rows}).series("5m", "JM2605")
        assert caller.prec == 5 and caller.rounding == ROUND_DOWN
        assert caller.traps[Inexact] and caller.traps[Rounded]
    assert actual == expected
