import argparse
from datetime import date, datetime, time
import sys
from typing import Any, Callable, Sequence, TextIO

from app.db.session import SessionLocal
from app.services.core_cli import verify_active_dataset


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Any] = SessionLocal,
    data_verifier: Callable[..., dict[str, Any]] = verify_active_dataset,
    stdout: TextIO = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(prog="guiyi-data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check-bars")
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
                start=_parse_cli_datetime(args.start, end_of_day=False) if args.start else datetime.min,
                end=_parse_cli_datetime(args.end, end_of_day=True) if args.end else datetime.max,
                provider=args.provider,
                profile_id=None,
                access_mode="browser",
                limit=5000,
                legacy_compat=True,
            )
            status = payload["result"]["quality"]
            print(
                f"status={status['status']} "
                f"missing_bars={status['missing_bars']} "
                f"duplicated_bars={status['duplicated_bars']} "
                f"abnormal_price_count={status['abnormal_price_count']} "
                f"abnormal_volume_count={status['abnormal_volume_count']} "
                f"report_count={status['report_count']}",
                file=stdout,
            )
        return 0
    return 2


def entrypoint() -> None:
    raise SystemExit(main())


def _parse_cli_datetime(value: str, end_of_day: bool) -> datetime:
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time.max if end_of_day else time.min)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


if __name__ == "__main__":
    entrypoint()
