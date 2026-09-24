"""Bounded read-only W1 audit for the fixed weekly-v2 product group."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.newow.product_release import FORMAL_WEEKLY_V2_PRODUCTS
from app.market_data.newow.readiness import ReadinessRequest
from app.market_data.newow.readiness_composition import build_newow_readiness
from guiyi_quant.newow.product_contracts import ProductFrequency


def proposed_unit_batches(
    report: dict[str, object],
) -> tuple[tuple[dict[str, str], ...], ...]:
    targets = report.get("repair_targets")
    if not isinstance(targets, list):
        raise ValueError("REMAINING19_REPAIR_TARGETS_INVALID")
    units: list[dict[str, str]] = []
    for target in targets:
        if not isinstance(target, dict) or target.get("status") != "PROPOSED":
            continue
        values = {
            "symbol": target.get("symbol"),
            "contract": target.get("contract"),
            "through": target.get("through"),
            "frequency": target.get("frequency"),
            "expected_plan_sha256": target.get("plan_sha256"),
        }
        if (
            any(not isinstance(item, str) for item in values.values())
            or values["frequency"] != "1w"
            or len(values["expected_plan_sha256"]) != 64
        ):
            raise ValueError("REMAINING19_REPAIR_TARGETS_INVALID")
        units.append({key: str(item) for key, item in values.items()})
    return tuple(
        tuple(units[index:index + 20])
        for index in range(0, len(units), 20)
    )


def parse_products(values: list[str]) -> tuple[str, ...]:
    products = tuple(value.strip().lower() for value in values)
    if (
        not products
        or len(products) > len(FORMAL_WEEKLY_V2_PRODUCTS)
        or len(set(products)) != len(products)
        or not set(products) <= set(FORMAL_WEEKLY_V2_PRODUCTS)
    ):
        raise ValueError("REMAINING19_SCOPE_INVALID")
    return products


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(allow_abbrev=False)
    value.add_argument("--product", action="append", required=True)
    value.add_argument("--as-of", required=True)
    value.add_argument("--output", required=True)
    value.add_argument("--matrix", action="store_true")
    value.add_argument("--consumer-only", action="store_true")
    value.add_argument("--units-output-root")
    value.add_argument("--max-work", type=int, default=100000)
    value.add_argument("--timeout-seconds", type=int, default=600)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    products = parse_products(args.product)
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("REMAINING19_CUTOFF_INVALID")
    as_of = as_of.astimezone(UTC)
    request = ReadinessRequest(
        products=products,
        as_of=as_of,
        matrix=bool(args.matrix),
        max_work=args.max_work,
        timeout_seconds=args.timeout_seconds,
        frequencies=(ProductFrequency.WEEKLY,),
        candidate_weekly=True,
        consumer_only=bool(args.consumer_only),
    )
    with SessionLocal() as session, readonly_transaction(
        session, timeout_seconds=args.timeout_seconds,
    ):
        before = catalog_revision(session, products, as_of.date(), ("1d", "1w"))
        report = build_newow_readiness(session, request=request)
        after = catalog_revision(session, products, as_of.date(), ("1d", "1w"))
    code_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True,
        cwd=Path(__file__).resolve().parents[1],
    ).strip()
    report["audit_identity"] = {
        "code_sha": code_sha,
        "input_quality_policy": "newow_weekly_input_quality_v2",
        "catalog_revision_before": before,
        "catalog_revision_after": after,
        "catalog_revision_stable": before == after,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report_bytes = (
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    ).encode()
    output.write_bytes(report_bytes)
    batches = proposed_unit_batches(report)
    unit_index = None
    if args.units_output_root:
        unit_root = Path(args.units_output_root)
        unit_root.mkdir(parents=True, exist_ok=True)
        entries = []
        for index, batch in enumerate(batches, start=1):
            path = unit_root / f"units-{index:03d}.json"
            content = (json.dumps(batch, ensure_ascii=False, indent=2) + "\n").encode()
            path.write_bytes(content)
            entries.append({
                "path": str(path),
                "sha256": hashlib.sha256(content).hexdigest(),
                "unit_count": len(batch),
            })
        unit_index = unit_root / "units-index.json"
        unit_index.write_text(json.dumps({
            "schema_version": "newow_remaining19_prepare_units_v1",
            "report_path": str(output),
            "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "batch_count": len(entries),
            "unit_count": sum(item["unit_count"] for item in entries),
            "batches": entries,
        }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "status": report["status"],
        "complete": report["complete"],
        "product_count": report["product_count"],
        "main_case_count": report["main_case_count"],
        "main_ready_count": report["main_ready_count"],
        "repair_target_count": len(report["repair_targets"]),
        "proposed_unit_count": sum(len(batch) for batch in batches),
        "unit_batch_count": len(batches),
        "units_index": None if unit_index is None else str(unit_index),
        "provider_requests": report["provider_requests"],
        "writes": report["writes"],
        "catalog_revision_stable": before == after,
    }))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({
            "status": "blocked", "error_type": type(exc).__name__,
            "provider_requests": 0, "writes": 0,
        }), file=sys.stderr)
        raise SystemExit(1)
