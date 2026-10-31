"""Bounded, revision-bound Newow page material in calculation evidence."""

from __future__ import annotations

import base64
import binascii
from datetime import date, datetime
from hashlib import sha256
import json
import tempfile
import zlib
from typing import cast

from guiyi_quant.newow.page_performance import PAGE_PERFORMANCE_VERSION, PAGE_SOURCE_SHA256


MAX_MATERIAL_BYTES = 128 * 1024 * 1024
MAX_COMPRESSED_BYTES = 48 * 1024 * 1024
_ENCODER = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                            allow_nan=False)
_DIGEST_ENCODER = json.JSONEncoder(
    sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    default=lambda item: item.isoformat() if hasattr(item, "isoformat") else str(item),
)


def _digest(value: object) -> str:
    result = sha256()
    for part in _DIGEST_ENCODER.iterencode(value):
        result.update(part.encode("utf-8"))
    return result.hexdigest()


def _proof_hash(proof: dict[str, object]) -> str:
    """Hash metadata and the whole base64 payload without a giant JSON copy."""
    digest = sha256()
    metadata = {key: value for key, value in proof.items()
                if key not in ("payload", "payload_hash")}
    digest.update(_digest(metadata).encode("ascii"))
    payload = proof["payload"]
    if not isinstance(payload, str) or not payload.isascii():
        raise ValueError("REFERENCE_PAGE_MATERIAL_INVALID")
    for start in range(0, len(payload), 65536):
        digest.update(payload[start:start + 65536].encode("ascii"))
    return digest.hexdigest()


def _reject_json_constant(_value: str):
    raise ValueError("REFERENCE_PAGE_MATERIAL_INVALID")


def _request_wire(request) -> dict[str, str]:
    return {
        "product": request.identity.product.lower(),
        "frequency": request.identity.frequency,
        "since": request.since.isoformat(),
        "through": request.through.isoformat(),
        "as_of": request.as_of.isoformat(),
    }


def input_integrity_binding(snapshot, request, *, stream_id: str, revision_id: str,
                            seq: int, manifest_sha256: str) -> dict[str, object] | None:
    """Bind each committed calculation seq to the exact frozen MDS source."""
    if snapshot.source_integrity is None:
        return None
    binding = {
        "schema": "reference_input_integrity_v1",
        "stream_id": stream_id, "revision_id": revision_id, "seq": seq,
        "manifest_sha256": manifest_sha256,
        "source_token": snapshot.source_token,
        "source_integrity": snapshot.source_integrity,
        "request": _request_wire(request),
    }
    return {**binding, "binding_sha256": _digest(binding)}


def validate_input_integrity(value: object, *, expected_binding: dict[str, object]):
    """Check a committed seq's source binding against independently read facts."""
    if (not isinstance(value, dict)
        or set(value) != {
            "schema", "stream_id", "revision_id", "seq", "manifest_sha256",
            "source_token", "source_integrity", "request", "binding_sha256",
        }
        or value["schema"] != "reference_input_integrity_v1"
        or type(value["seq"]) is not int or value["seq"] < 1
        or not isinstance(expected_binding, dict)
        or value["binding_sha256"] != _digest({
            key: part for key, part in value.items() if key != "binding_sha256"
        })
        or {key: part for key, part in value.items() if key != "binding_sha256"}
        != expected_binding):
        raise ValueError("REFERENCE_INPUT_INTEGRITY_CONFLICT")
    _validate_source_record(value["source_integrity"])
    if value["request"] != value["source_integrity"]["request"]:
        raise ValueError("REFERENCE_INPUT_INTEGRITY_CONFLICT")
    return value["source_integrity"]


def _material_binding(snapshot, request, *, stream_id: str, revision_id: str,
                      seq: int, manifest_sha256: str, end_input_index: int,
                      input_sha256: str) -> dict[str, object]:
    dependencies = snapshot.dependency_manifest.get("source_dependencies")
    return {
        "schema": "reference_page_material_binding_v1",
        "stream_id": stream_id, "revision_id": revision_id, "seq": seq,
        "manifest_sha256": manifest_sha256,
        "source_token": snapshot.source_token,
        "end_input_index": end_input_index,
        "input_count": len(snapshot.bars),
        "request": _request_wire(request),
        "cutoff": snapshot.projection_context.resolved.cutoff.isoformat(),
        "result_trading_day": snapshot.projection_context.resolved.actual_through.isoformat(),
        "page_version": PAGE_PERFORMANCE_VERSION,
        "page_source_sha256": PAGE_SOURCE_SHA256,
        "input_sha256": input_sha256,
        "source_integrity": snapshot.source_integrity,
        "fusion_source_dependencies": dependencies,
    }


def _compress_json(value: object, cancelled) -> tuple[str, int, str, int, str]:
    compressor = zlib.compressobj(level=6)
    raw_hash = sha256()
    compressed_hash = sha256()
    compressed = bytearray()
    raw_size = 0
    for part in _ENCODER.iterencode(value):
        if cancelled():
            raise ValueError("REFERENCE_PAGE_MATERIAL_INTERRUPTED")
        chunk = part.encode("utf-8")
        raw_size += len(chunk)
        if raw_size > MAX_MATERIAL_BYTES:
            raise ValueError("REFERENCE_PAGE_MATERIAL_LIMIT_EXCEEDED")
        raw_hash.update(chunk)
        packed = compressor.compress(chunk)
        if packed:
            compressed.extend(packed)
            compressed_hash.update(packed)
        if len(compressed) > MAX_COMPRESSED_BYTES:
            raise ValueError("REFERENCE_PAGE_MATERIAL_LIMIT_EXCEEDED")
    tail = compressor.flush()
    compressed.extend(tail)
    compressed_hash.update(tail)
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise ValueError("REFERENCE_PAGE_MATERIAL_LIMIT_EXCEEDED")
    return (base64.b64encode(compressed).decode("ascii"), raw_size,
            raw_hash.hexdigest(), len(compressed), compressed_hash.hexdigest())


def _fusion_replays(bars, cancelled):
    from types import SimpleNamespace
    from guiyi_quant.newow.product_contracts import ProductStrategy

    def actions_for(strategy):
        for index, item in enumerate(bars):
            if index % 256 == 0 and cancelled():
                raise ValueError("REFERENCE_PAGE_MATERIAL_INTERRUPTED")
            if item.strategy_input:
                for action in item.payload.source_actions:
                    if action.identity.strategy is strategy:
                        yield action

    return {
        strategy: SimpleNamespace(actions=actions_for(strategy))
        for strategy in (ProductStrategy.TREND, ProductStrategy.OSCILLATION)
    }


def build_final_batch_material(snapshot, request, *, stream_id: str,
                               revision_id: str, seq: int, manifest_sha256: str,
                               end_input_index: int, cancelled=lambda: False):
    """Create both page modes before the final calculation commit only."""
    context = snapshot.projection_context
    if context is None:
        return None
    if end_input_index != len(snapshot.bars):
        raise ValueError("REFERENCE_PAGE_MATERIAL_POSITION_CONFLICT")
    if cancelled():
        raise ValueError("REFERENCE_PAGE_MATERIAL_INTERRUPTED")
    from app.market_data.newow.page_performance_adapter import build_page_material

    fusion = request.identity.strategy_code.replace("-", "_") == "newow_dual_fusion"
    envelope = build_page_material(
        context.read_view(snapshot.bars), context.page_identity, context.resolved,
        fusion=fusion, replays=_fusion_replays(snapshot.bars, cancelled) if fusion else None,
        cancelled=cancelled,
    )
    if envelope.get("source_evidence_sha256") != snapshot.source_integrity["evidence_sha256"]:
        raise ValueError("REFERENCE_PAGE_MATERIAL_SOURCE_CONFLICT")
    binding = _material_binding(
        snapshot, request, stream_id=stream_id, revision_id=revision_id,
        seq=seq, manifest_sha256=manifest_sha256,
        end_input_index=end_input_index, input_sha256=envelope["input_sha256"],
    )
    payload, raw_size, raw_sha, compressed_size, compressed_sha = _compress_json(
        envelope, cancelled,
    )
    if cancelled():
        raise ValueError("REFERENCE_PAGE_MATERIAL_INTERRUPTED")
    proof = {
        "schema": "reference_page_material_v1",
        "binding": binding,
        "encoding": "zlib-json-base64-v1",
        "raw_size": raw_size, "raw_sha256": raw_sha,
        "compressed_size": compressed_size, "compressed_sha256": compressed_sha,
        "payload": payload,
    }
    return {**proof, "payload_hash": _proof_hash(proof)}


def validate_page_material(value: object, *, expected_binding: dict[str, object]):
    """Validate stored proof and decode an adapter envelope with bounded memory."""
    if not isinstance(value, dict) or set(value) != {
        "schema", "binding", "encoding", "raw_size", "raw_sha256",
        "compressed_size", "compressed_sha256", "payload", "payload_hash",
    } or value["schema"] != "reference_page_material_v1" or value["encoding"] != "zlib-json-base64-v1":
        raise ValueError("REFERENCE_PAGE_MATERIAL_INVALID")
    binding = value["binding"]
    if (not isinstance(binding, dict)
        or set(binding) != {
            "schema", "stream_id", "revision_id", "seq", "manifest_sha256",
            "source_token", "end_input_index", "input_count", "request", "cutoff",
            "result_trading_day", "page_version", "page_source_sha256",
            "input_sha256", "source_integrity", "fusion_source_dependencies",
        }
        or binding.get("schema") != "reference_page_material_binding_v1"
        or binding.get("page_version") != PAGE_PERFORMANCE_VERSION
        or binding.get("page_source_sha256") != PAGE_SOURCE_SHA256
        or type(binding.get("input_count")) is not int
        or type(binding.get("seq")) is not int or binding["seq"] < 1
        or binding["input_count"] < 1
        or binding.get("end_input_index") != binding.get("input_count")
        or binding != expected_binding
        or value["payload_hash"] != _proof_hash(value)):
        raise ValueError("REFERENCE_PAGE_MATERIAL_BINDING_CONFLICT")
    try:
        source_integrity = binding["source_integrity"]
        if not isinstance(source_integrity, dict):
            raise ValueError("REFERENCE_PAGE_MATERIAL_BINDING_CONFLICT")
        source_request = _validate_source_record(source_integrity)
        cutoff_text = binding["cutoff"]
        result_day_text = binding["result_trading_day"]
        if not isinstance(cutoff_text, str) or not isinstance(result_day_text, str):
            raise ValueError("REFERENCE_PAGE_MATERIAL_BINDING_CONFLICT")
        cutoff = datetime.fromisoformat(cutoff_text)
        date.fromisoformat(result_day_text)
        if (binding["request"] != source_request or cutoff.tzinfo is None
            or cutoff.utcoffset() is None
            or cutoff > datetime.fromisoformat(source_request["as_of"])):
            raise ValueError("REFERENCE_PAGE_MATERIAL_BINDING_CONFLICT")
    except (TypeError, ValueError) as error:
        raise ValueError("REFERENCE_PAGE_MATERIAL_BINDING_CONFLICT") from error
    if (type(value["raw_size"]) is not int or not 0 < value["raw_size"] <= MAX_MATERIAL_BYTES
        or type(value["compressed_size"]) is not int
        or not 0 < value["compressed_size"] <= MAX_COMPRESSED_BYTES
        or not isinstance(value["payload"], str)
        or len(value["payload"]) > 4 * ((MAX_COMPRESSED_BYTES + 2) // 3)):
        raise ValueError("REFERENCE_PAGE_MATERIAL_LIMIT_EXCEEDED")
    try:
        compressed = base64.b64decode(value["payload"], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("REFERENCE_PAGE_MATERIAL_INVALID") from error
    if (len(compressed) != value["compressed_size"]
        or sha256(compressed).hexdigest() != value["compressed_sha256"]):
        raise ValueError("REFERENCE_PAGE_MATERIAL_DIGEST_CONFLICT")
    decompressor = zlib.decompressobj()
    raw_hash = sha256()
    raw_size = 0
    try:
        with tempfile.TemporaryFile(mode="w+b") as output:
            for start in range(0, len(compressed), 65536):
                pending = compressed[start:start + 65536]
                while pending:
                    chunk = decompressor.decompress(
                        pending, min(65536, MAX_MATERIAL_BYTES - raw_size + 1),
                    )
                    pending = decompressor.unconsumed_tail
                    raw_size += len(chunk)
                    if raw_size > MAX_MATERIAL_BYTES:
                        raise ValueError("REFERENCE_PAGE_MATERIAL_LIMIT_EXCEEDED")
                    raw_hash.update(chunk)
                    output.write(chunk)
            tail = decompressor.flush(MAX_MATERIAL_BYTES - raw_size + 1)
            raw_size += len(tail)
            if raw_size > MAX_MATERIAL_BYTES:
                raise ValueError("REFERENCE_PAGE_MATERIAL_LIMIT_EXCEEDED")
            raw_hash.update(tail)
            output.write(tail)
            if (not decompressor.eof or decompressor.unused_data or raw_size != value["raw_size"]
                or raw_hash.hexdigest() != value["raw_sha256"]):
                raise ValueError("REFERENCE_PAGE_MATERIAL_DIGEST_CONFLICT")
            output.seek(0)
            envelope = json.load(output, parse_constant=_reject_json_constant)
    except (zlib.error, UnicodeError, json.JSONDecodeError, OSError) as error:
        raise ValueError("REFERENCE_PAGE_MATERIAL_INVALID") from error
    if (not isinstance(envelope, dict)
        or envelope.get("schema") != "newow_page_material_envelope_v1"
        or envelope.get("input_sha256") != binding.get("input_sha256")
        or envelope.get("source_evidence_sha256") != source_integrity.get("evidence_sha256")
        or not isinstance(envelope.get("material"), dict)
        or envelope["material"].get("page_version") != PAGE_PERFORMANCE_VERSION):
        raise ValueError("REFERENCE_PAGE_MATERIAL_INVALID")
    return envelope


def _validate_source_record(source_integrity: object) -> dict[str, str]:
    if (not isinstance(source_integrity, dict)
        or set(source_integrity) != {"schema", "source_schema", "request", "evidence_sha256"}
        or source_integrity["schema"] != "reference_mds_source_integrity_v1"
        or source_integrity["source_schema"] not in {
            "newow_completed_source_evidence_v1", "newow_intraday_source_evidence_v1",
        }
        or not isinstance(source_integrity["evidence_sha256"], str)
        or len(source_integrity["evidence_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in source_integrity["evidence_sha256"])):
        raise ValueError("REFERENCE_SOURCE_INTEGRITY_INVALID")
    request = source_integrity["request"]
    if not isinstance(request, dict) or set(request) != {
        "product", "frequency", "since", "through", "as_of",
    }:
        raise ValueError("REFERENCE_SOURCE_INTEGRITY_INVALID")
    try:
        if any(not isinstance(request[name], str) for name in request):
            raise ValueError("REFERENCE_SOURCE_INTEGRITY_INVALID")
        if (not isinstance(request["product"], str) or not request["product"].isalpha()
            or request["product"] != request["product"].lower()
            or request["frequency"] not in {"1m", "5m", "15m", "30m", "60m", "1d", "1w"}):
            raise ValueError("REFERENCE_SOURCE_INTEGRITY_INVALID")
        required_schema = (
            "newow_completed_source_evidence_v1"
            if request["frequency"] in {"1d", "1w"}
            else "newow_intraday_source_evidence_v1"
        )
        if source_integrity["source_schema"] != required_schema:
            raise ValueError("REFERENCE_SOURCE_INTEGRITY_INVALID")
        since = date.fromisoformat(cast(str, request["since"]))
        through = date.fromisoformat(cast(str, request["through"]))
        as_of = datetime.fromisoformat(cast(str, request["as_of"]))
        if since > through or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("REFERENCE_SOURCE_INTEGRITY_INVALID")
    except (TypeError, ValueError) as error:
        raise ValueError("REFERENCE_SOURCE_INTEGRITY_INVALID") from error
    return cast(dict[str, str], request)


def verify_source_integrity(reader, source_integrity: object) -> bool:
    """Recheck the exact original source window without replaying price Bars."""
    request = _validate_source_record(source_integrity)
    if not isinstance(source_integrity, dict):
        raise ValueError("REFERENCE_SOURCE_INTEGRITY_INVALID")
    try:
        fresh = reader.historical_source_evidence(
            product=request["product"], frequency=request["frequency"],
            since=date.fromisoformat(request["since"]),
            through=date.fromisoformat(request["through"]),
            as_of=datetime.fromisoformat(request["as_of"]),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("REFERENCE_SOURCE_INTEGRITY_INVALID") from error
    return (isinstance(fresh, dict)
            and fresh.get("schema") == source_integrity["source_schema"]
            and _digest(fresh) == source_integrity["evidence_sha256"])
