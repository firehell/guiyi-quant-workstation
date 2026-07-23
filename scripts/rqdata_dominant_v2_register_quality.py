"""将 dominant v2 Parquet 质量元数据注册到 DB / manifest。

CLI：``--summary-path`` 或 ``--product``+``--end-date`` 定位 summary → ``register_dominant_v2_quality`` → commit。
写入边界：会改 PostgreSQL 与 manifest；``--allow-quality-failed`` 允许 OHLC 失败以 warning 入库。
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

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_register import register_dominant_v2_quality  # noqa: E402
from app.services.rqdata_ingest.dominant_v2_parquet import FORMAL_START  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register dominant v2 parquet quality metadata in DB and manifest.")
    parser.add_argument("--product", default=None)
    parser.add_argument("--start-date", type=date.fromisoformat, default=FORMAL_START)
    parser.add_argument("--end-date", type=date.fromisoformat, default=None)
    parser.add_argument("--summary-path", type=Path, default=None)
    parser.add_argument("--manifest-path", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument(
        "--allow-quality-failed",
        action="store_true",
        help="Register RQData bars even when OHLC quality checks fail (stored as warning).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.summary_path is None:
        if not args.product or args.end_date is None:
            raise SystemExit("Provide --summary-path or both --product and --end-date")
        product = args.product.strip().lower()
        summary_path = args.output_root / "processed" / "v1b" / product / f"{product}_v2_parquet_{args.start_date:%Y%m%d}_{args.end_date:%Y%m%d}.json"
    else:
        summary_path = args.summary_path
    with SessionLocal() as session:
        result = register_dominant_v2_quality(
            session=session,
            summary_path=summary_path,
            manifest_path=args.manifest_path,
            allow_quality_failed=args.allow_quality_failed,
        )
        session.commit()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
