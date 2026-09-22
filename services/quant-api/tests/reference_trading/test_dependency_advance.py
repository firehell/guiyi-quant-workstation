from __future__ import annotations

from dataclasses import replace

import pytest

from app.reference_trading.contracts import prove_dependency_append
from app.reference_trading.repository import RepositoryConflict
from tests.reference_trading.test_repository import _open_batch, _seed_repository


def test_append_only_dependency_advance_commits_manifest_and_checkpoint_atomically() -> None:
    repository, _factory, stream, revision, manifest, token = _seed_repository()
    next_manifest = {
        "dataset_revision": "fixture-v1",
        "partitions": [
            {"key": "2026-08", "sha256": "a" * 64},
        ],
    }
    prepared = replace(
        _open_batch(stream, revision, next_manifest, token),
        dependency_advance=prove_dependency_append(
            manifest, next_manifest, appended_ranges=("2026-08",),
        ),
    )

    committed = repository.commit_batch(token, prepared)
    state = repository.read_state(stream.stream_id, revision)

    assert committed.seq == 2
    assert state.dependency_manifest == next_manifest
    assert state.dependency_digest == prepared.dependency_advance.new_digest
    assert state.checkpoint.seq == 2


def test_dependency_advance_rejects_changed_prefix_and_stale_prior_digest() -> None:
    repository, _factory, stream, revision, manifest, token = _seed_repository()
    changed = {"dataset_revision": "fixture-v2"}
    with pytest.raises(ValueError, match="append-only"):
        prove_dependency_append(manifest, changed, appended_ranges=("changed",))

    valid_new = {"dataset_revision": "fixture-v1", "partitions": ["tail"]}
    advance = prove_dependency_append(manifest, valid_new, appended_ranges=("tail",))
    forged = replace(advance, expected_prior_digest="0" * 64)
    prepared = replace(
        _open_batch(stream, revision, valid_new, token),
        dependency_advance=forged,
    )
    with pytest.raises(RepositoryConflict, match="DEPENDENCY_CONFLICT"):
        repository.commit_batch(token, prepared)
    assert repository.read_batch(stream.stream_id, revision, prepared.batch_key) is None


def test_dependency_advance_idempotent_replay_returns_receipt_after_digest_changed() -> None:
    repository, _factory, stream, revision, manifest, token = _seed_repository()
    next_manifest = {"dataset_revision": "fixture-v1", "partitions": ["tail"]}
    prepared = replace(
        _open_batch(stream, revision, next_manifest, token),
        dependency_advance=prove_dependency_append(
            manifest, next_manifest, appended_ranges=("tail",),
        ),
    )

    first = repository.commit_batch(token, prepared)
    second = repository.commit_batch(token, prepared)

    assert second.outcome == "noop"
    assert second.seq == first.seq
    assert second.checkpoint_hash == first.checkpoint_hash


def test_same_partition_tail_is_append_only_when_exact_bar_prefix_is_preserved() -> None:
    prior = {
        "reader": "newow_product_reader_v1",
        "input_fingerprints": ["a" * 64, "b" * 64],
        "rank1": [["RB2610", "2026-09-01", "2026-09-18"]],
    }
    extended = {
        "reader": "newow_product_reader_v1",
        "input_fingerprints": ["a" * 64, "b" * 64, "c" * 64],
        "rank1": [["RB2610", "2026-09-01", "2026-09-19"]],
    }

    proof = prove_dependency_append(
        prior, extended, appended_ranges=("same-partition:2026-09-19",),
    )

    assert proof.expected_prior_digest != proof.new_digest
    assert proof.prior_prefix_digest == proof.new_prefix_digest

    with pytest.raises(ValueError, match="append-only"):
        prove_dependency_append(
            prior,
            {
                **extended,
                "input_fingerprints": ["f" * 64, "b" * 64, "c" * 64],
            },
            appended_ranges=("same-partition:2026-09-19",),
        )

    with pytest.raises(ValueError, match="append-only"):
        prove_dependency_append(
            {**prior, "data_interruptions": []},
            {
                **extended,
                # A newly discovered boundary on the previously processed
                # last Bar changes that Bar's composite input identity.
                "input_fingerprints": ["a" * 64, "d" * 64, "c" * 64],
                "data_interruptions": ["e" * 64],
            },
            appended_ranges=("same-partition:2026-09-19",),
        )
