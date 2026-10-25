"""Bounded, read-only display of retained forward trades at one exact snapshot."""
from decimal import Decimal, InvalidOperation, localcontext

from app.reference_trading.query import QueryConflict

MAX_TRADES = 10_000
MAX_CURVE_POINTS = 800


def forward_panel(query, stream_id, *, since, through, cutoff=None):
    first = query.trades(stream_id, since=since, through=through, cutoff=cutoff, limit=50)
    if first['stream']['recording_mode'] != 'forward_observation':
        raise QueryConflict('MODE_NOT_AVAILABLE')
    snapshot = first['snapshot']
    summary = query.summary(stream_id, since=since, through=through, cutoff=cutoff, snapshot_token=snapshot)
    if summary['snapshot'] != snapshot:
        raise QueryConflict('SNAPSHOT_CONFLICT')
    rows = list(first['items'])
    ids = {row['reference_trade_id'] for row in rows}
    if len(ids) != len(rows):
        raise QueryConflict('CURSOR_CONFLICT')
    cursor = first['next_cursor']
    cursors = set()
    while cursor:
        if cursor in cursors or len(rows) >= MAX_TRADES:
            raise QueryConflict('QUERY_BUDGET_EXCEEDED')
        cursors.add(cursor)
        page = query.trades(stream_id, since=since, through=through, cutoff=cutoff,
                            limit=200, cursor=cursor, snapshot_token=snapshot)
        if any(page[key] != first[key] for key in ('snapshot', 'revision_id', 'seq', 'window')):
            raise QueryConflict('SNAPSHOT_CONFLICT')
        for row in page['items']:
            if row['reference_trade_id'] in ids:
                raise QueryConflict('CURSOR_CONFLICT')
            ids.add(row['reference_trade_id'])
            rows.append(row)
        cursor = page['next_cursor']
    if len(rows) > MAX_TRADES:
        raise QueryConflict('QUERY_BUDGET_EXCEEDED')
    closed = sorted((row for row in rows if row['status'] == 'CLOSED'
                     and since.isoformat() <= row['entry_trading_day'] <= through.isoformat()),
                    key=lambda row: (row['exit_bar_end'], row['reference_trade_id']))
    members = [row for row in rows if since.isoformat() <= row['entry_trading_day'] <= through.isoformat()]
    counts = dict(closed_count=len(closed), open_count=sum(row['status'] == 'OPEN' for row in members),
                  interrupted_count=sum(row['status'] not in ('OPEN', 'CLOSED') for row in members),
                  initial_count=sum(row['entry_trading_day'] < since.isoformat() for row in rows))
    if any(summary[key] != count for key, count in counts.items()):
        raise QueryConflict('SUMMARY_DATA_CONFLICT')
    points = []
    with localcontext() as context:
        context.prec = 50
        total = peak = drawdown = Decimal(0)
        for row in closed:
            try:
                value = Decimal(row['reference_return'])
            except (InvalidOperation, TypeError, ValueError):
                raise QueryConflict('SUMMARY_DATA_CONFLICT') from None
            if not value.is_finite():
                raise QueryConflict('SUMMARY_DATA_CONFLICT')
            total += value
            peak = max(peak, total)
            drawdown = max(drawdown, peak - total)
            points.append(dict(value=str(total), date=row['exit_trading_day'],
                               bar_end=row['exit_bar_end'], reference_trade_id=row['reference_trade_id'],
                               segment=':'.join(str(row[key]) for key in (
                                   'physical_contract', 'owner_segment_id', 'calculation_segment_id'))))
        expected_sum = summary['sum_return_percentage_points']
        if len(closed) != summary['closed_count'] or (closed and (
            expected_sum is None or total != Decimal(expected_sum)
        )):
            raise QueryConflict('SUMMARY_DATA_CONFLICT')
    # Sample geometry only; summary and drawdown always use every retained close.
    if len(points) > MAX_CURVE_POINTS:
        positions = {round(i * (len(points) - 1) / (MAX_CURVE_POINTS - 1)) for i in range(MAX_CURVE_POINTS)}
        # Keep segment boundaries as gaps, rather than joining over missing samples.
        sampled = []
        previous_index = None
        for index in sorted(positions):
            point = dict(points[index])
            if previous_index is not None and any(
                points[j]['segment'] != points[previous_index]['segment']
                for j in range(previous_index + 1, index + 1)
            ):
                point['segment'] += f':sample-boundary:{index}'
            sampled.append(point)
            previous_index = index
    else:
        sampled = points
    return dict(version='forward_reference_panel_v1', page=first, summary=summary,
                curve=sampled, total_curve_points=len(points),
                drawdown_percentage_points=str(drawdown) if closed else None)
