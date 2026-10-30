"""Exact private settings for the continuous single-account SimNow host.

Loading is read-only. The supervisor creates the account state root only after
it has taken its single-writer lock. Schema 3 is disabled preparation only and
cannot enter that supervisor lifecycle or establish any account facts.
"""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
import re
import stat


_FIELDS = frozenset(
    {
        "schema",
        "account_id",
        "state_root",
        "project_root",
        "sdk_python",
        "api_env",
        "mode",
        "enabled",
    }
)
_ACCOUNT = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 4096


class SettingsError(ValueError):
    """Fixed, non-secret configuration failure code."""


@dataclass(frozen=True)
class ContinuousSettings:
    schema: int
    account_id: str
    state_root: Path
    project_root: Path
    sdk_python: Path
    api_env: Path
    mode: str
    enabled: bool
    state_project_root: Path | None = None
    deployment_connection_permit: Path | None = None
    source_config_path: Path | None = None
    source_config_sha256: str | None = None
    account_takeover_pending: bool = False
    account_profile: object | None = None
    ordinary_takeover_permit: Path | None = None


def _path(value, *, code: str) -> Path:
    if type(value) is not str or not value or any(ord(c) < 32 for c in value):
        raise SettingsError(code)
    if not value.startswith("/") or any(
        piece in (".", "..") for piece in value.split("/")
    ):
        raise SettingsError(code)
    return Path(value)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError("SETTINGS_DUPLICATE_KEY")
        result[key] = value
    return result


def _read_private(path: Path) -> tuple[dict, str]:
    if not path.is_absolute() or path.is_symlink():
        raise SettingsError("SETTINGS_PRIVATE_FILE_REQUIRED")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise SettingsError("SETTINGS_PRIVATE_FILE_REQUIRED") from None
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > _MAX_BYTES
        ):
            raise SettingsError("SETTINGS_PRIVATE_FILE_REQUIRED")
        raw = os.read(fd, _MAX_BYTES + 1)
        if not raw or len(raw) > _MAX_BYTES:
            raise SettingsError("SETTINGS_FORMAT_INVALID")
    finally:
        os.close(fd)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise SettingsError("SETTINGS_FORMAT_INVALID") from None
    fields = (
        _FIELDS | {"state_project_root"}
        if type(value) is dict and value.get("schema") in (2, 3)
        else _FIELDS
    )
    if (
        type(value) is dict
        and "deployment_connection_permit" in value
        and value.get("schema") == 2
    ):
        fields = fields | {"deployment_connection_permit"}
    if (
        type(value) is dict
        and value.get("schema") == 2
        and "account_takeover_pending" in value
    ):
        fields = fields | {"account_takeover_pending"}
    if type(value) is dict and value.get("schema") == 2:
        fields = fields | ({"account_profile", "ordinary_takeover_permit"} & set(value))
    if type(value) is not dict or set(value) != fields:
        raise SettingsError("SETTINGS_FIELDS_INVALID")
    if value["schema"] == 3 and info.st_nlink != 1:
        raise SettingsError("SETTINGS_PRIVATE_FILE_REQUIRED")
    return value, hashlib.sha256(raw).hexdigest()


def load_settings(path: Path) -> ContinuousSettings:
    """Validate private identity and either existing state or disabled preparation."""
    value, config_sha = _read_private(Path(path))
    if type(value["schema"]) is not int or value["schema"] not in (1, 2, 3):
        raise SettingsError("SETTINGS_SCHEMA_INVALID")
    if value["schema"] == 3 and (
        value["mode"] != "observe" or value["enabled"] is not False
    ):
        raise SettingsError("PREPARATION_ONLY")
    account = value["account_id"]
    if type(account) is not str or _ACCOUNT.fullmatch(account) is None:
        raise SettingsError("SETTINGS_ACCOUNT_INVALID")
    modes = (
        ("observe", "manage", "trade")
        if value["schema"] == 2
        else ("observe", "manage")
    )
    if value["mode"] not in modes or type(value["mode"]) is not str:
        raise SettingsError("SETTINGS_MODE_INVALID")
    if type(value["enabled"]) is not bool:
        raise SettingsError("SETTINGS_ENABLED_INVALID")
    project = _path(value["project_root"], code="SETTINGS_PROJECT_INVALID")
    state = _path(value["state_root"], code="SETTINGS_STATE_INVALID")
    python = _path(value["sdk_python"], code="SETTINGS_SDK_INVALID")
    api_env = _path(value["api_env"], code="SETTINGS_API_ENV_INVALID")
    if project.is_symlink() or not project.is_dir():
        raise SettingsError("SETTINGS_PROJECT_INVALID")
    if not (project / "scripts/broker/simnow_controlled.py").is_file():
        raise SettingsError("SETTINGS_PROJECT_INVALID")
    anchor = (
        _path(value["state_project_root"], code="SETTINGS_STATE_INVALID")
        if value["schema"] in (2, 3)
        else project
    )
    if not anchor.is_dir() or anchor.is_symlink():
        raise SettingsError("SETTINGS_STATE_INVALID")
    expected = anchor / "output/simnow-controlled"
    if state != expected or state.resolve(strict=False) != expected.resolve(
        strict=False
    ):
        raise SettingsError("SETTINGS_STATE_INVALID")
    if (anchor / "output").is_symlink():
        raise SettingsError("SETTINGS_STATE_INVALID")
    if state.is_symlink():
        raise SettingsError("SETTINGS_STATE_INVALID")
    if state.exists():
        info = state.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise SettingsError("SETTINGS_STATE_INVALID")
    if not python.is_file() or not os.access(python, os.X_OK):
        raise SettingsError("SETTINGS_SDK_INVALID")
    if not api_env.is_dir():
        raise SettingsError("SETTINGS_API_ENV_INVALID")
    if value["schema"] == 2:
        from .account_binding import existing_account

        existing_account(state, account)
    if value["schema"] == 3:
        if Path(path).resolve() != Path(path):
            raise SettingsError("SETTINGS_PRIVATE_FILE_REQUIRED")
        if (
            anchor == project
            or anchor.resolve() != anchor
            or project.resolve() != project
            or state.is_relative_to(project / "output/simnow-controlled")
        ):
            raise SettingsError("PREPARATION_STATE_NOT_INDEPENDENT")
        for directory in (anchor, anchor / "output", state):
            if not directory.exists():
                continue
            info = directory.stat()
            if (
                directory.is_symlink()
                or directory.resolve() != directory
                or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise SettingsError("PREPARATION_PRIVATE_STATE_REQUIRED")
        if state.exists() and any(state.iterdir()):
            raise SettingsError("PREPARATION_STATE_NOT_EMPTY")
    permit = None
    if "deployment_connection_permit" in value:
        if (
            value["schema"] != 2
            or value["mode"] != "trade"
            or value["enabled"] is not True
        ):
            raise SettingsError("DEPLOYMENT_CONNECTION_INVALID")
        permit = _path(
            value["deployment_connection_permit"], code="DEPLOYMENT_CONNECTION_INVALID"
        )
        if (
            permit.resolve(strict=False) != permit
            or permit.name != "deployment-connection-permit.private.json"
        ):
            raise SettingsError("DEPLOYMENT_CONNECTION_INVALID")
        info = permit.parent.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise SettingsError("DEPLOYMENT_CONNECTION_INVALID")
    ordinary = None
    if "ordinary_takeover_permit" in value:
        if permit or value["mode"] != "trade" or not value["enabled"]:
            raise SettingsError("ORDINARY_TAKEOVER_INVALID")
        ordinary = _path(
            value["ordinary_takeover_permit"], code="ORDINARY_TAKEOVER_INVALID"
        )
        if (
            ordinary.resolve(strict=False) != ordinary
            or ordinary.name != "ordinary-takeover-permit.private.json"
        ):
            raise SettingsError("ORDINARY_TAKEOVER_INVALID")
        info = ordinary.parent.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise SettingsError("ORDINARY_TAKEOVER_INVALID")
    profile = None
    if "account_profile" in value:
        from .account_profile import AccountProfile

        profile = AccountProfile.from_dict(value["account_profile"])
        if profile.account_id != account or value["mode"] != "trade":
            raise SettingsError("ACCOUNT_PROFILE_IDENTITY_INVALID")
    pending = value.get("account_takeover_pending", False)
    if ordinary and not pending:
        raise SettingsError("ORDINARY_TAKEOVER_INVALID")
    if type(pending) is not bool or (
        pending
        and (
            not (permit or ordinary) or value["mode"] != "trade" or not value["enabled"]
        )
    ):
        raise SettingsError("ACCOUNT_TAKEOVER_PENDING_SETTINGS_INVALID")
    return ContinuousSettings(
        value["schema"],
        account,
        state,
        project,
        python,
        api_env,
        value["mode"],
        value["enabled"],
        anchor if value["schema"] in (2, 3) else None,
        permit,
        Path(path) if permit or ordinary or profile else None,
        config_sha if permit or ordinary or profile else None,
        pending,
        profile,
        ordinary,
    )
