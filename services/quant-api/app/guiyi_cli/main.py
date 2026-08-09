"""归一量化统一 CLI 入口（``uv run guiyi``）。

子域：``data``（历史数据 audit/update/refresh）、``runtime status``（只读健康）。
默认 JSON 输出至 stdout；参数错误与异常经 output 模块脱敏后写 stderr。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
import sys
from typing import Any, TextIO

from app.db.session import SessionLocal
from app.guiyi_cli.data_commands import build_request, run_data_command
from app.guiyi_cli.data_parser import CliUsageError, JsonArgumentParser, add_data_commands
from app.guiyi_cli.output import (
    argument_error_payload,
    exception_error_payload,
    print_json,
)
from app.market_data.composition import build_historical_data_manager
from app.market_data.maintenance import HistoricalDataManager
from app.market_data.product_retirement import ProductRetiredError
from app.services.runtime_health import build_runtime_health

SessionFactory = Callable[[], AbstractContextManager[Any]]
ManagerFactory = Callable[[Any], HistoricalDataManager]


def build_parser() -> argparse.ArgumentParser:
    """构建 guiyi 根解析器：data 与 runtime 两个子域。"""
    parser = JsonArgumentParser(prog="guiyi")
    domains = parser.add_subparsers(dest="domain", required=True)
    data = domains.add_parser("data")
    commands = data.add_subparsers(dest="data_command", required=True)
    add_data_commands(commands)
    runtime = domains.add_parser("runtime")
    runtime.add_subparsers(dest="runtime_command", required=True).add_parser("status")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: SessionFactory = SessionLocal,
    manager_factory: ManagerFactory = build_historical_data_manager,
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
    except ProductRetiredError as exc:
        print_json(
            exception_error_payload(
                command=command,
                exc=exc,
                readonly=True,
            ),
            stderr,
        )
        return 1
    except (CliUsageError, ValueError):
        # 参数/用法错误：固定 CLI_ARGUMENT_INVALID，不写 stack trace
        print_json(argument_error_payload(command), stderr)
        return 2

    try:
        if args.domain == "data":
            payload = _run_data(args, session_factory, manager_factory)
        else:
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
    except Exception as exc:  # noqa: BLE001 - safe CLI boundary
        # 执行期异常：error code 仅暴露公开码或 CLI_INTERNAL_ERROR
        print_json(
            exception_error_payload(
                command=command,
                exc=exc,
                readonly=not bool(getattr(args, "apply", False)),
            ),
            stderr,
        )
        return 1
    print_json(payload, stdout)
    return 0 if payload.get("status") in {"passed", "planned", "noop", "ok"} else 1


def _run_data(
    args: argparse.Namespace,
    session_factory: SessionFactory,
    manager_factory: ManagerFactory,
) -> dict[str, object]:
    """在 DB 会话内执行 data 子命令并返回 as_payload 字典。"""
    with session_factory() as session:
        return run_data_command(args, manager_factory(session)).as_payload()


def entrypoint() -> None:
    """setuptools/console_scripts 入口：将 main 退出码转为 SystemExit。"""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
