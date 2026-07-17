from __future__ import annotations

from datetime import date
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


def _module():
    return importlib.import_module("app.services.rqdata_ingest.direct_db_baseline_audit")


def test_unified_matrix_uses_only_final_classification_enum() -> None:
    module = _module()
    rows = module.build_unified_target_matrix(
        [
            _coverage(status="covered_passed", quality_status="passed"),
            _coverage(status="covered_warning", quality_status="warning", year=2025),
            _coverage(status="not_applicable", quality_status="", year=2019),
            _coverage(status="missing", quality_status="", year=2024),
        ]
    )

    assert {row["final_classification"] for row in rows} == {
        "covered_passed",
        "covered_warning",
        "not_applicable",
        "blocked_with_reason",
    }
    assert set(module.UNIFIED_MATRIX_COLUMNS).issubset(rows[0])
    assert all(row["classification_source"] for row in rows)


def test_conflict_partial_and_duplicate_never_classify_as_passed() -> None:
    module = _module()
    base = _coverage(status="covered_passed", quality_status="passed")

    conflict = module.build_unified_target_matrix([base], conflict_keys={module.coverage_key(base)})[0]
    partial = module.build_unified_target_matrix([{**base, "is_partial_window": True}])[0]
    duplicate = module.build_unified_target_matrix([{**base, "duplicate_active_count": 2}])[0]

    assert conflict["final_classification"] == "covered_warning"
    assert partial["final_classification"] == "covered_warning"
    assert duplicate["final_classification"] == "blocked_with_reason"


def test_coverage_key_accepts_duplicate_active_contract_code_shape() -> None:
    module = _module()

    assert module.coverage_key(
        {"product": "jm", "contract_role": "actual_contract", "contract_code": "JM2609", "period": "1d"}
    ) == ("jm", "actual_contract", "JM2609", "1d")


def test_profile_binding_rows_detect_missing_and_invalid_targets() -> None:
    module = _module()
    profiles = [
        SimpleNamespace(
            profile_id="research",
            quality_policy="passed_only",
            is_active=True,
            contract_roles=["dominant_main"],
            periods=["1d"],
        )
    ]
    bindings = [
        SimpleNamespace(
            id=1,
            profile_id="research",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            contract_role="dominant_main",
            period="1d",
            data_version="v1",
            market_data_file_id=10,
            binding_status="active",
        ),
        SimpleNamespace(
            id=2,
            profile_id="missing-profile",
            instrument_symbol="rb",
            contract_code="rb.MAIN",
            contract_role="dominant_main",
            period="1d",
            data_version="v2",
            market_data_file_id=999,
            binding_status="active",
        ),
    ]
    files = [
        SimpleNamespace(
            id=10,
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            data_version="v1",
            provider="rqdata",
            data_role="primary",
            quality_status="passed",
            file_path="/tmp/a",
        )
    ]

    rows = module.build_profile_binding_rows(profiles=profiles, bindings=bindings, market_files=files)

    assert rows[0]["binding_status"] == "active_valid"
    assert rows[0]["final_classification"] == "covered_passed"
    assert rows[1]["binding_status"] == "profile_missing;market_data_file_missing"
    assert rows[1]["final_classification"] == "blocked_with_reason"


def test_profile_binding_identity_mismatch_is_blocked() -> None:
    module = _module()
    profile = SimpleNamespace(
        profile_id="research",
        quality_policy="passed_only",
        is_active=True,
        contract_roles=["dominant_main"],
        periods=["1d"],
    )
    binding = SimpleNamespace(
        id=1,
        profile_id="research",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        contract_role="dominant_main",
        period="1d",
        data_version="v1",
        market_data_file_id=10,
        binding_status="active",
    )
    wrong_file = SimpleNamespace(
        id=10,
        instrument_symbol="rb",
        contract_code="rb.MAIN",
        period="1d",
        data_version="v2",
        provider="rqdata",
        data_role="primary",
        quality_status="passed",
        file_path="/tmp/rb",
    )

    row = module.build_profile_binding_rows(profiles=[profile], bindings=[binding], market_files=[wrong_file])[0]

    assert row["binding_status"] == "binding_file_identity_mismatch"
    assert row["final_classification"] == "blocked_with_reason"


def test_profile_binding_audit_emits_expected_missing_binding(tmp_path: Path) -> None:
    module = _module()
    config = tmp_path / "profile.json"
    config.write_text(
        json.dumps(
            {
                "profile_id": "research",
                "contract_roles": ["dominant_main"],
                "periods": ["1d"],
                "binding_scope": {"products": ["jm"]},
            }
        )
    )
    profile = SimpleNamespace(
        profile_id="research",
        quality_policy="passed_only",
        is_active=True,
        config_path=str(config),
        contract_roles=["dominant_main"],
        periods=["1d"],
    )

    rows = module.build_profile_binding_audit(
        profiles=[profile],
        bindings=[],
        market_files=[],
        coverage_rows=[_coverage(status="covered_passed", quality_status="passed")],
        project_root=tmp_path,
    )

    assert rows == [
        {
            "binding_id": None,
            "profile": "research",
            "product": "jm",
            "contract": "jm.MAIN",
            "contract_role": "dominant_main",
            "period": "1d",
            "data_version": "",
            "market_data_file_id": None,
            "binding_status": "binding_missing",
            "quality_policy": "passed_only",
            "final_classification": "blocked_with_reason",
            "classification_source": "profile_binding:binding_missing",
        }
    ]


def test_direct_database_gate_rejects_non_postgresql(tmp_path: Path) -> None:
    module = _module()
    session = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))

    with pytest.raises(module.DirectDatabaseGateError, match="must be PostgreSQL"):
        module.collect_direct_database_evidence(
            session,
            project_root=tmp_path,
            audit_end=date(2026, 7, 10),
            git_commit="abc",
            branch="codex/b-01",
            worktree=str(tmp_path),
        )


def test_blocked_package_contains_no_completion_matrices(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "blocked"

    paths = module.write_blocked_environment_package(
        output,
        evidence={"gate": module.BLOCKED_GATE, "db_snapshot_source": "unavailable", "db_error": "connection refused"},
    )

    assert json.loads((output / "environment_evidence.json").read_text())["gate"] == module.BLOCKED_GATE
    assert (output / "blocked_items.csv").exists()
    assert (output / "BLOCKED_DIRECT_DB_UNAVAILABLE.md").exists()
    assert not (output / "target_coverage_matrix.csv").exists()
    assert set(paths) == {"environment_evidence", "blocked_items", "blocked_summary"}


def test_write_success_reports_required_outputs_and_old_metric_delta(tmp_path: Path) -> None:
    module = _module()
    matrix = module.build_unified_target_matrix([_coverage(status="covered_passed", quality_status="passed")])
    payload = {
        "environment_evidence": {"db_snapshot_source": "database", "gate": module.READY_GATE},
        "target_coverage_matrix": matrix,
        "metadata_consistency_matrix": [],
        "weekly_gaps": [],
        "actual_roll_gaps": [],
        "profile_bindings": [],
        "cross_file_conflicts": [],
        "blocked_items": [],
        "physical_evidence": [],
    }

    output = tmp_path / "ready"
    paths = module.write_success_reports(output, payload=payload, audit_end=date(2026, 7, 10))
    summary = json.loads((output / "baseline_summary.json").read_text())

    assert module.REQUIRED_SUCCESS_FILENAMES.issubset({path.name for path in paths.values()})
    assert summary["current_metrics"]["covered_passed"] == 1
    assert summary["phase3_delta"]["covered_passed"] == 1 - 15350
    assert Path(summary["next_inputs"]["B-02"]) == output / "metadata_consistency_matrix.csv"
    assert Path(summary["next_inputs"]["B-02"]).is_file()
    assert list(pd.read_csv(tmp_path / "ready" / "weekly_gaps.csv").columns)
    assert list(pd.read_csv(tmp_path / "ready" / "profile_bindings.csv").columns)


def test_success_writer_never_overwrites_existing_directory(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "ready"
    output.mkdir()
    marker = output / "owned-by-other-process"
    marker.write_text("keep")

    with pytest.raises(FileExistsError):
        module.write_success_reports(
            output,
            payload={
                "environment_evidence": {"db_snapshot_source": "database"},
                "target_coverage_matrix": [],
                "metadata_consistency_matrix": [],
                "weekly_gaps": [],
            },
            audit_end=date(2026, 7, 10),
        )

    assert marker.read_text() == "keep"


def test_success_writer_cleans_private_temp_on_mid_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    calls = 0
    original = module._write_csv  # noqa: SLF001

    def fail_after_first(path, rows, columns):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        return original(path, rows, columns)

    monkeypatch.setattr(module, "_write_csv", fail_after_first)

    with pytest.raises(OSError, match="disk full"):
        module.write_success_reports(
            tmp_path / "ready",
            payload={
                "environment_evidence": {"db_snapshot_source": "database"},
                "target_coverage_matrix": [],
                "metadata_consistency_matrix": [],
                "weekly_gaps": [],
            },
            audit_end=date(2026, 7, 10),
        )

    assert not (tmp_path / "ready").exists()
    assert list(tmp_path.iterdir()) == []


def test_physical_audit_reuses_canonical_schema_contract(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "bad.parquet"
    pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-07-10"]),
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1],
            "open_interest": [1.0],
        }
    ).to_parquet(path)

    row = module.inspect_physical_evidence(
        [{"physical_path": str(path), "period": "1d", "contract_role": "dominant_main"}],
        project_root=tmp_path,
        expected_checksum_by_path={},
    )[0]

    assert row["schema_status"] == "schema_invalid"
    assert "turnover" in row["schema_missing"]
    assert row["physical_status"] == "schema_invalid"


def test_sanitize_error_redacts_json_and_url_credentials() -> None:
    module = _module()
    message = 'password: "top-secret" authorization="Bearer secret" postgresql://user:pw@127.0.0.1/db'

    sanitized = module.sanitize_error(message)

    assert "top-secret" not in sanitized
    assert "Bearer secret" not in sanitized
    assert ":pw@" not in sanitized


def test_missing_profile_products_file_fails_closed(tmp_path: Path) -> None:
    module = _module()
    config = tmp_path / "profile.json"
    config.write_text(
        json.dumps(
            {
                "contract_roles": ["dominant_main"],
                "periods": ["1d"],
                "binding_scope": {"products_file": "missing-products.txt"},
            }
        )
    )
    profile = SimpleNamespace(
        profile_id="research",
        quality_policy="passed_only",
        is_active=True,
        config_path=str(config),
        contract_roles=["dominant_main"],
        periods=["1d"],
    )

    with pytest.raises(module.AuditInputGateError, match="profile products file unavailable"):
        module.build_profile_binding_audit(
            profiles=[profile],
            bindings=[],
            market_files=[],
            coverage_rows=[_coverage(status="covered_passed", quality_status="passed")],
            project_root=tmp_path,
        )


def test_followup_inputs_preserve_weekly_and_actual_warnings() -> None:
    module = _module()
    weekly = module._build_weekly_gaps(  # noqa: SLF001
        [
            {
                "product": "jm",
                "pre_2020_status": "covered",
                "post_2020_passed_years": 7,
                "post_2020_expected_years": 7,
                "direct_1w_present": True,
            }
        ],
        [{**_coverage(status="covered_warning", quality_status="warning"), "period": "1w", "final_classification": "covered_warning"}],
    )
    actual = module._build_actual_roll_gaps(  # noqa: SLF001
        [
            {
                **_coverage(status="covered_warning", quality_status="warning"),
                "contract_role": "actual_contract",
                "final_classification": "covered_warning",
            }
        ],
        [],
    )

    assert weekly[0]["final_classification"] == "covered_warning"
    assert weekly[0]["next_task"] == "B-03"
    assert actual[0]["final_classification"] == "covered_warning"
    assert actual[0]["next_task"] == "B-04"


def test_full_universe_scope_rejects_subset() -> None:
    module = _module()

    with pytest.raises(module.AuditInputGateError, match="canonical full universe"):
        module.validate_full_universe_scope(
            products=["jm"],
            canonical_products=["jm", "rb"],
            window_products={"jm"},
        )


def _coverage(*, status: str, quality_status: str, year: int = 2026) -> dict:
    return {
        "product": "jm",
        "contract_role": "dominant_main",
        "symbol_or_contract": "jm.MAIN",
        "period": "1d",
        "year": year,
        "status": status,
        "issue_type": "" if status == "covered_passed" else status,
        "expected_start": f"{year}-01-01",
        "expected_end": f"{year}-07-10",
        "provider": "rqdata",
        "data_role": "primary",
        "quality_status": quality_status,
        "standard_path": "/tmp/jm.parquet",
        "evidence_source": "db_market_data_file,manifest",
        "db_market_data_file_id": 1,
    }
