from __future__ import annotations

from pathlib import Path

import pytest

from app.services.product_retirement_runtime_gate import (
    ProductRetirementRuntimeGateError,
    RetirementRuntimeRequest,
    append_journal,
    validate_runtime_request,
)


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
