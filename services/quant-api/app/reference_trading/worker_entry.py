"""Default-off foreground process for forward reference observations."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import signal
import os

from app.core.env import PROJECT_ROOT


ACTIVATION_MARKER = PROJECT_ROOT / ".run" / "reference-worker-enabled"


def historical_refresh_state_path() -> Path:
    return Path.home() / "Library/Application Support/GuiyiQuant/newow-historical-refresh-state.json"


def require_worker_enabled() -> None:
    try:
        enabled = ACTIVATION_MARKER.read_text(encoding="utf-8") == "enabled\n"
    except (OSError, UnicodeDecodeError):
        enabled = False
    if not enabled:
        raise RuntimeError("REFERENCE_WORKER_NOT_ENABLED")


@contextmanager
def open_forward_worker(*, ownership=None, warmup=False):
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
                    from app.reference_trading.recording_scope import recording_route_supported
                    if not recording_route_supported(identity.strategy_code, identity.frequency):
                        return False
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
                session.rollback()  # Refresh read-only Catalog state after natural publication.
                lease = catalog.acquire_maintenance_lock()
                if lease is None:
                    raise ForwardInputUnavailable("SOURCE_BUSY")
                try:
                    yield
                finally:
                    session.rollback()
                    lease.release()

            from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources

            from app.reference_trading.scheduled_reconciliation import (
                CompletedCanonicalReader, ScheduledCanonicalReconciliation,
            )
            reconciliation = ScheduledCanonicalReconciliation(
                SessionLocal, CompletedCanonicalReader(market_data, authority.owner_segments),
                read_guard=canonical_guard,
            )
            worker = build_forward_reference_worker(
                repository=repository, market_read=market_read,
                newow_reader=reader_for,
                owner_segments=authority.owner_segments,
                expected_endpoints=authority.expected_endpoints,
                newow_capability_ready=capability_ready,
                canonical_read_guard=canonical_guard, enabled=True,
                fusion_sources=SavedForwardFusionSources(SessionLocal),
                reconciliation_guard=reconciliation.assert_source_allowed,
                reconciliation_commit_guard=reconciliation.commit_guard,
            )
            if ownership is not None:
                worker.assert_owned = ownership.assert_owned
                worker.mark_ready = lambda: ownership.mark_ready({"cursor_validated": True})
            from app.reference_trading.live_wake import StreamForwardLiveWake
            durable_observations = os.getenv("GUIYI_OBSERVATION_STREAM_ENABLED", "0") == "1"
            worker.scan_live = not durable_observations
            wake_type = StreamForwardLiveWake if durable_observations else ForwardLiveWake
            wake = wake_type(redis, repository, worker, market_data)
            from app.reference_trading.historical_refresh import build_historical_refresh, RefreshThread
            refresh = RefreshThread(build_historical_refresh(
                SessionLocal, state_path=historical_refresh_state_path(),
            ))
            from app.notifications.newow import NewowNotificationDispatcher
            from app.notifications.newow_thread import NotificationThread
            notifications = NotificationThread(NewowNotificationDispatcher(SessionLocal,
                assert_owned=ownership.assert_owned if ownership else None,
                should_stop=ownership.should_drain if ownership else None))
            try:
                wake.subscribe()
                if not warmup:
                    refresh.start()
                    notifications.start()
                yield worker, wake, reconciliation
            finally:
                if notifications.is_alive():
                    notifications.stop()
                if not warmup:
                    refresh.stop(timeout=None)
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
    def run(ownership=None):
        with open_forward_worker(ownership=ownership) as (worker, wake, reconciliation):
            def wait(seconds):
                if ownership:
                    ownership.assert_owned()
                reconciliation.tick(now=datetime.now(UTC))
                wake.wait(seconds)
            worker.serve(should_stop=lambda: stopped or bool(ownership and ownership.should_drain()), wait=wait)
    from app.runtime_handover import run_supervised
    from app.runtime_bindings import read_bindings
    if read_bindings() is not None and os.getenv("GUIYI_RUNTIME_LEGACY_MODE") != "1":
        run_supervised("reference-worker", run, stop_requested=lambda: stopped)
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def warmup_reference_worker():
    """Read current checkpoints and calculate candidate captures without persistence."""
    with open_forward_worker(warmup=True) as (worker, _wake, _reconciliation):
        repository = worker._repository
        count = 0
        after = None
        while True:
            streams = repository.enabled_forward_stream_ids(limit=512, after=after)
            if not streams:
                break
            for stream_id in streams:
                service = worker._service_for(stream_id)
                token, checkpoint = repository.load_checkpoint(stream_id)
                pending = repository.read_pending_capture(stream_id)
                if pending:
                    capture_id, evidence = pending
                    service._evaluator(token, checkpoint, {**evidence, "capture_id": capture_id})
                else:
                    capture = worker._read_input(stream_id, "scan", None)
                    if capture is None:
                        _warmup_saved_capture(repository, stream_id, service)
                    else:
                        service._evaluator(token, checkpoint, {**capture.evidence(), "capture_id": "warmup"})
                count += 1
            after = streams[-1]
        if count == 0:
            raise RuntimeError("REFERENCE_WARMUP_SCOPE_EMPTY")
        return {"calculated": count}


def _warmup_saved_capture(repository, stream_id, service):
    """Recompute the last immutable calculation from its actual predecessor."""
    from sqlalchemy import select
    from app.reference_trading.models import ReferenceBatch, ReferenceStream
    from app.reference_trading.contracts import CheckpointToken
    from app.reference_trading.repository import _checkpoint_hash, _identity_from_row
    from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json
    with repository._session_factory() as session:
        stream = session.get(ReferenceStream, stream_id)
        batches = session.scalars(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == stream_id,
            ReferenceBatch.revision_id == stream.active_revision_id,
            ReferenceBatch.outcome == "committed", ReferenceBatch.checkpoint_text.is_not(None),
        ).order_by(ReferenceBatch.seq.desc()).limit(2)).all()
        if len(batches) != 2 or batches[0].seq != batches[1].seq + 1:
            raise RuntimeError("REFERENCE_WARMUP_PREIMAGE_UNAVAILABLE")
        latest, previous = batches
        evidence = latest.source_evidence
        capture = evidence.get("forward_capture_v1")
        if not isinstance(capture, dict):
            raise RuntimeError("REFERENCE_WARMUP_CAPTURE_UNAVAILABLE")
        checkpoint = adapter_checkpoint_from_json(previous.checkpoint_text,
            expected_stream=_identity_from_row(stream), expected_strategy_schema=previous.strategy_schema)
        token = CheckpointToken(stream_id, stream.active_revision_id, previous.seq,
                                stream.row_version, _checkpoint_hash(previous.checkpoint_text))
        service._evaluator(token, checkpoint, evidence)
