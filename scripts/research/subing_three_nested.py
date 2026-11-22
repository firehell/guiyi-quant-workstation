"""Require a new confirmed M5 cross after a live confirmed M15 opportunity."""

import argparse
from dataclasses import replace
from pathlib import Path

from app.market_data.new_subing_research import payload_hash
from scripts.research.subing_one_lot_stress import dump, hashes, sha, stressed
from scripts.research.subing_three_timing import evaluate, prepare_inputs, setups

PARENT_MINUTES = 150


def nested_m5(segment, frames, group):
    parents = setups(segment, frames['15m'], group)
    active, mask = None, {}
    for index, x in enumerate(segment.executions):
        at = x.bar.bar_end
        parent_now = parents.get(at)
        if parent_now:
            active = index, x.bar.trading_day, x.bar.session_open_at
        row = frames['5m'].get(at)
        if row is None:
            continue
        eligible = (
            active is not None and 0 < index - active[0] <= PARENT_MINUTES
            and active[1] == x.bar.trading_day
            and (group != 'intraday' or active[2] == x.bar.session_open_at)
        )
        # Feeding a verified endpoint with unavailable crossing facts resets a
        # previous M5 setup rather than carrying its cross into a fresh parent.
        mask[at] = row if eligible else {**row, 'golden': None, 'death': None}
    return setups(segment, mask, group, parent=parents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--group', choices=('intraday', 'trend'), required=True)
    parser.add_argument('--fee', type=int, choices=(1, 2), default=1)
    parser.add_argument('--slip', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    source_files = [Path(__file__).with_name(name) for name in (
        'subing_three_nested.py', 'subing_three_timing.py', 'subing_research_diagnostics.py',
        'subing_exit_comparison.py', 'subing_portfolio_replay.py',
    )]
    code = {**hashes(), **{path.name: sha(path) for path in source_files}}
    segments, frames, evidence = prepare_inputs(args.source)
    if args.fee != 1:
        segments = [replace(s, executions=tuple(stressed(s.executions, args.fee))) for s in segments]
    signals = {}
    for segment in segments:
        contract = segment.executions[0].bar.physical_contract
        signals[contract] = nested_m5(segment, frames[contract], args.group)
    row = evaluate(segments, signals, args.group, '5m-fresh-after-15m-v1',
                   payload_hash(evidence), args.fee, args.slip)
    if code != {**hashes(), **{path.name: sha(path) for path in source_files}}:
        raise ValueError('NESTED_ENTRY_CODE_CHANGED')
    dump(args.output, dict(kind='subing_m5_fresh_m15_parent_v1', parent_minutes=PARENT_MINUTES,
                           code_hashes=code, **evidence, run=row))


if __name__ == '__main__':
    main()
