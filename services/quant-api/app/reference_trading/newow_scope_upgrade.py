"""Exact all-or-nothing replacement of the existing Newow 720 observation routes.

The caller must park all producers/consumers before planning and applying. This
module never changes notifications, historical facts, or old reference positions.
"""
from datetime import UTC, datetime
from hashlib import sha256
import json

from sqlalchemy import select, text

from app.reference_trading.activation import ForwardActivation
from app.reference_trading.models import ReferenceActivationReceipt, ReferenceStream
from app.reference_trading.newow_bootstrap import (
    NewowForwardBootstrap, _BorrowedSession, _aware, _hash, validate_product_scope,
)
from app.reference_trading.repository import RepositoryConflict

FREQUENCIES = ('1w', '1d', '60m')
STRATEGIES = ('trend', 'oscillation', 'main_rise', 'dual_fusion')
VERSION = 'newow_forward_scope_upgrade_v1'
SCOPE_COUNT = 720
PRODUCT_COUNT = 60


def _route(row):
    return (row.product, row.strategy_code.replace('-', '_').removeprefix('newow_'), row.frequency)


def _wire(value):
    if isinstance(value, datetime):
        # SQLite returns timezone-naive values for timestamptz fixtures.
        return value.isoformat()
    if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
        return value
    return str(value)


def _facts(session, ids):
    """Protect every old fact and both notification tables without exposing content."""
    from app.notifications.newow import NewowNotificationPolicy, NewowNotificationDelivery
    from app.db.base import Base
    names = ('reference_revisions', 'reference_batches', 'reference_actions',
             'reference_trades', 'reference_marks', 'reference_capture_reconciliations',
             NewowNotificationPolicy.__tablename__, NewowNotificationDelivery.__tablename__)
    result = {}
    for name in names:
        table = Base.metadata.tables[name]
        query = select(table)
        if name == 'reference_capture_reconciliations':
            batches = Base.metadata.tables['reference_batches']
            query = query.where(table.c.capture_batch_id.in_(
                select(batches.c.batch_id).where(batches.c.stream_id.in_(ids))))
        elif name.startswith('reference_'):
            query = query.where(table.c.stream_id.in_(ids))
        # Deterministic full-row digests include OLD OPEN/checkpoints and delivery cursor.
        rows = session.execute(query).mappings().all()
        wires = sorted(json.dumps({k: _wire(v) for k, v in row.items()},
                                  sort_keys=True, separators=(',', ':')) for row in rows)
        result[name] = {'count': len(wires), 'sha256': sha256('\n'.join(wires).encode()).hexdigest()}
    return result


def _old_binding(session, row):
    receipt = session.scalar(select(ReferenceActivationReceipt).where(
        ReferenceActivationReceipt.stream_id == row.stream_id,
        ReferenceActivationReceipt.generation == row.activation_generation))
    if (not row.enabled or row.active_revision_id is None or receipt is None
            or receipt.disabled_at is not None or receipt.revision_id != row.active_revision_id
            or receipt.plan_hash != row.activation_plan_hash):
        raise RepositoryConflict('UPGRADE_OLD_RECEIPT_INVALID')
    return {'stream_id': row.stream_id, 'generation': row.activation_generation,
            'row_version': row.row_version, 'revision_id': row.active_revision_id,
            'latest_seq': row.latest_seq, 'activation_plan_hash': row.activation_plan_hash,
            'identity_hash': row.identity_hash, 'receipt_id': receipt.receipt_id,
            'stream_facts_sha256': _hash({column.name: _wire(getattr(row, column.name))
                for column in row.__table__.columns
                if column.name not in {'enabled', 'activation_generation', 'row_version', 'health'}}),
            'receipt_facts_sha256': _hash({column.name: _wire(getattr(receipt, column.name))
                for column in receipt.__table__.columns if column.name != 'disabled_at'})}


class NewowForwardScopeUpgrade:
    def __init__(self, session_factory):
        self._factory = session_factory

    def plan(self, operational, active, **options):
        products = validate_product_scope(operational, active)
        scope = NewowForwardBootstrap(self._factory).plan_scope(
            products, products, selected_frequencies=FREQUENCIES, **options)
        with self._factory() as session:
            return self._freeze(session, scope)

    def _freeze(self, session, scope):
        if (scope.get('expected_count') != SCOPE_COUNT or len(scope.get('items', [])) != SCOPE_COUNT
                or tuple(scope.get('frequencies', [])) != FREQUENCIES
                or len(scope.get('products', [])) != PRODUCT_COUNT):
            raise RepositoryConflict('UPGRADE_SCOPE_INVALID')
        expected = {(p, s, f) for p in scope['products'] for s in STRATEGIES for f in FREQUENCIES}
        items = scope['items']
        if (any(x['status'] != 'ready' or not x['plan'] for x in items)
                or {(x['product'], x['strategy'], x['frequency']) for x in items} != expected):
            raise RepositoryConflict('UPGRADE_NEW_SCOPE_NOT_READY')
        rows = session.scalars(select(ReferenceStream).where(
            ReferenceStream.recording_mode == 'forward_observation',
            ReferenceStream.enabled.is_(True))).all()
        # No unexpected active route is silently retained or disabled.
        if len(rows) != SCOPE_COUNT or {_route(row) for row in rows} != expected:
            raise RepositoryConflict('UPGRADE_OLD_SCOPE_MISMATCH')
        old = {_route(row): row for row in rows}
        mapping = []
        for item in sorted(items, key=lambda x: (x['product'], x['strategy'], x['frequency'])):
            key = (item['product'], item['strategy'], item['frequency'])
            binding = _old_binding(session, old[key])
            if binding['stream_id'] == item['plan']['target_stream_id']:
                raise RepositoryConflict('UPGRADE_IDENTITY_NOT_CHANGED')
            mapping.append({'route': list(key), 'old': binding, 'new': item['plan']})
        payload = {'version': VERSION, 'scope_plan_hash': scope['plan_hash'],
                   'products': scope['products'], 'frequencies': list(FREQUENCIES),
                   'expected_count': SCOPE_COUNT, 'mapping': mapping,
                   'protected_facts': _facts(session, [x['old']['stream_id'] for x in mapping])}
        return {**payload, 'plan_hash': _hash(payload)}

    def apply(self, plan, *, expected_plan_hash, now, clock=None):
        current = _aware(now)
        clock = clock or (lambda: datetime.now(UTC))
        payload = {k: v for k, v in plan.items() if k != 'plan_hash'}
        if (plan.get('version') != VERSION or _hash(payload) != plan.get('plan_hash')
                or expected_plan_hash != plan.get('plan_hash')):
            raise RepositoryConflict('PLAN_HASH_CONFLICT')
        products = validate_product_scope(plan['products'], plan['products'])
        mapping = plan['mapping']
        expected = {(p, s, f) for p in products for s in STRATEGIES for f in FREQUENCIES}
        if (plan['expected_count'] != SCOPE_COUNT or len(mapping) != SCOPE_COUNT
                or tuple(plan['frequencies']) != FREQUENCIES
                or {tuple(x['route']) for x in mapping} != expected
                or len({x['old']['stream_id'] for x in mapping}) != SCOPE_COUNT
                or len({x['new']['target_stream_id'] for x in mapping}) != SCOPE_COUNT):
            raise RepositoryConflict('UPGRADE_SCOPE_INVALID')
        starts = {(x['new']['recording_start'], x['new']['expires_at'], x['new']['host'],
                   x['new']['environment'], x['new']['recovery_policy']) for x in mapping}
        if (len(starts) != 1 or {x['old']['stream_id'] for x in mapping}
                & {x['new']['target_stream_id'] for x in mapping}):
            raise RepositoryConflict('UPGRADE_PLAN_BOUNDARY_MISMATCH')
        with self._factory() as session, session.begin():
            if session.get_bind().dialect.name == 'sqlite':
                session.execute(text('BEGIN IMMEDIATE'))
            if session.get_bind().dialect.name == 'postgresql':
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text("SET LOCAL statement_timeout = '300s'"))
                session.execute(text('SELECT pg_advisory_xact_lock(:key)'),
                                {'key': 7441435158900115})
            rows = session.scalars(select(ReferenceStream).where(
                ReferenceStream.recording_mode == 'forward_observation',
                ReferenceStream.enabled.is_(True)).with_for_update()).all()
            if {row.stream_id for row in rows} != {x['old']['stream_id'] for x in mapping}:
                raise RepositoryConflict('UPGRADE_OLD_SCOPE_DRIFT')
            indexed = {row.stream_id: row for row in rows}
            ids = [x['old']['stream_id'] for x in mapping]
            if _facts(session, ids) != plan['protected_facts']:
                raise RepositoryConflict('UPGRADE_PROTECTED_FACT_DRIFT')
            factory = lambda: _BorrowedSession(session)
            bootstrap = NewowForwardBootstrap(factory)
            # Validate every preimage before the first mutation. apply() also performs
            # locked source/target CAS and rolls the entire outer transaction back.
            for item in mapping:
                row = indexed[item['old']['stream_id']]
                new = item['new']
                if _old_binding(session, row) != item['old'] or _route(row) != tuple(item['route']):
                    raise RepositoryConflict('UPGRADE_OLD_STREAM_DRIFT')
                if [new.get('product'), new.get('strategy'), new.get('frequency')] != item['route']:
                    raise RepositoryConflict('UPGRADE_ROUTE_MISMATCH')
                if (current > _aware(datetime.fromisoformat(new['expires_at']))
                        or current >= _aware(datetime.fromisoformat(new['recording_start']))):
                    raise RepositoryConflict('PLAN_EXPIRED_OR_START_IN_PAST')
            def deadline():
                observed = _aware(clock())
                if observed < current:
                    raise RepositoryConflict('UPGRADE_CLOCK_REGRESSED')
                for item in mapping:
                    new = item['new']
                    if (observed > _aware(datetime.fromisoformat(new['expires_at']))
                            or observed >= _aware(datetime.fromisoformat(new['recording_start']))):
                        raise RepositoryConflict('PLAN_EXPIRED_OR_START_IN_PAST')
                return observed
            receipts = []
            for item in mapping:
                observed = deadline()
                ForwardActivation(factory).disable(item['old']['stream_id'],
                    expected_generation=item['old']['generation'], now=observed)
                receipts.append(bootstrap.apply(item['new'],
                    expected_plan_hash=item['new']['plan_hash'], now=observed))
            session.flush()
            if _facts(session, ids) != plan['protected_facts']:
                raise RepositoryConflict('UPGRADE_PROTECTED_FACT_CHANGED')
            active = session.scalars(select(ReferenceStream).where(
                ReferenceStream.recording_mode == 'forward_observation',
                ReferenceStream.enabled.is_(True))).all()
            if {row.stream_id for row in active} != {x['new']['target_stream_id'] for x in mapping}:
                raise RepositoryConflict('UPGRADE_NEW_SCOPE_MISMATCH')
            deadline()
            return {'version': VERSION, 'plan_hash': plan['plan_hash'],
                    'disabled_count': len(mapping), 'activated_count': len(receipts),
                    'receipts': receipts, 'protected_facts': plan['protected_facts']}
