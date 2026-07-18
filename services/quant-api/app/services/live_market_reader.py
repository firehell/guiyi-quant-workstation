from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.models.data_center import Contract, LiveAggregatedBar, LiveMinuteBar
from app.schemas.market import (
    LiveMarketBarsQuality,
    LiveMarketBarsRequest,
    LiveMarketBarsResponse,
    MarketBarsCoverage,
    MarketCoverageContract,
    MarketCoverageInstrument,
    MarketCoverageItem,
    MarketCoveragePeriod,
    MarketCoverageSummary,
    MarketWorkbenchCoverage,
    MarketWorkbenchSelection,
)

SUPPORTED_LIVE_PERIODS = frozenset({"1m", "5m", "15m", "30m", "60m"})
AGGREGATED_LIVE_PERIODS = SUPPORTED_LIVE_PERIODS - {"1m"}
PERIOD_ORDER = {"1m": 0, "5m": 1, "15m": 2, "30m": 3, "60m": 4}


class LiveMarketReader:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_coverage(
        self,
        *,
        symbol: str | None = None,
        contract: str | None = None,
        period: str | None = None,
        include_paths: bool = False,
        summary: bool = False,
    ) -> MarketWorkbenchCoverage | MarketCoverageSummary:
        items = self._coverage_items(symbol=symbol, contract=contract, period=period)
        if not include_paths:
            for item in items:
                item.file_path = None

        if summary and symbol and contract and period:
            if not items:
                return MarketCoverageSummary(symbol=symbol, contract=contract, period=period, available=False)
            item = items[0]
            return MarketCoverageSummary(
                symbol=item.symbol,
                contract=item.contract,
                period=item.period,
                available=True,
                provider=item.provider,
                start_time=item.start_time,
                end_time=item.end_time,
                row_count=item.row_count,
                quality_status=item.quality_status,
            )

        return MarketWorkbenchCoverage(
            instruments=_group_instruments(items),
            items=items,
            default_selection=_default_selection(items),
        )

    def get_bars(
        self,
        *,
        symbol: str,
        contract: str,
        period: str,
        start: datetime | None,
        end: datetime | None,
        provider: str | None,
        source_mode: str | None,
        limit: int,
    ) -> LiveMarketBarsResponse:
        _ensure_supported_period(period)
        rows = self._rows(
            symbol=symbol,
            contract=contract,
            period=period,
            start=_naive(start) if start else None,
            end=_naive(end) if end else None,
            provider=provider,
            source_mode=source_mode,
        )
        chart_rows = [row for row in rows if row.quality_status != "failed" and row.bar_status == "confirmed"][:limit]
        bars = [_row_to_bar(row) for row in chart_rows]
        coverage = _coverage_from_rows(symbol=symbol, contract=contract, period=period, rows=rows)
        return LiveMarketBarsResponse(
            bars=bars,
            quality=_quality(rows, chart_rows=chart_rows),
            coverage=coverage,
            request=LiveMarketBarsRequest(
                symbol=symbol,
                contract=contract,
                period=period,
                start=start,
                end=end,
                provider=provider,
                source_mode=source_mode,
                limit=limit,
            ),
            message=None if bars else "当前选择没有可展示的 live K 线",
        )

    def _coverage_items(
        self,
        *,
        symbol: str | None = None,
        contract: str | None = None,
        period: str | None = None,
    ) -> list[MarketCoverageItem]:
        contracts = self._contracts(symbol=symbol, contract=contract)
        items = self._minute_coverage_items(contracts, symbol=symbol, contract=contract, period=period)
        items.extend(self._aggregated_coverage_items(contracts, symbol=symbol, contract=contract, period=period))
        return sorted(items, key=lambda item: (item.symbol, item.contract, _period_rank(item.period), item.start_time))

    def _minute_coverage_items(
        self,
        contracts: dict[str, Contract],
        *,
        symbol: str | None = None,
        contract: str | None = None,
        period: str | None = None,
    ) -> list[MarketCoverageItem]:
        query = (
            select(
                LiveMinuteBar.instrument_symbol,
                LiveMinuteBar.contract_code,
                LiveMinuteBar.period,
                LiveMinuteBar.provider,
                LiveMinuteBar.source_mode,
                func.min(LiveMinuteBar.bar_datetime),
                func.max(LiveMinuteBar.bar_datetime),
                func.count(),
                func.sum(_quality_case(LiveMinuteBar.quality_status, "failed")),
                func.sum(_quality_case(LiveMinuteBar.quality_status, "warning")),
            )
            .group_by(
                LiveMinuteBar.instrument_symbol,
                LiveMinuteBar.contract_code,
                LiveMinuteBar.period,
                LiveMinuteBar.provider,
                LiveMinuteBar.source_mode,
            )
            .order_by(LiveMinuteBar.instrument_symbol, LiveMinuteBar.contract_code, LiveMinuteBar.period)
        )
        if symbol is not None:
            query = query.where(LiveMinuteBar.instrument_symbol == symbol)
        if contract is not None:
            query = query.where(LiveMinuteBar.contract_code == contract)
        if period is not None:
            query = query.where(LiveMinuteBar.period == period)
        return [
            _coverage_item(
                symbol=row[0],
                contract=row[1],
                period=row[2],
                provider=row[3],
                source_mode=row[4],
                start_time=row[5],
                end_time=row[6],
                row_count=row[7],
                failed_count=row[8],
                warning_count=row[9],
                contracts=contracts,
            )
            for row in self.session.execute(query)
        ]

    def _aggregated_coverage_items(
        self,
        contracts: dict[str, Contract],
        *,
        symbol: str | None = None,
        contract: str | None = None,
        period: str | None = None,
    ) -> list[MarketCoverageItem]:
        query = (
            select(
                LiveAggregatedBar.instrument_symbol,
                LiveAggregatedBar.contract_code,
                LiveAggregatedBar.period,
                LiveAggregatedBar.provider,
                LiveAggregatedBar.source_mode,
                func.min(LiveAggregatedBar.bar_datetime),
                func.max(LiveAggregatedBar.bar_datetime),
                func.count(),
                func.sum(_quality_case(LiveAggregatedBar.quality_status, "failed")),
                func.sum(_quality_case(LiveAggregatedBar.quality_status, "warning")),
            )
            .where(LiveAggregatedBar.period.in_(AGGREGATED_LIVE_PERIODS))
            .group_by(
                LiveAggregatedBar.instrument_symbol,
                LiveAggregatedBar.contract_code,
                LiveAggregatedBar.period,
                LiveAggregatedBar.provider,
                LiveAggregatedBar.source_mode,
            )
            .order_by(LiveAggregatedBar.instrument_symbol, LiveAggregatedBar.contract_code, LiveAggregatedBar.period)
        )
        if symbol is not None:
            query = query.where(LiveAggregatedBar.instrument_symbol == symbol)
        if contract is not None:
            query = query.where(LiveAggregatedBar.contract_code == contract)
        if period is not None:
            query = query.where(LiveAggregatedBar.period == period)
        return [
            _coverage_item(
                symbol=row[0],
                contract=row[1],
                period=row[2],
                provider=row[3],
                source_mode=row[4],
                start_time=row[5],
                end_time=row[6],
                row_count=row[7],
                failed_count=row[8],
                warning_count=row[9],
                contracts=contracts,
            )
            for row in self.session.execute(query)
        ]

    def _rows(
        self,
        *,
        symbol: str,
        contract: str,
        period: str,
        start: datetime | None,
        end: datetime | None,
        provider: str | None,
        source_mode: str | None,
    ) -> list[LiveMinuteBar | LiveAggregatedBar]:
        model = LiveMinuteBar if period == "1m" else LiveAggregatedBar
        query: Select[tuple[LiveMinuteBar | LiveAggregatedBar]] = select(model).where(
            model.instrument_symbol == symbol,
            model.contract_code == contract,
            model.period == period,
        )
        if start is not None:
            query = query.where(model.bar_datetime >= start)
        if end is not None:
            query = query.where(model.bar_datetime <= end)
        if provider is not None:
            query = query.where(model.provider == provider)
        if source_mode is not None:
            query = query.where(model.source_mode == source_mode)
        return list(self.session.scalars(query.order_by(model.bar_datetime)))

    def _contracts(self, *, symbol: str | None = None, contract: str | None = None) -> dict[str, Contract]:
        query = select(Contract)
        if contract is not None:
            query = query.where(Contract.contract_code == contract)
        if symbol is not None:
            query = query.where(func.lower(Contract.instrument_symbol) == symbol.lower())
        return {item.contract_code: item for item in self.session.scalars(query)}


def _quality_case(column: Any, value: str) -> Any:
    return case((column == value, 1), else_=0)


def _coverage_item(
    *,
    symbol: str,
    contract: str,
    period: str,
    provider: str,
    source_mode: str,
    start_time: datetime,
    end_time: datetime,
    row_count: int,
    failed_count: int | None,
    warning_count: int | None,
    contracts: dict[str, Contract],
) -> MarketCoverageItem:
    contract_row = contracts.get(contract)
    return MarketCoverageItem(
        symbol=symbol,
        contract=contract,
        period=period,
        provider=provider,
        data_type="live_db",
        source_mode=source_mode,
        exchange=contract_row.exchange_code if contract_row else None,
        name=contract_row.name if contract_row else None,
        start_time=start_time,
        end_time=end_time,
        row_count=int(row_count or 0),
        quality_status=_aggregate_status(failed_count=failed_count, warning_count=warning_count),
    )


def _coverage_from_rows(*, symbol: str, contract: str, period: str, rows: list[LiveMinuteBar | LiveAggregatedBar]) -> MarketBarsCoverage | None:
    if not rows:
        return None
    failed_count = sum(1 for row in rows if row.quality_status == "failed")
    warning_count = sum(1 for row in rows if row.quality_status == "warning")
    return MarketBarsCoverage(
        symbol=symbol,
        contract=contract,
        period=period,
        provider=rows[0].provider,
        data_type="live_db",
        source_mode=rows[0].source_mode,
        start_time=min(row.bar_datetime for row in rows),
        end_time=max(row.bar_datetime for row in rows),
        row_count=len(rows),
        quality_status=_aggregate_status(failed_count=failed_count, warning_count=warning_count),
    )


def _quality(rows: list[LiveMinuteBar | LiveAggregatedBar], *, chart_rows: list[LiveMinuteBar | LiveAggregatedBar]) -> LiveMarketBarsQuality:
    failed_count = sum(1 for row in rows if row.quality_status == "failed")
    rejected_count = sum(1 for row in rows if row.bar_status == "rejected")
    warning_count = sum(1 for row in rows if row.quality_status == "warning")
    passed_count = sum(1 for row in rows if row.quality_status == "passed")
    partial_count = sum(
        1
        for row in rows
        if isinstance(row, LiveAggregatedBar) and row.expected_bar_count > 0 and row.source_bar_count < row.expected_bar_count
    )
    chart_warning_count = sum(1 for row in chart_rows if row.quality_status == "warning")
    return LiveMarketBarsQuality(
        status=_visible_status(chart_row_count=len(chart_rows), warning_count=chart_warning_count, partial_count=partial_count, failed_count=failed_count),
        row_count=len(rows),
        chart_row_count=len(chart_rows),
        passed_count=passed_count,
        warning_count=warning_count,
        failed_count=failed_count,
        rejected_count=rejected_count,
        partial_count=partial_count,
    )


def _visible_status(*, chart_row_count: int, warning_count: int, partial_count: int, failed_count: int) -> str:
    if warning_count or partial_count:
        return "warning"
    if chart_row_count == 0 and failed_count:
        return "failed"
    return "passed" if chart_row_count else "unchecked"


def _row_to_bar(row: LiveMinuteBar | LiveAggregatedBar) -> dict[str, Any]:
    raw_payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
    base = {
        "time": _naive(row.bar_datetime).isoformat(),
        "datetime": _naive(row.bar_datetime),
        "trading_day": row.trading_day,
        "symbol": row.instrument_symbol,
        "contract": row.contract_code,
        "exchange": row.exchange_code,
        "open": _float(row.open),
        "high": _float(row.high),
        "low": _float(row.low),
        "close": _float(row.close),
        "volume": _float(row.volume),
        "openInterest": _float(row.open_interest),
        "turnover": _float(row.turnover),
        "period": row.period,
        "provider": row.provider,
        "data_version": None,
        "bar_status": row.bar_status,
        "quality_status": row.quality_status,
        "source_mode": row.source_mode,
        "revision": row.revision,
        "quality_reasons": list(raw_payload.get("quality_reasons") or []),
    }
    if isinstance(row, LiveAggregatedBar):
        base.update(
            {
                "source_bar_count": row.source_bar_count,
                "expected_bar_count": row.expected_bar_count,
                "source_start_datetime": _iso(row.source_start_datetime),
                "source_end_datetime": _iso(row.source_end_datetime),
            }
        )
    return base


def _group_instruments(items: list[MarketCoverageItem]) -> list[MarketCoverageInstrument]:
    by_symbol: dict[str, list[MarketCoverageItem]] = defaultdict(list)
    for item in items:
        by_symbol[item.symbol].append(item)

    instruments: list[MarketCoverageInstrument] = []
    for symbol, symbol_items in sorted(by_symbol.items()):
        contract_groups: dict[str, list[MarketCoverageItem]] = defaultdict(list)
        for item in symbol_items:
            contract_groups[item.contract].append(item)
        contracts = [
            MarketCoverageContract(
                contract=contract,
                name=contract_items[0].name,
                exchange=contract_items[0].exchange,
                provider=contract_items[0].provider,
                status=None,
                periods=[
                    MarketCoveragePeriod(
                        period=item.period,
                        provider=item.provider,
                        data_type=item.data_type,
                        source_mode=item.source_mode,
                        start_time=item.start_time,
                        end_time=item.end_time,
                        row_count=item.row_count,
                        quality_status=item.quality_status,
                    )
                    for item in sorted(contract_items, key=lambda value: _period_rank(value.period))
                ],
            )
            for contract, contract_items in sorted(contract_groups.items())
        ]
        instruments.append(
            MarketCoverageInstrument(
                symbol=symbol,
                name=symbol_items[0].name,
                exchange=symbol_items[0].exchange,
                sector=None,
                contracts=contracts,
            )
        )
    return instruments


def _default_selection(items: list[MarketCoverageItem]) -> MarketWorkbenchSelection | None:
    if not items:
        return None
    selected = next((item for item in items if item.symbol == "jm" and item.period == "1m"), None) or items[0]
    return MarketWorkbenchSelection(
        symbol=selected.symbol,
        contract=selected.contract,
        period=selected.period,
        provider=selected.provider,
        start=selected.start_time,
        end=selected.end_time,
    )


def _aggregate_status(*, failed_count: int | None, warning_count: int | None) -> str:
    if failed_count:
        return "failed"
    if warning_count:
        return "warning"
    return "passed"


def _period_rank(period: str) -> int:
    return PERIOD_ORDER.get(period, 99)


def _ensure_supported_period(period: str) -> None:
    if period not in SUPPORTED_LIVE_PERIODS:
        raise ValueError(f"unsupported live market period: {period}")


def _float(value: Decimal | int | float | None) -> float | None:
    return None if value is None else float(value)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _naive(value).isoformat()


def _naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
