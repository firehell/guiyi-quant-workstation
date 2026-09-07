"""Regenerate/check visual-only MACD via the existing kernel; no provider access."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'packages/quant-core'))
from guiyi_quant.indicators.macd import macd_series  # noqa: E402


def generate() -> str:
    source = """
import {buildNewowFixtureEnvelopeForTest as build} from './apps/quant-web/e2e/newow-product.helpers.mjs';
console.log(JSON.stringify(Object.fromEntries(['trend','oscillation','main_rise'].flatMap(s=>['1d','1w','60m'].map(f=>[s+':'+f,build('chart',s,f,false,null,{visualRich:true}).chart.value.bars])))))
"""
    inputs = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', source], cwd=ROOT, text=True))
    result = {}
    for key, bars in inputs.items():
        groups = {}
        for bar in bars:
            groups.setdefault(bar['segment_id'], []).append(bar)
        segments = []
        for sid, items in groups.items():
            values = macd_series([float(b['close']) for b in items], 12, 26, 9,
                                 ema_seed_policy='sma_window', histogram_scale=2,
                                 bar_ends=[b['bar_end'] for b in items])
            segments.append(dict(physical_contract=items[0]['physical_contract'], segment_id=sid,
                                 bar_ends=[b['bar_end'] for b in items],
                                 status=dict(status='ready', evidence_status='ACTIVE_CODE_VERIFIED', reason_code=None),
                                 data={name: [asdict(p) for p in getattr(values, name).points]
                                       for name in ['dif', 'dea', 'histogram']}))
        result[key] = dict(component='macd', formal_signal_eligible=False, page_parity=False, repainting=False,
                           formula_version=values.indicator_version, parameters=values.parameters,
                           parameters_hash=values.parameters_hash,
                           display_adapter_version='guiyi_newow_macd_display_v1', allowed_uses=['research_display'],
                           fixture_input=[[b['bar_end'], b['physical_contract'], b['segment_id'], b['close']] for b in bars],
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
            raise SystemExit('MACD visual fixture drift: regenerate with the existing kernel')
        print('MACD fixture matches existing kernel for 9 identities')
    else:
        target.write_text(output)
