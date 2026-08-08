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
    candidate_error_payload,
    exception_error_payload,
    print_json,
)
from app.market_data.composition import (
    CandidateTargetError,
    HistoricalDataTarget,
    build_historical_data_manager,
)
from app.market_data.maintenance import HistoricalDataManager
from app.services.runtime_health import build_runtime_health


SessionFactory = Callable[[], AbstractContextManager[Any]]
ManagerFactory = Callable[[Any], HistoricalDataManager]


def build_parser() -> argparse.ArgumentParser:
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
    raw = list(argv) if argv is not None else sys.argv[1:]
    command = ".".join(raw[:2]) if raw else "guiyi"
    try:
        args = build_parser().parse_args(raw)
        if args.domain == "data":
            build_request(args)
    except (CliUsageError, ValueError):
        print_json(argument_error_payload(command), stderr)
        return 2

    try:
        if args.domain == "data":
            payload = _run_data(args, session_factory, manager_factory)
        else:
            with session_factory() as session:
                health = runtime_health_builder(session)
                payload = {
                    "schema_version": 1,
                    "command": "runtime.status",
                    "status": health.get("status", "failed"),
                    "readonly": True,
                    "runtime": health,
                }
    except CandidateTargetError as exc:
        print_json(
            candidate_error_payload(
                reason_code=exc.code,
                mode=getattr(args, "candidate_mode", None),
                requested_through=getattr(args, "through", None),
            ),
            stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - safe CLI boundary
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
    candidate_root = getattr(args, "candidate_root", None)
    if candidate_root is None:
        with session_factory() as session:
            return run_data_command(args, manager_factory(session)).as_payload()

    if args.data_command not in {"update", "audit"}:
        raise ValueError("CLI_CANDIDATE_ARGUMENT_INVALID")
    if args.data_command == "update":
        target = HistoricalDataTarget.candidate(candidate_root, mode=args.candidate_mode)
    else:
        target = HistoricalDataTarget.candidate(candidate_root, mode="extend")
    with target.open_session() as session:
        identity = None
        if args.data_command == "update":
            request = build_request(args)
            assert request.through is not None
            identity = target.validate_update(session, request.through)
        else:
            target.validate_audit(session)
        result = run_data_command(args, target.build_manager(session))
        if (
            args.data_command == "update"
            and bool(args.apply)
            and result.status in {"passed", "noop"}
            and identity is not None
        ):
            assert result.through is not None
            target.record_through(result.through, identity)
        return result.as_payload()


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
