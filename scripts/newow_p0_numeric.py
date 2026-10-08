"""Artifact-only raw-source numeric parity; no DB, API or Runtime operations.

Every physical prefix is evaluated counterfactually as fully observation-eligible
and terminal-eligible. This checks the Python source kernel against independent
public-JS raw objects; it does not claim futures-masked API or 720-stream closure.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re

from guiyi_quant.newow.page_performance import (
    PAGE_PERFORMANCE_VERSION,
    PAGE_SOURCE_SHA256,
    PageAction,
    PageBar,
    PageSegment,
    compute_page_performance,
)
from scripts.newow_p0_candidate import write_once

SOURCE_HASHES = {
    "detail.html": PAGE_SOURCE_SHA256,
    "strategy-calc.js": "a91f3a7685e0dadb95927229c45b7ecffeee052d1269b79207ccb9fa08612a9e",
    "composite-decision-v2.js": "522bb42dca07758741b0c9fb25f666c0ae5e79f070c25c32ecc1d08200ff06b2",
    "trend-reversal-core.js": "85a72b64ca9b9a84ee04338cfffeb28b67dfae923699498a80eb71a22faf6f80",
}
PERIODS = {
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "60m": "60min",
    "1d": "day",
    "1w": "week",
}
STRATEGIES = ("trend", "oscillation", "main_rise", "fusion")
OMIT = {"segment_ids", "trading_days", "segment_id"}


def numeric(value):
    """Compare all source fields; omit only explicit futures adapter extensions."""
    if isinstance(value, dict):
        return {key: numeric(item) for key, item in value.items() if key not in OMIT}
    if isinstance(value, list):
        return [numeric(item) for item in value]
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value))
    return value


def differences(expected, actual):
    """Count every mismatch; retain bounded scalar-only locations, never arrays."""
    result = []
    count = 0

    def add(path, kind, left=None, right=None):
        nonlocal count
        count += 1
        if len(result) < 50:

            def scalar(value):
                return (
                    str(value)
                    if isinstance(value, Decimal)
                    else value
                    if isinstance(value, (str, int, float, bool)) or value is None
                    else "<structured value>"
                )

            result.append(
                {
                    "path": path,
                    "kind": kind,
                    "expected": scalar(left),
                    "actual": scalar(right),
                }
            )

    def walk(left, right, path):
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:
                    add(f"{path}.{key}", "missing_or_extra_field")
                else:
                    walk(left[key], right[key], f"{path}.{key}")
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                add(path, "array_length", len(left), len(right))
            for index, (a, b) in enumerate(zip(left, right)):
                walk(a, b, f"{path}[{index}]")
        elif type(left) is not type(right) or left != right:
            add(path, "value", left, right)

    walk(expected, actual, "$")
    return count, result


def verify_bindings(payload, raw, input_bytes):
    if (
        raw.get("schema") != "newow_v3379_market_source_raw_v1"
        or raw.get("source_version") != "3.3.79"
        or raw.get("source_sha256") != SOURCE_HASHES
    ):
        raise ValueError("P0_NUMERIC_SOURCE_IDENTITY_MISMATCH")
    if raw.get("input_bytes_sha256") != sha256(input_bytes).hexdigest() or raw.get(
        "input_sha256"
    ) != payload.get("input_sha256"):
        raise ValueError("P0_NUMERIC_INPUT_BINDING_MISMATCH")
    period = PERIODS.get(payload.get("frequency"), payload.get("period"))
    if period not in PERIODS.values() or raw.get("period") != period:
        raise ValueError("P0_NUMERIC_PERIOD_MISMATCH")
    for key in (
        "code_sha",
        "product",
        "frequency",
        "cutoff",
        "performance_since",
        "performance_through",
        "source_evidence_sha256",
    ):
        if raw.get("input_identity", {}).get(key) != payload.get(key):
            raise ValueError("P0_NUMERIC_IDENTITY_MISMATCH")
    if len(payload.get("segments", [])) != len(raw.get("segments", [])):
        raise ValueError("P0_NUMERIC_OWNER_MISMATCH")
    for segment, source in zip(payload["segments"], raw["segments"], strict=True):
        if segment["owner"] != source.get("owner") or len(
            segment["bars"]
        ) != source.get("bar_count"):
            raise ValueError("P0_NUMERIC_OWNER_MISMATCH")
    return period


PRICE_TOLERANCE = Decimal("1e-8")


def compare_native_signals(payload, raw):
    """Match all dated source markers; only prices allow representation tolerance.

    Decimal kernel values and JS shortest binary64 strings can differ in their
    last digits. The explicit 1e-8 tolerance applies solely to marker price;
    owner, instant, trading day, action kind, membership and counts stay exact.
    WARMUP_ONLY source-link witnesses are excluded; INITIAL_CLEAR_NO_ENTRY and
    NO_ELIGIBLE_ENTRY CLEAR facts are retained with ordinary eligible markers.
    """
    from datetime import datetime, timezone

    supplied = payload.get("native_actions")
    if not supplied:
        return {"status": "NOT_ASSESSED", "reason": "NATIVE_ACTIONS_NOT_SUPPLIED"}
    result = {
        "status": "PASSED",
        "price_tolerance": str(PRICE_TOLERANCE),
        "max_price_delta": "0",
        "date_owner_type_membership": "EXACT",
        "price_tolerance_reason": "Decimal versus JS binary64 number representation only",
        "checks": [],
    }
    try:

        def instant(value):
            parsed = datetime.fromisoformat(value)
            return (
                parsed.astimezone(timezone.utc).isoformat()
                if parsed.tzinfo is not None
                else parsed.isoformat()
            )

        bars_by_key = {}
        expected = {strategy: {} for strategy in ("trend", "oscillation")}
        native = {strategy: {} for strategy in expected}
        owners = {}
        since, through = (
            payload.get("performance_since"),
            payload.get("performance_through"),
        )

        def selected(bar):
            day = bar["trading_day"]
            return (
                bar["observation_eligible"]
                and (not since or day >= since)
                and (not through or day <= through)
            )

        for segment, source in zip(payload["segments"], raw["segments"], strict=True):
            physical = (
                segment["physical_contract"],
                segment["owner_segment_id"],
                segment["calculation_segment_id"],
            )
            owners[physical] = segment["owner"]
            for bar in segment["bars"]:
                key = (physical, instant(bar["date"]))
                if key in bars_by_key:
                    raise ValueError("P0_NATIVE_SOURCE_DUPLICATE_BAR")
                bars_by_key[key] = bar
            for strategy in expected:
                signals = (
                    source["chart"]["trend"]["signals"]
                    if strategy == "trend"
                    else source["chart"]["oscillation"]
                )
                for signal in signals:
                    if strategy == "trend":
                        index = signal["index"]
                        if type(index) is not int or not 0 <= index < len(
                            segment["bars"]
                        ):
                            raise ValueError("P0_NATIVE_RAW_SIGNAL_INVALID")
                        at = instant(segment["bars"][index]["date"])
                    else:
                        at = instant(signal["date"])
                    bar = bars_by_key[(physical, at)]
                    if not selected(bar):
                        continue
                    kind = signal["type"]
                    if kind not in ("buy", "sell"):
                        raise ValueError("P0_NATIVE_RAW_SIGNAL_INVALID")
                    key = (segment["owner"], at, kind)
                    expected[strategy].setdefault(key, []).append(
                        Decimal(str(signal["price"]))
                    )
        ignored_warmup = 0
        eligibility_counts = {
            "ELIGIBLE": 0,
            "NO_ELIGIBLE_ENTRY": 0,
            "INITIAL_CLEAR_NO_ENTRY": 0,
        }
        for strategy in expected:
            container = supplied.get(strategy)
            points = (
                container.get("actions") if isinstance(container, dict) else container
            )
            if not isinstance(points, list):
                raise ValueError("P0_NATIVE_ACTIONS_MISSING_BASE")
            for point in points:
                value = point["value"]
                eligibility = value["trade_eligibility"]
                if eligibility == "WARMUP_ONLY":
                    ignored_warmup += 1
                    continue
                if eligibility not in eligibility_counts or value["kind"] not in (
                    "BUILD",
                    "CLEAR",
                ):
                    raise ValueError("P0_NATIVE_ACTION_INVALID")
                physical = (
                    value["physical_contract"],
                    value["segment_id"],
                    value["calculation_segment_id"],
                )
                at = instant(value["bar_end"])
                bar = bars_by_key.get((physical, at))
                if (
                    bar is None
                    or point["trading_day"] != bar["trading_day"]
                    or value.get("trading_day", point["trading_day"])
                    != bar["trading_day"]
                ):
                    raise ValueError("P0_NATIVE_ACTION_DATE_OWNER_MISMATCH")
                if not selected(bar):
                    continue
                if eligibility != "ELIGIBLE" and value["kind"] != "CLEAR":
                    raise ValueError("P0_NATIVE_ACTION_INVALID")
                price = Decimal(str(value["reference_price"]))
                if not price.is_finite() or price <= 0:
                    raise ValueError("P0_NATIVE_ACTION_INVALID")
                key = (
                    owners[physical],
                    at,
                    "buy" if value["kind"] == "BUILD" else "sell",
                )
                native[strategy].setdefault(key, []).append(price)
                eligibility_counts[eligibility] += 1
        max_delta = Decimal(0)
        for strategy in expected:
            for owner in (segment["owner"] for segment in payload["segments"]):
                keys = sorted(
                    key
                    for key in set(expected[strategy]) | set(native[strategy])
                    if key[0] == owner
                )
                details = []
                count = 0
                owner_max = Decimal(0)
                for key in keys:
                    left, right = (
                        sorted(expected[strategy].get(key, [])),
                        sorted(native[strategy].get(key, [])),
                    )
                    if len(left) != len(right):
                        count += 1
                        if len(details) < 50:
                            details.append(
                                {
                                    "date": key[1],
                                    "type": key[2],
                                    "kind": "marker_count",
                                    "expected": len(left),
                                    "actual": len(right),
                                }
                            )
                    for a, b in zip(left, right):
                        delta = abs(a - b)
                        owner_max = max(owner_max, delta)
                        if delta > PRICE_TOLERANCE:
                            count += 1
                            if len(details) < 50:
                                details.append(
                                    {
                                        "date": key[1],
                                        "type": key[2],
                                        "kind": "price",
                                        "expected": str(a),
                                        "actual": str(b),
                                        "delta": str(delta),
                                    }
                                )
                max_delta = max(max_delta, owner_max)
                result["checks"].append(
                    {
                        "owner": owner,
                        "strategy": strategy,
                        "status": "FAILED" if count else "PASSED",
                        "expected_count": sum(
                            len(values)
                            for key, values in expected[strategy].items()
                            if key[0] == owner
                        ),
                        "native_count": sum(
                            len(values)
                            for key, values in native[strategy].items()
                            if key[0] == owner
                        ),
                        "difference_count": count,
                        "max_price_delta": str(owner_max),
                        "details": details,
                    }
                )
                if count:
                    result["status"] = "FAILED"
        result["max_price_delta"] = str(max_delta)
        result["ignored_warmup_only"] = ignored_warmup
        result["eligibility_counts"] = eligibility_counts
    except (ValueError, KeyError, TypeError, ArithmeticError) as error:
        reason = str(error)
        result["status"] = "FAILED"
        result["reason"] = (
            reason
            if re.fullmatch("P0_[A-Z0-9_]+", reason)
            else "P0_NATIVE_ACTION_INPUT_INVALID"
        )
    return result


def compare_artifacts(input_bytes: bytes, raw_bytes: bytes) -> dict:
    try:
        payload, raw = json.loads(input_bytes), json.loads(raw_bytes)
        if not isinstance(payload, dict) or not isinstance(raw, dict):
            raise ValueError("P0_NUMERIC_INPUT_INVALID")
    except (ValueError, TypeError):
        return {
            "schema": "newow_p0_raw_numeric_v1",
            "status": "FAILED",
            "reason": "P0_NUMERIC_INPUT_INVALID",
            "acceptance_scope": "RAW_SOURCE_PARITY_ONLY",
            "futures_adapter_comparison": "PENDING",
            "overall_720_acceptance": "NOT_ASSESSED",
            "all_raw_source_passed": False,
            "owner_count": 0,
            "owners": [],
            "native_signals": {"status": "NOT_ASSESSED"},
            "input_bytes_sha256": sha256(input_bytes).hexdigest(),
            "raw_oracle_bytes_sha256": sha256(raw_bytes).hexdigest(),
        }
    report = {
        "schema": "newow_p0_raw_numeric_v1",
        "status": "FAILED",
        "all_raw_source_passed": False,
        "acceptance_scope": "RAW_SOURCE_PARITY_ONLY",
        "futures_adapter_comparison": "PENDING",
        "overall_720_acceptance": "NOT_ASSESSED",
        "kernel_version": PAGE_PERFORMANCE_VERSION,
        "source_sha256": SOURCE_HASHES,
        "input_bytes_sha256": sha256(input_bytes).hexdigest(),
        "raw_oracle_bytes_sha256": sha256(raw_bytes).hexdigest(),
        "input_sha256": payload.get("input_sha256"),
        "product": payload.get("product"),
        "frequency": payload.get("frequency"),
        "owner_count": len(payload.get("segments", [])),
        "owners": [],
        "native_signals": {"status": "NOT_ASSESSED"},
    }
    try:
        period = verify_bindings(payload, raw, input_bytes)
    except (ValueError, KeyError, TypeError) as error:
        reason = str(error)
        report["reason"] = (
            reason
            if re.fullmatch("P0_[A-Z0-9_]+", reason)
            else "P0_NUMERIC_INPUT_INVALID"
        )
        return report
    all_passed = bool(payload["segments"])
    for segment, source in zip(payload["segments"], raw["segments"], strict=True):
        owner = {
            "owner": segment["owner"],
            "bar_count": len(segment["bars"]),
            "status": "PASSED",
            "checks": [],
        }
        try:
            bars = tuple(
                PageBar(
                    row["date"],
                    *(Decimal(str(row[key])) for key in ("high", "low", "close")),
                    True,
                    row.get("trading_day"),
                )
                for row in segment["bars"]
            )
            # Signal facts come only from independently generated public-JS chart.
            actions = tuple(
                PageAction(s["date"], s["type"], Decimal(str(s["price"])))
                for s in source["chart"]["fusion"]
            )
            for strategy in STRATEGIES:
                projection = compute_page_performance(
                    [
                        PageSegment(
                            segment["owner"],
                            bars,
                            True,
                            actions if strategy == "fusion" else (),
                        )
                    ],
                    strategy,
                    period=period,
                )
                for mode in ("ordinary", "ideal"):
                    count, details = differences(
                        numeric(source[mode][strategy]), numeric(projection[mode])
                    )
                    owner["checks"].append(
                        {
                            "strategy": strategy,
                            "mode": mode,
                            "status": "PASSED" if not count else "FAILED",
                            "difference_count": count,
                            "details": details,
                        }
                    )
                    if count:
                        owner["status"] = "FAILED"
        except (ValueError, KeyError, TypeError, ArithmeticError) as error:
            owner["status"] = "FAILED"
            reason = str(error)
            owner["reason"] = (
                reason
                if re.fullmatch("[A-Z0-9_]+", reason)
                else "P0_NUMERIC_OWNER_INVALID"
            )
        report["owners"].append(owner)
        all_passed = all_passed and owner["status"] == "PASSED"
    report["all_raw_source_passed"] = all_passed
    report["native_signals"] = compare_native_signals(payload, raw)
    report["status"] = (
        "PASSED"
        if all_passed and report["native_signals"]["status"] != "FAILED"
        else "FAILED"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare_artifacts(args.input.read_bytes(), args.oracle.read_bytes())
    write_once(args.output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "acceptance_scope": report["acceptance_scope"],
                "owner_count": report["owner_count"],
                "output": str(args.output),
            }
        ),
        flush=True,
    )
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
