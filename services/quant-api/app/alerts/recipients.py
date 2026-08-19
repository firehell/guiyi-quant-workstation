"""Frozen recipient directory and secret-safe private file handling."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import secrets
import stat
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
    parent_descriptor: int | None = None
    parent_metadata: os.stat_result | None = None
    temporary_name: str | None = None
    temporary_descriptor: int | None = None
    published = False
    published_identity: tuple[int, int] | None = None
    try:
        parent_descriptor, parent_metadata = _open_private_parent(recipients_path.parent)
        target_name = recipients_path.name
        if _entry_exists(parent_descriptor, target_name):
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
        temporary_descriptor, temporary_name = _create_private_temporary(
            parent_descriptor,
            target_name,
        )
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
        _validate_parent_binding(
            recipients_path.parent,
            parent_descriptor,
            parent_metadata,
        )
        os.link(
            temporary_name,
            target_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        published = True
        target_metadata = os.stat(
            target_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        temporary_metadata = os.stat(
            temporary_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        published_identity = (target_metadata.st_dev, target_metadata.st_ino)
        if published_identity != (temporary_metadata.st_dev, temporary_metadata.st_ino):
            raise ValueError
        os.fsync(parent_descriptor)
        _validate_parent_binding(
            recipients_path.parent,
            parent_descriptor,
            parent_metadata,
        )
        loaded = _load_recipient_directory_at(parent_descriptor, target_name)
        _validate_parent_binding(
            recipients_path.parent,
            parent_descriptor,
            parent_metadata,
        )
        os.unlink(temporary_name, dir_fd=parent_descriptor)
        temporary_name = None
        os.fsync(parent_descriptor)
        _validate_parent_binding(
            recipients_path.parent,
            parent_descriptor,
            parent_metadata,
        )
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
        if parent_descriptor is not None:
            if published:
                _unlink_published_target(
                    parent_descriptor,
                    recipients_path.name,
                    temporary_name,
                    published_identity,
                )
            if temporary_name is not None:
                _unlink_entry(parent_descriptor, temporary_name)
            try:
                os.fsync(parent_descriptor)
            except OSError:
                pass
        raise ClawbotRecipientError("CLAWBOT_RECIPIENTS_INVALID") from None
    finally:
        if parent_descriptor is not None:
            try:
                os.close(parent_descriptor)
            except OSError:
                pass


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


def _open_private_parent(parent: Path) -> tuple[int, os.stat_result]:
    descriptor: int | None = None
    metadata = _validate_private_parent(parent)
    try:
        descriptor = os.open(
            parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        _validate_private_parent_metadata(opened)
        if (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError
        return descriptor, metadata
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        raise


def _validate_parent_binding(
    parent: Path,
    descriptor: int,
    expected: os.stat_result,
) -> None:
    current = _validate_private_parent(parent)
    opened = os.fstat(descriptor)
    _validate_private_parent_metadata(opened)
    expected_identity = (expected.st_dev, expected.st_ino)
    if (
        (current.st_dev, current.st_ino) != expected_identity
        or (opened.st_dev, opened.st_ino) != expected_identity
    ):
        raise ValueError


def _validate_private_parent_metadata(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError


def _validate_private_file(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
    ):
        raise ValueError


def _entry_exists(parent_descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _create_private_temporary(parent_descriptor: int, target_name: str) -> tuple[int, str]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for _ in range(16):
        name = f".{target_name}.{secrets.token_hex(16)}"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        return descriptor, name
    raise OSError


def _load_recipient_directory_at(
    parent_descriptor: int,
    name: str,
) -> RecipientDirectory:
    descriptor: int | None = None
    try:
        metadata = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        _validate_private_file(metadata)
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(descriptor)
        _validate_private_file(opened)
        if (metadata.st_dev, metadata.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = None
            return _parse_directory(json.load(stream))
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unlink_published_target(
    parent_descriptor: int,
    target_name: str,
    temporary_name: str | None,
    published_identity: tuple[int, int] | None,
) -> None:
    try:
        target = os.stat(target_name, dir_fd=parent_descriptor, follow_symlinks=False)
        expected_identity = published_identity
        if expected_identity is None and temporary_name is not None:
            temporary = os.stat(
                temporary_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            expected_identity = (temporary.st_dev, temporary.st_ino)
        if expected_identity == (target.st_dev, target.st_ino):
            os.unlink(target_name, dir_fd=parent_descriptor)
    except OSError:
        pass


def _unlink_entry(parent_descriptor: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_descriptor)
    except OSError:
        pass


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
