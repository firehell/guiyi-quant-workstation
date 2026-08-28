"""Metadata-only SuBing performance lineage and pure mutable-tail decisions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from typing import Literal, Protocol

from ..catalog import CatalogError, CatalogPartition, MarketCatalog
from ..domain import (
    BarFrequency,
    DatasetKey,
    DatasetKind,
    ResolvedContractSegment,
    RQDATA_INTRADAY_HISTORY_START,
)
from ..errors import InfrastructureError
from ..market_data_service import MarketDataError, MarketDataService


_SEGMENT_FREQUENCIES = (BarFrequency.M1, BarFrequency.M5, BarFrequency.M15)


class SubingStrategyPerformanceLineageError(RuntimeError):
    code = "SUBING_STRATEGY_PERFORMANCE_LINEAGE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceSourceSegment:
    contract: str
    effective_start: date
    effective_end: date
    source_identity: str

    def __post_init__(self) -> None:
        if (
            not self.contract
            or type(self.effective_start) is not date
            or type(self.effective_end) is not date
            or self.effective_start > self.effective_end
            or not _is_sha256(self.source_identity)
        ):
            raise SubingStrategyPerformanceLineageError()


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceLineage:
    symbol: str
    coverage_since: date
    coverage_through: date
    ordered_segments: tuple[SubingStrategyPerformanceSourceSegment, ...]
    source_manifest_sha256: str

    def __post_init__(self) -> None:
        if (
            not _is_valid_symbol(self.symbol)
            or type(self.coverage_since) is not date
            or type(self.coverage_through) is not date
            or self.coverage_since > self.coverage_through
            or not self.ordered_segments
            or not _is_sha256(self.source_manifest_sha256)
        ):
            raise SubingStrategyPerformanceLineageError()


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceSemanticIdentity:
    strategy_id: str
    formula_version: str
    engine_identity_sha256: str

    def __post_init__(self) -> None:
        if (
            not self.strategy_id
            or not self.formula_version
            or not _is_sha256(self.engine_identity_sha256)
        ):
            raise SubingStrategyPerformanceLineageError()


@dataclass(frozen=True, slots=True)
class SubingStrategyPerformanceTailDecision:
    kind: Literal["UNCHANGED", "REPLAY_FROM_SEGMENT", "FULL_REBUILD_REQUIRED"]
    index: int | None = None

    def __post_init__(self) -> None:
        if self.kind == "REPLAY_FROM_SEGMENT":
            if type(self.index) is not int or self.index < 0:
                raise SubingStrategyPerformanceLineageError()
        elif self.index is not None:
            raise SubingStrategyPerformanceLineageError()


UNCHANGED = SubingStrategyPerformanceTailDecision("UNCHANGED")
FULL_REBUILD_REQUIRED = SubingStrategyPerformanceTailDecision("FULL_REBUILD_REQUIRED")


def REPLAY_FROM_SEGMENT(index: int) -> SubingStrategyPerformanceTailDecision:
    return SubingStrategyPerformanceTailDecision("REPLAY_FROM_SEGMENT", index)


class _CoverageWindow(Protocol):
    def product_start(self, symbol: str) -> date: ...

    def latest_complete_day(self, products: tuple[str, ...]) -> date: ...


class SubingStrategyPerformanceLineageResolver(Protocol):
    def expected_complete_through(self, symbol: str) -> date: ...

    def resolve(
        self,
        symbol: str,
        *,
        through: date | None = None,
    ) -> SubingStrategyPerformanceLineage: ...


class CatalogSubingStrategyPerformanceLineageResolver:
    """Catalog/MainContractMap adapter that never reads Canonical bars."""

    def __init__(
        self,
        *,
        market_data: MarketDataService,
        coverage: _CoverageWindow,
    ) -> None:
        self._market_data = market_data
        self._coverage = coverage

    def expected_complete_through(self, symbol: str) -> date:
        try:
            _require_symbol(symbol)
            complete = self._coverage.latest_complete_day((symbol,))
            mappings = self._market_data.catalog.main_map_before(symbol, None)
            if not mappings:
                raise MarketDataError("DOMINANT_CONTEXT_MISSING")
            return min(complete, mappings[-1].trade_date)
        except _LINEAGE_FAILURES:
            raise SubingStrategyPerformanceLineageError() from None

    def resolve(
        self,
        symbol: str,
        *,
        through: date | None = None,
    ) -> SubingStrategyPerformanceLineage:
        try:
            _require_symbol(symbol)
            since = max(
                self._coverage.product_start(symbol),
                RQDATA_INTRADAY_HISTORY_START,
            )
            coverage_through = (
                through if through is not None else self.expected_complete_through(symbol)
            )
            if type(coverage_through) is not date or since > coverage_through:
                raise SubingStrategyPerformanceLineageError()
            resolved = self._market_data.actual_dominant_segments(
                symbol,
                since,
                coverage_through,
            )
            if not resolved:
                raise SubingStrategyPerformanceLineageError()
            ordered = tuple(
                self._source_segment(symbol, segment) for segment in resolved
            )
            return SubingStrategyPerformanceLineage(
                symbol=symbol,
                coverage_since=since,
                coverage_through=coverage_through,
                ordered_segments=ordered,
                source_manifest_sha256=_source_manifest_sha256(
                    symbol=symbol,
                    coverage_since=since,
                    coverage_through=coverage_through,
                    segments=ordered,
                ),
            )
        except SubingStrategyPerformanceLineageError:
            raise
        except _LINEAGE_FAILURES:
            raise SubingStrategyPerformanceLineageError() from None

    def _source_segment(
        self,
        symbol: str,
        segment: ResolvedContractSegment,
    ) -> SubingStrategyPerformanceSourceSegment:
        catalog = self._market_data.catalog
        partitions = _ordered_partition_facts(
            catalog,
            symbol=symbol,
            contract=segment.contract,
            start=segment.start_trading_day,
            end=segment.end_trading_day,
        )
        source_identity = sha256(
            _canonical_bytes(
                {
                    "contract": segment.contract,
                    "effective_start": segment.start_trading_day.isoformat(),
                    "effective_end": segment.end_trading_day.isoformat(),
                    "partitions": partitions,
                }
            )
        ).hexdigest()
        return SubingStrategyPerformanceSourceSegment(
            contract=segment.contract,
            effective_start=segment.start_trading_day,
            effective_end=segment.end_trading_day,
            source_identity=source_identity,
        )


def decide_subing_strategy_performance_tail(
    *,
    previous: SubingStrategyPerformanceLineage,
    current: SubingStrategyPerformanceLineage,
    previous_identity: SubingStrategyPerformanceSemanticIdentity,
    current_identity: SubingStrategyPerformanceSemanticIdentity,
) -> SubingStrategyPerformanceTailDecision:
    if previous_identity != current_identity or previous.symbol != current.symbol:
        return FULL_REBUILD_REQUIRED
    if current.coverage_through < previous.coverage_through:
        return FULL_REBUILD_REQUIRED
    if current.coverage_since != previous.coverage_since:
        return FULL_REBUILD_REQUIRED
    if not _segments_well_formed(previous.ordered_segments) or not _segments_well_formed(
        current.ordered_segments
    ):
        return FULL_REBUILD_REQUIRED

    previous_segments = previous.ordered_segments
    current_segments = current.ordered_segments
    if (
        previous.coverage_through == current.coverage_through
        and previous.source_manifest_sha256 == current.source_manifest_sha256
    ):
        if previous_segments != current_segments:
            return FULL_REBUILD_REQUIRED
        return UNCHANGED

    mutable_index = len(previous_segments) - 1
    if mutable_index < 0 or current_segments[:mutable_index] != previous_segments[:mutable_index]:
        return FULL_REBUILD_REQUIRED
    if len(current_segments) < len(previous_segments):
        return FULL_REBUILD_REQUIRED
    if len(current_segments) > len(previous_segments) + 1:
        return FULL_REBUILD_REQUIRED

    previous_tail = previous_segments[mutable_index]
    current_tail = current_segments[mutable_index]
    if (
        previous_tail.contract != current_tail.contract
        or previous_tail.effective_start != current_tail.effective_start
        or current_tail.effective_end < previous_tail.effective_end
    ):
        return FULL_REBUILD_REQUIRED
    return REPLAY_FROM_SEGMENT(mutable_index)


def _segments_well_formed(
    segments: Sequence[SubingStrategyPerformanceSourceSegment],
) -> bool:
    if not segments:
        return False
    previous: SubingStrategyPerformanceSourceSegment | None = None
    for segment in segments:
        if segment.effective_start > segment.effective_end:
            return False
        if previous is not None and segment.effective_start <= previous.effective_end:
            return False
        previous = segment
    return True


def _ordered_partition_facts(
    catalog: MarketCatalog,
    *,
    symbol: str,
    contract: str,
    start: date,
    end: date,
) -> list[dict[str, object]]:
    window_start = datetime(start.year, start.month, start.day, tzinfo=UTC)
    window_end = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    facts: list[dict[str, object]] = []
    for frequency in _SEGMENT_FREQUENCIES:
        key = DatasetKey(
            DatasetKind.CONTRACT,
            symbol,
            contract,
            frequency,
        )
        partitions = catalog.partitions(key, window_start, window_end)
        if not partitions:
            raise SubingStrategyPerformanceLineageError()
        facts.extend(_partition_payload(catalog, partition) for partition in partitions)
    return facts


def _partition_payload(
    catalog: MarketCatalog,
    partition: CatalogPartition,
) -> dict[str, object]:
    try:
        file_uri = partition.file_path.relative_to(catalog.canonical_root).as_posix()
    except ValueError:
        raise SubingStrategyPerformanceLineageError() from None
    return {
        "frequency": partition.dataset.frequency.value,
        "year": partition.year,
        "month": partition.month,
        "coverage_start": partition.coverage_start.astimezone(UTC).isoformat(),
        "coverage_end": partition.coverage_end.astimezone(UTC).isoformat(),
        "file_uri": file_uri,
        "row_count": partition.row_count,
    }


def _source_manifest_sha256(
    *,
    symbol: str,
    coverage_since: date,
    coverage_through: date,
    segments: Sequence[SubingStrategyPerformanceSourceSegment],
) -> str:
    return sha256(
        _canonical_bytes(
            {
                "symbol": symbol,
                "coverage_since": coverage_since.isoformat(),
                "coverage_through": coverage_through.isoformat(),
                "segments": [
                    {
                        "contract": segment.contract,
                        "effective_start": segment.effective_start.isoformat(),
                        "effective_end": segment.effective_end.isoformat(),
                        "source_identity": segment.source_identity,
                    }
                    for segment in segments
                ],
            }
        )
    ).hexdigest()


def _require_symbol(symbol: str) -> None:
    if not _is_valid_symbol(symbol):
        raise SubingStrategyPerformanceLineageError()


def _is_valid_symbol(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isalpha()
        and value == value.lower()
    )


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


_LINEAGE_FAILURES = (
    MarketDataError,
    CatalogError,
    InfrastructureError,
    SubingStrategyPerformanceLineageError,
)
