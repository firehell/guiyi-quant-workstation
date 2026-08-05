from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any, Protocol

from app.core.env import load_project_env

SCHEDULER_LOCK_KEY = "guiyi:runtime:scheduler:singleton"
SCHEDULER_HEARTBEAT_KEY = "guiyi:runtime:scheduler:heartbeat"


class SignalGate(Protocol):
    def __call__(
        self,
        session: Any,
        *,
        phase: str,
        result: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guiyi JM-only live runtime scheduler")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print safe plan; no DB, Redis, RQData or writes")
    mode.add_argument("--once", action="store_true", help="run one guarded live write cycle")
    mode.add_argument("--run", action="store_true", help="run the supervised APScheduler loop")
    parser.add_argument("--product", default="jm", choices=("jm",))
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--confirm-live-write", action="store_true", help="required for --once/--run")
    parser.add_argument("--approval-packet", type=Path, help="hash-bound approval packet required for guarded writes")
    parser.add_argument("--approval-hash", help="explicitly approved packet hash required for guarded writes")
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
    signal_events_enabled = _enabled(source_env, "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED")
    if args.run and signal_events_enabled:
        if _enabled(source_env, "GUIYI_WECHAT_AUTOSEND_ENABLED"):
            print(json.dumps({"status": "blocked", "reason": "wechat_autosend_must_be_false"}, ensure_ascii=False))
            return 2
        if args.approval_packet is None or not args.approval_hash:
            print(
                json.dumps(
                    {"status": "blocked", "reason": "signal_event_approval_packet_and_hash_required"},
                    ensure_ascii=False,
                )
            )
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
    signal_gate: SignalGate | None = None
    if args.run and signal_events_enabled:
        try:
            signal_gate = _build_signal_gate(
                approval_packet=args.approval_packet,
                approval_hash=str(args.approval_hash),
                environ=source_env,
            )
            with factories["session_factory"]() as session:
                signal_gate(session, phase="verify")
                session.rollback()
        except Exception as exc:  # noqa: BLE001 - service authorization must fail closed.
            print(
                json.dumps(
                    {"status": "blocked", "reason": "signal_event_approval_invalid", "error_type": type(exc).__name__},
                    ensure_ascii=False,
                )
            )
            return 2
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
            signal_events_enabled=signal_events_enabled,
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
                    signal_events_enabled=signal_events_enabled,
                    signal_gate=signal_gate,
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
    signal_gate: SignalGate | None = None,
) -> dict[str, Any]:
    connection = redis_factory()
    lock = connection.lock(SCHEDULER_LOCK_KEY, timeout=max(60, poll_seconds * 3), blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return {"status": "lock_busy", "product": product, "singleton": True}
    gate_metadata: Mapping[str, Any] = {}
    signal_write_authorized = False
    gate_after_commit_required = False
    try:
        _heartbeat(
            connection,
            status="running",
            signal_events_enabled=signal_events_enabled,
            gate_metadata=gate_metadata,
        )
        with session_factory() as session:
            from app.services.live_runtime import LiveRuntimeCycleService

            signal_event_handler = None
            if signal_events_enabled:
                if signal_gate is None:
                    raise RuntimeError("signal_event_gate_required")
                pre_gate_metadata = signal_gate(session, phase="pre_write")
                signal_event_handler = pre_gate_metadata.get(
                    "signal_event_handler"
                )
                after_commit_requested = bool(
                    pre_gate_metadata.get("after_commit_required")
                )
                if after_commit_requested:
                    # Long-running S6-10 Approval D after-commit path is superseded.
                    raise RuntimeError("superseded_runtime_gate_disabled")
                gate_after_commit_required = False
                signal_write_authorized = signal_event_handler is not None
                if (
                    not signal_write_authorized
                    and pre_gate_metadata.get("gate_status")
                    not in {"waiting", "closed"}
                ):
                    raise RuntimeError(
                        "htdy_signal_event_handler_required"
                    )
                gate_metadata = {
                    key: value
                    for key, value in pre_gate_metadata.items()
                    if key != "signal_event_handler"
                }
            result = LiveRuntimeCycleService(session=session, client=client_factory).run_once(
                enabled=True,
                product=product,
                persist_signal_events=False,
                signal_event_handler=signal_event_handler,
            )
            payload = result.to_dict()
            if signal_write_authorized:
                gate_metadata = signal_gate(session, phase="post_write", result=payload)
            session.commit()
            if signal_write_authorized or gate_after_commit_required:
                gate_metadata = signal_gate(
                    session,
                    phase="after_commit",
                    result=payload,
                )
        _heartbeat(
            connection,
            status=payload["status"],
            signal_events_enabled=signal_events_enabled,
            gate_metadata=gate_metadata,
            signal_event_result=payload.get("signal_events"),
        )
        return payload
    except Exception as exc:  # noqa: BLE001 - scheduler must report a bounded, redacted failure.
        gate_status = (
            "blocked"
            if type(exc).__name__
            in {
                "LiveSignalEventGateError",
                "HtDySchemaV3GateError",
                "HtDyS610Error",
                "HtDyS610OneDayError",
                "HtDyS610RemainingWindowError",
                "HtDyS610LongRunningError",
            }
            else "failed"
        )
        _heartbeat(
            connection,
            status="failed",
            error_type=type(exc).__name__,
            signal_events_enabled=signal_events_enabled,
            gate_metadata={**gate_metadata, "gate_status": gate_status},
        )
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


def _heartbeat(
    connection: Any,
    *,
    status: str,
    error_type: str | None = None,
    signal_events_enabled: bool = False,
    gate_metadata: Mapping[str, Any] | None = None,
    signal_event_result: Mapping[str, Any] | None = None,
) -> None:
    gate = gate_metadata or {}
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "error_type": error_type,
        "pid": os.getpid(),
        "signal_events_enabled": signal_events_enabled,
        "signal_event_gate_status": gate.get("gate_status") or ("disabled" if not signal_events_enabled else "unknown"),
        "signal_event_gate_schema": gate.get("gate_schema"),
        "signal_event_authorization_hash": gate.get("authorization_hash"),
        "signal_event_target_trading_day": gate.get("target_trading_day"),
        "signal_event_mapping_prepared": bool(
            gate.get("mapping_prepared")
        ),
        "signal_event_expected_bucket_ends": gate.get(
            "expected_bucket_ends"
        ),
        "signal_event_last_decision_bucket_end": gate.get(
            "last_decision_bucket_end"
        ),
        "signal_event_result": dict(signal_event_result) if signal_event_result is not None else None,
    }
    connection.setex(SCHEDULER_HEARTBEAT_KEY, 180, json.dumps(payload, ensure_ascii=False))


def _build_signal_gate(
    *,
    approval_packet: Path | None,
    approval_hash: str,
    environ: Mapping[str, str],
) -> SignalGate:
    if approval_packet is None:
        raise ValueError("approval_packet_required")
    try:
        packet = json.loads(approval_packet.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("approval_packet_invalid") from exc
    if not isinstance(packet, dict):
        raise ValueError("approval_packet_invalid")

    schema_version = packet.get("schema_version")
    request_type = packet.get("request_type")
    packet_type = packet.get("packet_type")

    # Superseded S6-10 / Approval D gates fail closed before importing frozen modules.
    if (
        schema_version == 1
        and request_type == "htdy_s6_10_approval_d_no_code_promotion"
    ) or schema_version in {4, 5, 6, 7}:
        raise ValueError("superseded_runtime_gate_disabled")
    if _enabled(environ, "GUIYI_HTDY_S610_REQUIRED"):
        raise ValueError("superseded_runtime_gate_disabled")
    if isinstance(packet_type, str) and packet_type.startswith("htdy_s6_10_"):
        raise ValueError("superseded_runtime_gate_disabled")

    from app.services.htdy_s6_08_runtime_gate import build_runtime_gate

    return build_runtime_gate(
        parent_packet_path=approval_packet,
        approval_hash=approval_hash,
        environ=environ,
    )


def _verify_polling_trading_day(decision: Any, *, target_trading_day: str) -> None:
    if not decision.should_poll:
        return
    actual = decision.trading_day.isoformat() if decision.trading_day is not None else None
    if actual != target_trading_day:
        from app.services.live_signal_event_gate import LiveSignalEventGateError

        raise LiveSignalEventGateError("runtime_trading_day_mismatch")


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
