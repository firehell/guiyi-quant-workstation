from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from io import StringIO
import json

from app.guiyi_cli.main import main


class _NoSessionFactory:
    def __call__(self):
        raise AssertionError("runtime plan must not open a database session")


def test_runtime_plan_is_existing_scheduler_dry_run_without_side_effects() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["runtime", "plan", "--product", "jm", "--poll-seconds", "3"],
        environ={"GUIYI_LIVE_RUNTIME_ENABLED": "true"},
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "schema_version": 1,
        "command": "runtime.plan",
        "status": "planned",
        "readonly": True,
        "effects": {
            "would_open_database": False,
            "would_connect_redis": False,
            "would_construct_rqdata_client": False,
            "would_write_live_tables": False,
            "would_write_historical_active": False,
            "would_write_signal_event": False,
            "would_send_notification": False,
            "auto_order": False,
        },
        "plan": {
            "mode": "dry-run",
            "product": "jm",
            "poll_seconds": 5,
            "enabled": True,
        },
    }


def test_runtime_status_returns_health_payload_and_nonzero_for_failed_runtime() -> None:
    stdout = StringIO()
    stderr = StringIO()
    health = {
        "status": "failed",
        "generated_at": "2026-07-30T00:00:00+00:00",
        "readonly": True,
        "would_start_services": False,
        "would_enqueue_jobs": False,
        "would_send_notifications": False,
        "components": {"db": {"status": "failed"}},
    }

    exit_code = main(
        ["runtime", "status"],
        session_factory=lambda: nullcontext(object()),
        runtime_health_builder=lambda _session: health,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "schema_version": 1,
        "command": "runtime.status",
        "status": "failed",
        "readonly": True,
        "effects": {
            "would_start_services": False,
            "would_enqueue_jobs": False,
            "would_send_notifications": False,
        },
        "runtime": health,
    }


def test_data_verify_emits_stable_json_from_shared_service() -> None:
    stdout = StringIO()
    stderr = StringIO()
    observed: dict[str, object] = {}

    def verify(_session, **kwargs):
        observed.update(kwargs)
        return {
            "schema_version": 1,
            "command": "data.verify",
            "kind": "active-dataset",
            "status": "passed",
            "readonly": True,
            "effects": {
                "writes_database": False,
                "writes_parquet": False,
                "writes_manifest": False,
                "calls_rqdata": False,
            },
            "request": {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "period": "15m",
                "start": "2026-07-29T00:00:00",
                "end": "2026-07-29T23:59:59.999999",
                "provider": "rqdata",
                "profile_id": None,
                "access_mode": "browser",
                "limit": 5000,
            },
            "result": {
                "response_bar_count": 23,
                "quality": {"status": "passed"},
                "descriptor": {"lineage_token": "lineage-v1:test"},
            },
        }

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
            "--start",
            "2026-07-29",
            "--end",
            "2026-07-29",
            "--provider",
            "rqdata",
        ],
        session_factory=lambda: nullcontext(object()),
        data_verifier=verify,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["result"]["response_bar_count"] == 23
    assert observed == {
        "symbol": "jm",
        "contract": "jm.MAIN",
        "period": "15m",
        "start": datetime(2026, 7, 29, 0, 0),
        "end": datetime(2026, 7, 29, 23, 59, 59, 999999),
        "provider": "rqdata",
        "profile_id": None,
        "access_mode": "browser",
        "limit": 5000,
        "legacy_compat": False,
    }


def test_data_verify_maps_domain_error_to_bounded_json_stderr() -> None:
    from app.services.active_dataset import ActiveDatasetDomainError

    stdout = StringIO()
    stderr = StringIO()

    def reject(_session, **_kwargs):
        raise ActiveDatasetDomainError("DATASET_ASSET_MISSING")

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
        ],
        session_factory=lambda: nullcontext(object()),
        data_verifier=reject,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "data.verify",
        "status": "error",
        "readonly": True,
        "error": {
            "code": "DATASET_ASSET_MISSING",
            "type": "ActiveDatasetDomainError",
        },
    }


def test_data_verify_preserves_legacy_market_error_code_without_message() -> None:
    from app.services.market_workbench import MarketAccessError

    stdout = StringIO()
    stderr = StringIO()

    def reject(_session, **_kwargs):
        raise MarketAccessError(
            "MARKET_DATA_NOT_FOUND",
            "sensitive path must not reach stderr",
        )

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
        ],
        session_factory=lambda: nullcontext(object()),
        data_verifier=reject,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"] == {
        "code": "MARKET_DATA_NOT_FOUND",
        "type": "MarketAccessError",
    }


def test_data_verify_rejects_invalid_date_before_opening_database() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
            "--start",
            "not-a-date",
        ],
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "data.verify",
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_ARGUMENT_INVALID", "type": "ValueError"},
    }


def test_runtime_status_bounds_collector_error_without_traceback() -> None:
    stdout = StringIO()
    stderr = StringIO()

    def fail(_session):
        raise RuntimeError("database password must never reach stderr")

    exit_code = main(
        ["runtime", "status"],
        session_factory=lambda: nullcontext(object()),
        runtime_health_builder=fail,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "runtime.status",
        "status": "error",
        "readonly": True,
        "error": {"code": "RUNTIME_STATUS_FAILED", "type": "RuntimeError"},
    }


def test_data_verify_warning_returns_nonzero() -> None:
    stdout = StringIO()
    observed: dict[str, object] = {}

    def warning(_session, **kwargs):
        observed.update(kwargs)
        return {
            "schema_version": 1,
            "command": "data.verify",
            "status": "warning",
            "readonly": True,
        }

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
        ],
        session_factory=lambda: nullcontext(object()),
        data_verifier=warning,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 1
    assert observed["start"] is None
    assert observed["end"] is None


def test_parser_error_uses_bounded_json_and_exit_two() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--contract",
            "jm.MAIN",
            "--period",
            "15m",
            "--limit",
            "0",
        ],
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "schema_version": 1,
        "command": "data.verify",
        "status": "error",
        "readonly": True,
        "error": {"code": "CLI_ARGUMENT_INVALID", "type": "CliUsageError"},
    }
