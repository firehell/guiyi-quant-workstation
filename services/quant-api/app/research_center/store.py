"""Research task index and verified immutable sample files."""

from hashlib import sha256, file_digest
import json
import os
from pathlib import Path
import subprocess
import signal
from tempfile import TemporaryFile
from time import monotonic, sleep

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import text

from app.backtest_center.codec import encode
from app.core.env import PROJECT_ROOT
from app.research_center import VERSION
from app.research_center.assistant import local_model_config
from app.research_center.inputs import ResearchError

def worker_root():
    default = PROJECT_ROOT / "services/research-worker"
    return Path(os.getenv("GUIYI_RESEARCH_WORKER_ROOT", str(default))).expanduser()

TIME_BUDGET = 30
MAX_INPUT = 8 * 1024 * 1024
SELECT_TASK = """
    SELECT id, request, rerun_of, started_at,
           CASE WHEN status IN ('RUNNING','CANCELING') AND deadline<=clock_timestamp() THEN 'FAILED' ELSE status END AS status,
           CASE WHEN status IN ('RUNNING','CANCELING') AND deadline<=clock_timestamp() THEN 'WORKER_LEASE_EXPIRED'
                ELSE reason END AS reason,
           input_digest, result_digest, result, CAST(result AS text) AS result_text
    FROM statistics_research_tasks
"""


def checksum(path):
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def artifact_root():
    default = Path.home() / ".local/state/guiyi/statistics-research"
    return Path(os.getenv("GUIYI_RESEARCH_ARTIFACT_ROOT", str(default))).expanduser()


def worker_python():
    default = worker_root() / ".venv/bin/python"
    return Path(os.getenv("GUIYI_RESEARCH_WORKER_PYTHON", str(default))).expanduser()


def worker_revision():
    files = ("calculate_job.py", "performance.py", "advanced.py", "assistant_model.py", "uv.lock")
    return {name: checksum(worker_root() / name) for name in files}


def compute(payload, is_running):
    python = worker_python()
    command = [str(python), "-B", str(worker_root() / "calculate_job.py")]
    raw = encode(payload).encode()
    if len(raw) > MAX_INPUT:
        raise ResearchError("RESEARCH_INPUT_BUDGET_EXCEEDED")
    if not python.is_absolute() or not python.is_file():
        raise ResearchError("RESEARCH_WORKER_NOT_CONFIGURED")
    if not is_running():
        raise ResearchError("USER_CANCELED")
    try:
        with TemporaryFile() as source, TemporaryFile() as output:
            source.write(raw)
            source.seek(0)
            with subprocess.Popen(
                command, cwd=worker_root(), stdin=source, stdout=output, stderr=subprocess.DEVNULL,
                start_new_session=True,
                env={"PATH": os.defpath, "MPLCONFIGDIR": str(artifact_root() / ".matplotlib"),
                     "GUIYI_RESEARCH_PARENT_PID": str(os.getpid()),
                     "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "POLARS_MAX_THREADS": "2",
                     **(local_model_config() if payload["source"]["kind"] == "assistant" else {})},
            ) as worker:
                deadline = monotonic() + TIME_BUDGET
                try:
                    while worker.poll() is None:
                        if monotonic() >= deadline:
                            raise ResearchError("RESEARCH_WORKER_TIMEOUT")
                        if not is_running():
                            raise ResearchError("USER_CANCELED")
                        sleep(0.2)
                    if worker.returncode:
                        raise ResearchError("RESEARCH_CALCULATION_FAILED")
                finally:
                    if worker.poll() is None:
                        try:
                            os.killpg(worker.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        worker.wait()
            output.seek(0)
            report = output.read(MAX_INPUT + 1)
            if len(report) > MAX_INPUT:
                raise ResearchError("RESEARCH_OUTPUT_BUDGET_EXCEEDED")
            return json.loads(report)
    except ResearchError:
        raise
    except (OSError, ValueError):
        raise ResearchError("RESEARCH_CALCULATION_FAILED") from None


class Store:
    def __init__(self, session):
        self.db = session

    def one(self, query, **params):
        row = self.db.execute(text(query), params).mappings().one_or_none()
        return dict(row) if row else None

    def get(self, task_id):
        row = self.one(SELECT_TASK + " WHERE id=:id", id=task_id)
        if row is None:
            return None
        canonical = row.pop("result_text")
        if row["status"] == "SUCCEEDED":
            result = row["result"]
            if canonical is None or sha256(canonical.encode()).hexdigest() != row["result_digest"]:
                raise ResearchError("RESEARCH_INDEX_DIGEST_MISMATCH")
            path = artifact_root() / f'{task_id}.parquet'
            if not path.is_file() or checksum(path) != result["artifact_sha256"]:
                raise ResearchError("RESEARCH_ARTIFACT_UNAVAILABLE")
        return row

    def samples(self, task_id, offset, limit, month, group=None):
        row = self.get(task_id)
        if not row or row["status"] != "SUCCEEDED":
            raise ResearchError("RESEARCH_RESULT_UNAVAILABLE")
        samples = self.read_samples(task_id, row["result"]["artifact_sha256"])
        if row["result"]["source"]["kind"] == "backtest":
            if group:
                samples = [item for item in samples if item.get("group") == group]
            else:
                samples = [item for item in samples if item["record_type"] == "settlement"]
        if month:
            samples = [item for item in samples if item.get("trading_day", "").startswith(month)]
        return {"total": len(samples), "items": samples[offset:offset + limit]}

    def read_samples(self, task_id, expected_digest):
        path = artifact_root() / f"{task_id}.parquet"
        with path.open("rb") as handle:
            if file_digest(handle, "sha256").hexdigest() != expected_digest:
                raise ResearchError("RESEARCH_ARTIFACT_UNAVAILABLE")
            handle.seek(0)
            table = pq.read_table(handle)
        return [json.loads(value) for value in table.column("evidence_json").to_pylist()]

    def frozen_input(self, task):
        result = task["result"]
        payload = {name: result[name] for name in result["input_fields"]}
        payload["samples"] = self.read_samples(task["id"], result["artifact_sha256"])
        original = {"payload": payload, "worker_revision": result["worker_revision"], "version": result["version"]}
        if input_digest(original) != task["input_digest"]:
            raise ResearchError("RESEARCH_INPUT_DIGEST_MISMATCH")
        return payload

    def list(self, offset, limit):
        rows = self.db.execute(text(
            "SELECT id, request, started_at, status, reason FROM (" + SELECT_TASK + ") AS tasks"
            " ORDER BY started_at DESC, id DESC LIMIT :limit OFFSET :offset"
        ), {"limit": limit + 1, "offset": offset}).mappings()
        items = [dict(row) for row in rows]
        return {"items": items[:limit], "next_offset": offset + limit if len(items) > limit else None}

    def claim(self, task_id, request, fingerprint, rerun_of):
        # Serialize admission across API processes without holding a transaction during calculation.
        self.db.execute(text("SELECT pg_advisory_xact_lock(318728146, 1)"))
        row = self.get(task_id)
        if row:
            if row["request"] != request:
                raise ResearchError("RESEARCH_REQUEST_ID_CONFLICT")
            self.db.commit()
            return row
        if rerun_of:
            old = self.get(rerun_of)
            if (old is None or old["status"] in ("RUNNING", "CANCELING")
                    or {k: v for k, v in old["request"].items() if k != "rerun_of"}
                    != {k: v for k, v in request.items() if k != "rerun_of"}):
                raise ResearchError("RESEARCH_RERUN_SOURCE_INVALID")
        expired = self.db.execute(text("""
            UPDATE statistics_research_tasks SET status='FAILED', reason='WORKER_LEASE_EXPIRED'
            WHERE status IN ('RUNNING','CANCELING') AND deadline<=clock_timestamp() RETURNING id
        """)).scalars().all()
        for expired_id in expired:
            (artifact_root() / f"{expired_id}.parquet").unlink(missing_ok=True)
            (artifact_root() / f".{expired_id}.parquet.tmp").unlink(missing_ok=True)
        if self.one("""
            SELECT id FROM statistics_research_tasks
            WHERE status IN ('RUNNING','CANCELING') AND deadline>clock_timestamp() LIMIT 1
        """):
            raise ResearchError("RESEARCH_WORKER_BUSY")
        self.db.execute(text("""
            INSERT INTO statistics_research_tasks (id,request,status,deadline,input_digest,rerun_of)
            VALUES (:id,CAST(:request AS jsonb),'RUNNING',clock_timestamp()+interval '45 seconds',:digest,:rerun)
        """), {"id": task_id, "request": encode(request), "digest": fingerprint, "rerun": rerun_of})
        self.db.commit()
        return None

    def active(self, task_id):
        row = self.one("SELECT status, deadline>clock_timestamp() AS live "
                       "FROM statistics_research_tasks WHERE id=:id", id=task_id)
        self.db.commit()
        return bool(row and row["live"] and row["status"] == "RUNNING")

    def request_cancel(self, task_id):
        self.db.execute(text("""
            UPDATE statistics_research_tasks SET status='CANCELING', reason='USER_CANCELED'
            WHERE id=:id AND status='RUNNING' AND deadline>clock_timestamp()
        """), {"id": task_id})
        self.db.commit()
        return self.get(task_id)

    def terminate(self, task_id, reason):
        self.db.execute(text("""
            UPDATE statistics_research_tasks
            SET status=CASE WHEN status='CANCELING' THEN 'CANCELED' ELSE 'FAILED' END,
                reason=CASE WHEN status='CANCELING' THEN 'USER_CANCELED' ELSE :reason END
            WHERE id=:id AND status IN ('RUNNING','CANCELING') AND deadline>clock_timestamp()
        """), {"id": task_id, "reason": reason})
        self.db.commit()
        return self.get(task_id)

    def publish(self, task_id, payload, metrics, revision):
        root = artifact_root()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = root / f"{task_id}.parquet"
        temporary = root / f".{task_id}.parquet.tmp"
        # The index is the visibility boundary. Both names are recoverable by task identity.
        try:
            with temporary.open("xb") as handle:
                table = pa.table({"evidence_json": pa.array([encode(row) for row in payload["samples"]], type=pa.string())})
                pq.write_table(table, handle, compression="zstd")
                handle.flush()
                os.fsync(handle.fileno())
            artifact_hash = checksum(temporary)
            result = {
                **{k: v for k, v in payload.items() if k != "samples"}, **metrics,
                "artifact_sha256": artifact_hash, "version": VERSION, "worker_revision": revision,
                "input_fields": sorted(set(payload) - {"samples"}),
            }
            row = self.one("""
                SELECT id FROM statistics_research_tasks
                WHERE id=:id AND status='RUNNING' AND deadline>clock_timestamp() FOR UPDATE
            """, id=task_id)
            if row is None:
                return self.terminate(task_id, "RESEARCH_WORKER_LEASE_LOST")
            os.link(temporary, target)
            try:
                temporary.unlink()
                fd = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                target.unlink(missing_ok=True)
                raise
            updated = self.db.execute(text("""
                UPDATE statistics_research_tasks SET status='SUCCEEDED',
                    result_digest=encode(sha256(convert_to(CAST(CAST(:result AS jsonb) AS text), 'UTF8')), 'hex'),
                    result=CAST(:result AS jsonb)
                WHERE id=:id AND deadline>clock_timestamp()
            """), {"id": task_id, "result": encode(result)})
            if not updated.rowcount:
                target.unlink(missing_ok=True)
            self.db.commit()
            return self.get(task_id)
        finally:
            temporary.unlink(missing_ok=True)


def input_digest(payload):
    return sha256(encode(payload).encode()).hexdigest()
