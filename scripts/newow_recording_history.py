#!/usr/bin/env python3
"""Serial, exact historical plans for the Newow recording warm-up scope."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import fcntl
from datetime import UTC, date, datetime
import json
import os
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.market_data.operational_universe import load_active_products, load_operational_products
from app.reference_trading.composition import open_historical_reference_components
from app.reference_trading.models import ReferenceStream
from app.reference_trading.repository import ReferenceRepository
from app.reference_trading.newow_bootstrap import validate_product_scope
from app.reference_trading.planning import (
    HistoricalReferenceRequest, HistoricalStreamRequest, WorkBudget,
    plan_from_dict, plan_to_dict,
)
from app.guiyi_cli.reference_commands import _jsonable
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
from guiyi_quant.newow.product_contracts import ProductStrategy
from app.market_data.newow.product_release import candidate_input_quality_policy
from scripts.reference_trading_p9_manifest import _newow


def _read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64_000_000:
        raise ValueError('HISTORY_PRIOR_RESULT_REQUIRES_READBACK')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError, UnicodeError) as error:
        raise ValueError('HISTORY_PRIOR_RESULT_REQUIRES_READBACK') from error
    if not isinstance(value, dict):
        raise ValueError('HISTORY_PRIOR_RESULT_REQUIRES_READBACK')
    return value


def _atomic_json(path, value, *, exclusive=True):
    """Publish complete bytes durably; reservation never replaces older evidence."""
    if path.is_symlink():
        raise ValueError('HISTORY_PRIOR_RESULT_REQUIRES_READBACK')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(value, file, sort_keys=True, separators=(',', ':'))
            file.flush()
            os.fsync(file.fileno())
        if exclusive:
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise ValueError('HISTORY_PRIOR_RESULT_REQUIRES_READBACK') from error
        else:
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def product_apply_lock(out):
    """Nonblocking process lock covers reservation, mutation and receipt readback."""
    fd = os.open(out / '.history-apply.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('HISTORY_EXECUTION_BUSY') from error
        yield
    finally:
        os.close(fd)


def _intent(plan):
    if len(plan.streams) != 1:
        raise ValueError('HISTORY_PLAN_SCOPE_DRIFT')
    item = plan.streams[0]
    return {'version': 'newow_history_apply_intent_v1', 'plan_hash': plan.plan_hash,
            'stream_id': item.request.identity.stream_id, 'operation': plan.operation,
            'source_token': item.source_token, 'dependency_digest': item.dependency_digest,
            'input_manifest_sha256': item.input_manifest_sha256}


def _prior_receipt(plan, *, intent, receipt, read_state=None):
    if not intent.exists() and not intent.is_symlink() and not receipt.exists() and not receipt.is_symlink():
        return None
    if not intent.is_file() or not receipt.is_file() or _read_json(intent) != _intent(plan):
        raise ValueError('HISTORY_PRIOR_RESULT_REQUIRES_READBACK')
    value = _read_json(receipt)
    streams = value.get('streams')
    if (value.get('status') not in {'completed', 'noop'} or value.get('plan_hash') != plan.plan_hash
            or not isinstance(streams, list) or len(streams) != 1
            or not isinstance(streams[0], dict)
            or streams[0].get('stream_id') != plan.streams[0].request.identity.stream_id
            or streams[0].get('status') not in {'completed', 'noop'}):
        raise ValueError('HISTORY_PRIOR_RESULT_REQUIRES_READBACK')
    item = streams[0]
    state = (read_state or ReferenceRepository(SessionLocal).read_state)(_intent(plan)['stream_id'])
    snapshot = item.get('snapshot')
    if (state.revision_status != 'active'
            or item.get('active_revision_id') != state.revision_id
            or not isinstance(snapshot, dict) or snapshot.get('stream_id') != state.stream.stream_id
            or snapshot.get('revision_id') != state.revision_id
            or snapshot.get('seq') != state.checkpoint.seq
            or state.dependency_digest != plan.streams[0].dependency_digest):
        raise ValueError('HISTORY_PRIOR_RESULT_REQUIRES_READBACK')
    return value


def apply_exact_plan(service, plan, *, intent, receipt, read_state=None):
    """Reserve once before mutation. Missing terminal evidence always stops retry."""
    prior = _prior_receipt(plan, intent=intent, receipt=receipt, read_state=read_state)
    if prior is not None:
        return prior
    _atomic_json(intent, _intent(plan))
    report = getattr(service, 'execute' if plan.operation == 'build' else plan.operation)(plan, plan.plan_hash)
    wire = {**_jsonable(report), 'plan_hash': plan.plan_hash}
    _atomic_json(receipt, wire)
    return wire


def _checked_plan(path, product, frequency, strategy, cutoff):
    if not path.is_file() or path.is_symlink():
        raise ValueError('HISTORY_EXACT_PLAN_REQUIRED')
    plan = plan_from_dict(_read_json(path))
    if len(plan.streams) != 1:
        raise ValueError('HISTORY_PLAN_SCOPE_DRIFT')
    request = plan.streams[0].request
    policy = candidate_input_quality_policy(product, frequency, candidate_weekly=False)
    expected = (build_fusion_stream_identity(product, frequency, input_quality_policy=policy)
                if strategy == 'dual_fusion' else _newow(product, ProductStrategy(strategy), frequency, forward=False))
    if request.identity != expected or request.as_of != cutoff:
        raise ValueError('HISTORY_PLAN_SCOPE_DRIFT')
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--strategy', action='append', choices=('trend','oscillation','main_rise','dual_fusion'))
    args = parser.parse_args(argv)
    products = validate_product_scope(load_operational_products(), load_active_products())
    if args.product not in products or args.output_root.is_symlink():
        parser.error('invalid scope or output root')
    cutoff = datetime.fromisoformat(args.as_of)
    if cutoff.tzinfo is None or cutoff > datetime.now(UTC):
        parser.error('completed cutoff must be timezone aware and not future')
    out = args.output_root / args.product
    out.mkdir(parents=True, exist_ok=True)
    if out.is_symlink():
        parser.error('invalid product output path')
    failures = []
    selected = tuple(strategy for strategy in ('trend', 'oscillation', 'main_rise', 'dual_fusion')
                     if not args.strategy or strategy in args.strategy)
    cells = [(frequency, strategy) for frequency in ('1w', '1d', '60m') for strategy in selected]
    with product_apply_lock(out) if args.apply else nullcontext():
        # Validate all earlier intents before opening any mutating service. A
        # missing receipt in any selected cell stops the entire product apply.
        frozen = {}
        if args.apply:
            for frequency, strategy in cells:
                stem = f'{strategy}-{frequency}'
                plan = _checked_plan(out / f'{stem}-plan.json', args.product, frequency, strategy, cutoff)
                _prior_receipt(plan, intent=out / f'{stem}-intent.json', receipt=out / f'{stem}-receipt.json')
                frozen[(frequency, strategy)] = plan
        with open_historical_reference_components(reuse_market_inputs=True) as (planner, service):
            for frequency, strategy in cells:
                stem = f'{strategy}-{frequency}'
                plan_file, receipt = out / f'{stem}-plan.json', out / f'{stem}-receipt.json'
                try:
                    if args.apply:
                        wire = apply_exact_plan(service, frozen[(frequency, strategy)],
                                                intent=out / f'{stem}-intent.json', receipt=receipt)
                        print(json.dumps({'product': args.product, 'strategy': strategy,
                                          'frequency': frequency, 'status': wire['status']}), flush=True)
                        if wire['status'] not in {'completed', 'noop'}:
                            return 1  # No later route after a partial/unknown result.
                    else:
                        if plan_file.exists():
                            _checked_plan(plan_file, args.product, frequency, strategy, cutoff)
                            continue
                        policy = candidate_input_quality_policy(args.product, frequency, candidate_weekly=False)
                        identity = (build_fusion_stream_identity(args.product, frequency, input_quality_policy=policy)
                                    if strategy == 'dual_fusion' else _newow(args.product, ProductStrategy(strategy), frequency, forward=False))
                        from app.db.readonly import readonly_transaction
                        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=15):
                            existing = session.scalar(select(ReferenceStream).where(ReferenceStream.stream_id == identity.stream_id))
                            operation = 'rebuild' if existing and existing.active_revision_id else 'build'
                        since = date(2025, 9, 25) if frequency == '60m' else date(2023, 1, 1)
                        request = HistoricalStreamRequest(identity, since, cutoff.date(), cutoff)
                        plan = planner.plan(HistoricalReferenceRequest(
                            operation, (request,), WorkBudget(1, 500_000, 1800, 512_000_000),
                        ))
                        _atomic_json(plan_file, plan_to_dict(plan))
                        print(json.dumps({'product': args.product, 'strategy': strategy, 'frequency': frequency,
                                          'status': 'planned', 'input_count': plan.streams[0].input_count,
                                          'plan_hash': plan.plan_hash}), flush=True)
                except (ValueError, RuntimeError) as error:
                    code = str(error)
                    if not code.replace('_', '').isalnum() or len(code) > 100:
                        code = type(error).__name__
                    failures.append(stem)
                    print(json.dumps({'product': args.product, 'strategy': strategy, 'frequency': frequency,
                                      'status': 'blocked', 'reason': code}), flush=True)
                    if args.apply or code == 'SOURCE_BUSY':
                        return 1
    return 1 if failures else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        reason = str(error)
        if not reason or len(reason) > 100 or any(char not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for char in reason):
            reason = 'HISTORY_EXECUTION_FAILED_READBACK_REQUIRED'
        print(json.dumps({'status': 'blocked', 'reason': reason}), flush=True)
        raise SystemExit(1) from None
