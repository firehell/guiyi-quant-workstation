import pytest

from app.reference_trading import worker_entry


def test_worker_stays_off_without_exact_marker(tmp_path, monkeypatch):
    marker = tmp_path / "reference-worker-enabled"
    monkeypatch.setattr(worker_entry, "ACTIVATION_MARKER", marker)
    with pytest.raises(RuntimeError, match="REFERENCE_WORKER_NOT_ENABLED"):
        with worker_entry.open_forward_worker():
            raise AssertionError("disabled worker must not open resources")
    marker.write_text("enabled", encoding="utf-8")
    with pytest.raises(RuntimeError, match="REFERENCE_WORKER_NOT_ENABLED"):
        worker_entry.require_worker_enabled()


def test_unknown_historical_attempt_survives_release_root_change(tmp_path, monkeypatch):
    from pathlib import Path
    from app.reference_trading import worker_entry
    from app.reference_trading.historical_refresh import RefreshStateStore, VERSION
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(worker_entry, "PROJECT_ROOT", tmp_path / "release-one")
    old_path = worker_entry.historical_refresh_state_path()
    unknown = {"version": VERSION, "cursor": "", "routes": {"stream": {"status": "inflight"}}}
    RefreshStateStore(old_path).write(unknown)
    monkeypatch.setattr(worker_entry, "PROJECT_ROOT", tmp_path / "release-two")
    assert worker_entry.historical_refresh_state_path() == old_path
    assert RefreshStateStore(worker_entry.historical_refresh_state_path()).read() == unknown
