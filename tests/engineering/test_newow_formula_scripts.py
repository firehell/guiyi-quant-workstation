"""Pure scope/readback checks: no production DB, drain or service calls."""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace as NS

import pytest
from scripts import newow_formula_transition as transition
from scripts import newow_formula_prepare as prepare


def sid(value):
    return 'reference-stream:' + sha256(value.encode()).hexdigest()


@pytest.fixture
def scope(monkeypatch):
    products = {'p' + str(i) for i in range(60)}
    monkeypatch.setattr(transition, 'load_operational_products', lambda: products)
    monkeypatch.setattr(transition, 'identity', lambda p, s, f: NS(stream_id=sid(p+s+f)))
    groups = {p+'-'+f: [(sid(p+f+c+'old'), sid(p+c.removeprefix('newow_')+f))
                       for c in sorted(transition.CODES)]
              for p in products for f in ('1w', '1d', '60m')}
    return dict(version='newow_formula_transition_scope_v1', groups=groups,
                expires_at='2026-11-07T12:00:00+00:00', recording_start='2026-11-07T13:00:00+00:00')


def test_frozen_scope_requires_all_180_groups(scope):
    transition.validate_scope(scope)
    del scope['groups'][next(iter(scope['groups']))]
    with pytest.raises(ValueError, match='FORMULA_SCOPE_INCOMPLETE'):
        transition.validate_scope(scope)


def test_frozen_scope_rejects_wrong_target_and_duplicate_old(scope):
    keys = list(scope['groups'])
    invalid = deepcopy(scope)
    invalid['groups'][keys[0]][0] = (sid('old'), sid('wrong'))
    with pytest.raises(ValueError, match='FORMULA_SCOPE_DRIFT'):
        transition.validate_scope(invalid)
    invalid = deepcopy(scope)
    old = invalid['groups'][keys[0]][0][0]
    invalid['groups'][keys[1]][0] = (old, invalid['groups'][keys[1]][0][1])
    with pytest.raises(ValueError, match='FORMULA_SCOPE_DRIFT'):
        transition.validate_scope(invalid)


def test_saved_plan_must_match_scope_members_and_boundary(scope):
    pairs = next(iter(scope['groups'].values()))
    plan = {**scope, 'items': [dict(old=dict(stream=dict(stream_id=o)), bootstrap=dict(source=dict(stream_id=h))) for o,h in pairs]}
    transition.validate_plan_binding(plan, pairs, scope)
    plan['items'][0]['bootstrap']['source']['stream_id'] = sid('other')
    with pytest.raises(ValueError, match='FORMULA_PLAN_SCOPE_DRIFT'):
        transition.validate_plan_binding(plan, pairs, scope)


def test_prepare_receipt_rejects_cross_scope_before_db():
    def forbidden():
        raise AssertionError('must reject before connecting')
    with pytest.raises(ValueError, match='FORMULA_PREPARE_RECEIPT_INVALID'):
        prepare.committed_readback(forbidden, dict(status='COMMITTED', stream_id=sid('a')), expected_stream_id=sid('b'))


def test_prepare_receipt_revalidates_published_snapshot(monkeypatch):
    from app.reference_trading.newow_bootstrap import NewowForwardBootstrap
    snapshot = dict(stream_id=sid('a'), revision_id='rev', seq=3)
    record = dict(status='COMMITTED', stream_id=snapshot['stream_id'], result=dict(streams=[dict(stream_id=snapshot['stream_id'], status='completed', snapshot=snapshot)]))
    class Database:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def get_bind(self): return NS(dialect=NS(name='sqlite'))
    monkeypatch.setattr(NewowForwardBootstrap, '_source', lambda *_: (None, dict(snapshot)))
    prepare.committed_readback(Database, record, expected_stream_id=snapshot['stream_id'])
    monkeypatch.setattr(NewowForwardBootstrap, '_source', lambda *_: (None, {**snapshot, 'seq':4}))
    with pytest.raises(ValueError, match='FORMULA_PREPARE_READBACK_DRIFT'):
        prepare.committed_readback(Database, record, expected_stream_id=snapshot['stream_id'])
