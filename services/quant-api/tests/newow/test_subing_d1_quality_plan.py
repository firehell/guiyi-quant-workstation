from copy import deepcopy

import pytest

from app.market_data.subing_d1_quality_plan import (
    build_p9_quality_plan,
    build_plan,
    validate_apply_binding,
)


def inputs():
    impact = {"fixed_cutoff": "2026-09-18T18:30:00+08:00", "input_file_sha256": {"evidence": "a" * 64}}
    evidence = {"fixed_cutoff": impact["fixed_cutoff"], "items": []}
    for index in range(17):
        symbol = f"p{index:02d}"
        evidence["items"].append({
            "symbol": symbol, "fact_type": "nonpositive_close_in_consumed_prefix",
            "catalog_partitions": [{
                "contract": f"P{index:02d}2609", "month": "2026-09",
                "partition_id": index + 1, "file_uri": f"old/{index}.parquet",
                "file_sha256": f"{index + 1:064x}", "source_quality_sha256": None,
                "affected_dates": ["2026-09-01"],
            }],
        })
    source = {
        "fixed_research_cutoff": impact["fixed_cutoff"], "plan_sha256": "b" * 64,
        "all_66_target_evidence": {"closed": True, "observed": 66},
        "existing_1207_anomaly_source_evidence": {"closed": True, "total_with_saved_source_evidence": 1207},
        "oi_pf_september_18_independent_endpoints": {"count": 18, "classifications": {"NONPOSITIVE_CLOSE_SOURCE_FACT": 10, "POSITIVE_OHLC_SOURCE_FACT": 8}},
        "date_results": [
            {"symbol": symbol, "contract": contract, "day": f"2026-09-{day:02d}",
             "fresh_classification": "POSITIVE_OHLC_SOURCE_FACT" if day <= 4 else "NONPOSITIVE_CLOSE_SOURCE_FACT"}
            for symbol, contract in (("oi", "OI2609"), ("pf", "PF2609"))
            for day in range(1, 10)
        ],
    }
    return impact, evidence, source


def test_plan_is_deterministic_bounded_and_hash_bound():
    first = build_plan(*inputs(), excluded_target_count=40)
    second = build_plan(*inputs(), excluded_target_count=40)
    assert first == second
    assert first["product_count"] == 17
    assert first["target_partition_count"] == 19
    assert first["provider_request_budget"] == first["production_writes"] == 0
    assert first["excluded_unrelated_lifecycle_target_count"] == 40
    assert first["special_cases"]["oi_pf_2026_09"] == {
        "endpoint_count": 18, "valid_bar_count": 8,
        "nonpositive_close_break_count": 10,
        "required_union": "ValidCanonicalBar|ProvenNonpositiveCloseBreak",
    }
    assert {
        (item["symbol"], item["contract"], item["month"], item["operation"])
        for item in first["targets"]
        if item["operation"] == "CREATE_MIXED_UNION_PARTITION"
    } == {
        ("oi", "OI2609", "2026-09", "CREATE_MIXED_UNION_PARTITION"),
        ("pf", "PF2609", "2026-09", "CREATE_MIXED_UNION_PARTITION"),
    }
    validate_apply_binding(first, first["plan_sha256"])


def test_plan_rejects_stale_scope_duplicates_and_hashes():
    impact, evidence, source = inputs()
    with pytest.raises(ValueError, match="INPUT_CONFLICT"):
        build_plan(impact, evidence, source, excluded_target_count=39)
    duplicate = deepcopy(evidence)
    duplicate["items"][1]["symbol"] = duplicate["items"][0]["symbol"]
    duplicate["items"][1]["catalog_partitions"][0].update(
        contract="P002609", month="2026-09", partition_id=1, file_uri="old/0.parquet"
    )
    with pytest.raises(ValueError, match="DUPLICATE_TARGET"):
        build_plan(impact, duplicate, source, excluded_target_count=40)
    plan = build_plan(impact, evidence, source, excluded_target_count=40)
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        validate_apply_binding(plan, "0" * 64)


def p9_inputs():
    inventory = {
        "schema": "reference_p9_d1_quality_inventory_v1",
        "readonly": True,
        "source_inventory_sha256": "a" * 64,
        "summary": {
            "targets": 1,
            "affected_dates": 2,
            "states": {"TARGETS_PRESENT": 1},
            "zero_bar_targets": 2,
            "quality_fact_targets": 0,
            "missing_dates": 0,
        },
        "targets": [{
            "product": "al",
            "contract": "AL2302",
            "month": "2022-02",
            "state": "TARGETS_PRESENT",
            "partition_id": 12,
            "old_file_uri": "kind=contract/symbol=al/series=AL2302/frequency=1d/year=2022/month=02/part.parquet",
            "old_file_sha256": "b" * 64,
            "old_source_quality_sha256": None,
            "affected_dates": ["2022-02-16", "2022-02-17"],
            "affected_count": 2,
            "target_zero_bars": 2,
            "target_quality_facts": 0,
            "target_missing": 0,
        }],
    }
    source = {
        "status": "SOURCE_ZERO_CLOSE_CONFIRMED",
        "inventory_file_sha256": "a" * 64,
        "candidate_plan_sha256": "c" * 64,
        "candidate_file_sha256": "d" * 64,
        "journal_sha256": "e" * 64,
        "result_sha256": "f" * 64,
        "target_date_identities": 2,
        "target_rows_zero_close": 2,
        "requests_started": 1,
        "responses_saved": 1,
        "canonical_writes": 0,
        "database_writes": 0,
    }
    return inventory, source


def test_p9_plan_freezes_existing_partition_and_source_evidence():
    inventory, source = p9_inputs()
    first = build_p9_quality_plan(inventory, source, "1" * 64, "2" * 64)
    second = build_p9_quality_plan(inventory, source, "1" * 64, "2" * 64)
    assert first == second
    assert first["mode"] == "PREPARE_ONLY"
    assert first["target_partition_count"] == 1
    assert first["provider_request_budget"] == first["production_writes"] == 0
    assert first["targets"][0]["affected_dates"] == ["2022-02-16", "2022-02-17"]
    assert first["targets"][0]["old_file_sha256"] == "b" * 64
    validate_apply_binding(first, first["plan_sha256"])


def test_p9_plan_rejects_unproven_or_missing_source_dates():
    inventory, source = p9_inputs()
    source["target_rows_zero_close"] = 1
    with pytest.raises(ValueError, match="P9_SOURCE_SCOPE_INVALID"):
        build_p9_quality_plan(inventory, source, "1" * 64, "2" * 64)
    inventory, source = p9_inputs()
    inventory["targets"][0]["target_missing"] = 1
    with pytest.raises(ValueError, match="P9_QUALITY_TARGET_INVALID"):
        build_p9_quality_plan(inventory, source, "1" * 64, "2" * 64)
