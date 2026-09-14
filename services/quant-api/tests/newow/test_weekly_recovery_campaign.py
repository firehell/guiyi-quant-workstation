from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import threading
from typing import Any, Mapping

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.historical_data_manager import (
    BarBatch,
    BarFetchRequest,
    ContractWarmupRequest,
    HistoricalDataManager,
)
from app.market_data.newow.product_release import deferred_section_reason
from app.market_data.operational_universe import load_operational_products
from app.market_data.rqdata_adapter import ExchangeDailySourceRequest
from app.market_data.storage import CanonicalMonthlyStore
from app.models import Contract, Exchange, Instrument
from scripts.newow_weekly_recovery import (
    RecoveryError,
    _post_commit_readback,
    _write_json_exclusive,
    execute_prepared_batch,
    load_prepared_manifest,
    prepare_bounded_units,
    write_prepared_manifest,
)
from scripts.newow_weekly_recovery_campaign import (
    execute_campaign,
    main,
    parser,
    partition_ordinary_units,
    prepare_campaign,
    validate_campaign_manifest,
)
from tests.data_foundation.test_historical_data_manager import FakeCoverage, FakeMetadata


IDENTITY = {
    "code_commit": "b" * 40,
    "execution_code_sha256": "d" * 64,
    "config_sha256": "c" * 64,
    "canonical_root_sha256": "e" * 64,
}


def _ordinary_unit(index: int = 0) -> dict[str, Any]:
    return {
        "symbol": "ag",
        "contract": f"AG{1000 + index}",
        "through": "2026-09-11",
        "requested_through": "2026-09-11",
        "frequency": "1w",
        "plan_sha256": f"{index:064x}",
        "status": "PROPOSED",
        "expected_bar_count": index + 1,
        "target_windows": [
            {
                "dataset": ["contract", "ag", f"AG{1000 + index}", "1d"],
                "year": 2026,
                "month": 9,
                "expected_bar_count": index + 1,
            },
            {
                "dataset": ["contract", "ag", f"AG{1000 + index}", "1w"],
                "year": 2026,
                "month": 9,
                "expected_bar_count": 1,
            },
        ],
    }


def _report(units: list[dict[str, Any]]) -> dict[str, Any]:
    as_of = "2026-09-13T06:36:13+00:00"
    products = load_operational_products()
    requested: dict[str, dict[str, str]] = {}
    for item in units:
        requested.setdefault(item["symbol"], {})[item["contract"]] = item["through"]
    owners_by_symbol = {
        symbol: (
            requested.get(symbol)
            or {f"{symbol.upper()}1000": "2026-09-11"}
        )
        for symbol in products
    }
    enumerations = []
    for symbol in products:
        for section in ("chart", "auxiliary", "reference", "explanation"):
            row: dict[str, Any] = {
                "symbol": symbol,
                "frequency": "1w",
                "section": section,
                "status": "ENUMERATED",
                "as_of": as_of,
            }
            reason = deferred_section_reason(section)
            if reason is not None:
                row.update(status="UNOPENED", reason=reason)
            else:
                row.update(
                    since="2024-01-01",
                    through="2026-09-11",
                    owner_count=len(owners_by_symbol[symbol]),
                )
            enumerations.append(row)
    dependencies = []
    repair_keys = {(item["symbol"], item["contract"]) for item in units}
    for symbol, contracts in owners_by_symbol.items():
        for contract, through in contracts.items():
            for cutoff, sections in (
                (as_of, ("chart", "auxiliary")),
                ("2026-09-11T07:00:00+00:00", ("reference",)),
            ):
                dependency: dict[str, Any] = {
                    "symbol": symbol,
                    "contract": contract,
                    "frequency": "1w",
                    "through": through,
                    "as_of": cutoff,
                    "consumers": [
                        {
                            "strategy": strategy,
                            "frequency": "1w",
                            "section": section,
                        }
                        for section in sections
                        for strategy in ("trend", "oscillation", "main_rise")
                    ],
                    "owners": [{"since": "2024-01-01", "through": through}],
                }
                if (symbol, contract) in repair_keys:
                    dependency.update(
                        status="DATA_UNAVAILABLE",
                        reason="REPLAY_PREFIX_MISSING",
                        error={"code": "NEWOW_DATA_UNAVAILABLE", "diagnostic": {}},
                    )
                else:
                    dependency.update(
                        status="DATA_READY",
                        cutoff=f"{through}T07:00:00+00:00",
                        actual_bar_count=1,
                        expected_bar_count=1,
                    )
                dependencies.append(dependency)
    return {
        "schema_version": 1,
        "command": "data.newow-readiness",
        "status": "audited",
        "complete": True,
        "budget_exhausted": False,
        "readonly": True,
        "provider_requests": 0,
        "writes": 0,
        "release_stage": "weekly",
        "frequency_scope": ["1w"],
        "matrix": False,
        "as_of": as_of,
        "product_count": len(products),
        "main_case_count": 0,
        "main_ready_count": 0,
        "work_used": len(products) * 3 + len(dependencies) + len(units),
        "enumerations": enumerations,
        "dependencies": dependencies,
        "cases": [],
        "metadata_proposals": [],
        "repair_targets": units,
    }


def _native_child(
    root: Path,
    batch_id: str,
    units: tuple[dict[str, Any], ...],
    *,
    identity: Mapping[str, str] = IDENTITY,
) -> dict[str, Any]:
    child_units = []
    for item in units:
        child_units.append(
            {
                "symbol": item["symbol"],
                "contract": item["contract"],
                "through": item["through"],
                "frequency": item["frequency"],
                "plan_sha256": item["expected_plan_sha256"],
                "target_count": 2,
                "expected_bar_count": 2,
                "targets": [
                    {
                        "dataset": [
                            "contract",
                            item["symbol"],
                            item["contract"],
                            "1d",
                        ],
                        "year": 2026,
                        "month": 9,
                        "expected_start": "2026-09-01T07:00:00+00:00",
                        "expected_end": "2026-09-02T07:00:00+00:00",
                        "expected_bar_count": 1,
                    },
                    {
                        "dataset": [
                            "contract",
                            item["symbol"],
                            item["contract"],
                            "1w",
                        ],
                        "year": 2026,
                        "month": 9,
                        "expected_start": "2026-09-04T07:00:00+00:00",
                        "expected_end": "2026-09-04T07:00:00+00:00",
                        "expected_bar_count": 1,
                    },
                ],
                "source_requests": [],
            }
        )
    manifest = {
        "schema_version": "newow_weekly_recovery_prepare_v1",
        **identity,
        "unit_count": len(child_units),
        "units": child_units,
    }
    path = root / f"{batch_id}.prepare.json"
    digest = _write_json_exclusive(path, manifest)
    return {
        "status": "prepared",
        "readonly": True,
        "provider_requests": 0,
        "writes": 0,
        "prepared_file": str(path),
        "prepared_sha256": digest,
        "unit_count": len(child_units),
    }


def _campaign(tmp_path: Path, count: int) -> dict[str, Any]:
    return prepare_campaign(
        _report([_ordinary_unit(index) for index in range(count)]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(
            root, batch_id, units
        ),
    )


def _native_apply_result(
    child_path: Path,
    digest: str,
    batch_attempt: Path,
    *,
    status: str = "passed",
    return_code: int | None = None,
    completed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    child = json.loads(child_path.read_text(encoding="utf-8"))
    if completed is None and status == "passed":
        completed = [
            {
                **unit,
                "status": "passed",
                "remaining_target_count": 0,
                "readback": {
                    "catalog_physical_mds": "passed",
                    "mds_target_count": unit["target_count"],
                },
            }
            for unit in child["units"]
        ]
    completed_value = completed if completed is not None else []
    failure_index = len(completed_value)
    native_result = {
        "status": status,
        "completed": completed_value,
        "failed": (
            None
            if status == "passed"
            else {**child["units"][failure_index], "status": status}
        ),
        "unattempted": (
            [] if status == "passed" else child["units"][failure_index + 1 :]
        ),
        "retries": 0,
    }
    native_attempt = batch_attempt / "native"
    native_attempt.mkdir()
    receipt = {
        "schema_version": "newow_weekly_recovery_invocation_v1",
        "prepared_sha256": digest,
        **IDENTITY,
        "unit_count": len(child["units"]),
    }
    _write_json_exclusive(native_attempt / "invocation-receipt.json", receipt)
    _write_json_exclusive(native_attempt / "batch-result.json", native_result)
    return {
        "return_code": (0 if status == "passed" else 1)
        if return_code is None
        else return_code,
        "batch_result": {
            "schema_version": "newow_weekly_recovery_result_v1",
            "status": status,
            "readonly": False,
            "attempt_dir": str(native_attempt),
            "result": native_result,
        },
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("complete", False),
        ("budget_exhausted", True),
        ("as_of", "2026-09-13"),
        ("as_of", "not-a-date"),
        ("frequency_scope", ["1d"]),
        ("matrix", True),
        ("readonly", False),
        ("provider_requests", 1),
        ("writes", 1),
    ],
)
def test_partition_rejects_incomplete_exhausted_or_wrong_audit(
    field: str,
    value: object,
) -> None:
    report = _report([_ordinary_unit()])
    report[field] = value

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_rejects_missing_required_report_field() -> None:
    report = _report([_ordinary_unit()])
    del report["repair_targets"]

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


@pytest.mark.parametrize(
    "field",
    [
        "product_count",
        "main_case_count",
        "main_ready_count",
        "work_used",
        "enumerations",
        "dependencies",
        "cases",
    ],
)
def test_partition_rejects_cropped_native_report(field: str) -> None:
    report = _report([_ordinary_unit()])
    del report[field]

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_product_count",
        "missing_enumeration",
        "bad_deferred_enumeration",
        "missing_owner_count",
        "wrong_dependency_frequency",
        "missing_dependency_consumers",
        "missing_dependency_owners",
        "wrong_main_counts",
        "wrong_work_used",
    ],
)
def test_partition_rejects_inconsistent_native_report_sections(mutation: str) -> None:
    report = _report([_ordinary_unit()])
    if mutation == "wrong_product_count":
        report["product_count"] -= 1
    elif mutation == "missing_enumeration":
        report["enumerations"].pop()
    elif mutation == "bad_deferred_enumeration":
        report["enumerations"][-1]["reason"] = "WRONG"
    elif mutation == "missing_owner_count":
        del report["enumerations"][0]["owner_count"]
    elif mutation == "wrong_dependency_frequency":
        report["dependencies"][0]["frequency"] = "1d"
    elif mutation == "missing_dependency_consumers":
        del report["dependencies"][0]["consumers"]
    elif mutation == "missing_dependency_owners":
        del report["dependencies"][0]["owners"]
    elif mutation == "wrong_main_counts":
        report["main_case_count"] = 1
    elif mutation == "wrong_work_used":
        report["work_used"] += 1

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_rejects_missing_dependency_even_when_work_used_is_synced() -> None:
    report = _report([_ordinary_unit()])
    report["dependencies"].pop(0)
    report["work_used"] -= 1

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_rejects_duplicate_full_dependency_identity() -> None:
    report = _report([_ordinary_unit()])
    report["dependencies"].append(deepcopy(report["dependencies"][0]))
    report["work_used"] += 1

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


def test_partition_rejects_owner_removed_from_one_section_coverage() -> None:
    report = _report([])
    symbol = load_operational_products()[0]
    rows = [row for row in report["dependencies"] if row["symbol"] == symbol]
    assert len(rows) == 2
    second_owner = {"since": "2024-02-01", "through": rows[0]["through"]}
    for row in rows:
        row["owners"].append(second_owner)
    for enumeration in report["enumerations"]:
        if enumeration["symbol"] == symbol and enumeration["status"] == "ENUMERATED":
            enumeration["owner_count"] = 2
    rows[0]["owners"].remove(second_owner)

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(report)


@pytest.mark.parametrize("count", [0, 1, 20, 21, 1117])
def test_partition_has_exact_twenty_unit_boundaries_without_loss(count: int) -> None:
    units = [_ordinary_unit(index) for index in range(count)]

    batches = partition_ordinary_units(_report(units))

    expected_sizes = [20] * (count // 20)
    if count % 20:
        expected_sizes.append(count % 20)
    assert [len(group) for group in batches] == expected_sizes
    assert {
        (unit["symbol"], unit["contract"], unit["frequency"])
        for group in batches
        for unit in group
    } == {(unit["symbol"], unit["contract"], "1w") for unit in units}


def test_partition_excludes_nonordinary_statuses_and_campaign_counts_them(
    tmp_path: Path,
) -> None:
    review = {**_ordinary_unit(1), "status": "REVIEW_REQUIRED"}
    source_error = {
        **_ordinary_unit(2),
        "status": "SOURCE_EXCEPTION",
        "plan_sha256": None,
    }
    report = _report([_ordinary_unit(), review, source_error])

    batches = partition_ordinary_units(report)
    manifest = prepare_campaign(
        report,
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(
            root, batch_id, units
        ),
    )

    assert [[unit["contract"] for unit in group] for group in batches] == [["AG1000"]]
    assert manifest["scope"]["included_status_counts"] == {"PROPOSED": 1}
    assert manifest["scope"]["excluded_status_counts"] == {
        "REVIEW_REQUIRED": 1,
        "SOURCE_EXCEPTION": 1,
    }


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"through": "2026-09-10", "requested_through": "2026-09-10"},
        {"plan_sha256": "f" * 64},
    ],
)
def test_partition_rejects_duplicate_or_conflicting_unit_identity(
    change: dict[str, Any],
) -> None:
    first = _ordinary_unit()
    duplicate = {**first, **change}

    with pytest.raises(RecoveryError, match="^CAMPAIGN_SCOPE_CONFLICT$"):
        partition_ordinary_units(_report([first, duplicate]))


def test_partition_rejects_target_through_after_audit_as_of() -> None:
    unit = {**_ordinary_unit(), "through": "2026-09-14", "requested_through": "2026-09-14"}

    with pytest.raises(RecoveryError, match="^CAMPAIGN_REPORT_INVALID$"):
        partition_ordinary_units(_report([unit]))


def test_prepare_builds_all_children_and_one_hash_locked_campaign(tmp_path: Path) -> None:
    report = _report([_ordinary_unit(index) for index in range(21)])
    calls: list[tuple[str, int]] = []

    def invoke(
        units: tuple[dict[str, Any], ...], batch_id: str, root: Path
    ) -> dict[str, Any]:
        calls.append((batch_id, len(units)))
        return _native_child(root, batch_id, units)

    manifest = prepare_campaign(
        report,
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=invoke,
    )

    assert [child["batch_id"] for child in manifest["children"]] == [
        "batch-001",
        "batch-002",
    ]
    assert calls == [
        (manifest["children"][0]["artifact_id"], 20),
        (manifest["children"][1]["artifact_id"], 1),
    ]
    assert manifest["totals"] == {
        "batch_count": 2,
        "unit_count": 21,
        "target_count": 42,
        "expected_bar_count": 42,
    }
    assert manifest["children"][0]["unit_count"] == 20
    assert manifest["children"][-1]["unit_count"] == 1
    assert len(manifest["children"][0]["sha256"]) == 64
    assert manifest["children"][0]["path"] == (
        manifest["children"][0]["artifact_id"] + ".prepare.json"
    )
    assert manifest["children"][0]["artifact_id"].startswith("campaign-")
    assert manifest["writer_guard"]["path"] == (
        ".campaign-writer-" + IDENTITY["canonical_root_sha256"] + ".lock"
    )
    assert (tmp_path / manifest["writer_guard"]["path"]).is_file()
    assert len(manifest["scope"]["unit_identity_sha256"]) == 64
    assert len(manifest["scope"]["target_identity_sha256"]) == 64
    assert (tmp_path / "campaign.prepare.json").is_file()
    assert validate_campaign_manifest(manifest, evidence_root=tmp_path) == manifest

    with pytest.raises(RecoveryError, match="^CAMPAIGN_MANIFEST_EXISTS$"):
        prepare_campaign(
            report,
            report_sha256="f" * 64,
            evidence_root=tmp_path,
            execution_identity=IDENTITY,
            invoke_batch=invoke,
        )


def test_prepare_two_named_campaigns_share_root_without_overwriting_children(
    tmp_path: Path,
) -> None:
    report = _report([_ordinary_unit()])

    alpha = prepare_campaign(
        report,
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, artifact_id, root: _native_child(
            root, artifact_id, units
        ),
        name="alpha",
    )
    beta = prepare_campaign(
        report,
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, artifact_id, root: _native_child(
            root, artifact_id, units
        ),
        name="beta",
    )

    assert alpha["children"][0]["batch_id"] == "batch-001"
    assert beta["children"][0]["batch_id"] == "batch-001"
    assert alpha["children"][0]["path"] != beta["children"][0]["path"]
    assert alpha["writer_guard"] == beta["writer_guard"]
    assert (tmp_path / alpha["children"][0]["path"]).is_file()
    assert (tmp_path / beta["children"][0]["path"]).is_file()


def test_prepare_zero_units_creates_only_readonly_completed_campaign(tmp_path: Path) -> None:
    calls: list[object] = []

    manifest = prepare_campaign(
        _report([]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda *_args: calls.append(True),
    )

    assert calls == []
    assert manifest["status"] == "completed"
    assert manifest["readonly"] is True
    assert manifest["children"] == []
    assert manifest["totals"]["unit_count"] == 0
    assert manifest["provider_requests"] == 0
    assert manifest["writes"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_child",
        "extra_child",
        "reordered",
        "duplicate_unit",
        "wrong_hash",
        "wrong_identity",
        "absolute_path",
        "escaped_path",
    ],
)
def test_validate_campaign_rejects_incomplete_or_drifted_children_before_execution(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest = prepare_campaign(
        _report([_ordinary_unit(index) for index in range(21)]),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(
            root, batch_id, units
        ),
    )
    changed = deepcopy(manifest)
    if mutation == "missing_child":
        changed["children"].pop()
    elif mutation == "extra_child":
        changed["children"].append(deepcopy(changed["children"][-1]))
        changed["children"][-1]["batch_id"] = "batch-003"
    elif mutation == "reordered":
        changed["children"].reverse()
    elif mutation == "duplicate_unit":
        changed["children"][1]["units"] = [
            deepcopy(changed["children"][0]["units"][0])
        ]
    elif mutation == "wrong_hash":
        changed["children"][0]["sha256"] = "0" * 64
    elif mutation == "wrong_identity":
        changed["execution_identity"]["config_sha256"] = "0" * 64
    elif mutation == "absolute_path":
        changed["children"][0]["path"] = str(
            (tmp_path / "batch-001.prepare.json").resolve()
        )
    elif mutation == "escaped_path":
        changed["children"][0]["path"] = "../batch-001.prepare.json"

    with pytest.raises(RecoveryError):
        validate_campaign_manifest(changed, evidence_root=tmp_path)


def test_validate_campaign_rejects_symlinked_child(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    manifest = prepare_campaign(
        _report([_ordinary_unit()]),
        report_sha256="f" * 64,
        evidence_root=real,
        execution_identity=IDENTITY,
        invoke_batch=lambda units, batch_id, root: _native_child(
            root, batch_id, units
        ),
    )
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(RecoveryError, match="^CAMPAIGN_OUTPUT_ROOT_UNSAFE$"):
        validate_campaign_manifest(manifest, evidence_root=linked)


def test_validate_campaign_rejects_target_identity_drift_even_with_new_child_hash(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1)
    child_path = tmp_path / manifest["children"][0]["path"]
    child = json.loads(child_path.read_text())
    child["units"][0]["targets"][0]["dataset"][3] = "60m"
    child_path.write_text(
        json.dumps(child, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    manifest["children"][0]["sha256"] = hashlib.sha256(
        child_path.read_bytes()
    ).hexdigest()

    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        validate_campaign_manifest(manifest, evidence_root=tmp_path)


def test_validate_campaign_rejects_unit_expected_count_not_closed_by_targets(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1)
    child_path = tmp_path / manifest["children"][0]["path"]
    child = json.loads(child_path.read_text())
    child["units"][0]["expected_bar_count"] = 3
    child_path.write_text(
        json.dumps(child, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    manifest["children"][0]["sha256"] = hashlib.sha256(
        child_path.read_bytes()
    ).hexdigest()
    manifest["children"][0]["units"][0]["expected_bar_count"] = 3
    manifest["children"][0]["expected_bar_count"] = 3
    manifest["totals"]["expected_bar_count"] = 3

    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        validate_campaign_manifest(manifest, evidence_root=tmp_path)


def test_prepare_rejects_wrong_callback_type_without_campaign(tmp_path: Path) -> None:
    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        prepare_campaign(
            _report([_ordinary_unit()]),
            report_sha256="f" * 64,
            evidence_root=tmp_path,
            execution_identity=IDENTITY,
            invoke_batch=lambda *_args: [],
        )

    assert not (tmp_path / "campaign.prepare.json").exists()


def test_validate_campaign_rejects_oversized_child(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 1)
    path = tmp_path / manifest["children"][0]["path"]
    path.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    manifest["children"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        validate_campaign_manifest(manifest, evidence_root=tmp_path)


def test_cli_prepare_uses_native_main_in_process_and_one_evidence_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    report = _report([_ordinary_unit(index) for index in range(21)])
    report_path = tmp_path / "full-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    report_sha256 = hashlib.sha256(report_path.read_bytes()).hexdigest()
    project_env = tmp_path / "project.env"
    project_env.write_text("fixture", encoding="utf-8")
    native_calls: list[list[str]] = []

    monkeypatch.setattr(module, "_current_execution_identity", lambda _path: IDENTITY)

    def native_main(argv: list[str], *, stdout: io.StringIO) -> int:
        native_calls.append(argv)
        assert argv[0] == "prepare"
        root = Path(argv[argv.index("--output-root") + 1])
        batch_id = argv[argv.index("--name") + 1]
        units_path = Path(argv[argv.index("--units") + 1])
        assert root == tmp_path
        assert units_path.parent == tmp_path
        units = tuple(json.loads(units_path.read_text()))
        payload = _native_child(root, batch_id, units)
        stdout.write(json.dumps(payload))
        return 0

    monkeypatch.setattr(module.native, "main", native_main)
    output = io.StringIO()

    code = main(
        [
            "prepare",
            "--project-env",
            str(project_env),
            "--report",
            str(report_path),
            "--expected-report-sha256",
            report_sha256,
            "--output-root",
            str(tmp_path),
            "--name",
            "campaign",
        ],
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert code == 0
    assert payload["status"] == "prepared"
    assert payload["readonly"] is True
    assert payload["provider_requests"] == 0
    assert payload["writes"] == 0
    assert payload["batch_count"] == 2
    assert len(native_calls) == 2
    assert Path(payload["campaign_file"]) == tmp_path / "campaign.prepare.json"
    assert hashlib.sha256((tmp_path / "campaign.prepare.json").read_bytes()).hexdigest() == payload[
        "campaign_sha256"
    ]


def test_cli_prepare_rejects_report_hash_mismatch_before_native_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    report_path = tmp_path / "full-report.json"
    report_path.write_text(json.dumps(_report([_ordinary_unit()])), encoding="utf-8")
    project_env = tmp_path / "project.env"
    project_env.write_text("fixture", encoding="utf-8")
    native_calls: list[object] = []
    monkeypatch.setattr(module.native, "main", lambda *_args, **_kwargs: native_calls.append(True))
    output = io.StringIO()

    code = main(
        [
            "prepare",
            "--project-env",
            str(project_env),
            "--report",
            str(report_path),
            "--expected-report-sha256",
            "0" * 64,
            "--output-root",
            str(tmp_path),
            "--name",
            "campaign",
        ],
        stdout=output,
    )

    assert code == 1
    assert json.loads(output.getvalue())["error_code"] == "CAMPAIGN_REPORT_INVALID"
    assert native_calls == []


def test_campaign_cli_exposes_prepare_apply_and_inspect_modes() -> None:
    assert "{prepare,apply,inspect}" in parser().format_help()


def test_execute_stops_after_second_batch_failure_without_retry(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 41)
    invoked: list[str] = []

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        batch_id = attempt.name
        invoked.append(batch_id)
        return _native_apply_result(
            child,
            digest,
            attempt,
            status="passed" if batch_id == "batch-001" else "failed",
        )

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert invoked == ["batch-001", "batch-002"]
    assert result["status"] == "partial"
    assert result["completed_batch_ids"] == ["batch-001"]
    assert result["failed_batch"]["batch_id"] == "batch-002"
    assert result["unattempted_batch_ids"] == ["batch-003"]
    assert result["retries"] == 0


def test_execute_preserves_native_partial_success_exactly(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 22)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        prepared = json.loads(child.read_text())
        unit = prepared["units"][0]
        completed = [
            {
                **unit,
                "status": "passed",
                "remaining_target_count": 0,
                "readback": {
                    "catalog_physical_mds": "passed",
                    "mds_target_count": unit["target_count"],
                },
            }
        ]
        return _native_apply_result(
            child,
            digest,
            attempt,
            status="partial" if attempt.name == "batch-002" else "passed",
            completed=completed if attempt.name == "batch-002" else None,
        )

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "partial"
    assert result["failed_batch"]["native_result"]["result"]["completed"][0][
        "contract"
    ] == "AG1020"
    assert result["retries"] == 0


def test_execute_rejects_passed_terminal_without_all_frozen_units(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1)

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=lambda child, digest, attempt: _native_apply_result(
            child, digest, attempt, completed=[]
        ),
    )

    assert result["status"] == "unknown"
    assert result["unknown_batch"] == {
        "batch_id": "batch-001",
        "error_code": "CAMPAIGN_BATCH_OUTCOME_UNKNOWN",
    }


def test_execute_rejects_terminal_with_wrong_native_receipt(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 1)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        value = _native_apply_result(child, digest, attempt)
        receipt_path = attempt / "native" / "invocation-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["prepared_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "unknown"
    assert result["completed_batch_ids"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_unit_identity",
        "remaining_targets",
        "failed_readback",
        "wrong_readback_count",
        "unexpected_failed",
        "unexpected_unattempted",
    ],
)
def test_execute_rejects_unclosed_passed_native_terminal(
    tmp_path: Path,
    mutation: str,
) -> None:
    manifest = _campaign(tmp_path, 1)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        value = _native_apply_result(child, digest, attempt)
        result = value["batch_result"]["result"]
        if mutation == "wrong_unit_identity":
            result["completed"][0]["contract"] = "AG9999"
        elif mutation == "remaining_targets":
            result["completed"][0]["remaining_target_count"] = 1
        elif mutation == "failed_readback":
            result["completed"][0]["readback"]["catalog_physical_mds"] = "failed"
        elif mutation == "wrong_readback_count":
            result["completed"][0]["readback"]["mds_target_count"] = 1
        elif mutation == "unexpected_failed":
            result["failed"] = {"status": "failed"}
        elif mutation == "unexpected_unattempted":
            result["unattempted"] = [json.loads(child.read_text())["units"][0]]
        (attempt / "native" / "batch-result.json").write_text(
            json.dumps(result), encoding="utf-8"
        )
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "unknown"
    assert result["completed_batch_ids"] == []


@pytest.mark.parametrize("contradiction", ["completed", "failure_partial", "applied"])
def test_execute_rejects_failed_status_that_native_would_classify_partial(
    tmp_path: Path,
    contradiction: str,
) -> None:
    manifest = _campaign(tmp_path, 2)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        prepared = json.loads(child.read_text())
        completed = None
        if contradiction == "completed":
            unit = prepared["units"][0]
            completed = [
                {
                    **unit,
                    "status": "passed",
                    "remaining_target_count": 0,
                    "readback": {
                        "catalog_physical_mds": "passed",
                        "mds_target_count": unit["target_count"],
                    },
                }
            ]
        value = _native_apply_result(
            child,
            digest,
            attempt,
            status="failed",
            completed=completed,
        )
        native_result = value["batch_result"]["result"]
        if contradiction == "failure_partial":
            native_result["failed"]["status"] = "partial"
        elif contradiction == "applied":
            native_result["failed"]["result"] = {"applied": 1}
        (attempt / "native" / "batch-result.json").write_text(
            json.dumps(native_result), encoding="utf-8"
        )
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "unknown"
    assert result["completed_batch_ids"] == []


def test_execute_accepts_zero_completed_partial_current_unit_write(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 1)

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        value = _native_apply_result(
            child,
            digest,
            attempt,
            status="partial",
            completed=[],
        )
        native_result = value["batch_result"]["result"]
        native_result["failed"]["result"] = {"applied": 1}
        (attempt / "native" / "batch-result.json").write_text(
            json.dumps(native_result), encoding="utf-8"
        )
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "partial"
    assert result["failed_batch"]["native_result"]["result"]["completed"] == []


def test_campaign_started_persistence_failure_invokes_no_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    manifest = _campaign(tmp_path, 1)
    invoked: list[object] = []
    real_write = module.native._write_json_exclusive

    def fail_started(path: Path, payload: object) -> str:
        if path.name == "campaign-started.json":
            raise OSError
        return real_write(path, payload)

    monkeypatch.setattr(module.native, "_write_json_exclusive", fail_started)

    with pytest.raises(RecoveryError, match="^CAMPAIGN_STARTED_UNAVAILABLE$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-001",
            invoke_batch=lambda *_args: invoked.append(True),
        )

    assert invoked == []


@pytest.mark.parametrize("outcome", ["raises", "unreadable"])
def test_execute_exception_or_unreadable_terminal_is_unknown(
    tmp_path: Path,
    outcome: str,
) -> None:
    manifest = _campaign(tmp_path, 21)
    invoked: list[str] = []

    def invoke(_child: Path, _digest: str, attempt: Path) -> Mapping[str, Any]:
        invoked.append(attempt.name)
        if outcome == "raises":
            raise RuntimeError("private provider detail")
        return {"return_code": 1, "batch_result": None}

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "unknown"
    assert result["unknown_batch"]["batch_id"] == "batch-001"
    assert "private provider detail" not in json.dumps(result)
    assert result["unattempted_batch_ids"] == ["batch-002"]
    assert invoked == ["batch-001"]
    assert result["retries"] == 0


def test_final_summary_save_failure_cannot_report_completed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    manifest = _campaign(tmp_path, 1)
    real_write = module.native._write_json_exclusive

    def fail_result(path: Path, payload: object) -> str:
        if path.name == "campaign-result.json":
            raise OSError
        return real_write(path, payload)

    monkeypatch.setattr(module.native, "_write_json_exclusive", fail_result)

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=lambda child, digest, attempt: _native_apply_result(
            child, digest, attempt
        ),
    )

    assert result["status"] == "unknown"
    assert result["error_code"] == "CAMPAIGN_RESULT_UNAVAILABLE"


def test_execute_rejects_second_attempt_id_start(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 1)
    first = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=lambda child, digest, attempt: _native_apply_result(
            child, digest, attempt
        ),
    )
    assert first["status"] == "passed"

    with pytest.raises(RecoveryError, match="^CAMPAIGN_ATTEMPT_EXISTS$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-001",
            invoke_batch=lambda *_args: pytest.fail("duplicate attempt invoked a child"),
        )


def test_execute_rejects_concurrent_campaign_under_same_fixed_root(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 1)
    entered = threading.Event()
    release = threading.Event()
    thread_result: list[Mapping[str, Any]] = []

    def blocking(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        entered.set()
        assert release.wait(timeout=5)
        return _native_apply_result(child, digest, attempt)

    worker = threading.Thread(
        target=lambda: thread_result.append(
            execute_campaign(
                manifest,
                attempt_root=tmp_path / "attempt-001",
                invoke_batch=blocking,
            )
        )
    )
    worker.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(RecoveryError, match="^CAMPAIGN_ALREADY_RUNNING$"):
            execute_campaign(
                manifest,
                attempt_root=tmp_path / "attempt-002",
                invoke_batch=lambda *_args: pytest.fail("concurrent child invoked"),
            )
    finally:
        release.set()
        worker.join(timeout=5)

    assert thread_result[0]["status"] == "passed"


def test_execute_stops_if_bound_guard_path_is_replaced_between_batches(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 21)
    guard_path = tmp_path / (
        ".campaign-writer-" + IDENTITY["canonical_root_sha256"] + ".lock"
    )
    if not guard_path.exists():
        guard_path.touch(mode=0o600)
    invoked: list[str] = []

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        invoked.append(attempt.name)
        value = _native_apply_result(child, digest, attempt)
        if attempt.name == "batch-001":
            guard_path.unlink()
            guard_path.touch(mode=0o600)
        return value

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert invoked == ["batch-001"]
    assert result["status"] == "partial"
    assert result["failed_batch"] == {
        "batch_id": "batch-002",
        "error_code": "CAMPAIGN_GUARD_CHANGED",
    }

    with pytest.raises(RecoveryError, match="^CAMPAIGN_GUARD_CHANGED$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-002",
            invoke_batch=lambda *_args: pytest.fail("replacement guard was accepted"),
        )


def test_execute_never_recreates_missing_bound_guard(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 1)
    guard_path = tmp_path / manifest["writer_guard"]["path"]
    guard_path.unlink()

    with pytest.raises(RecoveryError, match="^CAMPAIGN_GUARD_CHANGED$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-001",
            invoke_batch=lambda *_args: pytest.fail("missing guard was recreated"),
        )

    assert not guard_path.exists()
    assert not (tmp_path / "attempt-001").exists()


def test_execute_validates_all_children_before_first_invocation(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 21)
    (tmp_path / manifest["children"][1]["path"]).write_text("{}", encoding="utf-8")
    invoked: list[object] = []

    with pytest.raises(RecoveryError, match="^CAMPAIGN_CHILD_INVALID$"):
        execute_campaign(
            manifest,
            attempt_root=tmp_path / "attempt-001",
            invoke_batch=lambda *_args: invoked.append(True),
        )

    assert invoked == []
    assert not (tmp_path / "attempt-001").exists()


def test_execute_stops_on_child_hash_drift_between_batches(tmp_path: Path) -> None:
    manifest = _campaign(tmp_path, 21)
    invoked: list[str] = []

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        invoked.append(attempt.name)
        if attempt.name == "batch-001":
            second = tmp_path / manifest["children"][1]["path"]
            second.write_text("{}", encoding="utf-8")
        return _native_apply_result(child, digest, attempt)

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert invoked == ["batch-001"]
    assert result["status"] == "partial"
    assert result["failed_batch"] == {
        "batch_id": "batch-002",
        "error_code": "CAMPAIGN_CHILD_DRIFT",
    }


def test_execute_21_units_across_two_native_batches_preserves_all_readbacks(
    tmp_path: Path,
) -> None:
    manifest = _campaign(tmp_path, 21)
    observed: list[str] = []

    def invoke(child: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        prepared = json.loads(child.read_text())
        assert hashlib.sha256(child.read_bytes()).hexdigest() == digest
        completed = []
        for unit in prepared["units"]:
            assert {target["dataset"][3] for target in unit["targets"]} == {"1d", "1w"}
            observed.append(unit["contract"])
            completed.append(
                {
                    **unit,
                    "status": "passed",
                    "remaining_target_count": 0,
                    "readback": {
                        "catalog_physical_mds": "passed",
                        "mds_target_count": 2,
                    },
                }
            )
        return _native_apply_result(child, digest, attempt, completed=completed)

    result = execute_campaign(
        manifest,
        attempt_root=tmp_path / "attempt-001",
        invoke_batch=invoke,
    )

    assert result["status"] == "passed"
    assert result["completed_batch_ids"] == ["batch-001", "batch-002"]
    assert observed == [f"AG{1000 + index}" for index in range(21)]
    assert all(
        unit["readback"]["catalog_physical_mds"] == "passed"
        for batch in result["completed_batches"]
        for unit in batch["native_result"]["result"]["completed"]
    )


def test_execute_21_units_crosses_two_real_native_batches_with_isolated_readback(
    tmp_path: Path,
) -> None:
    through = date(2025, 4, 4)
    trading_days = tuple(date(2025, 3, 31) + timedelta(days=index) for index in range(5))
    daily_ends = tuple(
        datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=7)
        for day in trading_days
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Exchange(code="DCE", name="DCE"))
    session.add(Instrument(symbol="ag", name="AG", exchange_code="DCE", is_active=True))
    contracts = [f"AG{1000 + index}" for index in range(21)]
    for contract in contracts:
        session.add(
            Contract(
                contract_code=contract,
                instrument_symbol="ag",
                exchange_code="DCE",
                listed_date=trading_days[0],
                expired_date=date(2025, 5, 1),
                provider="rqdata",
            )
        )
    session.commit()
    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    ends: dict[tuple[str, str, str, str], tuple[datetime, ...]] = {}
    for contract in contracts:
        ends[DatasetKey("contract", "ag", contract, "1d").as_tuple()] = daily_ends
        ends[DatasetKey("contract", "ag", contract, "1w").as_tuple()] = (
            daily_ends[-1],
        )
    coverage = FakeCoverage(ends)
    coverage.latest_day = through

    class Provider:
        def __init__(self) -> None:
            self.observer = None
            self.calls: list[tuple[DatasetKey, ...]] = []

        def exchange_daily_source_requests(
            self, requests: tuple[BarFetchRequest, ...]
        ) -> tuple[ExchangeDailySourceRequest, ...]:
            daily = tuple(
                request
                for request in requests
                if request.key.frequency.value == "1d"
            )
            dates = tuple(sorted({value.date() for item in daily for value in item.expected}))
            return (
                ExchangeDailySourceRequest(
                    contract=requests[0].key.series_or_contract,
                    start=dates[0],
                    end=dates[-1],
                    expected_dates=dates,
                ),
            )

        def fetch_many(
            self, requests: tuple[BarFetchRequest, ...]
        ) -> tuple[BarBatch, ...]:
            self.calls.append(tuple(request.key for request in requests))
            daily_dates = tuple(
                sorted(
                    {
                        value.date()
                        for request in requests
                        if request.key.frequency.value == "1d"
                        for value in request.expected
                    }
                )
            )
            source = ExchangeDailySourceRequest(
                contract=requests[0].key.series_or_contract,
                start=daily_dates[0],
                end=daily_dates[-1],
                expected_dates=daily_dates,
            )
            assert self.observer is not None
            self.observer.before_request(source)
            self.observer.after_response(
                source,
                tuple(
                    {
                        "date": day,
                        "open": Decimal("100"),
                        "high": Decimal("101"),
                        "low": Decimal("99"),
                        "close": Decimal("100"),
                        "volume": Decimal("1"),
                        "total_turnover": Decimal("100"),
                        "open_interest": Decimal("10"),
                        "settlement": Decimal("100"),
                        "prev_settlement": Decimal("100"),
                    }
                    for day in daily_dates
                ),
            )
            batches = []
            for request in requests:
                bars = []
                for bar_end in request.expected:
                    volume = Decimal("5") if request.key.frequency.value == "1w" else Decimal("1")
                    bars.append(
                        CanonicalBar(
                            bar_end,
                            bar_end.date(),
                            Decimal("100"),
                            Decimal("101"),
                            Decimal("99"),
                            Decimal("100"),
                            volume,
                            volume * Decimal("100"),
                            Decimal("10"),
                        )
                    )
                batches.append(BarBatch(tuple(bars)))
            return tuple(batches)

    provider = Provider()
    manager = HistoricalDataManager(
        catalog=MarketCatalog(session, canonical_root),
        store=CanonicalMonthlyStore(canonical_root),
        coverage=coverage,
        metadata=FakeMetadata(),
        provider=provider,
    )
    report_units = []
    for contract in contracts:
        plan = manager.contract_warmup(
            ContractWarmupRequest("ag", contract, through, frequency="1w")
        ).plan
        report_units.append(
            {
                "symbol": "ag",
                "contract": contract,
                "through": through.isoformat(),
                "requested_through": through.isoformat(),
                "frequency": "1w",
                "plan_sha256": plan.plan_sha256,
                "status": "PROPOSED",
                "expected_bar_count": plan.expected_bar_count,
                "target_windows": [dict(item) for item in plan.target_windows],
            }
        )
    identity = {
        **IDENTITY,
        "canonical_root_sha256": hashlib.sha256(
            str(canonical_root.resolve()).encode()
        ).hexdigest(),
    }

    def prepare_native(
        units: tuple[dict[str, Any], ...], batch_id: str, root: Path
    ) -> Mapping[str, Any]:
        child = prepare_bounded_units(
            manager=manager,
            adapter=provider,
            requests=tuple(
                ContractWarmupRequest(
                    unit["symbol"],
                    unit["contract"],
                    date.fromisoformat(unit["through"]),
                    expected_plan_sha256=unit["expected_plan_sha256"],
                    frequency="1w",
                )
                for unit in units
            ),
            expected_data_root=canonical_root,
            code_commit=identity["code_commit"],
            execution_code_sha256=identity["execution_code_sha256"],
            config_sha256=identity["config_sha256"],
        )
        path, digest = write_prepared_manifest(root, batch_id, child)
        return {
            "status": "prepared",
            "readonly": True,
            "provider_requests": 0,
            "writes": 0,
            "prepared_file": str(path),
            "prepared_sha256": digest,
            "unit_count": len(units),
        }

    campaign = prepare_campaign(
        _report(report_units),
        report_sha256="f" * 64,
        evidence_root=tmp_path,
        execution_identity=identity,
        invoke_batch=prepare_native,
    )

    def apply_native(child_path: Path, digest: str, attempt: Path) -> Mapping[str, Any]:
        child = load_prepared_manifest(child_path, digest)

        def open_unit(observer, unit):
            provider.observer = observer
            return (
                manager,
                lambda: None,
                lambda: _post_commit_readback(manager, unit),
                lambda: setattr(provider, "observer", None),
            )

        batch_result = execute_prepared_batch(
            manifest=child,
            attempt_dir=attempt,
            prepared_sha256=digest,
            current_code_commit=identity["code_commit"],
            current_execution_code_sha256=identity["execution_code_sha256"],
            current_config_sha256=identity["config_sha256"],
            current_canonical_root_sha256=identity["canonical_root_sha256"],
            open_unit=open_unit,
        )
        return {
            "return_code": 0 if batch_result["status"] == "passed" else 1,
            "batch_result": {
                "schema_version": "newow_weekly_recovery_result_v1",
                "status": batch_result["status"],
                "readonly": False,
                "attempt_dir": str(attempt),
                "result": batch_result,
            },
        }

    result = execute_campaign(
        campaign,
        attempt_root=tmp_path / "attempt-native",
        invoke_batch=apply_native,
    )

    assert result["status"] == "passed"
    assert result["completed_batch_ids"] == ["batch-001", "batch-002"]
    completed = [
        unit
        for batch in result["completed_batches"]
        for unit in batch["native_result"]["result"]["completed"]
    ]
    assert len(completed) == 21
    assert all(unit["remaining_target_count"] == 0 for unit in completed)
    assert all(unit["readback"]["catalog_physical_mds"] == "passed" for unit in completed)
    assert all(unit["readback"]["mds_target_count"] == 3 for unit in completed)
    assert len(provider.calls) == 21
    session.close()
    engine.dispose()


def test_cli_apply_calls_native_main_in_same_process_for_each_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    _campaign(tmp_path, 21)
    campaign_path = tmp_path / "campaign.prepare.json"
    campaign_sha256 = hashlib.sha256(campaign_path.read_bytes()).hexdigest()
    project_env = tmp_path / "project.env"
    project_env.write_text("fixture", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "_current_execution_identity", lambda _path: IDENTITY)

    def native_main(argv: list[str], *, stdout: io.StringIO) -> int:
        calls.append(argv)
        batch_attempt = Path(argv[argv.index("--output-root") + 1])
        child = Path(argv[argv.index("--prepared") + 1])
        digest = argv[argv.index("--expected-prepared-sha256") + 1]
        payload = _native_apply_result(child, digest, batch_attempt)["batch_result"]
        stdout.write(json.dumps(payload))
        return 0

    monkeypatch.setattr(module.native, "main", native_main)
    output = io.StringIO()

    code = main(
        [
            "apply",
            "--project-env",
            str(project_env),
            "--campaign",
            str(campaign_path),
            "--expected-campaign-sha256",
            campaign_sha256,
            "--output-root",
            str(tmp_path),
            "--attempt-id",
            "attempt-001",
            "--apply",
        ],
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert code == 0
    assert payload["status"] == "passed"
    assert [call[0] for call in calls] == ["apply", "apply"]
    assert all("--apply" in call for call in calls)
    assert all("--expected-prepared-sha256" in call for call in calls)


def test_cli_apply_rejects_current_code_or_config_drift_before_native_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import newow_weekly_recovery_campaign as module

    _campaign(tmp_path, 1)
    campaign_path = tmp_path / "campaign.prepare.json"
    campaign_sha256 = hashlib.sha256(campaign_path.read_bytes()).hexdigest()
    project_env = tmp_path / "project.env"
    project_env.write_text("fixture", encoding="utf-8")
    calls: list[object] = []
    monkeypatch.setattr(
        module,
        "_current_execution_identity",
        lambda _path: {**IDENTITY, "config_sha256": "0" * 64},
    )
    monkeypatch.setattr(module.native, "main", lambda *_args, **_kwargs: calls.append(True))
    output = io.StringIO()

    code = main(
        [
            "apply",
            "--project-env",
            str(project_env),
            "--campaign",
            str(campaign_path),
            "--expected-campaign-sha256",
            campaign_sha256,
            "--output-root",
            str(tmp_path),
            "--attempt-id",
            "attempt-001",
            "--apply",
        ],
        stdout=output,
    )

    assert code == 1
    assert json.loads(output.getvalue())["error_code"] == "EXECUTION_IDENTITY_CHANGED"
    assert calls == []
