"""Hindsight peaks from exact saved trade intervals and canonical physical Bars."""
from datetime import datetime
from decimal import Decimal, localcontext


def saved_theoretical(trades, marks, bars, strategy, since, through):
    closed = [t for t in trades if t['status'] == 'CLOSED' and since <= t['entry_trading_day'] <= through]
    rows, returns = [], []
    with localcontext() as context:
        context.prec = 28
        for trade in closed:
            start, stop = (datetime.fromisoformat(trade[k]) for k in ('entry_bar_end', 'exit_bar_end'))
            owned = [bar for bar in bars.get(trade['physical_contract'], ()) if start <= bar.bar_end <= stop]
            expected = {datetime.fromisoformat(m['bar_end']) for m in marks if m['trade_id'] == trade['reference_trade_id']}
            expected.add(stop)
            times = [bar.bar_end for bar in owned]
            if (len(times) != trade['holding_bars'] + 1 or len(set(times)) != len(times)
                or set(times) != expected or start not in expected
                or any(bar.close <= 0 or bar.high <= 0 for bar in owned)):
                return None
            peak = max(bar.high if strategy == 'oscillation' else bar.close for bar in owned)
            result = (peak / Decimal(trade['entry_reference_price']) - 1) * 100
            rows.append(dict(reference_trade_id=trade['public_reference_trade_id'], return_pct=str(result), ideal_exit_price=str(peak)))
            returns.append(result)
        count = len(returns)
        return dict(model_version='newow_hindsight_peak_reference_v1', hindsight=True, executable=False,
            returns=rows, sum_return_percentage_points=str(sum(returns, Decimal(0))),
            win_rate_pct=str(Decimal(sum(r > 0 for r in returns)) / count * 100) if count else None,
            mean_return_pct=str(sum(returns, Decimal(0)) / count) if count else None)
