from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from io import StringIO
import json

import pytest

from app.guiyi_cli.main import main
from app.services.data_operations.contracts import (
    CommandResult,
    CommandStatus,
    empty_effects,
)


class _NoSessionFactory:
    def __call__(self):
        raise AssertionError("must not open a database session")


def test_update_dry_run_uses_injected_workflow_without_session_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.data_operations.historical_update import HistoricalUpdateWorkflow
    from app.services.data_operations.contracts import HistoricalUpdateRequest

    stdout = StringIO()
    stderr = StringIO()
    seen: dict[str, object] = {}

    def fake_run(self, request: HistoricalUpdateRequest) -> CommandResult:
        seen["apply"] = request.apply
        seen["products"] = request.products
        return CommandResult(
            command="data.update",
            status=CommandStatus.PLANNED,
            readonly=True,
            effects=empty_effects(),
            extras={"plan_summary": {"product_count": 1}},
        )

    monkeypatch.setattr(HistoricalUpdateWorkflow, "run", fake_run)
    exit_code = main(
        ["data", "update", "--symbol", "jm"],
        session_factory=lambda: nullcontext(object()),
        stdout=stdout,
        stderr=stderr,
    )
    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["command"] == "data.update"
    assert payload["readonly"] is True
    assert seen["apply"] is False
    assert seen["products"] == ("jm",)


def test_download_plan_rejects_derived_frequency_before_session() -> None:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = main(
        [
            "data",
            "download",
            "--symbol",
            "jm",
            "--dataset-kind",
            "continuous",
            "--contract-or-series",
            "JM888",
            "--frequency",
            "15m",
            "--start",
            "2020-01-01T00:00:00Z",
            "--end",
            "2020-01-02T00:00:00Z",
        ],
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )
    assert exit_code == 2
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"


def test_download_plan_returns_readonly_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.data_operations.download import DownloadApplicationService
    from app.services.data_operations.contracts import DownloadRequest

    stdout = StringIO()
    stderr = StringIO()

    def fake_run(self, request: DownloadRequest) -> CommandResult:
        assert request.apply is False
        return CommandResult(
            command="data.download",
            status=CommandStatus.PLANNED,
            readonly=True,
            effects=empty_effects(),
        )

    monkeypatch.setattr(DownloadApplicationService, "run", fake_run)
    exit_code = main(
        [
            "data",
            "download",
            "--symbol",
            "jm",
            "--dataset-kind",
            "continuous",
            "--contract-or-series",
            "JM888",
            "--frequency",
            "1m",
            "--start",
            "2018-01-01T00:00:00Z",
            "--end",
            "2018-01-08T00:00:00Z",
        ],
        session_factory=lambda: nullcontext(object()),
        stdout=stdout,
        stderr=stderr,
    )
    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["command"] == "data.download"
    assert payload["status"] == "planned"
    assert payload["readonly"] is True
    assert payload["effects"]["auto_order"] is False


def test_aggregate_rejects_direct_frequency() -> None:
    stderr = StringIO()
    exit_code = main(
        [
            "data",
            "aggregate",
            "--symbol",
            "jm",
            "--dataset-kind",
            "continuous",
            "--contract-or-series",
            "JM888",
            "--frequency",
            "1m",
            "--start",
            "2020-01-01T00:00:00Z",
            "--end",
            "2020-01-02T00:00:00Z",
        ],
        session_factory=_NoSessionFactory(),
        stdout=StringIO(),
        stderr=stderr,
    )
    assert exit_code == 2
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"


def test_legacy_backfill_alias_is_rejected() -> None:
    stderr = StringIO()
    exit_code = main(
        ["data", "backfill", "--symbol", "jm"],
        session_factory=_NoSessionFactory(),
        stdout=StringIO(),
        stderr=stderr,
    )
    assert exit_code == 2
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"


def test_metadata_sync_requires_scope() -> None:
    stderr = StringIO()
    exit_code = main(
        ["data", "sync", "--apply"],
        session_factory=_NoSessionFactory(),
        stdout=StringIO(),
        stderr=stderr,
    )
    assert exit_code == 2


def test_audit_and_removed_routes_fail_closed() -> None:
    for argv in (
        ["data", "plan"],
        ["data", "migrate", "inventory"],
        ["data", "task07", "assess"],
    ):
        exit_code = main(
            argv,
            session_factory=_NoSessionFactory(),
            stdout=StringIO(),
            stderr=StringIO(),
        )
        assert exit_code == 2


def test_data_canonical_verify_dispatches_shared_data_core_reader() -> None:
    stdout = StringIO()
    stderr = StringIO()
    observed = {}

    def run(command, _session, args):
        observed.update({"command": command, "args": vars(args)})
        return {
            "schema_version": 1,
            "command": "data.verify",
            "status": "passed",
            "readonly": True,
        }

    exit_code = main(
        [
            "data",
            "verify",
            "--dataset-kind",
            "continuous",
            "--symbol",
            "jm",
            "--contract-or-series",
            "jm.MAIN",
            "--frequency",
            "15m",
            "--start",
            "2026-07-01T01:00:00Z",
            "--end",
            "2026-07-01T02:00:00Z",
            "--canonical-root",
            "/tmp/guiyi-canonical",
        ],
        session_factory=lambda: nullcontext(object()),
        data_core_runner=run,
        data_verifier=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy verifier must not run")
        ),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert observed["command"] == "verify"
    assert observed["args"]["dataset_kind"] == "continuous"


def test_runtime_plan_is_rejected_after_scheduler_retirement() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        ["runtime", "plan", "--product", "jm", "--poll-seconds", "3"],
        environ={"GUIYI_LIVE_RUNTIME_ENABLED": "true"},
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["code"] == (
        "CLI_ARGUMENT_INVALID"
    )


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



def _canonical_verify_argv(*, limit: str | None = None) -> list[str]:
    argv = [
        "data",
        "verify",
        "--symbol",
        "jm",
        "--dataset-kind",
        "continuous",
        "--contract-or-series",
        "JM888",
        "--frequency",
        "15m",
        "--canonical-root",
        "/tmp/canonical",
        "--start",
        "2026-07-29T00:00:00Z",
        "--end",
        "2026-07-29T23:59:59Z",
    ]
    if limit is not None:
        argv.extend(["--limit", limit])
    return argv


def test_data_verify_routes_to_data_core_runner() -> None:
    stdout = StringIO()
    stderr = StringIO()
    observed: dict[str, object] = {}

    def runner(command, _session, args):
        observed["command"] = command
        observed["dataset_kind"] = args.dataset_kind
        observed["contract_or_series"] = args.contract_or_series
        observed["frequency"] = args.frequency
        return {
            "schema_version": 1,
            "command": "data.verify",
            "status": "passed",
            "readonly": True,
            "result": {"response_bar_count": 23},
        }

    exit_code = main(
        _canonical_verify_argv(),
        session_factory=lambda: nullcontext(object()),
        data_core_runner=runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue())["result"]["response_bar_count"] == 23
    assert observed == {
        "command": "verify",
        "dataset_kind": "continuous",
        "contract_or_series": "JM888",
        "frequency": "15m",
    }


def test_data_verify_maps_runner_error_to_bounded_json_stderr() -> None:
    stdout = StringIO()
    stderr = StringIO()

    class Boom(Exception):
        code = "DATASET_ASSET_MISSING"

    def reject(_command, _session, _args):
        raise Boom("missing")

    exit_code = main(
        _canonical_verify_argv(),
        session_factory=lambda: nullcontext(object()),
        data_core_runner=reject,
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
        "error": {"code": "DATASET_ASSET_MISSING", "type": "Boom"},
    }


def test_data_verify_rejects_legacy_contract_period_grammar() -> None:
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
        ],
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"


def test_data_verify_requires_canonical_dataset_key_args() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        [
            "data",
            "verify",
            "--symbol",
            "jm",
            "--dataset-kind",
            "continuous",
        ],
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"



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

    def runner(_command, _session, _args):
        return {
            "schema_version": 1,
            "command": "data.verify",
            "status": "warning",
            "readonly": True,
        }

    exit_code = main(
        _canonical_verify_argv(),
        session_factory=lambda: nullcontext(object()),
        data_core_runner=runner,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 1


def test_parser_error_uses_bounded_json_and_exit_two() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        _canonical_verify_argv(limit="0"),
        session_factory=_NoSessionFactory(),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue())["error"]["code"] == "CLI_ARGUMENT_INVALID"

