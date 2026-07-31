import hashlib
import json

import pytest

from app.data_core.historical_apply_gate import (
    HistoricalApplyGateError,
    build_apply_approval_packet,
    verify_apply_approval_packet,
)


STATE = {
    "catalog_digest": "c" * 64,
    "mapping_digest": "d" * 64,
    "calendar_digest": "e" * 64,
    "session_digest": "f" * 64,
    "dataset_write_plan_digest": "1" * 64,
    "mapping_complete": True,
    "missing_mapping_days": [],
    "trading_days": ["2023-01-03"],
    "session_windows": [
        {
            "trading_day": "2023-01-03",
            "start": "2023-01-03T01:00:00+00:00",
            "end": "2023-01-03T01:01:00+00:00",
        }
    ],
    "dataset_write_plan": [],
}
STATE["state_digest"] = hashlib.sha256(
    json.dumps(STATE, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()

FACTS = {
    "task_head": "a" * 40,
    "source_checkout": "/tmp/project",
    "migration_revisions": ["20260730_0026", "20260730_0027"],
    "scope": {
        "symbol": "jm",
        "provider": "rqdata",
        "schema_version": "canonical-bar-v1",
        "dataset_kinds": ["continuous", "actual_dominant"],
        "direct_frequencies": ["1m", "1d", "1w"],
        "direct_frequency_matrix": {
            "continuous": ["1m", "1d", "1w"],
            "actual_dominant": ["1m", "1d"],
        },
        "window": {
            "start": "2023-01-03T00:00:00+00:00",
            "end": "2025-12-31T23:59:59+00:00",
        },
        "contract_or_series": ["JM.MAIN", "JM2609"],
    },
    "plan_digest": "b" * 64,
    "mapping_write_plan": {
        "provider": "rqdata",
        "symbol": "jm",
        "rank": 1,
        "start_day": "2023-01-03",
        "end_day": "2023-01-03",
        "trading_days": ["2023-01-03"],
        "allowed_contracts": ["JM2609"],
    },
    "current_state": STATE,
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
        "partial_apply_receipt": "/tmp/data/parquet/data-core-v2/receipts/apply.json",
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


def test_historical_apply_packet_allows_exact_mapping_bootstrap_plan() -> None:
    state = {
        **STATE,
        "mapping_complete": False,
        "missing_mapping_days": ["2023-01-03"],
    }
    state.pop("state_digest")
    state["state_digest"] = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    facts = {**FACTS, "current_state": state}

    packet = build_apply_approval_packet(bound_facts=facts)

    verify_apply_approval_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=facts,
    )


def test_historical_apply_packet_rejects_any_bound_fact_drift() -> None:
    packet = build_apply_approval_packet(bound_facts=FACTS)

    with pytest.raises(HistoricalApplyGateError, match="approval_facts_changed"):
        verify_apply_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts={**FACTS, "task_head": "c" * 40},
        )


def test_historical_apply_packet_accepts_receipt_bound_progress_state() -> None:
    packet = build_apply_approval_packet(bound_facts=FACTS)
    progressed_state = {**STATE, "catalog_digest": "9" * 64}
    progressed_state.pop("state_digest")
    progressed_state["state_digest"] = hashlib.sha256(
        json.dumps(progressed_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    progressed_facts = {**FACTS, "current_state": progressed_state}
    receipt = {
        "schema_version": 1,
        "bound_facts_digest": packet["packet_hash"],
        "progress_state_digest": progressed_state["state_digest"],
        "mapping": {"status": "passed"},
        "datasets": {},
    }

    verify_apply_approval_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=progressed_facts,
        progress_receipt=receipt,
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
