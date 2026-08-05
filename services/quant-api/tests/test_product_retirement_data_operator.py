from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine

from app.services.product_retirement_data_operator import ProductRetirementDataOperator


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
        def sync_direct(self, products, frequencies):
            calls.append((products, frequencies))

        def aggregate(self, products, frequencies):
            calls.append((products, frequencies))

    operator = ProductRetirementDataOperator(
        connection_factory=create_engine("sqlite://").connect,
        roots=roots,
        protected_root=tmp_path / "protected",
        database_revision="test-revision",
        refresher=Refresher(),
    )

    operator.sync_direct(("jm",), ("1m", "1d", "1w"))
    operator.aggregate(("jm",), ("5m", "15m", "30m", "60m"))

    assert calls == [
        (("jm",), ("1m", "1d", "1w")),
        (("jm",), ("5m", "15m", "30m", "60m")),
    ]
