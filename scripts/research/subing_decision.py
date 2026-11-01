"""Offline phase-3.2 decision replay. Explicit inputs only; never synthesize fills."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path


def replay(packet):
    from guiyi_quant.subing_decision import DecisionModel

    if not isinstance(packet, dict) or set(packet) != {'kind', 'contract', 'run_id', 'source_note', 'events'}:
        raise ValueError('REPLAY_PACKET_INVALID')
    if packet['kind'] not in ('ENGINEERING_SCENARIO', 'EXPLICIT_OBSERVATION_REPLAY'):
        raise ValueError('REPLAY_SOURCE_INVALID')
    if not isinstance(packet['source_note'], str) or not packet['source_note'].strip():
        raise ValueError('REPLAY_SOURCE_REQUIRED')
    if not isinstance(packet['events'], list) or not packet['events']:
        raise ValueError('REPLAY_EVENTS_REQUIRED')
    model = DecisionModel(packet['contract'], packet['run_id'])
    rows, seen = [], set()
    for event in packet['events']:
        before = model.state()
        row = model.apply(event)
        if event['event_id'] in seen:
            row = dict(event_id=event['event_id'], before=before, facts=event,
                       actions=[{'kind': 'DUPLICATE_IGNORED'}], after=model.state())
        seen.add(event['event_id'])
        rows.append(row)
    checkpoint = model.checkpoint()
    restored = DecisionModel.restore(checkpoint)
    if restored.checkpoint() != checkpoint:
        raise ValueError('REPLAY_RESTORE_MISMATCH')
    return dict(kind=packet['kind'], source_note=packet['source_note'], contract=packet['contract'],
                run_id=packet['run_id'], rows=rows, checkpoint=checkpoint,
                scope='离线决策回放；确认事件由输入提供，不是撮合、历史绩效或真实成交证明。')


def render(data):
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    return Path(__file__).with_suffix('.html').read_text().replace('__DATA__', payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('REPLAY_OUTPUT_EXISTS')
    raw = args.input.read_bytes()
    packet = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
    result = replay(packet)
    from guiyi_quant import subing_decision
    from guiyi_quant.indicators import subing_conditions
    result['input_sha256'] = sha256(raw).hexdigest()
    root = Path(__file__).resolve().parents[2]
    result['code_sha256'] = {p.resolve().relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest() for p in
                             (Path(__file__), Path(__file__).with_suffix('.html'), Path(subing_decision.__file__), Path(subing_conditions.__file__))}
    page = render(result)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'replay.json').write_text(json.dumps(result, ensure_ascii=False, allow_nan=False))
    (args.output / 'index.html').write_text(page)
    print(json.dumps({'status': 'DECISION_REPLAY_COMPLETE', 'events': len(result['rows']),
                      'kind': result['kind'], 'performance_computed': False}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'status': 'FAILED', 'code': 'DECISION_REPLAY_INVALID_OR_UNAVAILABLE'}))
        raise SystemExit(2) from None
