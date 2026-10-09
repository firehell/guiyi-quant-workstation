"""Thin internal entrypoint for launchd-owned Runtime services.

This module deliberately excludes the public Research CLI composition graph.
The public ``guiyi`` CLI reuses the same runners while retaining its parser and
JSON contract.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
import logging
import os
import signal
import sys
from typing import Any, TextIO

from app.alerts.composition import build_alert_runtime
from app.db.session import SessionLocal
from app.guiyi_cli.output import (
    argument_error_payload,
    exception_error_payload,
    print_json,
)
from app.market_data.after_market import build_after_market_updater
from app.market_data.composition import (
    build_historical_data_manager,
    build_live_market_service,
)
from app.market_data.historical_data_manager import HistoricalDataManager


SessionFactory = Callable[[], AbstractContextManager[Any]]
ManagerFactory = Callable[[Any], HistoricalDataManager]
AfterMarketFactory = Callable[..., Any]
LiveServiceFactory = Callable[[Any], Any]
AlertRuntimeFactory = Callable[[], Any]

_LOGGER = logging.getLogger(__name__)
_COMMANDS = {
    "market-feed": "runtime.market-feed",
    "live": "runtime.live",
    "alert": "runtime.alert",
    "after-market": "data.after-market",
    "late-provider-recovery": "data.late-provider-recovery",
    "weekly-audit": "data.weekly-audit",
    "weekly-audit-scheduled": "data.weekly-audit-scheduled",
}


def build_market_feed_service(session):
    from app.market_data.composition import build_market_feed_service as factory
    return factory(session)


def _owned_runner(service: str, run) -> None:
    """Drain cooperatively; SIGTERM cannot release ownership around an active send."""
    from app.runtime_handover import run_supervised
    stopped = False
    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True
    original = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        original[signum] = signal.signal(signum, stop)
    try:
        run_supervised(service, lambda owner: run(owner, lambda: stopped or owner.should_drain()),
                       stop_requested=lambda: stopped)
    finally:
        for signum, handler in original.items():
            signal.signal(signum, handler)


def run_live(
    *,
    session_factory: SessionFactory,
    live_service_factory: LiveServiceFactory,
) -> dict[str, object]:
    """Run the existing foreground Live service and return its public payload."""
    if os.getenv('GUIYI_RUNTIME_HANDOVER_ENABLED') == '1':
        def run(owner, should_stop):
            with session_factory() as session:
                instance = live_service_factory(session)
                instance.assert_owned = owner.assert_owned
                poll = instance.poll
                def checked_poll(now):
                    owner.mark_not_ready()
                    result = poll(now)
                    if result is None:
                        source = getattr(instance, 'source_provider', None)
                        if source is None:
                            owner.mark_ready()
                        else:
                            owner.mark_ready({'input_read_frontier': source.after,
                                'trading_day': source.day.isoformat() if source.day else None})
                    return result
                instance.poll = checked_poll
                instance.run_forever(should_stop=should_stop)
        _owned_runner('live', run)
    else:
        with session_factory() as session:
            live_service_factory(session).run_forever()
    return {
        "schema_version": 1,
        "command": "runtime.live",
        "status": "ok",
        "foreground": True,
    }


def run_alert(
    *,
    alert_runtime_factory: AlertRuntimeFactory,
) -> dict[str, object]:
    """Run the existing foreground Alert runtime and return its public payload."""
    if os.getenv('GUIYI_RUNTIME_HANDOVER_ENABLED') == '1':
        def run(owner, should_stop):
            instance = alert_runtime_factory(assert_owned=owner.assert_owned)
            instance.stop_requested = should_stop
            instance.mark_ready = owner.mark_ready
            instance.run_forever()
        _owned_runner('alert', run)
    else:
        alert_runtime_factory().run_forever()
    return {
        "schema_version": 1,
        "command": "runtime.alert",
        "status": "ok",
        "foreground": True,
    }


def run_after_market(
    *,
    session_factory: SessionFactory,
    manager_factory: ManagerFactory,
    after_market_factory: AfterMarketFactory,
    failure_notification: bool,
) -> dict[str, object]:
    """Run Market maintenance through the supervised Runtime entrypoint."""
    with session_factory() as session:
        manager = manager_factory(session)
        updater = after_market_factory(
            manager,
            failure_notification=failure_notification,
        )
        market_result = updater.run()
    return market_result.as_payload()


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: SessionFactory = SessionLocal,
    manager_factory: ManagerFactory = build_historical_data_manager,
    after_market_factory: AfterMarketFactory = build_after_market_updater,
    live_service_factory: LiveServiceFactory = build_live_market_service,
    alert_runtime_factory: AlertRuntimeFactory = build_alert_runtime,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Dispatch one internal launchd service without loading the public CLI."""
    raw = list(argv) if argv is not None else sys.argv[1:]
    if len(raw) != 1 or raw[0] not in _COMMANDS:
        print_json(argument_error_payload("runtime"), stderr)
        return 2
    service = raw[0]
    command = _COMMANDS[service]
    try:
        if service == 'market-feed':
            def run_feed(owner, should_stop):
                with session_factory() as session:
                    feed = build_market_feed_service(session)
                    if owner is not None:
                        feed.assert_owned = owner.assert_owned
                        poll = feed.poll
                        def checked_poll(now):
                            owner.mark_not_ready()
                            result = poll(now)
                            if result is None:
                                owner.mark_ready()
                            return result
                        feed.poll = checked_poll
                    feed.run_forever(should_stop=should_stop)
            if os.getenv('GUIYI_RUNTIME_HANDOVER_ENABLED') == '1':
                _owned_runner(service, run_feed)
            else:
                run_feed(None, lambda: False)
            payload = {'schema_version': 1, 'command': command, 'status': 'ok', 'foreground': True}
        elif service == "live":
            payload = run_live(
                session_factory=session_factory,
                live_service_factory=live_service_factory,
            )
        elif service == "alert":
            payload = run_alert(alert_runtime_factory=alert_runtime_factory)
        elif service == "late-provider-recovery":
            from app.market_data.late_provider_recovery import run_runtime_scheduled
            with session_factory() as session:
                payload = run_runtime_scheduled(manager_factory(session))
        elif service in {"weekly-audit", "weekly-audit-scheduled"}:
            payload = run_weekly_audit_service(
                session_factory=session_factory,
                manager_factory=manager_factory,
                scheduled=service == "weekly-audit-scheduled",
            )
        else:
            payload = run_after_market(
                session_factory=session_factory,
                manager_factory=manager_factory,
                after_market_factory=after_market_factory,
                failure_notification=True,
            )
    except Exception as exc:  # noqa: BLE001 - safe process boundary
        print_json(
            exception_error_payload(
                command=command,
                exc=exc,
                readonly=service in {"weekly-audit", "weekly-audit-scheduled"},
            ),
            stderr,
        )
        return 1
    print_json(payload, stdout)
    return 0 if payload.get("status") in {
        "passed", "skipped", "skipped_busy", "not_due", "already_attempted", "ok",
    } else 1


def run_weekly_audit_service(
    *, session_factory: SessionFactory, manager_factory: ManagerFactory,
    scheduled: bool = False,
) -> dict[str, object]:
    from datetime import datetime
    from app.core.env import PROJECT_ROOT
    from app.market_data.captured_recovery_runtime import runtime_heartbeat_identity
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.session_clock import SHANGHAI
    from app.market_data.weekly_audit import run_scheduled_weekly_audit, run_weekly_audit

    with session_factory() as session:
        runner = run_scheduled_weekly_audit if scheduled else run_weekly_audit
        return runner(manager_factory(session),
            status_path=PROJECT_ROOT / ".run" / "weekly-audit-status.json",
            products=load_operational_products(), identity=runtime_heartbeat_identity(),
            now=lambda: datetime.now(SHANGHAI))


def entrypoint() -> None:
    handler = None
    if len(sys.argv) == 2 and sys.argv[1] in {
        "market-feed", "live", "alert", "after-market", "late-provider-recovery", "weekly-audit", "weekly-audit-scheduled",
    }:
        from app.runtime_logging import install_runtime_diagnostics

        try:
            handler = install_runtime_diagnostics(sys.argv[1])
        except Exception:
            try:
                print("RUNTIME_LOG_UNAVAILABLE", file=sys.stderr)
            except Exception:
                pass
            if sys.argv[1] in {"live", "alert"}:
                raise SystemExit(1) from None
    try:
        raise SystemExit(main())
    finally:
        if handler is not None:
            logging.getLogger("app").removeHandler(handler)
            try:
                handler.close()
            except Exception:
                if sys.argv[1] in {"live", "alert"}:
                    raise


if __name__ == "__main__":
    entrypoint()
