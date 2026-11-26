"""Regenerate/check visual-only MACD using the registered TA-Lib calculation."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'packages/quant-core'))
from guiyi_quant.compute import (  # noqa: E402
    REGISTRY, BarSeries, CompletedBar, FeatureRequest, SeriesIdentity, Status,
)


def generate() -> str:
    source = """
import {buildNewowFixtureEnvelopeForTest as build} from './apps/quant-web/e2e/newow-product.helpers.mjs';
console.log(JSON.stringify(Object.fromEntries(['trend','oscillation','main_rise'].flatMap(s=>['1d','1w','60m'].flatMap(f=>[false,true].map(recordsHistory=>[s+':'+f+(recordsHistory?':records':''),build('chart',s,f,false,null,{visualRich:true,recordsHistory}).chart.value.bars]))))))
"""
    inputs = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', source], cwd=ROOT, text=True))
    result = {}
    for key, bars in inputs.items():
        frequency = key.split(':')[1]
        groups = {}
        for bar in bars:
            groups.setdefault(bar['calculation_segment_id'], []).append(bar)
        segments = []
        for sid, items in groups.items():
            physical_contract = items[0]['physical_contract']
            completed = []
            for bar in items:
                end = datetime.fromisoformat(bar['bar_end'])
                trading_day = date.fromisoformat(bar['trading_day'])
                completed.append(CompletedBar(
                    bar['physical_contract'], sid, trading_day, f'historical:{trading_day}',
                    end, end, end, None, None, None, float(bar['close']), None, 'VALID',
                ))
            series = BarSeries(
                SeriesIdentity('rb', physical_contract, sid, frequency, f'fixture:{key}'),
                tuple(completed),
            )
            (values,) = REGISTRY.calculate(
                series, (FeatureRequest('macd'),), as_of=completed[-1].bar_end, use='web',
            )
            if values.status not in (Status.READY, Status.WARMING):
                raise ValueError(f'invalid MACD fixture input for {key}:{sid}')
            ready = values.status is Status.READY
            data = {
                name: [
                    dict(
                        bar_end=bar['bar_end'],
                        value=point.values[name] if point.values is not None else None,
                        ready=point.status is Status.READY, valid=True,
                        reason='warming_up' if point.status is Status.WARMING else None,
                    )
                    for bar, point in zip(items, values.points, strict=True)
                ]
                for name in ('dif', 'dea', 'histogram')
            }
            segments.append(dict(physical_contract=items[0]['physical_contract'], segment_id=sid,
                                 bar_ends=[b['bar_end'] for b in items],
                                 status=dict(status='ready' if ready else 'warming',
                                             evidence_status='ACTIVE_CODE_VERIFIED',
                                             reason_code=None if ready else 'NEWOW_MACD_WARMING'),
                                 data=data))
        result[key] = dict(component='macd', formal_signal_eligible=False, page_parity=False, repainting=False,
                           formula_version=values.identity.formula_version, parameters=dict(values.parameters),
                           parameters_hash=values.identity.parameters_hash,
                           display_adapter_version='guiyi_newow_macd_display_v2', allowed_uses=['research_display'],
                           fixture_input=[[b['bar_end'], b['physical_contract'], b['calculation_segment_id'], b['close']] for b in bars],
                           segments=segments)
    return json.dumps(result, separators=(',', ':')) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = Path(__file__).with_name('newow-rich-macd.json')
    output = generate()
    if args.check:
        if output != target.read_text():
            raise SystemExit('MACD visual fixture drift: regenerate with the registered TA-Lib calculation')
        print('MACD fixture matches registered TA-Lib for 18 identity and history scenarios')
    else:
        target.write_text(output)
