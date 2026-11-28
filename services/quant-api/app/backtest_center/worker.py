"""Supervise a bounded, separate Plus process from the local workstation."""

from dataclasses import dataclass
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep

from .contracts import EXECUTION_POLICY, RESEARCH_PROFILE, BacktestError, RunConfig, admission_code
from .codec import digest, encode
from .provenance import code_digest
from .store import RunStore

log = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parents[4]
_ENTRY = Path(__file__).with_name("plus_entry.py")
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,100}$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^(?:rqalpha_plus_bundle_)?[0-9a-f]{64}$")
_ENV = (
    "HOME", "TMPDIR", "LANG", "LC_CTYPE", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "RQSDK_LICENSE",
)
_MAX_RUNTIME_SECONDS = 900
_MAX_RESULT_BYTES = 96 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Settings:
    path: Path
    python: Path | None
    bundle: Path | None
    revision: str | None = None

    @classmethod
    def local(cls):
        default = Path.home() / ".local/state/guiyi/backtest-center/research.sqlite3"
        python = os.getenv("GUIYI_BACKTEST_PLUS_PYTHON")
        bundle = os.getenv("GUIYI_BACKTEST_PLUS_BUNDLE")
        return cls(
            Path(os.getenv("GUIYI_BACKTEST_STORE", str(default))).expanduser(),
            Path(python).expanduser() if python else None,
            Path(bundle).expanduser() if bundle else None,
            os.getenv("GUIYI_BACKTEST_CODE_REVISION"),
        )

    def code_identity(self) -> dict:
        revision = self.revision
        if revision is None and (_ROOT / ".git").exists():
            try:
                revision = subprocess.check_output(
                    ["git", "rev-parse", "--verify", "HEAD"], cwd=_ROOT, text=True,
                    stderr=subprocess.DEVNULL, timeout=5,
                ).strip()
            except (OSError, subprocess.SubprocessError):
                pass
        if not revision or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise BacktestError("BACKTEST_CODE_REVISION_UNAVAILABLE")
        return {"code_revision": revision, "code_sha256": code_digest()}

    def bundle_path(self) -> Path | None:
        path = self.bundle
        if path and (path / "bundle").is_dir() and not (path / "h5").is_dir():
            return path / "bundle"
        return path

    def bundle_signature(self, contract: str) -> str | None:
        bundle = self.bundle_path()
        if not bundle or not bundle.is_absolute() or not bundle.is_dir():
            return None
        from .plus_inputs import BASE_FILES

        identities = []
        for relative in (*BASE_FILES, f"h5/future/{contract}.h5"):
            try:
                record = (bundle / relative).stat()
                identities.append((relative, record.st_dev, record.st_ino, record.st_size,
                                   record.st_mtime_ns, record.st_ctime_ns))
            except OSError:
                identities.append((relative, None))
        return digest(identities)

    def submission(self, config: dict) -> dict:
        try:
            code = self.code_identity()
        except BacktestError:
            code = {}
        return {**code, "bundle_signature": self.bundle_signature(config["contract"])}


def _read(path: Path, limit: int) -> dict:
    if path.stat().st_size > limit:
        raise BacktestError("BACKTEST_ARTIFACT_LIMIT")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise BacktestError("BACKTEST_ARTIFACT_INVALID")
    return data


def _snapshot(data: dict) -> None:
    engine = data.get("engine")
    if (
        not isinstance(engine, dict) or engine.get("name") != "rqalpha-plus" or not engine.get("version")
        or data.get("qualification") not in ("TRIAL", "QUALIFIED")
        or not isinstance(data.get("data_revision"), str) or not _REVISION.fullmatch(data["data_revision"])
        or not isinstance(data.get("input_sha256"), str) or not _HEX.fullmatch(data["input_sha256"])
    ):
        raise BacktestError("PLUS_INPUT_IDENTITY_INVALID")


def _result(data: dict, run_id: str, snapshot: dict) -> dict:
    if data.get("run_id") != run_id or data.get("snapshot_sha256") != digest(snapshot):
        raise BacktestError("BACKTEST_RESULT_IDENTITY_MISMATCH")
    result = data.get("result")
    if (
        not isinstance(result, dict) or not isinstance(result.get("summary"), dict)
        or not isinstance(result.get("report"), dict)
        or any(not isinstance(result.get(kind), list) for kind in ("bars", "markers", "trades", "equity"))
        or not result["equity"]
    ):
        raise BacktestError("BACKTEST_RESULT_INVALID")
    if any(not isinstance(row, dict) or not row.get("trade_id") for row in result["trades"]):
        raise BacktestError("BACKTEST_TRADE_IDENTITY_INVALID")
    return result


def _group_alive(process: subprocess.Popen) -> bool:
    process.poll()
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _stop(process: subprocess.Popen) -> None:
    deadline = monotonic() + 3
    if _group_alive(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            log.error("BACKTEST_ENGINE_STOP_UNCONFIRMED")
    while _group_alive(process) and monotonic() < deadline:
        sleep(0.05)
    if _group_alive(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            log.error("BACKTEST_ENGINE_STOP_UNCONFIRMED")
    # Keep the dispatcher lock and CANCELING state until termination is observable.
    while _group_alive(process):
        sleep(0.1)
    process.wait()


class Worker:
    def __init__(self, settings: Settings, store: RunStore):
        self.settings = settings
        self.store = store
        self.stopping = Event()
        self.thread = Thread(target=self.run, name="backtest-center", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=8)

    def run(self):
        lock_path = self.store.path.with_name(self.store.path.name + ".worker.lock")
        while not self.stopping.is_set():
            try:
                with lock_path.open("a+b") as lock:
                    try:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        self.stopping.wait(1)
                        continue
                    self._supervise(lock.fileno())
            except (OSError, sqlite3.Error):
                log.error("BACKTEST_WORKER_STORAGE_UNAVAILABLE")
                self.stopping.wait(1)

    def _supervise(self, fd):
        from .experiments import advance_experiments

        self.store.recover()
        while not self.stopping.is_set():
            advance_experiments(self.store)
            run = self.store.claim()
            if run is None:
                self.stopping.wait(0.25)
                continue
            try:
                self._execute(run, fd)
            except BacktestError as exc:
                self.store.finish_stopped(run["run_id"], exc.code)
            except (OSError, ValueError, subprocess.SubprocessError):
                self.store.finish_stopped(run["run_id"], "BACKTEST_ENGINE_PROCESS_ERROR")

    def _execute(self, run, fd):
        run_id = run["run_id"]
        config = RunConfig.model_validate(run["config"])
        code = admission_code(config)
        if code:
            raise BacktestError(code)
        python, bundle = self.settings.python, self.settings.bundle_path()
        if not python or not python.is_absolute() or not python.is_file() or not os.access(python, os.X_OK):
            raise BacktestError("PLUS_PYTHON_UNAVAILABLE")
        if not bundle or not bundle.is_absolute() or not bundle.is_dir():
            raise BacktestError("PLUS_NATIVE_BUNDLE_UNAVAILABLE")
        identity = self.settings.code_identity()
        submitted = run["submission_identity"]
        if submitted is not None:
            if identity.get("code_sha256") != submitted.get("code_sha256"):
                raise BacktestError("BACKTEST_SUBMITTED_CODE_CHANGED")
            if self.settings.bundle_signature(config.contract) != submitted.get("bundle_signature"):
                raise BacktestError("BACKTEST_SUBMITTED_DATA_CHANGED")
        source = self.store.get(run["source_run_id"]) if run["source_run_id"] else None
        expected = source["snapshot"] if source else None
        if expected and expected.get("code_sha256") != identity["code_sha256"]:
            raise BacktestError("REPLAY_CODE_REVISION_UNAVAILABLE")

        with TemporaryDirectory(prefix="plus-", dir=self.store.path.parent) as temp:
            scratch = Path(temp)
            request = {"run_id": run_id, "config": run["config"], "expected": expected, "identity": identity,
                       "execution_policy": EXECUTION_POLICY, "research_profile_id": RESEARCH_PROFILE}
            (scratch / "request.json").write_text(encode(request))
            process = subprocess.Popen(
                [str(python), "-I", "-B", str(_ENTRY), str(scratch), str(bundle.resolve())],
                cwd=scratch,
                env={"PATH": os.defpath, **{name: os.environ[name] for name in _ENV if name in os.environ}},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, pass_fds=(fd,),
            )
            try:
                snapshot = self._monitor(process, scratch, run_id, expected, submitted, config.contract)
            finally:
                _stop(process)

            response = scratch / "result.json"
            if not response.is_file():
                raise BacktestError("PLUS_PROCESS_EXITED_WITHOUT_RESULT")
            data = _read(response, _MAX_RESULT_BYTES)
            if error := data.get("error"):
                raise BacktestError(error if isinstance(error, str) and _CODE.fullmatch(error) else "PLUS_RUN_FAILED")
            if snapshot is None or process.returncode != 0:
                raise BacktestError("PLUS_ADMISSION_NOT_CONFIRMED")
            result = _result(data, run_id, snapshot)
            self.store.phase(run_id, "PUBLISHING")
            self._publish(run_id, result)

    def _monitor(self, process, scratch, run_id, expected, submitted, contract):
        deadline = monotonic() + _MAX_RUNTIME_SECONDS
        admission, ack = scratch / "admission.json", scratch / "admission.ok"
        snapshot = None
        while process.poll() is None:
            current = self.store.get(run_id)
            if current is None or current["status"] != "RUNNING":
                raise BacktestError("BACKTEST_CANCELED")
            if self.stopping.is_set():
                raise BacktestError("BACKTEST_WORKER_STOPPING")
            if monotonic() > deadline:
                raise BacktestError("BACKTEST_ENGINE_TIMEOUT")
            if snapshot is None and admission.is_file():
                snapshot = _read(admission, 128 * 1024)
                _snapshot(snapshot)
                if submitted is not None and self.settings.bundle_signature(contract) != submitted["bundle_signature"]:
                    raise BacktestError("BACKTEST_SUBMITTED_DATA_CHANGED")
                if expected and any(snapshot.get(key) != expected.get(key)
                                    for key in ("data_revision", "input_sha256", "engine", "data_files")):
                    raise BacktestError("REPLAY_INPUT_REVISION_UNAVAILABLE")
                if not self.store.admit(run_id, snapshot):
                    raise BacktestError("BACKTEST_CANCELED")
                ack.touch(exist_ok=False)
            self.stopping.wait(0.08)
        return snapshot

    def _publish(self, run_id, result):
        try:
            published = self.store.publish(run_id, result)
        except sqlite3.Error:
            # A separate connection owns the readback. Keep the Run fenced
            # if storage is still unavailable, even when the process is gone.
            current = self.store.get(run_id)
            if current and current["status"] == "SUCCEEDED" and current["result_digest"] == digest(result):
                return
            self.store.finish_stopped(run_id, "BACKTEST_PUBLICATION_INTERRUPTED")
            return
        if not published:
            self.store.finish_stopped(run_id, "BACKTEST_CANCELED")
