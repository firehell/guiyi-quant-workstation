from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


SENSITIVE_ENV_NAMES = (
    "RQDATAC2_CONF",
    "RQDATAC_CONF",
    "RQDATA_LICENSE_KEY",
    "RQDATA_USERNAME",
    "RQDATA_PASSWORD",
    "RQDATA_ADDR",
    "QYWX_WEBHOOK_URL",
)


def credential_presence(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = environ if environ is not None else os.environ
    return {name: "present" if source.get(name) else "missing" for name in SENSITIVE_ENV_NAMES}


def redact_message(message: Any, environ: Mapping[str, str] | None = None) -> str:
    text = "" if message is None else str(message)
    source = environ if environ is not None else os.environ
    for name in SENSITIVE_ENV_NAMES:
        value = source.get(name)
        if value:
            text = text.replace(value, "[REDACTED]")
    return text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RQData live 1m minimal ingest. Defaults are scoped to one safe poll.")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--exchange", default=None)
    parser.add_argument("--lookback-minutes", type=int, default=10)
    parser.add_argument("--once", action="store_true", help="Run exactly one ingest poll; long-running scheduler is intentionally unsupported in 4B.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned ingest target without constructing DB sessions or writing data.")
    parser.add_argument("--json", action="store_true", help="Print JSON output. The script also uses JSON by default for easy GPT handoff.")
    return parser.parse_args(argv)


def dry_run_payload(args: argparse.Namespace, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {
        "mode": "dry-run",
        "provider": "rqdata",
        "source_mode": "poll_get_price_1m",
        "contract_code": args.contract.upper(),
        "instrument_symbol": args.symbol.lower(),
        "exchange_code": args.exchange.upper() if args.exchange else None,
        "period": "1m",
        "lookback_minutes": max(1, args.lookback_minutes),
        "would_construct_rqdata_client": False,
        "would_open_database_session": False,
        "would_write_database": False,
        "would_write_parquet": False,
        "would_trigger_strategy": False,
        "would_send_wechat": False,
        "row_count": 0,
        "min_bar_datetime": None,
        "max_bar_datetime": None,
        "max_trading_day": None,
        "would_upsert_count": 0,
        "would_skip_count": 0,
        "credential_presence": credential_presence(environ),
    }


def main(
    argv: list[str] | None = None,
    *,
    client_factory: Callable[[], Any] | None = None,
    session_factory: Callable[[], Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = parse_args(argv)
    source_env = environ if environ is not None else os.environ
    if args.dry_run:
        print(json.dumps(dry_run_payload(args, source_env), ensure_ascii=False, indent=2, default=str))
        return 0
    if not args.once:
        print(
            json.dumps(
                {
                    "mode": "rejected",
                    "status": "failed",
                    "error_type": "UnsupportedLongRunningMode",
                    "error_message": "LIVE-1M-4B only supports --once; scheduler/daemon mode is out of scope.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    try:
        from app.db.session import SessionLocal
        from app.services.live_1m_ingest import LiveIngestConfig, LiveMinuteIngestService
        from app.services.rqdata_ingest.client import RqDataClient

        make_client = client_factory or (lambda: RqDataClient(load_env_file=True))
        make_session = session_factory or SessionLocal
        client = make_client()
        with make_session() as session:
            service = LiveMinuteIngestService(session=session, client=client)
            result = service.poll_once(
                LiveIngestConfig(
                    contract=args.contract,
                    symbol=args.symbol,
                    exchange=args.exchange,
                    lookback_minutes=args.lookback_minutes,
                ),
                dry_run=False,
            )
            session.commit()
        print(json.dumps({"mode": "once", "status": "ok", **result.to_dict()}, ensure_ascii=False, indent=2, default=str))
        return 0 if result.error_type is None else 1
    except Exception as exc:  # noqa: BLE001 - CLI must return a redacted structured failure.
        print(
            json.dumps(
                {
                    "mode": "once",
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": redact_message(exc, source_env),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
