"""Explicitly isolated Tick composition using the existing source and completed journals."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
import os
from pathlib import Path

from redis import Redis
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.market_data.catalog import MarketCatalog
from app.market_data.live_market import RedisLiveStore
from app.market_data.live_recovery_guard import _file_guard, after_market_recovery_guard
from app.market_data.market_archive import require_isolated_archive
from app.market_data.market_data_service import MarketDataService
from app.market_data.market_foundation_scope import bind_market_redis, bind_tick_source
from app.market_data.market_feed import DurableLiveMarketService, FeedLiveStore, MarketFeedService, StreamLiveProvider
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.observation_stream import ObservationStream
from app.market_data.operational_universe import load_operational_products
from app.market_data.storage import CanonicalMonthlyStore
from app.market_data.tick_feed import TickMarketDataProvider, TickPreviewStore
from app.market_data.tick_veighna import VeighNaTickDispatch
from app.services.newow_reference_mode import market_foundation_isolated


class _CatalogAuthority:
    def __init__(self, market_data: MarketDataService, phases: MarketPhaseResolver) -> None:
        self.market_data = market_data
        # Phase boundaries are authoritative minute boundaries. Reuse results
        # during source drain and derived publication, including a restart drain.
        self._resolve_minute = lru_cache(maxsize=1024)(phases.resolve)

    def resolve(self, symbol: str, now: datetime):
        return self._resolve_minute(symbol, now.replace(second=0, microsecond=0))

    def dominant_for_day(self, symbol: str, day: date) -> str:
        return self.market_data.dominant_segment_for_day(symbol, day).contract

    def sessions(self, symbol: str, day: date):
        return self.market_data.session_windows(symbol=symbol, trading_day=day)


@dataclass
class IsolatedTickMarket:
    preview: TickPreviewStore
    feed: MarketFeedService
    completed: DurableLiveMarketService
    session: Session
    _authority: _CatalogAuthority
    _store: RedisLiveStore
    _products: tuple[str, ...]
    _redis_url: str
    _active: bool = True
    _bound: bool = False

    def bind_day(self, day: date) -> None:
        """Bootstrap an empty isolated namespace or verify its existing day."""
        if not self._active:
            raise ValueError("TICK_RUNTIME_CLOSED")
        with readonly_transaction(self.session, timeout_seconds=15):
            owners = {symbol: self._authority.dominant_for_day(symbol, day)
                      for symbol in self._products}
            for symbol in owners:
                self._authority.sessions(symbol, day)
        stream = self.feed.source_stream
        key = stream.registration_key("live")
        if stream.redis.exists(key):
            registered = stream.registered_day("live")
            cursor = stream.cursor("live", registered)
            registered_owners = self._store.subscriptions(registered)
            if registered == day and registered_owners == owners:
                self._bound = True
                return
            if (
                registered > day or registered_owners is not None
                or cursor != stream.tail(registered)
                or not self.feed.closed_cleanup_evidence(registered, self.feed._clock())
            ):
                raise ValueError("TICK_RUNTIME_BASELINE_CONFLICT")
            completed = self.completed.completed_stream
            for consumer in ("alert", "reference"):
                if completed.redis.exists(completed.registration_key(consumer)) and (
                    completed.registered_day(consumer) != registered
                    or completed.cursor(consumer, registered) != completed.tail(registered)
                ):
                    raise ValueError("TICK_RUNTIME_BASELINE_CONFLICT")
            # Preserve the closed day's originals. The existing Feed day
            # handoff, rather than startup, creates the next authority.
            self._bound = True
            return
        if (stream.redis.exists(stream.key(day), stream.identity_key(day),
                               self.completed.completed_stream.key(day))
                or self._store.subscriptions(day) not in (None, owners)):
            raise ValueError("TICK_RUNTIME_BASELINE_CONFLICT")
        if self._store.subscriptions(day) is None:
            self._store.set_subscriptions(day, owners)
        stream.initialize("live", day, cursor="0-0")
        self._bound = True

    def poll(self, now: datetime) -> tuple[str | None, str | None]:
        if not self._active:
            raise ValueError("TICK_RUNTIME_CLOSED")
        if not self._bound:
            raise ValueError("TICK_RUNTIME_BASELINE_REQUIRED")
        with readonly_transaction(self.session, timeout_seconds=15):
            feed_result = self.feed.poll(now)
            # Committed minute facts remain drainable after a transient intake failure.
            live_result = self.completed.poll(max(now, self.feed._clock()))
        return feed_result, live_result


def _isolated_cleanup_evidence(store, sandbox: Path, products):
    def read(day, now):
        from app.market_data.market_archive import verified_retained_cleanup

        try:
            return verified_retained_cleanup(store, sandbox, day=day, products=products, now=now)
        except (OSError, ValueError, TypeError, KeyError):
            return None
    return read


@contextmanager
def open_isolated_tick_market(
    *, session: Session, database_url: URL, redis_url: str, canonical_root: Path,
    products: tuple[str, ...], client_factory: Callable,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    closed_cleanup_evidence=None,
) -> Iterator[IsolatedTickMarket]:
    if not market_foundation_isolated() or session.get_bind().url != database_url:
        raise ValueError("MARKET_FOUNDATION_ISOLATION_REQUIRED")
    sandbox = require_isolated_archive(database_url, redis_url, canonical_root)
    if len(set(products)) != len(products) or not 1 <= len(products) <= 60 or not set(products) <= set(
        load_operational_products()
    ):
        raise ValueError("TICK_RUNTIME_SCOPE_INVALID")

    redis = Redis.from_url(redis_url, socket_timeout=3, socket_connect_timeout=3, decode_responses=True)
    options = redis.connection_pool.connection_kwargs
    lock_root = Path(f"/private/tmp/guiyi-market-foundation-owners-{os.getuid()}")
    # Redis Pub/Sub channels are shared by every database on a server.
    with _file_guard(f"redis-{options['port']}.lock",
                     root=lock_root, wait=False, legacy_root=True):
        dispatch = None
        market = None
        try:
            redis.ping()
            bind_market_redis(redis, sandbox, database_url)
            bind_tick_source(redis)
            dispatch = VeighNaTickDispatch()
            preview = TickPreviewStore()
            source = ObservationStream(redis, kind="source")
            store = RedisLiveStore(redis)
            market_data = MarketDataService(MarketCatalog(session, canonical_root),
                                            CanonicalMonthlyStore(canonical_root))
            authority = _CatalogAuthority(market_data, MarketPhaseResolver(session))

            def provider() -> TickMarketDataProvider:
                client = client_factory()
                return TickMarketDataProvider(client, connection_identity=lambda: client._client,
                                              preview=preview, clock=clock, dispatch=dispatch)

            args = dict(dominant_source=authority, phase_resolver=authority, coverage_sessions=authority.sessions,
                        operational_products=products, authoritative_dominants=True, clock=clock,
                        closed_cleanup_evidence=(closed_cleanup_evidence or _isolated_cleanup_evidence(
                            store, sandbox, products,
                        )))
            feed = MarketFeedService(
                provider_factory=provider, source_stream=source, store=FeedLiveStore(redis), tick_source=True,
                shutdown_guard_factory=lambda: after_market_recovery_guard(wait=False), **args,
            )
            completed = DurableLiveMarketService(source_provider=StreamLiveProvider(source, require_tick=True), store=store, **args)
            market = IsolatedTickMarket(preview, feed, completed, session, authority, store, products, redis_url)
            yield market
        finally:
            try:
                if market is not None:
                    market._active = False
                    with readonly_transaction(session, timeout_seconds=15):
                        market.feed._discard_provider()
            finally:
                if dispatch is not None:
                    dispatch.close()
                redis.close()


def build_isolated_tick_display(
    market: IsolatedTickMarket, *, redis_url: str, canonical_root: Path,
    after_market_status_path: Path,
):
    """Compose only Market read routes around this owned Tick feed and Catalog."""
    from fastapi import FastAPI
    from redis.asyncio import Redis as AsyncRedis

    from app.api.market import router as history_router
    from app.api.market_live import MarketDisplayRuntime, router as live_router
    from app.api.reference_trading import (
        newow_after_close, newow_after_close_presentation, newow_after_close_section, summary, trades,
    )
    from app.db.session import get_db
    from app.market_data.composition import canonical_root as configured_root
    from app.market_data.market_home_live import MarketHomeLiveService
    from app.market_data.market_read_service import MarketReadService

    engine = market.session.get_bind()
    sandbox = require_isolated_archive(engine.url, redis_url, canonical_root)
    if (
        not market_foundation_isolated()
        or not market._active
        or market._redis_url != redis_url
        or configured_root() != canonical_root
        or not after_market_status_path.is_absolute()
        or after_market_status_path.resolve() != after_market_status_path
        or not after_market_status_path.is_relative_to(sandbox)
    ):
        raise ValueError("MARKET_FOUNDATION_ISOLATION_REQUIRED")

    def reader_sessions() -> Iterator[Session]:
        if not market._active or configured_root() != canonical_root:
            raise ValueError("MARKET_FOUNDATION_ISOLATION_REQUIRED")
        with Session(engine) as session, readonly_transaction(session, timeout_seconds=15):
            yield session

    open_session = contextmanager(reader_sessions)

    def historical(session):
        return MarketDataService(MarketCatalog(session, canonical_root), CanonicalMonthlyStore(canonical_root))

    @contextmanager
    def open_reader():
        with open_session() as session:
            yield MarketReadService(
                market_data=historical(session), phase_resolver=MarketPhaseResolver(session),
                operational_products=market._products, live_store=market._store,
                preview_reader=market.preview, after_market_status_path=after_market_status_path,
            )

    @contextmanager
    def open_home_reader():
        with open_session() as session:
            yield MarketHomeLiveService(
                market_data=historical(session), phase_resolver=MarketPhaseResolver(session),
                operational_products=market._products, live_store=market._store,
            )

    app = FastAPI(title="归一量化隔离 Market", docs_url=None, redoc_url=None, openapi_url=None)
    app.dependency_overrides[get_db] = reader_sessions
    def open_reference_session():
        if not market._active or configured_root() != canonical_root:
            raise ValueError("MARKET_FOUNDATION_ISOLATION_REQUIRED")
        return Session(engine)

    app.state.market_foundation_reference_sessions = open_reference_session
    app.state.market_foundation_section_root = sandbox
    app.state.market_display_runtime = MarketDisplayRuntime(
        open_reader, lambda: AsyncRedis.from_url(redis_url, socket_timeout=3), open_home_reader,
    )
    app.include_router(history_router)
    app.include_router(live_router)
    app.add_api_route("/api/v1/reference-trading/newow/after-close", newow_after_close, methods=["GET"])
    app.add_api_route("/api/v1/reference-trading/newow/after-close/presentation",
                      newow_after_close_presentation, methods=["GET"])
    app.add_api_route("/api/v1/reference-trading/newow/after-close/section",
                      newow_after_close_section, methods=["GET"])
    app.add_api_route("/api/v1/reference-trading/streams/{stream_id}/summary", summary, methods=["GET"])
    app.add_api_route("/api/v1/reference-trading/streams/{stream_id}/trades", trades, methods=["GET"])
    return app



def build_formal_tick_feed(redis, *, client_factory, dispatch, **kwargs) -> MarketFeedService:
    """Use the supervised Feed role and its existing durable publication guard."""
    from app.market_data.tick_preview_redis import RedisTickPreviewPublisher
    from app.market_data.tick_rqdata_client import create_tick_client

    if dispatch is None:
        raise ValueError("MARKET_TICK_DISPATCH_REQUIRED")
    client = None

    def assert_owned():
        check = getattr(feed, "assert_owned", None)
        if check is None:
            raise ValueError("MARKET_TICK_SUPERVISOR_REQUIRED")
        check()

    def provider():
        nonlocal client
        preview = RedisTickPreviewPublisher(redis, assert_owned=assert_owned)
        # Invalidate any previous process generation before opening this reader.
        preview.clear_activity(None)
        preview.flush()
        if client is None:
            client = client_factory()
        tick_client = create_tick_client(client)
        return TickMarketDataProvider(
            tick_client, connection_identity=lambda: tick_client._client,
            preview=preview, dispatch=dispatch, flush_preview=preview.flush,
        )

    feed = MarketFeedService(
        provider_factory=provider, source_stream=ObservationStream(redis, kind="source"),
        tick_source=True, **kwargs,
    )
    return feed


@contextmanager
def open_formal_tick_dispatch():
    dispatch = VeighNaTickDispatch()
    try:
        yield dispatch
    finally:
        dispatch.close()
