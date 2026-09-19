"""Bounded read-only candidate W1 audit for the fixed remaining-19 scope."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys

from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.newow.product_release import REMAINING_WEEKLY_V2_PRODUCTS
from app.market_data.newow.readiness import ReadinessRequest
from app.market_data.newow.readiness_composition import build_newow_readiness
from guiyi_quant.newow.product_contracts import ProductFrequency


def parse_products(values: list[str]) -> tuple[str, ...]:
    products = tuple(value.strip().lower() for value in values)
    if (
        not products
        or len(products) > len(REMAINING_WEEKLY_V2_PRODUCTS)
        or len(set(products)) != len(products)
        or not set(products) <= set(REMAINING_WEEKLY_V2_PRODUCTS)
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
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({
        "status": report["status"],
        "complete": report["complete"],
        "product_count": report["product_count"],
        "main_case_count": report["main_case_count"],
        "main_ready_count": report["main_ready_count"],
        "repair_target_count": len(report["repair_targets"]),
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
