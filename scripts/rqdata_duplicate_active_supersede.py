from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.duplicate_active_supersede import (  # noqa: E402
    build_duplicate_active_supersede_plan,
    write_duplicate_active_supersede_reports,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark duplicate active primary market_data_files as superseded.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "data_layer_phase2_supersede_20260712",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-duplicate-active-supersede", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as session:
        result = build_duplicate_active_supersede_plan(
            session=session,
            apply=args.apply,
            confirm=args.confirm_duplicate_active_supersede,
        )
        if args.apply and result["ready_to_apply"]:
            session.commit()
        else:
            session.rollback()

    outputs = write_duplicate_active_supersede_reports(result, output_dir=args.output_dir)
    print(json.dumps({**{k: v for k, v in result.items() if k != "plan_rows"}, "outputs": {k: str(v) for k, v in outputs.items()}}, indent=2, default=str))

    if args.apply and not result["ready_to_apply"]:
        return 2
    if result["duplicate_group_count"] == 0 and not args.apply:
        print("no duplicate active groups found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
