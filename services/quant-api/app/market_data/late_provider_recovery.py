"""One source check two calendar days after a safe late-data failure.

This state is separate from natural after-market acceptance. A durable claim is
consumed before provider I/O; crash/unknown outcomes are never automatically retried.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from contextlib import contextmanager
import os
import stat
import json
import secrets
from collections.abc import Callable

from app.market_data.after_market import (
    _load_status,
    _local_timestamp,
)
from app.market_data.historical_data_manager import UpdateRequest
from app.market_data.operational_universe import load_operational_products
from app.market_data.session_clock import SHANGHAI

SAFE_FAILURES = {"RQDATA_NOT_READY", "NEXT_TRADING_SESSION_NOT_READY"}


@contextmanager
def _owned_parent(path: Path, *, create: bool = False):
    path = path.absolute()
    if ".." in path.parts:
        raise ValueError("LATE_RECOVERY_STATE_INVALID")
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            try:
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
            except FileNotFoundError:
                if not create:
                    yield None
                    return
                os.mkdir(part, 0o700, dir_fd=directory)
                os.fsync(directory)
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
            os.close(directory)
            directory = child
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError("LATE_RECOVERY_STATE_INVALID")
        yield directory
    finally:
        os.close(directory)


def _state_bytes(path: Path, directory: int) -> bytes | None:
    try:
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o022
            or info.st_size > 1024 * 1024
        ):
            raise ValueError("LATE_RECOVERY_STATE_INVALID")
        return os.read(descriptor, 1024 * 1024 + 1)
    finally:
        os.close(descriptor)


def _write(path: Path, payload: dict) -> None:
    content = (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode()
    if len(content) > 1024 * 1024:
        raise ValueError("LATE_RECOVERY_STATE_INVALID")
    with _owned_parent(path, create=True) as directory:
        _state_bytes(
            path, directory
        )  # Reject aliases/special files before replacement.
        temporary = "." + path.name + "." + secrets.token_hex(16)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)  # Claim must survive a crash before provider I/O.
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass


def _read(path: Path) -> dict:
    with _owned_parent(path) as directory:
        content = _state_bytes(path, directory) if directory is not None else None
    if content is None:
        return {"schema_version": 1, "runs": {}}
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("LATE_RECOVERY_STATE_INVALID")
    if payload.get("schema_version") != 1 or not isinstance(payload.get("runs"), dict):
        raise ValueError("LATE_RECOVERY_STATE_INVALID")
    products = list(load_operational_products())
    for day, row in payload["runs"].items():
        failed_day = date.fromisoformat(day)
        due = datetime.combine(failed_day + timedelta(days=2), time(19, 5), SHANGHAI)
        if (
            not isinstance(row, dict)
            or row.get("products") != products
            or row.get("due_at") != due.isoformat()
            or row.get("state")
            not in {"pending", "claimed", "passed", "failed", "expired"}
            or row.get("error_code") not in SAFE_FAILURES
        ):
            raise ValueError("LATE_RECOVERY_STATE_INVALID")
    return payload


def schedule_failure(
    path: Path, result, products: tuple[str, ...], started: datetime
) -> None:
    """Caller owns the shared after-market guard; only pre-publication failures qualify."""
    if result.error_code not in SAFE_FAILURES or result.attempts != 2:
        return
    if products != load_operational_products():
        raise ValueError("LATE_RECOVERY_SCOPE_CHANGED")
    payload = _read(path)
    day = result.trading_day.isoformat()
    if day in payload["runs"]:
        return
    payload["runs"][day] = {
        "products": list(products),
        "state": "pending",
        "error_code": result.error_code,
        "original_started_at": started.isoformat(),
        "due_at": datetime.combine(
            result.trading_day + timedelta(days=2), time(19, 5), SHANGHAI
        ).isoformat(),
        # No public provider-notice API has been identified. Absence of evidence
        # is explicitly not treated as an announcement saying there is no delay.
        "announcement": "unavailable",
        "checks": 0,
    }
    _write(path, payload)


def run_scheduled(
    manager,
    *,
    path: Path,
    now: Callable[[], datetime],
    ready: Callable[[date], bool],
    invalidate: Callable[[], None],
    verify_identity: Callable[[], None],
    live_store,
) -> dict:
    """Caller owns after-market guard. No notification, manual rerun or backfill."""
    current = _local_timestamp(now())
    payload = _read(path)
    outcome = "not_due"
    for day, row in sorted(payload["runs"].items()):
        due = datetime.fromisoformat(row["due_at"])
        if row["state"] != "pending" or current < due:
            continue
        if current.date() != due.date() or current >= due + timedelta(hours=1):
            row.update(state="expired", finished_at=current.isoformat())
            _write(path, payload)
            outcome = "expired"
            continue
        verify_identity()
        row.update(state="claimed", checks=1, claimed_at=current.isoformat())
        _write(path, payload)
        # Any exception after the claim consumes the sole check, including unknown
        # commit/readback outcomes. Keep original natural task status untouched.
        try:
            row["stage"] = "source_readiness"
            target_day = date.fromisoformat(day)
            if not ready(target_day):
                row.update(state="failed", recovery_error="RQDATA_NOT_READY")
            else:
                row["stage"] = "metadata"
                lease = manager.catalog.acquire_maintenance_lock()
                if lease is None:
                    raise ValueError("MAINTENANCE_LOCKED")
                try:
                    verify_identity()
                    manager.metadata.synchronize_current_day(
                        tuple(row["products"]), target_day
                    )
                finally:
                    lease.release()
                request = UpdateRequest(
                    tuple(row["products"]),
                    None,
                    target_day,
                    mode="daily",
                    require_source_ready=True,
                )
                row["stage"] = "plan"
                plan = manager.daily_recovery(request, verify_identity=verify_identity)
                row["plan_sha256"] = plan.plan_sha256
                _write(path, payload)
                row["stage"] = "apply"
                _write(path, payload)
                applied = manager.daily_recovery(
                    replace(request, apply=True),
                    expected_plan_sha256=plan.plan_sha256,
                    before_apply=invalidate,
                    verify_identity=verify_identity,
                )
                if applied.maintenance.status not in {"passed", "noop"}:
                    raise ValueError("RECOVERY_FAILED")
                # Fresh resolver planning reads physical pointers and proves no
                # remaining exact daily target. Writer also strict-reads every
                # published partition via MarketDataService before commit.
                row["stage"] = "readback"
                readback = manager.daily_recovery(
                    request, verify_identity=verify_identity
                )
                if readback.target_windows:
                    raise ValueError("RECOVERY_READBACK_INCOMPLETE")
                row["stage"] = "live_cleanup"
                live_store.publish_state(
                    {"trading_day": day, "reason": "canonical_updated"}
                )
                live_store.cleanup_trading_day(target_day)
                row.update(state="passed", recovery_error=None)
        except Exception as exc:
            # Raw provider/DB exceptions never enter public status/logs.
            code = getattr(exc, "code", None)
            row.update(
                state="failed",
                recovery_error=code
                if code
                in {
                    "COMMIT_OUTCOME_UNKNOWN",
                    "RQDATA_NOT_READY",
                    "NEXT_TRADING_SESSION_NOT_READY",
                    "PROVIDER_QUOTA_EXHAUSTED",
                }
                else "RECOVERY_CHECK_OR_APPLY_FAILED",
            )
        row["finished_at"] = _local_timestamp(now()).isoformat()
        _write(path, payload)
        outcome = row["state"]
    return {
        "schema_version": 1,
        "command": "data.late-provider-recovery",
        "status": outcome,
    }


def run_runtime_scheduled(manager) -> dict:
    """Launchd composition bound to the current exact Runtime release."""
    import os
    from app.core.env import PROJECT_ROOT
    from app.market_data.captured_recovery_runtime import (
        _read_command,
        _verify_loaded_service,
    )
    from app.market_data.live_recovery_guard import after_market_recovery_guard
    from app.market_data.after_market import build_after_market_updater

    updater = build_after_market_updater(manager, failure_notification=False)

    def verify() -> None:
        git = ["/usr/bin/git", "-c", "core.fsmonitor=false"]
        commit = _read_command([*git, "rev-parse", "HEAD"], root=PROJECT_ROOT)
        if (
            commit != os.environ.get("GUIYI_RUNTIME_COMMIT")
            or _read_command(
                [*git, "rev-parse", "--abbrev-ref", "HEAD"], root=PROJECT_ROOT
            )
            != "HEAD"
            or _read_command([*git, "status", "--porcelain=v1"], root=PROJECT_ROOT)
        ):
            raise ValueError("LATE_RECOVERY_RUNTIME_CHANGED")
        tag = _read_command(
            [*git, "describe", "--exact-match", "--tags", "HEAD"], root=PROJECT_ROOT
        )
        if (
            _read_command(
                [*git, "cat-file", "-t", "refs/tags/" + tag], root=PROJECT_ROOT
            )
            != "tag"
            or _read_command(
                [*git, "rev-parse", "refs/tags/" + tag + "^{commit}"], root=PROJECT_ROOT
            )
            != commit
        ):
            raise ValueError("LATE_RECOVERY_RUNTIME_CHANGED")
        import stat

        marker = PROJECT_ROOT / ".run" / "market-runtime-enabled"
        info = marker.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or marker.read_bytes() != b"enabled\n"
        ):
            raise ValueError("LATE_RECOVERY_RUNTIME_DISABLED")
        for label in (
            "com.guiyi.quant-api",
            "com.guiyi.quant-live",
            "com.guiyi.quant-after-market",
            "com.guiyi.quant-late-provider-recovery",
        ):
            output = _read_command(
                ["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
                root=PROJECT_ROOT,
            )
            _verify_loaded_service(
                output,
                root=PROJECT_ROOT,
                commit=commit,
                allow_idle=label.endswith(("after-market", "late-provider-recovery")),
                working_directory=Path.home()
                if label.endswith("-api")
                else PROJECT_ROOT,
            )

    def ready(day: date) -> bool:
        if updater.rqdata is None:
            updater.rqdata = updater.rqdata_factory()
        return updater.rqdata.is_future_data_ready(day)

    with after_market_recovery_guard(wait=False):
        return run_scheduled(
            manager,
            path=PROJECT_ROOT / ".run" / "late-provider-recovery-status.json",
            now=lambda: datetime.now(SHANGHAI),
            ready=ready,
            invalidate=updater._invalidate_market_home_projection,
            verify_identity=verify,
            live_store=updater.live_store,
        )


def recovery_health(path: Path, current: datetime) -> dict:
    try:
        payload = _read(path)
        runs = [
            {
                "trading_day": day,
                **{
                    key: row.get(key)
                    for key in (
                        "state",
                        "due_at",
                        "checks",
                        "announcement",
                        "recovery_error",
                        "finished_at",
                        "stage",
                    )
                },
            }
            for day, row in sorted(payload["runs"].items())
        ]
        original = _load_status(path.with_name("after-market-status.json")).get(
            "last_failure"
        )
        if (
            isinstance(original, dict)
            and original.get("error_code") in SAFE_FAILURES
            and original.get("trading_day") not in payload["runs"]
        ):
            return {
                "status": "degraded",
                "readonly": True,
                "error_code": "LATE_RECOVERY_SCHEDULE_MISSING",
                "runs": runs,
            }
        return {
            "status": "degraded"
            if any(
                row["state"] in {"claimed", "failed", "expired"}
                or row["state"] == "pending"
                and datetime.fromisoformat(row["due_at"]) < current
                for row in runs
            )
            else "ok",
            "readonly": True,
            "runs": runs,
        }
    except Exception:
        return {
            "status": "degraded",
            "readonly": True,
            "error_code": "LATE_RECOVERY_STATE_INVALID",
        }
