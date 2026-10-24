"""Exact closed-night historical repair; never repairs original Live observations.

The existing manager owns the lock, provider, immutable publisher and commit seam.
This module only plans the smaller Session scope and prepares its merged candidates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
import hashlib
import json
import re

from app.market_data.aggregation import aggregate_from_1m, expected_intraday_ends
from app.market_data.domain import BarFrequency, DatasetKey
from app.market_data.operational_universe import load_active_products
from app.market_data.session_clock import SHANGHAI
from app.market_data.storage import PublishRequest, StorageError
from app.market_data.source_quality import NonpositiveCloseFact, PriceUnavailableFact


@dataclass(frozen=True, slots=True)
class ContractSessionRepairRequest:
    symbol: str
    contract: str
    trading_day: date
    session_end: datetime
    expected_plan_sha256: str | None = None
    apply: bool = False


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _snapshot(manager, key, day):
    rows = tuple(p for p in manager.catalog.all_partitions(key) if (p.year, p.month) == (day.year, day.month))
    if len(rows) > 1:
        raise StorageError('PARTITION_CATALOG_MISMATCH')
    if not rows:
        return (), (), None
    bars, quality = manager.store.read_catalog_partition_quality(rows[0])
    return bars, quality, {
        'revision': manager._partition_revision(rows[0]),
        'file_sha256': hashlib.sha256(rows[0].file_path.read_bytes()).hexdigest(),
        'bars_sha256': _hash([b.as_record() for b in bars]),
        'quality_sha256': _hash([q.to_record() for q in quality]),
    }


def _plan(manager, request, now):
    if request.session_end.tzinfo is None or request.session_end.utcoffset() is None:
        raise ValueError('SESSION_REPAIR_TIMEZONE_REQUIRED')
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('SESSION_REPAIR_TIMEZONE_REQUIRED')
    end = request.session_end.astimezone(UTC)
    symbol, contract = request.symbol.strip().lower(), request.contract.strip().upper()
    if symbol not in load_active_products():
        raise ValueError('SESSION_REPAIR_SYMBOL_INACTIVE')
    fact = manager.catalog.contract_fact(symbol, contract)
    day = request.trading_day
    if fact.provider != 'rqdata' or not fact.listed_date <= day < fact.expired_date:
        raise ValueError('SESSION_REPAIR_CONTRACT_INVALID')
    if manager.coverage.contract_trading_days(fact, day, day) != (day,):
        raise ValueError('SESSION_REPAIR_TRADING_DAY_INVALID')
    key = DatasetKey('contract', symbol, contract, BarFrequency.M1)
    all_sessions = manager.coverage.contract_session_windows(key, day)
    # Night Sessions precede the civil trading date; daytime breaks are not an
    # incomplete-day maintenance escape hatch.
    night = tuple(s for s in all_sessions if s.start.astimezone(SHANGHAI).date() < day)
    if not night or end != night[-1].end or end > now.astimezone(UTC):
        raise ValueError('SESSION_REPAIR_CLOSED_NIGHT_REQUIRED')
    if any(s.end > end for s in night):
        raise ValueError('SESSION_REPAIR_SESSION_INVALID')
    ends = expected_intraday_ends(night, BarFrequency.M1)
    h1_ends = expected_intraday_ends(night, BarFrequency.H1)
    # Independently bind Calendar/Session endpoint ownership, not civil dates.
    authoritative = manager.coverage.expected_bar_ends_for_trading_days(key, (day,))
    if tuple(t for t in authoritative if night[0].start < t <= end) != ends:
        raise ValueError('SESSION_REPAIR_ENDPOINT_OWNERSHIP_INVALID')
    h1_key = DatasetKey('contract', symbol, contract, BarFrequency.H1)
    snapshots = {k: _snapshot(manager, k, day) for k in (key, h1_key)}
    for k, scope in ((key, ends), (h1_key, h1_ends)):
        bars, quality, _revision = snapshots[k]
        if any(b.trading_day != day for b in bars if b.bar_end in scope):
            raise ValueError('SESSION_REPAIR_EXISTING_TRADING_DAY_CONFLICT')
        if any(q.bar_end in scope for q in quality):
            raise ValueError('SESSION_REPAIR_SOURCE_QUALITY_CONFLICT')
    missing = {k: tuple(t for t in scope if t not in {b.bar_end for b in snapshots[k][0]})
               for k, scope in ((key, ends), (h1_key, h1_ends))}
    identity = {
        'schema_version': 1, 'command': 'data.contract-session-repair',
        'symbol': symbol, 'contract': contract, 'contract_fact': asdict(fact),
        'trading_day': day.isoformat(), 'session_end': end.isoformat(),
        'sessions': [{'start': s.start.isoformat(), 'end': s.end.isoformat()} for s in night],
        'expected_1m': [t.isoformat() for t in ends],
        'expected_60m': [t.isoformat() for t in h1_ends],
        'partitions': {k.frequency.value: snapshots[k][2] for k in snapshots},
        'missing': {k.frequency.value: [t.isoformat() for t in missing[k]] for k in missing},
    }
    payload = {
        **identity, 'plan_sha256': _hash(identity), 'status': 'planned',
        'readonly': True, 'provider_requests': 0,
        'provider_request_count': int(bool(missing[key])),
        'missing_1m': len(missing[key]), 'missing_60m': len(missing[h1_key]),
        'applied': 0, 'failed': 0, 'blocked': 0, 'publications': [],
    }
    return payload, (key, h1_key, night, ends, h1_ends, snapshots, missing)


def _valid_prices(bar):
    values = (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.turnover, bar.open_interest)
    return (all(v.is_finite() for v in values if v is not None)
            and min(bar.open, bar.high, bar.low, bar.close) > 0
            and bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
            and all(v >= 0 for v in (bar.volume, bar.turnover, bar.open_interest) if v is not None))


def run_session_repair(manager, request, *, now=None, before_apply=None):
    from app.market_data.historical_data_manager import (
        BarFetchRequest, _Target, _is_global_failure, _release_maintenance_lease,
    )

    now = now or datetime.now(UTC)
    if not request.apply and request.expected_plan_sha256 is not None:
        raise ValueError('READONLY_PLAN_REQUIRED')
    if request.apply and (not isinstance(request.expected_plan_sha256, str)
                          or re.fullmatch('[0-9a-f]{64}', request.expected_plan_sha256) is None):
        raise ValueError('SESSION_REPAIR_PLAN_HASH_REQUIRED')
    plan, context = _plan(manager, request, now)
    if not request.apply:
        return plan
    lease = manager.catalog.acquire_maintenance_lock()
    if lease is None:
        return {**plan, 'status': 'blocked', 'readonly': False, 'blocked': 1, 'reason_code': 'maintenance_locked'}
    applied = requests = 0
    manager.publication_evidence = []
    try:
        plan, context = _plan(manager, request, now)
        if plan['plan_sha256'] != request.expected_plan_sha256:
            raise ValueError('SESSION_REPAIR_PLAN_CHANGED')
        key, h1_key, sessions, ends, h1_ends, snapshots, missing = context
        try:
            existing, quality, _ = snapshots[key]
            merged = {b.bar_end: b for b in existing}
            if missing[key]:
                requests = 1
                # The native date request returns the whole night anyway. Check
                # retained overlap rather than silently accepting a revision.
                batches = manager._fetch_many((BarFetchRequest(key, ends, (request.trading_day,) * len(ends)),))
                if len(batches) != 1:
                    raise StorageError('PROVIDER_BATCH_COUNT_MISMATCH')
                batch = batches[0]
                if batch.price_unavailable or (batch.source_key is not None or batch.requested_ends is not None) and (
                        batch.source_key != key or batch.requested_ends != ends):
                    raise StorageError('PROVIDER_BATCH_IDENTITY_MISMATCH')
                seen = set()
                for bar in batch.bars:
                    if bar.bar_end in seen:
                        raise StorageError('PROVIDER_BAR_DUPLICATE')
                    seen.add(bar.bar_end)
                    if bar.bar_end not in ends or bar.trading_day != request.trading_day or not _valid_prices(bar):
                        raise StorageError('SESSION_REPAIR_SOURCE_INVALID')
                    if bar.bar_end in merged and merged[bar.bar_end] != bar:
                        raise StorageError('SESSION_REPAIR_EXISTING_VALUE_CONFLICT')
                    merged[bar.bar_end] = bar
                if seen != set(ends):
                    raise StorageError('SOURCE_1M_INCOMPLETE')
            source = tuple(merged[t] for t in ends)
            if any(b.trading_day != request.trading_day or not _valid_prices(b) for b in source):
                raise StorageError('SESSION_REPAIR_SOURCE_INVALID')
            derived = aggregate_from_1m(source, target_frequency=BarFrequency.H1, sessions=sessions)
            if tuple(b.bar_end for b in derived) != h1_ends:
                raise StorageError('TARGET_WINDOW_INCOMPLETE')
            old_h1 = {b.bar_end: b for b in snapshots[h1_key][0]}
            if any(b.bar_end in old_h1 and old_h1[b.bar_end] != b for b in derived):
                raise StorageError('SESSION_REPAIR_EXISTING_VALUE_CONFLICT')
            candidates = (
                (key, tuple(merged[t] for t in sorted(merged)), quality, source),
                (h1_key, tuple(sorted({**old_h1, **{b.bar_end: b for b in derived}}.values(), key=lambda b: b.bar_end)), snapshots[h1_key][1], source),
            )
            if before_apply is not None and any(missing.values()):
                before_apply()
            for candidate_key, bars, facts, inputs in candidates:
                if not missing[candidate_key]:
                    continue
                # Preserve schema v1 provenance so the current Runtime remains a
                # compatible reader. The scope is bound into input_sha256 and the
                # returned plan/publication record carries the exact Session.
                source_type = 'canonical_1m' if candidate_key == h1_key else (
                    'rqdata' if type(manager.provider).__module__ == 'app.market_data.rqdata_adapter' else 'historical_provider')
                proof = {'version': 1, 'input_source': source_type,
                         'input_sha256': _hash({'plan_sha256': plan['plan_sha256'], 'bars': [b.as_record() for b in inputs]})}
                expected = tuple(sorted({b.bar_end for b in bars} | {q.bar_end for q in facts}))
                partition = manager.store.publish(PublishRequest(
                    candidate_key, request.trading_day.year, request.trading_day.month, bars, expected,
                    price_unavailable=tuple(q for q in facts if isinstance(q, PriceUnavailableFact)),
                    nonpositive_close=tuple(q for q in facts if isinstance(q, NonpositiveCloseFact)),
                    publication_provenance=proof,
                ))
                target = _Target(candidate_key, request.trading_day.year, request.trading_day.month,
                                 tuple(b.bar_end for b in bars), missing[candidate_key], snapshots[candidate_key][0])
                manager._commit_partition(partition, target)
                applied += 1
        except Exception as exc:
            if _is_global_failure(exc):
                raise
            manager.catalog.session.rollback()
            code = getattr(exc, 'code', None)
            return {**plan, 'status': 'partial' if applied else 'failed', 'readonly': False,
                    'applied': applied, 'failed': 1, 'provider_requests': requests,
                    'reason_code': code if isinstance(code, str) and re.fullmatch('[A-Z][A-Z0-9_]+', code) else 'SESSION_REPAIR_FAILED',
                    'publications': list(manager.publication_evidence)}
        return {**plan, 'status': 'passed', 'readonly': False, 'applied': applied,
                'provider_requests': requests, 'publications': list(manager.publication_evidence)}
    finally:
        _release_maintenance_lease(lease)
