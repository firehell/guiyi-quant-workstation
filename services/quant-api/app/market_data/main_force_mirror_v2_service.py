"""Historical-only Main Force Mirror V2 page orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol, TypedDict

from guiyi_quant.indicators.main_force_mirror_v2 import (
    MainForceMirrorV2Point,
    MemberRankDailyInput,
    MemberRankObservation,
    compute_main_force_mirror_v2,
    compute_member_rank_observation,
)

from app.market_data.actual_dominant_research import (
    ActualDominantResearchSeries,
    ActualDominantResearchSegmentIdentityError,
)
from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    ContractError,
    ContractTradingDayQuery,
    MarketSeriesPageResult,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
)
from app.market_data.errors import InfrastructureError
from app.market_data.market_data_service import MarketDataError
from app.market_data.member_rank_snapshot import (
    MemberRankDay,
    MemberRankSnapshotError,
    MemberRankSnapshotRepository,
)


class MainForceMirrorV2Error(RuntimeError):
    """Stable public V2 failure that never carries an internal cause."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MemberDatasetState:
    status: Literal["ready", "unavailable"]
    dataset_id: str | None
    schema_version: int | None
    admitted_product: bool
    coverage: tuple[date, date] | None


@dataclass(frozen=True, slots=True)
class MainForceMirrorV2PageResult:
    request_identity: Mapping[str, object]
    indicator_code: str
    indicator_version: str
    formal_policy_id: str
    parameters_hash: str
    points: tuple[MainForceMirrorV2Point, ...]
    member_dataset: MemberDatasetState
    has_more_before: bool
    next_before: datetime | None
    resolved_contract_segments: tuple[ResolvedContractSegment, ...]


class _MarketDataReader(Protocol):
    def query_page(self, request: SeriesPageQuery) -> MarketSeriesPageResult: ...

    def query_actual_dominant_trading_days(
        self, request: ActualDominantTradingDayQuery
    ) -> MarketSeriesResult: ...

    def query_contract_trading_days(
        self, request: ContractTradingDayQuery
    ) -> MarketSeriesResult: ...


class _SegmentLoader(Protocol):
    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries: ...


class _CoverageSource(Protocol):
    history_floor: date

    def previous_trading_day(self, symbol: str, trading_day: date) -> date: ...


class MainForceMirrorV2Service:
    """Compute one exact historical page from authoritative read boundaries."""

    def __init__(
        self,
        *,
        market_data: _MarketDataReader,
        segment_loader: _SegmentLoader,
        coverage: _CoverageSource,
        member_repository: MemberRankSnapshotRepository | None,
    ) -> None:
        self.market_data = market_data
        self.segment_loader = segment_loader
        self.coverage = coverage
        self.member_repository = member_repository

    def query_page(self, request: SeriesPageQuery) -> MainForceMirrorV2PageResult:
        self._validate_request(request)
        try:
            target = self.market_data.query_page(request)
            if not target.bars:
                raise MainForceMirrorV2Error("MFM_V2_MARKET_IDENTITY_CONFLICT")
            full, contracts = self._full_calculation_prefix(request, target)
            core = compute_main_force_mirror_v2(
                **_bar_inputs(full.bars, contracts),
            )
            member_inputs = self._member_inputs(
                request,
                full,
                contracts,
                core.points,
            )
            observation = compute_main_force_mirror_v2(
                **_bar_inputs(full.bars, contracts),
                member_inputs=member_inputs,
            )
        except MainForceMirrorV2Error:
            raise
        except ContractError:
            raise MainForceMirrorV2Error("MFM_V2_CONTRACT_INVALID") from None
        except MemberRankSnapshotError:
            raise MainForceMirrorV2Error("MFM_V2_MEMBER_DATASET_INVALID") from None
        except (MarketDataError, ActualDominantResearchSegmentIdentityError):
            raise MainForceMirrorV2Error("MFM_V2_MARKET_IDENTITY_CONFLICT") from None

        points_by_end = {point.bar_end: point for point in observation.points}
        if len(points_by_end) != len(observation.points):
            raise MainForceMirrorV2Error("MFM_V2_MARKET_IDENTITY_CONFLICT")
        try:
            points = tuple(points_by_end[bar.bar_end] for bar in target.bars)
        except KeyError:
            raise MainForceMirrorV2Error(
                "MFM_V2_MARKET_IDENTITY_CONFLICT"
            ) from None
        if tuple(point.bar_end for point in points) != tuple(
            bar.bar_end for bar in target.bars
        ):
            raise MainForceMirrorV2Error("MFM_V2_MARKET_IDENTITY_CONFLICT")

        return MainForceMirrorV2PageResult(
            request_identity=target.request_identity,
            indicator_code=observation.indicator_code,
            indicator_version=observation.indicator_version,
            formal_policy_id=observation.formal_policy_id,
            parameters_hash=observation.parameters_hash,
            points=points,
            member_dataset=self._member_dataset_state(request.symbol),
            has_more_before=target.has_more_before,
            next_before=target.next_before,
            resolved_contract_segments=target.resolved_contract_segments,
        )

    @staticmethod
    def _validate_request(request: SeriesPageQuery) -> None:
        if request.series_kind not in {
            SeriesKind.ACTUAL_DOMINANT,
            SeriesKind.CONTRACT,
        }:
            raise MainForceMirrorV2Error("MFM_V2_UNSUPPORTED_SERIES_KIND")
        if request.frequency is not BarFrequency.H1:
            raise MainForceMirrorV2Error("MFM_V2_UNSUPPORTED_FREQUENCY")

    def _full_calculation_prefix(
        self,
        request: SeriesPageQuery,
        target: MarketSeriesPageResult,
    ) -> tuple[MarketSeriesResult, tuple[str, ...]]:
        first_day = target.bars[0].trading_day
        last_day = target.bars[-1].trading_day
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            loaded = self.segment_loader.load(
                symbol=request.symbol,
                frequencies=(BarFrequency.H1,),
                since=first_day,
                through=last_day,
            )
            try:
                full = loaded.results[BarFrequency.H1]
            except KeyError:
                raise MainForceMirrorV2Error(
                    "MFM_V2_MARKET_IDENTITY_CONFLICT"
                ) from None
            segments = loaded.segments
            contracts = _contracts_for_bars(full.bars, segments)
            return full, contracts

        if request.contract is None:
            raise MainForceMirrorV2Error("MFM_V2_CONTRACT_INVALID")
        full = self.market_data.query_contract_trading_days(
            ContractTradingDayQuery(
                request.symbol,
                request.contract,
                BarFrequency.H1,
                self.coverage.history_floor,
                last_day,
            )
        )
        return full, (request.contract,) * len(full.bars)

    def _member_inputs(
        self,
        request: SeriesPageQuery,
        full: MarketSeriesResult,
        contracts: tuple[str, ...],
        core_points: tuple[MainForceMirrorV2Point, ...],
    ) -> tuple[MemberRankObservation | None, ...] | None:
        repository = self.member_repository
        if repository is None:
            return None
        if request.symbol not in repository.descriptor.admitted_products:
            return tuple(
                MemberRankObservation.unavailable(
                    "MFM_V2_MEMBER_PRODUCT_NOT_ADMITTED"
                )
                for _bar in full.bars
            )

        rank1_contract_by_day: Mapping[date, str] = {}
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            history = self.market_data.query_actual_dominant_trading_days(
                ActualDominantTradingDayQuery(
                    request.symbol,
                    BarFrequency.H1,
                    self.coverage.history_floor,
                    full.bars[-1].trading_day,
                )
            )
            rank1_contract_by_day = _contract_by_trading_day(
                history.bars,
                history.resolved_contract_segments,
            )

        observations: list[MemberRankObservation] = []
        previous_by_day: dict[date, date | None] = {}
        contexts: dict[
            tuple[str, date],
            tuple[MemberRankDailyInput, tuple[Decimal, ...]] | str,
        ] = {}
        for bar, contract, core_point in zip(
            full.bars, contracts, core_points, strict=True
        ):
            if bar.trading_day not in previous_by_day:
                previous_by_day[bar.trading_day] = self._previous_member_day(
                    request.symbol,
                    bar.trading_day,
                )
            member_trade_date = previous_by_day[bar.trading_day]
            if member_trade_date is None:
                observations.append(
                    MemberRankObservation.unavailable(
                        "MFM_V2_MEMBER_PREVIOUS_TRADING_DAY_MISSING"
                    )
                )
                continue

            context_key = (contract, member_trade_date)
            if context_key not in contexts:
                contexts[context_key] = self._member_context(
                    request,
                    contract,
                    member_trade_date,
                    rank1_contract_by_day,
                )
            context = contexts[context_key]
            if isinstance(context, str):
                observations.append(
                    MemberRankObservation.unavailable(
                        context,
                        member_trade_date=member_trade_date,
                    )
                )
                continue
            current, prior_biases = context
            observations.append(
                compute_member_rank_observation(
                    current,
                    prior_biases,
                    accumulated_pressure=core_point.accumulated_pressure,
                    caution=core_point.caution,
                )
            )
        return tuple(observations)

    def _previous_member_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> date | None:
        try:
            return self.coverage.previous_trading_day(symbol, trading_day)
        except InfrastructureError as exc:
            if exc.code != "COMPLETE_TRADING_DAY_MISSING":
                raise MainForceMirrorV2Error(
                    "MFM_V2_MARKET_IDENTITY_CONFLICT"
                ) from None
            return None

    def _member_context(
        self,
        request: SeriesPageQuery,
        contract: str,
        member_trade_date: date,
        rank1_contract_by_day: Mapping[date, str],
    ) -> tuple[MemberRankDailyInput, tuple[Decimal, ...]] | str:
        repository = self.member_repository
        if repository is None:
            raise MainForceMirrorV2Error("MFM_V2_MEMBER_DATASET_INVALID")
        try:
            current_day = repository.day(contract, member_trade_date)
        except MemberRankSnapshotError as exc:
            if exc.code.startswith("MEMBER_CONTRACT_DAY_"):
                return "MFM_V2_MEMBER_CONTRACT_DAY_INCOMPLETE"
            raise
        if current_day is None:
            return "MFM_V2_MEMBER_CONTRACT_DAY_INCOMPLETE"

        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            prior_days = repository.rank1_days_before(
                request.symbol,
                member_trade_date,
                limit=60,
                contract_by_day=rank1_contract_by_day,
            )
        else:
            prior_days = repository.contract_days_before(
                contract,
                member_trade_date,
                limit=60,
            )
        return (
            _daily_input(current_day),
            tuple(_daily_input(day).change_bias for day in prior_days),
        )

    def _member_dataset_state(self, symbol: str) -> MemberDatasetState:
        repository = self.member_repository
        if repository is None:
            return MemberDatasetState("unavailable", None, None, False, None)
        descriptor = repository.descriptor
        coverage = (
            (
                min(item.coverage_start for item in descriptor.partitions),
                max(item.coverage_end for item in descriptor.partitions),
            )
            if descriptor.partitions
            else None
        )
        return MemberDatasetState(
            "ready",
            descriptor.dataset_id,
            descriptor.schema_version,
            symbol in descriptor.admitted_products,
            coverage,
        )


class _BarInputs(TypedDict):
    bar_end: tuple[datetime, ...]
    trading_day: tuple[date, ...]
    physical_contract: tuple[str, ...]
    open_: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[float, ...]
    open_interest: tuple[float | None, ...]


def _bar_inputs(
    bars: tuple[CanonicalBar, ...],
    contracts: tuple[str, ...],
) -> _BarInputs:
    if len(bars) != len(contracts):
        raise MainForceMirrorV2Error("MFM_V2_MARKET_IDENTITY_CONFLICT")
    return {
        "bar_end": tuple(bar.bar_end for bar in bars),
        "trading_day": tuple(bar.trading_day for bar in bars),
        "physical_contract": contracts,
        "open_": tuple(float(bar.open) for bar in bars),
        "high": tuple(float(bar.high) for bar in bars),
        "low": tuple(float(bar.low) for bar in bars),
        "close": tuple(float(bar.close) for bar in bars),
        "volume": tuple(float(bar.volume) for bar in bars),
        "open_interest": tuple(
            None if bar.open_interest is None else float(bar.open_interest)
            for bar in bars
        ),
    }


def _contracts_for_bars(
    bars: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...],
) -> tuple[str, ...]:
    result: list[str] = []
    for bar in bars:
        matches = tuple(
            segment.contract
            for segment in segments
            if segment.start_trading_day
            <= bar.trading_day
            <= segment.end_trading_day
        )
        if len(matches) != 1:
            raise MainForceMirrorV2Error("MFM_V2_PHYSICAL_CONTRACT_MISSING")
        result.append(matches[0])
    return tuple(result)


def _contract_by_trading_day(
    bars: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...],
) -> Mapping[date, str]:
    contracts = _contracts_for_bars(bars, segments)
    result: dict[date, str] = {}
    for bar, contract in zip(bars, contracts, strict=True):
        previous = result.setdefault(bar.trading_day, contract)
        if previous != contract:
            raise MainForceMirrorV2Error("MFM_V2_MARKET_IDENTITY_CONFLICT")
    return result


def _daily_input(day: MemberRankDay) -> MemberRankDailyInput:
    long_rows = day.rows_for("long")
    short_rows = day.rows_for("short")
    volume_rows = day.rows_for("volume")
    if not (len(long_rows) == len(short_rows) == len(volume_rows) == 20):
        raise MainForceMirrorV2Error("MFM_V2_MEMBER_DATASET_INVALID")
    return MemberRankDailyInput(
        member_trade_date=day.trade_date,
        long_total=sum((row.value for row in long_rows), Decimal(0)),
        short_total=sum((row.value for row in short_rows), Decimal(0)),
        long_change_total=sum((row.change for row in long_rows), Decimal(0)),
        short_change_total=sum((row.change for row in short_rows), Decimal(0)),
        top5_volume_total=sum(
            (row.value for row in volume_rows if row.rank <= 5), Decimal(0)
        ),
        top20_volume_total=sum((row.value for row in volume_rows), Decimal(0)),
    )
