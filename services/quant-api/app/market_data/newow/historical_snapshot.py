"""Bounded read-only resolver for an explicitly selected historical Newow snapshot."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from time import monotonic
from typing import Literal

from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from app.market_data.market_data_service import MarketDataError
from app.market_data.diagnostics import MISSING_REASONS, data_reason
from app.market_data.errors import InfrastructureError

from .product_reader import (
    NewowProductReadCancelled,
    NewowProductReadError,
    NewowProductReader,
)
from .product_service import (
    AuxiliaryComponent,
    NewowProductService,
    NewowProductServiceError,
    ProductSection,
    SectionDelivery,
    ProductServiceQuery,
)
from .inflight import NewowComputationCancelled

_KNOWN_UNAVAILABLE = frozenset(
    {
        "NEWOW_COMPLETE_TRADING_DAY_MISSING",
        "NEWOW_COMPLETE_PERIOD_MISSING",
    }
)
_KNOWN_MARKET_UNAVAILABLE = frozenset(
    {
        "DATASET_OR_PARTITION_MISSING",
        "MAPPED_CONTRACT_DATASET_MISSING",
        "MAIN_CONTRACT_MAP_MISSING",
        "QUERY_WINDOW_EMPTY",
        "COMPLETE_WEEK_MISSING",
        "ACTUAL_DOMINANT_WEEKLY_DATASET_ABSENT",
        "DOMINANT_CONTEXT_MISSING",
        "TRADING_CALENDAR_MISSING",
        "TRADING_SESSION_MISSING",
        "CONTRACT_ACTIVE_WINDOW_MISSING",
    }
)


def is_historical_candidate_unavailable(error: str | MarketDataError | InfrastructureError) -> bool:
    if isinstance(error, str):
        return error in _KNOWN_MARKET_UNAVAILABLE
    reason = error.reason if isinstance(error, MarketDataError) else data_reason(error.code)
    return reason in MISSING_REASONS


class HistoricalSnapshotError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class HistoricalSnapshot:
    product: str
    strategy: ProductStrategy
    frequency: ProductFrequency
    trading_day: date
    as_of: datetime
    validated_sections: tuple[Literal["chart", "zhaoyao_mirror"], ...] = (
        "chart",
        "zhaoyao_mirror",
    )


class NewowHistoricalSnapshotResolver:
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
    ) -> HistoricalSnapshot:
        started = self._clock()

        def deadline_exceeded() -> bool:
            return self._clock() - started >= self._timeout

        def stopped() -> bool:
            return self._cancelled() or deadline_exceeded()

        if stopped():
            if deadline_exceeded():
                raise HistoricalSnapshotError("NEWOW_HISTORICAL_RESOLUTION_TIMEOUT")
            raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
        try:
            candidates = self._reader.historical_snapshot_candidates(
                product, as_of=self._now(), limit=20, cancelled=stopped
            )
        except NewowProductReadCancelled:
            if deadline_exceeded():
                raise HistoricalSnapshotError(
                    "NEWOW_HISTORICAL_RESOLUTION_TIMEOUT"
                ) from None
            raise
        service = self._service_factory(stopped)

        def delivery_unavailable(delivery: SectionDelivery) -> bool:
            if delivery.delivery != "delivered":
                raise HistoricalSnapshotError("NEWOW_HISTORICAL_SNAPSHOT_INVALID")
            status = delivery.status
            if status is None:
                raise HistoricalSnapshotError("NEWOW_HISTORICAL_SNAPSHOT_INVALID")
            if status.status.value == "ready" and delivery.value is not None:
                return False
            if (
                status.status.value == "unavailable"
                and delivery.value is None
                and status.reason_code in _KNOWN_UNAVAILABLE
            ):
                return True
            raise HistoricalSnapshotError("NEWOW_HISTORICAL_SNAPSHOT_INVALID")

        for trading_day, as_of in candidates:
            if stopped():
                if deadline_exceeded():
                    raise HistoricalSnapshotError("NEWOW_HISTORICAL_RESOLUTION_TIMEOUT")
                raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
            try:
                chart = service.query(
                    ProductServiceQuery(
                        product,
                        strategy,
                        frequency,
                        section=ProductSection.CHART,
                        as_of=as_of,
                    )
                )
                if stopped():
                    if deadline_exceeded():
                        raise HistoricalSnapshotError(
                            "NEWOW_HISTORICAL_RESOLUTION_TIMEOUT"
                        )
                    raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
                if chart.section is not ProductSection.CHART or chart.meta.as_of != as_of:
                    raise HistoricalSnapshotError("NEWOW_HISTORICAL_SNAPSHOT_INVALID")
                if delivery_unavailable(chart.chart):
                    continue
                mirror = service.query(
                    ProductServiceQuery(
                        product,
                        strategy,
                        frequency,
                        section=ProductSection.AUXILIARY,
                        component=AuxiliaryComponent.ZHAOYAO_MIRROR,
                        as_of=as_of,
                    )
                )
                if stopped():
                    if deadline_exceeded():
                        raise HistoricalSnapshotError("NEWOW_HISTORICAL_RESOLUTION_TIMEOUT")
                    raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
                if (
                    mirror.section is not ProductSection.AUXILIARY
                    or mirror.meta.as_of != as_of
                ):
                    raise HistoricalSnapshotError("NEWOW_HISTORICAL_SNAPSHOT_INVALID")
                if delivery_unavailable(mirror.auxiliary):
                    continue
                return HistoricalSnapshot(
                    product,
                    ProductStrategy(strategy),
                    ProductFrequency(frequency),
                    trading_day,
                    as_of,
                )
            except (NewowProductReadCancelled, NewowComputationCancelled):
                if deadline_exceeded():
                    raise HistoricalSnapshotError(
                        "NEWOW_HISTORICAL_RESOLUTION_TIMEOUT"
                    ) from None
                raise
            except (NewowProductReadError, NewowProductServiceError) as exc:
                if exc.code not in _KNOWN_UNAVAILABLE:
                    raise
            except (MarketDataError, InfrastructureError) as exc:
                if not is_historical_candidate_unavailable(exc):
                    raise
        if stopped():
            if deadline_exceeded():
                raise HistoricalSnapshotError("NEWOW_HISTORICAL_RESOLUTION_TIMEOUT")
            raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
        raise HistoricalSnapshotError("NEWOW_HISTORICAL_SNAPSHOT_UNAVAILABLE")
