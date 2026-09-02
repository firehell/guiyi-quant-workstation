"""归一量化统一 CLI 入口（``uv run guiyi``）。

子域：``data``（历史数据 audit/update/refresh）与 ``runtime``（健康、前台
Live、Alert 与显式 canary）。
默认 JSON 输出至 stdout；参数错误与异常经 output 模块脱敏后写 stderr。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
import sys
from typing import Any, TextIO

from app.db.session import SessionLocal
from app.alerts.composition import (
    acknowledge_alert_notification_failure,
    build_alert_runtime,
)
from app.alerts.notification import ALERT_AUDIENCES
from app.alerts.notification_composition import build_notification_sender_from_env
from app.guiyi_cli.data_commands import build_request, run_data_command
from app.guiyi_cli.data_parser import (
    CliUsageError,
    JsonArgumentParser,
    add_data_commands,
)
from app.guiyi_cli.output import (
    argument_error_payload,
    exception_error_payload,
    print_json,
)
from app.market_data.composition import (
    build_historical_data_manager,
    build_live_market_service,
)
from app.market_data.after_market import build_after_market_updater
from app.market_data.historical_data_manager import HistoricalDataManager
from app.services.runtime_health import build_runtime_health
from app.runtime_entry import run_after_market, run_alert, run_live

SessionFactory = Callable[[], AbstractContextManager[Any]]
ManagerFactory = Callable[[Any], HistoricalDataManager]
AfterMarketFactory = Callable[..., Any]
LiveServiceFactory = Callable[[Any], Any]
AlertRuntimeFactory = Callable[[], Any]
AlertCanarySenderFactory = Callable[[], Any]
AlertNotificationAcknowledger = Callable[[str], dict[str, object]]

def _execution_is_readonly(args: argparse.Namespace) -> bool:
    if args.domain == "runtime":
        if args.runtime_command == "status":
            return True
        return False
    return not bool(getattr(args, "apply", False))


def _parse_error_is_readonly(raw: Sequence[str]) -> bool:
    return not (
        len(raw) >= 2
        and raw[0] == "runtime"
        and raw[1]
        in {
            "live",
            "alert",
            "alert-canary",
            "acknowledge-alert-notification",
        }
    )


def build_parser() -> argparse.ArgumentParser:
    """构建 guiyi 根解析器：data 与 runtime。"""
    parser = JsonArgumentParser(prog="guiyi")
    domains = parser.add_subparsers(dest="domain", required=True)
    data = domains.add_parser("data")
    commands = data.add_subparsers(dest="data_command", required=True)
    add_data_commands(commands)
    runtime = domains.add_parser("runtime")
    runtime_commands = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_commands.add_parser("status")
    runtime_commands.add_parser("live")
    runtime_commands.add_parser("alert")
    alert_canary = runtime_commands.add_parser("alert-canary")
    alert_canary.add_argument(
        "--audience",
        required=True,
        choices=sorted(ALERT_AUDIENCES),
    )
    acknowledge_notification = runtime_commands.add_parser(
        "acknowledge-alert-notification"
    )
    acknowledge_notification.add_argument("--failure-at", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: SessionFactory = SessionLocal,
    manager_factory: ManagerFactory = build_historical_data_manager,
    after_market_factory: AfterMarketFactory = build_after_market_updater,
    live_service_factory: LiveServiceFactory = build_live_market_service,
    alert_runtime_factory: AlertRuntimeFactory = build_alert_runtime,
    alert_canary_sender_factory: AlertCanarySenderFactory = (
        build_notification_sender_from_env
    ),
    alert_notification_acknowledger: AlertNotificationAcknowledger = (
        acknowledge_alert_notification_failure
    ),
    runtime_health_builder=build_runtime_health,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """CLI 主流程：解析 → 执行 → JSON 输出；返回进程退出码（0 成功，2 参数，1 执行错误）。"""
    raw = list(argv) if argv is not None else sys.argv[1:]
    command = ".".join(raw[:2]) if raw else "guiyi"
    try:
        args = build_parser().parse_args(raw)
        if args.domain == "data":
            build_request(args)
    except (CliUsageError, ValueError):
        # 参数/用法错误：固定 CLI_ARGUMENT_INVALID，不写 stack trace
        payload = argument_error_payload(command)
        payload["readonly"] = _parse_error_is_readonly(raw)
        print_json(payload, stderr)
        return 2

    try:
        if args.domain == "data":
            payload = _run_data(
                args,
                session_factory,
                manager_factory,
                after_market_factory,
                stderr,
            )
        elif args.runtime_command == "status":
            # runtime status：只读聚合健康，与 HTTP /api/runtime/health 同源
            with session_factory() as session:
                health = runtime_health_builder(session)
                payload = {
                    "schema_version": 1,
                    "command": "runtime.status",
                    "status": health.get("status", "failed"),
                    "readonly": True,
                    "runtime": health,
                }
        elif args.runtime_command == "live":
            payload = run_live(
                session_factory=session_factory,
                live_service_factory=live_service_factory,
            )
        elif args.runtime_command == "alert":
            payload = run_alert(alert_runtime_factory=alert_runtime_factory)
        elif args.runtime_command == "alert-canary":
            acceptance = alert_canary_sender_factory().send_canary(args.audience)
            reference = acceptance.reference
            payload = {
                "schema_version": 1,
                "command": "runtime.alert-canary",
                "status": "accepted",
                "audience": args.audience,
                "provider_accepted": True,
                "provider_reference_suffix": (
                    reference[-6:] if isinstance(reference, str) else None
                ),
                "delivery_confirmed": False,
            }
        elif args.runtime_command == "acknowledge-alert-notification":
            acknowledged = alert_notification_acknowledger(args.failure_at)
            payload = {
                "schema_version": 1,
                "command": "runtime.acknowledge-alert-notification",
                "status": "acknowledged",
                "readonly": False,
                "last_notification_failure_at": acknowledged[
                    "last_notification_failure_at"
                ],
                "notification_acknowledged_at": acknowledged[
                    "notification_acknowledged_at"
                ],
                "notification_error_type": acknowledged[
                    "notification_error_type"
                ],
                "event_replayed": False,
                "notification_sent": False,
            }
        else:
            raise RuntimeError("CLI_RUNTIME_COMMAND_INVALID")
    except Exception as exc:  # noqa: BLE001 - safe CLI boundary
        # 执行期异常：error code 仅暴露公开码或 CLI_INTERNAL_ERROR
        print_json(
            exception_error_payload(
                command=command,
                exc=exc,
                readonly=_execution_is_readonly(args),
            ),
            stderr,
        )
        return 1
    print_json(payload, stdout)
    return (
        0
        if (
            payload.get("status")
            in {
                "passed",
                "planned",
                "published",
                "noop",
                "ok",
                "ready",
                "skipped",
                "accepted",
                "acknowledged",
            }
        )
        else 1
    )


def _run_data(
    args: argparse.Namespace,
    session_factory: SessionFactory,
    manager_factory: ManagerFactory,
    after_market_factory: AfterMarketFactory,
    stderr: TextIO,
) -> dict[str, object]:
    """在 DB 会话内执行 data 子命令并返回 as_payload 字典。"""
    if args.data_command == "after-market":
        return run_after_market(
            session_factory=session_factory,
            manager_factory=manager_factory,
            after_market_factory=after_market_factory,
            failure_notification=False,
        )
    with session_factory() as session:
        manager = manager_factory(session)
        return run_data_command(args, manager, progress_stream=stderr).as_payload()


def entrypoint() -> None:
    """setuptools/console_scripts 入口：将 main 退出码转为 SystemExit。"""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
