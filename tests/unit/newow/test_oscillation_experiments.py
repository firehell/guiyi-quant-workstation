import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from dataclasses import asdict
import pytest
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.oscillation_experiments import (
    ExperimentKind,
    calculate_experiment_series,
    step_experiment,
    restore_experiment_state,
    run_experiment_reference,
    run_base_oscillation_ideal,
)


def bar(i, o=100, h=110, low=100, c=105, segment="a"):
    t = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)
    return NewowDailyBar(
        "rb",
        "RB2605",
        segment,
        t.date(),
        t,
        *map(lambda x: D(str(x)), (o, h, low, c)),
        100,
        None,
        "test",
        True,
        True,
    )


def test_stop_priority_gap_and_no_reentry():
    bars = tuple(bar(i) for i in range(10)) + (bar(10, 90, 120, 85, 100),)
    result = calculate_experiment_series(bars, ExperimentKind.TEST1)
    assert not any(x.signals for x in result[:9])
    s = result[-1].signals
    assert len(s) == 1 and s[0].stop_loss and s[0].price == D(90)
    assert s[0].score == 0 and s[0].break_label is None


def test_ordinary_hhv_reentry_is_distinct_from_markers():
    bars = tuple(bar(i) for i in range(11))
    assert len(calculate_experiment_series(bars, ExperimentKind.TEST1)[-1].signals) == 1
    normal = run_experiment_reference(bars, ExperimentKind.TEST1)
    assert normal["summary"]["trade_count"] == 2
    assert normal["trades"][-1]["force_close"] is True


def test_test4_refresh_beats_old_reference_confirmation():
    bars = tuple(bar(i) for i in range(10)) + (
        bar(10, 105, 120, 100, 115),
        bar(11, 110, 121, 100, 118),
        bar(12, 110, 119, 100, 115),
    )
    result = calculate_experiment_series(bars, ExperimentKind.TEST4)
    assert not result[10].signals and not result[11].signals
    assert result[11].state.sell_reference == D(118)
    assert result[12].signals[0].price == D(110)
    assert result[12].signals[0].confirm_exit


def test_test2_locked_target_does_not_follow_rolling_hhv():
    bars = tuple(bar(i, h=120 if i == 0 else 110) for i in range(10)) + (
        bar(10, h=115),
    )
    r = calculate_experiment_series(bars, ExperimentKind.TEST2)
    assert r[-1].state.target_price == D(120) and not r[-1].signals


def test_restart_prefix_and_segment_reset():
    bars = tuple(bar(i, h=120 if i == 0 else 110) for i in range(20))
    for kind in ExperimentKind:
        all_result = calculate_experiment_series(bars, kind)
        prefix = calculate_experiment_series(bars[:12], kind)
        assert prefix == all_result[:12]
        restored = restore_experiment_state(asdict(prefix[-1].state))
        assert step_experiment(restored, bars[12], kind) == all_result[12]
        reset = step_experiment(restored, bar(12, segment="b"), kind)
        assert not reset.signals and reset.state.history_count == 1


def test_ideal_same_bar_close_and_no_forceclose():
    bars = tuple(bar(i) for i in range(11))
    ideal = run_base_oscillation_ideal(bars)
    assert ideal["summary"]["trade_count"] == 2
    assert not any(t["force_close"] for t in ideal["trades"])


ORACLE = (
    Path(__file__).resolve().parents[3]
    / "services/quant-api/tests/newow/fixtures/oscillation-experiments-public-oracle.json"
)


@pytest.mark.parametrize(
    "case", json.loads(ORACLE.read_text())["cases"], ids=lambda c: c["name"]
)
def test_public_source_oracle(case):
    bars = tuple(
        bar(i, b["open"], b["high"], b["low"], b["close"])
        for i, b in enumerate(case["bars"])
    )
    # Volume is part of break scoring, independently supplied by frozen witness.
    from dataclasses import replace

    bars = tuple(
        replace(b, volume=case["bars"][i]["volume"]) for i, b in enumerate(bars)
    )
    for exp in case["experiments"]:
        result = calculate_experiment_series(bars, ExperimentKind(exp["kind"]))
        actual = [(i, s) for i, r in enumerate(result) for s in r.signals]
        assert len(actual) == len(exp["markers"])
        for (i, s), expected in zip(actual, exp["markers"], strict=True):
            assert bars[i].trading_day.isoformat() == expected["date"]
            assert s.action.value == ("BUILD" if expected["type"] == "buy" else "CLEAR")
            assert float(s.price) == pytest.approx(expected["price"])
            assert s.stop_loss == expected.get("stopLoss", False)
            assert s.confirm_exit == expected.get("confirmExit", False)
            assert (
                s.score == expected["score"] and s.break_label == expected["breakLabel"]
            )
        for observed, expected in [
            (
                run_experiment_reference(bars, ExperimentKind(exp["kind"])),
                exp["ordinary"],
            ),
            (run_base_oscillation_ideal(bars), case["ideal"]),
        ]:
            assert (
                observed["summary"]["trade_count"] == expected["summary"]["tradeCount"]
            )
            assert D(observed["summary"]["cum_return_percentage_points"]) == D(
                str(expected["summary"]["cumReturn"])
            )
            assert D(observed["summary"]["max_drawdown_percentage_points"]) == D(
                str(expected["summary"]["maxDrawdown"])
            )
            assert D(observed["summary"]["accuracy_pct"]) == D(
                str(expected["summary"]["accuracy"])
            )
            assert len(observed["trades"]) == len(expected["trades"])
            for actual_trade, old in zip(
                observed["trades"], expected["trades"], strict=True
            ):
                assert D(actual_trade["entry_reference_price"]) == D(
                    str(old["buyPrice"])
                )
                assert D(actual_trade["exit_reference_price"]) == D(
                    str(old["sellPrice"])
                )
                assert D(actual_trade["return_percentage_points"]) == D(str(old["pct"]))
                assert actual_trade["stop_loss"] == old.get("stopLoss", False)
                assert actual_trade["force_close"] == old["forceClose"]
            assert [D(e) for e in observed["equity"]] == [
                D(str(e)) for e in expected["equity"]
            ]


def test_ma_gate_uses_only_previous_two_bars():
    rising = tuple(
        bar(i, o=100 + i, h=120 + i, low=95 + i, c=105 + i) for i in range(9)
    )
    # The current collapse lowers today's MA but must not erase the previous rise.
    result = calculate_experiment_series(
        rising + (bar(9, o=100, h=110, low=90, c=95),), ExperimentKind.TEST3
    )
    assert result[-1].signals[0].action.value == "BUILD"
    falling = tuple(
        bar(i, o=120 - i, h=130 - i, low=110 - i, c=125 - i) for i in range(9)
    )
    result = calculate_experiment_series(
        falling + (bar(9, o=100, h=200, low=90, c=190),), ExperimentKind.TEST3
    )
    assert not result[-1].signals


def test_no_same_entry_bar_stop_and_boundary_stop_inclusive():
    bars = tuple(bar(i) for i in range(10))
    result = calculate_experiment_series(bars, ExperimentKind.TEST1)
    assert result[-1].state.holding and len(result[-1].signals) == 1
    result = step_experiment(
        result[-1].state, bar(10, o=100, h=110, low=93, c=100), ExperimentKind.TEST1
    )
    assert result.signals[0].stop_loss and result.signals[0].price == D("93.0")


def test_terminal_false_is_interrupted_not_forceclosed():
    bars = tuple(bar(i, h=120 if i == 0 else 110) for i in range(11))
    result = run_experiment_reference(
        bars, ExperimentKind.TEST2, terminal_eligible=False
    )
    assert result["summary"]["trade_count"] == 0
    result = run_experiment_reference(bars, ExperimentKind.TEST2)
    assert result["summary"]["trade_count"] == 1 and result["trades"][0]["force_close"]


def test_warmup_layers_and_no_cross_segment_reference():
    from dataclasses import replace

    bars = tuple(replace(bar(i), observation_eligible=i >= 10) for i in range(11))
    markers = calculate_experiment_series(bars, ExperimentKind.TEST1)
    assert not markers[9].signals and markers[9].state.holding
    assert markers[10].signals[0].action.value == "CLEAR"
    ordinary = run_experiment_reference(bars, ExperimentKind.TEST1)
    assert ordinary["trades"][0]["entry_index"] == 10
    with pytest.raises(ValueError, match="MIXED_SEGMENT"):
        run_experiment_reference(
            bars[:-1] + (bar(10, segment="b"),), ExperimentKind.TEST1
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"highs": (D("NaN"),)},
        {"index": True},
        {"history_count": -1},
        {"entry_price": D(100)},
        {"last_bar_end": "bad"},
    ],
)
def test_invalid_checkpoints_fail_closed(payload):
    with pytest.raises(ValueError, match="STATE_INVALID"):
        restore_experiment_state(payload)
