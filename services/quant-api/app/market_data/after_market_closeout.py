"""Explicit interrupted-run closeout. Never a repair, retry or promotion override.

The old writer has no per-run publication ledger. Consequently this seam requires
the existing full audit at the interrupted cutoff, not an inference from progress
or Catalog endpoints. Missing old Live evidence remains explicitly unverified; it is never synthesized.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any

from app.db.readonly import readonly_transaction
from app.market_data.after_market import public_after_market_status, _rank1_matches_snapshot
from app.market_data.historical_data_manager import AuditRequest, HistoricalDataManager
from app.market_data.domain import BarFrequency, DatasetKey, DatasetKind
from app.market_data.session_clock import SHANGHAI


_NAME = "after-market-status.json"
_LIMIT = 1024 * 1024


class _WriteOutcomeUnknown(RuntimeError):
    def __init__(self, readback: str) -> None:
        self.readback = readback
        super().__init__("AFTER_MARKET_CLOSEOUT_OUTCOME_UNKNOWN")


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    """Pin an absolute directory without following any ancestor alias."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError
        yield fd
    finally:
        os.close(fd)


def _read(directory: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o022 or not 0 < info.st_size <= _LIMIT):
            raise ValueError
        value = os.read(fd, _LIMIT + 1)
        if len(value) != info.st_size:
            raise ValueError
        return value
    finally:
        os.close(fd)


@contextmanager
def _guard(root: Path) -> Iterator[Callable[[], None]]:
    # Do not create a different lock when legacy/shared guard evidence is absent.
    with _directory(root / ".run" / "live-recovery-guards") as directory:
        fd = os.open("after-market.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or info.st_mode & 0o022):
                raise ValueError
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def recheck() -> None:
                with _directory(root / ".run" / "live-recovery-guards") as current:
                    visible = os.stat("after-market.lock", dir_fd=current, follow_symlinks=False)
                    if (visible.st_dev, visible.st_ino, visible.st_nlink) != (info.st_dev, info.st_ino, 1):
                        raise ValueError
            yield recheck
        finally:
            os.close(fd)


def _replace(directory: int, original: bytes, payload: dict[str, Any]) -> None:
    """CAS under the shared writer guard; directory FD remains pinned through fsync."""
    temporary = f".{_NAME}.{secrets.token_hex(16)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        if _read(directory, _NAME) != original:
            raise ValueError
        try:
            os.replace(temporary, _NAME, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        except Exception:
            try:
                value = _read(directory, _NAME)
                readback = ("interrupted" if value == (json.dumps(payload, ensure_ascii=False) + "\n").encode()
                            else "original" if value == original else "changed")
            except Exception:
                readback = "unavailable"
            raise _WriteOutcomeUnknown(readback) from None
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def verify_runtime_release_identity(root: Path, commit: str) -> None:
    """Require the exact guarded immutable release without changing service state."""
    from app.market_data.captured_recovery_runtime import (
        _read_command, _verify_markers,
    )

    if root != root.resolve(strict=True):
        raise ValueError
    git = ["/usr/bin/git", "-c", "core.fsmonitor=false"]
    if (_read_command([*git, "rev-parse", "--show-toplevel"], root=root) != str(root)
            or _read_command([*git, "rev-parse", "--abbrev-ref", "HEAD"], root=root) != "HEAD"
            or _read_command([*git, "rev-parse", "HEAD"], root=root) != commit
            or _read_command([*git, "status", "--porcelain=v1", "--untracked-files=all"], root=root)):
        raise ValueError
    tag = _read_command([*git, "describe", "--exact-match", "--tags", "HEAD"], root=root)
    if (re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) is None
            or _read_command([*git, "cat-file", "-t", f"refs/tags/{tag}"], root=root) != "tag"
            or _read_command([*git, "rev-parse", f"refs/tags/{tag}^{{commit}}"], root=root) != commit):
        raise ValueError
    _verify_markers(root)


def verify_closeout_identity(
    root: Path, commit: str, *, home: Path | None = None
) -> None:
    """Require the exact guarded release still loaded by all five services, EOD idle."""
    from app.market_data.captured_recovery_runtime import (
        _read_command, _verify_after_market_plist, _verify_loaded_service,
    )

    verify_runtime_release_identity(root, commit)
    for service in ("api", "web", "live", "alert", "after-market"):
        _verify_after_market_plist(
            root=root,
            commit=commit,
            label=f"com.guiyi.quant-{service}",
            home=home,
        )
        output = _read_command(["/bin/launchctl", "print", f"gui/{os.getuid()}/com.guiyi.quant-{service}"], root=root)
        _verify_loaded_service(output, root=root, commit=commit, allow_idle=service == "after-market",
                               require_idle=service == "after-market",
                               working_directory=Path.home() if service in {"api", "web"} else root)


def _verify_committed_view(manager: HistoricalDataManager, products: tuple[str, ...], day: date) -> int:
    # Inventory from Catalog only, including pointers outside the expected window.
    for symbol in products:
        for partition in manager.catalog.product_partitions(symbol):
            manager.store.read_catalog_partition(partition)
    audit = manager.audit(AuditRequest(products, through=day))
    if (audit.action != "audit" or audit.status not in {"passed", "failed"} or audit.through != day
            or (audit.status == "passed") != (not audit.findings)
            or audit.failures or audit.applied or audit.blocked or audit.failed != len(audit.findings)
            or audit.provider_requests or audit.stop_reason is not None):
        raise ValueError
    for finding in audit.findings:
        if finding.code != "EXPECTED_PARTITION_MISSING" or finding.category != "partition":
            raise ValueError
        key = DatasetKey(DatasetKind(finding.dataset[0]), finding.dataset[1],
                         finding.dataset[2], BarFrequency(finding.dataset[3]))
        if key.symbol not in products or finding.year is None or finding.month is None:
            raise ValueError
        if key.kind is DatasetKind.CONTINUOUS:
            # The old audit code also uses MISSING for extra endpoints. Only a
            # true valid subset is unfinished work, never an extra/mismatched Bar.
            expected = set(manager.coverage.expected_bar_ends(key, finding.year, finding.month,
                manager.coverage.product_start(key.symbol), day))
            for partition in manager.catalog.all_partitions(key):
                if (partition.year, partition.month) == (finding.year, finding.month):
                    if not {bar.bar_end for bar in manager.store.read_catalog_partition(partition)} <= expected:
                        raise ValueError
    return len(audit.findings)


def _snapshot_evidence(
    manager: HistoricalDataManager, live_store: Any, products: tuple[str, ...], day: date,
) -> tuple[str, tuple[tuple[str, str], ...] | None]:
    snapshot = live_store.subscriptions(day)
    if snapshot is None:
        return "not_verified_missing", None
    if (not isinstance(snapshot, Mapping) or len(snapshot) != len(products)
            or any(not isinstance(symbol, str) or not isinstance(contract, str)
                   or not symbol.strip() or not contract.strip()
                   for symbol, contract in snapshot.items())):
        raise ValueError
    # Do not let normalization hide duplicate keys, invalid values or extra products.
    if not _rank1_matches_snapshot(manager, snapshot, products, day):
        raise ValueError
    return "verified_match", tuple(sorted(snapshot.items()))


def close_interrupted_run(
    manager: HistoricalDataManager, *, root: Path, expected_commit: str,
    expected_status_sha256: str, products: tuple[str, ...], live_store: Any,
    now: Callable[[], datetime], apply: bool = False,
    verify_identity: Callable[[Path, str], None] = verify_closeout_identity,
) -> dict[str, Any]:
    """Recheck everything in one lock window; only the diagnostic status may change.

    Dependencies are test seams, never operator-supplied evidence. A successful
    audit establishes the current committed view, not which operations the old
    process performed. No old run is relabeled passed; no historical notice/send.
    """
    result: dict[str, Any] = {
        "schema_version": 1, "command": "data.close-interrupted-after-market",
        "status": "blocked", "readonly": not apply, "status_written": False,
        "provider_requests": 0, "data_writes": 0,
        "error_code": "AFTER_MARKET_CLOSEOUT_BLOCKED",
    }
    try:
        if (type(apply) is not bool or re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None
                or re.fullmatch(r"[0-9a-f]{64}", expected_status_sha256) is None
                or not products or len(set(products)) != len(products)
                or any(re.fullmatch(r"[a-z]{1,4}", symbol) is None for symbol in products)):
            raise ValueError
        verify_identity(root, expected_commit)
        with _guard(root) as recheck_guard, _directory(root / ".run") as directory:
            verify_identity(root, expected_commit)
            original = _read(directory, _NAME)
            if hashlib.sha256(original).hexdigest() != expected_status_sha256:
                raise ValueError
            public = public_after_market_status(json.loads(original))
            current = public.get("current_run")
            if not isinstance(current, dict) or tuple(current["products"]) != products:
                raise ValueError
            started = datetime.fromisoformat(current["started_at"])
            clock = now()
            day = started.astimezone(SHANGHAI).date()
            if (clock.utcoffset() is None or started > clock or current["scheduled_date"] != day.isoformat()
                    or day > clock.astimezone(SHANGHAI).date()):
                raise ValueError
            lease = manager.catalog.acquire_maintenance_lock()
            if lease is None:
                raise ValueError
            try:
                with readonly_transaction(manager.catalog.session):
                    snapshot_evidence = _snapshot_evidence(manager, live_store, products, day)
                    pending = _verify_committed_view(manager, products, day)
                # The writer guard does not freeze ordinary Live initialization.
                # These are two observations, not a claim of whole-window immutability.
                with readonly_transaction(manager.catalog.session):
                    if _snapshot_evidence(manager, live_store, products, day) != snapshot_evidence:
                        raise ValueError
                snapshot_checked_at = now()
                if snapshot_checked_at.utcoffset() is None or snapshot_checked_at < clock:
                    raise ValueError
                # Recheck all identity evidence AFTER both independent DB/Redis reads.
                # A restart or path replacement during the second read must fail closed.
                verify_identity(root, expected_commit)
                recheck_guard()
                with _directory(root / ".run") as visible_directory:
                    pinned, visible = os.fstat(directory), os.fstat(visible_directory)
                    if (pinned.st_dev, pinned.st_ino) != (visible.st_dev, visible.st_ino):
                        raise ValueError
                if _read(directory, _NAME) != original:
                    raise ValueError
                finished = now()
                if finished.utcoffset() is None or finished < snapshot_checked_at:
                    raise ValueError
                interruption = {
                    "trading_day": day.isoformat(), "started_at": current["started_at"],
                    "closed_at": finished.astimezone(SHANGHAI).isoformat(),
                    "snapshot_checked_at": snapshot_checked_at.astimezone(SHANGHAI).isoformat(),
                    "snapshot_classification": snapshot_evidence[0],
                    "reconciliation_verified": snapshot_evidence[0] == "verified_match",
                }
                payload = {
                    "schema_version": 5, "last_interruption": interruption, "current_run": None,
                    "last_run": {"trading_day": day.isoformat(), "status": "interrupted",
                        "attempts": current.get("attempt"), "started_at": current["started_at"],
                        "finished_at": finished.astimezone(SHANGHAI).isoformat(), "products": list(products),
                        "error_code": "AFTER_MARKET_INTERRUPTED", "failure_notification": None},
                    "last_successful_trading_day": public["last_successful_trading_day"],
                    "last_failure": {"trading_day": day.isoformat(), "error_code": "AFTER_MARKET_INTERRUPTED"},
                }
                if not public_after_market_status(payload):
                    raise ValueError
                if apply:
                    _replace(directory, original, payload)
                    result["status_written"] = True
                result.update(status="closed_interrupted" if apply else "ready", error_code=None,
                              runtime_root=str(root), runtime_commit=expected_commit,
                              status_sha256=expected_status_sha256, trading_day=day.isoformat(),
                              pending_findings=pending, last_interruption=interruption)
                if apply:
                    terminal = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
                    result["terminal_status_sha256"] = hashlib.sha256(terminal).hexdigest()
            finally:
                lease.release()
    except _WriteOutcomeUnknown as exc:
        result.update(status="blocked", status_written=None, status_readback=exc.readback,
                      error_code="AFTER_MARKET_CLOSEOUT_OUTCOME_UNKNOWN")
    except Exception:
        # No raw exception, SQL, filesystem detail or provider response is public.
        result.update(status="blocked", error_code="AFTER_MARKET_CLOSEOUT_BLOCKED")
    return result
