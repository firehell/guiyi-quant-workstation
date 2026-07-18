from datetime import date
from types import SimpleNamespace

import duckdb

from app.services.rqdata_ingest.actual_dominant_roll_repair import (
    MAPPING_DATES,
    SUPERSEDE_PAIRS,
    WINNER_MANIFEST_IDS,
    build_mapping_operations,
    build_local_rebuild_operations,
    ledger_sha256,
    _build_local_parquet,
    _mapping_operation_state,
)


def test_repair_scope_is_frozen_to_eleven_mappings_ten_manifests_three_supersedes() -> None:
    assert len(MAPPING_DATES) == 11
    assert len(WINNER_MANIFEST_IDS) == 10
    assert SUPERSEDE_PAIRS == ((42428, 86646), (47880, 99695), (42446, 34104))
    operations = build_mapping_operations(existing_dates=set())
    assert len(operations) == 11
    assert {row["contract_code"] for row in operations} == {"JM2609"}
    assert {date.fromisoformat(row["trade_date"]) for row in operations} == set(MAPPING_DATES)


def test_mapping_plan_refuses_partially_populated_scope_and_hash_is_stable() -> None:
    try:
        build_mapping_operations(existing_dates={date(2026, 7, 10)})
    except ValueError as exc:
        assert "before-state drift" in str(exc)
    else:
        raise AssertionError("expected before-state drift")
    operations = build_mapping_operations(existing_dates=set())
    assert ledger_sha256(operations) == ledger_sha256(list(reversed(list(reversed(operations)))))


def test_mapping_apply_is_idempotent_only_for_the_exact_batch_row() -> None:
    operation = build_mapping_operations(existing_dates=set())[0]
    exact = SimpleNamespace(
        id=10,
        contract_code="JM2609",
        provider="rqdata",
        rule="volume_open_interest",
        rank=1,
        data_version="actual_dominant_roll_006_local_evidence_v1",
    )
    conflict = SimpleNamespace(**{**vars(exact), "id": 11, "contract_code": "JM2605"})

    assert _mapping_operation_state([], operation) == ("insert", None)
    assert _mapping_operation_state([exact], operation) == ("noop", 10)
    try:
        _mapping_operation_state([conflict], operation)
    except ValueError as exc:
        assert "mapping before-state drift" in str(exc)
    else:
        raise AssertionError("expected conflicting row to fail closed")


def test_local_rebuild_scope_is_only_two_jm2609_assets_for_three_days() -> None:
    operations = build_local_rebuild_operations()
    assert [(row["contract_code"], row["period"]) for row in operations] == [("JM2609", "1d"), ("JM2609", "1m")]
    assert {row["start_date"] for row in operations} == {"2026-07-08"}
    assert {row["end_date"] for row in operations} == {"2026-07-10"}


def test_local_daily_parquet_uses_canonical_interval_column(tmp_path) -> None:
    source = tmp_path / "raw.parquet"
    output = tmp_path / "canonical.parquet"
    with duckdb.connect() as connection:
        connection.execute("""COPY (SELECT 'JM2609' AS order_book_id, TIMESTAMP '2026-07-08' AS date,
            1.0 AS open, 2.0 AS high, 0.5 AS low, 1.5 AS close, 10.0 AS volume, 100.0 AS total_turnover,
            20.0 AS open_interest, TIMESTAMP '2026-07-08' AS datetime) TO ? (FORMAT PARQUET)""", [str(source)])

    _build_local_parquet(source=source, output=output, period="1d", data_version="test-v1")

    with duckdb.connect() as connection:
        row = connection.execute('SELECT "interval", period, trading_day FROM read_parquet(?)', [str(output)]).fetchone()
    assert row == ("1d", "1d", date(2026, 7, 8))
