from __future__ import annotations

import csv
from datetime import date
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import Contract, Exchange, Instrument
from app.services.rqdata_ingest.full_history_audit_v2 import (
    AuditV2Config,
    _actual_range_rows,
    _quality_status,
    build_expected_windows,
    run_full_history_audit_v2,
    write_full_history_audit_v2_reports,
)
from app.services.rqdata_ingest.full_history_contract import ActualRank1Range


GOLDEN = {
    "a": {"listing": "2002-03-15", "1m": "2010-01-04", "1d": "2002-03-15", "1w": "2002-03-15"},
    "al": {"listing": "1999-01-04", "1m": "2010-01-04", "1d": "2000-01-05", "1w": "2000-01-07"},
    "ag": {"listing": "2012-05-10", "1m": "2012-05-10", "1d": "2012-05-10", "1w": "2012-05-11"},
    "jm": {"listing": "2013-03-22", "1m": "2013-03-22", "1d": "2013-03-22", "1w": "2013-03-22"},
}


def _inventory_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for product, values in GOLDEN.items():
        for period in ("1m", "1d", "1w"):
            rows.append(
                {
                    "product": product,
                    "contract_role": "dominant_main",
                    "contract": f"{product}.MAIN",
                    "period": period,
                    "provider": "rqdata",
                    "data_role": "primary",
                    "data_version": "golden",
                    "physical_path": f"/tmp/{product}_{period}.parquet",
                    "physical_exists": True,
                    "physical_status": "readable",
                    "physical_min_datetime": values[period],
                    "physical_max_datetime": "2026-07-10",
                    "row_count": 1,
                    "schema_status": "valid",
                    "schema_consistency_status": "consistent",
                    "manifest_record_count": 1,
                    "db_record_count": 1,
                    "quality_statuses": '["passed"]',
                    "identity_conflict": False,
                    "source_interval": "[]",
                }
            )
    return rows


def test_golden_products_use_dynamic_supported_boundaries() -> None:
    rows = build_expected_windows(
        _inventory_rows(),
        listing_dates={product: date.fromisoformat(values["listing"]) for product, values in GOLDEN.items()},
        audit_end=date(2026, 7, 10),
        provider_evidence={},
        trading_days_by_product={},
    )

    keyed = {(row["product"], row["period"], row["source_role"]): row for row in rows}
    for product, values in GOLDEN.items():
        for period in ("1m", "1d", "1w"):
            row = keyed[(product, period, "direct")]
            assert row["target_start"] == values[period]
            assert row["target_end"] == "2026-07-10"
            assert row["boundary_status"] in {"start_boundary_supported", "start_boundary_unverified"}
    assert keyed[("ag", "1w", "direct")]["target_start"] == "2012-05-11"
    assert keyed[("jm", "1m", "direct")]["target_start"] != "2010-01-04"
    assert all("partial_or_missing_pre2020" not in json.dumps(row) for row in rows)


def test_derived_day_is_separate_from_direct_day_and_inherits_minute() -> None:
    rows = build_expected_windows(
        _inventory_rows(),
        listing_dates={product: date.fromisoformat(values["listing"]) for product, values in GOLDEN.items()},
        audit_end=date(2026, 7, 10),
        provider_evidence={},
        trading_days_by_product={},
    )
    al_days = [row for row in rows if row["product"] == "al" and row["period"] == "1d"]
    assert {(row["source_role"], row["target_start"]) for row in al_days} == {
        ("direct", "2000-01-05"),
        ("derived_from_1m", "2010-01-04"),
    }


def test_product_listed_after_audit_end_is_not_applicable() -> None:
    rows = build_expected_windows(
        [],
        listing_dates={"future": date(2027, 1, 1)},
        audit_end=date(2026, 7, 10),
        provider_evidence={},
        trading_days_by_product={},
    )
    assert rows
    assert {row["boundary_status"] for row in rows} == {"not_applicable"}
    assert all(not row["target_start"] for row in rows)


def test_actual_rank1_rows_use_direct_supported_starts_and_have_no_duplicates() -> None:
    expected = build_expected_windows(
        [row for row in _inventory_rows() if row["product"] == "jm"],
        listing_dates={"jm": date.fromisoformat(GOLDEN["jm"]["listing"])},
        audit_end=date(2026, 7, 10),
        provider_evidence={},
        trading_days_by_product={},
    )
    duplicate_range = ActualRank1Range(
        product="jm",
        contract="JM1305",
        start=date(2013, 3, 1),
        end=date(2013, 3, 25),
    )

    rows = _actual_range_rows((duplicate_range, duplicate_range), date(2026, 7, 10), expected)

    assert [(row["period"], row["expected_start"]) for row in rows] == [
        ("1d", "2013-03-22"),
        ("1m", "2013-03-22"),
    ]


def test_quality_gate_prefers_direct_db_evidence_and_retains_processed_provenance() -> None:
    row = {
        "quality_statuses": '["failed", "passed", "warning"]',
        "quality_statuses_manifest": '["passed"]',
        "quality_statuses_processed": '["failed"]',
        "quality_statuses_db": '["warning"]',
    }

    assert _quality_status([row]) == "warning"


def test_different_versions_do_not_create_path_conflict() -> None:
    rows = [row for row in _inventory_rows() if row["product"] == "a" and row["period"] == "1d"]
    duplicate = dict(rows[0])
    duplicate["physical_path"] = "/tmp/a_older_1d.parquet"
    duplicate["data_version"] = "older_version"
    windows = build_expected_windows(
        rows + [duplicate],
        listing_dates={"a": date(2002, 3, 15)},
        audit_end=date(2026, 7, 10),
        provider_evidence={},
        trading_days_by_product={},
    )
    direct = next(row for row in windows if row["period"] == "1d" and row["source_role"] == "direct")
    assert direct["target_start"] == "2002-03-15"


def test_authoritative_provider_evidence_resolves_boundary() -> None:
    rows = build_expected_windows(
        _inventory_rows(),
        listing_dates={"jm": date(2013, 3, 22)},
        audit_end=date(2026, 7, 10),
        provider_evidence={
            ("jm", "1m"): {"first_valid_bar": "2013-03-22", "authoritative": True},
        },
        trading_days_by_product={},
    )
    minute = next(row for row in rows if row["period"] == "1m" and row["source_role"] == "direct")
    assert minute["provider_authoritative_start"] == "2013-03-22"
    assert minute["boundary_status"] == "resolved"


def test_run_is_smoke_for_filtered_scope_and_writer_refuses_existing_v2(tmp_path: Path) -> None:
    inventory_dir = tmp_path / "inventory"
    inventory_dir.mkdir()
    rows = [row for row in _inventory_rows() if row["product"] == "a"]
    conflicting = dict(next(row for row in rows if row["period"] == "1d"))
    conflicting["physical_path"] = "/tmp/a_same_version_other_path.parquet"
    rows.append(conflicting)
    with (inventory_dir / "physical_inventory.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (inventory_dir / "inventory_summary.json").write_text(
        json.dumps({"status": "FULL_HISTORY_PHYSICAL_INVENTORY_READY", "db_snapshot_source": "direct_postgresql"}),
        encoding="utf-8",
    )
    session = Session(
        create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    Base.metadata.create_all(session.get_bind())
    session.add(Exchange(code="DCE", name="Dalian"))
    session.add(Instrument(symbol="a", name="Soybean", exchange_code="DCE"))
    session.add(
        Contract(
            contract_code="A0001",
            instrument_symbol="a",
            exchange_code="DCE",
            product="a",
            listed_date=date(2002, 3, 15),
            provider="rqdata",
        )
    )
    session.commit()

    result = run_full_history_audit_v2(
        AuditV2Config(
            project_root=tmp_path,
            inventory_dir=inventory_dir,
            products=("a",),
            require_postgresql=False,
        ),
        session,
    )
    assert result.summary["status"] == "FULL_HISTORY_AUDIT_V2_SMOKE_READY"
    assert result.summary["writes_database"] is False
    assert result.summary["writes_parquet"] is False
    assert result.summary["calls_rqdata"] is False
    direct_day = next(
        row
        for row in result.asset_layer_matrix
        if row["period"] == "1d" and row["source_role"] == "direct"
    )
    assert direct_day["physical_coverage"] == "conflict"
    output_dir = tmp_path / "reports"
    paths = write_full_history_audit_v2_reports(result, output_dir)
    assert paths["summary"].exists()
    with pytest.raises(FileExistsError, match="OUTPUT_EXISTS"):
        write_full_history_audit_v2_reports(result, output_dir)
