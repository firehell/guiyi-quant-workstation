from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from sqlalchemy import select

from app.models.data_center import AfterMarketSchedulerCheckpoint
from app.services.after_market_automation import (
    AfterMarketAutomationError,
    AfterMarketAutomationService,
    AutomationPolicy,
    ENABLE_PACKET_SCHEMA_VERSION,
    TASK_ID as AUTOMATION_TASK_ID,
    discover_eligible_trading_days,
    load_or_seed_checkpoint,
    run_delegated_archive_day,
    validate_enable_approval_packet,
)
from app.services.trading_session_clock import TradingSessionClock


PRODUCT = "jm"
LOCK_KEY = "guiyi:eod:jm:scheduler:singleton"
HEARTBEAT_KEY = "guiyi:eod:jm:scheduler:heartbeat"
LOCK_LEASE_SECONDS = 180
HEARTBEAT_TTL_SECONDS = 180


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guiyi independent JM after-market scheduler")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run-once", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--retry-failed-day", type=date.fromisoformat)
    mode.add_argument("--supervised-smoke", action="store_true")
    parser.add_argument("--product", default=PRODUCT, choices=(PRODUCT,))
    parser.add_argument("--approval-packet", type=Path)
    parser.add_argument("--approval-hash")
    parser.add_argument("--confirm-after-market-automation", action="store_true")
    parser.add_argument("--confirm-retry", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    session_factory: Callable[[], Any] | None = None,
    client_factory: Callable[[], Any] | None = None,
    redis_factory: Callable[[], Any] | None = None,
) -> int:
    args = parse_args(argv)
    source_env = environ if environ is not None else os.environ
    if args.dry_run:
        factory = session_factory or _default_session_factory()
        with factory() as session:
            checkpoint = session.scalar(
                select(AfterMarketSchedulerCheckpoint).where(AfterMarketSchedulerCheckpoint.product == args.product)
            )
            payload: dict[str, Any] = {
                "mode": "dry-run",
                "product": args.product,
                "enabled": _enabled(source_env, "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED"),
                "checkpoint_status": checkpoint.status if checkpoint is not None else "missing",
                "last_successful_trading_day": (
                    checkpoint.last_successful_trading_day.isoformat()
                    if checkpoint is not None and checkpoint.last_successful_trading_day
                    else None
                ),
                "would_construct_rqdata_client": False,
                "would_connect_redis": False,
                "would_write_database": False,
                "would_write_parquet": False,
                "would_write_signal_event": False,
                "would_send_notification": False,
            }
            if checkpoint is not None and checkpoint.last_successful_trading_day is not None:
                try:
                    eligibility = discover_eligible_trading_days(
                        last_successful_trading_day=checkpoint.last_successful_trading_day,
                        now=datetime.now(UTC),
                        clock=TradingSessionClock(session),
                    )
                    payload.update(
                        {
                            "backlog_status": "available",
                            "eligible_trading_days": [day.isoformat() for day in eligibility.days],
                            "latest_completed_trading_day": eligibility.latest_completed_trading_day.isoformat(),
                            "latest_eligible_trading_day": (
                                eligibility.latest_eligible_trading_day.isoformat()
                                if eligibility.latest_eligible_trading_day
                                else None
                            ),
                            "archive_lag_trading_days": eligibility.archive_lag_trading_days,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - dry-run remains read-only and reports unavailable facts.
                    payload.update({"backlog_status": "unavailable", "backlog_error_type": _error_type(exc)})
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.supervised_smoke:
        result = execute_guarded_cycle(
            redis_factory=redis_factory or _default_redis_factory(),
            cycle=lambda: {"status": "smoke", "writes_performed": False},
            heartbeat_namespace="smoke",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in {"smoke", "lock_busy"} else 1
    if not _enabled(source_env, "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED"):
        print(json.dumps({"status": "disabled", "reason": "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED is false"}))
        return 2
    if not args.confirm_after_market_automation:
        print(json.dumps({"status": "blocked", "reason": "explicit automation confirmation required"}))
        return 2
    if args.approval_packet is None or not args.approval_hash:
        print(json.dumps({"status": "blocked", "reason": "approval_packet_and_hash_required"}))
        return 2
    result = _execute_approved_mode(
        args=args,
        source_env=source_env,
        session_factory=session_factory,
        client_factory=client_factory,
        redis_factory=redis_factory,
    )
    print(json.dumps(result, ensure_ascii=False, default=str))
    return (
        0
        if result.get("status")
        in {"success", "idle", "waiting_provider", "retry_wait", "retry_armed", "lock_busy", "stopped"}
        else 1
    )


def execute_guarded_cycle(
    *,
    redis_factory: Callable[[], Any],
    cycle: Callable[[], dict[str, Any]],
    heartbeat_namespace: str | None = None,
) -> dict[str, Any]:
    connection = redis_factory()
    suffix = f":{heartbeat_namespace}" if heartbeat_namespace else ""
    lock = connection.lock(f"{LOCK_KEY}{suffix}", timeout=LOCK_LEASE_SECONDS, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return {"status": "lock_busy", "product": PRODUCT, "singleton": True}
    try:
        _heartbeat(connection, status="running", key=f"{HEARTBEAT_KEY}{suffix}")
        result = cycle()
        _heartbeat(connection, status=str(result.get("status") or "unknown"), key=f"{HEARTBEAT_KEY}{suffix}")
        return result
    except Exception as exc:  # noqa: BLE001 - process boundary returns a bounded error.
        error_type = _error_type(exc)
        _heartbeat(connection, status="failed", error_type=error_type, key=f"{HEARTBEAT_KEY}{suffix}")
        return {"status": "failed", "product": PRODUCT, "error_type": error_type}
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 - expired lease is already fail-closed.
            pass


def _execute_approved_mode(
    *,
    args: argparse.Namespace,
    source_env: Mapping[str, str],
    session_factory: Callable[[], Any] | None,
    client_factory: Callable[[], Any] | None,
    redis_factory: Callable[[], Any] | None,
) -> dict[str, Any]:
    del source_env
    try:
        packet = _read_object(args.approval_packet)
        if (
            packet.get("schema_version") != ENABLE_PACKET_SCHEMA_VERSION
            or packet.get("task_id") != "JM-EOD-INCREMENTAL-AUTOMATION-S6-07"
        ):
            raise AfterMarketAutomationError("automation_approval_identity_invalid")
        foundation_meta = packet.get("foundation_receipt") or {}
        foundation_path = Path(str(foundation_meta.get("path") or ""))
        foundation_receipt = _read_object(foundation_path)
        from app.core.env import PROJECT_ROOT

        selected_session_factory = session_factory or _default_session_factory()
        with selected_session_factory() as session:
            current_bound_facts = collect_current_bound_facts(
                session,
                project_root=PROJECT_ROOT,
                expected=packet.get("bound_facts") or {},
            )
            validate_enable_approval_packet(
                packet,
                approval_hash=str(args.approval_hash),
                current_bound_facts=current_bound_facts,
                foundation_receipt=foundation_receipt,
            )
            session.rollback()
    except AfterMarketAutomationError as exc:
        return {"status": "failed", "error_type": str(exc).split(":", 1)[0]}
    except Exception as exc:  # noqa: BLE001 - startup errors are redacted at the process boundary.
        return {"status": "failed", "error_type": type(exc).__name__}

    selected_redis_factory = redis_factory or _default_redis_factory()
    selected_client_factory = client_factory or _default_client_factory()
    output_root = Path(str(packet["bound_facts"]["output_root"]))
    policy = AutomationPolicy()

    def cycle() -> dict[str, Any]:
        with selected_session_factory() as session:
            cycle_foundation_receipt = _read_object(foundation_path)
            cycle_bound_facts = collect_current_bound_facts(
                session,
                project_root=PROJECT_ROOT,
                expected=packet.get("bound_facts") or {},
            )
            validate_enable_approval_packet(
                packet,
                approval_hash=str(args.approval_hash),
                current_bound_facts=cycle_bound_facts,
                foundation_receipt=cycle_foundation_receipt,
            )
            checkpoint = load_or_seed_checkpoint(
                session,
                authorization_hash=str(args.approval_hash),
                foundation_receipt=cycle_foundation_receipt,
                allow_authorization_rotation=True,
                authorization_rotation_failed_day=(
                    args.retry_failed_day if args.confirm_retry else None
                ),
            )
            if args.retry_failed_day is not None:
                AfterMarketAutomationService.reset_failed_day(
                    checkpoint,
                    trading_day=args.retry_failed_day,
                    confirmed=args.confirm_retry,
                )
                session.commit()
                return {
                    "event": "after_market_manual_retry",
                    "task_id": AUTOMATION_TASK_ID,
                    "product": PRODUCT,
                    "status": "retry_armed",
                    "trading_day": args.retry_failed_day.isoformat(),
                    "generated_at": datetime.now(UTC).isoformat(),
                }

            client_holder: dict[str, Any] = {}

            def daily_runner(trading_day: date):
                if "client" not in client_holder:
                    client_holder["client"] = selected_client_factory()
                return run_delegated_archive_day(
                    session=session,
                    client=client_holder["client"],
                    output_root=output_root,
                    project_root=PROJECT_ROOT,
                    trading_day=trading_day,
                    now=datetime.now(UTC),
                    git_identity=cycle_bound_facts["git"],
                    database_identity=cycle_bound_facts["database"],
                    parent_automation_approval_hash=str(args.approval_hash),
                    policy=policy,
                )

            result = AfterMarketAutomationService(
                session=session,
                clock=TradingSessionClock(session),
                daily_runner=daily_runner,
                now=datetime.now(UTC),
                policy=policy,
            ).run_once(checkpoint=checkpoint)
            return {
                "event": "after_market_cycle",
                "task_id": AUTOMATION_TASK_ID,
                "product": PRODUCT,
                "generated_at": datetime.now(UTC).isoformat(),
                **result,
            }

    try:
        if args.run:
            return run_forever(redis_factory=selected_redis_factory, cycle=cycle, policy=policy)
        return execute_guarded_cycle(redis_factory=selected_redis_factory, cycle=cycle)
    except Exception as exc:  # noqa: BLE001 - service boundary never emits secrets or tracebacks.
        return {"status": "failed", "product": PRODUCT, "error_type": _error_type(exc)}


def run_forever(
    *,
    redis_factory: Callable[[], Any],
    cycle: Callable[[], dict[str, Any]],
    policy: AutomationPolicy,
) -> dict[str, Any]:
    from apscheduler.schedulers.blocking import BlockingScheduler

    connection = redis_factory()
    lock = connection.lock(
        LOCK_KEY,
        timeout=policy.lock_lease_seconds,
        blocking_timeout=0,
        thread_local=False,
    )
    if not lock.acquire(blocking=False):
        return {"status": "lock_busy", "product": PRODUCT, "singleton": True}
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    terminal: dict[str, Any] = {"status": "stopped", "product": PRODUCT}

    def heartbeat_job() -> None:
        try:
            renew_scheduler_lease(lock, lease_seconds=policy.lock_lease_seconds)
        except Exception as exc:  # noqa: BLE001 - lost Redis lease terminates the process.
            terminal.update({"status": "failed", "error_type": _error_type(exc)})
            _heartbeat(connection, status="failed", error_type=terminal["error_type"])
            scheduler.shutdown(wait=False)
            return
        _heartbeat(connection, status="running")

    def cycle_job() -> None:
        try:
            result = cycle()
        except Exception as exc:  # noqa: BLE001 - authorization/DB drift terminates this service instance.
            terminal.update({"status": "failed", "error_type": _error_type(exc)})
            _heartbeat(connection, status="failed", error_type=terminal["error_type"])
            scheduler.shutdown(wait=False)
            return
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        _heartbeat(connection, status=str(result.get("status") or "unknown"))

    try:
        _heartbeat(connection, status="running")
        scheduler.add_job(
            heartbeat_job,
            trigger="interval",
            seconds=policy.heartbeat_interval_seconds,
            id="jm_after_market_heartbeat",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.add_job(
            cycle_job,
            trigger="interval",
            seconds=policy.scan_interval_seconds,
            next_run_time=datetime.now(UTC),
            id="jm_after_market_cycle",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=policy.scan_interval_seconds,
            replace_existing=True,
        )
        scheduler.start()
        return terminal
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 - expired lease needs no cleanup.
            pass


def renew_scheduler_lease(lock: Any, *, lease_seconds: int) -> None:
    try:
        extended = lock.extend(lease_seconds, replace_ttl=True)
    except Exception as exc:  # noqa: BLE001 - normalize Redis errors at the process boundary.
        raise AfterMarketAutomationError("scheduler_lock_renewal_failed") from exc
    if extended is False:
        raise AfterMarketAutomationError("scheduler_lock_lost")


def collect_current_bound_facts(session: Any, *, project_root: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    output_root = Path(str(expected.get("output_root") or ""))
    if not output_root.is_dir():
        raise AfterMarketAutomationError("output_root_unavailable")
    runtime_root = project_root.resolve(strict=False)
    expected_runtime = Path(str(expected.get("runtime_root") or "")).resolve(strict=False)
    if runtime_root != expected_runtime:
        raise AfterMarketAutomationError("runtime_root_drift")
    return {
        "git": _git_identity(project_root),
        "dependency_lock_sha256": _sha256_file(project_root / "services" / "quant-api" / "uv.lock"),
        "database": _database_identity(session),
        "runtime_root": str(runtime_root),
        "output_root": str(output_root.resolve(strict=False)),
        "output_device": output_root.stat().st_dev,
        "launchd_label": "com.guiyi.quant-after-market-scheduler",
    }


def _read_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        raise AfterMarketAutomationError("approval_artifact_missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AfterMarketAutomationError("approval_artifact_invalid")
    return payload


def _git_identity(project_root: Path) -> dict[str, str]:
    def value(*arguments: str) -> str:
        return subprocess.run(
            ("git", *arguments),
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    status = value("status", "--porcelain=v1", "--untracked-files=no")
    import hashlib

    return {
        "commit": value("rev-parse", "HEAD"),
        "tracked_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
    }


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_identity(session: Any) -> dict[str, Any]:
    from sqlalchemy import text

    url = session.get_bind().url
    revisions = session.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars().all()
    if len(revisions) != 1:
        raise AfterMarketAutomationError("automation_database_revision_invalid")
    return {
        "driver": url.drivername,
        "host": url.host,
        "port": url.port,
        "database": url.database,
        "alembic_revision": str(revisions[0]),
    }


def _heartbeat(connection: Any, *, status: str, key: str = HEARTBEAT_KEY, error_type: str | None = None) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "error_type": error_type,
        "pid": os.getpid(),
        "lock_status": "held",
    }
    connection.setex(key, HEARTBEAT_TTL_SECONDS, json.dumps(payload, ensure_ascii=False))


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _error_type(exc: Exception) -> str:
    if isinstance(exc, AfterMarketAutomationError):
        return str(exc).split(":", 1)[0]
    return type(exc).__name__


def _default_session_factory() -> Callable[[], Any]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.url import normalize_database_url

    database_url = normalize_database_url(
        os.getenv("DATABASE_URL", "postgresql+psycopg://guiyi@127.0.0.1:5432/guiyi_quant")
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _default_redis_factory() -> Callable[[], Any]:
    from app.queue import get_redis_connection

    return get_redis_connection


def _default_client_factory() -> Callable[[], Any]:
    from app.services.rqdata_ingest.client import RqDataClient

    return lambda: RqDataClient(load_env_file=False)


if __name__ == "__main__":
    raise SystemExit(main())
