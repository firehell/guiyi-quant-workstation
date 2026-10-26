"""Homepage projection composition: Catalog revisions and explicit offline builds."""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path

from sqlalchemy import func, literal, literal_column, select, text
from threading import Lock
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.core.env import PROJECT_ROOT
from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.composition import build_database_coverage_source, build_market_data_service, canonical_root
from app.market_data.operational_universe import load_active_products, load_operational_products
from app.models import Instrument, Exchange, Contract, TradingCalendar, TradingSession, MainContractMap, MarketDataset, MarketPartition
from guiyi_quant.newow.product_adapters import build_product_identity
from guiyi_quant.newow.home_independent_trend import HOME_TREND_VERSION
from guiyi_quant.newow.caution_display import CAUTION_DISPLAY_VERSION
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from app.market_data.market_home_overview import METRIC_POLICY_VERSION
from .composition import NewowComposition
from .daily_snapshot import NewowDailySnapshotResolver
from .weekly_snapshot import NewowWeeklySnapshotResolver, publication_state_from_status
from .product_release import candidate_input_quality_policy, CAPABILITY_SCHEMA_VERSION
from .product_service import ProductServiceQuery, ProductSection
from .home_cards import project_home_performance
from .home_projection import HomeProjection, ProjectionStore, projection_path, PERIODS, STRATEGIES



def configuration_identity():
    # These bounded repository inputs affect coverage, universe order or overview
    # presentation even when no Catalog row has changed.
    directory = PROJECT_ROOT / 'data/universe'
    files = ('product_window_starts.csv', 'active_history_floor.txt',
             'active_products.txt', 'operational_products.txt',
             'retired_products.txt', 'product_sectors.csv')
    dependencies = {name: sha256((directory / name).read_bytes()).hexdigest() for name in files}
    dependencies.update(capability=CAPABILITY_SCHEMA_VERSION, overview_policy=METRIC_POLICY_VERSION, home_trend=HOME_TREND_VERSION, caution_display=CAUTION_DISPLAY_VERSION)
    return sha256(json.dumps(dependencies, sort_keys=True).encode()).hexdigest()


def _digest_rows(session, table, owner, *, filters=(), joins=None, extra=()):
    # PostgreSQL assigns a new tuple version to every UPDATE, including equal-
    # count corrections. Ordered ids detect INSERT/DELETE; xmin+ctid distinguish
    # row versions without reading/serializing large TOASTed quality JSON.
    encoded = func.md5(func.concat(table.c.id, literal(':'),
        literal_column(f'{table.name}.xmin::text'), literal(':'),
        literal_column(f'{table.name}.ctid::text')))
    digest = func.md5(func.string_agg(encoded, aggregate_order_by(literal(''), table.c.id)))
    statement = select(owner, *extra, digest).select_from(joins if joins is not None else table).where(*filters).group_by(owner, *extra)
    return {tuple(row[:-1]): row[-1] for row in session.execute(statement)}


def catalog_versions(session, products):
    """Eight bounded aggregate queries, no Parquet reads or strategy execution.

    Fingerprint every row version, not max(updated_at)/counts: same-count changes and quality,
    map or session edits must invalidate. Digests are evaluated in PostgreSQL.
    """
    i, e, c, cal, se, m, d, p = (model.__table__ for model in (Instrument, Exchange, Contract, TradingCalendar, TradingSession, MainContractMap, MarketDataset, MarketPartition))
    instruments = {row.symbol: row.exchange_code for row in session.execute(select(i.c.symbol, i.c.exchange_code).where(i.c.symbol.in_(products)))}
    exchanges = tuple(set(instruments.values()))
    parts = {
        'instrument': _digest_rows(session, i, i.c.symbol, filters=(i.c.symbol.in_(products),)),
        'exchange': _digest_rows(session, e, e.c.code, filters=(e.c.code.in_(exchanges),)),
        'contract': _digest_rows(session, c, c.c.instrument_symbol, filters=(c.c.instrument_symbol.in_(products),)),
        'calendar': _digest_rows(session, cal, cal.c.exchange_code, filters=(cal.c.exchange_code.in_(exchanges),)),
        'session': _digest_rows(session, se, se.c.instrument_symbol, filters=(se.c.instrument_symbol.in_(products),)),
        'mapping': _digest_rows(session, m, m.c.symbol, filters=(m.c.symbol.in_(products),)),
        'dataset': _digest_rows(session, d, d.c.symbol, filters=(d.c.symbol.in_(products), d.c.kind == 'contract', d.c.frequency.in_(PERIODS)), extra=(d.c.frequency,)),
        'partition': _digest_rows(session, p, d.c.symbol, filters=(d.c.symbol.in_(products), d.c.kind == 'contract', d.c.frequency.in_(PERIODS)), joins=p.join(d, p.c.dataset_id == d.c.id), extra=(d.c.frequency,)),
    }
    # Coverage starting windows are an existing input to the authoritative reader.
    configuration = configuration_identity()
    versions = {}
    for product in products:
        if product not in instruments:
            continue
        common = {name: value.get((instruments[product] if name in {'calendar', 'exchange'} else product,)) for name, value in parts.items() if name not in {'dataset', 'partition'}}
        for frequency in PERIODS:
            policy = candidate_input_quality_policy(product, frequency, candidate_weekly=False)
            identities = [repr(build_product_identity(product, ProductStrategy(strategy), ProductFrequency(frequency), input_quality_policy=policy)) for strategy in STRATEGIES]
            deps = {**common, 'configuration': configuration, 'identities': identities,
                    'capability': CAPABILITY_SCHEMA_VERSION, 'projection': 'newow_home_projection_v1',
                    'reference': 'ordinary-page-performance-v1', 'home_trend': HOME_TREND_VERSION, 'caution_display': CAUTION_DISPLAY_VERSION}
            # Weekly source quality also depends on canonical D1 classification.
            for source_frequency in (('1d', '1w') if frequency == '1w' else ('1d',)):
                for name in ('dataset', 'partition'):
                    deps[f'{name}:{source_frequency}'] = parts[name].get((product, source_frequency))
            versions[f'{product}:{frequency}'] = sha256(json.dumps(deps, sort_keys=True).encode()).hexdigest()
    return versions


_VERSION_LOCK = Lock()
_VERSION_CACHE = None


def current_versions(products, *, now=None):
    # Exact DB visibility plus the existing session authority's next clock boundary.
    # Neither a TTL nor PostgreSQL approximate statistics prove unchanged sources.
    global _VERSION_CACHE
    instant = now or datetime.now(UTC)
    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=10):
        snapshot = session.scalar(text('SELECT pg_current_snapshot()::text'))
        configuration = configuration_identity()
        key = (str(session.get_bind().url.render_as_string(hide_password=True)), snapshot, tuple(products), configuration)
        with _VERSION_LOCK:
            if _VERSION_CACHE is not None and _VERSION_CACHE[0] == key and _VERSION_CACHE[2] <= instant < _VERSION_CACHE[3]:
                return dict(_VERSION_CACHE[1])
        coverage = build_database_coverage_source(session)
        target, boundary = coverage.latest_complete_day_with_refresh_at(tuple(products), now=instant)
        versions = catalog_versions(session, products)
        versions = {key: sha256(f'{value}:{target.isoformat()}:{configuration}'.encode()).hexdigest() for key, value in versions.items()}
        with _VERSION_LOCK:
            _VERSION_CACHE = (key, dict(versions), instant, boundary)
        return versions


def compute_period(session, product, frequency, now):
    """The existing resolvers/replay/projections remain the only calculation path."""
    from app.market_data.after_market import _load_status, public_after_market_status
    from app.api.newow_presentation import _json_value
    policy = candidate_input_quality_policy(product, frequency, candidate_weekly=False)
    market = build_market_data_service(session)
    coverage = build_database_coverage_source(session, reuse_session_windows=True)
    market.replay_coverage = coverage
    composition = NewowComposition(market, coverage, load_active_products(), policy, now=lambda: now)
    services = []
    def factory(cancelled):
        service = composition.service(cancelled=cancelled, reuse_read_inputs=True)
        services.append(service)
        return service
    reader = composition.reader()
    if frequency == '1d':
        resolver = NewowDailySnapshotResolver(reader, factory, now=lambda: now, timeout_seconds=600)
    else:
        status = public_after_market_status(_load_status(PROJECT_ROOT / '.run/after-market-status.json'))
        resolver = NewowWeeklySnapshotResolver(reader, factory, now=lambda: now, timeout_seconds=600,
            publication_state=lambda product, day, at: publication_state_from_status(status, product, day, at))
    snapshot, trend = resolver.resolve_with_chart(product, ProductStrategy.TREND, ProductFrequency(frequency))
    service = services[-1]
    facts = {}
    for strategy in STRATEGIES:
        result = trend if strategy == 'trend' else service.query(ProductServiceQuery(product, strategy, frequency, as_of=snapshot.as_of))
        summary = result.chart.value.home_summary if result.chart.value else None
        if summary is None:
            facts[strategy] = {'status': 'warming', 'state': None}
            continue
        facts[strategy] = {**summary, 'display_as_of': now, 'as_of': result.meta.as_of,
                           'freshness': snapshot.freshness, 'formula_versions': result.meta.identity.formula_versions,
                           'input_sha256': result.meta.input_content_sha256,
                           'data_revision_identity': result.meta.data_revision_identity}
        if facts[strategy].get('independent_trend') is not None:
            facts[strategy]['independent_trend']['parent_input_sha256'] = result.meta.input_content_sha256
        if frequency == '1d':
            reference = service.query(ProductServiceQuery(product, strategy, frequency,
                section=ProductSection.REFERENCE, as_of=snapshot.as_of, snapshot_token=result.meta.snapshot_token, history_limit=1))
            facts[strategy]['page_performance'] = project_home_performance(reference)
    return _json_value(facts)


def build_home_projection(*, output_path=None, now=None):
    products = load_operational_products()
    path = Path(output_path) if output_path is not None else Path(os.environ.get('GUIYI_HOME_PROJECTION_PATH', projection_path(canonical_root())))
    instant = now or (lambda: datetime.now(UTC))
    def compute(product, frequency):
        # Request-local input reuse never crosses this transaction or period.
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=600):
            return compute_period(session, product, frequency, instant())
    def overview():
        from app.market_data.composition import build_market_home_overview_service
        from app.market_data.market_home_projection import market_home_response
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=120):
            return market_home_response(build_market_home_overview_service(session).snapshot()).model_dump(mode='json')
    return HomeProjection(ProjectionStore(path), products, lambda: current_versions(products), compute, now=instant, overview=overview)


def build_home_overview_projection(_session=None):
    """Existing overview wire contract, backed by the same persisted homepage asset."""
    from app.market_data.market_home_overview import MarketHomeOverviewError
    from app.schemas.market import MarketHomeOverviewResponse
    class Reader:
        def read(self):
            value = build_home_projection().read()
            if value['overview'] is None:
                raise MarketHomeOverviewError('MARKET_HOME_PROJECTION_UNAVAILABLE')
            return MarketHomeOverviewResponse.model_validate({**value['overview'], 'projection_status': value['overview_status']})
    return Reader()
