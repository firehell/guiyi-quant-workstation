import pytest
from test_settings import fixture, write
from guiyi_quant.simnow_execution.settings import load_settings


def configuration(tmp_path, monkeypatch):
    config, value = fixture(tmp_path)
    value.update(
        schema=2, mode="trade", enabled=True, state_project_root=value["project_root"]
    )
    monkeypatch.setattr(
        "guiyi_quant.simnow_execution.account_binding.existing_account", lambda *_: None
    )
    return config, value


def test_original_profile_is_explicit_and_account_bound(tmp_path, monkeypatch):
    config, value = configuration(tmp_path, monkeypatch)
    value["account_profile"] = {
        "profile_id": "original_anchor_v1",
        "account_id": value["account_id"],
        "initial_readback_sha256": "b" * 64,
    }
    write(config, value)
    result = load_settings(config)
    assert result.account_profile.profile_id == "original_anchor_v1"
    value["account_profile"]["account_id"] = "c" * 64
    write(config, value)
    with pytest.raises(ValueError):
        load_settings(config)


def test_ordinary_permit_is_pending_trade_only_and_excludes_extra(
    tmp_path, monkeypatch
):
    config, value = configuration(tmp_path, monkeypatch)
    directory = tmp_path / "attempt"
    directory.mkdir(mode=0o700)
    value.update(
        ordinary_takeover_permit=str(
            directory / "ordinary-takeover-permit.private.json"
        ),
        account_takeover_pending=True,
    )
    write(config, value)
    result = load_settings(config)
    assert (
        result.ordinary_takeover_permit.name == "ordinary-takeover-permit.private.json"
    )
    assert result.source_config_sha256 and result.source_config_path == config
    value["deployment_connection_permit"] = str(
        directory / "deployment-connection-permit.private.json"
    )
    write(config, value)
    with pytest.raises(ValueError):
        load_settings(config)


@pytest.mark.parametrize(
    "change",
    [
        "missing_pending",
        "observe",
        "disabled",
        "bad_name",
        "public_parent",
        "bad_profile",
    ],
)
def test_ordinary_configuration_rejects_unsafe_variants(tmp_path, monkeypatch, change):
    config, value = configuration(tmp_path, monkeypatch)
    directory = tmp_path / "intent"
    directory.mkdir(mode=0o700)
    value.update(
        ordinary_takeover_permit=str(
            directory / "ordinary-takeover-permit.private.json"
        ),
        account_takeover_pending=True,
    )
    if change == "missing_pending":
        value["account_takeover_pending"] = False
    elif change == "observe":
        value["mode"] = "observe"
    elif change == "disabled":
        value["enabled"] = False
    elif change == "bad_name":
        value["ordinary_takeover_permit"] = str(directory / "other.json")
    elif change == "public_parent":
        directory.chmod(0o755)
    else:
        value["account_profile"] = dict(
            profile_id="original_anchor_v1",
            account_id=value["account_id"],
            initial_readback_sha256="invalid",
        )
    write(config, value)
    with pytest.raises(ValueError):
        load_settings(config)
