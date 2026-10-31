"""Stored page proof must survive JSON transport and reject altered bytes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json

import pytest

from app.reference_trading.page_material_storage import (
    _compress_json, _digest, _proof_hash, validate_page_material, verify_source_integrity,
)
from guiyi_quant.newow.page_performance import PAGE_PERFORMANCE_VERSION, PAGE_SOURCE_SHA256


def _proof():
    source = "a" * 64
    request = {
        "product": "jm", "frequency": "1d", "since": "2024-01-01",
        "through": "2024-02-01", "as_of": "2024-02-02T00:00:00+00:00",
    }
    source_integrity = {
        "schema": "reference_mds_source_integrity_v1",
        "source_schema": "newow_completed_source_evidence_v1",
        "request": request, "evidence_sha256": source,
    }
    binding = {
        "schema": "reference_page_material_binding_v1",
        "stream_id": "stream", "revision_id": "revision", "seq": 1,
        "manifest_sha256": "c" * 64, "source_token": "d" * 64,
        "page_version": PAGE_PERFORMANCE_VERSION,
        "page_source_sha256": PAGE_SOURCE_SHA256,
        "input_count": 1, "end_input_index": 1,
        "request": request, "cutoff": "2024-02-01T00:00:00+00:00",
        "result_trading_day": "2024-02-01",
        "input_sha256": "b" * 64,
        "source_integrity": source_integrity,
        "fusion_source_dependencies": None,
    }
    envelope = {
        "schema": "newow_page_material_envelope_v1",
        "input_sha256": binding["input_sha256"],
        "source_evidence_sha256": source,
        "material": {"page_version": PAGE_PERFORMANCE_VERSION, "segments": []},
    }
    payload, raw_size, raw_sha, compressed_size, compressed_sha = _compress_json(
        envelope, lambda: False,
    )
    proof = {
        "schema": "reference_page_material_v1",
        "binding": binding,
        "encoding": "zlib-json-base64-v1",
        "raw_size": raw_size, "raw_sha256": raw_sha,
        "compressed_size": compressed_size,
        "compressed_sha256": compressed_sha,
        "payload": payload,
    }
    return {**proof, "payload_hash": _proof_hash(proof)}, binding, envelope


def test_page_material_json_roundtrip_and_binding() -> None:
    proof, binding, envelope = _proof()
    transported = json.loads(json.dumps(proof))
    assert validate_page_material(transported, expected_binding=binding) == envelope
    with pytest.raises(ValueError, match="REFERENCE_PAGE_MATERIAL_BINDING_CONFLICT"):
        validate_page_material(transported, expected_binding={**binding, "input_sha256": "c" * 64})


def test_page_material_rejects_altered_compressed_bytes() -> None:
    proof, binding, _ = _proof()
    proof["payload"] = "A" + proof["payload"][1:]
    proof["payload_hash"] = _proof_hash(proof)
    with pytest.raises(ValueError, match="REFERENCE_PAGE_MATERIAL_DIGEST_CONFLICT"):
        validate_page_material(proof, expected_binding=binding)


def test_source_integrity_uses_original_exact_window() -> None:
    request = {
        "product": "jm", "frequency": "1d", "since": "2024-01-01",
        "through": "2024-02-01", "as_of": "2024-02-02T00:00:00+00:00",
    }
    expected = {"schema": "newow_completed_source_evidence_v1", "physical": ["frozen"]}

    class Reader:
        def historical_source_evidence(self, *, product, frequency, since, through, as_of):
            assert (product, frequency, since, through, as_of) == (
                "jm", "1d", date(2024, 1, 1), date(2024, 2, 1),
                datetime(2024, 2, 2, tzinfo=timezone.utc),
            )
            return expected

    record = {
        "schema": "reference_mds_source_integrity_v1",
        "source_schema": expected["schema"],
        "request": request, "evidence_sha256": _digest(expected),
    }
    assert verify_source_integrity(Reader(), record)
    record["evidence_sha256"] = sha256(b"different").hexdigest()
    assert not verify_source_integrity(Reader(), record)
