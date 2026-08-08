from __future__ import annotations

from datetime import date, datetime, time, timedelta
import ast
import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import data_center
import pytest


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return factory


def test_checkpoint_migration_identifiers_fit_postgresql_limit() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260721_0025_after_market_scheduler_checkpoint.py"
    )
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    identifiers = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith(("ix_", "uq_"))
    }

    assert identifiers
    assert {name for name in identifiers if len(name) > 63} == set()


def test_after_market_checkpoint_persists_independent_watermark_and_retry_state() -> None:
    SessionLocal = _session_factory()
    checkpoint_type = data_center.AfterMarketSchedulerCheckpoint
    with SessionLocal() as session:
        checkpoint = checkpoint_type(
            product="jm",
            exchange_code="DCE",
            status="retry_wait",
            authorization_hash="a" * 64,
            last_successful_trading_day=date(2026, 7, 21),
            current_trading_day=date(2026, 7, 22),
            last_attempt_at=datetime(2026, 7, 22, 17, 0),
            next_retry_at=datetime(2026, 7, 22, 17, 5),
            retry_count=1,
            last_error_type="ConnectionError",
            last_error_at=datetime(2026, 7, 22, 17, 0),
            last_result={"status": "failed"},
        )
        session.add(checkpoint)
        session.commit()

        stored = session.scalar(select(checkpoint_type).where(checkpoint_type.product == "jm"))

    assert stored is not None
    assert stored.last_successful_trading_day == date(2026, 7, 21)
    assert stored.current_trading_day == date(2026, 7, 22)
    assert stored.retry_count == 1
    assert stored.last_result == {"status": "failed"}


class FakeCalendarClock:
    def __init__(self, days: list[date]) -> None:
        self.days = days

    def latest_completed_trading_day(self, *, product: str, exchange: str, now: datetime) -> date:
        return self.days[-1]

    def trading_days_between(self, start: date, end: date, *, exchange: str):
        return [day for day in self.days if start <= day <= end], True

    def final_close_at(self, trading_day: date, *, product: str, exchange: str) -> datetime:
        return datetime.combine(trading_day, time(15, 0))


def test_discovery_returns_oldest_five_days_only_after_safe_delay() -> None:
    from app.services.after_market_automation import discover_eligible_trading_days

    days = [date(2026, 7, 21) + timedelta(days=offset) for offset in range(7)]
    result = discover_eligible_trading_days(
        last_successful_trading_day=date(2026, 7, 20),
        now=datetime(2026, 7, 27, 16, 30),
        clock=FakeCalendarClock(days),
        product="jm",
        exchange="DCE",
        safe_delay_minutes=120,
        max_catchup_days=5,
    )

    assert result.latest_completed_trading_day == date(2026, 7, 27)
    assert result.latest_eligible_trading_day == date(2026, 7, 26)
    assert result.days == tuple(days[:5])
    assert result.archive_lag_trading_days == 6


def test_enable_packet_is_service_scoped_and_invalidates_on_bound_fact_drift(tmp_path) -> None:
    from app.services.after_market_automation import (
        AfterMarketAutomationError,
        AutomationPolicy,
        build_enable_approval_packet,
        validate_enable_approval_packet,
    )

    foundation = {
        "gate": "JM_ARCHIVE_PASSED",
        "status": "completed",
        "trading_day": "2026-07-21",
        "actual_contract": "JM2609",
        "packet_hash": "e" * 64,
        "registered_asset_smoke": {"status": "passed"},
        "consumer_profile_smoke": {"status": "passed"},
        "immutable_active_assets": {"status": "passed"},
    }
    bound_facts = {
        "git": {"commit": "1" * 40, "tracked_status_sha256": "2" * 64},
        "dependency_lock_sha256": "3" * 64,
        "database": {
            "driver": "postgresql",
            "host": "localhost",
            "database": "guiyi",
            "alembic_revision": "20260721_0025",
        },
        "runtime_root": str(tmp_path / "runtime"),
        "output_root": str(tmp_path),
        "output_device": tmp_path.stat().st_dev,
        "launchd_label": "com.guiyi.quant-after-market-scheduler",
    }
    foundation_path = tmp_path / "completion_receipt.json"
    foundation_path.write_text(json.dumps(foundation, sort_keys=True) + "\n", encoding="utf-8")
    packet = build_enable_approval_packet(
        bound_facts=bound_facts,
        foundation_receipt=foundation,
        foundation_receipt_path=foundation_path,
        policy=AutomationPolicy(),
    )

    assert packet["schema_version"] == 2
    import hashlib

    assert packet["foundation_receipt"]["sha256"] == hashlib.sha256(foundation_path.read_bytes()).hexdigest()
    assert packet["task_id"] == "JM-EOD-INCREMENTAL-AUTOMATION-S6-07"
    assert packet["status"] == "approval_required"
    assert packet["policy"]["safe_delay_minutes"] == 120
    assert packet["policy"]["max_catchup_days"] == 5
    assert packet["policy"]["retry_delays_minutes"] == [5, 15, 30, 60, 120, 240]
    assert validate_enable_approval_packet(
        packet,
        approval_hash=packet["packet_hash"],
        current_bound_facts=bound_facts,
        foundation_receipt=foundation,
    )["packet_hash"] == packet["packet_hash"]

    drifted = {**bound_facts, "git": {**bound_facts["git"], "commit": "4" * 40}}
    with pytest.raises(AfterMarketAutomationError, match="automation_bound_fact_drift"):
        validate_enable_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_bound_facts=drifted,
            foundation_receipt=foundation,
        )

    packet["allowed_writes"] = ["signal_event"]
    from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash

    packet["packet_hash"] = canonical_packet_hash(packet)
    with pytest.raises(AfterMarketAutomationError, match="automation_write_scope_invalid"):
        validate_enable_approval_packet(
            packet,
            approval_hash=packet["packet_hash"],
            current_bound_facts=bound_facts,
            foundation_receipt=foundation,
        )


def test_enable_packet_rejects_missing_or_drifted_alembic_revision(tmp_path) -> None:
    from app.services.after_market_automation import (
        AfterMarketAutomationError,
        AutomationPolicy,
        build_enable_approval_packet,
        validate_enable_approval_packet,
    )

    foundation = {
        "gate": "JM_ARCHIVE_PASSED",
        "status": "completed",
        "trading_day": "2026-07-21",
        "actual_contract": "JM2609",
        "packet_hash": "e" * 64,
        "registered_asset_smoke": {"status": "passed"},
        "consumer_profile_smoke": {"status": "passed"},
        "immutable_active_assets": {"status": "passed"},
    }
    facts = {
        "git": {"commit": "1" * 40, "tracked_status_sha256": "2" * 64},
        "dependency_lock_sha256": "3" * 64,
        "database": {
            "driver": "postgresql",
            "host": "localhost",
            "database": "guiyi",
            "alembic_revision": "20260721_0025",
        },
        "runtime_root": str(tmp_path / "runtime"),
        "output_root": str(tmp_path),
        "output_device": tmp_path.stat().st_dev,
        "launchd_label": "com.guiyi.quant-after-market-scheduler",
    }
    foundation_path = tmp_path / "foundation.json"
    foundation_path.write_text(json.dumps(foundation, sort_keys=True) + "\n", encoding="utf-8")
    packet = build_enable_approval_packet(
        bound_facts=facts,
        foundation_receipt=foundation,
        foundation_receipt_path=foundation_path,
        policy=AutomationPolicy(),
    )

    for revision in (None, "20260718_0024"):
        drifted = {**facts, "database": {**facts["database"], "alembic_revision": revision}}
        with pytest.raises(AfterMarketAutomationError, match="automation_bound_fact_drift"):
            validate_enable_approval_packet(
                packet,
                approval_hash=packet["packet_hash"],
                current_bound_facts=drifted,
                foundation_receipt=foundation,
            )

def test_run_once_advances_only_successful_days_and_stops_on_first_failure() -> None:
    from app.services.after_market_automation import AfterMarketAutomationService, DailyArchiveResult

    SessionLocal = _session_factory()
    days = [date(2026, 7, 21), date(2026, 7, 22), date(2026, 7, 23)]
    calls: list[date] = []

    def runner(trading_day: date) -> DailyArchiveResult:
        calls.append(trading_day)
        if trading_day == date(2026, 7, 22):
            return DailyArchiveResult(status="failed", error_type="ConnectionError", retryable=True)
        return DailyArchiveResult(
            status="success",
            packet_hash=str(trading_day).replace("-", "").ljust(64, "0"),
            receipt_path=f"/tmp/{trading_day}/completion_receipt.json",
        )

    with SessionLocal() as session:
        checkpoint = data_center.AfterMarketSchedulerCheckpoint(
            product="jm",
            exchange_code="DCE",
            status="idle",
            authorization_hash="a" * 64,
            last_successful_trading_day=date(2026, 7, 20),
            retry_count=0,
            last_result={},
        )
        session.add(checkpoint)
        session.commit()
        result = AfterMarketAutomationService(
            session=session,
            clock=FakeCalendarClock(days),
            daily_runner=runner,
            now=datetime(2026, 7, 23, 18, 0),
        ).run_once(checkpoint=checkpoint)
        session.refresh(checkpoint)

    assert calls == days[:2]
    assert result["status"] == "retry_wait"
    assert checkpoint.last_successful_trading_day == date(2026, 7, 21)
    assert checkpoint.current_trading_day == date(2026, 7, 22)
    assert checkpoint.retry_count == 1
    assert checkpoint.next_retry_at == datetime(2026, 7, 23, 18, 5)


def test_provider_pending_waits_without_advancing_watermark_or_consuming_retry() -> None:
    from app.services.after_market_automation import AfterMarketAutomationService, DailyArchiveResult

    SessionLocal = _session_factory()
    pending_day = date(2026, 7, 22)
    with SessionLocal() as session:
        checkpoint = data_center.AfterMarketSchedulerCheckpoint(
            product="jm",
            exchange_code="DCE",
            status="idle",
            authorization_hash="a" * 64,
            last_successful_trading_day=date(2026, 7, 21),
            retry_count=0,
            last_result={},
        )
        session.add(checkpoint)
        session.commit()
        result = AfterMarketAutomationService(
            session=session,
            clock=FakeCalendarClock([pending_day]),
            daily_runner=lambda _day: DailyArchiveResult(status="waiting_provider"),
            now=datetime(2026, 7, 22, 18, 0),
        ).run_once(checkpoint=checkpoint)

        assert result["status"] == "waiting_provider"
        assert checkpoint.last_successful_trading_day == date(2026, 7, 21)
        assert checkpoint.current_trading_day == pending_day
        assert checkpoint.retry_count == 0
        assert checkpoint.next_retry_at == datetime(2026, 7, 22, 18, 5)


def test_scheduler_success_updates_checkpoint_without_side_channel_tables() -> None:
    from app.services.after_market_automation import AfterMarketAutomationService, DailyArchiveResult

    SessionLocal = _session_factory()
    trading_day = date(2026, 7, 22)
    with SessionLocal() as session:
        checkpoint = data_center.AfterMarketSchedulerCheckpoint(
            product="jm",
            exchange_code="DCE",
            status="idle",
            authorization_hash="a" * 64,
            last_successful_trading_day=date(2026, 7, 21),
            retry_count=0,
            last_result={},
        )
        session.add(checkpoint)
        session.commit()
        result = AfterMarketAutomationService(
            session=session,
            clock=FakeCalendarClock([trading_day]),
            daily_runner=lambda _day: DailyArchiveResult(
                status="success",
                packet_hash="d" * 64,
                receipt_path="/tmp/receipt.json",
            ),
            now=datetime(2026, 7, 22, 18, 0),
        ).run_once(checkpoint=checkpoint)

        session.refresh(checkpoint)
        assert result["status"] == "success"
        assert checkpoint.last_successful_trading_day == trading_day
        assert checkpoint.status == "success"


@pytest.mark.parametrize(
    "error_type",
    [
        "quality_gate_failed",
        "provider_rank1_mapping_target_missing",
        "consumer_profile_smoke_failed",
        "binding_snapshot_drift",
    ],
)
def test_contract_failures_block_current_day_without_processing_later_days(error_type: str) -> None:
    from app.services.after_market_automation import AfterMarketAutomationService, DailyArchiveResult

    SessionLocal = _session_factory()
    days = [date(2026, 7, 22), date(2026, 7, 23)]
    calls: list[date] = []
    with SessionLocal() as session:
        checkpoint = data_center.AfterMarketSchedulerCheckpoint(
            product="jm",
            exchange_code="DCE",
            status="idle",
            authorization_hash="a" * 64,
            last_successful_trading_day=date(2026, 7, 21),
            retry_count=0,
            last_result={},
        )
        session.add(checkpoint)
        session.commit()

        def runner(day: date) -> DailyArchiveResult:
            calls.append(day)
            return DailyArchiveResult(status="failed", error_type=error_type, retryable=False)

        result = AfterMarketAutomationService(
            session=session,
            clock=FakeCalendarClock(days),
            daily_runner=runner,
            now=datetime(2026, 7, 23, 18, 0),
        ).run_once(checkpoint=checkpoint)

        assert calls == [days[0]]
        assert result["status"] == "blocked"
        assert checkpoint.current_trading_day == days[0]
        assert checkpoint.last_error_type == error_type


def test_sixth_retry_uses_final_delay_then_next_failure_blocks_until_matching_reset() -> None:
    from app.services.after_market_automation import (
        AfterMarketAutomationError,
        AfterMarketAutomationService,
        DailyArchiveResult,
    )

    SessionLocal = _session_factory()
    failed_day = date(2026, 7, 22)
    with SessionLocal() as session:
        checkpoint = data_center.AfterMarketSchedulerCheckpoint(
            product="jm",
            exchange_code="DCE",
            status="retry_wait",
            authorization_hash="a" * 64,
            last_successful_trading_day=date(2026, 7, 21),
            current_trading_day=failed_day,
            retry_count=5,
            last_result={},
        )
        session.add(checkpoint)
        session.commit()
        service = AfterMarketAutomationService(
            session=session,
            clock=FakeCalendarClock([failed_day]),
            daily_runner=lambda _day: DailyArchiveResult(
                status="failed", error_type="ManifestWriteError", retryable=True
            ),
            now=datetime(2026, 7, 22, 18, 0),
        )

        service.run_once(checkpoint=checkpoint)
        assert checkpoint.status == "retry_wait"
        assert checkpoint.retry_count == 6
        assert checkpoint.next_retry_at == datetime(2026, 7, 22, 22, 0)

        checkpoint.next_retry_at = None
        service.run_once(checkpoint=checkpoint)
        assert checkpoint.status == "blocked"
        assert checkpoint.retry_count == 7
        with pytest.raises(AfterMarketAutomationError, match="retry_day_mismatch"):
            service.reset_failed_day(checkpoint, trading_day=date(2026, 7, 23), confirmed=True)
        service.reset_failed_day(checkpoint, trading_day=failed_day, confirmed=True)
        session.commit()
        assert checkpoint.status == "retry_wait"
        assert checkpoint.retry_count == 0


def test_delegated_daily_run_persists_create_only_packet_and_returns_daily_receipt(tmp_path, monkeypatch) -> None:
    from app.services import after_market_automation as automation

    audit_root = tmp_path / "reports" / "jm_eod_incremental_s6_07" / "s607_20260722_12345678"
    packet = {
        "packet_hash": "d" * 64,
        "bound_facts": {"parent_automation_approval_hash": "a" * 64},
        "execution_contract": {"status": "passed"},
        "execution_plan": {"audit_root": str(audit_root), "target": "2026-07-22"},
    }
    monkeypatch.setattr(automation, "collect_delegated_archive_packet", lambda *args, **kwargs: packet)
    monkeypatch.setattr(
        automation,
        "execute_archive",
        lambda *args, **kwargs: {
            "status": "success",
            "gate": "JM_EOD_ARCHIVE_DAY_PASSED",
            "packet_hash": "d" * 64,
        },
    )

    result = automation.run_delegated_archive_day(
        session=object(),
        client=object(),
        output_root=tmp_path,
        project_root=tmp_path,
        trading_day=date(2026, 7, 22),
        now=datetime(2026, 7, 22, 18, 0),
        git_identity={"commit": "1" * 40},
        database_identity={"driver": "sqlite"},
        parent_automation_approval_hash="a" * 64,
    )

    saved = audit_root / "execution_packet.json"
    assert saved.is_file()
    assert result.status == "success"
    assert result.packet_hash == "d" * 64
    assert result.receipt_path == str(audit_root / "completion_receipt.json")

    saved.write_text("{}\n", encoding="utf-8")
    with pytest.raises(automation.AfterMarketAutomationError, match="daily_execution_packet_drift"):
        automation.run_delegated_archive_day(
            session=object(),
            client=object(),
            output_root=tmp_path,
            project_root=tmp_path,
            trading_day=date(2026, 7, 22),
            now=datetime(2026, 7, 22, 18, 0),
            git_identity={"commit": "1" * 40},
            database_identity={"driver": "sqlite"},
            parent_automation_approval_hash="a" * 64,
        )


def test_existing_daily_receipt_is_reverified_without_provider_connection(tmp_path, monkeypatch) -> None:
    from app.services import after_market_automation as automation

    commit = "12345678" + "0" * 32
    audit_root = tmp_path / "reports" / "jm_eod_incremental_s6_07" / "s607_20260722_12345678"
    packet_path = audit_root / "execution_packet.json"
    packet_path.parent.mkdir(parents=True)
    packet = {
        "packet_hash": "d" * 64,
        "bound_facts": {
            "parent_automation_approval_hash": "a" * 64,
            "trading_day": "2026-07-22",
            "git": {"commit": commit},
        },
        "execution_plan": {"audit_root": str(audit_root)},
    }
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    monkeypatch.setattr(automation, "validate_approval_packet", lambda *args, **kwargs: {"status": "passed"})
    monkeypatch.setattr(
        automation,
        "_recover_committed_archive",
        lambda *args, **kwargs: {
            "status": "already_archived",
            "writes_performed": False,
            "receipt_path": str(audit_root / "completion_receipt.json"),
        },
    )
    monkeypatch.setattr(
        automation,
        "collect_delegated_archive_packet",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider must not be called")),
    )

    result = automation.run_delegated_archive_day(
        session=object(),
        client=object(),
        output_root=tmp_path,
        project_root=tmp_path,
        trading_day=date(2026, 7, 22),
        now=datetime(2026, 7, 22, 18, 0),
        git_identity={"commit": commit},
        database_identity={"driver": "sqlite"},
        parent_automation_approval_hash="a" * 64,
    )

    assert result.status == "already_archived"
    assert result.details == {"gate": "JM_EOD_ARCHIVE_DAY_PASSED", "evidence_reverified": True}


def test_checkpoint_bootstrap_uses_verified_s606_receipt_once() -> None:
    from app.services.after_market_automation import load_or_seed_checkpoint

    SessionLocal = _session_factory()
    receipt = {
        "gate": "JM_ARCHIVE_PASSED",
        "status": "completed",
        "trading_day": "2026-07-21",
        "actual_contract": "JM2609",
        "packet_hash": "e" * 64,
        "registered_asset_smoke": {"status": "passed"},
        "consumer_profile_smoke": {"status": "passed"},
        "immutable_active_assets": {"status": "passed"},
    }
    with SessionLocal() as session:
        first = load_or_seed_checkpoint(
            session,
            authorization_hash="a" * 64,
            foundation_receipt=receipt,
        )
        session.commit()
        second = load_or_seed_checkpoint(
            session,
            authorization_hash="a" * 64,
            foundation_receipt=receipt,
        )

        assert first.id == second.id
        assert first.last_successful_trading_day == date(2026, 7, 21)
        assert session.query(data_center.AfterMarketSchedulerCheckpoint).count() == 1


def test_idle_checkpoint_rotates_to_new_verified_service_authorization() -> None:
    from app.services.after_market_automation import AfterMarketAutomationError, load_or_seed_checkpoint

    SessionLocal = _session_factory()
    receipt = {
        "gate": "JM_ARCHIVE_PASSED",
        "status": "completed",
        "trading_day": "2026-07-21",
        "actual_contract": "JM2609",
        "packet_hash": "e" * 64,
        "registered_asset_smoke": {"status": "passed"},
        "consumer_profile_smoke": {"status": "passed"},
        "immutable_active_assets": {"status": "passed"},
    }
    with SessionLocal() as session:
        checkpoint = data_center.AfterMarketSchedulerCheckpoint(
            product="jm",
            exchange_code="DCE",
            status="idle",
            authorization_hash="a" * 64,
            last_successful_trading_day=date(2026, 7, 21),
            retry_count=0,
            last_result={"status": "idle"},
        )
        session.add(checkpoint)
        session.commit()

        with pytest.raises(AfterMarketAutomationError, match="checkpoint_authorization_hash_mismatch"):
            load_or_seed_checkpoint(
                session,
                authorization_hash="b" * 64,
                foundation_receipt=receipt,
            )

        rotated = load_or_seed_checkpoint(
            session,
            authorization_hash="b" * 64,
            foundation_receipt=receipt,
            allow_authorization_rotation=True,
        )

        assert rotated.id == checkpoint.id
        assert rotated.authorization_hash == "b" * 64
        assert rotated.last_successful_trading_day == date(2026, 7, 21)
        rotation = rotated.last_result["authorization_history"][-1]
        assert rotation["previous_authorization_hash"] == "a" * 64
        assert rotation["authorization_hash"] == "b" * 64

        from app.services.after_market_automation import AfterMarketAutomationService

        AfterMarketAutomationService(
            session=session,
            clock=FakeCalendarClock([date(2026, 7, 21)]),
            daily_runner=lambda _day: (_ for _ in ()).throw(AssertionError("no eligible day expected")),
            now=datetime(2026, 7, 22, 12, 0),
        ).run_once(checkpoint=rotated)
        session.refresh(rotated)

        persisted_rotation = rotated.last_result["authorization_history"][-1]
        assert persisted_rotation["previous_authorization_hash"] == "a" * 64
        assert persisted_rotation["authorization_hash"] == "b" * 64


@pytest.mark.parametrize(
    ("status", "current_trading_day", "retry_count"),
    [
        ("running", date(2026, 7, 22), 0),
        ("blocked", date(2026, 7, 22), 1),
        ("retry_wait", date(2026, 7, 22), 1),
    ],
)
def test_checkpoint_authorization_rotation_refuses_unfinished_day(
    status: str,
    current_trading_day: date,
    retry_count: int,
) -> None:
    from app.services.after_market_automation import AfterMarketAutomationError, load_or_seed_checkpoint

    SessionLocal = _session_factory()
    receipt = {
        "gate": "JM_ARCHIVE_PASSED",
        "status": "completed",
        "trading_day": "2026-07-21",
        "actual_contract": "JM2609",
        "packet_hash": "e" * 64,
        "registered_asset_smoke": {"status": "passed"},
        "consumer_profile_smoke": {"status": "passed"},
        "immutable_active_assets": {"status": "passed"},
    }
    with SessionLocal() as session:
        session.add(
            data_center.AfterMarketSchedulerCheckpoint(
                product="jm",
                exchange_code="DCE",
                status=status,
                authorization_hash="a" * 64,
                last_successful_trading_day=date(2026, 7, 21),
                current_trading_day=current_trading_day,
                retry_count=retry_count,
                last_result={"status": status},
            )
        )
        session.commit()

        with pytest.raises(AfterMarketAutomationError, match="checkpoint_authorization_hash_mismatch"):
            load_or_seed_checkpoint(
                session,
                authorization_hash="b" * 64,
                foundation_receipt=receipt,
                allow_authorization_rotation=True,
            )


def test_blocked_checkpoint_rotates_only_for_explicit_same_day_retry() -> None:
    from app.services.after_market_automation import AfterMarketAutomationError, load_or_seed_checkpoint

    SessionLocal = _session_factory()
    failed_day = date(2026, 7, 24)
    receipt = {
        "gate": "JM_ARCHIVE_PASSED",
        "status": "completed",
        "trading_day": "2026-07-21",
        "actual_contract": "JM2609",
        "packet_hash": "e" * 64,
        "registered_asset_smoke": {"status": "passed"},
        "consumer_profile_smoke": {"status": "passed"},
        "immutable_active_assets": {"status": "passed"},
    }
    with SessionLocal() as session:
        checkpoint = data_center.AfterMarketSchedulerCheckpoint(
            product="jm",
            exchange_code="DCE",
            status="blocked",
            authorization_hash="a" * 64,
            last_successful_trading_day=date(2026, 7, 23),
            current_trading_day=failed_day,
            retry_count=1,
            last_error_type="ValueError",
            last_error_at=datetime(2026, 7, 24, 17, 18),
            last_result={"status": "failed"},
        )
        session.add(checkpoint)
        session.commit()

        with pytest.raises(AfterMarketAutomationError, match="checkpoint_authorization_hash_mismatch"):
            load_or_seed_checkpoint(
                session,
                authorization_hash="b" * 64,
                foundation_receipt=receipt,
                allow_authorization_rotation=True,
                authorization_rotation_failed_day=date(2026, 7, 25),
            )

        rotated = load_or_seed_checkpoint(
            session,
            authorization_hash="b" * 64,
            foundation_receipt=receipt,
            allow_authorization_rotation=True,
            authorization_rotation_failed_day=failed_day,
        )

        assert rotated.authorization_hash == "b" * 64
        assert rotated.status == "blocked"
        assert rotated.current_trading_day == failed_day
        assert rotated.last_result["authorization_history"][-1]["reason"] == "explicit_failed_day_retry"


def test_output_root_failure_blocks_immediately_without_consuming_six_retries() -> None:
    from app.services.after_market_automation import AfterMarketAutomationError, AfterMarketAutomationService

    SessionLocal = _session_factory()
    failed_day = date(2026, 7, 22)
    with SessionLocal() as session:
        checkpoint = data_center.AfterMarketSchedulerCheckpoint(
            product="jm",
            exchange_code="DCE",
            status="idle",
            authorization_hash="a" * 64,
            last_successful_trading_day=date(2026, 7, 21),
            retry_count=0,
            last_result={},
        )
        session.add(checkpoint)
        session.commit()
        result = AfterMarketAutomationService(
            session=session,
            clock=FakeCalendarClock([failed_day]),
            daily_runner=lambda _day: (_ for _ in ()).throw(AfterMarketAutomationError("output_root_unavailable")),
            now=datetime(2026, 7, 22, 18, 0),
        ).run_once(checkpoint=checkpoint)

        assert result["status"] == "blocked"
        assert checkpoint.retry_count == 1
        assert checkpoint.last_error_type == "output_root_unavailable"
