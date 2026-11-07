"""Home worker installer uses only an isolated fixture and a fake launchctl."""
import plistlib
import shutil

import pytest

from test_market_runtime_launchd import (
    _copy_launchd_fixture, _run_installer_result, _run_status, _status_fixture,
)


@pytest.mark.parametrize('fail_install', [False, True])
def test_explicit_home_install_keeps_other_jobs_and_restores_failure_preimage(tmp_path, fail_install):
    repo = _copy_launchd_fixture(tmp_path / 'repo')
    home, fake_bin = tmp_path / 'home', tmp_path / 'bin'
    fake_bin.mkdir()
    launchctl = fake_bin / 'launchctl'
    launchctl.write_text(
        '#!/bin/sh\n'
        'if [ "$1" = print ] && [ "$2" = "gui/$UID" ]; then exit 0; fi\n'
        'if [ "$1" = print ]; then exit 113; fi\n'
        'printf "%s\\n" "$*" >> "$HOME/calls"\n'
        + ('if [ "$1" = bootstrap ]; then exit 81; fi\n' if fail_install else '')
        + 'exit 0\n'
    )
    launchctl.chmod(0o755)
    agents = home / 'Library/LaunchAgents'
    agents.mkdir(parents=True)
    api = agents / 'com.guiyi.quant-api.plist'
    original = plistlib.dumps({'EnvironmentVariables': {
        'GUIYI_PROJECT_ROOT': str(repo), 'GUIYI_RUNTIME_COMMIT': '1' * 40,
    }})
    api.write_bytes(original)
    shared = home / 'Library/Application Support/GuiyiQuant/run-local-service.sh'
    shared.parent.mkdir(parents=True)
    shutil.copy2(repo / 'scripts/ops/macos/run-local-service.sh', shared)
    original_launcher = shared.read_bytes()
    rendered = _run_installer_result(repo, home, fake_bin, '--render-only')
    assert rendered.returncode == 0
    assert not (repo / '.run/home-projection-enabled').exists()
    assert not (agents / 'com.guiyi.quant-home-projection.plist').exists()
    assert not (home / 'calls').exists()
    result = _run_installer_result(repo, home, fake_bin, '--confirm-home-projection')
    assert (result.returncode != 0) is fail_install
    assert shared.read_bytes() == original_launcher
    assert api.read_bytes() == original
    marker = repo / '.run/home-projection-enabled'
    plist = agents / 'com.guiyi.quant-home-projection.plist'
    if fail_install:
        assert not marker.exists()
        assert not plist.exists()
    else:
        assert marker.read_text() == 'enabled\n'
        assert plistlib.loads(plist.read_bytes())['ProgramArguments'][-1] == 'home-projection'
    assert not (repo / '.run/reference-worker-enabled').exists()
    assert all('quant-home-projection' in call for call in (home / 'calls').read_text().splitlines())


def test_home_status_is_readonly_and_rejects_orphan_definition(tmp_path):
    repo, home, fake_bin, calls = _status_fixture(tmp_path)
    marker = repo / '.run/home-projection-enabled'
    marker.write_text('enabled\n')
    marker.chmod(0o600)
    agents = home / 'Library/LaunchAgents'
    api = plistlib.loads((agents / 'com.guiyi.quant-api.plist').read_bytes())
    (agents / 'com.guiyi.quant-home-projection.plist').write_bytes(plistlib.dumps({
        'Label': 'com.guiyi.quant-home-projection',
        'EnvironmentVariables': api['EnvironmentVariables'],
    }))
    active = _run_status(repo, home, fake_bin)
    assert active.returncode == 0
    assert 'home_projection_enabled=true' in active.stdout
    marker.unlink()
    orphan = _run_status(repo, home, fake_bin)
    assert orphan.returncode != 0
    assert 'home_projection_orphan_plist=true' in orphan.stdout
    assert not calls.exists()
