from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_core.aggregation import AggregationSession
from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    BarsResult,
    DataCoreError,
    DatasetKey,
    DatasetKind,
)
from app.data_core.historical_reader import CanonicalHistoricalReader
from app.data_core.historical_sessions import product_sessions
from app.models.data_center import Instrument
from app.schemas.market import (
    CanonicalBarsRequest,
    CanonicalBarsResponse,
    CanonicalDataIdentity,
    MarketBarsCoverage,
    MarketBarsQuality,
    MarketCoverageContract,
    MarketCoverageInstrument,
    MarketCoverageItem,
    MarketCoveragePeriod,
    MarketReadLineage,
    MarketWorkbenchCoverage,
    MarketWorkbenchSelection,
)
from app.services.market_data_service import MarketDataService


class CanonicalReader(Protocol):
    def get_bars(self, query: BarQuery) -> BarsResult: ...


class CanonicalMarketDataService:
    def __init__(self, session: Session, *, reader: CanonicalReader) -> None:
        self._market_data = MarketDataService(
            session,
            canonical_reader=reader,
        )

    def get_bars(self, query: BarQuery) -> CanonicalBarsResponse:
        result = self._market_data.get_bars(query)
        return _response(query, result)


def build_canonical_reader(session: Session) -> CanonicalHistoricalReader:
    root_value = os.getenv("GUIYI_CANONICAL_DATA_ROOT", "").strip()
    if not root_value:
        raise DataCoreError(facts={"reason": "canonical_data_root_not_configured"})
    canonical_root = Path(root_value)
    if not canonical_root.is_absolute():
        raise DataCoreError(facts={"reason": "canonical_data_root_not_absolute"})
    return CanonicalHistoricalReader(
        catalog=HistoricalCatalog(session),
        canonical_root=canonical_root,
        session_provider=lambda symbol, start, end: product_sessions(
            session,
            symbol=symbol,
            start=start,
            end=end,
        ),
    )


def get_canonical_coverage(
    session: Session,
    *,
    symbol: str,
) -> MarketWorkbenchCoverage:
    normalized_symbol = symbol.strip().lower()
    exchanges = tuple(
        sorted(
            {
                str(value).strip().upper()
                for value in session.scalars(
                    select(Instrument.exchange_code).where(
                        func.lower(Instrument.symbol) == normalized_symbol
                    )
                )
                if str(value or "").strip()
            }
        )
    )
    if len(exchanges) != 1:
        raise DataCoreError(facts={"reason": "instrument_exchange_missing_or_ambiguous"})
    exchange = exchanges[0]
    catalog = HistoricalCatalog(session)
    items: list[MarketCoverageItem] = []
    for row in catalog.list_datasets(symbol=normalized_symbol):
        dataset = DatasetKey(
            provider=row.provider,
            dataset_kind=DatasetKind(row.dataset_kind),
            symbol=row.symbol,
            contract_or_series=row.contract_or_series,
            frequency=BarFrequency(row.frequency),
            adjustment=row.adjustment,
            schema_version=row.schema_version,
        )
        partitions = tuple(catalog.list_partitions(dataset))
        if not partitions:
            continue
        has_gap = bool(catalog.list_gaps(dataset))
        items.append(
            _coverage_item(
                dataset,
                period=dataset.frequency.value,
                start=min(item.coverage_start for item in partitions),
                end=max(item.coverage_end for item in partitions),
                row_count=sum(item.row_count for item in partitions),
                exchange=exchange,
                quality_status=(
                    "gap" if has_gap else "catalog_only_unverified"
                ),
            )
        )
        if dataset.frequency is BarFrequency.M1:
            for period in ("5m", "15m", "30m", "60m"):
                items.append(
                    _coverage_item(
                        dataset,
                        period=period,
                        start=min(item.coverage_start for item in partitions),
                        end=max(item.coverage_end for item in partitions),
                        row_count=0,
                        exchange=exchange,
                        quality_status=(
                            "gap" if has_gap else "catalog_only_unverified"
                        ),
                    )
                )
    ordered = sorted(
        items,
        key=lambda item: (item.contract, _period_order(item.period)),
    )
    contracts: list[MarketCoverageContract] = []
    for contract in sorted({item.contract for item in ordered}):
        contract_items = [item for item in ordered if item.contract == contract]
        first = contract_items[0]
        contracts.append(
            MarketCoverageContract(
                contract=contract,
                provider="rqdata",
                view_role=first.view_role,
                continuous_contract=first.continuous_contract,
                actual_contract=first.actual_contract,
                periods=[
                    MarketCoveragePeriod(**item.model_dump())
                    for item in contract_items
                ],
            )
        )
    preferred = next(
        (
            item
            for item in ordered
            if item.contract == f"{normalized_symbol.upper()}.MAIN" and item.period == "15m"
        ),
        ordered[0] if ordered else None,
    )
    return MarketWorkbenchCoverage(
        instruments=(
            [
                MarketCoverageInstrument(
                    symbol=normalized_symbol,
                    exchange=exchange,
                    contracts=contracts,
                )
            ]
            if contracts
            else []
        ),
        items=ordered,
        default_selection=(
            MarketWorkbenchSelection(
                symbol=preferred.symbol,
                contract=preferred.contract,
                period=preferred.period,
                provider="rqdata",
                profile_id=None,
                start=preferred.start_time,
                end=preferred.end_time,
            )
            if preferred is not None
            else None
        ),
    )


def _coverage_item(
    dataset: DatasetKey,
    *,
    period: str,
    start: datetime,
    end: datetime,
    row_count: int,
    exchange: str,
    quality_status: str,
) -> MarketCoverageItem:
    continuous = dataset.dataset_kind is DatasetKind.CONTINUOUS
    return MarketCoverageItem(
        symbol=dataset.symbol,
        contract=dataset.contract_or_series,
        period=period,
        provider="rqdata",
        data_type=dataset.dataset_kind.value,
        source_mode="historical",
        view_role=dataset.dataset_kind.value,
        continuous_contract=(dataset.contract_or_series if continuous else f"{dataset.symbol.upper()}.MAIN"),
        actual_contract=(None if continuous else dataset.contract_or_series),
        exchange=exchange,
        start_time=start,
        end_time=end,
        latest_bar_time=end,
        row_count=row_count,
        quality_status=quality_status,
        data_role="primary",
        profile_id=None,
        quality_policy="canonical_manifest_verification_required_on_read",
    )


def _period_order(period: str) -> int:
    return ("1m", "5m", "15m", "30m", "60m", "1d", "1w").index(period)


def jm_sessions(
    session: Session,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
) -> tuple[AggregationSession, ...]:
    """Compatibility name; canonical session resolution is product-generic."""

    return product_sessions(session, symbol=symbol, start=start, end=end)


def _response(query: BarQuery, result: BarsResult) -> CanonicalBarsResponse:
    identity_payload = {
        "dataset_kind": result.data_type.value,
        "frequency": query.frequency.value,
        "source_datasets": [
            {
                "provider": item.provider,
                "dataset_kind": item.dataset_kind.value,
                "symbol": item.symbol,
                "contract_or_series": item.contract_or_series,
                "frequency": item.frequency.value,
                "adjustment": item.adjustment,
                "schema_version": item.schema_version,
            }
            for item in result.source_datasets
        ],
        "manifest_digests": list(result.manifest_digests),
        "source_data_versions": list(result.source_data_versions),
        "requested_window": result.requested_window,
        "derived_frequency": (
            result.derived_frequency.value
            if result.derived_frequency is not None
            else None
        ),
    }
    data_identity = CanonicalDataIdentity(
        **identity_payload,
        request_identity_token=_identity_digest(identity_payload),
    )
    lineage_token = _identity_digest(
        {
            "provider": "rqdata",
            "dataset_kind": query.dataset_kind.value,
            "symbol": query.symbol,
            "contract_or_series": (
                query.contract_or_series
                or f"{query.symbol.upper()}.ACTUAL_DOMINANT"
            ),
            "frequency": query.frequency.value,
            "source_frequency": (
                "1m" if result.derived_frequency is not None else query.frequency.value
            ),
            "adjustment": "none",
            "schema_version": "canonical-bar-v1",
        }
    )
    bar_contracts = sorted({bar.contract_or_series for bar in result.bars})
    if query.dataset_kind.value == "continuous":
        resolved_contract = query.contract_or_series or f"{query.symbol}.MAIN"
        actual_contract = None
    else:
        actual_contract = bar_contracts[0] if len(bar_contracts) == 1 else None
        resolved_contract = (
            query.contract_or_series
            or actual_contract
            or f"{query.symbol}.ACTUAL_DOMINANT"
        )
    bars = [_bar_payload(bar) for bar in result.bars]
    return CanonicalBarsResponse(
        bars=bars,
        quality=MarketBarsQuality(status="passed"),
        coverage=MarketBarsCoverage(
            symbol=query.symbol,
            contract=resolved_contract,
            period=query.frequency.value,
            provider="rqdata",
            data_type=query.dataset_kind.value,
            source_mode="historical",
            view_role=query.dataset_kind.value,
            continuous_contract=(
                resolved_contract
                if query.dataset_kind.value == "continuous"
                else f"{query.symbol}.MAIN"
            ),
            actual_contract=(
                actual_contract
                if query.dataset_kind.value == "actual_dominant"
                else None
            ),
            start_time=query.start,
            end_time=query.end,
            latest_bar_time=(result.bars[-1].bar_end if result.bars else None),
            row_count=len(result.bars),
            quality_status="passed",
            data_role="primary",
        ),
        request=CanonicalBarsRequest(
            dataset_kind=query.dataset_kind.value,
            symbol=query.symbol,
            contract_or_series=query.contract_or_series,
            frequency=query.frequency.value,
            start=query.start,
            end=query.end,
        ),
        lineage=MarketReadLineage(
            access_mode="research",
            strict_research_ready=True,
            profile_id=None,
            quality_policy="canonical_manifest_verified",
            market_data_file_id=None,
            market_data_file_ids=[],
            data_version=(
                result.source_data_versions[0]
                if len(result.source_data_versions) == 1
                else None
            ),
            data_versions=list(result.source_data_versions),
            provider="rqdata",
            data_role="primary",
            quality_status="passed",
            source_interval=(
                "1m" if result.derived_frequency is not None else query.frequency.value
            ),
            source_intervals=[
                "1m" if result.derived_frequency is not None else query.frequency.value
            ],
            source_interval_basis="canonical_dataset_key",
            binding_snapshot=None,
            lineage_token=lineage_token,
            source_mode="historical",
            view_role=query.dataset_kind.value,
            continuous_contract=(
                resolved_contract
                if query.dataset_kind.value == "continuous"
                else f"{query.symbol}.MAIN"
            ),
            actual_contract=(
                actual_contract
                if query.dataset_kind.value == "actual_dominant"
                else None
            ),
            asset_evidence=[],
        ),
        strict_research_ready=True,
        message=None,
        data_identity=data_identity,
    )


def _bar_payload(bar: object) -> dict[str, object]:
    return {
        "time": bar.bar_end,
        "datetime": bar.bar_end,
        "bar_end": bar.bar_end,
        "trading_day": bar.trading_day,
        "symbol": bar.symbol,
        "contract": bar.contract_or_series,
        "contract_or_series": bar.contract_or_series,
        "frequency": bar.frequency.value,
        "period": bar.frequency.value,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": float(bar.volume),
        "turnover": float(bar.turnover) if bar.turnover is not None else None,
        "openInterest": (
            float(bar.open_interest) if bar.open_interest is not None else None
        ),
        "open_interest": (
            float(bar.open_interest) if bar.open_interest is not None else None
        ),
        "provider": bar.provider,
    }


def _identity_digest(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
