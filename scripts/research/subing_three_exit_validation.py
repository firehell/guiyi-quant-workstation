"""Summarize the seen-year SuBing fast-exit and H1→D1 reachability studies."""

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal as D
import json
from pathlib import Path

from guiyi_quant.subing_decision import _wire
from scripts.research.subing_one_lot_stress import dump, sha
from scripts.research.subing_portfolio_replay import load_segments

SLICE_STARTS = ('2025-11-21', '2026-02-21', '2026-05-21', '2026-08-21')


def load(path):
    return json.loads(path.read_bytes())


def summarize(ranges, hourly, segments):
    if (ranges['requested'], ranges['products'], ranges['execution_facts_sha256']) != (
        hourly['requested'], hourly['products'], hourly['execution_facts_sha256'],
    ):
        raise ValueError('EXIT_STUDIES_INPUT_IDENTITY_MISMATCH')
    if ranges['plan_hash'] != hourly['plan_hash']:
        raise ValueError('EXIT_STUDIES_PLAN_MISMATCH')
    for old, new in zip(hourly['coverage'], ranges['coverage'], strict=True):
        if old['status'] != 'VERIFIED' or new['status'] != 'VERIFIED' or (
            old['product'], old['contract'], old['days'], old['minutes'], old['evidence']['sources']
        ) != (new['product'], new['contract'], new['days'], new['minutes'], new['evidence']['sources']):
            raise ValueError('EXIT_STUDIES_HISTORY_SOURCE_CHANGED')
    structures = {s.executions[0].bar.physical_contract: s.structures for s in segments}
    rows = {}
    for label in ('A', 'B'):
        cohort = [p[label] for p in ranges['matched_entries']] + ranges['unmatched_entries'][label]
        closed = []
        by_regime, by_slice = {}, {}
        for trade in cohort:
            if trade['exit'] is None:
                continue
            opening = trade['opening']
            at = datetime.fromisoformat(opening['decision_bar_end']).isoformat()
            regime = structures[opening['contract']][at].get('base_regime', 'UNKNOWN')
            value = D(trade['net'])
            closed.append(value)
            month = max(k for k in SLICE_STARTS if trade['exit']['trading_day'] >= k)
            for bucket, key in ((by_regime, regime), (by_slice, month)):
                row = bucket.setdefault(key, Counter())
                row.update({'closed': 1, 'net': value, 'wins': int(value > 0),
                            'giveback': D(trade['giveback'])})
        wins = sorted((value for value in closed if value > 0), reverse=True)
        total_wins = sum(wins, D(0))
        rows[label] = dict(
            closed=len(closed), by_entry_regime=by_regime, closed_attribution_by_slice=by_slice,
            top_three_winning_cny=sum(wins[:3], D(0)),
            total_winning_cny=total_wins,
            top_three_share_of_wins=sum(wins[:3], D(0))/total_wins if total_wins else None,
            net_without_three_biggest_wins=sum(closed, D(0))-sum(wins[:3], D(0)),
            ending_net=ranges['portfolio_runs'][label]['net_pnl'],
            drawdown=ranges['portfolio_runs'][label]['drawdown'],
        )
    hourly_trades = [p['B'] for p in hourly['matched_entries']] + hourly['unmatched_entries']['B']
    handoffs = sum(p.get('handoff') is not None for p in hourly_trades)
    return dict(
        range_exit=rows,
        range_common_entry_comparison=ranges['common_entries'],
        hour_to_daily=dict(
            first_gate='existing confirmed H1 management in 3A B',
            candidate_exposed_positions=handoffs,
            inference_status=('NO_ELIGIBLE_H1_POSITION' if handoffs == 0 else 'FURTHER_RULES_REQUIRED'),
            causal_post_h1_incremental_pnl=None,
        ),
        chronological_slice_starts=SLICE_STARTS,
        holdout='RETROSPECTIVE_FIXED_RULE_SLICES_SEEN_ANNUAL_BASELINE',
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facts', type=Path, required=True)
    parser.add_argument('--range', type=Path, required=True)
    parser.add_argument('--hour', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ranges, hourly = load(args.range), load(args.hour)
    _, _, segments, evidence, _, fact_hashes = load_segments(
        args.facts, compare_exits=True, research_scope=True,
    )
    if any(row['status'] != 'VERIFIED' for row in evidence) or fact_hashes != ranges['execution_facts_sha256']:
        raise ValueError('EXIT_REGIME_CONTEXT_INCOMPLETE')
    for readback, saved in zip(evidence, ranges['coverage'], strict=True):
        if _wire(readback['evidence']['sources']) != saved['evidence']['sources']:
            raise ValueError('EXIT_REGIME_CONTEXT_CHANGED')
    dump(args.output, dict(
        **summarize(ranges, hourly, segments), code_sha256=sha(Path(__file__)),
        annual_h1_sha256=sha(args.hour), range_sha256=sha(args.range),
    ))


if __name__ == '__main__':
    main()
