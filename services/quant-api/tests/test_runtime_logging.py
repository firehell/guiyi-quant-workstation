from __future__ import annotations

import logging

import pytest


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
