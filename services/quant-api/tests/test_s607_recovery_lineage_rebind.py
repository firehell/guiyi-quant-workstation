from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def _source(tmp_path):
    return {
        "root": str(tmp_path / "源码"),
        "commit": "1" * 40,
        "tree": "2" * 40,
        "tracked_clean": True,
    }


def _evidence(tmp_path):
    from app.services.s607_recovery_lineage_rebind import (
        FINAL_DEPLOYMENT_PACKET_HASH,
        FINAL_REBIND_PACKET_HASH,
        FINAL_REBIND_RECEIPT_HASH,
        FINAL_SERVICE_PARENT_HASH,
        TRACKED_EVIDENCE_SHA256,
    )

    values = {}
    for name, sha256 in TRACKED_EVIDENCE_SHA256.items():
        values[name] = {
            "path": str(tmp_path / f"{name}.json"),
            "sha256": sha256,
        }
    values["final_deployment_packet"]["packet_hash"] = (
        FINAL_DEPLOYMENT_PACKET_HASH
    )
    values["final_deployment_receipt"]["approval_packet_hash"] = (
        FINAL_DEPLOYMENT_PACKET_HASH
    )
    values["final_rebind_packet"]["packet_hash"] = (
        FINAL_REBIND_PACKET_HASH
    )
    values["final_rebind_receipt"]["receipt_hash"] = (
        FINAL_REBIND_RECEIPT_HASH
    )
    values["final_service_parent"]["packet_hash"] = (
        FINAL_SERVICE_PARENT_HASH
    )
    return values


def _database_state():
    return {
        "database_revision": "20260721_0025",
        "counts": {
            "backtest_tasks": 23,
            "canonical_assets": 103381,
            "orders": 4225,
            "profile_bindings": 5138,
            "review_notes": 7,
            "signal_events": 3,
            "signal_notifications": 1,
            "signal_scan_tasks": 5,
            "strategy_signals": 5,
            "trades": 4361,
        },
        "hashes": {
            "backtest_state_sha256": (
                "fdf45ef1faf5da3c4808deb0174104150"
                "db309541e1a5361e9f404b75926df35"
            ),
            "canonical_assets_sha256": (
                "4e35672035cc483f79f339a265a44366"
                "c8ff65791532aac00647dcc2b855b28d"
            ),
            "forbidden_tables_sha256": (
                "904c57d96134345e70d26f2bf8d9c45b"
                "30262b4a5cdc210abc743d22c6d3e876"
            ),
            "profile_bindings_sha256": (
                "c5e90e7919bc77d8f39b9222c5aabe36"
                "c5d4fc5977800d571aa74d495de3d55e"
            ),
        },
        "checkpoint_count": 1,
        "checkpoint_sha256": (
            "107e209042be9762cc47f263a30ed8203"
            "82d08b217ef295c128a37b0985b853f"
        ),
    }


def _load_script(name: str):
    script = Path(__file__).resolve().parents[3] / "scripts" / name
    spec = importlib.util.spec_from_file_location(
        f"test_{script.stem}",
        script,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_and_verify_read_only_lineage_rebind_receipt(tmp_path) -> None:
    from app.services.s607_recovery_lineage_rebind import (
        ORIGINAL_RECOVERY_APPROVAL_PACKET_HASH,
        ORIGINAL_RECOVERY_RECEIPT_HASH,
        ORIGINAL_RECOVERY_RECEIPT_SHA256,
        build_recovery_lineage_rebind_receipt,
        verify_recovery_lineage_rebind_receipt,
    )

    source = _source(tmp_path)
    evidence = _evidence(tmp_path)
    database_state = _database_state()
    receipt = build_recovery_lineage_rebind_receipt(
        source=source,
        tracked_evidence=evidence,
        current_database_state=database_state,
        created_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )

    verify_recovery_lineage_rebind_receipt(
        receipt,
        current_source=source,
        current_tracked_evidence=evidence,
        current_database_state=database_state,
    )
    assert receipt["status"] == "completed"
    assert receipt["evidence_mode"] == "tracked_read_only_lineage_rebind_v1"
    assert receipt["original_recovery"] == {
        "approval_packet_hash": ORIGINAL_RECOVERY_APPROVAL_PACKET_HASH,
        "receipt_hash": ORIGINAL_RECOVERY_RECEIPT_HASH,
        "sha256": ORIGINAL_RECOVERY_RECEIPT_SHA256,
        "original_file_available": False,
    }
    assert receipt["migration_performed"] is False
    assert receipt["database_write_performed"] is False
    assert receipt["approval_r_rerun"] is False
    assert receipt["runtime_modified"] is False


@pytest.mark.parametrize(
    "drift",
    ["evidence", "database", "source", "receipt_hash", "safety"],
)
def test_lineage_rebind_receipt_fails_closed_on_any_drift(
    tmp_path,
    drift,
) -> None:
    from app.services.s607_recovery_lineage_rebind import (
        build_recovery_lineage_rebind_receipt,
        verify_recovery_lineage_rebind_receipt,
    )

    source = _source(tmp_path)
    evidence = _evidence(tmp_path)
    database_state = _database_state()
    receipt = build_recovery_lineage_rebind_receipt(
        source=source,
        tracked_evidence=evidence,
        current_database_state=database_state,
        created_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )
    current_source = deepcopy(source)
    current_evidence = deepcopy(evidence)
    current_database_state = deepcopy(database_state)
    candidate = deepcopy(receipt)
    if drift == "evidence":
        current_evidence["final_rebind_receipt"]["sha256"] = "0" * 64
    elif drift == "database":
        current_database_state["counts"]["signal_events"] += 1
    elif drift == "source":
        current_source["commit"] = "3" * 40
    elif drift == "receipt_hash":
        candidate["receipt_hash"] = "4" * 64
    else:
        candidate["database_write_performed"] = True

    with pytest.raises(RuntimeError, match="recovery_lineage_rebind_invalid"):
        verify_recovery_lineage_rebind_receipt(
            candidate,
            current_source=current_source,
            current_tracked_evidence=current_evidence,
            current_database_state=current_database_state,
        )


def test_lineage_rebind_receipt_is_create_only(tmp_path) -> None:
    from app.services.s607_recovery_lineage_rebind import (
        build_recovery_lineage_rebind_receipt,
        write_recovery_lineage_receipt_create_only,
    )

    receipt = build_recovery_lineage_rebind_receipt(
        source=_source(tmp_path),
        tracked_evidence=_evidence(tmp_path),
        current_database_state=_database_state(),
        created_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )
    path = tmp_path / "recovery_lineage_rebind_receipt.json"
    write_recovery_lineage_receipt_create_only(path, receipt)
    assert path.is_file()
    with pytest.raises(RuntimeError, match="create_only_path_exists"):
        write_recovery_lineage_receipt_create_only(path, receipt)


def test_lineage_rebind_identity_requires_exact_file_hash(tmp_path) -> None:
    from app.services.s607_recovery_lineage_rebind import (
        build_recovery_lineage_rebind_receipt,
        load_recovery_lineage_rebind_identity,
        sha256_file,
        write_recovery_lineage_receipt_create_only,
    )

    receipt = build_recovery_lineage_rebind_receipt(
        source=_source(tmp_path),
        tracked_evidence=_evidence(tmp_path),
        current_database_state=_database_state(),
        created_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )
    path = tmp_path / "recovery_lineage_rebind_receipt.json"
    write_recovery_lineage_receipt_create_only(path, receipt)
    identity = load_recovery_lineage_rebind_identity(
        path,
        expected_sha256=sha256_file(path),
    )
    assert identity["receipt_hash"] == receipt["receipt_hash"]
    assert identity["source_commit"] == receipt["source"]["commit"]
    assert (
        identity["evidence_mode"]
        == "tracked_read_only_lineage_rebind_v1"
    )
    with pytest.raises(RuntimeError, match="recovery_lineage_rebind_invalid"):
        load_recovery_lineage_rebind_identity(
            path,
            expected_sha256="0" * 64,
        )


def test_deployment_and_parent_gates_load_lineage_rebind_identity(
    tmp_path,
) -> None:
    from app.services.s607_recovery_lineage_rebind import (
        build_recovery_lineage_rebind_receipt,
        sha256_file,
        write_recovery_lineage_receipt_create_only,
    )

    receipt = build_recovery_lineage_rebind_receipt(
        source=_source(tmp_path),
        tracked_evidence=_evidence(tmp_path),
        current_database_state=_database_state(),
        created_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )
    path = tmp_path / "recovery_lineage_rebind_receipt.json"
    write_recovery_lineage_receipt_create_only(path, receipt)
    sha256 = sha256_file(path)
    deployment_gate = _load_script(
        "jm_live_signal_event_deployment_gate.py"
    )
    parent_gate = _load_script("jm_htdy_s6_08_schema_v3_gate.py")
    rebind_gate = _load_script("jm_eod_automation_gate.py")
    from app.services import htdy_s6_08_runtime_gate

    deployment_identity = (
        deployment_gate._validate_database_recovery_receipt(
            path,
            sha256,
        )
    )
    parent_identity = parent_gate._database_recovery_receipt_identity(
        path
    )
    rebind_identity = rebind_gate._database_recovery_receipt_identity(
        path
    )
    runtime_identity = (
        htdy_s6_08_runtime_gate
        ._database_recovery_receipt_identity(path)
    )
    assert deployment_identity == parent_identity
    assert deployment_identity == rebind_identity
    assert deployment_identity == runtime_identity
    assert (
        deployment_identity["evidence_mode"]
        == "tracked_read_only_lineage_rebind_v1"
    )


def test_tracked_evidence_loader_verifies_archived_success_chain() -> None:
    from app.services.s607_recovery_lineage_rebind import (
        FINAL_DEPLOYMENT_PACKET_HASH,
        FINAL_REBIND_PACKET_HASH,
        FINAL_REBIND_RECEIPT_HASH,
        collect_tracked_recovery_evidence,
    )

    root = Path(__file__).resolve().parents[3]
    evidence = collect_tracked_recovery_evidence(root)

    assert (
        evidence["final_deployment_packet"]["packet_hash"]
        == FINAL_DEPLOYMENT_PACKET_HASH
    )
    assert (
        evidence["final_rebind_packet"]["packet_hash"]
        == FINAL_REBIND_PACKET_HASH
    )
    assert (
        evidence["final_rebind_receipt"]["receipt_hash"]
        == FINAL_REBIND_RECEIPT_HASH
    )


def test_database_state_collector_is_read_only_and_rolls_back() -> None:
    from app.services.s607_recovery_lineage_rebind import (
        collect_database_state_read_only,
    )

    statements = []

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

    class Session:
        rolled_back = False
        closed = False

        def get_bind(self):
            return SimpleNamespace(
                dialect=SimpleNamespace(name="postgresql"),
                url=SimpleNamespace(drivername="postgresql+psycopg"),
            )

        def execute(self, statement):
            statements.append(str(statement))
            if "SET TRANSACTION READ ONLY" in str(statement):
                return Result(None)
            if "SHOW transaction_read_only" in str(statement):
                return Result("on")
            if "alembic_version" in str(statement):
                return Result("20260721_0025")
            raise AssertionError(statement)

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    session = Session()
    state = collect_database_state_read_only(
        "postgresql+psycopg://redacted",
        session_factory=lambda _: session,
        text_factory=lambda value: value,
        state_probe=lambda _: (
            _database_state()["counts"],
            _database_state()["hashes"],
        ),
        checkpoint_probe=lambda _: {
            "count": 1,
            "sha256": _database_state()["checkpoint_sha256"],
        },
    )

    assert state == _database_state()
    assert statements[:2] == [
        "SET TRANSACTION READ ONLY",
        "SHOW transaction_read_only",
    ]
    assert session.rolled_back is True
    assert session.closed is True


def test_lineage_rebind_cli_requires_confirmation() -> None:
    gate = _load_script("s607_recovery_lineage_rebind_gate.py")

    with pytest.raises(RuntimeError, match="confirmation_required"):
        gate.prepare_lineage_rebind(
            source_root=Path("/safe/source"),
            runtime_env=Path("/safe/project.env"),
            receipt_out=Path(
                "/safe/source/data/reports/"
                "jm_live_signal_event_s6_08/htdy_schema_v3/"
                "recovery_lineage_rebind/20260727-111111111111/"
                "recovery_lineage_rebind_receipt.json"
            ),
            confirmed=False,
        )


def test_lineage_rebind_allows_exact_s610_source_branch() -> None:
    gate = _load_script("s607_recovery_lineage_rebind_gate.py")

    assert (
        "codex/v1-htdy-s610-stability"
        in gate.ALLOWED_SOURCE_BRANCHES
    )


def test_lineage_rebind_cli_prepares_create_only_receipt(
    tmp_path,
) -> None:
    from app.services.s607_recovery_lineage_rebind import (
        load_recovery_lineage_rebind_identity,
        sha256_file,
    )

    gate = _load_script("s607_recovery_lineage_rebind_gate.py")
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = _source(source_root)
    source["root"] = str(source_root)
    receipt_out = (
        source_root
        / "data/reports/jm_live_signal_event_s6_08/htdy_schema_v3"
        / "20260727-111111111111"
        / "recovery_lineage_rebind_receipt.json"
    )
    receipt = gate.prepare_lineage_rebind(
        source_root=source_root,
        runtime_env=tmp_path / "project.env",
        receipt_out=receipt_out,
        confirmed=True,
        now=lambda: datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
        source_probe=lambda _: source,
        evidence_probe=lambda _: _evidence(tmp_path),
        environment_probe=lambda _: SimpleNamespace(
            database_url="postgresql+psycopg://redacted"
        ),
        database_probe=lambda _: _database_state(),
    )

    assert receipt_out.is_file()
    assert receipt["database_write_performed"] is False
    identity = load_recovery_lineage_rebind_identity(
        receipt_out,
        expected_sha256=sha256_file(receipt_out),
    )
    assert identity["source_commit"] == "1" * 40
    with pytest.raises(RuntimeError, match="create_only_path_exists"):
        gate.prepare_lineage_rebind(
            source_root=source_root,
            runtime_env=tmp_path / "project.env",
            receipt_out=receipt_out,
            confirmed=True,
            now=lambda: datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
            source_probe=lambda _: source,
            evidence_probe=lambda _: _evidence(tmp_path),
            environment_probe=lambda _: SimpleNamespace(
                database_url="postgresql+psycopg://redacted"
            ),
            database_probe=lambda _: _database_state(),
        )
