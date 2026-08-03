from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.db.base import Base
from app.models import backtest as _backtest_models  # noqa: F401
from app.models import review as _review_models  # noqa: F401
from app.models import signal as _signal_models  # noqa: F401
from app.models.data_center import MarketDataFile
from app.models.data_core import MarketDataset, MarketPartition
from app.services.derived_reference_inventory import (
    DerivedReferenceInventoryConfig,
    _RELATION_RULES,
    _catalog_identity_matches,
    build_derived_reference_inventory,
)


def test_inventory_is_deterministic_and_classifies_read_only_surfaces(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    _write_fixture_files(repo_root, data_root)
    connection = _fixture_connection()

    first = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=connection,
    )
    second = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=connection,
    )

    assert first == second
    assert first["schema_version"] == 1
    assert first["command"] == "derived-reference-inventory"
    assert first["safety"] == {
        "calls_rqdata": False,
        "filesystem_operations": ["read", "stat", "hash"],
        "readonly_database_transaction": True,
        "writes_database": False,
        "writes_filesystem": False,
    }
    assert [item["category"] for item in first["categories"]] == [
        "indicator_cache",
        "backtest",
        "signal_review",
        "live_eod_sample",
        "permanent_derived_periods",
        "duplicate_bar_layers",
        "profile_binding_legacy_lineage",
        "report_14_15_references",
    ]

    categories = {item["category"]: item for item in first["categories"]}
    assert all(
        item["database_tables"] or item["filesystem_paths"] or item["reference_locations"]
        for item in categories.values()
    )
    assert categories["backtest"]["database_tables"] == [
        {"count": 1, "disposition": "REBUILD_ONLY", "id_status": "complete", "ids": ["7"], "table": "backtest_reports"}
    ]
    assert categories["profile_binding_legacy_lineage"]["database_tables"] == [
        {"count": 1, "disposition": "REBUILD_ONLY", "id_status": "complete", "ids": ["8"], "table": "data_profiles"},
        {"count": 1, "disposition": "REBUILD_ONLY", "id_status": "complete", "ids": ["9"], "table": "profile_active_bindings"},
    ]
    assert categories["duplicate_bar_layers"]["filesystem_paths"] == [
        {
            "path": "data/parquet/canonical/jm/part-000.parquet",
                "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                "size_bytes": 3,
                "disposition": "REVIEW_REQUIRED",
        },
        {
            "path": "data/raw/jm/source.parquet",
                "sha256": "7692c3ad3540bb803c020b3aee66cd8887123234ea0c6e7143c0add73ff431ed",
                "size_bytes": 3,
                "disposition": "REVIEW_REQUIRED",
        },
        {
            "path": "data/standard/jm/normalized.parquet",
                "sha256": "3fc4ccfe745870e2c0d99f71f30ff0656c8dedd41cc1d7d3d376b0dbe685e2f3",
                "size_bytes": 3,
                "disposition": "REVIEW_REQUIRED",
        },
    ]
    assert [{key: item[key] for key in ("line", "path", "kind", "matched_token")} for item in categories["report_14_15_references"]["reference_locations"]] == [
        {"kind": "doc", "line": 1, "matched_token": "report 14", "path": "docs/gate.md"},
        {"kind": "code", "line": 1, "matched_token": "report_15_", "path": "services/quant-api/app/example.py"},
    ]


def test_market_data_inventory_columns_match_real_models() -> None:
    assert {"id", "provider", "data_type", "instrument_symbol", "contract_code", "period", "file_path", "checksum", "data_version", "data_role", "quality_status"} <= set(MarketDataFile.__table__.columns.keys())
    assert {"id", "provider", "symbol", "contract_or_series", "frequency", "adjustment", "schema_version"} <= set(MarketDataset.__table__.columns.keys())
    assert {"id", "dataset_id", "file_uri", "manifest_uri", "manifest_digest", "checksum", "manifest_version"} <= set(MarketPartition.__table__.columns.keys())


def test_relation_rule_columns_match_real_orm_tables() -> None:
    for rule in _RELATION_RULES:
        assert rule.table in Base.metadata.tables
        assert set(rule.columns) <= set(Base.metadata.tables[rule.table].columns.keys())


@pytest.mark.parametrize(
    ("dataset_kind", "row_contract", "catalog_contract", "expected"),
    [
        ("actual_dominant", "JM2609", "JM2609", True),
        ("continuous", "jm.main", "JM.MAIN", True),
        ("actual_dominant", "JM.MAIN", "JM.MAIN", False),
        ("continuous", "JM2609", "JM.MAIN", False),
        ("actual_dominant", "JMABC", "JMABC", False),
        ("actual_dominant", "JM", "JM", False),
        ("actual_dominant", "JM2609X", "JM2609X", False),
        ("actual_dominant", "JMX2609", "JMX2609", False),
    ],
)
def test_catalog_identity_supports_only_valid_actual_or_continuous_direct_contracts(
    dataset_kind: str, row_contract: str, catalog_contract: str, expected: bool,
) -> None:
    row = {"provider": "rqdata", "data_type": "bars", "data_role": "primary", "quality_status": "passed", "instrument_symbol": "jm", "contract_code": row_contract, "period": "1m", "checksum": "a"}
    catalog = {"provider": "rqdata", "symbol": "jm", "contract_or_series": catalog_contract, "frequency": "1m", "checksum": "a", "dataset_kind": dataset_kind, "adjustment": "none", "schema_version": "canonical-bar-v1", "manifest_uri": "manifest.json", "manifest_digest": "b"}
    assert _catalog_identity_matches(row, catalog) is expected


@pytest.mark.parametrize(
    ("dataset_kind", "period", "expected"),
    [
        ("actual_dominant", "1m", True), ("actual_dominant", "1d", True), ("actual_dominant", "1w", True),
        ("continuous", "1m", True), ("continuous", "1d", True), ("continuous", "1w", True),
    ],
)
def test_catalog_identity_enforces_direct_frequency_contract(dataset_kind: str, period: str, expected: bool) -> None:
    contract = "JM2609" if dataset_kind == "actual_dominant" else "JM.MAIN"
    row = {"provider": "rqdata", "data_type": "bars", "data_role": "primary", "quality_status": "passed", "instrument_symbol": "jm", "contract_code": contract, "period": period, "checksum": "a"}
    catalog = {"provider": "rqdata", "symbol": "jm", "contract_or_series": contract, "frequency": period, "checksum": "a", "dataset_kind": dataset_kind, "adjustment": "none", "schema_version": "canonical-bar-v1", "manifest_uri": "manifest.json", "manifest_digest": "b"}
    assert _catalog_identity_matches(row, catalog) is expected


def test_inventory_uses_sqlite_query_only_and_never_emits_write_statement(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "absent-data-root"
    repo_root.mkdir()
    connection = _fixture_connection()
    statements: list[str] = []
    connection.set_trace_callback(statements.append)

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=connection,
    )

    assert result["database"]["dialect"] == "sqlite"
    assert result["filesystem"]["data_root_exists"] is False
    assert any(statement.upper().startswith("PRAGMA QUERY_ONLY = ON") for statement in statements)
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "COMMIT"))
        for statement in statements
    )


def test_cli_emits_stable_json_without_database_configuration(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    _write_fixture_files(repo_root, data_root)
    script = Path(__file__).resolve().parents[3] / "scripts" / "derived_reference_inventory.py"
    command = [sys.executable, str(script), "--repo-root", str(repo_root), "--data-root", str(data_root)]

    first = subprocess.run(command, check=False, capture_output=True, text=True)
    second = subprocess.run(command, check=False, capture_output=True, text=True)

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stderr == second.stderr == ""
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert payload["database"]["available"] is False
    assert payload["readonly"] is True


def test_cli_rejects_delete_and_redacts_injected_database_url(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[3] / "scripts" / "derived_reference_inventory.py"
    secret_url = "postgresql://inventory_user:do-not-print@db.example.invalid/inventory"

    delete_attempt = subprocess.run([sys.executable, str(script), "--delete"], check=False, capture_output=True, text=True)
    invalid_database = subprocess.run(
        [sys.executable, str(script), "--database-url", secret_url, "--repo-root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert delete_attempt.returncode == 2
    assert invalid_database.returncode == 2
    assert secret_url not in invalid_database.stdout + invalid_database.stderr
    assert json.loads(invalid_database.stderr)["command"] == "derived-reference-inventory"


def test_postgresql_collector_sets_read_only_transaction_without_commit(tmp_path: Path) -> None:
    connection = _FakePostgresConnection()

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=tmp_path / "missing-repo", data_root=tmp_path / "missing-data"),
        connection=connection,
    )

    assert result["database"]["available"] is True
    assert result["database"]["dialect"] == "postgresql"
    assert result["database"]["tables"] == [
        {"count": 1, "disposition": "REBUILD_ONLY", "id_status": "complete", "ids": ["14"], "table": "backtest_reports"}
    ]
    assert connection.statements[:1] == ["BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"]
    assert connection.rollback_count == 1
    assert connection.commit_count == 0
    assert not any(
        statement.upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"))
        for statement in connection.statements
    )


def test_reference_scan_classifies_every_category_without_inventory_self_reference(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    _write_active_reference_files(repo_root)

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )

    categories = {item["category"]: item for item in result["categories"]}
    assert all(item["active_reference_status"] == "present" for item in categories.values())
    assert {item["category"] for item in categories.values() if item["reference_locations"]} == set(categories)
    assert all(
        all(location["path"] != "scripts/derived_reference_inventory.py" for location in item["reference_locations"])
        for item in categories.values()
    )
    assert all(
        {"path", "line", "kind", "matched_token", "reason"}.issubset(location)
        for item in categories.values()
        for location in item["reference_locations"]
    )
    assert any(location["path"] == "config.toml" for location in categories["backtest"]["reference_locations"])


def test_filesystem_rejects_external_symlink_and_reports_stable_budget_truncation(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    outside = tmp_path / "outside-secret.parquet"
    outside.write_bytes(b"do-not-read")
    (data_root / "raw").mkdir(parents=True)
    (data_root / "raw" / "0outside.parquet").symlink_to(outside)
    (data_root / "raw" / "a.parquet").write_bytes(b"a")
    (data_root / "raw" / "b.parquet").write_bytes(b"b")
    (data_root / "raw" / "c.parquet").write_bytes(b"c")
    config = DerivedReferenceInventoryConfig(
        repo_root=tmp_path / "repo",
        data_root=data_root,
        max_files=1,
        max_file_bytes=8,
        max_total_bytes=8,
    )

    first = build_derived_reference_inventory(config)
    second = build_derived_reference_inventory(config)

    assert first == second
    assert first["filesystem"]["truncated"] is True
    assert first["filesystem"]["records"] == [
        {
            "path": "data/raw/a.parquet",
                "sha256": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
                "size_bytes": 1,
                "disposition": "REVIEW_REQUIRED",
        }
    ]
    assert {item["code"] for item in first["filesystem"]["diagnostics"]} == {
        "MAX_FILES_EXCEEDED",
        "SYMLINK_SKIPPED",
    }
    assert sum(item["code"] == "MAX_FILES_EXCEEDED" for item in first["filesystem"]["diagnostics"]) == 1
    assert all("outside-secret" not in str(item) for item in first["filesystem"]["diagnostics"])


def test_database_uses_allowlist_reports_missing_and_fails_closed_on_id_limit(tmp_path: Path) -> None:
    connection = _fixture_connection()
    connection.execute("CREATE TABLE secrets (id INTEGER PRIMARY KEY, token TEXT)")
    connection.execute("INSERT INTO secrets VALUES (99, 'never-read')")
    connection.execute("INSERT INTO backtest_reports VALUES (70, 'second-report')")
    connection.commit()

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=tmp_path / "repo", data_root=tmp_path / "data", max_ids=1),
        connection=connection,
    )

    assert "secrets" not in {item["table"] for item in result["database"]["tables"]}
    backtest = next(item for item in result["database"]["tables"] if item["table"] == "backtest_reports")
    assert backtest == {"table": "backtest_reports", "count": 2, "ids": [], "id_status": "limit_exceeded", "disposition": "REBUILD_ONLY"}
    assert {item["code"] for item in result["database"]["diagnostics"]} >= {
        "ID_LIMIT_EXCEEDED",
        "TABLE_MISSING",
    }
    assert result["status"] == "incomplete"
    assert result["task07_zero_active_reference_eligible"] is False


def test_database_missing_table_forces_incomplete_even_with_existing_roots(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_fixture_connection(),
    )

    assert any(item["code"] == "TABLE_MISSING" for item in result["database"]["diagnostics"])
    assert result["status"] == "incomplete"
    assert result["task07_zero_active_reference_eligible"] is False


def test_real_sqlalchemy_sqlite_connection_uses_readonly_inventory_path(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE backtest_reports (id INTEGER PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("INSERT INTO backtest_reports VALUES (14, 'fixture')")
        result = build_derived_reference_inventory(
            DerivedReferenceInventoryConfig(repo_root=tmp_path / "repo", data_root=tmp_path / "data"),
            connection=connection,
        )

    assert result["database"]["available"] is True
    assert result["database"]["dialect"] == "sqlite"
    assert result["database"]["tables"] == [
        {"table": "backtest_reports", "count": 1, "ids": ["14"], "id_status": "complete", "disposition": "REBUILD_ONLY"}
    ]


def test_unknown_database_dialect_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported database dialect"):
        build_derived_reference_inventory(
            DerivedReferenceInventoryConfig(repo_root=tmp_path / "repo", data_root=tmp_path / "data"),
            connection=object(),
        )


def test_market_data_file_rows_require_catalog_evidence_and_classify_exact_rows(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    connection = _market_data_file_connection()

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root, canonical_root=Path("/data")),
        connection=connection,
    )

    categories = {item["category"]: item for item in result["categories"]}
    derived = categories["permanent_derived_periods"]["database_tables"]
    duplicate = categories["duplicate_bar_layers"]["database_tables"]
    assert derived[0]["table"] == "market_data_files"
    assert derived[0]["count"] == 1
    assert derived[0]["ids"] == ["2"]
    assert derived[0]["disposition"] == "REBUILD_ONLY"
    assert duplicate[0]["table"] == "market_data_files"
    assert duplicate[0]["ids"] == ["1", "3"]
    assert duplicate[0]["disposition"] == "REVIEW_REQUIRED"
    market_files = next(item for item in result["database"]["tables"] if item["table"] == "market_data_files")
    assert market_files["row_classifications"][0]["disposition"] == "REVIEW_REQUIRED"
    assert market_files["row_classifications"][0]["catalog_evidence"] == "metadata_aligned_partial_data_version_unverified"
    assert result["status"] == "incomplete"  # fixture intentionally lacks unrelated allowlisted tables


def test_reference_state_excludes_historical_and_non_active_sections_from_task07_gate(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    (repo_root / "docs" / "archive").mkdir(parents=True)
    data_root.mkdir()
    (repo_root / "docs" / "historical.md").write_text(
        "## Historical snapshot; not active Gate: archived evidence\nreport 14 backtest legacy lineage\n",
        encoding="utf-8",
    )
    (repo_root / "docs" / "archive" / "old.md").write_text("signal review\n", encoding="utf-8")

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )

    categories = {item["category"]: item for item in result["categories"]}
    assert categories["report_14_15_references"]["active_reference_status"] == "zero_active_references"
    assert categories["report_14_15_references"]["reference_locations"][0]["reference_state"] == "historical"
    assert categories["signal_review"]["reference_locations"][0]["reference_state"] == "historical"
    assert result["status"] == "complete"
    assert result["task07_zero_active_reference_eligible"] is True

    (repo_root / "docs" / "active.md").write_text("report 15 remains active\n", encoding="utf-8")
    active = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )
    active_category = next(item for item in active["categories"] if item["category"] == "report_14_15_references")
    assert active_category["active_reference_status"] == "present"
    assert active["task07_zero_active_reference_eligible"] is False


def test_task07_blocks_active_binding_even_when_repo_references_are_zero(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    connection = _complete_empty_connection()
    connection.execute(
        "INSERT INTO profile_active_bindings "
        "(id, profile_id, market_data_file_id, data_version, binding_status) VALUES (?, ?, ?, ?, ?)",
        (41, 7, 19, "v2", "active"),
    )
    connection.commit()

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=connection,
    )

    active_binding = next(
        rule for rule in result["database"]["relation_references"]
        if rule["rule"] == "active_profile_binding"
    )
    assert active_binding == {
        "rule": "active_profile_binding",
        "table": "profile_active_bindings",
        "predicate": "binding_status = active",
        "count": 1,
        "row_ids": ["41"],
        "target_ids": {"profile_id": ["7"], "market_data_file_id": ["19"], "data_version": ["v2"]},
        "status": "active",
        "reason": "active binding still targets legacy profile/file/version lineage",
    }
    assert result["database"]["active_relation_reference_count"] == 1
    assert result["task07_zero_active_reference_eligible"] is False


def test_task07_blocks_quality_report_file_fk_but_not_superseded_binding(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    connection = _complete_empty_connection()
    connection.execute(
        "INSERT INTO profile_active_bindings "
        "(id, profile_id, market_data_file_id, data_version, binding_status) VALUES (?, ?, ?, ?, ?)",
        (42, 8, 20, "v1", "superseded"),
    )
    connection.execute(
        "INSERT INTO data_quality_reports (id, file_id, task_id) VALUES (?, ?, ?)",
        (51, 20, None),
    )
    connection.commit()

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=connection,
    )

    relations = {rule["rule"]: rule for rule in result["database"]["relation_references"]}
    assert relations["active_profile_binding"]["count"] == 0
    assert relations["unknown_profile_binding_status"]["count"] == 0
    assert relations["quality_report_file_reference"]["row_ids"] == ["51"]
    assert relations["quality_report_file_reference"]["target_ids"] == {"file_id": ["20"]}
    assert result["database"]["active_relation_reference_count"] == 1
    assert result["task07_zero_active_reference_eligible"] is False


def test_inactive_rows_are_not_counted_but_uncertain_status_blocks(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    connection = _complete_empty_connection()
    connection.executemany(
        "INSERT INTO data_download_tasks (id, status) VALUES (?, ?)",
        [(61, "success"), (62, "provider_specific_unknown")],
    )
    connection.execute("INSERT INTO backtest_tasks (id, status) VALUES (?, ?)", (63, "success"))
    connection.execute("INSERT INTO signal_events (id, lifecycle_status) VALUES (?, ?)", (64, "archived"))
    connection.commit()

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=connection,
    )

    relations = {rule["rule"]: rule for rule in result["database"]["relation_references"]}
    assert relations["active_download_task"]["count"] == 0
    assert relations["unknown_download_task_status"]["row_ids"] == ["62"]
    assert relations["backtest_task_legacy_relation"]["count"] == 0
    assert relations["unknown_backtest_task_status"]["count"] == 0
    assert relations["signal_event_legacy_or_active"]["count"] == 0
    assert relations["unknown_signal_event_lifecycle"]["count"] == 0
    assert result["database"]["active_relation_reference_count"] == 1
    assert result["task07_zero_active_reference_eligible"] is False


@pytest.mark.parametrize("suffix", [".mjs", ".mts", ".cjs"])
def test_reference_scan_includes_extended_javascript_suffixes(tmp_path: Path, suffix: str) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    (repo_root / f"consumer{suffix}").write_text("backtest = true\n", encoding="utf-8")

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )

    backtest = next(category for category in result["categories"] if category["category"] == "backtest")
    assert backtest["reference_locations"][0]["path"] == f"consumer{suffix}"
    assert result["task07_zero_active_reference_eligible"] is False


def test_reference_scan_includes_makefile_and_fails_closed_for_unknown_extensionless_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    (repo_root / "Makefile").write_text("backtest:\n\t@true\n", encoding="utf-8")
    (repo_root / "consumer_config").write_text("signal = enabled\n", encoding="utf-8")

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )

    backtest = next(category for category in result["categories"] if category["category"] == "backtest")
    assert backtest["reference_locations"][0]["path"] == "Makefile"
    assert {item["code"] for item in result["reference_scan"]["diagnostics"]} >= {
        "REPO_UNKNOWN_EXTENSIONLESS_FILE"
    }
    assert result["status"] == "incomplete"


def test_reference_scan_fails_closed_for_unknown_suffix_and_explains_data_exclusion(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    (repo_root / "consumer.custom").write_text("backtest = enabled\n", encoding="utf-8")
    (repo_root / "fixture.csv").write_text("signal\n", encoding="utf-8")

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )

    assert {item["code"] for item in result["reference_scan"]["diagnostics"]} >= {
        "REPO_UNKNOWN_FILE_TYPE"
    }
    exclusions = {
        item["file_type"]: item["reason"]
        for item in result["reference_scan"]["explicit_file_type_exclusions"]
    }
    assert exclusions[".csv"] == "tabular data asset; not executable source or documentation"
    assert result["status"] == "incomplete"


def test_reference_scan_fails_closed_for_non_utf8_symlink_and_match_budget(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("backtest", encoding="utf-8")
    (repo_root / "0-link.py").symlink_to(outside)
    (repo_root / "1-invalid.py").write_bytes(bytes([255]))
    (repo_root / "2-many.py").write_text("backtest signal review live eod derived 15m", encoding="utf-8")

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root, max_files=3),
    )

    assert result["reference_scan"]["truncated"] is True
    assert {item["code"] for item in result["reference_scan"]["diagnostics"]} >= {
        "REPO_SYMLINK_SKIPPED",
        "REPO_NON_UTF8_SKIPPED",
        "REPO_MAX_MATCHES_EXCEEDED",
    }
    assert result["status"] == "incomplete"


def test_reference_scan_fails_closed_when_directory_budget_is_exhausted(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    (repo_root / "a" / "b").mkdir(parents=True)
    data_root.mkdir()
    (repo_root / "a" / "b" / "consumer.py").write_text("backtest", encoding="utf-8")

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root, max_directories=2),
    )

    assert result["status"] == "incomplete"
    assert {item["code"] for item in result["reference_scan"]["diagnostics"]} >= {"REPO_MAX_DIRECTORIES_EXCEEDED"}


def test_database_scan_error_is_structured_and_ineligible(tmp_path: Path) -> None:
    connection = sqlite3.connect(":memory:", factory=_BrokenSqliteConnection)
    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=tmp_path / "repo", data_root=tmp_path / "data"),
        connection=connection,
    )

    assert result["database"]["available"] is False
    assert result["database"]["diagnostics"][-1] == {"code": "DATABASE_SCAN_ERROR"}
    assert result["status"] == "incomplete"
    assert result["task07_zero_active_reference_eligible"] is False


def test_reference_scan_keeps_legacy_consumer_tests_and_fails_closed_on_ambiguous_status(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    (repo_root / "services" / "quant-api" / "tests").mkdir(parents=True)
    data_root.mkdir()
    (repo_root / "services" / "quant-api" / "tests" / "test_legacy_consumer.py").write_text(
        "def test_legacy_consumer():\n    backtest = canonical\n",
        encoding="utf-8",
    )
    (repo_root / "docs").mkdir()
    (repo_root / "docs" / "ambiguous.md").write_text("historical canonical backtest\n", encoding="utf-8")

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )

    backtest = next(item for item in result["categories"] if item["category"] == "backtest")
    states = {(item["path"], item["reference_state"]) for item in backtest["reference_locations"]}
    assert ("services/quant-api/tests/test_legacy_consumer.py", "active") in states
    assert ("docs/ambiguous.md", "review_required") in states
    assert backtest["active_reference_status"] == "present"
    assert result["task07_zero_active_reference_eligible"] is False


@pytest.mark.parametrize(
    ("text", "expected_state"),
    [
        ("frozen backtest reference", "review_required"),
        ("compatibility-only backtest is still used", "review_required"),
        ("historical snapshot; not active Gate: backtest", "historical"),
        ("superseded and unused backtest", "review_required"),
        ("历史快照且非 active Gate：backtest", "historical"),
        ("仅历史引用：backtest", "historical"),
        ("不再 active：backtest", "active"),
        ("已归档：backtest", "historical"),
    ],
)
def test_reference_state_requires_explicit_non_active_evidence(tmp_path: Path, text: str, expected_state: str) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    (repo_root / "reference.md").write_text(text, encoding="utf-8")

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )

    backtest = next(item for item in result["categories"] if item["category"] == "backtest")
    assert backtest["reference_locations"][0]["reference_state"] == expected_state
    assert result["task07_zero_active_reference_eligible"] is (expected_state in {"historical", "non_active"})


@pytest.mark.parametrize(
    ("relative", "text"),
    [
        ("docs/negated.md", "backtest is not merely historical reference"),
        ("docs/negated.md", "backtest must not be treated as not active"),
        ("services/quant-api/app/legacy.py", "historical snapshot; not active Gate: backtest"),
        ("services/quant-api/tests/test_legacy.py", "仅历史引用：backtest"),
    ],
)
def test_reference_state_never_downgrades_negated_or_code_test_text(tmp_path: Path, relative: str, text: str) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    path = repo_root / relative
    path.parent.mkdir(parents=True)
    data_root.mkdir()
    path.write_text(text, encoding="utf-8")

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )

    location = next(item for item in next(category for category in result["categories"] if category["category"] == "backtest")["reference_locations"])
    assert location["reference_state"] in {"active", "review_required"}
    assert location["disposition"] != "HISTORICAL_SNAPSHOT"
    assert result["task07_zero_active_reference_eligible"] is False


def test_archive_code_and_active_override_inside_historical_section_still_block_task07(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    (repo_root / "archive").mkdir(parents=True)
    data_root.mkdir()
    (repo_root / "archive" / "legacy.py").write_text("historical snapshot; not active Gate: backtest", encoding="utf-8")
    (repo_root / "docs").mkdir()
    (repo_root / "docs" / "history.md").write_text(
        "## Historical snapshot; not active Gate: legacy\ncurrent active backtest\n",
        encoding="utf-8",
    )

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )

    locations = next(category for category in result["categories"] if category["category"] == "backtest")["reference_locations"]
    assert {item["reference_state"] for item in locations} >= {"active"}
    assert result["task07_zero_active_reference_eligible"] is False


@pytest.mark.parametrize(
    "text",
    [
        "仅历史引用：old backtest; current signal remains active",
        "Historical snapshot; not active Gate: old backtest; current signal is active",
    ],
)
def test_mixed_historical_marker_with_current_active_text_blocks_task07(tmp_path: Path, text: str) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    (repo_root / "reference.md").write_text(text, encoding="utf-8")
    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root),
        connection=_complete_empty_connection(),
    )
    location = next(category for category in result["categories"] if category["category"] == "backtest")["reference_locations"][0]
    assert location["reference_state"] in {"active", "review_required"}
    assert result["task07_zero_active_reference_eligible"] is False


def test_market_data_file_mismatches_and_direct_5m_bars_are_never_keep(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root, canonical_root=Path("/data")),
        connection=_strict_market_data_file_connection(),
    )

    classes = next(item for item in result["database"]["tables"] if item["table"] == "market_data_files")["row_classifications"]
    assert [item["disposition"] for item in classes] == [
        "REVIEW_REQUIRED", "REBUILD_ONLY", "REVIEW_REQUIRED", "REVIEW_REQUIRED", "REVIEW_REQUIRED", "REVIEW_REQUIRED", "REBUILD_ONLY",
    ]
    assert classes[-1]["category"] == "permanent_derived_periods"
    assert classes[-1]["reason"] == "legacy bar period is regenerated from provider-direct canonical 1m bars"
    assert all(item["category"] is not None for item in classes)
    assert {item["code"] for item in result["database"]["diagnostics"]} >= {"PHYSICAL_KEEP_PROOF_REQUIRED"}
    assert all(category["database_scope"] == "INCOMPLETE" for category in result["categories"])
    assert result["status"] == "incomplete"


def test_market_data_file_path_normalization_rejects_root_escape_and_ambiguous_uri(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_root = tmp_path / "data"
    repo_root.mkdir()
    data_root.mkdir()
    connection = _market_data_file_connection()
    connection.execute(
        "INSERT INTO market_data_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (8, "rqdata", "bars", "jm", "JM2609", "1m", "/outside/linked.parquet", "outside", "v2", "primary", "passed"),
    )
    connection.execute(
        "INSERT INTO market_partitions VALUES (?, ?, ?, ?, ?, ?, ?)",
        (2, 1, "canonical/linked.parquet", "/data/manifests/duplicate.json", "c" * 64, "d" * 64, "v2"),
    )
    connection.commit()

    result = build_derived_reference_inventory(
        DerivedReferenceInventoryConfig(repo_root=repo_root, data_root=data_root, canonical_root=Path("/data")),
        connection=connection,
    )

    classes = next(item for item in result["database"]["tables"] if item["table"] == "market_data_files")["row_classifications"]
    assert next(item for item in classes if item["id"] == "1")["disposition"] == "REVIEW_REQUIRED"
    assert next(item for item in classes if item["id"] == "8")["disposition"] == "REVIEW_REQUIRED"
    assert {item["code"] for item in result["database"]["diagnostics"]} >= {
        "CATALOG_FILE_URI_AMBIGUOUS",
        "MARKET_DATA_FILE_PATH_OUTSIDE_CANONICAL_ROOT",
    }


def _fixture_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE backtest_reports (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE strategy_signals (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE review_notes (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE data_profiles (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE profile_active_bindings (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE live_minute_bars (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE indicator_cache (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE market_datasets (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE market_partitions (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE market_data_files (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE data_gaps (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO backtest_reports VALUES (7, 'report');
        INSERT INTO strategy_signals VALUES (3, 'signal');
        INSERT INTO review_notes VALUES (4, 'note');
        INSERT INTO data_profiles VALUES (8, 'profile');
        INSERT INTO profile_active_bindings VALUES (9, 'binding');
        INSERT INTO live_minute_bars VALUES (2, 'live');
        INSERT INTO indicator_cache VALUES (1, 'cache');
        INSERT INTO market_datasets VALUES (10, 'dataset');
        INSERT INTO market_partitions VALUES (11, 'partition');
        INSERT INTO market_data_files VALUES (12, 'file');
        INSERT INTO data_gaps VALUES (13, 'gap');
        """
    )
    connection.commit()
    return connection


def _market_data_file_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE market_data_files (
            id INTEGER PRIMARY KEY,
            provider TEXT NOT NULL,
            data_type TEXT NOT NULL,
            instrument_symbol TEXT,
            contract_code TEXT,
            period TEXT,
            file_path TEXT NOT NULL,
            checksum TEXT,
            data_version TEXT,
            data_role TEXT NOT NULL,
            quality_status TEXT NOT NULL
        );
        CREATE TABLE market_datasets (
            id INTEGER PRIMARY KEY,
            provider TEXT NOT NULL,
            dataset_kind TEXT NOT NULL,
            symbol TEXT NOT NULL,
            contract_or_series TEXT NOT NULL,
            frequency TEXT NOT NULL,
            adjustment TEXT NOT NULL,
            schema_version TEXT NOT NULL
        );
        CREATE TABLE market_partitions (
            id INTEGER PRIMARY KEY,
            dataset_id INTEGER NOT NULL,
            file_uri TEXT NOT NULL,
            manifest_uri TEXT NOT NULL,
            manifest_digest TEXT NOT NULL,
            checksum TEXT NOT NULL,
            manifest_version TEXT NOT NULL
        );
        INSERT INTO market_datasets VALUES (1, 'rqdata', 'actual_dominant', 'jm', 'JM2609', '1m', 'none', 'canonical-bar-v1');
        INSERT INTO market_partitions VALUES (
            1, 1, 'canonical/linked.parquet', '/data/manifests/linked.json',
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'v2'
        );
        INSERT INTO market_data_files VALUES
            (1, 'rqdata', 'bars', 'jm', 'JM2609', '1m', '/data/canonical/linked.parquet', 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'v2', 'primary', 'passed'),
            (2, 'rqdata', 'derived_bar', 'jm', 'JM2609', '15m', '/data/derived/jm/15m.parquet', 'derived-checksum', 'derived-v1', 'candidate', 'passed'),
            (3, 'rqdata', 'bars', 'jm', 'JM2609', '1m', '/data/canonical/unlinked.parquet', 'unlinked-checksum', 'v2', 'primary', 'passed');
        """
    )
    connection.commit()
    return connection


def _strict_market_data_file_connection() -> sqlite3.Connection:
    connection = _market_data_file_connection()
    connection.executemany(
        "INSERT INTO market_data_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (4, "rqdata", "bars", "wrong", "JM2609", "1m", "/data/canonical/linked.parquet", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "v2", "primary", "passed"),
            (5, "rqdata", "bars", "jm", "JM2609", "1m", "/data/canonical/linked.parquet", "wrong-checksum", "v2", "primary", "passed"),
            (6, "rqdata", "bars", "jm", "JM2609", "1m", "/data/canonical/linked.parquet", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "wrong-version", "primary", "passed"),
            (7, "rqdata", "bars", "jm", "JM2609", "5m", "/data/canonical/direct-5m.parquet", "five-minute", "v2", "primary", "passed"),
        ],
    )
    connection.commit()
    return connection


def _complete_empty_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    for table in (
        "after_market_scheduler_checkpoints",
        "data_gaps", "data_profiles", "live_aggregated_bars", "live_aggregation_checkpoints", "live_ingest_checkpoints",
        "live_minute_bars", "main_contract_map", "market_datasets", "market_partitions",
    ):
        connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
    connection.execute(
        "CREATE TABLE profile_active_bindings (id INTEGER PRIMARY KEY, profile_id INTEGER, market_data_file_id INTEGER, "
        "data_version TEXT, binding_status TEXT)"
    )
    connection.execute("CREATE TABLE data_quality_reports (id INTEGER PRIMARY KEY, file_id INTEGER, task_id INTEGER)")
    connection.execute("CREATE TABLE data_download_tasks (id INTEGER PRIMARY KEY, status TEXT)")
    connection.execute(
        "CREATE TABLE backtest_tasks (id INTEGER PRIMARY KEY, profile_id INTEGER, market_data_file_id INTEGER, "
        "binding_snapshot TEXT, status TEXT)"
    )
    connection.execute(
        "CREATE TABLE backtest_reports (id INTEGER PRIMARY KEY, profile_id INTEGER, market_data_file_id INTEGER, "
        "binding_snapshot TEXT, status TEXT)"
    )
    connection.execute("CREATE TABLE backtest_trades (id INTEGER PRIMARY KEY, report_id INTEGER)")
    connection.execute("CREATE TABLE backtest_orders (id INTEGER PRIMARY KEY, report_id INTEGER)")
    connection.execute(
        "CREATE TABLE strategy_signals (id INTEGER PRIMARY KEY, profile_id INTEGER, market_data_file_id INTEGER, "
        "status TEXT, is_active INTEGER)"
    )
    connection.execute(
        "CREATE TABLE signal_events (id INTEGER PRIMARY KEY, profile_id INTEGER, market_data_file_id INTEGER, "
        "lifecycle_status TEXT)"
    )
    connection.execute("CREATE TABLE review_notes (id INTEGER PRIMARY KEY, source_type TEXT, source_id INTEGER)")
    connection.execute("CREATE TABLE review_attachments (id INTEGER PRIMARY KEY, review_id INTEGER)")
    connection.execute("CREATE TABLE review_tags (id INTEGER PRIMARY KEY, is_active INTEGER)")
    connection.execute(
        "CREATE TABLE signal_scan_tasks (id INTEGER PRIMARY KEY, profile_id INTEGER, market_data_file_id INTEGER, status TEXT)"
    )
    connection.execute(
        "CREATE TABLE signal_notifications (id INTEGER PRIMARY KEY, event_id INTEGER, signal_id INTEGER, status TEXT)"
    )
    connection.execute(
        "CREATE TABLE market_data_files (id INTEGER PRIMARY KEY, provider TEXT, data_type TEXT, instrument_symbol TEXT, contract_code TEXT, "
        "period TEXT, file_path TEXT, checksum TEXT, data_version TEXT, data_role TEXT, quality_status TEXT, task_id INTEGER)"
    )
    connection.execute("DROP TABLE market_datasets")
    connection.execute("CREATE TABLE market_datasets (id INTEGER PRIMARY KEY, provider TEXT, dataset_kind TEXT, symbol TEXT, contract_or_series TEXT, frequency TEXT, adjustment TEXT, schema_version TEXT)")
    connection.execute("DROP TABLE market_partitions")
    connection.execute(
        "CREATE TABLE market_partitions (id INTEGER PRIMARY KEY, dataset_id INTEGER, file_uri TEXT, manifest_uri TEXT, manifest_digest TEXT, checksum TEXT, manifest_version TEXT)"
    )
    connection.commit()
    return connection


def _write_fixture_files(repo_root: Path, data_root: Path) -> None:
    (repo_root / "docs").mkdir(parents=True)
    (repo_root / "services" / "quant-api" / "app").mkdir(parents=True)
    (repo_root / "docs" / "gate.md").write_text("report 14 backup\n", encoding="utf-8")
    (repo_root / "services" / "quant-api" / "app" / "example.py").write_text(
        "report_15_runtime_gate = True\n",
        encoding="utf-8",
    )
    for relative_path, contents in (
        ("raw/jm/source.parquet", b"one"),
        ("standard/jm/normalized.parquet", b"two"),
        ("parquet/canonical/jm/part-000.parquet", b"abc"),
        ("derived/indicators/cache.json", b"{}"),
        ("derived/15m/part.parquet", b"derived"),
        ("backtest/run.json", b"{}"),
        ("signals/event.json", b"{}"),
        ("reviews/note.json", b"{}"),
        ("live/bar.json", b"{}"),
        ("eod/reconcile.json", b"{}"),
        ("samples/sample.json", b"{}"),
        ("legacy/profile/binding.json", b"{}"),
        ("reports/report_14_snapshot.json", b"{}"),
    ):
        path = data_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)


def _write_active_reference_files(repo_root: Path) -> None:
    (repo_root / "docs").mkdir(parents=True)
    (repo_root / "services" / "quant-api" / "app" / "services").mkdir(parents=True)
    (repo_root / "docs" / "active.md").write_text(
        "indicator cache\nbacktest\nsignal review\nlive eod ResearchSample\nderived 15m\n"
        "raw standard canonical\nDataProfile ActiveBinding legacy lineage\nreport 14 backup runtime gate\n",
        encoding="utf-8",
    )
    (repo_root / "services" / "quant-api" / "app" / "services" / "consumer.py").write_text(
        "MarketDataService canonical_consumer_input_v1\n",
        encoding="utf-8",
    )
    (repo_root / "config.toml").write_text("backtest = true\n", encoding="utf-8")


class _FakePostgresConnection:
    def __init__(self) -> None:
        self.engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.statements: list[str] = []
        self.rollback_count = 0
        self.commit_count = 0

    def exec_driver_sql(self, statement: str, parameters: tuple[object, ...] = ()) -> _FakePostgresResult:
        self.statements.append(statement + (f" {parameters!r}" if parameters else ""))
        if statement == "SELECT to_regclass(%s)":
            return _FakePostgresResult([(parameters[0].split(".")[-1],)] if parameters == ("public.backtest_reports",) else [(None,)])
        if "information_schema.columns" in statement:
            return _FakePostgresResult([("id",)] if parameters == ("public", "backtest_reports") else [])
        if "COUNT(*)" in statement:
            return _FakePostgresResult([(1,)])
        if "SELECT id" in statement:
            return _FakePostgresResult([(14,)])
        return _FakePostgresResult([])

    def rollback(self) -> None:
        self.rollback_count += 1

    def commit(self) -> None:
        self.commit_count += 1


class _FakePostgresResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _BrokenSqliteConnection(sqlite3.Connection):
    def execute(self, statement: str, parameters: object = ()) -> sqlite3.Cursor:
        raise sqlite3.OperationalError("fixture read failure")
