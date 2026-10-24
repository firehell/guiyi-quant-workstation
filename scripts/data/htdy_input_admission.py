"""Persist one exclusive read-only admission snapshot using configured services.

Run with the project's API/core PYTHONPATH and securely configured environment.
No provider is created; output files are diagnostics, never market publications.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path

from app.market_data.htdy_input_admission import audit_product, safe_error, summarize
from app.market_data.operational_universe import load_operational_products


def run(output: Path, *, at: datetime, products: tuple[str, ...]) -> dict:
    universe = load_operational_products()
    if (not products or len(set(products)) != len(products) or not set(products) <= set(universe)
            or at.tzinfo is None or at.utcoffset() is None or at > datetime.now(UTC)):
        raise ValueError("HTDY_ADMISSION_SCOPE_INVALID")
    # Import configuration-dependent services only after argument validation.
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_database_coverage_source, build_market_read_service
    from app.redis_connections import get_redis_connection

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for product in products:
        redis = get_redis_connection()
        try:
            with SessionLocal() as session, readonly_transaction(session, timeout_seconds=180):
                market = build_market_read_service(session, redis=redis)
                coverage = build_database_coverage_source(session, reuse_session_windows=True)
                market._market_data.replay_coverage = coverage
                row = audit_product(market, coverage, product, at)
        except Exception as error:
            row = {
                "product": product, "at": at, "readonly": True, "status": "BLOCKED",
                "history": {"status": "UNVERIFIED"}, "live": {"status": "UNVERIFIED"},
                "calculation_input": {"status": "UNVERIFIED"},
                "future_signal": {"status": "BLOCKED", "eligible_now": False, "first_seen_proven": False},
                "provider_requests": 0, "production_writes": 0, "errors": safe_error(error),
            }
        finally:
            redis.close()
        with (output / f"{product}.json").open("x", encoding="utf-8") as target:
            json.dump(row, target, ensure_ascii=False, sort_keys=True, default=str)
        rows.append(row)
        print(json.dumps({"product": product, "status": row["status"]}), flush=True)
    report = summarize(rows, at)
    with (output / "summary.json").open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, sort_keys=True, default=str)
    columns = ("product", "status", "history", "calculation_input", "live", "missing_m1", "missing_h1", "future_signal")
    with (output / "admission.csv").open("x", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "product": row["product"], "status": row["status"],
                "history": row["history"]["status"], "live": row["live"]["status"],
                "calculation_input": row["calculation_input"]["status"],
                "missing_m1": row["live"].get("source_1m", {}).get("missing_count"),
                "missing_h1": row["live"].get("h1", {}).get("missing_count"),
                "future_signal": row["future_signal"]["status"],
            })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of")
    parser.add_argument("--products", nargs="+")
    args = parser.parse_args()
    try:
        at = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(UTC)
        report = run(args.output, at=at, products=tuple(args.products or load_operational_products()))
    except Exception as error:
        print(json.dumps({"status": "AUDIT_STOPPED", "errors": safe_error(error)}), flush=True)
        return 1
    print(json.dumps({"counts": report["counts"], "first_seen_proven": False}), flush=True)
    return 0 if all(row["status"] == "INPUTS_VERIFIED_WAIT_NEW_OBSERVATION"
                    for row in report["rows"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
