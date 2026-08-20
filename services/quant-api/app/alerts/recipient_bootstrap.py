"""Two-step private recipient pairing for a stopped single-operator Runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
from typing import Any, TextIO

from app.alerts.clawbot import ClawbotContext, ClawbotRunner
from app.alerts.clawbot_owner import CLAWBOT_OWNER_ALIAS
from app.alerts.recipients import (
    ClawbotRecipient,
    ClawbotRecipientError,
    RecipientDirectory,
    load_recipient_directory,
)


_ALIAS_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_STAGING_SCHEMA_VERSION = 1
_STAGING_TTL = timedelta(minutes=10)
_FINGERPRINT_KEYS = {"user", "context"}


class RecipientBootstrapError(RuntimeError):
    """Stable public bootstrap failure without private identifiers or paths."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class BootstrapPrepareResult:
    alias: str
    baseline_candidate_count: int


@dataclass(frozen=True, slots=True)
class BootstrapConfirmResult:
    alias: str
    candidate_count: int


@dataclass(frozen=True, slots=True)
class RecipientRetireResult:
    alias: str
    active_recipient_count: int


class RecipientBootstrap:
    def __init__(
        self,
        runner: ClawbotRunner,
        recipients_path: Path,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        nonce_factory: Callable[[], bytes] = lambda: secrets.token_bytes(32),
    ) -> None:
        self._runner = runner
        self._recipients_path = recipients_path
        self._now = now
        self._nonce_factory = nonce_factory

    def prepare(self, alias: str) -> BootstrapPrepareResult:
        directory = self._load_directory()
        self._require_available_alias(alias, directory)
        if len(directory.recipients) >= 4:
            self._fail("CLAWBOT_RECIPIENT_ALIAS_UNAVAILABLE")
        staging = self._staging_path(alias)
        try:
            staging.lstat()
        except FileNotFoundError:
            pass
        except OSError:
            self._fail("CLAWBOT_RECIPIENT_STAGING_INVALID")
        else:
            self._fail("CLAWBOT_RECIPIENT_STAGING_EXISTS")
        account_id, contexts = self._snapshot(directory)
        del account_id
        nonce = self._nonce_factory()
        if not isinstance(nonce, bytes) or len(nonce) != 32:
            self._fail("CLAWBOT_RECIPIENT_STAGING_INVALID")
        prepared_at = self._timestamp()
        payload = {
            "schema_version": _STAGING_SCHEMA_VERSION,
            "alias": alias,
            "prepared_at": prepared_at.isoformat(),
            "expires_at": (prepared_at + _STAGING_TTL).isoformat(),
            "nonce": nonce.hex(),
            "fingerprints": self._fingerprints(nonce, contexts),
        }
        descriptor: int | None = None
        try:
            descriptor = os.open(
                staging,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                descriptor = None
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._fsync_parent()
        except FileExistsError:
            self._fail("CLAWBOT_RECIPIENT_STAGING_EXISTS")
        except (OSError, TypeError, ValueError):
            if descriptor is not None:
                os.close(descriptor)
            self._fail("CLAWBOT_RECIPIENT_STAGING_INVALID")
        return BootstrapPrepareResult(alias, len(contexts))

    def confirm(self, alias: str) -> BootstrapConfirmResult:
        directory = self._load_directory()
        self._require_available_alias(alias, directory)
        staging = self._staging_path(alias)
        stream, identity = self._open_staging(staging)
        with stream:
            payload = self._parse_staging(stream, alias)
            nonce = bytes.fromhex(payload["nonce"])
            baseline = {item["user"]: item["context"] for item in payload["fingerprints"]}
            _account_id, contexts = self._snapshot(directory)
            current = self._fingerprints(nonce, contexts)
            contexts_by_fingerprint = {
                self._fingerprint(nonce, context)["user"]: context for context in contexts
            }
            candidates = [
                contexts_by_fingerprint[fingerprint["user"]]
                for fingerprint in current
                if baseline.get(fingerprint["user"]) != fingerprint["context"]
            ]
            if len(candidates) != 1:
                self._fail("CLAWBOT_RECIPIENT_CANDIDATE_INVALID")
            refreshed = self._load_directory()
            self._require_available_alias(alias, refreshed)
            target = candidates[0].user_id
            if target in {recipient.target_user_id for recipient in refreshed.recipients}:
                self._fail("CLAWBOT_RECIPIENT_TARGET_BOUND")
            try:
                current_metadata = staging.lstat()
            except OSError:
                self._fail("CLAWBOT_RECIPIENT_STAGING_INVALID")
            if (current_metadata.st_dev, current_metadata.st_ino) != identity:
                self._fail("CLAWBOT_RECIPIENT_STAGING_INVALID")
            if self._timestamp() >= datetime.fromisoformat(payload["expires_at"]):
                self._fail("CLAWBOT_RECIPIENT_STAGING_EXPIRED")
            recipients = tuple(
                sorted(
                    (*refreshed.recipients, ClawbotRecipient(alias, refreshed.account_id, target)),
                    key=lambda recipient: (recipient.alias != CLAWBOT_OWNER_ALIAS, recipient.alias),
                )
            )
            updated = RecipientDirectory(
                refreshed.schema_version,
                refreshed.channel,
                refreshed.account_id,
                recipients,
                refreshed.retired_aliases,
            )
            self._replace_directory(updated)
        try:
            staging.unlink()
            self._fsync_parent()
        except OSError:
            self._fail("CLAWBOT_RECIPIENT_STAGING_INVALID")
        return BootstrapConfirmResult(alias, 1)

    def retire(self, alias: str) -> RecipientRetireResult:
        if alias == CLAWBOT_OWNER_ALIAS or _ALIAS_PATTERN.fullmatch(alias) is None:
            self._fail("CLAWBOT_RECIPIENT_RETIRE_INVALID")
        directory = self._load_directory()
        active = {recipient.alias: recipient for recipient in directory.recipients}
        if alias not in active:
            self._fail("CLAWBOT_RECIPIENT_RETIRE_INVALID")
        updated = RecipientDirectory(
            directory.schema_version,
            directory.channel,
            directory.account_id,
            tuple(recipient for recipient in directory.recipients if recipient.alias != alias),
            tuple(sorted((*directory.retired_aliases, alias))),
        )
        self._replace_directory(updated)
        return RecipientRetireResult(alias, len(updated.recipients))

    def _snapshot(
        self, directory: RecipientDirectory
    ) -> tuple[str, tuple[ClawbotContext, ...]]:
        try:
            account_id, contexts = self._runner.snapshot_contexts()
        except Exception as exc:
            if isinstance(exc, RecipientBootstrapError):
                raise
            self._fail("CLAWBOT_RECIPIENT_SNAPSHOT_INVALID")
        if account_id != directory.account_id:
            self._fail("CLAWBOT_RECIPIENT_SNAPSHOT_INVALID")
        return account_id, contexts

    def _load_directory(self) -> RecipientDirectory:
        try:
            return load_recipient_directory(self._recipients_path)
        except ClawbotRecipientError:
            self._fail("CLAWBOT_RECIPIENT_DIRECTORY_INVALID")

    @staticmethod
    def _require_available_alias(alias: str, directory: RecipientDirectory) -> None:
        if (
            not isinstance(alias, str)
            or _ALIAS_PATTERN.fullmatch(alias) is None
            or alias in directory.aliases
            or alias in directory.retired_aliases
        ):
            raise RecipientBootstrapError("CLAWBOT_RECIPIENT_ALIAS_UNAVAILABLE")

    def _staging_path(self, alias: str) -> Path:
        if _ALIAS_PATTERN.fullmatch(alias) is None:
            self._fail("CLAWBOT_RECIPIENT_ALIAS_UNAVAILABLE")
        return self._recipients_path.with_name(
            f".{self._recipients_path.name}.{alias}.staging"
        )

    def _open_staging(self, path: Path) -> tuple[TextIO, tuple[int, int]]:
        try:
            initial = path.lstat()
            self._validate_metadata(initial)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            opened = os.fstat(descriptor)
            self._validate_metadata(opened)
            if (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError
            return os.fdopen(descriptor, encoding="utf-8"), (opened.st_dev, opened.st_ino)
        except (OSError, ValueError):
            self._fail("CLAWBOT_RECIPIENT_STAGING_INVALID")

    def _parse_staging(self, stream: TextIO, alias: str) -> dict[str, Any]:
        try:
            payload = json.load(stream)
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "alias",
                "prepared_at",
                "expires_at",
                "nonce",
                "fingerprints",
            }:
                raise ValueError
            if payload["schema_version"] != _STAGING_SCHEMA_VERSION or payload["alias"] != alias:
                raise ValueError
            prepared = datetime.fromisoformat(payload["prepared_at"])
            expires = datetime.fromisoformat(payload["expires_at"])
            if prepared.tzinfo is None or expires != prepared + _STAGING_TTL:
                raise ValueError
            if self._timestamp() >= expires:
                self._fail("CLAWBOT_RECIPIENT_STAGING_EXPIRED")
            nonce = payload["nonce"]
            if not isinstance(nonce, str) or len(nonce) != 64 or len(bytes.fromhex(nonce)) != 32:
                raise ValueError
            fingerprints = payload["fingerprints"]
            if not isinstance(fingerprints, list) or len(fingerprints) > 64:
                raise ValueError
            for item in fingerprints:
                if (
                    not isinstance(item, dict)
                    or set(item) != _FINGERPRINT_KEYS
                    or any(not isinstance(value, str) or len(value) != 64 for value in item.values())
                ):
                    raise ValueError
            users = [item["user"] for item in fingerprints]
            if users != sorted(users) or len(set(users)) != len(users):
                raise ValueError
            return payload
        except RecipientBootstrapError:
            raise
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self._fail("CLAWBOT_RECIPIENT_STAGING_INVALID")

    @staticmethod
    def _fingerprints(
        nonce: bytes, contexts: tuple[ClawbotContext, ...]
    ) -> list[dict[str, str]]:
        return sorted(
            (RecipientBootstrap._fingerprint(nonce, context) for context in contexts),
            key=lambda value: value["user"],
        )

    @staticmethod
    def _fingerprint(nonce: bytes, context: ClawbotContext) -> dict[str, str]:
        return {
            "user": hmac.new(nonce, context.user_id.encode(), hashlib.sha256).hexdigest(),
            "context": hmac.new(
                nonce,
                context.user_id.encode() + b"\0" + context.context_token.encode(),
                hashlib.sha256,
            ).hexdigest(),
        }

    def _replace_directory(self, directory: RecipientDirectory) -> None:
        temporary: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{self._recipients_path.name}.",
                dir=self._recipients_path.parent,
            )
            temporary = Path(raw_path)
            os.fchmod(descriptor, 0o600)
            payload = {
                "schema_version": directory.schema_version,
                "channel": directory.channel,
                "account_id": directory.account_id,
                "active_recipients": [
                    {"alias": recipient.alias, "target_user_id": recipient.target_user_id}
                    for recipient in directory.recipients
                ],
                "retired_aliases": list(directory.retired_aliases),
            }
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            load_recipient_directory(temporary)
            os.replace(temporary, self._recipients_path)
            temporary = None
            self._fsync_parent()
            load_recipient_directory(self._recipients_path)
        except (OSError, TypeError, ValueError, ClawbotRecipientError):
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            self._fail("CLAWBOT_RECIPIENT_DIRECTORY_INVALID")

    def _fsync_parent(self) -> None:
        descriptor = os.open(
            self._recipients_path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _validate_metadata(metadata: os.stat_result) -> None:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
        ):
            raise ValueError

    def _timestamp(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            self._fail("CLAWBOT_RECIPIENT_STAGING_INVALID")
        return value

    @staticmethod
    def _fail(code: str) -> None:
        raise RecipientBootstrapError(code)
