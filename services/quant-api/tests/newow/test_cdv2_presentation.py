from copy import deepcopy

import pytest

from guiyi_quant.newow.composite_decision_v2 import compute_cdv2
from guiyi_quant.newow.composite_decision_presentation import describe_daily_weekly_cdv2


def decision(t, o, **kwargs):
    trend = dict(zip(("week", "day"), t))
    osc = dict(zip(("week", "day"), o))
    cd = compute_cdv2(trend, osc, **kwargs)
    return cd, describe_daily_weekly_cdv2(cd, trend, osc)


@pytest.mark.parametrize(
    "t,o,token,level",
    [
        (("wait", "wait"), ("hold", "hold"), "weekly_daily_bearish_hard_flat", "violate"),
        (("wait", "hold"), ("hold", "hold"), "weekly_bearish_daily_bullish_rebound_risk", "warn"),
        (("hold", "wait"), ("hold", "hold"), "weekly_bullish_daily_bearish_wait_for_daily_stability", "warn"),
        ((None, "wait"), (None, None), "single_bearish_unknown_counterpart_hard_flat", "violate"),
        (("hold", "hold"), ("hold", "wait"), "daily_oscillation_cleared", "warn"),
        (("hold", "hold"), ("wait", "hold"), "weekly_oscillation_cleared", "warn"),
        (("hold", "hold"), ("hold", "hold"), "normal_observation", "ok"),
        ((None, "hold"), ("hold", "hold"), "daily_weekly_inputs_missing", "unknown"),
        (("hold", "hold"), (None, "hold"), "daily_weekly_inputs_missing", "unknown"),
    ],
)
def test_first_action_reuses_existing_priority_without_hourly(t, o, token, level):
    cd, view = decision(t, o)
    first = view["first_action"]
    assert first["rule_token"] == token
    assert first["level"] == level
    assert view["scope"] == "daily_weekly"
    assert "60min" not in first["title"] + first["detail"]
    assert "持股" not in first["title"] + first["detail"]
    assert "大盘" not in first["title"] + first["detail"]
    assert cd["executable"] is False


def test_existing_cdv2_scores_action_and_exposure_are_not_rewritten():
    t = {"week": "hold", "day": "hold"}
    o = {"week": "hold", "day": "hold"}
    cd = compute_cdv2(t, o)
    original = deepcopy(cd)
    view = describe_daily_weekly_cdv2(cd, t, o)
    assert cd == original
    assert cd["total"] == 78
    assert cd["scores"] == {"trend": 24, "oscillation": 22, "resonance": 20, "direction": 12, "volatility": 0}
    assert view["first_action"]["source_formula_version"].startswith("newow_first_action_principle_")


@pytest.mark.parametrize("cross,mm", [({"type": "sell", "bars_ago": 0}, "MM3"), ({"type": "buy", "bars_ago": 2}, "MM4")])
def test_mismatch_advice_uses_real_daily_age(cross, mm):
    cd, view = decision(("wait", "wait") if mm == "MM3" else ("hold", "hold"), ("hold", "hold") if mm == "MM3" else ("wait", "wait"), cross=cross)
    assert cd["mismatch"] == mm
    assert ("最新一根" if cross["bars_ago"] == 0 else "2 根日K前") in view["advice"]
    assert "N 根前" not in view["advice"]


def test_reference_exposure_is_authoritative_in_first_action_copy():
    cd, view = decision(("wait", "hold"), ("hold", "hold"))
    assert cd["reference_exposure_cap"] == 10
    assert "0%–10%" in view["first_action"]["detail"]
    assert "≤30%" not in view["first_action"]["detail"]


def test_missing_and_high_volatility_advice_stay_explanatory():
    cd, view = decision((None, None), (None, None))
    assert cd["action"] == "等待信号"
    assert "等待" in view["advice"]
    cd, view = decision(("hold", "hold"), ("hold", "hold"), volatility="high")
    assert "波动率偏高" in view["advice"]
    assert cd["scores"]["volatility"] == -8


def test_hourly_first_action_and_missing_input_are_not_confirmation():
    from guiyi_quant.newow.composite_decision_presentation import describe_hourly_cdv2
    t = {"week": "hold", "day": "hold", "m60": "hold"}
    o = {"week": "hold", "day": "hold", "m60": "wait"}
    cd = compute_cdv2(t, o)
    view = describe_hourly_cdv2(cd, t, o)
    assert view["scope"] == "daily_weekly_hourly"
    assert view["first_action"]["level"] == "warn"
    o["m60"] = None
    view = describe_hourly_cdv2(compute_cdv2(t, o), t, o)
    assert view["first_action"]["level"] == "unknown"
