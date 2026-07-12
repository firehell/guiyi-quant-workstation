from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.data_layer_final_audit import (  # noqa: E402
    DEFAULT_AUDIT_END,
    resolve_git_commit,
    run_extended_final_audit,
    write_final_audit_reports,
)
from app.services.rqdata_ingest.full_universe_active_gate import (  # noqa: E402
    audit_full_universe_active_gate,
    write_stage8_6_reports,
)
from app.services.rqdata_ingest.target_coverage_audit import (  # noqa: E402
    audit_target_coverage,
    load_product_windows,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only data layer final audit orchestrator.")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data" / "universe" / "full_products_90.txt")
    parser.add_argument("--product-windows", type=Path, default=PROJECT_ROOT / "data" / "universe" / "product_1d_start_from_2020.csv")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--audit-end", type=date.fromisoformat, default=DEFAULT_AUDIT_END)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000/api/v1/data")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "reports" / "data_layer_final_audit_20260712",
    )
    args = parser.parse_args()

    products = _products_from_file(args.products_file)
    product_windows = load_product_windows(args.product_windows, products=products)
    git_commit = resolve_git_commit(args.project_root)
    db_snapshot_time = datetime.now(UTC).isoformat()

    target_result, session = _run_target_coverage(
        project_root=args.project_root,
        product_windows=product_windows,
        audit_end=args.audit_end,
        api_base_url=args.api_base_url,
    )

    try:
        stage8_6_1d = audit_full_universe_active_gate(
            session=session,
            project_root=args.project_root,
            products=products,
            profile="stage8_6_1d_first",
        )
        jm_six = audit_full_universe_active_gate(
            session=session,
            project_root=args.project_root,
            products=["jm"],
            profile="jm_main_six_period_latest",
        )
        extended = run_extended_final_audit(
            session=session,
            project_root=args.project_root,
            products=products,
            product_windows=product_windows,
            audit_end=args.audit_end,
            target_coverage_result=target_result,
            stage8_6_1d_result=stage8_6_1d,
            jm_six_period_result=jm_six,
            git_commit=git_commit,
            db_snapshot_time=db_snapshot_time,
        )
    finally:
        if session is not None:
            session.close()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stage8_paths = write_stage8_6_reports(stage8_6_1d, output_dir=output_dir / "stage8_6_1d")
    jm_paths = write_stage8_6_reports(jm_six, output_dir=output_dir / "jm_six_period")
    final_paths = write_final_audit_reports(
        output_dir=output_dir,
        target_coverage_result=target_result,
        extended_result=extended,
    )

    print("Data layer final audit completed")
    print("writes_database=False writes_parquet=False calls_rqdata=False")
    print(f"git_commit={git_commit}")
    print(f"audit_end={args.audit_end.isoformat()}")
    print(f"db_snapshot_source={target_result['db_snapshot_source']}")
    if target_result.get("db_error"):
        print(f"db_error={target_result['db_error']}")
    for name, path in {**stage8_paths, **jm_paths, **final_paths}.items():
        print(f"{name}: {path}")


def _run_target_coverage(
    *,
    project_root: Path,
    product_windows: dict,
    audit_end: date,
    api_base_url: str,
) -> tuple[dict, object | None]:
    db_error = ""
    db_snapshot_source = "database"
    session = None
    try:
        session = SessionLocal()
        result = audit_target_coverage(
            session=session,
            project_root=project_root,
            product_windows=product_windows,
            audit_end=audit_end,
            db_snapshot_source=db_snapshot_source,
        )
        return result, session
    except Exception as exc:  # noqa: BLE001
        if session is not None:
            session.close()
            session = None
        db_error = f"{type(exc).__name__}: {exc}"
        api_coverage, api_quality_reports, api_error = _load_api_snapshot(api_base_url)
        if api_error:
            db_snapshot_source = "manifest_only"
            db_error = f"{db_error}; api_snapshot_error={api_error}"
        else:
            db_snapshot_source = api_base_url
        result = audit_target_coverage(
            session=None,
            project_root=project_root,
            product_windows=product_windows,
            audit_end=audit_end,
            api_coverage=api_coverage,
            api_quality_reports=api_quality_reports,
            db_snapshot_source=db_snapshot_source,
            db_error=db_error,
        )
        return result, None


def _products_from_file(path: Path) -> list[str]:
    return [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _load_api_snapshot(api_base_url: str) -> tuple[list[dict], list[dict], str]:
    try:
        coverage = _get_json(f"{api_base_url.rstrip('/')}/coverage")
        quality_reports = _get_json(f"{api_base_url.rstrip('/')}/quality-reports")
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return [], [], f"{type(exc).__name__}: {exc}"
    return coverage, quality_reports, ""


def _get_json(url: str) -> list[dict]:
    with urlopen(url, timeout=5) as response:  # noqa: S310
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, list):
        raise json.JSONDecodeError("expected list payload", payload, 0)
    return data


if __name__ == "__main__":
    main()
