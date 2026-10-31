"""Lossless, bounded SHA256 leaf vectors for historical reference proof v5.

Each leaf remains independently addressable. Blocks are transport packing only;
they are never Merkle roots and cannot substitute for individual prefix checks.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Iterator, Sequence
from hashlib import sha256
import json
import re
from typing import overload


ENCODING = "sha256-leaves-b64-v1"
BLOCK_SIZE = 256
MAX_LEAVES = 2_000_000
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_KEYS = frozenset(("encoding", "block_size", "count", "blocks"))


def _leaf_bytes(value: str) -> bytes:
    if not isinstance(value, str) or _HEX.fullmatch(value) is None:
        raise ValueError("REFERENCE_FINGERPRINT_INVALID")
    return bytes.fromhex(value)


class PackedFingerprintBuilder:
    """Append one lowercase SHA256 at a time; hold at most one raw block."""

    def __init__(self) -> None:
        self._blocks: list[str] = []
        self._pending = bytearray()
        self._count = 0
        self._sealed = False

    @property
    def count(self) -> int:
        return self._count

    def add(self, fingerprint: str) -> None:
        if self._sealed or self._count >= MAX_LEAVES:
            raise ValueError("REFERENCE_FINGERPRINT_BUDGET_EXCEEDED")
        self._pending.extend(_leaf_bytes(fingerprint))
        self._count += 1
        if len(self._pending) == 32 * BLOCK_SIZE:
            self._blocks.append(base64.b64encode(self._pending).decode("ascii"))
            self._pending.clear()

    append = add

    def finish(self) -> dict[str, object]:
        if not self._sealed:
            if self._pending:
                self._blocks.append(base64.b64encode(self._pending).decode("ascii"))
                self._pending.clear()
            self._sealed = True
        return {
            "encoding": ENCODING, "block_size": BLOCK_SIZE,
            "count": self._count, "blocks": list(self._blocks),
        }

    seal = finish
    result = finish


class PackedFingerprints(Sequence[str]):
    """Validated view over an immutable copy of a packed wire vector."""

    def __init__(self, wire: object) -> None:
        if type(wire) is not dict or frozenset(wire) != _KEYS:
            raise ValueError("REFERENCE_FINGERPRINT_PACK_INVALID")
        if (wire["encoding"] != ENCODING
            or type(wire["block_size"]) is not int or wire["block_size"] != BLOCK_SIZE
            or type(wire["count"]) is not int
            or not 0 <= wire["count"] <= MAX_LEAVES
            or type(wire["blocks"]) is not list):
            raise ValueError("REFERENCE_FINGERPRINT_PACK_INVALID")
        count = wire["count"]
        blocks = wire["blocks"]
        if len(blocks) != (count + BLOCK_SIZE - 1) // BLOCK_SIZE:
            raise ValueError("REFERENCE_FINGERPRINT_PACK_INVALID")
        for index, encoded in enumerate(blocks):
            leaves = min(BLOCK_SIZE, count - index * BLOCK_SIZE)
            expected_bytes = 32 * leaves
            expected_chars = 4 * ((expected_bytes + 2) // 3)
            if type(encoded) is not str or len(encoded) != expected_chars:
                raise ValueError("REFERENCE_FINGERPRINT_PACK_INVALID")
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("REFERENCE_FINGERPRINT_PACK_INVALID") from exc
            if (len(decoded) != expected_bytes
                or base64.b64encode(decoded).decode("ascii") != encoded):
                raise ValueError("REFERENCE_FINGERPRINT_PACK_INVALID")
        self._count: int = count
        self._blocks: tuple[str, ...] = tuple(blocks)

    @property
    def leaf_count(self) -> int:
        return self._count

    def __len__(self) -> int:
        return self._count

    def item(self, index: int) -> str:
        if type(index) is not int:
            raise TypeError("fingerprint index must be an integer")
        if index < 0:
            index += self._count
        if not 0 <= index < self._count:
            raise IndexError(index)
        block = base64.b64decode(self._blocks[index // BLOCK_SIZE], validate=True)
        start = 32 * (index % BLOCK_SIZE)
        return block[start:start + 32].hex()

    @overload
    def __getitem__(self, index: int) -> str: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[str, ...]: ...

    def __getitem__(self, index: int | slice) -> str | tuple[str, ...]:
        if isinstance(index, slice):
            start, stop, step = index.indices(self._count)
            positions = range(start, stop, step)
            if len(positions) > BLOCK_SIZE:
                raise ValueError("REFERENCE_FINGERPRINT_SLICE_EXCEEDED")
            return tuple(self.item(position) for position in positions)
        return self.item(index)

    def iter_leaf(self) -> Iterator[str]:
        for encoded in self._blocks:
            block = base64.b64decode(encoded, validate=True)
            for start in range(0, len(block), 32):
                yield block[start:start + 32].hex()

    def __iter__(self) -> Iterator[str]:
        return self.iter_leaf()

    def to_wire(self) -> dict[str, object]:
        return {
            "encoding": ENCODING, "block_size": BLOCK_SIZE,
            "count": self._count, "blocks": list(self._blocks),
        }

    def is_prefix_of(self, other: PackedFingerprints | object) -> bool:
        if not isinstance(other, PackedFingerprints):
            other = PackedFingerprints(other)
        if self._count > other._count:
            return False
        complete, partial = divmod(self._count, BLOCK_SIZE)
        if self._blocks[:complete] != other._blocks[:complete]:
            return False
        if not partial:
            return True
        left = base64.b64decode(self._blocks[complete], validate=True)
        right = base64.b64decode(other._blocks[complete], validate=True)
        return left[:32 * partial] == right[:32 * partial]

    def equals(self, other: PackedFingerprints | object) -> bool:
        if not isinstance(other, PackedFingerprints):
            other = PackedFingerprints(other)
        return self._count == other._count and self._blocks == other._blocks

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PackedFingerprints):
            return NotImplemented
        return self.equals(other)

    def legacy_array_sha256(self) -> str:
        """The v4 canonical JSON hash without expanding a hex-string list."""
        digest = sha256(b"[")
        first = True
        for leaf in self:
            if not first:
                digest.update(b",")
            digest.update(b'"')
            digest.update(leaf.encode("ascii"))
            digest.update(b'"')
            first = False
        digest.update(b"]")
        return digest.hexdigest()


def pack_fingerprints(values: Iterable[str]) -> dict[str, object]:
    builder = PackedFingerprintBuilder()
    for value in values:
        builder.add(value)
    return builder.finish()


def packed_fingerprints_sha256(value: PackedFingerprints | object) -> str:
    """Canonical v5 encoded-vector hash, independent of dict insertion order."""
    vector = value if isinstance(value, PackedFingerprints) else PackedFingerprints(value)
    digest = sha256()
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False)
    for part in encoder.iterencode(vector.to_wire()):
        digest.update(part.encode("ascii"))
    return digest.hexdigest()
