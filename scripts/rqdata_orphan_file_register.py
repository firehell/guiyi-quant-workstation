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
from app.services.rqdata_ingest.orphan_file_register import (  # noqa: E402
    build_orphan_file_register_plan,
    write_orphan_file_register_reports,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Register orphan canonical parquet files into market_data_files.")
    parser.add_argument("--orphan-csv", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "data_layer_phase2_orphan_register_20260712",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-orphan-register", action="store_true")
    args = parser.parse_args()
    apply = args.apply

    with SessionLocal() as session:
        result = build_orphan_file_register_plan(
            session=session,
            project_root=args.project_root,
            orphan_csv=args.orphan_csv,
            apply=apply,
            confirm=args.confirm_orphan_register,
        )
        if apply and result["ready_to_apply"]:
            session.commit()
        else:
            session.rollback()

    outputs = write_orphan_file_register_reports(result, output_dir=args.output_dir)
    print(json.dumps({**{k: v for k, v in result.items() if k not in {"candidates", "apply_rows"}}, "outputs": {k: str(v) for k, v in outputs.items()}}, indent=2, default=str))
    return 2 if apply and not result["ready_to_apply"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
