"""Unique production composition root for unified data CLI / historical update.

CLI dry-run must not construct RQData clients, Canonical publishers, or live streams.
Apply paths construct writable dependencies lazily through factories.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Sequence

from sqlalchemy.orm import Session

from app.data_core.catalog import HistoricalCatalog
from app.data_core.product_retirement import load_active_products
from app.services.data_operations.aggregate import AggregateApplicationService
from app.services.data_operations.audit_v2 import AuditV2ApplicationService
from app.services.data_operations.contracts import (
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
        latest_completed_day=latest_completed_day,
    )
    factory = apply_deps_factory
    if apply and factory is None:
        factory = lambda: (_ for _ in ()).throw(
            HistoricalUpdateAbort("HISTORICAL_UPDATE_APPLY_DEPS_MISSING")
        )
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


def build_default_audit_service() -> AuditV2ApplicationService:
    """Fail-closed: unwired scopes return AUDIT_SCOPE_UNAVAILABLE (no empty passed)."""
    return AuditV2ApplicationService(checkers={})


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
