"""Filesystem-only artifacts and the single-run lock for local backtests."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, NoReturn
from zipfile import ZIP_DEFLATED, ZipFile

from app.backtest.config import BacktestSettings
from app.backtest.contracts import RunStatus
from app.backtest.errors import BacktestError, BacktestHttpErrorCode, RunFailureCode


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
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


class ArtifactStore:
    """Concrete, bounded filesystem storage for local research runs."""

    def __init__(self, settings: BacktestSettings) -> None:
        self.runs_root = settings.runs_root.resolve(strict=False)
        self.lock_path = self.runs_root / "active.lock"

    def run_paths(self, run_id: str) -> RunPaths:
        """Return only fixed paths below a validated run id."""

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
        """Create one fixed run tree and snapshot its registered strategy."""

        paths = self.run_paths(run_id)
        source = strategy_file.resolve(strict=True)
        source_metadata = strategy_file.lstat()
        if (
            not strategy_file.is_absolute()
            or stat.S_ISLNK(source_metadata.st_mode)
            or not stat.S_ISREG(source_metadata.st_mode)
        ):
            raise ValueError("BACKTEST_STRATEGY_SNAPSHOT_INVALID")
        source_bytes = source.read_bytes()
        strategy_sha256 = sha256(source_bytes).hexdigest()

        self._ensure_runs_root()
        paths.root.mkdir(mode=0o700)
        paths.report_dir.mkdir(mode=0o700)
        paths.strategy_file.write_bytes(source_bytes)
        paths.stdout_log.touch(mode=0o600)
        paths.stderr_log.touch(mode=0o600)
        self._write_json_atomic(paths.strategy_params_json, dict(strategy_params))
        payload = dict(run_record)
        payload["run_id"] = run_id
        payload["strategy_sha256"] = strategy_sha256
        self._write_json_atomic(paths.run_json, payload)
        return paths

    def read_run(self, run_id: str) -> dict[str, Any]:
        """Read the authoritative run record without following symlinks."""

        paths = self._existing_run_paths(run_id)
        return self._read_json_object(
            self._safe_regular_file(paths.root, paths.run_json),
            invalid_code="BACKTEST_RUN_RECORD_INVALID",
        )

    def update_run(
        self,
        run_id: str,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Merge and atomically replace the authoritative run record."""

        paths = self._existing_run_paths(run_id)
        current = self.read_run(run_id)
        updated = {**current, **dict(changes)}
        updated["run_id"] = current.get("run_id", run_id)
        updated["strategy_sha256"] = current.get("strategy_sha256")
        self._write_json_atomic(paths.run_json, updated)
        return updated

    def write_result(self, run_id: str, result: Mapping[str, Any]) -> None:
        """Atomically publish the Web-facing result projection."""

        paths = self._existing_run_paths(run_id)
        self._write_json_atomic(paths.result_json, dict(result))

    def read_result(self, run_id: str) -> dict[str, Any]:
        """Read the Web-facing result projection without following symlinks."""

        paths = self._existing_run_paths(run_id)
        path = self._safe_regular_file(paths.root, paths.result_json)
        return self._read_json_object(path, invalid_code="BACKTEST_RESULT_INVALID")

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return valid run records newest-first, bounded to 1..100."""

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("BACKTEST_RUN_LIMIT_INVALID")
        if not self.runs_root.exists():
            return []
        self._require_safe_directory(self.runs_root, self.runs_root)
        records: list[dict[str, Any]] = []
        for item in self.runs_root.iterdir():
            if _RUN_ID.fullmatch(item.name) is None:
                continue
            try:
                metadata = item.lstat()
                if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                    continue
                record = self.read_run(item.name)
            except (BacktestError, OSError, ValueError):
                continue
            if record.get("run_id") != item.name or not isinstance(
                record.get("started_at"), str
            ):
                continue
            records.append(record)
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
        """Read a bounded UTF-8-safe tail from one fixed log."""

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
        paths = self._existing_run_paths(run_id)
        path = self._safe_regular_file(paths.root, paths.root / _LOG_NAMES[stream])
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            content = handle.read(max_bytes)
        text = content.decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-max_lines:])

    def resolve_artifact(self, run_id: str, kind: str) -> Path:
        """Resolve one fixed persistent download kind or fail closed."""

        filename = _ARTIFACT_NAMES.get(kind)
        if filename is None:
            self._artifact_not_found()
        paths = self._existing_run_paths(run_id)
        try:
            return self._safe_regular_file(paths.root, paths.root / filename)
        except (FileNotFoundError, OSError, ValueError):
            self._artifact_not_found()

    @contextmanager
    def temporary_report_zip(self, run_id: str) -> Iterator[Path]:
        """Yield an OS-temporary report archive and remove it after consumption."""

        paths = self._existing_run_paths(run_id)
        try:
            report = self._require_safe_directory(paths.root, paths.report_dir)
            files = self._safe_report_files(paths.root, report)
        except (FileNotFoundError, OSError, ValueError):
            self._artifact_not_found()
        if not files:
            self._artifact_not_found()

        descriptor, raw_path = tempfile.mkstemp(
            prefix="guiyi-backtest-report-",
            suffix=".zip",
        )
        os.close(descriptor)
        zip_path = Path(raw_path)
        try:
            with ZipFile(zip_path, mode="w", compression=ZIP_DEFLATED) as archive:
                for item in files:
                    archive.write(
                        item, arcname=Path("report") / item.relative_to(report)
                    )
            yield zip_path
        finally:
            zip_path.unlink(missing_ok=True)

    def acquire_lock(self, run_id: str, *, pid: int, started_at: str) -> ActiveLock:
        """Acquire ``active.lock`` with O_EXCL or report a busy store."""

        self._validate_run_id(run_id)
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or not isinstance(started_at, str)
            or not started_at
        ):
            raise ValueError("BACKTEST_LOCK_INVALID")
        self._ensure_runs_root()
        lock = ActiveLock(run_id=run_id, pid=pid, started_at=started_at)
        try:
            descriptor = os.open(
                self.lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise BacktestError(BacktestHttpErrorCode.BACKTEST_ALREADY_RUNNING) from exc
        try:
            with os.fdopen(descriptor, mode="w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "run_id": lock.run_id,
                        "pid": lock.pid,
                        "started_at": lock.started_at,
                    },
                    handle,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self.lock_path.unlink(missing_ok=True)
            raise
        return lock

    def read_lock(self) -> ActiveLock | None:
        """Read the exact active lock payload without following symlinks."""

        try:
            self.lock_path.lstat()
        except FileNotFoundError:
            return None
        self._ensure_runs_root()
        path = self._safe_regular_file(self.runs_root, self.lock_path)
        payload = self._read_json_object(path, invalid_code="BACKTEST_LOCK_INVALID")
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
        return ActiveLock(run_id=run_id, pid=pid, started_at=started_at)

    def release_lock(self, run_id: str) -> bool:
        """Release only when the lock still names the matching run."""

        self._validate_run_id(run_id)
        lock = self.read_lock()
        if lock is None or lock.run_id != run_id:
            return False
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            return False
        return True

    def reconcile_stale_lock(
        self,
        *,
        pid_exists: Callable[[int], bool] | None = None,
    ) -> ActiveLock | None:
        """Keep live PIDs busy; interrupt a running run only after its PID is gone."""

        lock = self.read_lock()
        if lock is None:
            return None
        checker = pid_exists or self._pid_exists
        if checker(lock.pid):
            return lock
        run = self.read_run(lock.run_id)
        if run.get("status") == RunStatus.RUNNING:
            self.update_run(
                lock.run_id,
                {
                    "status": RunStatus.INTERRUPTED,
                    "failure_code": RunFailureCode.RUN_INTERRUPTED,
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        self.release_lock(lock.run_id)
        return None

    def _ensure_runs_root(self) -> None:
        self.runs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._require_safe_directory(self.runs_root, self.runs_root)

    def _existing_run_paths(self, run_id: str) -> RunPaths:
        paths = self.run_paths(run_id)
        try:
            self._require_safe_directory(self.runs_root, paths.root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise BacktestError(BacktestHttpErrorCode.BACKTEST_RUN_NOT_FOUND) from exc
        return paths

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise ValueError("BACKTEST_RUN_ID_INVALID")

    @staticmethod
    def _read_json_object(path: Path, *, invalid_code: str) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(invalid_code) from exc
        if not isinstance(payload, dict):
            raise ValueError(invalid_code)
        return payload

    @staticmethod
    def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(raw_temporary)
        try:
            with os.fdopen(descriptor, mode="w", encoding="utf-8") as handle:
                json.dump(
                    dict(payload),
                    handle,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _require_safe_directory(root: Path, path: Path) -> Path:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("BACKTEST_PATH_INVALID")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError("BACKTEST_PATH_INVALID")
        return resolved

    @staticmethod
    def _safe_regular_file(root: Path, path: Path) -> Path:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("BACKTEST_PATH_INVALID")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError("BACKTEST_PATH_INVALID")
        return resolved

    @staticmethod
    def _safe_report_files(run_root: Path, report: Path) -> list[Path]:
        files: list[Path] = []
        for item in sorted(report.rglob("*")):
            metadata = item.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("BACKTEST_PATH_INVALID")
            resolved = item.resolve(strict=True)
            if not resolved.is_relative_to(run_root):
                raise ValueError("BACKTEST_PATH_INVALID")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("BACKTEST_PATH_INVALID")
            files.append(resolved)
        return files

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
