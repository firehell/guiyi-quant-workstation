from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return factory


def test_scheduler_dry_run_never_constructs_provider_or_redis(capsys) -> None:
    from app.after_market_scheduler import main

    def fail_factory():
        raise AssertionError("dry-run must not construct provider or redis")

    exit_code = main(
        ["--dry-run"],
        environ={"GUIYI_AFTER_MARKET_AUTOMATION_ENABLED": "false"},
        session_factory=_session_factory(),
        client_factory=fail_factory,
        redis_factory=fail_factory,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["mode"] == "dry-run"
    assert payload["would_construct_rqdata_client"] is False
    assert payload["would_connect_redis"] is False
    assert payload["would_write_database"] is False
    assert payload["would_write_parquet"] is False
    assert payload["checkpoint_status"] == "missing"


def test_scheduler_default_provider_never_loads_project_env(monkeypatch) -> None:
    from app import after_market_scheduler as scheduler
    from app.services.rqdata_ingest import client as rq_client

    observed: list[bool] = []

    class FakeRqDataClient:
        def __init__(self, *, load_env_file: bool) -> None:
            observed.append(load_env_file)

    monkeypatch.setattr(rq_client, "RqDataClient", FakeRqDataClient)
    scheduler._default_client_factory()()

    assert observed == [False]


class BusyLock:
    def acquire(self, *, blocking: bool):
        return False


class BusyRedis:
    def lock(self, *args, **kwargs):
        return BusyLock()


class HeldLock:
    def acquire(self, *, blocking: bool):
        return True

    def release(self):
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[str, int, str]] = []

    def lock(self, *args, **kwargs):
        return HeldLock()

    def setex(self, key: str, ttl: int, payload: str):
        self.heartbeats.append((key, ttl, payload))


def test_scheduler_lock_conflict_never_starts_cycle() -> None:
    from app.after_market_scheduler import execute_guarded_cycle

    result = execute_guarded_cycle(
        redis_factory=BusyRedis,
        cycle=lambda: (_ for _ in ()).throw(AssertionError("busy lock must not start cycle")),
    )

    assert result == {"status": "lock_busy", "product": "jm", "singleton": True}


def test_scheduler_lease_loss_is_fail_closed() -> None:
    from app.after_market_scheduler import renew_scheduler_lease
    from app.services.after_market_automation import AfterMarketAutomationError

    class LostLock:
        def extend(self, *args, **kwargs):
            return False

    with pytest.raises(AfterMarketAutomationError, match="scheduler_lock_lost"):
        renew_scheduler_lease(LostLock(), lease_seconds=180)


def test_invalid_enable_packet_fails_before_redis_or_provider_construction(tmp_path, capsys) -> None:
    from app.after_market_scheduler import main

    packet_path = tmp_path / "approval_packet.json"
    packet_path.write_text('{"packet_hash":"invalid"}\n', encoding="utf-8")

    def fail_factory():
        raise AssertionError("invalid approval must fail before redis/provider construction")

    exit_code = main(
        [
            "--run-once",
            "--confirm-after-market-automation",
            "--approval-packet",
            str(packet_path),
            "--approval-hash",
            "invalid",
        ],
        environ={"GUIYI_AFTER_MARKET_AUTOMATION_ENABLED": "true"},
        session_factory=_session_factory(),
        client_factory=fail_factory,
        redis_factory=fail_factory,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "failed"
    assert payload["error_type"] == "automation_approval_identity_invalid"


def test_approved_cycle_revalidates_bound_facts_before_provider_construction(tmp_path, capsys, monkeypatch) -> None:
    from app import after_market_scheduler as scheduler
    from app.services.after_market_automation import AutomationPolicy, build_enable_approval_packet

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
    foundation_path = tmp_path / "foundation.json"
    foundation_path.write_text(json.dumps(foundation), encoding="utf-8")
    facts = {
        "git": {"commit": "1" * 40, "tracked_status_sha256": "2" * 64},
        "dependency_lock_sha256": "3" * 64,
        "database": {
            "driver": "postgresql",
            "host": "localhost",
            "database": "guiyi",
            "alembic_revision": "20260721_0025",
        },
        "runtime_root": str(Path(scheduler.__file__).resolve().parents[3]),
        "output_root": str(tmp_path),
        "output_device": tmp_path.stat().st_dev,
        "launchd_label": "com.guiyi.quant-after-market-scheduler",
    }
    packet = build_enable_approval_packet(
        bound_facts=facts,
        foundation_receipt=foundation,
        foundation_receipt_path=foundation_path,
        policy=AutomationPolicy(),
    )
    packet_path = tmp_path / "approval.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    calls = 0

    def collect_drifting_facts(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return facts
        return {**facts, "output_device": int(facts["output_device"]) + 1}

    monkeypatch.setattr(scheduler, "collect_current_bound_facts", collect_drifting_facts)

    def fail_client():
        raise AssertionError("bound-fact drift must fail before provider construction")

    exit_code = scheduler.main(
        [
            "--run-once",
            "--confirm-after-market-automation",
            "--approval-packet",
            str(packet_path),
            "--approval-hash",
            packet["packet_hash"],
        ],
        environ={"GUIYI_AFTER_MARKET_AUTOMATION_ENABLED": "true"},
        session_factory=_session_factory(),
        client_factory=fail_client,
        redis_factory=FakeRedis,
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert calls == 2
    assert payload["status"] == "failed"
    assert payload["error_type"] == "automation_bound_fact_drift"


def test_git_identity_ignores_branch_name_but_binds_commit_and_tracked_status(monkeypatch, tmp_path) -> None:
    from app import after_market_scheduler as scheduler

    responses = {
        ("status", "--porcelain=v1", "--untracked-files=no"): "",
        ("rev-parse", "HEAD"): "1" * 40,
        ("branch", "--show-current"): "main",
    }

    class Result:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    def fake_run(command, **kwargs):
        return Result(responses[tuple(command[1:])])

    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)

    assert scheduler._git_identity(tmp_path) == {
        "commit": "1" * 40,
        "tracked_status_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }
