"""One-key, source-bound correction. No provider, missing-key insert, or retry."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import date
from pathlib import Path

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.market_data.bounded_metadata import _normalize_response
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession


DAY = date(2022, 3, 16)
SOURCE_SHA256 = "265a3f83176e56869f72b185d0d801d95aa9e22584d08130f49de1c141b78aad"
BEFORE = {"id": 46796, "exchange_code": "SHFE", "trade_date": "2022-03-16",
          "is_trading_day": True, "has_night_session": False, "provider": "rqdata",
          "remark": "FULL-HISTORY-RESIDUAL-REPAIR-004B metadata-trading-calendar-001"}
REQUEST = {"method": "get_trading_periods", "contract": "AU2304", "symbol": "au",
           "exchange": "SHFE", "start_date": "2022-03-16", "end_date": "2022-03-16", "frequency": "1m"}


class CorrectionError(ValueError):
    def __init__(self, reason: str):
        self.code = "AU_CALENDAR_CORRECTION_" + reason
        super().__init__(self.code)


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      default=lambda item: item.isoformat())


def _hash(value) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _sha(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CorrectionError("EVIDENCE_INVALID")
        result[key] = value
    return result


def read_evidence(path: str, expected_sha256: str) -> dict:
    """Read one owned, bounded, unchanged ordinary file; hash is not provenance."""
    if not Path(path).is_absolute() or not _sha(expected_sha256):
        raise CorrectionError("EVIDENCE_INVALID")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_nlink != 1 or not 0 < before.st_size <= 65536):
                raise CorrectionError("EVIDENCE_INVALID")
            content = source.read(65537)
            after = os.fstat(source.fileno())
        unchanged = all(getattr(before, key) == getattr(after, key) for key in
                        ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))
        if not unchanged or hashlib.sha256(content).hexdigest() != expected_sha256:
            raise CorrectionError("EVIDENCE_CHANGED")
        evidence = json.loads(content, object_pairs_hook=_unique)
        rows = evidence["source_response"]
        # Pin the already-authorized real response, not caller-asserted source labels.
        if _hash(rows) != SOURCE_SHA256:
            raise CorrectionError("SOURCE_NOT_APPROVED")
        normalized = _normalize_response(REQUEST, rows)
        if not any(row["crosses_midnight"] or row["start_time"] >= "18:00:00" for row in normalized):
            raise CorrectionError("NIGHT_EVIDENCE_MISSING")
        return {"file_sha256": expected_sha256, "source_response_sha256": SOURCE_SHA256,
                "source_response": rows, "normalized_sessions": normalized}
    except CorrectionError:
        raise
    except Exception:
        raise CorrectionError("EVIDENCE_INVALID") from None


def _row(value) -> dict:
    return json.loads(_json({column.name: getattr(value, column.name) for column in value.__table__.columns}))


def _facts(session: Session, *, corrected: bool = False) -> dict:
    if session.get_bind().get_execution_options().get("schema_translate_map"):
        raise CorrectionError("SCHEMA_TRANSLATION_UNSUPPORTED")
    calendar = session.scalar(select(TradingCalendar).where(
        TradingCalendar.id == 46796, TradingCalendar.exchange_code == "SHFE", TradingCalendar.trade_date == DAY
    ).execution_options(populate_existing=True))
    if calendar is None or _row(calendar) != {**BEFORE, "has_night_session": corrected}:
        raise CorrectionError("CALENDAR_BASELINE_DRIFT")
    exchange = session.scalar(select(Exchange).where(Exchange.code == "SHFE").execution_options(populate_existing=True))
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == "au").execution_options(populate_existing=True))
    contract = session.scalar(select(Contract).where(Contract.contract_code == "AU2304").execution_options(populate_existing=True))
    if (exchange is None or not exchange.is_active or exchange.timezone != "Asia/Shanghai"
            or instrument is None or not instrument.is_active or instrument.exchange_code != "SHFE"
            or contract is None or contract.instrument_symbol != "au" or contract.exchange_code != "SHFE"
            or contract.provider != "rqdata" or contract.listed_date != DAY
            or contract.expired_date != date(2023, 4, 17)):
        raise CorrectionError("IDENTITY_DRIFT")
    # Prior diagnostic found no SHFE session at this date. Any new fact needs a new review.
    occupied = session.scalar(select(TradingSession.id).where(
        TradingSession.exchange_code == "SHFE", TradingSession.effective_from <= DAY,
        or_(TradingSession.effective_to.is_(None), TradingSession.effective_to >= DAY)).limit(1))
    if occupied is not None:
        raise CorrectionError("SESSION_BASELINE_DRIFT")
    bind = session.get_bind()
    url = bind.engine.url
    environment = {"driver": url.drivername, "host": url.host, "port": url.port,
                   "database": url.database, "schema_map": bind.get_execution_options().get("schema_translate_map")}
    if bind.dialect.name == "postgresql":
        environment["resolved_database"] = session.scalar(text("SELECT current_database()"))
        environment["resolved_schema"] = session.scalar(text("SELECT current_schema()"))
        relations = []
        for name in ("exchanges", "instruments", "contracts", "trading_calendars", "trading_sessions"):
            relation = session.execute(text(
                "SELECT n.nspname, c.relname, c.oid FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.oid = to_regclass(:name)"
            ), {"name": name}).one()
            relations.append(list(relation))
        environment["resolved_relations"] = relations
    return {"calendar": _row(calendar), "exchange": _row(exchange), "instrument": _row(instrument),
            "contract": _row(contract), "sessions": [], "database_identity_sha256": _hash(environment)}


def _plan(session: Session, evidence: dict) -> dict:
    if (not isinstance(evidence, dict) or not _sha(evidence.get("file_sha256"))
            or evidence.get("source_response_sha256") != SOURCE_SHA256
            or _hash(evidence.get("source_response")) != SOURCE_SHA256
            or evidence.get("normalized_sessions") != _normalize_response(REQUEST, evidence["source_response"])):
        raise CorrectionError("EVIDENCE_INVALID")
    plan = {"schema_version": 1, "command": "data.au-calendar-correction", "status": "planned",
            "readonly": True, "target": {k: BEFORE[k] for k in ("id", "exchange_code", "trade_date")},
            "change": {"has_night_session": {"before": False, "after": True}},
            "planned_calendar_updates": 1, "database_writes": 0, "provider_requests": 0,
            "canonical_writes": 0, "session_writes": 0, "evidence": evidence,
            "baseline": _facts(session)}
    return {**plan, "plan_sha256": _hash(plan)}


def plan_correction(session: Session, evidence: dict) -> dict:
    with readonly_transaction(session, timeout_seconds=60):
        return _plan(session, evidence)


def apply_correction(session: Session, plan: dict, *, expected_plan_sha256: str) -> None:
    """One transaction and one field. Commit uncertainty is never retried."""
    if (not isinstance(plan, dict) or not _sha(expected_plan_sha256)
            or plan.get("plan_sha256") != expected_plan_sha256
            or _hash({k: v for k, v in plan.items() if k != "plan_sha256"}) != expected_plan_sha256):
        raise CorrectionError("PLAN_HASH_INVALID")
    if session.in_transaction() or session.new or session.dirty or session.deleted:
        raise CorrectionError("SESSION_NOT_CLEAN")
    committing = False
    try:
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("SET LOCAL statement_timeout = '60s'"))
            session.execute(text("LOCK TABLE exchanges, instruments, contracts, trading_calendars, "
                                 "trading_sessions IN SHARE ROW EXCLUSIVE MODE"))
        elif dialect == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            raise CorrectionError("DIALECT_UNSUPPORTED")
        if _plan(session, plan["evidence"]) != plan:
            raise CorrectionError("PLAN_DRIFT")
        calendar = session.get(TradingCalendar, 46796)
        assert calendar is not None
        calendar.has_night_session = True
        session.flush()
        if _facts(session, corrected=True) != {
            **plan["baseline"], "calendar": {**BEFORE, "has_night_session": True}
        }:
            raise CorrectionError("IN_TRANSACTION_READBACK_FAILED")
        committing = True
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            session.invalidate()
        if committing:
            raise CorrectionError("COMMIT_OUTCOME_UNKNOWN") from None
        if isinstance(exc, CorrectionError):
            raise
        raise CorrectionError("APPLY_FAILED") from None


def run_correction(args, session_factory) -> dict:
    evidence = read_evidence(args.evidence, args.expected_evidence_sha256)
    with session_factory() as session:
        plan = plan_correction(session, evidence)
    if not args.apply:
        return plan
    with session_factory() as session:
        apply_correction(session, plan, expected_plan_sha256=args.expected_plan_sha256)
    try:
        with session_factory() as session, readonly_transaction(session, timeout_seconds=60):
            actual = _facts(session, corrected=True)
            if actual != {**plan["baseline"], "calendar": {**BEFORE, "has_night_session": True}}:
                raise CorrectionError("READBACK_FAILED")
    except Exception:
        raise CorrectionError("COMMITTED_READBACK_UNVERIFIED") from None
    return {"schema_version": 1, "command": "data.au-calendar-correction", "status": "passed",
            "readonly": False, "plan_sha256": plan["plan_sha256"], "database_writes": 1,
            "provider_requests": 0, "canonical_writes": 0, "session_writes": 0,
            "readback_verified": True, "calendar": actual["calendar"]}
