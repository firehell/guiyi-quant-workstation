"""Single-account SimNow credentials in the macOS login Keychain.

This module never invokes ``security`` or accepts credentials in command arguments.
Callers must not serialize or log the returned ``Credentials`` object.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import platform
import re
from contextlib import contextmanager
from dataclasses import dataclass


SERVICE = "com.guiyi.quant.simnow.first.credentials.v1"
ENVIRONMENT = "SIMNOW_FIRST"
BROKER = "9999"
_ACCOUNT = re.compile(r"[0-9a-f]{64}\Z")


class CredentialError(ValueError):
    """Fixed, non-secret error code for credential failures."""


def _validate_user(user: str) -> None:
    if type(user) is not str or re.fullmatch(r"[0-9]{1,12}", user) is None:
        raise CredentialError("INVESTOR_FORMAT_INVALID")


def _validate_password(password: str) -> None:
    if type(password) is not str or "\x00" in password:
        raise CredentialError("PASSWORD_FORMAT_INVALID")
    try:
        size = len(password.encode("utf-8"))
    except UnicodeEncodeError:
        raise CredentialError("PASSWORD_FORMAT_INVALID") from None
    if not 1 <= size <= 40:
        raise CredentialError("PASSWORD_FORMAT_INVALID")


def _validate_account(account_id: str) -> None:
    if type(account_id) is not str or _ACCOUNT.fullmatch(account_id) is None:
        raise CredentialError("CREDENTIAL_ACCOUNT_INVALID")


def fingerprint_for(user: str) -> str:
    """Match the existing controlled SimNow account identity exactly."""
    _validate_user(user)
    source = json.dumps([ENVIRONMENT, BROKER, user], separators=(",", ":"))
    return hashlib.sha256(source.encode("ascii")).hexdigest()


@dataclass(frozen=True, repr=False)
class Credentials:
    user: str
    password: str
    account_id: str

    def __post_init__(self) -> None:
        _validate_user(self.user)
        _validate_password(self.password)
        _validate_account(self.account_id)
        if fingerprint_for(self.user) != self.account_id:
            raise CredentialError("CREDENTIAL_IDENTITY_MISMATCH")

    def __repr__(self) -> str:
        return "Credentials(<redacted>)"


class CredentialStore:
    """Backend contract: add(account, bytes), get(account)->bytes|None, delete(account)."""

    def __init__(self, backend=None):
        self._backend = backend if backend is not None else _NativeKeychain()

    def save(self, user: str, password: str) -> str:
        account = fingerprint_for(user)
        _validate_password(password)
        payload = json.dumps(
            {"user": user, "password": password}, separators=(",", ":")
        ).encode()
        try:
            self._backend.add(account, payload)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("CREDENTIAL_STORE_UNAVAILABLE") from None
        return account

    def load(self, account_id: str) -> Credentials:
        _validate_account(account_id)
        try:
            payload = self._backend.get(account_id)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("CREDENTIAL_UNAVAILABLE") from None
        if payload is None:
            raise CredentialError("CREDENTIAL_UNAVAILABLE")
        try:
            value = json.loads(payload)
            if type(value) is not dict or set(value) != {"user", "password"}:
                raise ValueError
            result = Credentials(value["user"], value["password"], account_id)
        except CredentialError:
            raise
        except (TypeError, ValueError, UnicodeDecodeError):
            raise CredentialError("CREDENTIAL_CORRUPT") from None
        return result

    def delete(self, account_id: str) -> None:
        _validate_account(account_id)
        try:
            self._backend.delete(account_id)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("CREDENTIAL_STORE_UNAVAILABLE") from None


class _NativeKeychain:
    """Security.framework generic password API; fail closed without UI prompts."""

    def __init__(self):
        if platform.system() != "Darwin":
            raise CredentialError("MACOS_KEYCHAIN_REQUIRED")
        try:
            self._cf = ctypes.CDLL(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )
            self._sec = ctypes.CDLL(
                "/System/Library/Frameworks/Security.framework/Security"
            )
            self._cf.CFStringCreateWithCString.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_uint32,
            ]
            self._cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            self._cf.CFDataCreate.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_long,
            ]
            self._cf.CFDataCreate.restype = ctypes.c_void_p
            self._cf.CFDataGetLength.argtypes = [ctypes.c_void_p]
            self._cf.CFDataGetLength.restype = ctypes.c_long
            self._cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
            self._cf.CFDataGetBytePtr.restype = ctypes.c_void_p
            self._cf.CFDictionaryCreateMutable.argtypes = [
                ctypes.c_void_p,
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            self._cf.CFDictionaryCreateMutable.restype = ctypes.c_void_p
            self._cf.CFDictionarySetValue.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            self._cf.CFRelease.argtypes = [ctypes.c_void_p]
            self._sec.SecItemAdd.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self._sec.SecItemAdd.restype = ctypes.c_int32
            self._sec.SecItemCopyMatching.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            self._sec.SecItemCopyMatching.restype = ctypes.c_int32
            self._sec.SecItemDelete.argtypes = [ctypes.c_void_p]
            self._sec.SecItemDelete.restype = ctypes.c_int32
            self._keys = {
                name: ctypes.c_void_p.in_dll(self._sec, name).value
                for name in (
                    "kSecClass",
                    "kSecClassGenericPassword",
                    "kSecAttrService",
                    "kSecAttrAccount",
                    "kSecValueData",
                    "kSecReturnData",
                    "kSecMatchLimit",
                    "kSecMatchLimitOne",
                    "kSecUseAuthenticationUI",
                    "kSecUseAuthenticationUIFail",
                )
            }
            self._true = ctypes.c_void_p.in_dll(self._cf, "kCFBooleanTrue").value
        except Exception:
            raise CredentialError("MACOS_KEYCHAIN_UNAVAILABLE") from None

    def _string(self, value: str) -> int:
        # kCFStringEncodingUTF8 = 0x08000100.
        ref = self._cf.CFStringCreateWithCString(
            None, value.encode("utf-8"), 0x08000100
        )
        if not ref:
            raise CredentialError("MACOS_KEYCHAIN_UNAVAILABLE")
        return ref

    @contextmanager
    def _query(self, account: str, *, data: bytes | None = None, read: bool = False):
        refs = []
        query = self._cf.CFDictionaryCreateMutable(None, 0, None, None)
        if not query:
            raise CredentialError("MACOS_KEYCHAIN_UNAVAILABLE")
        refs.append(query)
        try:
            self._cf.CFDictionarySetValue(
                query, self._keys["kSecClass"], self._keys["kSecClassGenericPassword"]
            )
            for key, text in (
                ("kSecAttrService", SERVICE),
                ("kSecAttrAccount", account),
            ):
                value = self._string(text)
                refs.append(value)
                self._cf.CFDictionarySetValue(query, self._keys[key], value)
            self._cf.CFDictionarySetValue(
                query,
                self._keys["kSecUseAuthenticationUI"],
                self._keys["kSecUseAuthenticationUIFail"],
            )
            if data is not None:
                buffer = ctypes.create_string_buffer(data)
                ref = self._cf.CFDataCreate(None, buffer, len(data))
                if not ref:
                    raise CredentialError("MACOS_KEYCHAIN_UNAVAILABLE")
                refs.append(ref)
                self._cf.CFDictionarySetValue(query, self._keys["kSecValueData"], ref)
            if read:
                self._cf.CFDictionarySetValue(
                    query, self._keys["kSecReturnData"], self._true
                )
                self._cf.CFDictionarySetValue(
                    query, self._keys["kSecMatchLimit"], self._keys["kSecMatchLimitOne"]
                )
            yield query
        finally:
            for ref in reversed(refs):
                self._cf.CFRelease(ref)

    def add(self, account: str, data: bytes) -> None:
        with self._query(account, data=data) as query:
            status = self._sec.SecItemAdd(query, None)
        if status == -25299:
            raise CredentialError("CREDENTIAL_ALREADY_EXISTS")
        if status != 0:
            raise CredentialError("CREDENTIAL_STORE_UNAVAILABLE")

    def get(self, account: str) -> bytes | None:
        output = ctypes.c_void_p()
        with self._query(account, read=True) as query:
            status = self._sec.SecItemCopyMatching(query, ctypes.byref(output))
        if status == -25300:
            return None
        if status != 0 or not output.value:
            raise CredentialError("CREDENTIAL_UNAVAILABLE")
        try:
            length = self._cf.CFDataGetLength(output)
            if length < 1 or length > 1024:
                raise CredentialError("CREDENTIAL_CORRUPT")
            source = self._cf.CFDataGetBytePtr(output)
            if not source:
                raise CredentialError("CREDENTIAL_CORRUPT")
            return ctypes.string_at(source, length)
        finally:
            self._cf.CFRelease(output)

    def delete(self, account: str) -> None:
        with self._query(account) as query:
            status = self._sec.SecItemDelete(query)
        if status not in (0, -25300):
            raise CredentialError("CREDENTIAL_STORE_UNAVAILABLE")
