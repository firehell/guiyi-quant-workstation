from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime, time
import json
import os
from pathlib import Path
import sys
from typing import Any, TextIO

from app.data_core.historical_apply_gate import (
    HistoricalApplyGateError,
    load_apply_approval_packet,
)
from app.data_core.cli_service import run_data_core_command
from app.db.session import SessionLocal
from app.services.active_dataset import ActiveDatasetDomainError
from app.services.core_cli import verify_active_dataset
from app.services.market_workbench import MarketAccessError
from app.services.runtime_health import build_runtime_health
from app.runtime_scheduler import dry_run_payload


SessionFactory = Callable[[], AbstractContextManager[Any]]
DataVerifier = Callable[..., dict[str, Any]]
RuntimeHealthBuilder = Callable[[Any], dict[str, Any]]
DataCoreRunner = Callable[[str, Any, argparse.Namespace], dict[str, Any]]


class CliUsageError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="guiyi")
    domains = parser.add_subparsers(dest="domain", required=True)

    data = domains.add_parser("data")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    verify = data_commands.add_parser("verify")
    verify.add_argument("--symbol", required=True)
    verify.add_argument("--contract")
    verify.add_argument("--period")
    verify.add_argument(
        "--dataset-kind",
        choices=("continuous", "actual_dominant"),
    )
    verify.add_argument("--contract-or-series")
    verify.add_argument(
        "--frequency",
        choices=("1m", "5m", "15m", "30m", "60m", "1d", "1w"),
    )
    verify.add_argument("--canonical-root", type=Path)
    verify.add_argument("--start")
    verify.add_argument("--end")
    verify.add_argument("--provider")
    verify.add_argument("--profile-id")
    verify.add_argument("--access-mode", choices=("browser", "research"), default="browser")
    verify.add_argument("--limit", type=_positive_int, default=5000)
    plan = data_commands.add_parser("plan")
    _add_data_core_query_arguments(plan)
    sync = data_commands.add_parser("sync")
    _add_data_core_query_arguments(sync)
    sync.add_argument("--apply", action="store_true")
    sync.add_argument("--approval-packet", type=Path)
    sync.add_argument("--approval-hash")

    migrate = data_commands.add_parser("migrate")
    migrate_commands = migrate.add_subparsers(
        dest="migrate_command",
        required=True,
    )
    inventory = migrate_commands.add_parser("inventory")
    inventory.add_argument("--project-root", type=Path, required=True)
    plan_migration = migrate_commands.add_parser("plan")
    plan_migration.add_argument("--project-root", type=Path, required=True)
    plan_migration.add_argument("--legacy-root", type=Path, required=True)
    plan_migration.add_argument("--canonical-root", type=Path, required=True)
    plan_migration.add_argument("--staging-root", type=Path, required=True)
    plan_migration.add_argument("--start", required=True)
    plan_migration.add_argument("--end", required=True)
    shadow = migrate_commands.add_parser("shadow")
    shadow.add_argument("--legacy-json", type=Path, required=True)
    shadow.add_argument("--canonical-json", type=Path, required=True)
    shadow.add_argument("--allowed-boundary-key", action="append", default=[])
    apply = migrate_commands.add_parser("apply")
    apply.add_argument("--project-root", type=Path, required=True)
    apply.add_argument("--legacy-root", type=Path, required=True)
    apply.add_argument("--canonical-root", type=Path, required=True)
    apply.add_argument("--staging-root", type=Path, required=True)
    apply.add_argument("--start", required=True)
    apply.add_argument("--end", required=True)
    apply.add_argument("--approval-packet", type=Path)
    apply.add_argument("--approval-hash")

    runtime = domains.add_parser("runtime")
    runtime_commands = runtime.add_subparsers(
        dest="runtime_command",
        required=True,
    )
    runtime_commands.add_parser("status")
    plan = runtime_commands.add_parser("plan")
    plan.add_argument("--product", choices=("jm",), default="jm")
    plan.add_argument("--poll-seconds", type=_positive_int, default=20)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    session_factory: SessionFactory = SessionLocal,
    data_verifier: DataVerifier = verify_active_dataset,
    data_core_runner: DataCoreRunner = run_data_core_command,
    runtime_health_builder: RuntimeHealthBuilder = build_runtime_health,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    try:
        args = build_parser().parse_args(raw_argv)
        _validate_conditional_arguments(args)
    except CliUsageError as exc:
        _print_json(
            {
                "schema_version": 1,
                "command": _command_hint(raw_argv),
                "status": "error",
                "readonly": True,
                "error": {
                    "code": "CLI_ARGUMENT_INVALID",
                    "type": type(exc).__name__,
                },
            },
            stderr,
        )
        return 2
    data_core_command = _data_core_command(args)
    if data_core_command is not None:
        if _is_data_core_apply(args) and (
            args.approval_packet is None or not args.approval_hash
        ):
            _print_json(
                {
                    "schema_version": 1,
                    "command": f"data.{data_core_command}",
                    "status": "blocked",
                    "readonly": True,
                    "error": {
                        "code": "JM_REAL_DATA_GATE_REQUIRED",
                        "type": "HistoricalApplyGateError",
                    },
                },
                stderr,
            )
            return 78
        if args.data_command == "sync" and args.apply:
            _print_json(
                {
                    "schema_version": 1,
                    "command": f"data.{data_core_command}",
                    "status": "blocked",
                    "readonly": True,
                    "error": {
                        "code": "JM_REAL_DATA_APPLY_NOT_AUTHORIZED",
                        "type": "HistoricalApplyGateError",
                    },
                },
                stderr,
            )
            return 78
        if _is_migrate_apply(args):
            try:
                load_apply_approval_packet(
                    args.approval_packet,
                    approval_hash=args.approval_hash,
                )
            except HistoricalApplyGateError as exc:
                _print_json(
                    {
                        "schema_version": 1,
                        "command": f"data.{data_core_command}",
                        "status": "blocked",
                        "readonly": True,
                        "error": {"code": exc.code, "type": type(exc).__name__},
                    },
                    stderr,
                )
                return 78
        try:
            with session_factory() as session:
                payload = data_core_runner(data_core_command, session, args)
        except Exception as exc:  # noqa: BLE001 - bounded CLI boundary.
            code = getattr(exc, "code", "DATA_CORE_COMMAND_FAILED")
            _print_json(
                {
                    "schema_version": 1,
                    "command": f"data.{data_core_command}",
                    "status": "error",
                    "readonly": not _is_data_core_apply(args),
                    "error": {"code": code, "type": type(exc).__name__},
                },
                stderr,
            )
            return 1
        _print_json(payload, stdout)
        return 0 if payload.get("status") in {
            "passed",
            "planned",
            "passed_with_declared_boundaries",
        } else 1
    if args.domain == "runtime" and args.runtime_command == "plan":
        scheduler_plan = dry_run_payload(args, environ if environ is not None else os.environ)
        _print_json(
            {
                "schema_version": 1,
                "command": "runtime.plan",
                "status": "planned",
                "readonly": True,
                "effects": {
                    key: scheduler_plan[key]
                    for key in (
                        "would_open_database",
                        "would_connect_redis",
                        "would_construct_rqdata_client",
                        "would_write_live_tables",
                        "would_write_historical_active",
                        "would_write_signal_event",
                        "would_send_notification",
                        "auto_order",
                    )
                },
                "plan": {
                    key: scheduler_plan[key]
                    for key in ("mode", "product", "poll_seconds", "enabled")
                },
            },
            stdout,
        )
        return 0

    if args.domain == "runtime" and args.runtime_command == "status":
        try:
            with session_factory() as session:
                health = runtime_health_builder(session)
        except Exception as exc:  # noqa: BLE001 - never emit health exception text.
            _print_json(
                {
                    "schema_version": 1,
                    "command": "runtime.status",
                    "status": "error",
                    "readonly": True,
                    "error": {
                        "code": "RUNTIME_STATUS_FAILED",
                        "type": type(exc).__name__,
                    },
                },
                stderr,
            )
            return 1
        payload = {
            "schema_version": 1,
            "command": "runtime.status",
            "status": health.get("status", "failed"),
            "readonly": True,
            "effects": {
                key: health.get(key, False)
                for key in (
                    "would_start_services",
                    "would_enqueue_jobs",
                    "would_send_notifications",
                )
            },
            "runtime": health,
        }
        _print_json(payload, stdout)
        return 0 if health.get("status") == "ok" else 1

    command = "data.verify"
    try:
        start = _parse_datetime(args.start, end_of_day=False)
        end = _parse_datetime(args.end, end_of_day=True)
    except ValueError as exc:
        _print_json(
            {
                "schema_version": 1,
                "command": command,
                "status": "error",
                "readonly": True,
                "error": {
                    "code": "CLI_ARGUMENT_INVALID",
                    "type": type(exc).__name__,
                },
            },
            stderr,
        )
        return 2
    try:
        with session_factory() as session:
            payload = data_verifier(
                session,
                symbol=args.symbol,
                contract=args.contract,
                period=args.period,
                start=start,
                end=end,
                provider=args.provider,
                profile_id=args.profile_id,
                access_mode=args.access_mode,
                limit=args.limit,
                legacy_compat=False,
            )
    except ActiveDatasetDomainError as exc:
        _print_json(
            {
                "schema_version": 1,
                "command": command,
                "status": "error",
                "readonly": True,
                "error": {"code": exc.code, "type": type(exc).__name__},
            },
            stderr,
        )
        return 1
    except MarketAccessError as exc:
        _print_json(
            {
                "schema_version": 1,
                "command": command,
                "status": "error",
                "readonly": True,
                "error": {"code": exc.code, "type": type(exc).__name__},
            },
            stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits no exception text.
        _print_json(
            {
                "schema_version": 1,
                "command": command,
                "status": "error",
                "readonly": True,
                "error": {"code": "CLI_INTERNAL_ERROR", "type": type(exc).__name__},
            },
            stderr,
        )
        return 1
    _print_json(payload, stdout)
    return 0 if payload.get("status") == "passed" else 1


def entrypoint() -> None:
    raise SystemExit(main())


def _parse_datetime(
    value: str | None,
    *,
    end_of_day: bool,
) -> datetime | None:
    if value is None:
        return None
    if len(value) == 10:
        return datetime.combine(
            date.fromisoformat(value),
            time.max if end_of_day else time.min,
        )
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _add_data_core_query_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dataset-kind",
        choices=("continuous", "actual_dominant"),
        required=True,
    )
    parser.add_argument("--symbol", choices=("jm",), required=True)
    parser.add_argument("--contract-or-series", required=True)
    parser.add_argument(
        "--frequency",
        choices=("1m", "1d", "1w"),
        required=True,
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)


def _data_core_command(args: argparse.Namespace) -> str | None:
    if args.domain != "data":
        return None
    if args.data_command in {"plan", "sync"}:
        return str(args.data_command)
    if args.data_command == "verify" and args.dataset_kind is not None:
        return "verify"
    if args.data_command == "migrate":
        return f"migrate.{args.migrate_command}"
    return None


def _validate_conditional_arguments(args: argparse.Namespace) -> None:
    if args.domain != "data" or args.data_command != "verify":
        return
    if args.dataset_kind is not None:
        required = (
            args.contract_or_series,
            args.frequency,
            args.start,
            args.end,
            args.canonical_root,
        )
        if args.symbol.strip().lower() != "jm" or any(
            value is None or (isinstance(value, str) and not value.strip())
            for value in required
        ):
            raise CliUsageError("canonical verify requires exact JM identity/window/root")
        return
    if not args.contract or not args.period:
        raise CliUsageError("legacy verify requires contract and period")


def _is_data_core_apply(args: argparse.Namespace) -> bool:
    return bool(
        (args.data_command == "sync" and args.apply)
        or (
            args.data_command == "migrate"
            and args.migrate_command == "apply"
        )
    )


def _is_migrate_apply(args: argparse.Namespace) -> bool:
    return bool(
        args.data_command == "migrate"
        and args.migrate_command == "apply"
    )


def _print_json(payload: Mapping[str, Any], stream: TextIO) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ),
        file=stream,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _command_hint(argv: Sequence[str]) -> str:
    if len(argv) >= 2 and argv[0] in {"data", "runtime"}:
        return f"{argv[0]}.{argv[1]}"
    if argv:
        return str(argv[0])
    return "guiyi"


if __name__ == "__main__":
    entrypoint()
