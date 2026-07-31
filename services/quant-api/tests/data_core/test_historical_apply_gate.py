import hashlib
import json

import pytest

from app.data_core.historical_apply_gate import (
    HistoricalApplyGateError,
    build_apply_approval_packet,
    load_apply_approval_packet,
    verify_approved_apply_progress,
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
    "catalog_items": [],
    "mapping_rows": [],
    "dataset_write_plan": [],
}
STATE["catalog_digest"] = hashlib.sha256(
    json.dumps({"items": []}, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
STATE["mapping_digest"] = hashlib.sha256(
    json.dumps({"rows": []}, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
STATE["dataset_write_plan_digest"] = hashlib.sha256(
    json.dumps({"plans": []}, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
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


def test_full_history_sized_approval_packet_can_be_loaded(tmp_path) -> None:
    state = {
        **STATE,
        "session_windows": [
            {
                "trading_day": "2023-01-03",
                "start": "2023-01-03T01:00:00+00:00",
                "end": "2023-01-03T01:01:00+00:00",
            }
            for _ in range(33_000)
        ],
    }
    state.pop("state_digest")
    state["state_digest"] = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    packet = build_apply_approval_packet(
        bound_facts={**FACTS, "current_state": state}
    )
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(
        json.dumps(packet, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    assert packet_path.stat().st_size > 2 * 1024 * 1024
    assert load_apply_approval_packet(
        packet_path,
        approval_hash=packet["packet_hash"],
    ) == packet


def test_approval_packet_still_rejects_files_over_four_mebibytes(tmp_path) -> None:
    packet_path = tmp_path / "oversized-approval.json"
    packet_path.write_bytes(b"{" + b" " * (4 * 1024 * 1024))

    with pytest.raises(
        HistoricalApplyGateError,
        match="approval_packet_path_invalid",
    ):
        load_apply_approval_packet(packet_path, approval_hash="a" * 64)


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


def test_editable_receipt_cannot_authorize_unapproved_state_drift() -> None:
    packet = build_apply_approval_packet(bound_facts=FACTS)
    progressed_state = {**STATE, "calendar_digest": "9" * 64}
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

    with pytest.raises(HistoricalApplyGateError, match="approval_facts_changed"):
        verify_apply_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_facts=progressed_facts,
            progress_receipt=receipt,
        )


def test_mapping_commit_before_receipt_is_reconstructed_from_approved_plan() -> None:
    initial_state = {
        **STATE,
        "mapping_complete": False,
        "missing_mapping_days": ["2023-01-03"],
    }
    initial_state.pop("state_digest")
    initial_state["state_digest"] = hashlib.sha256(
        json.dumps(initial_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    approved_facts = {**FACTS, "current_state": initial_state}
    packet = build_apply_approval_packet(bound_facts=approved_facts)
    mapping_row = {
        "symbol": "jm",
        "trading_day": "2023-01-03",
        "actual_contract": "JM2609",
        "rank": 1,
        "data_version": "rqdata-v1",
    }
    progressed_state = {
        **initial_state,
        "mapping_digest": hashlib.sha256(
            json.dumps(
                {"rows": [mapping_row]},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "mapping_complete": True,
        "missing_mapping_days": [],
        "mapping_rows": [mapping_row],
    }
    progressed_state.pop("state_digest")
    progressed_state["state_digest"] = hashlib.sha256(
        json.dumps(progressed_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    progressed_facts = {**approved_facts, "current_state": progressed_state}

    progress = verify_approved_apply_progress(
        approved_facts,
        progressed_facts,
        verify_partition=lambda _dataset, _partition: True,
    )
    verify_apply_approval_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_facts=progressed_facts,
        verified_progress=progress,
    )

    assert progress.mapping_rows == (mapping_row,)


def test_dataset_commit_before_receipt_requires_physical_partition_verification() -> None:
    initial_state = {
        **STATE,
        "mapping_complete": False,
        "missing_mapping_days": ["2023-01-03"],
    }
    initial_state.pop("state_digest")
    initial_state["state_digest"] = hashlib.sha256(
        json.dumps(initial_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    approved_facts = {**FACTS, "current_state": initial_state}
    dataset = {
        "provider": "rqdata",
        "dataset_kind": "continuous",
        "symbol": "jm",
        "contract_or_series": "JM.MAIN",
        "frequency": "1m",
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }
    partition = {
        "coverage_start": "2023-01-03T00:00:00+00:00",
        "coverage_end": "2025-12-31T23:59:59+00:00",
        "manifest_digest": "3" * 64,
        "checksum": "4" * 64,
        "file_uri": "dataset/part.parquet",
        "manifest_uri": "dataset/part.manifest.json",
    }
    catalog_items = [{"dataset": dataset, "partitions": [partition], "gaps": []}]
    write_plans = [{
        "dataset": dataset,
        "mapping_valid_windows": [[
            "2023-01-03T00:00:00+00:00",
            "2025-12-31T23:59:59+00:00",
        ]],
        "missing_windows": [],
    }]
    progressed_state = {
        **initial_state,
        "catalog_items": catalog_items,
        "catalog_digest": hashlib.sha256(
            json.dumps(
                {"items": catalog_items}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "dataset_write_plan": write_plans,
        "dataset_write_plan_digest": hashlib.sha256(
            json.dumps(
                {"plans": write_plans}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }
    progressed_state.pop("state_digest")
    progressed_state["state_digest"] = hashlib.sha256(
        json.dumps(progressed_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    observed = []

    progress = verify_approved_apply_progress(
        approved_facts,
        {**approved_facts, "current_state": progressed_state},
        verify_partition=lambda actual_dataset, actual_partition: (
            observed.append((actual_dataset, actual_partition)) or True
        ),
    )

    assert observed == [(dataset, partition)]
    assert progress.completed_datasets == ({
        "dataset": dataset,
        "partition_evidence": [partition],
    },)


def test_progress_rejects_tampered_dataset_write_plan_digest() -> None:
    progressed_state = dict(STATE)
    progressed_state["dataset_write_plan_digest"] = "9" * 64
    progressed_state.pop("state_digest")
    progressed_state["state_digest"] = hashlib.sha256(
        json.dumps(progressed_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with pytest.raises(HistoricalApplyGateError) as exc_info:
        verify_approved_apply_progress(
            FACTS,
            {**FACTS, "current_state": progressed_state},
            verify_partition=lambda _dataset, _partition: True,
        )

    assert exc_info.value.code == "approval_facts_changed"


def test_progress_rejects_unverified_existing_partition() -> None:
    dataset = {
        "provider": "rqdata",
        "dataset_kind": "continuous",
        "symbol": "jm",
        "contract_or_series": "JM.MAIN",
        "frequency": "1m",
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }
    partition = {
        "coverage_start": "2023-01-03T00:00:00+00:00",
        "coverage_end": "2025-12-31T23:59:59+00:00",
        "manifest_digest": "3" * 64,
        "checksum": "4" * 64,
    }
    catalog_items = [{"dataset": dataset, "partitions": [partition], "gaps": []}]
    write_plans = [{
        "dataset": dataset,
        "mapping_valid_windows": [[
            "2023-01-03T00:00:00+00:00",
            "2025-12-31T23:59:59+00:00",
        ]],
        "missing_windows": [],
    }]
    initial_state = {
        **STATE,
        "mapping_complete": False,
        "missing_mapping_days": ["2023-01-03"],
        "catalog_items": catalog_items,
        "catalog_digest": hashlib.sha256(
            json.dumps(
                {"items": catalog_items}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "dataset_write_plan": write_plans,
        "dataset_write_plan_digest": hashlib.sha256(
            json.dumps(
                {"plans": write_plans}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }
    initial_state.pop("state_digest")
    initial_state["state_digest"] = hashlib.sha256(
        json.dumps(initial_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    facts = {**FACTS, "current_state": initial_state}

    with pytest.raises(HistoricalApplyGateError) as exc_info:
        verify_approved_apply_progress(
            facts,
            facts,
            verify_partition=lambda _dataset, _partition: False,
        )

    assert exc_info.value.code == "approval_progress_partition_invalid"


def test_partial_partition_cannot_be_declared_completed_by_cached_plan() -> None:
    initial_state = {
        **STATE,
        "mapping_complete": False,
        "missing_mapping_days": ["2023-01-03"],
    }
    initial_state.pop("state_digest")
    initial_state["state_digest"] = hashlib.sha256(
        json.dumps(initial_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    approved_facts = {**FACTS, "current_state": initial_state}
    dataset = {
        "provider": "rqdata",
        "dataset_kind": "continuous",
        "symbol": "jm",
        "contract_or_series": "JM.MAIN",
        "frequency": "1m",
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }
    partition = {
        "coverage_start": "2023-01-03T01:00:00+00:00",
        "coverage_end": "2023-01-03T01:01:00+00:00",
        "manifest_digest": "3" * 64,
        "checksum": "4" * 64,
    }
    catalog_items = [{"dataset": dataset, "partitions": [partition], "gaps": []}]
    write_plans = [{
        "dataset": dataset,
        "mapping_valid_windows": [[
            "2023-01-03T00:00:00+00:00",
            "2025-12-31T23:59:59+00:00",
        ]],
        "missing_windows": [],
    }]
    progressed_state = {
        **initial_state,
        "catalog_items": catalog_items,
        "catalog_digest": hashlib.sha256(
            json.dumps(
                {"items": catalog_items}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "dataset_write_plan": write_plans,
        "dataset_write_plan_digest": hashlib.sha256(
            json.dumps(
                {"plans": write_plans}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }
    progressed_state.pop("state_digest")
    progressed_state["state_digest"] = hashlib.sha256(
        json.dumps(progressed_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with pytest.raises(HistoricalApplyGateError) as exc_info:
        verify_approved_apply_progress(
            approved_facts,
            {**approved_facts, "current_state": progressed_state},
            verify_partition=lambda _dataset, _partition: True,
        )

    assert exc_info.value.code == "approval_facts_changed"


def test_unapproved_catalog_dataset_drift_is_rejected() -> None:
    initial_state = {
        **STATE,
        "mapping_complete": False,
        "missing_mapping_days": ["2023-01-03"],
    }
    initial_state.pop("state_digest")
    initial_state["state_digest"] = hashlib.sha256(
        json.dumps(initial_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    approved_facts = {**FACTS, "current_state": initial_state}
    bad_item = {
        "dataset": {
            "provider": "rqdata", "dataset_kind": "continuous", "symbol": "rb",
            "contract_or_series": "RB.MAIN", "frequency": "1m",
            "adjustment": "none", "schema_version": "canonical-bar-v1",
        },
        "partitions": [], "gaps": [],
    }
    progressed = {**initial_state, "catalog_items": [bad_item]}
    progressed["catalog_digest"] = hashlib.sha256(
        json.dumps(
            {"items": [bad_item]}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    progressed.pop("state_digest")
    progressed["state_digest"] = hashlib.sha256(
        json.dumps(progressed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    with pytest.raises(HistoricalApplyGateError, match="approval_facts_changed"):
        verify_approved_apply_progress(
            approved_facts,
            {**approved_facts, "current_state": progressed},
            verify_partition=lambda _dataset, _partition: True,
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
