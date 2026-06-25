from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import Contract, Instrument, MarketDataFile
from app.schemas.market import (
    MarketBarsCoverage,
    MarketBarsQuality,
    MarketBarsRequest,
    MarketBarsResponse,
    MarketCoverageContract,
    MarketCoverageInstrument,
    MarketCoverageItem,
    MarketCoveragePeriod,
    MarketWorkbenchCoverage,
    MarketWorkbenchSelection,
)
from app.services.market_data_reader import MarketDataReader

PERIOD_ORDER = {"1m": 0, "5m": 1, "15m": 2, "30m": 3, "60m": 4, "1d": 5}


def get_workbench_coverage(session: Session) -> MarketWorkbenchCoverage:
    reader = MarketDataReader(session)
    files = [item for item in reader.get_coverage() if item.instrument_symbol and item.contract_code and item.period]
    items = _aggregate_items(session, files)
    return MarketWorkbenchCoverage(
        instruments=_group_instruments(items),
        items=items,
        default_selection=_default_selection(items),
    )


def get_market_bars(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    start: datetime | None,
    end: datetime | None,
    provider: str | None,
    limit: int,
) -> MarketBarsResponse:
    coverage = _coverage_for_request(session, symbol=symbol, contract=contract, period=period, provider=provider)
    start_time = start or coverage.start_time if coverage else start
    end_time = end or coverage.end_time if coverage else end
    query_start = _naive(start_time or datetime.min)
    query_end = _naive(end_time or datetime.max)
    bars = MarketDataReader(session).load_bars(
        symbol=symbol,
        contract=contract,
        period=period,
        start=query_start,
        end=query_end,
        provider=provider,
        limit=limit,
    )
    quality = MarketDataReader(session).get_quality_status(
        symbol=symbol,
        contract=contract,
        period=period,
        start=query_start,
        end=query_end,
        provider=provider,
    )
    return MarketBarsResponse(
        bars=bars,
        quality=MarketBarsQuality(**quality),
        coverage=coverage,
        request=MarketBarsRequest(
            symbol=symbol,
            contract=contract,
            period=period,
            start=start_time,
            end=end_time,
            provider=provider,
            limit=limit,
        ),
        message=None if bars else "当前选择没有可展示的 K 线",
    )


def _aggregate_items(session: Session, files: list[MarketDataFile]) -> list[MarketCoverageItem]:
    contracts = {
        item.contract_code: item
        for item in session.scalars(select(Contract).where(Contract.contract_code.in_({file.contract_code for file in files})))
    }
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for file in files:
        key = (file.instrument_symbol or "", file.contract_code or "", file.period or "", file.provider, file.data_type)
        record = grouped.setdefault(
            key,
            {
                "symbol": file.instrument_symbol or "",
                "contract": file.contract_code or "",
                "period": file.period or "",
                "provider": file.provider,
                "data_type": file.data_type,
                "start_time": file.start_time,
                "end_time": file.end_time,
                "row_count": 0,
                "statuses": [],
            },
        )
        record["start_time"] = min(record["start_time"], file.start_time)
        record["end_time"] = max(record["end_time"], file.end_time)
        record["row_count"] += file.row_count or 0
        record["statuses"].append(file.quality_status)

    items: list[MarketCoverageItem] = []
    for record in grouped.values():
        contract = contracts.get(record["contract"])
        items.append(
            MarketCoverageItem(
                symbol=record["symbol"],
                contract=record["contract"],
                period=record["period"],
                provider=record["provider"],
                data_type=record["data_type"],
                exchange=contract.exchange_code if contract else None,
                name=contract.name if contract else None,
                start_time=record["start_time"],
                end_time=record["end_time"],
                row_count=record["row_count"],
                quality_status=_aggregate_status(record["statuses"]),
            )
        )
    return sorted(items, key=lambda item: (item.symbol, item.contract, _period_rank(item.period), item.start_time))


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
    preferred = next((item for item in items if item.symbol == "rb" and item.contract == "rb.MAIN" and item.period == "5m"), None)
    selected = preferred or next((item for item in items if item.period == "5m"), None) or items[0]
    return MarketWorkbenchSelection(
        symbol=selected.symbol,
        contract=selected.contract,
        period=selected.period,
        provider=selected.provider,
        start=selected.start_time,
        end=selected.end_time,
    )


def _coverage_for_request(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    provider: str | None,
) -> MarketBarsCoverage | None:
    files = MarketDataReader(session).get_coverage(symbol=symbol, contract=contract, period=period)
    if provider is not None:
        files = [file for file in files if file.provider == provider]
    items = _aggregate_items(session, files)
    if not items:
        return None
    item = items[0]
    return MarketBarsCoverage(
        symbol=item.symbol,
        contract=item.contract,
        period=item.period,
        provider=item.provider,
        data_type=item.data_type,
        start_time=item.start_time,
        end_time=item.end_time,
        row_count=item.row_count,
        quality_status=item.quality_status,
    )


def _aggregate_status(statuses: list[str]) -> str:
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    if "unchecked" in statuses:
        return "unchecked"
    return "passed" if statuses else "unchecked"


def _period_rank(period: str) -> int:
    return PERIOD_ORDER.get(period, 99)


def _naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
