import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from guiyi_quant.simnow_execution.credentials import CredentialError, fingerprint_for


SCRIPT = Path(__file__).parents[3] / "scripts/broker/simnow_credentials.py"
SPEC = importlib.util.spec_from_file_location("simnow_credentials_cli", SCRIPT)
assert SPEC and SPEC.loader
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


class FakeStore:
    def __init__(self):
        self.saved = None

    def save(self, user, password):
        self.saved = (user, password)
        return "a" * 64


class TtyOutput(io.StringIO):
    def isatty(self):
        return True


def test_provision_requires_tty_before_prompt(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(cli.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("prompted without TTY"))
    with pytest.raises(CredentialError, match="LOCAL_TTY_REQUIRED"):
        cli.provision(FakeStore())


def test_provision_uses_hidden_input_and_returns_only_fingerprint(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: "123456")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "fake secret")
    store = FakeStore()
    assert cli.provision(store) == "a" * 64
    assert store.saved == ("123456", "fake secret")


def test_expected_account_mismatch_rejects_before_password_or_keychain_write(
    monkeypatch,
):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: "123456")
    monkeypatch.setattr(
        cli.getpass, "getpass", lambda _: pytest.fail("password prompted")
    )
    store = FakeStore()
    with pytest.raises(CredentialError, match="CREDENTIAL_IDENTITY_MISMATCH"):
        cli.provision(store, "b" * 64)
    assert store.saved is None


def test_matching_expected_account_allows_provision(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda _: "123456")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "fake secret")
    store = FakeStore()
    assert cli.provision(store, fingerprint_for("123456")) == "a" * 64
    assert store.saved == ("123456", "fake secret")


def test_cli_expected_account_flag_is_checked_before_store_save(monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    output, errors = TtyOutput(), io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", output)
    monkeypatch.setattr(cli.sys, "stderr", errors)
    monkeypatch.setattr("builtins.input", lambda _: "123456")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "fake secret")
    store = FakeStore()
    monkeypatch.setattr(cli, "CredentialStore", lambda: store)
    assert cli.main(["provision", "--expected-account-id", "b" * 64]) == 2
    assert store.saved is None and output.getvalue() == ""
    assert errors.getvalue().strip() == "CREDENTIAL_IDENTITY_MISMATCH"
    errors.seek(0)
    errors.truncate(0)
    assert (
        cli.main(["provision", "--expected-account-id", fingerprint_for("123456")]) == 0
    )
    assert store.saved == ("123456", "fake secret")
    assert output.getvalue().strip() == f"CREDENTIAL_STORED account_id={'a' * 64}"
