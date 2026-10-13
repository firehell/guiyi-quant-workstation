"""Bounded input-only diagnosis; never captures, projects, acknowledges or sends."""
from time import monotonic

from app.reference_trading.runtime import diagnostic_reason, failure_reason


def diagnose_inputs(routes, pure_read_input, *, max_routes=120, max_seconds=120):
    routes = tuple(routes)
    if (not routes or len(routes) > max_routes or max_routes > 720
            or len(set(routes)) != len(routes) or not 0 < max_seconds <= 300):
        raise ValueError('REFERENCE_DIAGNOSTIC_BUDGET_INVALID')
    start, result = monotonic(), []
    for route in routes:
        if monotonic() - start >= max_seconds:
            break
        before = monotonic()
        try:
            capture = pure_read_input(route, 'scan', None)
        except Exception as error:  # Only stable domain codes leave this boundary.
            result.append({'stream_id': route, 'status': 'blocked',
                'reason': diagnostic_reason(failure_reason(error)),
                'error_type': type(error).__name__, 'seconds': round(monotonic() - before, 3)})
        else:
            result.append({'stream_id': route, 'status': 'input_available' if capture else 'no_input',
                'reason': None, 'seconds': round(monotonic() - before, 3)})
    return {'read_only': True, 'requested': len(routes), 'checked': len(result),
            'budget_exhausted': len(result) < len(routes), 'items': result}


def diagnose_current_inputs(routes, *, max_seconds=120):
    """Production-safe composition: DB read-only, Redis GET only, no worker lifecycle.

    This is an input diagnostic snapshot, not a publication/ownership acceptance.
    Each reader call is database-timeout bounded; the total budget stops new calls.
    """
    from contextlib import contextmanager, nullcontext
    from datetime import UTC, datetime
    from app.db.session import SessionLocal
    from app.db.readonly import readonly_transaction
    from app.market_data.composition import (build_market_data_service,
        build_market_read_service, build_database_coverage_source)
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.newow.product_release import candidate_input_quality_policy, require_open_frequency
    from app.market_data.operational_universe import load_active_products
    from app.redis_connections import get_redis_connection
    from app.reference_trading.composition import build_forward_reference_worker
    from app.reference_trading.forward_authority import ForwardMarketAuthority
    from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources
    from app.reference_trading.repository import ReferenceRepository
    from guiyi_quant.newow.product_contracts import ProductFrequency

    @contextmanager
    def factory():
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=20):
            yield session

    with factory() as session:
        redis = get_redis_connection()
        try:
            market = build_market_data_service(session)
            market_read = build_market_read_service(session, redis=redis)
            coverage, products = build_database_coverage_source(session), load_active_products()
            authority = ForwardMarketAuthority(market)
            def reader(identity):
                return NewowProductReader(market, coverage=coverage, active_products=products,
                    input_quality_policy=candidate_input_quality_policy(identity.product,
                        ProductFrequency(identity.frequency), candidate_weekly=False))
            def capability(identity):
                try:
                    require_open_frequency(ProductFrequency(identity.frequency))
                    return True
                except ValueError:
                    return False
            worker = build_forward_reference_worker(repository=ReferenceRepository(factory),
                market_read=market_read, newow_reader=reader,
                owner_segments=authority.owner_segments, expected_endpoints=authority.expected_endpoints,
                newow_capability_ready=capability, canonical_read_guard=nullcontext,
                enabled=False, now=lambda: datetime.now(UTC),
                fusion_sources=SavedForwardFusionSources(factory),
                reconciliation_guard=None)
            # This diagnoses input construction only. The runtime reconciliation
            # guard takes FOR UPDATE locks and must not run in a read-only snapshot;
            # known active mismatches are reported separately by Reference health.
            worker.scan_live = True
            return diagnose_inputs(routes, worker._read_input, max_seconds=max_seconds)
        finally:
            redis.close()
