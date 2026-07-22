"""将已确认的 live 1m 聚合为 live 多周期 bars（5m…1w）。

CLI：``--contract`` + ``--symbol``；``--dry-run`` 不打开 DB、不写 parquet。
聚合逻辑在 ``app.services.live_multi_tf_aggregation``。仅支持 ``--once``，不启守护进程。
"""

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
    """只报告敏感环境变量是否存在，不回显值。"""
    source = environ if environ is not None else os.environ
    return {name: "present" if source.get(name) else "missing" for name in SENSITIVE_ENV_NAMES}


def redact_message(message: Any, environ: Mapping[str, str] | None = None) -> str:
    """脱敏错误信息中的凭据明文。"""
    text = "" if message is None else str(message)
    source = environ if environ is not None else os.environ
    for name in SENSITIVE_ENV_NAMES:
        value = source.get(name)
        if value:
            text = text.replace(value, "[REDACTED]")
    return text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate confirmed live 1m rows into live multi-timeframe bars.")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--exchange", default=None)
    parser.add_argument(
        "--periods",
        default="5m,15m,30m,60m,1d,1w",
        help="Comma-separated target periods. Supported: 5m,15m,30m,60m,1d,1w.",
    )
    parser.add_argument("--once", action="store_true", help="Run exactly one aggregation pass; scheduler/daemon mode is intentionally unsupported.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned aggregation target without opening DB sessions or writing data.")
    parser.add_argument("--json", action="store_true", help="Print JSON output. The script also uses JSON by default for easy GPT handoff.")
    return parser.parse_args(argv)


def parse_periods(value: str) -> tuple[str, ...]:
    return tuple(period.strip().lower() for period in value.split(",") if period.strip())


def dry_run_payload(args: argparse.Namespace, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """dry-run 计划载荷：声明不会写库/写文件/触发策略或微信。"""
    return {
        "mode": "dry-run",
        "provider": "rqdata",
        "source_mode": "live_1m_sequential_bucket",
        "source_period": "1m",
        "contract_code": args.contract.upper(),
        "instrument_symbol": args.symbol.lower(),
        "exchange_code": args.exchange.upper() if args.exchange else None,
        "periods": list(parse_periods(args.periods)),
        "would_open_database_session": False,
        "would_write_database": False,
        "would_write_parquet": False,
        "would_register_market_data_files": False,
        "would_trigger_strategy": False,
        "would_run_backtest": False,
        "would_send_wechat": False,
        "credential_presence": credential_presence(environ),
    }


def main(
    argv: list[str] | None = None,
    *,
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
                    "error_message": "LIVE-1M-5 only supports --once; scheduler/daemon mode is out of scope.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    try:
        from app.db.session import SessionLocal
        from app.services.live_multi_tf_aggregation import LiveAggregationConfig, LiveMultiTfAggregationService

        make_session = session_factory or SessionLocal
        with make_session() as session:
            service = LiveMultiTfAggregationService(session=session)
            result = service.aggregate_once(
                LiveAggregationConfig(
                    contract=args.contract,
                    symbol=args.symbol,
                    exchange=args.exchange,
                    periods=parse_periods(args.periods),
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
