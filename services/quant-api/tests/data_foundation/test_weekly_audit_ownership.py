"""State ownership uses real process locks; audit/DB fixtures stay isolated."""
from datetime import timedelta
import io
import json
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.market_data import weekly_audit
from app.market_data.historical_data_manager import AuditFinding, AuditProgressEvent, MaintenanceResult
from tests.data_foundation.test_weekly_audit import IDENTITY, NOW


def _run(manager, path, *, now=NOW):
    return weekly_audit.run_weekly_audit(manager, status_path=path, products=("au",),
                                       identity=IDENTITY, now=lambda: now)


def _health(path, *, now=NOW):
    return weekly_audit.weekly_audit_health(path, identity=IDENTITY, products=("au",), now=now)["status"]


def _manager(session):
    return SimpleNamespace(catalog=SimpleNamespace(session=session,
        acquire_maintenance_lock=lambda: SimpleNamespace(release=lambda: None)),
        audit=lambda *args, **kwargs: MaintenanceResult("audit", "passed", NOW.date(), 0, 0, 0, 0, 0))


def _owner_process(path, stage, outcome, channel):
    """Pause at a real publication boundary until the competitor has finished."""
    path = Path(path)
    def pause(at):
        if stage == at:
            channel.send("paused")
            assert channel.poll(20), "parent did not resume owner"
            assert channel.recv() == "resume"
    original_write = weekly_audit._atomic_write_status
    def write(target, payload):
        if payload["status"] != "running":
            pause("terminal")
        original_write(target, payload)
    weekly_audit._atomic_write_status = write
    with Session(create_engine("sqlite://")) as session:
        manager = _manager(session)
        def acquire():
            pause("acquire")
            return SimpleNamespace(release=lambda: pause("release"))
        def audit(request, *, observer):
            observer(AuditProgressEvent("started", 0, 1, "au", None))
            pause("audit")
            if outcome == "failed":
                raise RuntimeError("private failure")
            if outcome == "interrupted":
                raise KeyboardInterrupt
            if outcome == "findings":
                return MaintenanceResult("audit", "failed", NOW.date(), 0, 0, 0, 0, 0,
                    findings=(AuditFinding("MAIN_CONTRACT_MAP_MISSING", "main_contract_map",
                                           ("metadata", "au", "rank1", "1d"), None, None),))
            return MaintenanceResult("audit", "passed", NOW.date(), 0, 0, 0, 0, 0)
        manager.catalog.acquire_maintenance_lock = acquire
        manager.audit = audit
        try:
            channel.send(_run(manager, path)["status"])
        except KeyboardInterrupt:
            channel.send("interrupted")
    channel.close()


@pytest.mark.parametrize("stage", ["acquire", "audit", "terminal", "release"])
@pytest.mark.parametrize("outcome", ["passed", "findings", "failed"])
def test_competitor_cannot_publish_at_any_owner_boundary(tmp_path, stage, outcome):
    _assert_competitor_preserves_owner(tmp_path, stage, outcome)


def test_interrupted_owner_stays_visible_and_releases_writer_lock(tmp_path):
    _assert_competitor_preserves_owner(tmp_path, "audit", "interrupted")


def _assert_competitor_preserves_owner(tmp_path, stage, outcome):
    path = tmp_path / "status.json"
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_owner_process, args=(str(path), stage, outcome, child))
    process.start()
    child.close()
    try:
        assert parent.poll(20), "owner did not reach boundary"
        assert parent.recv() == "paused"
        before = path.read_bytes()
        with Session(create_engine("sqlite://")) as session:
            manager = _manager(session)
            def unexpected():
                pytest.fail("competitor must not acquire maintenance lease")
            manager.catalog.acquire_maintenance_lock = unexpected
            result = _run(manager, path, now=NOW + timedelta(minutes=1))
            assert result["status"] == "skipped_busy"
            assert result["provider_requests"] == result["data_writes"] == 0
            assert not session.in_transaction()
        assert path.read_bytes() == before
        assert _health(path) == (outcome if stage == "release" else "running")
        parent.send("resume")
        assert parent.poll(20)
        assert parent.recv() == outcome
        process.join(20)
        assert process.exitcode == 0
        expected = "running" if outcome == "interrupted" else outcome
        assert _health(path) == expected
        assert _health(path, now=NOW + timedelta(hours=3)) == (
            "stuck" if outcome == "interrupted" else expected)
        if outcome != "interrupted":
            assert _health(path, now=NOW + timedelta(days=9)) == "stale"
        with Session(create_engine("sqlite://")) as session:
            assert _run(_manager(session), path, now=NOW + timedelta(minutes=2))["status"] == "passed"
        assert _health(path, now=NOW + timedelta(minutes=2)) == "passed"
        invalid = json.loads(path.read_text())
        invalid["runtime_commit"] = "b" * 40
        path.write_text(json.dumps(invalid))
        assert _health(path, now=NOW + timedelta(minutes=2)) == "invalid"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(20)
        parent.close()


def test_new_exclusive_busy_attempt_replaces_old_success(tmp_path):
    path = tmp_path / "status.json"
    with Session(create_engine("sqlite://")) as session:
        manager = _manager(session)
        assert _run(manager, path)["status"] == "passed"
        manager.catalog.acquire_maintenance_lock = lambda: None
        result = _run(manager, path, now=NOW + timedelta(minutes=1))
        assert result["status"] == "skipped_busy"
        assert result["through"] is None and result["completed"] == 0
        assert _health(path, now=NOW + timedelta(minutes=1)) == "skipped_busy"
        assert not session.in_transaction()


@pytest.mark.parametrize("operation", ["open", "flock"])
def test_guard_setup_failure_rejects_startup_without_publishing(tmp_path, monkeypatch, operation):
    from app import runtime_entry
    path = tmp_path / "status.json"
    with Session(create_engine("sqlite://")) as session:
        manager = _manager(session)
        _run(manager, path)
        before = path.read_bytes()
        def fail(*args, **kwargs):
            raise OSError("private guard details")
        def forbidden():
            pytest.fail("failed guard must not acquire maintenance lease")
        acquire = manager.catalog.acquire_maintenance_lock
        manager.catalog.acquire_maintenance_lock = forbidden
        with monkeypatch.context() as patch:
            patch.setattr(weekly_audit.os if operation == "open" else weekly_audit.fcntl, operation, fail)
            patch.setattr(runtime_entry, "run_weekly_audit_service", lambda **kwargs: _run(manager, path))
            output, error = io.StringIO(), io.StringIO()
            assert runtime_entry.main(["weekly-audit"], stdout=output, stderr=error) == 1
            assert json.loads(error.getvalue())["readonly"] is True
            assert "private" not in error.getvalue() and not output.getvalue()
        assert path.read_bytes() == before
        assert not session.in_transaction()
        manager.catalog.acquire_maintenance_lock = acquire
        assert _run(manager, path)["status"] == "passed"


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo", "writable"])
def test_unsafe_guard_does_not_touch_existing_status(tmp_path, kind):
    path = tmp_path / "status.json"
    path.write_bytes(b"previous state")
    guard = tmp_path / "status.json.lock"
    if kind == "symlink":
        guard.symlink_to(path)
    elif kind == "hardlink":
        os.link(path, guard)
    elif kind == "directory":
        guard.mkdir()
    elif kind == "fifo":
        os.mkfifo(guard)
    else:
        guard.touch(mode=0o600)
        guard.chmod(0o666)
    with Session(create_engine("sqlite://")) as session:
        with pytest.raises(RuntimeError, match="^WEEKLY_AUDIT_FAILED$"):
            _run(_manager(session), path)
        assert not session.in_transaction()
    assert path.read_bytes() == b"previous state"


@pytest.mark.parametrize("failed_write", [1, 2, 3], ids=["initial", "progress", "terminal"])
def test_write_failure_is_not_guard_busy_and_releases_leases(tmp_path, monkeypatch, failed_write):
    path = tmp_path / "status.json"
    calls, released = [], []
    original_write = weekly_audit._atomic_write_status
    def write(target, payload):
        calls.append(payload["status"])
        if len(calls) == failed_write:
            raise BlockingIOError("private write failure")
        original_write(target, payload)
    with Session(create_engine("sqlite://")) as session:
        manager = _manager(session)
        manager.catalog.acquire_maintenance_lock = lambda: SimpleNamespace(release=lambda: released.append(True))
        def audit(request, *, observer):
            observer(AuditProgressEvent("started", 0, 1, "au", None))
            return MaintenanceResult("audit", "passed", NOW.date(), 0, 0, 0, 0, 0)
        manager.audit = audit
        with monkeypatch.context() as patch:
            patch.setattr(weekly_audit, "_atomic_write_status", write)
            if failed_write == 2:
                assert _run(manager, path)["status"] == "failed"
                assert _health(path) == "failed"
                assert "private" not in path.read_text()
            else:
                with pytest.raises(BlockingIOError):
                    _run(manager, path)
                assert _health(path) == ("not_run" if failed_write == 1 else "running")
        assert released == ([] if failed_write == 1 else [True])
        assert not session.in_transaction()
        inode = (tmp_path / "status.json.lock").stat().st_ino
        assert _run(manager, path)["status"] == "passed"
        assert (tmp_path / "status.json.lock").stat().st_ino == inode


def test_process_death_releases_guard_without_relabeling_unfinished_run(tmp_path):
    path = tmp_path / "status.json"
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=_owner_process, args=(str(path), "audit", "passed", child))
    process.start()
    child.close()
    try:
        assert parent.poll(20) and parent.recv() == "paused"
        before = path.read_bytes()
        process.kill()
        process.join(20)
        assert process.exitcode is not None and process.exitcode != 0
        assert path.read_bytes() == before
        assert _health(path, now=NOW + timedelta(hours=3)) == "stuck"
        with Session(create_engine("sqlite://")) as session:
            assert _run(_manager(session), path)["status"] == "passed"
    finally:
        if process.is_alive():
            process.terminate()
        process.join(20)
        parent.close()


@pytest.mark.parametrize("state", ["not_run", "running", "passed", "findings", "failed", "skipped_busy", "stuck", "stale", "invalid"])
def test_actual_weekly_state_never_changes_operational_overall(tmp_path, monkeypatch, state):
    from app.services import runtime_health
    from tests.test_runtime_health import FakeRedis, _session_factory
    path = tmp_path / "status.json"
    monkeypatch.setattr(runtime_health, "runtime_heartbeat_identity", lambda: IDENTITY)
    monkeypatch.setattr(runtime_health, "load_operational_products", lambda: ("au",))
    with _session_factory()() as session:
        if state != "not_run":
            _run(_manager(session), path)
            payload = json.loads(path.read_text())
            payload["status"] = {"stuck": "running", "stale": "passed", "invalid": "passed"}.get(state, state)
            if state in {"running", "stuck"}:
                payload["finished_at"] = None
            if state == "failed":
                payload["error_code"] = "WEEKLY_AUDIT_FAILED"
            if state == "findings":
                payload.update(finding_count=1, findings=[{"code": "MAIN_CONTRACT_MAP_MISSING",
                    "category": "main_contract_map", "dataset": ["metadata", "au", "rank1", "1d"],
                    "year": None, "month": None}])
            if state == "invalid":
                payload["runtime_commit"] = "bad"
            path.write_text(json.dumps(payload))
        now = NOW + (timedelta(hours=3) if state == "stuck" else timedelta(days=9) if state == "stale" else timedelta())
        result = runtime_health.build_runtime_health(session, redis_factory=FakeRedis, now=now,
            live_runtime_enabled=False, after_market_automation_enabled=False, alert_runtime_enabled=False,
            notification_transport_configured=False, after_market_status_path=None, weekly_audit_status_path=path)
        assert result["components"]["weekly_audit"]["status"] == state
        assert result["status"] == "ok"
