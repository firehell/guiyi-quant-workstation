"""Resolve one verified complete W1 cutoff for every Newow section."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from time import monotonic
from typing import Literal
from zoneinfo import ZoneInfo

from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy

from app.market_data.market_data_service import MarketDataError

from .product_reader import NewowProductReadCancelled, NewowProductReader
from .product_release import CANDIDATE_WEEKLY_PRODUCTS
from .product_service import NewowProductService, ProductSection, ProductServiceQuery


PublicationState = Literal["pending_update", "failed", "stale", "unknown"]
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_AFTER_MARKET_SCHEDULE = time(18, 5)


def publication_state_from_status(
    status: Mapping[str, object], product: str, target_day: date, at: datetime,
) -> PublicationState:
    """Use exact run identity or the existing 18:05 target before tail fallback."""
    if product not in CANDIDATE_WEEKLY_PRODUCTS:
        return "unknown"
    current = status.get("current_run")
    last = status.get("last_run")
    target = target_day.isoformat()
    if isinstance(last, Mapping) and last.get("trading_day") == target:
        if product not in last.get("products", ()):
            return "unknown"
        return "failed" if last.get("status") != "passed" else "stale"
    if isinstance(current, Mapping):
        if current.get("scheduled_date") == target and product in current.get("products", ()):
            if at.astimezone(_SHANGHAI).date() > target_day:
                return "stale"
            return "pending_update"
        return "unknown"
    if (
        not isinstance(last, Mapping)
        or product not in last.get("products", ())
        or not isinstance(last.get("trading_day"), str)
        or last["trading_day"] >= target
    ):
        return "unknown"
    local = at.astimezone(_SHANGHAI)
    if local.date() == target_day and local.time() < _AFTER_MARKET_SCHEDULE:
        return "pending_update"
    return "unknown"


class WeeklySnapshotError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class WeeklySnapshot:
    product: str
    strategy: ProductStrategy
    frequency: ProductFrequency
    requested_at: datetime
    expected_period_end: datetime
    available_period_end: datetime
    as_of: datetime
    freshness: Literal["current", "pending_update"]
    current_context: dict[str, str | None]


class NewowWeeklySnapshotResolver:
    def __init__(
        self,
        reader: NewowProductReader,
        service_factory: Callable[[Callable[[], bool]], NewowProductService],
        *,
        now: Callable[[], datetime],
        publication_state: Callable[[str, object, datetime], PublicationState],
        monotonic_clock: Callable[[], float] = monotonic,
        timeout_seconds: float = 30.0,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self._reader = reader
        self._service_factory = service_factory
        self._now = now
        self._publication_state = publication_state
        self._clock = monotonic_clock
        self._timeout = timeout_seconds
        self._cancelled = cancelled or (lambda: False)

    def resolve(
        self, product: str, strategy: ProductStrategy, frequency: ProductFrequency,
    ) -> WeeklySnapshot:
        if ProductFrequency(frequency) is not ProductFrequency.WEEKLY:
            raise WeeklySnapshotError("NEWOW_FREQUENCY_NOT_OPEN")
        requested_at = self._now()
        started = self._clock()

        def stopped() -> bool:
            return self._cancelled() or self._clock() - started >= self._timeout

        if stopped():
            raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
        candidates = self._reader.weekly_snapshot_candidates(
            product, as_of=requested_at, limit=2, cancelled=stopped,
        )
        if not candidates:
            raise WeeklySnapshotError("NEWOW_WEEKLY_UNKNOWN")
        expected = candidates[0][1]
        service = self._service_factory(stopped)
        context = self._reader.current_owner_context(product, requested_at)
        pending = False
        for index, (day, cutoff) in enumerate(candidates):
            if stopped():
                raise NewowProductReadCancelled("NEWOW_READ_CANCELLED")
            try:
                result = service.query(ProductServiceQuery(
                    product, strategy, frequency, section=ProductSection.CHART,
                    as_of=cutoff,
                ))
            except MarketDataError as exc:
                if index != 0 or exc.code != "MAIN_CONTRACT_MAP_MISSING":
                    raise
                if not self._reader.weekly_tail_unpublished(product, day):
                    raise WeeklySnapshotError("NEWOW_WEEKLY_UNKNOWN") from exc
                state = self._publication_state(product, day, requested_at)
                if state not in ("pending_update", "failed", "stale", "unknown"):
                    raise WeeklySnapshotError("NEWOW_WEEKLY_UNKNOWN") from exc
                if state != "pending_update":
                    raise WeeklySnapshotError(f"NEWOW_WEEKLY_{state.upper()}") from exc
                pending = True
                continue
            if (
                result.section is not ProductSection.CHART
                or result.meta.as_of != cutoff
                or result.chart.delivery != "delivered"
                or result.chart.status is None
                or result.chart.value is None
            ):
                raise WeeklySnapshotError("NEWOW_WEEKLY_UNKNOWN")
            return WeeklySnapshot(
                product, ProductStrategy(strategy), ProductFrequency(frequency),
                requested_at, expected, cutoff, cutoff,
                "pending_update" if pending else "current", context,
            )
        raise WeeklySnapshotError("NEWOW_WEEKLY_UNKNOWN")
