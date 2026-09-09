from __future__ import annotations

import logging
import json

import pytest


def test_after_market_structured_progress_reopens_rotated_log_and_bounds_fields(tmp_path):
    from app.runtime_logging import runtime_diagnostic_handler
    path = tmp_path / "after-market.log"
    handler = runtime_diagnostic_handler(path)
    progress = {
        "scheduled_date": "2026-08-10", "started_at": "2026-08-10T18:05:00+08:00",
        "products": ["au"], "stage": "publishing", "attempt": 1,
        "updated_at": "2026-08-10T18:06:00+08:00", "stage_started_at": "2026-08-10T18:06:00+08:00",
        "current_symbol": "au", "current_partition": {"dataset": ["continuous", "au", "MAIN", "1m"], "year": 2026, "month": 8},
        "counters": {"reading": {"completed": 2}, "publishing": {"completed": 1}},
        "stage_durations": {"reading": .5}, "elapsed_seconds": 60., "retry_at": None,
    }
    record = logging.LogRecord("app.test", logging.INFO, "", 0, "AFTER_MARKET_PROGRESS", (), None)
    record.diagnostic_fields = {"progress": {**progress, "untrusted": "password=secret"}}
    try:
        handler.handle(record)
        assert json.loads(path.read_text())["progress"] == progress
        path.rename(tmp_path / "rotated.log")
        handler.handle(record)
        assert json.loads(path.read_text())["progress"] == progress
        record.diagnostic_fields["progress"]["current_partition"]["dataset"][2] = "password=secret"
        handler.handle(record)
        assert "progress" not in json.loads(path.read_text().splitlines()[-1])
        assert "secret" not in path.read_text()
    finally:
        handler.close()


def test_runtime_log_reopens_removed_file_and_redacts_untrusted_exception(tmp_path):
    from app.runtime_logging import runtime_diagnostic_handler

    path = tmp_path / "live-market.log"
    handler = runtime_diagnostic_handler(path)
    logger = logging.getLogger("app.test_diagnostics")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.warning("LIVE_GAP_DETECTED", extra={"diagnostic_fields": {"symbol": "jm", "missing_count": 1}})
        assert "LIVE_GAP_DETECTED" in path.read_text()
        path.unlink()
        logger.warning("LIVE_RECOVERY_REJECTED")
        assert "LIVE_RECOVERY_REJECTED" in path.read_text()
        assert "LIVE_GAP_DETECTED" not in path.read_text()
        try:
            raise ValueError("password=do-not-display")
        except ValueError:
            logger.exception("untrusted password=%s", "do-not-display")
        assert "do-not-display" not in path.read_text()
        assert "Traceback" not in path.read_text()
        assert "RUNTIME_DIAGNOSTIC_REDACTED" in path.read_text()
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_runtime_log_refuses_symlink_without_touching_target(tmp_path):
    from app.runtime_logging import runtime_diagnostic_handler

    target = tmp_path / "other"
    target.write_text("keep")
    path = tmp_path / "live-market.log"
    path.symlink_to(target)
    with pytest.raises(ValueError, match="RUNTIME_LOG_UNSAFE"):
        runtime_diagnostic_handler(path)
    assert target.read_text() == "keep"


def test_log_reopen_failure_does_not_dump_original_record(tmp_path, capsys):
    from app.runtime_logging import runtime_diagnostic_handler

    path = tmp_path / "live-market.log"
    handler = runtime_diagnostic_handler(path)
    path.unlink()
    target = tmp_path / "other"
    target.write_text("keep")
    path.symlink_to(target)
    try:
        handler.handle(logging.LogRecord("app.test", logging.ERROR, "", 0, "password=%s", ("hidden-value",), None))
        captured = capsys.readouterr()
        assert "hidden-value" not in captured.err
        assert "RUNTIME_LOG_UNAVAILABLE" in captured.err
        assert target.read_text() == "keep"
    finally:
        handler.close()
