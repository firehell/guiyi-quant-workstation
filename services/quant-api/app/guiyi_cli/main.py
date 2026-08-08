from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any, TextIO
import sys

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
from app.services.data_operations.contracts import CliArgumentInvalid
from app.services.runtime_health import build_runtime_health


SessionFactory = Callable[[], AbstractContextManager[Any]]
RuntimeHealthBuilder = Callable[[Any], dict[str, Any]]
DataCoreRunner = Callable[[str, Any, argparse.Namespace], dict[str, Any]]


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
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    session_factory: SessionFactory = SessionLocal,
    data_core_runner: DataCoreRunner = run_data_core_command,
    runtime_health_builder: RuntimeHealthBuilder = build_runtime_health,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    data_verifier: Any = None,
) -> int:
    del environ, data_verifier  # legacy ActiveDataset verifier retired from CLI
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

    if args.domain == "data" and args.data_command == "verify":
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

    print_json(argument_error_payload(_command_hint(raw_argv)), stderr)
    return 2


def entrypoint() -> None:
    raise SystemExit(main())


def _validate_conditional_arguments(args: argparse.Namespace) -> None:
    if args.domain != "data":
        return
    if args.data_command in {"download", "aggregate"}:
        if args.symbol is not None and not args.contract_or_series:
            raise CliUsageError("single target requires --contract-or-series")
        return
    if args.data_command != "verify":
        return
    required = (
        args.dataset_kind,
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
            "canonical verify requires exact JM DatasetKey identity/window/root"
        )


def _command_hint(argv: Sequence[str]) -> str:
    if len(argv) >= 2 and argv[0] in {"data", "runtime"}:
        return f"{argv[0]}.{argv[1]}"
    if argv:
        return str(argv[0])
    return "guiyi"


if __name__ == "__main__":
    entrypoint()
