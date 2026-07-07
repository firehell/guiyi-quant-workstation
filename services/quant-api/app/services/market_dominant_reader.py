from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import Exchange, Instrument, MainContractMap, MarketDataFile
from app.schemas.market import (
    DominantBarsCoveragePeriod,
    DominantContractItem,
    DominantContractListResponse,
)
from app.services.market_data_reader import ACTIVE_DATA_ROLE, ACTIVE_PRIMARY_PROVIDERS

DEFAULT_QUOTE_PERIOD = "15m"
CONTINUOUS_SUFFIX = ".MAIN"
SUPPORTED_QUOTE_PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d")


class QuoteContractError(ValueError):
    """Raised when a continuous contract is used in quote mode."""


def is_continuous_contract(contract: str) -> bool:
    normalized = (contract or "").strip()
    return normalized.upper().endswith(CONTINUOUS_SUFFIX)


def continuous_contract_for(product: str) -> str:
    return f"{product.strip().lower()}{CONTINUOUS_SUFFIX}"


def validate_quote_contract(contract: str) -> None:
    if is_continuous_contract(contract):
        raise QuoteContractError("行情页请使用 actual_contract，主连 *.MAIN 仅用于回测")


class DominantContractReader:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_dominants(
        self,
        *,
        exchange: str | None = None,
        quote_ready: bool | None = None,
        search: str | None = None,
    ) -> DominantContractListResponse:
        latest_mappings = self._latest_rank1_mappings()
        if not latest_mappings:
            return DominantContractListResponse(items=[], default_quote_period=DEFAULT_QUOTE_PERIOD)

        product_keys = {item.instrument_symbol.lower() for item in latest_mappings}
        instruments = {
            item.symbol.lower(): item
            for item in self.session.scalars(select(Instrument).where(func.lower(Instrument.symbol).in_(product_keys)))
        }
        exchanges = {
            item.code: item
            for item in self.session.scalars(
                select(Exchange).where(
                    Exchange.code.in_({inst.exchange_code for inst in instruments.values() if inst.exchange_code})
                )
            )
        }
        coverage_by_contract = self._coverage_by_product_contract()

        items: list[DominantContractItem] = []
        for mapping in sorted(latest_mappings, key=lambda row: row.instrument_symbol.lower()):
            product = mapping.instrument_symbol.lower()
            instrument = instruments.get(product)
            exchange_code = instrument.exchange_code if instrument else None
            if exchange and exchange_code and exchange_code.upper() != exchange.upper():
                continue

            actual_contract = mapping.contract_code
            period_coverage = coverage_by_contract.get((product, actual_contract), {})
            quote_period = self._quote_period_coverage(period_coverage)
            item = DominantContractItem(
                product=product,
                product_name=instrument.name if instrument else product.upper(),
                exchange=exchange_code,
                exchange_name=exchanges[exchange_code].name if exchange_code and exchange_code in exchanges else None,
                continuous_contract=continuous_contract_for(product),
                actual_contract=actual_contract,
                dominant_mapping_date=mapping.trade_date,
                bars_coverage=period_coverage,
                quote_ready=quote_period is not None and quote_period.available,
                default_period=DEFAULT_QUOTE_PERIOD,
            )
            if quote_ready is True and not item.quote_ready:
                continue
            if quote_ready is False and item.quote_ready:
                continue
            if search and not self._matches_search(item, search):
                continue
            items.append(item)

        return DominantContractListResponse(items=items, default_quote_period=DEFAULT_QUOTE_PERIOD)

    def _latest_rank1_mappings(self) -> list[MainContractMap]:
        latest_dates = dict(
            self.session.execute(
                select(MainContractMap.instrument_symbol, func.max(MainContractMap.trade_date)).where(
                    MainContractMap.rank == 1,
                    MainContractMap.provider == "rqdata",
                ).group_by(MainContractMap.instrument_symbol)
            ).all()
        )
        if not latest_dates:
            return []

        mappings: list[MainContractMap] = []
        for product, trade_date in latest_dates.items():
            row = self.session.scalar(
                select(MainContractMap)
                .where(
                    MainContractMap.instrument_symbol == product,
                    MainContractMap.trade_date == trade_date,
                    MainContractMap.rank == 1,
                    MainContractMap.provider == "rqdata",
                )
                .order_by(MainContractMap.created_at.desc(), MainContractMap.id.desc())
            )
            if row is not None and row.contract_code and not is_continuous_contract(row.contract_code):
                mappings.append(row)
        return mappings

    def _coverage_by_product_contract(
        self,
    ) -> dict[tuple[str, str], dict[str, DominantBarsCoveragePeriod]]:
        files = self.session.scalars(
            select(MarketDataFile).where(
                MarketDataFile.data_type == "bars",
                MarketDataFile.data_role == ACTIVE_DATA_ROLE,
                MarketDataFile.provider.in_(tuple(ACTIVE_PRIMARY_PROVIDERS)),
                MarketDataFile.quality_status != "failed",
                MarketDataFile.instrument_symbol.is_not(None),
                MarketDataFile.contract_code.is_not(None),
                MarketDataFile.period.is_not(None),
            )
        ).all()

        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for file in files:
            if is_continuous_contract(file.contract_code or ""):
                continue
            key = (
                (file.instrument_symbol or "").lower(),
                file.contract_code or "",
                file.period or "",
            )
            record = grouped.setdefault(
                key,
                {
                    "available": True,
                    "start_time": file.start_time,
                    "end_time": file.end_time,
                    "row_count": 0,
                    "quality_status": file.quality_status,
                },
            )
            record["start_time"] = min(record["start_time"], file.start_time)
            record["end_time"] = max(record["end_time"], file.end_time)
            record["row_count"] += file.row_count or 0
            record["quality_status"] = _aggregate_status(record["quality_status"], file.quality_status)

        by_contract: dict[tuple[str, str], dict[str, DominantBarsCoveragePeriod]] = defaultdict(dict)
        for (product, contract, period), record in grouped.items():
            by_contract[(product, contract)][period] = DominantBarsCoveragePeriod(
                available=True,
                start_time=record["start_time"],
                end_time=record["end_time"],
                row_count=record["row_count"],
                quality_status=record["quality_status"],
            )
        return by_contract

    @staticmethod
    def _quote_period_coverage(
        period_coverage: dict[str, DominantBarsCoveragePeriod],
    ) -> DominantBarsCoveragePeriod | None:
        period = period_coverage.get(DEFAULT_QUOTE_PERIOD)
        if period is not None and period.available and period.quality_status == "passed":
            return period
        for name in SUPPORTED_QUOTE_PERIODS:
            candidate = period_coverage.get(name)
            if candidate is not None and candidate.available and candidate.quality_status == "passed":
                return candidate
        return None

    @staticmethod
    def _matches_search(item: DominantContractItem, search: str) -> bool:
        needle = search.strip().lower()
        if not needle:
            return True
        haystacks = [
            item.product,
            item.product_name,
            item.actual_contract,
            item.exchange or "",
            item.exchange_name or "",
        ]
        return any(needle in value.lower() for value in haystacks if value)


def _aggregate_status(current: str, incoming: str) -> str:
    statuses = [current, incoming]
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    if "unchecked" in statuses:
        return "unchecked"
    return "passed"
