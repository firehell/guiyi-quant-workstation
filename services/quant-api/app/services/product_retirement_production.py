"""Production composition for the fixed 21-product retirement workflow."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.data_core.aggregation import AggregationSession, aggregate_bars
from app.data_core.canonical_store import (
    CANONICAL_MANIFEST_FORMAT_V2,
    CanonicalStore,
    PublishExpectation,
)
from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import (
    BarFrequency,
    BarQuery,
    DatasetKind,
    DatasetKey,
    DatasetOrigin,
    ManifestLineage,
)
from app.data_core.historical_reader import CanonicalHistoricalReader
from app.data_core.historical_sessions import build_provider_sessions
from app.data_core.historical_sync import (
    CanonicalBatchPublisher,
    HistoricalSynchronizer,
    plan_missing_windows,
)
from app.data_core.product_retirement import load_active_products
from app.data_core.rqdata_adapter import ProviderBarBatch, ProviderBarRequest
from app.data_core.rqdata_provider import CanonicalRQDataAdapter
from app.models.data_center import Instrument, TradingCalendar, TradingSession
from app.services.product_retirement_data_operator import ProductRetirementDataOperator
from app.services.product_retirement_refresh import (
    DIRECT_FREQUENCIES,
    RefreshTarget,
    RefreshWindow,
    RetainedUniverseRefreshExecutor,
)
from app.services.product_retirement_runtime_gate import (
    BoundProductRetirementCommandExecutor,
    REQUIRED_WRITER_SERVICES,
    RetirementRuntimeRequest,
)
from app.services.product_retirement_runtime_operator import LaunchdRuntimeOperator
from app.services.rqdata_ingest.client import RqDataClient
from app.services.trading_session_clock import SHANGHAI, TradingSessionClock


EXPECTED_DATABASE_REVISION = "20260803_0032"
MIN_FREE_BYTES = 1024 * 1024 * 1024
CALENDAR_LOOKBACK_DAYS = 45


class ProductRetirementProductionError(ValueError):
    """Fail-closed production binding or refresh failure."""


def select_refresh_days(
    *,
    trading_days: Sequence[date],
    latest_completed: date,
    today: date,
) -> tuple[tuple[date, ...], date]:
    """Select the exact ten-day mapping window and last non-partial week."""

    eligible = tuple(
        sorted({item for item in trading_days if item <= latest_completed})
    )
    if len(eligible) < 10:
        raise ProductRetirementProductionError(
            "PRODUCT_RETIREMENT_REFRESH_TRADING_DAYS_MISSING"
        )
    selected = eligible[-10:]
    current_week = today.isocalendar()[:2]
    weekly = tuple(item for item in eligible if item.isocalendar()[:2] < current_week)
    if not weekly:
        raise ProductRetirementProductionError(
            "PRODUCT_RETIREMENT_REFRESH_COMPLETE_WEEK_MISSING"
        )
    return selected, weekly[-1]


def calendar_refresh_bounds(
    *, provider_days: Sequence[date], today: date
) -> tuple[date, date]:
    normalized = tuple(sorted(set(provider_days)))
    if not normalized or normalized[-1] > today:
        raise ProductRetirementProductionError(
            "PRODUCT_RETIREMENT_RQDATA_CALENDAR_INVALID"
        )
    return normalized[0], today


class ProductionRetainedUniverseRefresher:
    """Refresh only retained products through the canonical V2 data path."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        rqdata_client: RqDataClient,
        canonical_root: Path,
        staging_root: Path,
        database_revision: str,
        now: Callable[[], datetime] | None = None,
        min_free_bytes: int = MIN_FREE_BYTES,
    ) -> None:
        self._session_factory = session_factory
        self._client = rqdata_client
        self._adapter = CanonicalRQDataAdapter(rqdata_client)
        self._canonical_root = canonical_root
        self._staging_root = staging_root
        self._database_revision = database_revision
        self._now = now or (lambda: datetime.now(UTC))
        self._min_free_bytes = min_free_bytes
        self._products: tuple[str, ...] = ()
        self._exchanges: dict[str, str] = {}
        self._provider_days: tuple[date, ...] = ()
        self._period_rows: dict[str, tuple[Mapping[str, Any], ...]] = {}
        self._sessions: dict[str, tuple[AggregationSession, ...]] = {}
        self._windows: dict[str, RefreshWindow] = {}
        self._weekly_ends: dict[str, datetime] = {}
        self._executor: RetainedUniverseRefreshExecutor | None = None
        self._store: CanonicalStore | None = None

    def preflight(self, request: RetirementRuntimeRequest) -> Mapping[str, Any]:
        products = load_active_products(request.active_products_path)
        if request.roots["canonical"].resolve(
            strict=True
        ) != self._canonical_root.resolve(strict=True):
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_CANONICAL_ROOT_MISMATCH"
            )
        if self._staging_root.exists() and (
            self._staging_root.is_symlink() or not self._staging_root.is_dir()
        ):
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_STAGING_ROOT_INVALID"
            )
        if shutil.disk_usage(self._canonical_root).free < self._min_free_bytes:
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_CANONICAL_DISK_SPACE_LOW"
            )
        with self._session_factory() as session:
            revision = session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if revision != self._database_revision:
                raise ProductRetirementProductionError(
                    "PRODUCT_RETIREMENT_DATABASE_REVISION_MISMATCH"
                )
            exchanges = _load_product_exchanges(session, products)
            _require_trading_sessions(session, exchanges)
        current = self._now().astimezone(SHANGHAI)
        provider_days = tuple(
            sorted(
                set(
                    self._client.trading_dates(
                        current.date() - timedelta(days=CALENDAR_LOOKBACK_DAYS),
                        current.date(),
                    )
                )
            )
        )
        if len(provider_days) < 10 or provider_days[-1] < current.date() - timedelta(
            days=7
        ):
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_RQDATA_CALENDAR_STALE"
            )
        readiness_day = provider_days[-1]
        if readiness_day == current.date() and current.time() < time(16, 0):
            readiness_day = provider_days[-2]
        readiness_categories = ("future_minbar", "future_daybar")
        readiness = self._client.market_data_readiness(
            expected_date=readiness_day,
            categories=readiness_categories,
        )
        for category in readiness_categories:
            row = readiness.get(category)
            if not isinstance(row, Mapping) or not bool(row.get("ready")):
                raise ProductRetirementProductionError(
                    f"PRODUCT_RETIREMENT_RQDATA_NOT_READY:{category}"
                )
            latest = date.fromisoformat(str(row.get("latest_date")))
            if latest < readiness_day:
                raise ProductRetirementProductionError(
                    f"PRODUCT_RETIREMENT_RQDATA_NOT_READY:{category}"
                )
        contracts = tuple(f"{product.upper()}88" for product in products)
        period_frame = self._client.contract_trading_periods(
            contracts,
            start_date=provider_days[0],
            end_date=provider_days[-1],
        )
        period_rows: dict[str, list[Mapping[str, Any]]] = {
            product: [] for product in products
        }
        contract_to_product = dict(zip(contracts, products, strict=True))
        for row in period_frame.to_dict("records"):
            product = contract_to_product.get(str(row.get("order_book_id", "")).upper())
            if product is None:
                raise ProductRetirementProductionError(
                    "PRODUCT_RETIREMENT_RQDATA_SESSION_OUTSIDE_SCOPE"
                )
            period_rows[product].append(dict(row))
        if any(not rows for rows in period_rows.values()):
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_RQDATA_SESSION_MISSING"
            )
        self._products = products
        self._exchanges = exchanges
        self._provider_days = provider_days
        self._period_rows = {
            product: tuple(rows) for product, rows in period_rows.items()
        }
        return {
            "status": "passed",
            "active_product_count": len(products),
            "exchange_count": len(set(exchanges.values())),
            "database_revision": revision,
            "provider_latest_trading_day": provider_days[-1].isoformat(),
            "provider_readiness_day": readiness_day.isoformat(),
            "provider_session_product_count": len(self._period_rows),
            "calls_rqdata": True,
            "writes_postgresql": False,
            "writes_canonical": False,
        }

    def sync_direct(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> Mapping[str, Any]:
        if frequencies != DIRECT_FREQUENCIES or products != self._products:
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_REFRESH_PREFLIGHT_SCOPE_MISMATCH"
            )
        self._refresh_calendar()
        self._build_refresh_windows()
        executor = RetainedUniverseRefreshExecutor(
            mapping_window=lambda symbol: self._windows.get(symbol),
            mapping_adapter=self._adapter,
            replace_mapping=self._replace_mapping,
            list_mappings=self._list_mappings,
            sync_direct_target=self._sync_direct_target,
            aggregate_target=self._aggregate_target,
        )
        receipt = dict(executor.sync_direct(products, frequencies))
        self._executor = executor
        return {
            **receipt,
            "calendar_start": min(self._provider_days).isoformat(),
            "calendar_end": self._now().astimezone(SHANGHAI).date().isoformat(),
            "mapping_overlap_trading_days": 10,
            "missing_only": True,
        }

    def aggregate(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> Mapping[str, Any]:
        if self._executor is None:
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_REFRESH_DIRECT_PHASE_REQUIRED"
            )
        receipt = dict(self._executor.aggregate(products, frequencies))
        return {**receipt, "missing_only": True, "calls_rqdata": False}

    def _refresh_calendar(self) -> None:
        start_day, end_day = calendar_refresh_bounds(
            provider_days=self._provider_days,
            today=self._now().astimezone(SHANGHAI).date(),
        )
        provider_days = set(self._provider_days)
        with self._session_factory() as session, session.begin():
            exchanges = tuple(sorted(set(self._exchanges.values())))
            night_by_exchange = {
                exchange: bool(
                    session.scalar(
                        select(TradingSession.id)
                        .where(
                            TradingSession.exchange_code.in_((exchange, "CNFE")),
                            TradingSession.is_active.is_(True),
                            or_(
                                TradingSession.crosses_midnight.is_(True),
                                TradingSession.start_time >= time(20, 0),
                            ),
                        )
                        .limit(1)
                    )
                )
                for exchange in exchanges
            }
            for exchange in exchanges:
                existing = {
                    row.trade_date: row
                    for row in session.scalars(
                        select(TradingCalendar).where(
                            TradingCalendar.exchange_code == exchange,
                            TradingCalendar.trade_date >= start_day,
                            TradingCalendar.trade_date <= end_day,
                        )
                    )
                }
                current = start_day
                while current <= end_day:
                    row = existing.get(current)
                    values = {
                        "is_trading_day": current in provider_days,
                        "has_night_session": night_by_exchange[exchange],
                        "provider": "rqdata",
                        "remark": "product retirement retained-universe refresh",
                    }
                    if row is None:
                        session.add(
                            TradingCalendar(
                                exchange_code=exchange,
                                trade_date=current,
                                **values,
                            )
                        )
                    else:
                        for key, value in values.items():
                            setattr(row, key, value)
                    current += timedelta(days=1)

    def _build_refresh_windows(self) -> None:
        current = self._now().astimezone(SHANGHAI)
        windows: dict[str, RefreshWindow] = {}
        weekly_ends: dict[str, datetime] = {}
        sessions_by_product: dict[str, tuple[AggregationSession, ...]] = {}
        with self._session_factory() as session:
            clock = TradingSessionClock(session)
            for symbol in self._products:
                exchange = self._exchanges[symbol]
                latest = clock.latest_completed_trading_day(
                    product=symbol,
                    exchange=exchange,
                    now=current,
                )
                trading_days = tuple(
                    session.scalars(
                        select(TradingCalendar.trade_date)
                        .where(
                            TradingCalendar.exchange_code == exchange,
                            TradingCalendar.is_trading_day.is_(True),
                            TradingCalendar.trade_date <= latest,
                        )
                        .order_by(TradingCalendar.trade_date)
                    )
                )
                selected, weekly_day = select_refresh_days(
                    trading_days=trading_days,
                    latest_completed=latest,
                    today=current.date(),
                )
                sessions = build_rqdata_aggregation_sessions(
                    product=symbol,
                    rows=self._period_rows.get(symbol, ()),
                    trading_days=selected,
                    provider_days=self._provider_days,
                )
                if not sessions or {item.trading_day for item in sessions} != set(
                    selected
                ):
                    raise ProductRetirementProductionError(
                        "PRODUCT_RETIREMENT_REFRESH_SESSION_COVERAGE_MISSING"
                    )
                start = min(item.start for item in sessions)
                end = max(item.end for item in sessions)
                weekly_sessions = tuple(
                    item for item in sessions if item.trading_day <= weekly_day
                )
                if not weekly_sessions:
                    raise ProductRetirementProductionError(
                        "PRODUCT_RETIREMENT_REFRESH_COMPLETE_WEEK_MISSING"
                    )
                windows[symbol] = RefreshWindow(
                    start_day=selected[0],
                    end_day=selected[-1],
                    start=start,
                    end=end,
                )
                weekly_ends[symbol] = max(item.end for item in weekly_sessions)
                sessions_by_product[symbol] = sessions
        self._windows = windows
        self._weekly_ends = weekly_ends
        self._sessions = sessions_by_product

    def _replace_mapping(
        self,
        symbol: str,
        start_day: date,
        end_day: date,
        rows: Sequence[Any],
    ) -> object:
        expected = tuple(
            item for item in self._provider_days if start_day <= item <= end_day
        )
        received = tuple(sorted(row.trading_day for row in rows))
        if received != expected:
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_REFRESH_MAPPING_COVERAGE_MISMATCH"
            )
        with self._session_factory() as session, session.begin():
            return HistoricalCatalog(session).replace_rank1_mapping_window(
                symbol=symbol,
                start_day=start_day,
                end_day=end_day,
                rows=rows,
            )

    def _list_mappings(
        self, symbol: str, start_day: date, end_day: date
    ) -> Sequence[Any]:
        with self._session_factory() as session:
            return tuple(
                item
                for item in HistoricalCatalog(session).list_main_contract_mappings(
                    instrument_symbol=symbol,
                    start_date=start_day,
                )
                if item.trading_day <= end_day
            )

    def _sync_direct_target(self, target: RefreshTarget) -> None:
        bounded = (
            replace(target, end=self._weekly_ends[target.symbol])
            if target.frequency == "1w"
            else target
        )
        dataset = _dataset_for_target(bounded)
        with self._session_factory() as session:
            catalog = HistoricalCatalog(session)
            store = self._canonical_store()

            def sessions(
                key: DatasetKey, start: datetime, end: datetime
            ) -> Sequence[Any]:
                values = _target_sessions(
                    catalog,
                    key,
                    start,
                    end,
                    sessions=self._sessions[key.symbol],
                )
                return build_provider_sessions(
                    key,
                    start=start,
                    end=end,
                    sessions=values,
                )

            synchronizer = HistoricalSynchronizer(
                catalog=catalog,
                adapter=self._adapter,
                session_provider=sessions,
                publish_batch=CanonicalBatchPublisher(store),
            )
            result = synchronizer.sync(
                dataset=dataset,
                start=bounded.start,
                end=bounded.end,
            )
            session.commit()
            if result.gap_windows:
                raise ProductRetirementProductionError(
                    "PRODUCT_RETIREMENT_DIRECT_REFRESH_GAP"
                )
            session.expire_all()
            _require_window_covered(catalog, dataset, bounded.start, bounded.end)

    def _aggregate_target(self, target: RefreshTarget) -> None:
        dataset = _dataset_for_target(target)
        source_key = replace(dataset, frequency=BarFrequency.M1)
        with self._session_factory() as session:
            catalog = HistoricalCatalog(session)
            store = self._canonical_store()
            missing = plan_missing_windows(
                dataset=dataset,
                start=target.start,
                end=target.end,
                covered_windows=tuple(
                    (item.coverage_start, item.coverage_end)
                    for item in catalog.list_effective_partitions(dataset)
                ),
            )
            for start, end in missing:
                sessions = _target_sessions(
                    catalog,
                    source_key,
                    start,
                    end,
                    sessions=self._sessions[source_key.symbol],
                )
                reader = CanonicalHistoricalReader(
                    catalog=catalog,
                    canonical_root=self._canonical_root,
                    session_provider=lambda _symbol, window_start, window_end: (
                        _target_sessions(
                            catalog,
                            source_key,
                            window_start,
                            window_end,
                            sessions=self._sessions[source_key.symbol],
                        )
                    ),
                )
                source = reader.get_bars(
                    BarQuery(
                        dataset_kind=source_key.dataset_kind,
                        symbol=source_key.symbol,
                        contract_or_series=source_key.contract_or_series,
                        frequency=BarFrequency.M1,
                        start=start,
                        end=end,
                    )
                )
                bars = aggregate_bars(
                    source.bars,
                    target_frequency=dataset.frequency,
                    sessions=sessions,
                    requested_window=(start, end),
                )
                provider_sessions = build_provider_sessions(
                    dataset,
                    start=start,
                    end=end,
                    sessions=sessions,
                )
                request = ProviderBarRequest(
                    dataset=dataset,
                    start=start,
                    end=end,
                    sessions=provider_sessions,
                )
                source_digest = _json_digest(
                    {
                        "manifest_digests": list(source.manifest_digests),
                        "source_data_versions": list(source.source_data_versions),
                    }
                )
                quality_digest = _json_digest(
                    {
                        "source_digest": source_digest,
                        "window": [start.isoformat(), end.isoformat()],
                    }
                )
                lineage = ManifestLineage(
                    origin=DatasetOrigin.PREAGGREGATED_FROM_1M,
                    source_frequency=BarFrequency.M1,
                    legacy_source_checksum=source_digest,
                    quality_evidence_digest=quality_digest,
                )
                batch = ProviderBarBatch(
                    request=request,
                    bars=bars,
                    data_version=f"retirement-refresh-{quality_digest[:16]}",
                )
                staged = store.stage(batch)
                source_batch = staged.source
                store.publish(
                    staged,
                    PublishExpectation(
                        dataset=source_batch.dataset,
                        coverage_start=source_batch.coverage_start,
                        coverage_end=source_batch.coverage_end,
                        row_count=source_batch.row_count,
                        data_version=source_batch.data_version,
                        manifest_version="canonical-manifest-v2",
                        manifest_format=CANONICAL_MANIFEST_FORMAT_V2,
                        file_checksum=staged.file_checksum,
                        canonical_logical_fingerprint=(
                            staged.canonical_logical_fingerprint
                        ),
                        lineage=lineage,
                    ),
                )
            session.expire_all()
            _require_window_covered(catalog, dataset, target.start, target.end)

    def _canonical_store(self) -> CanonicalStore:
        if self._store is None:
            self._store = CanonicalStore(
                staging_root=self._staging_root,
                canonical_root=self._canonical_root,
                metadata_session_factory=self._session_factory,
            )
        return self._store


def build_product_retirement_executor(
    request: RetirementRuntimeRequest,
) -> BoundProductRetirementCommandExecutor:
    """Bind the only production Runtime/data adapters for this command."""

    from app.db.session import SessionLocal, engine

    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    if revision != EXPECTED_DATABASE_REVISION:
        raise ProductRetirementProductionError(
            "PRODUCT_RETIREMENT_DATABASE_REVISION_MISMATCH"
        )
    canonical_root = request.roots["canonical"].resolve(strict=True)
    staging_root = canonical_root.parent / "staging"
    rqdata_client = RqDataClient(load_env_file=True)
    refresher = ProductionRetainedUniverseRefresher(
        session_factory=SessionLocal,
        rqdata_client=rqdata_client,
        canonical_root=canonical_root,
        staging_root=staging_root,
        database_revision=revision,
    )
    data_operator = ProductRetirementDataOperator(
        connection_factory=engine.connect,
        roots=request.roots,
        protected_root=request.protected_root,
        database_revision=revision,
        refresher=refresher,
    )
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    runtime_operator = LaunchdRuntimeOperator(
        service_plists={
            label: launch_agents / f"{label}.plist"
            for label in REQUIRED_WRITER_SERVICES
        }
    )
    return BoundProductRetirementCommandExecutor(
        inventory=lambda _request, runtime_sha: data_operator.inventory(
            runtime_sha=runtime_sha
        ),
        runtime_operator=runtime_operator,
        data_operator=data_operator,
    )


def _load_product_exchanges(
    session: Session, products: tuple[str, ...]
) -> dict[str, str]:
    rows = session.execute(
        select(Instrument.symbol, Instrument.exchange_code).where(
            func.lower(Instrument.symbol).in_(products),
            Instrument.is_active.is_(True),
        )
    ).all()
    result: dict[str, str] = {}
    for symbol, exchange in rows:
        normalized = str(symbol).strip().lower()
        value = str(exchange).strip().upper()
        if normalized in result and result[normalized] != value:
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_PRODUCT_EXCHANGE_AMBIGUOUS"
            )
        result[normalized] = value
    if set(result) != set(products):
        raise ProductRetirementProductionError(
            "PRODUCT_RETIREMENT_PRODUCT_EXCHANGE_MISSING"
        )
    return result


def _require_trading_sessions(session: Session, exchanges: Mapping[str, str]) -> None:
    for product, exchange in exchanges.items():
        found = session.scalar(
            select(TradingSession.id)
            .where(
                TradingSession.exchange_code.in_((exchange, "CNFE")),
                TradingSession.is_active.is_(True),
                or_(
                    func.lower(TradingSession.instrument_symbol) == product,
                    TradingSession.instrument_symbol.is_(None),
                ),
            )
            .limit(1)
        )
        if found is None:
            raise ProductRetirementProductionError(
                f"PRODUCT_RETIREMENT_TRADING_SESSION_MISSING:{product}"
            )


def _dataset_for_target(target: RefreshTarget) -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind(target.dataset_kind),
        symbol=target.symbol,
        contract_or_series=target.contract_or_series,
        frequency=BarFrequency(target.frequency),
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def _target_sessions(
    catalog: HistoricalCatalog,
    dataset: DatasetKey,
    start: datetime,
    end: datetime,
    *,
    sessions: Sequence[AggregationSession],
) -> tuple[Any, ...]:
    selected = tuple(item for item in sessions if item.start < end and start < item.end)
    if dataset.dataset_kind is DatasetKind.ACTUAL_DOMINANT:
        selected = tuple(
            item
            for item in selected
            if catalog.get_main_contract_mapping(
                instrument_symbol=dataset.symbol,
                trade_date=item.trading_day,
            ).actual_contract
            == dataset.contract_or_series
        )
    if not selected:
        raise ProductRetirementProductionError(
            "PRODUCT_RETIREMENT_TARGET_SESSION_MISSING"
        )
    return selected


def build_rqdata_aggregation_sessions(
    *,
    product: str,
    rows: Sequence[Mapping[str, Any]],
    trading_days: Sequence[date],
    provider_days: Sequence[date],
) -> tuple[AggregationSession, ...]:
    requested = tuple(sorted(set(trading_days)))
    available = tuple(sorted(set(provider_days)))
    if not product.strip() or not requested or not available:
        raise ProductRetirementProductionError(
            "PRODUCT_RETIREMENT_RQDATA_SESSION_SCOPE_INVALID"
        )
    hours_by_day: dict[date, str] = {}
    for row in rows:
        raw_day = row.get("date")
        trading_day = (
            raw_day.date()
            if isinstance(raw_day, datetime)
            else raw_day
            if isinstance(raw_day, date)
            else date.fromisoformat(str(raw_day))
        )
        hours = str(row.get("trading_hours", "")).strip()
        existing = hours_by_day.get(trading_day)
        if existing is not None and existing != hours:
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_RQDATA_SESSION_CONFLICT"
            )
        hours_by_day[trading_day] = hours
    if set(hours_by_day).intersection(requested) != set(requested):
        raise ProductRetirementProductionError(
            "PRODUCT_RETIREMENT_RQDATA_SESSION_COVERAGE_MISSING"
        )
    result: list[AggregationSession] = []
    for trading_day in requested:
        prior = tuple(item for item in available if item < trading_day)
        if not prior:
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_RQDATA_SESSION_PREVIOUS_DAY_MISSING"
            )
        previous_day = prior[-1]
        periods = tuple(
            item.strip()
            for item in hours_by_day[trading_day].split(",")
            if item.strip()
        )
        if not periods:
            raise ProductRetirementProductionError(
                "PRODUCT_RETIREMENT_RQDATA_SESSION_EMPTY"
            )
        for index, period in enumerate(periods, start=1):
            try:
                raw_start, raw_end = period.split("-", maxsplit=1)
                first_bar = time.fromisoformat(raw_start)
                last_bar = time.fromisoformat(raw_end)
            except ValueError as exc:
                raise ProductRetirementProductionError(
                    "PRODUCT_RETIREMENT_RQDATA_SESSION_FORMAT_INVALID"
                ) from exc
            anchor = previous_day if first_bar >= time(20) else trading_day
            first_end = datetime.combine(anchor, first_bar, tzinfo=SHANGHAI)
            session_start = first_end - timedelta(minutes=1)
            session_end = datetime.combine(anchor, last_bar, tzinfo=SHANGHAI)
            if last_bar < first_bar:
                session_end += timedelta(days=1)
            result.append(
                AggregationSession(
                    trading_day=trading_day,
                    name=f"rqdata_{index:02d}",
                    start=session_start.astimezone(UTC),
                    end=session_end.astimezone(UTC),
                )
            )
    return tuple(sorted(result, key=lambda item: (item.start, item.end)))


def _require_window_covered(
    catalog: HistoricalCatalog,
    dataset: DatasetKey,
    start: datetime,
    end: datetime,
) -> None:
    missing = plan_missing_windows(
        dataset=dataset,
        start=start,
        end=end,
        covered_windows=tuple(
            (item.coverage_start, item.coverage_end)
            for item in catalog.list_effective_partitions(dataset)
        ),
    )
    if missing:
        raise ProductRetirementProductionError(
            "PRODUCT_RETIREMENT_REFRESH_COVERAGE_MISSING"
        )


def _json_digest(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "ProductRetirementProductionError",
    "ProductionRetainedUniverseRefresher",
    "build_product_retirement_executor",
    "build_rqdata_aggregation_sessions",
    "calendar_refresh_bounds",
    "select_refresh_days",
]
