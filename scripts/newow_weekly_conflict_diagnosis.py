"""Read-only W1 versus authoritative physical D1 conflict diagnosis."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.composition import build_market_data_service
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.rqdata_adapter import _aggregate_daily_rows
from app.market_data.weekly_quality import weekly_daily_revision_sha256


FIELDS = ("open", "high", "low", "close", "volume", "turnover", "open_interest")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CONTRACT = re.compile(r"[A-Z]{1,8}[0-9]{3,4}\Z")
_SYMBOL = re.compile(r"[a-z]{1,8}\Z")


def _decimal(value: Decimal | None) -> dict[str, object]:
    if value is None:
        return {"value": None, "exponent": None}
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("WEEKLY_CONFLICT_DECIMAL_INVALID")
    return {"value": str(value), "exponent": exponent}


def field_differences(
    stored: CanonicalBar, d1_aggregate: CanonicalBar,
) -> dict[str, dict[str, object]]:
    """Return all seven fields, preserving numeric and precision distinctions."""
    result: dict[str, dict[str, object]] = {}
    for field in FIELDS:
        left = getattr(stored, field)
        right = getattr(d1_aggregate, field)
        stored_value = _decimal(left)
        aggregate_value = _decimal(right)
        result[field] = {
            "stored": stored_value["value"],
            "d1_aggregate": aggregate_value["value"],
            "stored_exponent": stored_value["exponent"],
            "d1_aggregate_exponent": aggregate_value["exponent"],
            "numeric_equal": left == right,
            "precision_equal": stored_value["exponent"] == aggregate_value["exponent"],
        }
    return result


def _partition_identity(row) -> dict[str, object]:
    return {
        "year": row.year,
        "month": row.month,
        "file_name": row.file_path.name,
        "row_count": row.row_count,
        "source_quality_sha256": row.source_quality_sha256,
    }


def _load_input(path: Path, expected_sha256: str) -> tuple[dict[str, object], ...]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("WEEKLY_CONFLICT_INPUT_HASH_MISMATCH")
    payload = json.loads(raw)
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if (
        payload.get("provider_requests") != 0
        or payload.get("writes") != 0
        or not isinstance(rows, list)
        or len(rows) != 20
    ):
        raise ValueError("WEEKLY_CONFLICT_INPUT_INVALID")
    validated: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("WEEKLY_CONFLICT_INPUT_INVALID")
        symbol, contract, through = row.get("symbol"), row.get("contract"), row.get("through")
        if (
            not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None
            or not isinstance(contract, str) or _CONTRACT.fullmatch(contract) is None
            or not isinstance(through, str)
            or row.get("code") != "WEEKLY_SOURCE_BAR_CONFLICT"
            or (symbol, contract) in seen
        ):
            raise ValueError("WEEKLY_CONFLICT_INPUT_INVALID")
        date.fromisoformat(through)
        seen.add((symbol, contract))
        validated.append(row)
    return tuple(validated)


def _diagnose(market, row: dict[str, object], cutoff: datetime) -> dict[str, object]:
    symbol = str(row["symbol"])
    contract = str(row["contract"])
    through = date.fromisoformat(str(row["through"]))
    weekly_expected = market.expected_contract_replay_endpoints(
        symbol=symbol, contract=contract, frequency=BarFrequency.W1,
        trading_day=through, cutoff=cutoff,
    )
    daily_expected = market.expected_contract_replay_endpoints(
        symbol=symbol, contract=contract, frequency=BarFrequency.D1,
        trading_day=through, cutoff=cutoff,
    )
    if not weekly_expected:
        raise ValueError("WEEKLY_CONFLICT_ENDPOINTS_MISSING")
    replay_cutoff = weekly_expected[-1][0]
    daily_bars, daily_gaps = market.query_contract_replay_quality_union(
        symbol=symbol, contract=contract, through=weekly_expected[-1][1],
        cutoff=replay_cutoff,
    )
    weekly_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.W1)
    daily_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.D1)
    weekly_rows = market.catalog.all_partitions(weekly_key)
    daily_rows = market.catalog.all_partitions(daily_key)
    stored = tuple(
        bar
        for partition in weekly_rows
        for bar in market.store.read_catalog_partition(partition)
        if bar.bar_end <= replay_cutoff
    )
    by_end = {bar.bar_end: bar for bar in stored}
    if len(by_end) != len(stored):
        raise ValueError("WEEKLY_CONFLICT_DUPLICATE_BAR")

    for week_end, week_day in weekly_expected:
        week = week_day.isocalendar()[:2]
        expected = tuple(point for point in daily_expected if point[1].isocalendar()[:2] == week)
        bars = tuple(bar for bar in daily_bars if bar.trading_day.isocalendar()[:2] == week)
        gaps = tuple(gap for gap in daily_gaps if gap.trading_day.isocalendar()[:2] == week)
        persisted = by_end.get(week_end)
        if persisted is None or gaps or tuple((bar.bar_end, bar.trading_day) for bar in bars) != expected:
            continue
        aggregate = _aggregate_daily_rows(tuple(
            (bar.trading_day, {field: getattr(bar, field) for field in FIELDS})
            for bar in bars
        ), bar_end=week_end)
        if persisted == aggregate:
            continue
        months = sorted({(day.year, day.month) for _, day in expected})
        selected_daily = tuple(
            partition for partition in daily_rows
            if (partition.year, partition.month) in months
        )
        daily_revision = weekly_daily_revision_sha256(
            tuple(
                (partition.file_path.name, partition.source_quality_sha256)
                for partition in selected_daily
            ),
            bars,
        )
        differences = field_differences(persisted, aggregate)
        numeric_fields = [field for field, value in differences.items() if not value["numeric_equal"]]
        precision_only = [
            field for field, value in differences.items()
            if value["numeric_equal"] and not value["precision_equal"]
        ]
        weekly_partition = next(
            partition for partition in weekly_rows
            if (partition.year, partition.month) == (week_day.year, week_day.month)
        )
        return {
            "symbol": symbol,
            "contract": contract,
            "requested_through": through.isoformat(),
            "first_conflict_week": {
                "iso_year": week[0],
                "iso_week": week[1],
                "week_end": week_end.isoformat(),
                "trading_day": week_day.isoformat(),
                "first_daily_endpoint": expected[0][0].isoformat(),
                "last_daily_endpoint": expected[-1][0].isoformat(),
                "daily_trading_days": [day.isoformat() for _, day in expected],
                "cross_month": len(months) > 1,
            },
            "identity": {
                "stored_weekly_bar_end": persisted.bar_end.isoformat(),
                "stored_weekly_trading_day": persisted.trading_day.isoformat(),
                "d1_aggregate_bar_end": aggregate.bar_end.isoformat(),
                "d1_aggregate_trading_day": aggregate.trading_day.isoformat(),
                "contract_owner_equal": True,
                "session_endpoint_equal": (
                    persisted.bar_end == aggregate.bar_end
                    and persisted.trading_day == aggregate.trading_day
                ),
            },
            "fields": differences,
            "numeric_conflict_fields": numeric_fields,
            "precision_only_fields": precision_only,
            "stored_w1_partition": _partition_identity(weekly_partition),
            "d1_partitions": [_partition_identity(item) for item in selected_daily],
            "d1_revision_sha256": daily_revision,
            "classification": "SOURCE_VERIFICATION_REQUIRED",
            "finding": "STORED_W1_DIFFERS_FROM_CURRENT_AUTHORITATIVE_D1_AGGREGATE",
            "provider_query_required": True,
        }
    raise ValueError("WEEKLY_CONFLICT_NOT_REPRODUCED")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(allow_abbrev=False)
    value.add_argument("--input", required=True)
    value.add_argument("--expected-input-sha256", required=True)
    value.add_argument("--as-of", required=True)
    value.add_argument("--output", required=True)
    return value


def diagnosis_status(
    results: list[dict[str, object]], *, catalog_revision_stable: bool
) -> str:
    """Fail closed unless every frozen contract was reproduced on one revision."""
    if (
        not catalog_revision_stable
        or len(results) != 20
        or any(
            item.get("classification") != "SOURCE_VERIFICATION_REQUIRED"
            for item in results
        )
    ):
        return "blocked"
    return "diagnosed"


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if _HASH.fullmatch(args.expected_input_sha256) is None:
        raise ValueError("WEEKLY_CONFLICT_INPUT_HASH_INVALID")
    cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("WEEKLY_CONFLICT_CUTOFF_INVALID")
    cutoff = cutoff.astimezone(UTC)
    rows = _load_input(Path(args.input), args.expected_input_sha256)
    products = tuple(sorted({str(row["symbol"]) for row in rows}))
    output = Path(args.output)
    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=300):
        before = catalog_revision(session, products, cutoff.date(), ("1d", "1w"))
        market = build_market_data_service(session)
        results = []
        for row in rows:
            try:
                results.append(_diagnose(market, row, cutoff))
            except Exception as exc:
                results.append({
                    "symbol": row["symbol"],
                    "contract": row["contract"],
                    "requested_through": row["through"],
                    "classification": "DIAGNOSIS_BLOCKED",
                    "error_type": type(exc).__name__,
                    **(
                        {"code": exc.code}
                        if isinstance(getattr(exc, "code", None), str)
                        else {}
                    ),
                    **(
                        {"reason": exc.reason}
                        if isinstance(getattr(exc, "reason", None), str)
                        else {}
                    ),
                    "provider_query_required": False,
                })
        after = catalog_revision(session, products, cutoff.date(), ("1d", "1w"))
    status = diagnosis_status(results, catalog_revision_stable=before == after)
    payload: dict[str, Any] = {
        "schema_version": "newow_weekly_conflict_diagnosis_v1",
        "status": status,
        "readonly": True,
        "provider_requests": 0,
        "writes": 0,
        "code_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True,
            cwd=Path(__file__).resolve().parents[1],
        ).strip(),
        "as_of": cutoff.isoformat(),
        "input_sha256": args.expected_input_sha256,
        "catalog_revision_before": before,
        "catalog_revision_after": after,
        "catalog_revision_stable": before == after,
        "contract_count": len(results),
        "classification_counts": {
            classification: sum(
                item["classification"] == classification for item in results
            )
            for classification in sorted({str(item["classification"]) for item in results})
        },
        "contracts": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "status": status,
        "contract_count": len(results),
        "catalog_revision_stable": before == after,
        "provider_requests": 0,
        "writes": 0,
    }))
    return 0 if status == "diagnosed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({
            "status": "blocked", "error_type": type(exc).__name__,
            "provider_requests": 0, "writes": 0,
        }), file=sys.stderr)
        raise SystemExit(1)
