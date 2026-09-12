from datetime import datetime
import json
import hashlib
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.market_data.historical_data_manager import MaintenanceResult
from tests.data_foundation.test_daily_maintenance import daily_manager  # noqa: F401
from tests.data_foundation.test_historical_data_manager import session  # noqa: F401

from app.market_data.after_market import public_after_market_status


def interrupted_status():
    return {
        "schema_version": 4, "current_run": None,
        "last_successful_trading_day": "2026-09-08",
        "last_failure": {"trading_day": "2026-09-09", "error_code": "AFTER_MARKET_INTERRUPTED"},
        "last_run": {
            "trading_day": "2026-09-09", "status": "interrupted", "attempts": None,
            "started_at": "2026-09-09T18:05:00+08:00",
            "finished_at": "2026-09-10T08:00:00+08:00", "products": ["au"],
            "error_code": "AFTER_MARKET_INTERRUPTED", "failure_notification": None,
        },
    }


def test_interrupted_is_not_success_and_legacy_attempts_remain_unknown():
    public = public_after_market_status(interrupted_status())
    assert public.get("last_run", {}).get("status") == "interrupted"
    assert public["last_run"]["attempts"] is None
    assert public["last_successful_trading_day"] == "2026-09-08"
    assert public["last_failure"]["error_code"] == "AFTER_MARKET_INTERRUPTED"


def test_unknown_attempts_are_not_accepted_for_success():
    raw = interrupted_status()
    raw["last_run"].update(status="passed", error_code=None)
    assert public_after_market_status(raw) == {}


def test_interrupted_does_not_prove_after_market_complete():
    from app.market_data.runtime_promotion import _after_market_status_decision
    assert _after_market_status_decision(interrupted_status(), trading_day=datetime(2026, 9, 9).date(),
        products=("au",), now=datetime.fromisoformat("2026-09-10T09:00:00+08:00")) == "missing"


@pytest.fixture
def closeout_case(tmp_path):
    root = tmp_path / "runtime"
    directory = root / ".run"
    directory.mkdir(parents=True, mode=0o700)
    guards = directory / "live-recovery-guards"
    guards.mkdir(mode=0o700)
    (guards / "after-market.lock").touch(mode=0o600)
    path = directory / "after-market-status.json"
    raw = interrupted_status()
    raw.update(schema_version=2, last_run=None, last_failure=None,
               current_run={"scheduled_date": "2026-09-09", "started_at": "2026-09-09T18:05:00+08:00", "products": ["au"]})
    content = (json.dumps(raw) + "\n").encode()
    path.write_bytes(content)
    path.chmod(0o600)
    with Session(create_engine("sqlite://")) as session:  # noqa: F811
        events = []
        def audit(request):
            assert session.scalar(text("PRAGMA query_only")) == 1
            assert request.products == ("au",) and request.through.isoformat() == "2026-09-09"
            events.append("audit")
            return MaintenanceResult("audit", "passed", request.through, 0, 0, 0, 0, 0)
        def acquire():
            assert not session.in_transaction()
            events.append("lock")
            return SimpleNamespace(release=lambda: events.append("release"))
        manager = SimpleNamespace(catalog=SimpleNamespace(session=session,
            acquire_maintenance_lock=acquire, main_map=lambda *args: [SimpleNamespace(contract="AU2612")],
            product_partitions=lambda symbol: ()),
            audit=audit)
        yield dict(root=root, path=path, content=content, session=session, events=events, manager=manager,
            kwargs=dict(root=root, expected_commit="a" * 40, expected_status_sha256=hashlib.sha256(content).hexdigest(),
                products=("au",), now=lambda: datetime.fromisoformat("2026-09-10T08:00:00+08:00"),
                verify_identity=lambda *args: None,
                live_store=SimpleNamespace(subscriptions=lambda day: {"au": "AU2612"})))


def close(case, **overrides):
    from app.market_data import after_market_closeout
    return after_market_closeout.close_interrupted_run(case["manager"], **{**case["kwargs"], **overrides})


def test_closeout_dry_run_never_changes_status(closeout_case):
    case = closeout_case
    result = close(case, apply=False)
    assert result["status"] == "ready" and result["status_written"] is False
    assert case["path"].read_bytes() == case["content"]
    assert case["events"] == ["lock", "audit", "release"]
    assert not case["session"].in_transaction()


def test_closeout_apply_retains_failure_and_previous_success_without_notification(closeout_case):
    case = closeout_case
    result = close(case, apply=True)
    assert result["status"] == "closed_interrupted" and result["status_written"] is True
    public = public_after_market_status(json.loads(case["path"].read_bytes()))
    assert public["current_run"] is None
    assert public["last_run"]["status"] == "interrupted"
    assert public["last_run"]["attempts"] is None
    assert public["last_run"]["failure_notification"] is None
    assert public["last_successful_trading_day"] == "2026-09-08"
    assert result["terminal_status_sha256"] == hashlib.sha256(case["path"].read_bytes()).hexdigest()
    assert close(case, apply=True)["status"] == "blocked"


@pytest.mark.parametrize("failure", ["hash", "busy", "identity", "audit", "live"])
def test_closeout_uncertainty_preserves_original_bytes(closeout_case, failure):
    case = closeout_case
    overrides = {}
    if failure == "hash":
        overrides["expected_status_sha256"] = "b" * 64
    elif failure == "busy":
        case["manager"].catalog.acquire_maintenance_lock = lambda: None
    elif failure == "identity":
        def reject(*args):
            raise ValueError("secret provider response")
        overrides["verify_identity"] = reject
    elif failure == "audit":
        case["manager"].audit = lambda *args: MaintenanceResult("audit", "failed", None, 0, 0, 0, 1, 0)
    else:
        overrides["live_store"] = SimpleNamespace(subscriptions=lambda day: {})
    result = close(case, apply=True, **overrides)
    assert result["status"] == "blocked" and result["status_written"] is False
    assert "secret" not in json.dumps(result)
    assert case["path"].read_bytes() == case["content"]


def test_interrupted_health_stays_degraded_even_when_previous_success_is_recent(tmp_path, monkeypatch):
    from app.services import runtime_health
    from app.schemas.runtime import RuntimeAfterMarketHealth
    path = tmp_path / "status.json"
    path.write_text(json.dumps(interrupted_status()))
    monkeypatch.setattr(runtime_health, "_expected_after_market_day", lambda *args, **kwargs: (datetime(2026, 9, 8).date(), False))
    value = runtime_health._collect_after_market_health(None, status_path=path, configured_enabled=True,
        now=datetime.fromisoformat("2026-09-10T09:00:00+08:00"))
    assert value["status"] == "degraded" and value["run_state"] == "interrupted"
    assert RuntimeAfterMarketHealth.model_validate(value).last_run.attempts is None


def test_closeout_cli_is_explicit_and_does_not_route_to_update(monkeypatch):
    import io
    from app.guiyi_cli.main import main
    from app.guiyi_cli import after_market_closeout
    calls = []
    monkeypatch.setattr(after_market_closeout, "run_closeout_command", lambda args, **kwargs:
        calls.append(args) or {"status": "closed_interrupted", "readonly": False}, raising=False)
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["data", "close-interrupted-after-market", "--runtime-root", "/fixture/runtime",
        "--runtime-commit", "a" * 40, "--expected-status-sha256", "b" * 64, "--apply"],
        stdout=stdout, stderr=stderr, manager_factory=lambda *args: pytest.fail("must not update"))
    assert code == 0 and calls[0].apply is True
    assert json.loads(stdout.getvalue())["status"] == "closed_interrupted"


def test_closeout_post_replace_sync_failure_is_unknown_not_unwritten(closeout_case, monkeypatch):
    import os
    from app.market_data import after_market_closeout
    real_sync = os.fsync
    calls = 0
    def fail_directory(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("private storage failure")
        real_sync(fd)
    monkeypatch.setattr(after_market_closeout.os, "fsync", fail_directory)
    result = close(closeout_case, apply=True)
    assert result["status"] == "blocked"
    assert result["status_written"] is None
    assert result["error_code"] == "AFTER_MARKET_CLOSEOUT_OUTCOME_UNKNOWN"
    assert result["status_readback"] == "interrupted"
    assert json.loads(closeout_case["path"].read_bytes())["last_run"]["status"] == "interrupted"


def test_committed_pointer_outside_expected_scope_is_still_read(closeout_case):
    case = closeout_case
    case["manager"].catalog.product_partitions = lambda symbol: (object(),)
    def corrupt(partition):
        raise ValueError("PARTITION_UNREADABLE")
    case["manager"].store = SimpleNamespace(read_catalog_partition=corrupt)
    assert close(case, apply=True)["status"] == "blocked"
    assert case["path"].read_bytes() == case["content"]


def test_partial_valid_missing_work_can_close_without_claiming_complete(closeout_case):
    from app.market_data.historical_data_manager import AuditFinding
    case = closeout_case
    finding = AuditFinding("EXPECTED_PARTITION_MISSING", "partition", ("contract", "au", "AU2612", "1m"), 2026, 9)
    case["manager"].audit = lambda request: MaintenanceResult("audit", "failed", request.through, 0, 0, 0, 1, 0, findings=(finding,))
    result = close(case, apply=True)
    assert result["status"] == "closed_interrupted"
    assert result["pending_findings"] == 1
    assert json.loads(case["path"].read_bytes())["last_successful_trading_day"] == "2026-09-08"


def test_continuous_extra_endpoints_cannot_masquerade_as_missing(closeout_case):
    from app.market_data.historical_data_manager import AuditFinding
    case = closeout_case
    finding = AuditFinding("EXPECTED_PARTITION_MISSING", "partition", ("continuous", "au", "MAIN", "1m"), 2026, 9)
    case["manager"].audit = lambda request: MaintenanceResult("audit", "failed", request.through, 0, 0, 0, 1, 0, findings=(finding,))
    case["manager"].coverage = SimpleNamespace(product_start=lambda symbol: datetime(2026, 1, 1).date(),
        expected_bar_ends=lambda *args: ())
    case["manager"].catalog.all_partitions = lambda key: (SimpleNamespace(year=2026, month=9),)
    case["manager"].store = SimpleNamespace(read_catalog_partition=lambda part: (SimpleNamespace(bar_end=datetime(2026, 9, 9)),))
    assert close(case, apply=True)["status"] == "blocked"
    assert case["path"].read_bytes() == case["content"]


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "guard_busy", "guard_missing"])
def test_unsafe_paths_and_live_writer_lock_stop_before_audit(closeout_case, kind):
    import os
    import fcntl
    case = closeout_case
    path = case["path"]
    fd = None
    if kind in {"symlink", "hardlink", "fifo"}:
        target = path.with_name("other.json")
        path.rename(target)
        if kind == "symlink":
            path.symlink_to(target)
        elif kind == "hardlink":
            os.link(target, path)
        else:
            os.mkfifo(path)
    else:
        lock = case["root"] / ".run/live-recovery-guards/after-market.lock"
        if kind == "guard_missing":
            lock.unlink()
        else:
            fd = os.open(lock, os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert close(case, apply=True)["status"] == "blocked"
        assert case["events"] == []
    finally:
        if fd is not None:
            os.close(fd)


def test_real_partial_catalog_and_parquet_closeout_is_readonly(daily_manager, closeout_case):  # noqa: F811
    case = closeout_case
    manager = daily_manager
    raw = json.loads(case["content"])
    raw["current_run"].update(scheduled_date="2025-03-07", started_at="2025-03-07T18:05:00+08:00", products=["jm"])
    raw["last_successful_trading_day"] = "2025-01-31"
    content = json.dumps(raw).encode()
    case["path"].write_bytes(content)
    case["manager"] = manager
    kwargs = dict(products=("jm",), expected_status_sha256=hashlib.sha256(content).hexdigest(),
        now=lambda: datetime.fromisoformat("2025-03-08T08:00:00+08:00"),
        live_store=SimpleNamespace(subscriptions=lambda day: {"jm": "JM2509"}))
    from app.models import MarketPartition
    from sqlalchemy import select
    before = tuple(manager.catalog.session.scalars(select(MarketPartition.file_uri)))
    manager.catalog.session.rollback()
    files = {p: p.read_bytes() for p in manager.store.root.rglob("*.parquet")}
    result = close(case, apply=True, **kwargs)
    assert result["status"] == "closed_interrupted"
    assert result["pending_findings"] > 0
    assert manager.provider.calls == [] and manager.metadata.calls == []
    assert tuple(manager.catalog.session.scalars(select(MarketPartition.file_uri))) == before
    assert all(p.read_bytes() == data for p, data in files.items())


def test_running_loaded_service_cannot_be_closed_even_without_lock():
    from app.market_data.captured_recovery_runtime import _verify_loaded_service, CapturedRecoveryRuntimeError
    from pathlib import Path
    output = 'service = {\n state = running\n pid = 123\n working directory = /fixture\n environment = {\n GUIYI_PROJECT_ROOT => /fixture\n GUIYI_RUNTIME_COMMIT => ' + 'a' * 40 + '\n }\n}\n'
    with pytest.raises(CapturedRecoveryRuntimeError):
        _verify_loaded_service(output, root=Path("/fixture"), commit="a" * 40, allow_idle=True, require_idle=True)


def test_finish_clock_reversal_preserves_original_state(closeout_case):
    case = closeout_case
    times = iter([datetime.fromisoformat("2026-09-10T08:00:00+08:00"), datetime.fromisoformat("2026-09-08T08:00:00+08:00")])
    assert close(case, apply=True, now=lambda: next(times))["status"] == "blocked"
    assert case["path"].read_bytes() == case["content"]


def test_closeout_requires_loaded_recovery_guard_declaration():
    from app.market_data.captured_recovery_runtime import _verify_loaded_service, CapturedRecoveryRuntimeError
    from pathlib import Path
    output = 'service = {\n state = running\n pid = 123\n working directory = /fixture\n environment = {\n GUIYI_PROJECT_ROOT => /fixture\n GUIYI_RUNTIME_COMMIT => ' + 'a' * 40 + '\n }\n}\n'
    with pytest.raises(CapturedRecoveryRuntimeError):
        _verify_loaded_service(output, root=Path("/fixture"), commit="a" * 40, require_guard=True)


def test_closed_interrupted_schema_is_readable_but_cannot_authorize_same_day_live_repair(monkeypatch):
    from app.guiyi_cli import captured_recovery
    monkeypatch.setattr(captured_recovery, "read_captured_file", lambda *args: json.dumps(interrupted_status()).encode())
    with pytest.raises(captured_recovery.CapturedRecoveryCliError):
        captured_recovery._after_market_preflight(datetime(2026, 9, 9).date())
    captured_recovery._after_market_preflight(datetime(2026, 9, 10).date())


def test_status_drift_after_audit_never_overwrites_new_run(closeout_case):
    case = closeout_case
    audit = case["manager"].audit
    replacement = case["content"] + b" "
    def drift(request):
        result = audit(request)
        case["path"].write_bytes(replacement)
        return result
    case["manager"].audit = drift
    assert close(case, apply=True)["status"] == "blocked"
    assert case["path"].read_bytes() == replacement


def test_runtime_directory_replacement_cannot_redirect_pinned_closeout(closeout_case):
    case = closeout_case
    audit = case["manager"].audit
    displaced = case["root"] / "displaced"
    def drift(request):
        result = audit(request)
        case["path"].parent.rename(displaced)
        case["path"].parent.mkdir(mode=0o700)
        case["path"].write_bytes(case["content"])
        return result
    case["manager"].audit = drift
    assert close(case, apply=True)["status"] == "blocked"
    assert (displaced / case["path"].name).read_bytes() == case["content"]
    assert case["path"].read_bytes() == case["content"]


def missing_interrupted_status():
    raw = interrupted_status()
    raw.update(schema_version=5, last_interruption={
        "trading_day": "2026-09-09", "started_at": "2026-09-09T18:05:00+08:00",
        "closed_at": "2026-09-10T08:00:00+08:00", "snapshot_checked_at": "2026-09-10T08:00:00+08:00",
        "snapshot_classification": "not_verified_missing", "reconciliation_verified": False,
    })
    return raw


@pytest.mark.parametrize("today", ["2026-09-09T21:00:00+08:00", "2026-09-10T08:00:00+08:00"])
@pytest.mark.parametrize("snapshot,classification,verified", [
    (None, "not_verified_missing", False), ({"au": "AU2612"}, "verified_match", True),
])
def test_same_or_old_day_closeout_records_observed_evidence(closeout_case, today, snapshot, classification, verified):
    calls = []
    def subscriptions(day):
        calls.append(day.isoformat())
        return snapshot
    result = close(closeout_case, apply=True, now=lambda: datetime.fromisoformat(today),
        live_store=SimpleNamespace(subscriptions=subscriptions))
    assert result["status"] == "closed_interrupted"
    assert calls == ["2026-09-09", "2026-09-09"]
    assert closeout_case["events"] == ["lock", "audit", "release"]
    raw = json.loads(closeout_case["path"].read_bytes())
    assert raw["schema_version"] == 5
    evidence = raw["last_interruption"]
    assert evidence == {"trading_day": "2026-09-09", "started_at": "2026-09-09T18:05:00+08:00",
        "closed_at": today, "snapshot_checked_at": today, "snapshot_classification": classification,
        "reconciliation_verified": verified}
    assert public_after_market_status(raw)["last_interruption"] == evidence
    assert result["last_interruption"] == evidence
    assert raw["last_successful_trading_day"] == "2026-09-08"


@pytest.mark.parametrize("snapshot", [{}, [], {"au": "AU2610"}, {"au": None},
    {"au": "AU2612", "ag": "AG2612"}, {"au": "AU2612", " AU ": "AU2612"},
    {"au": "AU2612", 1: 2}])
def test_present_invalid_or_mismatching_snapshot_is_never_missing(closeout_case, snapshot):
    result = close(closeout_case, apply=True, live_store=SimpleNamespace(subscriptions=lambda day: snapshot))
    assert result["status"] == "blocked" and result["status_written"] is False
    assert closeout_case["path"].read_bytes() == closeout_case["content"]


@pytest.mark.parametrize("snapshots", [
    [None, {"au": "AU2612"}], [{"au": "AU2612"}, None],
    [{"au": "AU2612"}, {"au": "au2612"}], [None, {}],
])
def test_snapshot_change_between_audit_and_replace_blocks_without_retry(closeout_case, snapshots):
    values = iter(snapshots)
    result = close(closeout_case, apply=True, live_store=SimpleNamespace(subscriptions=lambda day: next(values)))
    assert result["status"] == "blocked" and result["status_written"] is False
    assert closeout_case["path"].read_bytes() == closeout_case["content"]


@pytest.mark.parametrize("failing_read", [1, 2])
def test_snapshot_read_error_is_not_absence(closeout_case, failing_read):
    calls = 0
    def subscriptions(day):
        nonlocal calls
        calls += 1
        if calls == failing_read:
            raise ConnectionError("private Redis details")
        return None
    result = close(closeout_case, apply=True, live_store=SimpleNamespace(subscriptions=subscriptions))
    assert result["status"] == "blocked" and result["status_written"] is False
    assert "private" not in json.dumps(result)
    assert closeout_case["path"].read_bytes() == closeout_case["content"]


@pytest.mark.parametrize("today", ["2026-09-09T18:04:59+08:00", "2026-09-09T21:00:00"])
def test_future_start_or_naive_clock_blocks_before_audit(closeout_case, today):
    result = close(closeout_case, apply=True, now=lambda: datetime.fromisoformat(today))
    assert result["status"] == "blocked"
    assert closeout_case["events"] == []


def test_missing_snapshot_never_skips_physical_audit(closeout_case):
    closeout_case["manager"].catalog.product_partitions = lambda symbol: (object(),)
    def unreadable(partition):
        raise ValueError("PARTITION_UNREADABLE")
    closeout_case["manager"].store = SimpleNamespace(read_catalog_partition=unreadable)
    result = close(closeout_case, apply=True, live_store=SimpleNamespace(subscriptions=lambda day: None))
    assert result["status"] == "blocked" and result["status_written"] is False
    assert closeout_case["events"] == ["lock", "release"]


@pytest.mark.parametrize("change", [
    {"snapshot_classification": "missing"}, {"reconciliation_verified": True},
    {"reconciliation_verified": 0}, {"snapshot_checked_at": "invalid"},
    {"trading_day": "2026-09-08"}, {"closed_at": "2026-09-09T00:00:00+08:00"},
])
def test_v5_reader_rejects_inconsistent_interruption_evidence(change):
    raw = missing_interrupted_status()
    raw["last_interruption"].update(change)
    assert public_after_market_status(raw) == {}


def test_v5_reader_and_health_expose_missing_evidence(tmp_path, monkeypatch):
    from app.services import runtime_health
    from app.schemas.runtime import RuntimeAfterMarketHealth
    raw = missing_interrupted_status()
    public = public_after_market_status(raw)
    assert public["last_interruption"] == raw["last_interruption"]
    path = tmp_path / "status.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(runtime_health, "_expected_after_market_day", lambda *args, **kwargs: (datetime(2026, 9, 8).date(), False))
    result = runtime_health._collect_after_market_health(None, status_path=path, configured_enabled=True,
        now=datetime.fromisoformat("2026-09-10T09:00:00+08:00"))
    assert result["run_state"] == "interrupted" and result["status"] == "degraded"
    assert RuntimeAfterMarketHealth.model_validate(result).model_dump()["last_interruption"] == raw["last_interruption"]
    from app.market_data.runtime_promotion import _after_market_status_decision
    assert _after_market_status_decision(raw, trading_day=datetime(2026, 9, 9).date(), products=("au",),
        now=datetime.fromisoformat("2026-09-10T09:00:00+08:00")) == "missing"


def test_v5_captured_reader_retains_same_day_repair_block(monkeypatch):
    from app.guiyi_cli import captured_recovery
    monkeypatch.setattr(captured_recovery, "read_captured_file", lambda *args: json.dumps(missing_interrupted_status()).encode())
    with pytest.raises(captured_recovery.CapturedRecoveryCliError):
        captured_recovery._after_market_preflight(datetime(2026, 9, 9).date())
    captured_recovery._after_market_preflight(datetime(2026, 9, 10).date())


def test_v5_missing_evidence_stays_visible_when_expected_calendar_is_unavailable(tmp_path, monkeypatch):
    from app.services import runtime_health
    raw = missing_interrupted_status()
    path = tmp_path / "status.json"
    path.write_text(json.dumps(raw))
    def unavailable(*args, **kwargs):
        raise ValueError("TRADING_SESSION_MISSING")
    monkeypatch.setattr(runtime_health, "_expected_after_market_day", unavailable)
    result = runtime_health._collect_after_market_health(None, status_path=path, configured_enabled=True,
        now=datetime.fromisoformat("2026-09-10T09:00:00+08:00"))
    assert result["status"] == "degraded"
    assert result["error_type"] == "after_market_expected_day_invalid"
    assert result["last_interruption"] == raw["last_interruption"]


@pytest.mark.parametrize("run", ["last_run", "current_run"])
def test_v5_reader_rejects_interruption_closed_after_later_run_started(run):
    raw = missing_interrupted_status()
    if run == "last_run":
        raw["last_run"].update(status="passed", attempts=1, error_code=None,
            started_at="2026-09-10T07:59:00+08:00", finished_at="2026-09-10T09:00:00+08:00")
    else:
        raw["current_run"] = {"scheduled_date": "2026-09-10", "started_at": "2026-09-10T07:59:00+08:00",
            "products": ["au"], "attempt": 0, "stage": "calendar", "updated_at": "2026-09-10T07:59:00+08:00",
            "stage_started_at": "2026-09-10T07:59:00+08:00", "elapsed_seconds": 0.0,
            "current_partition": None, "current_symbol": None, "counters": {}, "stage_durations": {}, "retry_at": None}
    assert public_after_market_status(raw) == {}


def test_v5_future_interruption_without_last_run_cannot_authorize_promotion(tmp_path, monkeypatch):
    from app.services import runtime_health
    from app.market_data.runtime_promotion import _after_market_status_decision
    raw = missing_interrupted_status()
    raw["last_run"] = None
    now = datetime.fromisoformat("2026-09-10T07:00:00+08:00")
    assert _after_market_status_decision(raw, trading_day=now.date(), products=("au",), now=now) == "unavailable"
    path = tmp_path / "status.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(runtime_health, "_expected_after_market_day", lambda *a, **k: (now.date(), False))
    result = runtime_health._collect_after_market_health(None, status_path=path, configured_enabled=True, now=now)
    assert result["error_type"] == "after_market_status_invalid"


@pytest.mark.parametrize("drift", ["restart", "guard"])
def test_missing_snapshot_does_not_bypass_identity_or_guard_drift(closeout_case, drift):
    case = closeout_case
    calls = 0
    def identity(*args):
        nonlocal calls
        calls += 1
        if drift == "restart" and calls == 3:
            raise ValueError("process restarted")
    audit = case["manager"].audit
    def changed_guard(request):
        result = audit(request)
        guard = case["root"] / ".run/live-recovery-guards/after-market.lock"
        guard.rename(guard.with_suffix(".old"))
        guard.touch(mode=0o600)
        return result
    if drift == "guard":
        case["manager"].audit = changed_guard
    result = close(case, apply=True, verify_identity=identity,
        live_store=SimpleNamespace(subscriptions=lambda day: None))
    assert result["status"] == "blocked" and result["status_written"] is False
    assert case["path"].read_bytes() == case["content"]


def test_concurrent_closeout_cannot_publish_while_first_holds_writer_guard(closeout_case):
    case = closeout_case
    audit = case["manager"].audit
    contender = []
    def competing_closeout(request):
        contender.append(close(case, apply=True))
        return audit(request)
    case["manager"].audit = competing_closeout
    assert close(case, apply=True, live_store=SimpleNamespace(subscriptions=lambda day: None))["status"] == "closed_interrupted"
    assert len(contender) == 1 and contender[0]["status"] == "blocked"
    assert contender[0]["status_written"] is False


def test_missing_snapshot_closeout_cas_rejects_state_change_during_temporary_sync(closeout_case, monkeypatch):
    from app.market_data import after_market_closeout
    real_sync = after_market_closeout.os.fsync
    newer = closeout_case["content"] + b" "
    def drift(fd):
        closeout_case["path"].write_bytes(newer)
        real_sync(fd)
    monkeypatch.setattr(after_market_closeout.os, "fsync", drift)
    result = close(closeout_case, apply=True, live_store=SimpleNamespace(subscriptions=lambda day: None))
    assert result["status"] == "blocked" and result["status_written"] is False
    assert closeout_case["path"].read_bytes() == newer


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_legacy_schema_never_inherits_v5_interruption_evidence(version):
    raw = missing_interrupted_status()
    raw.update(schema_version=version)
    if version < 4:
        raw["last_run"].update(status="failed", attempts=1, error_code="UPDATE_FAILED")
    public = public_after_market_status(raw)
    assert public and "last_interruption" not in public


@pytest.mark.parametrize("drift", ["restart", "guard", "directory"])
def test_second_snapshot_read_cannot_bypass_final_identity_checks(closeout_case, drift):
    case = closeout_case
    reads = 0
    restarted = False
    displaced = case["root"] / "displaced"
    def subscriptions(day):
        nonlocal reads, restarted
        reads += 1
        if reads == 2:
            if drift == "restart":
                restarted = True
            elif drift == "guard":
                guard = case["root"] / ".run/live-recovery-guards/after-market.lock"
                guard.rename(guard.with_suffix(".old"))
                guard.touch(mode=0o600)
            else:
                case["path"].parent.rename(displaced)
                case["path"].parent.mkdir(mode=0o700)
                # Keep the guard inode visible so the directory check is independently required.
                (displaced / "live-recovery-guards").rename(case["path"].parent / "live-recovery-guards")
                case["path"].write_bytes(case["content"])
        return None
    def verify(*args):
        if restarted:
            raise ValueError("consumer restarted")
    result = close(case, apply=True, verify_identity=verify,
        live_store=SimpleNamespace(subscriptions=subscriptions))
    assert reads == 2
    assert result["status"] == "blocked" and result["status_written"] is False
    assert case["path"].read_bytes() == case["content"]
    if drift == "directory":
        assert (displaced / case["path"].name).read_bytes() == case["content"]


def test_snapshot_timestamp_precedes_final_identity_check_completion(closeout_case):
    times = iter(["2026-09-10T08:00:00+08:00", "2026-09-10T08:10:00+08:00", "2026-09-10T08:12:00+08:00"])
    result = close(closeout_case, apply=True, now=lambda: datetime.fromisoformat(next(times)))
    assert result["status"] == "closed_interrupted"
    evidence = result["last_interruption"]
    assert evidence["snapshot_checked_at"] == "2026-09-10T08:10:00+08:00"
    assert evidence["closed_at"] == "2026-09-10T08:12:00+08:00"
