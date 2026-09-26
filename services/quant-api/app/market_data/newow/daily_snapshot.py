"""Resolve the latest verified D1 close without treating an unpublished tail as history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from time import monotonic
from typing import Literal

from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy

from app.market_data.market_data_service import MarketDataError
from app.market_data.diagnostics import data_reason
from app.market_data.errors import InfrastructureError

from .product_reader import NewowProductReadCancelled, NewowProductReadError, NewowProductReader
from .product_service import NewowProductService, NewowProductServiceError, ProductSection, ProductServiceQuery


_MISSING_DATA = frozenset({
    "REPLAY_PREFIX_MISSING", "REPLAY_ENDPOINTS_MISSING",
    "DATASET_OR_PARTITION_MISSING", "COMPLETE_PERIOD_MISSING",
})


class DailySnapshotError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DailySnapshot:
    product: str
    strategy: ProductStrategy
    frequency: ProductFrequency
    requested_at: datetime
    expected_trading_day: date
    available_trading_day: date
    as_of: datetime
    freshness: Literal["current", "pending_update"]


class NewowDailySnapshotResolver:
    def __init__(
        self,
        reader: NewowProductReader,
        service_factory: Callable[[Callable[[], bool]], NewowProductService],
        *,
        now: Callable[[], datetime],
        monotonic_clock: Callable[[], float] = monotonic,
        timeout_seconds: float = 30.0,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self._reader = reader
        self._service_factory = service_factory
        self._now = now
        self._clock = monotonic_clock
        self._timeout = timeout_seconds
        self._cancelled = cancelled or (lambda: False)

    def resolve(
        self, product: str, strategy: ProductStrategy, frequency: ProductFrequency
    ) -> DailySnapshot:
        if ProductFrequency(frequency) is not ProductFrequency.DAILY:
            raise DailySnapshotError("NEWOW_FREQUENCY_NOT_OPEN")
        requested_at = self._now()
        started = self._clock()

        def stopped() -> bool:
            return self._cancelled() or self._clock() - started >= self._timeout

        if stopped():
            raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
        candidates = self._reader.historical_snapshot_candidates(
            product, as_of=requested_at, limit=20, cancelled=stopped
        )
        if not candidates:
            raise DailySnapshotError("NEWOW_DAILY_SNAPSHOT_UNAVAILABLE")
        expected = candidates[0][0]
        service = self._service_factory(stopped)
        for day, cutoff in candidates:
            if stopped():
                raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
            try:
                result = service.query(ProductServiceQuery(
                    product, strategy, frequency, section=ProductSection.CHART,
                    as_of=cutoff,
                ))
            except (MarketDataError, InfrastructureError, NewowProductReadError, NewowProductServiceError) as exc:
                # A historical display is a separately validated earlier cutoff,
                # never a replacement Bar or a repair of the current snapshot.
                if exc.code == "MAIN_CONTRACT_MAP_MISSING":
                    try:
                        self._reader.dependency_owners(product, day, day)
                    except MarketDataError as owner_exc:
                        if owner_exc.code == "MAIN_CONTRACT_MAP_MISSING":
                            continue
                        raise
                    raise
                reason = getattr(exc, "reason", None) or data_reason(exc.code) or exc.code
                if reason in _MISSING_DATA or exc.code == "NEWOW_COMPLETE_TRADING_DAY_MISSING":
                    continue
                raise
            if stopped():
                raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
            if (
                result.section is not ProductSection.CHART
                or result.meta.as_of != cutoff
                or result.chart.delivery != "delivered"
                or result.chart.status is None
                or result.chart.status.status.value not in {"ready", "warming"}
            ):
                raise DailySnapshotError("NEWOW_DAILY_SNAPSHOT_INVALID")
            if result.chart.value is None:
                raise DailySnapshotError("NEWOW_DAILY_SNAPSHOT_UNAVAILABLE")
            return DailySnapshot(
                product, ProductStrategy(strategy), ProductFrequency(frequency),
                requested_at, expected, day, cutoff,
                "current" if day == expected else "pending_update",
            )
        raise DailySnapshotError("NEWOW_DAILY_SNAPSHOT_UNAVAILABLE")
