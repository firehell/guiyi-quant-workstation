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
import re
import stat
import json
import secrets
from collections.abc import Callable

from app.market_data.late_worker_policy import provider_ready
from app.market_data.after_market import (
    AfterMarketUpdater,
    _load_status,
    _local_timestamp,
    _public_historical_publications,
    _public_live_evidence,
    public_after_market_status,
)
from app.market_data.after_market_limits import MAX_PUBLICATIONS, MAX_PUBLICATION_BYTES, MAX_STATUS_BYTES
from app.market_data.historical_data_manager import UpdateRequest
from app.market_data.operational_universe import load_operational_products
from app.market_data.session_clock import SHANGHAI

SAFE_FAILURES = {"RQDATA_NOT_READY", "NEXT_TRADING_SESSION_NOT_READY"}
_PUBLIC_RECOVERY_CODES = SAFE_FAILURES | {
    "COMMIT_OUTCOME_UNKNOWN",
    "PROVIDER_QUOTA_EXHAUSTED",
    "CANONICAL_READBACK_UNVERIFIED",
    "LIVE_DOMINANT_MISMATCH",
    "MAINTENANCE_LOCKED",
    "MARKET_ARCHIVE_RECEIPT_UNAVAILABLE",
    "PUBLICATION_EVIDENCE_CAPACITY_EXCEEDED",
    "LATE_RECOVERY_PUBLICATION_EVIDENCE_INVALID",
}


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
            or info.st_size > MAX_STATUS_BYTES
        ):
            raise ValueError("LATE_RECOVERY_STATE_INVALID")
        return os.read(descriptor, MAX_STATUS_BYTES + 1)
    finally:
        os.close(descriptor)


def _write(path: Path, payload: dict) -> None:
    content = _state_content(payload)
    if len(content) > MAX_STATUS_BYTES:
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


def _state_content(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")


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
    for day, row in payload["runs"].items():
        failed_day = date.fromisoformat(day)
        due = datetime.combine(failed_day + timedelta(days=2), time(19, 5), SHANGHAI)
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("products"), list)
            or not row["products"]
            or any(not isinstance(product, str) or re.fullmatch(r"[a-z]{1,4}", product) is None
                   for product in row["products"])
            or len(set(row["products"])) != len(row["products"])
            or row.get("due_at") != due.isoformat()
            or row.get("state")
            not in {"pending", "claimed", "passed", "failed", "expired"}
            or row.get("error_code") not in SAFE_FAILURES
            or row.get("archive_mode") not in (None, "rqdata_tick")
            or "archive_scope_sha256" in row and (
                not isinstance(row["archive_scope_sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", row["archive_scope_sha256"]) is None
            )
        ):
            raise ValueError("LATE_RECOVERY_STATE_INVALID")
    return payload


def schedule_failure(
    path: Path, result, products: tuple[str, ...], started: datetime, *,
    archive_scope: Callable[[], str | None] | None = None,
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
    if archive_scope is not None:
        payload["runs"][day]["archive_mode"] = "rqdata_tick"
        if (proof := archive_scope()) is not None:
            payload["runs"][day]["archive_scope_sha256"] = proof
    _write(path, payload)


def _unresolved_archive_commit(payload: dict) -> bool:
    return any(
        row.get("recovery_error") == "COMMIT_OUTCOME_UNKNOWN"
        or row.get("archive_mode") == "rqdata_tick"
        and row["state"] == "claimed" and row.get("stage") in {"metadata_apply", "apply"}
        for row in payload["runs"].values()
    )


def _sync_archive_metadata(manager, products, day, verify_identity, checkpoint) -> None:
    from app.market_data.current_day_metadata_recovery import (
        apply_current_day_metadata,
        encode_current_day_snapshot,
        plan_current_day_metadata,
    )

    metadata = manager.metadata
    lease = manager.catalog.acquire_maintenance_lock()
    if lease is None:
        raise ValueError("MAINTENANCE_LOCKED")
    try:
        verify_identity()
        snapshot = encode_current_day_snapshot(
            metadata.capture_current_day(products, day), products=products, trading_day=day,
        )
        digest = snapshot["snapshot_sha256"]
        plan = plan_current_day_metadata(
            manager.catalog, snapshot, expected_snapshot_sha256=digest,
            products=products, trading_day=day,
        )
    finally:
        lease.release()
    if any(plan["counts"][kind] for kind in ("calendar_insert", "session_insert", "main_contract_insert")):
        checkpoint("metadata_apply")
        apply_current_day_metadata(
            metadata, snapshot, expected_snapshot_sha256=digest,
            expected_plan_sha256=plan["plan_sha256"], products=products, trading_day=day,
            acquire_maintenance_lock=manager.catalog.acquire_maintenance_lock,
            verify_identity=verify_identity,
        )


def _preflight_archive_publications(payload: dict, count: int, evidence_bytes: int) -> None:
    # Capacity must include the existing late-state history and the cleanup checkpoint.
    if (count > MAX_PUBLICATIONS or evidence_bytes > MAX_PUBLICATION_BYTES
            or len(_state_content(payload)) + evidence_bytes + 64 * 1024 > MAX_STATUS_BYTES):
        raise ValueError("PUBLICATION_EVIDENCE_CAPACITY_EXCEEDED")


def _formal_archive_blocker(path: Path, late_state: dict) -> str | None:
    from app.market_data.after_market_history import _bytes

    if _unresolved_archive_commit(late_state):
        return "commit_outcome_unknown"
    try:
        natural = public_after_market_status(json.loads(_bytes(path)))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return "natural_archive_unverified"
    if (natural.get("last_run") or {}).get("error_code") == "COMMIT_OUTCOME_UNKNOWN":
        return "commit_outcome_unknown"
    if not natural or natural.get("current_run") is not None:
        return "natural_archive_unverified"
    return None


def _recovery_error(exc: Exception) -> str:
    # Only bounded public codes are retained. Raw provider/DB details stay private.
    code = getattr(exc, "code", None)
    if type(exc) is ValueError and len(exc.args) == 1:
        code = exc.args[0]
    if code == "CURRENT_DAY_METADATA_COMMIT_OUTCOME_UNKNOWN":
        return "COMMIT_OUTCOME_UNKNOWN"
    if code == "CURRENT_DAY_METADATA_MAINTENANCE_LOCKED":
        return "MAINTENANCE_LOCKED"
    return code if isinstance(code, str) and code in _PUBLIC_RECOVERY_CODES else "RECOVERY_CHECK_OR_APPLY_FAILED"


def _finish_formal_archive(
    archive: AfterMarketUpdater, day: date, row: dict, *, publications: list[dict[str, object]],
    verify_identity: Callable[[], None], persist: Callable[[], None], restart_evidence: dict | None = None,
) -> None:
    def record_cleanup(evidence: dict) -> None:
        row.update(
            stage="receipt" if evidence["cleanup_verified"] else "live_cleanup",
            live_evidence=evidence, historical_publications=publications,
        )
        persist()

    row["market_archive_receipt_sha256"] = archive.finish_late_archive(
        tuple(row["products"]), day, started_at=row["claimed_at"], publications=publications,
        verify_identity=verify_identity, checkpoint=record_cleanup, restart_evidence=restart_evidence,
        scheduled_scope=row.get("archive_scope_sha256"),
    )
    row.pop("historical_publications", None)


def _resume_formal_cleanup(
    archive: AfterMarketUpdater, day: date, row: dict, *,
    verify_identity: Callable[[], None], persist: Callable[[], None],
) -> None:
    publications = _public_historical_publications(row.get("historical_publications"), row["products"])
    evidence = _public_live_evidence(row.get("live_evidence"), day.isoformat(), row.get("claimed_at"),
                                     row["products"], 1)
    if (row.get("checks") != 1 or publications is None or evidence is None
            or "canonical_readback" not in evidence
            or evidence["cleanup_verified"] != (row["stage"] == "receipt")
            or evidence["canonical_live_exclusion"] != (
                "historical_publications_recorded" if publications else "no_publication"
            )):
        raise ValueError("CANONICAL_READBACK_UNVERIFIED")
    _finish_formal_archive(
        archive, day, row, publications=publications, verify_identity=verify_identity,
        persist=persist, restart_evidence=evidence,
    )


def _has_cleanup_checkpoint(row: dict) -> bool:
    return (row.get("archive_mode") == "rqdata_tick" and row["state"] == "claimed"
            and row.get("stage") in {"live_cleanup", "receipt"})


def _finish_cleanup_claim(archive: AfterMarketUpdater, day: date, row: dict, *, verify_identity, persist) -> str:
    if tuple(row["products"]) != load_operational_products():
        raise ValueError("LATE_RECOVERY_STATE_INVALID")
    verify_identity()
    try:
        _resume_formal_cleanup(archive, day, row, verify_identity=verify_identity, persist=persist)
        row.update(state="passed", recovery_error=None)
    except Exception as exc:
        row.update(state="failed", recovery_error=_recovery_error(exc))
    row["finished_at"] = _local_timestamp(archive.now()).isoformat()
    persist()
    return row["state"]


def prepare_natural_archive(archive: AfterMarketUpdater) -> str | None:
    """While holding the shared guard, finish prior cleanup before advancing pointers."""
    path = archive.status_path.with_name("late-provider-recovery-status.json")
    payload = _read(path)
    if _unresolved_archive_commit(payload):
        return "COMMIT_OUTCOME_UNKNOWN"
    for day, row in sorted(payload["runs"].items()):
        if _has_cleanup_checkpoint(row):
            blocker = _formal_archive_blocker(archive.status_path, payload)
            if blocker == "commit_outcome_unknown":
                return "COMMIT_OUTCOME_UNKNOWN"
            if blocker is not None or archive.archive_binding is None:
                return "CANONICAL_READBACK_UNVERIFIED"
            if _finish_cleanup_claim(archive, date.fromisoformat(day), row,
                                     verify_identity=archive.archive_binding,
                                     persist=lambda: _write(path, payload)) != "passed":
                return "CANONICAL_READBACK_UNVERIFIED"
    return None


def run_scheduled(
    manager,
    *,
    path: Path,
    now: Callable[[], datetime],
    ready: Callable[[date], bool],
    invalidate: Callable[[], None],
    verify_identity: Callable[[], None],
    live_store,
    retain_newow_receipt: bool = False,
    formal_archive: AfterMarketUpdater | None = None,
) -> dict:
    """Caller owns after-market guard. No notification, manual rerun or backfill."""
    current = _local_timestamp(now())
    payload = _read(path)
    outcome = "not_due"
    if formal_archive is not None:
        blocker = _formal_archive_blocker(formal_archive.status_path, payload)
        if blocker is not None:
            return {"schema_version": 1, "command": "data.late-provider-recovery", "status": blocker}

    def persist() -> None:
        _write(path, payload)

    for day, row in sorted(payload["runs"].items()):
        if formal_archive is not None and _has_cleanup_checkpoint(row):
            # Continue the existing claim only from a durable pre-delete proof.
            # This path cannot call the provider or write the historical Catalog.
            outcome = _finish_cleanup_claim(formal_archive, date.fromisoformat(day), row,
                                            verify_identity=verify_identity, persist=persist)
            continue
        due = datetime.fromisoformat(row["due_at"])
        if row["state"] != "pending" or current < due:
            continue
        if tuple(row["products"]) != load_operational_products():
            raise ValueError("LATE_RECOVERY_STATE_INVALID")
        if current.date() != due.date() or current >= due + timedelta(hours=1):
            row.update(state="expired", finished_at=current.isoformat())
            persist()
            outcome = "expired"
            continue
        if (formal_archive is not None) != (row.get("archive_mode") == "rqdata_tick"):
            outcome = "archive_source_changed"
            continue
        verify_identity()
        claimed_at = _local_timestamp(now())
        if claimed_at < due:
            continue
        if claimed_at >= due + timedelta(hours=1):
            row.update(state="expired", finished_at=claimed_at.isoformat())
            persist()
            outcome = "expired"
            continue
        row.update(state="claimed", checks=1, claimed_at=claimed_at.isoformat())
        persist()
        # Any exception after the claim consumes the sole check, including unknown
        # commit/readback outcomes. Keep original natural task status untouched.
        publications = None
        products = tuple(row["products"])
        target_day = date.fromisoformat(day)

        def archive_scope() -> None:
            if formal_archive is not None and not formal_archive.archive_live_scope_matches(
                products, target_day, scheduled_scope=row.get("archive_scope_sha256"),
            ):
                raise ValueError("LIVE_DOMINANT_MISMATCH")

        def stage(value: str) -> None:
            row["stage"] = value
            persist()

        def before_apply() -> None:
            archive_scope()
            invalidate()

        try:
            row["stage"] = "source_readiness"
            archive_scope()
            if not ready(target_day):
                row.update(state="failed", recovery_error="RQDATA_NOT_READY")
            else:
                row["stage"] = "metadata"
                if formal_archive is not None:
                    _sync_archive_metadata(manager, products, target_day, verify_identity, stage)
                else:
                    lease = manager.catalog.acquire_maintenance_lock()
                    if lease is None:
                        raise ValueError("MAINTENANCE_LOCKED")
                    try:
                        verify_identity()
                        manager.metadata.synchronize_current_day(products, target_day)
                    finally:
                        lease.release()
                row["stage"] = "plan"
                request = UpdateRequest(
                    products,
                    None,
                    target_day,
                    mode="daily",
                    require_source_ready=True,
                )
                plan = manager.daily_recovery(request, verify_identity=verify_identity)
                row["plan_sha256"] = plan.plan_sha256
                stage("apply")
                applied = manager.daily_recovery(
                    replace(request, apply=True),
                    expected_plan_sha256=plan.plan_sha256,
                    before_apply=before_apply,
                    verify_identity=verify_identity,
                    **({"before_daily_apply": lambda count, size: _preflight_archive_publications(payload, count, size)}
                       if formal_archive is not None else {}),
                )
                if applied.maintenance.status not in {"passed", "noop"}:
                    raise ValueError(getattr(applied.maintenance, "stop_reason", None) or "RECOVERY_FAILED")
                if retain_newow_receipt or formal_archive is not None:
                    publications = _public_historical_publications(manager.publication_evidence, row["products"])
                    if (publications is None or formal_archive is not None
                            and len(publications) != applied.maintenance.applied):
                        raise ValueError("LATE_RECOVERY_PUBLICATION_EVIDENCE_INVALID")
                if formal_archive is not None:
                    stage("readback")
                    _finish_formal_archive(
                        formal_archive, target_day, row, publications=publications,
                        verify_identity=verify_identity, persist=persist,
                    )
                else:
                    row["stage"] = "readback"
                    readback = manager.daily_recovery(request, verify_identity=verify_identity)
                    if readback.target_windows:
                        raise ValueError("RECOVERY_READBACK_INCOMPLETE")
                    row["stage"] = "live_cleanup"
                    live_store.publish_state({"trading_day": day, "reason": "canonical_updated"})
                    live_store.cleanup_trading_day(target_day)
                row.update(state="passed", recovery_error=None)
        except Exception as exc:
            row.update(state="failed", recovery_error=_recovery_error(exc))
        row["finished_at"] = _local_timestamp(now()).isoformat()
        if row["state"] == "passed" and retain_newow_receipt and publications is not None:
            from app.services.newow_backtest_eod import archive_publication

            research_status = {
                "schema_version": 4,
                "last_successful_trading_day": day,
                "last_run": {"status": "passed", "trading_day": day, "attempts": 1,
                             "products": row["products"], "started_at": row["claimed_at"],
                             "finished_at": row["finished_at"], "error_code": None,
                             "historical_publications": publications},
            }
            try:
                row["newow_publication_sha256"] = archive_publication(
                    path.with_name("after-market-status.json"), research_status, late=True,
                )
            except (OSError, ValueError, RuntimeError):
                row["newow_publication_error"] = "BACKTEST_SOURCE_PUBLICATION_RETAIN_FAILED"
        persist()
        outcome = row["state"]
        if formal_archive is not None and row.get("recovery_error") == "COMMIT_OUTCOME_UNKNOWN":
            outcome = "commit_outcome_unknown"
            break
    return {
        "schema_version": 1,
        "command": "data.late-provider-recovery",
        "status": outcome,
    }


def run_runtime_scheduled(manager) -> dict:
    """Launchd composition bound to the current exact Runtime release."""
    from app.core.env import PROJECT_ROOT
    from app.market_data.captured_recovery_runtime import (
        _verify_loaded_service,
    )
    from app.market_data.live_recovery_guard import after_market_recovery_guard
    from app.market_data.after_market import build_after_market_updater

    from app.market_data.market_foundation_scope import (
        formal_tick_requested,
        require_bar_writer_namespace,
        require_formal_tick_binding,
    )
    from app.redis_connections import get_redis_connection

    formal_tick = formal_tick_requested()
    updater = build_after_market_updater(manager, failure_notification=False, late_recovery=formal_tick)

    def verify() -> None:
        if updater.research_update is not None:
            from app.services.newow_reference_mode import after_market_only

            # The updater factory has already verified the isolated DB, Canonical
            # and Redis bindings. No formal launchd identities are needed here.
            if not after_market_only() or updater.status_path.parent != PROJECT_ROOT / ".run" / "newow-isolated":
                raise ValueError("LATE_RECOVERY_RUNTIME_CHANGED")
            return
        from app.runtime_bindings import authorized_program_arguments, read_bindings, verify_release
        from app.runtime_identity import launchd_arguments, launchd_environments, read_launchd_service

        if read_bindings() != registry or registry is None:
            raise ValueError("LATE_RECOVERY_RUNTIME_CHANGED")
        services = ("api", "live", "after-market", "late-provider-recovery")
        if formal_tick:
            services += ("market-feed",)
        for service in services:
            binding = registry.services[service]
            root = Path(binding.root)
            if not binding.enabled:
                raise ValueError("LATE_RECOVERY_RUNTIME_DISABLED")
            if service == "late-provider-recovery" and (
                root != PROJECT_ROOT or binding.commit != os.environ.get("GUIYI_RUNTIME_COMMIT")
                or binding.tag != os.environ.get("GUIYI_RUNTIME_TAG")
                or str(binding.generation) != os.environ.get("GUIYI_RUNTIME_GENERATION")
            ):
                raise ValueError("LATE_RECOVERY_RUNTIME_CHANGED")
            verify_release(root, binding.tag, binding.commit)
            output = read_launchd_service(binding.label, root=root)
            if (output is None or launchd_arguments(output) != authorized_program_arguments(binding, Path.home())
                    or re.findall(r"^\tprogram = (.+)$", output, re.MULTILINE) != ["/bin/bash"]):
                raise ValueError("LATE_RECOVERY_RUNTIME_CHANGED")
            environments = launchd_environments(output)
            overrides = {"GUIYI_RUNTIME_ENV", "GUIYI_RUNTIME_DIR", "DATABASE_URL", "REDIS_URL",
                         "GUIYI_CANONICAL_DATA_ROOT", "GUIYI_MARKET_SOURCE"}
            if (any(env.keys() & overrides for env in environments)
                    or not any(env.get("GUIYI_RUNTIME_TAG") == binding.tag
                               and env.get("GUIYI_RUNTIME_GENERATION") == str(binding.generation)
                               for env in environments)):
                raise ValueError("LATE_RECOVERY_RUNTIME_CHANGED")
            _verify_loaded_service(
                output, root=root, commit=binding.commit,
                allow_idle=service in {"after-market", "late-provider-recovery"},
                working_directory=Path.home() if service == "api" else root,
            )
        with get_redis_connection() as redis:
            if formal_tick:
                if updater.status_path != Path(registry.services["after-market"].root) / ".run/after-market-status.json":
                    raise ValueError("LATE_RECOVERY_RUNTIME_CHANGED")
                require_formal_tick_binding(redis, manager.catalog.session.get_bind().url, manager.catalog.canonical_root)
            else:
                require_bar_writer_namespace(redis)

    from app.runtime_bindings import read_bindings

    registry = None
    with after_market_recovery_guard(wait=False):
        if updater.research_update is not None:
            status_path = updater.status_path
        else:
            registry = read_bindings()
            verify()
            status_path = Path(registry.services["after-market"].root) / ".run/after-market-status.json"
        result = run_scheduled(
            manager,
            path=status_path.with_name("late-provider-recovery-status.json"),
            now=lambda: datetime.now(SHANGHAI),
            ready=lambda day: provider_ready(updater, day),
            invalidate=updater._invalidate_market_home_projection,
            verify_identity=verify,
            live_store=updater.live_store,
            retain_newow_receipt=updater.research_update is not None,
            formal_archive=updater if formal_tick else None,
        )
    if result["status"] == "passed" and updater.research_update is not None:
        updater.research_update(updater.status_path, None)
    return result


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
                        "market_archive_receipt_sha256",
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
