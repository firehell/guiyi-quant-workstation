"""Read-only Newow actual-dominant D1 detail endpoint."""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import UTC, date, datetime
import re
from typing import Literal, cast
from collections.abc import Callable

from anyio import from_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from guiyi_quant.newow.product_identity import InputQualityPolicy
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from app.reference_trading.presentation import PresentationUnavailable
from app.reference_trading.query import QueryConflict

from app.db.session import SessionLocal, get_db, engine
from app.api.conditional import conditional_json
from app.core.env import PROJECT_ROOT
from app.market_data.after_market import _load_status, public_after_market_status
from app.market_data.composition import (
    build_database_coverage_source,
    build_market_data_service,
)
from app.market_data.newow.composition import NewowComposition
from app.market_data.newow.historical_snapshot import (
    NewowHistoricalSnapshotResolver,
)
from app.market_data.newow.daily_snapshot import NewowDailySnapshotResolver
from app.market_data.newow.weekly_snapshot import (
    NewowWeeklySnapshotResolver,
    publication_state_from_status,
)
from app.market_data.newow.public_errors import public_product_error
from app.market_data.newow.product_release import (
    AU_PERIOD_PREVIEW_FREQUENCIES,
    INTRADAY_BATCH_PREVIEW_SYMBOLS,
    INTRADAY_SINGLE_PREVIEW_SYMBOLS,
    AU_PERIOD_PREVIEW_SCHEMA_VERSION,
    AU_PERIOD_PREVIEW_STAGE,
    CAPABILITY_SCHEMA_VERSION,
    CANDIDATE_CAPABILITY_SCHEMA_VERSION,
    CANDIDATE_WEEKLY_PRODUCTS,
    CANDIDATE_DEFERRED_FREQUENCIES,
    CANDIDATE_OPEN_FREQUENCIES,
    CANDIDATE_RELEASE_STAGE,
    DEFERRED_SECTIONS,
    HOURLY_PRODUCT_PREVIEW_DEFERRED,
    HOURLY_PRODUCT_PREVIEW_FREQUENCIES,
    HOURLY_PRODUCT_PREVIEW_SCHEMA_VERSION,
    HOURLY_PRODUCT_PREVIEW_STAGE,
    HOURLY_PRODUCT_PREVIEW_SYMBOLS,
    PD_PT_HOURLY_PREVIEW_SCHEMA_VERSION,
    PD_PT_HOURLY_PREVIEW_STAGE,
    PD_PT_HOURLY_PREVIEW_SYMBOLS,
    OPEN_INTRADAY_PRODUCTS,
    INTRADAY_HISTORY_AS_OF,
    INTRADAY_HISTORY_SCHEMA,
    INTRADAY_HISTORY_FREQUENCIES,
    FROZEN_INTRADAY_FREQUENCIES,
    LATEST_COMPLETED_FREQUENCIES,
    MAIN_RISE_FREQUENCIES,
    released_intraday_as_of,
    OPEN_WEEKLY_PRODUCTS,
    OPEN_SECTIONS,
    RELEASE_STAGE,
    candidate_input_quality_policy,
    require_open_frequency,
    require_candidate_weekly_product,
    require_open_weekly_product,
    require_open_section,
)
from app.market_data.newow.inflight import (
    InFlightCoordinator,
)
from app.market_data.newow.product_service import (
    NewowProductService,
    ProductServiceQuery,
    ProductSection,
    AuxiliaryComponent,
)
from app.market_data.newow.resource_gate import HeavyResourceGate
from app.market_data.newow.snapshot_cache import SnapshotCache
from app.market_data.operational_universe import (
    ActiveUniverseError,
    load_active_products,
)
from app.market_data.newow.trend_detail_query import NewowTrendDetailQuery
from app.market_data.newow.trend_detail_service import (
    NewowTrendDetailError,
    NewowTrendDetailService,
)
from app.market_data.product_taxonomy import ProductTaxonomyError, load_product_taxonomy
from app.schemas.market_newow import (
    NewowTrendDetailResponse,
)
from app.schemas.market_newow_product import (
    CurrentSnapshotContextOut,
    DeferredFrequencyOut,
    DeferredSectionOut,
    NewowHistoricalSnapshotResponse,
    NewowDailySnapshotResponse,
    NewowWeeklySnapshotResponse,
    NewowProductCapabilitiesResponse,
    NewowProductResponse,
)

from app.api.newow_presentation import (
    _auxiliary_data_value as _auxiliary_data_value,
    _json_value,
    _product_response,
    _response,
    _trade as _trade,
)

router = APIRouter(prefix="/api/v1/market/newow", tags=["market"])

_CLIENT_ERRORS = frozenset(
    {"NEWOW_INVALID_PRODUCT", "NEWOW_INVALID_RANGE", "NEWOW_RANGE_TOO_LARGE"}
)
_PRODUCT_CACHE = SnapshotCache()
_INTRADAY_HISTORY_CACHE = SnapshotCache(max_bytes=512 * 1024 * 1024, max_entry_bytes=256 * 1024 * 1024)
_PRODUCT_GATE = HeavyResourceGate()
# Saved minute history has independent bounded admission; it must not starve
# current chart comparisons and D1/W1 background calculations.
_PERSISTED_REFERENCE_GATE = HeavyResourceGate(max_running=1, max_waiting=2, wait_timeout=50)
_PRODUCT_INFLIGHT = InFlightCoordinator()
_PRODUCT_QUERY_FIELDS = frozenset(
    {
        "product",
        "strategy",
        "frequency",
        "series_kind",
        "section",
        "from",
        "through",
        "performance_since",
        "performance_through",
        "as_of",
        "chart_limit",
        "chart_before",
        "chart_older_window",
        "component",
        "history_limit",
        "history_before",
        "snapshot_token",
        "include_fusion",
        "fusion_before",
        "decision_v2",
        "resolve_current",
    }
)
_HISTORICAL_QUERY_FIELDS = frozenset({"product", "strategy", "frequency"})


@router.get("/ai-analysis")
def newow_ai_analysis(request: Request, product: str = Query(...),
                      as_of: datetime = Query(...), session: Session = Depends(get_db)):
    """Six page-estimate summaries; no LLM, persistence or Runtime mutation."""
    from time import monotonic
    from guiyi_quant.newow.ai_analysis import PAGE_FORMULA, FUTURES_ADAPTER, PAGE_SOURCE_SHA256
    from app.market_data.newow.ai_analysis import analyze_product
    if set(request.query_params) != {"product", "as_of"} or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise HTTPException(status_code=422, detail={"code": "NEWOW_INVALID_QUERY"})
    product = _normalize_public_product(product)
    if as_of.utcoffset() is None:
        raise HTTPException(status_code=422, detail={"code": "NEWOW_INVALID_AS_OF"})
    as_of = as_of.astimezone(UTC)
    now = getattr(request.state, "candidate_preview_as_of", None) or datetime.now(UTC)
    if as_of > now:
        raise HTTPException(status_code=422, detail={"code": "NEWOW_INVALID_AS_OF"})
    # v3 binds all six combinations to the requested completed Canonical cutoff.
    # Candidate previews retain their immutable v2 wire identity.
    deadline = monotonic() + 30
    def cancelled():
        if monotonic() >= deadline:
            return True
        try:
            return from_thread.run(request.is_disconnected)
        except RuntimeError:
            return False
    def reader_factory(frequency):
        return _build_snapshot_inputs(session, cancelled, lambda: now,
            _input_quality_policy(request, product, frequency))[0]
    try:
        with _PRODUCT_GATE.acquire(cancelled):
            combos = analyze_product(product, as_of, reader_factory, cancelled,
                                     lambda frequency: _enforce_product_frequency(request, product, frequency))
        return {"schema_version": ("newow_ai_analysis_v2" if getattr(request.state, "candidate_preview_as_of", None) is not None else "newow_ai_analysis_v3"), "product": product,
                "as_of": _json_value(as_of), "formula_version": PAGE_FORMULA,
                "futures_adapter_version": FUTURES_ADAPTER, "page_source_sha256": PAGE_SOURCE_SHA256,
                "page_kernel_parity": True, "page_parity": False, "executable": False,
                "combos": _json_value(combos)}
    except HTTPException:
        raise
    except Exception as error:
        status, detail = public_product_error(error, context={"symbol": product})
        raise HTTPException(status_code=status, detail=detail) from error


def _normalize_public_product(product: str) -> str:
    if re.fullmatch(r"[A-Za-z]{1,8}", product) is None:
        raise HTTPException(
            status_code=422, detail={"code": "NEWOW_INVALID_PRODUCT"}
        )
    return product.lower()


def _hourly_preview_products(request: Request) -> frozenset[str] | None:
    return getattr(request.state, "hourly_preview_products", None)


def _input_quality_policy(
    request: Request, product: str, frequency: ProductFrequency | str,
) -> InputQualityPolicy:
    return candidate_input_quality_policy(
        product,
        frequency,
        candidate_weekly=(
            getattr(request.state, "candidate_preview_as_of", None) is not None
        ),
    )


def _require_strategy_frequency(request: Request, strategy: str, frequency: str) -> None:
    """Keep the immutable minute candidates closed while opening formal hourly main rise."""
    if strategy != "main_rise":
        return
    preview = getattr(request.state, "intraday_preview_products", None) is not None
    if frequency in ("5m", "15m", "30m") or (frequency == "60m" and preview):
        raise ValueError("NEWOW_INVALID_QUERY" if preview else "NEWOW_FREQUENCY_NOT_OPEN")


def _enforce_product_frequency(request: Request, product: str, frequency: str) -> None:
    selected = ProductFrequency(frequency)
    intraday = getattr(request.state, "intraday_preview_products", None)
    if intraday is not None:
        if product not in (intraday & (INTRADAY_BATCH_PREVIEW_SYMBOLS | INTRADAY_SINGLE_PREVIEW_SYMBOLS)):
            raise HTTPException(status_code=403, detail={"code": "PREVIEW_PRODUCT_OUT_OF_SCOPE"})
        if selected is ProductFrequency.MINUTE:
            raise ValueError("NEWOW_FREQUENCY_NOT_OPEN")
        return
    if (getattr(request.state, "candidate_preview_as_of", None) is None
        and not getattr(request.state, "au_period_preview", False)
        and _hourly_preview_products(request) is None
        and selected in INTRADAY_HISTORY_FREQUENCIES):
        if product not in OPEN_INTRADAY_PRODUCTS:
            raise ValueError("NEWOW_FREQUENCY_NOT_OPEN")
        return
    hourly = _hourly_preview_products(request)
    if (
        hourly is not None
        and selected is ProductFrequency.HOURLY
        and product not in (hourly & HOURLY_PRODUCT_PREVIEW_SYMBOLS)
    ):
        raise HTTPException(
            status_code=403, detail={"code": "PREVIEW_PRODUCT_OUT_OF_SCOPE"}
        )
    if getattr(request.state, "au_period_preview", False):
        if selected not in AU_PERIOD_PREVIEW_FREQUENCIES:
            raise HTTPException(
                status_code=409, detail={"code": "NEWOW_FREQUENCY_NOT_OPEN"}
            )
        return
    require_open_frequency(
        selected,
        candidate=getattr(request.state, "candidate_preview_as_of", None) is not None,
        hourly_preview=hourly is not None,
    )
    if selected is ProductFrequency.WEEKLY:
        if getattr(request.state, "candidate_preview_as_of", None) is not None:
            require_candidate_weekly_product(product)
        else:
            require_open_weekly_product(product)


@router.get(
    "/product-capabilities", response_model=NewowProductCapabilitiesResponse,
    response_model_exclude_none=True,
)
def newow_product_capabilities(request: Request) -> NewowProductCapabilitiesResponse | JSONResponse:
    """Return the single public scope used by clients for this staged release."""
    if getattr(request.state, "intraday_preview_products", None) is not None:
        batch = getattr(request.state, "intraday_preview_batch", False)
        single = batch and not request.state.intraday_preview_products <= INTRADAY_BATCH_PREVIEW_SYMBOLS
        return NewowProductCapabilitiesResponse(
            schema_version=("newow_product_capabilities_v27" if single else "newow_product_capabilities_v26" if batch
                            else "newow_product_capabilities_v25"),
            release_stage=("single_product_intraday_candidate" if single else "black_steel_intraday_candidate" if batch
                           else "rb_intraday_candidate"),
            intraday_products=(sorted(request.state.intraday_preview_products)
                               if batch else None),
            open_frequencies=["5m", "15m", "30m", "60m", "1d", "1w"],
            open_sections=list(OPEN_SECTIONS), deferred_frequencies=[],
            deferred_sections=[DeferredSectionOut(section=section, reason_code=reason)
                               for section, reason in DEFERRED_SECTIONS],
        )
    candidate = getattr(request.state, "candidate_preview_as_of", None) is not None
    au_preview = candidate and getattr(request.state, "au_period_preview", False)
    hourly_products = _hourly_preview_products(request) if candidate and not au_preview else None
    hourly_preview = hourly_products is not None
    pd_pt_preview = hourly_preview and hourly_products <= PD_PT_HOURLY_PREVIEW_SYMBOLS
    frequencies = (
        AU_PERIOD_PREVIEW_FREQUENCIES if au_preview else
        HOURLY_PRODUCT_PREVIEW_FREQUENCIES if hourly_preview else
        CANDIDATE_OPEN_FREQUENCIES if candidate else (*INTRADAY_HISTORY_FREQUENCIES, ProductFrequency.DAILY, ProductFrequency.WEEKLY)
    )
    deferred = (
        () if au_preview else
        HOURLY_PRODUCT_PREVIEW_DEFERRED if hourly_preview else
        CANDIDATE_DEFERRED_FREQUENCIES if candidate else ()
    )
    capability = NewowProductCapabilitiesResponse(
        schema_version=(
            AU_PERIOD_PREVIEW_SCHEMA_VERSION if au_preview else
            PD_PT_HOURLY_PREVIEW_SCHEMA_VERSION if pd_pt_preview else
            HOURLY_PRODUCT_PREVIEW_SCHEMA_VERSION if hourly_preview else
            CANDIDATE_CAPABILITY_SCHEMA_VERSION if candidate else CAPABILITY_SCHEMA_VERSION
        ),
        release_stage=(
            AU_PERIOD_PREVIEW_STAGE if au_preview else
            PD_PT_HOURLY_PREVIEW_STAGE if pd_pt_preview else
            HOURLY_PRODUCT_PREVIEW_STAGE if hourly_preview else
            CANDIDATE_RELEASE_STAGE if candidate else RELEASE_STAGE
        ),
        open_frequencies=[item.value for item in frequencies],
        intraday_products=list(OPEN_INTRADAY_PRODUCTS) if not candidate else None,
        intraday_as_of=None,
        latest_completed_frequencies=([item.value for item in LATEST_COMPLETED_FREQUENCIES] if not candidate else None),
        strategy_frequencies=({
            "trend": [item.value for item in frequencies],
            "oscillation": [item.value for item in frequencies],
            "main_rise": [item.value for item in MAIN_RISE_FREQUENCIES],
            "dual": [item.value for item in frequencies],
        } if not candidate else None),
        weekly_products=(
            list(CANDIDATE_WEEKLY_PRODUCTS)
            if candidate and not au_preview and not hourly_preview
            else list(OPEN_WEEKLY_PRODUCTS) if not candidate else None
        ),
        deferred_frequencies=[
            DeferredFrequencyOut(frequency=frequency.value, reason_code=reason)
            for frequency, reason in deferred
        ],
        open_sections=list(OPEN_SECTIONS),
        deferred_sections=[
            DeferredSectionOut(section=section, reason_code=reason)
            for section, reason in DEFERRED_SECTIONS
        ],
    )

    # Formal v33 explicitly publishes a null historical cap; older preview
    # contracts continue omitting their absent optional fields.
    if not candidate:
        return conditional_json(request, capability.model_dump(mode="json"))
    return capability


@router.get("/trend-detail", response_model=NewowTrendDetailResponse)
def newow_trend_detail(
    product: str = Query(...),
    from_: date = Query(..., alias="from"),
    through: date = Query(...),
    frequency: Literal["1d"] = Query(default="1d"),
    series_kind: Literal["actual_dominant"] = Query(default="actual_dominant"),
    session: Session = Depends(get_db),
) -> NewowTrendDetailResponse:
    del frequency, series_kind
    product = _normalize_public_product(product)
    try:
        result = NewowTrendDetailService(
            build_market_data_service(session), taxonomy=load_product_taxonomy()
        ).query(NewowTrendDetailQuery(product, from_, through))
        return _response(result)
    except NewowTrendDetailError as exc:
        raise HTTPException(
            status_code=422 if exc.code in _CLIENT_ERRORS else 409,
            detail={"code": exc.code},
        ) from exc
    except ProductTaxonomyError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "NEWOW_DATA_UNAVAILABLE"}
        ) from exc
    except ValueError as exc:
        code = str(exc)
        if code not in _CLIENT_ERRORS:
            code = "NEWOW_DATA_UNAVAILABLE"
        raise HTTPException(status_code=422, detail={"code": code}) from exc


def _build_product_service(
    session: Session,
    cancelled: Callable[[], bool] | None = None,
    quality_policy: InputQualityPolicy = InputQualityPolicy.V1,
    *, historical_intraday: bool = False, current_reference: bool = False,
    reuse_read_inputs: bool = False,
) -> NewowProductService:
    market_data = build_market_data_service(session)
    coverage = build_database_coverage_source(session)
    active = load_active_products()

    composition = NewowComposition(
        market_data, coverage, active, quality_policy,
        context_quality_policy=lambda product, frequency: candidate_input_quality_policy(
            product, frequency, candidate_weekly=False,
        ),
    )

    mode = os.getenv("REFERENCE_TRADING_READER_MODE", "legacy")
    if mode not in {"legacy", "persisted"}:
        raise ValueError("REFERENCE_READER_MODE_INVALID")
    if mode == "persisted" or historical_intraday or current_reference:
        from app.reference_trading.persisted_newow import PersistedNewowReference
        factory = (sessionmaker(bind=engine.execution_options(
            schema_translate_map={None: INTRADAY_HISTORY_SCHEMA}), autoflush=False)
            if historical_intraday else SessionLocal)
        persisted_reference = PersistedNewowReference(factory).section
    else:
        persisted_reference = None
    return composition.service(
        cache=_INTRADAY_HISTORY_CACHE if historical_intraday else _PRODUCT_CACHE,
        heavy_gate=_PRODUCT_GATE,
        persisted_reference_gate=_PERSISTED_REFERENCE_GATE,
        inflight=_PRODUCT_INFLIGHT,
        cancelled=cancelled,
        persisted_reference=persisted_reference,
        reuse_read_inputs=reuse_read_inputs,
    )


def _build_snapshot_inputs(
    session: Session,
    cancelled: Callable[[], bool],
    now: Callable[[], datetime],
    quality_policy: InputQualityPolicy = InputQualityPolicy.V1,
    *, home_services: list[NewowProductService] | None = None,
):
    market_data = build_market_data_service(session)
    coverage = build_database_coverage_source(
        session, reuse_session_windows=home_services is not None,
    )
    if home_services is not None:
        # This MDS/coverage pair is confined to one bounded HTTP read; cached
        # windows never cross transactions or reach a maintenance writer.
        market_data.replay_coverage = coverage
    active = load_active_products()
    composition = NewowComposition(
        market_data, coverage, active, quality_policy, now=now,
    )
    reader = composition.reader(cancelled=cancelled)

    def service_factory(deadline_cancelled: Callable[[], bool]) -> NewowProductService:
        service = composition.service(
            cache=_PRODUCT_CACHE,
            heavy_gate=_PRODUCT_GATE,
            inflight=_PRODUCT_INFLIGHT,
            cancelled=deadline_cancelled,
            reuse_read_inputs=home_services is not None,
        )
        if home_services is not None:
            home_services.append(service)
        return service

    return reader, service_factory


def _build_historical_resolver(
    session: Session,
    cancelled: Callable[[], bool],
    now: Callable[[], datetime],
    quality_policy: InputQualityPolicy = InputQualityPolicy.V1,
) -> NewowHistoricalSnapshotResolver:
    reader, service_factory = _build_snapshot_inputs(
        session, cancelled, now, quality_policy
    )
    return NewowHistoricalSnapshotResolver(reader, service_factory, now=now, cancelled=cancelled)


def _build_daily_resolver(
    session: Session,
    cancelled: Callable[[], bool],
    now: Callable[[], datetime],
    quality_policy: InputQualityPolicy = InputQualityPolicy.V1,
    *, home_services: list[NewowProductService] | None = None,
) -> NewowDailySnapshotResolver:
    reader, service_factory = _build_snapshot_inputs(
        session, cancelled, now, quality_policy, home_services=home_services,
    )
    return NewowDailySnapshotResolver(reader, service_factory, now=now, cancelled=cancelled)


def _build_weekly_resolver(
    session: Session,
    cancelled: Callable[[], bool],
    now: Callable[[], datetime],
    quality_policy: InputQualityPolicy = InputQualityPolicy.V1,
    *, home_services: list[NewowProductService] | None = None,
) -> NewowWeeklySnapshotResolver:
    reader, service_factory = _build_snapshot_inputs(
        session, cancelled, now, quality_policy, home_services=home_services
    )
    status = public_after_market_status(_load_status(
        PROJECT_ROOT / ".run" / "after-market-status.json"
    ))
    return NewowWeeklySnapshotResolver(
        reader, service_factory, now=now, cancelled=cancelled,
        publication_state=lambda product, day, at: publication_state_from_status(
            status, product, day, at,
        ),
    )


@router.get("/historical-snapshot", response_model=NewowHistoricalSnapshotResponse)
def newow_historical_snapshot(
    request: Request,
    product: str = Query(...),
    strategy: Literal["trend", "oscillation", "main_rise"] = Query(...),
    frequency: Literal["1w", "1d", "60m", "1m", "5m", "15m", "30m"] = Query(...),
    session: Session = Depends(get_db),
) -> NewowHistoricalSnapshotResponse:
    unknown = set(request.query_params) - _HISTORICAL_QUERY_FIELDS
    duplicates = {
        key
        for key in request.query_params
        if len(request.query_params.getlist(key)) != 1
    }
    if unknown or duplicates:
        raise HTTPException(status_code=422, detail={"code": "NEWOW_INVALID_QUERY"})
    product = _normalize_public_product(product)

    def cancelled() -> bool:
        try:
            return from_thread.run(request.is_disconnected)
        except RuntimeError:
            return False

    now = getattr(request.state, "candidate_preview_as_of", None) or datetime.now(UTC)
    try:
        _enforce_product_frequency(request, product, frequency)
        _require_strategy_frequency(request, strategy, frequency)
        policy = _input_quality_policy(request, product, frequency)
        if (getattr(request.state, "candidate_preview_as_of", None) is None
            and ProductFrequency(frequency) in FROZEN_INTRADAY_FREQUENCIES):
            now = INTRADAY_HISTORY_AS_OF
        resolver = (
            _build_historical_resolver(session, cancelled, lambda: now)
            if policy is InputQualityPolicy.V1
            else _build_historical_resolver(session, cancelled, lambda: now, policy)
        )
        result = resolver.resolve(
            product, ProductStrategy(strategy), ProductFrequency(frequency)
        )
        return NewowHistoricalSnapshotResponse(
            product=result.product,
            strategy=result.strategy.value,
            frequency=result.frequency.value,
            trading_day=result.trading_day,
            as_of=result.as_of,
            validated_sections=list(result.validated_sections),
        )
    except (ActiveUniverseError, ProductTaxonomyError) as exc:
        raise HTTPException(
            status_code=409, detail={"code": "NEWOW_DATA_UNAVAILABLE"}
        ) from exc
    except Exception as exc:
        status, detail = public_product_error(
            exc, context={"symbol": product, "frequency": frequency}
        )
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/home-cards")
def newow_home_cards(request: Request, products: str = Query(...), session: Session = Depends(get_db)):
    """Bounded D1/W1 facts; a failed period never suppresses another product."""
    if set(request.query_params) != {'products'} or len(request.query_params.getlist('products')) != 1:
        raise HTTPException(422, detail={'code': 'NEWOW_INVALID_QUERY'})
    names = products.split(',')
    if not 1 <= len(names) <= 12 or len(set(names)) != len(names):
        raise HTTPException(422, detail={'code': 'NEWOW_INVALID_QUERY'})
    names = [_normalize_public_product(name) for name in names]
    if len(set(names)) != len(names):
        raise HTTPException(422, detail={'code': 'NEWOW_INVALID_QUERY'})
    now = getattr(request.state, 'candidate_preview_as_of', None) or datetime.now(UTC)

    def cancelled():
        try:
            return from_thread.run(request.is_disconnected)
        except RuntimeError:
            return False

    def unavailable(exc, product, frequency):
        _, detail = public_product_error(exc, context={'symbol': product, 'frequency': frequency})
        return {'status': 'unavailable', 'state': None, 'reason_code': detail.get('code', 'NEWOW_DATA_UNAVAILABLE')}

    items = []
    for product in names:
        strategies: dict[str, dict[str, dict[str, object]]] = {
            strategy: {} for strategy in ('trend', 'oscillation')
        }
        for frequency in ('1d', '1w'):
            if cancelled():
                raise HTTPException(409, detail={'code': 'NEWOW_REQUEST_CANCELLED'})
            try:
                _enforce_product_frequency(request, product, frequency)
                policy = _input_quality_policy(request, product, frequency)
                home_services: list[NewowProductService] = []
                resolver = (_build_daily_resolver if frequency == '1d' else _build_weekly_resolver)(session, cancelled, lambda: now, policy, home_services=home_services)
                snapshot = resolver.resolve(product, ProductStrategy.TREND, ProductFrequency(frequency))
                # One pinned request lifecycle; never reuse unchecked inputs
                # between HTTP requests or different authority generations.
                # The resolver already validated this exact prefix. Reuse its
                # request-local service, retaining its deadline and cancellation.
                service = home_services[-1] if home_services else _build_product_service(session, cancelled, policy, reuse_read_inputs=True)
            except Exception as exc:
                for strategy in strategies:
                    strategies[strategy][frequency] = unavailable(exc, product, frequency)
                continue
            for strategy in strategies:
                try:
                    _require_strategy_frequency(request, strategy, frequency)
                    result = service.query(ProductServiceQuery(product, ProductStrategy(strategy), ProductFrequency(frequency), as_of=snapshot.as_of))
                    summary = result.chart.value.home_summary if result.chart.value else None
                    if summary is None:
                        strategies[strategy][frequency] = {'status': 'warming', 'state': None, 'reason_code': 'NEWOW_CHART_WARMING'}
                    else:
                        strategies[strategy][frequency] = {**summary, 'display_as_of': now, 'as_of': result.meta.as_of,
                            'freshness': snapshot.freshness, 'formula_versions': result.meta.identity.formula_versions,
                            'input_sha256': result.meta.input_content_sha256, 'snapshot_token': result.meta.snapshot_token,
                            'data_revision_identity': result.meta.data_revision_identity,
                            'snapshot_context': {**cast(dict[str, object], _json_value(snapshot)), 'strategy': strategy,
                                'schema_version': 'newow_daily_snapshot_v1' if frequency == '1d' else 'newow_weekly_snapshot_v1',
                                'series_kind': 'actual_dominant'}}
                except Exception as exc:
                    strategies[strategy][frequency] = unavailable(exc, product, frequency)
        items.append({'product': product, 'strategies': strategies})
    payload = _json_value({'schema_version': 'newow_home_cards_v2', 'requested_at': now, 'items': items})
    # Keep snapshot_token in the validator: expiry/eviction must send a new
    # body, otherwise a 304 could leave lazy performance with a dead owner.
    healthy = all(period.get('status') != 'unavailable'
                  and isinstance(period.get('snapshot_token'), str)
                  and _PRODUCT_CACHE.fact_key_for_token(period['snapshot_token']) is not None
                  for item in items for strategy in item['strategies'].values()
                  for period in strategy.values())
    return conditional_json(request, payload,
        volatile=frozenset({'requested_at', 'display_as_of', 'read_at'}),
        allow_not_modified=healthy)


@router.get('/home-card-performance')
def newow_home_card_performance(
    request: Request, product: str = Query(...),
    strategy: Literal['trend', 'oscillation'] = Query(...),
    as_of: datetime = Query(...), snapshot_token: str = Query(..., min_length=1, max_length=256),
    session: Session = Depends(get_db),
):
    """Lazy ordinary page statistics bound to the displayed daily snapshot."""
    allowed = {'product', 'strategy', 'as_of', 'snapshot_token'}
    if set(request.query_params) != allowed or any(len(request.query_params.getlist(key)) != 1 for key in allowed) or as_of.tzinfo is None:
        raise HTTPException(422, detail={'code': 'NEWOW_INVALID_QUERY'})
    product = _normalize_public_product(product)

    def cancelled():
        try:
            return from_thread.run(request.is_disconnected)
        except RuntimeError:
            return False

    try:
        _enforce_product_frequency(request, product, '1d')
        _require_strategy_frequency(request, strategy, '1d')
        policy = _input_quality_policy(request, product, '1d')
        service = _build_product_service(session, cancelled, policy)
        result = service.query(ProductServiceQuery(
            product, ProductStrategy(strategy), ProductFrequency.DAILY,
            section=ProductSection.REFERENCE, as_of=as_of, snapshot_token=snapshot_token, history_limit=1,
        ))
        from app.market_data.newow.home_cards import project_home_performance
        return JSONResponse(_json_value({
            'schema_version': 'newow_home_performance_v1', 'product': product,
            'strategy': strategy, 'snapshot_token': result.meta.snapshot_token,
            'as_of': result.meta.as_of, 'performance': project_home_performance(result),
        }))
    except Exception as exc:
        status, detail = public_product_error(exc, context={'symbol': product, 'frequency': '1d'})
        raise HTTPException(status, detail=detail) from exc


@router.get("/daily-snapshot", response_model=NewowDailySnapshotResponse)
def newow_daily_snapshot(
    request: Request,
    product: str = Query(...),
    strategy: Literal["trend", "oscillation", "main_rise"] = Query(...),
    frequency: Literal["1d"] = Query("1d"),
    session: Session = Depends(get_db),
) -> NewowDailySnapshotResponse:
    if (set(request.query_params) - _HISTORICAL_QUERY_FIELDS) or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise HTTPException(status_code=422, detail={"code": "NEWOW_INVALID_QUERY"})
    product = _normalize_public_product(product)

    def cancelled() -> bool:
        try:
            return from_thread.run(request.is_disconnected)
        except RuntimeError:
            return False

    now = getattr(request.state, "candidate_preview_as_of", None) or datetime.now(UTC)
    try:
        require_open_frequency(ProductFrequency(frequency))
        policy = _input_quality_policy(request, product, frequency)
        result = _build_daily_resolver(session, cancelled, lambda: now, policy).resolve(
            product, ProductStrategy(strategy), ProductFrequency(frequency)
        )
        return NewowDailySnapshotResponse(
            product=result.product,
            strategy=result.strategy.value,
            frequency=result.frequency.value,
            requested_at=result.requested_at,
            expected_trading_day=result.expected_trading_day,
            available_trading_day=result.available_trading_day,
            as_of=result.as_of,
            freshness=result.freshness,
        )
    except (ActiveUniverseError, ProductTaxonomyError) as exc:
        raise HTTPException(status_code=409, detail={"code": "NEWOW_DATA_UNAVAILABLE"}) from exc
    except Exception as exc:
        status, detail = public_product_error(
            exc, context={"symbol": product, "frequency": frequency}
        )
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/weekly-snapshot", response_model=NewowWeeklySnapshotResponse)
def newow_weekly_snapshot(
    request: Request,
    product: str = Query(...),
    strategy: Literal["trend", "oscillation", "main_rise"] = Query(...),
    frequency: Literal["1w"] = Query("1w"),
    session: Session = Depends(get_db),
) -> NewowWeeklySnapshotResponse:
    if (set(request.query_params) - _HISTORICAL_QUERY_FIELDS) or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise HTTPException(status_code=422, detail={"code": "NEWOW_INVALID_QUERY"})
    product = _normalize_public_product(product)

    def cancelled() -> bool:
        try:
            return from_thread.run(request.is_disconnected)
        except RuntimeError:
            return False

    now = getattr(request.state, "candidate_preview_as_of", None) or datetime.now(UTC)
    try:
        _enforce_product_frequency(request, product, frequency)
        _require_strategy_frequency(request, strategy, frequency)
        policy = _input_quality_policy(request, product, frequency)
        resolver = (
            _build_weekly_resolver(session, cancelled, lambda: now)
            if policy is InputQualityPolicy.V1
            else _build_weekly_resolver(session, cancelled, lambda: now, policy)
        )
        result = resolver.resolve(
            product, ProductStrategy(strategy), ProductFrequency(frequency),
        )
        return NewowWeeklySnapshotResponse(
            product=result.product, strategy=result.strategy.value,
            frequency=result.frequency.value, requested_at=result.requested_at,
            expected_period_end=result.expected_period_end,
            available_period_end=result.available_period_end,
            as_of=result.as_of, freshness=result.freshness,
            current_context=result.current_context,
        )
    except (ActiveUniverseError, ProductTaxonomyError) as exc:
        raise HTTPException(status_code=409, detail={"code": "NEWOW_DATA_UNAVAILABLE"}) from exc
    except Exception as exc:
        status, detail = public_product_error(
            exc, context={"symbol": product, "frequency": frequency},
        )
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/strategy-detail", response_model=NewowProductResponse)
def newow_strategy_detail(
    request: Request,
    product: str = Query(...),
    strategy: Literal["trend", "oscillation", "main_rise"] = Query(...),
    frequency: Literal["1w", "1d", "60m", "1m", "5m", "15m", "30m"] = Query(...),
    series_kind: Literal["actual_dominant"] = Query("actual_dominant"),
    section: Literal[
        "chart", "auxiliary", "reference", "explanation", "comparator"
    ] = Query("chart"),
    from_: date | None = Query(None, alias="from"),
    through: date | None = Query(None),
    performance_since: date | None = Query(None),
    performance_through: date | None = Query(None),
    as_of: datetime | None = Query(None),
    chart_limit: int = Query(500, ge=1, le=2000),
    chart_before: str | None = Query(None, min_length=1, max_length=2048),
    chart_older_window: str | None = Query(None, min_length=1, max_length=256),
    component: Literal[
        "macd", "main_force_control", "up_down_energy", "trend_reversal", "zhaoyao_mirror", "cup_handle"
    ]
    | None = Query(None),
    history_limit: int = Query(50, ge=1, le=200),
    history_before: str | None = Query(None, min_length=1, max_length=2048),
    snapshot_token: str | None = Query(None, min_length=1, max_length=256),
    include_fusion: bool = Query(False),
    fusion_before: str | None = Query(None, min_length=1, max_length=2048),
    decision_v2: bool = Query(False),
    resolve_current: bool = Query(False),
    session: Session = Depends(get_db),
) -> NewowProductResponse:
    unknown = set(request.query_params) - _PRODUCT_QUERY_FIELDS
    duplicates = {
        key
        for key in request.query_params
        if len(request.query_params.getlist(key)) != 1
    }
    if (
        unknown
        or (resolve_current and (frequency not in {"1d", "1w"} or section != "chart" or as_of is not None
            or any(value is not None for value in (from_, through, performance_since, performance_through,
                chart_before, chart_older_window, component, history_before, snapshot_token, fusion_before))
            or include_fusion or decision_v2))
        or duplicates
        or (as_of is not None and as_of.utcoffset() is None)
        or (as_of is not None and as_of.astimezone(UTC) > datetime.now(UTC))
    ):
        raise HTTPException(status_code=422, detail={"code": "NEWOW_INVALID_QUERY"})
    product = _normalize_public_product(product)
    try:
        _enforce_product_frequency(request, product, frequency)
        _require_strategy_frequency(request, strategy, frequency)
        if not (decision_v2 and section == "explanation"):
            require_open_section(section)

        def cancelled() -> bool:
            try:
                return from_thread.run(request.is_disconnected)
            except RuntimeError:
                return False

        if resolve_current and frequency in {"1d", "1w"}:
            now = getattr(request.state, "candidate_preview_as_of", None) or datetime.now(UTC)
            policy = _input_quality_policy(request, product, frequency)
            resolver_factory = _build_daily_resolver if frequency == "1d" else _build_weekly_resolver
            resolver = resolver_factory(session, cancelled, lambda: now, policy, home_services=[])
            snapshot, chart = resolver.resolve_with_chart(
                product, ProductStrategy(strategy), ProductFrequency(frequency), chart_limit=chart_limit,
            )
            context = asdict(snapshot)
            context.pop("product")
            context.pop("strategy")
            context["frequency"] = snapshot.frequency.value
            response = _product_response(chart)
            return response.model_copy(update={"snapshot_context": CurrentSnapshotContextOut.model_validate(context)})

        if (getattr(request.state, "candidate_preview_as_of", None) is None
            and ProductFrequency(frequency) in FROZEN_INTRADAY_FREQUENCIES):
            as_of = released_intraday_as_of(as_of)
        product_query = ProductServiceQuery(
            product=product,
            strategy=ProductStrategy(strategy),
            frequency=ProductFrequency(frequency),
            section=ProductSection(section),
            since=from_,
            through=through,
            performance_since=performance_since,
            performance_through=performance_through,
            as_of=as_of,
            series_kind=series_kind,
            chart_limit=chart_limit,
            chart_before=chart_before,
            chart_older_window=chart_older_window,
            component=AuxiliaryComponent(component) if component is not None else None,
            history_limit=history_limit,
            history_before=history_before,
            snapshot_token=snapshot_token,
            include_fusion=include_fusion,
            fusion_before=fusion_before,
            decision_v2=decision_v2,
        )
        policy = _input_quality_policy(request, product, frequency)
        historical_intraday = (getattr(request.state, "candidate_preview_as_of", None) is None
                               and ProductFrequency(frequency) in FROZEN_INTRADAY_FREQUENCIES)
        service = (_build_product_service(session, cancelled, policy, historical_intraday=True)
                   if historical_intraday else
                   _build_product_service(session, cancelled, policy, current_reference=True) if frequency in {"5m", "15m", "30m", "60m"} else
                   _build_product_service(session, cancelled) if policy is InputQualityPolicy.V1
                   else _build_product_service(session, cancelled, policy))
        result = service.query(product_query)
        return _product_response(result)
    except (ActiveUniverseError, ProductTaxonomyError) as exc:
        raise HTTPException(
            status_code=409, detail={"code": "NEWOW_DATA_UNAVAILABLE"}
        ) from exc
    except QueryConflict as exc:
        status = 503 if exc.code in {
            "NOT_BUILT", "STALE_INVALID", "SOURCE_IDENTITY_UNVERIFIED",
            "PRESENTATION_NOT_MATERIALIZED", "PRESENTATION_BUDGET_EXCEEDED",
        } else 409
        raise HTTPException(status_code=status, detail={"code": exc.code}) from None
    except PresentationUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": str(exc)}) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail={"code": "REFERENCE_SCHEMA_UNAVAILABLE"}) from None
    except Exception as exc:
        status, detail = public_product_error(
            exc, context={"symbol": product, "frequency": frequency}
        )
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/experiments")
def newow_experiments(
    request: Request,
    product: str = Query(...),
    frequency: Literal["1w", "1d", "60m", "1m", "5m", "15m", "30m"] = Query(...),
    kind: Literal["osc-test", "osc-test2", "osc-test3", "osc-test4"] = Query(...),
    as_of: datetime | None = Query(None),
    from_: date | None = Query(None, alias="from"),
    through: date | None = Query(None),
    chart_limit: int = Query(500, ge=11, le=2000),
    all_history: bool = Query(False),
    session: Session = Depends(get_db),
):
    """Public experiments, calculated read-only from existing completed inputs."""
    from app.market_data.newow.experiments import ExperimentQuery, NewowExperimentService
    from guiyi_quant.newow.oscillation_experiments import ExperimentKind
    allowed = {"product", "frequency", "kind", "as_of", "from", "through", "chart_limit", "all_history"}
    if (set(request.query_params) - allowed
        or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params)
        or (as_of is not None and (as_of.utcoffset() is None or as_of.astimezone(UTC) > datetime.now(UTC)))):
        raise HTTPException(status_code=422, detail={"code": "NEWOW_INVALID_QUERY"})
    product = _normalize_public_product(product)
    try:
        _enforce_product_frequency(request, product, frequency)
        policy = _input_quality_policy(request, product, frequency)
        preview_as_of = getattr(request.state, "candidate_preview_as_of", None)
        if preview_as_of is not None:
            if as_of is not None and as_of > preview_as_of:
                raise ValueError("NEWOW_INVALID_AS_OF")
            as_of = as_of or preview_as_of
        if (getattr(request.state, "candidate_preview_as_of", None) is None
            and ProductFrequency(frequency) in FROZEN_INTRADAY_FREQUENCIES):
            as_of = released_intraday_as_of(as_of)
        def cancelled():
            try:
                return from_thread.run(request.is_disconnected)
            except RuntimeError:
                return False
        reader = NewowComposition(
            build_market_data_service(session), build_database_coverage_source(session),
            load_active_products(), policy,
        ).reader(cancelled=cancelled)
        with _PRODUCT_GATE.acquire(cancelled):
            result = NewowExperimentService(reader, cancelled=cancelled).query(ExperimentQuery(
                product, ProductFrequency(frequency), ExperimentKind(kind), as_of, from_, through, chart_limit, all_history,
            ))
        return result
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail={"code": "NEWOW_DATA_UNAVAILABLE"}) from None
    except Exception as exc:
        status, detail = public_product_error(exc, context={"symbol": product, "frequency": frequency})
        raise HTTPException(status_code=status, detail=detail) from exc
