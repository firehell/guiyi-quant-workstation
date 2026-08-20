"""Frozen v2 recipient configuration for Clawbot Alert delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any
import unicodedata

from app.alerts.clawbot_owner import (
    CLAWBOT_CHANNEL,
    CLAWBOT_OWNER_ALIAS,
    ClawbotOwnerError,
    load_clawbot_owner,
)


RECIPIENT_DIRECTORY_SCHEMA_VERSION = 2
_DIRECTORY_KEYS = {
    "schema_version",
    "channel",
    "account_id",
    "active_recipients",
    "retired_aliases",
}
_RECIPIENT_KEYS = {"alias", "target_user_id"}
_ALIAS_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_MAX_ACTIVE_RECIPIENTS = 4


class ClawbotRecipientError(RuntimeError):
    """Stable public error that never includes recipient configuration data."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ClawbotRecipient:
    alias: str
    account_id: str = field(repr=False)
    target_user_id: str = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class RecipientDirectory:
    schema_version: int
    channel: str
    account_id: str
    recipients: tuple[ClawbotRecipient, ...]
    retired_aliases: tuple[str, ...]

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(recipient.alias for recipient in self.recipients)

    def __repr__(self) -> str:
        return (
            "RecipientDirectory("
            f"schema_version={self.schema_version!r}, "
            f"channel={self.channel!r}, "
            f"aliases={self.aliases!r}, "
            f"recipient_count={len(self.recipients)!r}, "
            f"retired_aliases={self.retired_aliases!r}"
            ")"
        )

    def recipients_for(self, rule_code: str) -> tuple[ClawbotRecipient, ...]:
        if rule_code == "htdy_original_15m":
            return self.recipients
        if rule_code == "subing_entry_signal_v1":
            return (self.recipients[0],)
        raise ClawbotRecipientError("CLAWBOT_RECIPIENT_RULE_INVALID")


def load_recipient_directory(path: Path) -> RecipientDirectory:
    """Load one immutable recipient directory from a private local file."""
    try:
        _validate_parent(path.parent)
        initial = path.lstat()
        _validate_file_metadata(initial)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            opened = os.fstat(stream.fileno())
            _validate_file_metadata(opened)
            if (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError
            return _parse_directory(json.load(stream))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise ClawbotRecipientError("CLAWBOT_RECIPIENT_INVALID") from None


def initialize_recipients_from_owner(owner_path: Path, recipients_path: Path) -> RecipientDirectory:
    """Create a v2 owner-only directory without changing the v1 owner file."""
    temporary: Path | None = None
    try:
        owner = load_clawbot_owner(owner_path)
        _validate_parent(recipients_path.parent)
        try:
            recipients_path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError
        directory = _parse_directory(
            {
                "schema_version": RECIPIENT_DIRECTORY_SCHEMA_VERSION,
                "channel": CLAWBOT_CHANNEL,
                "account_id": owner.account_id,
                "active_recipients": [
                    {"alias": CLAWBOT_OWNER_ALIAS, "target_user_id": owner.target_user_id}
                ],
                "retired_aliases": [],
            }
        )
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{recipients_path.name}.", dir=recipients_path.parent)
        temporary = Path(raw_path)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(_serialize_directory(directory), stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        load_recipient_directory(temporary)
        os.replace(temporary, recipients_path)
        temporary = None
        _fsync_parent(recipients_path.parent)
        return load_recipient_directory(recipients_path)
    except (OSError, UnicodeError, TypeError, ValueError, ClawbotOwnerError, ClawbotRecipientError):
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise ClawbotRecipientError("CLAWBOT_RECIPIENT_INVALID") from None


def validate_clawbot_recipient_ids(account_id: object, target_user_id: object) -> None:
    """Apply the shared account and direct-target identifier contract."""
    try:
        _validate_identifier(account_id)
        _validate_identifier(target_user_id)
        if not isinstance(target_user_id, str) or not target_user_id.endswith("@im.wechat") or target_user_id == "@im.wechat":
            raise ValueError
    except (TypeError, ValueError):
        raise ClawbotRecipientError("CLAWBOT_RECIPIENT_INVALID") from None


def _validate_parent(parent: Path) -> None:
    metadata = parent.lstat()
    if (
        not parent.is_absolute()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError


def _validate_file_metadata(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError


def _parse_directory(payload: Any) -> RecipientDirectory:
    if not isinstance(payload, dict) or set(payload) != _DIRECTORY_KEYS:
        raise ValueError
    schema_version = payload["schema_version"]
    channel = payload["channel"]
    account_id = payload["account_id"]
    active = payload["active_recipients"]
    retired = payload["retired_aliases"]
    if (
        type(schema_version) is not int
        or schema_version != RECIPIENT_DIRECTORY_SCHEMA_VERSION
        or channel != CLAWBOT_CHANNEL
        or not isinstance(active, list)
        or not isinstance(retired, list)
        or not 1 <= len(active) <= _MAX_ACTIVE_RECIPIENTS
    ):
        raise ValueError
    _validate_identifier(account_id)
    recipients = tuple(_parse_recipient(item, account_id) for item in active)
    aliases = tuple(recipient.alias for recipient in recipients)
    targets = tuple(recipient.target_user_id for recipient in recipients)
    retired_aliases = tuple(_parse_alias(alias) for alias in retired)
    if (
        len(set(aliases)) != len(aliases)
        or len(set(targets)) != len(targets)
        or len(set(retired_aliases)) != len(retired_aliases)
        or CLAWBOT_OWNER_ALIAS not in aliases
        or set(aliases) & set(retired_aliases)
        or aliases != (CLAWBOT_OWNER_ALIAS, *sorted(alias for alias in aliases if alias != CLAWBOT_OWNER_ALIAS))
        or retired_aliases != tuple(sorted(retired_aliases))
    ):
        raise ValueError
    return RecipientDirectory(
        schema_version,
        channel,
        account_id,
        recipients,
        retired_aliases,
    )


def _parse_recipient(payload: object, account_id: object) -> ClawbotRecipient:
    if not isinstance(payload, dict) or set(payload) != _RECIPIENT_KEYS:
        raise ValueError
    alias = _parse_alias(payload["alias"])
    target_user_id = payload["target_user_id"]
    validate_clawbot_recipient_ids(account_id, target_user_id)
    if not isinstance(account_id, str) or not isinstance(target_user_id, str):
        raise ValueError
    return ClawbotRecipient(alias, account_id, target_user_id)


def _parse_alias(value: object) -> str:
    if not isinstance(value, str) or _ALIAS_PATTERN.fullmatch(value) is None:
        raise ValueError
    return value


def _validate_identifier(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError


def _serialize_directory(directory: RecipientDirectory) -> dict[str, object]:
    return {
        "schema_version": directory.schema_version,
        "channel": directory.channel,
        "account_id": directory.account_id,
        "active_recipients": [
            {"alias": recipient.alias, "target_user_id": recipient.target_user_id}
            for recipient in directory.recipients
        ],
        "retired_aliases": list(directory.retired_aliases),
    }


def _fsync_parent(parent: Path) -> None:
    descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
