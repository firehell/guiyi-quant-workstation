"""Causal and reconciliation boundaries for the sealed two-bar experiment."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from guiyi_quant import lms_near405 as kernel
from lms405_regime_confirmation_study import (
    confirmed_invalidation,
    continuous_attribution,
    delayed_replay,
    label_operations,
)
from lms_near405_backtest import execute_reference
from test_near405 import bar, entry_bars, until

D = Decimal
T = datetime(2026, 1, 5, 1, tzinfo=UTC)


def held(side="LONG", created=7):
    return dict(original_side=side, entry_index=7, cycle_seq=1,
                plan=dict(environment="RANGE", lower="100", upper="110", created_index=created))


def set_environment(monkeypatch, sequence):
    monkeypatch.setattr(kernel, "context", lambda bars, i: {"environment": sequence.get(i, "RANGE")}
                        if i >= 7 else None)


@pytest.mark.parametrize(("side", "opposite"), [("LONG", "DOWN"), ("SHORT", "UP")])
def test_opposition_must_persist_into_next_completed_bar(monkeypatch, side, opposite):
    sequence = {7: opposite, 8: opposite, 10: opposite, 11: opposite}
    set_environment(monkeypatch, sequence)
    bars = [SimpleNamespace(close=D(105)) for _ in range(12)]
    assert kernel._invalid(held(side), bars[:9], 8, None) == "REGIME_INVALID"
    assert [confirmed_invalidation(held(side), bars[:i + 1], i, None) for i in range(8, 12)] == [
        None, None, None, "REGIME_INVALID",
    ]
    assert confirmed_invalidation(held(side), bars, 11, None, activation=11) == "REGIME_INVALID"
    assert confirmed_invalidation(held(side), bars, 11, None, activation=10) == "REGIME_INVALID"
    # A later local fork preserves already visible baseline exits before its activation.
    assert confirmed_invalidation(held(side), bars, 11, None, activation=12) == "REGIME_INVALID"


@pytest.mark.parametrize(("price", "created", "expected"), [
    (99, 7, "RISK_INVALID"), (111, 7, "RANGE_TARGET"), (105, -4, "PLAN_EXPIRED"),
])
def test_other_exits_can_fire_on_the_first_opposing_bar(monkeypatch, price, created, expected):
    set_environment(monkeypatch, {8: "DOWN"})
    bars = [SimpleNamespace(close=D(105)) for _ in range(8)] + [SimpleNamespace(close=D(price))]
    assert confirmed_invalidation(held(created=created), bars, 8, None) == expected


def test_shared_prefix_then_delayed_exit_and_no_global_change(monkeypatch):
    original = kernel.context
    monkeypatch.setattr(
        kernel, "context", lambda bars, i: original(bars, i) | {"environment": "DOWN"}
        if i >= 8 else original(bars, i),
    )
    bars = entry_bars() + [bar(i, 106, 107, 104, 106) for i in range(8, 10)]
    baseline = kernel.replay(bars, as_of=until(bars), timely_fixture=True)
    partial = delayed_replay(bars, until(bars[:9]))
    candidate = delayed_replay(bars, until(bars))
    assert partial == delayed_replay(bars[:9], until(bars[:9]))
    assert partial["transitions"] == candidate["transitions"][:1] == baseline["transitions"][:1]
    assert baseline["transitions"][-1]["reason"] == candidate["transitions"][-1]["reason"] == "REGIME_INVALID"
    assert baseline["transitions"][-1]["known_at"] < candidate["transitions"][-1]["known_at"]
    assert kernel.replay(bars, as_of=until(bars), timely_fixture=True) == baseline


def minute(i, price):
    return dict(contract="JM2701", trading_day="2026-01-05", bar_end=(T + timedelta(minutes=i + 1)).isoformat(),
                open=str(price), high=str(price + 1), low=str(price - 1), close=str(price), volume="100")


def intent(i, long, short, cycle):
    return dict(known_at=(T + timedelta(minutes=i, microseconds=2)).isoformat(),
                after=dict(long=str(long), short=str(short), cycle_id=cycle if long + short else None))


def test_continuous_tracks_exclusive_opportunities_and_terminal_mtm():
    bars = [minute(i, 100 + i) for i in range(10)]
    baseline = execute_reference(
        bars, [intent(1, 1, 0, "b1"), intent(3, 0, 0, "b1"), intent(5, 1, 0, "b2")],
        D(10), D(1), D(3), 1,
    )
    candidate = execute_reference(
        bars, [intent(1, 1, 0, "c1"), intent(4, 0, 0, "c1")], D(10), D(1), D(3), 1,
    )
    episodes, ops = continuous_attribution("test-window", "JM2701", baseline, candidate)
    assert len(ops) == 5
    assert [r["status"] for r in episodes] == ["COMMON_FLAT", "TERMINAL_MARKED"]
    assert episodes[0]["net"] == 10 and episodes[1]["baseline_only_open"] == 1
    assert sum(r["net"] for r in episodes) == D(candidate["net_pnl"]) - D(baseline["net_pnl"])
    shared = [r for r in ops if r["shared"]]
    assert len(shared) == 2 and not any(r["segment"] for r in shared)


def test_delayed_original_open_under_lock_keeps_its_role():
    lock = dict(known_at="known", action="LOCK", reason="OPPOSING_KEYBAR", decision_id="decision",
                proposal_id="proposal", after={"original_side": "LONG"})
    ledger = [
        dict(window="test-window", contract="JM2701", path="baseline", segment=1,
             side=side, shared=False, offset="OPEN", decision_known_at="known")
        for side in ("long", "short")
    ]
    segment = dict(window="test-window", contract="JM2701", segment=1, baseline_only_open=2, candidate_only_open=0)
    label_operations(ledger, [segment], {"transitions": [lock]}, {"transitions": []})
    assert segment["baseline_only_original_open"] == segment["baseline_only_protection_open"] == 1
    assert all(row["decision_id"] == "decision" for row in ledger)
