"""Verify marked giveback and fixed-fill cost sensitivity in the timing study."""

import argparse
from bisect import bisect_left
from datetime import datetime
from decimal import Decimal as D
import json
from pathlib import Path

from guiyi_quant.subing_decision import _wire, direction_sign
from scripts.research.subing_one_lot_stress import dump, sha
from scripts.research.subing_portfolio_replay import load_segments


def close_fee(facts, price, open_day):
    kind = 'close_today' if facts.trading_day.isoformat() == open_day else 'close'
    return facts.fees.amount(kind, price, facts.multiplier)


def price_with_slip(execution, fill, ticks):
    bar, facts = execution.bar, execution.facts
    buying = fill['order_side'] == 'BUY'
    price = bar.close + (1 if buying else -1) * facts.tick_size * ticks
    if (bar.volume < 1 or not bar.low <= price <= bar.high
            or not facts.limit_down <= price <= facts.limit_up
            or buying and bar.low == facts.limit_up
            or not buying and bar.high == facts.limit_down):
        return None
    return price


def attribute(trade, xs, ends):
    opening, closing = trade['entry'], trade['exit']
    oi = bisect_left(ends, datetime.fromisoformat(opening['fill_bar_end']))
    ci = bisect_left(ends, datetime.fromisoformat(closing['fill_bar_end']))
    if (xs[oi].bar.bar_end.isoformat() != opening['fill_bar_end']
            or xs[ci].bar.bar_end.isoformat() != closing['fill_bar_end'] or ci <= oi):
        raise ValueError('TIMING_ATTRIBUTION_MINUTE_IDENTITY')
    for i, fill in ((oi, opening), (ci, closing)):
        if price_with_slip(xs[i], fill, 1) != D(fill['price']):
            raise ValueError('TIMING_ATTRIBUTION_PRICE_CONFLICT')
    multiplier = xs[oi].facts.multiplier
    direction = direction_sign(opening['side'])
    open_day = opening['trading_day']
    net = D(trade['net'])
    entry, entry_fee = D(opening['price']), D(opening['fee'])
    exit_fee = D(closing['fee'])
    if direction * (D(closing['price']) - entry) * multiplier - entry_fee - exit_fee != net:
        raise ValueError('TIMING_ATTRIBUTION_NET_CONFLICT')
    peak = max(
        [net] + [direction * (xs[i].bar.close - entry) * multiplier - entry_fee
                 - close_fee(xs[i].facts, xs[i].bar.close, open_day)
                 for i in range(oi, ci)],
    )
    stress_in = price_with_slip(xs[oi], opening, 2)
    stress_out = price_with_slip(xs[ci], closing, 2)
    stress_slip = None
    if stress_in is not None and stress_out is not None:
        stress_slip = (
            direction * (stress_out - stress_in) * multiplier
            - xs[oi].facts.fees.amount('open', stress_in, multiplier)
            - close_fee(xs[ci].facts, stress_out, open_day)
        )
    return dict(contract=trade['contract'], entry=opening['fill_at'], net=net, peak_net=peak,
                giveback=peak-net, double_fee_fixed_path_net=net-entry_fee-exit_fee,
                two_tick_same_fill_minutes_net=stress_slip)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facts', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    _, _, segments, coverage, _, hashes = load_segments(
        args.facts, compare_exits=True, research_scope=True,
    )
    if any(row['status'] != 'VERIFIED' for row in coverage):
        raise ValueError('TIMING_ATTRIBUTION_INPUT_INCOMPLETE')
    by_contract = {}
    for s in segments:
        xs = s.executions
        by_contract[xs[0].bar.physical_contract] = (xs, [x.bar.bar_end for x in xs])
    report, sources = {}, {}
    for group in ('intraday', 'trend'):
        baseline = args.results / f'{group}.json'
        strict = args.results / f'{group}-5m-strict.json'
        a, b = (json.loads(p.read_bytes()) for p in (baseline, strict))
        sources.update({p.name: sha(p) for p in (baseline, strict)})
        for evidence in (a, b):
            if _wire(coverage) != evidence['coverage'] or hashes != evidence['execution_facts_sha256']:
                raise ValueError('TIMING_ATTRIBUTION_INPUT_CHANGED')
        report[group] = {}
        for freq, run in {**a['runs'], '5m': b['run']}.items():
            rounds = [attribute(trade, *by_contract[trade['contract']]) for trade in run['trades']]
            feasible = [row['two_tick_same_fill_minutes_net'] for row in rounds
                        if row['two_tick_same_fill_minutes_net'] is not None]
            report[group][freq] = dict(
                closed_rounds=len(rounds),
                giveback=sum((row['giveback'] for row in rounds), D(0)),
                double_fee_fixed_path_net=sum((row['double_fee_fixed_path_net'] for row in rounds), D(0)),
                two_tick_same_minutes_feasible_rounds=len(feasible),
                two_tick_all_rounds_net=sum(feasible, D(0)) if len(feasible) == len(rounds) else None,
                rounds=rounds,
            )
    dump(args.output, dict(runs=report, result_files_sha256=sources,
                           method='fixed filled paths; two-tick price checked on original minute only',
                           code_sha256=sha(Path(__file__))))


if __name__ == '__main__':
    main()
