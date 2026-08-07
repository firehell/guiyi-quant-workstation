from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import MainContractMap, MarketDataFile
from app.services.active_dataset import (
    ActiveDatasetDomainError,
    DatasetAsset,
    DatasetDescriptor,
    DatasetRequest,
    validate_dataset_request,
)
from app.services.actual_contract_semantics import (
    load_effective_main_contract_mapping,
    load_strict_main_contract_mapping,
)
from app.services.market_workbench import MarketReadContext, resolve_market_read_context


ResolveContext = Callable[..., MarketReadContext]
FallbackCandidatesLoader = Callable[..., list[MarketDataFile]]
MappingLoader = Callable[..., MainContractMap | None]


@dataclass(frozen=True)
class HistoricalDatasetResolution:
    """Internal carrier that keeps the once-resolved legacy context in-process."""

    descriptor: DatasetDescriptor
    context: MarketReadContext


class ActiveDatasetResolver:
    """Adapt the existing historical selector without becoming a second selector."""

    def __init__(
        self,
        session: Session,
        *,
        resolve_context: ResolveContext = resolve_market_read_context,
        fallback_candidates_loader: FallbackCandidatesLoader | None = None,
        strict_mapping_loader: MappingLoader = load_strict_main_contract_mapping,
        effective_mapping_loader: MappingLoader = load_effective_main_contract_mapping,
    ) -> None:
        self._session = session
        self._resolve_context = resolve_context
        self._fallback_candidates_loader = (
            fallback_candidates_loader or _load_legacy_fallback_candidates
        )
        self._strict_mapping_loader = strict_mapping_loader
        self._effective_mapping_loader = effective_mapping_loader

    def resolve_historical(self, request: DatasetRequest) -> HistoricalDatasetResolution:
        normalized = validate_dataset_request(request)
        if normalized.data_context != "historical":
            raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
        resolved_contract, mapping_identity = self._resolve_contract(normalized)

        context = self._resolve_context(
            self._session,
            symbol=normalized.symbol,
            contract=resolved_contract,
            period=normalized.period,
            provider=normalized.provider,
            data_role=normalized.data_role,
            profile_id=normalized.profile_id,
            access_mode=normalized.access_mode,
            expected_market_data_file_id=normalized.expected_market_data_file_id,
            expected_lineage_token=normalized.expected_lineage_token,
        )
        self._validate_profile_binding(
            context,
            symbol=normalized.symbol,
            contract=resolved_contract,
            period=normalized.period,
        )
        if (
            normalized.contract_selector == "dominant_rank1"
            and context.lineage.actual_contract != resolved_contract
        ):
            raise ActiveDatasetDomainError("DATASET_ACTUAL_CONTRACT_MISMATCH")
        assets = tuple(_dataset_asset(item) for item in context.lineage.asset_evidence)
        descriptor = DatasetDescriptor(
            data_context="historical",
            access_mode=normalized.access_mode,
            symbol=normalized.symbol,
            contract_selector=normalized.contract_selector,
            requested_contract=normalized.contract,
            resolved_contract=resolved_contract,
            contract_role=context.lineage.view_role,
            continuous_contract=context.lineage.continuous_contract,
            actual_contract=context.lineage.actual_contract,
            period=normalized.period,
            provider=context.lineage.provider,
            data_role=context.lineage.data_role,
            live_source_mode=None,
            quality_status=context.lineage.quality_status or "unchecked",
            strict_research_ready=context.lineage.strict_research_ready,
            profile_id=context.lineage.profile_id,
            quality_policy=context.lineage.quality_policy,
            binding_snapshot=(
                dict(context.lineage.binding_snapshot)
                if context.lineage.binding_snapshot is not None
                else None
            ),
            assets=assets,
            mapping_identity=mapping_identity,
            coverage_start=_coverage_boundary(assets, "coverage_start", min),
            coverage_end=_coverage_boundary(assets, "coverage_end", max),
            source_coverage_row_count=sum(
                int(market_file.row_count or 0) for market_file in context.market_files
            ),
            source_max_bar=None,
            source_revision_hash=_historical_source_revision_hash(
                assets=assets,
                lineage_token=context.lineage.lineage_token,
            ),
            lineage_kind="historical_asset",
            lineage_token=context.lineage.lineage_token,
            warnings=(),
        )
        return HistoricalDatasetResolution(descriptor=descriptor, context=context)

    def resolve_live(self, request: DatasetRequest) -> DatasetDescriptor:
        """Poll live dataset context is retired; reject explicitly."""
        del request
        raise ActiveDatasetDomainError("LIVE_CONTEXT_RETIRED")

    def _resolve_contract(
        self,
        request: DatasetRequest,
    ) -> tuple[str, dict[str, Any] | None]:
        if request.contract_selector == "explicit":
            if request.contract is None:
                raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
            return request.contract, None

        mapping_date = request.mapping_date
        if mapping_date is None:
            raise ActiveDatasetDomainError("DATASET_REQUEST_UNSUPPORTED")
        strict = self._strict_mapping_loader(
            self._session,
            instrument_symbol=request.symbol,
            trade_date=mapping_date,
        )
        effective = self._effective_mapping_loader(
            self._session,
            instrument_symbol=request.symbol,
            trade_date=mapping_date,
        )
        if strict is None or effective is None:
            raise ActiveDatasetDomainError("DATASET_ACTUAL_CONTRACT_MISMATCH")
        if _mapping_comparison_identity(strict) != _mapping_comparison_identity(effective):
            raise ActiveDatasetDomainError("DATASET_ACTUAL_CONTRACT_MISMATCH")
        if request.contract is not None and request.contract != strict.contract_code:
            raise ActiveDatasetDomainError("DATASET_ACTUAL_CONTRACT_MISMATCH")
        return strict.contract_code, _mapping_identity(strict)

    def _validate_profile_binding(
        self,
        context: MarketReadContext,
        *,
        symbol: str,
        contract: str,
        period: str,
    ) -> None:
        if context.profile_lineage is None:
            return
        snapshot = context.profile_lineage.binding_snapshot
        if not isinstance(snapshot, dict):
            raise ActiveDatasetDomainError("DATASET_LINEAGE_CHANGED")
        selected_id = context.lineage.market_data_file_id
        pinned_id = snapshot.get("market_data_file_id")
        if pinned_id is not None:
            if selected_id != pinned_id:
                raise ActiveDatasetDomainError("DATASET_LINEAGE_CHANGED")
            return

        candidates = self._fallback_candidates_loader(
            self._session,
            symbol=symbol,
            contract=contract,
            period=period,
            data_version=snapshot.get("data_version"),
            data_role="primary",
        )
        if not candidates:
            raise ActiveDatasetDomainError("DATASET_ASSET_MISSING")
        if len(candidates) > 1:
            raise ActiveDatasetDomainError("DATASET_ASSET_AMBIGUOUS")
        if candidates[0].id != selected_id:
            raise ActiveDatasetDomainError("DATASET_LINEAGE_CHANGED")


def _load_legacy_fallback_candidates(
    session: Session,
    *,
    symbol: str,
    contract: str,
    period: str,
    data_version: str | None,
    data_role: str,
) -> list[MarketDataFile]:
    return list(
        session.scalars(
            select(MarketDataFile).where(
                MarketDataFile.instrument_symbol == symbol,
                MarketDataFile.contract_code == contract,
                MarketDataFile.period == period,
                MarketDataFile.data_version == data_version,
                MarketDataFile.data_role == data_role,
            )
        )
    )


def _mapping_comparison_identity(mapping: MainContractMap) -> tuple[Any, ...]:
    return (
        mapping.id,
        mapping.contract_code,
        mapping.trade_date,
        mapping.provider,
        mapping.rule,
        mapping.rank,
        mapping.data_version,
    )


def _mapping_identity(mapping: MainContractMap) -> dict[str, Any]:
    return {
        "id": mapping.id,
        "instrument_symbol": mapping.instrument_symbol,
        "contract_code": mapping.contract_code,
        "trade_date": mapping.trade_date.isoformat(),
        "provider": mapping.provider,
        "rule": mapping.rule,
        "rank": mapping.rank,
        "data_version": mapping.data_version,
    }


def _dataset_asset(evidence: dict[str, Any]) -> DatasetAsset:
    return DatasetAsset(
        market_data_file_id=evidence.get("market_data_file_id"),
        provider=str(evidence.get("provider") or ""),
        data_role=evidence.get("data_role"),
        quality_status=str(evidence.get("quality_status") or "unchecked"),
        data_version=evidence.get("data_version"),
        checksum=evidence.get("checksum"),
        coverage_start=_parse_datetime(evidence.get("start_time")),
        coverage_end=_parse_datetime(evidence.get("end_time")),
        source_interval=evidence.get("source_interval"),
        source_interval_basis=evidence.get("source_interval_basis"),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _coverage_boundary(
    assets: tuple[DatasetAsset, ...],
    field_name: str,
    chooser: Callable[[list[datetime]], datetime],
) -> datetime | None:
    values = [
        value
        for asset in assets
        if (value := getattr(asset, field_name)) is not None
    ]
    return chooser(values) if values else None


def _historical_source_revision_hash(
    *,
    assets: tuple[DatasetAsset, ...],
    lineage_token: str,
) -> str:
    payload = {
        "assets": [
            {
                "market_data_file_id": asset.market_data_file_id,
                "checksum": asset.checksum,
            }
            for asset in assets
        ],
        "lineage_token": lineage_token,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
