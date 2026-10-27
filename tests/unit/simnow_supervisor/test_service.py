import importlib.util
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[3] / "scripts/ops/macos/simnow-service.py"
SPEC = importlib.util.spec_from_file_location("simnow_service", SCRIPT)
assert SPEC and SPEC.loader
service = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(service)


def settings(tmp_path, *, mode="observe", enabled=False):
    root = tmp_path / "project"
    state = tmp_path / "state"
    root.mkdir()
    state.mkdir(mode=0o700)
    (root / "scripts/broker").mkdir(parents=True)
    (root / "scripts/broker/simnow_supervisor.py").touch()
    python = tmp_path / "python"
    python.touch(mode=0o700)
    return SimpleNamespace(
        account_id="a" * 64,
        state_root=state,
        project_root=root,
        sdk_python=python,
        api_env=tmp_path / "private.env",
        mode=mode,
        enabled=enabled,
    )


def test_render_observe_is_deterministic_and_has_no_secrets(tmp_path):
    config = tmp_path / "private.json"
    config.write_text("{}")
    config_settings = settings(tmp_path)
    data = service.render_launch_agent(config_settings, config)
    payload = plistlib.loads(data)
    assert payload["Label"] == "com.guiyi.quant-simnow"
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["ThrottleInterval"] == 60
    assert payload["ProgramArguments"][-3:] == [
        "--config",
        str(config),
        "--observe-only",
    ]
    assert "password" not in data.decode().lower()
    assert service.render_launch_agent(config_settings, config) == data


@pytest.mark.parametrize("mode", ["manage", "execute", "live"])
def test_renderer_rejects_non_observe_mode(tmp_path, mode):
    with pytest.raises(ValueError, match="OBSERVE_ONLY"):
        service.render_launch_agent(
            settings(tmp_path, mode=mode), tmp_path / "private.json"
        )


def test_renderer_accepts_venv_python_symlink(tmp_path):
    config = tmp_path / "private.json"
    config.write_text("{}")
    value = settings(tmp_path)
    link = tmp_path / "venv-python"
    link.symlink_to(value.sdk_python)
    value.sdk_python = link
    payload = plistlib.loads(service.render_launch_agent(value, config))
    assert payload["ProgramArguments"][0] == str(link)


def test_installer_only_accepts_private_enabled_observe_and_never_loads(tmp_path):
    config = tmp_path / "private.json"
    config.write_text("{}")
    config.chmod(0o600)
    value = settings(tmp_path, enabled=True)
    target = service.install_observe(value, config, home=tmp_path / "home")
    assert target.name == "com.guiyi.quant-simnow.plist"
    assert target.stat().st_mode & 0o777 == 0o600
    logs = tmp_path / "home/Library/Logs/GuiyiQuant/SimNow"
    assert logs.stat().st_mode & 0o777 == 0o700
    assert plistlib.loads(target.read_bytes())["StandardOutPath"] == str(
        logs / "supervisor.out.log"
    )
    assert not (value.state_root / ".logs").exists()
    with pytest.raises(ValueError, match="SERVICE_ALREADY_EXISTS"):
        service.install_observe(value, config, home=tmp_path / "home")


def test_installer_rejects_nonprivate_config_and_disabled_setting(tmp_path):
    config = tmp_path / "private.json"
    config.write_text("{}")
    value = settings(tmp_path, enabled=True)
    config.chmod(0o644)
    with pytest.raises(ValueError, match="PRIVATE_PATH_REQUIRED"):
        service.install_observe(value, config, home=tmp_path / "home")
    config.chmod(0o600)
    value.enabled = False
    with pytest.raises(ValueError, match="OBSERVE_ENABLED_REQUIRED"):
        service.install_observe(value, config, home=tmp_path / "home")


def test_renderer_uses_user_logs_instead_of_external_volume(tmp_path):
    config = tmp_path / "private.json"
    config.write_text("{}")
    value = settings(tmp_path)
    home = tmp_path / "home"
    result = plistlib.loads(service.render_launch_agent(value, config, home=home))
    logs = home / "Library/Logs/GuiyiQuant/SimNow"
    assert result["StandardOutPath"] == str(logs / "supervisor.out.log")
    assert result["StandardErrorPath"] == str(logs / "supervisor.err.log")
    assert result["WorkingDirectory"] == str(value.project_root)
    assert result["ProgramArguments"][-1] == "--observe-only"


def test_trade_render_is_explicit_and_never_overwrites_observe_installer(tmp_path):
    value = settings(tmp_path, mode="trade")
    value.schema = 2
    config = tmp_path / "trade.json"
    config.write_text("{}")
    config.chmod(0o600)
    result = plistlib.loads(service.render_trade_launch_agent(value, config))
    assert result["Label"] == "com.guiyi.quant-simnow"
    assert result["ProgramArguments"][-1] == "--trade"
    assert not (tmp_path / "home").exists()
    with pytest.raises(ValueError, match="OBSERVE_ONLY"):
        service.render_launch_agent(value, config)
    with pytest.raises(ValueError, match="OBSERVE_ENABLED_REQUIRED"):
        service.install_observe(value, config, home=tmp_path / "home")


def test_trade_preflight_reads_binding_without_creating_locks_or_loading_keychain(
    tmp_path, monkeypatch
):
    from test_settings import existing_v2
    from guiyi_quant.simnow_execution.settings import load_settings
    from guiyi_quant.simnow_execution import credentials, supervisor

    config, value, folder = existing_v2(tmp_path)
    project = Path(value["project_root"])
    (project / "scripts/broker/simnow_supervisor.py").touch()
    monkeypatch.setattr(
        credentials.CredentialStore, "load", lambda *_: pytest.fail("Keychain loaded")
    )
    monkeypatch.setattr(
        supervisor, "global_account_lock_directory", lambda: tmp_path / "never-created"
    )
    result = service.preflight_trade(load_settings(config), config, products=("RB",))
    assert (
        result["candidate_valid"]
        and not result["execution_permitted"]
        and not result["broker_io"]
    )
    assert (
        not (tmp_path / "never-created").exists()
        and not (folder / "host.lock").exists()
    )
