#!/usr/bin/env python3
"""Read-only, bounded P9 historical source plans for an explicit product batch."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from time import monotonic

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.market_data.newow.product_release import CAPABILITY_SCHEMA_VERSION, OPEN_WEEKLY_PRODUCTS
from app.market_data.operational_universe import load_active_products, load_operational_products
from app.market_data.market_data_service import MarketDataError
from app.reference_trading.composition import open_historical_reference_components
from app.reference_trading.planning import (
    HistoricalReferenceRequest, HistoricalStreamRequest, WorkBudget,
)
from guiyi_quant.reference_trading import RecordingMode, StreamIdentity

from scripts.reference_trading_p9_manifest import ROOT, enumerate_scope, write_new_manifest


def _exact_checkout(expected_sha: str) -> str:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if expected_sha != commit or len(commit) != 40:
        raise ValueError("P9_CODE_IDENTITY_MISMATCH")
    if subprocess.check_output(
        ["git", "-c", "core.fsmonitor=false", "status", "--porcelain=v1"],
        cwd=ROOT, text=True,
    ).strip():
        raise ValueError("P9_CHECKOUT_DIRTY")
    return commit


def _formal_requests(
    rows: list[dict[str, object]], products: tuple[str, ...],
    since: date, through: date, as_of: datetime,
) -> tuple[HistoricalStreamRequest, ...]:
    selected = []
    for row in rows:
        if (
            row["gate"] != "FORMAL_CANDIDATE"
            or row["recording_mode"] != "historical_replay"
            or str(row["product"]).upper() not in products
        ):
            continue
        selected.append(HistoricalStreamRequest(StreamIdentity(
            strategy_code=row["strategy_code"],
            formula_versions=tuple(row["formula_versions"]),
            profile_id=row["profile_id"],
            reference_model_version=row["reference_model_version"],
            futures_adaptation_version=row["futures_adaptation_version"],
            product=row["product"], frequency=row["frequency"],
            series_kind="actual_dominant", recording_mode=RecordingMode.HISTORICAL_REPLAY,
            observation_policy_version=None,
        ), since, through, as_of))
    if {request.identity.product.upper() for request in selected} != set(products):
        raise ValueError("P9_PRODUCT_SCOPE_INVALID")
    return tuple(selected)


def plan_batch(
    requests: tuple[HistoricalStreamRequest, ...], *, operation: str,
    max_streams: int, max_total_bars: int, max_total_bytes: int,
    max_total_seconds: int, max_stream_bars: int, max_stream_bytes: int,
    max_stream_seconds: int, planner_context,
    clock=monotonic,
) -> dict[str, object]:
    if not requests or len(requests) > max_streams or max_streams > 60:
        raise ValueError("P9_STREAM_BUDGET_INVALID")
    if any(type(value) is not int or value <= 0 for value in (
        max_total_bars, max_total_bytes, max_total_seconds,
        max_stream_bars, max_stream_bytes, max_stream_seconds,
    )):
        raise ValueError("P9_WORK_BUDGET_INVALID")
    if len({request.identity.stream_id for request in requests}) != len(requests):
        raise ValueError("P9_STREAM_SCOPE_DUPLICATE")
    deadline = clock() + max_total_seconds
    used_bars = used_bytes = 0
    results: list[dict[str, object]] = []
    for stream_request in requests:
        identity = stream_request.identity
        base = {"stream_id": identity.stream_id, "product": identity.product,
                "strategy_code": identity.strategy_code, "frequency": identity.frequency,
                "requested_operation": operation, "execution_gate": "UNVERIFIED"}
        remaining_seconds = int(deadline - clock())
        remaining_bars = max_total_bars - used_bars
        remaining_bytes = max_total_bytes - used_bytes
        if min(remaining_seconds, remaining_bars, remaining_bytes) <= 0:
            results.append({**base, "status": "BLOCKED", "reason": "P9_TOTAL_BUDGET_EXCEEDED"})
            continue
        budget = WorkBudget(
            1, min(max_stream_bars, remaining_bars),
            min(max_stream_seconds, remaining_seconds),
            min(max_stream_bytes, remaining_bytes),
        )
        try:
            with planner_context() as planner:
                plan = planner.plan(HistoricalReferenceRequest(
                    operation, (stream_request,), budget,
                ))
            stream = plan.streams[0]
        except (ValueError, MarketDataError) as error:
            code = str(error)
            if code in {"P9_DATABASE_IDENTITY_MISMATCH", "P9_SCHEMA_VERSION_MISMATCH"}:
                raise
            safe_prefixes = (
                "REFERENCE_", "SOURCE_", "DATASET_", "QUALITY_",
                "SESSION_", "CALENDAR_", "MAIN_", "P9_", "SUBING_", "NEWOW_",
            )
            reason = (
                code if code.startswith(safe_prefixes)
                and code.isupper() and code.replace("_", "").isalnum()
                else "P9_SOURCE_BLOCKED"
            )
            results.append({**base, "status": "BLOCKED", "reason": reason})
            continue
        except SQLAlchemyError:
            raise
        except Exception:
            results.append({**base, "status": "BLOCKED", "reason": "P9_SOURCE_READ_FAILED"})
            continue
        if (
            clock() >= deadline
            or stream.input_count > min(max_stream_bars, remaining_bars)
            or stream.input_bytes > min(max_stream_bytes, remaining_bytes)
        ):
            results.append({**base, "status": "BLOCKED", "reason": "P9_TOTAL_BUDGET_EXCEEDED"})
            continue
        used_bars += stream.input_count
        used_bytes += stream.input_bytes
        results.append({
            **base, "status": "SOURCE_READY", "plan_hash": plan.plan_hash,
            "input_count": stream.input_count, "input_bytes": stream.input_bytes,
            "source_digest": stream.dependency_digest,
            "source_token_sha256": sha256(stream.source_token.encode()).hexdigest(),
            "storage_start": stream.storage_start.isoformat(),
            "target_completed_through": stream.target_completed_through.isoformat(),
        })
    return {
        "results": results,
        "counts": {"selected": len(results),
                   "source_ready": sum(item["status"] == "SOURCE_READY" for item in results),
                   "blocked": sum(item["status"] == "BLOCKED" for item in results)},
        "used_input_bars": used_bars, "used_input_bytes": used_bytes,
    }


def _readonly_session(expected_database: str, expected_schema: str):
    from app.db.session import SessionLocal

    session = SessionLocal()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        if session.execute(text("SELECT current_database()")).scalar_one() != expected_database:
            raise ValueError("P9_DATABASE_IDENTITY_MISMATCH")
        if session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != expected_schema:
            raise ValueError("P9_SCHEMA_VERSION_MISMATCH")
        return session
    except BaseException:
        session.close()
        raise


def _database_preflight(expected_database: str, expected_schema: str) -> None:
    with _readonly_session(expected_database, expected_schema):
        pass


@contextmanager
def _readonly_planner(expected_database: str, expected_schema: str):
    def readonly_session():
        return _readonly_session(expected_database, expected_schema)

    with open_historical_reference_components(session_factory=readonly_session) as (planner, _):
        yield planner


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-code-sha", required=True)
    parser.add_argument("--expected-capability-schema-version", required=True)
    parser.add_argument("--expected-active-sha256", required=True)
    parser.add_argument("--expected-operational-sha256", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--expected-schema-version", required=True)
    parser.add_argument("--products", required=True, help="Comma-separated explicit product batch")
    parser.add_argument("--since", type=date.fromisoformat, required=True)
    parser.add_argument("--through", type=date.fromisoformat, required=True)
    parser.add_argument("--as-of", type=datetime.fromisoformat, required=True)
    parser.add_argument("--operation", choices=("build", "advance", "rebuild"), required=True)
    parser.add_argument("--max-streams", type=int, required=True)
    parser.add_argument("--max-total-bars", type=int, required=True)
    parser.add_argument("--max-total-bytes", type=int, required=True)
    parser.add_argument("--max-total-seconds", type=int, required=True)
    parser.add_argument("--max-stream-bars", type=int, required=True)
    parser.add_argument("--max-stream-bytes", type=int, required=True)
    parser.add_argument("--max-stream-seconds", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    commit = _exact_checkout(args.expected_code_sha)
    active_sha = sha256((ROOT / "data/universe/active_products.txt").read_bytes()).hexdigest()
    operational_sha = sha256((ROOT / "data/universe/operational_products.txt").read_bytes()).hexdigest()
    if (
        args.expected_capability_schema_version != CAPABILITY_SCHEMA_VERSION
        or args.expected_active_sha256 != active_sha
        or args.expected_operational_sha256 != operational_sha
    ):
        parser.error("P9_CAPABILITY_OR_UNIVERSE_MISMATCH")
    if args.as_of.tzinfo is None or args.as_of.utcoffset() is None:
        parser.error("P9_AS_OF_TIMEZONE_REQUIRED")
    if args.as_of > datetime.now(args.as_of.tzinfo):
        parser.error("P9_AS_OF_IN_FUTURE")
    products = tuple(item.strip().upper() for item in args.products.split(","))
    if len(products) != len(set(products)) or any(not item for item in products):
        parser.error("P9_PRODUCT_SCOPE_INVALID")
    scope = enumerate_scope(
        load_active_products(), load_operational_products(), tuple(OPEN_WEEKLY_PRODUCTS), {},
    )
    requests = _formal_requests(scope["streams"], products, args.since, args.through, args.as_of)
    try:
        _database_preflight(args.expected_database_name, args.expected_schema_version)
        report = plan_batch(
            requests, operation=args.operation, max_streams=args.max_streams,
            max_total_bars=args.max_total_bars, max_total_bytes=args.max_total_bytes,
            max_total_seconds=args.max_total_seconds, max_stream_bars=args.max_stream_bars,
            max_stream_bytes=args.max_stream_bytes, max_stream_seconds=args.max_stream_seconds,
            planner_context=lambda: _readonly_planner(
                args.expected_database_name, args.expected_schema_version,
            ),
        )
    except (SQLAlchemyError, ValueError) as error:
        if isinstance(error, SQLAlchemyError) or str(error) in {
            "P9_DATABASE_IDENTITY_MISMATCH", "P9_SCHEMA_VERSION_MISMATCH",
        }:
            parser.error("P9_DATABASE_PREFLIGHT_FAILED")
        raise
    body = {
        "schema_version": 1, "artifact_kind": "source_readiness_audit",
        "readonly": True, "apply_supported": False,
        "full_historical_reference_plan_saved": False,
        "db_data_writes": 0, "maintenance_advisory_lock": "per_stream_released",
        "code_sha": commit, "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
        "active_products_file_sha256": active_sha,
        "operational_products_file_sha256": operational_sha,
        "queried_database_name": args.expected_database_name,
        "queried_schema_version": args.expected_schema_version,
        "window": {"since": args.since.isoformat(), "through": args.through.isoformat(),
                   "as_of": args.as_of.isoformat()},
        "products": products,
        "budget": {name: getattr(args, name) for name in (
            "max_streams", "max_total_bars", "max_total_bytes", "max_total_seconds",
            "max_stream_bars", "max_stream_bytes", "max_stream_seconds",
        )},
        **report,
    }
    output = write_new_manifest(args.output, body)
    print(json.dumps({"status": "source_readiness_audit", "readonly": True,
                      "output": str(output), "code_sha": commit, "counts": report["counts"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
