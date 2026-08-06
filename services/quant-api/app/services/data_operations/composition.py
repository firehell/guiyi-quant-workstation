"""Unique production composition root for unified data CLI / historical update.

CLI dry-run must not construct RQData clients, Canonical publishers, or live streams.
Apply paths construct writable dependencies lazily through factories.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

from sqlalchemy.orm import Session, sessionmaker

from app.data_core.aggregation import AggregationSession
from app.data_core.catalog import HistoricalCatalog
from app.data_core.contracts import DatasetKey
from app.data_core.historical_sessions import build_provider_sessions, product_sessions
from app.data_core.product_retirement import load_active_products
from app.services.data_operations.aggregate import AggregateApplicationService
from app.services.data_operations.audit_v2 import (
    AuditV2ApplicationService,
    build_catalog_audit_checkers,
)
from app.services.data_operations.contracts import (
    AuditScope,
    CliArgumentInvalid,
    MetadataSyncScope,
)
from app.services.data_operations.download import DownloadApplicationService
from app.services.data_operations.historical_update import (
    ApplyDeps,
    HistoricalUpdateAbort,
    HistoricalUpdateWorkflow,
)
from app.services.data_operations.metadata_sync import MetadataSyncApplicationService
from app.services.data_operations.metadata_sync import default_rqdata_ingest_service_map
from app.services.data_operations.m2_architecture_audit import build_m2_audit_checker
from app.services.data_operations.publisher import DerivedCanonicalPublisher
from app.services.data_operations.target_planner import (
    HistoricalUpdateTargetPlanner,
    covered_windows_from_catalog,
)
from app.services.data_operations.target_verifier import TargetWindowVerifier


DEFAULT_ACTIVE_PRODUCTS_PATH = Path("data/universe/active_products.txt")


def build_historical_update_workflow(
    *,
    session: Session,
    apply: bool = False,
    active_products_path: Path | None = None,
    apply_deps_factory: Callable[[], ApplyDeps] | None = None,
    latest_completed_day: Callable[[str], date] | None = None,
) -> HistoricalUpdateWorkflow:
    """Build workflow. Writable deps only when ``apply`` and factory provided."""
    catalog = HistoricalCatalog(session)

    def list_mappings(symbol: str, start_day: date, end_day: date) -> Sequence[object]:
        return tuple(
            item
            for item in catalog.list_main_contract_mappings(
                instrument_symbol=symbol,
                start_date=start_day,
            )
            if item.trading_day <= end_day
        )

    planner = HistoricalUpdateTargetPlanner(
        list_mappings=list_mappings,
        covered_windows=lambda probe: covered_windows_from_catalog(catalog, probe),
        list_gaps=lambda probe: catalog.list_gaps(
            _probe_to_dataset_key(probe)
        ),
        latest_completed_day=latest_completed_day,
    )
    factory = apply_deps_factory
    if apply and factory is None:
        composition = DataOperationsComposition(session=session, catalog=catalog)
        factory = composition.historical_update_apply_deps
    if not apply:
        factory = None
    del active_products_path  # reserved for callers that expand --universe active
    return HistoricalUpdateWorkflow(planner=planner, apply_deps_factory=factory)


def load_universe_products(
    *,
    symbol: str | None,
    universe: str | None,
    active_products_path: Path = DEFAULT_ACTIVE_PRODUCTS_PATH,
) -> tuple[str, ...]:
    from app.data_core.product_retirement import assert_products_active

    if (symbol is None) == (universe is None):
        raise CliArgumentInvalid(
            facts={
                "field": "selector",
                "reason": "exactly_one_of_symbol_or_universe",
            }
        )
    if symbol is not None:
        return assert_products_active((symbol,))
    if universe != "active":
        raise CliArgumentInvalid(
            facts={"field": "universe", "allowed": "active", "value": universe}
        )
    return load_active_products(active_products_path)


def build_default_audit_service(
    session: Session | None = None,
) -> AuditV2ApplicationService:
    """Use real read-only Catalog checks when a CLI database session is available."""
    if session is None:
        return AuditV2ApplicationService(checkers={})
    composition = DataOperationsComposition(session=session)
    return AuditV2ApplicationService(
        checkers={
            **build_catalog_audit_checkers(
            catalog=HistoricalCatalog(session), strict_probe=composition._market_data_readable
            ),
            AuditScope.M2: _LazyM2AuditChecker(session),
        },
    )


def build_readonly_download_service(session: Session) -> DownloadApplicationService:
    catalog = HistoricalCatalog(session)

    def factory() -> object:
        raise CliArgumentInvalid(
            facts={"reason": "download_apply_requires_injected_synchronizer"}
        )

    return DownloadApplicationService(
        synchronizer_factory=factory,  # type: ignore[arg-type]
        catalog=catalog,
    )


def build_readonly_aggregate_service(session: Session) -> AggregateApplicationService:
    catalog = HistoricalCatalog(session)

    class _UnavailableMarket:
        def get_bars(self, request: object) -> object:
            raise CliArgumentInvalid(
                facts={"reason": "aggregate_requires_injected_market_data"}
            )

    return AggregateApplicationService(
        market_data=_UnavailableMarket(),  # type: ignore[arg-type]
        session_provider=lambda *_args, **_kwargs: (),
        catalog=catalog,
        publisher=None,
    )


def build_partial_metadata_service(
    session: Session,
    *,
    services: Mapping[MetadataSyncScope, object] | None = None,
) -> MetadataSyncApplicationService:
    """Wire only Calendar / Sessions / MainContractMap when provided.

    Unwired scopes stay absent so apply fail-closes; instruments/contracts are not
    M1 production-ready prerequisites.
    """

    class _Unavailable:
        def plan(self, **kwargs: object) -> Mapping[str, object]:
            return {"dry_run": True, **kwargs}

        def apply(self, **kwargs: object) -> Mapping[str, object]:
            raise CliArgumentInvalid(
                facts={"reason": "metadata_scope_unavailable", "kwargs": sorted(kwargs)}
            )

    wired = dict(services or {})
    resolved: dict[MetadataSyncScope, object] = {}
    for scope in MetadataSyncScope:
        if scope is MetadataSyncScope.ALL:
            continue
        if scope in wired:
            resolved[scope] = wired[scope]
        else:
            # Unwired scopes stay fail-closed; update only needs calendar/sessions/map.
            resolved[scope] = _Unavailable()
    return MetadataSyncApplicationService(
        services=resolved,  # type: ignore[arg-type]
        begin_transaction=session.begin,
        commit=session.commit,
        rollback=session.rollback,
    )


def build_apply_deps(
    *,
    download: DownloadApplicationService,
    aggregate: AggregateApplicationService,
    metadata: MetadataSyncApplicationService | None = None,
    verifier: TargetWindowVerifier | None = None,
    readiness: Callable[[], Mapping[str, object]] | None = None,
) -> ApplyDeps:
    return ApplyDeps(
        download=download,
        aggregate=aggregate,
        metadata=metadata,
        verifier=verifier,
        readiness=readiness,
    )


def _probe_to_dataset_key(probe: object) -> DatasetKey:
    return DatasetKey(
        provider=getattr(probe, "provider"),
        dataset_kind=getattr(probe, "dataset_kind"),
        symbol=getattr(probe, "symbol"),
        contract_or_series=getattr(probe, "contract_or_series"),
        frequency=getattr(probe, "frequency"),
        adjustment=getattr(probe, "adjustment"),
        schema_version=getattr(probe, "schema_version"),
    )


class _LazyDerivedPublisher:
    def __init__(self, factory: Callable[[], DerivedCanonicalPublisher]) -> None:
        self._factory = factory

    def __call__(self, *args: object, **kwargs: object) -> object:
        return self._factory()(*args, **kwargs)  # type: ignore[arg-type]


class _LazyMarketData:
    def __init__(self, factory: Callable[[], object]) -> None:
        self._factory = factory

    def get_bars(self, request: object) -> object:
        return self._factory().get_bars(request)  # type: ignore[attr-defined]


class _LazyM2AuditChecker:
    """Construct filesystem reader only for the explicit M2 read-only command."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.m2_summary: Mapping[str, int] = {}

    def __call__(self, request: object) -> Sequence[object]:
        from app.data_core.contracts import BarQuery
        from app.services.canonical_market_data import build_canonical_reader
        from app.services.market_data_service import MarketDataService

        reader = build_canonical_reader(self._session)
        market_data = MarketDataService(self._session, canonical_reader=reader)

        def readable(dataset: DatasetKey, start: datetime, end: datetime) -> bool:
            result = market_data.get_bars(
                BarQuery(
                    dataset_kind=dataset.dataset_kind,
                    symbol=dataset.symbol,
                    # M2 validates rank-1 mappings independently. The reader
                    # probe stays on this concrete target so it does not
                    # rematerialize every actual contract for every boundary.
                    contract_or_series=dataset.contract_or_series,
                    frequency=dataset.frequency,
                    start=start,
                    end=end,
                )
            )
            return bool(result.bars)

        checker = build_m2_audit_checker(
            catalog=HistoricalCatalog(self._session),
            verify_partition=reader.verify_partition,
            market_data_readable=readable,
        )
        findings = checker(request)  # type: ignore[arg-type]
        self.m2_summary = dict(getattr(checker, "m2_summary", {}))
        return findings


class DataOperationsComposition:
    """Production composition root; writable dependencies stay lazy until apply."""

    def __init__(
        self,
        *,
        session: Session,
        catalog: HistoricalCatalog | None = None,
        market_data: object | None = None,
        session_provider: Callable[
            [DatasetKey, datetime, datetime], Sequence[AggregationSession]
        ] | None = None,
        rqdata_client_factory: Callable[[], object] | None = None,
        bar_adapter_factory: Callable[[], object] | None = None,
        canonical_store_factory: Callable[[], object] | None = None,
        canonical_root: Path | None = None,
    ) -> None:
        self._session = session
        self._catalog = catalog or HistoricalCatalog(session)
        self._market_data = market_data or _LazyMarketData(self._build_market_data)
        self._session_provider = session_provider or self._default_aggregation_sessions
        self._rqdata_client_factory = rqdata_client_factory or self._build_rqdata_client
        self._bar_adapter_factory = bar_adapter_factory or self._build_bar_adapter
        self._canonical_store_factory = canonical_store_factory or self._build_store
        self._canonical_root = canonical_root

    def download_service(self) -> DownloadApplicationService:
        return DownloadApplicationService(
            synchronizer_factory=self._build_historical_synchronizer,
            catalog=self._catalog,
            commit_target=self._session.commit,
            rollback_target=self._session.rollback,
        )

    def aggregate_service(self) -> AggregateApplicationService:
        return AggregateApplicationService(
            market_data=self._market_data,  # type: ignore[arg-type]
            session_provider=self._session_provider,
            catalog=self._catalog,
            publisher=_LazyDerivedPublisher(
                lambda: DerivedCanonicalPublisher(self._canonical_store_factory())  # type: ignore[arg-type]
            ),
        )

    def metadata_service(self) -> MetadataSyncApplicationService:
        from app.core.env import PROJECT_ROOT
        from app.services.rqdata_ingest.ingestors import (
            CatalogIngestor,
            ContractUniverseIngestor,
            MainMappingIngestor,
        )

        def catalog_factory() -> object:
            return CatalogIngestor(self._session, self._rqdata_client_factory(), PROJECT_ROOT)

        def contracts_factory() -> object:
            return ContractUniverseIngestor(self._session, self._rqdata_client_factory(), PROJECT_ROOT)

        def mapping_factory() -> object:
            return MainMappingIngestor(self._session, self._rqdata_client_factory(), PROJECT_ROOT)

        return MetadataSyncApplicationService(
            services=default_rqdata_ingest_service_map(
                catalog_ingestor_factory=catalog_factory,
                contract_ingestor_factory=contracts_factory,
                main_mapping_ingestor_factory=mapping_factory,
                start=None,
                end=None,
            ),
            begin_transaction=self._session.begin,
            commit=self._session.commit,
            rollback=self._session.rollback,
        )

    def historical_update_apply_deps(self) -> ApplyDeps:
        return build_apply_deps(
            download=self.download_service(),
            aggregate=self.aggregate_service(),
            metadata=self.metadata_service(),
            verifier=TargetWindowVerifier(
                catalog=self._catalog,
                market_data_readable=self._market_data_readable,
            ),
            readiness=self._readiness,
        )

    def _build_historical_synchronizer(self) -> object:
        from app.data_core.historical_sync import CanonicalBatchPublisher, HistoricalSynchronizer

        return HistoricalSynchronizer(
            catalog=self._catalog,
            adapter=self._bar_adapter_factory(),  # type: ignore[arg-type]
            session_provider=self._provider_sessions,
            publish_batch=CanonicalBatchPublisher(self._canonical_store_factory()),  # type: ignore[arg-type]
        )

    def _build_rqdata_client(self) -> object:
        from app.services.rqdata_ingest.client import RqDataClient

        return RqDataClient(load_env_file=True)

    def _build_bar_adapter(self) -> object:
        from app.data_core.rqdata_provider import CanonicalRQDataAdapter

        return CanonicalRQDataAdapter(self._rqdata_client_factory())  # type: ignore[arg-type]

    def _build_store(self) -> object:
        from app.data_core.canonical_store import CanonicalStore

        root = self._resolve_canonical_root()
        return CanonicalStore(
            staging_root=root.parent / "staging",
            canonical_root=root,
            metadata_session_factory=sessionmaker(
                bind=self._session.get_bind(), expire_on_commit=False
            ),
        )

    def _build_market_data(self) -> object:
        from app.services.canonical_market_data import build_canonical_reader
        from app.services.market_data_service import MarketDataService

        return MarketDataService(
            self._session,
            canonical_reader=build_canonical_reader(self._session),
        )

    def _market_data_readable(self, target: object) -> bool:
        from app.data_core.contracts import BarQuery

        result = self._market_data.get_bars(
            BarQuery(
                dataset_kind=getattr(target, "dataset_kind"),
                symbol=getattr(target, "symbol"),
                contract_or_series=getattr(target, "contract_or_series"),
                frequency=getattr(target, "frequency"),
                start=getattr(target, "start"),
                end=getattr(target, "end"),
            )
        )
        return bool(getattr(result, "bars", ()))

    def _readiness(self) -> Mapping[str, object]:
        if self._session.get_bind() is None:
            raise HistoricalUpdateAbort("HISTORICAL_UPDATE_DATABASE_UNAVAILABLE")
        return {"database": "available"}

    def _resolve_canonical_root(self) -> Path:
        if self._canonical_root is not None:
            return self._canonical_root
        from app.services.canonical_market_data import configured_canonical_root

        return configured_canonical_root()

    def _default_aggregation_sessions(
        self, dataset: DatasetKey, start: datetime, end: datetime
    ) -> Sequence[AggregationSession]:
        return product_sessions(self._session, symbol=dataset.symbol, start=start, end=end)

    def _provider_sessions(
        self, dataset: DatasetKey, start: datetime, end: datetime
    ) -> Sequence[object]:
        return build_provider_sessions(
            dataset,
            start=start,
            end=end,
            sessions=self._default_aggregation_sessions(dataset, start, end),
        )
