"""为单品种写出 dominant v2 raw/standard Parquet（不默认注册 DB）。

CLI：``--product`` + ``--end-date`` → ``build_dominant_v2_parquet_assets`` → 落 summary JSON。
算法在 ``app.services.rqdata_ingest.dominant_v2_parquet``。
仅聚合周期（5m/15m/30m/60m/1d）时可跳过 RQData client；``--force`` 允许覆盖已有输出。
注册请另跑 ``rqdata_dominant_v2_register_quality.py``。
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402

from app.models.data_center import Instrument  # noqa: E402
from app.services.rqdata_ingest.client import RqDataClient  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_parquet import FORMAL_START, PERIODS, build_dominant_v2_parquet_assets  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write dominant v2 raw and standard parquet assets for one product.")
    parser.add_argument("--product", required=True)
    parser.add_argument("--exchange", default=None, help="Optional exchange override; otherwise read from Instrument table or fallback DCE.")
    parser.add_argument("--start-date", type=date.fromisoformat, default=FORMAL_START)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--summary-path", type=Path, default=None)
    parser.add_argument("--period", action="append", choices=PERIODS, dest="periods")
    parser.add_argument("--force", action="store_true", help="Allow replacing existing dominant v2 parquet outputs.")
    return parser.parse_args(argv)


def resolve_exchange(product: str, override: str | None) -> str:
    """交易所覆盖 → Instrument 表 → 默认 DCE。"""
    if override:
        return override.upper()
    try:
        from app.db.session import SessionLocal

        with SessionLocal() as session:
            instrument = session.scalar(select(Instrument).where(Instrument.symbol == product.strip().lower()))
            if instrument is not None and instrument.exchange_code:
                return str(instrument.exchange_code).upper()
    except Exception:
        pass
    return "DCE"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    product = args.product.strip().lower()
    exchange = resolve_exchange(product, args.exchange)
    periods = tuple(args.periods) if args.periods else PERIODS
    client = None if periods and all(period in {"5m", "15m", "30m", "60m", "1d"} for period in periods) else RqDataClient(load_env_file=True)
    summary = build_dominant_v2_parquet_assets(
        client=client,
        output_root=args.output_root,
        product=product,
        exchange=exchange,
        start_date=args.start_date,
        end_date=args.end_date,
        periods=periods,
        force=args.force,
    )
    summary_path = args.summary_path or args.output_root / "processed" / "v1b" / product / f"{product}_v2_parquet_{args.start_date:%Y%m%d}_{args.end_date:%Y%m%d}.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"product": product, "exchange": exchange, "summary_path": str(summary_path), "periods": list(summary["periods"].keys())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
