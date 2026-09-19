import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import pytest

from app.market_data.catalog import CatalogPartition
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.market_data.subing_d1_quality_candidates import (
    CandidatePreparationError,
    SourceProof,
    build_candidate_manifest,
    build_source_proof_index,
    prepare_replacement_candidate,
    verify_plan_input_files,
)


def _bar(day: int, close: str) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=datetime(2026, 9, day, 7, tzinfo=UTC),
        trading_day=date(2026, 9, day),
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1"),
        turnover=Decimal("2"),
        open_interest=Decimal("3"),
    )


def _fixture(tmp_path):
    key = DatasetKey(DatasetKind.CONTRACT, "oi", "OI2609", BarFrequency.D1)
    old_root = tmp_path / "old"
    old_root.mkdir()
    old = CanonicalMonthlyStore(old_root).publish(PublishRequest(
        key, 2026, 9, (_bar(1, "10"), _bar(2, "0")),
        (_bar(1, "10").bar_end, _bar(2, "0").bar_end),
    ))
    partition = CatalogPartition(
        dataset=key,
        year=2026,
        month=9,
        coverage_start=old.coverage_start,
        coverage_end=old.coverage_end,
        file_path=old.parquet_path,
        row_count=old.row_count,
    )
    target = {
        "symbol": "oi",
        "contract": "OI2609",
        "month": "2026-09",
        "partition_id": 7,
        "old_file_uri": old.parquet_path.relative_to(old_root).as_posix(),
        "old_file_sha256": sha256(old.parquet_path.read_bytes()).hexdigest(),
        "old_source_quality_sha256": None,
        "affected_dates": ["2026-09-02"],
        "operation": "REPLACE_EXISTING_PARTITION",
    }
    return old_root, partition, target


def test_prepare_replacement_candidate_moves_nonpositive_bar_to_quality_fact(tmp_path):
    old_root, partition, target = _fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    proof = SourceProof(
        request_sha256="a" * 64,
        response_sha256="b" * 64,
        observed_at=datetime(2026, 9, 19, 4, tzinfo=UTC),
        classification="NONPOSITIVE_CLOSE_SOURCE_FACT",
        source_values={
            "open": Decimal("0"), "high": Decimal("0"), "low": Decimal("0"),
            "close": Decimal("0"), "volume": Decimal("1"), "turnover": Decimal("2"),
            "open_interest": Decimal("3"),
        },
    )

    prepared = prepare_replacement_candidate(
        target=target,
        partition=partition,
        active_root=old_root,
        candidate_root=candidate_root,
        proofs={("oi", "OI2609", date(2026, 9, 2)): proof},
    )

    manifest = prepared.manifest
    assert manifest["state"] == "CANDIDATE_FROZEN"
    assert manifest["row_count"] == 1
    assert manifest["source_quality_count"] == 1
    assert len(manifest["candidate_file_sha256"]) == 64
    assert len(manifest["candidate_content_sha256"]) == 64
    assert len(manifest["candidate_source_quality_sha256"]) == 64
    assert len(manifest["candidate_quality_sidecar_sha256"]) == 64
    assert (candidate_root / manifest["candidate_quality_sidecar_uri"]).is_file()
    candidate = CatalogPartition(
        dataset=partition.dataset,
        year=partition.year,
        month=partition.month,
        coverage_start=datetime.fromisoformat(manifest["coverage_start"]),
        coverage_end=datetime.fromisoformat(manifest["coverage_end"]),
        file_path=candidate_root / manifest["candidate_file_uri"],
        row_count=manifest["row_count"],
        source_coverage_start=datetime.fromisoformat(manifest["source_coverage_start"]),
        source_coverage_end=datetime.fromisoformat(manifest["source_coverage_end"]),
        source_quality=prepared.partition.source_quality,
        source_quality_sha256=manifest["candidate_source_quality_sha256"],
    )
    bars, facts = CanonicalMonthlyStore(candidate_root).read_catalog_partition_quality(candidate)
    assert [bar.trading_day for bar in bars] == [date(2026, 9, 1)]
    assert [fact.trading_day for fact in facts] == [date(2026, 9, 2)]


def test_prepare_replacement_candidate_rejects_old_file_hash_drift(tmp_path):
    old_root, partition, target = _fixture(tmp_path)
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    target["old_file_sha256"] = "0" * 64

    with pytest.raises(CandidatePreparationError, match="OLD_FILE_HASH_DRIFT"):
        prepare_replacement_candidate(
            target=target,
            partition=partition,
            active_root=old_root,
            candidate_root=candidate_root,
            proofs={},
        )


def test_source_proof_index_verifies_saved_raw_bytes_and_rows(tmp_path):
    artifact = tmp_path / "batch/source-response-0001.json"
    artifact.parent.mkdir()
    raw = {
        "schema_version": 1,
        "request": {
            "method": "futures.get_exchange_daily",
            "contract": "OI2611",
            "start": "2025-11-17",
            "end": "2025-11-28",
            "expected_dates": ["2025-11-17"],
        },
        "rows": [{
            "date": "2025-11-17", "open": "0", "high": "0", "low": "0",
            "close": "0", "volume": "1", "total_turnover": "2", "open_interest": "3",
        }],
    }
    artifact.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n")
    digest = sha256(artifact.read_bytes()).hexdigest()
    refresh = {
        "items": [{
            "symbol": "oi",
            "saved_raw_artifacts": [{
                "artifact": "batch/source-response-0001.json",
                "artifact_sha256": digest,
                "journal_payload_sha256": digest,
                "journal_matches_file": True,
                "request": raw["request"],
                "proved_dates": ["2025-11-17"],
            }],
        }],
    }

    proofs = build_source_proof_index(refresh, raw_evidence_root=tmp_path)

    saved = proofs[("oi", "OI2611", date(2025, 11, 17))]
    assert saved.response_sha256 == digest
    assert len(saved.request_sha256) == 64
    assert saved.classification == "NONPOSITIVE_CLOSE_SOURCE_FACT"
    assert saved.source_values["close"] == Decimal("0")

    artifact.write_text("{}\n")
    with pytest.raises(CandidatePreparationError, match="SOURCE_RAW_HASH_MISMATCH"):
        build_source_proof_index(refresh, raw_evidence_root=tmp_path)


def test_source_proof_index_accepts_zero_ohl_positive_close_fact(tmp_path):
    artifact = tmp_path / "batch/source-response-0001.json"
    artifact.parent.mkdir()
    raw = {
        "schema_version": 1,
        "request": {
            "method": "futures.get_exchange_daily",
            "contract": "OI2611",
            "start": "2025-11-17",
            "end": "2025-11-17",
            "expected_dates": ["2025-11-17"],
        },
        "rows": [{
            "date": "2025-11-17", "open": "0", "high": "0", "low": "0",
            "close": "10", "volume": "1", "total_turnover": "2", "open_interest": "3",
        }],
    }
    artifact.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n")
    digest = sha256(artifact.read_bytes()).hexdigest()
    refresh = {
        "items": [{
            "symbol": "oi",
            "saved_raw_artifacts": [{
                "artifact": "batch/source-response-0001.json",
                "artifact_sha256": digest,
                "journal_payload_sha256": digest,
                "journal_matches_file": True,
                "request": raw["request"],
                "proved_dates": ["2025-11-17"],
            }],
        }],
    }

    proof = build_source_proof_index(refresh, raw_evidence_root=tmp_path)[
        ("oi", "OI2611", date(2025, 11, 17))
    ]

    assert proof.classification == "ZERO_OHL_POSITIVE_CLOSE_SOURCE_FACT"


def test_candidate_manifest_keeps_create_targets_blocked_without_source_bytes():
    plan = {
        "plan_sha256": "e" * 64,
        "fixed_cutoff": "2026-09-18T18:30:00+08:00",
        "target_partition_count": 3,
        "targets": [
            {"symbol": "oi", "contract": "OI2611", "month": "2025-11", "operation": "REPLACE_EXISTING_PARTITION"},
            {"symbol": "oi", "contract": "OI2609", "month": "2026-09", "operation": "CREATE_MIXED_UNION_PARTITION", "expected_endpoints_sha256": "f" * 64},
            {"symbol": "pf", "contract": "PF2609", "month": "2026-09", "operation": "CREATE_MIXED_UNION_PARTITION", "expected_endpoints_sha256": "1" * 64},
        ],
    }
    candidate = {
        "state": "CANDIDATE_FROZEN",
        "symbol": "oi",
        "contract": "OI2611",
        "month": "2025-11",
        "old_file_uri": "old.parquet",
        "old_file_sha256": "2" * 64,
        "candidate_file_uri": "new.parquet",
        "candidate_file_sha256": "3" * 64,
        "candidate_content_sha256": "4" * 64,
        "candidate_source_quality_sha256": "5" * 64,
        "candidate_quality_sidecar_uri": "quality.json",
        "candidate_quality_sidecar_sha256": "6" * 64,
        "row_count": 1,
        "source_quality_count": 1,
    }

    manifest = build_candidate_manifest(
        plan=plan,
        candidate_root="data/canonical-candidates/" + "e" * 64,
        candidates=[candidate],
    )

    assert manifest["state"] == "PARTIAL_CANDIDATES_1_OF_3"
    assert manifest["production_writes"] == manifest["provider_requests"] == 0
    assert manifest["frozen_candidate_count"] == 1
    assert manifest["blocked_target_count"] == 2
    assert {item["reason"] for item in manifest["blocked_targets"]} == {
        "SOURCE_RESPONSE_BYTES_UNAVAILABLE"
    }
    assert len(manifest["manifest_sha256"]) == 64


def test_verify_plan_input_files_requires_and_hashes_all_three_inputs(tmp_path):
    names = (
        "d1-17-source-diagnosis.json",
        "d1-17-source-evidence-refresh.json",
        "d1-17-source-verification-complete.json",
    )
    inputs = {}
    hashes = {}
    for index, name in enumerate(names):
        path = tmp_path / name
        path.write_text(f'{{"index":{index}}}\n')
        inputs[name] = path
        hashes[name] = sha256(path.read_bytes()).hexdigest()
    plan = {"input_evidence": {"impact_input_sha256": hashes}}

    verify_plan_input_files(plan, inputs)

    inputs[names[0]].write_text("{}\n")
    with pytest.raises(CandidatePreparationError, match="PLAN_EVIDENCE_HASH_MISMATCH"):
        verify_plan_input_files(plan, inputs)
    with pytest.raises(CandidatePreparationError, match="PLAN_EVIDENCE_BINDING_INVALID"):
        verify_plan_input_files(plan, {name: path for name, path in inputs.items() if name != names[0]})
