"""Dependency auth normalization must match the existing local service launcher."""

import importlib.util
from pathlib import Path
from urllib.parse import unquote, urlsplit
from types import SimpleNamespace
import pytest


SPEC = importlib.util.spec_from_file_location(
    "continuous_runner",
    Path(__file__).parents[3] / "scripts/broker/simnow_supervisor.py",
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_documented_default_redis_url_uses_shared_password_without_mutating_source():
    source = {
        "REDIS_URL": "redis://127.0.0.1:6379/0",
        "POSTGRES_PASSWORD": "fixture @ value",
    }
    prepared = runner.dependency_environment(source)
    assert (
        unquote(urlsplit(prepared["REDIS_URL"]).password) == source["POSTGRES_PASSWORD"]
    )
    assert prepared["PGOPTIONS"] == "-c default_transaction_read_only=on"
    assert source["REDIS_URL"] == "redis://127.0.0.1:6379/0"


def test_explicit_redis_endpoint_and_auth_are_preserved():
    source = {
        "REDIS_URL": "redis://fixture:fixture@localhost:6380/4",
        "POSTGRES_PASSWORD": "other",
    }
    assert runner.dependency_environment(source)["REDIS_URL"] == source["REDIS_URL"]


def test_explicit_redis_password_wins_over_postgres_and_empty_url_is_normalized():
    source = {
        "REDIS_URL": "",
        "REDIS_PASSWORD": "redis fixture",
        "POSTGRES_PASSWORD": "pg fixture",
    }
    assert (
        unquote(urlsplit(runner.dependency_environment(source)["REDIS_URL"]).password)
        == source["REDIS_PASSWORD"]
    )


def test_keychain_only_check_never_bootstraps_sdk_or_market(
    monkeypatch, tmp_path, capsys
):
    from guiyi_quant.simnow_execution import settings, credentials

    account = "a" * 64
    config = SimpleNamespace(
        project_root=Path(runner.__file__).resolve().parents[2],
        mode="observe",
        account_id=account,
    )
    monkeypatch.setattr(settings, "load_settings", lambda _: config)

    class Store:
        def load(self, key):
            assert key == account
            return SimpleNamespace(account_id=key)

    monkeypatch.setattr(credentials, "CredentialStore", Store)
    monkeypatch.setattr(
        runner.importlib.util,
        "spec_from_file_location",
        lambda *_: pytest.fail("SDK must not load"),
    )
    assert (
        runner.main(
            ["--config", str(tmp_path / "config"), "--observe-only", "--check-keychain"]
        )
        == 0
    )
    assert (
        capsys.readouterr().out.strip()
        == "CONTINUOUS_KEYCHAIN_LOAD_VERIFIED_NO_BROKER_IO"
    )


def test_keychain_check_propagates_fixed_failure_without_network(monkeypatch, tmp_path):
    from guiyi_quant.simnow_execution import settings, credentials

    config = SimpleNamespace(
        project_root=Path(runner.__file__).resolve().parents[2],
        mode="observe",
        account_id="a" * 64,
    )
    monkeypatch.setattr(settings, "load_settings", lambda _: config)

    class Store:
        def load(self, _):
            raise credentials.CredentialError("CREDENTIAL_UNAVAILABLE")

    monkeypatch.setattr(credentials, "CredentialStore", Store)
    with pytest.raises(credentials.CredentialError, match="CREDENTIAL_UNAVAILABLE"):
        runner.main(
            ["--config", str(tmp_path / "config"), "--observe-only", "--check-keychain"]
        )


@pytest.mark.parametrize(
    "mode,flag",
    [
        ("trade", None),
        ("trade", "--observe-only"),
        ("observe", "--trade"),
        ("manage", "--trade"),
    ],
)
def test_trade_requires_matching_config_and_startup_flag_before_credentials(
    monkeypatch, tmp_path, mode, flag
):
    from guiyi_quant.simnow_execution import settings

    value = SimpleNamespace(
        project_root=Path(runner.__file__).resolve().parents[2], mode=mode
    )
    monkeypatch.setattr(settings, "load_settings", lambda _: value)
    monkeypatch.setattr(
        runner.importlib.util,
        "spec_from_file_location",
        lambda *_: pytest.fail("SDK loaded"),
    )
    args = ["--config", str(tmp_path / "config")] + ([flag] if flag else [])
    with pytest.raises(ValueError, match="CONTINUOUS_SOURCE_OR_MODE_INVALID"):
        runner.main(args)
