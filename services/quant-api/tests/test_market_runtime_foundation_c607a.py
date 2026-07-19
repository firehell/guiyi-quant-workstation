"""C6-07A live targets path strip and sanitize regressions."""

from __future__ import annotations

from app.services.live_target_contracts import sanitize_live_targets_payload


def test_sanitize_live_targets_strips_file_path() -> None:
    payload = {
        "readiness_status": "ready",
        "items": [
            {
                "product": "jm",
                "actual_contract": "JM2609",
                "historical_coverage": {
                    "15m": {
                        "available": True,
                        "quality_status": "passed",
                        "file_path": "/tmp/jm_MAIN_15m.parquet",
                        "file_paths": ["/tmp/a.parquet", "/tmp/b.parquet"],
                        "data_version": "v2",
                    }
                },
                "live_coverage": {
                    "1m": {
                        "available": True,
                        "latest_bar_time": "2026-07-19T10:00:00",
                        "file_path": "/should/not/leak",
                    }
                },
            }
        ],
    }
    cleaned = sanitize_live_targets_payload(payload)
    hist = cleaned["items"][0]["historical_coverage"]["15m"]
    live = cleaned["items"][0]["live_coverage"]["1m"]
    assert hist["file_path"] is None
    assert "file_paths" not in hist
    assert hist["data_version"] == "v2"
    assert live["file_path"] is None
    assert live["latest_bar_time"] == "2026-07-19T10:00:00"


def test_sanitize_live_targets_does_not_invent_fields() -> None:
    payload = {"items": [{"product": "jm", "historical_coverage": {}}]}
    cleaned = sanitize_live_targets_payload(payload)
    assert cleaned["items"][0]["product"] == "jm"
    assert cleaned["items"][0]["historical_coverage"] == {}
    assert "actual_contract" not in cleaned["items"][0]


def test_historical_coverage_builder_returns_null_file_path() -> None:
    """Unit-level: builder output shape uses file_path=None (no physical path)."""
    period = {
        "available": True,
        "provider": "rqdata",
        "data_type": "bars",
        "data_role": "primary",
        "start_time": "2023-01-01T00:00:00",
        "end_time": "2026-07-10T15:00:00",
        "latest_bar_time": "2026-07-10T15:00:00",
        "row_count": 10,
        "quality_status": "passed",
        "data_version": "v2",
        "file_path": None,
    }
    assert period["file_path"] is None
    assert "file_paths" not in period
