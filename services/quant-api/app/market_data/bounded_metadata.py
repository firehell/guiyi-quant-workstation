"""Exact missing metadata: read-only plan, separate fetch, insert-only transaction.

Payload hashes bind operator-reviewed content, not authority to perform an operation.
There is deliberately no synchronizer, provider retry, or historical Bar writer here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, time, timedelta
import hashlib
import json
import re
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.market_data.coverage_source import _calendar_context_start
from app.market_data.operational_universe import load_active_products
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession


class MetadataRepairError(ValueError):
    """Bounded public failure; raw DB/provider exceptions are never exposed."""

    def __init__(self, reason: str):
        self.code = "METADATA_REPAIR_" + reason
        super().__init__(self.code)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      default=lambda item: item.isoformat())


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _sealed(value: dict, field: str) -> dict:
    return {**value, field: _hash(value)}


def _check(value: dict, field: str, expected: str | None = None) -> None:
    if not isinstance(value, dict):
        raise MetadataRepairError("PAYLOAD_INVALID")
    actual = value.get(field)
    if (not isinstance(actual, str) or re.fullmatch("[0-9a-f]{64}", actual) is None
            or actual != _hash({k: v for k, v in value.items() if k != field})
            or (expected is not None and actual != expected)):
        raise MetadataRepairError("HASH_INVALID")


def _day(value: Any) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise MetadataRepairError("DATE_INVALID")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise MetadataRepairError("DATE_INVALID") from None


def _days(start: date, end: date):
    if not 0 <= (end - start).days <= 20000:
        raise MetadataRepairError("SCOPE_INVALID")
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def validate_targets(targets: Any) -> list[dict]:
    """Only explicit active product/physical contract/owner-through triples."""
    if not isinstance(targets, list) or not 1 <= len(targets) <= 64:
        raise MetadataRepairError("SCOPE_INVALID")
    unique = {}
    active = load_active_products()
    for item in targets:
        if not isinstance(item, dict) or set(item) != {"symbol", "contract", "through"}:
            raise MetadataRepairError("SCOPE_INVALID")
        symbol, contract = item["symbol"], item["contract"]
        if (not isinstance(symbol, str) or symbol not in active
                or not isinstance(contract, str)
                or re.fullmatch(re.escape(symbol.upper()) + r"\d{3,4}", contract) is None):
            raise MetadataRepairError("IDENTITY_INVALID")
        through = _day(item["through"])
        if through >= date.today():
            raise MetadataRepairError("SCOPE_INVALID")
        normalized = {**item, "through": through.isoformat()}
        unique[_json(normalized)] = normalized
    return [unique[key] for key in sorted(unique)]


def _row(row: Any) -> dict:
    return json.loads(_json({column.name: getattr(row, column.name)
                            for column in row.__table__.columns}))


def plan_metadata(session: Session, targets: list[dict], *, classification: dict | None = None,
                  evidence_sources: list[dict] | None = None) -> dict:
    """Read relevant Catalog facts; no provider or writer construction."""
    targets = validate_targets(targets)
    classified: list[dict] = []
    source_hash = None
    if classification is not None:
        _validate_snapshot(classification)
        if classification["plan"]["targets"] != targets:
            raise MetadataRepairError("CLASSIFICATION_SCOPE_INVALID")
        classified = classification["classified"]
        source_hash = classification["snapshot_sha256"]
    return _plan(session, targets, classified, source_hash,
                 evidence_sources if evidence_sources is not None else [])


def _identity(session: Session, target: dict) -> tuple[Contract, Instrument, Exchange]:
    contract = session.scalar(select(Contract).where(Contract.contract_code == target["contract"]))
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == target["symbol"]))
    exchange = None if instrument is None else session.scalar(
        select(Exchange).where(Exchange.code == instrument.exchange_code))
    if (contract is None or instrument is None or exchange is None
            or contract.instrument_symbol != target["symbol"]
            or contract.exchange_code != instrument.exchange_code
            or contract.provider != "rqdata" or not instrument.is_active or not exchange.is_active
            or contract.listed_date is None or contract.expired_date is None
            or contract.listed_date >= contract.expired_date):
        raise MetadataRepairError("IDENTITY_UNKNOWN")
    return contract, instrument, exchange


def _plan(session: Session, targets: list[dict], classified: list[dict], source_hash: str | None,
          evidence_sources: list[dict]) -> dict:
    if session.new or session.dirty or session.deleted:
        raise MetadataRepairError("SESSION_NOT_CLEAN")
    # A reusable Session may retain identity-map objects after an earlier commit.
    # All facts below must be read under this transaction's current lock/snapshot.
    session.expire_all()
    facts: list[dict] = []
    resolved = []
    calendar_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    session_sources: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for target in targets:
        contract, instrument, exchange = _identity(session, target)
        assert contract.listed_date is not None and contract.expired_date is not None
        through = min(_day(target["through"]), contract.expired_date - timedelta(days=1))
        if through < contract.listed_date:
            raise MetadataRepairError("SCOPE_INVALID")
        facts.extend((_row(contract), _row(instrument), _row(exchange)))
        context_start = _calendar_context_start(contract.listed_date)
        context_end = through + timedelta(days=7)
        resolved.append({**target, "exchange": exchange.code,
                         "listed_date": contract.listed_date.isoformat(),
                         "expired_date": contract.expired_date.isoformat(),
                         "effective_through": through.isoformat(),
                         "calendar_start": context_start.isoformat(),
                         "calendar_end": context_end.isoformat()})
        for day in _days(context_start, context_end):
            calendar_sources[(exchange.code, day.isoformat())].add(contract.contract_code)
        for day in _days(contract.listed_date, through):
            session_sources[(instrument.symbol, exchange.code, day.isoformat())].add(contract.contract_code)
    if len(calendar_sources) + len(session_sources) > 120000:
        raise MetadataRepairError("SCOPE_INVALID")
    exchanges = {key[0] for key in calendar_sources}
    floor, ceiling = min(k[1] for k in calendar_sources), max(k[1] for k in calendar_sources)
    calendars = list(session.scalars(select(TradingCalendar).where(
        TradingCalendar.exchange_code.in_(exchanges), TradingCalendar.trade_date >= _day(floor),
        TradingCalendar.trade_date <= _day(ceiling))))
    calendars = [row for row in calendars if (row.exchange_code, row.trade_date.isoformat()) in calendar_sources]
    calendar_by_key = {(r.exchange_code, r.trade_date.isoformat()): r for r in calendars}
    for row in calendars:
        if row.provider != "rqdata" or (not row.is_trading_day and row.has_night_session):
            raise MetadataRepairError("CALENDAR_CONFLICT")
    sessions = list(session.scalars(select(TradingSession).where(
        TradingSession.instrument_symbol.in_({t["symbol"] for t in targets}),
        TradingSession.effective_from <= _day(ceiling),
        or_(TradingSession.effective_to.is_(None), TradingSession.effective_to >= _day(floor)))))
    existing_session_days: set[tuple[str, str]] = set()
    for existing_session in sessions:
        if (existing_session.start_time == existing_session.end_time
                or existing_session.crosses_midnight != (existing_session.end_time < existing_session.start_time)
                or any(value.second or value.microsecond for value in (existing_session.start_time, existing_session.end_time))
                or existing_session.start_time.minute not in {0, 30}):
            raise MetadataRepairError("SESSION_INVALID")
        if existing_session.is_active and existing_session.effective_from == existing_session.effective_to:
            key = (existing_session.exchange_code, existing_session.effective_from.isoformat())
            if key in calendar_sources:
                existing_session_days.add(key)
                calendar = calendar_by_key.get(key)
                night = existing_session.start_time >= time(18) or existing_session.crosses_midnight
                if calendar is not None and (
                    not calendar.is_trading_day or (night and not calendar.has_night_session)
                ):
                    raise MetadataRepairError("CALENDAR_CONFLICT")
    # Preserve every existing row (including inactive/partial/template rows) in the baseline.
    # An occupied date is never repaired by appending missing pieces.
    facts.extend(_row(row) for row in (*calendars, *sessions))
    missing_calendars = [{"exchange": exchange, "date": day, "source_contracts": sorted(sources)}
                         for (exchange, day), sources in sorted(calendar_sources.items())
                         if (exchange, day) not in calendar_by_key]
    classifications = {(r["exchange"], r["date"]): r["is_trading_day"] for r in classified}
    if any(key not in calendar_sources for key in classifications):
        raise MetadataRepairError("CLASSIFICATION_SCOPE_INVALID")
    for key, trading in classifications.items():
        if key in calendar_by_key and calendar_by_key[key].is_trading_day != trading:
            raise MetadataRepairError("CALENDAR_CONFLICT")
    missing_sessions, occupied = [], 0
    for (symbol, exchange_code, day), sources in sorted(session_sources.items()):
        calendar = calendar_by_key.get((exchange_code, day))
        trading = calendar.is_trading_day if calendar is not None else classifications.get((exchange_code, day))
        if trading is not True:
            continue
        existing = [r for r in sessions if r.instrument_symbol == symbol
                    and r.effective_from <= _day(day)
                    and (r.effective_to is None or r.effective_to >= _day(day))]
        if existing:
            occupied += 1
            if any(r.exchange_code != exchange_code or r.provider != "rqdata" or not r.is_active
                   or r.effective_from != _day(day) or r.effective_to != _day(day) for r in existing):
                raise MetadataRepairError("SESSION_OVERLAP")
            continue
        missing_sessions.append({"symbol": symbol, "exchange": exchange_code, "date": day,
                                 "source_contracts": sorted(sources)})
    source_values, evidence_resolved = [], []
    if not isinstance(evidence_sources, list) or len(evidence_sources) > 4096:
        raise MetadataRepairError("SCOPE_INVALID")
    for source in evidence_sources:
        if not isinstance(source, dict) or set(source) != {"symbol", "contract", "date"}:
            raise MetadataRepairError("SCOPE_INVALID")
        validate_targets([{ "symbol": source["symbol"], "contract": source["contract"], "through": source["date"]}])
        source_contract, source_instrument, source_exchange = _identity(session, source)
        source_day = _day(source["date"])
        assert source_contract.listed_date is not None and source_contract.expired_date is not None
        if (not source_contract.listed_date <= source_day < source_contract.expired_date
                or not any(r["exchange"] == source_exchange.code and r["date"] == source["date"] for r in missing_calendars)
                or classifications.get((source_exchange.code, source["date"])) is not True):
            raise MetadataRepairError("EVIDENCE_SCOPE_INVALID")
        source_values.append(source)
        evidence_resolved.append({**source, "exchange": source_exchange.code,
                                  "listed_date": source_contract.listed_date.isoformat(),
                                  "expired_date": source_contract.expired_date.isoformat()})
        facts.extend((_row(source_contract), _row(source_instrument), _row(source_exchange)))
    source_values = sorted({_json(r): r for r in source_values}.values(), key=_json)
    evidence_resolved = sorted({_json(r): r for r in evidence_resolved}.values(), key=_json)
    requests = _requests(missing_calendars, missing_sessions, classifications, evidence_resolved)
    return _sealed({"version": 1, "command": "data.metadata-repair", "status": "planned", "readonly": True,
                    "targets": targets, "resolved_targets": resolved,
                    "baseline_sha256": _hash(sorted({_json(f): f for f in facts}.values(), key=_json)),
                    "classification": classified, "classification_source_sha256": source_hash,
                    "missing_calendars": missing_calendars, "missing_sessions": missing_sessions,
                    "existing_session_days": [{"exchange": exchange, "date": day}
                                              for exchange, day in sorted(existing_session_days)],
                    "evidence_sources": source_values, "resolved_evidence_sources": evidence_resolved,
                    "session_calendars": [_row(row) for row in sorted(calendars, key=lambda r: (r.exchange_code, r.trade_date))
                                          if any(r["exchange"] == row.exchange_code and r["date"] == row.trade_date.isoformat() for r in missing_sessions)],
                    "existing_night_evidence": sorted([_row(row) for row in sessions
                        if row.provider == "rqdata" and row.is_active
                        and row.effective_from == row.effective_to
                        and any(t["symbol"] == row.instrument_symbol and t["exchange"] == row.exchange_code for t in resolved)
                        and (row.start_time >= time(18) or row.crosses_midnight)], key=_json),
                    "requests": requests,
                    "counts": {"natural_date_keys": len(missing_calendars), "session_dates": len(missing_sessions),
                               "session_rows": None, "existing_session_dates_preserved": occupied,
                               "evidence_source_days": len(source_values),
                               "provider_requests": len(requests)},
                    "impact": "insert missing Calendar and whole Session days only; consumers use existing Catalog",
                    "recovery": "rollback before commit; after commit preserve inserted facts and replan; no automatic deletion"},
                   "plan_sha256")


def _requests(calendars: list[dict], sessions: list[dict], classifications: dict,
              evidence_sources: list[dict]) -> list[dict]:
    requests: list[dict] = []
    for item in calendars:
        if (item["exchange"], item["date"]) in classifications:
            continue
        if (requests and requests[-1]["method"] == "get_trading_dates"
                and requests[-1]["exchange"] == item["exchange"]
                and _day(requests[-1]["end_date"]) + timedelta(days=1) == _day(item["date"])):
            requests[-1]["end_date"] = item["date"]
        else:
            requests.append({"method": "get_trading_dates", "exchange": item["exchange"],
                             "start_date": item["date"], "end_date": item["date"]})
    for item in sessions:
        for contract in item["source_contracts"]:
            requests.append({"method": "get_trading_periods", "contract": contract,
                             "symbol": item["symbol"], "exchange": item["exchange"],
                             "start_date": item["date"], "end_date": item["date"], "frequency": "1m"})
    for source in evidence_sources:
        request = {"method": "get_trading_periods", "contract": source["contract"], "symbol": source["symbol"],
                   "exchange": source["exchange"], "start_date": source["date"], "end_date": source["date"], "frequency": "1m"}
        if request not in requests:
            requests.append(request)
    return requests


def _validate_plan(plan: dict, expected: str | None = None) -> None:
    _check(plan, "plan_sha256", expected)
    if plan.get("version") != 1 or validate_targets(plan["targets"]) != plan["targets"]:
        raise MetadataRepairError("PLAN_INVALID")
    classifications = {(r["exchange"], r["date"]): r["is_trading_day"] for r in plan["classification"]}
    if plan["requests"] != _requests(plan["missing_calendars"], plan["missing_sessions"], classifications, plan["resolved_evidence_sources"]):
        raise MetadataRepairError("SCOPE_INVALID")
    if [{key: r[key] for key in ("symbol", "contract", "through")} for r in plan["resolved_targets"]] != plan["targets"]:
        raise MetadataRepairError("SCOPE_INVALID")
    for resolved in plan["resolved_targets"]:
        start, expired = _day(resolved["listed_date"]), _day(resolved["expired_date"])
        through = min(_day(resolved["through"]), expired - timedelta(days=1))
        if (start > through or resolved["effective_through"] != through.isoformat()
                or resolved["calendar_start"] != _calendar_context_start(start).isoformat()
                or resolved["calendar_end"] != (through + timedelta(days=7)).isoformat()):
            raise MetadataRepairError("SCOPE_INVALID")
    for kind, rows in (("calendar", plan["missing_calendars"]), ("session", plan["missing_sessions"])):
        if len(rows) != len({_json(row) for row in rows}):
            raise MetadataRepairError("SCOPE_INVALID")
        for row in rows:
            start_key, end_key = ("calendar_start", "calendar_end") if kind == "calendar" else ("listed_date", "effective_through")
            sources = sorted({r["contract"] for r in plan["resolved_targets"]
                              if r["exchange"] == row["exchange"] and r[start_key] <= row["date"] <= r[end_key]
                              and (kind == "calendar" or r["symbol"] == row["symbol"])})
            if not sources or sources != row["source_contracts"]:
                raise MetadataRepairError("SCOPE_INVALID")
    for source in plan["resolved_evidence_sources"]:
        if (not source["listed_date"] <= source["date"] < source["expired_date"]
                or classifications.get((source["exchange"], source["date"])) is not True
                or not any(r["exchange"] == source["exchange"] and r["date"] == source["date"] for r in plan["missing_calendars"])):
            raise MetadataRepairError("EVIDENCE_SCOPE_INVALID")


def recheck_plan(session: Session, plan: dict, *, expected_plan_sha256: str) -> None:
    """Refresh Catalog prerequisites before any provider construction."""
    _validate_plan(plan, expected_plan_sha256)
    fresh = _plan(session, plan["targets"], plan["classification"], plan["classification_source_sha256"], plan["evidence_sources"])
    if fresh != plan:
        raise MetadataRepairError("PLAN_DRIFT")


def fetch_metadata(plan: dict, *, expected_plan_sha256: str, api: Any) -> dict:
    """Execute the frozen requests serially once; never expand from returned dates."""
    from app.market_data.rqdata_adapter import fetch_bounded_metadata_request

    _validate_plan(plan, expected_plan_sha256)
    responses = []
    seen_sessions: dict[tuple[str, str], list[dict]] = {}
    for request in plan["requests"]:
        try:
            response = fetch_bounded_metadata_request(api, request)
        except Exception:
            raise MetadataRepairError("PROVIDER_FAILED") from None
        rows = _normalize_response(request, response)
        if request["method"] == "get_trading_periods":
            _merge_sessions(seen_sessions, request, rows)
            _check_calendar_night(plan, rows)
        responses.append(response)
    return _snapshot(plan, responses)


def _normalize_response(request: dict, response: list) -> list[dict]:
    from app.market_data.rqdata_adapter import historical_session_rows

    if request["method"] == "get_trading_dates":
        if not isinstance(response, list) or len(response) != len(set(response)):
            raise MetadataRepairError("PROVIDER_RESPONSE_INVALID")
        dates = {_day(value) for value in response}
        scope = set(_days(_day(request["start_date"]), _day(request["end_date"])))
        if not dates <= scope:
            raise MetadataRepairError("PROVIDER_SCOPE_INVALID")
        return [{"exchange": request["exchange"], "date": day.isoformat(), "is_trading_day": day in dates}
                for day in sorted(scope)]
    day = _day(request["start_date"])
    if (not isinstance(response, list) or len(response) != 1 or not isinstance(response[0], dict)
            or set(response[0]) != {"order_book_id", "date", "trading_hours"}
            or response[0]["order_book_id"] != request["contract"]
            or _day(response[0]["date"]) != day
            or not isinstance(response[0]["trading_hours"], str)):
        raise MetadataRepairError("PROVIDER_SCOPE_INVALID")
    try:
        normalized = list(historical_session_rows(
            tuple(response), [(request["symbol"], day, request["contract"])],
            {request["symbol"]: request["exchange"]}, reject_extra=True))
    except Exception:
        raise MetadataRepairError("PROVIDER_SESSIONS_INVALID") from None
    return json.loads(_json(normalized))


def _merge_sessions(seen: dict[tuple[str, str], list[dict]], request: dict, rows: list[dict]) -> None:
    key = (request["symbol"], request["start_date"])
    if key in seen and seen[key] != rows:
        raise MetadataRepairError("SOURCE_DISAGREEMENT")
    seen[key] = rows


def _snapshot(plan: dict, responses: list) -> dict:
    if len(responses) != len(plan["requests"]):
        raise MetadataRepairError("PROVIDER_RESPONSE_INVALID")
    classified = {(r["exchange"], r["date"]): r for r in plan["classification"]}
    sessions_by_key: dict[tuple[str, str], list[dict]] = {}
    for request, response in zip(plan["requests"], responses, strict=True):
        rows = _normalize_response(request, response)
        if request["method"] == "get_trading_dates":
            for row in rows:
                classified[(row["exchange"], row["date"])] = row
        else:
            _merge_sessions(sessions_by_key, request, rows)
            _check_calendar_night(plan, rows)
    source_sessions = [row for key in sorted(sessions_by_key) for row in sessions_by_key[key]]
    writable_keys = {(r["symbol"], r["date"]) for r in plan["missing_sessions"]}
    sessions = [row for row in source_sessions if (row["instrument_symbol"], row["effective_from"]) in writable_keys]
    calendars, blockers = [], []
    for missing in plan["missing_calendars"]:
        key = (missing["exchange"], missing["date"])
        item = classified.get(key)
        if item is None or type(item.get("is_trading_day")) is not bool:
            raise MetadataRepairError("CLASSIFICATION_INVALID")
        # Positive evidence proves exchange night existence. Absence in one product
        # cannot prove exchange-wide absence; this bounded operation must stop there.
        night = any(row["exchange_code"] == missing["exchange"]
                    and row["effective_from"] == missing["date"]
                    and (row["start_time"] >= "18:00:00" or row["crosses_midnight"])
                    for row in (*source_sessions, *plan["existing_night_evidence"]))
        if not item["is_trading_day"] and (
            night or {"exchange": missing["exchange"], "date": missing["date"]} in plan["existing_session_days"]
        ):
            raise MetadataRepairError("CALENDAR_CONFLICT")
        if item["is_trading_day"] and not night:
            blockers.append({**missing, "code": "NIGHT_SESSION_EVIDENCE_REQUIRED"})
        else:
            calendars.append({"exchange_code": missing["exchange"], "trade_date": missing["date"],
                              "is_trading_day": item["is_trading_day"], "has_night_session": night,
                              "provider": "rqdata"})
    return _sealed({"version": 1, "command": "data.metadata-repair", "status": "blocked" if blockers else "prepared",
                    "readonly": False, "database_writes": 0, "provider_request_count": len(responses),
                    "plan": plan, "responses": responses,
                    "classified": [classified[key] for key in sorted(classified)],
                    "calendars": calendars, "sessions": sessions, "blockers": blockers}, "snapshot_sha256")


def _validate_snapshot(snapshot: dict) -> None:
    _check(snapshot, "snapshot_sha256")
    _validate_plan(snapshot["plan"])
    if _snapshot(snapshot["plan"], snapshot["responses"]) != snapshot:
        raise MetadataRepairError("SNAPSHOT_INVALID")


def _check_calendar_night(plan: dict, rows: list[dict]) -> None:
    for row in rows:
        night = row["start_time"] >= "18:00:00" or row["crosses_midnight"]
        if night and any(r["exchange_code"] == row["exchange_code"]
                         and r["trade_date"] == row["effective_from"] and not r["has_night_session"]
                         for r in plan["session_calendars"]):
            raise MetadataRepairError("CALENDAR_CONFLICT")


def apply_metadata(session: Session, snapshot: dict, *, expected_plan_sha256: str,
                   expected_snapshot_sha256: str) -> dict:
    """Fresh lock/recheck then one insert-only commit. No provider exists on this path."""
    _check(snapshot, "snapshot_sha256", expected_snapshot_sha256)
    _validate_snapshot(snapshot)
    plan = snapshot["plan"]
    _validate_plan(plan, expected_plan_sha256)
    if snapshot["blockers"]:
        raise MetadataRepairError("SNAPSHOT_BLOCKED")
    if session.in_transaction() or session.new or session.dirty or session.deleted:
        raise MetadataRepairError("SESSION_NOT_CLEAN")
    try:
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("LOCK TABLE exchanges, instruments, contracts, trading_calendars, "
                                 "trading_sessions IN SHARE ROW EXCLUSIVE MODE"))
        elif dialect == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            raise MetadataRepairError("DIALECT_UNSUPPORTED")
        fresh = _plan(session, plan["targets"], plan["classification"], plan["classification_source_sha256"], plan["evidence_sources"])
        if fresh != plan:
            raise MetadataRepairError("PLAN_DRIFT")
        for row in snapshot["calendars"]:
            session.add(TradingCalendar(**{**row, "trade_date": _day(row["trade_date"])}))
        for row in snapshot["sessions"]:
            session.add(TradingSession(**{**row, "effective_from": _day(row["effective_from"]),
                                          "effective_to": _day(row["effective_to"]),
                                          "start_time": time.fromisoformat(row["start_time"]),
                                          "end_time": time.fromisoformat(row["end_time"])}))
        session.flush()
        session.commit()
    except Exception as exc:
        session.rollback()
        if isinstance(exc, MetadataRepairError):
            raise
        raise MetadataRepairError("APPLY_FAILED") from None
    return {"command": "data.metadata-repair", "status": "passed", "readonly": False,
            "plan_sha256": expected_plan_sha256, "snapshot_sha256": expected_snapshot_sha256,
            "calendar_rows": len(snapshot["calendars"]), "session_rows": len(snapshot["sessions"])}
