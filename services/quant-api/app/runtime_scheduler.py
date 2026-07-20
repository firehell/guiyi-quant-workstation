from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any

from app.core.env import load_project_env

SCHEDULER_LOCK_KEY = "guiyi:runtime:scheduler:singleton"
SCHEDULER_HEARTBEAT_KEY = "guiyi:runtime:scheduler:heartbeat"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guiyi JM-only live runtime scheduler")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print safe plan; no DB, Redis, RQData or writes")
    mode.add_argument("--once", action="store_true", help="run one guarded live write cycle")
    mode.add_argument("--run", action="store_true", help="run the supervised APScheduler loop")
    parser.add_argument("--product", default="jm", choices=("jm",))
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--confirm-live-write", action="store_true", help="required for --once/--run")
    parser.add_argument("--approval-packet", type=Path, help="hash-bound approval packet required for --once")
    parser.add_argument("--approval-hash", help="explicitly approved packet hash required for --once")
    return parser.parse_args(argv)


def dry_run_payload(args: argparse.Namespace, environ: Mapping[str, str]) -> dict[str, Any]:
    return {
        "mode": "dry-run",
        "product": args.product,
        "poll_seconds": max(5, args.poll_seconds),
        "enabled": _enabled(environ, "GUIYI_LIVE_RUNTIME_ENABLED"),
        "would_open_database": False,
        "would_connect_redis": False,
        "would_construct_rqdata_client": False,
        "would_write_live_tables": False,
        "would_write_historical_active": False,
        "would_write_signal_event": False,
        "would_send_notification": False,
        "auto_order": False,
    }


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
        print(json.dumps(dry_run_payload(args, source_env), ensure_ascii=False, indent=2))
        return 0
    if environ is None:
        load_project_env()
        source_env = os.environ
    if not args.confirm_live_write:
        print(json.dumps({"status": "blocked", "reason": "--confirm-live-write is required"}, ensure_ascii=False))
        return 2
    if not _enabled(source_env, "GUIYI_LIVE_RUNTIME_ENABLED"):
        print(json.dumps({"status": "disabled", "reason": "GUIYI_LIVE_RUNTIME_ENABLED is false"}, ensure_ascii=False))
        return 2
    if args.once:
        forbidden = [
            name
            for name in (
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
                "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED",
                "GUIYI_WECHAT_AUTOSEND_ENABLED",
            )
            if _enabled(source_env, name)
        ]
        if forbidden:
            print(
                json.dumps(
                    {
                        "status": "blocked",
                        "reason": "forbidden_runtime_flags_enabled",
                        "enabled_flags": forbidden,
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        if args.approval_packet is None or not args.approval_hash:
            print(json.dumps({"status": "blocked", "reason": "approval_packet_and_hash_required"}, ensure_ascii=False))
            return 2

    factories = _factories(session_factory=session_factory, client_factory=client_factory, redis_factory=redis_factory)
    if args.once:
        try:
            from app.core.env import PROJECT_ROOT
            from app.services.live_t3_gate import collect_bound_facts, load_packet, verify_approval_packet

            with factories["session_factory"]() as session:
                current_facts = collect_bound_facts(
                    session,
                    project_root=PROJECT_ROOT,
                    environ=source_env,
                )
                session.rollback()
            verify_approval_packet(
                load_packet(args.approval_packet),
                approval_hash=args.approval_hash,
                current_facts=current_facts,
            )
        except Exception as exc:  # noqa: BLE001 - approval failures must be bounded and fail closed.
            print(
                json.dumps(
                    {"status": "blocked", "reason": "approval_packet_invalid", "error_type": type(exc).__name__},
                    ensure_ascii=False,
                )
            )
            return 2
        result = execute_guarded_cycle(
            product=args.product,
            poll_seconds=args.poll_seconds,
            signal_events_enabled=_enabled(source_env, "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"),
            **factories,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") in {"success", "idle", "lock_busy"} else 1

    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        lambda: print(
            json.dumps(
                execute_guarded_cycle(
                    product=args.product,
                    poll_seconds=args.poll_seconds,
                    signal_events_enabled=_enabled(source_env, "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED"),
                    **factories,
                ),
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        ),
        trigger="interval",
        seconds=max(5, args.poll_seconds),
        id="jm_live_runtime_cycle",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=max(5, args.poll_seconds),
        replace_existing=True,
    )
    if _enabled(source_env, "GUIYI_WECHAT_AUTOSEND_ENABLED"):
        from app.queue import get_notification_queue

        scheduler.add_job(
            lambda: print(
                json.dumps(
                    execute_notification_dispatch(
                        session_factory=factories["session_factory"],
                        queue_factory=get_notification_queue,
                        enabled=True,
                    ),
                    ensure_ascii=False,
                    default=str,
                ),
                flush=True,
            ),
            trigger="interval",
            seconds=max(10, args.poll_seconds),
            id="jm_live_notification_dispatch",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=max(10, args.poll_seconds),
            replace_existing=True,
        )
    scheduler.start()
    return 0


def execute_guarded_cycle(
    *,
    product: str,
    poll_seconds: int,
    session_factory: Callable[[], Any],
    client_factory: Callable[[], Any],
    redis_factory: Callable[[], Any],
    signal_events_enabled: bool = False,
) -> dict[str, Any]:
    connection = redis_factory()
    lock = connection.lock(SCHEDULER_LOCK_KEY, timeout=max(60, poll_seconds * 3), blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return {"status": "lock_busy", "product": product, "singleton": True}
    try:
        _heartbeat(connection, status="running")
        with session_factory() as session:
            from app.services.live_runtime import LiveRuntimeCycleService

            result = LiveRuntimeCycleService(session=session, client=client_factory).run_once(
                enabled=True,
                product=product,
                persist_signal_events=signal_events_enabled,
            )
            session.commit()
        payload = result.to_dict()
        _heartbeat(connection, status=payload["status"])
        return payload
    except Exception as exc:  # noqa: BLE001 - scheduler must report a bounded, redacted failure.
        _heartbeat(connection, status="failed", error_type=type(exc).__name__)
        return {"status": "failed", "product": product, "error_type": type(exc).__name__, "error_message": _safe_message(exc)}
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 - an expired Redis lease is already safe.
            pass


def execute_notification_dispatch(
    *,
    session_factory: Callable[[], Any],
    queue_factory: Callable[[], Any],
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {"status": "disabled", "enabled": False}
    try:
        with session_factory() as session:
            from app.services.notification_dispatch import NotificationDispatchService

            result = NotificationDispatchService(session, queue_factory()).enqueue_due(enabled=True)
            session.commit()
        return result.to_dict()
    except Exception as exc:  # noqa: BLE001 - scheduler reports bounded failure and keeps running.
        return {"status": "failed", "enabled": True, "error_type": type(exc).__name__, "error_message": _safe_message(exc)}


def _factories(
    *,
    session_factory: Callable[[], Any] | None,
    client_factory: Callable[[], Any] | None,
    redis_factory: Callable[[], Any] | None,
) -> dict[str, Callable[[], Any]]:
    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal
    if client_factory is None:
        from app.services.rqdata_ingest.client import RqDataClient

        def create_client() -> Any:
            return RqDataClient(load_env_file=True)

        client_factory = create_client
    if redis_factory is None:
        from app.queue import get_redis_connection

        redis_factory = get_redis_connection
    return {"session_factory": session_factory, "client_factory": client_factory, "redis_factory": redis_factory}


def _heartbeat(connection: Any, *, status: str, error_type: str | None = None) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "error_type": error_type,
        "pid": os.getpid(),
    }
    connection.setex(SCHEDULER_HEARTBEAT_KEY, 180, json.dumps(payload, ensure_ascii=False))


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_message(exc: Exception) -> str | None:
    text = str(exc).strip()
    if not text:
        return None
    lowered = text.lower()
    if any(part in lowered for part in ("password", "secret", "token", "webhook", "license", "cookie", "key")):
        return None
    return text[:200]


if __name__ == "__main__":
    raise SystemExit(main())
