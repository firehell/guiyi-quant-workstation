"""Single-host Runtime ownership and reversible drain requests.

An OS lock, not a heartbeat expiry, authorizes effects. The run callback must
close all its workers and in-flight transports before returning to this wrapper.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
from time import sleep
from uuid import uuid4

SERVICES = frozenset({'api', 'web', 'market-feed', 'live', 'alert',
                      'reference-worker', 'after-market', 'late-provider-recovery',
                      'weekly-audit', 'log-rotate'})


class HandoverError(RuntimeError):
    """Only fixed, non-secret diagnostics cross the process boundary."""


def runtime_directory() -> Path:
    return Path.home() / 'Library/Application Support/GuiyiQuant'


def _path(directory: Path, service: str, suffix: str) -> Path:
    if service not in SERVICES or not directory.is_absolute():
        raise HandoverError('RUNTIME_CONTROL_INVALID')
    if directory.is_symlink() or (directory.exists() and directory.resolve() != directory):
        raise HandoverError('RUNTIME_CONTROL_INVALID')
    return directory / f'{service}.{suffix}'


def _read(path: Path) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError:
        raise HandoverError('RUNTIME_CONTROL_INVALID') from None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 65536):
            raise HandoverError('RUNTIME_CONTROL_INVALID')
        data = os.read(fd, 65537)
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeError):
        raise HandoverError('RUNTIME_CONTROL_INVALID') from None
    finally:
        os.close(fd)


def _write(path: Path, payload: dict) -> None:
    directory = path.parent
    if directory.is_symlink() or (directory.exists() and directory.resolve() != directory):
        raise HandoverError('RUNTIME_CONTROL_INVALID')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise HandoverError('RUNTIME_CONTROL_INVALID')
    if path.is_symlink():
        raise HandoverError('RUNTIME_CONTROL_INVALID')
    fd, temporary = tempfile.mkstemp(prefix='.runtime-control-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_service_state(service: str, *, runtime_dir: Path | None = None) -> dict | None:
    directory = runtime_dir or runtime_directory()
    value = _read(_path(directory, service, 'owner.json'))
    if value is not None and (value.get('schema_version') != 1 or value.get('service') != service):
        raise HandoverError('RUNTIME_CONTROL_INVALID')
    return value


def request_drain(service: str, *, generation: int, runtime_dir: Path | None = None) -> str:
    if type(generation) is not int or generation < 1:
        raise HandoverError('RUNTIME_CONTROL_INVALID')
    request_id = uuid4().hex
    path = _path(runtime_dir or runtime_directory(), service, 'handover.json')
    _write(path, {'schema_version': 1, 'service': service, 'generation': generation,
                  'request_id': request_id, 'phase': 'drain'})
    return request_id


def cancel_drain(service: str, *, request_id: str, runtime_dir: Path | None = None) -> None:
    path = _path(runtime_dir or runtime_directory(), service, 'handover.json')
    value = _read(path)
    if value is None or value.get('request_id') != request_id:
        raise HandoverError('RUNTIME_CONTROL_CONFLICT')
    value['phase'] = 'cancelled'
    _write(path, value)


class RunOwnership:
    def __init__(self, service: str, *, runtime_dir: Path | None = None,
                 generation: int | None = None, verify: Callable[[], None] | None = None):
        self.service = service
        self.directory = runtime_dir or runtime_directory()
        _path(self.directory, service, 'owner.lock')
        self._fd: int | None = None
        self._verify = verify or self._verify_binding
        if generation is None:
            from app.runtime_bindings import resolve_service_binding
            binding = resolve_service_binding(service)
            if binding is None:
                raise HandoverError('RUNTIME_BINDING_REQUIRED')
            generation = binding.generation
        if type(generation) is not int or generation < 1:
            raise HandoverError('RUNTIME_CONTROL_INVALID')
        self.generation = generation

    def _verify_binding(self) -> None:
        from app.core.env import PROJECT_ROOT
        from app.runtime_bindings import resolve_service_binding
        binding = resolve_service_binding(self.service)
        if (binding is None or not binding.enabled or binding.generation != self.generation
                or Path(binding.root) != PROJECT_ROOT
                or binding.commit != os.environ.get('GUIYI_RUNTIME_COMMIT')
                or str(binding.generation) != os.environ.get('GUIYI_RUNTIME_GENERATION')
                or binding.tag != os.environ.get('GUIYI_RUNTIME_TAG')):
            raise HandoverError('RUNTIME_GENERATION_CHANGED')

    @contextmanager
    def acquired(self) -> Iterator[RunOwnership]:
        if self._fd is not None:
            raise HandoverError('RUNTIME_OWNER_BUSY')
        path = _path(self.directory, self.service, 'owner.lock')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        except OSError:
            raise HandoverError('RUNTIME_OWNER_INVALID') from None
        locked = False
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise HandoverError('RUNTIME_OWNER_INVALID')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HandoverError('RUNTIME_OWNER_BUSY') from None
            locked = True
            self._fd = fd
            self.assert_owned()
            self._state('active')
            yield self
            self._state('parked' if self.should_drain() else 'stopped')
        finally:
            self._fd = None
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def assert_owned(self) -> None:
        if self._fd is None:
            raise HandoverError('RUNTIME_OWNER_REQUIRED')
        self._verify()
        path = _path(self.directory, self.service, 'owner.lock')
        try:
            disk, held = path.lstat(), os.fstat(self._fd)
        except OSError:
            raise HandoverError('RUNTIME_OWNER_INVALID') from None
        if stat.S_ISLNK(disk.st_mode) or (disk.st_ino, disk.st_dev) != (held.st_ino, held.st_dev):
            raise HandoverError('RUNTIME_OWNER_INVALID')

    def should_drain(self) -> bool:
        value = _read(_path(self.directory, self.service, 'handover.json'))
        if value is None:
            return False
        if (value.get('schema_version') != 1 or value.get('service') != self.service
                or type(value.get('generation')) is not int
                or value.get('phase') not in {'drain', 'cancelled'}
                or not isinstance(value.get('request_id'), str)):
            raise HandoverError('RUNTIME_CONTROL_INVALID')
        return value['generation'] == self.generation and value['phase'] == 'drain'

    def _state(self, phase: str) -> None:
        _write(_path(self.directory, self.service, 'owner.json'), {
            'schema_version': 1, 'service': self.service, 'generation': self.generation,
            'phase': phase, 'pid': os.getpid(), 'at': datetime.now(UTC).isoformat(),
        })

    def mark_not_ready(self) -> None:
        self.assert_owned()
        self._state('active')

    def mark_ready(self, proof: dict | None = None) -> None:
        self.assert_owned()
        _write(_path(self.directory, self.service, 'owner.json'), {
            'schema_version': 1, 'service': self.service, 'generation': self.generation,
            'phase': 'active', 'ready': True, 'pid': os.getpid(),
            'proof': proof or {'cycle_ok': True}, 'at': datetime.now(UTC).isoformat(),
        })


def run_supervised(service: str, run: Callable[[RunOwnership], None], *,
                   stop_requested: Callable[[], bool] = lambda: False) -> None:
    owner = RunOwnership(service)
    while not stop_requested():
        owner._verify()
        with owner.acquired():
            run(owner)
        if not owner.should_drain():
            return
        while owner.should_drain() and not stop_requested():
            try:
                owner._verify()
            except HandoverError:
                return  # New generation owns the service; never resume the old writer.
            sleep(0.1)


@contextmanager
def deployment_lock(*, runtime_dir: Path | None = None) -> Iterator[None]:
    directory = runtime_dir or runtime_directory()
    _path(directory, 'api', 'owner.lock')  # Validate the permitted directory.
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory / 'deployment.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_mode & 0o077 or metadata.st_nlink != 1):
            raise HandoverError('RUNTIME_CONTROL_INVALID')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HandoverError('RUNTIME_DEPLOYMENT_BUSY') from None
        yield
    finally:
        os.close(fd)


def owner_lock_available(service: str, *, runtime_dir: Path | None = None) -> bool:
    """Read-only lock proof: do not rewrite the parked owner's progress report."""
    path = _path(runtime_dir or runtime_directory(), service, 'owner.lock')
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise HandoverError('RUNTIME_OWNER_INVALID') from None
    try:
        held = os.fstat(fd)
        if not stat.S_ISREG(held.st_mode) or held.st_uid != os.getuid() or held.st_mode & 0o077:
            raise HandoverError('RUNTIME_OWNER_INVALID')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    finally:
        os.close(fd)
