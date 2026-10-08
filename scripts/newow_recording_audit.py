#!/usr/bin/env python3
"""Read-only exact-identity historical recording readback; no market/full replay reads."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path

from sqlalchemy import select

from app.db.readonly import readonly_transaction
from app.market_data.newow.product_release import candidate_input_quality_policy
from app.reference_trading.models import ReferenceStream, ReferenceRevision, ReferenceBatch
from app.reference_trading.newow_bootstrap import validate_product_scope
from app.reference_trading.repository import _identity_from_row
from guiyi_quant.newow.fusion_reference import build_fusion_stream_identity
from guiyi_quant.newow.product_contracts import ProductStrategy
from scripts.reference_trading_p9_manifest import _newow

STRATEGIES = ('trend', 'oscillation', 'main_rise', 'dual_fusion')
FREQUENCIES = ('1w', '1d', '60m')


def formal_identities(products):
    result = []
    for product in products:
        for frequency in FREQUENCIES:
            policy = candidate_input_quality_policy(product, frequency, candidate_weekly=False)
            for strategy in STRATEGIES:
                identity = (build_fusion_stream_identity(product, frequency, input_quality_policy=policy)
                            if strategy == 'dual_fusion' else _newow(product, ProductStrategy(strategy), frequency, forward=False))
                result.append((product, strategy, frequency, identity))
    return result


def _time(value):
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def audit_history(session, products, *, at):
    """One bounded repeatable-read metadata snapshot for the exact registered matrix."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError('AUDIT_TIME_INVALID')
    if len(products) > 60 or len(set(products)) != len(products):
        raise ValueError('AUDIT_SCOPE_INVALID')
    expected = formal_identities(products)
    s, r, b = ReferenceStream, ReferenceRevision, ReferenceBatch
    with readonly_transaction(session, timeout_seconds=30):
        # Only the explicit boundary-policy JSON scalar; no full manifest,
        # checkpoint_text, strategy state or replay data.
        rows = session.execute(select(
            s, r.revision_id, r.status, r.last_seq, b.batch_id, b.seq,
            b.computed_through, b.kind, b.strategy_schema,
            b.dependency_manifest['reference_boundary_policy_version'].as_string(),
        ).outerjoin(r, (r.stream_id == s.stream_id) & (r.revision_id == s.active_revision_id))
          .outerjoin(b, (b.stream_id == r.stream_id) & (b.revision_id == r.revision_id)
                     & (b.batch_id == r.checkpoint_batch_id))
          .where(s.stream_id.in_([identity.stream_id for _, _, _, identity in expected]))).all()
        stored = {row[0].stream_id: row for row in rows}
        items = []
        for product, strategy, frequency, identity in expected:
            item = {'product': product, 'strategy': strategy, 'frequency': frequency,
                    'stream_id': identity.stream_id, 'registered': False, 'active_revision_id': None,
                    'revision_status': None, 'health': None, 'latest_seq': None, 'revision_seq': None,
                    'checkpoint_seq': None, 'computed_through': None, 'strategy_schema': None,
                    'reference_boundary_policy_version': None,
                    'status': 'NOT_REGISTERED'}
            row = stored.get(identity.stream_id)
            if row is not None:
                stream, revision_id, revision_status, revision_seq, batch_id, seq, computed, kind, schema, boundary_policy = row
                item.update(registered=True, active_revision_id=stream.active_revision_id,
                            revision_status=revision_status, health=stream.health, latest_seq=stream.latest_seq,
                            revision_seq=revision_seq, checkpoint_seq=seq, computed_through=_time(computed),
                            strategy_schema=schema, reference_boundary_policy_version=boundary_policy, status='READY')
                if (_identity_from_row(stream) != identity
                        or stream.identity_hash != identity.stream_id.removeprefix('reference-stream:')):
                    item['status'] = 'IDENTITY_CONFLICT'
                elif stream.active_revision_id is None:
                    item['status'] = 'NO_ACTIVE_REVISION'
                elif revision_id is None or revision_status != 'active':
                    item['status'] = 'REVISION_NOT_ACTIVE'
                elif batch_id is None or computed is None or kind not in {'seed_seal', 'calculation'}:
                    item['status'] = 'CHECKPOINT_MISSING'
                elif schema != ('newow_dual_fusion_reference_v1' if strategy == 'dual_fusion' else 'newow_product_replay_v1'):
                    item['status'] = 'CHECKPOINT_SCHEMA_CONFLICT'
                elif seq != revision_seq or seq != stream.latest_seq:
                    item['status'] = 'SEQ_MISMATCH'
                elif datetime.fromisoformat(item['computed_through']) > at:
                    item['status'] = 'FUTURE_CHECKPOINT'
                elif stream.health != 'READY':
                    item['status'] = 'HEALTH_NOT_READY'
                elif frequency == '1d':
                    from app.reference_trading.inputs import NEWOW_D1_REFERENCE_BOUNDARY_POLICY
                    if boundary_policy != NEWOW_D1_REFERENCE_BOUNDARY_POLICY:
                        item['status'] = 'BOUNDARY_POLICY_STALE'
            items.append(item)
    def summarize(values):
        return {'expected_count': len(values), 'registered_count': sum(item['registered'] for item in values),
                'active_count': sum(item['revision_status'] == 'active' and item['status'] != 'IDENTITY_CONFLICT' for item in values),
                'ready_count': sum(item['status'] == 'READY' for item in values),
                'status_counts': dict(sorted(Counter(item['status'] for item in values).items())),
                'health_counts': dict(sorted(Counter(item['health'] or 'NOT_REGISTERED' for item in values).items())),
                'computed_through_counts': dict(sorted(Counter(item['computed_through'] or 'NONE' for item in values).items()))}
    return {'version': 'newow_formal_history_metadata_audit_v1', 'observed_at': at.isoformat(),
            'recording_mode': 'historical_replay', 'scope': 'formal_exact_identity',
            **summarize(items),
            'by_combination': [{'strategy': strategy, 'frequency': frequency,
                                **summarize([item for item in items if item['strategy'] == strategy and item['frequency'] == frequency])}
                               for frequency in FREQUENCIES for strategy in STRATEGIES],
            'by_product': [{'product': product, **summarize([item for item in items if item['product'] == product])}
                           for product in products], 'items': items}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-env', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        raise ValueError('AUDIT_OUTPUT_EXISTS')
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.session import normalize_database_url
    from app.market_data.operational_universe import load_operational_products, load_active_products
    from scripts.newow_weekly_recovery import load_private_readonly_settings
    from scripts.newow_recording_history import _atomic_json
    settings, _ = load_private_readonly_settings(args.project_env)
    engine = create_engine(normalize_database_url(settings['DATABASE_URL']), pool_pre_ping=True)
    try:
        products = validate_product_scope(load_operational_products(), load_active_products())
        with sessionmaker(engine, expire_on_commit=False)() as session:
            result = audit_history(session, products, at=datetime.now(UTC))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(args.output, result)
        print(json.dumps({key: result[key] for key in (
            'version', 'observed_at', 'expected_count', 'registered_count', 'active_count', 'ready_count', 'status_counts',
        )}, sort_keys=True), flush=True)
        return 0
    finally:
        engine.dispose()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        reason = str(error)
        if not reason or len(reason) > 100 or any(char not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for char in reason):
            reason = 'HISTORY_AUDIT_FAILED'
        print(json.dumps({'status': 'blocked', 'reason': reason}), flush=True)
        raise SystemExit(1) from None
