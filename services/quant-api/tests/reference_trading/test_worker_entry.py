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
