"""Read only the recorded P6 group files and compute the acceptance table."""
from itertools import groupby
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
GROUPS = ('60-16-alone', '60-16-concurrent', '70-20-alone', '70-20-concurrent')

def host_counters(path):
    items = path.read_text().splitlines()
    swap = next(line for line in items if line.startswith('vm.swapusage'))
    counters = dict(re.findall(r'(Swapins|Swapouts|Pageins|Pageouts):\s*(\d+)', '\n'.join(items)))
    devices = items[-3].split()
    disk_fields = items[-1].split()
    return {
        'swap_used_mb': float(re.search(r'used = ([.\d]+)M', swap)[1]),
        **{key: int(value) for key, value in counters.items()},
        'disk_transfer_mb': {device: float(disk_fields[slot * 3 + 2]) for slot, device in enumerate(devices)},
    }

def nearest(values, q):
    return sorted(values)[math.ceil(q * len(values)) - 1]

def analyze(group):
    summary_path = ROOT / group / 'summary.json'
    trace_path = ROOT / group / 'batches.jsonl'
    if not trace_path.exists():
        return {'group': group, 'state': 'not_started'}
    batches = [json.loads(line) for line in trace_path.read_text().splitlines()]
    if not summary_path.exists():
        return {'group': group, 'state': 'in_progress_or_incomplete', 'batches': len(batches)}
    state = json.loads(summary_path.read_text())
    before, after = [host_counters(ROOT / f'{group}-host-{when}.txt') for when in ('before', 'after')]
    values = [item['seconds'] for item in batches]
    peaks = [r for r in batches if r['kind'].startswith('synthetic')]
    rep = [r for r in batches if r['kind'].startswith('representative')]
    rep_endpoint_wall = [max(r['seconds'] for r in rows) for _, rows in groupby(rep, key=lambda r: r['end'])]
    assert len(batches) == state['batches'] == 110 and len(peaks) == state['peaks'] == 20
    assert all(p['logical_decisions'] == state['market'] * 18 for p in peaks)
    p95, p99 = nearest(values, .95), nearest(values, .99)
    assert p95 == state['p95_seconds'] and p99 == state['p99_seconds']
    return {
        'group': group, 'state': 'complete', 'batch_count': len(batches), 'peak_count': len(peaks),
        'representative_minutes': state['representative_minutes'],
        'p95_seconds': p95, 'p99_seconds': p99, 'max_seconds': max(values),
        'representative_endpoint_max_seconds': max(rep_endpoint_wall),
        'peak_over_60s': sum(record['seconds'] >= 60 for record in peaks),
        'batch_over_5s': sum(value > 5 for value in values),
        'batch_over_10s': sum(value > 10 for value in values),
        'latency_pass': p95 <= 5 and p99 <= 10,
        'research_overlap_batches': sum(record['research_alive_before'] for record in batches),
        'research_wall_seconds': [r['wall_seconds'] for r in state['research']],
        'callback_drain_seconds': state['native_callback_drain_seconds'],
        'trading_rss_mib': state['after']['max_rss_bytes'] / 2**20,
        'research_rss_mib': state['research_max_rss_bytes'] / 2**20 if state['research_max_rss_bytes'] else None,
        'trading_cpu_seconds': state['after']['cpu_seconds'] - state['before']['cpu_seconds'],
        'pg_physical_block_reads': state['after']['pg_blks_read'] - state['before']['pg_blks_read'],
        'pg_buffer_hits': state['after']['pg_blks_hit'] - state['before']['pg_blks_hit'],
        'disk_total_transfer_mb': {device: val - before['disk_transfer_mb'][device]
                                   for device, val in after['disk_transfer_mb'].items()},
        'swapouts_delta': after['Swapouts'] - before['Swapouts'],
        'checks': state['checks'],
    }

if __name__ == '__main__':
    print(json.dumps([analyze(g) for g in GROUPS], indent=2))
