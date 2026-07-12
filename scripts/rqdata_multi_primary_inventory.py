from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import MarketDataFile  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Export readonly multi-primary market_data_files inventory.")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/reports/multi_primary_inventory_latest")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        rows = session.execute(
            select(
                MarketDataFile.instrument_symbol,
                MarketDataFile.contract_code,
                MarketDataFile.period,
                func.count(MarketDataFile.id),
            )
            .where(
                MarketDataFile.data_role == "primary",
                MarketDataFile.quality_status != "failed",
                MarketDataFile.provider == "rqdata",
            )
            .group_by(MarketDataFile.instrument_symbol, MarketDataFile.contract_code, MarketDataFile.period)
            .having(func.count(MarketDataFile.id) > 1)
            .order_by(MarketDataFile.instrument_symbol, MarketDataFile.contract_code, MarketDataFile.period)
        ).all()

    frame = pd.DataFrame(rows, columns=["instrument_symbol", "contract_code", "period", "primary_count"])
    output = args.output_dir / "multi_primary_inventory.csv"
    frame.to_csv(output, index=False)
    summary = args.output_dir / "MULTI_PRIMARY_INVENTORY.md"
    summary.write_text(
        "\n".join(
            [
                "# Multi Primary Inventory",
                "",
                f"- combinations: {len(frame)}",
                f"- output: `{output}`",
                "- readonly export only; no DB writes",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"combinations={len(frame)}")
    print(f"output={output}")


if __name__ == "__main__":
    main()
