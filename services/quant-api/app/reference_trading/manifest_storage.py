"""Lossless same-revision dependency-manifest references; no schema migration."""

from app.reference_trading.contracts import manifest_sha256
from app.reference_trading.models import ReferenceBatch

REF = "_reference_dependency_manifest_v1"
LARGE_KEYS = frozenset(
    {"input_fingerprints", "calendar_session_effective_fingerprints", "source_input_fingerprints"}
)
MIN_BYTES = 64_000


class ManifestStorageError(ValueError):
    def __init__(self):
        super().__init__("REFERENCE_MANIFEST_STORAGE_INVALID")


def _head(full):
    return {key: value for key, value in full.items() if key not in LARGE_KEYS}


def resolve_manifest(session, batch):
    raw = batch.dependency_manifest
    if not isinstance(raw, dict):
        raise ManifestStorageError()
    if REF not in raw:
        return raw
    ref = raw[REF]
    if (
        not isinstance(ref, dict)
        or set(ref) != {"batch_id", "sha256"}
        or not isinstance(ref["batch_id"], str)
        or not 0 < len(ref["batch_id"]) <= 96
        or not isinstance(ref["sha256"], str)
        or len(ref["sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in ref["sha256"])
        or batch.kind != "calculation"
        or type(batch.seq) is not int
    ):
        raise ManifestStorageError()
    anchor = session.get(ReferenceBatch, ref["batch_id"])
    if (
        anchor is None
        or anchor.stream_id != batch.stream_id
        or anchor.revision_id != batch.revision_id
        or anchor.kind not in {"seed_seal", "calculation"}
        or anchor.outcome != "committed"
        or type(anchor.seq) is not int
        or not 0 < anchor.seq < batch.seq
        or not isinstance(anchor.dependency_manifest, dict)
        or REF in anchor.dependency_manifest
    ):
        raise ManifestStorageError()
    full = anchor.dependency_manifest
    if manifest_sha256(full) != ref["sha256"] or {
        key: value for key, value in raw.items() if key != REF
    } != _head(full):
        raise ManifestStorageError()
    return full


def store_manifest(session, prior_batch, full, digest):
    """Store a validated historical calculation without repeating its large arrays."""
    if REF in full:
        raise ManifestStorageError()
    # Fingerprints are fixed-width hex, so this bound avoids serializing a
    # small manifest only to discover it did not need indirection.
    if sum(len(full.get(key, ())) for key in LARGE_KEYS) * 64 < MIN_BYTES:
        return full
    prior = resolve_manifest(session, prior_batch)
    if manifest_sha256(prior) != digest:
        return full  # First batch of a new immutable digest is its inline anchor.
    raw = prior_batch.dependency_manifest
    anchor_id = raw[REF]["batch_id"] if REF in raw else prior_batch.batch_id
    return {**_head(full), REF: {"batch_id": anchor_id, "sha256": digest}}
