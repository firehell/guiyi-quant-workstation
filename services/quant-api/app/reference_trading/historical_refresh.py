"""One bounded historical refresh thread within the observation worker lifecycle.

The durable control file is recovery state, never observation or Runtime evidence.
Unknown commits and interrupted processes require readback instead of blind retry.
"""
from __future__ import annotations

from app.reference_trading.recording_scope import FREQUENCIES, MAX_ROUTES, recording_route_supported

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
import fcntl
import json
import os
from pathlib import Path
from threading import Event, Thread

from guiyi_quant.reference_trading import RecordingMode

from app.reference_trading.planning import (
    HistoricalReferenceRequest, HistoricalStreamRequest, WorkBudget,
    _canonical_identity, plan_from_dict, plan_to_dict,
)
from app.reference_trading.service import ResumeToken

VERSION = 'newow_historical_refresh_v1'
STRATEGIES = ('trend', 'oscillation', 'main_rise', 'dual_fusion')
BUDGET = WorkBudget(1, 500_000, 1800, 512_000_000)


def _strategy(identity):
    return identity.strategy_code.replace('-', '_').removeprefix('newow_')


def _reason(error):
    value = str(error)
    return value if len(value) <= 100 and value.replace('_', '').isalnum() else 'REFRESH_FAILED_READBACK_REQUIRED'


@dataclass(frozen=True)
class RefreshRoute:
    identity: object
    since: date | None
    computed_through: datetime | None
    reason: str | None = None

    @property
    def key(self):
        return (self.identity.product, FREQUENCIES.index(self.identity.frequency),
                STRATEGIES.index(_strategy(self.identity)))


class RefreshStateStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self):
        if not self.path.exists():
            return {'version': VERSION, 'cursor': '', 'routes': {}}
        if self.path.is_symlink() or self.path.stat().st_size > 64_000_000:
            raise ValueError('REFRESH_STATE_INVALID')
        value = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or set(value) != {'version', 'cursor', 'routes'}
                or value['version'] != VERSION or not isinstance(value['cursor'], str)
                or not isinstance(value['routes'], dict) or len(value['routes']) > MAX_ROUTES):
            raise ValueError('REFRESH_STATE_INVALID')
        for stream_id, item in value['routes'].items():
            if (not isinstance(stream_id, str) or not isinstance(item, dict)
                    or item.get('status') not in {'pending', 'inflight', 'blocked'}):
                raise ValueError('REFRESH_STATE_INVALID')
        return value

    def write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError('REFRESH_STATE_INVALID')
        data = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        if len(data) > 64_000_000:
            raise ValueError('REFRESH_STATE_BUDGET_EXCEEDED')
        temporary = self.path.with_name(self.path.name + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def exclusive(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            yield True
        finally:
            os.close(fd)


class HistoricalRefresh:
    def __init__(self, *, routes, endpoint, components, state):
        self._routes, self._endpoint, self._components = routes, endpoint, components
        self.state = state

    def tick(self, *, now, cancelled=lambda: False):
        if cancelled():
            return
        with self.state.exclusive() as acquired:
            if acquired:
                self._tick(now, cancelled)

    def _tick(self, now, cancelled):
        state = self.state.read()
        # An unknown process exit may have happened between a commit and its
        # callback. A saved older resume token cannot prove the last outcome.
        for item in state['routes'].values():
            if item['status'] == 'inflight':
                item.update(status='blocked', reason='REFRESH_READBACK_REQUIRED')
        self.state.write(state)
        routes = sorted(self._routes(), key=lambda route: route.key)
        if len(routes) > MAX_ROUTES:
            raise ValueError('REFRESH_SCOPE_INVALID')
        ids = [route.identity.stream_id for route in routes]
        offset = ids.index(state['cursor']) + 1 if state['cursor'] in ids else 0
        endpoints = {}
        for route in (routes[offset:] + routes[:offset])[:32]:
            identity = route.identity
            key = identity.stream_id
            prior = state['routes'].get(key)
            if prior and prior['status'] == 'blocked':
                continue
            state['cursor'] = key
            if (route.reason and not prior) or not _canonical_identity(identity) or route.since is None:
                state['routes'][key] = {'status': 'blocked', 'reason': route.reason or 'SOURCE_IDENTITY_UNVERIFIED'}
                self.state.write(state)
                return
            try:
                endpoint_key = (identity.product, identity.frequency)
                if endpoint_key not in endpoints:
                    endpoints[endpoint_key] = self._endpoint(route, now)
                endpoint, trading_day = endpoints[endpoint_key]
                if (endpoint.tzinfo is None or endpoint > now or type(trading_day) is not date):
                    raise ValueError('AUTHORITATIVE_ENDPOINT_UNAVAILABLE')
                if not prior and route.computed_through is not None and endpoint <= route.computed_through:
                    continue
                if _strategy(identity) == 'dual_fusion':
                    base = [item for item in routes if item.identity.product == identity.product
                            and item.identity.frequency == identity.frequency
                            and _strategy(item.identity) != 'dual_fusion']
                    if (len(base) != 3 or any(item.computed_through is None or item.computed_through < endpoint
                                            for item in base)):
                        continue
                self._execute(route, endpoint, trading_day, prior, state, now, cancelled)
            except Exception as error:
                reason = _reason(error)
                if reason != 'SOURCE_BUSY':
                    state['routes'][key] = {'status': 'blocked', 'reason': reason}
                    self.state.write(state)
            return  # One selected stream per tick, even when planning fails.
        self.state.write(state)

    def _execute(self, route, endpoint, trading_day, prior, state, now, cancelled):
        key = route.identity.stream_id
        def after_batch(stage, context):
            if stage == 'committed' and context.get('resume_token'):
                state['routes'][key]['resume'] = asdict(context['resume_token'])
                self.state.write(state)  # Still inflight until a known report.
        with self._components(cancelled=cancelled, after_batch=after_batch,
                              now=lambda: now) as (planner, service):
            if prior:
                plan = plan_from_dict(prior['plan'])
                if (len(plan.streams) != 1 or plan.streams[0].request.identity != route.identity
                        or plan.streams[0].request.since != route.since):
                    raise ValueError('REFRESH_PLAN_SCOPE_DRIFT')
                if prior.get('rebuild_required'):
                    # Rebuild only the exact same endpoint and source already
                    # proven by the failed append plan. Never shrink its prefix.
                    replacement = planner.plan(HistoricalReferenceRequest(
                        'rebuild', (plan.streams[0].request,), BUDGET,
                    ))
                    before, after = plan.streams[0], replacement.streams[0]
                    if (before.source_token != after.source_token
                            or before.input_manifest_sha256 != after.input_manifest_sha256
                            or before.target_completed_through != after.target_completed_through):
                        raise ValueError('SOURCE_CHANGED')
                    plan, prior = replacement, None
            else:
                plan = planner.plan(HistoricalReferenceRequest(
                    'advance', (HistoricalStreamRequest(route.identity, route.since,
                                                        trading_day, endpoint),), BUDGET,
                ))
                if plan.streams[0].target_completed_through != endpoint:
                    raise ValueError('AUTHORITATIVE_ENDPOINT_CONFLICT')
            pending = {'status': 'inflight', 'reason': None, 'plan': plan_to_dict(plan)}
            if prior and prior.get('resume'):
                pending['resume'] = prior['resume']
            state['routes'][key] = pending
            self.state.write(state)  # Must be durable before any repository mutation.
            if cancelled():
                pending['status'] = 'pending'
                self.state.write(state)
                return
            if pending.get('resume'):
                token = ResumeToken(**pending['resume'])
                report = service.resume(plan, token, plan.plan_hash)
            else:
                report = getattr(service, plan.operation)(plan, plan.plan_hash)
            if len(report.streams) != 1:
                raise ValueError('REFRESH_REPORT_INVALID')
            result = report.streams[0]
            if result.status in {'completed', 'noop'}:
                del state['routes'][key]
            elif result.reason == 'SOURCE_BUSY' and plan.operation == 'advance':
                pending.update(status='pending', reason='SOURCE_BUSY')
            elif result.reason == 'REBUILD_REQUIRED' and plan.operation == 'advance':
                pending.update(status='pending', rebuild_required=True, reason='REBUILD_REQUIRED')
            elif result.status == 'partial' and result.reason == 'INTERRUPTED' and (
                result.resume_token is not None or plan.operation == 'advance'
            ):
                pending.update(status='pending', reason='INTERRUPTED')
                if result.resume_token:
                    pending['resume'] = asdict(result.resume_token)
            else:
                pending.update(status='blocked', reason=result.reason or 'REFRESH_FAILED_READBACK_REQUIRED')
            self.state.write(state)


class RefreshThread:
    """Single cancellable worker; foreground observation never joins each tick."""
    def __init__(self, runner, *, interval=30, now=lambda: datetime.now(UTC)):
        self._runner, self._interval, self._now = runner, interval, now
        self._stop = Event()
        self.last_error = None
        # Cancellation normally completes shutdown. Daemon is a bounded final
        # exit fallback; any unfinished mutation stays inflight and blocks restart.
        self._started = False
        self._thread = Thread(target=self._run, name='newow-historical-refresh', daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                self._runner.tick(now=self._now(), cancelled=self._stop.is_set)
            except Exception as error:
                self.last_error = _reason(error)
                return  # Invalid state/storage never gets blindly overwritten.
            self._stop.wait(self._interval)

    def start(self):
        self._thread.start()
        self._started = True

    def stop(self, *, timeout=5):
        self._stop.set()
        if self._started:
            self._thread.join(timeout)

    def is_alive(self):
        return self._thread.is_alive()


def build_historical_refresh(session_factory, *, state_path):
    """Only metadata and one authoritative endpoint are read before full planning.

    Each callback creates its own session in the refresh thread. No MDS, Session,
    Redis client or canonical lease crosses from the foreground worker.
    """
    from sqlalchemy import select
    from app.db.readonly import readonly_transaction
    from app.reference_trading.models import ReferenceStream, ReferenceRevision, ReferenceBatch
    from app.reference_trading.repository import _identity_from_row
    from app.reference_trading.composition import open_historical_reference_components
    from app.market_data.operational_universe import load_operational_products, load_active_products
    from app.reference_trading.newow_bootstrap import validate_product_scope
    products = validate_product_scope(load_operational_products(), load_active_products())

    def routes():
        with session_factory() as session, readonly_transaction(session, timeout_seconds=15):
            rows = session.scalars(select(ReferenceStream).where(
                ReferenceStream.recording_mode == RecordingMode.FORWARD_OBSERVATION.value,
                ReferenceStream.enabled.is_(True), ReferenceStream.product.in_(products),
                ReferenceStream.frequency.in_(FREQUENCIES),
            )).all()
            identities = [_identity_from_row(row) for row in rows
                          if recording_route_supported(_strategy(_identity_from_row(row)), row.frequency)]
        historical = [replace(identity, recording_mode=RecordingMode.HISTORICAL_REPLAY,
                              observation_policy_version=None) for identity in identities]
        with session_factory() as session, readonly_transaction(session, timeout_seconds=15):
            # Fetch only the current endpoint and original query boundary. Reading
            # 720 strategy checkpoints/manifests here would replay history per tick.
            rows = session.execute(select(
                ReferenceStream.stream_id, ReferenceRevision.status,
                ReferenceBatch.computed_through,
                ReferenceBatch.dependency_manifest['query_since'].as_string(),
            ).join(ReferenceRevision, (ReferenceRevision.stream_id == ReferenceStream.stream_id)
                   & (ReferenceRevision.revision_id == ReferenceStream.active_revision_id))
              .join(ReferenceBatch, ReferenceBatch.batch_id == ReferenceRevision.checkpoint_batch_id)
              .where(ReferenceStream.stream_id.in_([item.stream_id for item in historical]))).all()
            stored = {row[0]: row[1:] for row in rows}
        result = []
        for identity in historical:
            value = stored.get(identity.stream_id)
            if value is None or value[2] is None:
                result.append(RefreshRoute(identity, None, None, 'HISTORY_SOURCE_MISSING'))
                continue
            status, watermark, since = value
            # SQLite drops timezone metadata; PostgreSQL retains it.
            if watermark is not None and watermark.tzinfo is None:
                watermark = watermark.replace(tzinfo=UTC)
            result.append(RefreshRoute(identity, date.fromisoformat(since), watermark,
                                       None if status == 'active' else 'HISTORY_NOT_PUBLISHED'))
        return result

    def endpoint(route, now):
        from app.market_data.composition import build_market_data_service
        from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery
        with session_factory() as session, readonly_transaction(session, timeout_seconds=15):
            page = build_market_data_service(session).query_page(SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT, route.identity.product, BarFrequency(route.identity.frequency),
                # Discover the Catalog-published tail, rather than requiring
                # historical coverage through wall-clock Live time. Prepared
                # Calendar/Session/MainMap facts do not publish Canonical bars.
                # _tick separately rejects a future endpoint; the planner then
                # validates the complete prefix through this exact endpoint.
                before=None, limit=1,
            ))
            if not page.bars:
                raise ValueError('AUTHORITATIVE_ENDPOINT_UNAVAILABLE')
            bar = page.bars[-1]
            return bar.bar_end, bar.trading_day

    @contextmanager
    def components(**kwargs):
        with open_historical_reference_components(
            session_factory=session_factory, reuse_market_inputs=True, **kwargs,
        ) as value:
            yield value

    return HistoricalRefresh(routes=routes, endpoint=endpoint, components=components,
                             state=RefreshStateStore(state_path))
