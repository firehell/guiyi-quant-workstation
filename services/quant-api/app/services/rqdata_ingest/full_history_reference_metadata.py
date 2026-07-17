from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.data_center import (
    Contract,
    FuturesContinuousContractMap,
    FuturesContractUniverse,
    FuturesTradingParameter,
    MainContractMap,
    TradingCalendar,
)
from app.services.rqdata_ingest.full_history_contract import ActualRank1Range


GAP_CATEGORIES = frozenset(
    {
        "asset_registration_gap",
        "main_contract_map_gap",
        "contract_universe_gap",
        "continuous_contract_map_gap",
        "trading_parameter_gap",
        "trading_calendar_gap",
        "trading_session_gap",
    }
)


@dataclass(frozen=True)
class ReferenceMetadataConfig:
    products: tuple[str, ...]
    audit_end: date
    require_postgresql: bool = True
    actual_role_products: tuple[str, ...] = ()
    continuous_role_products: tuple[str, ...] = ()
    minute_scope_products: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceMetadataResult:
    matrix: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    rank1_ranges: tuple[ActualRank1Range, ...]
    listing_dates: dict[str, date]
    exchange_by_product: dict[str, str]
    trading_days_by_product: dict[str, tuple[date, ...]]


def collect_reference_metadata(
    session: Session,
    config: ReferenceMetadataConfig,
) -> ReferenceMetadataResult:
    dialect = session.get_bind().dialect.name
    if config.require_postgresql and dialect != "postgresql":
        raise RuntimeError(f"ENV_BLOCKED_DB: direct PostgreSQL required, got {dialect}")
    if dialect == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))

    products = tuple(sorted({item.strip().lower() for item in config.products if item.strip()}))
    actual_products = set(config.actual_role_products or products)
    continuous_products = set(config.continuous_role_products)
    minute_products = set(config.minute_scope_products or products)
    matrix: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    contract_rows = list(
        session.execute(
            select(Contract.product, Contract.instrument_symbol, Contract.exchange_code, func.min(Contract.listed_date))
            .where(func.lower(func.coalesce(Contract.product, Contract.instrument_symbol)).in_(products))
            .group_by(Contract.product, Contract.instrument_symbol, Contract.exchange_code)
        )
    )
    listing_dates: dict[str, date] = {}
    exchange_by_product: dict[str, str] = {}
    for product_value, instrument_symbol, exchange_code, listed_date in contract_rows:
        product = (product_value or instrument_symbol or "").lower()
        if listed_date is not None:
            listing_dates[product] = min(listing_dates.get(product, listed_date), listed_date)
        if exchange_code:
            exchange_by_product[product] = exchange_code

    for product in products:
        _append_status(
            matrix,
            gaps,
            product=product,
            metadata_type="asset_registration",
            applicable=True,
            status="passed" if product in listing_dates else "gap",
            reason="registered_contract_listing" if product in listing_dates else "missing_contract_listing",
            gap_category="asset_registration_gap",
            start=listing_dates.get(product),
            end=config.audit_end,
        )

    rank_rows = list(
        session.execute(
            select(MainContractMap.instrument_symbol, MainContractMap.trade_date, MainContractMap.contract_code)
            .where(
                func.lower(MainContractMap.instrument_symbol).in_(products),
                MainContractMap.rank == 1,
                MainContractMap.trade_date <= config.audit_end,
            )
            .order_by(MainContractMap.instrument_symbol, MainContractMap.trade_date)
        )
    )
    rank_by_product: dict[str, list[tuple[date, str]]] = defaultdict(list)
    for product, trade_date, contract in rank_rows:
        rank_by_product[product.lower()].append((trade_date, contract))
    universe_bounds = _bounds_by_product(
        session,
        FuturesContractUniverse,
        products,
        config.audit_end,
    )
    parameter_bounds = _bounds_by_product(
        session,
        FuturesTradingParameter,
        products,
        config.audit_end,
    )
    continuous_bounds = _bounds_by_product(
        session,
        FuturesContinuousContractMap,
        products,
        config.audit_end,
    )

    trading_days_by_exchange: dict[str, tuple[date, ...]] = {}
    for exchange in sorted(set(exchange_by_product.values())):
        days = tuple(
            session.scalars(
                select(TradingCalendar.trade_date)
                .where(
                    TradingCalendar.exchange_code == exchange,
                    TradingCalendar.is_trading_day.is_(True),
                    TradingCalendar.trade_date <= config.audit_end,
                )
                .order_by(TradingCalendar.trade_date)
            )
        )
        trading_days_by_exchange[exchange] = days

    for product in products:
        listing = listing_dates.get(product)
        rank_bounds = _tuple_bounds(rank_by_product.get(product, []))
        actual = product in actual_products
        _append_status(
            matrix,
            gaps,
            product=product,
            metadata_type="main_contract_map",
            applicable=actual,
            status="passed" if rank_bounds else "gap",
            reason="rank1_mapping_present" if rank_bounds else "missing_rank1_mapping",
            gap_category="main_contract_map_gap",
            start=rank_bounds[0] if rank_bounds else None,
            end=rank_bounds[1] if rank_bounds else None,
        )
        _append_status(
            matrix,
            gaps,
            product=product,
            metadata_type="contract_universe",
            applicable=actual or product in minute_products,
            status="passed" if product in universe_bounds else "gap",
            reason="contract_universe_present" if product in universe_bounds else "missing_contract_universe",
            gap_category="contract_universe_gap",
            start=universe_bounds.get(product, (None, None))[0],
            end=universe_bounds.get(product, (None, None))[1],
        )
        _append_status(
            matrix,
            gaps,
            product=product,
            metadata_type="continuous_contract_map",
            applicable=product in continuous_products,
            status="passed" if product in continuous_bounds else "gap",
            reason="continuous_mapping_present" if product in continuous_bounds else "missing_continuous_mapping",
            gap_category="continuous_contract_map_gap",
            start=continuous_bounds.get(product, (None, None))[0],
            end=continuous_bounds.get(product, (None, None))[1],
        )
        _append_status(
            matrix,
            gaps,
            product=product,
            metadata_type="trading_parameter",
            applicable=actual,
            status="passed" if product in parameter_bounds else "gap",
            reason="trading_parameters_present" if product in parameter_bounds else "missing_trading_parameters",
            gap_category="trading_parameter_gap",
            start=parameter_bounds.get(product, (None, None))[0],
            end=parameter_bounds.get(product, (None, None))[1],
        )

        exchange = exchange_by_product.get(product, "")
        days = trading_days_by_exchange.get(exchange, ())
        calendar_complete = bool(listing and days and days[0] <= listing and days[-1] >= config.audit_end)
        _append_status(
            matrix,
            gaps,
            product=product,
            metadata_type="trading_calendar",
            applicable=bool(exchange),
            status="passed" if calendar_complete else "gap",
            reason="calendar_covers_listing_through_audit_end" if calendar_complete else "calendar_boundary_incomplete",
            gap_category="trading_calendar_gap",
            start=days[0] if days else None,
            end=days[-1] if days else None,
        )
        if not calendar_complete:
            for row in matrix:
                if (
                    row["product"] == product
                    and row["metadata_type"] in {"main_contract_map", "contract_universe", "trading_parameter"}
                    and row["status"] == "passed"
                ):
                    row["status"] = "unverified"
                    row["reason"] = "blocked_by_trading_calendar"

        _append_status(
            matrix,
            gaps,
            product=product,
            metadata_type="trading_session",
            applicable=False,
            status="not_applicable",
            reason="static_session_not_historical_reference_requirement",
            gap_category="trading_session_gap",
            start=None,
            end=None,
            not_applicable_reason="static_session_not_historical_reference_requirement",
        )

    trading_days_by_product = {
        product: trading_days_by_exchange.get(exchange_by_product.get(product, ""), ()) for product in products
    }
    return ReferenceMetadataResult(
        matrix=sorted(matrix, key=lambda row: (row["product"], row["metadata_type"])),
        gaps=sorted(gaps, key=lambda row: (row["product"], row["gap_category"])),
        rank1_ranges=_rank1_ranges(rank_by_product, trading_days_by_product),
        listing_dates=listing_dates,
        exchange_by_product=exchange_by_product,
        trading_days_by_product=trading_days_by_product,
    )


def _bounds_by_product(
    session: Session,
    model: type[Any],
    products: tuple[str, ...],
    audit_end: date,
) -> dict[str, tuple[date, date]]:
    symbol = model.instrument_symbol
    rows = session.execute(
        select(func.lower(symbol), func.min(model.trade_date), func.max(model.trade_date))
        .where(func.lower(symbol).in_(products), model.trade_date <= audit_end)
        .group_by(func.lower(symbol))
    )
    return {product: (minimum, maximum) for product, minimum, maximum in rows if minimum and maximum}


def _tuple_bounds(items: list[tuple[date, str]]) -> tuple[date, date] | None:
    if not items:
        return None
    return items[0][0], items[-1][0]


def _rank1_ranges(
    rows: dict[str, list[tuple[date, str]]],
    trading_days_by_product: dict[str, tuple[date, ...]],
) -> tuple[ActualRank1Range, ...]:
    result: list[ActualRank1Range] = []
    for product in sorted(rows):
        current_contract = ""
        start: date | None = None
        end: date | None = None
        calendar = trading_days_by_product.get(product, ())
        calendar_positions = {day: index for index, day in enumerate(calendar)}
        previous_date: date | None = None
        for trade_date, contract in rows[product]:
            nonconsecutive = bool(
                previous_date
                and calendar_positions
                and (
                    previous_date not in calendar_positions
                    or trade_date not in calendar_positions
                    or calendar_positions[trade_date] != calendar_positions[previous_date] + 1
                )
            )
            if current_contract and (contract != current_contract or nonconsecutive):
                result.append(ActualRank1Range(product, current_contract, start or trade_date, end))
                start = trade_date
            elif not current_contract:
                start = trade_date
            current_contract = contract
            end = trade_date
            previous_date = trade_date
        if current_contract and start and end:
            result.append(ActualRank1Range(product, current_contract, start, end))
    return tuple(result)


def _append_status(
    matrix: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    *,
    product: str,
    metadata_type: str,
    applicable: bool,
    status: str,
    reason: str,
    gap_category: str,
    start: date | None,
    end: date | None,
    not_applicable_reason: str = "profile_scope_not_applicable",
) -> None:
    if not applicable:
        status = "not_applicable"
        reason = not_applicable_reason
    row = {
        "product": product,
        "metadata_type": metadata_type,
        "applicability": "applicable" if applicable else "not_applicable",
        "status": status,
        "reason": reason,
        "evidence_start": start.isoformat() if start else "",
        "evidence_end": end.isoformat() if end else "",
    }
    matrix.append(row)
    if applicable and status in {"gap", "unverified"}:
        gaps.append(
            {
                "product": product,
                "gap_category": gap_category,
                "status": status,
                "reason": reason,
                "start": row["evidence_start"],
                "end": row["evidence_end"],
            }
        )


__all__ = [
    "GAP_CATEGORIES",
    "ReferenceMetadataConfig",
    "ReferenceMetadataResult",
    "collect_reference_metadata",
]
