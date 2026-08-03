from __future__ import annotations

from collections import defaultdict
import logging
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_core.contracts import BAR_FREQUENCY_VALUES
from app.models.data_center import Exchange, Instrument, MainContractMap, MarketDataFile
from app.schemas.market import (
    DominantBarsCoveragePeriod,
    DominantContractItem,
    DominantContractListResponse,
)
from app.services.futures_contract_utils import (
    continuous_contract_for,
    display_product_name,
    is_continuous_contract,
    is_synthetic_futures_contract,
    normalize_product_name,
)

__all__ = [
    "DEFAULT_QUOTE_PERIOD",
    "DominantContractReader",
    "QuoteContractError",
    "continuous_contract_for",
    "is_continuous_contract",
    "is_synthetic_futures_contract",
    "normalize_product_name",
    "validate_quote_contract",
]
from app.services.market_data_reader import ACTIVE_DATA_ROLE, ACTIVE_PRIMARY_PROVIDERS

DEFAULT_QUOTE_PERIOD = "15m"
SUPPORTED_QUOTE_PERIODS = BAR_FREQUENCY_VALUES
logger = logging.getLogger(__name__)


class QuoteContractError(ValueError):
    """Raised when a continuous contract is used in quote mode."""


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
        symbol: str | None = None,
    ) -> DominantContractListResponse:
        started = time.perf_counter()
        latest_mappings = self._latest_rank1_mappings(symbol=symbol)
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
        coverage_by_contract = self._coverage_by_product_contract(product_keys=product_keys)

        items: list[DominantContractItem] = []
        for mapping in sorted(latest_mappings, key=lambda row: row.instrument_symbol.lower()):
            product = mapping.instrument_symbol.lower()
            instrument = instruments.get(product)
            exchange_code = instrument.exchange_code if instrument else None
            if exchange and exchange_code and exchange_code.upper() != exchange.upper():
                continue

            actual_contract = mapping.contract_code
            if not actual_contract or is_synthetic_futures_contract(actual_contract):
                continue

            period_coverage = coverage_by_contract.get((product, actual_contract), {})
            quote_period = self._quote_period_coverage(period_coverage)
            item = DominantContractItem(
                product=product,
                product_name=display_product_name(instrument.name if instrument else None, product),
                exchange=exchange_code,
                exchange_name=exchanges[exchange_code].name if exchange_code and exchange_code in exchanges else None,
                sector=instrument.sector if instrument else None,
                category=instrument.category if instrument else None,
                is_active=instrument.is_active if instrument else True,
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

        total_ms = (time.perf_counter() - started) * 1000
        logger.info("dominants items=%d total_ms=%.1f symbol=%s", len(items), total_ms, symbol)
        if total_ms >= 5000:
            logger.warning("slow dominants total_ms=%.1f symbol=%s", total_ms, symbol)
        elif total_ms >= 1000:
            logger.info("slow dominants total_ms=%.1f symbol=%s", total_ms, symbol)

        return DominantContractListResponse(items=items, default_quote_period=DEFAULT_QUOTE_PERIOD)

    def _latest_rank1_mappings(self, *, symbol: str | None = None) -> list[MainContractMap]:
        product_key = func.lower(MainContractMap.instrument_symbol)
        query = select(MainContractMap).where(
            MainContractMap.rank == 1,
            MainContractMap.provider == "rqdata",
        )
        if symbol is not None:
            query = query.where(product_key == symbol.lower())
        rows = self.session.scalars(
            query.order_by(product_key, MainContractMap.trade_date.desc(), MainContractMap.created_at.desc(), MainContractMap.id.desc())
        ).all()
        if not rows:
            return []

        mappings: list[MainContractMap] = []
        seen_products: set[str] = set()
        for row in rows:
            product = (row.instrument_symbol or "").lower()
            if product in seen_products:
                continue
            if not row.contract_code or is_synthetic_futures_contract(row.contract_code):
                continue
            seen_products.add(product)
            mappings.append(row)
        return mappings

    def _coverage_by_product_contract(
        self,
        *,
        product_keys: set[str] | None = None,
    ) -> dict[tuple[str, str], dict[str, DominantBarsCoveragePeriod]]:
        query = select(MarketDataFile).where(
            MarketDataFile.data_type == "bars",
            MarketDataFile.data_role == ACTIVE_DATA_ROLE,
            MarketDataFile.provider.in_(tuple(ACTIVE_PRIMARY_PROVIDERS)),
            MarketDataFile.quality_status != "failed",
            MarketDataFile.instrument_symbol.is_not(None),
            MarketDataFile.contract_code.is_not(None),
            MarketDataFile.period.is_not(None),
        )
        if product_keys:
            query = query.where(func.lower(MarketDataFile.instrument_symbol).in_(product_keys))
        files = self.session.scalars(query).all()

        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for file in files:
            if is_synthetic_futures_contract(file.contract_code or ""):
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
