from types import SimpleNamespace
from copy import deepcopy
from hashlib import sha256
import pytest
from app.reference_trading import manifest_storage as storage
from app.reference_trading.models import ReferenceBatch
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401
from app.reference_trading.contracts import manifest_sha256


def case():
    full = {
        "reader": "subing_mds_historical_v1",
        "query_since": "2023-01-01",
        "input_fingerprints": [
            sha256(str(i).encode()).hexdigest() for i in range(1500)
        ],
    }
    anchor = SimpleNamespace(
        batch_id="anchor",
        stream_id="s",
        revision_id="r",
        seq=1,
        kind="seed_seal",
        outcome="committed",
        dependency_manifest=full,
    )

    class Session:
        def get(self, model, key):
            assert model is ReferenceBatch
            return anchor if key == "anchor" else None

    return Session(), anchor, full


def test_same_digest_stored_once_and_new_digest_gets_new_anchor():
    session, anchor, full = case()
    raw = storage.store_manifest(session, anchor, full, manifest_sha256(full))
    assert raw["query_since"] == "2023-01-01" and "input_fingerprints" not in raw
    assert len(str(raw)) < 1000
    child = SimpleNamespace(
        batch_id="next",
        stream_id="s",
        revision_id="r",
        seq=2,
        kind="calculation",
        outcome="committed",
        dependency_manifest=raw,
    )
    assert storage.resolve_manifest(session, child) == full
    assert storage.store_manifest(session, child, full, manifest_sha256(full)) == raw
    advanced = {**full, "input_fingerprints": full["input_fingerprints"] + ["f" * 64]}
    assert (
        storage.store_manifest(session, child, advanced, manifest_sha256(advanced))
        == advanced
    )


@pytest.mark.parametrize(
    "corrupt", ["head", "hash", "stream", "revision", "seq", "chain", "missing"]
)
def test_invalid_anchor_never_falls_back(corrupt):
    session, anchor, full = case()
    raw = deepcopy(storage.store_manifest(session, anchor, full, manifest_sha256(full)))
    child = SimpleNamespace(
        stream_id="s",
        revision_id="r",
        seq=2,
        kind="calculation",
        outcome="committed",
        dependency_manifest=raw,
    )
    if corrupt == "head":
        raw["query_since"] = "2024-01-01"
    if corrupt == "hash":
        raw[storage.REF]["sha256"] = "0" * 64
    if corrupt == "stream":
        anchor.stream_id = "other"
    if corrupt == "revision":
        anchor.revision_id = "other"
    if corrupt == "seq":
        anchor.seq = 3
    if corrupt == "chain":
        anchor.dependency_manifest = raw
    if corrupt == "missing":
        raw[storage.REF]["batch_id"] = "missing"
    with pytest.raises(ValueError):
        storage.resolve_manifest(session, child)


@pytest.mark.parametrize(
    "backend",
    ["sqlite", pytest.param("postgresql", marks=pytest.mark.isolated_postgresql)],
)
def test_real_historical_pipeline_reads_compact_subing_and_semantic_newow_manifests(
    tmp_path, monkeypatch, request, backend
):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from tests.reference_trading.test_historical_integration import (
        _verify_historical_pipeline,
    )
    from app.reference_trading.models import ReferenceStream

    monkeypatch.setattr(storage, "MIN_BYTES", 1)
    engine = (
        request.getfixturevalue("reference_postgresql")
        if backend == "postgresql"
        else create_engine("sqlite+pysqlite:///:memory:")
    )
    from app.db.base import Base

    Base.metadata.create_all(engine)
    _verify_historical_pipeline(engine, tmp_path, monkeypatch)
    with Session(engine) as session:
        rows = session.execute(
            select(ReferenceBatch, ReferenceStream.strategy_code)
            .join(
                ReferenceStream, ReferenceStream.stream_id == ReferenceBatch.stream_id
            )
            .where(ReferenceBatch.kind == "calculation")
        ).all()
        compact = [
            row for row, strategy in rows if storage.REF in row.dependency_manifest
        ]
        assert compact
        assert all(
            (strategy.replace("-", "_") == "subing_reference"
             or storage.resolve_manifest(session, row).get("reader") == "newow_product_reader_prefix_v4")
            for row, strategy in rows
            if storage.REF in row.dependency_manifest
        )
        assert any(strategy.startswith("newow_") and storage.REF in row.dependency_manifest
                   for row, strategy in rows)
        for row in compact:
            assert storage.resolve_manifest(session, row)["input_fingerprints"]
