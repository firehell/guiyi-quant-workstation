"""归一量化统一 CLI 入口（``uv run guiyi``）。

子域：``data``（历史数据 audit/update/refresh）、``research``（只读研究）与
``runtime``（健康、前台 Live、Alert 与显式 canary）。
默认 JSON 输出至 stdout；参数错误与异常经 output 模块脱敏后写 stderr。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
import logging
from pathlib import Path
import stat
import sys
from typing import Any, TextIO

from app.db.session import SessionLocal
from app.alerts.composition import build_alert_runtime
from app.alerts.notification import ALERT_AUDIENCES
from app.alerts.notification_composition import build_notification_sender_from_env
from app.core.env import PROJECT_ROOT
from app.execution_review.composition import build_execution_review_roll_reconciler
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
from app.guiyi_cli.research_parser import add_research_commands
from app.guiyi_cli.research_commands import (
    ResearchRequest,
    build_research_request,
    run_research_command,
)
from app.market_data.composition import (
    build_historical_data_manager,
    build_live_market_service,
    build_main_force_mirror_futures_research_service,
    build_multi_candidate_robustness_service,
    build_n_candidate_validation_service,
    build_n_structure_research_service,
    build_subing_candidate_validation_service,
    build_subing_calibration_research_service,
    build_subing_lifecycle_research_service,
)
from app.market_data.after_market import build_after_market_updater
from app.market_data.candidate_validation_schedule import CandidateValidationRequest
from app.market_data.historical_data_manager import HistoricalDataManager
from app.market_data.product_retirement import ProductRetiredError
from app.services.runtime_health import build_runtime_health

SessionFactory = Callable[[], AbstractContextManager[Any]]
ManagerFactory = Callable[[Any], HistoricalDataManager]
AfterMarketFactory = Callable[[HistoricalDataManager], Any]
LiveServiceFactory = Callable[[Any], Any]
AlertRuntimeFactory = Callable[[], Any]
AlertCanarySenderFactory = Callable[[], Any]
ResearchServiceFactory = Callable[[Any], Any]
RollReconcilerFactory = Callable[[Any], Any]
RollMarkerState = Callable[[], str]

logger = logging.getLogger(__name__)


def _execution_is_readonly(args: argparse.Namespace) -> bool:
    if args.domain == "research":
        return True
    if args.domain == "runtime":
        if args.runtime_command == "status":
            return True
        return False
    return not bool(getattr(args, "apply", False))


def _parse_error_is_readonly(raw: Sequence[str]) -> bool:
    return not (
        len(raw) >= 2
        and raw[0] == "runtime"
        and raw[1] in {"live", "alert", "alert-canary"}
    )


def _execution_review_roll_marker_state(
    project_root: Path = PROJECT_ROOT,
) -> str:
    marker = project_root / ".run/execution-review-roll-enabled"
    try:
        metadata = marker.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return "invalid"
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            return "invalid"
        return "enabled" if marker.read_bytes() == b"enabled\n" else "invalid"
    except FileNotFoundError:
        return "disabled"
    except OSError:
        return "invalid"


def build_parser() -> argparse.ArgumentParser:
    """构建 guiyi 根解析器：data、research 与 runtime。"""
    parser = JsonArgumentParser(prog="guiyi")
    domains = parser.add_subparsers(dest="domain", required=True)
    data = domains.add_parser("data")
    commands = data.add_subparsers(dest="data_command", required=True)
    add_data_commands(commands)
    research = domains.add_parser("research")
    research_commands = research.add_subparsers(dest="research_command", required=True)
    add_research_commands(research_commands)
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
    research_service_factory: ResearchServiceFactory = (
        build_subing_calibration_research_service
    ),
    lifecycle_research_service_factory: ResearchServiceFactory = (
        build_subing_lifecycle_research_service
    ),
    candidate_validation_service_factory: ResearchServiceFactory = (
        build_subing_candidate_validation_service
    ),
    n_candidate_validation_service_factory: ResearchServiceFactory = (
        build_n_candidate_validation_service
    ),
    main_force_mirror_futures_research_service_factory: ResearchServiceFactory = (
        build_main_force_mirror_futures_research_service
    ),
    n_structure_research_service_factory: ResearchServiceFactory = (
        build_n_structure_research_service
    ),
    multi_candidate_robustness_service_factory: ResearchServiceFactory = (
        build_multi_candidate_robustness_service
    ),
    execution_review_roll_marker_state: RollMarkerState = (
        _execution_review_roll_marker_state
    ),
    roll_reconciler_factory: RollReconcilerFactory = (
        build_execution_review_roll_reconciler
    ),
    runtime_health_builder=build_runtime_health,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """CLI 主流程：解析 → 执行 → JSON 输出；返回进程退出码（0 成功，2 参数，1 执行错误）。"""
    raw = list(argv) if argv is not None else sys.argv[1:]
    command = ".".join(raw[:2]) if raw else "guiyi"
    research_request: ResearchRequest | None = None
    try:
        args = build_parser().parse_args(raw)
        if args.domain == "data":
            build_request(args)
        elif args.domain == "research":
            research_request = build_research_request(args)
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
                execution_review_roll_marker_state,
                roll_reconciler_factory,
            )
        elif args.domain == "research":
            assert research_request is not None
            with session_factory() as session:
                if args.research_command == "subing-lifecycle":
                    service_factory = lifecycle_research_service_factory
                elif args.research_command == "candidate-robustness":
                    service_factory = multi_candidate_robustness_service_factory
                elif args.research_command == "n-structure":
                    service_factory = n_structure_research_service_factory
                elif args.research_command == "candidate-validation":
                    if not isinstance(research_request, CandidateValidationRequest):
                        raise ValueError("CLI_CANDIDATE_REQUEST_INVALID")
                    if (
                        research_request.candidate_id
                        == "subing_lifecycle_v2_candidate_v1"
                    ):
                        service_factory = candidate_validation_service_factory
                    elif research_request.candidate_id == "n_structure_5m_candidate_v1":
                        service_factory = n_candidate_validation_service_factory
                    else:
                        raise ValueError("CLI_CANDIDATE_ID_INVALID")
                elif args.research_command == "main-force-mirror-futures":
                    service_factory = main_force_mirror_futures_research_service_factory
                elif args.research_command == "subing-calibration":
                    service_factory = research_service_factory
                else:
                    raise ValueError("CLI_RESEARCH_COMMAND_INVALID")
                payload = run_research_command(
                    research_request,
                    service_factory(session),
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
            # 前台阻塞循环由 launchd/终端托管；Python 不 daemonize 或启动 worker。
            with session_factory() as session:
                live_service_factory(session).run_forever()
            payload = {
                "schema_version": 1,
                "command": "runtime.live",
                "status": "ok",
                "foreground": True,
            }
        elif args.runtime_command == "alert":
            alert_runtime_factory().run_forever()
            payload = {
                "schema_version": 1,
                "command": "runtime.alert",
                "status": "ok",
                "foreground": True,
            }
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
        if payload.get("status")
        in {"passed", "planned", "noop", "ok", "ready", "skipped", "accepted"}
        else 1
    )


def _run_data(
    args: argparse.Namespace,
    session_factory: SessionFactory,
    manager_factory: ManagerFactory,
    after_market_factory: AfterMarketFactory,
    execution_review_roll_marker_state: RollMarkerState,
    roll_reconciler_factory: RollReconcilerFactory,
) -> dict[str, object]:
    """在 DB 会话内执行 data 子命令并返回 as_payload 字典。"""
    if args.data_command == "after-market":
        with session_factory() as session:
            manager = manager_factory(session)
            market_result = after_market_factory(manager).run()
        payload = market_result.as_payload()
        if (
            market_result.status == "passed"
            and execution_review_roll_marker_state() == "enabled"
        ):
            try:
                with session_factory() as followup_session:
                    roll_reconciler_factory(followup_session).reconcile_open_episodes()
            except Exception:  # noqa: BLE001 - isolated best-effort follow-up
                logger.warning("EXECUTION_REVIEW_ROLL_FOLLOWUP_FAILED")
        return payload
    with session_factory() as session:
        manager = manager_factory(session)
        return run_data_command(args, manager).as_payload()


def entrypoint() -> None:
    """setuptools/console_scripts 入口：将 main 退出码转为 SystemExit。"""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
