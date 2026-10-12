"""Task CLI I/O and parked owner proof without production resources."""
from dataclasses import replace
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[4]/'output/live-observation-recovery-20261012/recover.py'


def cli():
    spec = importlib.util.spec_from_file_location('task_observation_restore', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_serialized_plan_is_exact_and_hash_detects_tampering():
    from app.market_data.observation_restore import ProjectionRestorePlan
    module = cli()
    plan = ProjectionRestorePlan(date(2026, 10, 12), ('key',), (b'\x00\xffbytes',),
                                 '{"bars":[]}', '1-0', '0-0', 10, 4)
    encoded = module.serialize_plan(plan)
    assert module.deserialize_plan(json.loads(json.dumps(encoded))) == plan
    assert replace(plan, keys=('other-key',)).sha256 != plan.sha256
    encoded['source_cursor'] = '1-0'
    with pytest.raises(ValueError, match='PLAN_HASH_CONFLICT'):
        module.deserialize_plan(encoded)


def owner_fixture(tmp_path):
    module = cli()
    bindings, owners = {}, {}
    for service in module.SERVICES:
        record = {'schema_version': 1, 'service': service, 'generation': 16, 'phase': 'parked',
                  'ready': False, 'proof': {'failure_code': 'original_failure'}}
        path = tmp_path/f'{service}.owner.json'
        path.write_text(json.dumps(record))
        os.chmod(path, 0o600)
        lock = tmp_path/f'{service}.owner.lock'
        lock.touch(mode=0o600)
        bindings[service] = {'generation': 16}
        owners[service] = {'record': dict(record)}
    return module, bindings, owners


def test_parked_lock_proof_never_rewrites_failure_record(tmp_path):
    module, bindings, owners = owner_fixture(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.glob('*.owner.json')}
    with module.parked_owner_locks(tmp_path, bindings, owners) as assert_owned:
        assert_owned()
    assert {path.name: path.read_bytes() for path in tmp_path.glob('*.owner.json')} == before


@pytest.mark.parametrize('mutation', ('active', 'proof', 'replaced_inode'))
def test_owner_change_blocks_assertion(tmp_path, mutation):
    module, bindings, owners = owner_fixture(tmp_path)
    with module.parked_owner_locks(tmp_path, bindings, owners) as assert_owned:
        if mutation == 'replaced_inode':
            replacement = tmp_path/'replacement'
            replacement.touch(mode=0o600)
            replacement.replace(tmp_path/'live.owner.lock')
        else:
            record = dict(owners['live']['record'])
            record['phase' if mutation == 'active' else 'proof'] = 'active' if mutation == 'active' else {}
            (tmp_path/'live.owner.json').write_text(json.dumps(record))
        with pytest.raises(ValueError, match='OWNER_'):
            assert_owned()


def test_missing_owner_inode_is_not_created(tmp_path):
    module, bindings, owners = owner_fixture(tmp_path)
    path = tmp_path/'live.owner.lock'
    path.unlink()
    with pytest.raises(FileNotFoundError):
        with module.parked_owner_locks(tmp_path, bindings, owners):
            pass
    assert not path.exists()



def test_scheduled_after_market_uses_lock_without_inventing_owner_record(tmp_path):
    module, bindings, original = owner_fixture(tmp_path)
    (tmp_path/'after-market.owner.json').unlink()
    frozen = module.owners(tmp_path)
    assert frozen['after-market']['record'] is None
    with module.parked_owner_locks(tmp_path, bindings, frozen) as assert_owned:
        assert_owned()
    assert not (tmp_path/'after-market.owner.json').exists()
    (tmp_path/'live.owner.json').unlink()
    with pytest.raises(ValueError, match='OWNER_STATE_MISSING'):
        module.owners(tmp_path)



def test_task_plan_hash_binds_failure_proof_and_cli():
    module = cli()
    payload = {'candidate': {'commit': 'a'*40}, 'original_owners': {'live': {'proof': 'failure'}},
               'cli_sha256': 'b'*64}
    original = module.task_plan_hash(payload)
    payload['task_plan_sha256'] = original
    assert module.task_plan_hash(payload) == original
    payload['original_owners']['live']['proof'] = 'changed'
    assert module.task_plan_hash(payload) != original



def test_file_bounds_reject_oversize_without_partial_read(tmp_path):
    module = cli()
    path = tmp_path/'plan.json'
    path.write_bytes(b'123456')
    with pytest.raises(ValueError, match='TASK_FILE_INVALID'):
        module.read_file(path, limit=5)
    assert module.read_file(path, limit=6) == b'123456'
    assert module.MAX_PLAN_BYTES >= 128*1024*1024



def test_deployment_lock_excludes_restore_before_other_locks(tmp_path, monkeypatch):
    from app.runtime_handover import deployment_lock, HandoverError
    module, bindings, original = owner_fixture(tmp_path)
    called = []
    monkeypatch.setattr(module, 'parked_owner_locks', lambda *args: called.append(args))
    with deployment_lock(runtime_dir=tmp_path):
        with pytest.raises(HandoverError, match='RUNTIME_DEPLOYMENT_BUSY'):
            with module.restore_locks(tmp_path, bindings, original, ('rb',)):
                pytest.fail('restore entered while deployment was running')
    assert called == []


def test_restore_holds_deployment_through_readback_scope(tmp_path, monkeypatch):
    from app.runtime_handover import deployment_lock, HandoverError
    module, bindings, original = owner_fixture(tmp_path)
    monkeypatch.setenv('GUIYI_RUNTIME_HANDOVER_ENABLED', '0')
    monkeypatch.setattr('app.runtime_bindings.read_bindings', lambda *args, **kwargs: None)
    before = {path.name: path.read_bytes() for path in tmp_path.glob('*.owner.json')}
    with module.restore_locks(tmp_path, bindings, original, ('rb',)) as assert_owned:
        assert_owned()
        with pytest.raises(HandoverError, match='RUNTIME_DEPLOYMENT_BUSY'):
            with deployment_lock(runtime_dir=tmp_path):
                pytest.fail('promotion entered during restore/readback')
    with deployment_lock(runtime_dir=tmp_path):
        pass
    assert {path.name: path.read_bytes() for path in tmp_path.glob('*.owner.json')} == before
