"""Explicit observe-only bootstrap, separate from disabled preparation startup.

Native reports are supplied under the shared account lock. No transport, sender,
settlement action, position recovery or default capital exists in this module.
The four journals and disabled runtime config become visible in one directory rename.
"""
from contextlib import closing
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
import json
import os
import stat
import tempfile

from .. import htdy_account_execution as account
from ..htdy_account_execution.codec import digest
from .account_binding import existing_account
from .evidence import Evidence
from .inbox import SignalInbox
from .inventory import read_snapshot, project_readback, order_status, number
from .journal import Journal
from .settings import load_settings
from .supervisor import global_account_lock


def _preparation(config):
    settings = load_settings(Path(config))
    if settings.schema != 3 or settings.enabled or settings.mode != 'observe':
        raise ValueError('OBSERVE_PREPARATION_REQUIRED')
    return settings


def _fresh(settings, reader, now, check):
    check()
    snapshot = read_snapshot(reader(), now=now())
    check()
    if snapshot.account_id != settings.account_id:
        raise ValueError('BOOTSTRAP_ACCOUNT_MISMATCH')
    _snapshot_current(snapshot, now)
    return snapshot


def _snapshot_current(snapshot, now):
    instant = now()
    if not snapshot.at <= instant < snapshot.at + timedelta(seconds=30):
        raise ValueError('BOOTSTRAP_SNAPSHOT_EXPIRED')


def probe_account(config, reader, *, now, check=lambda: None):
    """Query all account facts without touching an account directory or journal."""
    settings = _preparation(config)
    with global_account_lock(settings.account_id):
        if _preparation(config) != settings:
            raise ValueError('BOOTSTRAP_CONFIG_CHANGED')
        snapshot = _fresh(settings, reader, now, check)
        if _preparation(config) != settings:
            raise ValueError('BOOTSTRAP_CONFIG_CHANGED')
        return snapshot


def _require_flat(snapshot):
    data = snapshot.data
    for position in data['positions']:
        if any(position[k] for k in ('Position', 'LongFrozen', 'ShortFrozen')):
            raise ValueError('BOOTSTRAP_ACCOUNT_NOT_FLAT')
    if any(order_status(row) not in ('FILLED', 'CANCELLED', 'REJECTED') for row in data['orders']):
        raise ValueError('BOOTSTRAP_PENDING_OR_UNKNOWN_ORDER')
    if any(number(data['funds'][0][key]) != 0
           for key in ('CurrMargin', 'FrozenMargin', 'FrozenCommission')):
        raise ValueError('BOOTSTRAP_OCCUPANCY_UNEXPLAINED')
    funds = data['funds'][0]
    if number(funds['Balance'], signed=True) != number(funds['Available'], signed=True):
        raise ValueError('BOOTSTRAP_OCCUPANCY_UNEXPLAINED')


def _private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (path.is_symlink() or path.resolve() != path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('BOOTSTRAP_PRIVATE_DIRECTORY_REQUIRED')


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_config(path, settings):
    value = {key: str(v) if isinstance(v, Path) else v for key, v in asdict(settings).items()}
    value.update(schema=2, enabled=False, mode='observe')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def initialize_observe(config, products, reader, *, now, assert_closed, check=lambda: None,
                       fault=lambda _stage: None):
    """Publish an independently observed flat baseline; never adopt old obligations."""
    check()
    if not assert_closed():
        raise ValueError('BOOTSTRAP_CLOSED_WINDOW_REQUIRED')
    settings = _preparation(config)
    with global_account_lock(settings.account_id):
        if _preparation(config) != settings:
            raise ValueError('BOOTSTRAP_CONFIG_CHANGED')
        snapshot = _fresh(settings, reader, now, check)
        _require_flat(snapshot)
        at = now()
        readback, _ = project_readback(snapshot, (), None, None, snapshot.at + timedelta(seconds=30))
        state = account.start(settings.account_id, products, at, readback)
        output = settings.state_project_root / 'output'
        _private_directory(output)
        temporary = Path(tempfile.mkdtemp(prefix='.observe-bootstrap-', dir=output))
        stage = temporary / settings.account_id
        stage.mkdir(mode=0o700)
        # A partial stage remains private evidence and is never a configured account root.
        with closing(account.LocalStore(stage / 'account.sqlite', state)):
            pass
        fault('account_created')
        with closing(Journal(stage / 'dispatch.sqlite', settings.account_id)):
            pass
        with closing(SignalInbox(stage / 'signals.sqlite', settings.account_id, products)):
            pass
        with closing(Evidence(stage / 'native-evidence.sqlite', settings.account_id)) as evidence:
            evidence.append(snapshot)
        _write_config(stage / 'observe.private.json', settings)
        verified = existing_account(temporary, settings.account_id)
        if digest(verified) != digest(state):
            raise ValueError('BOOTSTRAP_JOURNAL_READBACK_MISMATCH')
        check()
        if not assert_closed():
            raise ValueError('BOOTSTRAP_CLOSED_WINDOW_REQUIRED')
        _snapshot_current(snapshot, now)
        if _preparation(config) != settings:
            raise ValueError('BOOTSTRAP_CONFIG_CHANGED')
        fault('before_publish')
        _private_directory(settings.state_root)
        target = settings.state_root / settings.account_id
        if target.exists() or target.is_symlink():
            raise ValueError('BOOTSTRAP_TARGET_ALREADY_EXISTS')
        _fsync_directory(stage)
        check()
        os.rename(stage, target)
        _fsync_directory(settings.state_root)
        temporary.rmdir()
        runtime = target / 'observe.private.json'
        published = load_settings(runtime)
        if published.schema != 2 or published.enabled or published.mode != 'observe':
            raise ValueError('BOOTSTRAP_PUBLISHED_CONFIG_INVALID')
        return {'config_path': str(runtime), 'account_id': settings.account_id,
                'checkpoint_sha256': digest(verified), 'source_id': snapshot.source_id,
                'account_reconciled': True, 'execution_permitted': False,
                'mode': 'observe', 'enabled': False}
