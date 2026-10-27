"""Credential tests never call the real Keychain."""

import hashlib
import json

import pytest

from guiyi_quant.simnow_execution.credentials import (
    CredentialError,
    CredentialStore,
    Credentials,
    fingerprint_for,
)


class FakeBackend:
    def __init__(self):
        self.items = {}

    def add(self, account, data):
        if account in self.items:
            raise CredentialError("CREDENTIAL_ALREADY_EXISTS")
        self.items[account] = data

    def get(self, account):
        return self.items.get(account)

    def delete(self, account):
        self.items.pop(account, None)


def test_roundtrip_uses_fixed_account_identity_and_redacts_repr():
    backend = FakeBackend()
    store = CredentialStore(backend)
    account = store.save("123456", "fake secret")
    expected = hashlib.sha256(
        json.dumps(["SIMNOW_FIRST", "9999", "123456"], separators=(",", ":")).encode()
    ).hexdigest()
    assert account == expected == fingerprint_for("123456")
    loaded = store.load(account)
    assert loaded == Credentials("123456", "fake secret", account)
    assert "fake secret" not in repr(loaded)
    assert "123456" not in repr(loaded)
    assert "fake secret" not in repr(store)
    store.delete(account)
    with pytest.raises(CredentialError, match="CREDENTIAL_UNAVAILABLE"):
        store.load(account)


@pytest.mark.parametrize(
    "user,password",
    [
        ("1234567890123", "fake"),
        ("12x", "fake"),
        ("１２３", "fake"),
        ("", "fake"),
        ("123", ""),
        ("123", "x" * 41),
        ("123", "nul\x00value"),
        ("123", "\ud800"),
    ],
)
def test_invalid_credential_is_rejected_without_backend_write(user, password):
    backend = FakeBackend()
    with pytest.raises(CredentialError):
        CredentialStore(backend).save(user, password)
    assert backend.items == {}


def test_tampered_or_wrong_identity_is_rejected():
    backend = FakeBackend()
    store = CredentialStore(backend)
    account = store.save("123", "fake")
    backend.items[account] = json.dumps({"user": "999", "password": "fake"}).encode()
    with pytest.raises(CredentialError, match="CREDENTIAL_IDENTITY_MISMATCH"):
        store.load(account)
    with pytest.raises(CredentialError, match="CREDENTIAL_ACCOUNT_INVALID"):
        store.load("not-a-fingerprint")
