import pytest

from app.data_core.historical_apply_gate import (
    HistoricalApplyGateError,
    build_apply_approval_packet,
    verify_apply_approval_packet,
)


FACTS = {
    "task_head": "a" * 40,
    "migration_revisions": ["20260730_0026", "20260730_0027"],
    "scope": {
        "symbol": "jm",
        "provider": "rqdata",
        "schema_version": "canonical-bar-v1",
        "dataset_kinds": ["continuous", "actual_dominant"],
        "direct_frequencies": ["1m", "1d", "1w"],
        "window": {
            "start": "2023-01-03T00:00:00+00:00",
            "end": "2025-12-31T23:59:59+00:00",
        },
        "contract_or_series": ["JM.MAIN", "JM2609"],
    },
    "plan_digest": "b" * 64,
    "write_set": {
        "canonical_root": "/tmp/data/parquet/data-core-v2/canonical",
        "staging_root": "/tmp/data/parquet/data-core-v2/staging",
        "postgresql_target": {
            "drivername": "postgresql+psycopg",
            "username": "guiyi",
            "host": "127.0.0.1",
            "port": 5432,
            "database": "guiyi_quant",
        },
        "postgresql_tables": [
            "market_datasets",
            "market_partitions",
            "data_gaps",
            "main_contract_map",
        ],
        "writes_legacy_market_data_assets": False,
    },
    "rollback": {
        "deletes_physical_data": False,
        "strategy": "keep_legacy_readonly_and_disable_canonical_consumer",
    },
}


def test_historical_apply_packet_binds_head_migrations_scope_and_plan_digest() -> None:
    packet = build_apply_approval_packet(bound_facts=FACTS)

    verify_apply_approval_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=FACTS,
    )


def test_historical_apply_packet_rejects_any_bound_fact_drift() -> None:
    packet = build_apply_approval_packet(bound_facts=FACTS)

    with pytest.raises(HistoricalApplyGateError, match="approval_facts_changed"):
        verify_apply_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts={**FACTS, "task_head": "c" * 40},
        )


def test_historical_apply_packet_rejects_window_drift() -> None:
    packet = build_apply_approval_packet(bound_facts=FACTS)
    changed_scope = {
        **FACTS["scope"],
        "window": {
            "start": "2023-01-03T00:00:00+00:00",
            "end": "2026-01-01T00:00:00+00:00",
        },
    }

    with pytest.raises(HistoricalApplyGateError, match="approval_facts_changed"):
        verify_apply_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts={**FACTS, "scope": changed_scope},
        )


def test_historical_apply_packet_rejects_non_jm_or_adjusted_series_identity() -> None:
    changed_scope = {
        **FACTS["scope"],
        "contract_or_series": ["JM.MAIN", "JM2609", "RB2610"],
    }

    with pytest.raises(HistoricalApplyGateError, match="approval_facts_invalid"):
        build_apply_approval_packet(
            bound_facts={**FACTS, "scope": changed_scope}
        )


def test_historical_apply_packet_rejects_roots_outside_data_core_v2_layout() -> None:
    changed_write_set = {
        **FACTS["write_set"],
        "canonical_root": "/tmp/guiyi-canonical",
        "staging_root": "/tmp/guiyi-staging",
    }

    with pytest.raises(HistoricalApplyGateError, match="approval_facts_invalid"):
        build_apply_approval_packet(
            bound_facts={**FACTS, "write_set": changed_write_set}
        )
