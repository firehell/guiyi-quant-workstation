from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.paper.matrix import run_matrix_cell
from guiyi_quant.newow.research_backtest import BacktestAction, BacktestIntent
from guiyi_quant.paper import FeeSchedule, ObserveExecutionBar, PaperProfile, command_from_dict, command_to_dict, Initialize


START = datetime(2026, 9, 28, 1, tzinfo=UTC)


def case(monkeypatch, frequency="5m"):
    fees = FeeSchedule(D("0.0001"), D(0), D("0.0001"), D(0), D("0.0002"), D(0), "facts")
    bars = tuple(ObserveExecutionBar(str(i), START+timedelta(minutes=i+1), "2026-09-28", "JM2701",
        START+timedelta(minutes=i), START+timedelta(minutes=i+1), True,
        D(1000), D(1010), D(950), D(1000), 20, True, D(1500), D(500), D("0.5"), 1,
        D(60), fees, D(10000), f"market{i}", "cost", "limit", "margin") for i in range(15))
    ends = (bars[4].bar_end, bars[9].bar_end)
    source = SimpleNamespace(frequency=frequency, input_sha256="a"*64, replay_segments=(),
        bars=tuple(SimpleNamespace(bar_end=end, physical_contract="JM2701", trading_day=date(2026,9,28)) for end in ends))
    intents = tuple(BacktestIntent(action, end, "newow_trend_causal_target_v1")
                    for action, end in zip((BacktestAction.BUILD, BacktestAction.CLEAR), ends))
    monkeypatch.setattr("app.paper.matrix.build_causal_matrix_intents", lambda *_: (intents, ("newow_trend_causal_target_v1",)))
    return source, bars


@pytest.mark.parametrize("frequency", ["5m", "15m", "30m", "60m", "1d", "1w"])
def test_fixed_profile_all_six_frequencies_roundtrip(frequency):
    profile = PaperProfile("research-matrix", "signal-v1", frequency=frequency)
    command = Initialize("init", START, profile)
    assert command_from_dict(command_to_dict(command)) == command
    with pytest.raises(ValueError):
        replace(profile, daily_loss_fraction=D("0.03"))


def test_new_frequency_uses_same_next_minute_and_sourced_fees(monkeypatch):
    source, bars = case(monkeypatch, "1d")
    result = run_matrix_cell(source, bars, "b"*64, "c"*64, "trend")
    assert result["status"] == "COMPLETE" and result["annual_eligible"]
    assert result["closed_trades"] == 1 and result["fill_count"] == 2
    # 1000.5 entry, 999.5 exit, fees 6.003+11.994. No signal-close fill.
    assert D(result["equity"]) == D("49922.003")
    stress = run_matrix_cell(source, bars, "b"*64, "c"*64, "trend", scenario="double_commission")
    assert D(stress["fees_paid"]) == D(result["fees_paid"])*2
    assert stress["run_hash"] != result["run_hash"]


def test_rollover_keeps_old_valuation_and_excludes_annual_ranking(monkeypatch):
    source, bars = case(monkeypatch)
    bars = bars[:8] + tuple(replace(b, physical_contract="JM2705", open=D(1400), close=D(1400), high=D(1400)) for b in bars[8:])
    # Only the first completed signal is from the old contract.
    source.bars = source.bars[:1]
    result = run_matrix_cell(source, bars, "b"*64, "c"*64, "trend")
    assert result["status"] == "PAPER_ROLLOVER_INTERRUPTED" and not result["annual_eligible"]
    assert result["position_contract"] == "JM2701" and result["position_qty"] == 1
    assert result["valuation_at"] == bars[7].bar_end.isoformat()
    assert D(result["equity"]) < D(50000)


def test_owner_diagnostic_is_not_continuous_year(monkeypatch):
    source, bars = case(monkeypatch)
    result = run_matrix_cell(source, bars, "b"*64, "c"*64, "trend", physical_contract="JM2701")
    assert result["scope"] == "independent_physical_segment" and not result["annual_eligible"]


def test_missing_signal_endpoint_fails_instead_of_early_fill(monkeypatch):
    source, bars = case(monkeypatch, "1w")
    with pytest.raises(ValueError, match="MATRIX_SIGNAL_EXECUTION_ALIGNMENT_FAILED"):
        run_matrix_cell(source, bars[:4] + bars[5:], "b"*64, "c"*64, "trend")


def test_zero_volume_has_no_fake_trade_or_rank(monkeypatch):
    source, bars = case(monkeypatch)
    result = run_matrix_cell(source, tuple(replace(b, volume=0) for b in bars), "b"*64, "c"*64, "trend")
    assert result["closed_trades"] == 0 and not result["annual_eligible"]
