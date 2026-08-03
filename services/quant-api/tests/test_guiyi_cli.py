from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
import hashlib
from io import StringIO
import json
from pathlib import Path

from app.data_core.historical_apply_gate import (
    build_apply_approval_packet,
    expected_partial_apply_receipt_path,
)
from app.guiyi_cli.main import main


class _NoSessionFactory:
    def __call__(self):
        raise AssertionError("runtime plan must not open a database session")


def test_data_core_plan_uses_explicit_identity_and_window() -> None:
    stdout = StringIO()
    stderr = StringIO()
    observed = {}

    def run(command, _session, args):
        observed.update({"command": command, "args": vars(args)})
        return {
            "schema_version": 1,
            "command": "data.plan",
            "status": "planned",
            "readonly": True,
            "effects": {
                "calls_rqdata": False,
                "writes_postgresql": False,
                "writes_parquet": False,
            },
        }

    exit_code = main(
        [
            "data",
            "plan",
            "--dataset-kind",
            "actual_dominant",
            "--symbol",
            "jm",
            "--contract-or-series",
            "JM2609",
            "--frequency",
            "1m",
            "--start",
            "2026-07-01T01:00:00Z",
            "--end",
            "2026-07-01T02:00:00Z",
        ],
        session_factory=lambda: nullcontext(object()),
        data_core_runner=run,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["status"] == "planned"
    assert observed["command"] == "plan"
    assert observed["args"]["dataset_kind"] == "actual_dominant"


def test_data_core_apply_is_blocked_before_opening_database_without_gate() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "sync",
            "--apply",
            "--dataset-kind",
            "actual_dominant",
            "--symbol",
            "jm",
            "--contract-or-series",
            "JM2609",
            "--frequency",
            "1m",
            "--start",
            "2026-07-01T01:00:00Z",
            "--end",
            "2026-07-01T02:00:00Z",
        ],
        session_factory=_NoSessionFactory(),
        data_core_runner=lambda *_args: (_ for _ in ()).throw(
            AssertionError("must not dispatch")
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 78
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["code"] == (
        "JM_REAL_DATA_GATE_REQUIRED"
    )


def test_data_core_apply_with_packet_stays_blocked_until_exact_authorization() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "sync",
            "--apply",
            "--dataset-kind",
            "actual_dominant",
            "--symbol",
            "jm",
            "--contract-or-series",
            "JM2609",
            "--frequency",
            "1m",
            "--start",
            "2026-07-01T01:00:00Z",
            "--end",
            "2026-07-01T02:00:00Z",
            "--approval-packet",
            "/tmp/task04-packet.json",
            "--approval-hash",
            "a" * 64,
        ],
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 78
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["code"] == (
        "JM_REAL_DATA_APPLY_NOT_AUTHORIZED"
    )


def _migrate_apply_facts() -> dict[str, object]:
    session_policy = {"policy_version": "fixture"}
    state = {
        "catalog_digest": "c" * 64,
        "mapping_digest": "d" * 64,
        "calendar_digest": "e" * 64,
        "session_digest": "f" * 64,
        "session_policy": session_policy,
        "session_policy_digest": hashlib.sha256(
            json.dumps(
                session_policy,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "dataset_write_plan_digest": "1" * 64,
        "mapping_complete": True,
        "missing_mapping_days": [],
        "trading_days": ["2026-07-01"],
        "session_windows": [
            {
                "trading_day": "2026-07-01",
                "start": "2026-07-01T01:00:00+00:00",
                "end": "2026-07-01T01:01:00+00:00",
            }
        ],
        "catalog_items": [],
        "mapping_rows": [
            {
                "symbol": "jm",
                "trading_day": "2026-07-01",
                "actual_contract": "JM2609",
                "rank": 1,
                "data_version": "rqdata-test-rank1",
            }
        ],
        "dataset_write_plan": [],
    }
    state["catalog_digest"] = hashlib.sha256(
        json.dumps({"items": []}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    state["mapping_digest"] = hashlib.sha256(
        json.dumps(
            {"rows": state["mapping_rows"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    state["dataset_write_plan_digest"] = hashlib.sha256(
        json.dumps(
            {"plans": state["dataset_write_plan"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    state["state_digest"] = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    facts = {
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
                "start": "2026-07-01T00:00:00+00:00",
                "end": "2026-07-03T00:00:00+00:00",
            },
            "contract_or_series": ["JM.MAIN", "JM2609"],
        },
        "plan_digest": "b" * 64,
        "mapping_write_plan": {
            "provider": "rqdata",
            "symbol": "jm",
            "rank": 1,
            "start_day": "2026-07-01",
            "end_day": "2026-07-01",
            "trading_days": ["2026-07-01"],
            "allowed_contracts": ["JM2609"],
        },
        "current_state": state,
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
    facts["write_set"]["partial_apply_receipt"] = str(
        expected_partial_apply_receipt_path(facts)
    )
    return facts


def test_data_migrate_apply_preflights_packet_then_dispatches_runner(
    tmp_path: Path,
) -> None:
    packet = build_apply_approval_packet(bound_facts=_migrate_apply_facts())
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    stdout = StringIO()
    stderr = StringIO()
    observed: dict[str, object] = {}

    def run(command, _session, args):
        observed.update({"command": command, "packet": args.approval_packet})
        return {
            "schema_version": 1,
            "command": "data.migrate.apply",
            "status": "passed",
            "readonly": False,
        }

    exit_code = main(
        [
            "data",
            "migrate",
            "apply",
            "--project-root",
            "/tmp/project",
            "--legacy-root",
            "/tmp/legacy",
            "--canonical-root",
            "/tmp/data/parquet/data-core-v2/canonical",
            "--staging-root",
            "/tmp/data/parquet/data-core-v2/staging",
            "--start",
            "2026-07-01T00:00:00Z",
            "--end",
            "2026-07-03T00:00:00Z",
            "--approval-packet",
            str(packet_path),
            "--approval-hash",
            packet["packet_hash"],
            "--preflight-receipt",
            str(tmp_path / "preflight.json"),
            "--preflight-hash",
            "d" * 64,
        ],
        session_factory=lambda: nullcontext(object()),
        data_core_runner=run,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert observed == {"command": "migrate.apply", "packet": packet_path}
    assert json.loads(stdout.getvalue())["readonly"] is False


def test_data_migrate_apply_rejects_packet_hash_before_database_open(
    tmp_path: Path,
) -> None:
    packet = build_apply_approval_packet(bound_facts=_migrate_apply_facts())
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "migrate",
            "apply",
            "--project-root",
            "/tmp/project",
            "--legacy-root",
            "/tmp/legacy",
            "--canonical-root",
            "/tmp/data/parquet/data-core-v2/canonical",
            "--staging-root",
            "/tmp/data/parquet/data-core-v2/staging",
            "--start",
            "2026-07-01T00:00:00Z",
            "--end",
            "2026-07-03T00:00:00Z",
            "--approval-packet",
            str(packet_path),
            "--approval-hash",
            "c" * 64,
            "--preflight-receipt",
            str(tmp_path / "preflight.json"),
            "--preflight-hash",
            "d" * 64,
        ],
        session_factory=_NoSessionFactory(),
        stderr=stderr,
    )

    assert exit_code == 78
    assert json.loads(stderr.getvalue())["error"]["code"] == (
        "approval_packet_mismatch"
    )


def test_data_migrate_shadow_rejects_packet_hash_before_database_open(
    tmp_path: Path,
) -> None:
    packet = build_apply_approval_packet(bound_facts=_migrate_apply_facts())
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "migrate",
            "shadow",
            "--project-root",
            "/tmp/project",
            "--legacy-root",
            "/tmp/legacy",
            "--canonical-root",
            "/tmp/data/parquet/data-core-v2/canonical",
            "--start",
            "2026-07-01T00:00:00Z",
            "--end",
            "2026-07-03T00:00:00Z",
            "--approval-packet",
            str(packet_path),
            "--approval-hash",
            "c" * 64,
            "--apply-receipt",
            "/tmp/data/parquet/data-core-v2/receipts/apply.json",
            "--apply-receipt-hash",
            "d" * 64,
        ],
        session_factory=_NoSessionFactory(),
        stderr=stderr,
    )

    assert exit_code == 78
    assert json.loads(stderr.getvalue())["error"]["code"] == (
        "approval_packet_mismatch"
    )


def test_data_migrate_inventory_dispatches_read_only_runner() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["data", "migrate", "inventory", "--project-root", "/tmp/guiyi"],
        session_factory=lambda: nullcontext(object()),
        data_core_runner=lambda command, _session, _args: {
            "schema_version": 1,
            "command": f"data.{command}",
            "status": "passed",
            "readonly": True,
            "items": [],
        },
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["command"] == "data.migrate.inventory"


def test_data_canonical_verify_dispatches_shared_data_core_reader() -> None:
    stdout = StringIO()
    stderr = StringIO()
    observed = {}

    def run(command, _session, args):
        observed.update({"command": command, "args": vars(args)})
        return {
            "schema_version": 1,
            "command": "data.verify",
            "status": "passed",
            "readonly": True,
        }

    exit_code = main(
        [
            "data",
            "verify",
            "--dataset-kind",
            "continuous",
            "--symbol",
            "jm",
            "--contract-or-series",
            "jm.MAIN",
            "--frequency",
            "15m",
            "--start",
            "2026-07-01T01:00:00Z",
            "--end",
            "2026-07-01T02:00:00Z",
            "--canonical-root",
            "/tmp/guiyi-canonical",
        ],
        session_factory=lambda: nullcontext(object()),
        data_core_runner=run,
        data_verifier=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy verifier must not run")
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert observed["command"] == "verify"
    assert observed["args"]["dataset_kind"] == "continuous"


def test_data_sync_rejects_derived_frequency_before_opening_database() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "sync",
            "--dataset-kind",
            "continuous",
            "--symbol",
            "jm",
            "--contract-or-series",
            "jm.MAIN",
            "--frequency",
            "15m",
            "--start",
            "2026-07-01T01:00:00Z",
            "--end",
            "2026-07-01T02:00:00Z",
        ],
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"


def test_runtime_plan_is_existing_scheduler_dry_run_without_side_effects() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["runtime", "plan", "--product", "jm", "--poll-seconds", "3"],
        environ={"GUIYI_LIVE_RUNTIME_ENABLED": "true"},
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "schema_version": 1,
        "command": "runtime.plan",
        "status": "planned",
        "readonly": True,
        "effects": {
            "would_open_database": False,
            "would_connect_redis": False,
            "would_construct_rqdata_client": False,
            "would_write_live_tables": False,
            "would_write_historical_active": False,
            "would_write_signal_event": False,
            "would_send_notification": False,
            "auto_order": False,
        },
        "plan": {
            "mode": "dry-run",
            "product": "jm",
            "poll_seconds": 5,
            "enabled": True,
        },
    }


def test_runtime_status_returns_health_payload_and_nonzero_for_failed_runtime() -> None:
    stdout = StringIO()
    stderr = StringIO()
    health = {
        "status": "failed",
        "generated_at": "2026-07-30T00:00:00+00:00",
        "readonly": True,
        "would_start_services": False,
        "would_enqueue_jobs": False,
        "would_send_notifications": False,
        "components": {"db": {"status": "failed"}},
    }

    exit_code = main(
        ["runtime", "status"],
        session_factory=lambda: nullcontext(object()),
        runtime_health_builder=lambda _session: health,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "schema_version": 1,
        "command": "runtime.status",
        "status": "failed",
        "readonly": True,
        "effects": {
            "would_start_services": False,
            "would_enqueue_jobs": False,
            "would_send_notifications": False,
        },
        "runtime": health,
    }


def test_data_verify_emits_stable_json_from_shared_service() -> None:
    stdout = StringIO()
    stderr = StringIO()
    observed: dict[str, object] = {}

    def verify(_session, **kwargs):
        observed.update(kwargs)
        return {
            "schema_version": 1,
            "command": "data.verify",
            "kind": "active-dataset",
            "status": "passed",
            "readonly": True,
            "effects": {
                "writes_database": False,
                "writes_parquet": False,
                "writes_manifest": False,
                "calls_rqdata": False,
            },
            "request": {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "15m",
                "start": "2026-07-29T00:00:00",
                "end": "2026-07-29T23:59:59.999999",
                "provider": "rqdata",
                "profile_id": None,
                "access_mode": "browser",
                "limit": 5000,
            },
            "result": {
                "response_bar_count": 23,
                "quality": {"status": "passed"},
                "descriptor": {"lineage_token": "lineage-v1:test"},
            },
        }

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
            "--start",
            "2026-07-29",
            "--end",
            "2026-07-29",
            "--provider",
            "rqdata",
        ],
        session_factory=lambda: nullcontext(object()),
        data_verifier=verify,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["result"]["response_bar_count"] == 23
    assert observed == {
        "symbol": "jm",
        "contract": "jm.MAIN",
        "period": "15m",
        "start": datetime(2026, 7, 29, 0, 0),
        "end": datetime(2026, 7, 29, 23, 59, 59, 999999),
        "provider": "rqdata",
        "profile_id": None,
        "access_mode": "browser",
        "limit": 5000,
        "legacy_compat": False,
    }


def test_data_verify_maps_domain_error_to_bounded_json_stderr() -> None:
    from app.services.active_dataset import ActiveDatasetDomainError

    stdout = StringIO()
    stderr = StringIO()

    def reject(_session, **_kwargs):
        raise ActiveDatasetDomainError("DATASET_ASSET_MISSING")

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
        ],
        session_factory=lambda: nullcontext(object()),
        data_verifier=reject,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "data.verify",
        "status": "error",
        "readonly": True,
        "error": {
            "code": "DATASET_ASSET_MISSING",
            "type": "ActiveDatasetDomainError",
        },
    }


def test_data_verify_preserves_legacy_market_error_code_without_message() -> None:
    from app.services.market_workbench import MarketAccessError

    stdout = StringIO()
    stderr = StringIO()

    def reject(_session, **_kwargs):
        raise MarketAccessError(
            "MARKET_DATA_NOT_FOUND",
            "sensitive path must not reach stderr",
        )

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
        ],
        session_factory=lambda: nullcontext(object()),
        data_verifier=reject,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"] == {
        "code": "MARKET_DATA_NOT_FOUND",
        "type": "MarketAccessError",
    }


def test_data_verify_rejects_invalid_date_before_opening_database() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
            "--start",
            "not-a-date",
        ],
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "data.verify",
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_ARGUMENT_INVALID", "type": "ValueError"},
    }


def test_runtime_status_bounds_collector_error_without_traceback() -> None:
    stdout = StringIO()
    stderr = StringIO()

    def fail(_session):
        raise RuntimeError("database password must never reach stderr")

    exit_code = main(
        ["runtime", "status"],
        session_factory=lambda: nullcontext(object()),
        runtime_health_builder=fail,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "runtime.status",
        "status": "error",
        "readonly": True,
        "error": {"code": "RUNTIME_STATUS_FAILED", "type": "RuntimeError"},
    }


def test_data_verify_warning_returns_nonzero() -> None:
    stdout = StringIO()
    observed: dict[str, object] = {}

    def warning(_session, **kwargs):
        observed.update(kwargs)
        return {
            "schema_version": 1,
            "command": "data.verify",
            "status": "warning",
            "readonly": True,
        }

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
        ],
        session_factory=lambda: nullcontext(object()),
        data_verifier=warning,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 1
    assert observed["start"] is None
    assert observed["end"] is None


def test_parser_error_uses_bounded_json_and_exit_two() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
            "--limit",
            "0",
        ],
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "data.verify",
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_ARGUMENT_INVALID", "type": "CliUsageError"},
    }
