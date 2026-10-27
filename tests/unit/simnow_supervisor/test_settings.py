"""Private configuration contract; no SDK, Keychain or broker calls."""

import json
import os

import pytest

from guiyi_quant.simnow_execution.settings import load_settings


def fixture(tmp_path):
    project = tmp_path / "project"
    (project / "scripts/broker").mkdir(parents=True)
    (project / "scripts/broker/simnow_controlled.py").touch()
    (project / "output").mkdir()
    state = project / "output/simnow-controlled"
    python = tmp_path / "python-real"
    python.touch(mode=0o700)
    sdk_python = tmp_path / "sdk-python"
    sdk_python.symlink_to(python)
    api_env = tmp_path / "api-venv"
    api_env.mkdir()
    config = tmp_path / "private.json"
    value = {
        "schema": 1,
        "account_id": "a" * 64,
        "state_root": str(state),
        "project_root": str(project),
        "sdk_python": str(sdk_python),
        "api_env": str(api_env),
        "mode": "observe",
        "enabled": False,
    }
    return config, value


def write(config, value):
    config.write_text(json.dumps(value))
    config.chmod(0o600)


def test_valid_config_preserves_venv_symlink_and_does_not_create_state(tmp_path):
    config, value = fixture(tmp_path)
    write(config, value)
    result = load_settings(config)
    assert result.schema == 1
    assert result.account_id == "a" * 64
    assert str(result.sdk_python) == value["sdk_python"]
    assert str(result.api_env) == value["api_env"]
    assert result.mode == "observe" and result.enabled is False
    assert not result.state_root.exists()


def test_manage_mode_is_valid_for_private_supervisor_config(tmp_path):
    config, value = fixture(tmp_path)
    value["mode"] = "manage"
    value["enabled"] = True
    write(config, value)
    result = load_settings(config)
    assert result.mode == "manage" and result.enabled is True


@pytest.mark.parametrize(
    "field,bad",
    [
        ("schema", True),
        ("schema", 2),
        ("account_id", "A" * 64),
        ("account_id", "not-an-account"),
        ("mode", "live"),
        ("enabled", 1),
        ("state_root", "/tmp/other-root"),
        ("project_root", "relative"),
        ("sdk_python", "/no/such/python"),
        ("api_env", "/no/such/venv"),
    ],
)
def test_rejects_invalid_exact_fields(tmp_path, field, bad):
    config, value = fixture(tmp_path)
    value[field] = bad
    write(config, value)
    with pytest.raises(ValueError):
        load_settings(config)


def test_rejects_unknown_missing_and_duplicate_keys(tmp_path):
    config, value = fixture(tmp_path)
    value["secret"] = "must not be accepted"
    write(config, value)
    with pytest.raises(ValueError):
        load_settings(config)
    del value["secret"]
    del value["enabled"]
    write(config, value)
    with pytest.raises(ValueError):
        load_settings(config)
    config.write_text('{"schema":1,"schema":1}')
    config.chmod(0o600)
    with pytest.raises(ValueError):
        load_settings(config)


def test_requires_owner_regular_0600_non_symlink_and_bounded_json(tmp_path):
    config, value = fixture(tmp_path)
    write(config, value)
    config.chmod(0o644)
    with pytest.raises(ValueError):
        load_settings(config)
    config.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(config)
    with pytest.raises(ValueError):
        load_settings(link)
    config.write_text("x" * 8192)
    with pytest.raises(ValueError):
        load_settings(config)
    config.unlink()
    config.mkdir()
    with pytest.raises(ValueError):
        load_settings(config)


def test_rejects_public_or_symlink_state_root(tmp_path):
    config, value = fixture(tmp_path)
    state = tmp_path / "project/output/simnow-controlled"
    state.mkdir(mode=0o755)
    write(config, value)
    with pytest.raises(ValueError):
        load_settings(config)
    state.rmdir()
    state.symlink_to(tmp_path / "api-venv")
    with pytest.raises(ValueError):
        load_settings(config)


def test_rejects_output_parent_symlink_that_redirects_account_root(tmp_path):
    config, value = fixture(tmp_path)
    output = tmp_path / "project/output"
    output.rmdir()
    external = tmp_path / "external"
    external.mkdir()
    output.symlink_to(external)
    write(config, value)
    with pytest.raises(ValueError, match="SETTINGS_STATE_INVALID"):
        load_settings(config)


def test_rejects_non_owner_private_config(tmp_path, monkeypatch):
    config, value = fixture(tmp_path)
    write(config, value)
    monkeypatch.setattr(os, "getuid", lambda: -1)
    with pytest.raises(ValueError):
        load_settings(config)
