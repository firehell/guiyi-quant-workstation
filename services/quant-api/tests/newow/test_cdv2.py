from itertools import product
import pytest
from guiyi_quant.newow.composite_decision_v2 import compute_cdv2


def states(values):
    return dict(zip(("week", "day", "m60"), values))


def test_all_bearish_clear_is_high_confidence_with_zero_long_exposure():
    r = compute_cdv2(states(("sell",) * 3), states(("sell",) * 3))
    assert r["resonance"] == "R4" and r["total"] == 100
    assert r["reference_exposure_cap"] == 0 and r["bearish_gated"]


def test_r4_requires_only_two_explicit_cycles():
    r = compute_cdv2(states(("hold", "hold", None)), states(("hold", "hold", None)))
    assert r["resonance"] == "R4"
    assert r["total"] == 78 and r["reference_exposure_cap"] == 50


@pytest.mark.parametrize(
    "trend,osc,age,cross,mm",
    [
        (("hold", "hold", None), ("wait", "wait", None), 3, None, "MM1"),
        ((None, "wait", None), ("hold", "hold", None), 3, None, "MM2"),
        (
            ("wait", "wait", None),
            ("hold", "hold", None),
            0,
            {"type": "sell", "bars_ago": 2},
            "MM3",
        ),
        (
            ("hold", "hold", None),
            ("wait", "wait", None),
            0,
            {"type": "buy", "bars_ago": 0},
            "MM4",
        ),
        (("wait", "wait", None), ("hold", "hold", None), 3, None, None),
    ],
)
def test_mismatch_priority(trend, osc, age, cross, mm):
    r = compute_cdv2(states(trend), states(osc), osc_age=age, cross=cross)
    assert r["mismatch"] == mm
    if mm:
        assert r["exempt"] and r["reference_exposure_cap"] <= 30


def test_missing_age_is_not_zero_and_extra_is_visible():
    r = compute_cdv2(
        states(("hold",) * 3),
        states(("hold",) * 3),
        volatility="high",
        j_reduce=True,
        care=True,
        tent=True,
    )
    assert r["oscillation_age"] == -1
    assert r["scores"]["volatility"] == -8 and r["cert_extra"] == -11
    assert r["total"] == sum(r["scores"].values()) + sum(r["deductions"].values()) == 81
    assert r["executable"] is False and r["explanation_only"]


def test_state_cube_is_total_and_never_executable():
    for t in product(("hold", "wait", None), repeat=3):
        for o in product(("hold", "wait", None), repeat=3):
            r = compute_cdv2(states(t), states(o))
            assert 0 <= r["total"] <= 100
            assert r["resonance"] in ("R0", "R1", "R2", "R3", "R4")
            assert r["reference_exposure_cap"] in (0, 10, 30, 50, 60, 100)
            assert not r["executable"]
