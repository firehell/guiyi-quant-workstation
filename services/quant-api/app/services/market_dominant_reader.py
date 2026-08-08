from __future__ import annotations

from collections import defaultdict
import logging
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_core.contracts import BAR_FREQUENCY_VALUES
from app.models.data_center import Exchange, Instrument, MainContractMap
from app.models.data_core import DataGap, MarketDataset, MarketPartition
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

DEFAULT_QUOTE_PERIOD = "15m"
SUPPORTED_QUOTE_PERIODS = BAR_FREQUENCY_VALUES
logger = logging.getLogger(__name__)


class QuoteContractError(ValueError):
    """Raised when a continuous contract is used in quote mode."""


def validate_quote_contract(contract: str) -> None:
    if is_continuous_contract(contract):
        raise QuoteContractError("行情页请使用 actual_contract，主连 *.MAIN 仅用于连续序列研究")


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

            period_coverage = coverage_by_contract.get((product, actual_contract.upper()), {})
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
        """Build bars_coverage from Catalog actual_dominant partitions (not legacy MarketDataFile)."""
        query = select(MarketDataset).where(
            MarketDataset.provider == "rqdata",
            MarketDataset.dataset_kind == "actual_dominant",
        )
        if product_keys:
            query = query.where(MarketDataset.symbol.in_(sorted(product_keys)))
        datasets = list(self.session.scalars(query))
        if not datasets:
            return {}

        dataset_ids = [row.id for row in datasets]
        partitions = list(
            self.session.scalars(
                select(MarketPartition).where(MarketPartition.dataset_id.in_(dataset_ids))
            )
        )
        gap_dataset_ids = {
            dataset_id
            for dataset_id in self.session.scalars(
                select(DataGap.dataset_id).where(DataGap.dataset_id.in_(dataset_ids)).distinct()
            )
        }

        partitions_by_dataset: dict[int, list[MarketPartition]] = defaultdict(list)
        for partition in partitions:
            partitions_by_dataset[partition.dataset_id].append(partition)

        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for dataset in datasets:
            if is_synthetic_futures_contract(dataset.contract_or_series):
                continue
            if dataset.frequency not in SUPPORTED_QUOTE_PERIODS:
                continue
            rows = partitions_by_dataset.get(dataset.id) or []
            if not rows:
                continue
            has_gap = dataset.id in gap_dataset_ids
            key = (
                dataset.symbol.lower(),
                dataset.contract_or_series.upper(),
                dataset.frequency,
            )
            start_time = min(row.coverage_start for row in rows)
            end_time = max(row.coverage_end for row in rows)
            row_count = sum(row.row_count or 0 for row in rows)
            quality_status = "gap" if has_gap else "passed"
            record = grouped.setdefault(
                key,
                {
                    "available": True,
                    "start_time": start_time,
                    "end_time": end_time,
                    "row_count": 0,
                    "quality_status": quality_status,
                },
            )
            record["start_time"] = min(record["start_time"], start_time)
            record["end_time"] = max(record["end_time"], end_time)
            record["row_count"] += row_count
            record["quality_status"] = _aggregate_status(record["quality_status"], quality_status)

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
    statuses = {current, incoming}
    if "failed" in statuses:
        return "failed"
    if "gap" in statuses:
        return "gap"
    if "warning" in statuses:
        return "warning"
    if "unchecked" in statuses:
        return "unchecked"
    return "passed"
