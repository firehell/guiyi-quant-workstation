"""Independent zero-cost per-bar valuation of paired page-reference trades."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext, ROUND_HALF_EVEN

from .product_contracts import ProductBar
from .reference_statistics import PerformanceWindow, reference_return_pct
from .reference_trades import ReferenceTrade

MODEL_VERSION = 'newow_reference_marked_curve_v1'
FUSION_THEORETICAL_MODEL_VERSION = 'newow_dual_fusion_hindsight_peak_high_v1'


def reference_trade_rows(trades: tuple[ReferenceTrade, ...]) -> list[dict[str, object]]:
    fields = ('reference_trade_id', 'physical_contract', 'segment_id', 'calculation_segment_id',
              'entry_bar_end', 'entry_trading_day', 'entry_reference_price', 'exit_bar_end',
              'exit_reference_price', 'status', 'reference_return_pct', 'holding_bars',
              'mark_bar_end', 'interrupted_at')
    return [{key: (value.isoformat() if hasattr(value, 'isoformat') else str(value) if value is not None else None)
             for key in fields for value in (getattr(trade, key),)} for trade in trades]


def _time(row: dict, field: str) -> datetime | None:
    value = row.get(field)
    return datetime.fromisoformat(value) if value is not None else None


def _owner(row: dict) -> tuple:
    return row['physical_contract'], row['segment_id'], row.get('calculation_segment_id') or row['segment_id']


def _owned_bars(rows: list[dict], bars: tuple[ProductBar, ...], window: PerformanceWindow):
    by_owner: dict[tuple, list[ProductBar]] = {}
    for bar in bars:
        if bar.bar.bar_end <= window.cutoff and bar.bar.observation_eligible:
            owner = bar.bar.physical_contract, bar.bar.segment_id, bar.calculation_segment_id
            by_owner.setdefault(owner, []).append(bar)
    selected = []
    for row in rows:
        if not window.since.isoformat() <= row['entry_trading_day'] <= window.through.isoformat():
            continue
        start = _time(row, 'entry_bar_end')
        stop = _time(row, 'exit_bar_end') or _time(row, 'mark_bar_end')
        if start is None or stop is None or stop > window.cutoff:
            return None
        owned = sorted((bar for bar in by_owner.get(_owner(row), ()) if start <= bar.bar.bar_end <= stop),
                       key=lambda item: item.bar.bar_end)
        times = [bar.bar.bar_end for bar in owned]
        if (not times or times[0] != start or times[-1] != stop or len(times) != int(row['holding_bars']) + 1
                or len(set(times)) != len(times)):
            return None
        selected.append((row, owned))
    return selected


def holding_reference_curve(rows: list[dict], bars: tuple[ProductBar, ...], window: PerformanceWindow) -> dict | None:
    """Simple closed percentage points plus same-owner floating Close return.

    Entry membership is unchanged. Interrupted marks never become realized returns;
    their boundary breaks the curve instead of silently valuing the new owner.
    """
    selected = _owned_bars(rows, bars, window)
    if selected is None:
        return None
    members = [row for row, _ in selected]
    closed = sorted((row for row in members if row['status'] == 'CLOSED'),
                    key=lambda row: (_time(row, 'exit_bar_end'), row['reference_trade_id']))
    active_by_time = {}
    interruptions = sorted(_time(row, 'interrupted_at') for row in members if row.get('interrupted_at'))
    for row, owned in selected:
        for bar in owned:
            # CLEAR is processed before a same-Bar new BUILD.
            if row['status'] == 'CLOSED' and bar.bar.bar_end == _time(row, 'exit_bar_end'):
                continue
            active_by_time.setdefault(bar.bar.bar_end, []).append((row, bar))
    points = []
    total, closed_index, interruption_index = Decimal(0), 0, 0
    eligible = sorted((bar for bar in bars if bar.bar.observation_eligible and bar.bar.bar_end <= window.cutoff
                       and window.since <= bar.bar.trading_day <= window.through), key=lambda bar: bar.bar.bar_end)
    if len({bar.bar.bar_end for bar in eligible}) != len(eligible):
        return None
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        for bar in eligible:
            time = bar.bar.bar_end
            while closed_index < len(closed) and _time(closed[closed_index], 'exit_bar_end') <= time:
                total += Decimal(closed[closed_index]['reference_return_pct'])
                closed_index += 1
            broken = False
            while interruption_index < len(interruptions) and interruptions[interruption_index] <= time:
                broken = True
                interruption_index += 1
            active = active_by_time.get(time, [])
            if len(active) > 1:
                return None
            floating, trade_id, entry_day, status = Decimal(0), None, None, 'FLAT'
            if active:
                row, owned = active[0]
                floating = reference_return_pct(Decimal(row['entry_reference_price']), owned.bar.close)
                trade_id, entry_day, status = row['reference_trade_id'], row['entry_trading_day'], 'HOLDING'
            if broken:
                status = 'INTERRUPTED'
            points.append({'bar_end': time.isoformat(), 'trading_day': bar.bar.trading_day.isoformat(),
                'physical_contract': bar.bar.physical_contract, 'segment_id': bar.bar.segment_id,
                'calculation_segment_id': bar.calculation_segment_id, 'reference_trade_id': trade_id,
                'entry_trading_day': entry_day,
                'status': status, 'closed_return_percentage_points': str(total),
                'floating_return_pct': str(floating) if not broken else None,
                'marked_return_percentage_points': str(total + floating) if not broken else None})
    return {'model_version': MODEL_VERSION, 'page_parity': True, 'executable': False, 'points': points}


def fusion_theoretical_reference(rows: list[dict], bars: tuple[ProductBar, ...], window: PerformanceWindow) -> dict | None:
    """Preserve fusion pairing and membership; retrospective exit uses peak High."""
    selected = _owned_bars([row for row in rows if row['status'] == 'CLOSED'], bars, window)
    if selected is None:
        return None
    returns = []
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        for row, owned in selected:
            peak = max(bar.bar.high for bar in owned)
            value = reference_return_pct(Decimal(row['entry_reference_price']), peak)
            returns.append({'reference_trade_id': row['reference_trade_id'], 'return_pct': str(value), 'ideal_exit_price': str(peak)})
        values = [Decimal(row['return_pct']) for row in returns]
        total = sum(values, Decimal(0))
        count = len(values)
        return {'model_version': FUSION_THEORETICAL_MODEL_VERSION, 'hindsight': True, 'executable': False,
                'returns': returns, 'sum_return_percentage_points': str(total),
                'win_rate_pct': str(Decimal(sum(value > 0 for value in values)) / Decimal(count) * 100) if count else None,
                'mean_return_pct': str(total / Decimal(count)) if count else None}
