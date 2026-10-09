"""Display saved per-Bar marks; never infer prices or replay a strategy."""
from datetime import datetime
from decimal import Decimal, localcontext


def saved_holding_curve(trades, marks, availability, since, through, cutoff, boundaries=()):
    members = {t['reference_trade_id']: t for t in trades
               if since <= t['entry_trading_day'] <= through}
    marked = {key: {} for key in members}
    def instant(value):
        return datetime.fromisoformat(value)
    for mark in marks:
        trade = members.get(mark['trade_id'])
        if trade is None:
            continue
        at = instant(mark['bar_end'])
        if at > cutoff or at < instant(trade['entry_bar_end']):
            return None
        stop = trade.get('exit_bar_end') or trade.get('interrupted_at')
        if stop and at >= instant(stop):
            return None
        previous = marked[mark['trade_id']].get(at)
        if previous and previous != mark:
            return None
        marked[mark['trade_id']][at] = mark
    # Every held completed Bar must have a saved valuation, not an interpolated price.
    for key, trade in members.items():
        count = int(trade['holding_bars']) + (0 if trade['status'] == 'CLOSED' else 1)
        values = sorted(marked[key].values(), key=lambda m: instant(m['bar_end']))
        if len(values) != count or [m['holding_bars'] for m in values] != list(range(count)):
            return None
    boundary_days = {instant(p['value']['bar_end']): p['trading_day'] for p in boundaries}
    timeline = {}
    for point in availability:
        value = point['value']
        at = instant(value['bar_end'])
        if since <= point['trading_day'] <= through and at <= cutoff:
            if at in timeline and timeline[at][:2] != (point['trading_day'], value):
                return None
            timeline[at] = (point['trading_day'], value, [])
    for key, trade in members.items():
        owner = {'physical_contract': trade['physical_contract'], 'segment_id': trade['owner_segment_id'],
                 'calculation_segment_id': trade['calculation_segment_id']}
        for at, mark in marked[key].items():
            day, value, active = timeline.setdefault(at, (mark['trading_day'], owner, []))
            if any(value[k] != owner[k] for k in owner):
                return None
            active.append((trade, mark))
        end = trade.get('exit_bar_end') or trade.get('interrupted_at')
        if end and instant(end) <= cutoff:
            at = instant(end)
            day = trade.get('exit_trading_day') or boundary_days.get(at)
            if day is None:
                return None
            timeline.setdefault(at, (day, owner, []))
    closed = sorted((t for t in members.values() if t['status'] == 'CLOSED'), key=lambda t: instant(t['exit_bar_end']))
    interrupted = {instant(t['interrupted_at']) for t in members.values() if t.get('interrupted_at')}
    points, total, index = [], Decimal(0), 0
    with localcontext() as context:
        context.prec = 28
        for at, (day, owner, active) in sorted(timeline.items()):
            while index < len(closed) and instant(closed[index]['exit_bar_end']) <= at:
                total += Decimal(closed[index]['reference_return'])
                index += 1
            expected = [t for t in members.values() if instant(t['entry_bar_end']) <= at
                and (at < instant(t['exit_bar_end'] or t['interrupted_at'])
                     if t.get('exit_bar_end') or t.get('interrupted_at') else at <= instant(t['mark_bar_end']))]
            if len(active) > 1 or (expected and not active):
                return None
            trade, mark = active[0] if active else (None, None)
            floating = Decimal(mark['reference_return']) if mark else Decimal(0)
            broken = at in interrupted or owner.get('status', 'ready') != 'ready'
            points.append({'bar_end': at.isoformat(), 'trading_day': day,
                'physical_contract': owner['physical_contract'], 'segment_id': owner['segment_id'],
                'calculation_segment_id': owner['calculation_segment_id'],
                'reference_trade_id': trade['public_reference_trade_id'] if trade else None,
                'entry_trading_day': trade['entry_trading_day'] if trade else None,
                'status': 'INTERRUPTED' if broken else 'HOLDING' if trade else 'FLAT',
                'closed_return_percentage_points': str(total),
                'floating_return_pct': None if broken else str(floating),
                'marked_return_percentage_points': None if broken else str(total + floating)})
    return {'model_version': 'newow_reference_marked_curve_v1', 'page_parity': True,
            'executable': False, 'points': points} if points else None
