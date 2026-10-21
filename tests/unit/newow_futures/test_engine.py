from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from guiyi_quant.new_subing import ExecutionFacts
from guiyi_quant.paper import FeeSchedule
from guiyi_quant.newow_futures import Bar, ExecutionBar, Profile, Variant
from guiyi_quant.newow_futures.engine import run_research

T = datetime(2026, 10, 9, 0, tzinfo=timezone.utc)
DAY = date(2026, 10, 9)


def source(multiplier="10", volume="10", count=200):
    fees = FeeSchedule(D(0), D(0), D(0), D(0), D(0), D(0), "fees")
    facts = ExecutionFacts("RB2701", DAY, D(".1"), D(multiplier), D(100), D(".1"), D(".1"), D(10000), D(1), fees, "facts")
    rows = []
    for i in range(count):
        at = T + timedelta(minutes=i + 1)
        price = D(100) + D(i) / 2
        rows.append(Bar("rb", "RB2701", "1m", at, DAY, price, price + D(".2"), price - D(".2"),
                        price, D(volume), str(i), at, session_close_at=T + timedelta(hours=10),
                        owner_segment_id="owner", calculation_segment_id="calc"))
    base = []
    for i in range(4, count, 5):
        group = rows[i - 4:i + 1]
        base.append(replace(rows[i], frequency="5m", open=group[0].open,
                            high=max(x.high for x in group), low=min(x.low for x in group)))
    return {"5m": tuple(base)}, tuple(ExecutionBar(x, facts) for x in rows), {("RB2701", DAY): D(".1")}


def run(bars, executions, ticks):
    return run_research(bars, executions, profile=Profile(Variant.TREND, "5m"),
                        since=DAY, through=DAY, ticks=ticks)


def test_completed_signals_fill_only_at_strictly_later_minute_open_and_leave_terminal_open():
    bars, executions, ticks = source()
    result = run(bars, executions, ticks)
    assert result["fills"]
    first = result["fills"][0]
    entry_at = datetime.fromisoformat(first["at"])
    decision_at = datetime.fromisoformat(first["decision_at"])
    assert entry_at > decision_at
    execution = next(x for x in executions if x.bar.bar_end - timedelta(minutes=1) == entry_at)
    assert D(first["price"]) == execution.bar.open + D(".1")
    assert result["summary"]["ending_qty"] > 0
    assert result["trades"][-1]["status"] == "OPEN"
    assert not any(f["action"] == "CLOSE" for f in result["fills"])


def test_no_capital_does_not_fabricate_fills_or_suppress_reference():
    bars, executions, ticks = source(multiplier="100000")
    result = run(bars, executions, ticks)
    assert result["fills"] == []
    assert result["summary"]["status"] == "INSUFFICIENT_CAPITAL"
    assert any(d["reason"] == "MIN_LOT_BUDGET" for d in result["decisions"])
    assert result["reference"]["actions"]
    assert result["reference"]["snapshot"]["side"] == "LONG"


def test_zero_volume_records_pending_without_imaginary_fill():
    bars, executions, ticks = source(volume="0")
    result = run(bars, executions, ticks)
    assert result["fills"] == []
    assert result["summary"]["status"] == "PENDING_UNFILLED"
    assert any(d["reason"] == "ZERO_VOLUME" for d in result["decisions"])


def test_replay_prefix_does_not_change_past_fills():
    bars, executions, ticks = source()
    full = run(bars, executions, ticks)
    shorter = run({"5m": bars["5m"][:-5]}, executions[:-25], ticks)
    cutoff = executions[-26].bar.bar_end
    assert shorter["fills"] == [f for f in full["fills"] if datetime.fromisoformat(f["at"]) < cutoff]


def test_favorable_gap_can_only_shrink_or_preserve_requested_quantity():
    bars, executions, ticks = source()
    original = run(bars, executions, ticks)
    fill = original["fills"][0]
    fill_at = datetime.fromisoformat(fill["at"])
    changed = list(executions)
    index = next(i for i, item in enumerate(changed) if item.bar.bar_end - timedelta(minutes=1) == fill_at)
    changed[index] = replace(changed[index], bar=replace(changed[index].bar, open=D("147"), low=D("146.9")))
    result = run(bars, tuple(changed), ticks)
    request = next(d for d in result["decisions"] if d["action"] == "ENTER")
    assert result["fills"][0]["qty"] <= request["requested_qty"]
    assert result["fills"][0]["qty"] <= 8


def test_new_owner_never_prices_old_open_position():
    bars, executions, ticks = source()
    old = executions[-1]
    at = old.bar.bar_end + timedelta(minutes=1)
    newbar = replace(old.bar, physical_contract="RB2705", owner_segment_id="new", bar_end=at,
                     confirmed_at=at, open=D(5000), high=D(5001), low=D(4999), close=D(5000))
    newfacts = replace(old.facts, physical_contract="RB2705")
    result = run(bars, (*executions, ExecutionBar(newbar, newfacts)), ticks)
    assert result["summary"]["status"] == "ROLLOVER_INTERRUPTED"
    assert result["summary"]["account_return_pct"] is None
    assert result["trades"][-1]["status"] == "ROLLOVER_INTERRUPTED"
    assert result["trades"][-1]["exit_price"] is None


def test_pending_reduction_does_not_suppress_higher_priority_exit(monkeypatch):
    import guiyi_quant.newow_futures.engine as module
    from guiyi_quant.newow_futures import Decision
    bars, executions, ticks = source(count=130)
    original = module.evaluate

    def scripted(profile, base, higher, position, **kwargs):
        if position and base.bar.bar_end == T + timedelta(minutes=110):
            return Decision('REDUCE', 1, 'BASE_TREND_REDUCTION', position)
        if position and base.bar.bar_end >= T + timedelta(minutes=115):
            return Decision('CLOSE', 1, 'HOLDING_TREND_EXIT', position)
        return original(profile, base, higher, position, **kwargs)

    monkeypatch.setattr(module, 'evaluate', scripted)
    executions = tuple(replace(x, bar=replace(x.bar, volume=D(0))) if
                       x.bar.bar_end >= T + timedelta(minutes=111) else x for x in executions)
    result = run(bars, executions, ticks)
    assert result['summary']['pending_action'] == 'CLOSE'
    assert any(r['reason'] == 'SUPERSEDED_BY_CLOSE' for r in result['decisions'])
