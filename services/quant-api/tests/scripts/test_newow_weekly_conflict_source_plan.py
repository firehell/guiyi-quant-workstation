from __future__ import annotations

import pytest

from scripts.newow_weekly_conflict_source_plan import build_source_plan


def _week(contract: str, symbol: str, days: list[str], *, iso_year: int, iso_week: int, cross_month: bool = False):
    return {
        "iso_year": iso_year,
        "iso_week": iso_week,
        "week_end": f"{days[-1]}T07:00:00+00:00",
        "trading_day": days[-1],
        "daily_trading_days": days,
        "cross_month": cross_month,
        "numeric_conflict_fields": ["turnover"],
        "stored_w1_partition": {
            "year": int(days[-1][:4]),
            "month": int(days[-1][5:7]),
            "file_name": f"part.{contract.lower()}.parquet",
            "row_count": 1,
            "source_quality_sha256": None,
        },
        "d1_partitions": [
            {
                "year": int(days[0][:4]),
                "month": int(days[0][5:7]),
                "file_name": f"part.{contract.lower()}-d1.parquet",
                "row_count": 5,
                "source_quality_sha256": None,
            }
        ],
        "identity": {"contract_owner_equal": True},
    }


def _diagnosis() -> dict[str, object]:
    return {
        "schema_version": "newow_weekly_conflict_diagnosis_v2",
        "status": "diagnosed",
        "as_of": "2026-09-18T07:00:00.000001+00:00",
        "catalog_revision_before": "a" * 64,
        "catalog_revision_after": "a" * 64,
        "catalog_revision_stable": True,
        "code_sha": "b" * 40,
        "input_sha256": "c" * 64,
        "contracts": [
            {
                "symbol": "b",
                "contract": "B2501",
                "requested_through": "2024-12-19",
                "classification": "SOURCE_VERIFICATION_REQUIRED",
                "conflict_weeks": [
                    _week("B2501", "b", ["2024-10-21", "2024-10-22", "2024-10-23", "2024-10-24", "2024-10-25"], iso_year=2024, iso_week=43),
                ],
            },
            {
                "symbol": "b",
                "contract": "B2609",
                "requested_through": "2026-08-14",
                "classification": "SOURCE_VERIFICATION_REQUIRED",
                "conflict_weeks": [
                    _week("B2609", "b", ["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"], iso_year=2026, iso_week=26),
                    _week("B2609", "b", ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"], iso_year=2026, iso_week=33),
                ],
            },
            {
                "symbol": "cj",
                "contract": "CJ2601",
                "requested_through": "2025-12-09",
                "classification": "SOURCE_VERIFICATION_REQUIRED",
                "conflict_weeks": [
                    {
                        **_week(
                            "CJ2601",
                            "cj",
                            ["2025-06-30", "2025-07-01", "2025-07-02", "2025-07-03", "2025-07-04"],
                            iso_year=2025,
                            iso_week=27,
                            cross_month=True,
                        ),
                        "d1_partitions": [
                            {
                                "year": 2025,
                                "month": 6,
                                "file_name": "part.cj2601-d1-06.parquet",
                                "row_count": 20,
                                "source_quality_sha256": None,
                            },
                            {
                                "year": 2025,
                                "month": 7,
                                "file_name": "part.cj2601-d1-07.parquet",
                                "row_count": 23,
                                "source_quality_sha256": None,
                            },
                        ],
                    },
                ],
            },
        ],
    }


def test_plan_emits_one_exchange_daily_request_per_conflict_week_without_merging():
    plan = build_source_plan(_diagnosis())

    assert plan["schema_version"] == "newow_weekly_conflict_source_plan_v1"
    assert plan["method"] == "futures.get_exchange_daily"
    assert plan["canonical_writes_allowed"] is False
    assert plan["database_writes_allowed"] is False
    assert plan["retry_allowed"] is False
    assert plan["request_count"] == 4
    assert plan["expected_source_rows"] == 20
    assert [item["contract"] for item in plan["requests"]] == ["B2501", "B2609", "B2609", "CJ2601"]
    assert plan["requests"][1]["expected_dates"] == [
        "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
    ]
    assert plan["requests"][2]["expected_dates"] == [
        "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
    ]
    cj = plan["requests"][3]
    assert cj["start"] == "2025-06-30"
    assert cj["end"] == "2025-07-04"
    assert cj["cross_month"] is True
    assert [item["file_name"] for item in cj["d1_partitions"]] == [
        "part.cj2601-d1-06.parquet",
        "part.cj2601-d1-07.parquet",
    ]
    assert all(item["method"] == "futures.get_exchange_daily" for item in plan["requests"])
    assert len({item["request_sha256"] for item in plan["requests"]}) == 4
    assert len(plan["plan_sha256"]) == 64


def test_plan_rejects_merging_unrelated_contracts_or_nonadjacent_weeks():
    diagnosis = _diagnosis()
    diagnosis["contracts"][0]["conflict_weeks"].append(
        {
            **_week("B2505", "b", ["2024-12-16", "2024-12-17", "2024-12-18", "2024-12-19", "2024-12-20"], iso_year=2024, iso_week=51),
            "contract": "B2505",
        }
    )

    with pytest.raises(ValueError, match="SOURCE_PLAN_CONTRACT_MISMATCH"):
        build_source_plan(diagnosis)
