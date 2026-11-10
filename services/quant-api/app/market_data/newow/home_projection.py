"""Persisted homepage display projection. Reads never invoke market computation."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
import fcntl
from hashlib import sha256
import json
import logging
import os
import re
from pathlib import Path
import stat
from uuid import uuid4

from app.market_data.market_home_projection import _open_projection_parent

SCHEMA = 'newow_home_projection_v1'
MAX_BYTES = 2 * 1024 * 1024
PERIODS = ('1d', '1w')
STRATEGIES = ('trend', 'oscillation')
_LOGGER = logging.getLogger(__name__)


def _log_period_failure(product, period, stage, code, exc):
    # Keep the failure location, never exception text, locals or absolute paths.
    trace = exc.__traceback__
    while trace is not None and trace.tb_next is not None:
        trace = trace.tb_next
    location = Path(trace.tb_frame.f_code.co_filename).name if trace else 'unknown'
    function = trace.tb_frame.f_code.co_name if trace else 'unknown'
    def label(value):
        return value if re.fullmatch(r'[A-Za-z0-9_.<>-]{1,100}', value) else 'redacted'
    try:
        _LOGGER.warning(
            'home_projection_period_failed product=%s period=%s stage=%s code=%s '
            'exception_type=%s file=%s line=%s function=%s',
            label(product), period, stage, code, label(type(exc).__name__),
            label(location), trace.tb_lineno if trace else 0, label(function),
        )
    except Exception:
        # Diagnostic delivery must not stop other products or replace old facts.
        pass


class ProjectionError(RuntimeError):
    code = 'HOME_PROJECTION_UNAVAILABLE'


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def projection_path(root: Path) -> Path:
    return root.resolve() / '.derived' / 'newow-home.json'


class ProjectionStore:
    def __init__(self, path: Path, *, schema=SCHEMA, max_bytes=MAX_BYTES, max_items=60):
        self.path = path
        self.schema, self.max_bytes, self.max_items = schema, max_bytes, max_items
        self.write_guard = None

    def load(self):
        parent = None
        try:
            parent = _open_projection_parent(self.path.parent, create=False)
            if parent is None:
                return None
            fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                meta = os.fstat(fd)
                if not stat.S_ISREG(meta.st_mode) or not 0 < meta.st_size <= self.max_bytes:
                    return None
                value = json.loads(os.read(fd, self.max_bytes + 1))
            finally:
                os.close(fd)
            payload = value['payload']
            if value['sha256'] != sha256(_encoded(payload)).hexdigest() or payload['schema_version'] != self.schema:
                return None
            if not isinstance(payload['items'], dict) or len(payload['items']) > self.max_items:
                return None
            return payload
        except (OSError, ValueError, KeyError, TypeError):
            return None
        finally:
            if parent is not None:
                os.close(parent)

    def save(self, payload):
        if self.write_guard is not None:
            self.write_guard()
        encoded = _encoded({'payload': payload, 'sha256': sha256(_encoded(payload)).hexdigest()})
        if len(encoded) > self.max_bytes:
            raise ProjectionError()
        parent = _open_projection_parent(self.path.parent, create=True)
        name = f'.{self.path.name}.{uuid4().hex}.tmp'
        fd = None
        try:
            try:
                old = os.stat(self.path.name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISREG(old.st_mode):
                    raise ProjectionError()
            except FileNotFoundError:
                pass
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            view = memoryview(encoded)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise ProjectionError()
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = None
            if self.write_guard is not None:
                self.write_guard()
            os.replace(name, self.path.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(name, dir_fd=parent)
            except FileNotFoundError:
                pass
            os.close(parent)

    @contextmanager
    def lock(self):
        parent = _open_projection_parent(self.path.parent, create=True)
        fd = None
        acquired = False
        try:
            fd = os.open(f'{self.path.name}.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ProjectionError()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError as exc:
                raise ProjectionError() from exc
            yield
        finally:
            if fd is not None:
                if acquired:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            os.close(parent)

    def building(self):
        # Existence is not proof of a running builder: only the held lock is.
        parent = None
        fd = None
        try:
            parent = _open_projection_parent(self.path.parent, create=False)
            if parent is None:
                return False
            fd = os.open(f'{self.path.name}.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return False
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
        except OSError:
            return False
        finally:
            if fd is not None:
                os.close(fd)
            if parent is not None:
                os.close(parent)


class HomeProjection:
    def __init__(self, store, products, versions, compute=None, *, now=None, overview=None):
        if len(products) > 60 or len(set(products)) != len(products):
            raise ProjectionError()
        self.store, self.products = store, tuple(products)
        self.versions, self.compute = versions, compute
        self.overview = overview
        self.now = now or (lambda: datetime.now(UTC))
        self.source_scope = None
        self.delivery = None

    def read(self):
        data = self.store.load() or {'items': {}}
        try:
            versions = self.versions()
        except Exception:
            versions = {}
        building = self.store.building()
        deliveries = self.delivery(versions) if self.delivery is not None else {}
        output = []
        for product in self.products:
            item = data['items'].get(product, {})
            periods = item.get('periods', {})
            states = {}
            reasons = {}
            strategies = {s: {} for s in STRATEGIES}
            for period in PERIODS:
                entry = periods.get(period)
                state = 'missing' if not entry else 'ready'
                reason = 'SUMMARY_MISSING' if not entry else None
                if entry and (not versions.get(f'{product}:{period}') or entry.get('version') != versions.get(f'{product}:{period}')):
                    state = 'stale'
                    reason = 'SOURCE_VERSION_UNAVAILABLE' if not versions.get(f'{product}:{period}') else 'SOURCE_VERSION_CHANGED'
                if entry and any(value.get('freshness') == 'pending_update' for value in entry['facts'].values()):
                    state = 'stale'
                    reason = 'PERIOD_PENDING_UPDATE'
                failure_versions = item.get('failure_versions')
                if item.get('failures', {}).get(period) and (
                    failure_versions is None or failure_versions.get(period) == versions.get(f'{product}:{period}')
                ):
                    state = 'failed'
                    reason = 'SUMMARY_BUILD_FAILED'
                if building and item.get('building'):
                    state = 'updating'
                    reason = 'SUMMARY_BUILDING'
                elif item.get('building'):
                    state = 'failed'
                    reason = 'SUMMARY_BUILD_INTERRUPTED'
                states[period] = state
                reasons[period] = reason
                for strategy in STRATEGIES:
                    strategies[strategy][period] = deepcopy(entry['facts'][strategy]) if entry else {'status': 'unavailable', 'state': None}
                    if entry:
                        strategies[strategy][period]['display_as_of'] = item.get('computed_at')
            status = next((value for value in ('updating', 'failed', 'missing', 'stale') if value in states.values()), 'ready')
            output.append({'product': product, 'strategies': strategies, 'projection_status': status,
                           'period_status': states, 'period_reason_codes': reasons, 'computed_at': item.get('computed_at'),
                           'source_versions': {p: periods.get(p, {}).get('version') for p in PERIODS},
                           **({'recovery': deliveries[product]} if product in deliveries else {})})
        return {'schema_version': SCHEMA, 'generated_at': data.get('generated_at'),
                'requested_at': self.now().isoformat(), 'page_parity': True, 'executable': False,
                'items': output, 'overview': data.get('overview'),
                'overview_status': 'failed' if data.get('overview_failed') else 'ready' if data.get('overview') is not None and bool(versions) and data.get('overview_versions') == versions else 'missing' if not data.get('overview') else 'stale'}

    def _refresh_overview(self, data):
        if self.overview is None:
            return
        versions = self.versions()
        previous = data.get('overview')
        if (not data.get('overview_failed') and previous is not None
                and previous.get('participant_count') != 0 and data.get('overview_versions') == versions):
            return
        try:
            if not versions:
                raise ProjectionError()
            value = self.overview()
            if self.versions() != versions:
                raise ProjectionError()
            if value.get('participant_count') == 0:
                # The session can close before today's Canonical D1 is published.
                # Keep the last populated snapshot until the next source revision.
                if previous is None or previous.get('participant_count') == 0:
                    data['overview'] = value
                data['overview_failed'] = True
            else:
                data['overview'], data['overview_versions'] = value, versions
                data.pop('overview_failed', None)
        except Exception as exc:
            _log_period_failure('overview', 'overview', 'compute_overview', 'HOME_OVERVIEW_BUILD_FAILED', exc)
            data['overview_failed'] = True
        self.store.save(data)

    def build_overview(self):
        with self.store.lock():
            data = self.store.load() or {'schema_version': SCHEMA, 'items': {}}
            self._refresh_overview(data)
        return self.read()

    def build(self, products=None, *, include_overview=True):
        selected = self.products if products is None else tuple(products)
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(self.products) or self.compute is None:
            raise ProjectionError()
        with self.store.lock():
            data = self.store.load() or {'schema_version': SCHEMA, 'items': {}}
            data['items'] = {p: value for p, value in data['items'].items() if p in self.products}
            if include_overview:
                self._refresh_overview(data)
            if self.source_scope is not None:
                data['source_scope'] = self.source_scope()
            for product in selected:
                before = self.versions()
                item = data['items'].setdefault(product, {'periods': {}})
                if not item.get('failures') and not item.get('building') and all(before.get(f'{product}:{period}') and item['periods'].get(period, {}).get('version') == before.get(f'{product}:{period}') for period in PERIODS):
                    continue
                previous_periods = deepcopy(item['periods'])
                retry_periods = set(item.get('failures', {}))
                if item.get('building'):
                    retry_periods.update(PERIODS)
                item['failures'] = {}
                item.pop('failure_versions', None)
                item['building'] = True
                data['generated_at'] = self.now().isoformat()
                self.store.save(data)
                for period in PERIODS:
                    key = f'{product}:{period}'
                    version = before.get(key)
                    if version and item['periods'].get(period, {}).get('version') == version and period not in retry_periods:
                        continue
                    stage = 'source_version'
                    try:
                        if not version:
                            raise ProjectionError()
                        stage = 'compute'
                        facts = self.compute(product, period)
                        stage = 'verify_source_version'
                        if self.versions().get(key) != version:
                            raise ProjectionError()
                        stage = 'validate_facts'
                        if set(facts) != set(STRATEGIES):
                            raise ProjectionError()
                        # Persist display facts, never an expiring query capability.
                        stage = 'prepare_snapshot'
                        facts = deepcopy(facts)
                        for value in facts.values():
                            value.pop('snapshot_token', None)
                            value.pop('snapshot_context', None)
                        item['periods'][period] = {'version': version, 'facts': facts}
                    except Exception as exc:
                        code = getattr(exc, 'code', '')
                        item['failures'][period] = code if isinstance(code, str) and re.fullmatch(r'(NEWOW|MARKET|MAIN_CONTRACT|HOME)_[A-Z0-9_]{1,100}', code) else 'HOME_PROJECTION_BUILD_FAILED'
                        _log_period_failure(product, period, stage, item['failures'][period], exc)
                        break
                try:
                    after = self.versions()
                except Exception as exc:
                    after = None
                    code = getattr(exc, 'code', '')
                    code = code if isinstance(code, str) and re.fullmatch(r'(NEWOW|MARKET|MAIN_CONTRACT|HOME)_[A-Z0-9_]{1,100}', code) else 'HOME_PROJECTION_BUILD_FAILED'
                    item['failures'] = dict.fromkeys(PERIODS, code)
                    _log_period_failure(product, 'pair', 'verify_source_version', code, exc)
                if after is not None and any(after.get(f'{product}:{period}') != before.get(f'{product}:{period}') for period in PERIODS):
                    item['failures'] = dict.fromkeys(PERIODS, 'HOME_PROJECTION_SOURCE_CHANGED')
                if item['failures']:
                    item['periods'] = previous_periods
                    item['failure_versions'] = {period: before.get(f'{product}:{period}') for period in PERIODS}
                item['building'] = False
                if not item['failures']:
                    item['computed_at'] = self.now().isoformat()
                self.store.save(data)
        return self.read()
