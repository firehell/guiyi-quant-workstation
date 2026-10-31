"""Lossless same-revision dependency-manifest references; no schema migration."""

from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
from types import SimpleNamespace

from sqlalchemy import BigInteger, Text, and_, case, cast, event, func, literal, literal_column, or_, select, true, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.reference_trading.contracts import (
    DependencyAdvance, manifest_sha256, validate_dependency_advance,
)
from app.reference_trading.models import ReferenceBatch
from app.reference_trading.fingerprint_proof import fingerprint_count
from app.reference_trading.packed_fingerprints import (
    BLOCK_SIZE, ENCODING, MAX_LEAVES, PackedFingerprints,
)

REF = "_reference_dependency_manifest_v1"
DELTA_REF = "_reference_dependency_manifest_v2"
LARGE_KEYS = frozenset(
    {"input_fingerprints", "calendar_session_effective_fingerprints", "source_input_fingerprints"}
)
MIN_BYTES = 64_000
MAX_HEAD_BYTES = 8 * 1024 * 1024
MAX_VECTOR_META_BYTES = 4 * 1024
MAX_BLOCK_CHARS = 4 * ((32 * 256 + 2) // 3)
MAX_BLOCKS = (MAX_LEAVES + BLOCK_SIZE - 1) // BLOCK_SIZE
MAX_DELTA_DEPTH = 12
MAX_DELTA_BYTES = 1024 * 1024
MAX_LEGACY_TOTAL_LEAVES = 2_000_000
LEGACY_ARRAY_READERS = frozenset({
    "newow_product_reader_v2", "newow_product_reader_intraday_v3",
    "newow_product_reader_prefix_v4", "newow_fusion_saved_sources_v1",
    "newow_fusion_saved_sources_v2", "subing_mds_historical_v1",
})
BOUNDED_LEGACY_KEYS = {
    "newow_product_reader_prefix_v4": frozenset({
        "input_fingerprints", "calendar_session_effective_fingerprints",
    }),
    "newow_fusion_saved_sources_v2": LARGE_KEYS,
}
_HEX_LEAF = re.compile(r"[0-9a-f]{64}\Z")


class ManifestStorageError(ValueError):
    def __init__(self):
        super().__init__("REFERENCE_MANIFEST_STORAGE_INVALID")


class _VerificationScope:
    def __init__(self, expected, digest):
        if not isinstance(expected, dict) or manifest_sha256(expected) != digest:
            raise ManifestStorageError()
        try:
            self.large_member_count = sum(
                fingerprint_count(expected[key]) for key in LARGE_KEYS if key in expected
            )
        except (TypeError, ValueError) as error:
            raise ManifestStorageError() from error
        self.expected = expected
        self.digest = digest
        self.packed_vectors = (
            {key: expected[key] for key in LARGE_KEYS if key in expected}
            if "input_fingerprints" in expected
            and all(type(expected[key]) is dict for key in LARGE_KEYS if key in expected)
            else None
        )
        self.anchor_key = None
        self.anchor_chain = None
        self.resolved = None

    def clear(self):
        self.anchor_key = None
        self.anchor_chain = None
        self.resolved = None


_scope: ContextVar[_VerificationScope | None] = ContextVar(
    "reference_manifest_verification_scope", default=None,
)


@contextmanager
def verified_manifest_scope(expected_manifest, expected_digest):
    """Reuse a verified PG anchor only during one pinned historical operation."""
    scope = _VerificationScope(expected_manifest, expected_digest)
    token = _scope.set(scope)
    try:
        yield
    finally:
        scope.clear()
        _scope.reset(token)


@event.listens_for(Session, "after_soft_rollback")
def _clear_after_rollback(_session, _previous_transaction):
    scope = _scope.get()
    if scope is not None:
        scope.clear()


def _head(full):
    return {key: value for key, value in full.items() if key not in LARGE_KEYS}


def _bounded_json_size(value, limit):
    size = 0
    for part in json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=True, allow_nan=False).iterencode(value):
        size += len(part.encode("utf-8"))
        if size > limit:
            return False
    return True


def _same_json(left, right):
    return manifest_sha256(left) == manifest_sha256(right)


def _json_size(value):
    return sum(len(part.encode("utf-8")) for part in json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).iterencode(value))


def _sha256_text(value):
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _v5_manifest(value):
    return (type(value) is dict
            and (value.get("reader") == "newow_product_reader_prefix_v5"
                 or (value.get("reader") == "newow_fusion_saved_sources_v3"
                     and value.get("source_reader") == "newow_product_reader_prefix_v5")))


def _delta_full(raw, parent, *, parent_id, parent_depth):
    if (type(raw) is not dict or set(raw).intersection({REF, DELTA_REF}) != {DELTA_REF}
            or set(raw).intersection(LARGE_KEYS)
            or not _v5_manifest(raw) or not _v5_manifest(parent)
            or not _bounded_json_size(raw[DELTA_REF], MAX_DELTA_BYTES)):
        raise ManifestStorageError()
    ref = raw[DELTA_REF]
    if (type(ref) is not dict
            or set(ref) != {"parent_batch_id", "parent_sha256", "sha256", "depth", "vectors"}
            or ref["parent_batch_id"] != parent_id
            or not _sha256_text(ref["parent_sha256"])
            or not _sha256_text(ref["sha256"])
            or type(ref["depth"]) is not int
            or ref["depth"] != parent_depth + 1
            or not 1 <= ref["depth"] <= MAX_DELTA_DEPTH
            or type(ref["vectors"]) is not dict
            or ref["parent_sha256"] != manifest_sha256(parent)):
        raise ManifestStorageError()
    keys = {key for key in LARGE_KEYS if key in parent}
    if ("input_fingerprints" not in keys or set(ref["vectors"]) != keys):
        raise ManifestStorageError()
    full = {key: value for key, value in raw.items() if key != DELTA_REF}
    for key in keys:
        part = ref["vectors"][key]
        try:
            prior = PackedFingerprints(parent[key])
            if (type(part) is not dict
                    or set(part) != {"old_count", "new_count", "from_block", "blocks"}
                    or type(part["old_count"]) is not int
                    or type(part["new_count"]) is not int
                    or type(part["from_block"]) is not int
                    or type(part["blocks"]) is not list
                    or part["old_count"] != prior.leaf_count
                    or not prior.leaf_count <= part["new_count"] <= MAX_LEAVES
                    or part["from_block"] != prior.leaf_count // BLOCK_SIZE):
                raise ManifestStorageError()
            wire = {"encoding": ENCODING, "block_size": BLOCK_SIZE,
                    "count": part["new_count"],
                    "blocks": parent[key]["blocks"][:part["from_block"]] + part["blocks"]}
            current = PackedFingerprints(wire)
            if not prior.is_prefix_of(current):
                raise ManifestStorageError()
        except (TypeError, ValueError) as error:
            raise ManifestStorageError() from error
        full[key] = wire
    if manifest_sha256(full) != ref["sha256"]:
        raise ManifestStorageError()
    return full, ref["depth"]


def _pg_scope(session):
    scope = _scope.get()
    if scope is None or session.get_bind().dialect.name != "postgresql":
        return None
    return scope


def has_verified_manifest_scope(session):
    return _pg_scope(session) is not None


def _pg_body_hash():
    # This is PostgreSQL JSONB text bytes, not the canonical manifest hash.
    return func.encode(func.sha256(func.convert_to(
        cast(ReferenceBatch.dependency_manifest, Text), "UTF8",
    )), "hex")


def _pg_head():
    return _without_large(ReferenceBatch.dependency_manifest)


def _without_large(value):
    for key in sorted(LARGE_KEYS):
        value = value.op("-")(key)
    return value


def _pg_probe(session, batch_id):
    head = _pg_head()
    safe_head = case((and_(
        func.jsonb_typeof(ReferenceBatch.dependency_manifest) == "object",
        func.octet_length(cast(head, Text)) <= MAX_HEAD_BYTES,
    ), head), else_=cast(literal(None), JSONB))
    large_present = or_(*(
        ReferenceBatch.dependency_manifest.op("?")(key)
        for key in sorted(LARGE_KEYS)
    ))
    presence = func.jsonb_build_object(*(
        argument for key in sorted(LARGE_KEYS)
        for argument in (key, ReferenceBatch.dependency_manifest.op("?")(key))
    ))
    array_counts = func.jsonb_build_object(*(
        argument for key in sorted(LARGE_KEYS)
        for argument in (key, case((
            func.jsonb_typeof(ReferenceBatch.dependency_manifest.op("->")(key)) == "array",
            func.jsonb_array_length(ReferenceBatch.dependency_manifest.op("->")(key)),
        ), else_=-1))
    ))
    return session.execute(select(
        ReferenceBatch.batch_id, ReferenceBatch.stream_id,
        ReferenceBatch.revision_id, ReferenceBatch.kind,
        ReferenceBatch.outcome, ReferenceBatch.seq,
        safe_head, _pg_body_hash(), large_present, presence,
        func.jsonb_typeof(ReferenceBatch.dependency_manifest.op("->")("input_fingerprints")),
        array_counts,
    ).where(ReferenceBatch.batch_id == batch_id)).one_or_none()


def _pg_full(session, batch_id):
    # Full JSON and its server byte digest are from the same SELECT snapshot.
    return session.execute(select(
        ReferenceBatch.batch_id, ReferenceBatch.stream_id,
        ReferenceBatch.revision_id, ReferenceBatch.kind,
        ReferenceBatch.outcome, ReferenceBatch.seq,
        ReferenceBatch.dependency_manifest, _pg_body_hash(),
    ).where(ReferenceBatch.batch_id == batch_id)).one_or_none()


def _pg_packed_rows(batch_id, vector_limits, *, legacy_arrays=False):
    """One PG snapshot emits bounded vector metadata and blocks or SHA leaves."""
    body = select(
        ReferenceBatch.batch_id.label("batch_id"),
        ReferenceBatch.stream_id.label("stream_id"),
        ReferenceBatch.revision_id.label("revision_id"),
        ReferenceBatch.kind.label("batch_kind"),
        ReferenceBatch.outcome.label("outcome"),
        ReferenceBatch.seq.label("seq"),
        ReferenceBatch.dependency_manifest.label("manifest"),
        _pg_body_hash().label("server_hash"),
    ).where(ReferenceBatch.batch_id == batch_id).cte("anchor_body")
    body = body.prefix_with("MATERIALIZED", dialect="postgresql")
    raw_head = _without_large(body.c.manifest)
    safe_head = case((and_(
        func.jsonb_typeof(body.c.manifest) == "object",
        func.octet_length(cast(raw_head, Text)) <= MAX_HEAD_BYTES,
    ), raw_head), else_=cast(literal(None), JSONB))
    presence = func.jsonb_build_object(*(
        argument for key in sorted(LARGE_KEYS)
        for argument in (key, body.c.manifest.op("?")(key))
    ))
    empty_json = cast(literal(None), JSONB)

    def row(kind, key, ordinal, metadata, block, value_type, size, count,
            batch, stream, revision, batch_kind, outcome, seq, server_hash,
            present):
        return select(
            kind.label("row_kind"), key.label("vector_key"),
            ordinal.label("ordinal"), metadata.label("metadata"),
            block.label("block"), value_type.label("value_type"),
            size.label("value_length"), count.label("block_count"),
            batch.label("batch_id"), stream.label("stream_id"),
            revision.label("revision_id"), batch_kind.label("batch_kind"),
            outcome.label("outcome"), seq.label("seq"),
            server_hash.label("server_hash"), present.label("presence"),
        )

    null_text = cast(literal(None), Text)
    null_int = cast(literal(None), BigInteger)
    branches = [row(
        literal("header"), null_text, null_int, safe_head,
        null_text, null_text, null_int, null_int,
        body.c.batch_id, body.c.stream_id, body.c.revision_id,
        body.c.batch_kind, body.c.outcome, body.c.seq,
        body.c.server_hash, presence,
    ).select_from(body)]
    for key, max_blocks in sorted(vector_limits.items()):
        vector = body.c.manifest.op("->")(key)
        if legacy_arrays:
            vector_type = func.jsonb_typeof(vector)
            leaf_count = case((vector_type == "array", func.jsonb_array_length(vector)),
                              else_=-1)
            branches.append(row(
                literal("vector"), literal(key), null_int, empty_json,
                null_text, vector_type, null_int, leaf_count,
                null_text, null_text, null_text, null_text, null_text,
                null_int, null_text, empty_json,
            ).select_from(body))
            safe_leaves = case((and_(vector_type == "array", leaf_count <= max_blocks),
                                vector), else_=literal_column("'[]'::jsonb"))
            leaf = func.jsonb_array_elements(safe_leaves).table_valued(
                "value", with_ordinality="ordinality",
            ).lateral("legacy_leaf")
            value_type = func.jsonb_typeof(leaf.c.value)
            decoded = leaf.c.value.op("#>>")(literal_column("'{}'::text[]"))
            size = case((value_type == "string", func.octet_length(decoded)), else_=-1)
            safe_leaf = case((and_(value_type == "string", size <= 64),
                              decoded), else_=null_text)
            branches.append(row(
                literal("leaf"), literal(key), leaf.c.ordinality,
                empty_json, safe_leaf, value_type, size, null_int,
                null_text, null_text, null_text, null_text, null_text,
                null_int, null_text, empty_json,
            ).select_from(body.join(leaf, true())))
            continue
        blocks = vector.op("->")("blocks")
        vector_type = func.jsonb_typeof(vector)
        blocks_type = func.jsonb_typeof(blocks)
        block_count = case((blocks_type == "array", func.jsonb_array_length(blocks)),
                           else_=-1)
        raw_metadata = vector.op("-")("blocks")
        safe_metadata = case((and_(
            vector_type == "object",
            func.octet_length(cast(raw_metadata, Text)) <= MAX_VECTOR_META_BYTES,
        ), raw_metadata), else_=empty_json)
        branches.append(row(
            literal("vector"), literal(key), null_int, safe_metadata,
            null_text, vector_type, null_int, block_count,
            null_text, null_text, null_text, null_text, null_text,
            null_int, null_text, empty_json,
        ).select_from(body))
        safe_blocks = case((and_(
            vector_type == "object", blocks_type == "array",
            block_count <= max_blocks,
        ), blocks), else_=literal_column("'[]'::jsonb"))
        element = func.jsonb_array_elements(safe_blocks).table_valued(
            "value", with_ordinality="ordinality",
        ).lateral("packed_block")
        value_type = func.jsonb_typeof(element.c.value)
        decoded = element.c.value.op("#>>")(literal_column("'{}'::text[]"))
        size = case((value_type == "string", func.octet_length(decoded)), else_=-1)
        safe_block = case((and_(value_type == "string", size <= MAX_BLOCK_CHARS),
                           decoded), else_=null_text)
        branches.append(row(
            literal("block"), literal(key), element.c.ordinality,
            empty_json, safe_block, value_type, size, null_int,
            null_text, null_text, null_text, null_text, null_text,
            null_int, null_text, empty_json,
        ).select_from(body.join(element, true())))
    return union_all(*branches)


def _pg_compare_packed(session, batch_id, probe, scope):
    vectors = scope.packed_vectors
    expected_head = _head(scope.expected)
    if (vectors is None or not _bounded_json_size(expected_head, MAX_HEAD_BYTES)
            or any(not _bounded_json_size(
                {key: value for key, value in vector.items() if key != "blocks"},
                MAX_VECTOR_META_BYTES,
            ) for vector in vectors.values())):
        raise ManifestStorageError()
    seen_header = False
    seen_meta = {key: False for key in vectors}
    seen_blocks = {key: bytearray(len(vector["blocks"]))
                   for key, vector in vectors.items()}
    different = False
    result = session.execute(_pg_packed_rows(
        batch_id, {key: len(vector["blocks"]) for key, vector in vectors.items()},
    ).execution_options(
        stream_results=True, yield_per=128,
    ))
    try:
        for item in result:
            if item.row_kind == "header":
                if seen_header or (
                    item.batch_id, item.stream_id, item.revision_id,
                    item.batch_kind, item.outcome, item.seq,
                ) != _identity(probe) or item.server_hash != probe[7]:
                    raise ManifestStorageError()
                seen_header = True
                if (not isinstance(item.metadata, dict)
                        or not isinstance(item.presence, dict)
                        or not _same_json(item.presence,
                                          {key: key in vectors for key in sorted(LARGE_KEYS)})
                        or not _same_json(item.metadata, expected_head)):
                    raise ManifestStorageError()
                continue
            key = item.vector_key
            if key not in vectors:
                raise ManifestStorageError()
            vector = vectors[key]
            if item.row_kind == "vector":
                if seen_meta[key] or item.value_type != "object":
                    raise ManifestStorageError()
                seen_meta[key] = True
                if (not isinstance(item.metadata, dict)
                        or set(item.metadata) != {"encoding", "block_size", "count"}
                        or type(item.metadata["encoding"]) is not str
                        or item.metadata["encoding"] != ENCODING
                        or type(item.metadata["block_size"]) is not int
                        or item.metadata["block_size"] != BLOCK_SIZE
                        or type(item.metadata["count"]) is not int
                        or not 0 <= item.metadata["count"] <= MAX_LEAVES
                        or type(item.block_count) is not int
                        or item.block_count != len(vector["blocks"])):
                    raise ManifestStorageError()
                if not _same_json(item.metadata, {name: value for name, value in vector.items()
                                                  if name != "blocks"}):
                    different = True
            elif item.row_kind == "block":
                ordinal = item.ordinal
                if (type(ordinal) is not int or not 1 <= ordinal <= len(seen_blocks[key])
                        or seen_blocks[key][ordinal - 1]
                        or item.value_type != "string"
                        or type(item.value_length) is not int
                        or not 0 <= item.value_length <= MAX_BLOCK_CHARS
                        or not isinstance(item.block, str)):
                    raise ManifestStorageError()
                seen_blocks[key][ordinal - 1] = 1
                if item.block != vector["blocks"][ordinal - 1]:
                    different = True
            else:
                raise ManifestStorageError()
    finally:
        result.close()
    if (not seen_header or not all(seen_meta.values())
            or any(not all(bits) for bits in seen_blocks.values())):
        raise ManifestStorageError()
    return not different


def _pg_construct_packed(session, batch_id, probe):
    """Rebuild an exact v5 manifest from bounded PG rows, never a JSONB blob."""
    head, presence = probe[6], probe[9]
    if not isinstance(head, dict) or not isinstance(presence, dict):
        raise ManifestStorageError()
    v5 = (head.get("reader") == "newow_product_reader_prefix_v5"
          or head.get("source_reader") == "newow_product_reader_prefix_v5"
          or head.get("reader") == "newow_fusion_saved_sources_v3")
    if not v5:
        reader = head.get("reader")
        if type(reader) is str and reader in BOUNDED_LEGACY_KEYS:
            return _pg_construct_legacy_arrays(
                session, batch_id, probe, BOUNDED_LEGACY_KEYS[reader],
            )
        if (set(presence) == LARGE_KEYS
                and all(value is False for value in presence.values())):
            return head
        if probe[10] == "array" and (
                type(reader) is str and reader in LEGACY_ARRAY_READERS
                or (type(head.get("source_reader")) is str
                    and head["source_reader"] in LEGACY_ARRAY_READERS)):
            return None
        raise ManifestStorageError()
    if (not v5 or set(presence) != LARGE_KEYS
            or (head.get("reader") == "newow_fusion_saved_sources_v3"
                and head.get("source_reader") != "newow_product_reader_prefix_v5")
            or any(type(value) is not bool for value in presence.values())
            or presence["input_fingerprints"] is not True
            or probe[10] != "object"):
        raise ManifestStorageError()
    keys = tuple(key for key in sorted(LARGE_KEYS) if presence[key])
    slots = {key: [None] * MAX_BLOCKS for key in keys}
    metadata = {}
    seen_header = False
    result = session.execute(_pg_packed_rows(
        batch_id, {key: MAX_BLOCKS for key in keys},
    ).execution_options(stream_results=True, yield_per=128))
    try:
        for item in result:
            if item.row_kind == "header":
                if (seen_header
                        or (item.batch_id, item.stream_id, item.revision_id,
                            item.batch_kind, item.outcome, item.seq) != _identity(probe)
                        or item.server_hash != probe[7]
                        or not _same_json(item.metadata, head)
                        or not _same_json(item.presence, presence)):
                    raise ManifestStorageError()
                seen_header = True
                continue
            key = item.vector_key
            if key not in slots:
                raise ManifestStorageError()
            if item.row_kind == "vector":
                raw = item.metadata
                if (key in metadata or item.value_type != "object"
                        or not isinstance(raw, dict)
                        or set(raw) != {"encoding", "block_size", "count"}
                        or raw["encoding"] != ENCODING
                        or type(raw["block_size"]) is not int
                        or raw["block_size"] != BLOCK_SIZE
                        or type(raw["count"]) is not int
                        or not 0 <= raw["count"] <= MAX_LEAVES
                        or type(item.block_count) is not int
                        or item.block_count != (raw["count"] + BLOCK_SIZE - 1) // BLOCK_SIZE):
                    raise ManifestStorageError()
                metadata[key] = (raw, item.block_count)
            elif item.row_kind == "block":
                ordinal = item.ordinal
                if (type(ordinal) is not int or not 1 <= ordinal <= MAX_BLOCKS
                        or slots[key][ordinal - 1] is not None
                        or item.value_type != "string"
                        or type(item.value_length) is not int
                        or not 0 <= item.value_length <= MAX_BLOCK_CHARS
                        or not isinstance(item.block, str)):
                    raise ManifestStorageError()
                slots[key][ordinal - 1] = item.block
            else:
                raise ManifestStorageError()
    finally:
        result.close()
    if not seen_header or set(metadata) != set(keys):
        raise ManifestStorageError()
    full = dict(head)
    for key in keys:
        raw, count = metadata[key]
        if (any(value is None for value in slots[key][:count])
                or any(value is not None for value in slots[key][count:])):
            raise ManifestStorageError()
        wire = {**raw, "blocks": slots[key][:count]}
        try:
            PackedFingerprints(wire)
        except (TypeError, ValueError) as error:
            raise ManifestStorageError() from error
        full[key] = wire
    return full


def _pg_construct_legacy_arrays(session, batch_id, probe, keys):
    """Preserve old Newow SHA lists while avoiding one large JSONB client value."""
    head, presence, counts = probe[6], probe[9], probe[11]
    if (type(head) is not dict or type(presence) is not dict
            or type(counts) is not dict
            or set(presence) != LARGE_KEYS or set(counts) != LARGE_KEYS
            or any(type(presence[key]) is not bool for key in LARGE_KEYS)
            or {key for key in LARGE_KEYS if presence[key]} != keys
            or any(type(counts[key]) is not int for key in LARGE_KEYS)
            or any(not 0 <= counts[key] <= MAX_LEAVES for key in keys)
            or sum(counts[key] for key in keys) > MAX_LEGACY_TOTAL_LEAVES
            or any(counts[key] != -1 for key in LARGE_KEYS - keys)
            or probe[10] != "array"
            or (head.get("reader") == "newow_fusion_saved_sources_v2"
                and (type(head.get("source_reader")) is not str
                     or head["source_reader"] not in {
                    "newow_product_reader_v2",
                    "newow_product_reader_intraday_v3",
                    "newow_product_reader_prefix_v4",
                }))):
        raise ManifestStorageError()
    slots = {key: [None] * counts[key] for key in keys}
    seen_header = False
    seen_meta = {key: False for key in keys}
    result = session.execute(_pg_packed_rows(
        batch_id, {key: counts[key] for key in keys}, legacy_arrays=True,
    ).execution_options(stream_results=True, yield_per=128))
    try:
        for item in result:
            if item.row_kind == "header":
                if (seen_header
                        or (item.batch_id, item.stream_id, item.revision_id,
                            item.batch_kind, item.outcome, item.seq) != _identity(probe)
                        or item.server_hash != probe[7]
                        or not _same_json(item.metadata, head)
                        or not _same_json(item.presence, presence)):
                    raise ManifestStorageError()
                seen_header = True
                continue
            key = item.vector_key
            if key not in slots:
                raise ManifestStorageError()
            if item.row_kind == "vector":
                if (seen_meta[key] or item.value_type != "array"
                        or type(item.block_count) is not int
                        or item.block_count != counts[key]):
                    raise ManifestStorageError()
                seen_meta[key] = True
            elif item.row_kind == "leaf":
                ordinal = item.ordinal
                if (type(ordinal) is not int
                        or not 1 <= ordinal <= counts[key]
                        or slots[key][ordinal - 1] is not None
                        or item.value_type != "string"
                        or item.value_length != 64
                        or type(item.block) is not str
                        or _HEX_LEAF.fullmatch(item.block) is None):
                    raise ManifestStorageError()
                slots[key][ordinal - 1] = item.block
            else:
                raise ManifestStorageError()
    finally:
        result.close()
    if (not seen_header or not all(seen_meta.values())
            or any(any(value is None for value in slots[key]) for key in keys)):
        raise ManifestStorageError()
    return {**head, **slots}


def _identity(row):
    return tuple(row[:6])


def _pg_actual_manifest(session, batch_id, probe):
    packed = _pg_construct_packed(session, batch_id, probe)
    if packed is not None:
        return packed
    full = _pg_full(session, batch_id)
    if (full is None or _identity(full) != _identity(probe)
            or full[7] != probe[7] or not isinstance(full[6], dict)
            or REF in full[6]):
        raise ManifestStorageError()
    return full[6]


def _verified_anchor(session, identity, probe, scope, *, allow_other=False):
    if (_identity(probe) != identity
            or identity[3] not in {"seed_seal", "calculation"}
            or identity[4] != "committed"
            or not isinstance(probe[6], dict)
            or REF in probe[6]
            or not _same_json(probe[6], _head(scope.expected))
            or not isinstance(probe[7], str) or len(probe[7]) != 64):
        raise ManifestStorageError()
    key = (session.get_bind(), *identity, probe[7])
    if (scope.anchor_key is not None
            and scope.anchor_key[:2] == key[:2]
            and scope.anchor_key != key):
        raise ManifestStorageError()
    if key == scope.anchor_key:
        return scope.expected
    if scope.packed_vectors is not None:
        if _pg_compare_packed(session, identity[0], probe, scope):
            scope.anchor_key = key
            return scope.expected
        if not allow_other:
            raise ManifestStorageError()
    actual = _pg_actual_manifest(session, identity[0], probe)
    if manifest_sha256(actual) != scope.digest or actual != scope.expected:
        if allow_other:
            return actual
        raise ManifestStorageError()
    scope.anchor_key = key
    scope.anchor_chain = None
    return scope.expected


def _verified_delta_anchor(session, probe, scope, *, allow_other=False):
    identity = _identity(probe)
    if (identity[3] != "calculation" or identity[4] != "committed"
            or type(identity[5]) is not int or type(probe[6]) is not dict
            or DELTA_REF not in probe[6]
            or not isinstance(probe[7], str) or len(probe[7]) != 64):
        raise ManifestStorageError()
    key = (session.get_bind(), *identity, probe[7])
    if (scope.anchor_key is not None
            and scope.anchor_key[:2] == key[:2]
            and scope.anchor_key != key):
        raise ManifestStorageError()
    if key == scope.anchor_key:
        if (scope.anchor_chain is None or not scope.anchor_chain
                or scope.anchor_chain[0] != (identity, probe[7])):
            raise ManifestStorageError()
        for saved_identity, saved_hash in scope.anchor_chain[1:]:
            current = _pg_probe(session, saved_identity[0])
            if (current is None or _identity(current) != saved_identity
                    or current[7] != saved_hash):
                raise ManifestStorageError()
        return scope.expected
    chain = []
    full, _ = _pg_resolve_any_with_depth(
        session, _pg_batch_from_probe(probe), probe=probe, chain=chain,
    )
    if manifest_sha256(full) != scope.digest or not _same_json(full, scope.expected):
        if allow_other:
            return full
        raise ManifestStorageError()
    scope.anchor_key = key
    scope.anchor_chain = tuple(chain)
    return scope.expected


def _pg_resolve(session, batch, scope):
    if manifest_sha256(scope.expected) != scope.digest:
        raise ManifestStorageError()
    probe = _pg_probe(session, batch.batch_id)
    if probe is None or _identity(probe) != (
        batch.batch_id, batch.stream_id, batch.revision_id,
        batch.kind, batch.outcome, batch.seq,
    ) or not isinstance(probe[6], dict):
        raise ManifestStorageError()
    if (scope.anchor_key is not None
            and scope.anchor_key[:2] == (session.get_bind(), batch.batch_id)
            and scope.anchor_key != (session.get_bind(), *_identity(probe), probe[7])):
        raise ManifestStorageError()
    head = probe[6]
    if DELTA_REF in head:
        full = _verified_delta_anchor(session, probe, scope, allow_other=True)
        scope.resolved = (
            session.get_bind(), batch.batch_id, batch.batch_id,
            _identity(probe), probe[6], probe[7],
        )
        return full
    if REF not in head:
        # A prior revision may have a different digest during append validation.
        if not _same_json(head, _head(scope.expected)):
            result = _pg_actual_manifest(session, batch.batch_id, probe)
            scope.resolved = (
                session.get_bind(), batch.batch_id, batch.batch_id,
                _identity(probe), probe[6], probe[7],
            )
            return result
        result = _verified_anchor(session, _identity(probe), probe, scope,
                                  allow_other=True)
        scope.resolved = (
            session.get_bind(), batch.batch_id, batch.batch_id,
            _identity(probe), probe[6], probe[7],
        )
        return result
    ref = head[REF]
    if (not isinstance(ref, dict) or set(ref) != {"batch_id", "sha256"}
            or not isinstance(ref["batch_id"], str)
            or not 0 < len(ref["batch_id"]) <= 96
            or not isinstance(ref["sha256"], str)
            or len(ref["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in ref["sha256"])
            or batch.kind != "calculation" or type(batch.seq) is not int
            or probe[8] or any(probe[9].values())):
        raise ManifestStorageError()
    if ref["sha256"] != scope.digest:
        # The append path needs the prior manifest, not the new plan manifest.
        result = _pg_resolve_any(session, batch, probe=probe)
        scope.resolved = (
            session.get_bind(), batch.batch_id, ref["batch_id"],
            _identity(probe), probe[6], probe[7],
        )
        return result
    if not _same_json({key: value for key, value in head.items() if key != REF},
                      _head(scope.expected)):
        raise ManifestStorageError()
    anchor_probe = _pg_probe(session, ref["batch_id"])
    if anchor_probe is None:
        raise ManifestStorageError()
    anchor_identity = _identity(anchor_probe)
    if (anchor_identity[1] != batch.stream_id
            or anchor_identity[2] != batch.revision_id
            or type(anchor_identity[5]) is not int
            or not 0 < anchor_identity[5] < batch.seq
            or not isinstance(anchor_probe[6], dict)):
        raise ManifestStorageError()
    if DELTA_REF in anchor_probe[6]:
        result = _verified_delta_anchor(session, anchor_probe, scope)
        scope.resolved = (
            session.get_bind(), batch.batch_id, ref["batch_id"],
            _identity(probe), probe[6], probe[7],
        )
        return result
    result = _verified_anchor(session, anchor_identity, anchor_probe, scope)
    scope.resolved = (
        session.get_bind(), batch.batch_id, ref["batch_id"],
        _identity(probe), probe[6], probe[7],
    )
    return result


def _pg_resolve_any(session, batch, *, probe=None):
    full, _ = _pg_resolve_any_with_depth(session, batch, probe=probe)
    return full


def _pg_batch_from_probe(probe):
    return SimpleNamespace(batch_id=probe[0], stream_id=probe[1],
                           revision_id=probe[2], kind=probe[3],
                           outcome=probe[4], seq=probe[5])


def _pg_resolve_any_with_depth(session, batch, *, probe=None, hops=0, chain=None):
    if hops > MAX_DELTA_DEPTH + 2:
        raise ManifestStorageError()
    probe = _pg_probe(session, batch.batch_id) if probe is None else probe
    if (probe is None or _identity(probe) != (
            batch.batch_id, batch.stream_id, batch.revision_id,
            batch.kind, batch.outcome, batch.seq,
        ) or not isinstance(probe[6], dict)):
        raise ManifestStorageError()
    if chain is not None:
        chain.append((_identity(probe), probe[7]))
    head = probe[6]
    if REF not in head and DELTA_REF not in head:
        return _pg_actual_manifest(session, batch.batch_id, probe), 0
    if (REF in head and DELTA_REF in head) or any(probe[9].values()) or batch.kind != "calculation":
        raise ManifestStorageError()
    if DELTA_REF in head:
        ref = head[DELTA_REF]
        if (type(ref) is not dict
                or type(ref.get("parent_batch_id")) is not str
                or not 0 < len(ref["parent_batch_id"]) <= 96):
            raise ManifestStorageError()
        parent_id = ref["parent_batch_id"]
    else:
        ref = head[REF]
        if (type(ref) is not dict
                or type(ref.get("batch_id")) is not str
                or not 0 < len(ref["batch_id"]) <= 96):
            raise ManifestStorageError()
        parent_id = ref["batch_id"]
    anchor = _pg_probe(session, parent_id)
    if (anchor is None or anchor[1] != batch.stream_id
            or anchor[2] != batch.revision_id
            or anchor[3] not in {"seed_seal", "calculation"}
            or anchor[4] != "committed"
            or type(anchor[5]) is not int or not 0 < anchor[5] < batch.seq
            or not isinstance(anchor[6], dict)):
        raise ManifestStorageError()
    if REF in anchor[6]:
        raise ManifestStorageError()
    parent, parent_depth = _pg_resolve_any_with_depth(
        session, _pg_batch_from_probe(anchor), probe=anchor, hops=hops + 1,
        chain=chain,
    )
    if DELTA_REF in head:
        return _delta_full(head, parent, parent_id=parent_id,
                           parent_depth=parent_depth)
    ref = head[REF]
    if (not isinstance(ref, dict) or set(ref) != {"batch_id", "sha256"}
            or not isinstance(ref["batch_id"], str)
            or not 0 < len(ref["batch_id"]) <= 96
            or not isinstance(ref["sha256"], str)
            or len(ref["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in ref["sha256"])
            or batch.kind != "calculation" or type(batch.seq) is not int):
        raise ManifestStorageError()
    if (manifest_sha256(parent) != ref["sha256"]
            or not _same_json({key: value for key, value in head.items() if key != REF},
                              _head(parent))):
        raise ManifestStorageError()
    return parent, parent_depth


def resolve_manifest(session, batch):
    scope = _pg_scope(session)
    if scope is not None:
        try:
            return _pg_resolve(session, batch, scope)
        except BaseException:
            scope.clear()
            raise
    get_bind = getattr(session, "get_bind", None)
    if callable(get_bind) and get_bind().dialect.name == "postgresql":
        return _pg_resolve_any(session, batch)
    return _resolve_uncached(session, batch)


def _resolve_uncached(session, batch):
    full, _ = _resolve_uncached_with_depth(session, batch)
    return full


def _resolve_uncached_with_depth(session, batch, *, hops=0):
    if hops > MAX_DELTA_DEPTH + 2:
        raise ManifestStorageError()
    raw = batch.dependency_manifest
    if not isinstance(raw, dict):
        raise ManifestStorageError()
    if REF not in raw and DELTA_REF not in raw:
        return raw, 0
    if (REF in raw and DELTA_REF in raw) or set(raw).intersection(LARGE_KEYS) or batch.kind != "calculation" or type(batch.seq) is not int:
        raise ManifestStorageError()
    ref = raw[REF] if REF in raw else raw[DELTA_REF]
    parent_id = (ref.get("batch_id") if REF in raw else ref.get("parent_batch_id")) if type(ref) is dict else None
    if type(parent_id) is not str or not 0 < len(parent_id) <= 96:
        raise ManifestStorageError()
    anchor = session.get(ReferenceBatch, parent_id)
    if (
        anchor is None
        or anchor.stream_id != batch.stream_id
        or anchor.revision_id != batch.revision_id
        or anchor.kind not in {"seed_seal", "calculation"}
        or anchor.outcome != "committed"
        or type(anchor.seq) is not int
        or not 0 < anchor.seq < batch.seq
        or not isinstance(anchor.dependency_manifest, dict)
    ):
        raise ManifestStorageError()
    if REF in anchor.dependency_manifest:
        raise ManifestStorageError()
    full, parent_depth = _resolve_uncached_with_depth(session, anchor, hops=hops + 1)
    if DELTA_REF in raw:
        return _delta_full(raw, full, parent_id=parent_id,
                           parent_depth=parent_depth)
    if (type(ref) is not dict or set(ref) != {"batch_id", "sha256"}
            or not _sha256_text(ref["sha256"])
            or manifest_sha256(full) != ref["sha256"] or not _same_json(
                {key: value for key, value in raw.items() if key != REF}, _head(full),
            )
    ):
        raise ManifestStorageError()
    return full, parent_depth


def _proof_anchor(session, prior_batch, scope):
    if scope is not None:
        saved = scope.resolved
        probe = _pg_probe(session, prior_batch.batch_id)
        if (saved is None or probe is None
                or saved[:2] != (session.get_bind(), prior_batch.batch_id)
                or saved[3] != _identity(probe)
                or not _same_json(saved[4], probe[6])
                or saved[5] != probe[7]):
            raise ManifestStorageError()
        anchor_id = saved[2]
    else:
        get_bind = getattr(session, "get_bind", None)
        if callable(get_bind) and get_bind().dialect.name == "postgresql":
            probe = _pg_probe(session, prior_batch.batch_id)
            if (probe is None or _identity(probe) != (
                    prior_batch.batch_id, prior_batch.stream_id,
                    prior_batch.revision_id, prior_batch.kind,
                    prior_batch.outcome, prior_batch.seq)):
                raise ManifestStorageError()
            raw = probe[6]
        else:
            raw = prior_batch.dependency_manifest
        if type(raw) is not dict:
            raise ManifestStorageError()
        anchor_id = raw[REF]["batch_id"] if REF in raw else prior_batch.batch_id
    if type(anchor_id) is not str or not 0 < len(anchor_id) <= 96:
        raise ManifestStorageError()
    return anchor_id


def _proof_anchor_depth(session, prior_batch, anchor_id):
    get_bind = getattr(session, "get_bind", None)
    if callable(get_bind) and get_bind().dialect.name == "postgresql":
        probe = _pg_probe(session, anchor_id)
        if probe is None:
            raise ManifestStorageError()
        identity = _identity(probe)
        raw = probe[6]
    else:
        anchor = session.get(ReferenceBatch, anchor_id)
        if anchor is None:
            raise ManifestStorageError()
        identity = (anchor.batch_id, anchor.stream_id, anchor.revision_id,
                    anchor.kind, anchor.outcome, anchor.seq)
        raw = anchor.dependency_manifest
    if (identity[1:3] != (prior_batch.stream_id, prior_batch.revision_id)
            or identity[3] not in {"seed_seal", "calculation"}
            or identity[4] != "committed"
            or type(identity[5]) is not int
            or not 0 < identity[5] <= prior_batch.seq
            or type(raw) is not dict or REF in raw):
        raise ManifestStorageError()
    if DELTA_REF not in raw:
        return 0
    ref = raw[DELTA_REF]
    if (type(ref) is not dict or type(ref.get("depth")) is not int
            or not 1 <= ref["depth"] <= MAX_DELTA_DEPTH):
        raise ManifestStorageError()
    return ref["depth"]


def _delta_candidate(prior, full, *, parent_id, prior_digest, digest, depth):
    if (not _v5_manifest(prior) or not _v5_manifest(full)
            or depth >= MAX_DELTA_DEPTH
            or set(prior).intersection({REF, DELTA_REF})
            or set(full).intersection({REF, DELTA_REF})):
        return None
    keys = {key for key in LARGE_KEYS if key in prior}
    if keys != {key for key in LARGE_KEYS if key in full} or "input_fingerprints" not in keys:
        return None
    vectors = {}
    try:
        for key in sorted(keys):
            old = PackedFingerprints(prior[key])
            new = PackedFingerprints(full[key])
            if not old.is_prefix_of(new):
                return None
            from_block = old.leaf_count // BLOCK_SIZE
            vectors[key] = {
                "old_count": old.leaf_count, "new_count": new.leaf_count,
                "from_block": from_block,
                "blocks": full[key]["blocks"][from_block:],
            }
    except (TypeError, ValueError):
        return None
    ref = {"parent_batch_id": parent_id, "parent_sha256": prior_digest,
           "sha256": digest, "depth": depth + 1, "vectors": vectors}
    if not _bounded_json_size(ref, MAX_DELTA_BYTES):
        return None
    raw = {**_head(full), DELTA_REF: ref}
    if (not _bounded_json_size(raw, MAX_HEAD_BYTES)
            or _bounded_json_size(full, _json_size(raw))):
        return None
    return raw


def store_manifest(session, prior_batch, full, digest, *, dependency_advance=None):
    """Store a validated historical calculation without repeating its large arrays."""
    if REF in full or DELTA_REF in full:
        raise ManifestStorageError()
    scope = _pg_scope(session)
    try:
        if scope is not None and full is scope.expected:
            # Resolve first: every commit still rehashes the mutable plan object
            # and rechecks the current PostgreSQL anchor/ref bytes.
            prior = resolve_manifest(session, prior_batch)
            member_count = scope.large_member_count
            prior_digest = (scope.digest if prior is scope.expected
                            else manifest_sha256(prior))
        else:
            member_count = sum(
                fingerprint_count(full[key]) for key in LARGE_KEYS if key in full
            )
            if member_count * 64 < MIN_BYTES:
                return full
            prior = resolve_manifest(session, prior_batch)
            prior_digest = manifest_sha256(prior)
        # Fingerprints are fixed-width hex, so this bound avoids serializing a
        # small manifest only to discover it did not need indirection.
        if member_count * 64 < MIN_BYTES:
            return full
        if prior_digest != digest:
            if (not isinstance(dependency_advance, DependencyAdvance)
                    or dependency_advance.expected_prior_digest != prior_digest
                    or dependency_advance.new_digest != digest
                    or dependency_advance.new_manifest is not full):
                return full
            try:
                validate_dependency_advance(prior, dependency_advance)
            except ValueError:
                return full
            anchor_id = _proof_anchor(session, prior_batch, scope)
            depth = _proof_anchor_depth(session, prior_batch, anchor_id)
            candidate = _delta_candidate(
                prior, full, parent_id=anchor_id, prior_digest=prior_digest,
                digest=digest, depth=depth,
            )
            return candidate if candidate is not None else full
        anchor_id = _proof_anchor(session, prior_batch, scope)
        return {**_head(full), REF: {"batch_id": anchor_id, "sha256": digest}}
    except BaseException:
        if scope is not None:
            scope.clear()
        raise
