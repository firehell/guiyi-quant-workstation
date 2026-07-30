from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from app.schemas.market import (
    MarketBarsCoverage,
    MarketBarsQuality,
    MarketBarsRequest,
    MarketBarsResponse,
    MarketReadLineage,
    LiveMarketBarsResponse,
)
from app.services.active_dataset import (
    ActiveDatasetDomainError,
    BarsResult,
    DatasetAsset,
    DatasetDescriptor,
    DatasetRequest,
)
from app.services.active_dataset_resolver import (
    ActiveDatasetResolver,
    HistoricalDatasetResolution,
)
from app.services.market_workbench import (
    MarketAccessError,
    _lineage_changed,
    get_market_bars,
)
from app.services.live_market_reader import LiveMarketReader


LIVE_RESPONSE_REVISION_VERSION = "live-response-revision-v1"
LIVE_RESPONSE_SNAPSHOT_VERSION = "live-response-snapshot-v1"
LIVE_RESPONSE_BAR_FIELDS = (
    "live_bar_id",
    "time",
    "datetime",
    "trading_day",
    "symbol",
    "contract",
    "exchange",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "openInterest",
    "turnover",
    "period",
    "provider",
    "data_version",
    "bar_status",
    "quality_status",
    "source_mode",
    "revision",
    "confirmed_at",
    "quality_reasons",
    "source_bar_count",
    "expected_bar_count",
    "source_start_datetime",
    "source_end_datetime",
)


class HistoricalResolver(Protocol):
    def resolve_historical(
        self,
        request: DatasetRequest,
    ) -> HistoricalDatasetResolution: ...

    def resolve_live(self, request: DatasetRequest) -> DatasetDescriptor: ...


class LiveReader(Protocol):
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
    ) -> LiveMarketBarsResponse: ...


HistoricalBarsLoader = Callable[..., MarketBarsResponse]


class MarketDataService:
    """Compatibility Facade over the existing resolver/workbench/readers."""

    def __init__(
        self,
        session: Session,
        *,
        resolver: HistoricalResolver | None = None,
        historical_bars_loader: HistoricalBarsLoader = get_market_bars,
        live_reader: LiveReader | None = None,
    ) -> None:
        self._session = session
        self._resolver = resolver or ActiveDatasetResolver(session)
        self._historical_bars_loader = historical_bars_loader
        self._live_reader = live_reader or LiveMarketReader(session)

    def get_bars(
        self,
        request: DatasetRequest,
        *,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        tail: bool,
    ) -> BarsResult:
        if request.data_context == "historical":
            return self._get_historical_bars(
                request,
                start=start,
                end=end,
                limit=limit,
                tail=tail,
            )
        return self._get_live_bars(
            request,
            start=start,
            end=end,
            limit=limit,
            tail=tail,
        )

    def to_market_bars_response(self, result: BarsResult) -> MarketBarsResponse:
        if result.descriptor.data_context != "historical":
            raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
        return MarketBarsResponse(
            bars=list(result.bars),
            quality=MarketBarsQuality(**result.quality),
            coverage=(
                MarketBarsCoverage(**result.coverage)
                if result.coverage is not None
                else None
            ),
            request=MarketBarsRequest(**result.response_request),
            lineage=_market_read_lineage_from_descriptor(result.descriptor),
            strict_research_ready=result.descriptor.strict_research_ready,
            message=result.message,
        )

    def _get_historical_bars(
        self,
        request: DatasetRequest,
        *,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        tail: bool,
    ) -> BarsResult:
        resolution = self._resolver.resolve_historical(request)
        descriptor = resolution.descriptor
        context = resolution.context
        response = self._historical_bars_loader(
            self._session,
            symbol=descriptor.symbol,
            contract=descriptor.resolved_contract,
            period=descriptor.period,
            start=start,
            end=end,
            provider=request.provider,
            data_role=request.data_role,
            limit=limit,
            quote_mode=request.quote_mode,
            allow_continuous=request.allow_continuous,
            tail=tail,
            profile_id=request.profile_id,
            access_mode=request.access_mode,
            expected_market_data_file_id=request.expected_market_data_file_id,
            expected_lineage_token=request.expected_lineage_token,
            resolved_context=context,
            frozen_market_data_file_ids=context.lineage.market_data_file_ids,
            frozen_asset_evidence=context.lineage.asset_evidence,
        )
        expected_lineage = _market_read_lineage_from_descriptor(descriptor)
        if (
            response.lineage.model_dump(mode="json")
            != expected_lineage.model_dump(mode="json")
        ):
            raise _lineage_changed(
                descriptor.symbol,
                descriptor.resolved_contract,
                descriptor.period,
                descriptor.profile_id,
            )

        descriptor = replace(
            descriptor,
            source_max_bar=_maximum_bar_datetime(response.bars),
            source_revision_hash=descriptor.source_revision_hash,
        )
        return BarsResult(
            descriptor=descriptor,
            bars=tuple(response.bars),
            response_bar_count=len(response.bars),
            quality=response.quality.model_dump(mode="python"),
            coverage=(
                response.coverage.model_dump(mode="python")
                if response.coverage is not None
                else None
            ),
            response_request=response.request.model_dump(mode="python"),
            message=response.message,
        )

    def _get_live_bars(
        self,
        request: DatasetRequest,
        *,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        tail: bool,
    ) -> BarsResult:
        descriptor = self._resolver.resolve_live(request)
        if tail:
            raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
        response = self._live_reader.get_bars(
            symbol=descriptor.symbol,
            contract=descriptor.resolved_contract,
            period=descriptor.period,
            start=start,
            end=end,
            provider=descriptor.provider,
            source_mode=descriptor.live_source_mode,
            limit=limit,
        )
        _validate_live_response(
            response,
            descriptor=descriptor,
            start=start,
            end=end,
            limit=limit,
        )
        source_revision_hash = _live_response_revision_hash(response)
        lineage_token = _live_response_snapshot_token(
            descriptor=descriptor,
            start=start,
            end=end,
            limit=limit,
            tail=tail,
            source_revision_hash=source_revision_hash,
        )
        coverage = response.coverage
        descriptor = replace(
            descriptor,
            quality_status=response.quality.status,
            coverage_start=coverage.start_time if coverage is not None else None,
            coverage_end=coverage.end_time if coverage is not None else None,
            source_coverage_row_count=(
                coverage.row_count
                if coverage is not None
                else response.quality.row_count
            ),
            source_max_bar=_maximum_bar_datetime(response.bars),
            source_revision_hash=source_revision_hash,
            lineage_kind="live_response_snapshot",
            lineage_token=lineage_token,
        )
        return BarsResult(
            descriptor=descriptor,
            bars=tuple(response.bars),
            response_bar_count=len(response.bars),
            quality=response.quality.model_dump(mode="python"),
            coverage=(
                response.coverage.model_dump(mode="python")
                if response.coverage is not None
                else None
            ),
            response_request=response.request.model_dump(mode="python"),
            message=response.message,
        )


def _market_read_lineage_from_descriptor(
    descriptor: DatasetDescriptor,
) -> MarketReadLineage:
    if descriptor.data_context != "historical" or descriptor.lineage_token is None:
        raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")

    evidence = [_asset_evidence(asset) for asset in descriptor.assets]
    file_ids = [
        asset.market_data_file_id
        for asset in descriptor.assets
        if asset.market_data_file_id is not None
    ]
    versions = sorted(
        {
            asset.data_version
            for asset in descriptor.assets
            if asset.data_version is not None
        }
    )
    source_intervals = sorted(
        {
            asset.source_interval
            for asset in descriptor.assets
            if asset.source_interval is not None
        }
    )
    source_interval_bases = sorted(
        {
            asset.source_interval_basis
            for asset in descriptor.assets
            if asset.source_interval_basis is not None
        }
    )
    return MarketReadLineage(
        access_mode=descriptor.access_mode,
        strict_research_ready=descriptor.strict_research_ready,
        profile_id=descriptor.profile_id,
        quality_policy=descriptor.quality_policy,
        market_data_file_id=file_ids[0] if len(file_ids) == 1 else None,
        market_data_file_ids=file_ids,
        data_version=(
            descriptor.assets[0].data_version
            if len(descriptor.assets) == 1
            else _join_distinct(versions)
        ),
        data_versions=versions,
        provider=descriptor.provider,
        data_role=descriptor.data_role,
        quality_status=descriptor.quality_status,
        source_interval=(
            source_intervals[0]
            if len(source_intervals) == 1
            else _join_distinct(source_intervals)
        ),
        source_intervals=source_intervals,
        source_interval_basis=(
            source_interval_bases[0]
            if len(source_interval_bases) == 1
            else _join_distinct(source_interval_bases)
        ),
        binding_snapshot=descriptor.binding_snapshot,
        lineage_token=descriptor.lineage_token,
        source_mode="historical",
        view_role=descriptor.contract_role,
        continuous_contract=descriptor.continuous_contract,
        actual_contract=descriptor.actual_contract,
        asset_evidence=evidence,
    )


def _asset_evidence(asset: DatasetAsset) -> dict[str, Any]:
    return {
        "market_data_file_id": asset.market_data_file_id,
        "data_version": asset.data_version,
        "provider": asset.provider,
        "data_role": asset.data_role,
        "quality_status": asset.quality_status,
        "checksum": asset.checksum,
        "start_time": (
            asset.coverage_start.isoformat()
            if asset.coverage_start is not None
            else None
        ),
        "end_time": (
            asset.coverage_end.isoformat()
            if asset.coverage_end is not None
            else None
        ),
        "source_interval": asset.source_interval,
        "source_interval_basis": asset.source_interval_basis,
    }


def _validate_live_response(
    response: LiveMarketBarsResponse,
    *,
    descriptor: DatasetDescriptor,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> None:
    expected_mode = descriptor.live_source_mode
    expected_provider = descriptor.provider
    if (
        response.request.provider != expected_provider
        or response.request.source_mode != expected_mode
    ):
        raise ActiveDatasetDomainError("LIVE_SOURCE_MODE_MISMATCH")
    if response.coverage is not None and (
        response.coverage.provider != expected_provider
        or response.coverage.source_mode != expected_mode
    ):
        raise ActiveDatasetDomainError("LIVE_SOURCE_MODE_MISMATCH")
    for bar in response.bars:
        if (
            bar.get("provider") != expected_provider
            or bar.get("source_mode") != expected_mode
        ):
            raise ActiveDatasetDomainError("LIVE_SOURCE_MODE_MISMATCH")

    if (
        response.request.symbol != descriptor.symbol
        or response.request.contract != descriptor.resolved_contract
        or response.request.period != descriptor.period
        or response.request.start != start
        or response.request.end != end
        or response.request.limit != limit
    ):
        raise ActiveDatasetDomainError("DATASET_LINEAGE_CHANGED")
    if response.coverage is not None and (
        response.coverage.symbol != descriptor.symbol
        or response.coverage.contract != descriptor.resolved_contract
        or response.coverage.period != descriptor.period
    ):
        raise ActiveDatasetDomainError("DATASET_LINEAGE_CHANGED")
    for bar in response.bars:
        if (
            bar.get("symbol") != descriptor.symbol
            or bar.get("contract") != descriptor.resolved_contract
            or bar.get("period") != descriptor.period
        ):
            raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")


def _live_response_revision_hash(response: LiveMarketBarsResponse) -> str:
    response_json = response.model_dump(mode="json")
    normalized_bars: list[dict[str, Any]] = []
    for raw_bar in response_json["bars"]:
        normalized = dict(raw_bar)
        for field in LIVE_RESPONSE_BAR_FIELDS:
            normalized.setdefault(field, None)
        normalized_bars.append(normalized)
    normalized_bars.sort(key=_live_bar_sort_key)
    return _versioned_hash(
        LIVE_RESPONSE_REVISION_VERSION,
        {
            "version": LIVE_RESPONSE_REVISION_VERSION,
            "bars": normalized_bars,
        },
    )


def _live_response_snapshot_token(
    *,
    descriptor: DatasetDescriptor,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    tail: bool,
    source_revision_hash: str,
) -> str:
    return _versioned_hash(
        LIVE_RESPONSE_SNAPSHOT_VERSION,
        {
            "version": LIVE_RESPONSE_SNAPSHOT_VERSION,
            "snapshot": {
                "symbol": descriptor.symbol,
                "contract": descriptor.resolved_contract,
                "period": descriptor.period,
                "provider": descriptor.provider,
                "source_mode": descriptor.live_source_mode,
                "start": start.isoformat() if start is not None else None,
                "end": end.isoformat() if end is not None else None,
                "limit": limit,
                "tail": tail,
                "source_revision_hash": source_revision_hash,
            },
        },
    )


def _versioned_hash(version: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return f"{version}:{hashlib.sha256(encoded).hexdigest()}"


def _live_bar_sort_key(bar: dict[str, Any]) -> tuple[str, tuple[int, int | str]]:
    live_bar_id = bar.get("live_bar_id")
    id_key: tuple[int, int | str]
    if isinstance(live_bar_id, int) and not isinstance(live_bar_id, bool):
        id_key = (0, live_bar_id)
    else:
        id_key = (1, "" if live_bar_id is None else str(live_bar_id))
    return ("" if bar.get("time") is None else str(bar["time"]), id_key)


def _maximum_bar_datetime(bars: list[dict[str, Any]]) -> datetime | None:
    values = [
        value
        for bar in bars
        if (value := _bar_datetime(bar)) is not None
    ]
    return max(values, key=_datetime_sort_key) if values else None


def _bar_datetime(bar: dict[str, Any]) -> datetime | None:
    value = bar.get("datetime")
    if isinstance(value, datetime):
        return value
    if value is None:
        value = bar.get("time")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _datetime_sort_key(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _join_distinct(values: list[str]) -> str | None:
    return ", ".join(values) if values else None


__all__ = ["MarketDataService", "MarketAccessError"]
