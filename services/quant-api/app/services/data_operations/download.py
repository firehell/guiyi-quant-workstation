"""Download application orchestration over V2 HistoricalSynchronizer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol, Sequence

from app.data_core.contracts import DIRECT_FREQUENCIES, DatasetKey
from app.data_core.historical_sync import plan_missing_windows
from app.services.data_operations.contracts import (
    CommandResult,
    CommandStatus,
    DataTarget,
    DownloadRequest,
    EffectSummary,
    PublicError,
    TargetResult,
    empty_effects,
    overall_batch_status,
    require_direct_frequency,
)
from app.services.data_operations.guards import (
    assert_no_gap_intersection,
    refuse_cross_kind_fallback,
    to_dataset_key,
)


class _SyncResult(Protocol):
    dry_run: bool
    planned_windows: Sequence[tuple[datetime, datetime]]
    published_windows: Sequence[tuple[datetime, datetime]]
    gap_windows: Sequence[tuple[datetime, datetime]]


class _Synchronizer(Protocol):
    def sync(
        self,
        *,
        dataset: DatasetKey,
        start: datetime,
        end: datetime,
        dry_run: bool = False,
        replace_existing: bool = False,
    ) -> _SyncResult: ...


class _Catalog(Protocol):
    def list_partitions(self, key: DatasetKey) -> Sequence[object]: ...

    def list_gaps(self, key: DatasetKey) -> Sequence[object]: ...


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    targets: tuple[DataTarget, ...]
    windows_by_target: tuple[tuple[DataTarget, tuple[tuple[datetime, datetime], ...]], ...]
    apply: bool


class DownloadApplicationService:
    """Plan/apply exact DatasetKey historical downloads without CLI algorithms."""

    def __init__(
        self,
        *,
        synchronizer_factory: Callable[[], _Synchronizer],
        catalog: _Catalog | None = None,
        covered_windows: Callable[
            [DatasetKey], Sequence[tuple[datetime, datetime]]
        ]
        | None = None,
        listing_lower_bound: Callable[[DataTarget], datetime | None] | None = None,
    ) -> None:
        self._synchronizer_factory = synchronizer_factory
        self._catalog = catalog
        self._covered_windows = covered_windows
        self._listing_lower_bound = listing_lower_bound

    def plan(self, request: DownloadRequest) -> DownloadPlan:
        prepared: list[tuple[DataTarget, tuple[tuple[datetime, datetime], ...]]] = []
        for target in request.targets:
            require_direct_frequency(target.frequency)
            dataset = to_dataset_key(target)
            refuse_cross_kind_fallback(
                requested=target.dataset_kind,
                resolved=dataset.dataset_kind,
            )
            covered = self._resolve_covered(dataset)
            windows = plan_missing_windows(
                dataset=dataset,
                start=target.start,
                end=target.end,
                covered_windows=covered,
            )
            unavailable = self._explicit_unavailable_prefix(target)
            if unavailable is not None:
                windows = _merge_unavailable_prefix(windows, unavailable, target.end)
            prepared.append((target, windows))
        return DownloadPlan(
            targets=tuple(request.targets),
            windows_by_target=tuple(prepared),
            apply=request.apply,
        )

    def execute(self, plan: DownloadPlan) -> CommandResult:
        if not plan.apply:
            results = [
                TargetResult(
                    target=target,
                    status=CommandStatus.PLANNED,
                    detail={
                        "missing_windows": [
                            {"start": start.isoformat(), "end": end.isoformat()}
                            for start, end in windows
                        ]
                    },
                )
                for target, windows in plan.windows_by_target
            ]
            return CommandResult(
                command="data.download",
                status=overall_batch_status(results),
                readonly=True,
                effects=empty_effects(),
                targets=tuple(results),
            )

        synchronizer: _Synchronizer | None = None
        results: list[TargetResult] = []
        attempted = 0
        published = 0
        gap_recorded = 0
        for target, planned in plan.windows_by_target:
            require_direct_frequency(target.frequency)
            dataset = to_dataset_key(target)
            try:
                if not planned:
                    results.append(
                        TargetResult(
                            target=target,
                            status=CommandStatus.PASSED,
                            detail={"action": "no_op", "published_windows": []},
                        )
                    )
                    continue
                if synchronizer is None:
                    synchronizer = self._synchronizer_factory()
                attempted += 1
                published_windows: list[object] = []
                gap_windows: list[object] = []
                planned_windows: list[object] = []
                for window_start, window_end in planned:
                    if self._catalog is not None:
                        assert_no_gap_intersection(
                            self._catalog,
                            dataset=dataset,
                            start=window_start,
                            end=window_end,
                        )
                    sync_result = synchronizer.sync(
                        dataset=dataset,
                        start=window_start,
                        end=window_end,
                        dry_run=False,
                    )
                    planned_windows.extend(sync_result.planned_windows)
                    published_windows.extend(sync_result.published_windows)
                    gap_windows.extend(sync_result.gap_windows)
            except Exception as exc:  # noqa: BLE001 - preserve per-target isolation
                results.append(
                    TargetResult(
                        target=target,
                        status=CommandStatus.ERROR,
                        error=PublicError(
                            code=getattr(exc, "code", "DOWNLOAD_FAILED"),
                            type=type(exc).__name__,
                        ),
                    )
                )
                continue
            published += len(published_windows)
            gap_recorded += len(gap_windows)
            if gap_windows and not published_windows:
                status = CommandStatus.ERROR
            elif gap_windows:
                status = CommandStatus.PARTIAL
            else:
                status = CommandStatus.PASSED
            results.append(
                TargetResult(
                    target=target,
                    status=status,
                    detail={
                        "planned_windows": _window_payload(planned_windows),
                        "published_windows": _window_payload(published_windows),
                        "gap_windows": _window_payload(gap_windows),
                        "provider": dataset.provider,
                        "dataset_kind": dataset.dataset_kind.value,
                        "symbol": dataset.symbol,
                        "contract_or_series": dataset.contract_or_series,
                        "frequency": dataset.frequency.value,
                        "adjustment": dataset.adjustment,
                        "schema_version": dataset.schema_version,
                    },
                )
            )
        return CommandResult(
            command="data.download",
            status=overall_batch_status(results),
            readonly=False,
            effects=EffectSummary(
                calls_rqdata=attempted > 0,
                writes_staging=published > 0,
                writes_canonical=published > 0,
                writes_postgresql=published > 0 or gap_recorded > 0,
                writes_historical_active=published > 0,
            ),
            targets=tuple(results),
        )

    def run(self, request: DownloadRequest) -> CommandResult:
        return self.execute(self.plan(request))

    def _resolve_covered(
        self,
        dataset: DatasetKey,
    ) -> Sequence[tuple[datetime, datetime]]:
        if self._covered_windows is not None:
            return tuple(self._covered_windows(dataset))
        if self._catalog is None:
            return ()
        partitions = self._catalog.list_partitions(dataset)
        covered: list[tuple[datetime, datetime]] = []
        for partition in partitions:
            start = getattr(partition, "coverage_start", None)
            end = getattr(partition, "coverage_end", None)
            if isinstance(start, datetime) and isinstance(end, datetime):
                covered.append((start, end))
        return tuple(covered)

    def _explicit_unavailable_prefix(
        self,
        target: DataTarget,
    ) -> tuple[datetime, datetime] | None:
        if self._listing_lower_bound is None:
            return None
        lower = self._listing_lower_bound(target)
        if lower is None or lower <= target.start:
            return None
        if lower >= target.end:
            return (target.start, target.end)
        return (target.start, lower)


def _window_payload(
    windows: Sequence[tuple[datetime, datetime]],
) -> list[dict[str, str]]:
    return [
        {"start": start.isoformat(), "end": end.isoformat()} for start, end in windows
    ]


def _merge_unavailable_prefix(
    windows: tuple[tuple[datetime, datetime], ...],
    unavailable: tuple[datetime, datetime],
    request_end: datetime,
) -> tuple[tuple[datetime, datetime], ...]:
    """Keep unavailable prefixes explicit; never clamp the request window away."""
    prefix_start, prefix_end = unavailable
    if prefix_end > request_end:
        prefix_end = request_end
    if prefix_start >= prefix_end:
        return windows
    merged = [(prefix_start, prefix_end), *windows]
    # Deduplicate exact duplicates while preserving order.
    seen: set[tuple[datetime, datetime]] = set()
    unique: list[tuple[datetime, datetime]] = []
    for window in merged:
        if window in seen:
            continue
        seen.add(window)
        unique.append(window)
    return tuple(unique)


def supports_download_frequency(value: object) -> bool:
    from app.data_core.contracts import BarFrequency

    try:
        parsed = value if isinstance(value, BarFrequency) else BarFrequency(str(value))
    except (TypeError, ValueError):
        return False
    return parsed in DIRECT_FREQUENCIES
