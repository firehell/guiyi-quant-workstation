"""Offline hypothesis: retain confirmed box context through break and reentry.

Seeds come only from archived, then-known boxes. This is not a strategy gate.
The excursion envelope on reentry is a proposed rule, not owner-confirmed.
"""
from dataclasses import dataclass, asdict
from decimal import Decimal
from datetime import datetime
from pathlib import Path
import hashlib
import json

VERSION = 'subing_box_reentry_spike_v1'
D = Decimal

@dataclass(frozen=True)
class State:
    lower: Decimal | None = None
    upper: Decimal | None = None
    side: str | None = None
    count: int = 0
    confirmed: bool = False
    excursion_low: Decimal | None = None
    excursion_high: Decimal | None = None
    last_at: datetime | None = None
    contract: str | None = None


def step(s, *, at, contract, high, low, close, seed=None, valid=True):
    if at.tzinfo is None or (s.last_at and at <= s.last_at):
        raise ValueError('NON_MONOTONIC_OR_NAIVE_TIME')
    if s.contract and s.contract != contract:
        raise ValueError('CONTRACT_CHANGED')
    if not valid:
        return State(last_at=at, contract=contract), 'UNKNOWN'
    if not all(isinstance(x, D) and x.is_finite() and x > 0 for x in (high, low, close)) or not low <= close <= high:
        raise ValueError('INVALID_OHLC')
    if s.lower is None:
        if seed is None:
            return State(last_at=at, contract=contract), 'UNKNOWN'
        lower, upper = seed
        if not all(isinstance(x, D) and x.is_finite() and x > 0 for x in seed) or lower >= upper:
            raise ValueError('INVALID_SEED')
        return State(lower=lower, upper=upper, last_at=at, contract=contract), 'RANGE_SEEDED'
    side = 'UP' if close > s.upper else 'DOWN' if close < s.lower else None
    if s.confirmed:
        if side == s.side:
            return State(s.lower, s.upper, s.side, 4, True,
                         min(s.excursion_low, low), max(s.excursion_high, high), at, contract), 'BREAK_CONFIRMED'
        if side is not None:
            # A jump across both edges is not a return inside the old box.
            # No policy has been established for it; discard this hypothesis.
            return State(last_at=at, contract=contract), 'UNKNOWN'
        # A new wider envelope is available only on actual inside reentry;
        # prior points retain their original boundaries.
        lo = min(s.lower, s.excursion_low, low)
        hi = max(s.upper, s.excursion_high, high)
        return State(lower=lo, upper=hi, last_at=at, contract=contract), 'REENTERED_RANGE'
    if side is None:
        return State(lower=s.lower, upper=s.upper, last_at=at, contract=contract), 'BREAK_FAILED' if s.side else 'RANGE'
    if s.side and side != s.side:
        # Failed old attempt; the opposite-side attempt cannot count this bar.
        return State(lower=s.lower, upper=s.upper, last_at=at, contract=contract), 'BREAK_FAILED'
    count = s.count + 1 if side == s.side else 1
    lo = min(s.excursion_low, low) if s.excursion_low is not None else low
    hi = max(s.excursion_high, high) if s.excursion_high is not None else high
    return State(s.lower, s.upper, side, count, count == 4, lo, hi, at, contract), 'BREAK_CONFIRMED' if count == 4 else 'BREAK_PENDING'


def usable_record(record):
    return record is not None and record.get('regime') in ('RANGE', 'TREND_UP', 'TREND_DOWN') and record.get('reason') not in ('COVERAGE_INVALID', 'INPUT_INVALID', 'FACTOR_INPUT_INVALID', 'WARMUP')


def run():
    root = Path(__file__).resolve().parents[2]
    cards_path = root/'output/subing-demand-review-20261103-final/cards.json'
    cards = json.loads(cards_path.read_text())['cards']
    outputs = []; hashes = {str(cards_path.relative_to(root)): hashlib.sha256(cards_path.read_bytes()).hexdigest()}
    for c in cards:
        if c['kind'] != 'HISTORICAL_MODEL':
            continue
        envpath = root/f"output/subing-regime-add-20261103-001/{c['contract']}-environment.json"
        hashes[str(envpath.relative_to(root))] = hashlib.sha256(envpath.read_bytes()).hexdigest()
        # Start at displayed context, intentionally report insufficient seed
        # instead of claiming full physical-contract-prefix inference.
        env = {datetime.fromisoformat(r['time']): r['range_factor'] for r in json.loads(envpath.read_text()) if r['frequency']=='30m'}
        s = State(); points = []
        for b in c['bars']:
            at = datetime.fromisoformat(b['time'])
            assert at <= datetime.fromisoformat(c['at'])
            f = env.get(at)
            box = f.get('box') if f else None
            # Seed only a formation/active box known at this exact time, never
            # import a retrospective boundary or borrow another contract's box.
            seed = (D(box['lower']), D(box['upper'])) if box and f['phase'] in ('RANGE_ACTIVE','RANGE_EXPANDING') else None
            s, phase = step(s, at=at, contract=c['contract'], high=D(str(b['high'])), low=D(str(b['low'])), close=D(str(b['close'])), seed=seed, valid=usable_record(f))
            points.append({'time': b['time'], 'phase': phase, 'close': str(b['close']), 'state': asdict(s)})
        outputs.append({'case':c['id'], 'contract':c['contract'], 'points':points})
    out = root/'output/subing-box-reentry-20261104'
    out.mkdir(exist_ok=True)
    (out/'result.json').write_text(json.dumps({'version':VERSION,'sources':hashes,'scope':'64-bar seen case contexts; archived seeds; NOT full-prefix or execution validation', 'cases':outputs},default=str,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([{'case':x['case'], **x['points'][-1]} for x in outputs],default=str,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    run()
