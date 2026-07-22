"""从已有 final-audit CSV 组装数据 stage 收口包（只读审计）。

写入边界：只写报告目录下的收口产物；**不写** DB / parquet / manifest，**不调** RQData。
逻辑在 ``app.services.rqdata_ingest.data_stage_closure.build_data_stage_closure_package``。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.rqdata_ingest.data_stage_closure import build_data_stage_closure_package  # noqa: E402


def main() -> None:
    """读取 input-dir 审计 CSV → 输出 stage closure 包路径清单。"""
    parser = argparse.ArgumentParser(description="Build read-only data stage closure audit package from existing final-audit CSVs.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "data_layer_final_audit_phase3_20260712",
        help="Directory containing DATA_LAYER_FINAL_AUDIT outputs such as target_coverage_matrix.csv.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "data_stage_closure",
        help="Directory for data stage closure package outputs.",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    paths = build_data_stage_closure_package(input_dir=args.input_dir, output_dir=args.output_dir, project_root=args.project_root)
    print("Data stage closure package completed")
    print("writes_database=False writes_parquet=False writes_manifest=False calls_rqdata=False")
    print(f"input_dir={args.input_dir}")
    print(f"output_dir={args.output_dir}")
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
