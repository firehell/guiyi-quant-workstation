from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.paper.history import build_historical_plan, execution_command
from guiyi_quant.newow.research_backtest import (
    BacktestAction, BacktestIntent, DUAL_FUSION_CAUSAL_SIGNAL_VERSION,
    NewowResearchBar,
)
from guiyi_quant.paper import apply_command, apply_events


D = Decimal
START = datetime(2026, 9, 28, 1, tzinfo=UTC)
DAY = date(2026, 9, 28)


def fixture_input():
    minutes = tuple(NewowResearchBar(
        product="jm", physical_contract="JM2701", segment_id="segment1", trading_day=DAY,
        bar_end=START+timedelta(minutes=i), open=D("1000"), high=D("1001"), low=D("999"), close=D("1000"),
        volume=10, open_interest=100, source_identity=f"canonical:{i}",
        observation_eligible=True, completed=True, frequency="1m",
    ) for i in range(1, 16))
    signals = tuple(replace(minutes[i-1], frequency="5m") for i in (5, 10, 15))
    source = SimpleNamespace(bars=signals, input_sha256="a"*64)
    raw = {"schema_version": 1, "source": "rqdata", "plan_hash": "b"*64,
           "captured_at": "2026-10-11T14:47:35+00:00", "contracts": {
        "JM2701": {"instrument": {"contract_multiplier": "60", "tick_size": "0.5"},
                   "parameters": [{"date": DAY.isoformat(), "commission_type": "by_money",
                                   "open_commission": "0.0001", "close_commission": "0.0001",
                                   "close_commission_today": "0.0002", "long_margin_ratio": "0.12"}],
                   "daily": [{"date": DAY.isoformat(), "limit_up": "2000", "limit_down": "100",
                              "prev_settlement": "1000", "settlement": "1900"}]}}}
    intents = (BacktestIntent(BacktestAction.BUILD, signals[0].bar_end, DUAL_FUSION_CAUSAL_SIGNAL_VERSION),
               BacktestIntent(BacktestAction.CLEAR, signals[1].bar_end, DUAL_FUSION_CAUSAL_SIGNAL_VERSION))
    return source, minutes, raw, intents


def final_state(plan):
    state = None
    for command in plan.commands:
        state = apply_events(state, apply_command(state, command))
    return state


def test_completed_5m_signal_fills_only_strictly_later_physical_1m_open():
    source, minutes, raw, intents = fixture_input()
    plan = build_historical_plan(source, minutes, raw, intents=intents)
    state = final_state(plan)
    assert len(state.fills) == 2
    assert state.fills[0].fill_at == START+timedelta(minutes=6)
    assert state.fills[0].price == D("1000.5")
    assert state.fills[1].fill_at == START+timedelta(minutes=11)
    assert state.fills[1].price == D("999.5")
    assert state.fills[1].fee == D("11.994")
    assert state.cash == D("49922.003")
    assert plan.expected_summary["live_or_oos_evidence"] is False


def test_source_identity_and_restarts_are_deterministic():
    source, minutes, raw, intents = fixture_input()
    first = build_historical_plan(source, minutes, raw, intents=intents)
    second = build_historical_plan(source, minutes, raw, intents=intents)
    assert first == second
    raw["captured_at"] = "2026-10-11T15:00:00+00:00"
    changed = build_historical_plan(source, minutes, raw, intents=intents)
    assert changed.run_hash != first.run_hash
    assert changed.commands[0].command_id == first.commands[0].command_id == "initialize"
    assert changed.commands[0].profile != first.commands[0].profile


def test_margin_uses_previous_settlement_never_future_daily_close():
    _, minutes, raw, _ = fixture_input()
    command = execution_command(minutes[0], raw, "hash")
    assert command.margin_per_contract == D("7200")
    raw["contracts"]["JM2701"]["daily"][0]["settlement"] = "999999"
    assert execution_command(minutes[0], raw, "hash").margin_per_contract == command.margin_per_contract


@pytest.mark.parametrize("change", ["missing_day", "duplicate_day", "unknown_commission", "missing_limit", "five_minute"])
def test_execution_facts_and_frequency_fail_closed(change):
    _, minutes, raw, _ = fixture_input()
    bar = minutes[0]
    body = raw["contracts"]["JM2701"]
    if change == "missing_day":
        body["parameters"] = []
    elif change == "duplicate_day":
        body["daily"] *= 2
    elif change == "unknown_commission":
        body["parameters"][0]["commission_type"] = "guess"
    elif change == "missing_limit":
        del body["daily"][0]["limit_up"]
    else:
        bar = replace(bar, frequency="5m")
    with pytest.raises(ValueError):
        execution_command(bar, raw, "hash")


def test_signal_and_execution_contract_mismatch_rejected_before_writes():
    source, minutes, raw, intents = fixture_input()
    minutes = tuple(replace(b, physical_contract="JM2609") if b.bar_end == source.bars[0].bar_end else b for b in minutes)
    with pytest.raises(ValueError, match="PAPER_SIGNAL_EXECUTION_ALIGNMENT_FAILED"):
        build_historical_plan(source, minutes, raw, intents=intents)


def test_clear_cancels_unfilled_open_with_distinct_simulator_ack():
    source, minutes, raw, intents = fixture_input()
    minutes = tuple(replace(b, volume=0) if b.bar_end <= START+timedelta(minutes=10) else b for b in minutes)
    plan = build_historical_plan(source, minutes, raw, intents=intents)
    state = final_state(plan)
    assert state.fills == ()
    assert state.position_qty == 0
    assert len(state.orders) == 1 and state.orders[0].status == "CANCELLED"
    assert any(c.__class__.__name__ == "ResolveOrder" for c in plan.commands)


def test_daily_loss_stop_closes_on_future_bar_and_does_not_reopen():
    source, minutes, raw, intents = fixture_input()
    minutes = tuple(replace(b, open=D("970"), high=D("971"), low=D("969"), close=D("970"))
                    if b.bar_end >= START+timedelta(minutes=8) else b for b in minutes)
    source.bars = tuple(replace(minutes[i-1], frequency="5m") for i in (5, 10, 15))
    intents = (intents[0], BacktestIntent(BacktestAction.BUILD, source.bars[1].bar_end, DUAL_FUSION_CAUSAL_SIGNAL_VERSION))
    state = final_state(build_historical_plan(source, minutes, raw, intents=intents))
    assert state.daily_halt and state.position_qty == 0
    assert len(state.fills) == 2
    assert state.fills[1].fill_at == START+timedelta(minutes=9)
    assert state.equity < D("49000")  # A gap may overshoot the threshold.


@pytest.mark.parametrize("url", [None, "postgresql+psycopg://postgres:secret-not-for-logs@remote.example:15462/guiyi_paper_demo"])
def test_cli_requires_explicit_isolated_database_and_sanitizes_errors(url):
    env = dict(os.environ)
    env.pop("GUIYI_PAPER_DATABASE_URL", None)
    env["DATABASE_URL"] = "postgresql+psycopg://postgres:production-secret@localhost:5432/guiyi"
    if url is not None:
        env["GUIYI_PAPER_DATABASE_URL"] = url
    result = subprocess.run([sys.executable, "scripts/research/jm_paper.py", "init"],
                            env=env, cwd=Path(__file__).resolve().parents[4],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "BLOCKED"
    assert "secret" not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
