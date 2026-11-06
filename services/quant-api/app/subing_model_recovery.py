"""Versioned Canonical catch-up for the existing development run.

Historical bars update indicators only. They never enter AccountEngine.step.
An account with exposure, obligations or a latched failure stays protected.
"""
from copy import deepcopy
from datetime import datetime

from app.subing_model.pipeline import bar
from app.subing_model.store import digest
from guiyi_quant.subing_decision import _wire
from guiyi_quant.indicators.subing_conditions import EntryWindow

POLICY = 'canonical_indicator_catchup_no_execution_v1'


def flat_without_obligations(account):
    if account is None:
        return True
    if account.halted or account.protection_observation:
        return False
    if account.engine is None:
        return True
    engine = account.engine
    model = engine.model
    return not (engine.layers or model.layers or model.pending or model.clear_reasons
                or model.exit_layers or model.day_halted or model.pullback)


def apply_event(pipe, event):
    if event.get('recovery_policy') is None:
        pipe.apply(event)
        return
    if event['recovery_policy'] != POLICY:
        raise ValueError('MODEL_RECOVERY_POLICY_UNKNOWN')
    now = datetime.fromisoformat(event['observed_at'])
    before = deepcopy(pipe.account.state()) if pipe.account else None
    can_resume = flat_without_obligations(pipe.account)
    if event['account_can_resume'] is not can_resume:
        raise ValueError('MODEL_RECOVERY_ACCOUNT_DRIFT')
    for product, update in event['products'].items():
        f = pipe.factors[product]
        row = pipe.products[product]
        if update['contract'] != row['contract']:
            raise ValueError('MODEL_RECOVERY_ROLLOVER_REQUIRES_REVIEW')
        for frequency in ('1d', '60m', '30m'):
            rows = update['bars'][frequency]
            if digest(rows) != update['proofs'][frequency]['hash']:
                raise ValueError('MODEL_RECOVERY_SOURCE_HASH_INVALID')
            for raw in rows:
                b = bar(raw)
                if b.bar_end > now:
                    raise ValueError('MODEL_RECOVERY_FUTURE_BAR')
                last = f.trends[frequency].last_end
                if last is None or b.bar_end > last:
                    f.step(frequency, b)
                    if frequency == '30m':
                        pipe.chart[product].append(_wire(dict(
                            at=b.bar_end, open=b.open, high=b.high, low=b.low,
                            close=b.close, ema21=f.frame['ema21'], **(f.structure_point or {}))))
                        pipe.chart[product] = pipe.chart[product][-128:]
        # The complete validated 1m source anchors the observed close; it is
        # intentionally never passed to the account or represented as Live.
        minutes = update['bars']['1m']
        if not minutes or digest(minutes) != update['proofs']['1m']['hash']:
            raise ValueError('MODEL_RECOVERY_MINUTES_INVALID')
        latest = bar(minutes[-1])
        if latest.bar_end > now:
            raise ValueError('MODEL_RECOVERY_FUTURE_BAR')
        for frequency in ('1m', '30m', '60m'):
            rows = update['bars'][frequency]
            if not rows:
                raise ValueError('MODEL_RECOVERY_PREFIX_EMPTY')
            pipe.last[(product, frequency)] = bar(rows[-1]).bar_end
        row.update(bar_end=latest.bar_end.isoformat(), observed_at=now.isoformat(),
                   close=str(latest.close), warmup_only=False,
                   regime=f.frame['regime'] if f.frame else 'UNKNOWN',
                   daily=f.daily[-1] if f.daily else None, hourly=f.hourly,
                   structure=_wire(f.structure_point), execution_enabled=False,
                   source_kind='CANONICAL_INDICATOR_RECOVERY',
                   status='WARMUP_INCOMPLETE' if row['warmup_errors'] else 'OBSERVING')
    if pipe.account:
        if can_resume and pipe.account.engine:
            model = pipe.account.engine.model
            model.windows = {s: EntryWindow(model.contract) for s in ('LONG', 'SHORT')}
            model.reset_after = now
        elif not can_resume:
            pipe.account.halted = pipe.account.halted or 'OBSERVATION_INTERRUPTED_REVIEW_REQUIRED'
    pipe.source_day = event['source_day']
    pipe.source_cursor = event['cursor']
    pipe.sequence += 1
    # Keep a separate recovery record: the last account valuation and decision
    # stay at their original knowledge time. No invented zero-PnL valuation.
    after = pipe.account.state() if pipe.account else None
    protected = ('cash', 'equity', 'fees', 'net_pnl', 'fills', 'open_layers', 'summary')
    if before and any(before.get(k) != after.get(k) for k in protected):
        raise ValueError('MODEL_RECOVERY_ACCOUNT_CHANGED')
    pipe.last_outcome = _wire(dict(run_identity_hash=digest(pipe.identity),
        state_hash=digest(pipe.state()), model_fills=[], model_decisions=[],
        recovery_policy=POLICY, account_can_resume=can_resume))
    if event.get('outcome') is not None and event['outcome'] != pipe.last_outcome:
        raise ValueError('MODEL_OUTCOME_REPLAY_CONFLICT')


def consumed_bars(identity, events):
    """All originally consumed values, not merely final closes or watermarks."""
    known = {}

    def add(product, frequency, raw):
        key = (product, frequency)
        b = bar(raw)
        rows = known.setdefault(key, {})
        if b.bar_end in rows and rows[b.bar_end] != b:
            raise ValueError('MODEL_CONSUMED_INPUT_CONFLICT')
        rows[b.bar_end] = b

    for product, prepared in identity['prepared'].items():
        for frequency, rows in prepared['warmup'].items():
            for raw in rows:
                add(product, frequency, raw)
    for event in [dict(observations=identity['bootstrap']), *events]:
        for row in event.get('observations', []):
            _, _, product, frequency = row['channel'].split(':')
            add(product, frequency, row['data'])
        for product, rows in event.get('daily_updates', {}).items():
            for raw in rows:
                add(product, '1d', raw)
        for product, update in event.get('products', {}).items():
            for frequency, rows in update['bars'].items():
                for raw in rows:
                    add(product, frequency, raw)
    return known


def verify_overlap(known, rows):
    current = {b.bar_end: b for b in rows}
    if any(current.get(at) != b for at, b in known.items()):
        raise ValueError('MODEL_RECOVERY_PRIOR_CONFLICT')
