#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import PROJECT_ROOT as APP_PROJECT_ROOT, SessionLocal  # noqa: E402
from app.services.profile_binding_candidate_generator import DEFAULT_PROFILE_IDS, load_products_file  # noqa: E402
from app.services.profile_binding_rollout import (  # noqa: E402
    run_apply_mode,
    run_dry_run_mode,
    run_generate_mode,
    run_rollback_batch_mode,
    run_verify_mode,
)


def _parse_profiles(value: str) -> list[str]:
    if value == "all":
        return list(DEFAULT_PROFILE_IDS)
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_products(value: str | None, products_file: Path | None) -> set[str]:
    if value:
        return {item.strip().lower() for item in value.split(",") if item.strip()}
    if products_file:
        return load_products_file(products_file)
    return set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile binding rollout: generate / dry-run / apply / verify / rollback.")
    parser.add_argument(
        "--mode",
        choices=["generate", "dry-run", "apply", "verify", "rollback-batch"],
        required=True,
    )
    parser.add_argument("--profiles", default="all", help="Comma-separated profile ids or 'all'.")
    parser.add_argument("--products", default="", help="Comma-separated product symbols.")
    parser.add_argument("--products-file", type=Path, default=PROJECT_ROOT / "data/universe/full_products_90.txt")
    parser.add_argument(
        "--sealing-dir",
        type=Path,
        default=PROJECT_ROOT / "data/reports/data_sealing_audit_20260712_162941",
    )
    parser.add_argument(
        "--multi-primary-csv",
        type=Path,
        default=PROJECT_ROOT / "data/reports/multi_primary_inventory_latest/multi_primary_inventory.csv",
    )
    parser.add_argument(
        "--residual-dir",
        type=Path,
        default=PROJECT_ROOT / "data/reports/residual_root_cause_audit_20260712",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data/reports/profile_binding_rollout_latest",
    )
    parser.add_argument("--batch-id", default="", help="Apply / verify / rollback batch id.")
    parser.add_argument(
        "--candidates-path",
        type=Path,
        default=None,
        help="Override binding_candidates.csv path (defaults to output-dir/binding_candidates.csv).",
    )
    parser.add_argument("--commit", action="store_true", help="Commit DB writes for apply/rollback.")
    args = parser.parse_args()

    profile_ids = _parse_profiles(args.profiles)
    products = _parse_products(args.products or None, args.products_file)
    candidates_path = args.candidates_path or (args.output_dir / "binding_candidates.csv")

    with SessionLocal() as session:
        if args.mode == "generate":
            result = run_generate_mode(
                session,
                profile_ids=profile_ids,
                products_file=args.products_file,
                sealing_dir=args.sealing_dir,
                project_root=APP_PROJECT_ROOT,
                output_dir=args.output_dir,
                multi_primary_csv=args.multi_primary_csv,
                residual_dir=args.residual_dir,
            )
        elif args.mode == "dry-run":
            result = run_dry_run_mode(
                session,
                profile_ids=profile_ids,
                products=products,
                candidates_path=candidates_path,
                project_root=APP_PROJECT_ROOT,
            )
        elif args.mode == "apply":
            if not args.batch_id:
                parser.error("--batch-id is required for apply mode")
            result = run_apply_mode(
                session,
                profile_ids=profile_ids,
                products=products,
                candidates_path=candidates_path,
                output_dir=args.output_dir,
                batch_id=args.batch_id,
                project_root=APP_PROJECT_ROOT,
                commit=args.commit,
            )
        elif args.mode == "verify":
            result = run_verify_mode(
                session,
                output_dir=args.output_dir,
                batch_id=args.batch_id or None,
                candidates_path=candidates_path,
                project_root=APP_PROJECT_ROOT,
            )
        else:
            if not args.batch_id:
                parser.error("--batch-id is required for rollback-batch mode")
            result = run_rollback_batch_mode(
                session,
                output_dir=args.output_dir,
                batch_id=args.batch_id,
                commit=args.commit,
            )

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
