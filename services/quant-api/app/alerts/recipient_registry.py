"""Private, immutable Weixin notification recipient registry."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


_CHANNEL = "openclaw-weixin"
_MAX_RECIPIENTS = 16


class RecipientRegistryError(RuntimeError):
    """Stable error that never includes private registry content or paths."""


@dataclass(frozen=True, slots=True)
class NotificationRecipient:
    alias: str
    target: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class RecipientRegistryDocument:
    version: int
    channel: str
    account_id: str
    recipients: tuple[NotificationRecipient, ...]

    @property
    def enabled_recipients(self) -> tuple[NotificationRecipient, ...]:
        return tuple(recipient for recipient in self.recipients if recipient.enabled)


def load_recipient_registry(path: Path) -> RecipientRegistryDocument:
    """Load a strict 0600 regular-file registry without following symlinks."""
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except RecipientRegistryError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID") from None
    try:
        return _document_from_payload(payload)
    except (KeyError, TypeError, ValueError):
        raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID") from None


def write_recipient_registry(path: Path, document: RecipientRegistryDocument) -> None:
    """Atomically persist a complete immutable document in an existing 0700 parent."""
    _validate_document(document)
    parent = path.parent
    try:
        parent_metadata = parent.lstat()
        if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_IMODE(parent_metadata.st_mode) != 0o700:
            raise RecipientRegistryError("RECIPIENT_REGISTRY_PARENT_INVALID")
        try:
            target_metadata = path.lstat()
        except FileNotFoundError:
            target_metadata = None
        if target_metadata is not None and (
            not stat.S_ISREG(target_metadata.st_mode)
            or stat.S_IMODE(target_metadata.st_mode) != 0o600
        ):
            raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
    except RecipientRegistryError:
        raise
    except OSError:
        raise RecipientRegistryError("RECIPIENT_REGISTRY_PARENT_INVALID") from None

    payload = {
        "version": document.version,
        "channel": document.channel,
        "account_id": document.account_id,
        "recipients": [
            {
                "alias": recipient.alias,
                "target": recipient.target,
                "enabled": recipient.enabled,
            }
            for recipient in document.recipients
        ],
    }
    temporary_path: str | None = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.tmp.",
            dir=parent,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        directory_descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except RecipientRegistryError:
        raise
    except OSError:
        raise RecipientRegistryError("RECIPIENT_REGISTRY_WRITE_FAILED") from None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def add_recipient(
    document: RecipientRegistryDocument,
    recipient: NotificationRecipient,
) -> RecipientRegistryDocument:
    updated = RecipientRegistryDocument(
        document.version,
        document.channel,
        document.account_id,
        (*document.recipients, recipient),
    )
    _validate_document(updated)
    return updated


def _document_from_payload(payload: Any) -> RecipientRegistryDocument:
    if not isinstance(payload, dict) or set(payload) != {
        "version",
        "channel",
        "account_id",
        "recipients",
    }:
        raise ValueError
    raw_recipients = payload["recipients"]
    if not isinstance(raw_recipients, list):
        raise ValueError
    recipients: list[NotificationRecipient] = []
    for raw in raw_recipients:
        if not isinstance(raw, dict) or set(raw) != {"alias", "target", "enabled"}:
            raise ValueError
        recipients.append(
            NotificationRecipient(raw["alias"], raw["target"], raw["enabled"])
        )
    document = RecipientRegistryDocument(
        payload["version"],
        payload["channel"],
        payload["account_id"],
        tuple(recipients),
    )
    _validate_document(document)
    return document


def _validate_document(document: RecipientRegistryDocument) -> None:
    if type(document.version) is not int or document.version != 1:
        raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
    if document.channel != _CHANNEL:
        raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
    if not _is_trimmed_nonempty(document.account_id):
        raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
    if not document.recipients or len(document.recipients) > _MAX_RECIPIENTS:
        raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
    aliases: set[str] = set()
    targets: set[str] = set()
    for recipient in document.recipients:
        if not isinstance(recipient, NotificationRecipient):
            raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
        if not _is_trimmed_nonempty(recipient.alias):
            raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
        if (
            not _is_trimmed_nonempty(recipient.target)
            or not recipient.target.endswith("@im.wechat")
        ):
            raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
        if type(recipient.enabled) is not bool:
            raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
        if recipient.alias in aliases or recipient.target in targets:
            raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")
        aliases.add(recipient.alias)
        targets.add(recipient.target)
    if not any(recipient.enabled for recipient in document.recipients):
        raise RecipientRegistryError("RECIPIENT_REGISTRY_INVALID")


def _is_trimmed_nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value.strip() == value
