"""Runtime-bound current-day metadata capture, exact plan, and one-shot apply.

The snapshot is provider evidence, not write authority.  Plan and apply never
construct a provider; apply revalidates the exact Catalog diff while holding the
global maintenance lease and then delegates to ``MetadataSynchronizer``'s
validated current-day writer.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hashlib
import json
import re
from typing import Any, Callable, Mapping

from sqlalchemy import or_, select

from app.market_data.metadata import MetadataSnapshot, MetadataSynchronizer
from app.market_data.closeout_binding import RuntimeRecoveryBindingError
from app.models import MainContractMap, TradingCalendar, TradingSession


class CurrentDayMetadataRecoveryError(ValueError):
    """Bounded public failure for the explicit recovery command."""

    def __init__(self, reason: str):
        self.code = "CURRENT_DAY_METADATA_" + reason
        super().__init__(self.code)


def _json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise CurrentDayMetadataRecoveryError("PAYLOAD_INVALID") from None


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _encode_value(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is date:
        return {"$date": value.isoformat()}
    if type(value) is time and value.tzinfo is None:
        return {"$time": value.isoformat()}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID")
        return {key: _encode_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_encode_value(item) for item in value]
    raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID")


def _decode_value(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if isinstance(value, list):
        return tuple(_decode_value(item) for item in value)
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID")
    if set(value) == {"$date"}:
        try:
            return date.fromisoformat(value["$date"])
        except (TypeError, ValueError):
            raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID") from None
    if set(value) == {"$time"}:
        try:
            parsed = time.fromisoformat(value["$time"])
        except (TypeError, ValueError):
            raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID") from None
        if parsed.tzinfo is not None:
            raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID")
        return parsed
    if any(key.startswith("$") for key in value):
        raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID")
    return {key: _decode_value(item) for key, item in value.items()}


def application_call_summary(product_count: int) -> dict[str, Any]:
    """Document this adapter's application calls, never provider billing units."""
    if type(product_count) is not int or not 1 <= product_count <= 64:
        raise CurrentDayMetadataRecoveryError("SCOPE_INVALID")
    calls = (
        {
            "method": "get_trading_dates",
            "purpose": "next_trading_day_probe",
            "count": 1,
        },
        {
            "method": "all_instruments",
            "purpose": "complete_futures_inventory",
            "count": 1,
        },
        {"method": "get_trading_dates", "purpose": "bounded_calendar", "count": 1},
        {
            "method": "futures.get_dominant",
            "purpose": "rank1_by_product",
            "count": product_count,
        },
        {"method": "get_trading_periods", "purpose": "batched_sessions", "count": 1},
    )
    return {
        "boundary": "application_level_not_provider_billing",
        "total": product_count + 4,
        "calls": list(calls),
    }


def encode_current_day_snapshot(
    snapshot: MetadataSnapshot,
    *,
    products: tuple[str, ...],
    trading_day: date,
    source_capture_sha256: str | None = None,
) -> dict[str, Any]:
    """Encode one snapshot with an exact semantic SHA-256."""
    normalized = _products(products)
    _trading_day(trading_day)
    payload = {
        "schema_version": 1,
        "command": "data.current-day-metadata-recovery",
        "status": "captured",
        "readonly": source_capture_sha256 is not None,
        "products": list(normalized),
        "trading_day": trading_day.isoformat(),
        "source": {
            "method": (
                "frozen_rqdata_capture"
                if source_capture_sha256 is not None
                else "RQDataMarketAdapter.fetch_current_day_metadata"
            ),
            "arguments": {
                "products": list(normalized),
                "trading_day": trading_day.isoformat(),
            },
            **(
                {"capture_sha256": source_capture_sha256}
                if source_capture_sha256 is not None
                else {}
            ),
        },
        "application_calls": application_call_summary(len(normalized)),
        "snapshot": {
            "exchanges": _encode_value(snapshot.exchanges),
            "instruments": _encode_value(snapshot.instruments),
            "contracts": _encode_value(snapshot.contracts),
            "calendars": _encode_value(snapshot.calendars),
            "sessions": _encode_value(snapshot.sessions),
            "main_contracts": _encode_value(snapshot.main_contracts),
            "main_contract_starts": _encode_value(snapshot.main_contract_starts),
        },
        "database_writes": 0,
        "canonical_writes": 0,
    }
    return {**payload, "snapshot_sha256": _hash(payload)}


def import_frozen_current_day_capture(
    content: bytes,
    *,
    expected_capture_sha256: str,
    products: tuple[str, ...],
    trading_day: date,
    snapshot_builder: Callable[[dict[str, Any], tuple[str, ...], date], MetadataSnapshot]
    | None = None,
) -> dict[str, Any]:
    """Reconstruct the normal snapshot from one pinned, provider-free source response."""
    if (
        not isinstance(content, bytes)
        or not 0 < len(content) <= 16 * 1024 * 1024
        or not isinstance(expected_capture_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_capture_sha256) is None
        or hashlib.sha256(content).hexdigest() != expected_capture_sha256
    ):
        raise CurrentDayMetadataRecoveryError("CAPTURE_HASH_INVALID")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CurrentDayMetadataRecoveryError("CAPTURE_INVALID")
            result[key] = value
        return result

    try:
        source = json.loads(content, object_pairs_hook=unique_object)
    except (UnicodeError, ValueError, TypeError):
        raise CurrentDayMetadataRecoveryError("CAPTURE_INVALID") from None
    normalized = _products(products)
    _trading_day(trading_day)
    expected_keys = {
        "allowed_session_dates", "bar_requests", "calendar_end",
        "candidate_commit", "capture_finished_at", "capture_started_at",
        "operational_products", "physical_contract_budget", "probe_end",
        "production_writes", "provider_call_budget", "provider_call_count",
        "provider_calls", "requested_contracts", "schema_version",
        "snapshot_summary", "source_dominants", "source_instruments",
        "source_periods", "source_trading_dates", "status", "trading_day",
    }
    calls = [
        "get_trading_dates", "all_instruments", "get_trading_dates",
        *(["get_dominant"] * len(normalized)), "get_trading_periods",
    ]
    try:
        probe_dates, bounded_dates = source["source_trading_dates"]
        next_day = next(
            date.fromisoformat(value)
            for value in probe_dates
            if date.fromisoformat(value) > trading_day
        )
        calendar_end = max(
            trading_day + timedelta(days=7 - trading_day.isoweekday()), next_day
        )
        starts = datetime.fromisoformat(source["capture_started_at"])
        finished = datetime.fromisoformat(source["capture_finished_at"])
        requested = source["requested_contracts"]
        summary = source["snapshot_summary"]
        valid = (
            isinstance(source, dict)
            and set(source) == expected_keys
            and source["schema_version"] == 1
            and source["status"] == "source_captured"
            and source["trading_day"] == trading_day.isoformat()
            and source["operational_products"] == list(normalized)
            and isinstance(source["candidate_commit"], str)
            and re.fullmatch(r"[0-9a-f]{40}", source["candidate_commit"]) is not None
            and starts.utcoffset() is not None
            and finished.utcoffset() is not None
            and starts <= finished <= datetime.now(finished.tzinfo)
            and source["probe_end"] == (trading_day + timedelta(days=14)).isoformat()
            and source["calendar_end"] == calendar_end.isoformat()
            and type(source["provider_call_budget"]) is int
            and source["provider_call_budget"] == len(calls)
            and type(source["provider_call_count"]) is int
            and source["provider_call_count"] == len(calls)
            and source["provider_calls"] == calls
            and type(source["bar_requests"]) is int
            and source["bar_requests"] == 0
            and type(source["production_writes"]) is int
            and source["production_writes"] == 0
            and type(source["physical_contract_budget"]) is int
            and 1 <= source["physical_contract_budget"] <= 150
            and isinstance(requested, list)
            and 0 < len(requested) <= source["physical_contract_budget"]
            and len(set(requested)) == len(requested)
            and all(isinstance(value, str) and value == value.upper() for value in requested)
            and isinstance(probe_dates, list)
            and isinstance(bounded_dates, list)
            and trading_day.isoformat() in probe_dates
            and trading_day.isoformat() in bounded_dates
            and next_day.isoformat() in bounded_dates
            and probe_dates == sorted(set(probe_dates))
            and bounded_dates == sorted(set(bounded_dates))
            and all(trading_day <= date.fromisoformat(value) <= calendar_end for value in bounded_dates)
            and isinstance(source["allowed_session_dates"], list)
            and source["allowed_session_dates"] == sorted(set(source["allowed_session_dates"]))
            and set(source["allowed_session_dates"]) <= set(bounded_dates)
            and {trading_day.isoformat(), next_day.isoformat()} <= set(source["allowed_session_dates"])
            and isinstance(source["source_instruments"], list)
            and isinstance(source["source_periods"], list)
            and isinstance(source["source_dominants"], dict)
            and set(source["source_dominants"]) == {item.upper() for item in normalized}
            and all(isinstance(value, list) for value in source["source_dominants"].values())
            and isinstance(summary, dict)
            and set(summary) == {"calendar_rows", "rank1_rows", "session_rows", "unknown_calendar_keys"}
            and summary["unknown_calendar_keys"] == []
            and all(type(summary[key]) is int and summary[key] >= 0 for key in ("calendar_rows", "rank1_rows", "session_rows"))
        )
    except (KeyError, TypeError, ValueError, StopIteration):
        valid = False
    if not valid:
        raise CurrentDayMetadataRecoveryError("CAPTURE_INVALID")
    if snapshot_builder is None:
        from app.market_data.frozen_metadata_capture import frozen_snapshot

        snapshot_builder = frozen_snapshot
    try:
        snapshot = snapshot_builder(source, normalized, trading_day)
    except Exception:
        raise CurrentDayMetadataRecoveryError("CAPTURE_SOURCE_INVALID") from None
    if not isinstance(snapshot, MetadataSnapshot):
        raise CurrentDayMetadataRecoveryError("CAPTURE_SOURCE_INVALID")
    encoded = encode_current_day_snapshot(
        snapshot,
        products=normalized,
        trading_day=trading_day,
        source_capture_sha256=expected_capture_sha256,
    )
    return encoded


def decode_current_day_snapshot(
    payload: Any,
    *,
    expected_snapshot_sha256: str,
    products: tuple[str, ...],
    trading_day: date,
) -> MetadataSnapshot:
    """Strictly decode only the canonical snapshot schema and exact identity."""
    expected_keys = {
        "schema_version",
        "command",
        "status",
        "readonly",
        "products",
        "trading_day",
        "source",
        "application_calls",
        "snapshot",
        "database_writes",
        "canonical_writes",
        "snapshot_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID")
    actual = payload.get("snapshot_sha256")
    unsigned = {
        key: value for key, value in payload.items() if key != "snapshot_sha256"
    }
    if (
        not isinstance(expected_snapshot_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_snapshot_sha256) is None
        or actual != expected_snapshot_sha256
        or actual != _hash(unsigned)
    ):
        raise CurrentDayMetadataRecoveryError("SNAPSHOT_HASH_INVALID")
    normalized = _products(products)
    _trading_day(trading_day)
    source = payload.get("source")
    normal_source = {
        "method": "RQDataMarketAdapter.fetch_current_day_metadata",
        "arguments": {"products": list(normalized), "trading_day": trading_day.isoformat()},
    }
    frozen_source = {
        "method": "frozen_rqdata_capture",
        "arguments": {"products": list(normalized), "trading_day": trading_day.isoformat()},
        "capture_sha256": source.get("capture_sha256") if isinstance(source, dict) else None,
    }
    valid_source = source == normal_source or (
        source == frozen_source
        and isinstance(frozen_source["capture_sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", frozen_source["capture_sha256"]) is not None
    )
    if (
        payload["schema_version"] != 1
        or payload["command"] != "data.current-day-metadata-recovery"
        or payload["status"] != "captured"
        or payload["readonly"] is not (source == frozen_source)
        or payload["products"] != list(normalized)
        or payload["trading_day"] != trading_day.isoformat()
        or not valid_source
        or payload["application_calls"] != application_call_summary(len(normalized))
        or payload["database_writes"] != 0
        or payload["canonical_writes"] != 0
        or not isinstance(payload["snapshot"], dict)
        or set(payload["snapshot"])
        != {
            "exchanges",
            "instruments",
            "contracts",
            "calendars",
            "sessions",
            "main_contracts",
            "main_contract_starts",
        }
    ):
        raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID")
    decoded = {key: _decode_value(value) for key, value in payload["snapshot"].items()}
    if not isinstance(decoded["main_contract_starts"], dict):
        raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID")
    try:
        snapshot = MetadataSnapshot(**decoded)
    except TypeError:
        raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID") from None
    return snapshot


def plan_current_day_metadata(
    catalog,
    snapshot_payload: dict[str, Any],
    *,
    expected_snapshot_sha256: str,
    products: tuple[str, ...],
    trading_day: date,
) -> dict[str, Any]:
    """Validate source and disclose every persistent fact as equal or insert."""
    session = catalog.session
    snapshot = decode_current_day_snapshot(
        snapshot_payload,
        expected_snapshot_sha256=expected_snapshot_sha256,
        products=products,
        trading_day=trading_day,
    )
    synchronizer = MetadataSynchronizer(_NoProvider(), catalog)
    try:
        prepared = synchronizer.prepare_current_day_snapshot(
            snapshot, products, trading_day
        )
        facts = _fact_diff(session, prepared)
    except CurrentDayMetadataRecoveryError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", None)
        reason = code if isinstance(code, str) else str(exc)
        if reason in {
            "CALENDAR_SOURCE_CONFLICT",
            "CURRENT_DAY_CALENDAR_INVALID",
            "CALENDAR_NIGHT_AUTHORITY_MISSING",
        }:
            raise CurrentDayMetadataRecoveryError("CALENDAR_CONFLICT") from None
        if reason in {
            "CURRENT_DAY_TRADING_SESSION_INVALID",
            "NEXT_TRADING_SESSION_NOT_READY",
        }:
            raise CurrentDayMetadataRecoveryError("SESSION_INVALID") from None
        if reason == "CURRENT_DAY_MAIN_CONTRACT_MAP_INVALID":
            raise CurrentDayMetadataRecoveryError("MAIN_CONTRACT_INVALID") from None
        raise CurrentDayMetadataRecoveryError("SNAPSHOT_INVALID") from None
    counts = {
        f"{kind}_{state}": sum(
            item["kind"] == kind and item["state"] == state for item in facts
        )
        for kind in ("calendar", "session", "main_contract")
        for state in ("equal", "insert")
    }
    payload = {
        "schema_version": 1,
        "command": "data.current-day-metadata-recovery",
        "status": "planned",
        "readonly": True,
        "products": list(_products(products)),
        "trading_day": trading_day.isoformat(),
        "snapshot_sha256": expected_snapshot_sha256,
        "facts": facts,
        "counts": counts,
        "provider_requests": 0,
        "database_writes": 0,
        "canonical_writes": 0,
    }
    return {**payload, "plan_sha256": _hash(payload)}


def apply_current_day_metadata(
    synchronizer: MetadataSynchronizer,
    snapshot_payload: dict[str, Any],
    *,
    expected_snapshot_sha256: str,
    expected_plan_sha256: str,
    products: tuple[str, ...],
    trading_day: date,
    acquire_maintenance_lock: Callable[[], Any],
    verify_identity: Callable[[], None],
) -> dict[str, Any]:
    """Acquire lease, recheck Runtime and exact plan, then commit without provider."""
    if re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha256 or "") is None:
        raise CurrentDayMetadataRecoveryError("PLAN_HASH_INVALID")
    lease = acquire_maintenance_lock()
    if lease is None:
        raise CurrentDayMetadataRecoveryError("MAINTENANCE_LOCKED")
    try:
        try:
            verify_identity()
        except (RuntimeRecoveryBindingError, CurrentDayMetadataRecoveryError):
            raise
        except Exception:
            raise CurrentDayMetadataRecoveryError("RUNTIME_IDENTITY_DRIFT") from None
        session = synchronizer.catalog.session
        session.expire_all()
        fresh = plan_current_day_metadata(
            synchronizer.catalog,
            snapshot_payload,
            expected_snapshot_sha256=expected_snapshot_sha256,
            products=products,
            trading_day=trading_day,
        )
        if fresh["plan_sha256"] != expected_plan_sha256:
            raise CurrentDayMetadataRecoveryError("PLAN_DRIFT")
        try:
            verify_identity()
        except (RuntimeRecoveryBindingError, CurrentDayMetadataRecoveryError):
            raise
        except Exception:
            raise CurrentDayMetadataRecoveryError("RUNTIME_IDENTITY_DRIFT") from None
        try:
            prepared = synchronizer.prepare_current_day_snapshot(
                decode_current_day_snapshot(
                    snapshot_payload,
                    expected_snapshot_sha256=expected_snapshot_sha256,
                    products=products,
                    trading_day=trading_day,
                ),
                products,
                trading_day,
            )
            synchronizer.write_prepared_current_day(prepared, preserve_equal=True)
        except Exception:
            session.rollback()
            raise CurrentDayMetadataRecoveryError("APPLY_FAILED") from None
        try:
            session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
            raise CurrentDayMetadataRecoveryError("COMMIT_OUTCOME_UNKNOWN") from None
        counts = fresh["counts"]
        return {
            "schema_version": 1,
            "command": "data.current-day-metadata-recovery",
            "status": "applied",
            "readonly": False,
            "trading_day": trading_day.isoformat(),
            "product_count": len(_products(products)),
            "snapshot_sha256": expected_snapshot_sha256,
            "plan_sha256": expected_plan_sha256,
            "calendar_writes": counts["calendar_insert"],
            "session_writes": counts["session_insert"],
            "main_contract_writes": counts["main_contract_insert"],
            "provider_requests": 0,
        }
    finally:
        lease.release()


def _fact_diff(session, prepared) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for source in prepared.calendars:
        values = {
            "exchange_code": source["exchange_code"],
            "trade_date": source["trade_date"].isoformat(),
            "is_trading_day": source["is_trading_day"],
            "has_night_session": source["has_night_session"],
            "provider": source.get("provider", "rqdata"),
        }
        row = session.scalar(
            select(TradingCalendar).where(
                TradingCalendar.exchange_code == source["exchange_code"],
                TradingCalendar.trade_date == source["trade_date"],
            )
        )
        if row is not None and any(
            getattr(row, key) != value
            for key, value in values.items()
            if key not in {"trade_date"}
        ):
            raise CurrentDayMetadataRecoveryError("CALENDAR_CONFLICT")
        facts.append(
            {"kind": "calendar", "state": "equal" if row else "insert", **values}
        )
    sessions_by_day: dict[tuple[str, date], list[dict[str, Any]]] = {}
    for source in prepared.sessions:
        key = (source["instrument_symbol"], source["effective_from"])
        sessions_by_day.setdefault(key, []).append(_source_session_values(source))
    for (symbol, day), expected_rows in sorted(sessions_by_day.items()):
        overlapping = tuple(
            session.scalars(
                select(TradingSession).where(
                    TradingSession.instrument_symbol == symbol,
                    TradingSession.effective_from <= day,
                    or_(
                        TradingSession.effective_to.is_(None),
                        TradingSession.effective_to >= day,
                    ),
                )
            )
        )
        expected_rows = sorted(expected_rows, key=_json)
        existing_rows = sorted((_session_values(row) for row in overlapping), key=_json)
        if existing_rows and existing_rows != expected_rows:
            raise CurrentDayMetadataRecoveryError("SESSION_CONFLICT")
        for expected in expected_rows:
            facts.append(
                {
                    "kind": "session",
                    "state": "equal" if existing_rows else "insert",
                    **expected,
                }
            )
    for symbol, row_day, contract in prepared.main_contracts:
        expected = {
            "symbol": symbol,
            "trade_date": row_day.isoformat(),
            "contract_code": contract,
            "rank": 1,
            "rule": "volume_open_interest",
        }
        row = session.scalar(
            select(MainContractMap).where(
                MainContractMap.symbol == symbol,
                MainContractMap.trade_date == row_day,
            )
        )
        if row is not None and any(
            getattr(row, key) != value
            for key, value in expected.items()
            if key != "trade_date"
        ):
            raise CurrentDayMetadataRecoveryError("MAIN_CONTRACT_CONFLICT")
        facts.append(
            {"kind": "main_contract", "state": "equal" if row else "insert", **expected}
        )
    return sorted(facts, key=_json)


def _session_values(row: TradingSession) -> dict[str, Any]:
    return {
        "exchange_code": row.exchange_code,
        "instrument_symbol": row.instrument_symbol,
        "session_name": row.session_name,
        "start_time": row.start_time.isoformat(),
        "end_time": row.end_time.isoformat(),
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "crosses_midnight": row.crosses_midnight,
        "is_active": row.is_active,
        "provider": row.provider,
    }


def _source_session_values(source: Mapping[str, Any]) -> dict[str, Any]:
    effective_to = source["effective_to"]
    return {
        "exchange_code": source["exchange_code"],
        "instrument_symbol": source["instrument_symbol"],
        "session_name": source["session_name"],
        "start_time": source["start_time"].isoformat(),
        "end_time": source["end_time"].isoformat(),
        "effective_from": source["effective_from"].isoformat(),
        "effective_to": effective_to.isoformat() if effective_to else None,
        "crosses_midnight": source["crosses_midnight"],
        "is_active": source["is_active"],
        "provider": source.get("provider", "rqdata"),
    }


def _products(products: tuple[str, ...]) -> tuple[str, ...]:
    if (
        not products
        or len(products) > 64
        or any(
            not isinstance(item, str) or not item or item != item.strip().lower()
            for item in products
        )
        or len(set(products)) != len(products)
    ):
        raise CurrentDayMetadataRecoveryError("SCOPE_INVALID")
    return products


def _trading_day(value: date) -> date:
    if type(value) is not date:
        raise CurrentDayMetadataRecoveryError("TRADING_DAY_INVALID")
    return value


class _NoProvider:
    def fetch_metadata(self, *_args, **_kwargs):
        raise AssertionError("provider is unavailable in plan/apply")

    def fetch_current_day_metadata(self, *_args, **_kwargs):
        raise AssertionError("provider is unavailable in plan/apply")
