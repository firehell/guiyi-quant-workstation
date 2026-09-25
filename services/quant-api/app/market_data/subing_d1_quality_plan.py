"""Pure, non-applying plan builder for the approved SuBing D1 quality contract."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import PurePosixPath
from typing import Any, Mapping

FIXED_CUTOFF = "2026-09-18T18:30:00+08:00"


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def build_plan(
    impact: Mapping[str, Any],
    evidence: Mapping[str, Any],
    source_complete: Mapping[str, Any],
    *,
    excluded_target_count: int,
) -> dict[str, Any]:
    """Return a deterministic prepare-only plan; this function performs no I/O."""
    if not (
        impact.get("fixed_cutoff") == FIXED_CUTOFF
        and evidence.get("fixed_cutoff") == FIXED_CUTOFF
        and source_complete.get("fixed_research_cutoff") == FIXED_CUTOFF
        and source_complete.get("all_66_target_evidence", {}).get("closed") is True
        and source_complete.get("existing_1207_anomaly_source_evidence", {}).get("closed") is True
        and excluded_target_count == 40
    ):
        raise ValueError("SUBING_D1_PLAN_INPUT_CONFLICT")
    items = evidence.get("items")
    if not isinstance(items, list) or len(items) != 17:
        raise ValueError("SUBING_D1_PLAN_SCOPE_CONFLICT")
    targets: list[dict[str, Any]] = []
    products: list[str] = []
    for item in items:
        symbol = item["symbol"]
        products.append(symbol)
        for partition in item["catalog_partitions"]:
            targets.append({
                "symbol": symbol,
                "contract": partition["contract"],
                "month": partition["month"],
                "partition_id": partition["partition_id"],
                "old_file_uri": partition["file_uri"],
                "old_file_sha256": partition["file_sha256"],
                "old_source_quality_sha256": partition.get("source_quality_sha256"),
                "affected_dates": sorted(partition["affected_dates"]),
                "source_fact_type": item["fact_type"],
                "operation": "REPLACE_EXISTING_PARTITION",
            })
    for symbol, contract in (("oi", "OI2609"), ("pf", "PF2609")):
        endpoints = sorted(
            {
                row["day"]: row["fresh_classification"]
                for row in source_complete.get("date_results", [])
                if row.get("symbol") == symbol
                and row.get("contract") == contract
                and str(row.get("day", "")).startswith("2026-09")
            }.items()
        )
        if len(endpoints) != 9:
            raise ValueError("SUBING_D1_PLAN_OI_PF_CONFLICT")
        targets.append({
            "symbol": symbol,
            "contract": contract,
            "month": "2026-09",
            "partition_id": None,
            "old_file_uri": None,
            "old_file_sha256": None,
            "old_source_quality_sha256": None,
            "affected_dates": [day for day, _ in endpoints],
            "expected_endpoint_classifications": [
                {"trading_day": day, "source_classification": classification}
                for day, classification in endpoints
            ],
            "expected_endpoints_sha256": sha256(canonical_json(endpoints)).hexdigest(),
            "source_fact_type": "mixed_valid_and_nonpositive_close",
            "operation": "CREATE_MIXED_UNION_PARTITION",
            "staging_state": "REQUIRES_IMMUTABLE_CANDIDATE_HASHES_BEFORE_APPLY",
        })
    targets.sort(key=lambda row: (row["symbol"], row["contract"], row["month"]))
    identities = [(row["symbol"], row["contract"], row["month"]) for row in targets]
    if len(identities) != len(set(identities)):
        raise ValueError("SUBING_D1_PLAN_DUPLICATE_TARGET")
    oi_pf = source_complete.get("oi_pf_september_18_independent_endpoints", {})
    if oi_pf.get("count") != 18 or oi_pf.get("classifications") != {
        "NONPOSITIVE_CLOSE_SOURCE_FACT": 10,
        "POSITIVE_OHLC_SOURCE_FACT": 8,
    }:
        raise ValueError("SUBING_D1_PLAN_OI_PF_CONFLICT")
    body: dict[str, Any] = {
        "schema": "subing-d1-quality-production-plan-v1",
        "mode": "PREPARE_ONLY",
        "fixed_cutoff": FIXED_CUTOFF,
        "provider_request_budget": 0,
        "production_writes": 0,
        "products": sorted(products),
        "product_count": len(products),
        "target_partition_count": len(targets),
        "targets": targets,
        "excluded_unrelated_lifecycle_target_count": excluded_target_count,
        "special_cases": {
            "oi_pf_2026_09": {
                "endpoint_count": 18,
                "valid_bar_count": 8,
                "nonpositive_close_break_count": 10,
                "required_union": "ValidCanonicalBar|ProvenNonpositiveCloseBreak",
            },
            "rs_latest_owner": {
                "valid_bar_count": 3,
                "research_status": "WARMING",
            },
        },
        "versions": {
            "quality_policy": "subing-d1-quality-segment-v1",
            "endpoint_union": "canonical-source-quality-union-v1",
            "reference_model": "subing_reference_reverse_close_quality_segment_v2",
            "formula": "subing_ths_1d_v1",
        },
        "apply_preconditions": {
            "maintenance_lock": "market-data-canonical-publication-exclusive-v1",
            "compare_old_pointer_and_hashes": True,
            "stage_validate_fsync_atomic_pointer_commit": True,
            "catalog_and_file_commit_are_one_recoverable_unit": True,
            "post_commit_strict_readback": True,
            "create_targets_require_staged_file_and_quality_hashes": True,
            "idempotent_already_applied_requires_exact_hash_match": True,
            "stale_pointer_or_hash": "ABORT_WITHOUT_WRITE",
            "partial_commit": "RESTORE_OLD_POINTER_AND_RETAIN_IMMUTABLE_FILE",
        },
        "input_evidence": {
            "impact_input_sha256": impact["input_file_sha256"],
            "source_plan_sha256": source_complete["plan_sha256"],
            "all_66_observed": source_complete["all_66_target_evidence"]["observed"],
            "existing_1207_closed": source_complete["existing_1207_anomaly_source_evidence"]["total_with_saved_source_evidence"],
        },
    }
    body["plan_sha256"] = sha256(canonical_json(body)).hexdigest()
    return body


def validate_apply_binding(plan: Mapping[str, Any], expected_plan_sha256: str) -> None:
    """Future apply guard. It validates binding only and never performs the apply."""
    body = dict(plan)
    actual = body.pop("plan_sha256", None)
    calculated = sha256(canonical_json(body)).hexdigest()
    if actual != calculated or actual != expected_plan_sha256:
        raise ValueError("SUBING_D1_PLAN_HASH_MISMATCH")
    if plan.get("mode") != "PREPARE_ONLY" or plan.get("provider_request_budget") != 0:
        raise ValueError("SUBING_D1_PLAN_MODE_CONFLICT")


def build_p9_quality_plan(
    inventory: Mapping[str, Any],
    source: Mapping[str, Any],
    inventory_file_sha256: str,
    source_file_sha256: str,
) -> dict[str, Any]:
    """Freeze P9's proven zero-close D1 Bars as replacement candidates only."""
    def digest(value: object) -> bool:
        return isinstance(value, str) and len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )

    if not all(digest(value) for value in (
        inventory_file_sha256,
        source_file_sha256,
        inventory.get("source_inventory_sha256"),
        source.get("inventory_file_sha256"),
        source.get("candidate_plan_sha256"),
        source.get("candidate_file_sha256"),
        source.get("journal_sha256"),
        source.get("result_sha256"),
    )) or inventory.get("source_inventory_sha256") != source.get("inventory_file_sha256"):
        raise ValueError("P9_SOURCE_IDENTITY_INVALID")
    items = inventory.get("targets")
    summary = inventory.get("summary")
    if (
        inventory.get("schema") != "reference_p9_d1_quality_inventory_v1"
        or inventory.get("readonly") is not True
        or not isinstance(items, list)
        or not isinstance(summary, Mapping)
        or not items
        or summary.get("targets") != len(items)
        or summary.get("states") != {"TARGETS_PRESENT": len(items)}
        or summary.get("quality_fact_targets") != 0
        or summary.get("missing_dates") != 0
    ):
        raise ValueError("P9_QUALITY_INVENTORY_INVALID")
    if (
        source.get("status") != "SOURCE_ZERO_CLOSE_CONFIRMED"
        or source.get("canonical_writes") != 0
        or source.get("database_writes") != 0
        or type(source.get("requests_started")) is not int
        or source["requests_started"] <= 0
        or source.get("responses_saved") != source["requests_started"]
        or source.get("target_date_identities") != summary.get("affected_dates")
        or source.get("target_rows_zero_close") != summary.get("affected_dates")
        or summary.get("zero_bar_targets") != summary.get("affected_dates")
    ):
        raise ValueError("P9_SOURCE_SCOPE_INVALID")

    targets: list[dict[str, Any]] = []
    identities: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("P9_QUALITY_TARGET_INVALID")
        symbol, contract, month = (
            item.get("product"), item.get("contract"), item.get("month")
        )
        days = item.get("affected_dates")
        uri = item.get("old_file_uri")
        try:
            year, month_number = (int(value) for value in str(month).split("-"))
            parsed_days = [date.fromisoformat(str(value)) for value in days]
            path = PurePosixPath(str(uri))
        except (TypeError, ValueError) as exc:
            raise ValueError("P9_QUALITY_TARGET_INVALID") from exc
        identity = (str(symbol), str(contract), str(month))
        if (
            not isinstance(symbol, str)
            or not isinstance(contract, str)
            or not isinstance(month, str)
            or month != f"{year:04d}-{month_number:02d}"
            or identity in identities
            or item.get("state") != "TARGETS_PRESENT"
            or type(item.get("partition_id")) is not int
            or item["partition_id"] <= 0
            or not digest(item.get("old_file_sha256"))
            or item.get("old_source_quality_sha256") is not None
            and not digest(item.get("old_source_quality_sha256"))
            or not isinstance(days, list)
            or not parsed_days
            or parsed_days != sorted(set(parsed_days))
            or any(day.year != year or day.month != month_number for day in parsed_days)
            or item.get("affected_count") != len(parsed_days)
            or item.get("target_zero_bars") != len(parsed_days)
            or item.get("target_quality_facts") != 0
            or item.get("target_missing") != 0
            or path.is_absolute()
            or ".." in path.parts
            or path.parts[:6] != (
                "kind=contract", f"symbol={symbol}", f"series={contract}",
                "frequency=1d", f"year={year:04d}", f"month={month_number:02d}",
            )
        ):
            raise ValueError("P9_QUALITY_TARGET_INVALID")
        identities.add(identity)
        targets.append({
            "symbol": symbol,
            "contract": contract,
            "month": month,
            "partition_id": item["partition_id"],
            "old_file_uri": uri,
            "old_file_sha256": item["old_file_sha256"],
            "old_source_quality_sha256": item["old_source_quality_sha256"],
            "affected_dates": [day.isoformat() for day in parsed_days],
            "source_fact_type": "nonpositive_close_source_quality",
            "operation": "REPLACE_EXISTING_PARTITION",
        })
    if sum(len(item["affected_dates"]) for item in targets) != summary["affected_dates"]:
        raise ValueError("P9_QUALITY_INVENTORY_INVALID")
    targets.sort(key=lambda row: (row["symbol"], row["contract"], row["month"]))
    products = sorted({item["symbol"] for item in targets})
    body: dict[str, Any] = {
        "schema": "subing-d1-quality-production-plan-v1",
        "mode": "PREPARE_ONLY",
        "fixed_cutoff": "2026-09-23T16:00:00+08:00",
        "provider_request_budget": 0,
        "production_writes": 0,
        "products": products,
        "product_count": len(products),
        "target_partition_count": len(targets),
        "targets": targets,
        "versions": {
            "quality_policy": "subing-d1-quality-segment-v1",
            "endpoint_union": "canonical-source-quality-union-v1",
            "reference_model": "subing_reference_reverse_close_quality_segment_v2",
            "formula": "subing_ths_1d_v1",
        },
        "apply_preconditions": {
            "maintenance_lock": "market-data-canonical-publication-exclusive-v1",
            "compare_old_pointer_and_hashes": True,
            "stage_validate_fsync_atomic_pointer_commit": True,
            "catalog_and_file_commit_are_one_recoverable_unit": True,
            "post_commit_strict_readback": True,
            "idempotent_already_applied_requires_exact_hash_match": True,
            "stale_pointer_or_hash": "ABORT_WITHOUT_WRITE",
            "partial_commit": "RESTORE_OLD_POINTER_AND_RETAIN_IMMUTABLE_FILE",
        },
        "input_evidence": {
            "quality_inventory_file_sha256": inventory_file_sha256,
            "source_summary_file_sha256": source_file_sha256,
            "source_inventory_file_sha256": source["inventory_file_sha256"],
            "source_candidate_plan_sha256": source["candidate_plan_sha256"],
            "source_candidate_file_sha256": source["candidate_file_sha256"],
            "source_journal_sha256": source["journal_sha256"],
            "source_result_sha256": source["result_sha256"],
        },
    }
    body["plan_sha256"] = sha256(canonical_json(body)).hexdigest()
    return body
