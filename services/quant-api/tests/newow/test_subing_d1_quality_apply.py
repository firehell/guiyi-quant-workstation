from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.source_quality import NonpositiveCloseFact
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.market_data.subing_d1_quality_candidates import build_candidate_manifest
from app.market_data.subing_d1_quality_plan import canonical_json
from app.models import MarketDataset, MarketPartition


def _bar(day: int, close: str = "10") -> CanonicalBar:
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


def _quality(day: int) -> NonpositiveCloseFact:
    return NonpositiveCloseFact(
        bar_end=datetime(2026, 9, day, 7, tzinfo=UTC),
        trading_day=date(2026, 9, day),
        open=Decimal("0"),
        high=Decimal("0"),
        low=Decimal("0"),
        close=Decimal("0"),
        volume=Decimal("1"),
        turnover=Decimal("0"),
        open_interest=Decimal("3"),
        request_sha256="a" * 64,
        response_sha256="b" * 64,
        observed_at=datetime(2026, 9, 19, tzinfo=UTC),
    )


def _case(tmp_path):
    active_root = tmp_path / "active"
    candidate_root = tmp_path / "candidates"
    active_root.mkdir()
    candidate_root.mkdir()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    MarketDataset.__table__.create(engine)
    MarketPartition.__table__.create(engine)
    key = DatasetKey(DatasetKind.CONTRACT, "oi", "OI2609", BarFrequency.D1)
    old = CanonicalMonthlyStore(active_root).publish(PublishRequest(
        key, 2026, 9, (_bar(1), _bar(2)), (_bar(1).bar_end, _bar(2).bar_end),
    ))
    with Session(engine) as session:
        catalog = MarketCatalog(session, active_root)
        catalog.register_partition(old)
        session.commit()
        partition_id = session.query(MarketPartition.id).scalar()
    quality = _quality(2)
    candidate = CanonicalMonthlyStore(candidate_root).publish(PublishRequest(
        key, 2026, 9, (_bar(1),), (_bar(1).bar_end, quality.bar_end),
        nonpositive_close=(quality,),
    ))
    sidecar = candidate.parquet_path.parent / "quality.json"
    sidecar_body = {
        "schema": "canonical-source-quality-sidecar-v1",
        "source_quality": [quality.to_record()],
    }
    sidecar.write_bytes(canonical_json(sidecar_body))
    target = {
        "symbol": "oi",
        "contract": "OI2609",
        "month": "2026-09",
        "partition_id": partition_id,
        "old_file_uri": old.parquet_path.relative_to(active_root).as_posix(),
        "old_file_sha256": sha256(old.parquet_path.read_bytes()).hexdigest(),
        "old_source_quality_sha256": None,
        "affected_dates": ["2026-09-02"],
        "operation": "REPLACE_EXISTING_PARTITION",
    }
    plan = {
        "schema": "subing-d1-quality-production-plan-v1",
        "mode": "PREPARE_ONLY",
        "provider_request_budget": 0,
        "target_partition_count": 1,
        "targets": [target],
    }
    plan["plan_sha256"] = sha256(canonical_json(plan)).hexdigest()
    content_body = {
        "bars": [{
            "bar_end": _bar(1).bar_end.isoformat(),
            "trading_day": _bar(1).trading_day.isoformat(),
            "open": "10.000000000000000000",
            "high": "10.000000000000000000",
            "low": "10.000000000000000000",
            "close": "10.000000000000000000",
            "volume": "1.000000000000000000",
            "turnover": "2.000000000000000000",
            "open_interest": "3.000000000000000000",
        }],
        "source_quality": [quality.to_record()],
    }
    item = {
        "state": "CANDIDATE_FROZEN",
        "operation": "REPLACE_EXISTING_PARTITION",
        "symbol": "oi",
        "contract": "OI2609",
        "month": "2026-09",
        "partition_id": partition_id,
        "old_file_uri": target["old_file_uri"],
        "old_file_sha256": target["old_file_sha256"],
        "old_source_quality_sha256": None,
        "candidate_file_uri": candidate.parquet_path.relative_to(candidate_root).as_posix(),
        "candidate_file_sha256": sha256(candidate.parquet_path.read_bytes()).hexdigest(),
        "candidate_content_sha256": sha256(canonical_json(content_body)).hexdigest(),
        "candidate_source_quality_sha256": candidate.source_quality_sha256,
        "candidate_quality_sidecar_uri": sidecar.relative_to(candidate_root).as_posix(),
        "candidate_quality_sidecar_sha256": sha256(sidecar.read_bytes()).hexdigest(),
        "row_count": 1,
        "source_quality_count": 1,
        "affected_dates": ["2026-09-02"],
        "coverage_start": candidate.coverage_start.isoformat(),
        "coverage_end": candidate.coverage_end.isoformat(),
        "source_coverage_start": candidate.source_coverage_start.isoformat(),
        "source_coverage_end": candidate.source_coverage_end.isoformat(),
    }
    manifest = build_candidate_manifest(
        plan=plan,
        candidate_root="candidates",
        candidates=[item],
    )
    return engine, active_root, candidate_root, plan, manifest, old


def test_apply_frozen_candidates_commits_exact_pointer_and_is_idempotent(tmp_path) -> None:
    from app.market_data.subing_d1_quality_apply import (
        apply_frozen_candidates,
        preflight_frozen_candidates,
    )

    engine, active_root, candidate_root, plan, manifest, old = _case(tmp_path)
    with Session(engine) as session:
        preflight = preflight_frozen_candidates(
            session=session,
            active_root=active_root,
            candidate_root=candidate_root,
            plan=plan,
            manifest=manifest,
            expected_plan_sha256=plan["plan_sha256"],
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
        first = apply_frozen_candidates(
            session=session,
            active_root=active_root,
            candidate_root=candidate_root,
            plan=plan,
            manifest=manifest,
            expected_plan_sha256=plan["plan_sha256"],
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
        second = apply_frozen_candidates(
            session=session,
            active_root=active_root,
            candidate_root=candidate_root,
            plan=plan,
            manifest=manifest,
            expected_plan_sha256=plan["plan_sha256"],
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
        partition = MarketCatalog(session, active_root).all_partitions(
            DatasetKey(DatasetKind.CONTRACT, "oi", "OI2609", BarFrequency.D1)
        )[0]
        bars, facts = CanonicalMonthlyStore(active_root).read_catalog_partition_quality(partition)

    assert preflight == {"status": "ready", "target_count": 1, "old_count": 1, "noop_count": 0}
    assert first == {"status": "applied", "target_count": 1, "applied_count": 1, "noop_count": 0}
    assert second == {"status": "already_applied", "target_count": 1, "applied_count": 0, "noop_count": 0}
    assert bars == (_bar(1),)
    assert facts == (_quality(2),)
    assert old.parquet_path.is_file()


def test_apply_frozen_candidates_rejects_catalog_drift_before_install(tmp_path) -> None:
    from app.market_data.subing_d1_quality_apply import (
        QualityCandidateApplyError,
        apply_frozen_candidates,
    )

    engine, active_root, candidate_root, plan, manifest, _old = _case(tmp_path)
    with Session(engine) as session:
        row = session.query(MarketPartition).one()
        row.file_uri = row.file_uri.replace("part.", "part." + "f" * 64 + ".")
        session.commit()
        with pytest.raises(QualityCandidateApplyError, match="OLD_PARTITION_POINTER_DRIFT"):
            apply_frozen_candidates(
                session=session,
                active_root=active_root,
                candidate_root=candidate_root,
                plan=plan,
                manifest=manifest,
                expected_plan_sha256=plan["plan_sha256"],
                expected_manifest_sha256=manifest["manifest_sha256"],
            )

    candidate_hash = manifest["candidates"][0]["candidate_file_sha256"]
    assert not tuple(active_root.rglob(f"part.{candidate_hash}.parquet"))


def test_apply_frozen_candidates_creates_an_exact_missing_partition(tmp_path) -> None:
    from app.market_data.subing_d1_quality_apply import apply_frozen_candidates

    engine, active_root, candidate_root, plan, manifest, _old = _case(tmp_path)
    with Session(engine) as session:
        session.query(MarketPartition).delete()
        session.commit()
    target = dict(plan["targets"][0])
    target.update({
        "operation": "CREATE_MIXED_UNION_PARTITION",
        "partition_id": None,
        "old_file_uri": None,
        "old_file_sha256": None,
        "old_source_quality_sha256": None,
    })
    plan = {
        "schema": "subing-d1-quality-production-plan-v1",
        "mode": "PREPARE_ONLY",
        "provider_request_budget": 0,
        "target_partition_count": 1,
        "targets": [target],
    }
    plan["plan_sha256"] = sha256(canonical_json(plan)).hexdigest()
    item = dict(manifest["candidates"][0])
    item.update({
        "operation": "CREATE_MIXED_UNION_PARTITION",
        "partition_id": None,
        "old_file_uri": None,
        "old_file_sha256": None,
        "old_source_quality_sha256": None,
    })
    manifest = build_candidate_manifest(
        plan=plan,
        candidate_root="candidates",
        candidates=[item],
    )

    with Session(engine) as session:
        result = apply_frozen_candidates(
            session=session,
            active_root=active_root,
            candidate_root=candidate_root,
            plan=plan,
            manifest=manifest,
            expected_plan_sha256=plan["plan_sha256"],
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
        assert session.query(MarketPartition).count() == 1

    assert result == {"status": "applied", "target_count": 1, "applied_count": 1, "noop_count": 0}


def test_apply_frozen_candidates_marks_commit_exception_unknown(tmp_path, monkeypatch) -> None:
    from app.market_data.subing_d1_quality_apply import (
        QualityCandidateApplyError,
        apply_frozen_candidates,
    )

    engine, active_root, candidate_root, plan, manifest, old = _case(tmp_path)
    with Session(engine) as session:
        monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("lost ack")))
        with pytest.raises(QualityCandidateApplyError, match="COMMIT_OUTCOME_UNKNOWN"):
            apply_frozen_candidates(
                session=session,
                active_root=active_root,
                candidate_root=candidate_root,
                plan=plan,
                manifest=manifest,
                expected_plan_sha256=plan["plan_sha256"],
                expected_manifest_sha256=manifest["manifest_sha256"],
            )

    with Session(engine) as verify:
        assert verify.query(MarketPartition).one().file_uri == old.parquet_path.relative_to(active_root).as_posix()


def test_commit_ack_lost_stops_without_automatic_restore(tmp_path, monkeypatch) -> None:
    from app.market_data.subing_d1_quality_apply import (
        QualityCandidateApplyError,
        apply_frozen_candidates,
    )

    engine, active_root, candidate_root, plan, manifest, old = _case(tmp_path)
    with Session(engine) as session:
        real_commit = session.commit

        def commit_then_lose_ack():
            real_commit()
            raise RuntimeError("lost ack")

        monkeypatch.setattr(session, "commit", commit_then_lose_ack)
        with pytest.raises(QualityCandidateApplyError, match="^COMMIT_OUTCOME_UNKNOWN$"):
            apply_frozen_candidates(
                session=session,
                active_root=active_root,
                candidate_root=candidate_root,
                plan=plan,
                manifest=manifest,
                expected_plan_sha256=plan["plan_sha256"],
                expected_manifest_sha256=manifest["manifest_sha256"],
            )

    with Session(engine) as verify:
        assert verify.query(MarketPartition).one().file_uri != old.parquet_path.relative_to(active_root).as_posix()


def test_commit_unknown_is_not_masked_when_cleanup_rollback_fails(tmp_path, monkeypatch) -> None:
    from app.market_data.subing_d1_quality_apply import (
        QualityCandidateApplyError,
        apply_frozen_candidates,
    )

    engine, active_root, candidate_root, plan, manifest, _old = _case(tmp_path)
    with Session(engine) as session:
        monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("lost ack")))
        monkeypatch.setattr(session, "rollback", lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")))
        with pytest.raises(QualityCandidateApplyError, match="COMMIT_OUTCOME_UNKNOWN"):
            apply_frozen_candidates(
                session=session,
                active_root=active_root,
                candidate_root=candidate_root,
                plan=plan,
                manifest=manifest,
                expected_plan_sha256=plan["plan_sha256"],
                expected_manifest_sha256=manifest["manifest_sha256"],
            )


def test_post_commit_readback_failure_restores_old_pointer(tmp_path, monkeypatch) -> None:
    import app.market_data.subing_d1_quality_apply as module

    engine, active_root, candidate_root, plan, manifest, old = _case(tmp_path)
    real_readback = module._strict_batch_readback
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise module.QualityCandidateApplyError("injected")
        return real_readback(*args, **kwargs)

    monkeypatch.setattr(module, "_strict_batch_readback", fail_second)
    with Session(engine) as session:
        with pytest.raises(
            module.QualityCandidateApplyError,
            match="POST_COMMIT_READBACK_INVALID_ROLLED_BACK",
        ):
            module.apply_frozen_candidates(
                session=session,
                active_root=active_root,
                candidate_root=candidate_root,
                plan=plan,
                manifest=manifest,
                expected_plan_sha256=plan["plan_sha256"],
                expected_manifest_sha256=manifest["manifest_sha256"],
            )

    with Session(engine) as verify:
        assert verify.query(MarketPartition).one().file_uri == old.parquet_path.relative_to(active_root).as_posix()


def test_receipt_journal_reserves_target_before_apply_and_records_outcome(tmp_path) -> None:
    from app.market_data.subing_d1_quality_apply import QualityCandidateApplyError
    from scripts.subing_d1_quality_apply import ReceiptJournal

    path = tmp_path / "receipt.jsonl"
    journal = ReceiptJournal.reserve(path, {"status": "prepared", "plan_sha256": "a" * 64})
    with pytest.raises(QualityCandidateApplyError, match="APPLY_RECEIPT_EXISTS"):
        ReceiptJournal.reserve(path, {"status": "prepared"})
    journal.append({"status": "applied", "target_count": 156})
    journal.close()

    assert [json.loads(line) for line in path.read_text().splitlines()] == [
        {"status": "prepared", "plan_sha256": "a" * 64},
        {"status": "applied", "target_count": 156},
    ]
