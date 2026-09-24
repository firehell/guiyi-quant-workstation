from __future__ import annotations

import logging
import json

import pytest

from app.alerts.notification import AlertNotificationMessage, NotificationTransportError
from app.alerts.registry import HTDY_ALERT_RULE_CODE
from app.alerts.runtime import AlertRuntime


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


def test_after_market_exception_types_are_bounded_and_distinct(tmp_path):
    from app.runtime_logging import runtime_diagnostic_handler

    path = tmp_path / "after-market.log"
    handler = runtime_diagnostic_handler(path)
    logger = logging.getLogger("app.market_data.after_market")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        from app.market_data.after_market import _diagnostic_warning

        for name in ("RuntimeError", "OSError", "SecretError_password=hidden"):
            _diagnostic_warning(
                "after_market_attempt_failed stage=canonical_update attempt=%s detail_code=%s exception_type=%s",
                1, "UNEXPECTED_UPDATE_EXCEPTION", name,
                stage="canonical_update", attempt=1,
                detail_code="UNEXPECTED_UPDATE_EXCEPTION", exception_type=name,
            )
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [row["exception_type"] for row in rows] == ["RuntimeError", "OSError", "REDACTED"]
        assert "hidden" not in path.read_text()
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_after_market_calendar_failure_context_is_bounded(tmp_path):
    from app.runtime_logging import runtime_diagnostic_handler

    path = tmp_path / "after-market.log"
    handler = runtime_diagnostic_handler(path)
    logger = logging.getLogger("app.market_data.after_market")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        from app.market_data.after_market import _diagnostic_warning

        for context in (
            {"exchange_code": "DCE", "calendar_day": "2026-09-28",
             "reason_code": "SESSION_COVERAGE_INCOMPLETE"},
            {"exchange_code": "password=hidden", "calendar_day": "password=hidden",
             "reason_code": "password=hidden"},
        ):
            _diagnostic_warning(
                "after_market_attempt_failed stage=canonical_update attempt=%s "
                "detail_code=%s exception_type=%s",
                1, "CALENDAR_NIGHT_AUTHORITY_MISSING", "ValueError",
                stage="canonical_update", attempt=1,
                detail_code="CALENDAR_NIGHT_AUTHORITY_MISSING",
                exception_type="ValueError", failure_context=context,
            )
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert {key: rows[0][key] for key in context} == {
            "exchange_code": "DCE", "calendar_day": "2026-09-28",
            "reason_code": "SESSION_COVERAGE_INCOMPLETE",
        }
        assert all(key not in rows[1] for key in context)
        assert "hidden" not in path.read_text()
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_after_market_target_failure_log_keeps_only_bounded_identity(tmp_path):
    from app.market_data.after_market import _log_first_maintenance_failure
    from app.runtime_logging import runtime_diagnostic_handler

    path = tmp_path / "after-market.log"
    handler = runtime_diagnostic_handler(path)
    logger = logging.getLogger("app.market_data.after_market")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        _log_first_maintenance_failure({
            "dataset": ("contract", "rs", "RS2609", "1d"),
            "year": 2025, "month": 11,
            "reason_code": "SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED",
        }, 1, 2)
        _log_first_maintenance_failure({
            "dataset": ("contract", "password=hidden", "RS2609", "1d"),
            "reason_code": "password=hidden",
        }, 1, 1)
        _log_first_maintenance_failure({
            "dataset": ("continuous", "rs", "MAIN", "1d"),
            "year": 2026, "month": 9,
            "reason_code": "StorageError",
        }, 1, 1)
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert rows[0]["code"] == "AFTER_MARKET_TARGET_FAILURE"
        assert rows[0]["reason_code"] == "SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED"
        assert (rows[0]["symbol"], rows[0]["contract"], rows[0]["year"], rows[0]["month"]) == (
            "rs", "RS2609", 2025, 11,
        )
        assert rows[1]["reason_code"] == "OTHER_TARGET_FAILURE"
        assert rows[2]["symbol"] == "rs"
        assert "contract" not in rows[2]
        assert "hidden" not in path.read_text()
    finally:
        logger.removeHandler(handler)
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


def test_alert_transport_failure_persists_only_safe_exact_event_identity(tmp_path):
    from datetime import UTC, datetime

    from app.runtime_logging import runtime_diagnostic_handler

    path = tmp_path / "alert-runtime.log"
    handler = runtime_diagnostic_handler(path)
    logger = logging.getLogger("app.alerts.runtime")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    at = datetime(2026, 9, 14, 1, 15, tzinfo=UTC)
    sensitive_marker = "provider-body-sensitive-marker"

    class Sender:
        @staticmethod
        def send(_message):
            raise NotificationTransportError(
                diagnostic_code="PUSHPLUS_PROVIDER_REJECTED"
            )

    runtime = AlertRuntime(
        session_factory=lambda: None,  # type: ignore[arg-type]
        market_read_factory=lambda _session: None,  # type: ignore[arg-type]
        evaluators={},
        sender=Sender(),
        operational_products=(),
        taxonomy={},
    )
    message = AlertNotificationMessage(
        rule_code=HTDY_ALERT_RULE_CODE,
        symbol="jm",
        product_name=sensitive_marker,
        contract="JM2609",
        frequency="15m",
        bar_end=at,
        detected_at=at,
        result_codes=("buy",),
    )
    try:
        runtime._send_messages_once([message], processing_now=at)
        payload = json.loads(path.read_text())
        assert payload == {
            "at": payload["at"],
            "bar_end": "2026-09-14T01:15:00+00:00",
            "code": "PUSHPLUS_PROVIDER_REJECTED",
            "contract": "JM2609",
            "frequency": "15m",
            "rule_code": "htdy_original_15m",
            "symbol": "jm",
        }
        assert sensitive_marker not in path.read_text()
    finally:
        logger.removeHandler(handler)
        logger.propagate = True
        handler.close()


def test_runtime_log_omits_unknown_rule_and_nonformal_frequency(tmp_path):
    from app.runtime_logging import runtime_diagnostic_handler

    path = tmp_path / "alert-runtime.log"
    handler = runtime_diagnostic_handler(path)
    record = logging.LogRecord(
        "app.alerts.runtime",
        logging.WARNING,
        "",
        0,
        "ALERT_NOTIFICATION_TRANSPORT_FAILED",
        (),
        None,
    )
    record.diagnostic_code = "PUSHPLUS_REQUEST_OUTCOME_UNKNOWN"
    record.diagnostic_fields = {
        "rule_code": "unknown_rule",
        "symbol": "jm",
        "contract": "JM2609",
        "frequency": "2h",
        "bar_end": "2026-09-14T01:15:00+00:00",
    }
    try:
        handler.handle(record)
        payload = json.loads(path.read_text())
        assert "rule_code" not in payload
        assert "frequency" not in payload
        assert payload["symbol"] == "jm"
        assert payload["contract"] == "JM2609"
    finally:
        handler.close()
