from datetime import date, datetime
from types import SimpleNamespace
import json
import pytest

from app.market_data.after_market import AfterMarketResult
from app.market_data.late_provider_recovery import (
    schedule_failure,
    run_scheduled,
    recovery_health,
)
from app.market_data.operational_universe import load_operational_products
from app.market_data.session_clock import SHANGHAI

DAY = date(2026, 9, 30)
PRODUCTS = load_operational_products()


def clock(day, hour=19, minute=5):
    return datetime(2026, 10, day, hour, minute, tzinfo=SHANGHAI)


def scheduled(tmp_path):
    path = tmp_path / "late.json"
    schedule_failure(
        path,
        AfterMarketResult("failed", DAY, 2, "RQDATA_NOT_READY"),
        PRODUCTS,
        datetime(2026, 9, 30, 18, 5, tzinfo=SHANGHAI),
    )
    return path


def runner(path, current, ready=lambda day: False, manager=None, **kw):
    return run_scheduled(
        manager,
        path=path,
        now=lambda: current,
        ready=ready,
        invalidate=lambda: None,
        verify_identity=lambda: None,
        live_store=SimpleNamespace(
            publish_state=lambda data: None, cleanup_trading_day=lambda day: None
        ),
        **kw,
    )


def test_due_two_calendar_days_in_holiday_and_only_once(tmp_path):
    path = scheduled(tmp_path)
    calls = []
    assert runner(path, clock(2, 19, 4))["status"] == "not_due"
    assert (
        runner(path, clock(2), ready=lambda day: calls.append(day) or False)["status"]
        == "failed"
    )
    runner(path, clock(2), ready=lambda day: calls.append(day) or True)
    assert calls == [DAY]
    assert json.loads(path.read_text())["runs"][DAY.isoformat()]["checks"] == 1


def test_same_original_failure_does_not_reschedule(tmp_path):
    path = scheduled(tmp_path)
    runner(path, clock(2))
    original = path.read_bytes()
    schedule_failure(
        path,
        AfterMarketResult("failed", DAY, 2, "RQDATA_NOT_READY"),
        PRODUCTS,
        clock(2),
    )
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "error",
    ["UPDATE_FAILED", "COMMIT_OUTCOME_UNKNOWN", "HISTORICAL_MAINTENANCE_REQUIRED"],
)
def test_unknown_or_partial_failures_are_never_eligible(tmp_path, error):
    path = tmp_path / "late.json"
    schedule_failure(
        path, AfterMarketResult("failed", DAY, 2, error), PRODUCTS, clock(2)
    )
    assert not path.exists()


def test_expired_trigger_never_calls_provider(tmp_path):
    path = scheduled(tmp_path)
    assert (
        runner(path, clock(3), ready=lambda day: pytest.fail("late trigger"))["status"]
        == "expired"
    )
    assert recovery_health(path, clock(3))["status"] == "degraded"


def test_crash_after_claim_never_retries(tmp_path):
    path = scheduled(tmp_path)

    def crash(day):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        runner(path, clock(2), ready=crash)
    assert (
        runner(path, clock(2), ready=lambda day: pytest.fail("repeated"))["status"]
        == "not_due"
    )
    assert recovery_health(path, clock(2))["status"] == "degraded"


def test_exact_recovery_hash_and_fresh_readback(tmp_path):
    path = scheduled(tmp_path)
    calls = []

    class Manager:
        catalog = SimpleNamespace(
            acquire_maintenance_lock=lambda: SimpleNamespace(
                release=lambda: calls.append("release")
            )
        )
        metadata = SimpleNamespace(
            synchronize_current_day=lambda products, day: calls.append((products, day))
        )

        def daily_recovery(self, request, **kw):
            calls.append((request, kw))
            return SimpleNamespace(
                plan_sha256="a" * 64,
                target_windows=(),
                maintenance=SimpleNamespace(status="passed"),
            )

    assert (
        runner(path, clock(2), ready=lambda day: True, manager=Manager())["status"]
        == "passed"
    )
    requests = [
        item for item in calls if isinstance(item, tuple) and hasattr(item[0], "apply")
    ]
    assert [item[0].apply for item in requests] == [False, True, False]
    assert all(
        item[0].through == DAY and item[0].products == PRODUCTS for item in requests
    )
    assert requests[1][1]["expected_plan_sha256"] == "a" * 64


def test_scope_drift_fails_before_provider(tmp_path):
    path = scheduled(tmp_path)
    payload = json.loads(path.read_text())
    payload["runs"][DAY.isoformat()]["products"] = ["rs"]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="STATE_INVALID"):
        runner(path, clock(2), ready=lambda day: pytest.fail("scope drift"))


@pytest.mark.parametrize("stage", ["metadata", "apply", "readback"])
def test_failure_after_claim_never_repeats_recovery(tmp_path, stage):
    path = scheduled(tmp_path)
    calls = []

    def sync(*args):
        if stage == "metadata":
            raise RuntimeError("private provider details")

    class Manager:
        catalog = SimpleNamespace(
            acquire_maintenance_lock=lambda: SimpleNamespace(release=lambda: None)
        )
        metadata = SimpleNamespace(synchronize_current_day=sync)

        def daily_recovery(self, request, **kw):
            calls.append(request.apply)
            if request.apply and stage == "apply":
                raise RuntimeError("COMMIT_OUTCOME_UNKNOWN")
            remaining = ("missing",) if len(calls) == 3 and stage == "readback" else ()
            return SimpleNamespace(
                plan_sha256="a" * 64,
                target_windows=remaining,
                maintenance=SimpleNamespace(status="passed"),
            )

    assert (
        runner(path, clock(2), ready=lambda day: True, manager=Manager())["status"]
        == "failed"
    )
    before = list(calls)
    runner(path, clock(2), ready=lambda day: pytest.fail("retry"), manager=Manager())
    assert calls == before
    assert "private" not in path.read_text()


@pytest.mark.parametrize(
    "kind", ["symlink", "dangling", "hardlink", "directory", "writable"]
)
def test_unsafe_owned_state_rejected_without_provider_or_replacement(tmp_path, kind):
    import os

    path = tmp_path / "late.json"
    other = tmp_path / "other.json"
    other.write_text('{"schema_version":1,"runs":{}}')
    if kind == "symlink":
        path.symlink_to(other)
    elif kind == "dangling":
        path.symlink_to(tmp_path / "missing")
    elif kind == "hardlink":
        os.link(other, path)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_text(other.read_text())
        path.chmod(0o666)
    before = other.read_bytes()
    with pytest.raises((ValueError, OSError)):
        runner(path, clock(2), ready=lambda day: pytest.fail("unsafe state"))
    assert other.read_bytes() == before


def test_claim_directory_fsync_failure_blocks_provider(tmp_path, monkeypatch):
    import os
    import stat

    path = scheduled(tmp_path)
    real = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("fixture failure")
        real(fd)

    monkeypatch.setattr(os, "fsync", fail_directory)
    with pytest.raises(OSError):
        runner(path, clock(2), ready=lambda day: pytest.fail("non durable claim"))
