"""Default-off foreground process for forward reference observations."""

from __future__ import annotations

from contextlib import contextmanager
import signal

from app.core.env import PROJECT_ROOT


ACTIVATION_MARKER = PROJECT_ROOT / ".run" / "reference-worker-enabled"


def require_worker_enabled() -> None:
    try:
        enabled = ACTIVATION_MARKER.read_text(encoding="utf-8") == "enabled\n"
    except (OSError, UnicodeDecodeError):
        enabled = False
    if not enabled:
        raise RuntimeError("REFERENCE_WORKER_NOT_ENABLED")


@contextmanager
def open_forward_worker():
    """Open DB and Redis only after an explicit local enable marker is present."""
    require_worker_enabled()
    from app.db.session import SessionLocal
    from app.market_data.catalog import MarketCatalog
    from app.market_data.composition import (
        build_database_coverage_source, build_market_data_service,
        build_market_read_service, canonical_root,
    )
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.newow.product_release import (
        candidate_input_quality_policy, require_open_frequency,
        require_open_weekly_product,
    )
    from app.market_data.operational_universe import load_active_products
    from app.redis_connections import get_redis_connection
    from app.reference_trading.composition import build_forward_reference_worker
    from app.reference_trading.forward_authority import ForwardMarketAuthority
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    from app.reference_trading.live_wake import ForwardLiveWake
    from app.reference_trading.repository import ReferenceRepository
    from guiyi_quant.newow.product_contracts import ProductFrequency

    with SessionLocal() as session:
        redis = get_redis_connection()
        try:
            market_data = build_market_data_service(session)
            market_read = build_market_read_service(session, redis=redis)
            coverage = build_database_coverage_source(session)
            products = load_active_products()
            authority = ForwardMarketAuthority(market_data)
            catalog = MarketCatalog(session, canonical_root())
            repository = ReferenceRepository(SessionLocal)

            def capability_ready(identity):
                try:
                    frequency = ProductFrequency(identity.frequency)
                    require_open_frequency(frequency)
                    if frequency is ProductFrequency.WEEKLY:
                        require_open_weekly_product(identity.product)
                except ValueError:
                    return False
                return True

            def reader_for(identity):
                if not capability_ready(identity):
                    raise ForwardInputUnavailable("NEWOW_CAPABILITY_CLOSED")
                policy = candidate_input_quality_policy(
                    identity.product, ProductFrequency(identity.frequency),
                    candidate_weekly=False,
                )
                return NewowProductReader(
                    market_data, coverage=coverage, active_products=products,
                    input_quality_policy=policy,
                )

            @contextmanager
            def canonical_guard():
                lease = catalog.acquire_maintenance_lock()
                if lease is None:
                    raise ForwardInputUnavailable("SOURCE_BUSY")
                try:
                    yield
                finally:
                    lease.release()

            worker = build_forward_reference_worker(
                repository=repository, market_read=market_read,
                newow_reader=reader_for,
                owner_segments=authority.owner_segments,
                expected_endpoints=authority.expected_endpoints,
                newow_capability_ready=capability_ready,
                canonical_read_guard=canonical_guard, enabled=True,
            )
            wake = ForwardLiveWake(redis, repository, worker, market_data)
            try:
                wake.subscribe()
                yield worker, wake
            finally:
                wake.close()
        finally:
            redis.close()


def main() -> int:
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with open_forward_worker() as (worker, wake):
        worker.serve(should_stop=lambda: stopped, wait=wake.wait)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
