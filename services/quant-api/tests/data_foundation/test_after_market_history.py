from datetime import UTC, datetime
import json

import pytest

from app.market_data.after_market_history import NAME, make_history, publish_history, read_history

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
PRODUCTS = ("au",)


def evidence():
    return make_history(json.dumps({"schema_version": 3, "current_run": None,
        "last_run": {"trading_day": "2026-09-30", "status": "passed", "attempts": 1,
            "started_at": "2026-09-30T18:05:00+08:00", "finished_at": "2026-09-30T18:11:00+08:00",
            "products": ["au"], "error_code": None},
        "last_successful_trading_day": "2026-09-30", "last_failure": None}).encode(),
        commit="a" * 40, products=PRODUCTS, now=NOW)


def test_history_create_once_and_reject_conflicting_overwrite(tmp_path):
    path = tmp_path / NAME
    value = evidence()
    assert publish_history(path, value) == "retained"
    assert publish_history(path, value) == "already_retained"
    assert path.stat().st_mode & 0o777 == 0o600
    assert read_history(path, products=PRODUCTS, now=NOW) == value
    with pytest.raises(ValueError, match="CONFLICT"):
        publish_history(path, {**value, "source_commit": "b" * 40})
    assert read_history(path, products=PRODUCTS, now=NOW) == value


def test_proof_rejects_tampered_scope_digest_and_future_time(tmp_path):
    path = tmp_path / NAME
    value = evidence()
    publish_history(path, value)
    with pytest.raises(ValueError):
        read_history(path, products=("rb",), now=NOW)
    with pytest.raises(ValueError):
        read_history(path, products=PRODUCTS, now=datetime(2026, 9, 30, tzinfo=UTC))
    value["status"]["last_successful_trading_day"] = "2026-10-01"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        read_history(path, products=PRODUCTS, now=NOW)


def test_history_rejects_symlink_and_fifo_without_blocking(tmp_path):
    import os
    target = tmp_path / "target"
    publish_history(target, evidence())
    path = tmp_path / NAME
    path.symlink_to(target)
    with pytest.raises(OSError):
        read_history(path, products=PRODUCTS, now=NOW)
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(ValueError):
        read_history(path, products=PRODUCTS, now=NOW)


@pytest.mark.parametrize("state", ["failed", "interrupted", "running", "stuck", "degraded"])
def test_retained_success_never_hides_current_negative_state(tmp_path, monkeypatch, state):
    from app.services import runtime_health as health
    publish_history(tmp_path / NAME, evidence())
    current = {"status": "degraded", "run_state": state, "last_successful_trading_day": None,
               "expected_trading_day": "2026-09-30", "current_run": None, "last_run": None}
    monkeypatch.setattr(health, "_collect_current_after_market_health", lambda *a, **kw: current)
    monkeypatch.setattr(health, "load_operational_products", lambda: PRODUCTS)
    assert health._collect_after_market_health(None, tmp_path / "after-market-status.json",
            now=NOW, configured_enabled=True) == current


@pytest.mark.parametrize("state", ["pending", "missed", "completed"])
def test_success_is_retained_with_provenance_and_no_synthetic_run(tmp_path, monkeypatch, state):
    from app.services import runtime_health as health
    publish_history(tmp_path / NAME, evidence())
    current = {"status": "pending", "run_state": state, "last_successful_trading_day": None,
               "expected_trading_day": "2026-09-30", "current_run": None, "last_run": None}
    monkeypatch.setattr(health, "_collect_current_after_market_health", lambda *a, **kw: current)
    monkeypatch.setattr(health, "load_operational_products", lambda: PRODUCTS)
    result = health._collect_after_market_health(None, tmp_path / "after-market-status.json",
            now=NOW, configured_enabled=True)
    assert result["status"] == "ok" and result["run_state"] == "retained"
    assert result["last_run"] is None and result["current_run"] is None
    assert result["retained_success"]["source_commit"] == "a" * 40
    assert not (tmp_path / "after-market-status.json").exists()
    current["expected_trading_day"] = "2026-10-09"
    result = health._collect_after_market_health(None, tmp_path / "after-market-status.json",
            now=NOW, configured_enabled=True)
    assert result["status"] == "degraded" and result["run_state"] == "missed"


def test_invalid_history_is_degraded(tmp_path, monkeypatch):
    from app.services import runtime_health as health
    (tmp_path / NAME).write_text("{}")
    monkeypatch.setattr(health, "_collect_current_after_market_health", lambda *a, **kw:
                        {"status": "pending", "run_state": "pending"})
    monkeypatch.setattr(health, "load_operational_products", lambda: PRODUCTS)
    result = health._collect_after_market_health(None, tmp_path / "after-market-status.json",
            now=NOW, configured_enabled=True)
    assert result["error_type"] == "after_market_history_invalid"


def test_api_schema_preserves_retained_origin():
    from app.schemas.runtime import RuntimeAfterMarketHealth
    value = evidence()
    public = RuntimeAfterMarketHealth(status="ok", run_state="retained", retained_success={
        "trading_day": "2026-09-30", "source_commit": value["source_commit"],
        "source_status_sha256": value["source_status_sha256"], "source_run_started_at": "x",
        "source_run_finished_at": "y", "source_run_status": "passed", "retained_at": value["retained_at"]})
    assert public.model_dump()["retained_success"]["source_commit"] == "a" * 40


def test_future_trading_day_rejected():
    value = evidence()["status"]
    value["last_run"]["trading_day"] = "2030-01-01"
    value["last_successful_trading_day"] = "2030-01-01"
    with pytest.raises(ValueError):
        make_history(json.dumps(value).encode(), commit="a" * 40, products=PRODUCTS, now=NOW)


def test_failed_then_skipped_is_not_hidden_by_retained_same_day_success(tmp_path, monkeypatch):
    from app.services import runtime_health as health
    publish_history(tmp_path / NAME, evidence())
    current = {"status": "degraded", "run_state": "missed", "last_successful_trading_day": None,
        "expected_trading_day": "2026-09-30", "current_run": None,
        "last_run": {"status": "skipped"},
        "last_failure": {"trading_day": "2026-09-30", "error_code": "COMMIT_OUTCOME_UNKNOWN"}}
    monkeypatch.setattr(health, "_collect_current_after_market_health", lambda *a, **kw: current)
    monkeypatch.setattr(health, "load_operational_products", lambda: PRODUCTS)
    assert health._collect_after_market_health(None, tmp_path / "after-market-status.json",
                now=NOW, configured_enabled=True) == current


def test_supervised_retention_idempotent_after_failed_install_and_next_release(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import subprocess
    from app.market_data import after_market_history as module
    from app.market_data import runtime_status_authority, operational_universe
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(module, "datetime", FixedDatetime)
    monkeypatch.setattr(operational_universe, "load_operational_products", lambda: PRODUCTS)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "a" * 40)
    source, target, next_target = [tmp_path / name for name in ("old", "new", "next")]
    for root in (source, target, next_target):
        (root / ".run").mkdir(parents=True)
    source_status = source / ".run/after-market-status.json"
    source_status.write_text(json.dumps(evidence()["status"]))
    authority = SimpleNamespace(path=source_status, mode="loaded", recheck=lambda: None)
    monkeypatch.setattr(runtime_status_authority, "resolve_market_runtime_status_authority", lambda **kw: authority)
    assert module.retain_from_supervised(target, apply=False) == "ready"
    assert not (target / ".run" / NAME).exists()
    assert module.retain_from_supervised(target, apply=True) == "retained"
    assert module.retain_from_supervised(target, apply=True) == "already_retained"
    assert module.retain_from_supervised(source, apply=True) == "same_runtime"
    authority.path = target / ".run/after-market-status.json"
    assert module.retain_from_supervised(next_target, apply=True) == "retained"
    assert (next_target / ".run" / NAME).read_bytes() == (target / ".run" / NAME).read_bytes()


def test_retained_failure_is_visible_without_fabricating_natural_run(tmp_path, monkeypatch):
    from app.services import runtime_health as health
    value = evidence()["status"]
    value["last_run"].update(status="failed", error_code="COMMIT_OUTCOME_UNKNOWN")
    value["last_successful_trading_day"] = None
    value["last_failure"] = {"trading_day": "2026-09-30", "error_code": "COMMIT_OUTCOME_UNKNOWN"}
    value = make_history(json.dumps(value).encode(), commit="a" * 40, products=PRODUCTS, now=NOW)
    publish_history(tmp_path / NAME, value)
    current = {"status": "pending", "run_state": "pending", "last_successful_trading_day": None,
               "expected_trading_day": "2026-09-30", "current_run": None, "last_run": None}
    monkeypatch.setattr(health, "_collect_current_after_market_health", lambda *a, **kw: current)
    monkeypatch.setattr(health, "load_operational_products", lambda: PRODUCTS)
    result = health._collect_after_market_health(None, tmp_path / "after-market-status.json", now=NOW, configured_enabled=True)
    assert result["status"] == "degraded" and result["run_state"] == "failed"
    assert result["last_run"] is None
    assert result["retained_failure"]["source_commit"] == "a" * 40


def test_failure_then_skip_without_success_is_valid_negative_evidence(tmp_path):
    value = evidence()["status"]
    value["last_run"].update(status="skipped", attempts=0, error_code="NON_TRADING_DAY")
    value["last_successful_trading_day"] = None
    value["last_failure"] = {"trading_day": "2026-09-30", "error_code": "COMMIT_OUTCOME_UNKNOWN"}
    value = make_history(json.dumps(value).encode(), commit="a" * 40, products=PRODUCTS, now=NOW)
    publish_history(tmp_path / NAME, value)
    assert read_history(tmp_path / NAME, products=PRODUCTS, now=NOW)["status"]["last_failure"]["error_code"] == "COMMIT_OUTCOME_UNKNOWN"


def test_install_guard_excludes_writer_through_installer_and_is_released(tmp_path, monkeypatch):
    import fcntl
    import os
    from types import SimpleNamespace
    from app.market_data import after_market_history as module, runtime_status_authority
    source, target = tmp_path / "source", tmp_path / "target"
    guard = source / ".run/live-recovery-guards/after-market.lock"
    guard.parent.mkdir(parents=True, mode=0o700)
    guard.touch(mode=0o600)
    target.mkdir()
    authority = SimpleNamespace(path=source / ".run/after-market-status.json", mode="loaded", recheck=lambda: None)
    monkeypatch.setattr(runtime_status_authority, "resolve_market_runtime_status_authority", lambda **kw: authority)
    calls = []
    def installer(args, **kwargs):
        inherited = kwargs["pass_fds"][0]
        monkeypatch.setenv("GUIYI_MARKET_INSTALL_GUARD_FD", str(inherited))
        module.verify_install_guard(target)
        other = os.open(guard, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(other)
        calls.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, "run", installer)
    assert module.install_with_history_guard(target) == 0
    assert calls[0][-1] == "--confirm-market-runtime"
    fd = os.open(guard, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.close(fd)
