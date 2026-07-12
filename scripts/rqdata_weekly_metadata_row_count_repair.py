from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import select


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import MarketDataFile  # noqa: E402
from app.services.rqdata_ingest.weekly_metadata_row_count_repair import (  # noqa: E402
    CONFIRM_FLAG,
    apply_weekly_metadata_row_count_repair,
    build_weekly_metadata_row_count_repair_plan,
    write_weekly_metadata_row_count_repair_reports,
)
from app.services.rqdata_ingest.weekly_row_count_reconcile import DbMarketFileSnapshot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled DB metadata row-count repair for AD/EC/OP 20260707 weekly assets.")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "reports" / "ad_ec_op_weekly_metadata_repair_20260712")
    parser.add_argument("--apply", action="store_true", help=f"Apply the controlled DB row_count update. Requires {CONFIRM_FLAG}.")
    parser.add_argument(
        "--confirm-ad-ec-op-weekly-row-count-repair",
        action="store_true",
        help="Required confirmation for the controlled three-row DB metadata repair.",
    )
    args = parser.parse_args()

    confirm = args.confirm_ad_ec_op_weekly_row_count_repair
    db_status, db_error_type, db_rows = _load_db_rows()
    plan = build_weekly_metadata_row_count_repair_plan(
        project_root=PROJECT_ROOT,
        output_dir=args.output_dir,
        db_status=db_status,
        db_error_type=db_error_type,
        db_rows=db_rows,
        apply=args.apply,
        confirm=confirm,
    )

    result = plan
    if args.apply and plan["ready_to_apply"]:
        with SessionLocal() as session:
            result = apply_weekly_metadata_row_count_repair(session=session, plan=plan)
            if result["writes_database"]:
                session.commit()
            else:
                session.rollback()

    outputs = write_weekly_metadata_row_count_repair_reports(result, output_dir=args.output_dir)
    print("Weekly metadata row-count repair completed")
    print(f"operation={result['operation']}")
    print(f"writes_database={result['writes_database']} writes_parquet=False calls_rqdata=False")
    print(f"db_status={result['db_status']}")
    print(f"ready_to_apply={result['ready_to_apply']}")
    if result["db_error_type"]:
        print(f"db_error_type={result['db_error_type']}")
    if result["blocked_reasons"]:
        print(f"blocked_reasons={','.join(result['blocked_reasons'])}")
    for name, path in outputs.items():
        print(f"{name}: {path}")


def _load_db_rows() -> tuple[str, str, list[DbMarketFileSnapshot]]:
    try:
        with SessionLocal() as session:
            rows = list(
                session.scalars(
                    select(MarketDataFile).where(
                        MarketDataFile.provider == "rqdata",
                        MarketDataFile.data_type == "bars",
                        MarketDataFile.period == "1w",
                        MarketDataFile.instrument_symbol.in_(["ad", "ec", "op"]),
                    )
                )
            )
    except Exception as exc:  # noqa: BLE001 - dry-run reports DB availability without leaking secrets.
        return "unavailable", type(exc).__name__, []
    return "available", "", [_snapshot(row) for row in rows]


def _snapshot(row: MarketDataFile) -> DbMarketFileSnapshot:
    return DbMarketFileSnapshot(
        id=row.id,
        file_path=row.file_path,
        row_count=row.row_count,
        start_time="" if row.start_time is None else row.start_time.isoformat(),
        end_time="" if row.end_time is None else row.end_time.isoformat(),
        checksum=row.checksum or "",
        data_role=row.data_role,
        quality_status=row.quality_status,
        data_version=row.data_version or "",
    )


if __name__ == "__main__":
    main()
