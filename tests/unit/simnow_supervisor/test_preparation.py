"""Independent preparation cannot establish account facts or activate a host."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess

import pytest

from guiyi_quant.simnow_execution.settings import load_settings
from test_settings import fixture, write
from test_service import service
from test_runner_environment import runner


def preparation(tmp_path):
    config, value = fixture(tmp_path)
    anchor = tmp_path / "independent"
    anchor.mkdir(mode=0o700)
    value.update(schema=3, state_project_root=str(anchor),
                 state_root=str(anchor / "output/simnow-controlled"))
    write(config, value)
    return config, value


def test_preparation_loads_without_creating_or_assuming_account(tmp_path):
    config, value = preparation(tmp_path)
    settings = load_settings(config)
    assert settings.schema == 3 and not settings.enabled
    assert settings.mode == "observe"
    assert settings.state_project_root == Path(value["state_project_root"])
    assert not settings.state_root.exists()


@pytest.mark.parametrize("field,value", [("enabled", True), ("mode", "manage"), ("mode", "trade")])
def test_preparation_rejects_any_activation(tmp_path, field, value):
    config, data = preparation(tmp_path)
    data[field] = value
    write(config, data)
    with pytest.raises(ValueError, match="PREPARATION"):
        load_settings(config)


@pytest.mark.parametrize("fault", ["code_anchor", "public_anchor", "symlink_anchor", "parent_alias", "reused_state", "output_alias"])
def test_preparation_rejects_aliases_reuse_and_wrong_permissions(tmp_path, fault):
    config, value = preparation(tmp_path)
    anchor = Path(value["state_project_root"])
    state = Path(value["state_root"])
    if fault == "code_anchor":
        value.update(state_project_root=value["project_root"],
                     state_root=str(Path(value["project_root"]) / "output/simnow-controlled"))
    elif fault == "public_anchor":
        anchor.chmod(0o755)
    elif fault == "symlink_anchor":
        link = tmp_path / "alias"
        link.symlink_to(anchor, target_is_directory=True)
        value.update(state_project_root=str(link), state_root=str(link / "output/simnow-controlled"))
    elif fault == "parent_alias":
        link = tmp_path / "alias"
        link.symlink_to(tmp_path, target_is_directory=True)
        value.update(state_project_root=str(link / "independent"),
                     state_root=str(link / "independent/output/simnow-controlled"))
    elif fault == "reused_state":
        state.mkdir(mode=0o700, parents=True)
        (state / "account.sqlite").write_bytes(b"must remain unchanged")
    else:
        (anchor / "output").symlink_to(Path(value["project_root"]) / "output", target_is_directory=True)
    write(config, value)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file() and not p.is_symlink()}
    with pytest.raises(ValueError):
        load_settings(config)
    assert before == {p: p.read_bytes() for p in before}


def test_preparation_preflight_is_readonly_and_does_not_establish_runtime_readiness(tmp_path, monkeypatch):
    from guiyi_quant.simnow_execution import credentials, supervisor
    import socket

    config, value = preparation(tmp_path)
    settings = load_settings(config)
    (settings.project_root / "scripts/broker/simnow_supervisor.py").touch()
    before = set(tmp_path.rglob("*"))
    monkeypatch.setattr(credentials.CredentialStore, "load", lambda *_: pytest.fail("credentials read"))
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: pytest.fail("network"))
    monkeypatch.setattr(socket.socket, "connect", lambda *_args: pytest.fail("network"))
    monkeypatch.setattr(supervisor, "account_lock", lambda *_: pytest.fail("runtime lock"))

    def sdk_check(args, **kwargs):
        assert args == [str(settings.sdk_python), "-I", "-B",
                        str(settings.project_root / "scripts/broker/simnow_supervisor.py"),
                        "--config", str(config), "--observe-only", "--check"]
        assert kwargs["timeout"] <= 30
        return SimpleNamespace(returncode=0, stdout="CONTINUOUS_CONFIG_SDK_COMPATIBLE_NO_BROKER_IO\n")

    monkeypatch.setattr(subprocess, "run", sdk_check)
    result = service.preflight_preparation(settings, config)
    assert result == {
        "schema": "simnow_preparation_preflight_v1", "preparation_valid": True,
        "old_account_state": "UNKNOWN", "new_account_state": "UNINITIALIZED",
        "account_reconciled": False, "balance_verified": False, "positions_verified": False,
        "runtime_ready": False, "execution_permitted": False, "broker_io": False,
        "credentials_loaded": False, "mode": "observe", "enabled": False,
    }
    assert set(tmp_path.rglob("*")) == before
    assert json.loads(json.dumps(result))["balance_verified"] is False


@pytest.mark.parametrize("fault", ["returncode", "output", "timeout"])
def test_preparation_preflight_fails_closed_for_sdk_failure(tmp_path, monkeypatch, fault):
    config, _ = preparation(tmp_path)
    settings = load_settings(config)
    (settings.project_root / "scripts/broker/simnow_supervisor.py").touch()

    def sdk_check(*args, **kwargs):
        if fault == "timeout":
            raise subprocess.TimeoutExpired(args[0], 30)
        return SimpleNamespace(returncode=1 if fault == "returncode" else 0, stdout="unverified")

    monkeypatch.setattr(subprocess, "run", sdk_check)
    with pytest.raises(ValueError, match="PREPARATION_SDK"):
        service.preflight_preparation(settings, config)
    assert not settings.state_root.exists()


def test_preparation_cannot_render_install_or_acquire_account_locks(tmp_path):
    from guiyi_quant.simnow_execution.supervisor import account_lock

    config, _ = preparation(tmp_path)
    settings = load_settings(config)
    for action in (service.render_launch_agent, service.install_observe, service.render_trade_launch_agent):
        with pytest.raises(ValueError):
            action(settings, config)
    with pytest.raises(ValueError, match="PREPARATION"):
        with account_lock(replace(settings, enabled=True)):
            pytest.fail("host entered")
    assert not settings.state_root.exists()


@pytest.mark.parametrize("flag", [None, "--check-keychain"])
def test_preparation_runner_rejects_start_or_keychain_before_sdk(tmp_path, monkeypatch, flag):
    from guiyi_quant.simnow_execution import settings, credentials

    config, _ = preparation(tmp_path)
    loaded = replace(load_settings(config), project_root=Path(runner.__file__).resolve().parents[2])
    monkeypatch.setattr(settings, "load_settings", lambda _: loaded)
    monkeypatch.setattr(credentials.CredentialStore, "load", lambda *_: pytest.fail("credentials read"))
    monkeypatch.setattr(runner.importlib.util, "spec_from_file_location", lambda *_: pytest.fail("SDK bootstrapped"))
    args = ["--config", str(config), "--observe-only"] + ([flag] if flag else [])
    with pytest.raises(ValueError, match="PREPARATION"):
        runner.main(args)


@pytest.mark.parametrize("change", ["settings", "account"])
def test_preparation_preflight_does_not_accept_state_changes_during_sdk_check(tmp_path, monkeypatch, change):
    config, value = preparation(tmp_path)
    settings = load_settings(config)
    (settings.project_root / "scripts/broker/simnow_supervisor.py").touch()

    def sdk_check(*_args, **_kwargs):
        if change == "settings":
            value["account_id"] = "b" * 64
            write(config, value)
        else:
            (settings.state_project_root / "output").mkdir(mode=0o700)
            settings.state_root.mkdir(mode=0o700)
            (settings.state_root / "unexpected.sqlite").touch(mode=0o600)
        return SimpleNamespace(returncode=0, stdout="CONTINUOUS_CONFIG_SDK_COMPATIBLE_NO_BROKER_IO\n")

    monkeypatch.setattr(subprocess, "run", sdk_check)
    with pytest.raises(ValueError, match="PREPARATION"):
        service.preflight_preparation(settings, config)
