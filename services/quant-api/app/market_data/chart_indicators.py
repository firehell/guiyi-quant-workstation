"""Project requested chart studies from one bounded, verified historical Bar window."""

from collections.abc import Callable
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


def project_chart_study_display(
    request: SeriesPageQuery, page: MarketSeriesPageResult | None,
    *, first: datetime, last: datetime, studies: tuple[MarketChartStudyId, ...],
    check_cancelled: Callable[[], None] | None = None,
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
    owners = ((_owner(request, page, bar), bar) for bar in page.bars)
    for (contract, segment_id), group in groupby(owners, key=lambda item: item[0]):
        if check_cancelled is not None:
            check_cancelled()
        bars = tuple(bar for _, bar in group)
        source_hashes = tuple(canonical_bar_source_sha256(bar) for bar in bars)
        segment_digest = sha256()
        for source_hash in source_hashes:
            segment_digest.update(bytes.fromhex(source_hash))
        source_digest.update(segment_id.encode())
        source_digest.update(segment_digest.digest())
        series = BarSeries(
            SeriesIdentity(request.symbol, contract, segment_id, request.frequency.value, segment_digest.hexdigest()),
            tuple(
                # This historical reference uses the canonical completion Bar end.
                CompletedBar(
                    contract, segment_id, bar.trading_day, f"historical:{bar.trading_day}",
                    bar.bar_end, bar.bar_end, bar.bar_end, None, None, None,
                    float(bar.close), None, "MISSING" if bar.is_strict_no_trade else "VALID",
                )
                for bar in bars
            ),
        )
        window = ComputeWindow.from_series(series, as_of=last)
        calculated = _CHART_COMPUTE.submit_batch(window, requests, use="web", load=lambda: series).result()
        if check_cancelled is not None:
            check_cancelled()
        segments.append(MarketChartStudySegmentOut(
            physical_contract=contract, segment_id=segment_id,
            bars=[
                MarketChartStudyBarOut(bar_end=bar.bar_end, close=bar.close, source_bar_sha256=source_hash)
                for bar, source_hash in zip(bars, source_hashes, strict=True)
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
    return MarketChartStudyDisplayOut(
        **scope, source_revision=source_digest.hexdigest(), unavailable_reason=None, segments=segments,
    )
