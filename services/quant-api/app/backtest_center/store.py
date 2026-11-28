"""Durable Run metadata and atomic, immutable result publication in one local database."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .codec import digest, encode
from .contracts import BacktestError, RunConfig
from .replay import chart_window, fill_roles, scoped_chart


_SCHEMA = """
CREATE TABLE IF NOT EXISTS bt_runs (
    seq INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    request_key TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL,
    source_run_id TEXT REFERENCES bt_runs(run_id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    diagnostic TEXT,
    config TEXT NOT NULL,
    submission_identity TEXT,
    snapshot TEXT,
    result_digest TEXT,
    summary TEXT,
    report TEXT
);
CREATE INDEX IF NOT EXISTS bt_runs_status ON bt_runs(status, seq);
CREATE TABLE IF NOT EXISTS bt_rows (
    run_id TEXT NOT NULL REFERENCES bt_runs(run_id),
    kind TEXT NOT NULL,
    seq INTEGER NOT NULL,
    identity TEXT,
    payload TEXT NOT NULL,
    PRIMARY KEY(run_id, kind, seq),
    UNIQUE(run_id, kind, identity)
);
CREATE TABLE IF NOT EXISTS bt_events (
    seq INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES bt_runs(run_id),
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL,
    diagnostic TEXT
);
CREATE INDEX IF NOT EXISTS bt_events_run ON bt_events(run_id, seq);
CREATE TABLE IF NOT EXISTS bt_templates (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    config TEXT NOT NULL
);
"""

QUEUE_LIMIT = 64
STATUSES = ("QUEUED", "RUNNING", "CANCELING", "SUCCEEDED", "FAILED", "CANCELED")
_RESULT_FIELDS = ("trades", "equity", "bars", "markers")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run(row):
    if row is None:
        return None
    data = dict(row)
    for name in ("config", "submission_identity", "snapshot", "summary"):
        data[name] = json.loads(data[name]) if data[name] is not None else None
    data["qualification"] = (data["snapshot"] or {}).get("qualification", "UNVERIFIED")
    for name in ("seq", "request_key", "request_digest", "report"):
        data.pop(name)
    return data


def _record_event(db, row) -> None:
    db.execute(
        "INSERT INTO bt_events (run_id, at, status, phase, diagnostic) VALUES (?,?,?,?,?)",
        tuple(row[key] for key in ("run_id", "updated_at", "status", "phase", "diagnostic")),
    )


def _template(row):
    return {**dict(row), "config": json.loads(row["config"])}


def _compare_decimal(left: str, right: str) -> int:
    left_amount, right_amount = Decimal(left), Decimal(right)
    return (left_amount > right_amount) - (left_amount < right_amount)


class RunStore:
    def __init__(self, path: Path, submission_identity=None):
        self.submission_identity = submission_identity
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)
        finally:
            db.close()

    @contextmanager
    def connection(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.create_collation("DECIMAL", _compare_decimal)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, run_id: str) -> dict | None:
        with self.connection() as db:
            return _run(db.execute("SELECT * FROM bt_runs WHERE run_id=?", (run_id,)).fetchone())

    def list(self, *, offset: int, limit: int, **filters) -> dict:
        columns = {
            "strategy_id": ("json_extract(config,'$.strategy_id')", "="),
            "product": ("json_extract(config,'$.product')", "="),
            "signal_frequency": ("json_extract(config,'$.signal_frequency')", "="),
            "start": ("json_extract(config,'$.end')", ">="),
            "end": ("json_extract(config,'$.start')", "<="),
        }
        clauses, values = [], []
        for name, (column, operator) in columns.items():
            if (value := filters.get(name)) is not None:
                clauses.append(f"{column}{operator}?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else " WHERE 1"
        with self.connection() as db:
            counts = dict.fromkeys(STATUSES, 0)
            counts.update({row[0]: row[1] for row in db.execute(
                "SELECT status, COUNT(*) FROM bt_runs" + where + " GROUP BY status", values
            )})
            latest = _run(db.execute(
                "SELECT * FROM bt_runs" + where + " ORDER BY seq DESC LIMIT 1", values
            ).fetchone())
            success = _run(db.execute(
                "SELECT * FROM bt_runs" + where + " AND status='SUCCEEDED' ORDER BY seq DESC LIMIT 1", values
            ).fetchone())
            status = filters.get("status")
            if status:
                where += " AND status=?"
                values.append(status)
            total = counts[status] if status else sum(counts.values())
            order = "seq DESC"
            if filters.get("sort") == "net_return":
                returns = "CAST(json_extract(summary,'$.metrics.net_return.value') AS TEXT) COLLATE DECIMAL"
                where += (f" AND status='SUCCEEDED' AND {returns} > '0'"
                          " AND CAST(json_extract(summary,'$.metrics.trade_count.value') AS INTEGER) > 0")
                order = f"{returns} DESC, seq DESC"
                total = db.execute("SELECT COUNT(*) FROM bt_runs" + where, values).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM bt_runs" + where + f" ORDER BY {order} LIMIT ? OFFSET ?", (*values, limit, offset)
            )
            return {"items": [_run(row) for row in rows], "total": total,
                    "counts": counts, "latest_attempt": latest, "latest_success": success}

    def templates(self) -> list[dict]:
        with self.connection() as db:
            return [_template(row) for row in db.execute("SELECT * FROM bt_templates ORDER BY updated_at DESC")]

    def save_template(self, template_id: str, name: str, config: RunConfig) -> dict:
        now = _now()
        with self.connection(write=True) as db:
            row = db.execute("""
                INSERT INTO bt_templates VALUES (?,?,?,?,?)
                ON CONFLICT(template_id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at,
                config=excluded.config RETURNING *
                """, (template_id, name, now, now, encode(config.model_dump(mode="json")))).fetchone()
            return _template(row)

    def submit(self, request_key: str, config: dict, *, source_run_id=None) -> dict:
        model = RunConfig.model_validate(config)
        return self._submit(request_key, model.model_dump(mode="json"), source_run_id)

    def _submit(self, request_key, config, source_run_id):
        identity = digest({"source_run_id": source_run_id, "config": config})
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM bt_runs WHERE request_key=?", (request_key,)).fetchone()
            if row is not None:
                if row["request_digest"] != identity:
                    raise BacktestError("BACKTEST_REQUEST_KEY_CONFLICT")
                return _run(row)
            active = db.execute(
                "SELECT COUNT(*) FROM bt_runs WHERE status IN ('QUEUED','RUNNING','CANCELING')"
            ).fetchone()[0]
            if active >= QUEUE_LIMIT:
                raise BacktestError("BACKTEST_QUEUE_FULL")
            now = _now()
            submitted = self.submission_identity(config) if self.submission_identity is not None else None
            row = db.execute("""
                INSERT INTO bt_runs (run_id,request_key,request_digest,source_run_id,created_at,updated_at,
                    status,phase,config,submission_identity) VALUES (?,?,?,?,?,?,'QUEUED','QUEUED',?,?) RETURNING *
                """, (uuid4().hex, request_key, identity, source_run_id, now, now, encode(config),
                      encode(submitted) if submitted is not None else None)).fetchone()
            _record_event(db, row)
            return _run(row)

    def rerun(self, run_id: str, request_key: str) -> dict:
        run = self.get(run_id)
        if run is None:
            raise BacktestError("BACKTEST_RUN_NOT_FOUND")
        if run["status"] not in ("SUCCEEDED", "FAILED", "CANCELED"):
            raise BacktestError("BACKTEST_RERUN_REQUIRES_TERMINAL")
        return self._submit(request_key, run["config"], run_id)

    def cancel(self, run_id: str) -> dict:
        with self.connection(write=True) as db:
            row = db.execute("""
                UPDATE bt_runs SET status=CASE status WHEN 'QUEUED' THEN 'CANCELED' ELSE 'CANCELING' END,
                    phase=CASE status WHEN 'QUEUED' THEN 'CANCELED' ELSE 'STOPPING_ENGINE' END, updated_at=?
                WHERE run_id=? AND status IN ('QUEUED','RUNNING') RETURNING *
                """, (_now(), run_id)).fetchone()
            if row is not None:
                _record_event(db, row)
            else:
                row = db.execute("SELECT * FROM bt_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise BacktestError("BACKTEST_RUN_NOT_FOUND")
            return _run(row)

    def recover(self) -> None:
        """Called under the exclusive worker lock after the previous engine has exited."""
        with self.connection(write=True) as db:
            rows = db.execute("""
                UPDATE bt_runs SET status=CASE status WHEN 'CANCELING' THEN 'CANCELED' ELSE 'FAILED' END,
                    diagnostic='BACKTEST_INTERRUPTED_BEFORE_PUBLICATION', phase='RECOVERY', updated_at=?
                WHERE status IN ('RUNNING','CANCELING') RETURNING *
                """, (_now(),)).fetchall()
            for row in rows:
                _record_event(db, row)

    def claim(self) -> dict | None:
        with self.connection(write=True) as db:
            row = db.execute("""
                UPDATE bt_runs SET status='RUNNING', phase='CHECKING_INPUT', updated_at=?
                WHERE seq=(SELECT MIN(seq) FROM bt_runs WHERE status='QUEUED') RETURNING *
                """, (_now(),)).fetchone()
            if row is not None:
                _record_event(db, row)
            return _run(row)

    def admit(self, run_id: str, snapshot: dict) -> bool:
        with self.connection(write=True) as db:
            row = db.execute("""
                UPDATE bt_runs SET snapshot=?,phase='EXECUTING_PLUS',updated_at=?
                WHERE run_id=? AND status='RUNNING' AND snapshot IS NULL RETURNING *
                """, (encode(snapshot), _now(), run_id)).fetchone()
            if row is None:
                return False
            _record_event(db, row)
            return True

    def phase(self, run_id: str, phase: str) -> None:
        with self.connection(write=True) as db:
            row = db.execute("""
                UPDATE bt_runs SET phase=?,updated_at=? WHERE run_id=? AND status='RUNNING' AND phase<>? RETURNING *
                """, (phase, _now(), run_id, phase)).fetchone()
            if row is not None:
                _record_event(db, row)

    def finish_stopped(self, run_id: str, diagnostic: str) -> None:
        with self.connection(write=True) as db:
            row = db.execute("""
                UPDATE bt_runs SET status=CASE status WHEN 'CANCELING' THEN 'CANCELED' ELSE 'FAILED' END,
                    phase='ENGINE_STOPPED', diagnostic=?, updated_at=?
                WHERE run_id=? AND status IN ('RUNNING','CANCELING') RETURNING *
                """, (diagnostic, _now(), run_id)).fetchone()
            if row is not None:
                _record_event(db, row)

    def publish(self, run_id: str, result: dict) -> bool:
        result_digest = digest(result)
        summary, report = encode(result["summary"]), encode(result["report"])
        with self.connection(write=True) as db:
            row = db.execute("""
                UPDATE bt_runs SET status='SUCCEEDED',phase='PUBLISHED',updated_at=?,result_digest=?,summary=?,report=?
                WHERE run_id=? AND status='RUNNING' AND snapshot IS NOT NULL RETURNING *
                """, (_now(), result_digest, summary, report, run_id)).fetchone()
            if row is None:
                return False
            for kind in _RESULT_FIELDS:
                db.executemany("INSERT INTO bt_rows VALUES(?,?,?,?,?)", (
                    (run_id, kind, seq, payload.get("trade_id") if kind == "trades" else None, encode(payload))
                    for seq, payload in enumerate(result.get(kind, ()))
                ))
            _record_event(db, row)
        return True

    def events(self, run_id: str) -> dict:
        with self.connection() as db:
            rows = db.execute("""
                SELECT at,status,phase,diagnostic FROM bt_events WHERE run_id=? ORDER BY seq DESC LIMIT 32
                """, (run_id,)).fetchall()
            if not rows:
                # Runs archived before the event journal still have a persisted last stage.
                current = db.execute("""
                    SELECT updated_at AS at,status,phase,diagnostic FROM bt_runs WHERE run_id=?
                    """, (run_id,)).fetchone()
                if current is None:
                    raise BacktestError("BACKTEST_RUN_NOT_FOUND")
                rows = [current]
            return {"run_id": run_id, "items": [dict(row) for row in reversed(rows)]}

    def _succeeded(self, db, run_id):
        row = db.execute("SELECT * FROM bt_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise BacktestError("BACKTEST_RUN_NOT_FOUND")
        if row["status"] != "SUCCEEDED":
            raise BacktestError("BACKTEST_RESULT_UNAVAILABLE")
        return row

    def _rows(self, db, run_id, kind, limit=-1, offset=0):
        return [json.loads(row[0]) for row in db.execute("""
            SELECT payload FROM bt_rows WHERE run_id=? AND kind=? ORDER BY seq LIMIT ? OFFSET ?
            """, (run_id, kind, limit, offset))]

    def page(self, run_id: str, kind: str, offset: int, limit: int) -> dict:
        with self.connection() as db:
            self._succeeded(db, run_id)
            total = db.execute("SELECT COUNT(*) FROM bt_rows WHERE run_id=? AND kind=?", (run_id, kind)).fetchone()[0]
            return {"run_id": run_id, "items": self._rows(db, run_id, kind, limit, offset), "total": total}

    def result(self, run_id: str) -> dict | None:
        with self.connection() as db:
            try:
                row = self._succeeded(db, run_id)
            except BacktestError:
                return None
            return {"summary": json.loads(row["summary"]), "report": json.loads(row["report"]),
                    **{kind: self._rows(db, run_id, kind) for kind in ("trades", "equity")}}

    def report(self, run_id: str) -> dict:
        with self.connection() as db:
            row = self._succeeded(db, run_id)
            return json.loads(row["report"])

    def replay(self, run_id: str, trade_id: str) -> dict:
        """Read only the publication's own chart, including when the native bundle changes later."""
        with self.connection() as db:
            row = self._succeeded(db, run_id)
            record = db.execute("""
                SELECT payload FROM bt_rows WHERE run_id=? AND kind='trades' AND identity=?
                """, (run_id, trade_id)).fetchone()
            if record is None:
                raise BacktestError("BACKTEST_TRADE_NOT_FOUND")
            trade = json.loads(record[0])
            config, snapshot = json.loads(row["config"]), json.loads(row["snapshot"])
            report = json.loads(row["report"])
            artifact = {"summary": json.loads(row["summary"]), "report": report,
                        **{kind: self._rows(db, run_id, kind) for kind in _RESULT_FIELDS}}
            intact = digest(artifact) == row["result_digest"]

        contract, frequency, revision = trade["contract"], config["signal_frequency"], snapshot["data_revision"]
        fills, attempts = [], []
        reason = "RUN_CHART_WINDOW_UNAVAILABLE"
        try:
            if not intact:
                raise ValueError("RUN_CHART_EVIDENCE_MISMATCH")
            roles = fill_roles(trade)
            fills = [fill for fill in report.get("native_fills", ()) if fill.get("native_trade_id") in roles
                     and fill.get("contract") == contract]
            signal_ids = {trade[key] for key in ("entry_signal_id", "exit_signal_id") if trade.get(key)}
            signal_ids.update(fill["signal_id"] for fill in fills if fill.get("signal_id"))
            attempts = [item for item in report.get("attempts", ()) if item.get("signal_id") in signal_ids
                        and item.get("contract", contract) == contract]
            series, events = scoped_chart(artifact["bars"], artifact["markers"], contract, config, snapshot)
            bars, markers = chart_window(series, events, trade, fills, roles, frequency)
        except (KeyError, TypeError, ValueError):
            bars, markers = [], []
            reason = "RUN_CHART_EVIDENCE_MISMATCH"

        return {"run_id": run_id, "trade": trade, "contract": contract, "frequency": frequency,
                "revision": revision, "input_sha256": snapshot.get("input_sha256"),
                "available": bool(bars), "reason": None if bars else reason, "bars": bars, "markers": markers,
                "native_fills": fills, "attempts": attempts}
