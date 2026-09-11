from __future__ import annotations

import io
import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.market_data.historical_data_manager import (
    DailyRecoveryResult,
    MaintenanceProgressEvent,
    MaintenanceResult,
)


@pytest.mark.parametrize(
    ("apply", "expected_plan_sha256"),
    [(False, None), (True, "d" * 64)],
)
def test_daily_recovery_builds_exact_bound_request_from_runtime_products(
    apply, expected_plan_sha256
) -> None:
    from app.guiyi_cli.daily_recovery import run_daily_recovery

    progress = io.StringIO()
    received = []
    runtime = SimpleNamespace(
        products=("ag", "au"),
        verify_identity=lambda: None,
        invalidate_projection=lambda: None,
    )

    class Manager:
        def daily_recovery(
            self,
            request,
            *,
            expected_plan_sha256,
            before_apply,
            verify_identity,
            observer,
        ):
            received.append(
                (
                    request,
                    expected_plan_sha256,
                    before_apply,
                    verify_identity,
                )
            )
            observer(
                MaintenanceProgressEvent(
                    phase="planning",
                    state="started",
                    symbol="ag",
                    dataset=None,
                    year=None,
                    month=None,
                    completed=0,
                    total=None,
                    elapsed_seconds=0.0,
                )
            )
            observer(
                MaintenanceProgressEvent(
                    phase="planning",
                    state="completed",
                    symbol="ag",
                    dataset=None,
                    year=None,
                    month=None,
                    completed=1,
                    total=None,
                    elapsed_seconds=0.125,
                )
            )
            return DailyRecoveryResult(
                maintenance=MaintenanceResult(
                    "update", "planned", request.through, 1, 0, 0, 0, 0
                ),
                plan_sha256="c" * 64,
                target_windows=(),
                readonly=not request.apply,
            )

    runtime.manager = Manager()

    @contextmanager
    def open_runtime(root, commit, status_sha256):
        received.append((root, commit, status_sha256))
        yield runtime

    args = SimpleNamespace(
        runtime_root="/runtime",
        runtime_commit="a" * 40,
        expected_status_sha256="b" * 64,
        through="2026-09-11",
        apply=apply,
        expected_plan_sha256=expected_plan_sha256,
    )

    payload = run_daily_recovery(
        args,
        progress_stream=progress,
        runtime_context_factory=open_runtime,
    )

    request = received[1][0]
    assert received[0] == (Path("/runtime"), "a" * 40, "b" * 64)
    assert request.products == ("ag", "au")
    assert request.since is None
    assert request.through == date(2026, 9, 11)
    assert request.apply is apply
    assert request.sync_current_day_metadata is False
    assert request.mode == "daily"
    assert received[1][1] == expected_plan_sha256
    assert received[1][2] is runtime.invalidate_projection
    assert received[1][3] is runtime.verify_identity
    assert payload["status"] == "planned"
    assert payload["plan_sha256"] == "c" * 64
    assert [json.loads(line)["state"] for line in progress.getvalue().splitlines()] == [
        "started",
        "completed",
    ]


def test_daily_recovery_progress_is_bounded_and_credential_free() -> None:
    from app.guiyi_cli.daily_recovery import maintenance_progress_writer

    stream = io.StringIO()
    writer = maintenance_progress_writer(stream)
    writer(
        MaintenanceProgressEvent(
            phase="provider",
            state="failed",
            symbol="ag",
            dataset=("contract", "ag", "AG2610", "1m"),
            year=2026,
            month=9,
            completed=7,
            total=None,
            elapsed_seconds=1.25,
        )
    )

    assert json.loads(stream.getvalue()) == {
        "schema_version": 1,
        "event": "data.daily-recovery.progress",
        "phase": "provider",
        "state": "failed",
        "symbol": "ag",
        "dataset": ["contract", "ag", "AG2610", "1m"],
        "year": 2026,
        "month": 9,
        "completed": 7,
        "elapsed_seconds": 1.25,
    }
