import importlib.util
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location(
    "four_unity_signals", ROOT / "scripts/research/four_unity_signals.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def bars(n):
    from datetime import date, timedelta

    return [
        dict(
            date=str(date(2020, 1, 1) + timedelta(days=i)),
            open=100 + i % 9,
            close=101 + i % 9,
            high=104 + i % 9,
            low=98 + i % 9,
            volume=10000,
        )
        for i in range(n)
    ]


def test_filter_suppresses_exact_following_bars():
    assert m.filter_signal(np.ones(13, dtype=bool), 5).tolist() == [
        True,
        False,
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
        True,
    ]


def test_cross_requires_strict_current_and_previous_lte():
    assert m.cross(np.array([1.0, 1.75, 2.0, 2.0, 1.0, 2.0]), 1.75).tolist() == [
        False,
        False,
        True,
        False,
        False,
        True,
    ]


def test_zero_denominator_is_not_fabricated_zero():
    assert np.isnan(m.divide(np.array([1.0]), np.array([0.0]))[0])
    flat = [
        dict(date=b["date"], open=1, high=1, low=1, close=1, volume=0)
        for b in bars(105)
    ]
    result = m.compute_signals(flat)
    assert not any(any(r["ready"].values()) for r in result["realtime"])
    assert not any(any(r["entries"].values()) for r in result["realtime"])


def test_prefix_invariance_and_batch_incremental_endpoint_parity():
    data = bars(110)
    full = m.compute_signals(data)
    short = m.compute_signals(data[:105])
    for a, b in zip(full["realtime"][:105], short["realtime"]):
        assert a["entries"] == b["entries"] and a["exit"] == b["exit"]
        assert a["conditions"] == b["conditions"]
    assert full["realtime"][-1] == full["final_chart"][-1]
    assert full["realtime"][-1]["ready"]["pullback"] is False
    assert (
        "XMA6_EXTERNAL_ORACLE_UNRESOLVED"
        in full["realtime"][-1]["block_reasons"]["pullback"]
    )


def test_duplicate_dates_and_invalid_prices_rejected():
    with pytest.raises(ValueError):
        m.compute_signals(bars(1) * 2)
    bad = bars(1)
    bad[0]["high"] = 0
    with pytest.raises(ValueError):
        m.compute_signals(bad)


def test_fly_hand_calculated_ema():
    data = [
        dict(date=f"2020-01-0{i + 1}", open=10, high=14, low=6, close=c, volume=100)
        for i, c in enumerate((8, 10, 12))
    ]
    # Raw oscillator = 1,2,3; EMA4 alpha=.4 => 1,1.4,2.04.
    assert [
        r["conditions"]["fly_value"] for r in m.compute_signals(data)["realtime"]
    ] == pytest.approx([1, 1.4, 2.04])


def test_dsq_escape_conditions_and_ten_bar_suppression_hand_fixture():
    close = np.array(
        [100.0] * 13 + [90.0, 91.0, 90.0, 91.0] + [100.0] * 7 + [90.0, 91.0]
    )
    a4 = np.full(len(close), 20.0)
    b1 = np.full(len(close), 19.5)
    bottom, top = m._dsq_escape_signals(a4, b1, close)
    # Rising closes 14,16,25 are still below MA13*.996; 16 is suppressed.
    assert np.flatnonzero(bottom).tolist() == [14, 25]
    assert not top.any()
    close = np.array([100.0] * 13 + [110.0, 109.0, 110.0, 109.0])
    bottom, top = m._dsq_escape_signals(np.full(17, 80.0), np.full(17, 79.0), close)
    assert np.flatnonzero(top).tolist() == [14]
    assert not bottom.any()


def test_capital_zero_ddx_sma_and_last_bar_dy_hand_fixture():
    o = np.array([10.0, 10.0, 10.0])
    h = np.full(3, 14.0)
    low = np.full(3, 6.0)
    c = np.array([12.0, 10.0, 9.0])
    v = np.full(3, 12000.0)
    ddx, v2, dy2 = m._capital_zero_funds(o, h, low, c, v)
    # Q0=1500, DDX=Q0*(2*C-H-L)/3/10000 => .2,0,-.1.
    # First REF is undefined: IF(C>=REF(C),DDX,-DDX/100) seeds -.002.
    # SMA2 recursively gives -.002,-.001,0; only last DY is one.
    assert ddx == pytest.approx([0.2, 0, -0.1])
    assert v2 == pytest.approx([-0.002, -0.001, 0])
    assert np.isnan(dy2[0])
    assert dy2[1:] == pytest.approx([-0.002, -1.001])
    # Earlier declining bar DY stays zero in final-chart evaluation.
    assert dy2[1] > -0.01


def test_third_candle_fires_once_and_xma_repaints():
    from guiyi_quant.indicators.htdy_original import _new_third_consecutive

    flags = np.array([False, True, True, True, True, False, True, True, True])
    assert np.flatnonzero(_new_third_consecutive(flags)).tolist() == [3, 8]
    # A new extreme bar changes prior centered-channel values, whereas stored
    # realtime endpoints retain their old value when later bars arrive.
    data = bars(20)
    result = m.compute_signals(data)
    assert any(
        a["conditions"]["zd1"] != b["conditions"]["zd1"]
        for a, b in zip(result["realtime"][:-1], result["final_chart"][:-1])
    )


def test_nonpositive_price_rejected_and_refdate_oracle_disclosed():
    data = bars(1)
    data[0]["low"] = 0
    with pytest.raises(ValueError, match="OHLCV"):
        m.compute_signals(data)
    assert m.compute_signals([])["metadata"]["refdate_oracle_status"].startswith(
        "externally_unresolved"
    )
