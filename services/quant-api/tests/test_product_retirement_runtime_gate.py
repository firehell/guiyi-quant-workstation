from __future__ import annotations

from pathlib import Path

import pytest

from app.services.product_retirement_runtime_gate import (
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

    with pytest.raises(ProductRetirementRuntimeGateError, match="PROTECTED_ROOT_OVERLAP"):
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
        inventory=lambda _request, _runtime_sha: (_ for _ in ()).throw(RuntimeError("inventory failed")),
    )

    result = gate.execute_precommit(request, operator=operator)

    assert result["status"] == "rejected"
    assert operator.checkout_calls == [request.release_tag, request.rollback_tag]
    assert operator.restart_calls == 0
    assert operator.writer_states() == {
        service: "stopped" for service in REQUIRED_WRITER_SERVICES
    }
