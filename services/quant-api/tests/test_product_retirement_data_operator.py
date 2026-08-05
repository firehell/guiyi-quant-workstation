from __future__ import annotations

from pathlib import Path
import json

import pytest
from sqlalchemy import create_engine

from app.data_core.product_retirement import RetirementDatabaseRow, packet_digest
from app.services import product_retirement_data_operator as operator_module
from app.services.product_retirement_data_operator import ProductRetirementDataOperator
from app.services.product_retirement_runtime_gate import ProductRetirementPrecommitError


def test_inventory_binds_runtime_sha_and_fixed_roots(tmp_path: Path) -> None:
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for root in roots.values():
        root.mkdir(parents=True)
    engine = create_engine("sqlite://")
    operator = ProductRetirementDataOperator(
        connection_factory=engine.connect,
        roots=roots,
        protected_root=tmp_path / "protected",
        database_revision="test-revision",
        now=lambda: "2026-08-05T00:00:00+00:00",
    )
    (tmp_path / "protected").mkdir()

    inventory = operator.inventory(runtime_sha="a" * 40)

    packet = inventory["packet"]
    assert packet["bound_facts"] == {
        "code_sha": "a" * 40,
        "runtime_sha": "a" * 40,
        "database_revision": "test-revision",
    }
    assert packet["scope"]["data_roots"] == {
        label: str(path.resolve()) for label, path in roots.items()
    }
    assert inventory["packet_sha256"]


def test_retained_refresh_is_delegated_only_for_frozen_period_sets(
    tmp_path: Path,
) -> None:
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for root in roots.values():
        root.mkdir(parents=True)
    (tmp_path / "protected").mkdir()
    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    class Refresher:
        def preflight(self, request):
            calls.append(((request.release_tag,), ("preflight",)))
            return {"status": "passed"}

        def sync_direct(self, products, frequencies):
            calls.append((products, frequencies))
            return {"status": "passed", "target_count": 1}

        def aggregate(self, products, frequencies):
            calls.append((products, frequencies))
            return {"status": "passed", "target_count": 1}

    operator = ProductRetirementDataOperator(
        connection_factory=create_engine("sqlite://").connect,
        roots=roots,
        protected_root=tmp_path / "protected",
        database_revision="test-revision",
        refresher=Refresher(),
    )

    from app.services.product_retirement_runtime_gate import RetirementRuntimeRequest

    active_products = tmp_path / "active.txt"
    active_products.write_text("jm\n", encoding="utf-8")
    request = RetirementRuntimeRequest(
        release_tag="runtime-test",
        rollback_tag="runtime-rollback-test",
        runtime_root=tmp_path,
        protected_root=tmp_path / "protected",
        active_products_path=active_products,
        roots=roots,
    )

    assert operator.preflight(request) == {"status": "passed"}
    assert operator.sync_direct(("jm",), ("1m", "1d", "1w"))["status"] == "passed"
    assert (
        operator.aggregate(("jm",), ("5m", "15m", "30m", "60m"))["status"] == "passed"
    )

    assert calls == [
        (("runtime-test",), ("preflight",)),
        (("jm",), ("1m", "1d", "1w")),
        (("jm",), ("5m", "15m", "30m", "60m")),
    ]


def test_inventory_externalizes_database_rows_inside_protected_root(
    tmp_path: Path, monkeypatch
) -> None:
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for root in roots.values():
        root.mkdir(parents=True)
    protected = tmp_path / "protected"
    protected.mkdir()
    row = RetirementDatabaseRow(
        table="instruments",
        primary_key=(("id", 7),),
        identity_columns=("symbol",),
        identity_digest="a" * 64,
        reasons=("product:jr",),
    )
    monkeypatch.setattr(operator_module, "inventory_files", lambda _roots: ((), ()))
    monkeypatch.setattr(
        operator_module, "inventory_database", lambda _connection: ((row,), ())
    )
    operator = ProductRetirementDataOperator(
        connection_factory=create_engine("sqlite://").connect,
        roots=roots,
        protected_root=protected,
        database_revision="test-revision",
        now=lambda: "2026-08-05T00:00:00+00:00",
    )

    inventory = operator.inventory(runtime_sha="a" * 40)

    packet = inventory["packet"]
    inventory_path = Path(inventory["inventory_path"])
    assert packet["database_rows"] == []
    assert packet["database_row_shards"][0]["row_count"] == 1
    assert inventory_path.parent == protected
    assert packet_digest(
        json.loads(inventory_path.read_text(encoding="utf-8"))
    ) == packet_digest(packet)
    shard = protected / packet["database_row_shards"][0]["relative_path"]
    assert shard.is_file()


def test_apply_wraps_any_before_commit_failure_for_runtime_rollback(
    tmp_path: Path,
) -> None:
    roots = {
        "raw": tmp_path / "data/raw",
        "canonical": tmp_path / "data/canonical",
        "processed": tmp_path / "data/processed",
    }
    for root in roots.values():
        root.mkdir(parents=True)
    protected = tmp_path / "protected"
    protected.mkdir()
    operator = ProductRetirementDataOperator(
        connection_factory=create_engine("sqlite://").connect,
        roots=roots,
        protected_root=protected,
        database_revision="test-revision",
    )
    packet: dict[str, object] = {}

    with pytest.raises(ProductRetirementPrecommitError):
        operator.apply(
            {
                "packet": packet,
                "packet_sha256": packet_digest(packet),
                "packet_root": str(protected),
            },
            {
                "runtime_sha": "a" * 40,
                "run_id": "run-001",
                "release_tag": "runtime-test",
                "shutdown_receipt_sha256": "b" * 64,
            },
        )
