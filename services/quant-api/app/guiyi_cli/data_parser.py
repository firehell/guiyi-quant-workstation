"""Argument grammar and allow-lists for ``guiyi data`` commands."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Sequence

from app.data_core.contracts import BAR_FREQUENCY_VALUES, BarFrequency, DatasetKind
from app.services.data_operations.contracts import (
    DIRECT_FREQUENCY_VALUES,
    DERIVED_FREQUENCY_VALUES,
    AuditScope,
    CliArgumentInvalid,
    MetadataSyncScope,
)


class CliUsageError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)


def add_data_commands(data_commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register unified + retained legacy data commands on an existing subparser."""
    verify = data_commands.add_parser("verify")
    verify.add_argument("--symbol", required=True)
    verify.add_argument("--contract")
    verify.add_argument("--period")
    verify.add_argument(
        "--dataset-kind",
        choices=("continuous", "actual_dominant"),
    )
    verify.add_argument("--contract-or-series")
    verify.add_argument("--frequency", choices=BAR_FREQUENCY_VALUES)
    verify.add_argument("--canonical-root", type=Path)
    verify.add_argument("--start")
    verify.add_argument("--end")
    verify.add_argument("--provider")
    verify.add_argument("--profile-id")
    verify.add_argument("--access-mode", choices=("browser", "research"), default="browser")
    verify.add_argument("--limit", type=_positive_int, default=5000)

    download = data_commands.add_parser("download")
    _add_target_arguments(download, frequencies=sorted(DIRECT_FREQUENCY_VALUES))
    download.add_argument("--batch-size", type=_positive_int)
    download.add_argument("--apply", action="store_true")

    aggregate = data_commands.add_parser("aggregate")
    _add_target_arguments(aggregate, frequencies=sorted(DERIVED_FREQUENCY_VALUES))
    aggregate.add_argument("--batch-size", type=_positive_int)
    aggregate.add_argument("--apply", action="store_true")

    live = data_commands.add_parser("live")
    _add_target_arguments(live, frequencies=("1m",), require_window=False)
    live.add_argument(
        "--confirm-observation-write",
        action="store_true",
        help="Local effect selector only; not external authorization.",
    )

    sync = data_commands.add_parser("sync")
    sync.add_argument(
        "--scope",
        choices=tuple(scope.value for scope in MetadataSyncScope),
        required=True,
    )
    sync.add_argument("--symbol")
    sync.add_argument("--symbols-file", type=Path)
    sync.add_argument("--start")
    sync.add_argument("--end")
    sync.add_argument("--apply", action="store_true")

    audit = data_commands.add_parser("audit")
    audit.add_argument(
        "--scope",
        choices=tuple(scope.value for scope in AuditScope),
        required=True,
    )
    audit.add_argument("--symbol")
    audit.add_argument("--symbols-file", type=Path)
    audit.add_argument(
        "--dataset-kind",
        choices=("continuous", "actual_dominant"),
    )
    audit.add_argument("--frequency", choices=BAR_FREQUENCY_VALUES)
    audit.add_argument("--start")
    audit.add_argument("--end")

    # Legacy plan/migrate/task07 routes intentionally omitted after replacement cutover.


def parse_aware_datetime(value: str, *, field_name: str) -> datetime:
    try:
        if len(value) == 10:
            parsed = datetime.combine(date.fromisoformat(value), time.min, tzinfo=UTC)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CliArgumentInvalid(
            facts={"field": field_name, "reason": "malformed"}
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CliArgumentInvalid(
            facts={"field": field_name, "reason": "timezone_required"}
        )
    return parsed.astimezone(UTC)


def require_paired_window(
    start: str | None,
    end: str | None,
) -> tuple[datetime, datetime]:
    if (start is None) != (end is None):
        raise CliArgumentInvalid(facts={"field": "window", "reason": "unpaired"})
    if start is None or end is None:
        raise CliArgumentInvalid(facts={"field": "window", "reason": "required"})
    start_dt = parse_aware_datetime(start, field_name="start")
    end_dt = parse_aware_datetime(end, field_name="end")
    if start_dt >= end_dt:
        raise CliArgumentInvalid(facts={"field": "window", "reason": "invalid"})
    return start_dt, end_dt


def optional_paired_window(
    start: str | None,
    end: str | None,
) -> tuple[datetime, datetime] | None:
    if start is None and end is None:
        return None
    return require_paired_window(start, end)


def parse_dataset_kind(value: str) -> DatasetKind:
    try:
        return DatasetKind(value)
    except ValueError as exc:
        raise CliArgumentInvalid(facts={"field": "dataset_kind"}) from exc


def parse_frequency(value: str) -> BarFrequency:
    try:
        return BarFrequency(value)
    except ValueError as exc:
        raise CliArgumentInvalid(facts={"field": "frequency"}) from exc


def reject_legacy_backfill_alias(argv: Sequence[str]) -> None:
    lowered = {item.lower() for item in argv}
    if "backfill" in lowered or "--pre-2020" in lowered or "--pre2020" in lowered:
        raise CliUsageError("legacy backfill aliases are rejected")


def _add_target_arguments(
    parser: argparse.ArgumentParser,
    *,
    frequencies: Sequence[str],
    require_window: bool = True,
) -> None:
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--symbol")
    selector.add_argument("--symbols-file", type=Path)
    parser.add_argument(
        "--dataset-kind",
        choices=("continuous", "actual_dominant"),
        required=True,
    )
    parser.add_argument("--contract-or-series")
    parser.add_argument("--frequency", choices=tuple(frequencies), required=True)
    parser.add_argument("--start", required=require_window)
    parser.add_argument("--end", required=require_window)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed
