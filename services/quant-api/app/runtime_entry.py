"""Thin internal entrypoint for launchd-owned Runtime services.

This module deliberately excludes the public Research CLI composition graph.
The public ``guiyi`` CLI reuses the same runners while retaining its parser and
JSON contract.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
import logging
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
    "live": "runtime.live",
    "alert": "runtime.alert",
    "after-market": "data.after-market",
    "weekly-audit": "data.weekly-audit",
}


def run_live(
    *,
    session_factory: SessionFactory,
    live_service_factory: LiveServiceFactory,
) -> dict[str, object]:
    """Run the existing foreground Live service and return its public payload."""
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
        if service == "live":
            payload = run_live(
                session_factory=session_factory,
                live_service_factory=live_service_factory,
            )
        elif service == "alert":
            payload = run_alert(alert_runtime_factory=alert_runtime_factory)
        elif service == "weekly-audit":
            payload = run_weekly_audit_service(session_factory=session_factory, manager_factory=manager_factory)
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
                readonly=service == "weekly-audit",
            ),
            stderr,
        )
        return 1
    print_json(payload, stdout)
    return 0 if payload.get("status") in {"passed", "skipped", "skipped_busy", "ok"} else 1


def run_weekly_audit_service(*, session_factory: SessionFactory, manager_factory: ManagerFactory) -> dict[str, object]:
    from datetime import datetime
    from app.core.env import PROJECT_ROOT
    from app.market_data.captured_recovery_runtime import runtime_heartbeat_identity
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.session_clock import SHANGHAI
    from app.market_data.weekly_audit import run_weekly_audit

    with session_factory() as session:
        return run_weekly_audit(manager_factory(session),
            status_path=PROJECT_ROOT / ".run" / "weekly-audit-status.json",
            products=load_operational_products(), identity=runtime_heartbeat_identity(),
            now=lambda: datetime.now(SHANGHAI))


def entrypoint() -> None:
    handler = None
    if len(sys.argv) == 2 and sys.argv[1] in {"live", "alert", "after-market", "weekly-audit"}:
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
