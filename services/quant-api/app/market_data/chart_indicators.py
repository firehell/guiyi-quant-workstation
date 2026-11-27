"""Page-independent, display-only projection of registered generic chart studies."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from itertools import groupby
from typing import Literal

from guiyi_quant.compute import REGISTRY, BarSeries, CompletedBar, FeaturePoint, FeatureRequest, SeriesIdentity

from app.compute_runtime import ComputeRuntime, ComputeWindow
from app.market_data.domain import (
    CanonicalBar,
    MarketSeriesPageResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesPageQuery,
    canonical_bar_source_sha256,
)
from app.market_data.market_data_service import MarketDataError
from app.schemas.market import (
    MarketChartStudyBarOut,
    MarketChartStudyDisplayOut,
    MarketChartStudyFeatureOut,
    MarketChartStudyId,
    MarketChartStudyPointOut,
    MarketChartStudySegmentOut,
)

_CHART_COMPUTE = ComputeRuntime(REGISTRY, batch_pending=1, cache_entries=64, cache_points=120_000)
ANCHOR_POLICY = "trading_month_256_v1"
WARM_PREFIX = 256
_MAX_PREFIX_PAGES = 8
ChartBarSource = Literal["canonical", "completed_live", "active_preview"]


@dataclass(frozen=True, slots=True)
class OwnedChartBar:
    bar: CanonicalBar
    contract: str
    owner_segment: str

    @property
    def quality_ok(self) -> bool:
        return not self.bar.is_strict_no_trade and self.bar.close > 0


@dataclass(frozen=True, slots=True)
class ChartStudyBlock:
    rows: tuple[OwnedChartBar, ...]
    output_start: int

    @property
    def anchor(self) -> datetime:
        return self.rows[0].bar.bar_end

    @property
    def segment_id(self) -> str:
        return block_segment_id(self.rows[0], self.rows[self.output_start].bar.trading_day)


def block_segment_id(first: OwnedChartBar, trading_day: date) -> str:
    return f"{ANCHOR_POLICY}:{first.owner_segment}:{trading_day:%Y-%m}:{first.bar.bar_end.isoformat()}"


def source_revision(rows: tuple[OwnedChartBar, ...]) -> str:
    digest = sha256()
    for row in rows:
        digest.update(row.owner_segment.encode())
        digest.update(bytes.fromhex(canonical_bar_source_sha256(row.bar)))
    return digest.hexdigest()


def study_bar(row: OwnedChartBar, segment_id: str) -> CompletedBar:
    bar = row.bar
    return CompletedBar(
        row.contract, segment_id, bar.trading_day, f"chart:{bar.trading_day}",
        bar.bar_end, bar.bar_end, bar.bar_end, None, None, None,
        float(bar.close), None, "VALID" if row.quality_ok else "MISSING",
    )


def bar_output(bar: CanonicalBar, source: ChartBarSource) -> MarketChartStudyBarOut:
    return MarketChartStudyBarOut(
        bar_end=bar.bar_end, trading_day=bar.trading_day, source=source,
        open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=bar.volume,
        source_bar_sha256=canonical_bar_source_sha256(bar),
    )


def point_output(point: FeaturePoint) -> MarketChartStudyPointOut:
    return MarketChartStudyPointOut(
        status=point.status.value,
        values={key: float(value) for key, value in point.values.items()} if point.values is not None else None,
        diagnostic=point.diagnostic,
    )


def chart_scope(request: SeriesPageQuery, last: datetime) -> dict:
    return dict(
        symbol=request.symbol, series_kind=request.series_kind, contract=request.contract,
        frequency=request.frequency.value, as_of=last,
    )


def _owner(
    request: SeriesPageQuery, segments: tuple[ResolvedContractSegment, ...], bar: CanonicalBar,
) -> tuple[str, str]:
    if request.contract is not None:
        return request.contract, f"contract:{request.contract}"
    matches = [
        segment for segment in segments
        if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
    ]
    if len(matches) != 1:
        raise MarketDataError("MARKET_CHART_STUDY_PHYSICAL_OWNER_INVALID")
    segment = matches[0]
    return segment.contract, f"{segment.contract}:{segment.start_trading_day}"


def _owned_page(request: SeriesPageQuery, page: MarketSeriesPageResult) -> tuple[OwnedChartBar, ...]:
    return tuple(OwnedChartBar(bar, *_owner(request, page.resolved_contract_segments, bar)) for bar in page.bars)


def _required_prefix(
    rows: tuple[OwnedChartBar, ...], first: datetime, *, exact_owner: bool = False,
) -> tuple[int, bool]:
    target = next(index for index, row in enumerate(rows) if row.bar.bar_end == first)
    owner = rows[target]
    month = _month(rows[target].bar.trading_day)
    if not rows[target].quality_ok:
        return 0, False
    preceding = 0
    for row in reversed(rows[:target]):
        if row.contract != owner.contract or (exact_owner and row.owner_segment != owner.owner_segment) or not row.quality_ok:
            return 0, False
        if _month(row.bar.trading_day) < month:
            preceding += 1
            if preceding == WARM_PREFIX:
                return 0, False
    return WARM_PREFIX - preceding, _month(rows[0].bar.trading_day) == month


def _month(day: date) -> tuple[int, int]:
    return day.year, day.month


def load_chart_study_rows(
    request: SeriesPageQuery, page: MarketSeriesPageResult | None, *, first: datetime, last: datetime,
    read_previous: Callable[[datetime, int, bool], MarketSeriesPageResult] | None = None,
    prove_owner_segments: Callable[[date, date], tuple[ResolvedContractSegment, ...]] | None = None,
    prove_coverage_start: Callable[[OwnedChartBar, date], None] | None = None,
) -> tuple[OwnedChartBar, ...]:
    if (
        page is None or len(page.bars) != request.limit
        or page.bars[0].bar_end != first or page.bars[-1].bar_end != last
    ):
        raise MarketDataError("MARKET_CHART_STUDY_WINDOW_MISMATCH")

    rows = _owned_page(request, page)
    for _ in range(_MAX_PREFIX_PAGES):
        required, need_month_head = _required_prefix(rows, first)
        if not page.has_more_before or not required:
            break
        if read_previous is None:
            raise MarketDataError("MARKET_CHART_STUDY_ANCHOR_UNAVAILABLE")
        page = read_previous(rows[0].bar.bar_end, required, need_month_head)
        previous = _owned_page(request, page)
        if not previous or previous[-1].bar.bar_end >= rows[0].bar.bar_end:
            raise MarketDataError("MARKET_CHART_STUDY_ANCHOR_UNAVAILABLE")
        rows = previous + rows
    if page.has_more_before and _required_prefix(rows, first)[0]:
        raise MarketDataError("MARKET_CHART_STUDY_ANCHOR_UNAVAILABLE")

    if request.contract is None and prove_owner_segments is not None:
        segments = prove_owner_segments(rows[0].bar.trading_day, rows[-1].bar.trading_day)
        proved = tuple(OwnedChartBar(row.bar, *_owner(request, segments, row.bar)) for row in rows)
        if any(old.contract != new.contract for old, new in zip(rows, proved, strict=True)):
            raise MarketDataError("MARKET_CHART_STUDY_PHYSICAL_OWNER_INVALID")
        if _required_prefix(proved, first, exact_owner=True)[0]:
            if page.has_more_before or prove_coverage_start is None:
                raise MarketDataError("MARKET_CHART_STUDY_ANCHOR_UNAVAILABLE")
            start_segment = next(segment for segment in segments
                                 if segment.start_trading_day <= proved[0].bar.trading_day <= segment.end_trading_day)
            prove_coverage_start(proved[0], start_segment.start_trading_day)
        return proved
    # Page-local owner segment names only serve callers with a single verified page.
    return rows


def calculation_blocks(rows: tuple[OwnedChartBar, ...]) -> tuple[ChartStudyBlock, ...]:
    blocks: list[ChartStudyBlock] = []
    for (_, quality_ok), group in groupby(rows, key=lambda row: (row.owner_segment, row.quality_ok)):
        segment = tuple(group)
        if not quality_ok:
            blocks.extend(ChartStudyBlock((row,), 0) for row in segment)
            continue
        offset = 0
        for _, group_in_month in groupby(segment, key=lambda row: _month(row.bar.trading_day)):
            month_length = len(tuple(group_in_month))
            start = max(0, offset - WARM_PREFIX)
            blocks.append(ChartStudyBlock(segment[start:offset + month_length], offset - start))
            offset += month_length
    return tuple(blocks)


def block_series(request: SeriesPageQuery, block: ChartStudyBlock) -> BarSeries:
    segment_id = block.segment_id
    identity = SeriesIdentity(
        request.symbol, block.rows[0].contract, segment_id, request.frequency.value, source_revision(block.rows),
    )
    return BarSeries(identity, tuple(study_bar(row, segment_id) for row in block.rows))


def project_chart_study_display(
    request: SeriesPageQuery, page: MarketSeriesPageResult | None,
    *, first: datetime, last: datetime, studies: tuple[MarketChartStudyId, ...],
    check_cancelled: Callable[[], float | None] | None = None,
    read_current: Callable[[], MarketSeriesPageResult] | None = None,
    rows: tuple[OwnedChartBar, ...] | None = None,
    read_current_rows: Callable[[], tuple[OwnedChartBar, ...]] | None = None,
) -> MarketChartStudyDisplayOut:
    scope = chart_scope(request, last)
    if request.series_kind is SeriesKind.CONTINUOUS:
        return MarketChartStudyDisplayOut(
            **scope, source_revision=None, unavailable_reason="PHYSICAL_OWNER_REQUIRED", segments=[],
        )

    rows = rows if rows is not None else load_chart_study_rows(request, page, first=first, last=last)
    features = tuple(FeatureRequest(study) for study in studies)
    segments = []
    calculated_uncached = False
    calculated_inputs: list[BarSeries] = []
    for block in calculation_blocks(rows):
        if block.rows[-1].bar.bar_end < first:
            continue
        if check_cancelled is not None:
            check_cancelled()
        series = block_series(request, block)
        window = ComputeWindow.from_series(series, as_of=block.rows[-1].bar.bar_end)
        calculated = _CHART_COMPUTE.read_batch(window, features, use="web")
        if calculated is None:
            calculated_uncached = True
            job = _CHART_COMPUTE.submit_batch(window, features, use="web", load=lambda: series)
            try:
                if check_cancelled is None:
                    calculated = job.result()
                else:
                    while True:
                        try:
                            calculated = job.result(timeout=min(0.1, check_cancelled()))
                            break
                        except TimeoutError:
                            if job.done():
                                raise
                            # Check the request deadline/disconnect on the next wait.
                            check_cancelled()
            except TimeoutError:
                _CHART_COMPUTE.invalidate_revision(series.identity, from_bar_end=block.anchor)
                raise
        calculated_inputs.append(series)
        offset = next(index for index, row in enumerate(block.rows) if index >= block.output_start
                      and row.bar.bar_end >= first)
        segments.append(MarketChartStudySegmentOut(
            physical_contract=series.identity.physical_contract, segment_id=block.segment_id,
            calculation_anchor=block.anchor,
            bars=[bar_output(row.bar, "canonical") for row in block.rows[offset:]],
            features=[
                MarketChartStudyFeatureOut(
                    study=study, formula_version=result.identity.formula_version,
                    backend_version=result.identity.backend_version,
                    parameters_hash=result.identity.parameters_hash,
                    points=[point_output(point) for point in result.points[offset:]],
                )
                for study, result in zip(studies, calculated, strict=True)
            ],
        ))
    if calculated_uncached and (read_current_rows is not None or read_current is not None):
        current = (
            read_current_rows() if read_current_rows is not None
            else load_chart_study_rows(request, read_current(), first=first, last=last)
        )
        if rows != current:
            current_ids = {
                (block.segment_id, source_revision(block.rows))
                for block in calculation_blocks(current)
            }
            for series in calculated_inputs:
                identity = series.identity
                if (identity.segment_id, identity.source_revision) not in current_ids:
                    _CHART_COMPUTE.invalidate_revision(identity, from_bar_end=series.bars[0].bar_end)
            raise MarketDataError("MARKET_CHART_STUDY_WINDOW_MISMATCH")
    if check_cancelled is not None:
        check_cancelled()
    return MarketChartStudyDisplayOut(
        **scope, source_revision=source_revision(rows), unavailable_reason=None, segments=segments,
    )
