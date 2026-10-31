"""v3.3.79 public page estimates, independent of strategy/ReferenceTrade facts.

All intermediate arithmetic follows binary64 public JavaScript; emitted numbers
are Decimal strings. Segment boundaries discard open pairing without realizing
it. Only an explicitly eligible final input terminal gets ordinary forceClose.
Futures adapter drawdown is the maximum source drawdown within each independent
physical/quality segment. Open marked peaks never carry into a later segment;
dropping an interrupted floating estimate is not a realized page loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import floor, isfinite
from typing import Any, Callable, Sequence, cast

from .ai_analysis import fixed

PAGE_PERFORMANCE_VERSION = "newow_page_performance_v3379_v2"
PAGE_SOURCE_SHA256 = "3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d"


@dataclass(frozen=True)
class PageBar:
    date: str
    high: Decimal
    low: Decimal
    close: Decimal
    observation_eligible: bool = True
    trading_day: str | None = None


@dataclass(frozen=True)
class PageAction:
    date: str
    type: str
    price: Decimal
    # Caller supplies source merge order: oscillation first, then trend.


@dataclass(frozen=True)
class PageSegment:
    owner: str
    bars: Sequence[PageBar]
    terminal_eligible: bool = False
    actions: Sequence[PageAction] = ()


def _number(value: float, digits: int) -> str:
    # parseFloat(toFixed()) removes negative zero and insignificant zeroes.
    result = fixed(value, digits)
    return format(result.normalize(), "f") if result else "0"


def _sum_js(values) -> float:
    # Python 3.12+ sum(float) compensates; JavaScript accumulates in order.
    total = 0.0
    for value in values:
        total += value
    return total


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ValueError("REFERENCE_PAGE_MATERIAL_INTERRUPTED")


def _ma(values: list[float], n: int,
        cancelled: Callable[[], bool] | None = None) -> list[float]:
    output = []
    for i in range(len(values)):
        if i % 256 == 0:
            _check_cancelled(cancelled)
        output.append(
            _sum_js(reversed(values[max(0, i - n + 1):i + 1])) / min(i + 1, n)
        )
    return output


def _segment(
    segment: PageSegment, strategy: str, ideal: bool, period: str, terminal: bool,
    cancelled: Callable[[], bool] | None = None,
) -> dict | None:
    _check_cancelled(cancelled)
    bars = segment.bars
    minimum, start = (
        (2, 0)
        if strategy == "fusion"
        else (36, 34)
        if strategy == "main_rise"
        else (11, 9)
    )
    if len(bars) < minimum or (strategy == "fusion" and not segment.actions):
        return None
    rows = []
    for index, bar in enumerate(bars):
        if index % 256 == 0:
            _check_cancelled(cancelled)
        rows.append((float(bar.high), float(bar.low), float(bar.close)))
    jj = []
    for index, (high, low, close) in enumerate(rows):
        if index % 256 == 0:
            _check_cancelled(cancelled)
        jj.append((close + high + low) / 3)
    b10, ma35, ma45 = (
        _ma(jj, 10, cancelled), _ma(jj, 35, cancelled), _ma(jj, 45, cancelled)
    )
    states = []
    if strategy != "main_rise":
        for index, ((_, _, close), average) in enumerate(zip(rows, b10)):
            if index % 256 == 0:
                _check_cancelled(cancelled)
            states.append(close >= average)
    else:
        for index, (slow, fast) in enumerate(zip(ma35, ma45)):
            if index % 256 == 0:
                _check_cancelled(cancelled)
            states.append(slow >= fast)
    hhv = []
    llv = []
    for i in range(len(rows)):
        if i % 256 == 0:
            _check_cancelled(cancelled)
        hhv.append(max(h for h, _, _ in rows[max(0, i - 9):i + 1]))
        llv.append(min(low for _, low, _ in rows[max(0, i - 9):i + 1]))
    by_date: dict[str, dict[str, list[float]]] = {}
    for action_index, action in enumerate(segment.actions):
        if action_index % 256 == 0:
            _check_cancelled(cancelled)
        by_date.setdefault(action.date, {"buy": [], "sell": []})[action.type].append(
            float(action.price)
        )
    dates, equity, trades = [], [], []
    buy = None
    buy_date = ""
    buy_index = -1
    position_high = cum = peak = drawdown = 0.0
    wins = 0

    def enter(i: int, price: float, high: float):
        nonlocal buy, buy_date, buy_index, position_high
        buy, buy_date, buy_index, position_high = price, bars[i].date, i, high

    def exit_(i: int, price: float, force=False):
        nonlocal buy, cum, wins, drawdown
        pct = (price - cast(float, buy)) / cast(float, buy) * 100
        trade = {
            "buyDate": buy_date,
            "buyPrice": _number(cast(float, buy), 2),
            "sellDate": bars[i].date,
            "sellPrice": _number(price, 2),
            "pct": _number(pct, 2),
            "forceClose": force,
        }
        if force and strategy in ("oscillation", "fusion"):
            trade["buyBarIsLive"] = buy_index == len(bars) - 1
        trades.append(trade)
        cum += pct
        wins += int(pct > 0)
        if ideal and pct < 0:
            drawdown = max(drawdown, abs(pct))
        buy = None

    for i in range(start, len(rows)):
        if i % 256 == 0:
            _check_cancelled(cancelled)
        if not bars[i].observation_eligible:
            continue
        high, low, close = rows[i]
        up = states[i] and not states[i - 1] if i else False
        down = not states[i] and states[i - 1] if i else False
        if strategy == "oscillation":
            if ideal:
                if buy is None and low <= llv[i]:
                    enter(i, low, hhv[i])
                if buy is not None:
                    position_high = max(position_high, hhv[i])
                    if high >= hhv[i]:
                        exit_(i, position_high)
            else:
                if buy is not None and high >= hhv[i]:
                    exit_(i, high)
                if buy is None and low <= llv[i]:
                    enter(i, low, high)
        elif strategy == "fusion":
            actions = by_date.get(bars[i].date, {"buy": [], "sell": []})
            if buy is not None and actions["sell"]:
                exit_(i, position_high if ideal else actions["sell"][0])
            if buy is None and actions["buy"]:
                enter(i, actions["buy"][0], high)
            if buy is not None:
                position_high = max(position_high, high)
        else:
            entry_price = (
                close
                if ideal and strategy == "main_rise"
                else ma45[i]
                if strategy == "main_rise"
                else b10[i]
            )
            if up and buy is None:
                enter(i, entry_price, close)
            if ideal and strategy == "trend" and buy is not None:
                position_high = max(position_high, close)
            if down and buy is not None:
                exit_(i, position_high if ideal else entry_price)
            if ideal and strategy == "main_rise" and buy is not None:
                position_high = max(position_high, close)
        marked = cum + (
            (close - buy) / buy * 100 if buy is not None and not ideal else 0
        )
        if not ideal:
            peak = max(peak, marked)
            drawdown = max(drawdown, peak - marked)
        dates.append(bars[i].date)
        equity.append(_number(marked, 4))
    interrupted = buy is not None and not (terminal and not ideal)
    if buy is not None and terminal and not ideal and bars[-1].observation_eligible:
        exit_(len(bars) - 1, rows[-1][2], True)
    _check_cancelled(cancelled)
    return {
        "period": period,
        "drawdown_kind": "maximum_trade_loss" if ideal else "peak_difference",
        "summary": {
            "cumReturn": _number(cum, 2),
            "accuracy": floor(wins / len(trades) * 100 + 0.5) if trades else 0,
            "maxDrawdown": _number(drawdown, 2),
            "tradeCount": len(trades),
        },
        "dates": dates,
        "equity": equity,
        "trades": trades,
        "_cum": cum,
        "_wins": wins,
        "_drawdown": drawdown,
        "_interrupted": int(interrupted),
    }


def filter_page_by_date(
    data: dict | None, since: str | None, through: str | None = None
) -> dict | None:
    """Exact public filterBacktestByDate: exit membership, marked normalization.

    Public no-match start date returns unfiltered data; retain this observable
    behavior rather than silently substituting a different window contract.
    """
    if not data or not data["dates"] or (not since and not through):
        return data
    tokens = data.get("trading_days", data["dates"])
    index = next((i for i, d in enumerate(tokens) if d >= since), 0) if since else 0
    # The source start-only no-match behavior is deliberately preserved.
    end = next(
        (i for i, d in enumerate(tokens) if through and d > through), len(tokens)
    )
    if index == 0 and end == len(tokens):
        return data
    dates = data["dates"][index:end]
    days = tokens[index:end]
    values = [float(v) for v in data["equity"][index:end]]
    equity = [_number(v - values[0], 4) for v in values] if values else []
    trades = [
        t for t in data["trades"] if dates and dates[0] <= t["sellDate"] <= dates[-1]
    ]
    cum = _sum_js(float(t["pct"]) for t in trades)
    peak, dd = float("-inf"), 0.0
    for value in equity:
        peak = max(peak, float(value))
        dd = max(dd, peak - float(value))
    result = {
        "period": data["period"],
        "drawdown_kind": "peak_difference",
        "summary": {
            "cumReturn": _number(cum, 2),
            "accuracy": floor(
                sum(float(t["pct"]) > 0 for t in trades) / len(trades) * 100 + 0.5
            )
            if trades
            else 0,
            "maxDrawdown": _number(dd, 2),
            "tradeCount": len(trades),
        },
        "dates": dates,
        "equity": equity,
        "trades": trades,
    }
    if "segment_ids" in data:
        result["segment_ids"] = data["segment_ids"][index:end]
        result["trading_days"] = days
    return result


PAGE_MATERIAL_SCHEMA = "newow_page_material_v1"


def build_page_performance_material(
    segments: Sequence[PageSegment],
    strategy: str,
    *,
    period: str = "day",
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Compute both source modes once from validated, complete owner segments.

    The unified reader adapter must establish completed/session/quality segment
    identity and terminal eligibility. This function never reads data or emits
    strategy actions, ReferenceTrades, account fills, or Runtime decisions.
    """
    if strategy not in ("trend", "oscillation", "main_rise", "fusion"):
        raise ValueError("NEWOW_INVALID_QUERY")
    _check_cancelled(cancelled)
    last_eligible_date = None
    last_eligible_day = None
    owners = set()
    for segment in segments:
        _check_cancelled(cancelled)
        if not isinstance(segment, PageSegment):
            raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
        if (
            not isinstance(segment.owner, str)
            or not segment.owner
            or segment.owner in owners
            or type(segment.terminal_eligible) is not bool
        ):
            raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
        owners.add(segment.owner)
        dates = set()
        last_date = None
        seen_eligible = False
        for bar_index, bar in enumerate(segment.bars):
            if bar_index % 256 == 0:
                _check_cancelled(cancelled)
            if not isinstance(bar, PageBar):
                raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
            if (
                not isinstance(bar.date, str)
                or not bar.date
                or (last_date is not None and bar.date <= last_date)
            ):
                raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
            if type(bar.observation_eligible) is not bool or (
                seen_eligible and not bar.observation_eligible
            ):
                raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
            seen_eligible = seen_eligible or bar.observation_eligible
            if bar.trading_day is not None and (
                not isinstance(bar.trading_day, str) or not bar.trading_day
            ):
                raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
            if bar.observation_eligible:
                if last_eligible_date is not None and bar.date <= last_eligible_date:
                    raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
                last_eligible_date = bar.date
                source_day = bar.trading_day or bar.date
                last_eligible_day = max(last_eligible_day or source_day, source_day)
            for value in (bar.high, bar.low, bar.close):
                if (
                    not isinstance(value, Decimal)
                    or not value.is_finite()
                    or value <= 0
                    or not isfinite(float(value))
                    or float(value) <= 0
                ):
                    raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
            if not bar.low <= bar.close <= bar.high:
                raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
            last_date = bar.date
            dates.add(bar.date)
        for action_index, action in enumerate(segment.actions):
            if action_index % 256 == 0:
                _check_cancelled(cancelled)
            if not isinstance(action, PageAction):
                raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
            if (
                action.date not in dates
                or action.type not in ("buy", "sell")
                or not isinstance(action.price, Decimal)
                or not action.price.is_finite()
                or action.price <= 0
                or not isfinite(float(action.price))
                or float(action.price) <= 0
            ):
                raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
    material_segments = []
    for index, segment in enumerate(segments):
        _check_cancelled(cancelled)
        day_map = {}
        for bar_index, bar in enumerate(segment.bars):
            if bar_index % 256 == 0:
                _check_cancelled(cancelled)
            day_map[bar.date] = bar.trading_day or bar.date
        modes = {}
        for ideal in (False, True):
            _check_cancelled(cancelled)
            result = _segment(
                segment, strategy, ideal, period,
                index == len(segments) - 1 and segment.terminal_eligible,
                cancelled,
            )
            if result is not None:
                trading_days = []
                for day_index, day in enumerate(result["dates"]):
                    if day_index % 256 == 0:
                        _check_cancelled(cancelled)
                    trading_days.append(day_map[day])
                result["trading_days"] = trading_days
                result["segment_ids"] = [segment.owner] * len(result["dates"])
                for trade_index, trade in enumerate(result["trades"]):
                    if trade_index % 256 == 0:
                        _check_cancelled(cancelled)
                    trade["segment_id"] = segment.owner
            modes["ideal" if ideal else "ordinary"] = result
            _check_cancelled(cancelled)
        material_segments.append({"owner": segment.owner, **modes})
    _check_cancelled(cancelled)
    return {
        "schema": PAGE_MATERIAL_SCHEMA,
        "page_version": PAGE_PERFORMANCE_VERSION,
        "strategy": strategy,
        "period": period,
        "segment_count": len(segments),
        "last_eligible_day": last_eligible_day,
        "segments": material_segments,
    }


def project_page_performance_material(
    material: dict, *, since: str | None = None, through: str | None = None,
    selected_mode: str | None = None,
) -> dict:
    """Apply the original public window and aggregation rules to frozen modes."""
    if (
        (since is not None and (not isinstance(since, str) or not since))
        or (through is not None and (not isinstance(through, str) or not through))
        or (since is not None and through is not None and since > through)
        or selected_mode not in (None, "ordinary", "ideal")
    ):
        raise ValueError("NEWOW_INVALID_QUERY")
    if (not isinstance(material, dict)
        or material.get("schema") != PAGE_MATERIAL_SCHEMA
        or material.get("page_version") != PAGE_PERFORMANCE_VERSION
        or material.get("strategy") not in ("trend", "oscillation", "main_rise", "fusion")
        or type(material.get("segment_count")) is not int
        or material["segment_count"] < 0
        or not isinstance(material.get("period"), str)
        or not material["period"]
        or not isinstance(material.get("segments"), list)
        or len(material["segments"]) != material["segment_count"]
        or (material.get("last_eligible_day") is not None
            and not isinstance(material["last_eligible_day"], str))):
        raise ValueError("NEWOW_PAGE_MATERIAL_INVALID")
    segments = material["segments"]
    period = material["period"]
    output = {
        "version": PAGE_PERFORMANCE_VERSION,
        "source_version": "3.3.79",
        "source_sha256": PAGE_SOURCE_SHA256,
        "page_parity": True,
        "executable": False,
        "strategy": material["strategy"],
        "segment_count": material["segment_count"],
    }
    # Public no-match fallback belongs to the full source sequence, not to
    # each physical owner. Once the overall input reaches the requested start,
    # ended owners must not re-enter the window through that fallback.
    window_start_matched = (
        since is not None and material["last_eligible_day"] is not None
        and material["last_eligible_day"] >= since
    )
    for ideal in ((False, True) if selected_mode is None else (selected_mode == "ideal",)):
        aggregate: dict[str, Any] = {
            "period": period,
            "dates": [],
            "equity": [],
            "trades": [],
            "segment_ids": [],
            "trading_days": [],
        }
        drawdown_kinds: set[str] = set()
        cum = dd = 0.0
        wins = interrupted = used = 0
        for segment in segments:
            if not isinstance(segment, dict) or not isinstance(segment.get("owner"), str):
                raise ValueError("NEWOW_PAGE_MATERIAL_INVALID")
            result = segment.get("ideal" if ideal else "ordinary")
            if result is None:
                continue
            if not isinstance(result, dict) or not isinstance(result.get("trading_days"), list):
                raise ValueError("NEWOW_PAGE_MATERIAL_INVALID")
            if (window_start_matched and result["trading_days"]
                    and result["trading_days"][-1] < since):
                continue
            used += 1
            raw_cum, raw_wins, raw_dd = (
                result["_cum"],
                result["_wins"],
                result["_drawdown"],
            )
            interrupted += result["_interrupted"]
            result = cast(dict[str, Any], filter_page_by_date(result, since, through))
            if (since or through) and "_cum" not in result:
                raw_cum = float(result["summary"]["cumReturn"])
                raw_wins = sum(float(t["pct"]) > 0 for t in result["trades"])
                raw_dd = float(result["summary"]["maxDrawdown"])
            drawdown_kinds.add(result["drawdown_kind"])
            aggregate["segment_ids"].extend(result["segment_ids"])
            aggregate["trading_days"].extend(result["trading_days"])
            aggregate["dates"].extend(result["dates"])
            aggregate["equity"].extend(
                _number(cum + float(v), 4) for v in result["equity"]
            )
            aggregate["trades"].extend(result["trades"])
            cum += raw_cum
            wins += raw_wins
            dd = max(dd, raw_dd)
        trades = aggregate["trades"]
        aggregate["drawdown_kind"] = next(iter(drawdown_kinds)) if len(drawdown_kinds) == 1 else "mixed_segment"
        aggregate["summary"] = {
            "cumReturn": _number(cum, 2),
            "accuracy": floor(wins / len(trades) * 100 + 0.5) if trades else 0,
            "maxDrawdown": _number(dd, 2),
            "tradeCount": len(trades),
        }
        output["ideal" if ideal else "ordinary"] = aggregate if used else None
        output["ideal_open_count" if ideal else "ordinary_interrupted_count"] = (
            interrupted
        )
    return output


def compute_page_performance(
    segments: Sequence[PageSegment], strategy: str, *, period: str = "day",
    since: str | None = None, through: str | None = None,
    selected_mode: str | None = None,
) -> dict:
    """Current page formula, now shared with frozen material projection."""
    if (
        (since is not None and (not isinstance(since, str) or not since))
        or (through is not None and (not isinstance(through, str) or not through))
        or (since is not None and through is not None and since > through)
        or selected_mode not in (None, "ordinary", "ideal")
    ):
        raise ValueError("NEWOW_INVALID_QUERY")
    return project_page_performance_material(
        build_page_performance_material(segments, strategy, period=period),
        since=since, through=through, selected_mode=selected_mode,
    )
