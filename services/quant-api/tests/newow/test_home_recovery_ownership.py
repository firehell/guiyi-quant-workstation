"""Ownership and process-liveness regressions; never mutate a live Runtime."""
import os
import select
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app.market_data.newow import home_recovery
from app.market_data.newow.home_projection import ProjectionError


@pytest.mark.parametrize('enabled', [False, True])
def test_formal_cli_never_constructs_an_unsupervised_writer(tmp_path, monkeypatch, enabled):
    from app.market_data import composition
    from app.market_data.newow import home_projection_composition
    from app import runtime_bindings
    canonical = tmp_path / 'canonical'
    target = canonical / '.derived/newow-home.json'
    home = SimpleNamespace(store=SimpleNamespace(path=target), read=lambda: {'read_only': True})
    monkeypatch.setattr(composition, 'canonical_root', lambda: canonical)
    monkeypatch.setattr(home_projection_composition, 'build_home_projection', lambda **_: home)
    monkeypatch.setattr(runtime_bindings, 'resolve_service_binding', lambda _: SimpleNamespace(enabled=enabled))
    def forbidden(*_, **__):
        raise AssertionError('formal CLI created an independent writer')
    monkeypatch.setattr(home_recovery, 'HomeRecovery', forbidden)
    if enabled:
        assert home_recovery.run_home_build(output_path=target) == {'read_only': True, 'build_request': {'mode': 'owner', 'readonly': True}}
    else:
        with pytest.raises(ProjectionError):
            home_recovery.run_home_build()
    assert not target.exists()


def test_owner_heartbeat_stays_fresh_and_never_reactivates_drain():
    clock = [0]
    drained = [False]
    beats, assertions = [], []
    guard, ready = home_recovery.owner_heartbeat(
        lambda: assertions.append(clock[0]), lambda: beats.append(clock[0]), lambda: drained[0],
        clock=lambda: clock[0])
    guard()
    assert beats == []
    ready()
    for second in range(1, 66):
        clock[0] = second
        guard()
    assert beats == list(range(0, 66, 5))
    drained[0] = True
    clock[0] = 90
    guard()
    assert beats[-1] == 65 and assertions[-1] == 90


def test_parent_death_before_registration_reaps_actual_gated_child(tmp_path):
    # The helper dies before sending G. Application imports/DB access never start.
    program = r'''
import os, subprocess, sys, time
reader, writer = os.pipe()
process = subprocess.Popen([sys.executable, '-B', sys.argv[1], '--product', 'rb', '--period', '1d',
 '--token', 'a' * 32, '--parent-fd', str(reader)], pass_fds=(reader,),
 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
os.close(reader)
print(process.pid, flush=True)
time.sleep(20)
'''
    parent = subprocess.Popen([sys.executable, '-B', '-c', program, str(home_recovery.Path(home_recovery.__file__).with_name('home_child_bootstrap.py'))], stdout=subprocess.PIPE, text=True,
                              env={**os.environ, 'GUIYI_HOME_CHILD_ROOT': str(tmp_path / 'home.json.children')})
    pid = None
    try:
        assert select.select([parent.stdout], [], [], 3)[0]
        pid = int(parent.stdout.readline())
        parent.kill()
        parent.wait(timeout=2)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            state = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'stat='], capture_output=True,
                                   text=True, timeout=1).stdout.strip()
            if not state or state.startswith('Z'):
                break
            time.sleep(.03)
        else:
            pytest.fail('unregistered child survived parent pipe EOF')
        assert not list(tmp_path.rglob('*.json'))
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)
        if parent.stdout:
            parent.stdout.close()
        if pid:
            subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'stat='], capture_output=True, timeout=1)
