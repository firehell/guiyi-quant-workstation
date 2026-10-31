"""Lossless bounded SHA256 leaf proof wire and partial-block prefix checks."""

import base64
from hashlib import sha256
import json

import pytest

from app.reference_trading.packed_fingerprints import (
    BLOCK_SIZE, ENCODING, MAX_LEAVES, PackedFingerprintBuilder,
    PackedFingerprints, pack_fingerprints, packed_fingerprints_sha256,
)


def _leaves(count):
    return [sha256(str(index).encode()).hexdigest() for index in range(count)]


@pytest.mark.parametrize("count", (0, 1, 255, 256, 257, 513))
def test_roundtrip_exact_leaves_and_canonical_hashes(count):
    values = _leaves(count)
    builder = PackedFingerprintBuilder()
    for value in values:
        builder.add(value)
    wire = builder.finish()
    assert builder.seal() == wire
    assert builder.count == count
    assert wire["encoding"] == ENCODING
    assert wire["block_size"] == BLOCK_SIZE
    assert len(wire["blocks"]) == (count + BLOCK_SIZE - 1) // BLOCK_SIZE
    view = PackedFingerprints(wire)
    assert list(view.iter_leaf()) == values
    assert list(view) == values
    assert view.leaf_count == len(view) == count
    assert view.to_wire() == wire
    assert view.equals(pack_fingerprints(values))
    assert view.legacy_array_sha256() == sha256(json.dumps(
        values, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()).hexdigest()
    assert packed_fingerprints_sha256(wire) == sha256(json.dumps(
        wire, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()).hexdigest()
    if count:
        assert view.count(values[0]) == 1
        assert view[0] == values[0]
        assert view[-1] == values[-1]
        assert view[:min(count, 2)] == tuple(values[:2])
        with pytest.raises(IndexError):
            view[count]
    with pytest.raises(ValueError, match="BUDGET_EXCEEDED"):
        builder.add("a" * 64)


@pytest.mark.parametrize("prefix", (0, 1, 255, 256, 257, 511, 512, 513))
def test_prefix_checks_exact_leaf_inside_partial_block(prefix):
    values = _leaves(513)
    shorter = PackedFingerprints(pack_fingerprints(values[:prefix]))
    full = PackedFingerprints(pack_fingerprints(values))
    assert shorter.is_prefix_of(full)
    assert shorter.equals(full) is (prefix == 513)
    if prefix:
        changed = values.copy()
        changed[prefix - 1] = "0" * 64 if changed[prefix - 1] != "0" * 64 else "1" * 64
        assert not shorter.is_prefix_of(pack_fingerprints(changed))
    if prefix < 513:
        assert not full.is_prefix_of(shorter)


@pytest.mark.parametrize("mutation", (
    lambda w: w.update(extra=1),
    lambda w: w.pop("encoding"),
    lambda w: w.update(encoding="sha256-blockroot-v1"),
    lambda w: w.update(block_size=True),
    lambda w: w.update(block_size=128),
    lambda w: w.update(count=True),
    lambda w: w.update(count=-1),
    lambda w: w.update(count=MAX_LEAVES + 1),
    lambda w: w.update(count=257),
    lambda w: w.update(blocks=[]),
    lambda w: w["blocks"].__setitem__(0, w["blocks"][0][:-1]),
    lambda w: w["blocks"].__setitem__(0, w["blocks"][0][:-1] + "!"),
    lambda w: w["blocks"].__setitem__(0, base64.b64encode(b"x" * 33).decode()),
    lambda w: w["blocks"].__setitem__(0, base64.b64encode(b"x" * 32).decode().rstrip("=")),
))
def test_rejects_noncanonical_or_misaligned_wire(mutation):
    wire = pack_fingerprints(["a" * 64])
    mutation(wire)
    with pytest.raises(ValueError, match="REFERENCE_FINGERPRINT_PACK_INVALID"):
        PackedFingerprints(wire)


@pytest.mark.parametrize("leaf", ("A" * 64, "a" * 63, "g" * 64, 5, None))
def test_builder_rejects_noncanonical_leaf(leaf):
    builder = PackedFingerprintBuilder()
    with pytest.raises(ValueError, match="REFERENCE_FINGERPRINT_INVALID"):
        builder.append(leaf)
    assert builder.count == 0


def test_slice_rejects_whole_vector_expansion():
    view = PackedFingerprints(pack_fingerprints(_leaves(257)))
    assert view[255:257] == tuple(_leaves(257)[255:257])
    with pytest.raises(ValueError, match="REFERENCE_FINGERPRINT_SLICE_EXCEEDED"):
        view[:]
