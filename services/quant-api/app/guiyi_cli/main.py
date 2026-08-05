from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime, time
import os
from pathlib import Path
import sys
from typing import Any, TextIO

from app.data_core.cli_service import run_data_core_command
from app.db.session import SessionLocal
from app.guiyi_cli.data_commands import (
    build_data_operation_request,
    is_new_data_operation,
    run_data_operation,
)
from app.guiyi_cli.data_parser import (
    CliUsageError,
    JsonArgumentParser,
    add_data_commands,
    reject_legacy_backfill_alias,
)
from app.guiyi_cli.output import (
    argument_error_payload,
    exception_error_payload,
    print_json,
)
from app.services.active_dataset import ActiveDatasetDomainError
from app.services.core_cli import verify_active_dataset
from app.services.data_operations.contracts import CliArgumentInvalid
from app.services.market_workbench import MarketAccessError
from app.services.runtime_health import build_runtime_health
from app.services.product_retirement_runtime_gate import (
    ProductRetirementExecutionService,
    RetirementRuntimeRequest,
)
from app.runtime_scheduler import dry_run_payload


SessionFactory = Callable[[], AbstractContextManager[Any]]
DataVerifier = Callable[..., dict[str, Any]]
RuntimeHealthBuilder = Callable[[Any], dict[str, Any]]
DataCoreRunner = Callable[[str, Any, argparse.Namespace], dict[str, Any]]
RetirementExecutionFactory = Callable[[], Any]


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="guiyi")
    domains = parser.add_subparsers(dest="domain", required=True)

    data = domains.add_parser("data")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    add_data_commands(data_commands)

    runtime = domains.add_parser("runtime")
    runtime_commands = runtime.add_subparsers(
        dest="runtime_command",
        required=True,
    )
    runtime_commands.add_parser("status")
    plan = runtime_commands.add_parser("plan")
    plan.add_argument("--product", choices=("jm",), default="jm")
    plan.add_argument("--poll-seconds", type=_positive_int, default=20)
    retirement = runtime_commands.add_parser("product-retirement")
    retirement_commands = retirement.add_subparsers(
        dest="retirement_command",
        required=True,
    )
    for command in ("plan", "execute", "resume"):
        child = retirement_commands.add_parser(command)
        child.add_argument("--release-tag", required=True)
        child.add_argument("--rollback-tag", required=True)
        child.add_argument("--runtime-root", type=Path, required=True)
        child.add_argument("--protected-root", type=Path, required=True)
        child.add_argument("--active-products-path", type=Path, required=True)
        child.add_argument("--data-root", action="append", required=True)
        if command == "resume":
            child.add_argument("--journal", type=Path, required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    session_factory: SessionFactory = SessionLocal,
    data_verifier: DataVerifier = verify_active_dataset,
    data_core_runner: DataCoreRunner = run_data_core_command,
    runtime_health_builder: RuntimeHealthBuilder = build_runtime_health,
    retirement_execution_factory: RetirementExecutionFactory | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    try:
        reject_legacy_backfill_alias(raw_argv)
        args = build_parser().parse_args(raw_argv)
        _validate_conditional_arguments(args)
    except (CliUsageError, CliArgumentInvalid):
        print_json(argument_error_payload(_command_hint(raw_argv)), stderr)
        return 2

    if is_new_data_operation(args):
        try:
            build_data_operation_request(args)
            with session_factory() as session:
                payload = run_data_operation(args, session=session)
        except (CliUsageError, CliArgumentInvalid):
            print_json(argument_error_payload(_command_hint(raw_argv)), stderr)
            return 2
        except Exception as exc:  # noqa: BLE001 - bounded CLI boundary
            print_json(
                exception_error_payload(
                    command=_command_hint(raw_argv),
                    exc=exc,
                    readonly=not bool(getattr(args, "apply", False)),
                ),
                stderr,
            )
            return 1
        print_json(payload, stdout)
        status = payload.get("status")
        return 0 if status in {"passed", "planned"} else 1

    if (
        args.domain == "data"
        and args.data_command == "verify"
        and args.dataset_kind is not None
    ):
        try:
            with session_factory() as session:
                payload = data_core_runner("verify", session, args)
        except Exception as exc:  # noqa: BLE001 - bounded CLI boundary
            code = getattr(exc, "code", "DATA_CORE_COMMAND_FAILED")
            print_json(
                {
                    "schema_version": 1,
                    "command": "data.verify",
                    "status": "error",
                    "readonly": True,
                    "error": {"code": code, "type": type(exc).__name__},
                },
                stderr,
            )
            return 1
        print_json(payload, stdout)
        return 0 if payload.get("status") in {"passed", "planned"} else 1

    if args.domain == "runtime" and args.runtime_command == "plan":
        scheduler_plan = dry_run_payload(
            args, environ if environ is not None else os.environ
        )
        print_json(
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

    if args.domain == "runtime" and args.runtime_command == "product-retirement":
        try:
            request = RetirementRuntimeRequest(
                release_tag=args.release_tag,
                rollback_tag=args.rollback_tag,
                runtime_root=args.runtime_root,
                protected_root=args.protected_root,
                active_products_path=args.active_products_path,
                roots=_parse_retirement_roots(args.data_root),
            )
            factory = (
                retirement_execution_factory or _default_retirement_execution_service
            )
            executor = factory()
            if args.retirement_command == "plan":
                payload = dict(executor.plan(request))
                print_json(payload, stdout)
                return 0 if payload.get("status") == "planned" else 1
            if args.retirement_command == "execute":
                payload = dict(executor.execute(request))
            else:
                payload = dict(executor.resume(request, journal_path=args.journal))
            print_json(payload, stdout)
            return 0 if payload.get("status") == "completed" else 1
        except (CliUsageError, ValueError):
            print_json(argument_error_payload(_command_hint(raw_argv)), stderr)
            return 2

    if args.domain == "runtime" and args.runtime_command == "status":
        try:
            with session_factory() as session:
                health = runtime_health_builder(session)
        except Exception as exc:  # noqa: BLE001 - never emit health exception text.
            print_json(
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
        print_json(payload, stdout)
        return 0 if health.get("status") == "ok" else 1

    # Retained read-only legacy verify path.
    command = "data.verify"
    if args.domain != "data" or args.data_command != "verify":
        print_json(argument_error_payload(_command_hint(raw_argv)), stderr)
        return 2
    try:
        start = _parse_datetime(args.start, end_of_day=False)
        end = _parse_datetime(args.end, end_of_day=True)
    except ValueError as exc:
        print_json(
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
        print_json(
            exception_error_payload(command=command, exc=exc, readonly=True),
            stderr,
        )
        return 1
    except MarketAccessError as exc:
        print_json(
            exception_error_payload(command=command, exc=exc, readonly=True),
            stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits no exception text.
        print_json(
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
    print_json(payload, stdout)
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


def _validate_conditional_arguments(args: argparse.Namespace) -> None:
    if args.domain != "data":
        return
    if args.data_command in {"download", "aggregate", "live"}:
        if args.symbol is not None and not args.contract_or_series:
            raise CliUsageError("single target requires --contract-or-series")
        return
    if args.data_command != "verify":
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
            raise CliUsageError(
                "canonical verify requires exact JM identity/window/root"
            )
        return
    if not args.contract or not args.period:
        raise CliUsageError("legacy verify requires contract and period")


def _command_hint(argv: Sequence[str]) -> str:
    if len(argv) >= 2 and argv[0] in {"data", "runtime"}:
        return f"{argv[0]}.{argv[1]}"
    if argv:
        return str(argv[0])
    return "guiyi"


def _parse_retirement_roots(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise CliUsageError("retirement data root requires label=path")
        label, value = raw.split("=", maxsplit=1)
        normalized = label.strip().lower()
        path = Path(value).expanduser()
        if normalized in result or not path.is_absolute():
            raise CliUsageError("retirement data root invalid")
        result[normalized] = path
    if set(result) != {"raw", "canonical", "processed"}:
        raise CliUsageError("retirement data root labels invalid")
    return result


class _UnavailableRetirementExecutionService:
    """Expose planning without silently constructing production operators."""

    def __init__(self, service: ProductRetirementExecutionService) -> None:
        self._service = service

    def plan(self, request: RetirementRuntimeRequest) -> Mapping[str, Any]:
        return self._service.plan(request)

    def execute(self, request: RetirementRuntimeRequest) -> Mapping[str, Any]:
        del request
        raise ValueError("PRODUCT_RETIREMENT_EXECUTION_OPERATOR_NOT_CONFIGURED")

    def resume(
        self,
        request: RetirementRuntimeRequest,
        *,
        journal_path: Path,
    ) -> Mapping[str, Any]:
        del request, journal_path
        raise ValueError("PRODUCT_RETIREMENT_EXECUTION_OPERATOR_NOT_CONFIGURED")


def _default_retirement_execution_service() -> _UnavailableRetirementExecutionService:
    def unavailable_inventory(
        _request: RetirementRuntimeRequest, _runtime_sha: str
    ) -> Mapping[str, Any]:
        raise RuntimeError("PRODUCT_RETIREMENT_EXECUTION_OPERATOR_NOT_CONFIGURED")

    return _UnavailableRetirementExecutionService(
        ProductRetirementExecutionService(inventory=unavailable_inventory)
    )


if __name__ == "__main__":
    entrypoint()
