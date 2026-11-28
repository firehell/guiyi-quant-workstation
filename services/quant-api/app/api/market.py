"""Read-only Market API backed by the canonical MarketDataService."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import ceil
from time import monotonic
from typing import Literal, cast
from threading import BoundedSemaphore, Event
from decimal import Decimal

from anyio import CapacityLimiter, create_task_group, sleep, to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from app.api.conditional import conditional_json
from app.api.market_live import _display_runtime
from app.market_data.newow.home_projection_composition import build_home_overview_projection as build_market_home_projection
from sqlalchemy.orm import Session

from app.compute_runtime import ComputeBusy
from app.db.session import get_db
from app.db.readonly import readonly_transaction
from app.market_data.chart_indicators import (
    OwnedChartBar, load_chart_study_rows, project_chart_study_display, source_revision,
)
from app.market_data.chart_study_live import (
    project_chart_study_tail, read_chart_study_seed, retain_chart_study_seed, verify_tail_reconciliation,
)
from app.market_data.composition import (
    build_market_data_service,
    build_market_research_service,
    open_market_read_service,
)
from app.market_data.domain import (
    BarFrequency,
    canonical_bar_source_sha256,
    ContractError,
    MarketSeriesPageResult,
    SeriesKind,
    SeriesPageQuery,
    parse_rfc3339_instant,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.market_home_overview import MarketHomeOverviewError
from app.market_data.market_research_service import ResearchSeriesIdentity
from app.market_data.product_taxonomy import ProductTaxonomyError
from app.schemas.market import (
    ContractSegmentOut,
    CoverageOut,
    DominantContractListResponse,
    DominantContractOut,
    MarketBarOut,
    MarketBarsPageResponse,
    MarketChartStudyDisplayOut,
    MarketChartStudyId,
    MarketChartStudyProfile,
    MarketHomeOverviewResponse,
    MarketPageMetaOut,
    MarketProductDirectoryItem,
    MarketProductDirectoryResponse,
    ProductResearchResponse,
)

router = APIRouter(prefix="/api/v1/market", tags=["market"])
_DYNAMIC_RANGE_GATE = BoundedSemaphore(1)
_CHART_STUDY_GATE = BoundedSemaphore(1)
_CHART_STUDY_THREADS = CapacityLimiter(1)
_CHART_STUDY_BUDGET_SECONDS = 8
_CHART_STUDIES_PATTERN = r"^(ema10|ema21|ema60|boll|macd)(,(ema10|ema21|ema60|boll|macd)){0,4}$"


@router.get("/research/home-overview", response_model=MarketHomeOverviewResponse)
def market_home_overview(
    request: Request,
    session: Session = Depends(get_db),
) -> Response:
    try:
        projection = build_market_home_projection(session)
        if getattr(request.state, 'candidate_preview_as_of', None) is not None:
            raise HTTPException(503, detail={'code': 'HOME_PROJECTION_PREVIEW_UNAVAILABLE'})
        value = projection.read()
        return conditional_json(request, value.model_dump(mode="json"))
    except MarketHomeOverviewError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc


@router.get("/bars/page", response_model=MarketBarsPageResponse)
def canonical_market_bars_page(
    http_request: Request,
    series_kind: str = Query(...),
    symbol: str = Query(...),
    frequency: str = Query(...),
    before: str | None = Query(default=None),
    limit: int = Query(default=1200, ge=1, le=2000),
    contract: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> MarketBarsPageResponse:
    try:
        request = SeriesPageQuery(
            series_kind=cast(SeriesKind, series_kind),
            symbol=symbol,
            contract=contract,
            frequency=cast(BarFrequency, frequency),
            before=(
                parse_rfc3339_instant(before, field="datetime")
                if before is not None
                else None
            ),
            limit=limit,
        )
        result = build_market_data_service(session).query_page(request)
    except ContractError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    include_source_hash = getattr(http_request.app.state, "market_foundation_reference_sessions", None) is not None
    return MarketBarsPageResponse(
        request=dict(result.request_identity),
        bars=[
            MarketBarOut(
                bar_end=bar.bar_end,
                trading_day=bar.trading_day,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest,
                source_bar_sha256=canonical_bar_source_sha256(bar) if include_source_hash else None,
            )
            for bar in result.bars
        ],
        canonical_coverage=(
            CoverageOut(start=result.canonical_coverage[0], end=result.canonical_coverage[1])
            if result.canonical_coverage
            else None
        ),
        page=MarketPageMetaOut(
            has_more_before=result.has_more_before,
            next_before=result.next_before,
        ),
        resolved_contract_segments=[
            ContractSegmentOut(
                contract=item.contract,
                start_trading_day=item.start_trading_day,
                end_trading_day=item.end_trading_day,
            )
            for item in result.resolved_contract_segments
        ],
    )


def _chart_studies(studies: str) -> tuple[MarketChartStudyId, ...]:
    requested = tuple(cast(MarketChartStudyId, study) for study in studies.split(","))
    if len(set(requested)) != len(requested):
        raise ContractError(field="studies", reason="duplicate")
    return requested


async def _run_chart_study(http_request: Request, calculate) -> MarketChartStudyDisplayOut:
    if not _CHART_STUDY_GATE.acquire(blocking=False):
        raise HTTPException(status_code=503, detail={"code": "MARKET_CHART_STUDY_BUSY"})
    deadline = monotonic() + _CHART_STUDY_BUDGET_SECONDS
    cancelled = Event()

    def check() -> float:
        remaining = deadline - monotonic()
        if cancelled.is_set() or remaining <= 0:
            raise TimeoutError
        return remaining

    async def watch_disconnect() -> None:
        while not await http_request.is_disconnected():
            await sleep(0.1)
        cancelled.set()

    # Capture worker exceptions outside the task group so FastAPI retains the
    # public error code without an ExceptionGroup wrapper.
    def work():
        try:
            return calculate(check), None
        except Exception as exc:
            return None, exc

    try:
        async with create_task_group() as group:
            group.start_soon(watch_disconnect)
            value, error = await to_thread.run_sync(work, limiter=_CHART_STUDY_THREADS)
            group.cancel_scope.cancel()
        if error is not None:
            raise error
        assert value is not None
        return value
    except MarketDataError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from None
    except ComputeBusy:
        raise HTTPException(status_code=503, detail={"code": "MARKET_CHART_STUDY_BUSY"}) from None
    except TimeoutError:
        raise HTTPException(status_code=503, detail={"code": "MARKET_CHART_STUDY_BUDGET_EXCEEDED"}) from None
    except Exception:
        raise HTTPException(status_code=503, detail={"code": "MARKET_CHART_STUDY_UNAVAILABLE"}) from None
    finally:
        _CHART_STUDY_GATE.release()


@router.get("/indicators/chart-window", response_model=MarketChartStudyDisplayOut)
async def market_chart_window_studies(
    http_request: Request, series_kind: SeriesKind, symbol: str, frequency: BarFrequency,
    first: str, last: str, count: int = Query(ge=1, le=2000),
    studies: str = Query(pattern=_CHART_STUDIES_PATTERN),
    contract: str | None = None, profile: MarketChartStudyProfile | Literal["newow"] | None = None,
    session: Session = Depends(get_db),
) -> MarketChartStudyDisplayOut:
    """Slice aligned generic study results to the requested Canonical Bars."""
    try:
        requested = _chart_studies(studies)
        start = parse_rfc3339_instant(first, field="first")
        end = parse_rfc3339_instant(last, field="last")
        now = getattr(http_request.state, "candidate_preview_as_of", None) or datetime.now(UTC)
        if start > end or (start == end) != (count == 1) or end > now:
            raise ContractError(field="window", reason="invalid")
        before = end if series_kind is SeriesKind.CONTRACT else end + timedelta(microseconds=1)
        query = SeriesPageQuery(series_kind, symbol, frequency, before, count, contract)
    except ContractError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "facts": dict(exc.facts)}) from None
    if query.series_kind is SeriesKind.CONTINUOUS:
        return project_chart_study_display(query, None, first=start, last=end, studies=requested)

    def calculate(check) -> MarketChartStudyDisplayOut:
        def read_rows(*, retain: bool = False):
            with Session(bind=session.get_bind()) as snapshot, readonly_transaction(snapshot, timeout_seconds=ceil(check())):
                service = build_market_data_service(snapshot, check_cancelled=check)
                mapping_cache = {}

                def read_previous(cursor: datetime, required: int, need_month_head: bool) -> MarketSeriesPageResult:
                    if need_month_head:
                        limit = 320 if frequency in (BarFrequency.D1, BarFrequency.W1) else 2000
                    else:
                        limit = required
                    while True:
                        older = SeriesPageQuery(series_kind, symbol, frequency, cursor, limit, contract)
                        try:
                            return service.query_page(older, mapping_cache=mapping_cache)
                        except MarketDataError as exc:
                            if limit == 1 or exc.code not in {
                                "PRICE_UNAVAILABLE", "SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED",
                                "DATASET_OR_PARTITION_MISSING", "MAPPED_CONTRACT_DATASET_MISSING",
                            }:
                                raise
                            # A quality fact can lie beyond the required anchor.
                            # Shrink the read, never the verified calculation prefix.
                            check()
                            limit = max(1, limit // 2)

                def prove_coverage_start(first: OwnedChartBar, since: date) -> None:
                    # A successful historical page can lack an entire older month.
                    # The first stored row alone cannot prove the rank-1 start.
                    if (first.bar.trading_day - since).days > 31:
                        raise MarketDataError("MARKET_CHART_STUDY_ANCHOR_UNAVAILABLE")
                    expected = service.expected_contract_replay_endpoints(
                        symbol=query.symbol, contract=first.contract, frequency=query.frequency,
                        trading_day=first.bar.trading_day, cutoff=first.bar.bar_end, since=since,
                    )
                    if expected != ((first.bar.bar_end, first.bar.trading_day),):
                        raise MarketDataError("MARKET_CHART_STUDY_ANCHOR_UNAVAILABLE")

                page = (
                    service.query_page_inclusive(query) if query.series_kind is SeriesKind.CONTRACT
                    else service.query_page(query, mapping_cache=mapping_cache)
                )
                rows = load_chart_study_rows(
                    query, page, first=start, last=end, read_previous=read_previous,
                    prove_owner_segments=lambda since, through: service.actual_dominant_segments(
                        query.symbol, since, through,
                    ),
                    prove_coverage_start=prove_coverage_start,
                )
                if retain:
                    # Keep the latest verified prefix available to the optional
                    # tail request. Unusable evidence must not remove history.
                    try:
                        retain_chart_study_seed(service, query, rows, source_revision(rows), requested)
                    except MarketDataError:
                        pass
            check()
            return rows

        return project_chart_study_display(
            query, None, first=start, last=end, studies=requested, check_cancelled=check,
            rows=read_rows(retain=profile is not None and profile != "newow"), read_current_rows=read_rows,
        )

    return await _run_chart_study(http_request, calculate)


@router.get("/indicators/chart-tail", response_model=MarketChartStudyDisplayOut)
async def market_chart_tail_studies(
    http_request: Request, series_kind: SeriesKind, symbol: str, frequency: BarFrequency,
    profile: MarketChartStudyProfile, canonical_end: str,
    source_revision: str = Query(pattern=r"^[0-9a-f]{64}$"),
    studies: str = Query(pattern=_CHART_STUDIES_PATTERN),
    completed_through: str | None = None, include_preview: bool = False,
    contract: str | None = None, session: Session = Depends(get_db),
) -> MarketChartStudyDisplayOut:
    """Read a verified completed Live prefix and an optional independent active point."""
    del profile  # The whitelist is the display-consumer admission contract.
    now = getattr(http_request.state, "candidate_preview_as_of", None) or datetime.now(UTC)
    try:
        requested = _chart_studies(studies)
        end = parse_rfc3339_instant(canonical_end, field="canonical_end")
        through = (parse_rfc3339_instant(completed_through, field="completed_through")
                   if completed_through is not None else None)
        if (series_kind is SeriesKind.CONTINUOUS or end > now
                or through is not None and not end < through <= now):
            raise ContractError(field="window", reason="invalid")
        query = SeriesPageQuery(series_kind, symbol, frequency, contract=contract, limit=1)
    except ContractError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "facts": dict(exc.facts)}) from None

    def calculate(check) -> MarketChartStudyDisplayOut:
        runtime = _display_runtime(http_request)
        opener = runtime.open_reader if runtime is not None else open_market_read_service
        with Session(bind=session.get_bind()) as snapshot, readonly_transaction(snapshot, timeout_seconds=ceil(check())):
            service = build_market_data_service(snapshot, check_cancelled=check)
            seed = read_chart_study_seed(service, query, end, source_revision, requested)
            as_of = getattr(http_request.state, "candidate_preview_as_of", None) or datetime.now(UTC)
            with opener() as reader:
                display = reader.display_snapshot(query, end, as_of)
            check()
            response = project_chart_study_tail(
                service, query, display, seed, canonical_end=end, revision=source_revision,
                studies=requested, through=through, include_preview=include_preview, now=as_of, check_cancelled=check,
            )
        # If a Canonical publication raced the transient read, suppress the old
        # prefix rather than delivering a momentarily obsolete mixed result.
        with Session(bind=session.get_bind()) as snapshot, readonly_transaction(snapshot, timeout_seconds=ceil(check())):
            service = build_market_data_service(snapshot, check_cancelled=check)
            read_chart_study_seed(service, query, end, source_revision, requested)
            verify_tail_reconciliation(service, query, display, response)
        return response

    return await _run_chart_study(http_request, calculate)


@router.get("/dominants", response_model=DominantContractListResponse)
def market_dominants(request: Request, session: Session = Depends(get_db)) -> Response:
    items = build_market_data_service(session).list_latest_dominants()
    value = DominantContractListResponse(
        items=[
            DominantContractOut(
                product=item.symbol,
                product_name=item.product_name,
                sector=item.sector,
                exchange=item.exchange,
                actual_contract=item.actual_contract,
                dominant_mapping_date=item.dominant_mapping_date,
            )
            for item in items
        ]
    )

    return conditional_json(request, value.model_dump(mode="json"))


@router.get("/product-directory", response_model=MarketProductDirectoryResponse)
def market_product_directory(request: Request, session: Session = Depends(get_db)) -> Response:
    try:
        items = build_market_data_service(session).list_product_directory()
    except (MarketDataError, ProductTaxonomyError) as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    value = MarketProductDirectoryResponse(items=[
        MarketProductDirectoryItem(
            product=item.product, product_name=item.product_name,
            exchange=item.exchange, sector=item.sector,
        ) for item in items
    ])
    response = conditional_json(request, value.model_dump(mode="json"))
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response

@router.get("/research/product", response_model=ProductResearchResponse)
def product_research(
    symbol: str = Query(...),
    series_kind: str = Query(...),
    contract: str | None = Query(default=None),
    session: Session = Depends(get_db),
) -> ProductResearchResponse:
    try:
        snapshot = build_market_research_service(session).product_snapshot(
            ResearchSeriesIdentity(
                symbol=symbol,
                series_kind=cast(SeriesKind, series_kind),
                contract=contract,
            )
        )
    except ContractError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "facts": dict(exc.facts)},
        ) from exc
    except MarketDataError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    metrics = snapshot.metrics
    return ProductResearchResponse(
        symbol=snapshot.symbol,
        product_name=snapshot.product_name,
        sector=snapshot.sector,
        exchange=snapshot.exchange,
        series_kind=snapshot.series_kind.value,
        contract=snapshot.contract,
        as_of=snapshot.as_of,
        current_dominant=snapshot.current_dominant,
        metric_contract=snapshot.metric_contract,
        dominant_mapping_date=snapshot.dominant_mapping_date,
        daily_trend=metrics.daily_trend,
        weekly_trend=metrics.weekly_trend,
        position20=metrics.position20,
        distance_to_20d_high=metrics.distance_to_20d_high,
        distance_to_20d_low=metrics.distance_to_20d_low,
        volume_ratio20=metrics.volume_ratio20,
        oi_change_1d=metrics.oi_change_1d,
        turnover_change_5d=metrics.turnover_change_5d,
        atr14_percentile252=metrics.atr14_percentile252,
        recent_daily=[
            MarketBarOut(
                bar_end=bar.bar_end,
                trading_day=bar.trading_day,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                turnover=bar.turnover,
                open_interest=bar.open_interest,
            )
            for bar in snapshot.recent_daily
        ],
    )


@router.get('/indicators/dynamic-range')
def dynamic_range_indicator(
    symbol: str, contract: str, frequency: str, start: str, end: str,
    session: Session = Depends(get_db),
):
    """Optional research display; no writes, live promotion or trading consumers."""
    from datetime import datetime, timezone
    from time import monotonic
    from fastapi.encoders import jsonable_encoder
    from app.db.readonly import readonly_transaction
    from app.market_data.dynamic_range import chart_window, DynamicRangeError
    from app.market_data.new_subing_research import NewSubingInputError

    if not _DYNAMIC_RANGE_GATE.acquire(blocking=False):
        raise HTTPException(503, detail={'code': 'DYNAMIC_RANGE_BUSY'})
    deadline = monotonic()+25

    def check():
        if monotonic() > deadline:
            raise DynamicRangeError('DYNAMIC_RANGE_BUDGET_EXCEEDED')

    try:
        first = parse_rfc3339_instant(start, field='start')
        last = parse_rfc3339_instant(end, field='end')
        if last > datetime.now(timezone.utc):
            raise DynamicRangeError('DYNAMIC_RANGE_WINDOW_INVALID')
        with readonly_transaction(session, timeout_seconds=25):
            result = chart_window(build_market_data_service(session, check_cancelled=check), symbol=symbol,
                contract=contract, frequency=frequency, start=first, end=last, check=check)
        return jsonable_encoder(result, custom_encoder={Decimal: str})
    except ContractError:
        raise HTTPException(422, detail={'code': 'DYNAMIC_RANGE_QUERY_INVALID'}) from None
    except (DynamicRangeError, MarketDataError, NewSubingInputError) as exc:
        raise HTTPException(409, detail={'code': exc.code}) from None
    except Exception:
        raise HTTPException(503, detail={'code': 'DYNAMIC_RANGE_UNAVAILABLE'}) from None
    finally:
        _DYNAMIC_RANGE_GATE.release()
