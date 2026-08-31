"""Thin internal entrypoint for launchd-owned Runtime services.

This module deliberately excludes the public Research CLI composition graph.
The public ``guiyi`` CLI reuses the same runners while retaining its parser and
JSON contract.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
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
    build_subing_daily_watch_generator,
)
from app.market_data.historical_data_manager import HistoricalDataManager


SessionFactory = Callable[[], AbstractContextManager[Any]]
ManagerFactory = Callable[[Any], HistoricalDataManager]
AfterMarketFactory = Callable[..., Any]
LiveServiceFactory = Callable[[Any], Any]
AlertRuntimeFactory = Callable[[], Any]
DailyWatchGeneratorFactory = Callable[[Any], Any]

_LOGGER = logging.getLogger(__name__)
_COMMANDS = {
    "live": "runtime.live",
    "alert": "runtime.alert",
    "after-market": "data.after-market",
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
    daily_watch_generator_factory: DailyWatchGeneratorFactory | None = None,
) -> dict[str, object]:
    """Run Market maintenance, then optional isolated follow-ups.

    The Daily Watch factory is injected only by the supervised Runtime entrypoint.
    """
    def post_update(trading_day: date) -> None:
        if daily_watch_generator_factory is None:
            return
        with session_factory() as daily_watch_session:
            daily_watch_generator_factory(daily_watch_session).run(trading_day)

    with session_factory() as session:
        manager = manager_factory(session)
        market_result = after_market_factory(
            manager,
            failure_notification=failure_notification,
        ).run(
            post_update=(post_update if daily_watch_generator_factory is not None else None)
        )
    return market_result.as_payload()


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: SessionFactory = SessionLocal,
    manager_factory: ManagerFactory = build_historical_data_manager,
    after_market_factory: AfterMarketFactory = build_after_market_updater,
    live_service_factory: LiveServiceFactory = build_live_market_service,
    alert_runtime_factory: AlertRuntimeFactory = build_alert_runtime,
    daily_watch_generator_factory: DailyWatchGeneratorFactory = (
        build_subing_daily_watch_generator
    ),
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
        else:
            payload = run_after_market(
                session_factory=session_factory,
                manager_factory=manager_factory,
                after_market_factory=after_market_factory,
                failure_notification=True,
                daily_watch_generator_factory=daily_watch_generator_factory,
            )
    except Exception as exc:  # noqa: BLE001 - safe process boundary
        print_json(
            exception_error_payload(
                command=command,
                exc=exc,
                readonly=service == "after-market",
            ),
            stderr,
        )
        return 1
    print_json(payload, stdout)
    return 0 if payload.get("status") in {"passed", "skipped", "ok"} else 1


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
