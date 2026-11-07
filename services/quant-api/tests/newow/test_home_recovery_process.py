"""Real subprocess fault injection only: these fixtures are not business/runtime acceptance."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app.market_data.newow.home_projection import ProjectionStore
from app.market_data.newow.home_recovery import (
    HomeComputeError, IsolatedCompute, process_identity, stop_child,
)
from app.market_data.newow.home_recovery_state import RecoveryPolicy, WorkStore


@pytest.fixture
def processes():
    owned = []
    try:
        yield owned
    finally:
        for process in owned:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            else:
                process.wait(timeout=1)
        assert all(process.poll() is not None for process in owned)


class ChildFactory:
    """Keep the actual isolated-compute contract while substituting a tiny child program."""
    def __init__(self, processes, mode='sleep'):
        self.processes, self.mode = processes, mode
        self.arguments = []

    def __call__(self, command, **kwargs):
        self.arguments.append((command, kwargs))
        token = command[command.index('--token') + 1]
        script = '''
import os
from pathlib import Path
import sys
import time
mode, token = sys.argv[1:]
if mode == 'sleep':
    time.sleep(10)
elif mode == 'stdout':
    print('{"ok":true,"items":{"facts":{"invented":"stdout"}}}', flush=True)
    time.sleep(.05)
elif mode != 'missing':
    from app.market_data.newow.home_projection import ProjectionStore
    root = Path(os.environ['GUIYI_HOME_CHILD_ROOT'])
    payload = {'schema_version':'newow_home_compute_v1',
               'token': '0' * 32 if mode == 'wrong-token' else token,
               'ok':True, 'items':{'facts':{'trend':{'state':'HOLD'}, 'oscillation':{'state':'FLAT'}}}}
    ProjectionStore(root / (token + '.json'), schema='newow_home_compute_v1').save(payload)
'''
        process = subprocess.Popen([sys.executable, '-B', '-c', script, self.mode, token], **kwargs)
        self.processes.append(process)
        return process


def fixture(tmp_path, processes, *, mode='sleep', seconds=.15, register_error=False, stop=None):
    home_store = ProjectionStore(tmp_path / 'home.json')
    home_store.save({'schema_version': 'newow_home_projection_v1', 'items': {}, 'untouched': 'last-good'})
    before = home_store.path.read_bytes()
    work = WorkStore(home_store.path)
    state = work.state()
    registrations, clears = [], []

    def register(child):
        registrations.append(deepcopy(child))
        state['child'] = child
        work.save(state)
        if register_error:
            raise RuntimeError('simulated register persistence failure')

    def clear():
        clears.append(True)
        state.pop('child', None)
        work.save(state)

    factory = ChildFactory(processes, mode)
    compute = IsolatedCompute(
        SimpleNamespace(store=home_store), RecoveryPolicy(period_seconds=seconds), register, clear,
        assert_owned=lambda: None, stop_requested=stop or (lambda: False), popen=factory,
    )
    return compute, factory, home_store, before, work, registrations, clears


def assert_clean(factory, store, before, work, clears):
    assert len(factory.processes) == 1
    assert factory.processes[0].poll() is not None
    assert factory.processes[0].wait(timeout=1) is not None
    assert store.path.read_bytes() == before
    assert 'child' not in work.state()
    assert len(clears) == 1
    child_root = store.path.with_name(store.path.name + '.children')
    assert not child_root.exists() or not list(child_root.glob('*.json'))


def test_parent_hard_deadline_terminates_real_sleeping_child_and_clears_registration(tmp_path, processes):
    compute, factory, store, before, work, registrations, clears = fixture(tmp_path, processes)
    started = time.monotonic()
    with pytest.raises(HomeComputeError) as result:
        compute('rb', '1d')
    assert result.value.detail == {'category': 'timeout', 'code': 'HOME_COMPUTE_TIMEOUT', 'stage': '1d'}
    assert time.monotonic() - started < 3
    assert len(registrations) == 1
    assert registrations[0]['pid'] == processes[0].pid
    assert len(registrations[0]['identity']) == 64
    assert compute.errors == [result.value.detail]
    assert_clean(factory, store, before, work, clears)


def test_registration_exception_still_reaps_child_and_clears_journal(tmp_path, processes):
    compute, factory, store, before, work, registrations, clears = fixture(tmp_path, processes, register_error=True)
    with pytest.raises(RuntimeError, match='register persistence failure'):
        compute('rb', '1w')
    assert len(registrations) == 1
    assert_clean(factory, store, before, work, clears)


def test_parent_stop_request_is_interrupted_and_reaps_child(tmp_path, processes):
    compute, factory, store, before, work, registrations, clears = fixture(tmp_path, processes, seconds=2, stop=lambda: True)
    with pytest.raises(HomeComputeError) as result:
        compute('rb', '1w')
    assert result.value.detail == {'category': 'interrupted', 'code': 'HOME_COMPUTE_INTERRUPTED', 'stage': '1w'}
    assert len(registrations) == 1
    assert_clean(factory, store, before, work, clears)


def test_orphan_cleanup_requires_exact_registered_process_identity(processes):
    child = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(10)'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(child)
    identity = process_identity(child.pid)
    assert identity is not None
    stop_child(child.pid, '0' * 64)
    assert child.poll() is None
    stop_child(child.pid, identity)
    assert child.wait(timeout=1) is not None
    assert process_identity(child.pid) is None


@pytest.mark.parametrize('mode', ['missing', 'wrong-token', 'stdout'])
def test_missing_or_wrong_token_output_and_arbitrary_stdout_are_never_accepted(tmp_path, processes, mode):
    compute, factory, store, before, work, _, clears = fixture(tmp_path, processes, mode=mode, seconds=2)
    with pytest.raises(HomeComputeError) as result:
        compute('rb', '1d')
    assert result.value.detail['category'] == 'unknown'
    assert result.value.detail['code'] == 'HOME_COMPUTE_EXITED'
    assert_clean(factory, store, before, work, clears)


def test_verified_child_store_envelope_returns_only_owned_facts(tmp_path, processes):
    compute, factory, store, before, work, _, clears = fixture(tmp_path, processes, mode='normal', seconds=2)
    assert compute('rb', '1d') == {'trend': {'state': 'HOLD'}, 'oscillation': {'state': 'FLAT'}}
    command, options = factory.arguments[0]
    assert command[command.index('--product') + 1] == 'rb'
    assert command[command.index('--period') + 1] == '1d'
    assert Path(options['env']['GUIYI_HOME_CHILD_ROOT']).parent == store.path.parent
    assert options['stdout'] == subprocess.DEVNULL and options['stderr'] == subprocess.DEVNULL
    assert compute.errors == []
    assert_clean(factory, store, before, work, clears)
