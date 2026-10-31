"""One bounded historical refresh thread within the observation worker lifecycle.

The durable control file is recovery state, never observation or Runtime evidence.
Unknown commits and interrupted processes require readback instead of blind retry.
"""
from __future__ import annotations

from app.reference_trading.recording_scope import FREQUENCIES, MAX_ROUTES as NEWOW_MAX_ROUTES

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
import fcntl
import json
import os
import re
from pathlib import Path
from threading import Event, Thread
from time import monotonic

from guiyi_quant.reference_trading import RecordingMode, StreamIdentity

from app.reference_trading.planning import (
    HistoricalReferenceRequest, HistoricalStreamRequest, WorkBudget,
    _canonical_identity, plan_from_dict, plan_to_dict,
)
from app.reference_trading.service import ResumeToken
from app.reference_trading.refresh_plan_codec import (
    RefreshPlanCodecError, decode_plan, encode_plan, validate_encoded_plan,
)

MAX_REFRESH_STATE_BYTES = 64_000_000
VERSION = 'newow_historical_refresh_v1'
PLAN_FILE_CODEC = 'reference_refresh_plan_file_v1'
STRATEGIES = ('trend', 'oscillation', 'main_rise', 'dual_fusion', 'subing_reference')
MAX_ROUTES = NEWOW_MAX_ROUTES + 60 * 6
# Logical input volume stays capped; bounded Newow reads separately avoid full residency.
BUDGET = WorkBudget(1, 1_000_000, 1800, 512_000_000)
SUBING_BUDGET = WorkBudget(1, 2_000_000, 1800, 8_192_000_000)


def _strategy(identity):
    return identity.strategy_code.replace('-', '_').removeprefix('newow_')


def _reason(error):
    value = str(error)
    return value if len(value) <= 100 and value.replace('_', '').isalnum() else 'REFRESH_FAILED_READBACK_REQUIRED'


@dataclass(frozen=True)
class RefreshRoute:
    identity: StreamIdentity
    since: date | None
    computed_through: datetime | None
    reason: str | None = None

    @property
    def key(self):
        return (self.identity.product, FREQUENCIES.index(self.identity.frequency),
                STRATEGIES.index(_strategy(self.identity)))


class RefreshStateError(ValueError):
    """Storage failure stops processing without overwriting unknown commit evidence."""


class RefreshPlanningYield(RuntimeError):
    """Pure planning was cooperatively cancelled before formal service work."""


class RefreshStateStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self):
        if not self.path.exists():
            return {'version': VERSION, 'cursor': '', 'routes': {}}
        if self.path.is_symlink() or self.path.stat().st_size > MAX_REFRESH_STATE_BYTES:
            raise RefreshStateError('REFRESH_STATE_INVALID')
        value = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or set(value) != {'version', 'cursor', 'routes'}
                or value['version'] != VERSION or not isinstance(value['cursor'], str)
                or not isinstance(value['routes'], dict) or len(value['routes']) > MAX_ROUTES):
            raise RefreshStateError('REFRESH_STATE_INVALID')
        for stream_id, item in value['routes'].items():
            if (not isinstance(stream_id, str) or not isinstance(item, dict)
                    or item.get('status') not in {'pending', 'inflight', 'blocked'}):
                raise RefreshStateError('REFRESH_STATE_INVALID')
            if isinstance(item.get('plan'), dict) and 'codec' in item['plan']:
                try:
                    if item['plan']['codec'] == PLAN_FILE_CODEC:
                        self._validate_file_ref(item['plan'])
                    else:
                        validate_encoded_plan(item['plan'])
                except RefreshPlanCodecError as error:
                    raise RefreshStateError(str(error)) from error
        return value

    @staticmethod
    def _validate_file_ref(value):
        if (set(value) != {'codec', 'file', 'sha256'} or value['codec'] != PLAN_FILE_CODEC
                or not isinstance(value['sha256'], str) or re.fullmatch('[a-f0-9]{64}', value['sha256']) is None
                or value['file'] != value['sha256']+'.json'):
            raise RefreshPlanCodecError()

    def store_plan(self, value):
        from app.reference_trading.plan_bundle import canonical_size_digest, write_plan, read_plan, _parent
        if value.get('codec') == PLAN_FILE_CODEC:
            self._validate_file_ref(value)
            return value
        if 'codec' in value:
            validate_encoded_plan(value)
            return value
        size, digest = canonical_size_digest(value)
        if size <= 64_000:
            return encode_plan(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        folder = self.path.with_name(self.path.name+'.plans')
        with _parent(self.path) as (fd, name):
            try:
                os.mkdir(name+'.plans', mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            check = os.open(name+'.plans', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                try:
                    os.stat(digest+'.json', dir_fd=check, follow_symlinks=False)
                except FileNotFoundError:
                    exists = False
                else:
                    exists = True
            finally:
                os.close(check)
        target = folder/(digest+'.json')
        if exists:
            if canonical_size_digest(read_plan(target, trusted_root=self.path.parent))[1] != digest:
                raise RefreshPlanCodecError()
        else:
            write_plan(target, value, force_bundle=True, trusted_root=self.path.parent)
        return {'codec': PLAN_FILE_CODEC, 'file': digest+'.json', 'sha256': digest}

    def read_plan(self, value):
        if value.get('codec') != PLAN_FILE_CODEC:
            return decode_plan(value)
        from app.reference_trading.plan_bundle import canonical_size_digest, read_plan
        self._validate_file_ref(value)
        target = self.path.with_name(self.path.name+'.plans')/value['file']
        result = read_plan(target, trusted_root=self.path.parent)
        if canonical_size_digest(result)[1] != value['sha256']:
            raise RefreshPlanCodecError()
        return result

    def write(self, value):
        try:
            self._write(value)
        except OSError as error:
            raise RefreshStateError('REFRESH_STATE_WRITE_UNKNOWN') from error

    def _write(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise RefreshStateError('REFRESH_STATE_INVALID')
        # Encode a copy: callers retain full plans for committed callbacks.
        try:
            stored = {**value, 'routes': {key: ({**item, 'plan': self.store_plan(item['plan'])}
                if 'plan' in item else dict(item)) for key, item in value['routes'].items()}}
            data = json.dumps(stored, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        except (RefreshPlanCodecError, TypeError, ValueError) as error:
            raise RefreshStateError('REFRESH_STATE_INVALID') from error
        if len(data) > MAX_REFRESH_STATE_BYTES:
            raise RefreshStateError('REFRESH_STATE_BUDGET_EXCEEDED')
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
        except OSError as error:
            raise RefreshStateError('REFRESH_STATE_WRITE_UNKNOWN') from error
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
    def __init__(self, *, routes, endpoint, components, state,
                 needs_source_verification=None):
        self._routes, self._endpoint, self._components = routes, endpoint, components
        self._needs_source_verification = needs_source_verification
        self.state = state
        self.last_progress = {}

    def tick(self, *, now, cancelled=lambda: False, batch_limit=None):
        if batch_limit is not None and (type(batch_limit) is not int or batch_limit < 1):
            raise ValueError('REFRESH_BATCH_LIMIT_INVALID')
        if cancelled():
            return
        with self.state.exclusive() as acquired:
            if acquired:
                self._tick(now, cancelled, batch_limit)

    def _tick(self, now, cancelled, batch_limit):
        state = self.state.read()
        self.last_progress = {**self.last_progress,
            'backlog_count': sum(item['status'] != 'blocked' for item in state['routes'].values()),
            'blocked_route_count': sum(item['status'] == 'blocked' for item in state['routes'].values())}
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
            if cancelled():
                return
            previous_cursor = state['cursor']
            identity = route.identity
            key = identity.stream_id
            prior = state['routes'].get(key)
            # Persist scan progress even when this bounded page contains only
            # blocked streams; otherwise later routes starve forever.
            state['cursor'] = key
            if prior and prior['status'] == 'blocked':
                continue
            source_changed = route.reason in {'CANONICAL_SOURCE_REVISION_CHANGED', 'INPUT_PROOF_UPGRADE_REQUIRED'}
            if (route.reason and not source_changed and not prior) or not _canonical_identity(identity) or route.since is None:
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
                if not prior and not source_changed and route.computed_through is not None and endpoint <= route.computed_through:
                    if (self._needs_source_verification is None
                            or not self._needs_source_verification(route, now, cancelled)):
                        continue
                if _strategy(identity) == 'dual_fusion':
                    base = [item for item in routes if item.identity.product == identity.product
                            and item.identity.frequency == identity.frequency
                            and _strategy(item.identity) in {'trend', 'oscillation'}]
                    if (len(base) != 2 or any(item.reason is not None or item.computed_through is None
                                            or item.computed_through < endpoint for item in base)):
                        self.last_progress = {'at': now.isoformat(), 'stream_id': key,
                            'stage': 'waiting', 'reason': 'BASE_DEPENDENCIES_PENDING',
                            'target': endpoint.isoformat()}
                        continue
                self._execute(route, endpoint, trading_day, prior, state, now, cancelled, batch_limit)
            except RefreshPlanningYield:
                state['cursor'] = previous_cursor
                self.state.write(state)  # Keep the original plan/rebuild/resume facts.
                self.last_progress = {**self.last_progress, 'stage': 'pending',
                                      'reason': 'FOREGROUND_YIELD'}
            except RefreshStateError:
                raise  # Retain the last durable inflight/resume proof; never replace it.
            except Exception as error:
                reason = _reason(error)
                self.last_progress = {**self.last_progress, 'stage': 'blocked', 'reason': reason}
                if reason != 'SOURCE_BUSY':
                    state['routes'][key] = {**state['routes'].get(key, {}), 'status': 'blocked', 'reason': reason}
                    self.state.write(state)
            return  # One selected stream per tick, even when planning fails.
        self.state.write(state)

    def _execute(self, route, endpoint, trading_day, prior, state, now, cancelled, batch_limit):
        budget = SUBING_BUDGET if _strategy(route.identity) == 'subing_reference' else BUDGET
        key = route.identity.stream_id
        storage_failure: RefreshStateError | None = None
        original_cancelled = cancelled
        committed_batches = 0
        deadline = monotonic() + budget.max_elapsed_seconds
        self.last_progress = {'at': now.isoformat(), 'stream_id': key,
                              'target': endpoint.isoformat(), 'stage': 'planning',
                              'backlog_count': self.last_progress.get('backlog_count', 0),
                              'blocked_route_count': self.last_progress.get('blocked_route_count', 0)}
        def cancelled():
            return (original_cancelled() or monotonic() >= deadline
                    or (batch_limit is not None and committed_batches >= batch_limit))
        def after_batch(stage, context):
            nonlocal storage_failure, committed_batches
            if stage == 'committed':
                if context.get('resume_token'):
                    state['routes'][key]['resume'] = asdict(context['resume_token'])
                try:
                    self.state.write(state)  # Still inflight until a known report.
                    committed_batches += 1
                    self.last_progress = {**self.last_progress, 'stage': 'committed',
                                          'committed_batches': committed_batches}
                except RefreshStateError as error:
                    storage_failure = error
                    raise
        @contextmanager
        def protected_components():
            nonlocal storage_failure
            try:
                with self._components(cancelled=cancelled, after_batch=after_batch,
                                      now=lambda: now) as components:
                    try:
                        yield components
                    except RefreshStateError as error:
                        storage_failure = error
                        raise
            except BaseException:
                # Lease/component cleanup must not replace a proven storage
                # unknown and send it through the generic blocked-state writer.
                if storage_failure is not None:
                    raise storage_failure
                raise
        with protected_components() as (planner, service):
            def prepare(request):
                from app.market_data.newow.product_reader import NewowProductReadCancelled
                try:
                    return planner.plan(request)
                except NewowProductReadCancelled:
                    if cancelled():
                        raise RefreshPlanningYield() from None
                    raise
            def rebuild_plan(frozen):
                replacement = prepare(HistoricalReferenceRequest(
                    'rebuild', (frozen.streams[0].request,), budget,
                ))
                before, after = frozen.streams[0], replacement.streams[0]
                if (before.source_token != after.source_token
                        or before.input_manifest_sha256 != after.input_manifest_sha256
                        or before.target_completed_through != after.target_completed_through):
                    raise ValueError('SOURCE_CHANGED')
                return replacement
            if prior:
                try:
                    plan = plan_from_dict(self.state.read_plan(prior['plan']))
                except ValueError as error:
                    raise RefreshStateError('REFRESH_PLAN_READBACK_REQUIRED') from error
                if (len(plan.streams) != 1 or plan.streams[0].request.identity != route.identity
                        or plan.streams[0].request.since != route.since):
                    raise ValueError('REFRESH_PLAN_SCOPE_DRIFT')
                if getattr(service, '_reader', None) is not None:
                    from app.reference_trading.refresh_recovery import prepare_source_recovery, install_source_recovery
                    from app.market_data.newow.product_reader import NewowProductReadCancelled
                    try:
                        with prepare_source_recovery(route, prior, plan, planner=planner, service=service,
                                                     endpoint=endpoint, trading_day=trading_day) as recovery:
                            if recovery is not None:
                                try:
                                    plan = install_source_recovery(self.state, state, recovery)
                                except OSError as error:
                                    raise RefreshStateError('REFRESH_RECOVERY_WRITE_UNKNOWN') from error
                                prior = None
                    except NewowProductReadCancelled:
                        if cancelled():
                            raise RefreshPlanningYield() from None
                        raise
                if prior and prior.get('rebuild_required'):
                    # Rebuild only the exact same endpoint and source already
                    # proven by the failed append plan. Never shrink its prefix.
                    plan, prior = rebuild_plan(plan), None
            else:
                plan = prepare(HistoricalReferenceRequest(
                    'rebuild' if route.reason in {'CANONICAL_SOURCE_REVISION_CHANGED', 'INPUT_PROOF_UPGRADE_REQUIRED'} else 'advance',
                    (HistoricalStreamRequest(route.identity, route.since,
                                                        trading_day, endpoint),), budget,
                ))
                if plan.streams[0].target_completed_through != endpoint:
                    raise ValueError('AUTHORITATIVE_ENDPOINT_CONFLICT')
            pending = {'status': 'inflight', 'reason': None, 'plan': self.state.store_plan(plan_to_dict(plan))}
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
            # HistoricalReferenceService isolates exceptions into stream reports.
            # A committed callback's control-storage failure must survive that boundary.
            if storage_failure is not None:
                raise storage_failure
            if len(report.streams) != 1:
                raise ValueError('REFRESH_REPORT_INVALID')
            result = report.streams[0]
            if (plan.operation == 'advance' and result.status == 'blocked'
                    and result.reason == 'REBUILD_REQUIRED'
                    and result.completed_bars == 0 and result.last_batch_key is None
                    and result.resume_token is None and committed_batches == 0):
                # Native advance rejected before its first mutation. Persist that
                # known boundary before planning the exact same-source rebuild.
                # A yield retains the old recoverable contract, not a new attempt.
                pending.update(status='pending', rebuild_required=True, reason='REBUILD_REQUIRED')
                self.state.write(state)
                if cancelled():
                    self.last_progress = {**self.last_progress, 'stage': 'pending',
                                          'reason': 'REBUILD_REQUIRED'}
                    return
                self.last_progress = {**self.last_progress, 'stage': 'rebuild_planning'}
                plan = rebuild_plan(plan)
                pending = {'status': 'inflight', 'reason': None,
                           'plan': self.state.store_plan(plan_to_dict(plan))}
                state['routes'][key] = pending
                self.state.write(state)
                if cancelled():
                    pending['status'] = 'pending'
                    self.state.write(state)
                    return
                self.last_progress = {**self.last_progress, 'stage': 'rebuilding'}
                report = service.rebuild(plan, plan.plan_hash)
                if storage_failure is not None:
                    raise storage_failure
                if len(report.streams) != 1:
                    raise ValueError('REFRESH_REPORT_INVALID')
                result = report.streams[0]
            if result.status in {'completed', 'noop'}:
                del state['routes'][key]
            elif result.reason == 'INPUT_READ_INTERRUPTED' and cancelled():
                # The service explicitly proves this interruption preceded all
                # repository mutation. A bare reader error is not such proof.
                pending.update(status='pending', reason='INTERRUPTED')
            elif result.reason == 'SOURCE_BUSY' and plan.operation == 'advance':
                pending.update(status='pending', reason='SOURCE_BUSY')
            elif result.reason == 'REBUILD_REQUIRED' and plan.operation == 'advance':
                # Only the exact zero-effect result above permits conversion.
                # Unexpected partial effects cannot become an automatic rebuild.
                pending.update(status='blocked', reason='REFRESH_READBACK_REQUIRED')
            elif result.status == 'partial' and result.reason == 'INTERRUPTED' and (
                result.resume_token is not None or plan.operation == 'advance'
            ):
                pending.update(status='pending', reason='INTERRUPTED')
                if result.resume_token:
                    pending['resume'] = asdict(result.resume_token)
            else:
                pending.update(status='blocked', reason=result.reason or 'REFRESH_FAILED_READBACK_REQUIRED')
            self.state.write(state)
            self.last_progress = {**self.last_progress, 'stage': result.status,
                                  'reason': _reason(ValueError(result.reason)) if result.reason else None}


class RefreshThread:
    """Single cancellable worker; foreground observation never joins each tick."""
    def __init__(self, runner, *, interval=30, now=lambda: datetime.now(UTC),
                 can_run=lambda: True, yield_requested=lambda: False,
                 on_tick_started=lambda: True, on_tick_finished=lambda: None, batch_limit=None, idle_interval=None):
        self._runner, self._interval, self._now = runner, interval, now
        self._idle_interval = interval if idle_interval is None else idle_interval
        self._can_run, self._yield_requested = can_run, yield_requested
        self._on_tick_started, self._on_tick_finished = on_tick_started, on_tick_finished
        self._batch_limit = batch_limit
        self._stop = Event()
        self.last_error = None
        self.wait_reason = None
        self.last_attempt_at = None
        self.last_success_at = None
        # Cancellation normally completes shutdown. Daemon is a bounded final
        # exit fallback; any unfinished mutation stays inflight and blocks restart.
        self._started = False
        self._thread = Thread(target=self._run, name='newow-historical-refresh', daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                if not self._can_run():
                    self._stop.wait(.1)
                    continue
                if self._stop.is_set():
                    return
                if not self._on_tick_started():
                    self._stop.wait(.1)
                    continue
                try:
                    attempt_now = self._now()
                    self.last_attempt_at = attempt_now.isoformat()
                    previous_progress = getattr(self._runner, 'last_progress', None)
                    options = {} if self._batch_limit is None else {'batch_limit': self._batch_limit}
                    self._runner.tick(now=attempt_now, cancelled=lambda:
                        self._stop.is_set() or self._yield_requested(), **options)
                finally:
                    self._on_tick_finished()
            except Exception as error:
                self.last_error = _reason(error)
                return  # Invalid state/storage never gets blindly overwritten.
            if (getattr(self._runner, "last_progress", {}).get("at") == self.last_attempt_at
                    and getattr(self._runner, "last_progress", {}).get("stage") in {"completed", "noop"}):
                self.last_success_at = self.last_attempt_at
            progressed = previous_progress != getattr(self._runner, 'last_progress', None)
            self._stop.wait(self._interval if progressed else self._idle_interval)

    def start(self):
        self._thread.start()
        self._started = True

    def stop(self, *, timeout=5):
        self._stop.set()
        if self._started:
            self._thread.join(timeout)

    def is_alive(self):
        return self._thread.is_alive()

    def diagnostic_snapshot(self):
        return {**dict(getattr(self._runner, 'last_progress', {})),
                "wait_reason": self.wait_reason, "last_attempt_at": self.last_attempt_at,
                "last_success_at": self.last_success_at}


def _history_route_supported(identity):
    """Maintain only existing canonical histories in the public page scope."""
    if identity.recording_mode is not RecordingMode.HISTORICAL_REPLAY or not _canonical_identity(identity):
        return False
    strategy = _strategy(identity)
    if strategy == 'subing_reference':
        return (identity.strategy_code == 'subing_reference'
                and identity.series_kind == 'actual_dominant'
                and identity.frequency in FREQUENCIES)
    if (identity.strategy_code != f'newow_{strategy}'
            or identity.product != identity.product.lower()
            or identity.series_kind != 'actual_dominant'
            or strategy not in STRATEGIES):
        return False
    from app.market_data.newow.product_release import (
        OPEN_FREQUENCIES, OPEN_INTRADAY_PRODUCTS, OPEN_WEEKLY_PRODUCTS,
        MAIN_RISE_FREQUENCIES,
    )
    from guiyi_quant.newow.product_contracts import ProductFrequency
    frequency = ProductFrequency(identity.frequency)
    if frequency not in OPEN_FREQUENCIES:
        return False
    if strategy == 'main_rise' and frequency not in MAIN_RISE_FREQUENCIES:
        return False
    if frequency is ProductFrequency.WEEKLY:
        return identity.product in OPEN_WEEKLY_PRODUCTS
    if identity.frequency in {'5m', '15m', '30m', '60m'}:
        return identity.product in OPEN_INTRADAY_PRODUCTS
    return True


def build_historical_refresh(session_factory, *, state_path):
    """Only metadata and one authoritative endpoint are read before full planning.

    Each callback creates its own session in the refresh thread. No MDS, Session,
    Redis client or canonical lease crosses from the foreground worker.
    """
    from sqlalchemy import select, func
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
                ReferenceStream.recording_mode == RecordingMode.HISTORICAL_REPLAY.value,
                func.lower(ReferenceStream.product).in_(products),
                ReferenceStream.frequency.in_(FREQUENCIES),
            )).all()
            # A page history asset is maintained independently of observation
            # activation. Exact canonical identity excludes superseded formulas
            # and quality policies; no forward stream is enabled or created.
            historical = [identity for row in rows
                          if _history_route_supported(identity := _identity_from_row(row))]
        with session_factory() as session, readonly_transaction(session, timeout_seconds=15):
            # Fetch only the current endpoint and original query boundary. Reading
            # 720 strategy checkpoints/manifests here would replay history per tick.
            rows = session.execute(select(
                ReferenceStream.stream_id, ReferenceRevision.status,
                ReferenceBatch.computed_through,
                ReferenceBatch.dependency_manifest['query_since'].as_string(),
                ReferenceRevision.invalid_reason,
                ReferenceBatch.dependency_manifest['reader'].as_string(),
                ReferenceBatch.dependency_manifest['source_reader'].as_string(),
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
            status, watermark, since, invalid_reason, reader_version, source_reader_version = value
            # SQLite drops timezone metadata; PostgreSQL retains it.
            if watermark is not None and watermark.tzinfo is None:
                watermark = watermark.replace(tzinfo=UTC)
            reason = None if status == 'active' else (
                'CANONICAL_SOURCE_REVISION_CHANGED'
                if status == 'invalid' and invalid_reason == 'P4_SOURCE_REVISION_REBUILD'
                else 'HISTORY_NOT_PUBLISHED')
            if (reason is None and _strategy(identity) in {'trend', 'oscillation', 'main_rise'}
                    and reader_version != 'newow_product_reader_prefix_v5'):
                reason = 'INPUT_PROOF_UPGRADE_REQUIRED'
            if (reason is None and _strategy(identity) == 'dual_fusion'
                    and (reader_version != 'newow_fusion_saved_sources_v3'
                         or source_reader_version != 'newow_product_reader_prefix_v5')):
                reason = 'INPUT_PROOF_UPGRADE_REQUIRED'
            result.append(RefreshRoute(identity, date.fromisoformat(since), watermark, reason))
        return result

    def endpoint(route, now):
        from app.market_data.composition import build_market_data_service
        from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery
        from app.market_data.newow.product_release import candidate_input_quality_policy
        with session_factory() as session:
            market = build_market_data_service(session)
            lease = market.catalog.acquire_maintenance_lock(caller='reference-endpoint')
            if lease is None:
                raise ValueError('SOURCE_BUSY')
            try:
                with readonly_transaction(session, timeout_seconds=15):
                    if _strategy(route.identity) == 'subing_reference':
                        page = market.query_page(SeriesPageQuery(
                            SeriesKind.ACTUAL_DOMINANT, route.identity.product.lower(),
                            BarFrequency(route.identity.frequency), before=None, limit=1,
                        ))
                        if not page.bars:
                            raise ValueError('AUTHORITATIVE_ENDPOINT_UNAVAILABLE')
                        return page.bars[-1].bar_end, page.bars[-1].trading_day
                    return market.published_reference_endpoint(
                        symbol=route.identity.product.lower(),
                        frequency=BarFrequency(route.identity.frequency), as_of=now,
                        quality_policy=candidate_input_quality_policy(
                            route.identity.product.lower(), route.identity.frequency,
                            candidate_weekly=False,
                        ).value,
                    )
            finally:
                lease.release()

    @contextmanager
    def components(**kwargs):
        with open_historical_reference_components(
            session_factory=session_factory, reuse_market_inputs=True, **kwargs,
        ) as value:
            yield value

    def needs_source_verification(route, now, cancelled):
        """Recheck the committed source under the usual Canonical lease.

        A changed byte proof enters the native advance path, which decides
        whether the semantic prefix is unchanged or requires a new revision.
        """
        from app.reference_trading.contracts import manifest_sha256
        from app.reference_trading.manifest_storage import resolve_manifest
        from app.reference_trading.models import ReferenceStream, ReferenceRevision, ReferenceBatch
        from app.reference_trading.page_material_query import latest_input_integrity
        from app.reference_trading.page_material_storage import (
            validate_input_integrity, verify_source_integrity,
        )
        if _strategy(route.identity) == 'subing_reference':
            return False
        if cancelled():
            raise RefreshPlanningYield()
        with components(cancelled=cancelled, after_batch=None, now=lambda: now) as (_planner, service):
            # components() holds the same maintenance lease used by planning.
            with session_factory() as session, readonly_transaction(session, timeout_seconds=30):
                stream = session.get(ReferenceStream, route.identity.stream_id)
                revision = (session.get(ReferenceRevision, (stream.stream_id, stream.active_revision_id))
                            if stream is not None and stream.active_revision_id is not None else None)
                batch = (session.get(ReferenceBatch, revision.checkpoint_batch_id)
                         if revision is not None and revision.checkpoint_batch_id is not None else None)
                if (stream is None or revision is None or batch is None
                        or revision.status != 'active' or stream.health != 'READY'
                        or stream.latest_seq != revision.last_seq
                        or batch.stream_id != stream.stream_id
                        or batch.revision_id != revision.revision_id
                        or batch.seq != revision.last_seq or batch.kind != 'calculation'
                        or batch.outcome != 'committed'):
                    raise ValueError('SOURCE_IDENTITY_UNVERIFIED')
                saved_through = batch.computed_through
                if saved_through is not None and saved_through.tzinfo is None:
                    saved_through = saved_through.replace(tzinfo=UTC)
                if saved_through != route.computed_through:
                    raise ValueError('SOURCE_IDENTITY_UNVERIFIED')
                manifest = resolve_manifest(session, batch)
                digest = manifest_sha256(manifest)
                record = latest_input_integrity(session, batch)
                if (digest != revision.dependency_digest or not isinstance(record, dict)
                        or route.since is None or manifest.get('query_since') != route.since.isoformat()):
                    raise ValueError('SOURCE_IDENTITY_UNVERIFIED')
                request = record.get('request')
                expected = {
                    'schema': 'reference_input_integrity_v1',
                    'stream_id': stream.stream_id, 'revision_id': revision.revision_id,
                    'seq': batch.seq, 'manifest_sha256': digest, 'source_token': digest,
                    'source_integrity': record.get('source_integrity'), 'request': request,
                }
                try:
                    validate_input_integrity(record, expected_binding=expected)
                except (TypeError, ValueError, KeyError) as error:
                    raise ValueError('SOURCE_IDENTITY_UNVERIFIED') from error
                if (request['product'] != route.identity.product.lower()
                        or request['frequency'] != route.identity.frequency
                        or request['since'] != route.since.isoformat()):
                    raise ValueError('SOURCE_IDENTITY_UNVERIFIED')
                source = record['source_integrity']
            if cancelled():
                raise RefreshPlanningYield()
            reader = service._reader._newow_for(route.identity)
            try:
                unchanged = verify_source_integrity(reader, source)
            except (TypeError, ValueError, KeyError) as error:
                raise ValueError('SOURCE_IDENTITY_UNVERIFIED') from error
            if cancelled():
                raise RefreshPlanningYield()
            return not unchanged

    return HistoricalRefresh(routes=routes, endpoint=endpoint, components=components,
                             state=RefreshStateStore(state_path),
                             needs_source_verification=needs_source_verification)
