"""Latest/window bar helper over MarketDataService for historical consumers.

Live observation remains on LiveMarketReader. Profile/MarketDataFile selectors
are not accepted as bar selectors; callers may still validate Profile identity
separately, then read bars here by DatasetKey.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.data_core.bar_schema import CANONICAL_BAR_SCHEMA_VERSION
from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import (
    BarQuery,
    DataCoreError,
    DatasetKey,
    DatasetKind,
    parse_bar_frequency,
)
from app.services.canonical_market_data import build_canonical_reader
from app.services.market_data_service import MarketDataService

SHANGHAI = ZoneInfo("Asia/Shanghai")
HISTORICAL_BAR_SOURCE_CANONICAL = "canonical"


class CanonicalBarLoader:
    """Fail-closed latest/window bar reads through the V2 historical facade."""

    def __init__(
        self,
        session: Session,
        *,
        market_data: MarketDataService | None = None,
    ) -> None:
        self.session = session
        self._market_data = market_data
        self._catalog = HistoricalCatalog(session)

    def load_latest_bars(
        self,
        symbol: str,
        contract: str,
        period: str,
        *,
        limit: int = 500,
        provider: str | None = None,
        data_role: str = "primary",
    ) -> list[dict[str, Any]]:
        del provider, data_role
        if limit <= 0:
            return []
        query = self._latest_query(symbol=symbol, contract=contract, period=period)
        result = self._service().get_bars(query)
        return [
            _bar_payload(item, exchange=None)
            for item in result.bars[-limit:]
        ]

    def load_bars(
        self,
        symbol: str,
        contract: str,
        period: str,
        *,
        start: datetime,
        end: datetime,
        limit: int | None = None,
        tail: bool = False,
        provider: str | None = None,
        data_role: str = "primary",
    ) -> list[dict[str, Any]]:
        del provider, data_role
        query = BarQuery(
            dataset_kind=self._dataset_kind(contract),
            symbol=symbol,
            contract_or_series=contract,
            frequency=parse_bar_frequency(period),
            start=_as_aware(start),
            end=_as_aware(end),
        )
        result = self._service().get_bars(query)
        bars = [_bar_payload(item, exchange=None) for item in result.bars]
        if limit is None or limit <= 0 or len(bars) <= limit:
            return bars
        return bars[-limit:] if tail else bars[:limit]

    def get_quality_status(
        self,
        *,
        symbol: str,
        contract: str,
        period: str,
        start: datetime | None = None,
        end: datetime | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        del provider
        key = self._dataset_key(symbol=symbol, contract=contract, period=period)
        partitions = self._catalog.list_partitions(key)
        if not partitions:
            return _quality_payload(
                status="failed",
                provider="rqdata",
                report_count=0,
            )
        coverage_start = min(item.coverage_start for item in partitions)
        coverage_end = max(item.coverage_end for item in partitions)
        window_start = _as_aware(start) if start is not None else coverage_start
        window_end = _as_aware(end) if end is not None else coverage_end
        gaps = self._catalog.list_gaps(key)
        intersecting = [
            gap
            for gap in gaps
            if _as_aware(gap.gap_end) >= window_start
            and _as_aware(gap.gap_start) <= window_end
        ]
        status = "failed" if intersecting else "passed"
        return _quality_payload(
            status=status,
            provider=key.provider,
            report_count=len(intersecting),
            coverage_start=coverage_start.isoformat(),
            coverage_end=coverage_end.isoformat(),
        )

    def _service(self) -> MarketDataService:
        if self._market_data is None:
            self._market_data = MarketDataService(
                self.session,
                canonical_reader=build_canonical_reader(self.session),
            )
        return self._market_data

    def _latest_query(
        self, *, symbol: str, contract: str, period: str
    ) -> BarQuery:
        key = self._dataset_key(symbol=symbol, contract=contract, period=period)
        partitions = self._catalog.list_partitions(key)
        if not partitions:
            raise DataCoreError(
                facts={
                    "reason": "canonical_coverage_missing",
                    "symbol": symbol,
                    "contract": contract,
                    "period": period,
                }
            )
        coverage_start = min(item.coverage_start for item in partitions)
        coverage_end = max(item.coverage_end for item in partitions)
        start = max(coverage_start, coverage_end - timedelta(days=3650))
        return BarQuery(
            dataset_kind=key.dataset_kind,
            symbol=key.symbol,
            contract_or_series=key.contract_or_series,
            frequency=key.frequency,
            start=start,
            end=coverage_end,
        )

    def _dataset_key(
        self, *, symbol: str, contract: str, period: str
    ) -> DatasetKey:
        return DatasetKey(
            provider="rqdata",
            dataset_kind=self._dataset_kind(contract),
            symbol=symbol.strip().lower(),
            contract_or_series=contract.strip().upper(),
            frequency=parse_bar_frequency(period),
            adjustment="none",
            schema_version=CANONICAL_BAR_SCHEMA_VERSION,
        )

    @staticmethod
    def _dataset_kind(contract: str) -> DatasetKind:
        if contract.strip().upper().endswith(".MAIN"):
            return DatasetKind.CONTINUOUS
        return DatasetKind.ACTUAL_DOMINANT


def shanghai_naive_bound_to_utc(value: datetime) -> datetime:
    """Treat naive MarketDataFile / legacy bounds as Asia/Shanghai, return UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=SHANGHAI).astimezone(UTC)
    return value.astimezone(UTC)


def query_bound_to_utc(value: datetime) -> datetime:
    """Normalize a workbench/API query bound to UTC for Canonical reads.

    Aware values keep their instant. Naive values from MarketDataFile / coverage
    are treated as Asia/Shanghai (legacy store convention).
    """
    return shanghai_naive_bound_to_utc(value)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _quality_payload(
    *,
    status: str,
    provider: str,
    report_count: int,
    coverage_start: str | None = None,
    coverage_end: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "provider": provider,
        "report_count": report_count,
        "missing_bars": 0,
        "duplicated_bars": 0,
        "abnormal_price_count": 0,
        "abnormal_volume_count": 0,
        "warning_reasons": [],
        "cross_file_conflicts": 0,
        "conflict_details": None,
    }
    if coverage_start is not None:
        payload["coverage_start"] = coverage_start
    if coverage_end is not None:
        payload["coverage_end"] = coverage_end
    return payload


def _bar_payload(bar: Any, *, exchange: str | None) -> dict[str, Any]:
    return {
        "symbol": bar.symbol,
        "contract": bar.contract_or_series,
        "exchange": exchange,
        "datetime": bar.bar_end,
        "trading_day": bar.trading_day,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume),
        "turnover": None if bar.turnover is None else float(bar.turnover),
        "open_interest": None
        if bar.open_interest is None
        else float(bar.open_interest),
        "period": bar.frequency.value,
        "provider": bar.provider,
    }
