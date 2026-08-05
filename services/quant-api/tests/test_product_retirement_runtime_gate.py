from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.product_retirement_runtime_gate import (
    ProductRetirementExecutionService,
    ProductRetirementPrecommitError,
    ProductRetirementRuntimeGate,
    ProductRetirementRuntimeGateError,
    REQUIRED_WRITER_SERVICES,
    RetirementRuntimeRequest,
    append_journal,
    validate_runtime_request,
)


class _RuntimeOperator:
    def __init__(self) -> None:
        self.checkout_calls: list[str] = []
        self.restart_calls = 0
        self.states = {service: "stopped" for service in REQUIRED_WRITER_SERVICES}

    def stop_writer_services(self):
        return self.states

    def writer_states(self):
        return self.states

    def runtime_identity(self, _root: Path) -> str:
        return "b" * 40

    def checkout_detached(self, _root: Path, ref: str) -> str:
        self.checkout_calls.append(ref)
        return "c" * 40

    def restart_services(self):
        self.restart_calls += 1
        return self.states


class _DataOperator:
    def __init__(self, *, apply_status: str) -> None:
        self.apply_status = apply_status
        self.calls: list[tuple[object, ...]] = []

    def apply(self, _inventory, _precommit):
        self.calls.append(("apply",))
        return {"status": self.apply_status}

    def finalize(self, _inventory, _receipt):
        self.calls.append(("finalize",))
        return {"status": "applied"}

    def verify(self):
        self.calls.append(("verify",))
        return {"status": "passed"}

    def sync_direct(self, _products, frequencies):
        self.calls.append(("sync_direct", tuple(frequencies)))

    def aggregate(self, _products, frequencies):
        self.calls.append(("aggregate", tuple(frequencies)))


def test_validate_runtime_request_rejects_protected_root_inside_runtime(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = runtime_root / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text("jm\n", encoding="utf-8")

    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )

    with pytest.raises(
        ProductRetirementRuntimeGateError, match="PROTECTED_ROOT_OVERLAP"
    ):
        validate_runtime_request(request)


def test_append_journal_creates_one_append_only_record(tmp_path: Path) -> None:
    journal = append_journal(
        tmp_path,
        {"run_id": "run-001", "status": "preflight", "runtime_sha": "a" * 40},
    )

    assert journal.name == "product-retirement-run-001.jsonl"
    assert journal.read_text(encoding="utf-8") == (
        '{"run_id":"run-001","runtime_sha":"' + "a" * 40 + '","status":"preflight"}\n'
    )
    with pytest.raises(FileExistsError):
        append_journal(tmp_path, {"run_id": "run-001", "status": "duplicate"})


def test_precommit_inventory_failure_rolls_runtime_back_and_keeps_services_stopped(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text("jm\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    operator = _RuntimeOperator()
    gate = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: (_ for _ in ()).throw(
            RuntimeError("inventory failed")
        ),
    )

    result = gate.execute_precommit(request, operator=operator)

    assert result["status"] == "rejected"
    assert operator.checkout_calls == [request.release_tag, request.rollback_tag]
    assert operator.restart_calls == 0
    assert operator.writer_states() == {
        service: "stopped" for service in REQUIRED_WRITER_SERVICES
    }


def test_precommit_binds_one_run_shutdown_receipt(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        label: tmp_path / f"data/{label}" for label in ("raw", "canonical", "processed")
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text("jm\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    gate = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"},
        run_id_factory=lambda: "run-001",
    )

    result = gate.execute_precommit(request, operator=_RuntimeOperator())

    assert result["run_id"] == "run-001"
    assert result["release_tag"] == request.release_tag
    assert result["runtime_sha"] == "c" * 40
    assert len(result["shutdown_receipt_sha256"]) == 64


def test_postcommit_purge_failure_keeps_services_stopped(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text("jm\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    runtime = _RuntimeOperator()
    data = _DataOperator(apply_status="db_committed_purge_pending")
    gate = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    )

    result = gate.execute(request, runtime_operator=runtime, data_operator=data)

    assert result["status"] == "db_committed_purge_pending"
    assert data.calls == [("apply",)]
    assert runtime.restart_calls == 0


def test_database_apply_failure_rolls_runtime_back_and_keeps_services_stopped(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        label: tmp_path / f"data/{label}" for label in ("raw", "canonical", "processed")
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text("jm\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )

    class _FailingDataOperator(_DataOperator):
        def apply(self, _inventory, _precommit):
            raise ProductRetirementPrecommitError("database unavailable")

    runtime = _RuntimeOperator()
    result = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    ).execute(
        request,
        runtime_operator=runtime,
        data_operator=_FailingDataOperator(apply_status="applied"),
    )

    assert result["status"] == "rejected"
    assert result["phase"] == "precommit"
    assert runtime.checkout_calls == [request.release_tag, request.rollback_tag]
    assert runtime.restart_calls == 0


def test_resume_finalizes_then_updates_retained_periods_and_restarts(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n",
        encoding="utf-8",
    )
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )
    journal = protected_root / "pending.jsonl"
    journal.write_text(
        json.dumps(
            {
                "status": "db_committed_purge_pending",
                "inventory": {"packet": "fresh"},
                "receipt": {"status": "db_committed_purge_pending"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runtime = _RuntimeOperator()
    data = _DataOperator(apply_status="applied")
    gate = ProductRetirementRuntimeGate(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    )

    result = gate.resume(
        request,
        journal_path=journal,
        runtime_operator=runtime,
        data_operator=data,
    )

    assert result["status"] == "completed"
    assert data.calls == [
        ("finalize",),
        ("verify",),
        ("sync_direct", ("1m", "1d", "1w")),
        ("aggregate", ("5m", "15m", "30m", "60m")),
    ]
    assert runtime.restart_calls == 1


def test_execution_service_plan_declares_fixed_frequency_contract(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    protected_root = tmp_path / "audit"
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for path in (runtime_root, protected_root, *roots.values()):
        path.mkdir(parents=True, exist_ok=True)
    active_products_path = tmp_path / "active_products.txt"
    active_products_path.write_text(
        "\n".join(f"keep_{index}" for index in range(69)) + "\n",
        encoding="utf-8",
    )
    request = RetirementRuntimeRequest(
        release_tag="runtime-20260805-c9de1cdf",
        rollback_tag="runtime-rollback-20260805-9e816720",
        runtime_root=runtime_root,
        protected_root=protected_root,
        active_products_path=active_products_path,
        roots=roots,
    )

    plan = ProductRetirementExecutionService(
        inventory=lambda _request, _runtime_sha: {"packet": "fresh"}
    ).plan(request)

    assert plan["status"] == "planned"
    assert plan["active_product_count"] == 69
    assert plan["direct_frequencies"] == ["1m", "1d", "1w"]
    assert plan["derived_frequencies"] == ["5m", "15m", "30m", "60m"]
    assert plan["mapping_overlap_trading_days"] == 10
