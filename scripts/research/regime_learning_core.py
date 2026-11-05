"""Causal reference labels and deterministic, development-only blind sampling.

Research labels are proxies, never ground truth or strategy permissions.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import math

LABEL_VERSION = 'price_path_20_40_v1'
FREQUENCIES = ('1d', '30m', '60m')
QUOTAS = {'TREND_UP': 8, 'TREND_DOWN': 8, 'RANGE': 7, 'DISPUTED': 7}


def regression(closes: list[float]) -> dict:
    n = len(closes)
    mean = sum(closes) / n
    center = (n-1)/2
    xx = sum((i-center)**2 for i in range(n))
    yy = sum((c-mean)**2 for c in closes)
    xy = sum((i-center)*(c-mean) for i, c in enumerate(closes))
    return {'slope': xy/xx, 'r2': max(0.0, min(1.0, xy*xy/(xx*yy))) if yy else 0.0,
            'displacement': closes[-1]-closes[0]}


def reference_label(closes: list[float], atr: float | None) -> dict:
    if len(closes) < 40 or atr is None or not math.isfinite(atr) or atr <= 0:
        return {'label': 'UNKNOWN', 'reason': 'WARMUP_OR_ATR_INVALID'}
    if any(not math.isfinite(c) or c <= 0 for c in closes[-40:]):
        return {'label': 'UNKNOWN', 'reason': 'PRICE_INVALID'}
    paths = [regression(closes[-n:]) for n in (20, 40)]
    for p in paths:
        p['displacement_atr'] = p['displacement']/atr
    up = all(p['slope'] > 0 and p['displacement_atr'] >= 2 and p['r2'] >= .4 for p in paths)
    down = all(p['slope'] < 0 and p['displacement_atr'] <= -2 and p['r2'] >= .4 for p in paths)
    label = 'TREND_UP' if up else 'TREND_DOWN' if down else 'RANGE' if all(p['r2'] <= .2 for p in paths) else 'DISPUTED'
    return {'label': label, 'paths': paths}


def temporal_split(days: list[str]) -> dict:
    days = sorted(set(days))
    if len(days) < 20:
        raise ValueError('RESEARCH_DATES_INSUFFICIENT')
    test_index = len(days)*4//5
    development = days[:test_index]
    # Training expands, validation blocks occupy successive quarters of development.
    cuts = [len(development)*i//4 for i in (1, 2, 3, 4)]
    folds = [{'train_through': development[cuts[i]-1],
              'validation_from': development[cuts[i]],
              'validation_through': development[cuts[i+1]-1]} for i in range(3)]
    return {'test_from': days[test_index], 'test_through': days[-1], 'folds': folds,
            'window_bars': 64, 'purge_policy': 'every_input_bar_must_belong_to_same_split',
            'known_development': [{'symbol': 'jm', 'since': '2026-07-13', 'through': '2026-10-30'}]}


class BlindPool:
    """Bounded hash reservoir per frequency/label/product; no holdout admission."""
    def __init__(self, test_from: str):
        self.test_from = test_from
        self.pools: dict[tuple, list[dict]] = {}

    def offer(self, *, symbol: str, frequency: str, contract: str, sector: str,
              label: str, bars: list[dict]) -> None:
        if frequency not in FREQUENCIES or label not in QUOTAS or len(bars) != 64:
            return
        if any(b['day'] >= self.test_from for b in bars):
            return
        identity = f'{symbol}:{frequency}:{contract}:{bars[-1]["time"]}'
        rank = sha256(identity.encode()).hexdigest()
        sample = dict(id=rank[:20], rank=rank, symbol=symbol, frequency=frequency,
                      contract=contract, sector=sector, reference=label, bars=bars)
        key = (frequency, label, symbol)
        pool = self.pools.setdefault(key, [])
        if any(p['id'] == sample['id'] for p in pool):
            return
        pool.append(sample)
        pool.sort(key=lambda p: p['rank'])
        del pool[12:]

    def select(self) -> tuple[list[dict], dict]:
        selected = []
        deficits = {}
        for frequency in FREQUENCIES:
            used_products: Counter = Counter()
            used_sectors: Counter = Counter()
            chosen = []
            for label, quota in QUOTAS.items():
                available = [s for (f, c, _), pool in self.pools.items() if f == frequency and c == label for s in pool]
                count = 0
                while available and count < quota:
                    available.sort(key=lambda s: (used_sectors[s['sector']], used_products[s['symbol']], s['rank']))
                    s = available.pop(0)
                    if used_products[s['symbol']] >= 3:
                        continue
                    if any(p['symbol'] == s['symbol'] and p['contract'] == s['contract']
                           and not (p['bars'][-1]['time'] < s['bars'][0]['time'] or s['bars'][-1]['time'] < p['bars'][0]['time']) for p in chosen):
                        continue
                    chosen.append(s)
                    count += 1
                    used_products[s['symbol']] += 1
                    used_sectors[s['sector']] += 1
                if count != quota:
                    deficits[f'{frequency}:{label}'] = quota-count
            selected.extend(chosen)
        return sorted(selected, key=lambda s: s['rank']), deficits


def blind_payload(samples: list[dict], dataset_id: str) -> dict:
    """Allowlist only: reference labels/baseline/probabilities never enter blind HTML."""
    return {'dataset_id': dataset_id, 'label_version': LABEL_VERSION,
            'samples': [{k: s[k] for k in ('id', 'symbol', 'frequency', 'contract', 'bars')} for s in samples]}



def sample_partition(*, symbol: str, days: list[str], splits: dict) -> str:
    """No cross-boundary sequences and no already-seen JM in holdout evaluation."""
    if len(days) != 64 or days != sorted(days):
        return 'INELIGIBLE'
    for known in splits['known_development']:
        if symbol == known['symbol'] and any(known['since'] <= d <= known['through'] for d in days):
            return 'CASE_REGRESSION'
    if all(d < splits['test_from'] for d in days):
        return 'DEVELOPMENT'
    if all(splits['test_from'] <= d <= splits['test_through'] for d in days):
        return 'SEALED_TEST'
    return 'PURGED_BOUNDARY'
