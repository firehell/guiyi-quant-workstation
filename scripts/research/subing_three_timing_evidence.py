"""Independent timing-input parity and D1-veto evidence for the three-product study."""

import argparse
from collections import Counter
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

from scripts.research.subing_one_lot_stress import dump, sha
from scripts.research.subing_three_nested import nested_m5
from scripts.research.subing_three_timing import prepare_inputs, setups


def diagnostics(segments, frames):
    parity = 0
    counts = {}
    for segment in segments:
        contract = segment.executions[0].bar.physical_contract
        clocks = frames[contract]
        m30 = clocks['30m']
        for at, raw in segment.observations.items():
            bar = raw['m30']
            if bar is None:
                continue
            point = m30[at]
            actual = (point['golden'], point['death'], point['tier'])
            expected = (bar['near_zero_golden'], bar['near_zero_death'], bar['volume_tier'])
            if actual != expected or any(
                (fresh is None) != (stored is None) or
                (fresh is not None and D(str(fresh)) != D(stored))
                for fresh, stored in ((point['angle'], bar['minute_angle']),
                                      (point['ema'], bar['ema21']))
            ):
                raise ValueError(f'BASE_M30_FACTOR_PARITY_CHANGED:{contract}:{at}')
            parity += 1
        neutral = replace(segment, observations={
            at: dict(obs, daily_direction='NEUTRAL')
            for at, obs in segment.observations.items()
        })
        row = counts[contract] = {}
        for group in ('intraday', 'trend'):
            row[group] = {}
            for frequency, points in clocks.items():
                selected = setups(segment, points, group)
                if frequency == '5m':
                    selected = nested_m5(segment, clocks, group)
                d1 = Counter()
                for item in selected.values():
                    original = item['d1']
                    same = original == ('UP' if item['side'] == 'LONG' else 'DOWN')
                    d1['same' if same else original.lower()] += 1
                row[group][frequency] = dict(qualified=len(selected), d1=dict(d1))
                if group == 'intraday':
                    # Remove only the daily veto. This first-setup screen has
                    # its own cross consumption, so counts are not subtractions.
                    unvetoed = (nested_m5(neutral, clocks, group) if frequency == '5m'
                                else setups(neutral, points, group))
                    counter = Counter()
                    for at, item in unvetoed.items():
                        direction = segment.observations[at]['daily_direction']
                        same = direction == ('UP' if item['side'] == 'LONG' else 'DOWN')
                        counter['same' if same else 'opposed' if direction in ('UP', 'DOWN')
                                else direction.lower()] += 1
                    row[group][frequency]['first_setup_without_d1_veto'] = dict(counter)
    return dict(m30_parity_bars=parity, contracts=counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    segments, frames, evidence = prepare_inputs(args.source)
    dump(args.output, dict(
        **diagnostics(segments, frames), **evidence,
        code_sha256=sha(Path(__file__)),
    ))


if __name__ == '__main__':
    main()
