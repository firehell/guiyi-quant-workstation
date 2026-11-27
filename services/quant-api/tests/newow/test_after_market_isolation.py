from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.market_data.after_market import _atomic_write_status
from app.services import newow_backtest_eod as eod


def _status(day, *, finished=None, product="fu"):
    started = f"{finished or day}T18:05:00+08:00"
    ended = f"{finished or day}T18:10:00+08:00"
    return {
        "schema_version": 4, "last_successful_trading_day": str(day),
        "last_run": {
            "status": "passed", "trading_day": str(day), "attempts": 1,
            "started_at": started, "finished_at": ended, "products": [product],
            "error_code": None,
            "historical_publications": [{
                "dataset": ["contract", product, product.upper() + "2605", "1m"],
                "year": day.year, "month": day.month,
                "file_name": "part." + "b" * 64 + ".parquet",
                "provenance": {"version": 1, "input_source": "historical_provider", "input_sha256": "b" * 64},
            }],
        },
    }


def test_outbox_recovers_duplicate_failure_and_historical_revision(tmp_path, monkeypatch):
    path = tmp_path / "after-market-status.json"
    config = tmp_path / "config.json"
    config.write_text("test-config")
    old = date(2026, 1, 5)
    latest = old + timedelta(days=1)
    calls = []
    crash = True

    def consume(status, day, config_path, *, latest_days, publication_is_stable, publication_fence):
        nonlocal crash
        assert publication_is_stable()
        calls.append((day, latest_days["fu"]))
        if crash:
            crash = False
            return [{"status": "UNKNOWN", "code": "BACKTEST_JOB_BUSY"}]
        return [{"status": "SUCCEEDED"}]

    monkeypatch.setattr(eod, "consume_status", consume)
    _atomic_write_status(path, _status(old))
    eod.retain_publication(path)
    _atomic_write_status(path, _status(latest))
    first = eod.reconcile_publications(path, config)
    assert [row["deferred"] for row in first] == [1, 0]
    assert calls == [(latest, latest), (old, latest)]
    assert len(eod.reconcile_publications(path, config)) == 1
    assert eod.reconcile_publications(path, config) == []

    revision = _status(old, finished=latest + timedelta(days=1))
    partial = {**revision, "last_run": {**revision["last_run"], "status": "failed", "error_code": "UPDATE_FAILED"}}
    _atomic_write_status(path, partial)
    assert eod.reconcile_publications(path, config) == []
    _atomic_write_status(path, revision)
    report, = eod.reconcile_publications(path, config)
    assert calls[-1] == (old, latest)
    assert report["trigger"] == "canonical_publication"
    assert report["computed"] == 1
    assert report["failed"] == []
    assert report["publication_to_completion_seconds"] >= 0
    assert eod.reconcile_publications(path, config) == []


def test_isolated_http_and_legacy_workers_do_not_dispatch_reference(monkeypatch):
    from app import develop_preview
    from app.market_data.newow.home_recovery import run_home_build, run_home_recovery_forever
    from app.reference_trading.worker_entry import _open_forward_worker
    import pytest

    calls = []
    monkeypatch.setenv("GUIYI_NEWOW_REFERENCE_MODE", "after_market_isolated")
    monkeypatch.setattr(eod, "reconcile_publications", lambda *_: calls.append("publication"))
    monkeypatch.setattr(develop_preview, "run_develop_recovery", lambda *_: calls.append("home"))
    with TestClient(develop_preview.create_develop_app()) as client:
        for name in ("strategy-detail", "historical-snapshot", "daily-snapshot", "weekly-snapshot",
                     "ai-analysis", "experiments"):
            response = client.get(f"/api/v1/market/newow/{name}")
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "NEWOW_AFTER_MARKET_ONLY"
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/market/newow/product-capabilities").status_code != 409
    for run in (run_home_build, run_home_recovery_forever):
        with pytest.raises(RuntimeError, match="NEWOW_AFTER_MARKET_ONLY"):
            run()
    with pytest.raises(RuntimeError, match="NEWOW_AFTER_MARKET_ONLY"), _open_forward_worker():
        pass
    assert calls == []



def test_skipped_maintenance_keeps_last_durable_authority(tmp_path):
    path = tmp_path / "after-market-status.json"
    day = date(2026, 1, 9)
    original = _status(day)
    _atomic_write_status(path, original)
    expected = eod._current_authority(path)
    eod.retain_publication(path)
    weekend = day + timedelta(days=1)
    skipped = _status(weekend)
    skipped["last_successful_trading_day"] = str(day)
    skipped["last_run"].update(status="skipped", attempts=0, error_code="NON_TRADING_DAY")
    del skipped["last_run"]["historical_publications"]
    _atomic_write_status(path, skipped)
    assert expected is not None and eod._current_authority(path) == expected


def test_distinct_late_success_cannot_clear_unsettled_newer_normal_publication(tmp_path, monkeypatch):
    path = tmp_path / "after-market-status.json"
    day = date(2026, 1, 9)
    failed = _status(day)
    failed["last_successful_trading_day"] = str(day - timedelta(days=1))
    failed["last_failure"] = {"trading_day": str(day), "error_code": "UPDATE_FAILED"}
    failed["last_run"].update(status="failed", error_code="UPDATE_FAILED")
    _atomic_write_status(path, failed)
    late = _status(day - timedelta(days=2), finished=day + timedelta(days=1))
    digest = eod.archive_publication(path, late, late=True)
    run = late["last_run"]
    monkeypatch.setattr(eod, "_late_recovery_rows", lambda _: [{
        "state": "passed", "checks": 1, "stage": "live_cleanup", "error_code": "RQDATA_NOT_READY",
        "newow_publication_sha256": digest, "products": run["products"],
        "claimed_at": run["started_at"], "finished_at": run["finished_at"],
    }])
    assert eod._current_authority(path) is None


def test_isolated_redis_cannot_fall_back_to_runtime_port():
    import pytest
    from app.services.newow_reference_mode import require_isolated_redis

    for address in ("", "redis://127.0.0.1:6379/0", "redis://localhost:6379/14",
                    "redis://127.0.0.1:6380/0?host=example.test"):
        with pytest.raises(ValueError, match="BACKTEST_ISOLATED_REDIS_REQUIRED"):
            require_isolated_redis(address)
    require_isolated_redis("redis://127.0.0.1:16379/0")



def test_orphan_late_receipt_is_not_a_trigger_and_metadata_only_success_is(tmp_path, monkeypatch):
    path = tmp_path / "after-market-status.json"
    config = tmp_path / "config.json"
    config.write_text("fixture")
    day = date(2026, 1, 9)
    orphan = _status(day - timedelta(days=1), product="rb")
    eod.archive_publication(path, orphan, late=True)
    metadata = _status(day)
    metadata["last_run"]["historical_publications"] = []
    _atomic_write_status(path, metadata)
    calls = []
    monkeypatch.setattr(eod, "consume_status",
                        lambda raw, day, config_path, **kwargs: calls.append(kwargs["latest_days"]) or [])
    assert len(eod.reconcile_publications(path, config)) == 1
    assert calls == [{"fu": day}]
    assert eod.reconcile_publications(path, config) == []
