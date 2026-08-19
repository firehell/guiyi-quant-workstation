"""Frozen recipient directory and secret-safe private file handling."""

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

from app.alerts.clawbot_owner import ClawbotOwnerError, load_clawbot_owner


CLAWBOT_RECIPIENT_SCHEMA_VERSION = 2
CLAWBOT_RECIPIENT_CHANNEL = "openclaw-weixin"
CLAWBOT_OWNER_ALIAS = "owner"
CLAWBOT_RECIPIENTS_PATH_ENV = "GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH"
_SCHEMA_KEYS = {
    "schema_version",
    "channel",
    "account_id",
    "active_recipients",
    "retired_aliases",
}
_ACTIVE_RECIPIENT_KEYS = {"alias", "target_user_id"}
_ALIAS_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_DIRECT_TARGET_SUFFIX = "@im.wechat"
_MAX_ACTIVE_RECIPIENTS = 5


class ClawbotRecipientError(RuntimeError):
    """Stable public error that never contains recipient private data."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ClawbotRecipient:
    alias: str
    account_id: str = field(repr=False)
    target_user_id: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class RecipientDirectory:
    schema_version: int
    channel: str
    recipients: tuple[ClawbotRecipient, ...] = field(repr=False)
    retired_aliases: tuple[str, ...]

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(recipient.alias for recipient in self.recipients)

    @property
    def owner(self) -> ClawbotRecipient:
        return self.recipients[0]

    def recipients_for(self, rule_code: str) -> tuple[ClawbotRecipient, ...]:
        if rule_code == "htdy_original_15m":
            return self.recipients
        if rule_code == "subing_entry_signal_v1":
            return (self.owner,)
        raise ClawbotRecipientError("CLAWBOT_RECIPIENT_RULE_INVALID")


@dataclass(frozen=True, slots=True)
class RecipientInitializationResult:
    channel: str
    recipient_count: int
    active_aliases: tuple[str, ...]
    recipients_written: bool


def load_recipient_directory(path: Path) -> RecipientDirectory:
    descriptor: int | None = None
    try:
        parent_metadata = _validate_private_parent(path.parent)
        metadata = path.lstat()
        _validate_private_file(metadata)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        _validate_private_file(opened)
        reopened_parent = _validate_private_parent(path.parent)
        if (
            (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino)
            or (parent_metadata.st_dev, parent_metadata.st_ino)
            != (reopened_parent.st_dev, reopened_parent.st_ino)
        ):
            raise ValueError
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = None
            return _parse_directory(json.load(stream))
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        raise ClawbotRecipientError("CLAWBOT_RECIPIENTS_INVALID") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def initialize_recipients_from_owner(
    owner_path: Path,
    recipients_path: Path,
) -> RecipientInitializationResult:
    temporary: Path | None = None
    temporary_descriptor: int | None = None
    try:
        _validate_private_parent(recipients_path.parent)
        try:
            recipients_path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError
        owner = load_clawbot_owner(owner_path)
        directory = _parse_directory(
            {
                "schema_version": CLAWBOT_RECIPIENT_SCHEMA_VERSION,
                "channel": CLAWBOT_RECIPIENT_CHANNEL,
                "account_id": owner.account_id,
                "active_recipients": [
                    {
                        "alias": CLAWBOT_OWNER_ALIAS,
                        "target_user_id": owner.target_user_id,
                    }
                ],
                "retired_aliases": [],
            }
        )
        temporary_descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{recipients_path.name}.",
            dir=recipients_path.parent,
        )
        temporary = Path(raw_path)
        os.fchmod(temporary_descriptor, 0o600)
        payload = {
            "schema_version": directory.schema_version,
            "channel": directory.channel,
            "account_id": directory.owner.account_id,
            "active_recipients": [
                {
                    "alias": directory.owner.alias,
                    "target_user_id": directory.owner.target_user_id,
                }
            ],
            "retired_aliases": [],
        }
        with os.fdopen(temporary_descriptor, "w", encoding="utf-8") as stream:
            temporary_descriptor = None
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, recipients_path, follow_symlinks=False)
        temporary.unlink()
        temporary = None
        _fsync_directory(recipients_path.parent)
        loaded = load_recipient_directory(recipients_path)
        return RecipientInitializationResult(
            channel=loaded.channel,
            recipient_count=len(loaded.recipients),
            active_aliases=loaded.aliases,
            recipients_written=True,
        )
    except (
        OSError,
        UnicodeError,
        KeyError,
        TypeError,
        ValueError,
        ClawbotOwnerError,
        ClawbotRecipientError,
    ):
        if temporary_descriptor is not None:
            try:
                os.close(temporary_descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise ClawbotRecipientError("CLAWBOT_RECIPIENTS_INVALID") from None


def validate_clawbot_recipient_ids(account_id: object, target_user_id: object) -> None:
    try:
        _validate_identifier(account_id)
        _validate_identifier(target_user_id)
        if (
            not isinstance(target_user_id, str)
            or not target_user_id.endswith(_DIRECT_TARGET_SUFFIX)
            or target_user_id == _DIRECT_TARGET_SUFFIX
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise ClawbotRecipientError("CLAWBOT_RECIPIENTS_INVALID") from None


def _validate_private_parent(parent: Path) -> os.stat_result:
    if not parent.is_absolute():
        raise ValueError
    metadata = parent.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError
    return metadata


def _validate_private_file(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError


def _parse_directory(payload: Any) -> RecipientDirectory:
    if not isinstance(payload, dict) or set(payload) != _SCHEMA_KEYS:
        raise ValueError
    schema_version = payload["schema_version"]
    channel = payload["channel"]
    account_id = payload["account_id"]
    active_payload = payload["active_recipients"]
    retired_payload = payload["retired_aliases"]
    if (
        type(schema_version) is not int
        or schema_version != CLAWBOT_RECIPIENT_SCHEMA_VERSION
        or channel != CLAWBOT_RECIPIENT_CHANNEL
    ):
        raise ValueError
    _validate_identifier(account_id)
    if (
        not isinstance(active_payload, list)
        or not 1 <= len(active_payload) <= _MAX_ACTIVE_RECIPIENTS
        or not isinstance(retired_payload, list)
    ):
        raise ValueError

    recipients: list[ClawbotRecipient] = []
    for item in active_payload:
        if not isinstance(item, dict) or set(item) != _ACTIVE_RECIPIENT_KEYS:
            raise ValueError
        alias = item["alias"]
        target_user_id = item["target_user_id"]
        _validate_alias(alias)
        validate_clawbot_recipient_ids(account_id, target_user_id)
        recipients.append(ClawbotRecipient(alias, account_id, target_user_id))

    retired_aliases: list[str] = []
    for alias in retired_payload:
        _validate_alias(alias)
        retired_aliases.append(alias)

    aliases = [recipient.alias for recipient in recipients]
    targets = [recipient.target_user_id for recipient in recipients]
    if (
        aliases.count(CLAWBOT_OWNER_ALIAS) != 1
        or len(set(aliases)) != len(aliases)
        or len(set(targets)) != len(targets)
        or len(set(retired_aliases)) != len(retired_aliases)
        or set(aliases).intersection(retired_aliases)
    ):
        raise ValueError
    ordered = tuple(
        sorted(
            recipients,
            key=lambda recipient: (recipient.alias != CLAWBOT_OWNER_ALIAS, recipient.alias),
        )
    )
    return RecipientDirectory(
        schema_version=schema_version,
        channel=channel,
        recipients=ordered,
        retired_aliases=tuple(sorted(retired_aliases)),
    )


def _validate_alias(value: object) -> None:
    if not isinstance(value, str) or _ALIAS_PATTERN.fullmatch(value) is None:
        raise ValueError


def _validate_identifier(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
