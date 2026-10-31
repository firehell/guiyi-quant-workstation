"""Exact pending-source retirement; no candidate deletion or retry of unknown writes."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
import json

from app.reference_trading.planning import (
    HistoricalReferenceRequest, HistoricalStreamRequest, canonical_sha256,
    plan_from_dict, plan_to_dict,
)
from app.reference_trading.service import ResumeToken


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


def _readback(repository, old_plan, prior):
    item = old_plan.streams[0]
    stream_id = item.request.identity.stream_id
    active = repository.read_state(stream_id)
    result = {'active': asdict(active), 'active_progress': _progress(repository, active)}
    resume = prior.get('resume')
    if resume is None:
        if (old_plan.operation != 'advance' or not (prior.get('rebuild_required') is True
                or prior.get('reason') in {'INTERRUPTED', 'SOURCE_BUSY'})):
            raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
        if active.revision_status not in {'active', 'invalid'}:
            raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
        return result
    token = ResumeToken(**resume)
    if (token.plan_hash != old_plan.plan_hash or token.stream_id != stream_id
            or token.source_token != item.source_token or old_plan.operation not in {'build', 'rebuild'}):
        raise ValueError('REFRESH_RECOVERY_RESUME_CONFLICT')
    saved = repository.read_state(stream_id, token.revision_id)
    checkpoint, decoded = repository.load_checkpoint(stream_id, token.revision_id)
    if (saved.revision_status != 'candidate' or saved.stream.active_revision_id == token.revision_id
            or saved.dependency_digest != item.dependency_digest
            or saved.dependency_manifest != item.input_manifest
            or saved.checkpoint != checkpoint or decoded.stream != item.request.identity
            or saved.checkpoint_batch_key != token.last_batch_key):
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    receipt = repository.read_batch(stream_id, token.revision_id, token.last_batch_key)
    if (receipt is None or receipt.seq != checkpoint.seq
            or receipt.checkpoint_hash != checkpoint.state_hash):
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    if token.last_batch_key.startswith('seed:'):
        seed = json.dumps({'plan_hash': old_plan.plan_hash, 'stream_id': stream_id},
                          sort_keys=True, separators=(',', ':'))
        if (token.next_input_index != 0 or checkpoint.seq != 1
                or token.last_batch_key != 'seed:' + sha256(seed.encode()).hexdigest()):
            raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    elif saved.source_evidence.get('end_input_index') != token.next_input_index:
        raise ValueError('REFRESH_RECOVERY_READBACK_REQUIRED')
    result['candidate'] = asdict(saved)
    result['candidate_progress'] = _progress(repository, saved)
    return result


@contextmanager
def prepare_source_recovery(route, prior, old_plan, *, planner, service, endpoint, trading_day):
    """Dry-run proof held under the new source guard until caller installs it.

    Caller owns the refresh-state exclusive lock and native component scope.
    Only a successful authoritative replan of the OLD request can establish a
    changed source; a timeout/missing input/False revalidate cannot establish it.
    """
    if (prior.get('status') != 'pending' or prior.get('reason') not in {None, 'INTERRUPTED', 'SOURCE_BUSY', 'REBUILD_REQUIRED'}
            or len(old_plan.streams) != 1 or old_plan.streams[0].request.identity != route.identity
            or old_plan.streams[0].request.since != route.since):
        raise ValueError('REFRESH_RECOVERY_NOT_ELIGIBLE')
    old = old_plan.streams[0]
    observed = planner.plan(HistoricalReferenceRequest('rebuild', (old.request,), old_plan.budget))
    if observed.streams[0].source_token == old.source_token:
        yield None
        return
    before = _readback(service._repository, old_plan, prior)
    new_plan = planner.plan(HistoricalReferenceRequest('rebuild', (
        HistoricalStreamRequest(route.identity, route.since, trading_day, endpoint),), old_plan.budget))
    new = new_plan.streams[0]
    if new.target_completed_through != endpoint:
        raise ValueError('AUTHORITATIVE_ENDPOINT_CONFLICT')
    reader = service._reader
    with reader.source_guard(new.request, expected_source_token=new.source_token):
        snapshot = reader.load_stream(new.request, expected_source_token=new.source_token)
        if not service._snapshot_matches(new, snapshot):
            raise ValueError('SOURCE_CHANGED')
        after = _readback(service._repository, old_plan, prior)
        if before != after:
            raise ValueError('REFRESH_RECOVERY_READBACK_CHANGED')
        value = {'version': 'reference_refresh_source_recovery_v1',
                 'stream_id': route.identity.stream_id, 'prior': prior,
                 'old_plan': plan_to_dict(old_plan), 'old_plan_hash': old_plan.plan_hash,
                 'readback': before, 'readback_sha256': canonical_sha256(before),
                 'source_change': {'old': old.source_token, 'current': observed.streams[0].source_token},
                 'new_plan': plan_to_dict(new_plan), 'new_plan_hash': new_plan.plan_hash}
        yield value


def install_source_recovery(store, state, recovery):
    """CAS state only after immutable archival; never mutates saved candidates."""
    from app.reference_trading.plan_bundle import canonical_bytes, read_plan, write_plan
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
    digest = sha256(canonical_bytes(recovery)).hexdigest()
    target = store.path.with_name(store.path.name + '.recovery-' + digest + '.json')
    if target.exists():
        if canonical_bytes(read_plan(target, trusted_root=store.path.parent)) != canonical_bytes(recovery):
            raise ValueError('REFRESH_RECOVERY_ARCHIVE_CONFLICT')
    else:
        write_plan(target, recovery, trusted_root=store.path.parent)
    if canonical_bytes(read_plan(target, trusted_root=store.path.parent)) != canonical_bytes(recovery):
        raise ValueError('REFRESH_RECOVERY_ARCHIVE_CONFLICT')
    state['routes'][stream_id] = {'status': 'pending', 'reason': None,
        'plan': store.store_plan(recovery['new_plan']), 'recovery_archive_sha256': digest}
    store.write(state)
    return new


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
                                         endpoint=endpoint, trading_day=trading_day) as recovery:
                if recovery is None:
                    return {'status': 'source_unchanged', 'stream_id': stream_id}
                digest = canonical_sha256(recovery)
                if apply:
                    if expected_recovery_sha256 != digest:
                        raise ValueError('REFRESH_RECOVERY_HASH_CONFLICT')
                    install_source_recovery(runner.state, state, recovery)
                return {'status': 'installed' if apply else 'ready',
                        'recovery_sha256': digest, 'recovery': recovery}
