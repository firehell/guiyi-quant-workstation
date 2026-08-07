"""Deprecated ``guiyi-data`` entrypoint.

Use ``guiyi data verify`` instead. This thin wrapper remains for one deprecation
window and only exposes check-bars compatibility.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time
import sys
from typing import Any, Callable, Sequence, TextIO

from app.db.session import SessionLocal
from app.services.core_cli import verify_active_dataset


_DEPRECATION = (
    "guiyi-data is deprecated; use `guiyi data verify` "
    "(uv run --project services/quant-api guiyi data verify ...)."
)


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Any] = SessionLocal,
    data_verifier: Callable[..., dict[str, Any]] = verify_active_dataset,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    print(_DEPRECATION, file=stderr)
    parser = argparse.ArgumentParser(
        prog="guiyi-data",
        description=_DEPRECATION,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check-bars",
        help="Deprecated alias of `guiyi data verify`",
    )
    check_parser.add_argument("--symbol", required=True)
    check_parser.add_argument("--contract", required=True)
    check_parser.add_argument("--period", required=True)
    check_parser.add_argument("--start")
    check_parser.add_argument("--end")
    check_parser.add_argument("--provider")

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "check-bars":
        with session_factory() as session:
            payload = data_verifier(
                session,
                symbol=args.symbol,
                contract=args.contract,
                period=args.period,
                start=_parse_cli_datetime(args.start, end_of_day=False)
                if args.start
                else None,
                end=_parse_cli_datetime(args.end, end_of_day=True)
                if args.end
                else None,
                provider=args.provider,
                profile_id=None,
                access_mode="canonical",
                limit=5000,
                legacy_compat=True,
            )
            quality = payload["result"].get("quality") or {}
            print(
                f"status={payload['status']} "
                f"quality_status={quality.get('status')} "
                f"response_bar_count={payload['result'].get('response_bar_count')} "
                f"selection_mode={payload['result'].get('selection_mode')}",
                file=stdout,
            )
        return 0
    return 2


def entrypoint() -> None:
    raise SystemExit(main())


def _parse_cli_datetime(value: str, end_of_day: bool) -> datetime:
    if len(value) == 10:
        return datetime.combine(
            date.fromisoformat(value), time.max if end_of_day else time.min
        )
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


if __name__ == "__main__":
    entrypoint()
