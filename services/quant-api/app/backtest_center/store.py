"""Durable Run metadata and atomic, immutable result publication in one local database."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from pydantic import ValidationError

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
CREATE TABLE IF NOT EXISTS bt_run_checkpoints (
    run_id TEXT PRIMARY KEY REFERENCES bt_runs(run_id),
    through TEXT NOT NULL,
    checkpoint_digest TEXT NOT NULL,
    checkpoint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bt_run_extensions (
    run_id TEXT PRIMARY KEY REFERENCES bt_runs(run_id),
    incremental TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bt_run_interruptions (
    run_id TEXT PRIMARY KEY REFERENCES bt_runs(run_id),
    evidence TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bt_templates (
    template_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    config TEXT NOT NULL
);
"""

_RUN_SELECT = """
SELECT bt_runs.*,
    EXISTS (SELECT 1 FROM bt_run_checkpoints WHERE run_id=bt_runs.run_id) AS has_checkpoint,
    (SELECT incremental FROM bt_run_extensions WHERE run_id=bt_runs.run_id) AS incremental,
    (SELECT evidence FROM bt_run_interruptions WHERE run_id=bt_runs.run_id AND bt_runs.status='FAILED') AS interruption
FROM bt_runs
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
    for name in ("config", "submission_identity", "snapshot", "summary", "incremental", "interruption"):
        data[name] = json.loads(data[name]) if data[name] is not None else None
    data["can_extend"] = (bool(data.pop("has_checkpoint")) and data["status"] == "SUCCEEDED"
                          and data["config"]["sample_type"] == "historical")
    data["qualification"] = (data["snapshot"] or {}).get("qualification", "UNVERIFIED")
    for name in ("seq", "request_key", "request_digest", "report"):
        data.pop(name)
    return data


def _read_run(db, run_id):
    return _run(db.execute(_RUN_SELECT + " WHERE run_id=?", (run_id,)).fetchone())


def _checkpoint_digest(row, checkpoint):
    return digest({"run_id": row["run_id"], "config": row["config"], "snapshot": row["snapshot"],
                   "result_digest": row["result_digest"], "checkpoint": checkpoint})


def _equity_days(result):
    days = [item["trading_day"] for item in result["equity"]]
    if (not days or any(date.fromisoformat(day).isoformat() != day for day in days)
            or days != sorted(set(days))):
        raise ValueError("invalid equity day order")
    return days


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
            row = db.execute(_RUN_SELECT + " WHERE run_id=?", (run_id,)).fetchone()
            result = _run(row)
            if result is not None and result["can_extend"]:
                result["can_extend"] = self._checkpoint(db, row) is not None
            return result

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
                _RUN_SELECT + where + " ORDER BY seq DESC LIMIT 1", values
            ).fetchone())
            success = _run(db.execute(
                _RUN_SELECT + where + " AND status='SUCCEEDED' ORDER BY seq DESC LIMIT 1", values
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
                _RUN_SELECT + where + f" ORDER BY {order} LIMIT ? OFFSET ?", (*values, limit, offset)
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
        with self.connection(write=True) as db:
            return self._queue(db, request_key, config, source_run_id)

    def _queue(self, db, request_key, config, source_run_id, *, extension_source=None):
        request = {"source_run_id": source_run_id, "config": config}
        if extension_source is not None:
            request["action"] = "extend"
        identity = digest(request)
        row = db.execute("SELECT run_id, request_digest FROM bt_runs WHERE request_key=?", (request_key,)).fetchone()
        if row is not None:
            if row["request_digest"] != identity:
                raise BacktestError("BACKTEST_REQUEST_KEY_CONFLICT")
            return _read_run(db, row["run_id"])
        incremental = None
        if extension_source is not None:
            checkpoint = self._checkpoint(db, extension_source)
            if checkpoint is None:
                raise BacktestError("BACKTEST_EXTENSION_SOURCE_UNAVAILABLE")
            incremental = {"source_run_id": source_run_id, "through": checkpoint["through"]}
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
        if incremental is not None:
            db.execute("INSERT INTO bt_run_extensions VALUES (?,?)", (row["run_id"], encode(incremental)))
        _record_event(db, row)
        return _read_run(db, row["run_id"])

    def extend(self, run_id: str, end: date, request_key: str) -> dict:
        with self.connection(write=True) as db:
            source = db.execute("SELECT * FROM bt_runs WHERE run_id=?", (run_id,)).fetchone()
            if source is None:
                raise BacktestError("BACKTEST_RUN_NOT_FOUND")
            config = json.loads(source["config"])
            if end <= date.fromisoformat(config["end"]):
                raise BacktestError("BACKTEST_EXTENSION_WINDOW_INVALID")
            try:
                effective = RunConfig.model_validate({**config, "end": end}).model_dump(mode="json")
            except ValidationError:
                raise BacktestError("BACKTEST_EXTENSION_WINDOW_INVALID") from None
            return self._queue(db, request_key, effective, run_id, extension_source=source)

    def rerun(self, run_id: str, request_key: str) -> dict:
        run = self.get(run_id)
        if run is None:
            raise BacktestError("BACKTEST_RUN_NOT_FOUND")
        if run["status"] not in ("SUCCEEDED", "FAILED", "CANCELED"):
            raise BacktestError("BACKTEST_RERUN_REQUIRES_TERMINAL")
        if run["incremental"] is not None:
            raise BacktestError("BACKTEST_INCREMENTAL_RERUN_UNAVAILABLE")
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
            return _read_run(db, run_id)

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
            return _read_run(db, row["run_id"]) if row is not None else None

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

    def finish_stopped(self, run_id: str, diagnostic: str, *, interruption: dict | None = None) -> None:
        with self.connection(write=True) as db:
            row = db.execute("""
                UPDATE bt_runs SET status=CASE status WHEN 'CANCELING' THEN 'CANCELED' ELSE 'FAILED' END,
                    phase='ENGINE_STOPPED', diagnostic=?, updated_at=?
                WHERE run_id=? AND status IN ('RUNNING','CANCELING') RETURNING *
                """, (diagnostic, _now(), run_id)).fetchone()
            if row is None:
                return
            if (
                row["status"] == "FAILED" and diagnostic == "ROLLOVER_INTERRUPTED"
                and interruption is not None and interruption.get("status") == diagnostic
                and isinstance(contract := interruption.get("contract"), str) and contract
                and row["snapshot"] is not None and json.loads(row["snapshot"]).get("physical_contract") == contract
            ):
                db.execute("INSERT INTO bt_run_interruptions (run_id, evidence) VALUES (?,?)",
                           (run_id, encode(interruption)))
            _record_event(db, row)

    def _checkpoint(self, db, source) -> dict | None:
        if source["status"] != "SUCCEEDED" or json.loads(source["config"])["sample_type"] != "historical":
            return None
        row = db.execute("SELECT * FROM bt_run_checkpoints WHERE run_id=?", (source["run_id"],)).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["checkpoint"])
            if (isinstance(payload, dict) and payload.get("through") == row["through"]
                    and _checkpoint_digest(source, payload) == row["checkpoint_digest"]):
                return payload
        except (TypeError, ValueError):
            return None
        return None

    def extension_source(self, run_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM bt_runs WHERE run_id=?", (run_id,)).fetchone()
            checkpoint = self._checkpoint(db, row) if row is not None else None
            if checkpoint is None:
                return None
            try:
                result = self._artifact(db, row)
                if digest(result) != row["result_digest"] or checkpoint["through"] != _equity_days(result)[-1]:
                    return None
            except (KeyError, TypeError, ValueError):
                return None
            return {"run": _read_run(db, run_id), "checkpoint": checkpoint, "result": result}

    def _record_incremental_result(self, db, row, result):
        scope_row = db.execute("SELECT incremental FROM bt_run_extensions WHERE run_id=?", (row["run_id"],)).fetchone()
        if scope_row is None:
            return
        scope = json.loads(scope_row["incremental"])
        reported = result["report"].get("incremental")
        try:
            days = _equity_days(result)
            through = scope["through"]
            appended = [day for day in days if day > through]
            prefix = self._rows(db, scope["source_run_id"], "equity")
            if (not isinstance(reported, dict) or through not in days or not appended or not prefix
                    or result["equity"][:len(prefix)] != prefix
                    or not all(reported.get(key) == value for key, value in scope.items())
                    or reported.get("appended_trading_days") != appended
                    or type(reported.get("executed_minutes")) is not int or reported["executed_minutes"] <= 0):
                raise ValueError("invalid extension scope")
        except (KeyError, TypeError, ValueError):
            raise BacktestError("BACKTEST_EXTENSION_RESULT_INVALID") from None
        scope.update(appended_trading_days=appended, executed_minutes=reported["executed_minutes"])
        db.execute("UPDATE bt_run_extensions SET incremental=? WHERE run_id=?", (encode(scope), row["run_id"]))

    def publish(self, run_id: str, result: dict, *, checkpoint: dict | None = None) -> bool:
        result_digest = digest(result)
        summary, report = encode(result["summary"]), encode(result["report"])
        with self.connection(write=True) as db:
            row = db.execute("""
                UPDATE bt_runs SET status='SUCCEEDED',phase='PUBLISHED',updated_at=?,result_digest=?,summary=?,report=?
                WHERE run_id=? AND status='RUNNING' AND snapshot IS NOT NULL RETURNING *
                """, (_now(), result_digest, summary, report, run_id)).fetchone()
            if row is None:
                return False
            self._record_incremental_result(db, row, result)
            if checkpoint is not None:
                try:
                    config = json.loads(row["config"])
                    through = _equity_days(result)[-1]
                    if (config["sample_type"] != "historical" or not isinstance(checkpoint, dict)
                            or checkpoint.get("through") != through):
                        raise ValueError("invalid checkpoint scope")
                    checkpoint_data = encode(checkpoint)
                    checkpoint_digest = _checkpoint_digest(row, checkpoint)
                except (KeyError, TypeError, ValueError):
                    raise BacktestError("BACKTEST_EXTENSION_CHECKPOINT_INVALID") from None
                db.execute("INSERT INTO bt_run_checkpoints VALUES (?,?,?,?)",
                           (run_id, through, checkpoint_digest, checkpoint_data))
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

    def _artifact(self, db, row):
        return {"summary": json.loads(row["summary"]), "report": json.loads(row["report"]),
                **{kind: self._rows(db, row["run_id"], kind) for kind in _RESULT_FIELDS}}

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
            artifact = self._artifact(db, row)
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


@contextmanager
def _read_publication(path: Path):
    db = sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        db.execute("PRAGMA query_only=ON")
        yield db
    finally:
        db.close()


def read_published_runs(path: Path, day: date, contract: str) -> list[tuple[str, str]]:
    """List successful publications for one physical contract and trading day."""
    with _read_publication(path) as db:
        return db.execute("""
            SELECT run_id, json_extract(config, '$.strategy_id')
            FROM bt_runs WHERE status='SUCCEEDED'
                AND upper(json_extract(config, '$.contract'))=?
                AND json_extract(config, '$.start')<=? AND json_extract(config, '$.end')>=?
            ORDER BY seq DESC LIMIT 100
        """, (contract, day.isoformat(), day.isoformat())).fetchall()


def read_published_trades(path: Path, run_id: str, day: date, trade_id: str | None) -> list[dict]:
    """Read completed native result rows without opening a writer or starting a worker."""
    with _read_publication(path) as db:
        rows = db.execute("""
            SELECT trades.payload
            FROM bt_runs runs
            JOIN bt_rows trades ON trades.run_id=runs.run_id AND trades.kind='trades'
            JOIN json_each(runs.report, '$.native_fills') fills
                ON json_extract(fills.value, '$.native_trade_id')=trades.identity
            WHERE runs.run_id=? AND runs.status='SUCCEEDED'
                AND json_extract(fills.value, '$.trading_day')=?
                AND (? IS NULL OR trades.identity=?)
            ORDER BY trades.seq LIMIT 201
        """, (run_id, day.isoformat(), trade_id, trade_id)).fetchall()
        return [json.loads(row[0]) for row in rows]
