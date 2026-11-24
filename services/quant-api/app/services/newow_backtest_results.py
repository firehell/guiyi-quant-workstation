"""Isolated PostgreSQL storage for checked Newow historical results."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

from sqlalchemy import Date, DateTime, Numeric, column, create_engine, func, insert, select, table, text, update
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.db.url import normalize_database_url


FORMAL_PROFILE = "trend_5m_rqalpha_v1"
TRIAL_PROFILE = "trend_5m_rqalpha_trial_v1"
_DATABASES = {"guiyi_newow_backtest", "guiyi_newow_backtest_test"}
_DIGEST = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_MONEY = Numeric(28, 8)
_QUANTUM = Decimal("0.00000001")
_JOB_SLOT = "newow_backtest_job_slot"
_EQUITY_FIELDS = ("equity", "cash", "margin", "fees", "unrealized_pnl", "drawdown")
_TRADE_FIELDS = ("physical_contract", "side", "position_effect", "quantity")
_TRADE_AMOUNTS = ("price", "fee", "commission", "tax", "gross_pnl", "net_pnl")

_SERIES = table(
    "newow_backtest_series",
    *(column(name) for name in (
        "id", "product", "strategy", "frequency", "research_profile_id",
        "generation", "published_run_id", "last_attempt_id",
    )),
)
_SERIES_PUBLICATIONS = table(
    "newow_backtest_series", column("id"), column("source_publication_at", DateTime(timezone=True)),
    column("source_publication_sha256"),
)
_RUNS = table(
    "newow_backtest_runs",
    *(column(name) for name in (
        "run_id", "series_id", "generation", "eligible", "status", "error_code",
        "result_digest", "started_at", "finished_at",
    )),
    column("as_of_trading_day", Date),
    column("manifest", JSONB),
    column("summary", JSONB),
)
_TRADES = table(
    "newow_backtest_trades",
    column("run_id"), column("seq"),
    *(column(name) for name in _TRADE_FIELDS),
    *(column(name, _MONEY) for name in _TRADE_AMOUNTS),
    column("detail", JSONB),
)
_EQUITY = table(
    "newow_backtest_equity",
    column("run_id"), column("seq"), column("trading_day", Date),
    *(column(name, _MONEY) for name in _EQUITY_FIELDS),
    column("detail", JSONB),
)


class ResultStoreError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SeriesKey:
    product: str
    strategy: str
    frequency: str
    research_profile_id: str

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[a-z]{1,12}", self.product)
            or self.strategy not in {"trend", "oscillation", "dual_fusion"}
            or self.frequency not in {"5m", "15m", "30m", "60m", "1d", "1w"}
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", self.research_profile_id)
        ):
            raise ResultStoreError("BACKTEST_SERIES_INVALID")

    @property
    def is_trial(self) -> bool:
        return self.research_profile_id == f"{self.strategy}_{self.frequency}_rqalpha_trial_v1"


@dataclass(frozen=True, slots=True)
class Admission:
    run_id: str
    generation: int
    should_run: bool
    status: str = "RUNNING"


def _json_default(value: object) -> str:
    if isinstance(value, Decimal) and value.is_finite():
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("BACKTEST_VALUE_INVALID")


def _json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
            default=_json_default,
        )
    except (TypeError, ValueError, OverflowError):
        raise ResultStoreError("BACKTEST_VALUE_INVALID") from None


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _job_lock_keys(key: SeriesKey) -> tuple[int, int]:
    digest = bytes.fromhex(_digest({"domain": _JOB_SLOT, "series": asdict(key)}))
    return int.from_bytes(digest[:4], signed=True), int.from_bytes(digest[4:8], signed=True)


def _date(value: object) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        except ValueError:
            pass
    raise ResultStoreError("BACKTEST_TRADING_DAY_INVALID")


def _amount(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ResultStoreError("BACKTEST_AMOUNT_INVALID")
    try:
        amount = Decimal(value)
        normalized = amount.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, ValueError):
        raise ResultStoreError("BACKTEST_AMOUNT_INVALID") from None
    if not normalized.is_finite() or amount != normalized or abs(normalized) >= Decimal("1e20"):
        raise ResultStoreError("BACKTEST_AMOUNT_INVALID")
    return normalized if normalized else Decimal("0.00000000")


def _child_row(
    payload: Mapping[str, object], run_id: str, seq: int, *, equity: bool,
) -> dict:
    detail = dict(payload)
    if "run_id" in detail or detail.pop("seq", seq) != seq:
        raise ResultStoreError("BACKTEST_SEQUENCE_INVALID")
    fields: dict[str, object] = {}
    if equity:
        fields["trading_day"] = _date(detail.pop("trading_day", None))
        fields.update((key, _amount(detail.pop(key, None))) for key in _EQUITY_FIELDS)
    else:
        fields.update((key, detail.pop(key, None)) for key in _TRADE_FIELDS)
        for key in _TRADE_AMOUNTS:
            value = detail.pop(key, None)
            fields[key] = _amount(value) if value is not None or key in {"price", "fee"} else None
        contract = fields["physical_contract"]
        if (
            not isinstance(contract, str) or not re.fullmatch(r"[A-Z]{1,12}[0-9]{3,4}", contract)
            or type(fields["quantity"]) is not int or not 1 <= fields["quantity"] <= 2**31 - 1
        ):
            raise ResultStoreError("BACKTEST_TRADE_INVALID")
    return {"run_id": run_id, "seq": seq, **fields, "detail": json.loads(_json(detail))}


def _encode_cursor(run_id: str, kind: str, seq: int) -> str:
    return base64.urlsafe_b64encode(f"1:{kind}:{run_id}:{seq}".encode()).decode().rstrip("=")


def _decode_cursor(value: str | None, run_id: str, kind: str) -> int:
    if value is None:
        return -1
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,140}", value):
        raise ResultStoreError("BACKTEST_CURSOR_INVALID")
    try:
        version, resource, run, seq_text = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True,
        ).decode().split(":")
        seq = int(seq_text)
        if (
            (version, resource, run) != ("1", kind, run_id)
            or not 0 <= seq <= 2**31 - 1
            or value != _encode_cursor(run_id, kind, seq)
        ):
            raise ValueError
        return seq
    except ValueError:
        raise ResultStoreError("BACKTEST_CURSOR_INVALID") from None


def _attempt(row: Mapping[str, object] | None) -> dict | None:
    if row is None:
        return None
    return {
        key: _json_default(row[key]) if isinstance(row[key], date) else row[key]
        for key in ("run_id", "generation", "status", "error_code", "as_of_trading_day",
                    "started_at", "finished_at")
    }


class ResultStore:
    """Use an explicit local research database, independent of the application DSN."""

    def __init__(self, dsn: str, *, read_only: bool = False) -> None:
        try:
            url = make_url(normalize_database_url(dsn))
            if (
                url.drivername != "postgresql+psycopg" or url.query
                or url.host not in {"127.0.0.1", "::1", "localhost"}
                or not url.port or url.port == 5432 or not url.username
                or url.database not in _DATABASES
            ):
                raise ArgumentError
            self._engine = create_engine(
                url, poolclass=NullPool, hide_parameters=True,
                connect_args={
                    "hostaddr": "::1" if url.host == "::1" else "127.0.0.1",
                    "connect_timeout": 3,
                    "options": "-c statement_timeout=10000",
                },
            )
        except (ArgumentError, ValueError, TypeError):
            raise ResultStoreError("BACKTEST_DATABASE_UNAVAILABLE") from None
        self._database = url.database
        self._read_only = read_only

    def close(self) -> None:
        self._engine.dispose()

    def _verify_database(self, conn: Connection) -> None:
        if conn.execute(select(func.current_database())).scalar_one() != self._database:
            raise ResultStoreError("BACKTEST_DATABASE_UNAVAILABLE")

    def _write_access(self) -> None:
        if self._read_only:
            raise ResultStoreError("BACKTEST_RESULT_READ_ONLY")

    @contextmanager
    def job_slot(self, key: SeriesKey, *, wait_seconds: int = 0) -> Iterator[Connection]:
        """Keep one database session per series, optionally waiting for an active runner."""
        self._write_access()
        try:
            connection = self._engine.connect()
        except SQLAlchemyError:
            raise ResultStoreError("BACKTEST_DATABASE_UNAVAILABLE") from None
        with connection:
            try:
                with connection.begin():
                    self._verify_database(connection)
                    if wait_seconds:
                        connection.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                                           {"timeout": str(wait_seconds * 1000)})
                        connection.execute(select(func.pg_advisory_lock(*_job_lock_keys(key))))
                    elif not connection.scalar(select(func.pg_try_advisory_lock(*_job_lock_keys(key)))):
                        raise ResultStoreError("BACKTEST_JOB_BUSY")
                connection.info[_JOB_SLOT] = key
            except SQLAlchemyError as exc:
                code = "BACKTEST_JOB_BUSY" if getattr(getattr(exc, "orig", None), "sqlstate", None) == "57014" else "BACKTEST_DATABASE_UNAVAILABLE"
                raise ResultStoreError(code) from None
            # NullPool closes the database session on exit and releases its lock.
            yield connection

    def _verify_job_slot(self, connection: Connection, key: SeriesKey) -> None:
        if connection.closed or connection.invalidated or connection.engine is not self._engine:
            raise ResultStoreError("BACKTEST_JOB_SLOT_LOST")
        if connection.info.get(_JOB_SLOT) != key:
            raise ResultStoreError("BACKTEST_JOB_SLOT_LOST")
        major, minor = _job_lock_keys(key)
        try:
            held = connection.scalar(text("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_locks
                    WHERE locktype = 'advisory' AND pid = pg_backend_pid()
                      AND mode = 'ExclusiveLock' AND granted AND objsubid = 2
                      AND classid::bigint = :major AND objid::bigint = :minor
                )
            """), {"major": major % (1 << 32), "minor": minor % (1 << 32)})
        except SQLAlchemyError:
            raise ResultStoreError("BACKTEST_JOB_SLOT_LOST") from None
        if not held:
            raise ResultStoreError("BACKTEST_JOB_SLOT_LOST")

    @staticmethod
    def _result_counts(conn: Connection, run_id: str) -> tuple[int, int]:
        trade_count = conn.scalar(select(func.count()).select_from(_TRADES).where(_TRADES.c.run_id == run_id))
        equity_count = conn.scalar(select(func.count()).select_from(_EQUITY).where(_EQUITY.c.run_id == run_id))
        return trade_count, equity_count

    def observe_source_publication(
        self, key: SeriesKey, at: datetime, digest: str, connection: Connection,
    ) -> bool:
        """Fence delayed receipts without including delivery identity in the run hash."""
        self._write_access()
        if at.utcoffset() is None or _DIGEST.fullmatch(digest) is None:
            raise ResultStoreError("BACKTEST_SOURCE_PUBLICATION_INVALID")
        identity = asdict(key)
        where = [getattr(_SERIES.c, name) == value for name, value in identity.items()]
        try:
            with connection.begin():
                self._verify_job_slot(connection, key)
                connection.execute(pg_insert(_SERIES).values(**identity).on_conflict_do_nothing())
                series_id = connection.execute(select(_SERIES.c.id).where(*where).with_for_update()).scalar_one()
                target = _SERIES_PUBLICATIONS.c
                previous_at, previous_digest = connection.execute(select(
                    target.source_publication_at, target.source_publication_sha256,
                ).where(target.id == series_id)).one()
                if previous_at is not None and previous_at > at:
                    return False
                if previous_at == at and previous_digest != digest:
                    raise ResultStoreError("BACKTEST_SOURCE_PUBLICATION_CONFLICT")
                if previous_at != at:
                    connection.execute(update(_SERIES_PUBLICATIONS).where(target.id == series_id).values(
                        source_publication_at=at, source_publication_sha256=digest,
                    ))
                return True
        except SQLAlchemyError:
            raise ResultStoreError("BACKTEST_SOURCE_PUBLICATION_WRITE_FAILED") from None

    def admit(
        self, key: SeriesKey, manifest: Mapping[str, object], *, eligible: bool,
        job_connection: Connection | None = None, retry_failed: bool = True,
    ) -> Admission:
        self._write_access()
        if type(eligible) is not bool or (eligible and key.is_trial):
            raise ResultStoreError("BACKTEST_QUALIFICATION_INVALID")
        day = _date(manifest.get("as_of_trading_day"))
        frozen = json.loads(_json(dict(manifest) | {"as_of_trading_day": day.isoformat()}))
        identity = asdict(key)
        run_id = _digest({"series": identity, "manifest": frozen, "eligible": eligible})
        where = [getattr(_SERIES.c, name) == value for name, value in identity.items()]
        try:
            existing_connection = nullcontext(job_connection) if job_connection is not None else self._engine.connect()
            with existing_connection as conn, conn.begin():
                if job_connection is not None:
                    self._verify_job_slot(conn, key)
                self._verify_database(conn)
                conn.execute(pg_insert(_SERIES).values(**identity).on_conflict_do_nothing())
                series = conn.execute(select(_SERIES).where(*where).with_for_update()).mappings().one()
                existing = conn.execute(select(_RUNS).where(_RUNS.c.run_id == run_id)).mappings().one_or_none()
                if existing and existing["status"] == "SUCCEEDED":
                    return Admission(run_id, existing["generation"], False, "SUCCEEDED")
                if existing and existing["status"] == "FAILED" and not retry_failed:
                    return Admission(run_id, existing["generation"], False, "FAILED")
                if existing and existing["status"] == "RUNNING":
                    if job_connection is None:
                        return Admission(run_id, existing["generation"], False)
                    if series["published_run_id"] == run_id or self._result_counts(conn, run_id) != (0, 0):
                        raise ResultStoreError("BACKTEST_COMMIT_OUTCOME_UNKNOWN")
                generation = series["generation"] + 1
                values = {
                    "series_id": series["id"], "generation": generation, "manifest": frozen,
                    "eligible": eligible, "as_of_trading_day": day, "status": "RUNNING",
                    "started_at": func.now(), "finished_at": None, "error_code": None,
                }
                if existing:
                    conn.execute(update(_RUNS).where(_RUNS.c.run_id == run_id).values(**values))
                else:
                    conn.execute(insert(_RUNS).values(run_id=run_id, **values))
                conn.execute(update(_SERIES).where(_SERIES.c.id == series["id"]).values(
                    generation=generation, last_attempt_id=run_id,
                ))
                return Admission(run_id, generation, True)
        except SQLAlchemyError:
            raise ResultStoreError("BACKTEST_ADMIT_FAILED") from None

    def _locked(self, conn: Connection, admission: Admission) -> tuple[Mapping, Mapping]:
        run_series = select(_RUNS.c.series_id).where(_RUNS.c.run_id == admission.run_id).scalar_subquery()
        series = conn.execute(
            select(_SERIES).where(_SERIES.c.id == run_series).with_for_update()
        ).mappings().one_or_none()
        if series is None:
            raise ResultStoreError("BACKTEST_RUN_NOT_FOUND")
        run = conn.execute(select(_RUNS).where(_RUNS.c.run_id == admission.run_id)).mappings().one()
        if admission.generation != run["generation"]:
            raise ResultStoreError("BACKTEST_STALE_ATTEMPT")
        return series, run

    def fail(self, admission: Admission, code: str) -> None:
        self._write_access()
        if not _CODE.fullmatch(code):
            raise ResultStoreError("BACKTEST_ERROR_CODE_INVALID")
        try:
            with self._engine.begin() as conn:
                self._verify_database(conn)
                _, run = self._locked(conn, admission)
                if run["status"] == "FAILED" and run["error_code"] == code:
                    return
                if run["status"] != "RUNNING" or not admission.should_run:
                    raise ResultStoreError("BACKTEST_RUN_NOT_ACTIVE")
                conn.execute(update(_RUNS).where(_RUNS.c.run_id == admission.run_id).values(
                    status="FAILED", error_code=code, finished_at=func.now(),
                ))
        except SQLAlchemyError:
            raise ResultStoreError("BACKTEST_FAILURE_WRITE_FAILED") from None

    def publish(
        self, admission: Admission, summary: Mapping[str, object],
        trades: Sequence[Mapping[str, object]], equity: Sequence[Mapping[str, object]],
    ) -> None:
        self._write_access()
        run_id = admission.run_id
        trade_rows = [_child_row(row, run_id, seq, equity=False) for seq, row in enumerate(trades, 1)]
        equity_rows = [_child_row(row, run_id, seq, equity=True) for seq, row in enumerate(equity)]
        if not equity_rows or any(
            previous["trading_day"] > current["trading_day"]
            for previous, current in zip(equity_rows, equity_rows[1:])
        ):
            raise ResultStoreError("BACKTEST_EQUITY_INVALID")
        normalized_summary = json.loads(_json(dict(summary)))
        digest = _digest({"summary": normalized_summary, "trades": trade_rows, "equity": equity_rows})
        committing = False
        try:
            with self._engine.connect() as conn, conn.begin() as tx:
                self._verify_database(conn)
                series, run = self._locked(conn, admission)
                if run["status"] == "SUCCEEDED":
                    if run["result_digest"] != digest:
                        raise ResultStoreError("BACKTEST_RESULT_CONFLICT")
                    return
                if run["status"] != "RUNNING" or not admission.should_run:
                    raise ResultStoreError("BACKTEST_RUN_NOT_ACTIVE")
                if not run["eligible"] and not SeriesKey(
                    series["product"], series["strategy"], series["frequency"], series["research_profile_id"],
                ).is_trial:
                    raise ResultStoreError("BACKTEST_FORMAL_INELIGIBLE")
                if equity_rows[-1]["trading_day"] != run["as_of_trading_day"]:
                    raise ResultStoreError("BACKTEST_EQUITY_INVALID")
                if trade_rows:
                    conn.execute(insert(_TRADES), trade_rows)
                conn.execute(insert(_EQUITY), equity_rows)
                conn.execute(update(_RUNS).where(_RUNS.c.run_id == run_id).values(
                    status="SUCCEEDED", summary=normalized_summary, result_digest=digest, finished_at=func.now(),
                ))
                published = conn.execute(
                    select(_RUNS.c.generation, _RUNS.c.as_of_trading_day)
                    .where(_RUNS.c.run_id == series["published_run_id"])
                ).one_or_none()
                if published is None or (
                    admission.generation > published.generation and run["as_of_trading_day"] >= published.as_of_trading_day
                ):
                    conn.execute(update(_SERIES).where(_SERIES.c.id == series["id"]).values(published_run_id=run_id))
                committing = True
                tx.commit()
        except SQLAlchemyError:
            if committing:
                self._readback_publication(admission, digest, len(trade_rows), len(equity_rows))
                return
            raise ResultStoreError("BACKTEST_RESULT_WRITE_FAILED") from None

    def _readback_publication(self, admission: Admission, digest: str, trades: int, equity: int) -> None:
        """Resolve a lost commit acknowledgement from an independent read-only snapshot."""
        run_id = admission.run_id
        try:
            with self._reader() as conn:
                self._verify_database(conn)
                row = conn.execute(select(
                    _RUNS.c.status, _RUNS.c.generation, _RUNS.c.result_digest,
                    _RUNS.c.as_of_trading_day, _SERIES.c.published_run_id,
                ).join(_SERIES, _RUNS.c.series_id == _SERIES.c.id).where(_RUNS.c.run_id == run_id)).one()
                counts = self._result_counts(conn, run_id)
                if row.generation == admission.generation:
                    if row.status == "RUNNING" and counts == (0, 0) and row.published_run_id != run_id:
                        raise ResultStoreError("BACKTEST_RESULT_WRITE_FAILED")
                    if row.status == "SUCCEEDED" and row.result_digest == digest and counts == (trades, equity):
                        pointer = self._get_run(conn, row.published_run_id)
                        if pointer and pointer["status"] == "SUCCEEDED" and (
                            row.published_run_id == run_id or pointer["generation"] > row.generation
                            or pointer["as_of_trading_day"] > row.as_of_trading_day
                        ):
                            return
        except SQLAlchemyError:
            pass
        raise ResultStoreError("BACKTEST_COMMIT_OUTCOME_UNKNOWN")

    def _reader(self) -> Connection:
        return self._engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True,
        )

    @staticmethod
    def _get_run(conn: Connection, run_id: str | None) -> Mapping | None:
        if run_id is None:
            return None
        return conn.execute(select(_RUNS).where(_RUNS.c.run_id == run_id)).mappings().one_or_none()

    def latest(self, key: SeriesKey) -> dict:
        where = [getattr(_SERIES.c, name) == value for name, value in asdict(key).items()]
        try:
            with self._reader() as conn:
                self._verify_database(conn)
                series = conn.execute(select(_SERIES).where(*where)).mappings().one_or_none()
                if series is None:
                    return {"result": None, "last_attempt": None}
                published = self._get_run(conn, series["published_run_id"])
                result = None
                if published is not None:
                    if published["status"] != "SUCCEEDED":
                        raise ResultStoreError("BACKTEST_DATABASE_UNAVAILABLE")
                    result = {
                        "run_id": published["run_id"],
                        "as_of_trading_day": published["as_of_trading_day"].isoformat(),
                        "qualification": "QUALIFIED" if published["eligible"] else "TRIAL",
                        "manifest": published["manifest"],
                        "summary": published["summary"],
                    }
                return {"result": result, "last_attempt": _attempt(self._get_run(conn, series["last_attempt_id"]))}
        except SQLAlchemyError:
            raise ResultStoreError("BACKTEST_DATABASE_UNAVAILABLE") from None

    def page(self, run_id: str, kind: str, limit: int = 50, cursor: str | None = None) -> dict:
        if not _DIGEST.fullmatch(run_id):
            raise ResultStoreError("BACKTEST_RUN_NOT_FOUND")
        if kind not in {"trades", "equity"} or not 1 <= limit <= 200:
            raise ResultStoreError("BACKTEST_PAGE_INVALID")
        seq = _decode_cursor(cursor, run_id, kind)
        child = _TRADES if kind == "trades" else _EQUITY
        try:
            with self._reader() as conn:
                self._verify_database(conn)
                run = self._get_run(conn, run_id)
                if run is None or run["status"] != "SUCCEEDED":
                    raise ResultStoreError("BACKTEST_RUN_NOT_FOUND")
                rows = conn.execute(select(child).where(
                    child.c.run_id == run_id, child.c.seq > seq,
                ).order_by(child.c.seq).limit(limit + 1)).mappings().all()
        except SQLAlchemyError:
            raise ResultStoreError("BACKTEST_DATABASE_UNAVAILABLE") from None
        items = [
            json.loads(_json(row["detail"] | {
                name: value for name, value in row.items() if name not in {"run_id", "detail"}
            }))
            for row in rows[:limit]
        ]
        next_cursor = _encode_cursor(run_id, kind, rows[limit - 1]["seq"]) if len(rows) > limit else None
        return {"run_id": run_id, "items": items, "next_cursor": next_cursor}
