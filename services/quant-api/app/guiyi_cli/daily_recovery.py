"""Explicit Runtime-bound entry point for one hash-locked daily recovery."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TextIO

from app.market_data.composition import open_runtime_bound_historical_maintenance
from app.market_data.historical_data_manager import (
    MaintenanceProgressEvent,
    UpdateRequest,
)


def maintenance_progress_writer(stream: TextIO):
    """Encode the bounded maintenance observer contract as NDJSON on stderr."""

    def write(event: MaintenanceProgressEvent) -> None:
        payload: dict[str, object] = {
            "schema_version": 1,
            "event": "data.daily-recovery.progress",
            "phase": event.phase,
            "state": event.state,
            "symbol": event.symbol,
            "dataset": event.dataset,
            "year": event.year,
            "month": event.month,
            "completed": event.completed,
            "elapsed_seconds": event.elapsed_seconds,
        }
        if event.total is not None:
            payload["total"] = event.total
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        if stream.write(line) != len(line):
            raise OSError("CLI_MAINTENANCE_PROGRESS_SHORT_WRITE")
        stream.flush()

    return write


def run_daily_recovery(
    args,
    *,
    progress_stream: TextIO,
    runtime_context_factory=open_runtime_bound_historical_maintenance,
) -> dict[str, object]:
    """Build the exact P60/fixed-through request and delegate its CAS to the manager."""

    through = date.fromisoformat(args.through)
    with runtime_context_factory(
        Path(args.runtime_root),
        args.runtime_commit,
        args.expected_status_sha256,
    ) as runtime:
        request = UpdateRequest(
            products=runtime.products,
            since=None,
            through=through,
            apply=bool(args.apply),
            sync_current_day_metadata=False,
            mode="daily",
        )
        result = runtime.manager.daily_recovery(
            request,
            expected_plan_sha256=args.expected_plan_sha256,
            before_apply=runtime.invalidate_projection,
            verify_identity=runtime.verify_identity,
            observer=maintenance_progress_writer(progress_stream),
        )
        return result.as_payload()
