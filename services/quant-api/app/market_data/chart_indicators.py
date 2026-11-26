"""Project requested chart studies from one bounded, verified historical Bar window."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from itertools import groupby

from guiyi_quant.compute import REGISTRY, BarSeries, CompletedBar, FeatureRequest, SeriesIdentity

from app.compute_runtime import ComputeRuntime, ComputeWindow
from app.market_data.domain import (
    CanonicalBar,
    MarketSeriesPageResult,
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


_CHART_COMPUTE = ComputeRuntime(REGISTRY, batch_pending=1, cache_entries=64, cache_points=16_000)


@dataclass(frozen=True, slots=True)
class _ChartStudySource:
    identity: SeriesIdentity
    bars: tuple[CanonicalBar, ...]
    bar_hashes: tuple[str, ...]


def _owner(
    request: SeriesPageQuery, page: MarketSeriesPageResult, bar: CanonicalBar,
) -> tuple[str, str]:
    if request.contract is not None:
        return request.contract, f"contract:{request.contract}"
    matches = [
        segment for segment in page.resolved_contract_segments
        if segment.start_trading_day <= bar.trading_day <= segment.end_trading_day
    ]
    if len(matches) != 1:
        raise MarketDataError("MARKET_CHART_STUDY_PHYSICAL_OWNER_INVALID")
    segment = matches[0]
    return segment.contract, f"{segment.contract}:{segment.start_trading_day}"


def _sources(request: SeriesPageQuery, page: MarketSeriesPageResult) -> tuple[_ChartStudySource, ...]:
    owners = ((_owner(request, page, bar), bar) for bar in page.bars)
    sources = []
    for (contract, segment_id), group in groupby(owners, key=lambda item: item[0]):
        bars = tuple(bar for _, bar in group)
        hashes = tuple(canonical_bar_source_sha256(bar) for bar in bars)
        revision = sha256(b"".join(bytes.fromhex(value) for value in hashes)).hexdigest()
        identity = SeriesIdentity(request.symbol, contract, segment_id, request.frequency.value, revision)
        sources.append(_ChartStudySource(identity, bars, hashes))
    return tuple(sources)


def project_chart_study_display(
    request: SeriesPageQuery, page: MarketSeriesPageResult | None,
    *, first: datetime, last: datetime, studies: tuple[MarketChartStudyId, ...],
    check_cancelled: Callable[[], float | None] | None = None,
    read_current: Callable[[], MarketSeriesPageResult] | None = None,
) -> MarketChartStudyDisplayOut:
    scope = dict(
        symbol=request.symbol, series_kind=request.series_kind,
        contract=request.contract, frequency=request.frequency.value, as_of=last,
    )
    if request.series_kind is SeriesKind.CONTINUOUS:
        return MarketChartStudyDisplayOut(
            **scope, source_revision=None, unavailable_reason="PHYSICAL_OWNER_REQUIRED", segments=[],
        )
    if (
        page is None or len(page.bars) != request.limit
        or page.bars[0].bar_end != first or page.bars[-1].bar_end != last
    ):
        raise MarketDataError("MARKET_CHART_STUDY_WINDOW_MISMATCH")

    requests = tuple(FeatureRequest(study) for study in studies)
    source_digest = sha256()
    segments = []
    sources = _sources(request, page)
    calculated_uncached = False
    for source in sources:
        if check_cancelled is not None:
            check_cancelled()
        identity = source.identity
        contract, segment_id = identity.physical_contract, identity.segment_id
        source_digest.update(segment_id.encode())
        source_digest.update(bytes.fromhex(identity.source_revision))
        series = BarSeries(
            identity,
            tuple(
                # This historical reference uses the canonical completion Bar end.
                CompletedBar(
                    contract, segment_id, bar.trading_day, f"historical:{bar.trading_day}",
                    bar.bar_end, bar.bar_end, bar.bar_end, None, None, None,
                    float(bar.close), None, "MISSING" if bar.is_strict_no_trade else "VALID",
                )
                for bar in source.bars
            ),
        )
        window = ComputeWindow.from_series(series, as_of=last)
        calculated = _CHART_COMPUTE.read_batch(window, requests, use="web") if read_current is not None else None
        if calculated is None:
            calculated_uncached = True
            job = _CHART_COMPUTE.submit_batch(window, requests, use="web", load=lambda: series)
            try:
                calculated = job.result(timeout=check_cancelled() if check_cancelled is not None else None)
            except TimeoutError:
                _CHART_COMPUTE.invalidate_revision(identity, from_bar_end=source.bars[0].bar_end)
                raise
        if check_cancelled is not None:
            check_cancelled()
        segments.append(MarketChartStudySegmentOut(
            physical_contract=contract, segment_id=segment_id,
            bars=[
                MarketChartStudyBarOut(bar_end=bar.bar_end, close=bar.close, source_bar_sha256=source_hash)
                for bar, source_hash in zip(source.bars, source.bar_hashes, strict=True)
            ],
            features=[
                MarketChartStudyFeatureOut(
                    study=study, formula_version=result.identity.formula_version,
                    backend_version=result.identity.backend_version,
                    parameters_hash=result.identity.parameters_hash,
                    points=[
                        MarketChartStudyPointOut(
                            status=point.status.value,
                            values={key: float(value) for key, value in point.values.items()}
                            if point.values is not None else None,
                            diagnostic=point.diagnostic,
                        )
                        for point in result.points
                    ],
                )
                for study, result in zip(studies, calculated, strict=True)
            ],
        ))
    if read_current is not None and calculated_uncached:
        # A queued calculation outlives the read transaction that supplied it.
        # Check the same bounded Market window again before exposing its result.
        current = _sources(request, read_current())
        if tuple(source.identity for source in sources) != tuple(source.identity for source in current):
            current_identities = {source.identity for source in current}
            for source in sources:
                if source.identity not in current_identities:
                    _CHART_COMPUTE.invalidate_revision(source.identity, from_bar_end=source.bars[0].bar_end)
            raise MarketDataError("MARKET_CHART_STUDY_WINDOW_MISMATCH")
        if check_cancelled is not None:
            check_cancelled()
    return MarketChartStudyDisplayOut(
        **scope, source_revision=source_digest.hexdigest(), unavailable_reason=None, segments=segments,
    )
