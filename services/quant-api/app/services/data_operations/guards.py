"""Shared fail-closed identity and DataGap guards for data operations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from app.data_core.contracts import (
    DataGapError,
    DatasetAmbiguousError,
    DatasetKey,
    DatasetKind,
)
from app.services.data_operations.contracts import DataOperationsError, DataTarget


class _GapLike(Protocol):
    gap_start: datetime
    gap_end: datetime


class _CatalogLike(Protocol):
    def list_gaps(self, key: DatasetKey) -> Sequence[_GapLike]: ...

    def get_main_contract_mapping(
        self,
        *,
        instrument_symbol: str,
        trade_date: object,
    ) -> object: ...


def to_dataset_key(target: DataTarget) -> DatasetKey:
    return DatasetKey(
        provider=target.provider,
        dataset_kind=target.dataset_kind,
        symbol=target.symbol,
        contract_or_series=target.contract_or_series,
        frequency=target.frequency,
        adjustment=target.adjustment,
        schema_version=target.schema_version,
    )


def assert_no_gap_intersection(
    catalog: _CatalogLike,
    *,
    dataset: DatasetKey,
    start: datetime,
    end: datetime,
) -> None:
    for gap in catalog.list_gaps(dataset):
        if _intersects(gap.gap_start, gap.gap_end, start, end):
            raise DataGapError(
                facts={
                    "reason": "request_intersects_data_gap",
                    "dataset_kind": dataset.dataset_kind.value,
                    "symbol": dataset.symbol,
                    "contract_or_series": dataset.contract_or_series,
                    "frequency": dataset.frequency.value,
                }
            )


def assert_actual_dominant_mapping(
    catalog: _CatalogLike,
    *,
    target: DataTarget,
    trading_days: Sequence[object],
) -> None:
    if target.dataset_kind is not DatasetKind.ACTUAL_DOMINANT:
        return
    seen: dict[object, str] = {}
    for trading_day in trading_days:
        try:
            mapping = catalog.get_main_contract_mapping(
                instrument_symbol=target.symbol,
                trade_date=trading_day,
            )
        except Exception as exc:  # noqa: BLE001 - map catalog misses to stable refusal
            raise DatasetAmbiguousError(
                facts={
                    "reason": "main_contract_map_missing",
                    "symbol": target.symbol,
                    "trading_day": str(trading_day),
                }
            ) from exc
        contract = str(getattr(mapping, "actual_contract", "") or "").strip().upper()
        if not contract:
            raise DatasetAmbiguousError(
                facts={
                    "reason": "main_contract_map_incomplete",
                    "symbol": target.symbol,
                    "trading_day": str(trading_day),
                }
            )
        previous = seen.get(trading_day)
        if previous is not None and previous != contract:
            raise DatasetAmbiguousError(
                facts={
                    "reason": "main_contract_map_ambiguous",
                    "symbol": target.symbol,
                    "trading_day": str(trading_day),
                }
            )
        seen[trading_day] = contract
        if contract != target.contract_or_series:
            raise DataOperationsError(
                code="DATASET_KIND_MISMATCH",
                facts={
                    "reason": "no_continuous_or_contract_fallback",
                    "expected": target.contract_or_series,
                    "mapped": contract,
                }
            )


def refuse_cross_kind_fallback(*, requested: DatasetKind, resolved: DatasetKind) -> None:
    if requested is not resolved:
        raise DataOperationsError(
            code="DATASET_KIND_MISMATCH",
            facts={
                "reason": "cross_kind_fallback_forbidden",
                "requested": requested.value,
                "resolved": resolved.value,
            },
        )


def _intersects(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> bool:
    return left_start < right_end and right_start < left_end
