"""Independent readonly settlement for the six-product Newow 60m recovery."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from scripts.newow_weekly_recovery import RecoveryError, _canonical_json, _error_code
from scripts.newow_weekly_recovery_campaign import _HOURLY_PRODUCTS


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Summarize frozen 60m inventory without mutating data."
    )
    commands = value.add_subparsers(dest="mode", required=True)
    inventory = commands.add_parser("inventory", allow_abbrev=False)
    inventory.add_argument("--report-dir", required=True)
    inventory.add_argument("--expected-as-of", required=True)
    inventory.add_argument("--output", required=True)
    return value


def summarize_inventory(
    *,
    report_dir: Path,
    expected_as_of: str,
) -> dict[str, Any]:
    as_of = datetime.fromisoformat(expected_as_of)
    if as_of.tzinfo is None:
        raise RecoveryError("CAMPAIGN_REPORT_INVALID")
    rows: list[dict[str, Any]] = []
    for symbol in _HOURLY_PRODUCTS:
        path = Path(report_dir) / f"{symbol}-60m.json"
        payload = json.loads(path.read_bytes())
        if (
            payload.get("as_of") != expected_as_of
            or payload.get("frequency_scope") != ["60m"]
            or payload.get("command") != "data.newow-readiness"
            or payload.get("provider_requests") != 0
            or payload.get("writes") != 0
        ):
            raise RecoveryError("CAMPAIGN_REPORT_INVALID")
        repairs = [
            item
            for item in payload.get("repair_targets") or []
            if isinstance(item, Mapping)
        ]
        proposed = [item for item in repairs if item.get("status") == "PROPOSED"]
        derive = [
            item for item in proposed if item.get("provider_request_count") == 0
        ]
        download = [
            item
            for item in proposed
            if isinstance(item.get("provider_request_count"), int)
            and item.get("provider_request_count") > 0
        ]
        review = Counter(
            item.get("status")
            for item in repairs
            if item.get("status") not in {None, "PROPOSED"}
            and isinstance(item.get("status"), str)
        )
        deps = [
            item
            for item in payload.get("dependencies") or []
            if isinstance(item, Mapping) and item.get("frequency") == "60m"
        ]
        rows.append(
            {
                "symbol": symbol,
                "complete": payload.get("complete") is True
                and payload.get("status") == "audited"
                and payload.get("budget_exhausted") is False,
                "status": payload.get("status"),
                "dependency_ready": sum(
                    item.get("status") == "DATA_READY" for item in deps
                ),
                "dependency_not_ready": sum(
                    item.get("status") != "DATA_READY" for item in deps
                ),
                "proposed": len(proposed),
                "derive_only": len(derive),
                "need_1m": len(download),
                "review_required": dict(review),
                "provider_request_count": sum(
                    int(item.get("provider_request_count") or 0) for item in proposed
                ),
                "expected_bar_count": sum(
                    int(item.get("expected_bar_count") or 0) for item in proposed
                ),
            }
        )
    return {
        "schema_version": "newow_hourly_recovery_inventory_v1",
        "as_of": expected_as_of,
        "products": list(_HOURLY_PRODUCTS),
        "inventory_complete": all(item["complete"] for item in rows),
        "totals": {
            "proposed": sum(item["proposed"] for item in rows),
            "derive_only": sum(item["derive_only"] for item in rows),
            "need_1m": sum(item["need_1m"] for item in rows),
            "provider_request_count": sum(
                item["provider_request_count"] for item in rows
            ),
            "expected_bar_count": sum(item["expected_bar_count"] for item in rows),
        },
        "rows": rows,
        "report_sha256": {
            symbol: hashlib.sha256(
                (Path(report_dir) / f"{symbol}-60m.json").read_bytes()
            ).hexdigest()
            for symbol in _HOURLY_PRODUCTS
        },
    }


def main(argv: list[str] | None = None, *, stdout=sys.stdout) -> int:
    try:
        args = parser().parse_args(argv)
        summary = summarize_inventory(
            report_dir=Path(args.report_dir),
            expected_as_of=args.expected_as_of,
        )
        Path(args.output).write_text(
            _canonical_json(summary) + "\n",
            encoding="utf-8",
        )
        stdout.write(_canonical_json(summary) + "\n")
        return 0 if summary["inventory_complete"] else 1
    except (RecoveryError, ValueError, OSError, json.JSONDecodeError, KeyError) as exc:
        payload = {
            "schema_version": "newow_hourly_recovery_inventory_error_v1",
            "status": "failed",
            "error_code": _error_code(exc)
            if isinstance(exc, RecoveryError)
            else "INVENTORY_INVALID",
        }
        stdout.write(_canonical_json(payload) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
