"""Pure, non-applying plan builder for the approved SuBing D1 quality contract."""

from __future__ import annotations

from hashlib import sha256
import json
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
