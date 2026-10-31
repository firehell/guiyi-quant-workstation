"""Exact pending-source retirement; no candidate deletion or retry of unknown writes."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256

from app.reference_trading.planning import (
    HistoricalReferenceRequest, HistoricalStreamRequest, canonical_sha256,
    plan_from_dict,
)
from app.reference_trading.service import ResumeToken, verify_seed_only_resume


def _progress(repository, state):
    from sqlalchemy import select, func
    from app.reference_trading.models import ReferenceBatch
    with repository._session_factory() as session:
        maximum = session.scalar(select(func.max(ReferenceBatch.seq)).where(
            ReferenceBatch.stream_id == state.stream.stream_id,
            ReferenceBatch.revision_id == state.revision_id))
    receipt = repository.read_batch(state.stream.stream_id, state.revision_id, state.checkpoint_batch_key)
    if (maximum != state.checkpoint.seq or receipt is None or receipt.seq != state.checkpoint.seq
            or receipt.checkpoint_hash != state.checkpoint.state_hash):
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    return {'max_committed_seq': maximum, 'last_receipt': asdict(receipt)}


def _manifest_readback(manifest):
    from app.reference_trading.plan_bundle import canonical_size_digest

    size, digest = canonical_size_digest(manifest)
    return {'schema': 'reference_manifest_canonical_digest_v1',
            'canonical_bytes': size, 'sha256': digest}


def _state_readback(state, *, manifest_proof=None):
    return {
        'stream': asdict(state.stream),
        'revision_id': state.revision_id,
        'revision_status': state.revision_status,
        'dependency_manifest': manifest_proof or _manifest_readback(state.dependency_manifest),
        'dependency_digest': state.dependency_digest,
        'checkpoint': asdict(state.checkpoint),
        'checkpoint_batch_key': state.checkpoint_batch_key,
        'source_evidence': deepcopy(state.source_evidence),
    }


def _plan_wire_shared_manifest(plan):
    """Encode the established plan wire without copying its large manifest."""
    from app.reference_trading.planning import _wire

    return {
        'schema_version': plan.schema_version,
        'operation': plan.operation,
        'streams': [
            {
                'request': _wire(item.request),
                'storage_start': item.storage_start.isoformat(),
                'target_completed_through': item.target_completed_through.isoformat(),
                'input_count': item.input_count,
                'input_bytes': item.input_bytes,
                'input_manifest': item.input_manifest,
                'input_manifest_sha256': item.input_manifest_sha256,
                'dependency_digest': item.dependency_digest,
                'source_token': item.source_token,
            }
            for item in plan.streams
        ],
        'budget': _wire(plan.budget),
        'batch_size': plan.batch_size,
        'plan_hash': plan.plan_hash,
    }


@contextmanager
def _verified_plan_input(item, service):
    """Keep the one authoritative source pin through the recovery decision."""
    reader = service._reader
    with ExitStack() as inputs:
        verified_pin = getattr(reader, 'pin_verified_stream', None)
        if callable(verified_pin):
            inputs.enter_context(verified_pin(
                item.request, expected_manifest=item.input_manifest,
                expected_source_token=item.source_token,
            ))
        inputs.enter_context(reader.source_guard(
            item.request, expected_source_token=item.source_token,
        ))
        snapshot = reader.load_stream(item.request, expected_source_token=item.source_token)
        release = getattr(reader, 'release_snapshot', None)
        if callable(release):
            inputs.callback(release, snapshot)
        if not service._snapshot_matches(item, snapshot):
            raise ValueError('SOURCE_CHANGED')
        yield


_FUSION_PROOF_UPGRADE = 'newow_fusion_saved_source_proof_upgrade_v1'
_LEGACY_FUSION_SOURCE_READERS = frozenset({
    'newow_product_reader_v1', 'newow_product_reader_v2',
    'newow_product_reader_intraday_v3', 'newow_product_reader_prefix_v4',
})


def _legacy_fusion_proof_upgrade(route, old_plan):
    from app.reference_trading.historical_refresh import _history_route_supported

    old = old_plan.streams[0]
    manifest = old.input_manifest
    return (route.reason in {'INPUT_PROOF_UPGRADE_REQUIRED', 'CANONICAL_SOURCE_REVISION_CHANGED'}
            and route.identity.strategy_code == 'newow_dual_fusion'
            and _history_route_supported(route.identity)
            and _legacy_fusion_manifest(manifest))


def _legacy_fusion_manifest(manifest):
    reader = manifest.get('reader')
    source_reader = manifest.get('source_reader')
    if reader == 'newow_fusion_saved_sources_v1' and source_reader is None:
        source_reader = 'newow_product_reader_intraday_v3'
    return (reader in {'newow_fusion_saved_sources_v1', 'newow_fusion_saved_sources_v2'}
            and source_reader in _LEGACY_FUSION_SOURCE_READERS
            and (reader == 'newow_fusion_saved_sources_v1'
                 or isinstance(manifest.get('source_input_fingerprints'), list))
            and not isinstance(manifest.get('source_input_fingerprints'), dict))


def _proof_upgrade_record(old, new):
    manifest = old.input_manifest
    source_reader = manifest.get('source_reader')
    if manifest.get('reader') == 'newow_fusion_saved_sources_v1' and source_reader is None:
        source_reader = 'newow_product_reader_intraday_v3'
    return {
        'policy': _FUSION_PROOF_UPGRADE,
        'old_reader': manifest['reader'], 'old_source_reader': source_reader,
        'old_target_completed_through': old.target_completed_through.isoformat(),
        'old_frozen_source_token': old.source_token,
        'new_reader': new.input_manifest['reader'],
        'new_source_reader': new.input_manifest['source_reader'],
        'new_target_completed_through': new.target_completed_through.isoformat(),
        'new_rebuild_source_token': new.source_token,
    }


def _readback(repository, old_plan, prior, *, proof_upgrade_route=None):
    item = old_plan.streams[0]
    stream_id = item.request.identity.stream_id
    active = repository.read_state(stream_id)
    if proof_upgrade_route is not None:
        expected_status = ('invalid' if proof_upgrade_route.reason == 'CANONICAL_SOURCE_REVISION_CHANGED'
                           else 'active')
        if (active.revision_status != expected_status
                or active.stream.stream_id != stream_id
                or active.stream.active_revision_id != active.revision_id
                or active.stream.latest_seq != active.checkpoint.seq
                or active.dependency_manifest.get('query_since') != proof_upgrade_route.since.isoformat()
                or not _legacy_fusion_manifest(active.dependency_manifest)):
            raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    result = {'active': _state_readback(active), 'active_progress': _progress(repository, active)}
    resume = prior.get('resume')
    if resume is None:
        if (old_plan.operation != 'advance' or not (prior.get('rebuild_required') is True
                or prior.get('reason') in {'INTERRUPTED', 'SOURCE_BUSY'})):
            raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
        if active.revision_status not in {'active', 'invalid'}:
            raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
        return result
    del active
    token = ResumeToken(**resume)
    if (token.plan_hash != old_plan.plan_hash or token.stream_id != stream_id
            or token.source_token != item.source_token or old_plan.operation not in {'build', 'rebuild'}):
        raise ValueError('REFRESH_RECOVERY_RESUME_CONFLICT')
    saved = repository.read_state(stream_id, token.revision_id)
    saved_manifest_proof = _manifest_readback(saved.dependency_manifest)
    checkpoint, decoded = repository.load_checkpoint(stream_id, token.revision_id)
    seed_only = saved.checkpoint_batch_key.startswith('seed-seal:')
    if (saved.revision_status != 'candidate' or saved.stream.active_revision_id == token.revision_id
            or saved.dependency_digest != item.dependency_digest
            or saved_manifest_proof['sha256'] != item.dependency_digest
            or saved.dependency_manifest != item.input_manifest
            or saved.checkpoint != checkpoint or decoded.stream != item.request.identity
            or (not seed_only and saved.checkpoint_batch_key != token.last_batch_key)):
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    receipt = repository.read_batch(stream_id, token.revision_id, saved.checkpoint_batch_key)
    if (receipt is None or receipt.seq != checkpoint.seq
            or receipt.checkpoint_hash != checkpoint.state_hash):
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    if seed_only:
        try:
            verify_seed_only_resume(
                old_plan.plan_hash, stream_id, token, saved, checkpoint, receipt,
            )
        except ValueError as error:
            raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED') from error
    elif token.last_batch_key.startswith('seed:'):
        # A seed-only claim cannot authenticate a later calculation checkpoint.
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    elif saved.source_evidence.get('end_input_index') != token.next_input_index:
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    result['candidate'] = _state_readback(saved, manifest_proof=saved_manifest_proof)
    result['candidate_progress'] = _progress(repository, saved)
    return result


@contextmanager
def prepare_source_recovery(route, prior, old_plan, *, planner, service, endpoint, trading_day,
                            route_recheck=None):
    """Dry-run proof held under the new source guard until caller installs it.

    Caller owns the refresh-state exclusive lock and native component scope.
    A legacy Fusion proof-format upgrade uses the current authoritative request
    and exact old readback; all other routes require OLD-request revalidation.
    """
    if (prior.get('status') != 'pending' or prior.get('reason') not in {None, 'INTERRUPTED', 'SOURCE_BUSY', 'REBUILD_REQUIRED'}
            or len(old_plan.streams) != 1 or old_plan.streams[0].request.identity != route.identity
            or old_plan.streams[0].request.since != route.since):
        raise ValueError('REFRESH_RECOVERY_NOT_ELIGIBLE')
    old = old_plan.streams[0]
    proof_upgrade = _legacy_fusion_proof_upgrade(route, old_plan)
    if proof_upgrade:
        if (route_recheck is None
                or [fresh for fresh in route_recheck()
                    if fresh.identity.stream_id == route.identity.stream_id] != [route]):
            raise ValueError('REFRESH_RECOVERY_ROUTE_CHANGED')
        if (route.computed_through is None or endpoint < route.computed_through
                or endpoint < old.target_completed_through):
            raise ValueError('AUTHORITATIVE_ENDPOINT_CONFLICT')
        before = _readback(service._repository, old_plan, prior, proof_upgrade_route=route)
    else:
        observed = planner.plan(HistoricalReferenceRequest('rebuild', (old.request,), old_plan.budget))
        observed_source_token = observed.streams[0].source_token
        del observed
        if observed_source_token == old.source_token:
            yield None
            return
        before = _readback(service._repository, old_plan, prior)
    new_plan = planner.plan(HistoricalReferenceRequest('rebuild', (
        HistoricalStreamRequest(route.identity, route.since, trading_day, endpoint),), old_plan.budget))
    if len(new_plan.streams) != 1:
        raise ValueError('AUTHORITATIVE_ENDPOINT_CONFLICT')
    new = new_plan.streams[0]
    if (new_plan.operation != 'rebuild'
            or new.request.identity != route.identity or new.request.since != route.since
            or new.request.through != trading_day or new.request.as_of != endpoint
            or new.target_completed_through != endpoint
            or proof_upgrade and (
                new.input_manifest.get('reader') != 'newow_fusion_saved_sources_v3'
                or new.input_manifest.get('source_reader') != 'newow_product_reader_prefix_v5'
                or new.source_token == old.source_token)):
        raise ValueError('AUTHORITATIVE_ENDPOINT_CONFLICT')
    with _verified_plan_input(new, service):
        after = _readback(service._repository, old_plan, prior,
                          proof_upgrade_route=route if proof_upgrade else None)
        if before != after:
            raise ValueError('REFRESH_RECOVERY_READBACK_CHANGED')
        value = {'version': ('reference_refresh_fusion_proof_upgrade_v1' if proof_upgrade
                             else 'reference_refresh_source_recovery_v2'),
                 'stream_id': route.identity.stream_id, 'prior': prior,
                 'old_plan': _plan_wire_shared_manifest(old_plan), 'old_plan_hash': old_plan.plan_hash,
                 'readback': before, 'readback_sha256': canonical_sha256(before),
                 'new_plan': _plan_wire_shared_manifest(new_plan), 'new_plan_hash': new_plan.plan_hash}
        if proof_upgrade:
            value['proof_upgrade'] = _proof_upgrade_record(old, new)
        else:
            value['source_change'] = {'old': old.source_token, 'current': observed_source_token}
        yield value


def _planning_failure_readback(repository, route, endpoint):
    """Prove the existing published checkpoint and absence of an unknown candidate."""
    from sqlalchemy import select
    from datetime import UTC
    from app.reference_trading.models import ReferenceBatch, ReferenceRevision

    stream_id = route.identity.stream_id
    active = repository.read_state(stream_id)
    if (active.revision_status not in {'active', 'invalid'}
            or active.stream.stream_id != stream_id
            or active.stream.active_revision_id != active.revision_id
            or active.stream.latest_seq != active.checkpoint.seq
            or active.checkpoint.seq < 1
            or active.dependency_manifest.get('query_since') != route.since.isoformat()):
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    progress = _progress(repository, active)
    with repository._session_factory() as session:
        revisions = session.execute(select(
            ReferenceRevision.revision_id, ReferenceRevision.status,
            ReferenceRevision.last_seq, ReferenceRevision.checkpoint_batch_id,
            ReferenceRevision.dependency_digest,
        ).where(ReferenceRevision.stream_id == stream_id)
            .order_by(ReferenceRevision.revision_id)).all()
        active_rows = [row for row in revisions if row[0] == active.revision_id]
        if len(active_rows) != 1 or active_rows[0][3] is None:
            raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
        committed_through = session.execute(select(ReferenceBatch.computed_through).where(
            ReferenceBatch.batch_id == active_rows[0][3],
        )).scalar_one_or_none()
    if committed_through is not None and committed_through.tzinfo is None:
        committed_through = committed_through.replace(tzinfo=UTC)
    if (committed_through is None or committed_through != route.computed_through
            or endpoint < committed_through):
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    if (not revisions or any(row[1] == 'candidate' for row in revisions)
            or not any(row[0] == active.revision_id
                       and row[1] == active.revision_status
                       and row[2] == active.checkpoint.seq
                       for row in revisions)):
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    return {
        'active': _state_readback(active), 'active_progress': progress,
        'revisions': [list(row) for row in revisions],
    }


def _archive_recovery(store, recovery):
    from app.reference_trading.plan_bundle import canonical_size_digest, read_plan, write_plan

    size, digest = canonical_size_digest(recovery)
    target = store.path.with_name(store.path.name + '.recovery-' + digest + '.json')
    if target.exists():
        if canonical_size_digest(read_plan(target, trusted_root=store.path.parent)) != (size, digest):
            raise ValueError('REFRESH_RECOVERY_ARCHIVE_CONFLICT')
    else:
        write_plan(target, recovery, trusted_root=store.path.parent)
    if canonical_size_digest(read_plan(target, trusted_root=store.path.parent)) != (size, digest):
        raise ValueError('REFRESH_RECOVERY_ARCHIVE_CONFLICT')
    return digest


def install_source_recovery(store, state, recovery):
    """CAS state only after immutable archival; never mutates saved candidates."""
    stream_id = recovery['stream_id']
    current = store.read()
    if (current['version'] != state['version'] or current['routes'] != state['routes']
            or current['routes'].get(stream_id) != recovery['prior']):
        raise ValueError('REFRESH_RECOVERY_STATE_CHANGED')
    old = plan_from_dict(recovery['old_plan'])
    new = plan_from_dict(recovery['new_plan'])
    if (old.plan_hash != recovery['old_plan_hash'] or new.plan_hash != recovery['new_plan_hash']
            or old.streams[0].request.identity != new.streams[0].request.identity
            or old.streams[0].request.since != new.streams[0].request.since or new.operation != 'rebuild'):
        raise ValueError('REFRESH_RECOVERY_PLAN_CONFLICT')
    if recovery.get('version') == 'reference_refresh_fusion_proof_upgrade_v1':
        old_item, new_item = old.streams[0], new.streams[0]
        expected_upgrade = _proof_upgrade_record(old_item, new_item)
        if (set(recovery) != {'version', 'stream_id', 'prior', 'old_plan', 'old_plan_hash',
                             'readback', 'readback_sha256', 'new_plan', 'new_plan_hash',
                             'proof_upgrade'}
                or recovery.get('proof_upgrade') != expected_upgrade
                or expected_upgrade['policy'] != _FUSION_PROOF_UPGRADE
                or old_item.request.identity.strategy_code != 'newow_dual_fusion'
                or not _legacy_fusion_manifest(old_item.input_manifest)
                or expected_upgrade['new_reader'] != 'newow_fusion_saved_sources_v3'
                or expected_upgrade['new_source_reader'] != 'newow_product_reader_prefix_v5'
                or old_item.target_completed_through > new_item.target_completed_through
                or old_item.source_token == new_item.source_token):
            raise ValueError('REFRESH_RECOVERY_PLAN_CONFLICT')
    digest = _archive_recovery(store, recovery)
    state['routes'][stream_id] = {'status': 'pending', 'reason': None,
        'plan': store.store_plan(recovery['new_plan']), 'recovery_archive_sha256': digest}
    store.write(state)
    return new


def install_planning_failure_recovery(store, state, recovery):
    """Archive one known pre-plan failure before installing a native pending plan."""
    if (not isinstance(recovery, dict) or set(recovery) != {
            'version', 'stream_id', 'prior',
            'readback', 'readback_sha256', 'since', 'endpoint', 'trading_day',
            'new_plan', 'new_plan_hash',
        } or recovery['version'] != 'reference_refresh_planning_failure_recovery_v1'
            or recovery['prior'] != {
                'status': 'blocked', 'reason': 'REFERENCE_BUDGET_EXCEEDED',
            } or canonical_sha256(recovery['readback']) != recovery['readback_sha256']):
        raise ValueError('REFRESH_RECOVERY_PLAN_CONFLICT')
    stream_id = recovery['stream_id']
    current = store.read()
    if current != state or current['routes'].get(stream_id) != recovery['prior']:
        raise ValueError('REFRESH_RECOVERY_STATE_CHANGED')
    # This byte guard covers non-cooperating writers during this one locked
    # apply; it is deliberately absent from the dry-run recovery identity.
    if not store.path.exists():
        raise ValueError('REFRESH_RECOVERY_STATE_CHANGED')
    state_bytes_sha256 = sha256(store.path.read_bytes()).hexdigest()
    plan = plan_from_dict(recovery['new_plan'])
    if (plan.plan_hash != recovery['new_plan_hash'] or plan.operation != 'rebuild'
            or len(plan.streams) != 1
            or plan.streams[0].request.identity.stream_id != stream_id
            or recovery['readback']['active']['stream']['stream_id'] != stream_id
            or plan.streams[0].request.since.isoformat() != recovery['since']
            or plan.streams[0].request.through.isoformat() != recovery['trading_day']
            or plan.streams[0].target_completed_through.isoformat() != recovery['endpoint']):
        raise ValueError('REFRESH_RECOVERY_PLAN_CONFLICT')
    digest = _archive_recovery(store, recovery)
    if (not store.path.exists()
            or sha256(store.path.read_bytes()).hexdigest() != state_bytes_sha256):
        raise ValueError('REFRESH_RECOVERY_STATE_CHANGED')
    updated = deepcopy(current)
    plan_ref = store.store_plan(recovery['new_plan'])
    if (not store.path.exists()
            or sha256(store.path.read_bytes()).hexdigest() != state_bytes_sha256):
        raise ValueError('REFRESH_RECOVERY_STATE_CHANGED')
    updated['routes'][stream_id] = {
        'status': 'pending', 'reason': None,
        'plan': plan_ref,
        'recovery_archive_sha256': digest,
    }
    store.write(updated)
    return plan


def recover_blocked_planning(runner, stream_id, *, now, apply=False,
                             expected_recovery_sha256=None, cancelled=lambda: False):
    """Dry-run/CAS one Newow budget failure that occurred before any plan existed."""
    from datetime import date
    from app.reference_trading.historical_refresh import BUDGET, _history_route_supported, _strategy

    with runner.state.exclusive() as acquired:
        if not acquired:
            raise ValueError('SOURCE_BUSY')
        state = runner.state.read()
        prior = state['routes'].get(stream_id)
        if prior != {'status': 'blocked', 'reason': 'REFERENCE_BUDGET_EXCEEDED'}:
            raise ValueError('REFRESH_RECOVERY_NOT_ELIGIBLE')
        routes = [route for route in runner._routes() if route.identity.stream_id == stream_id]
        if len(routes) != 1:
            raise ValueError('REFRESH_RECOVERY_SCOPE_CONFLICT')
        route = routes[0]
        if (not _history_route_supported(route.identity)
                or _strategy(route.identity) not in {'trend', 'oscillation', 'main_rise', 'dual_fusion'}
                or route.since is None or route.computed_through is None
                or route.reason not in {None, 'INPUT_PROOF_UPGRADE_REQUIRED',
                                         'CANONICAL_SOURCE_REVISION_CHANGED'}):
            raise ValueError('REFRESH_RECOVERY_NOT_ELIGIBLE')
        endpoint, trading_day = runner._endpoint(route, now)
        if (endpoint.tzinfo is None or endpoint.utcoffset() is None
                or endpoint > now or type(trading_day) is not date):
            raise ValueError('AUTHORITATIVE_ENDPOINT_UNAVAILABLE')
        with runner._components(cancelled=cancelled, now=lambda: now) as (planner, service):
            if [fresh for fresh in runner._routes()
                    if fresh.identity.stream_id == stream_id] != [route]:
                raise ValueError('REFRESH_RECOVERY_ROUTE_CHANGED')
            before = _planning_failure_readback(service._repository, route, endpoint)
            plan = planner.plan(HistoricalReferenceRequest(
                'rebuild', (HistoricalStreamRequest(
                    route.identity, route.since, trading_day, endpoint,
                ),), BUDGET,
            ))
            item = plan.streams[0]
            if (len(plan.streams) != 1 or item.request.identity != route.identity
                    or item.request.since != route.since
                    or item.target_completed_through != endpoint):
                raise ValueError('AUTHORITATIVE_ENDPOINT_CONFLICT')
            with _verified_plan_input(item, service):
                after = _planning_failure_readback(service._repository, route, endpoint)
                if before != after:
                    raise ValueError('REFRESH_RECOVERY_READBACK_CHANGED')
                recovery = {
                    'version': 'reference_refresh_planning_failure_recovery_v1',
                    'stream_id': stream_id, 'prior': deepcopy(prior),
                    'readback': before, 'readback_sha256': canonical_sha256(before),
                    'since': route.since.isoformat(),
                    'endpoint': endpoint.isoformat(), 'trading_day': trading_day.isoformat(),
                    'new_plan': _plan_wire_shared_manifest(plan),
                    'new_plan_hash': plan.plan_hash,
                }
                digest = canonical_sha256(recovery)
                if apply:
                    if expected_recovery_sha256 != digest:
                        raise ValueError('REFRESH_RECOVERY_HASH_CONFLICT')
                    install_planning_failure_recovery(runner.state, state, recovery)
                return {
                    'status': 'installed' if apply else 'ready',
                    'recovery_sha256': digest, 'recovery': recovery,
                }


def recover_pending_source(runner, stream_id, *, now, apply=False, expected_recovery_sha256=None):
    """Bounded manual dry-run/apply using the SAME path as the existing worker.

    Apply only installs the new frozen intent; the native worker/service executes
    it subsequently. No repository write occurs here. Unknown work is ineligible.
    """
    with runner.state.exclusive() as acquired:
        if not acquired:
            raise ValueError('SOURCE_BUSY')
        state = runner.state.read()
        prior = state['routes'].get(stream_id)
        if prior is None:
            raise ValueError('REFRESH_RECOVERY_INTENT_MISSING')
        routes = [route for route in runner._routes() if route.identity.stream_id == stream_id]
        if len(routes) != 1:
            raise ValueError('REFRESH_RECOVERY_SCOPE_CONFLICT')
        route = routes[0]
        old = plan_from_dict(runner.state.read_plan(prior['plan']))
        endpoint, trading_day = runner._endpoint(route, now)
        if endpoint.tzinfo is None or endpoint > now:
            raise ValueError('AUTHORITATIVE_ENDPOINT_UNAVAILABLE')
        with runner._components(now=lambda: now) as (planner, service):
            with prepare_source_recovery(route, prior, old, planner=planner, service=service,
                                         endpoint=endpoint, trading_day=trading_day,
                                         route_recheck=runner._routes) as recovery:
                if recovery is None:
                    return {'status': 'source_unchanged', 'stream_id': stream_id}
                digest = canonical_sha256(recovery)
                if apply:
                    if expected_recovery_sha256 != digest:
                        raise ValueError('REFRESH_RECOVERY_HASH_CONFLICT')
                    install_source_recovery(runner.state, state, recovery)
                return {'status': 'installed' if apply else 'ready',
                        'recovery_sha256': digest, 'recovery': recovery}
