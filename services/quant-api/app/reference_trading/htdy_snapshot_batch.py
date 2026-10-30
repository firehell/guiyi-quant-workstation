"""Explicit serial existing-data HTDY snapshot batch; no provider or broker calls."""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import stat
from time import monotonic

from app.core.env import PROJECT_ROOT
from app.market_data.market_home_projection import _open_projection_parent
from app.reference_trading.htdy_snapshot import (
    SnapshotError, SnapshotStore, _encode, _read, _write_temp, safe_failure, snapshot_root,
)


def _execution_identity():
    files = (
        'services/quant-api/app/reference_trading/htdy_snapshot.py',
        'services/quant-api/app/reference_trading/htdy_snapshot_batch.py',
        'services/quant-api/app/reference_trading/htdy_history.py',
        'services/quant-api/app/reference_trading/signal_window.py',
        'services/quant-api/app/alerts/evaluators.py',
        'services/quant-api/app/market_data/subing_reference.py',
        'services/quant-api/app/market_data/composition.py',
        'services/quant-api/app/market_data/market_data_service.py',
        'services/quant-api/app/api/market_subing_reference.py',
        'packages/quant-core/guiyi_quant/reference_trading/htdy.py',
        'packages/quant-core/guiyi_quant/reference_trading/contracts.py',
        'packages/quant-core/guiyi_quant/reference_trading/reducer.py',
        'packages/quant-core/guiyi_quant/indicators/htdy_original.py',
        'packages/quant-core/guiyi_quant/indicators/registry.py',
    )
    return {name: sha256((PROJECT_ROOT / name).read_bytes()).hexdigest() for name in files}


def freeze_manifest(products, active_products, through, floors):
    if (len(products) != 60 or len(set(products)) != 60 or len(active_products) != 60
            or set(products) != set(active_products) or 'jm' not in products
            or set(floors) != set(products)):
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_UNIVERSE_INVALID')
    ordered = ['jm', *(symbol for symbol in products if symbol != 'jm')]
    from dataclasses import asdict
    from fastapi.encoders import jsonable_encoder
    from app.reference_trading.htdy_history import history_identity
    identity = history_identity('jm', '60m')
    value = dict(version='htdy_snapshot_batch_v2', products=ordered,
                 product_budget_seconds=600, input_context_bars=32, execution_files=_execution_identity(),
                 stream_template=jsonable_encoder(asdict(identity)), display_projection_version='htdy_snapshot_display_v2',
                 formula_versions=list(identity.formula_versions), reference_model_version=identity.reference_model_version,
                 operational=list(products), active=list(active_products),
                 through=through.isoformat(), full_history=True,
                 storage_starts={symbol: floors[symbol].isoformat() for symbol in ordered})
    return {**value, 'manifest_id': sha256(_encode(value)).hexdigest()}


def _save(parent, name, value):
    try:
        if not stat.S_ISREG(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
            raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
    except FileNotFoundError:
        pass
    envelope = dict(value)
    envelope.pop('state_sha256', None)
    envelope['state_sha256'] = sha256(_encode(envelope)).hexdigest()
    temp = _write_temp(parent, envelope)
    try:
        os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temp, dir_fd=parent)
        except FileNotFoundError:
            pass


def _read_state(parent, name, *, allow_legacy=False):
    value = _read(parent, name)
    digest = value.get('state_sha256')
    body = {key: item for key, item in value.items() if key != 'state_sha256'}
    if digest is None:
        if not allow_legacy or value.get('manifest', {}).get('version') != 'htdy_snapshot_batch_v1':
            raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
    elif digest != sha256(_encode(body)).hexdigest():
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
    return body


def _inherit(manifest, path, store):
    source = Path(path)
    if not source.is_absolute() or source != source.resolve():
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
    parent = _open_projection_parent(source.parent, create=False)
    if parent is None:
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
    source_lock = None
    try:
        # Never create or modify the source attempt. Its existing private lock
        # proves the source runner has exited before freezing its result state.
        source_lock = os.open(source.name + '.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        info = os.fstat(source_lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
            raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
        try:
            fcntl.flock(source_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SnapshotError('HTDY_SNAPSHOT_BATCH_BUSY') from None
        old = _read_state(parent, source.name, allow_legacy=True)
    except SnapshotError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID') from None
    finally:
        try:
            if source_lock is not None:
                os.close(source_lock)
        finally:
            os.close(parent)
    old_manifest = old['manifest']
    if old_manifest.get('manifest_id') != sha256(_encode({key: value for key, value in old_manifest.items() if key != 'manifest_id'})).hexdigest():
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
    if old_manifest.get('input_context_bars') not in (None, 32):
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
    fixed = ('products', 'operational', 'active', 'through', 'full_history', 'storage_starts',
             'formula_versions', 'reference_model_version', 'stream_template', 'display_projection_version', 'product_budget_seconds')
    if (any(old_manifest.get(key) != manifest[key] for key in fixed)
            or set(old['items']) != set(manifest['products'])):
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
    current = dict(manifest)
    current['inheritance'] = dict(source_manifest_id=old_manifest['manifest_id'],
        source_progress_content_sha256=sha256(_encode(old)).hexdigest())
    current.pop('manifest_id', None)
    current['manifest_id'] = sha256(_encode(current)).hexdigest()
    items = {}
    for symbol in current['products']:
        prior = old['items'][symbol]
        if prior['status'] == 'succeeded':
            try:
                proof = _snapshot_proof(store, symbol, current, prior['snapshot_id'])
                if proof['source_token'] != prior['source_token']:
                    raise SnapshotError('HTDY_SNAPSHOT_BATCH_EVIDENCE_INVALID')
                items[symbol] = {**prior, 'inherited': True}
            except SnapshotError as exc:
                items[symbol] = {**prior, 'status': 'interrupted', 'code': 'HTDY_SNAPSHOT_BATCH_EVIDENCE_INVALID', 'readback_code': exc.code}
        elif prior['status'] == 'failed':
            items[symbol] = dict(status='pending', previous_attempt_status='failed', previous_code=prior.get('code'))
        elif prior['status'] in {'interrupted', 'running'}:
            items[symbol] = {**prior, 'status': 'interrupted', 'code': prior.get('code', 'HTDY_SNAPSHOT_BATCH_RESULT_UNPROVEN')}
        else:
            raise SnapshotError('HTDY_SNAPSHOT_BATCH_INHERIT_INCOMPLETE')
    return current, items


def _snapshot_proof(store, symbol, manifest, identifier=None):
    from guiyi_quant.reference_trading import StreamIdentity
    expected_stream = StreamIdentity(**{**manifest['stream_template'], 'product': symbol.upper()})
    value = store.read(symbol, snapshot_id=identifier, limit=1)
    if (value['product'] != symbol or value['frequency'] != '60m'
            or value['since'] != manifest['storage_starts'][symbol]
            or value['through'] != manifest['through']
            or value['formula_versions'] != manifest['formula_versions']
            or value['reference_model_version'] != manifest['reference_model_version']
            or value.get('display_projection_version') != manifest['display_projection_version']
            or value['stream_id'] != expected_stream.stream_id):
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_SCOPE_MISMATCH')
    return {key: value[key] for key in ('snapshot_id', 'source_token', 'since', 'through', 'computed_through')}


def run_batch(manifest, path, *, build_product, store, seed_jm_snapshot=None, inherit_state=None, on_result=lambda _: None):
    """One process, one product at a time; uncertain attempts are never retried."""
    path = Path(path)
    if not path.is_absolute() or path != path.resolve():
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
    inherited_items = None
    if inherit_state is not None:
        if seed_jm_snapshot is not None or path == Path(inherit_state):
            raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
        manifest, inherited_items = _inherit(manifest, inherit_state, store)
    parent, lock = None, None
    try:
        parent = _open_projection_parent(path.parent, create=True)
        lock = os.open(path.name + '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SnapshotError('HTDY_SNAPSHOT_BATCH_BUSY') from None
        try:
            state = _read_state(parent, path.name)
            if state.get('manifest') != manifest or set(state.get('items', {})) != set(manifest['products']):
                raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
            if any(not isinstance(item, dict) or item.get('status') not in {'pending', 'running', 'succeeded', 'failed', 'interrupted'} for item in state['items'].values()):
                raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
        except FileNotFoundError:
            state = {'manifest': manifest, 'items': inherited_items or {symbol: {'status': 'pending'} for symbol in manifest['products']}}
            _save(parent, path.name, state)
        if seed_jm_snapshot and state['items']['jm']['status'] == 'pending':
            proof = _snapshot_proof(store, 'jm', manifest, seed_jm_snapshot)
            state['items']['jm'] = {'status': 'succeeded', 'seeded': True, **proof}
            _save(parent, path.name, state)
        for symbol in manifest['products']:
            item = state['items'][symbol]
            if item['status'] == 'running':
                # Previous process ended without a durable success receipt.
                # Read back the candidate identity, but never infer this attempt
                # succeeded merely because a compatible latest file exists.
                item['status'] = 'interrupted'
                item['code'] = 'HTDY_SNAPSHOT_BATCH_RESULT_UNPROVEN'
                try:
                    item['readback'] = _snapshot_proof(store, symbol, manifest)
                except SnapshotError as exc:
                    item['readback_code'] = exc.code
                _save(parent, path.name, state)
                on_result({'product': symbol, **item})
            if item['status'] != 'pending':
                if item['status'] == 'succeeded':
                    if not isinstance(item.get('snapshot_id'), str) or not isinstance(item.get('source_token'), str):
                        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
                    try:
                        proof = _snapshot_proof(store, symbol, manifest, item['snapshot_id'])
                        if proof['source_token'] != item['source_token']:
                            raise SnapshotError('HTDY_SNAPSHOT_BATCH_EVIDENCE_INVALID')
                    except SnapshotError as exc:
                        item.update(status='interrupted', code='HTDY_SNAPSHOT_BATCH_EVIDENCE_INVALID', readback_code=exc.code)
                        _save(parent, path.name, state)
                        on_result({'product': symbol, **item})
                continue
            if _execution_identity() != manifest['execution_files']:
                raise SnapshotError('HTDY_SNAPSHOT_BATCH_EXECUTION_CHANGED')
            try:
                previous = store.read(symbol, limit=1)['snapshot_id']
            except SnapshotError:
                previous = None
            state['items'][symbol] = {'status': 'running', 'started_at': datetime.now(UTC).isoformat(), 'previous_snapshot_id': previous}
            _save(parent, path.name, state)
            try:
                result = build_product(symbol)
                proof = _snapshot_proof(store, symbol, manifest, result['snapshot_id'])
                item = {'status': 'succeeded', **proof}
            except Exception as exc:
                item = safe_failure(exc)
                try:
                    proof = _snapshot_proof(store, symbol, manifest)
                    if proof['snapshot_id'] != previous:
                        item.update(status='interrupted', code='HTDY_SNAPSHOT_BATCH_RESULT_UNPROVEN', readback=proof)
                except SnapshotError:
                    pass
            state['items'][symbol] = item
            _save(parent, path.name, state)
            on_result({'product': symbol, **item})
        return state
    except SnapshotError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID') from None
    finally:
        try:
            if lock is not None:
                os.close(lock)
        finally:
            if parent is not None:
                os.close(parent)


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run',))
    parser.add_argument('--through', type=date.fromisoformat, required=True)
    parser.add_argument('--state', type=Path)
    provenance = parser.add_mutually_exclusive_group()
    provenance.add_argument('--seed-jm-snapshot')
    provenance.add_argument('--inherit-state', type=Path)
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    try:
        from app.private_settings import load_private_readonly_settings
        settings, _ = load_private_readonly_settings(Path.home() / 'Library/Application Support/GuiyiQuant/project.env')
        os.environ.update({key: settings[key] for key in ('DATABASE_URL', 'GUIYI_CANONICAL_DATA_ROOT')})
        from app.api.market_subing_reference import _build_service
        from app.db.session import SessionLocal
        from app.db.readonly import readonly_transaction
        from app.market_data.operational_universe import load_active_products, load_operational_products
        from app.market_data.subing_reference import SubingReferenceQuery
        from app.reference_trading.htdy_snapshot import build_snapshot
        active, products = load_active_products(), load_operational_products()
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            service = _build_service(session, lambda: None)
            floors = {symbol: service.historical_storage_start(symbol) for symbol in products}
        manifest = freeze_manifest(products, active, args.through, floors)
        state_path = args.state or PROJECT_ROOT / f'.run/htdy-full-{args.through.isoformat()}.json'
        store = SnapshotStore(snapshot_root())
        if args.preflight:
            seed = _snapshot_proof(store, 'jm', manifest, args.seed_jm_snapshot) if args.seed_jm_snapshot else None
            if args.inherit_state is not None:
                if state_path == args.inherit_state:
                    raise SnapshotError('HTDY_SNAPSHOT_BATCH_STATE_INVALID')
                manifest, _items = _inherit(manifest, args.inherit_state, store)
            print(json.dumps({'status': 'preflight_passed', 'manifest_id': manifest['manifest_id'], 'products': manifest['products'], 'product_budget_seconds': 600, 'input_context_bars': 32, 'seed_jm': seed, 'inheritance_counts': {status: sum(item['status'] == status for item in _items.values()) for status in ('succeeded', 'pending', 'interrupted')} if args.inherit_state is not None else None}), flush=True)
            return
        def build_product(symbol):
            deadline = monotonic() + 600
            def check_cancelled():
                if monotonic() > deadline:
                    raise SnapshotError('HTDY_SNAPSHOT_BUDGET_EXCEEDED')
            with SessionLocal() as session, readonly_transaction(session, timeout_seconds=600):
                service = _build_service(session, check_cancelled, historical_window_days=None, physical_context_bars=32)
                if service.historical_storage_start(symbol).isoformat() != manifest['storage_starts'][symbol]:
                    raise SnapshotError('HTDY_SNAPSHOT_BATCH_SCOPE_MISMATCH')
                return build_snapshot(service, SubingReferenceQuery(symbol, through=args.through, frequency='60m'), full_history=True, store=store)
        result = run_batch(manifest, state_path, build_product=build_product, store=store,
            seed_jm_snapshot=args.seed_jm_snapshot, inherit_state=args.inherit_state, on_result=lambda value: print(json.dumps(value), flush=True))
        print(json.dumps({'status': 'finished', 'counts': {status: sum(item['status'] == status for item in result['items'].values()) for status in ('succeeded', 'failed', 'interrupted', 'pending')}}), flush=True)
    except Exception as exc:
        print(json.dumps(safe_failure(exc)), flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
