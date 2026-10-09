"""Explicit P4 composition; importing this module creates no engine or client."""

from __future__ import annotations

from app.reference_trading.recording_scope import LIVE_FREQUENCIES

from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from app.reference_trading.inputs import HistoricalInputReader
from app.reference_trading.planning import HistoricalReferencePlanner


def build_forward_reference_worker(
    *, repository, market_read, newow_reader, owner_segments,
    expected_endpoints, newow_capability_ready,
    canonical_read_guard=None, now: Callable[[], datetime] = lambda: datetime.now(UTC),
    enabled: bool = False, fusion_sources=None, reconciliation_guard=None,
    reconciliation_commit_guard=None,
):
    """Compose a default-off worker; callers provide authoritative read seams."""
    from app.reference_trading.forward_inputs import (
        ForwardInputUnavailable, capture_htdy_live, capture_newow_canonical,
        capture_newow_live, capture_subing_live,
    )
    from app.reference_trading.forward_service import ForwardReferenceService
    from app.reference_trading.htdy import evaluate_htdy_capture
    from app.reference_trading.newow_forward import evaluate_newow_capture
    from app.reference_trading.newow_fusion_forward import evaluate_fusion_capture
    from app.reference_trading.input_cache import NewowInputCache

    cache = NewowInputCache()
    cached_live = cache.live_reader(market_read)
    from app.reference_trading.recovery import (
        capture_observation_gap, evaluate_observation_gap,
    )
    from app.reference_trading.runtime import ForwardReferenceWorker
    from app.reference_trading.subing_forward import evaluate_subing_capture

    def service_for(stream_id: str) -> ForwardReferenceService:
        if reconciliation_guard is not None:
            reconciliation_guard(stream_id)
        state = repository.read_state(stream_id)
        _, checkpoint = repository.load_checkpoint(stream_id, state.revision_id)
        stream = checkpoint.stream
        if stream is None:
            raise ValueError("FORWARD_CHECKPOINT_INVALID")
        code = stream.strategy_code.replace("-", "_")
        if code == "newow_dual_fusion":
            evaluator = evaluate_fusion_capture
        elif code.startswith("newow_"):
            evaluator = evaluate_newow_capture
        elif code == "subing_reference":
            evaluator = evaluate_subing_capture
        elif code == "htdy":
            evaluator = evaluate_htdy_capture
        else:
            raise ValueError("FORWARD_STRATEGY_UNSUPPORTED")
        def evaluate(token, checkpoint, evidence):
            if reconciliation_guard is not None:
                reconciliation_guard(stream_id)
            capture = evidence.get("forward_capture_v1")
            selected = (
                evaluate_observation_gap
                if isinstance(capture, dict) and capture.get("eligibility") == "gap_recovery"
                else evaluator
            )
            return selected(
                token, checkpoint, evidence,
                dependency_manifest=state.dependency_manifest,
            )

        return ForwardReferenceService(repository, evaluate, commit_guard=reconciliation_commit_guard)

    def read_input(stream_id: str, kind: str, event_bar_end: datetime | None):
        if reconciliation_guard is not None:
            reconciliation_guard(stream_id)
        context = repository.forward_source_context(stream_id)
        if context is None:
            return None
        (identity, revision_id, generation, recording_start, computed_through,
         recovery_policy, prior_owner_id, prior_calculation_id) = context
        observed = cache.observed_at or now()
        after = (
            computed_through if computed_through is not None
            else recording_start - timedelta(microseconds=1)
        )
        common = dict(
            revision_id=revision_id, generation=generation, after=after, now=observed,
        )
        code = identity.strategy_code.replace("-", "_")
        try:
            if code == "htdy":
                return capture_htdy_live(
                    market_read, identity, wake_kind=kind,
                    event_bar_end=event_bar_end,
                    owner_segments=owner_segments, **common,
                )
            if code == "subing_reference":
                return capture_subing_live(
                    market_read, identity, wake_kind=kind,
                    owner_segments=owner_segments,
                    expected_endpoints=expected_endpoints,
                    event_bar_end=event_bar_end,
                    **common,
                )
            if code == "newow_dual_fusion":
                if fusion_sources is None:
                    raise ForwardInputUnavailable("REFERENCE_FUSION_SOURCES_UNAVAILABLE")
                return fusion_sources(identity, **common)
            if code.startswith("newow_"):
                if identity.frequency in LIVE_FREQUENCIES:
                    return capture_newow_live(
                        cached_live, identity, wake_kind=kind,
                        owner_segments=owner_segments,
                        expected_endpoints=expected_endpoints,
                        event_bar_end=event_bar_end,
                        capability_ready=newow_capability_ready, **common,
                    )
                if identity.frequency in {"1d", "1w"}:
                    if canonical_read_guard is None:
                        raise ForwardInputUnavailable("CANONICAL_READ_GUARD_MISSING")
                    with canonical_read_guard():
                        return capture_newow_canonical(
                            cache.canonical_reader(
                                newow_reader(identity) if callable(newow_reader) else newow_reader,
                                identity,
                            ),
                            identity, revision_id=revision_id,
                            generation=generation, after=computed_through,
                            recording_start=recording_start, now=observed,
                            capability_ready=newow_capability_ready,
                            prior_owner_segment_id=prior_owner_id,
                            prior_calculation_segment_id=prior_calculation_id,
                        )
        except ForwardInputUnavailable as error:
            if recovery_policy != "interrupt_and_restart" or str(error) not in {
                "OBSERVATION_GAP", "FIRST_SEEN_NOT_PROVEN",
            }:
                raise
            return capture_observation_gap(
                identity, revision_id=revision_id, generation=generation,
                previous_watermark=computed_through, observed_at=observed,
                reason=str(error), trading_day=error.trading_day,
                endpoints=error.endpoints,
            )
        raise ValueError("FORWARD_STRATEGY_UNSUPPORTED")

    return ForwardReferenceWorker(
        repository, service_for, read_input, enabled=enabled,
        begin_unit=lambda: cache.begin(now()), end_unit=cache.end,
    )


def build_historical_reference_planner(
    *, input_reader: HistoricalInputReader, repository: object | None = None,
    now: Callable | None = None,
) -> HistoricalReferencePlanner:
    return HistoricalReferencePlanner(input_reader, repository=repository, now=now)


@contextmanager
def open_historical_reference_components(*, session_factory=None, cancelled=lambda: False,
                                         after_batch=None, now=None, reuse_market_inputs=False):
    """Compose P4 from read-only MDS consumers and the P3 repository on demand."""
    from app.db.session import SessionLocal
    from app.market_data.catalog import MarketCatalog
    from app.market_data.composition import (
        build_database_coverage_source,
        build_market_data_service,
        canonical_root,
    )
    from app.market_data.newow.product_reader import NewowProductReader
    from app.market_data.newow.product_release import candidate_input_quality_policy
    from app.market_data.operational_universe import load_active_products
    from app.market_data.subing_reference import SubingReferenceService
    from app.reference_trading.inputs import MarketDataHistoricalInputReader
    from app.reference_trading.repository import ReferenceRepository
    from app.reference_trading.service import HistoricalReferenceService

    factory = session_factory or SessionLocal
    with factory() as session:
        market_data = build_market_data_service(session)
        coverage = build_database_coverage_source(session)
        products = load_active_products()
        catalog = MarketCatalog(session, canonical_root())

        @contextmanager
        def guard():
            lease = catalog.acquire_maintenance_lock()
            if lease is None:
                raise ValueError("SOURCE_BUSY")
            try:
                yield
            finally:
                lease.release()

        from app.reference_trading.history_input_cache import HistoricalMarketReadCache
        market_cache = HistoricalMarketReadCache(guard, cancelled=cancelled)

        def newow_for(identity):
            policy = candidate_input_quality_policy(
                identity.product.lower(), identity.frequency, candidate_weekly=False,
            )
            reader = NewowProductReader(
                market_data,
                coverage=coverage,
                active_products=products,
                cancelled=cancelled,
                input_quality_policy=policy,
            )
            return market_cache.reader(reader, policy_key=(policy.value, ())) if reuse_market_inputs else reader

        from app.reference_trading.newow_fusion import SavedFusionSources
        reader = MarketDataHistoricalInputReader(
            newow_reader=newow_for,
            subing_service=SubingReferenceService(
                market_data,
                coverage=coverage,
                active_products=products,
            ),
            read_guard=market_cache.guard if reuse_market_inputs else guard,
            pin_verified_inputs=True,
            compact_intraday_inputs=True,
            fusion_sources=SavedFusionSources(factory),
        )
        repository = ReferenceRepository(factory)
        planner = HistoricalReferencePlanner(reader, repository=repository, now=now)
        service = HistoricalReferenceService(repository, reader, cancelled=cancelled, after_batch=after_batch)
        if reuse_market_inputs:
            with market_cache.scope():
                yield planner, service
        else:
            yield planner, service
