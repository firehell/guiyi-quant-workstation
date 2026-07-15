from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import MarketDataFile  # noqa: E402
from app.services.rqdata_ingest.residual_root_cause_audit import run_residual_root_cause_audit  # noqa: E402
from app.services.rqdata_ingest.weekly_row_count_reconcile import DbMarketFileSnapshot  # noqa: E402


def _load_db_rows() -> tuple[str, list[DbMarketFileSnapshot]]:
    try:
        with SessionLocal() as session:
            rows = session.scalars(select(MarketDataFile)).all()
            snapshots = [
                DbMarketFileSnapshot(
                    id=row.id,
                    file_path=row.file_path,
                    row_count=row.row_count,
                    start_time=row.start_time.isoformat() if row.start_time else "",
                    end_time=row.end_time.isoformat() if row.end_time else "",
                    checksum=row.checksum or "",
                    data_role=row.data_role,
                    quality_status=row.quality_status,
                    data_version=row.data_version,
                )
                for row in rows
            ]
            return "available", snapshots
    except Exception as exc:  # noqa: BLE001
        return "unavailable", []


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only residual root cause audit for A1 sealing anomalies.")
    parser.add_argument(
        "--sealing-dir",
        type=Path,
        default=PROJECT_ROOT / "data/reports/data_sealing_audit_20260712_162941",
    )
    parser.add_argument(
        "--multi-primary",
        type=Path,
        default=PROJECT_ROOT / "data/reports/multi_primary_inventory_latest/multi_primary_inventory.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/reports/residual_root_cause_audit_20260712")
    parser.add_argument("--require-direct-db", action="store_true")
    args = parser.parse_args()

    db_status, db_rows = _load_db_rows()
    if args.require_direct_db and db_status != "available":
        raise SystemExit("require-direct-db set but database is unavailable")

    result = run_residual_root_cause_audit(
        project_root=PROJECT_ROOT,
        sealing_dir=args.sealing_dir,
        output_dir=args.output_dir,
        multi_primary_csv=args.multi_primary,
        db_rows=db_rows if db_status == "available" else None,
        db_status=db_status,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
