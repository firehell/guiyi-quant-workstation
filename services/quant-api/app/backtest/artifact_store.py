"""Race-safe filesystem artifacts and single-run lock for local backtests."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import tempfile
import threading
from typing import Any, BinaryIO, NoReturn, cast
from zipfile import ZIP_DEFLATED, ZipFile

from app.backtest.config import BacktestSettings
from app.backtest.contracts import RunStatus
from app.backtest.errors import BacktestError, BacktestHttpErrorCode, RunFailureCode


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LOG_NAMES = {"stdout": "stdout.log", "stderr": "stderr.log"}
_ARTIFACT_NAMES = {
    "result_pickle": "result.pkl",
    "equity_png": "equity.png",
    "stdout_log": "stdout.log",
    "stderr_log": "stderr.log",
    "run_json": "run.json",
}
_MAX_LOG_LINES = 200
_MAX_LOG_BYTES = 65_536
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FILE_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
_CREATE_FILE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


@dataclass(frozen=True, slots=True)
class RunPaths:
    """The complete persistent path contract for one run."""

    root: Path
    run_json: Path
    result_json: Path
    strategy_file: Path
    strategy_params_json: Path
    result_pickle: Path
    equity_png: Path
    report_dir: Path
    stdout_log: Path
    stderr_log: Path


@dataclass(frozen=True, slots=True)
class ActiveLock:
    """The exact contents of ``active.lock``."""

    run_id: str
    pid: int
    started_at: str


@dataclass(frozen=True, slots=True)
class _OpenedLock:
    lock: ActiveLock
    descriptor: int
    device: int
    inode: int


class ArtifactStore:
    """Concrete filesystem store using descriptor-relative, no-follow access."""

    def __init__(self, settings: BacktestSettings) -> None:
        self.runs_root = settings.runs_root.resolve(strict=False)
        self.lock_path = self.runs_root / "active.lock"
        self._thread_lock = threading.RLock()

    def run_paths(self, run_id: str) -> RunPaths:
        """Return the fixed child path contract for a validated run id."""

        self._validate_run_id(run_id)
        root = self.runs_root / run_id
        return RunPaths(
            root=root,
            run_json=root / "run.json",
            result_json=root / "result.json",
            strategy_file=root / "strategy.py",
            strategy_params_json=root / "strategy_params.json",
            result_pickle=root / "result.pkl",
            equity_png=root / "equity.png",
            report_dir=root / "report",
            stdout_log=root / "stdout.log",
            stderr_log=root / "stderr.log",
        )

    def create_run(
        self,
        run_id: str,
        *,
        run_record: Mapping[str, Any],
        strategy_file: Path,
        strategy_params: Mapping[str, Any],
    ) -> RunPaths:
        """Create one fixed run tree and snapshot an already registered strategy."""

        paths = self.run_paths(run_id)
        with self._open_absolute_regular_file(strategy_file) as source_descriptor:
            source_bytes = self._read_all(source_descriptor)
        strategy_sha256 = sha256(source_bytes).hexdigest()
        payload = dict(run_record)
        payload["run_id"] = run_id
        payload["strategy_sha256"] = strategy_sha256

        with self._open_runs_root(create=True) as root_descriptor:
            os.mkdir(run_id, mode=0o700, dir_fd=root_descriptor)
            with self._open_directory_at(root_descriptor, run_id) as run_descriptor:
                os.mkdir("report", mode=0o700, dir_fd=run_descriptor)
                self._write_exclusive_at(
                    run_descriptor,
                    "strategy.py",
                    source_bytes,
                )
                self._write_exclusive_at(run_descriptor, "stdout.log", b"")
                self._write_exclusive_at(run_descriptor, "stderr.log", b"")
                self._write_json_atomic_at(
                    run_descriptor,
                    "strategy_params.json",
                    strategy_params,
                )
                self._write_json_atomic_at(run_descriptor, "run.json", payload)
        return paths

    def read_run(self, run_id: str) -> dict[str, Any]:
        """Read the authoritative run record through an opened run directory."""

        with self._open_runs_root() as root_descriptor:
            with self._open_run(root_descriptor, run_id) as run_descriptor:
                return self._read_json_at(
                    run_descriptor,
                    "run.json",
                    invalid_code="BACKTEST_RUN_RECORD_INVALID",
                )

    def update_run(
        self,
        run_id: str,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Merge and atomically replace the run record within one opened dir."""

        with self._open_runs_root() as root_descriptor:
            with self._open_run(root_descriptor, run_id) as run_descriptor:
                current = self._read_json_at(
                    run_descriptor,
                    "run.json",
                    invalid_code="BACKTEST_RUN_RECORD_INVALID",
                )
                if current.get("run_id") != run_id:
                    raise ValueError("BACKTEST_RUN_RECORD_INVALID")
                updated = {**current, **dict(changes)}
                updated["run_id"] = run_id
                updated["strategy_sha256"] = current.get("strategy_sha256")
                self._write_json_atomic_at(run_descriptor, "run.json", updated)
                return updated

    def write_result(self, run_id: str, result: Mapping[str, Any]) -> None:
        """Atomically publish result JSON inside the opened run directory."""

        with self._open_runs_root() as root_descriptor:
            with self._open_run(root_descriptor, run_id) as run_descriptor:
                self._write_json_atomic_at(run_descriptor, "result.json", result)

    def read_result(self, run_id: str) -> dict[str, Any]:
        """Read projected result JSON through an opened run directory."""

        with self._open_runs_root() as root_descriptor:
            with self._open_run(root_descriptor, run_id) as run_descriptor:
                return self._read_json_at(
                    run_descriptor,
                    "result.json",
                    invalid_code="BACKTEST_RESULT_INVALID",
                )

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return valid run records newest-first, bounded to 1..100."""

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("BACKTEST_RUN_LIMIT_INVALID")
        try:
            with self._open_runs_root() as root_descriptor:
                names = os.listdir(root_descriptor)
                records: list[dict[str, Any]] = []
                for name in names:
                    if _RUN_ID.fullmatch(name) is None:
                        continue
                    try:
                        with self._open_run(root_descriptor, name) as run_descriptor:
                            record = self._read_json_at(
                                run_descriptor,
                                "run.json",
                                invalid_code="BACKTEST_RUN_RECORD_INVALID",
                            )
                    except (BacktestError, OSError, ValueError):
                        continue
                    if record.get("run_id") != name or not isinstance(
                        record.get("started_at"), str
                    ):
                        continue
                    records.append(record)
        except FileNotFoundError:
            return []
        records.sort(
            key=lambda item: (str(item["started_at"]), str(item["run_id"])),
            reverse=True,
        )
        return records[:limit]

    def read_log_tail(
        self,
        run_id: str,
        stream: str,
        *,
        max_lines: int = _MAX_LOG_LINES,
        max_bytes: int = _MAX_LOG_BYTES,
    ) -> str:
        """Read a tail bounded by both line count and final UTF-8 byte length."""

        if (
            stream not in _LOG_NAMES
            or isinstance(max_lines, bool)
            or not isinstance(max_lines, int)
            or not 1 <= max_lines <= _MAX_LOG_LINES
            or isinstance(max_bytes, bool)
            or not isinstance(max_bytes, int)
            or not 1 <= max_bytes <= _MAX_LOG_BYTES
        ):
            raise ValueError("BACKTEST_LOG_REQUEST_INVALID")
        with self._open_runs_root() as root_descriptor:
            with self._open_run(root_descriptor, run_id) as run_descriptor:
                descriptor = self._open_regular_at(
                    run_descriptor,
                    _LOG_NAMES[stream],
                )
                try:
                    size = os.lseek(descriptor, 0, os.SEEK_END)
                    os.lseek(descriptor, max(0, size - max_bytes), os.SEEK_SET)
                    content = os.read(descriptor, max_bytes)
                finally:
                    os.close(descriptor)
        text = content.decode("utf-8", errors="replace")
        line_bounded = "\n".join(text.splitlines()[-max_lines:])
        return self._encoded_tail(line_bounded, max_bytes)

    def resolve_artifact(self, run_id: str, kind: str) -> BinaryIO:
        """Return an opened no-follow artifact stream, never a reusable path."""

        filename = _ARTIFACT_NAMES.get(kind)
        if filename is None:
            self._artifact_not_found()
        try:
            with self._open_runs_root() as root_descriptor:
                with self._open_run(root_descriptor, run_id) as run_descriptor:
                    descriptor = self._open_regular_at(run_descriptor, filename)
        except (FileNotFoundError, OSError, ValueError):
            self._artifact_not_found()
        try:
            return cast(BinaryIO, os.fdopen(descriptor, mode="rb"))
        except Exception:
            os.close(descriptor)
            raise

    @contextmanager
    def temporary_report_zip(self, run_id: str) -> Iterator[BinaryIO]:
        """Yield an anonymous temporary ZIP stream and close it after use."""

        with tempfile.TemporaryFile(mode="w+b") as temporary:
            try:
                with self._open_runs_root() as root_descriptor:
                    with self._open_run(root_descriptor, run_id) as run_descriptor:
                        with self._open_directory_at(
                            run_descriptor,
                            "report",
                        ) as report_descriptor:
                            with ZipFile(
                                temporary,
                                mode="w",
                                compression=ZIP_DEFLATED,
                            ) as archive:
                                count = self._zip_directory(
                                    archive,
                                    report_descriptor,
                                    PurePosixPath("report"),
                                )
            except BacktestError:
                raise
            except (FileNotFoundError, OSError, ValueError):
                self._artifact_not_found()
            if count == 0:
                self._artifact_not_found()
            temporary.seek(0)
            yield cast(BinaryIO, temporary)

    def acquire_lock(self, run_id: str, *, pid: int, started_at: str) -> ActiveLock:
        """Acquire ``active.lock`` with O_EXCL under process/thread serialization."""

        self._validate_run_id(run_id)
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or not isinstance(started_at, str)
            or not started_at
        ):
            raise ValueError("BACKTEST_LOCK_INVALID")
        lock = ActiveLock(run_id=run_id, pid=pid, started_at=started_at)
        payload = {
            "run_id": lock.run_id,
            "pid": lock.pid,
            "started_at": lock.started_at,
        }
        data = self._json_bytes(payload)
        with self._locked_root(create=True) as root_descriptor:
            try:
                descriptor = os.open(
                    "active.lock",
                    _CREATE_FILE_FLAGS,
                    0o600,
                    dir_fd=root_descriptor,
                )
            except FileExistsError as exc:
                raise BacktestError(
                    BacktestHttpErrorCode.BACKTEST_ALREADY_RUNNING
                ) from exc
            identity = os.fstat(descriptor)
            try:
                with os.fdopen(descriptor, mode="wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                self._unlink_if_identity(root_descriptor, identity)
                raise
        return lock

    def read_lock(self) -> ActiveLock | None:
        """Read the exact active lock through a serialized opened descriptor."""

        try:
            with self._locked_root() as root_descriptor:
                opened = self._open_lock_at(root_descriptor)
                if opened is None:
                    return None
                try:
                    return opened.lock
                finally:
                    os.close(opened.descriptor)
        except FileNotFoundError:
            return None

    def release_lock(self, run_id: str) -> bool:
        """Delete only the serialized, identity-matched lock for this owner."""

        self._validate_run_id(run_id)
        try:
            with self._locked_root() as root_descriptor:
                return self._release_lock_at(root_descriptor, run_id)
        except FileNotFoundError:
            return False

    def reconcile_stale_lock(
        self,
        *,
        pid_exists: Callable[[int], bool] | None = None,
    ) -> ActiveLock | None:
        """Keep live PIDs busy and fail closed on damaged run identity."""

        try:
            with self._locked_root() as root_descriptor:
                opened = self._open_lock_at(root_descriptor)
                if opened is None:
                    return None
                try:
                    checker = pid_exists or self._pid_exists
                    if checker(opened.lock.pid):
                        return opened.lock
                    with self._open_run(
                        root_descriptor,
                        opened.lock.run_id,
                    ) as run_descriptor:
                        run = self._read_json_at(
                            run_descriptor,
                            "run.json",
                            invalid_code="BACKTEST_RUN_RECORD_INVALID",
                        )
                        status = self._validated_reconcile_status(run, opened.lock)
                        if status is RunStatus.RUNNING:
                            updated = {
                                **run,
                                "status": RunStatus.INTERRUPTED,
                                "failure_code": RunFailureCode.RUN_INTERRUPTED,
                                "finished_at": datetime.now(timezone.utc).isoformat(),
                            }
                            self._write_json_atomic_at(
                                run_descriptor,
                                "run.json",
                                updated,
                            )
                    if not self._unlink_if_opened_lock(root_descriptor, opened):
                        raise ValueError("BACKTEST_LOCK_INVALID")
                    return None
                finally:
                    os.close(opened.descriptor)
        except FileNotFoundError:
            return None

    @contextmanager
    def _locked_root(self, *, create: bool = False) -> Iterator[int]:
        with self._thread_lock:
            with self._open_runs_root(create=create) as root_descriptor:
                fcntl.flock(root_descriptor, fcntl.LOCK_EX)
                try:
                    yield root_descriptor
                finally:
                    fcntl.flock(root_descriptor, fcntl.LOCK_UN)

    @contextmanager
    def _open_runs_root(self, *, create: bool = False) -> Iterator[int]:
        with self._open_absolute_directory(
            self.runs_root,
            create=create,
        ) as descriptor:
            yield descriptor

    @classmethod
    @contextmanager
    def _open_absolute_directory(
        cls,
        path: Path,
        *,
        create: bool,
    ) -> Iterator[int]:
        if not path.is_absolute():
            raise ValueError("BACKTEST_PATH_INVALID")
        descriptor = os.open("/", _DIRECTORY_FLAGS)
        try:
            for component in path.parts[1:]:
                if create:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                next_descriptor = os.open(
                    component,
                    _DIRECTORY_FLAGS,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = next_descriptor
            cls._require_directory_descriptor(descriptor)
            yield descriptor
        finally:
            os.close(descriptor)

    @classmethod
    @contextmanager
    def _open_absolute_regular_file(cls, path: Path) -> Iterator[int]:
        if not path.is_absolute() or not path.name:
            raise ValueError("BACKTEST_STRATEGY_SNAPSHOT_INVALID")
        try:
            with cls._open_absolute_directory(
                path.parent,
                create=False,
            ) as parent_descriptor:
                descriptor = cls._open_regular_at(parent_descriptor, path.name)
                try:
                    yield descriptor
                finally:
                    os.close(descriptor)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise ValueError("BACKTEST_STRATEGY_SNAPSHOT_INVALID") from exc

    @classmethod
    @contextmanager
    def _open_directory_at(cls, parent_descriptor: int, name: str) -> Iterator[int]:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_descriptor)
        try:
            cls._require_directory_descriptor(descriptor)
            yield descriptor
        finally:
            os.close(descriptor)

    @classmethod
    @contextmanager
    def _open_run(cls, root_descriptor: int, run_id: str) -> Iterator[int]:
        cls._validate_run_id(run_id)
        try:
            descriptor = os.open(
                run_id,
                _DIRECTORY_FLAGS,
                dir_fd=root_descriptor,
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise BacktestError(BacktestHttpErrorCode.BACKTEST_RUN_NOT_FOUND) from exc
        try:
            cls._require_directory_descriptor(descriptor)
        except ValueError as exc:
            os.close(descriptor)
            raise BacktestError(BacktestHttpErrorCode.BACKTEST_RUN_NOT_FOUND) from exc
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _open_regular_at(parent_descriptor: int, name: str) -> int:
        try:
            descriptor = os.open(name, _READ_FILE_FLAGS, dir_fd=parent_descriptor)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise ValueError("BACKTEST_PATH_INVALID") from exc
            raise
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(descriptor)
            raise ValueError("BACKTEST_PATH_INVALID")
        return descriptor

    @staticmethod
    def _write_exclusive_at(
        parent_descriptor: int,
        name: str,
        content: bytes,
    ) -> None:
        descriptor = os.open(
            name,
            _CREATE_FILE_FLAGS,
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            with os.fdopen(descriptor, mode="wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise

    @classmethod
    def _write_json_atomic_at(
        cls,
        parent_descriptor: int,
        name: str,
        payload: Mapping[str, Any],
    ) -> None:
        content = cls._json_bytes(payload)
        temporary = f".{name}.{secrets.token_hex(16)}.tmp"
        try:
            cls._write_exclusive_at(parent_descriptor, temporary, content)
            os.replace(
                temporary,
                name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
        finally:
            try:
                os.unlink(temporary, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass

    @classmethod
    def _read_json_at(
        cls,
        parent_descriptor: int,
        name: str,
        *,
        invalid_code: str,
    ) -> dict[str, Any]:
        descriptor = cls._open_regular_at(parent_descriptor, name)
        try:
            return cls._read_json_descriptor(descriptor, invalid_code=invalid_code)
        finally:
            os.close(descriptor)

    @classmethod
    def _read_json_descriptor(
        cls,
        descriptor: int,
        *,
        invalid_code: str,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(cls._read_all(descriptor).decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(invalid_code) from exc
        if not isinstance(payload, dict):
            raise ValueError(invalid_code)
        return payload

    @staticmethod
    def _read_all(descriptor: int) -> bytes:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    @staticmethod
    def _json_bytes(payload: Mapping[str, Any]) -> bytes:
        rendered = json.dumps(
            dict(payload),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return f"{rendered}\n".encode("utf-8")

    @staticmethod
    def _encoded_tail(text: str, max_bytes: int) -> str:
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        start = len(encoded) - max_bytes
        while start < len(encoded) and encoded[start] & 0b1100_0000 == 0b1000_0000:
            start += 1
        return encoded[start:].decode("utf-8")

    @classmethod
    def _zip_directory(
        cls,
        archive: ZipFile,
        directory_descriptor: int,
        archive_root: PurePosixPath,
    ) -> int:
        count = 0
        for name in sorted(os.listdir(directory_descriptor)):
            if not name or name in {".", ".."} or "/" in name:
                raise ValueError("BACKTEST_PATH_INVALID")
            try:
                with cls._open_directory_at(
                    directory_descriptor,
                    name,
                ) as child_descriptor:
                    count += cls._zip_directory(
                        archive,
                        child_descriptor,
                        archive_root / name,
                    )
                continue
            except OSError as exc:
                if exc.errno not in {errno.ENOTDIR, errno.ELOOP}:
                    raise
                if exc.errno == errno.ELOOP:
                    raise ValueError("BACKTEST_PATH_INVALID") from exc
            descriptor = cls._open_regular_at(directory_descriptor, name)
            try:
                archive.writestr(str(archive_root / name), cls._read_all(descriptor))
            finally:
                os.close(descriptor)
            count += 1
        return count

    @classmethod
    def _open_lock_at(cls, root_descriptor: int) -> _OpenedLock | None:
        try:
            descriptor = cls._open_regular_at(root_descriptor, "active.lock")
        except FileNotFoundError:
            return None
        try:
            payload = cls._read_json_descriptor(
                descriptor,
                invalid_code="BACKTEST_LOCK_INVALID",
            )
            if set(payload) != {"run_id", "pid", "started_at"}:
                raise ValueError("BACKTEST_LOCK_INVALID")
            run_id = payload["run_id"]
            pid = payload["pid"]
            started_at = payload["started_at"]
            if (
                not isinstance(run_id, str)
                or _RUN_ID.fullmatch(run_id) is None
                or isinstance(pid, bool)
                or not isinstance(pid, int)
                or pid <= 0
                or not isinstance(started_at, str)
                or not started_at
            ):
                raise ValueError("BACKTEST_LOCK_INVALID")
            metadata = os.fstat(descriptor)
            return _OpenedLock(
                lock=ActiveLock(run_id=run_id, pid=pid, started_at=started_at),
                descriptor=descriptor,
                device=metadata.st_dev,
                inode=metadata.st_ino,
            )
        except Exception:
            os.close(descriptor)
            raise

    @classmethod
    def _release_lock_at(cls, root_descriptor: int, run_id: str) -> bool:
        opened = cls._open_lock_at(root_descriptor)
        if opened is None:
            return False
        try:
            if opened.lock.run_id != run_id:
                return False
            return cls._unlink_if_opened_lock(root_descriptor, opened)
        finally:
            os.close(opened.descriptor)

    @staticmethod
    def _unlink_if_opened_lock(root_descriptor: int, opened: _OpenedLock) -> bool:
        try:
            metadata = os.stat(
                "active.lock",
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        if (metadata.st_dev, metadata.st_ino) != (opened.device, opened.inode):
            return False
        os.unlink("active.lock", dir_fd=root_descriptor)
        return True

    @staticmethod
    def _unlink_if_identity(root_descriptor: int, identity: os.stat_result) -> bool:
        try:
            metadata = os.stat(
                "active.lock",
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        if (metadata.st_dev, metadata.st_ino) != (identity.st_dev, identity.st_ino):
            return False
        os.unlink("active.lock", dir_fd=root_descriptor)
        return True

    @staticmethod
    def _validated_reconcile_status(
        run: Mapping[str, Any],
        lock: ActiveLock,
    ) -> RunStatus:
        strategy_sha256 = run.get("strategy_sha256")
        if (
            run.get("run_id") != lock.run_id
            or run.get("started_at") != lock.started_at
            or not isinstance(strategy_sha256, str)
            or _SHA256.fullmatch(strategy_sha256) is None
        ):
            raise ValueError("BACKTEST_RUN_RECORD_INVALID")
        status = run.get("status")
        if not isinstance(status, str):
            raise ValueError("BACKTEST_RUN_RECORD_INVALID")
        try:
            return RunStatus(status)
        except ValueError as exc:
            raise ValueError("BACKTEST_RUN_RECORD_INVALID") from exc

    @staticmethod
    def _require_directory_descriptor(descriptor: int) -> None:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise ValueError("BACKTEST_PATH_INVALID")

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise ValueError("BACKTEST_RUN_ID_INVALID")

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _artifact_not_found() -> NoReturn:
        raise BacktestError(BacktestHttpErrorCode.BACKTEST_ARTIFACT_NOT_FOUND)


__all__ = ["ActiveLock", "ArtifactStore", "RunPaths"]
