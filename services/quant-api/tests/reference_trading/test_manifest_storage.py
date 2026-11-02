from types import SimpleNamespace
from copy import deepcopy
from hashlib import sha256
import pytest
from app.reference_trading import manifest_storage as storage
from app.reference_trading.models import ReferenceBatch
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401
from tests.reference_trading.test_repository_postgresql import reference_postgresql  # noqa: F401
from app.reference_trading.contracts import manifest_sha256, prove_dependency_append


def _pg_anchor(engine, *, packed=False, fusion=False, leaf_count=1500,
               manifest_override=None):
    from sqlalchemy import select
    from sqlalchemy.orm import Session, sessionmaker
    from guiyi_quant.newow.product_adapters import seed_replay_state
    from guiyi_quant.reference_trading import ReferenceState
    from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
    from app.reference_trading.contracts import SeedChunk
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.packed_fingerprints import pack_fingerprints
    from tests.reference_trading.test_repository import _stream

    factory = sessionmaker(engine, expire_on_commit=False)
    repo = ReferenceRepository(factory)
    stream = _stream()
    row = repo.ensure_stream(stream)
    leaves = [sha256(str(i).encode()).hexdigest() for i in range(leaf_count)]
    full = {
        "reader": "newow_product_reader_prefix_v5" if packed else "newow_product_reader_prefix_v4",
        "query_since": "2026-09-01",
        "input_fingerprints": pack_fingerprints(leaves) if packed else leaves,
    }
    if not packed:
        full['calendar_session_effective_fingerprints'] = list(reversed(leaves))
    if packed:
        full['numeric_one'] = 1
    if fusion:
        full['calendar_session_effective_fingerprints'] = pack_fingerprints(reversed(leaves))
        full['source_input_fingerprints'] = pack_fingerprints(leaves)
    if manifest_override is not None:
        full = manifest_override
    digest = manifest_sha256(full)
    revision = repo.create_revision(stream.stream_id, row.row_version, digest)
    checkpoint = AdapterCheckpoint(seed_replay_state(), stream=stream,
                                   reference_state=ReferenceState.flat(stream))
    root = sha256(b"seed").hexdigest()
    repo.stage_seed_chunk(revision, SeedChunk("seed", 0, 1, root, "seed"))
    repo.seal_seed(revision, full, checkpoint, "newow_product_replay_v1")
    with Session(engine) as session:
        anchor_id = session.scalar(select(ReferenceBatch.batch_id).where(
            ReferenceBatch.stream_id == stream.stream_id,
            ReferenceBatch.revision_id == revision,
            ReferenceBatch.kind == "seed_seal",
        ))
    return full, digest, stream.stream_id, revision, anchor_id


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize('leaf_count', (1024, 1025, 32769))
def test_pg_legacy_transport_is_bounded_blocks_with_exact_digest(
    reference_postgresql, leaf_count,  # noqa: F811
):
    from sqlalchemy.orm import Session, defer

    full, digest, _, _, anchor_id = _pg_anchor(reference_postgresql, leaf_count=leaf_count)
    with Session(reference_postgresql) as session:
        rows = session.execute(storage._pg_packed_rows(anchor_id, {
            'input_fingerprints': leaf_count,
            'calendar_session_effective_fingerprints': leaf_count,
        }, legacy_arrays=True)).all()
        blocks = [row for row in rows if row.row_kind == 'legacy_block']
        assert len(rows) == 3 + 2 * ((leaf_count + storage.BLOCK_SIZE - 1) // storage.BLOCK_SIZE)
        assert all(0 < len(row.metadata) <= storage.BLOCK_SIZE for row in blocks)
        anchor = session.get(ReferenceBatch, anchor_id,
                             options=[defer(ReferenceBatch.dependency_manifest)])
        restored = storage.resolve_manifest(session, anchor)
        assert restored == full
        assert manifest_sha256(restored) == digest


@pytest.mark.parametrize('tamper', (
    None, 'missing', 'duplicate', 'short', 'long', 'bool_count', 'bad_sha', 'bad_ordinal',
))
def test_legacy_blocks_require_complete_unique_exact_valid_leaves(tamper):
    head = {'reader': 'newow_product_reader_prefix_v4'}
    keys = {'input_fingerprints'}
    counts = {key: 257 if key in keys else -1 for key in storage.LARGE_KEYS}
    presence = {key: key in keys for key in storage.LARGE_KEYS}
    probe = ('batch', 'stream', 'revision', 'seed_seal', 'committed', 1,
             head, 'digest', None, presence, 'array', counts)
    header = SimpleNamespace(row_kind='header', batch_id='batch', stream_id='stream',
        revision_id='revision', batch_kind='seed_seal', outcome='committed', seq=1,
        server_hash='digest', metadata=head, presence=presence)
    vector = SimpleNamespace(row_kind='vector', vector_key='input_fingerprints',
        value_type='array', block_count=257)
    def block(ordinal, values, count):
        return SimpleNamespace(row_kind='legacy_block', vector_key='input_fingerprints',
            ordinal=ordinal, metadata=values, block_count=count)
    first = block(1, ['a' * 64] * 256, 256)
    last = block(2, ['b' * 64], 1)
    blocks = [last, first]  # SQL group result order is deliberately irrelevant.
    if tamper == 'missing': blocks.pop()
    elif tamper == 'duplicate': blocks.append(first)
    elif tamper == 'short': first.metadata.pop()
    elif tamper == 'long': last.metadata.append('c' * 64)
    elif tamper == 'bool_count': last.block_count = True
    elif tamper == 'bad_sha': last.metadata[0] = 'A' * 64
    elif tamper == 'bad_ordinal': last.ordinal = True
    class Result:
        closed = False
        def __iter__(self): return iter([header, vector, *blocks])
        def close(self): self.closed = True
    result = Result()
    session = SimpleNamespace(execute=lambda _: result)
    if tamper is None:
        assert storage._pg_construct_legacy_arrays(session, 'batch', probe, keys) == {
            **head, 'input_fingerprints': ['a' * 64] * 256 + ['b' * 64],
        }
    else:
        with pytest.raises(storage.ManifestStorageError):
            storage._pg_construct_legacy_arrays(session, 'batch', probe, keys)
    assert result.closed


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize('manifest', (
    {'htdy60m_first_seen_reference_v1': {'product': 'JM'},
     'scope_plan_hash': 'a' * 64},
    {'subing_activation_v2': {'product': 'JM'}, 'plan_hash': 'b' * 64},
))
def test_pg_opaque_activation_manifest_read_state_uses_bounded_head(
    reference_postgresql, monkeypatch, manifest,  # noqa: F811
):
    from sqlalchemy.orm import sessionmaker
    from app.reference_trading.repository import ReferenceRepository

    full, digest, stream_id, revision_id, _ = _pg_anchor(
        reference_postgresql, manifest_override=manifest,
    )
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('opaque manifest fetched full JSON'))
    state = ReferenceRepository(sessionmaker(reference_postgresql)).read_state(
        stream_id, revision_id,
    )
    assert state.dependency_manifest == full
    assert state.dependency_digest == digest


@pytest.mark.isolated_postgresql
def test_pg_fusion_v3_with_legacy_source_array_fails_without_full_fallback(
    reference_postgresql, monkeypatch,  # noqa: F811
):
    from sqlalchemy.orm import Session, defer

    manifest = {
        'reader': 'newow_fusion_saved_sources_v3',
        'source_reader': 'newow_product_reader_prefix_v4',
        'input_fingerprints': ['a' * 64],
    }
    _, _, _, _, anchor_id = _pg_anchor(
        reference_postgresql, manifest_override=manifest,
    )
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('fusion v3 fetched full JSON'))
    with Session(reference_postgresql) as session:
        anchor = session.get(ReferenceBatch, anchor_id,
                             options=[defer(ReferenceBatch.dependency_manifest)])
        with pytest.raises(storage.ManifestStorageError):
            storage.resolve_manifest(session, anchor)


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize('fusion', (False, True))
def test_pg_legacy_newow_arrays_reconstruct_exact_list_and_digest_bounded(
    reference_postgresql, monkeypatch, fusion,  # noqa: F811
):
    from sqlalchemy.orm import Session, defer

    leaves = [sha256(str(index).encode()).hexdigest() for index in range(1500)]
    if fusion:
        manifest = {
            'reader': 'newow_fusion_saved_sources_v2',
            'source_reader': 'newow_product_reader_prefix_v4',
            'input_fingerprints': leaves,
            'calendar_session_effective_fingerprints': list(reversed(leaves)),
            'source_input_fingerprints': list(leaves),
        }
        full, digest, _, _, anchor_id = _pg_anchor(
            reference_postgresql, manifest_override=manifest,
        )
    else:
        full, digest, _, _, anchor_id = _pg_anchor(reference_postgresql)
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('legacy Newow fetched full JSON'))
    with Session(reference_postgresql) as session:
        anchor = session.get(ReferenceBatch, anchor_id,
                             options=[defer(ReferenceBatch.dependency_manifest)])
        restored = storage.resolve_manifest(session, anchor)
    assert restored == full
    assert manifest_sha256(restored) == digest
    assert isinstance(restored['input_fingerprints'], list)
    assert restored['input_fingerprints'][0] == leaves[0]
    assert restored['input_fingerprints'][-1] == leaves[-1]
    assert len(restored['input_fingerprints']) == len(leaves)


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize('tamper', ('bool_leaf', 'upper_leaf', 'oversized_leaf',
                                   'extra_vector', 'missing_vector', 'budget'))
def test_pg_legacy_newow_array_corruption_never_fetches_full_json(
    reference_postgresql, monkeypatch, tamper,  # noqa: F811
):
    from sqlalchemy import update
    from sqlalchemy.orm import Session, defer

    full, _, _, _, anchor_id = _pg_anchor(reference_postgresql)
    changed = deepcopy(full)
    if tamper == 'bool_leaf':
        changed['input_fingerprints'][0] = True
    elif tamper == 'upper_leaf':
        changed['input_fingerprints'][0] = 'A' * 64
    elif tamper == 'oversized_leaf':
        changed['input_fingerprints'][0] = 'a' * 65
    elif tamper == 'extra_vector':
        changed['source_input_fingerprints'] = ['a' * 64]
    elif tamper == 'missing_vector':
        del changed['calendar_session_effective_fingerprints']
    else:
        monkeypatch.setattr(storage, 'MAX_LEGACY_TOTAL_LEAVES', 100)
    if tamper != 'budget':
        with reference_postgresql.begin() as connection:
            connection.execute(update(ReferenceBatch).where(
                ReferenceBatch.batch_id == anchor_id,
            ).values(dependency_manifest=changed))
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('corrupt legacy Newow fetched full JSON'))
    with Session(reference_postgresql) as session:
        anchor = session.get(ReferenceBatch, anchor_id,
                             options=[defer(ReferenceBatch.dependency_manifest)])
        with pytest.raises(storage.ManifestStorageError):
            storage.resolve_manifest(session, anchor)


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


def test_v5_delta_roundtrip_latest_anchor_and_chain_limit():
    from app.reference_trading.packed_fingerprints import pack_fingerprints

    rows = {}

    class Session:
        def get(self, model, key):
            assert model is ReferenceBatch
            return rows.get(key)

    session = Session()
    leaves = [sha256(str(index).encode()).hexdigest() for index in range(1500)]
    full = {'reader': 'newow_product_reader_prefix_v5',
            'input_fingerprints': pack_fingerprints(leaves), 'through': '2026-09-01'}
    prior = SimpleNamespace(batch_id='anchor', stream_id='s', revision_id='r',
                            seq=1, kind='seed_seal', outcome='committed',
                            dependency_manifest=full)
    rows[prior.batch_id] = prior
    for index in range(1, storage.MAX_DELTA_DEPTH + 3):
        leaves.append(sha256(f'new-{index}'.encode()).hexdigest())
        next_full = {**full, 'input_fingerprints': pack_fingerprints(leaves)}
        advance = prove_dependency_append(
            full, next_full, appended_ranges=(f'new-{index}',),
        )
        raw = storage.store_manifest(
            session, prior, next_full, manifest_sha256(next_full),
            dependency_advance=advance,
        )
        if index != storage.MAX_DELTA_DEPTH + 1:
            assert storage.DELTA_REF in raw
            assert raw[storage.DELTA_REF]['depth'] == (
                index if index <= storage.MAX_DELTA_DEPTH else 1
            )
        else:
            assert raw == next_full
        child = SimpleNamespace(batch_id=f'child-{index}', stream_id='s',
                                revision_id='r', seq=prior.seq + 1,
                                kind='calculation', outcome='committed',
                                dependency_manifest=raw)
        rows[child.batch_id] = child
        assert storage.resolve_manifest(session, child) == next_full
        if index == 1:
            same = storage.store_manifest(
                session, child, next_full, manifest_sha256(next_full),
            )
            assert same[storage.REF]['batch_id'] == child.batch_id
            reference = SimpleNamespace(batch_id='same', stream_id='s',
                                        revision_id='r', seq=child.seq + 1,
                                        kind='calculation', outcome='committed',
                                        dependency_manifest=same)
            rows[reference.batch_id] = reference
            assert storage.resolve_manifest(session, reference) == next_full
            prior = reference
        else:
            prior = child
        full = next_full


def test_v5_delta_rejects_corrupt_parent_vector_and_metadata(monkeypatch):
    from app.reference_trading.packed_fingerprints import pack_fingerprints

    leaves = [sha256(str(index).encode()).hexdigest() for index in range(1500)]
    full = {'reader': 'newow_product_reader_prefix_v5',
            'input_fingerprints': pack_fingerprints(leaves)}
    anchor = SimpleNamespace(batch_id='anchor', stream_id='s', revision_id='r',
                             seq=1, kind='seed_seal', outcome='committed',
                             dependency_manifest=full)

    class Session:
        def get(self, model, key):
            assert model is ReferenceBatch
            return anchor if key == 'anchor' else None

    session = Session()
    newer = {**full, 'input_fingerprints': pack_fingerprints((*leaves, 'a' * 64))}
    proof = prove_dependency_append(full, newer, appended_ranges=('new',))
    raw = storage.store_manifest(session, anchor, newer, manifest_sha256(newer),
                                 dependency_advance=proof)
    assert storage.DELTA_REF in raw
    for field in ('parent_sha256', 'old_count', 'blocks'):
        changed = deepcopy(raw)
        ref = changed[storage.DELTA_REF]
        if field == 'parent_sha256':
            ref[field] = '0' * 64
        elif field == 'old_count':
            ref['vectors']['input_fingerprints'][field] -= 1
        else:
            ref['vectors']['input_fingerprints'][field][0] = 'A'
        child = SimpleNamespace(batch_id='child', stream_id='s', revision_id='r',
                                seq=2, kind='calculation', outcome='committed',
                                dependency_manifest=changed)
        with pytest.raises(storage.ManifestStorageError):
            storage.resolve_manifest(session, child)
    assert storage.store_manifest(session, anchor, newer,
                                  manifest_sha256(newer)) == newer
    monkeypatch.setattr(storage, 'MAX_DELTA_BYTES', 100)
    assert storage.store_manifest(session, anchor, newer,
                                  manifest_sha256(newer),
                                  dependency_advance=proof) == newer


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
             or storage.resolve_manifest(session, row).get("reader") == "newow_product_reader_prefix_v5")
            for row, strategy in rows
            if storage.REF in row.dependency_manifest
        )
        assert any(strategy.startswith("newow_") and storage.REF in row.dependency_manifest
                   for row, strategy in rows)
        for row in compact:
            assert storage.resolve_manifest(session, row)["input_fingerprints"]


@pytest.mark.isolated_postgresql
def test_scoped_pg_anchor_hit_never_fetches_full_json_again(reference_postgresql, monkeypatch):  # noqa: F811
    from datetime import UTC, datetime
    from sqlalchemy.orm import Session, defer

    full, digest, stream_id, revision_id, anchor_id = _pg_anchor(reference_postgresql)
    counted = storage.fingerprint_count
    count_calls = []

    def count_once(value):
        count_calls.append(1)
        return counted(value)

    monkeypatch.setattr(storage, "fingerprint_count", count_once)
    with storage.verified_manifest_scope(full, digest):
        with Session(reference_postgresql) as session, session.begin():
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, anchor) is full
            raw = storage.store_manifest(session, anchor, full, digest)
            assert raw[storage.REF]["batch_id"] == anchor_id
            assert len(count_calls) == 2
            for seq in range(2, 10):
                session.add(ReferenceBatch(
                    batch_id=f"manifest-child-{seq}", stream_id=stream_id,
                    revision_id=revision_id, batch_key=f"manifest-child-{seq}",
                    payload_hash="0" * 64, kind="calculation", outcome="committed",
                    seq=seq, expected_seq=seq - 1, dependency_manifest=raw,
                    source_evidence={}, projected_action_pks=[], diagnostics=[],
                    processed_at=datetime.now(UTC),
                ))
        with monkeypatch.context() as patch:
            patch.setattr(storage, "_pg_full", lambda *_args: pytest.fail("full JSON fetched on hit"))
            with Session(reference_postgresql) as session:
                anchor = session.get(ReferenceBatch, anchor_id,
                                     options=[defer(ReferenceBatch.dependency_manifest)])
                assert storage.resolve_manifest(session, anchor) is full
                assert "dependency_manifest" not in anchor.__dict__
                for seq in range(2, 10):
                    child_id = f"manifest-child-{seq}"
                    child = session.get(ReferenceBatch, child_id,
                                        options=[defer(ReferenceBatch.dependency_manifest)])
                    assert storage.resolve_manifest(session, child) is full
                    assert storage._scope.get().resolved[1] == child_id
                    assert storage._scope.get().anchor_key[1] == anchor_id


@pytest.mark.isolated_postgresql
def test_scoped_pg_manifest_mutation_fails_before_reusing_cached_count(
    reference_postgresql,  # noqa: F811
):
    from sqlalchemy.orm import Session, defer

    full, digest, _, _, anchor_id = _pg_anchor(reference_postgresql)
    with storage.verified_manifest_scope(full, digest):
        full["query_since"] = "2025-01-01"
        with Session(reference_postgresql) as session:
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            with pytest.raises(storage.ManifestStorageError):
                storage.store_manifest(session, anchor, full, digest)
        assert storage._scope.get().anchor_key is None
        assert storage._scope.get().resolved is None


@pytest.mark.isolated_postgresql
def test_pg_first_packed_anchor_verifies_multiple_blocks_without_full_json(
    reference_postgresql, monkeypatch,  # noqa: F811
):
    from sqlalchemy.orm import Session, defer

    full, digest, _, _, anchor_id = _pg_anchor(reference_postgresql, packed=True, fusion=True)
    assert len(full['input_fingerprints']['blocks']) > 1
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('full JSON fetched for packed anchor'))
    with storage.verified_manifest_scope(full, digest):
        with Session(reference_postgresql) as session:
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, anchor) is full
            assert 'dependency_manifest' not in anchor.__dict__


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize('tamper', (
    'block', 'count', 'type', 'marker', 'missing', 'oversized_block',
    'unicode_block', 'oversized_metadata', 'extra_vector', 'oversized_head',
    'float_count', 'float_block_size', 'bool_head', 'v5_array',
))
def test_pg_first_packed_anchor_rejects_corrupt_blocks_and_metadata(
    reference_postgresql, monkeypatch, tamper,  # noqa: F811
):
    from datetime import UTC, datetime
    from sqlalchemy import update
    from sqlalchemy.orm import Session, defer

    full, digest, stream_id, revision_id, anchor_id = _pg_anchor(
        reference_postgresql, packed=True,
    )
    child_id = 'packed-reference-child'
    with Session(reference_postgresql) as session, session.begin():
        anchor = session.get(ReferenceBatch, anchor_id)
        raw = storage.store_manifest(session, anchor, full, digest)
        session.add(ReferenceBatch(
            batch_id=child_id, stream_id=stream_id, revision_id=revision_id,
            batch_key=child_id, payload_hash='0' * 64,
            kind='calculation', outcome='committed', seq=2, expected_seq=1,
            dependency_manifest=raw, source_evidence={}, projected_action_pks=[],
            diagnostics=[], processed_at=datetime.now(UTC),
        ))
    changed = deepcopy(full)
    vector = changed['input_fingerprints']
    blocks = vector['blocks']
    if tamper == 'block':
        blocks[0] = ('A' if blocks[0][0] != 'A' else 'B') + blocks[0][1:]
    elif tamper == 'count':
        vector['count'] += 1
    elif tamper == 'type':
        blocks[0] = 7
    elif tamper == 'marker':
        vector['encoding'] = 'unknown-marker'
    elif tamper == 'missing':
        blocks.pop()
    elif tamper == 'oversized_block':
        blocks[0] = 'x' * (storage.MAX_BLOCK_CHARS + 1)
    elif tamper == 'unicode_block':
        blocks[0] = '你' * storage.MAX_BLOCK_CHARS
    elif tamper == 'oversized_metadata':
        vector['unknown'] = 'x' * (storage.MAX_VECTOR_META_BYTES + 1)
    elif tamper == 'extra_vector':
        changed['source_input_fingerprints'] = deepcopy(vector)
    elif tamper == 'float_count':
        vector['count'] = float(vector['count'])
    elif tamper == 'float_block_size':
        vector['block_size'] = float(vector['block_size'])
    elif tamper == 'bool_head':
        changed['numeric_one'] = True
    elif tamper == 'v5_array':
        from app.reference_trading.packed_fingerprints import PackedFingerprints
        changed['input_fingerprints'] = list(PackedFingerprints(full['input_fingerprints']))
    else:
        changed['unknown_head'] = 'x' * (storage.MAX_HEAD_BYTES + 1)
    with reference_postgresql.begin() as connection:
        connection.execute(update(ReferenceBatch).where(
            ReferenceBatch.batch_id == anchor_id,
        ).values(dependency_manifest=changed))
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('corrupt packed anchor fetched full JSON'))
    with storage.verified_manifest_scope(full, digest):
        with Session(reference_postgresql) as session:
            child = session.get(ReferenceBatch, child_id,
                                options=[defer(ReferenceBatch.dependency_manifest)])
            with pytest.raises(storage.ManifestStorageError):
                storage.resolve_manifest(session, child)
    with Session(reference_postgresql) as session:
        child = session.get(ReferenceBatch, child_id,
                            options=[defer(ReferenceBatch.dependency_manifest)])
        with pytest.raises(storage.ManifestStorageError):
            storage.resolve_manifest(session, child)


@pytest.mark.isolated_postgresql
def test_pg_v5_bool_count_cannot_equal_integer_one_or_use_full_fallback(
    reference_postgresql, monkeypatch,  # noqa: F811
):
    from sqlalchemy import update
    from sqlalchemy.orm import Session, defer

    full, digest, _, _, anchor_id = _pg_anchor(
        reference_postgresql, packed=True, leaf_count=1,
    )
    changed = deepcopy(full)
    changed['input_fingerprints']['count'] = True
    with reference_postgresql.begin() as connection:
        connection.execute(update(ReferenceBatch).where(
            ReferenceBatch.batch_id == anchor_id,
        ).values(dependency_manifest=changed))
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('v5 bool count fetched full JSON'))
    with storage.verified_manifest_scope(full, digest):
        with Session(reference_postgresql) as session:
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            with pytest.raises(storage.ManifestStorageError):
                storage.resolve_manifest(session, anchor)
    with Session(reference_postgresql) as session:
        anchor = session.get(ReferenceBatch, anchor_id,
                             options=[defer(ReferenceBatch.dependency_manifest)])
        with pytest.raises(storage.ManifestStorageError):
            storage.resolve_manifest(session, anchor)


@pytest.mark.isolated_postgresql
def test_pg_unscoped_packed_anchor_and_read_state_reconstruct_without_full_json(
    reference_postgresql, monkeypatch,  # noqa: F811
):
    from sqlalchemy.orm import Session, defer, sessionmaker
    from app.reference_trading.repository import ReferenceRepository

    full, digest, stream_id, revision_id, anchor_id = _pg_anchor(
        reference_postgresql, packed=True, fusion=True,
    )
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('unscoped v5 fetched full JSON'))
    with Session(reference_postgresql) as session:
        anchor = session.get(ReferenceBatch, anchor_id,
                             options=[defer(ReferenceBatch.dependency_manifest)])
        assert storage.resolve_manifest(session, anchor) == full
        assert 'dependency_manifest' not in anchor.__dict__
    state = ReferenceRepository(sessionmaker(reference_postgresql)).read_state(
        stream_id, revision_id,
    )
    assert state.dependency_manifest == full
    assert state.dependency_digest == digest


@pytest.mark.isolated_postgresql
def test_pg_unscoped_packed_reference_and_append_prior_reconstruct_bounded(
    reference_postgresql, monkeypatch,  # noqa: F811
):
    from datetime import UTC, datetime
    from sqlalchemy.orm import Session, defer
    from app.reference_trading.packed_fingerprints import PackedFingerprints, pack_fingerprints

    full, digest, stream_id, revision_id, anchor_id = _pg_anchor(
        reference_postgresql, packed=True,
    )
    child_id = 'bounded-reference-child'
    with Session(reference_postgresql) as session, session.begin():
        anchor = session.get(ReferenceBatch, anchor_id)
        raw = storage.store_manifest(session, anchor, full, digest)
        session.add(ReferenceBatch(
            batch_id=child_id, stream_id=stream_id, revision_id=revision_id,
            batch_key=child_id, payload_hash='0' * 64,
            kind='calculation', outcome='committed', seq=2, expected_seq=1,
            dependency_manifest=raw, source_evidence={}, projected_action_pks=[],
            diagnostics=[], processed_at=datetime.now(UTC),
        ))
    newer = {**full, 'query_since': '2026-09-02',
             'input_fingerprints': pack_fingerprints((
                 *PackedFingerprints(full['input_fingerprints']), 'a' * 64,
             ))}
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('v5 reference/prior fetched full JSON'))
    with Session(reference_postgresql) as session:
        child = session.get(ReferenceBatch, child_id,
                            options=[defer(ReferenceBatch.dependency_manifest)])
        assert storage.resolve_manifest(session, child) == full
    with storage.verified_manifest_scope(newer, manifest_sha256(newer)):
        with Session(reference_postgresql) as session:
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, anchor) == full
            child = session.get(ReferenceBatch, child_id,
                                options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, child) == full


@pytest.mark.isolated_postgresql
def test_pg_v5_delta_and_v1_child_reconstruct_without_full_json(
    reference_postgresql, monkeypatch,  # noqa: F811
):
    from datetime import UTC, datetime
    from sqlalchemy.orm import Session, defer
    from app.reference_trading.packed_fingerprints import PackedFingerprints, pack_fingerprints

    full, _, stream_id, revision_id, anchor_id = _pg_anchor(
        reference_postgresql, packed=True,
    )
    new = {**full, 'input_fingerprints': pack_fingerprints((
        *PackedFingerprints(full['input_fingerprints']), 'a' * 64,
    ))}
    proof = prove_dependency_append(full, new, appended_ranges=('new',))
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('v5 delta fetched full JSON'))
    original_resolve = storage._pg_resolve_any_with_depth
    reconstruction_calls = []

    def counted_reconstruction(*args, **kwargs):
        reconstruction_calls.append(1)
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(storage, '_pg_resolve_any_with_depth', counted_reconstruction)
    with storage.verified_manifest_scope(new, manifest_sha256(new)):
        with Session(reference_postgresql) as session, session.begin():
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            raw = storage.store_manifest(
                session, anchor, new, manifest_sha256(new), dependency_advance=proof,
            )
            assert storage.DELTA_REF in raw
            session.add(ReferenceBatch(
                batch_id='delta-child', stream_id=stream_id,
                revision_id=revision_id, batch_key='delta-child',
                payload_hash='0' * 64, kind='calculation', outcome='committed',
                seq=2, expected_seq=1, dependency_manifest=raw,
                source_evidence={}, projected_action_pks=[], diagnostics=[],
                processed_at=datetime.now(UTC),
            ))
        with Session(reference_postgresql) as session, session.begin():
            child = session.get(ReferenceBatch, 'delta-child',
                                options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, child) is new
            first_reconstruction_count = len(reconstruction_calls)
            same = storage.store_manifest(session, child, new, manifest_sha256(new))
            assert same[storage.REF]['batch_id'] == child.batch_id
            session.add(ReferenceBatch(
                batch_id='v1-after-delta', stream_id=stream_id,
                revision_id=revision_id, batch_key='v1-after-delta',
                payload_hash='0' * 64, kind='calculation', outcome='committed',
                seq=3, expected_seq=2, dependency_manifest=same,
                source_evidence={}, projected_action_pks=[], diagnostics=[],
                processed_at=datetime.now(UTC),
            ))
            session.flush()
            latest = session.get(ReferenceBatch, 'v1-after-delta',
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, latest) is new
            assert len(reconstruction_calls) == first_reconstruction_count
    with Session(reference_postgresql) as session:
        child = session.get(ReferenceBatch, 'v1-after-delta',
                            options=[defer(ReferenceBatch.dependency_manifest)])
        assert storage.resolve_manifest(session, child) == new


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize('tamper', ('delta_block', 'parent_digest', 'parent_block', 'parent_id'))
def test_pg_v5_delta_rejects_tampered_child_or_parent_bounded(
    reference_postgresql, monkeypatch, tamper,  # noqa: F811
):
    from datetime import UTC, datetime
    from sqlalchemy import update
    from sqlalchemy.orm import Session, defer
    from app.reference_trading.packed_fingerprints import PackedFingerprints, pack_fingerprints

    full, _, stream_id, revision_id, anchor_id = _pg_anchor(
        reference_postgresql, packed=True,
    )
    new = {**full, 'input_fingerprints': pack_fingerprints((
        *PackedFingerprints(full['input_fingerprints']), 'a' * 64,
    ))}
    proof = prove_dependency_append(full, new, appended_ranges=('new',))
    with Session(reference_postgresql) as session, session.begin():
        anchor = session.get(ReferenceBatch, anchor_id)
        raw = storage.store_manifest(
            session, anchor, new, manifest_sha256(new), dependency_advance=proof,
        )
        assert storage.DELTA_REF in raw
        session.add(ReferenceBatch(
            batch_id='delta-tamper-child', stream_id=stream_id,
            revision_id=revision_id, batch_key='delta-tamper-child',
            payload_hash='0' * 64, kind='calculation', outcome='committed',
            seq=2, expected_seq=1, dependency_manifest=raw,
            source_evidence={}, projected_action_pks=[], diagnostics=[],
            processed_at=datetime.now(UTC),
        ))
    if tamper in {'delta_block', 'parent_digest', 'parent_id'}:
        changed = deepcopy(raw)
        ref = changed[storage.DELTA_REF]
        if tamper == 'delta_block':
            ref['vectors']['input_fingerprints']['blocks'][0] = 'A'
        elif tamper == 'parent_digest':
            ref['parent_sha256'] = '0' * 64
        else:
            ref['parent_batch_id'] = 'missing'
        target_id = 'delta-tamper-child'
    else:
        changed = deepcopy(full)
        changed['input_fingerprints']['blocks'][0] = 'A'
        target_id = anchor_id
    with reference_postgresql.begin() as connection:
        connection.execute(update(ReferenceBatch).where(
            ReferenceBatch.batch_id == target_id,
        ).values(dependency_manifest=changed))
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('tampered delta fetched full JSON'))
    with Session(reference_postgresql) as session:
        child = session.get(ReferenceBatch, 'delta-tamper-child',
                            options=[defer(ReferenceBatch.dependency_manifest)])
        with pytest.raises(storage.ManifestStorageError):
            storage.resolve_manifest(session, child)


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize('target', ('delta', 'v1_child'))
def test_pg_scoped_delta_cache_rechecks_parent_after_other_transaction(
    reference_postgresql, monkeypatch, target,  # noqa: F811
):
    from datetime import UTC, datetime
    from sqlalchemy import update
    from sqlalchemy.orm import Session, defer
    from app.reference_trading.packed_fingerprints import PackedFingerprints, pack_fingerprints

    full, _, stream_id, revision_id, anchor_id = _pg_anchor(
        reference_postgresql, packed=True,
    )
    new = {**full, 'input_fingerprints': pack_fingerprints((
        *PackedFingerprints(full['input_fingerprints']), 'a' * 64,
    ))}
    proof = prove_dependency_append(full, new, appended_ranges=('new',))
    with Session(reference_postgresql) as session, session.begin():
        anchor = session.get(ReferenceBatch, anchor_id)
        delta = storage.store_manifest(
            session, anchor, new, manifest_sha256(new), dependency_advance=proof,
        )
        assert storage.DELTA_REF in delta
        session.add(ReferenceBatch(
            batch_id='cached-delta', stream_id=stream_id,
            revision_id=revision_id, batch_key='cached-delta',
            payload_hash='0' * 64, kind='calculation', outcome='committed',
            seq=2, expected_seq=1, dependency_manifest=delta,
            source_evidence={}, projected_action_pks=[], diagnostics=[],
            processed_at=datetime.now(UTC),
        ))
        session.add(ReferenceBatch(
            batch_id='cached-v1', stream_id=stream_id,
            revision_id=revision_id, batch_key='cached-v1',
            payload_hash='0' * 64, kind='calculation', outcome='committed',
            seq=3, expected_seq=2,
            dependency_manifest={**storage._head(new), storage.REF: {
                'batch_id': 'cached-delta', 'sha256': manifest_sha256(new),
            }},
            source_evidence={}, projected_action_pks=[], diagnostics=[],
            processed_at=datetime.now(UTC),
        ))
    batch_id = 'cached-delta' if target == 'delta' else 'cached-v1'
    monkeypatch.setattr(storage, '_pg_full',
                        lambda *_args: pytest.fail('cached delta fetched full JSON'))
    with storage.verified_manifest_scope(new, manifest_sha256(new)):
        with Session(reference_postgresql) as session:
            row = session.get(ReferenceBatch, batch_id,
                              options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, row) is new
        changed = deepcopy(full)
        block = changed['input_fingerprints']['blocks'][0]
        changed['input_fingerprints']['blocks'][0] = (
            'A' if block[0] != 'A' else 'B'
        ) + block[1:]
        with reference_postgresql.begin() as connection:
            connection.execute(update(ReferenceBatch).where(
                ReferenceBatch.batch_id == anchor_id,
            ).values(dependency_manifest=changed))
        with Session(reference_postgresql) as session:
            row = session.get(ReferenceBatch, batch_id,
                              options=[defer(ReferenceBatch.dependency_manifest)])
            with pytest.raises(storage.ManifestStorageError):
                storage.resolve_manifest(session, row)


def test_commit_batch_hashes_prepared_manifest_once(monkeypatch):
    from app.reference_trading import repository as repository_module
    from tests.reference_trading.test_repository import _open_batch, _seed_repository

    repo, _, stream, revision, manifest, token = _seed_repository()
    prepared = _open_batch(stream, revision, manifest, token)
    original = repository_module.manifest_sha256
    calls = []

    def counted(value):
        if value is prepared.dependency_manifest:
            calls.append(1)
        return original(value)

    monkeypatch.setattr(repository_module, "manifest_sha256", counted)
    repo.commit_batch(token, prepared)
    assert len(calls) == 1


@pytest.mark.isolated_postgresql
@pytest.mark.parametrize("tamper", ("body", "identity", "head"))
def test_scoped_pg_anchor_rejects_changed_body_identity_or_reference_head(
    reference_postgresql, tamper,  # noqa: F811
):
    from datetime import UTC, datetime
    from sqlalchemy import update
    from sqlalchemy.orm import Session, defer

    full, digest, stream_id, revision_id, anchor_id = _pg_anchor(reference_postgresql)
    child_id = "manifest-child"
    with storage.verified_manifest_scope(full, digest):
        with Session(reference_postgresql) as session, session.begin():
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, anchor) is full
            raw = storage.store_manifest(session, anchor, full, digest)
            session.add(ReferenceBatch(
                batch_id=child_id, stream_id=stream_id, revision_id=revision_id,
                batch_key="manifest-child", payload_hash="0" * 64,
                kind="calculation", outcome="committed", seq=2, expected_seq=1,
                dependency_manifest=raw, source_evidence={}, projected_action_pks=[],
                diagnostics=[], processed_at=datetime.now(UTC),
            ))
        with reference_postgresql.begin() as connection:
            if tamper == "body":
                changed = {**full, "input_fingerprints": ["a" * 64, *full["input_fingerprints"][1:]]}
                connection.execute(update(ReferenceBatch).where(
                    ReferenceBatch.batch_id == anchor_id,
                ).values(dependency_manifest=changed))
            elif tamper == "identity":
                connection.execute(update(ReferenceBatch).where(
                    ReferenceBatch.batch_id == anchor_id,
                ).values(outcome="failed"))
            else:
                changed = {**raw, "query_since": "2025-01-01"}
                connection.execute(update(ReferenceBatch).where(
                    ReferenceBatch.batch_id == child_id,
                ).values(dependency_manifest=changed))
        with Session(reference_postgresql) as session:
            child = session.get(ReferenceBatch, child_id,
                                options=[defer(ReferenceBatch.dependency_manifest)])
            with pytest.raises(storage.ManifestStorageError):
                storage.resolve_manifest(session, child)


@pytest.mark.isolated_postgresql
def test_scoped_pg_inline_anchor_rejects_changed_body_before_allow_other(
    reference_postgresql,  # noqa: F811
):
    from sqlalchemy import update
    from sqlalchemy.orm import Session, defer

    full, digest, _, _, anchor_id = _pg_anchor(reference_postgresql)
    with storage.verified_manifest_scope(full, digest):
        with Session(reference_postgresql) as session:
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, anchor) is full
        changed = {**full, "input_fingerprints": ["a" * 64, *full["input_fingerprints"][1:]]}
        with reference_postgresql.begin() as connection:
            connection.execute(update(ReferenceBatch).where(
                ReferenceBatch.batch_id == anchor_id,
            ).values(dependency_manifest=changed))
        with Session(reference_postgresql) as session:
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            with pytest.raises(storage.ManifestStorageError):
                storage.resolve_manifest(session, anchor)


@pytest.mark.isolated_postgresql
def test_scoped_pg_anchor_rechecks_after_scope_exit_and_rollback(
    reference_postgresql, monkeypatch,  # noqa: F811
):
    from sqlalchemy.orm import Session, defer

    full, digest, _, _, anchor_id = _pg_anchor(reference_postgresql)
    original = storage._pg_actual_manifest
    calls = []

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(storage, "_pg_actual_manifest", counted)
    with storage.verified_manifest_scope(full, digest):
        with Session(reference_postgresql) as session:
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, anchor) is full
            assert len(calls) == 1
            session.rollback()
            assert storage._scope.get().anchor_key is None
            assert storage._scope.get().resolved is None
        with Session(reference_postgresql) as session:
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, anchor) is full
            assert len(calls) == 2
    with storage.verified_manifest_scope(full, digest):
        with Session(reference_postgresql) as session:
            anchor = session.get(ReferenceBatch, anchor_id,
                                 options=[defer(ReferenceBatch.dependency_manifest)])
            assert storage.resolve_manifest(session, anchor) is full
            assert len(calls) == 3
