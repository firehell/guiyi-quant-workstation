"""Strict immutable owner configuration for Clawbot alerts."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any
import unicodedata


CLAWBOT_OWNER_VERSION = 1
CLAWBOT_CHANNEL = "openclaw-weixin"
CLAWBOT_OWNER_ALIAS = "owner"
_SCHEMA_KEYS = {"version", "channel", "owner_alias", "account_id", "target_user_id"}


class ClawbotOwnerError(RuntimeError):
    """Stable public error that never contains private owner data."""


@dataclass(frozen=True, slots=True)
class ClawbotOwner:
    version: int
    channel: str
    owner_alias: str
    account_id: str
    target_user_id: str


def load_clawbot_owner(path: Path) -> ClawbotOwner:
    try:
        _validate_parent(path.parent)
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
        ):
            raise ValueError
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_uid != os.getuid()
            ):
                raise ValueError
            return _parse_owner(json.load(stream))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise ClawbotOwnerError("CLAWBOT_OWNER_INVALID") from None


def write_clawbot_owner_atomic(path: Path, *, account_id: str, target_user_id: str) -> None:
    temporary: Path | None = None
    try:
        _validate_parent(path.parent)
        owner = _parse_owner(
            {
                "version": CLAWBOT_OWNER_VERSION,
                "channel": CLAWBOT_CHANNEL,
                "owner_alias": CLAWBOT_OWNER_ALIAS,
                "account_id": account_id,
                "target_user_id": target_user_id,
            }
        )
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(raw_path)
        os.fchmod(descriptor, 0o600)
        payload = {
            "version": owner.version,
            "channel": owner.channel,
            "owner_alias": owner.owner_alias,
            "account_id": owner.account_id,
            "target_user_id": owner.target_user_id,
        }
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        load_clawbot_owner(path)
    except (OSError, UnicodeError, TypeError, ValueError, ClawbotOwnerError):
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise ClawbotOwnerError("CLAWBOT_OWNER_INVALID") from None


def _validate_parent(parent: Path) -> None:
    metadata = parent.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError


def _parse_owner(payload: Any) -> ClawbotOwner:
    if not isinstance(payload, dict) or set(payload) != _SCHEMA_KEYS:
        raise ValueError
    version = payload["version"]
    channel = payload["channel"]
    owner_alias = payload["owner_alias"]
    account_id = payload["account_id"]
    target_user_id = payload["target_user_id"]
    if type(version) is not int or version != CLAWBOT_OWNER_VERSION:
        raise ValueError
    if channel != CLAWBOT_CHANNEL or owner_alias != CLAWBOT_OWNER_ALIAS:
        raise ValueError
    _validate_identifier(account_id)
    _validate_identifier(target_user_id)
    if not target_user_id.endswith("@im.wechat") or target_user_id == "@im.wechat":
        raise ValueError
    return ClawbotOwner(version, channel, owner_alias, account_id, target_user_id)


def _validate_identifier(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError
