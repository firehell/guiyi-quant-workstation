"""Default-off foreground process for forward reference observations."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep
import signal
import os
import sys

from app.core.env import PROJECT_ROOT


ACTIVATION_MARKER = PROJECT_ROOT / ".run" / "reference-worker-enabled"


def _check_warmup_deadline(deadline: float | None) -> None:
    if deadline is not None and monotonic() >= deadline:
        raise RuntimeError("REFERENCE_WARMUP_TIMEOUT")


def _acquire_canonical_lease(catalog, *, deadline: float | None):
    """Only read-only candidate composition waits for the existing exclusive lease."""
    from app.reference_trading.forward_inputs import ForwardInputUnavailable
    while True:
        _check_warmup_deadline(deadline)
        lease = catalog.acquire_maintenance_lock()
        if lease is not None:
            if deadline is not None and monotonic() >= deadline:
                lease.release()
                raise RuntimeError("REFERENCE_WARMUP_TIMEOUT")
            return lease
        if deadline is None:
            raise ForwardInputUnavailable("SOURCE_BUSY")
        sleep(min(0.1, max(0.0, deadline - monotonic())))


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
def open_forward_worker(*, ownership=None, warmup=False, warmup_deadline=None):
    """Persist bounded startup diagnostics without changing startup ordering."""
    from app.reference_trading.runtime import diagnostic_reason
    if warmup:
        warmup_deadline = warmup_deadline if warmup_deadline is not None else monotonic() + 120.0
    else:
        warmup_deadline = None
    stage = 'compose'
    last_runtime = {}
    def publish(next_stage, **background_health):
        nonlocal stage
        stage = next_stage
        if ownership is not None:
            ownership.mark_not_ready({'reference_runtime': {**last_runtime, **background_health,
                'stage': stage, 'ready': False}})
    def report_health(proof):
        nonlocal last_runtime
        receiving = proof.get('receiving')
        last_runtime = {key: value for key, value in proof.items() if key != 'receiving'}
        if ownership is not None:
            intake_ready = 'receiving' not in proof
            if not intake_ready:
                from app.reference_trading.operational_readiness import valid_receiving_wait_proof
                intake_ready = (isinstance(receiving, dict)
                    and type(receiving.get('protocol_version')) is int and receiving['protocol_version'] == 2
                    and receiving.get('intake_error') is None
                    and valid_receiving_wait_proof(receiving.get('waiting_history_proof')))
            payload = {'reference_runtime': last_runtime, 'cursor_validated': True}
            if 'receiving' in proof:
                payload['receiving'] = receiving
            (ownership.mark_ready if proof['ready'] and intake_ready else ownership.mark_not_ready)(payload)
    publish(stage)
    try:
        with _open_forward_worker(ownership=ownership, warmup=warmup, warmup_deadline=warmup_deadline,
                publish_stage=publish,
                report_health=report_health) as value:
            yield value
    except Exception as error:
        if ownership is not None:
            ownership.mark_not_ready({'reference_runtime': {**last_runtime, 'stage': stage, 'ready': False,
                'failure_code': diagnostic_reason(str(error))}})
        raise


@contextmanager
def _open_forward_worker(*, ownership=None, warmup=False, warmup_deadline=None,
                         publish_stage=lambda _stage, **_fields: None,
                         report_health=lambda _proof: None):
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

    worker = None
    def check_foreground_cancelled():
        if worker is not None:
            worker.check_cancelled()

    with SessionLocal() as session:
        publish_stage('database_open')
        redis = get_redis_connection()
        try:
            market_data = build_market_data_service(session, check_cancelled=check_foreground_cancelled)
            market_read = build_market_read_service(session, redis=redis,
                                                   check_cancelled=check_foreground_cancelled)
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
                    cancelled=lambda: (worker.check_cancelled() or False),
                )

            @contextmanager
            def canonical_guard():
                worker.check_cancelled()
                with worker.timings.measure("background_wait"), refresh_priority.foreground():
                    worker.check_cancelled()
                    session.rollback()  # Refresh Catalog after natural publication.
                    lease = _acquire_canonical_lease(catalog, deadline=warmup_deadline if warmup else None)
                    try:
                        yield
                    finally:
                        session.rollback()
                        lease.release()

            from app.reference_trading.refresh_priority import RefreshPriority
            refresh_priority = RefreshPriority()

            def history_can_run():
                if worker.stop_requested():
                    return False
                if not refresh_priority.can_run():
                    return False
                from app.reference_trading.refresh_priority import historical_rest_allowed
                if not historical_rest_allowed(SessionLocal, products, now=datetime.now(UTC),
                                               cancelled=worker.stop_requested):
                    refresh_priority.withdraw()
                    return False
                return True

            from app.reference_trading.newow_fusion_forward import SavedForwardFusionSources

            from app.reference_trading.scheduled_reconciliation import (
                CompletedCanonicalReader, ScheduledCanonicalReconciliation,
            )
            reconciliation = ScheduledCanonicalReconciliation(
                SessionLocal, CompletedCanonicalReader(market_data, authority.owner_segments,
                                                       source_revision_policy=True),
                read_guard=canonical_guard,
                check_cancelled=lambda: worker.check_cancelled(),
            )
            from app.market_data.subing_reference import SubingReferenceService
            subing_service = SubingReferenceService(
                market_data, coverage=coverage, active_products=products,
                check_cancelled=lambda: worker.check_cancelled(),
            )
            worker = build_forward_reference_worker(
                repository=repository, market_read=market_read,
                newow_reader=reader_for, subing_service=subing_service,
                subing_owner_started_at=authority.owner_started_at,
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
                def report(proof):
                    from app.reference_trading.runtime import diagnostic_reason
                    proof = {**proof, 'historical_refresh_alive': refresh.is_alive(),
                        'historical_refresh': refresh.diagnostic_snapshot(),
                        'historical_refresh_error': None if refresh.last_error is None
                            else diagnostic_reason(refresh.last_error),
                        'notifications_alive': notifications.is_alive()}
                    if inbox_mode:
                        from app.reference_trading.operational_readiness import build_receiving_wait_proof
                        receiving = {'protocol_version': 2,
                            'intake_error': getattr(wake, 'intake_error', None),
                            'waiting_history_proof': None}
                        if proof.get('stage') in {'cycle', 'receiving_cycle'} and receiving['intake_error'] is None:
                            try:
                                receiving['waiting_history_proof'] = build_receiving_wait_proof(
                                    SessionLocal, worker.health().blocked)
                            except Exception:
                                # A failed readback is never lifecycle readiness.
                                pass
                        proof = {**proof, 'receiving': receiving}
                    report_health(proof)
                worker.report_health = report
            worker.observation_priority = refresh_priority.observation
            from app.reference_trading.live_wake import StreamForwardLiveWake
            durable_observations = os.getenv("GUIYI_OBSERVATION_STREAM_ENABLED", "0") == "1"
            worker.scan_live = not durable_observations
            wake_type = StreamForwardLiveWake if durable_observations else ForwardLiveWake
            inbox_mode = False
            if durable_observations:
                from app.reference_trading.inbox_protocol import (
                    build_receiving_protocol, require_inbox_schema,
                )
                from app.runtime_handover import runtime_directory
                if (runtime_directory()/"reference-receiving-protocol.json").exists():
                    from app.market_data.observation_stream import ObservationStream
                    require_inbox_schema(SessionLocal)
                    protocol = build_receiving_protocol()
                    if ownership is None and not warmup:
                        raise RuntimeError("REFERENCE_INBOX_OWNER_REQUIRED")
                    inbox_mode = protocol.activate(ObservationStream(redis, kind="completed"),
                        assert_owned=ownership.assert_owned if ownership else lambda: None, warmup=warmup)
            repository.inbox_enabled = inbox_mode
            if inbox_mode:
                from app.reference_trading.inbox import ReferenceInboxRepository
                from app.reference_trading.live_wake import InboxForwardLiveWake
                from app.market_data.contract_preparation_runtime import build_contract_preparation_requester
                wake = InboxForwardLiveWake(redis, repository, worker, market_data,
                    inbox=ReferenceInboxRepository(SessionLocal, timings=worker.timings,
                        check_cancelled=worker.check_cancelled),
                    request_history=build_contract_preparation_requester())
                worker.has_foreground_work = lambda: (
                    wake.has_pending_work() or repository.has_pending_forward_capture())
                if not warmup:
                    wake.on_intake_failure = protocol.block_intake
                wake.intake_error = protocol.read().get("intake_error")
                wake.on_receiving_round = lambda: worker.report_health(
                    worker.diagnostic_health(stage='receiving_cycle', ready=False))
            else:
                wake = wake_type(redis, repository, worker, market_data)
            if durable_observations:
                wake.stop_requested = ownership.should_drain if ownership else lambda: False
                worker.poll_observations = wake.poll
            from app.reference_trading.historical_refresh import build_historical_refresh, RefreshThread
            refresh = RefreshThread(build_historical_refresh(
                SessionLocal, state_path=historical_refresh_state_path(),
            ), batch_limit=1, can_run=history_can_run, yield_requested=refresh_priority.yield_requested,
                on_tick_started=refresh_priority.begin, on_tick_finished=refresh_priority.finish)
            from app.notifications.newow import NewowNotificationDispatcher
            from app.notifications.newow_thread import NotificationThread
            notifications = NotificationThread(NewowNotificationDispatcher(SessionLocal,
                assert_owned=ownership.assert_owned if ownership else None,
                should_stop=ownership.should_drain if ownership else None))
            try:
                publish_stage('stream_subscribe')
                wake.subscribe()
                if not warmup:
                    publish_stage('notifications_start')
                    notifications.start()
                    defer_historical_refresh(worker, refresh,
                        should_stop=ownership.should_drain if ownership else lambda: False,
                        priority=refresh_priority)
                publish_stage('running')
                yield worker, wake, reconciliation
            finally:
                failed = sys.exc_info()[0] is not None
                try:
                    if not failed:
                        publish_stage('draining')
                finally:
                    close_worker_resources(notifications, refresh, wake, warmup=warmup)
                if not failed:
                    publish_stage('drained', historical_refresh_alive=refresh.is_alive(),
                        notifications_alive=notifications.is_alive())
        finally:
            redis.close()


def close_worker_resources(notifications, refresh, wake, *, warmup):
    """Every close is attempted; failed diagnostics never bypass transport drain."""
    try:
        if notifications.is_alive():
            notifications.stop()
    finally:
        try:
            if not warmup:
                refresh.stop(timeout=None)
        finally:
            wake.close()
    if notifications.is_alive() or refresh.is_alive():
        raise RuntimeError("REFERENCE_BACKGROUND_DRAIN_INCOMPLETE")


def defer_historical_refresh(worker, refresh, *, should_stop, priority=None):
    """The first committed healthy foreground proof precedes background startup."""
    attempted = False
    def after_healthy_round():
        nonlocal attempted
        if should_stop():
            return
        if getattr(worker, 'has_foreground_work', lambda: False)():
            if priority is not None:
                priority.withdraw()
            return
        if priority is not None:
            priority.grant()
        if attempted:
            return
        attempted = True  # A failed/unknown thread start is never retried.
        refresh.start()
    worker.after_healthy_round = after_healthy_round


def main() -> int:
    from app.runtime_logging import install_runtime_diagnostics
    install_runtime_diagnostics("reference-worker")
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def run(ownership=None):
        with open_forward_worker(ownership=ownership) as (worker, wake, reconciliation):
            def should_stop():
                return stopped or bool(ownership and ownership.should_drain())
            wake.stop_requested = should_stop
            healthy_round = worker.after_healthy_round
            def after_healthy_round():
                if not should_stop():
                    healthy_round()
            worker.after_healthy_round = after_healthy_round
            def wait(seconds):
                if ownership:
                    ownership.assert_owned()
                if should_stop():
                    return
                reconciliation.tick(now=datetime.now(UTC))
                wake.wait(seconds)
            worker.serve(should_stop=should_stop, wait=wait)
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
    """Validate every route while sharing raw inputs for one scheduling group."""
    deadline = monotonic() + 120.0
    with open_forward_worker(warmup=True, warmup_deadline=deadline) as (worker, _wake, _reconciliation):
        repository = worker._repository
        count = 0
        initialized = 0
        after = None
        while True:
            _check_warmup_deadline(deadline)
            keys = worker._enabled_keys(limit=512, after=after)
            if not keys:
                break
            for key in keys:
                _check_warmup_deadline(deadline)
                try:
                    worker._begin_unit()
                    # The repository orders base routes before fusion and pages
                    # distinct keys, so a group cannot straddle a page boundary.
                    routes = worker._work_routes(key)
                    for stream_id in routes:
                        _check_warmup_deadline(deadline)
                        from app.reference_trading.recording_scope import LIVE_FREQUENCIES
                        pending = repository.read_pending_capture(stream_id)
                        context = repository.forward_source_context(stream_id)
                        if (not worker.scan_live and not pending and context is not None
                                and context[0].frequency in LIVE_FREQUENCIES):
                            if not any(repository.read_pending_capture(route) is not None for route in routes):
                                continue
                        service = worker._service_for(stream_id)
                        token, checkpoint = repository.load_checkpoint(stream_id)
                        result = "calculated"
                        if pending:
                            capture_id, evidence = pending
                            service._evaluator(token, checkpoint, {**evidence, "capture_id": capture_id})
                        else:
                            capture = worker._read_input(stream_id, "scan", None)
                            if capture is None:
                                result = _warmup_saved_capture(repository, stream_id, service)
                            else:
                                service._evaluator(token, checkpoint, {**capture.evidence(), "capture_id": "warmup"})
                        if result == "initialized":
                            initialized += 1
                        else:
                            count += 1
                        _check_warmup_deadline(deadline)
                finally:
                    worker._end_unit()
            after = keys[-1]
        if count + initialized == 0:
            raise RuntimeError("REFERENCE_WARMUP_SCOPE_EMPTY")
        return {"calculated": count, **({"initialized": initialized} if initialized else {})}


def _warmup_saved_capture(repository, stream_id, service):
    """Replay a real calculation, or verify a never-calculated activation seed."""
    from sqlalchemy import select, text
    from app.reference_trading.models import ReferenceBatch, ReferenceStream
    from app.reference_trading.contracts import CheckpointToken
    from app.reference_trading.repository import _checkpoint_hash, _identity_from_row
    from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json
    with repository._session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
        stream = session.get(ReferenceStream, stream_id)
        if stream is None or stream.active_revision_id is None:
            raise RuntimeError("REFERENCE_WARMUP_PREIMAGE_UNAVAILABLE")
        batches = session.scalars(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == stream_id,
            ReferenceBatch.revision_id == stream.active_revision_id,
            ReferenceBatch.outcome == "committed", ReferenceBatch.checkpoint_text.is_not(None),
        ).order_by(ReferenceBatch.seq.desc()).limit(2)).all()
        if len(batches) == 1 and batches[0].kind == "seed_seal" and batches[0].seq == 1:
            _validate_initial_seed(session, repository, stream, batches[0])
            return "initialized"
        if len(batches) != 2 or batches[0].seq != batches[1].seq + 1:
            raise RuntimeError("REFERENCE_WARMUP_PREIMAGE_UNAVAILABLE")
        latest, previous = batches
        evidence = _saved_capture_evidence(session, stream, latest, previous)
        checkpoint = adapter_checkpoint_from_json(previous.checkpoint_text,
            expected_stream=_identity_from_row(stream), expected_strategy_schema=previous.strategy_schema)
        token = CheckpointToken(stream_id, stream.active_revision_id, previous.seq,
                                stream.row_version, _checkpoint_hash(previous.checkpoint_text))
        service._evaluator(token, checkpoint, evidence)
        return "calculated"


def _validate_initial_seed(session, repository, stream, seed):
    """Validate the original zero-calculation contract without fabricating a Bar.

    A seed seal has seq=1 and expected_seq=0. It is initialization evidence,
    never a replacement preimage for an already calculated or pending stream.
    """
    from hashlib import sha256
    from sqlalchemy import select
    from app.reference_trading.models import ReferenceActivationReceipt, ReferenceBatch, ReferenceRevision
    from app.reference_trading.repository import _aware, _checkpoint_hash, _identity_from_row, RepositoryConflict
    from app.reference_trading.contracts import manifest_sha256
    from guiyi_quant.reference_trading import RecordingMode, ReferenceState
    from guiyi_quant.reference_trading.strategy_checkpoint import adapter_checkpoint_from_json

    failure = "REFERENCE_WARMUP_INITIAL_SEED_INVALID"
    try:
        revision = session.get(ReferenceRevision, (stream.stream_id, stream.active_revision_id))
        if (not stream.enabled or stream.recording_mode != RecordingMode.FORWARD_OBSERVATION.value
                or stream.activation_generation != 1 or stream.recording_start is None
                or revision is None or revision.status != "active" or revision.parent_revision_id is not None
                or revision.last_seq != 1 or stream.latest_seq != 1
                or revision.checkpoint_batch_id != seed.batch_id
                or seed.stream_id != stream.stream_id or seed.revision_id != revision.revision_id
                or seed.kind != "seed_seal" or seed.outcome != "committed"
                or seed.seq != 1 or seed.expected_seq != 0 or seed.pre_state_hash is not None
                or not seed.checkpoint_text or not seed.strategy_schema
                or seed.projected_action_pks or seed.diagnostics or seed.consumed_by_batch_id is not None):
            raise ValueError
        receipts = session.scalars(select(ReferenceActivationReceipt).where(
            ReferenceActivationReceipt.stream_id == stream.stream_id)).all()
        if len(receipts) != 1:
            raise ValueError
        receipt = receipts[0]
        if (receipt.revision_id != revision.revision_id or receipt.generation != stream.activation_generation
                or receipt.disabled_at is not None or receipt.plan_hash != stream.activation_plan_hash
                or not isinstance(receipt.plan_hash, str) or len(receipt.plan_hash) != 64
                or any(char not in "0123456789abcdef" for char in receipt.plan_hash)
                or _aware(receipt.recording_start) != _aware(stream.recording_start)
                or _aware(receipt.activated_at) > _aware(receipt.recording_start)):
            raise ValueError
        identity = _identity_from_row(stream)
        if (identity.stream_id != stream.stream_id
                or stream.identity_hash != identity.stream_id.removeprefix("reference-stream:")):
            raise ValueError
        checkpoint = adapter_checkpoint_from_json(seed.checkpoint_text,
            expected_stream=identity, expected_strategy_schema=seed.strategy_schema)
        state_hash = _checkpoint_hash(seed.checkpoint_text)
        digest = manifest_sha256(seed.dependency_manifest)
        if (checkpoint.reference_state != ReferenceState.flat(identity, recording_start=_aware(stream.recording_start))
                or _aware(seed.computed_through) != checkpoint.computed_through
                or seed.last_event_bar_end is not None or seed.last_event_kind is not None
                or seed.last_event_sequence is not None or seed.post_state_hash != state_hash
                or seed.batch_key != "seed-seal:" + state_hash or revision.dependency_digest != digest
                or seed.payload_hash != sha256((digest + state_hash).encode()).hexdigest()):
            raise ValueError
        # Exact hash linkage is shared with seal_seed; no second seed algorithm.
        rows = session.scalars(select(ReferenceBatch).where(
            ReferenceBatch.stream_id == stream.stream_id,
            ReferenceBatch.revision_id == revision.revision_id)).all()
        chunks = [row for row in rows if row.kind == "seed_chunk"]
        if len(rows) != len(chunks) + 1:
            raise ValueError
        ever_calculated = session.scalar(select(ReferenceBatch.batch_id).where(
            ReferenceBatch.stream_id == stream.stream_id,
            ReferenceBatch.kind.in_(("calculation", "capture"))).limit(1))
        if ever_calculated is not None:
            raise ValueError
        repository._validate_chunks(chunks)
        if (seed.source_evidence != {"seed_root_hash": chunks[0].seed_root_hash}
                or any(row.outcome != "staged" or row.seq is not None or row.expected_seq != 0
                    or row.checkpoint_text is not None or row.consumed_by_batch_id is not None
                    or row.payload_hash != sha256(row.seed_chunk_text.encode()).hexdigest() for row in chunks)):
            raise ValueError
        activation = seed.dependency_manifest.get("subing_activation_v2")
        if activation is not None and (
                not isinstance(activation, dict)
                or activation.get("stream_id") != stream.stream_id
                or activation.get("product") != identity.product or activation.get("frequency") != identity.frequency
                or activation.get("version") != identity.observation_policy_version
                or activation.get("host") != receipt.host or activation.get("environment") != receipt.environment
                or datetime.fromisoformat(activation["recording_start"]) != _aware(receipt.recording_start)
                or seed.dependency_manifest.get("plan_hash") != manifest_sha256(activation)):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError, RepositoryConflict):
        raise RuntimeError(failure) from None


def _saved_capture_evidence(session, stream, latest, previous):
    """Resolve compact calculation proof to its exact immutable capture fact."""
    from app.reference_trading.capture import ForwardCapture
    from app.reference_trading.models import ReferenceBatch
    proof = latest.source_evidence.get('forward_capture_v1')
    if not isinstance(proof, dict) or not isinstance(proof.get('capture_id'), str):
        raise RuntimeError('REFERENCE_WARMUP_CAPTURE_UNAVAILABLE')
    row = session.get(ReferenceBatch, proof['capture_id'])
    if (row is None or row.kind != 'capture' or row.outcome != 'consumed'
            or row.stream_id != stream.stream_id or row.revision_id != stream.active_revision_id
            or row.consumed_by_batch_id != latest.batch_id or latest.kind != 'calculation'
            or latest.expected_seq != previous.seq or row.expected_seq != previous.seq):
        raise RuntimeError('REFERENCE_WARMUP_CAPTURE_CONFLICT')
    full = row.source_evidence.get('forward_capture_v1')
    if (not isinstance(full, dict) or full.get('hash') != proof.get('hash')
            or row.payload_hash != proof.get('hash') or full.get('generation') != proof.get('generation')
            or full.get('generation') != stream.activation_generation):
        raise RuntimeError('REFERENCE_WARMUP_CAPTURE_CONFLICT')
    try:
        capture = ForwardCapture(stream.stream_id, stream.active_revision_id, full['generation'],
            full['source_key'], datetime.fromisoformat(full['bar_end']), datetime.fromisoformat(full['observed_at']),
            full['source_kind'], full['input_payload'], full['source_proof'], full['eligibility'])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError('REFERENCE_WARMUP_CAPTURE_INVALID') from None
    if capture.capture_hash != row.payload_hash or capture.batch_key != row.batch_key:
        raise RuntimeError('REFERENCE_WARMUP_CAPTURE_CONFLICT')
    return {**row.source_evidence, 'capture_id': row.batch_id}
