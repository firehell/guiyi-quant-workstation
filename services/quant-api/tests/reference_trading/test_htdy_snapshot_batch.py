from copy import deepcopy
from datetime import date
import json

import pytest

from app.reference_trading.htdy_snapshot import SnapshotError
from app.reference_trading.htdy_snapshot_batch import freeze_manifest, run_batch


def manifest():
    products = ['jm', *(f'{a}{b}' for a in 'abc' for b in 'abcdefghijklmnopqrst')][:60]
    return freeze_manifest(products, products, date(2026, 10, 30), {symbol: date(2023, 1, 1) for symbol in products})


class Store:
    def __init__(self):
        self.values = {}
    def read(self, symbol, *, snapshot_id=None, limit=1):
        if symbol not in self.values:
            raise SnapshotError('HTDY_SNAPSHOT_NOT_BUILT')
        value = self.values[symbol]
        if snapshot_id is not None and snapshot_id != value['snapshot_id']:
            raise SnapshotError('HTDY_SNAPSHOT_NOT_BUILT')
        return value
    def publish(self, symbol):
        from app.reference_trading.htdy_history import history_identity
        identity=history_identity(symbol,'60m')
        self.values[symbol] = dict(product=symbol, frequency='60m', since='2023-01-01', through='2026-10-30',
            snapshot_id=symbol, source_token='a'*64, formula_versions=list(identity.formula_versions), reference_model_version=identity.reference_model_version, stream_id=identity.stream_id, display_projection_version='htdy_snapshot_display_v2', computed_through='2026-10-30T07:00:00Z')
        return self.values[symbol]


def test_freezes_scope_budget_execution_identity_and_jm_first():
    value=manifest()
    assert value['products'][0] == 'jm' and len(value['products']) == 60
    assert value['product_budget_seconds'] == 600
    assert value['execution_files'] and value['reference_model_version']
    with pytest.raises(SnapshotError):
        freeze_manifest(['jm'], ['jm'], date(2026,10,30), {'jm':date(2023,1,1)})


def test_seeded_jm_is_not_rebuilt_and_failures_do_not_stop_other_products(tmp_path):
    value, store, calls = manifest(), Store(), []
    store.publish('jm')
    def build(symbol):
        calls.append(symbol)
        if symbol == 'aa':
            raise SnapshotError('HTDY_REFERENCE_DATA_UNAVAILABLE')
        return store.publish(symbol)
    path=tmp_path/'progress.json'
    result=run_batch(value,path,build_product=build,store=store,seed_jm_snapshot='jm')
    assert 'jm' not in calls and len(calls) == 59
    assert result['items']['jm']['status'] == 'succeeded'
    assert result['items']['aa']['status'] == 'failed'
    assert sum(item['status']=='succeeded' for item in result['items'].values()) == 59
    run_batch(value,path,build_product=lambda _:pytest.fail('attempt was repeated'),store=store)


def test_interrupted_attempt_is_read_back_not_retried_and_pending_continues(tmp_path):
    value, store, calls = manifest(), Store(), []
    path=tmp_path/'progress.json'
    state={'manifest':value,'items':{symbol:{'status':'pending'} for symbol in value['products']}}
    state['items']['jm']={'status':'running','started_at':'2026-10-30T01:00:00Z'}
    write_progress(path, state)
    store.publish('jm')
    def build(symbol):
        calls.append(symbol)
        return store.publish(symbol)
    result=run_batch(value,path,build_product=build,store=store)
    assert 'jm' not in calls and len(calls)==59
    assert result['items']['jm']['status']=='interrupted'
    assert result['items']['jm']['readback']['source_token']=='a'*64


def test_changed_manifest_is_rejected_without_rebuilding(tmp_path):
    value, store = manifest(), Store()
    path=tmp_path/'progress.json'
    run_batch(value,path,build_product=store.publish,store=store)
    changed=deepcopy(value)
    changed['through']='2026-10-29'
    with pytest.raises(SnapshotError,match='HTDY_SNAPSHOT_BATCH_STATE_INVALID'):
        run_batch(changed,path,build_product=lambda _:pytest.fail('manifest drift built'),store=store)


def test_unknown_publication_result_stays_interrupted(tmp_path):
    value, store=manifest(), Store()
    def build(symbol):
        result=store.publish(symbol)
        if symbol=='jm':
            raise SnapshotError('HTDY_SNAPSHOT_CORRUPT')
        return result
    result=run_batch(value,tmp_path/'progress.json',build_product=build,store=store)
    assert result['items']['jm']['status']=='interrupted'
    assert result['items']['jm']['readback']['snapshot_id']=='jm'
    assert sum(item['status']=='succeeded' for item in result['items'].values()) == 59


@pytest.mark.parametrize('field,value',[('formula_versions',['foreign']),('reference_model_version','foreign'),('display_projection_version','foreign'),('stream_id','foreign')])
def test_seed_must_match_frozen_formula_model_and_stream(tmp_path,field,value):
    value_manifest,store=manifest(),Store()
    store.publish('jm')[field]=value
    with pytest.raises(SnapshotError,match='HTDY_SNAPSHOT_BATCH_SCOPE_MISMATCH'):
        run_batch(value_manifest,tmp_path/'progress.json',build_product=lambda _:pytest.fail('unproven seed built'),store=store,seed_jm_snapshot='jm')


def test_lost_success_artifact_is_interrupted_without_blocking_pending(tmp_path):
    value,store,calls=manifest(),Store(),[]
    store.publish('jm')
    state={'manifest':value,'items':{symbol:{'status':'pending'} for symbol in value['products']}}
    state['items']['jm']={'status':'succeeded','snapshot_id':'jm','source_token':'a'*64}
    path=tmp_path/'progress.json'
    write_progress(path, state)
    del store.values['jm']
    def build(symbol):
        calls.append(symbol)
        return store.publish(symbol)
    result=run_batch(value,path,build_product=build,store=store)
    assert 'jm' not in calls and len(calls)==59
    assert result['items']['jm']['status']=='interrupted'
    assert result['items']['jm']['code']=='HTDY_SNAPSHOT_BATCH_EVIDENCE_INVALID'



def write_progress(path, state):
    from hashlib import sha256
    from app.reference_trading.htdy_snapshot import _encode
    value = deepcopy(state)
    value['state_sha256'] = sha256(_encode(value)).hexdigest()
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def test_new_attempt_inherits_success_retries_only_failed_and_preserves_original(tmp_path):
    from hashlib import sha256
    from app.reference_trading.htdy_snapshot import _encode
    value, store, calls = manifest(), Store(), []
    old_manifest = deepcopy(value)
    old_manifest['version'] = 'htdy_snapshot_batch_v1'
    old_manifest.pop('manifest_id')
    old_manifest['manifest_id'] = sha256(_encode(old_manifest)).hexdigest()
    old = dict(manifest=old_manifest, items={})
    for symbol in value['products']:
        result=store.publish(symbol)
        old['items'][symbol]={key: result[key] for key in ('snapshot_id','source_token','since','through','computed_through')}
        old['items'][symbol]['status']='succeeded'
    old['items']['aa']={'status':'failed','code':'HTDY_SNAPSHOT_SOURCE_CHANGED'}
    old['items']['ab']={'status':'interrupted','code':'HTDY_SNAPSHOT_BATCH_RESULT_UNPROVEN'}
    original=tmp_path/'attempt1.json'
    original.write_text(json.dumps(old))
    original.chmod(0o600)
    lock_path=original.with_name(original.name+'.lock')
    lock_path.write_text('')
    lock_path.chmod(0o600)
    before=original.read_bytes()
    def build(symbol):
        calls.append(symbol)
        return store.publish(symbol)
    new=tmp_path/'attempt2.json'
    result=run_batch(value,new,build_product=build,store=store,inherit_state=original)
    assert calls == ['aa']
    assert result['items']['jm']['inherited'] is True
    assert result['items']['ab']['status']=='interrupted'
    assert result['items']['aa']['status']=='succeeded'
    assert original.read_bytes()==before
    assert result['manifest']['inheritance']['source_manifest_id']==old_manifest['manifest_id']
    run_batch(value,new,build_product=lambda _:pytest.fail('completed new attempt repeated'),store=store,inherit_state=original)


def test_progress_hash_blocks_status_corruption_and_retries(tmp_path):
    value,store=manifest(),Store()
    path=tmp_path/'progress.json'
    run_batch(value,path,build_product=store.publish,store=store)
    damaged=json.loads(path.read_text())
    damaged['items']['jm']['status']='pending'
    path.write_text(json.dumps(damaged))
    with pytest.raises(SnapshotError,match='HTDY_SNAPSHOT_BATCH_STATE_INVALID'):
        run_batch(value,path,build_product=lambda _:pytest.fail('corrupt status retried'),store=store)



def test_inheritance_refuses_a_running_source_without_creating_new_attempt(tmp_path):
    import fcntl
    import os
    value,store=manifest(),Store()
    original=tmp_path/'attempt1.json'
    run_batch(value,original,build_product=store.publish,store=store)
    before=original.read_bytes()
    fd=os.open(original.with_name(original.name+'.lock'),os.O_RDONLY)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        target=tmp_path/'attempt2.json'
        with pytest.raises(SnapshotError,match='HTDY_SNAPSHOT_BATCH_BUSY'):
            run_batch(value,target,build_product=lambda _:pytest.fail('running source inherited'),store=store,inherit_state=original)
        assert not target.exists()
        assert original.read_bytes()==before
    finally:
        os.close(fd)


def test_inheritance_missing_source_lock_fails_closed_without_creating_lock(tmp_path):
    value,store=manifest(),Store()
    original=tmp_path/'attempt1.json'
    run_batch(value,original,build_product=store.publish,store=store)
    lock_path=original.with_name(original.name+'.lock')
    lock_path.unlink()
    target=tmp_path/'attempt2.json'
    with pytest.raises(SnapshotError,match='HTDY_SNAPSHOT_BATCH_STATE_INVALID'):
        run_batch(value,target,build_product=lambda _:pytest.fail('missing source lock inherited'),store=store,inherit_state=original)
    assert not lock_path.exists() and not target.exists()
