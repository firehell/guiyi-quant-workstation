"""Atomic filesystem store for schema-v3 SuBing performance snapshots."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Protocol

from .performance_snapshot import (
    SubingStrategyPerformanceSnapshot,
    SubingStrategyPerformanceSnapshotError,
    encode_subing_strategy_performance_snapshot,
    parse_subing_strategy_performance_snapshot,
)


_MANIFEST_SCHEMA_VERSION = 1
_MANIFEST_FIELDS = frozenset({
    "generated_at",
    "identity_sha256",
    "manifest_sha256",
    "payload_sha256",
    "schema_version",
    "snapshot_path",
    "snapshot_sha256",
    "symbol",
    "through",
})
_MANIFEST_HASH_FIELDS = _MANIFEST_FIELDS - {"manifest_sha256"}


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceSnapshotReceipt:
    symbol: str
    through: date
    snapshot_path: str
    snapshot_sha256: str
    identity_sha256: str
    payload_sha256: str
    manifest_sha256: str
    generated_at: datetime


class SubingStrategyPerformanceSnapshotStore(Protocol):
    def read_current(
        self,
        *,
        symbol: str,
        expected_through: date,
        allow_older: bool = False,
    ) -> SubingStrategyPerformanceSnapshot: ...

    def publish_current(
        self, snapshot: SubingStrategyPerformanceSnapshot
    ) -> SubingStrategyPerformanceSnapshotReceipt: ...


class SubingStrategyPerformanceFileSnapshotStore:
    def __init__(
        self,
        root: Path,
        *,
        root_validator: Callable[[], Path],
        trusted_base_validator: Callable[[], Path] | None = None,
    ) -> None:
        self._root = root
        self._root_validator = root_validator
        self._trusted_base_validator = trusted_base_validator or root_validator

    def read_current(
        self,
        *,
        symbol: str,
        expected_through: date,
        allow_older: bool = False,
    ) -> SubingStrategyPerformanceSnapshot:
        try:
            if (
                not _is_valid_symbol(symbol)
                or type(expected_through) is not date
                or type(allow_older) is not bool
            ):
                raise SubingStrategyPerformanceSnapshotError()
            manifest_path = self._contained_path(f"current/{symbol}.json")
            self._preflight(manifest_path)
            if not manifest_path.exists():
                raise SubingStrategyPerformanceSnapshotError()
            self._assert_path_secure(manifest_path)
            manifest = _parse_manifest(self._read_bytes(manifest_path))
            self._preflight(manifest_path)
            manifest_through = manifest["through"]
            if manifest["symbol"] != symbol:
                raise SubingStrategyPerformanceSnapshotError()
            if allow_older:
                if manifest_through > expected_through:
                    raise SubingStrategyPerformanceSnapshotError()
            elif manifest_through != expected_through:
                raise SubingStrategyPerformanceSnapshotError()
            snapshot_path_text = manifest["snapshot_path"]
            expected_relative = _snapshot_relative_path(
                symbol=symbol,
                through=manifest_through,
                snapshot_sha256=str(manifest["snapshot_sha256"]),
            )
            if snapshot_path_text != expected_relative:
                raise SubingStrategyPerformanceSnapshotError()
            snapshot_path = self._contained_path(snapshot_path_text)
            self._preflight(snapshot_path)
            if not snapshot_path.exists():
                raise SubingStrategyPerformanceSnapshotError()
            self._assert_path_secure(snapshot_path)
            snapshot = parse_subing_strategy_performance_snapshot(
                self._read_bytes(snapshot_path)
            )
            self._preflight(snapshot_path)
            if (
                snapshot.symbol != symbol
                or snapshot.coverage_through != manifest_through
                or snapshot.snapshot_sha256 != manifest["snapshot_sha256"]
                or snapshot.identity_sha256 != manifest["identity_sha256"]
                or snapshot.payload_sha256 != manifest["payload_sha256"]
                or snapshot.generated_at.astimezone(UTC).isoformat()
                != manifest["generated_at"]
            ):
                raise SubingStrategyPerformanceSnapshotError()
            return snapshot
        except SubingStrategyPerformanceSnapshotError:
            raise
        except (OSError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            raise SubingStrategyPerformanceSnapshotError() from None

    def publish_current(
        self, snapshot: SubingStrategyPerformanceSnapshot
    ) -> SubingStrategyPerformanceSnapshotReceipt:
        try:
            content = encode_subing_strategy_performance_snapshot(snapshot)
            relative = _snapshot_relative_path(
                symbol=snapshot.symbol,
                through=snapshot.coverage_through,
                snapshot_sha256=snapshot.snapshot_sha256,
            )
            snapshot_path = self._contained_path(relative)
            self._publish_immutable(snapshot, snapshot_path, content)
            body = _manifest_body(snapshot, relative)
            manifest_sha256 = sha256(_canonical_bytes(body)).hexdigest()
            envelope = dict(body)
            envelope["manifest_sha256"] = manifest_sha256
            manifest_path = self._contained_path(f"current/{snapshot.symbol}.json")
            self._atomic_replace(manifest_path, _canonical_bytes(envelope))
            return SubingStrategyPerformanceSnapshotReceipt(
                symbol=snapshot.symbol,
                through=snapshot.coverage_through,
                snapshot_path=relative,
                snapshot_sha256=snapshot.snapshot_sha256,
                identity_sha256=snapshot.identity_sha256,
                payload_sha256=snapshot.payload_sha256,
                manifest_sha256=manifest_sha256,
                generated_at=snapshot.generated_at,
            )
        except SubingStrategyPerformanceSnapshotError:
            raise
        except (OSError, TypeError, ValueError):
            raise SubingStrategyPerformanceSnapshotError() from None

    def _publish_immutable(
        self,
        snapshot: SubingStrategyPerformanceSnapshot,
        path: Path,
        content: bytes,
    ) -> None:
        self._ensure_parent(path.parent)
        self._preflight(path)
        if path.is_symlink():
            raise SubingStrategyPerformanceSnapshotError()
        if path.exists():
            self._assert_path_secure(path)
            if path.read_bytes() != content:
                raise SubingStrategyPerformanceSnapshotError()
        else:
            self._atomic_replace(path, content)
        self._preflight(path)
        restored = parse_subing_strategy_performance_snapshot(self._read_bytes(path))
        if (
            restored.snapshot_sha256 != snapshot.snapshot_sha256
            or restored.identity_sha256 != snapshot.identity_sha256
            or restored.payload_sha256 != snapshot.payload_sha256
            or restored.symbol != snapshot.symbol
            or restored.coverage_through != snapshot.coverage_through
            or restored.generated_at != snapshot.generated_at
        ):
            raise SubingStrategyPerformanceSnapshotError()

    def _atomic_replace(self, target: Path, content: bytes) -> None:
        self._ensure_parent(target.parent)
        self._preflight(target)
        descriptor = -1
        temporary: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
            )
            temporary = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            self._preflight(target)
            os.replace(temporary, target)
            temporary = None
            self._fsync_directory(target.parent)
            self._assert_path_secure(target)
        except SubingStrategyPerformanceSnapshotError:
            raise
        except (OSError, TypeError, ValueError):
            raise SubingStrategyPerformanceSnapshotError() from None
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _fsync_directory(self, directory: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        fd = os.open(directory, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _contained_path(self, relative: str) -> Path:
        if not _is_safe_relative_path(relative):
            raise SubingStrategyPerformanceSnapshotError()
        path = self._root.joinpath(*Path(relative).parts)
        path.relative_to(self._root)
        return path

    def _read_bytes(self, path: Path) -> bytes:
        self._preflight(path)
        self._assert_path_secure(path)
        content = path.read_bytes()
        self._preflight(path)
        return content

    def _preflight(self, path: Path) -> None:
        try:
            if self._root_validator() != self._root:
                raise SubingStrategyPerformanceSnapshotError()
            trusted_base = self._trusted_base_validator()
            self._root.relative_to(trusted_base)
            path.relative_to(self._root)
            if trusted_base.exists() and trusted_base.is_symlink():
                raise SubingStrategyPerformanceSnapshotError()
            if self._root.exists() and self._root.is_symlink():
                raise SubingStrategyPerformanceSnapshotError()
            current = trusted_base
            for part in path.relative_to(trusted_base).parts:
                if current.exists() and current.is_symlink():
                    raise SubingStrategyPerformanceSnapshotError()
                current = current / part
            if current.exists() and current.is_symlink():
                raise SubingStrategyPerformanceSnapshotError()
        except SubingStrategyPerformanceSnapshotError:
            raise
        except Exception:
            raise SubingStrategyPerformanceSnapshotError() from None

    def _ensure_parent(self, parent: Path) -> None:
        try:
            trusted_base = self._trusted_base_validator()
            self._root.relative_to(trusted_base)
            parent.relative_to(self._root)
            if not trusted_base.is_dir() or trusted_base.is_symlink():
                raise SubingStrategyPerformanceSnapshotError()
            current = trusted_base
            for part in parent.relative_to(trusted_base).parts:
                if current.exists() and current.is_symlink():
                    raise SubingStrategyPerformanceSnapshotError()
                current = current / part
                current.mkdir(mode=0o700, parents=False, exist_ok=True)
                os.chmod(current, 0o700)
                self._assert_secure_directory(current)
        except SubingStrategyPerformanceSnapshotError:
            raise
        except Exception:
            raise SubingStrategyPerformanceSnapshotError() from None

    def _assert_path_secure(self, path: Path) -> None:
        current = self._root
        for index, part in enumerate(path.relative_to(self._root).parts):
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise SubingStrategyPerformanceSnapshotError()
            last = index == len(path.relative_to(self._root).parts) - 1
            if last:
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                ):
                    raise SubingStrategyPerformanceSnapshotError()
                continue
            self._assert_secure_directory(current)

    def _assert_secure_directory(self, path: Path) -> None:
        info = path.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise SubingStrategyPerformanceSnapshotError()


def _snapshot_relative_path(
    *,
    symbol: str,
    through: date,
    snapshot_sha256: str,
) -> str:
    return f"snapshots/{symbol}/{through.isoformat()}/{snapshot_sha256}.json"


def _manifest_body(
    snapshot: SubingStrategyPerformanceSnapshot,
    snapshot_path: str,
) -> dict[str, object]:
    return {
        "generated_at": snapshot.generated_at.astimezone(UTC).isoformat(),
        "identity_sha256": snapshot.identity_sha256,
        "payload_sha256": snapshot.payload_sha256,
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "snapshot_path": snapshot_path,
        "snapshot_sha256": snapshot.snapshot_sha256,
        "symbol": snapshot.symbol,
        "through": snapshot.coverage_through.isoformat(),
    }


def _parse_manifest(content: bytes) -> dict[str, object]:
    envelope = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(envelope, dict):
        raise SubingStrategyPerformanceSnapshotError()
    if set(envelope) != _MANIFEST_FIELDS:
        raise SubingStrategyPerformanceSnapshotError()
    if envelope.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        raise SubingStrategyPerformanceSnapshotError()
    _reject_path_tokens(envelope)
    symbol = envelope.get("symbol")
    through_text = envelope.get("through")
    snapshot_path = envelope.get("snapshot_path")
    generated_at_text = envelope.get("generated_at")
    if (
        not _is_valid_symbol(symbol if isinstance(symbol, str) else "")
        or not isinstance(through_text, str)
        or not isinstance(snapshot_path, str)
        or not isinstance(generated_at_text, str)
        or not _is_safe_relative_path(snapshot_path)
        or not all(
            _is_sha256(envelope[field])
            for field in (
                "identity_sha256",
                "payload_sha256",
                "snapshot_sha256",
                "manifest_sha256",
            )
        )
    ):
        raise SubingStrategyPerformanceSnapshotError()
    through = date.fromisoformat(through_text)
    generated_at = datetime.fromisoformat(generated_at_text)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise SubingStrategyPerformanceSnapshotError()
    body = {field: envelope[field] for field in sorted(_MANIFEST_HASH_FIELDS)}
    if sha256(_canonical_bytes(body)).hexdigest() != envelope["manifest_sha256"]:
        raise SubingStrategyPerformanceSnapshotError()
    return {
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "identity_sha256": envelope["identity_sha256"],
        "manifest_sha256": envelope["manifest_sha256"],
        "payload_sha256": envelope["payload_sha256"],
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "snapshot_path": snapshot_path,
        "snapshot_sha256": envelope["snapshot_sha256"],
        "symbol": symbol,
        "through": through,
    }


def _is_safe_relative_path(value: str) -> bool:
    if (
        not value
        or value.startswith("/")
        or ".." in value
        or "\\" in value
    ):
        return False
    path = Path(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _is_valid_symbol(value: str) -> bool:
    return bool(
        value
        and value.isascii()
        and value.isalpha()
        and value == value.lower()
    )


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        raise SubingStrategyPerformanceSnapshotError()
    return dict(pairs)


def _reject_path_tokens(value: object) -> None:
    if isinstance(value, str):
        if value.startswith("/") or ".." in value:
            raise SubingStrategyPerformanceSnapshotError()
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_path_tokens(item)


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
