"""Freeze exact exchange-daily windows from all-conflict-week diagnosis."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
import re
from typing import Any, Mapping


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA = "newow_weekly_conflict_source_plan_v1"
_DIAGNOSIS_SCHEMA = "newow_weekly_conflict_diagnosis_v2"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_dates(days: object) -> tuple[str, ...]:
    if not isinstance(days, list) or not days:
        raise ValueError("SOURCE_PLAN_DATES_INVALID")
    parsed: list[str] = []
    seen: set[str] = set()
    for item in days:
        if not isinstance(item, str):
            raise ValueError("SOURCE_PLAN_DATES_INVALID")
        parsed_day = date.fromisoformat(item)
        iso = parsed_day.isoformat()
        if iso in seen:
            raise ValueError("SOURCE_PLAN_DATES_INVALID")
        seen.add(iso)
        parsed.append(iso)
    if tuple(parsed) != tuple(sorted(parsed)):
        raise ValueError("SOURCE_PLAN_DATES_INVALID")
    return tuple(parsed)


def _request_payload(contract: str, days: tuple[str, ...]) -> dict[str, object]:
    return {
        "method": "futures.get_exchange_daily",
        "contract": contract,
        "start": days[0],
        "end": days[-1],
        "expected_dates": list(days),
    }


def build_source_plan(diagnosis: Mapping[str, Any]) -> dict[str, object]:
    """Emit one frozen exchange-daily request per conflict week."""
    if (
        diagnosis.get("schema_version") != _DIAGNOSIS_SCHEMA
        or diagnosis.get("status") != "diagnosed"
        or diagnosis.get("catalog_revision_stable") is not True
        or diagnosis.get("catalog_revision_before") != diagnosis.get("catalog_revision_after")
    ):
        raise ValueError("SOURCE_PLAN_DIAGNOSIS_INVALID")
    contracts = diagnosis.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise ValueError("SOURCE_PLAN_DIAGNOSIS_INVALID")
    requests: list[dict[str, object]] = []
    for item in contracts:
        if not isinstance(item, Mapping):
            raise ValueError("SOURCE_PLAN_DIAGNOSIS_INVALID")
        symbol = item.get("symbol")
        contract = item.get("contract")
        weeks = item.get("conflict_weeks")
        if (
            not isinstance(symbol, str)
            or not isinstance(contract, str)
            or item.get("classification") != "SOURCE_VERIFICATION_REQUIRED"
            or not isinstance(weeks, list)
            or not weeks
        ):
            raise ValueError("SOURCE_PLAN_DIAGNOSIS_INVALID")
        for week in weeks:
            if not isinstance(week, Mapping):
                raise ValueError("SOURCE_PLAN_DIAGNOSIS_INVALID")
            if week.get("contract") not in (None, contract):
                raise ValueError("SOURCE_PLAN_CONTRACT_MISMATCH")
            days = _require_dates(week.get("daily_trading_days"))
            if date.fromisoformat(days[-1]).isocalendar()[:2] != (
                week.get("iso_year"),
                week.get("iso_week"),
            ):
                raise ValueError("SOURCE_PLAN_WEEK_IDENTITY_INVALID")
            stored_contract = week.get("stored_w1_partition")
            if not isinstance(stored_contract, Mapping):
                raise ValueError("SOURCE_PLAN_PARTITION_INVALID")
            payload = _request_payload(contract, days)
            requests.append({
                "symbol": symbol,
                "contract": contract,
                "method": payload["method"],
                "start": payload["start"],
                "end": payload["end"],
                "expected_dates": payload["expected_dates"],
                "week_end": week["week_end"],
                "trading_day": week["trading_day"],
                "iso_year": week["iso_year"],
                "iso_week": week["iso_week"],
                "cross_month": bool(week.get("cross_month")),
                "numeric_conflict_fields": list(week["numeric_conflict_fields"]),
                "stored_w1_partition": dict(week["stored_w1_partition"]),
                "d1_partitions": list(week["d1_partitions"]),
                "d1_revision_sha256": week.get("d1_revision_sha256"),
                "request_sha256": _sha256(payload),
            })
    unsigned: dict[str, object] = {
        "schema_version": _SCHEMA,
        "command": "newow.weekly-conflict-source-verification",
        "method": "futures.get_exchange_daily",
        "as_of": diagnosis["as_of"],
        "code_sha": diagnosis["code_sha"],
        "input_sha256": diagnosis["input_sha256"],
        "catalog_revision": diagnosis["catalog_revision_after"],
        "provider_execution_authorized": True,
        "canonical_writes_allowed": False,
        "database_writes_allowed": False,
        "retry_allowed": False,
        "request_count": len(requests),
        "expected_source_rows": sum(len(item["expected_dates"]) for item in requests),
        "requests": requests,
        "rules": [
            "capture provider response without OHLC substitution",
            "settlement and prev_settlement are evidence only",
            "stop on first extra, missing, or duplicate trading day",
            "no retry",
            "no Canonical or database writes",
        ],
    }
    unsigned["plan_sha256"] = _sha256({key: value for key, value in unsigned.items() if key != "plan_sha256"})
    return unsigned


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(allow_abbrev=False)
    value.add_argument("--diagnosis", required=True)
    value.add_argument("--expected-diagnosis-sha256", required=True)
    value.add_argument("--output", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if _HASH.fullmatch(args.expected_diagnosis_sha256) is None:
        raise ValueError("SOURCE_PLAN_DIAGNOSIS_HASH_INVALID")
    raw = Path(args.diagnosis).read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.expected_diagnosis_sha256:
        raise ValueError("SOURCE_PLAN_DIAGNOSIS_HASH_MISMATCH")
    plan = build_source_plan(json.loads(raw))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "status": "planned",
        "request_count": plan["request_count"],
        "expected_source_rows": plan["expected_source_rows"],
        "plan_sha256": plan["plan_sha256"],
        "canonical_writes_allowed": False,
        "database_writes_allowed": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
