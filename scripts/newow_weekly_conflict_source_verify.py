"""Read-only exchange-daily source verification for frozen W1 turnover conflicts."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.composition import build_market_data_service
from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.newow.after_market_consumer_audit import catalog_revision
from app.market_data.rqdata_adapter import (
    ExchangeDailySourceRequest,
    RQDataMarketAdapter,
    _aggregate_daily_rows,
    _canonical_bar,
    _row_date,
)
from scripts.newow_weekly_conflict_diagnosis import FIELDS
from scripts.newow_weekly_conflict_source_plan import _canonical_json, _sha256
from scripts.newow_weekly_recovery import (
    AttemptJournal,
    RecoveryError,
    create_attempt_directory,
    read_attempt_outcome,
)


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_NON_TURNOVER = ("open", "high", "low", "close", "volume", "open_interest")
_PLAN_SCHEMA = "newow_weekly_conflict_source_plan_v1"


class SourceVerifyError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_source_dates(
    expected: tuple[date, ...], observed: tuple[date, ...],
) -> None:
    """Require the frozen week dates exactly; extra or missing days stop the queue."""
    if len(observed) != len(set(observed)):
        raise SourceVerifyError("SOURCE_RESPONSE_DUPLICATE_DAY")
    expected_set = set(expected)
    observed_set = set(observed)
    if observed_set - expected_set:
        raise SourceVerifyError("SOURCE_RESPONSE_EXTRA_DATES")
    if expected_set - observed_set:
        raise SourceVerifyError("SOURCE_RESPONSE_MISSING_DATES")


def classify_conflict_week(
    *,
    provider_daily: tuple[CanonicalBar, ...],
    stored_daily: tuple[CanonicalBar, ...],
    stored_weekly: CanonicalBar,
) -> dict[str, object]:
    """Compare provider daily, stored D1 and stored W1 without choosing a write."""
    if tuple(bar.trading_day for bar in provider_daily) != tuple(
        bar.trading_day for bar in stored_daily
    ) or not provider_daily:
        return {
            "classification": "INCONCLUSIVE",
            "repair_target": "NONE",
            "stop_queue": True,
            "reason": "DAILY_DATE_MISMATCH",
        }
    for provider, stored in zip(provider_daily, stored_daily, strict=True):
        for field in _NON_TURNOVER:
            if getattr(provider, field) != getattr(stored, field):
                return {
                    "classification": "INCONCLUSIVE",
                    "repair_target": "NONE",
                    "stop_queue": True,
                    "reason": "BEYOND_TURNOVER_ASSUMPTION",
                }
    aggregate = _aggregate_daily_rows(
        tuple(
            (bar.trading_day, {field: getattr(bar, field) for field in FIELDS})
            for bar in provider_daily
        ),
        bar_end=stored_weekly.bar_end,
    )
    for field in _NON_TURNOVER:
        if getattr(aggregate, field) != getattr(stored_weekly, field):
            return {
                "classification": "INCONCLUSIVE",
                "repair_target": "NONE",
                "stop_queue": True,
                "reason": "BEYOND_TURNOVER_ASSUMPTION",
            }
    provider_matches_d1 = all(
        provider.turnover == stored.turnover
        for provider, stored in zip(provider_daily, stored_daily, strict=True)
    )
    provider_matches_w1 = aggregate.turnover == stored_weekly.turnover
    if provider_matches_d1 and not provider_matches_w1:
        return {
            "classification": "PROVIDER_MATCHES_D1_NOT_W1",
            "repair_target": "W1_PARTITION",
            "stop_queue": False,
            "reason": "STORED_W1_TURNOVER_STALE",
        }
    if not provider_matches_d1 and provider_matches_w1:
        return {
            "classification": "PROVIDER_MATCHES_NEITHER_D1_STALE",
            "repair_target": "D1_THEN_W1",
            "stop_queue": False,
            "reason": "STORED_D1_TURNOVER_STALE",
        }
    return {
        "classification": "INCONCLUSIVE",
        "repair_target": "NONE",
        "stop_queue": False,
        "reason": "PROVIDER_MATCHES_NEITHER",
    }


def load_plan(path: Path, expected_sha256: str) -> dict[str, Any]:
    plan = json.loads(path.read_text())
    body = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if (
        plan.get("schema_version") != _PLAN_SCHEMA
        or plan.get("plan_sha256") != expected_sha256
        or _sha256(body) != expected_sha256
        or plan.get("canonical_writes_allowed") is not False
        or plan.get("database_writes_allowed") is not False
        or plan.get("retry_allowed") is not False
        or plan.get("method") != "futures.get_exchange_daily"
        or not isinstance(plan.get("requests"), list)
        or plan.get("request_count") != len(plan["requests"])
    ):
        raise SourceVerifyError("SOURCE_PLAN_INVALID")
    return plan


def _source_request(item: Mapping[str, Any]) -> ExchangeDailySourceRequest:
    days = tuple(date.fromisoformat(value) for value in item["expected_dates"])
    return ExchangeDailySourceRequest(
        contract=str(item["contract"]),
        start=date.fromisoformat(str(item["start"])),
        end=date.fromisoformat(str(item["end"])),
        expected_dates=days,
    )


def _stored_week(
    market: Any, item: Mapping[str, Any], cutoff: datetime,
) -> tuple[tuple[CanonicalBar, ...], CanonicalBar]:
    symbol = str(item["symbol"])
    contract = str(item["contract"])
    through = date.fromisoformat(str(item["trading_day"]))
    week_end = datetime.fromisoformat(str(item["week_end"]))
    daily_expected = market.expected_contract_replay_endpoints(
        symbol=symbol, contract=contract, frequency=BarFrequency.D1,
        trading_day=through, cutoff=cutoff,
    )
    daily_bars, daily_gaps = market.query_contract_replay_quality_union(
        symbol=symbol, contract=contract, through=through, cutoff=week_end,
    )
    week = through.isocalendar()[:2]
    expected = tuple(point for point in daily_expected if point[1].isocalendar()[:2] == week)
    bars = tuple(bar for bar in daily_bars if bar.trading_day.isocalendar()[:2] == week)
    gaps = tuple(gap for gap in daily_gaps if gap.trading_day.isocalendar()[:2] == week)
    if gaps or tuple((bar.bar_end, bar.trading_day) for bar in bars) != expected:
        raise SourceVerifyError("STORED_D1_WEEK_INCOMPLETE")
    weekly_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.W1)
    stored_weekly = None
    for partition in market.catalog.all_partitions(weekly_key):
        for bar in market.store.read_catalog_partition(partition):
            if bar.bar_end == week_end:
                stored_weekly = bar
                break
    if stored_weekly is None:
        raise SourceVerifyError("STORED_W1_BAR_MISSING")
    return bars, stored_weekly


def _provider_bars(
    rows: Mapping[date, dict[str, Any]],
    stored_daily: tuple[CanonicalBar, ...],
) -> tuple[CanonicalBar, ...]:
    bars: list[CanonicalBar] = []
    for stored in stored_daily:
        row = rows.get(stored.trading_day)
        if row is None:
            raise SourceVerifyError("SOURCE_RESPONSE_MISSING_DATES")
        bars.append(_canonical_bar(row, stored.bar_end, stored.trading_day))
    return tuple(bars)


class _StrictObserver:
    def __init__(self, journal: AttemptJournal) -> None:
        self.journal = journal
        self.last_response: tuple[dict[str, Any], ...] = ()

    def before_request(self, request: ExchangeDailySourceRequest) -> None:
        self.journal.before_request(request)

    def after_response(
        self,
        request: ExchangeDailySourceRequest,
        response: tuple[dict[str, Any], ...],
    ) -> None:
        self.journal.after_response(request, response)
        self.last_response = response
        observed = tuple(_row_date(row) for row in response)
        validate_source_dates(request.expected_dates, observed)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(allow_abbrev=False)
    commands = value.add_subparsers(dest="mode", required=True)
    for name in ("preflight", "execute"):
        command = commands.add_parser(name, allow_abbrev=False)
        command.add_argument("--plan", required=True)
        command.add_argument("--expected-plan-sha256", required=True)
        command.add_argument("--output", required=True)
        if name == "execute":
            command.add_argument("--output-root", required=True)
            command.add_argument("--attempt-id", required=True)
            command.add_argument("--execute-source-query", action="store_true", required=True)
    return value


def _preflight(plan: Mapping[str, Any]) -> dict[str, object]:
    cutoff = datetime.fromisoformat(str(plan["as_of"])).astimezone(UTC)
    products = tuple(sorted({str(item["symbol"]) for item in plan["requests"]}))
    with SessionLocal() as session, readonly_transaction(session, timeout_seconds=300):
        revision = catalog_revision(session, products, cutoff.date(), ("1d", "1w"))
        if revision != plan["catalog_revision"]:
            raise SourceVerifyError("CATALOG_REVISION_CHANGED")
        lease = build_market_data_service(session).catalog.acquire_maintenance_lock()
        available = lease is not None
        if lease is not None:
            lease.release()
        if not available:
            raise SourceVerifyError("MAINTENANCE_LOCK_UNAVAILABLE")
    return {
        "schema_version": "newow_weekly_conflict_source_verify_preflight_v1",
        "status": "source_query_preflight_passed",
        "readonly": True,
        "maintenance_lock_available": True,
        "provider_requests": 0,
        "writes": 0,
        "plan_sha256": plan["plan_sha256"],
        "catalog_revision": revision,
        "request_count": plan["request_count"],
    }


def _execute(args: argparse.Namespace, plan: Mapping[str, Any]) -> dict[str, object]:
    if _ATTEMPT_ID.fullmatch(args.attempt_id) is None:
        raise SourceVerifyError("ATTEMPT_ID_INVALID")
    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)
    attempt = create_attempt_directory(root, args.attempt_id)
    requests = tuple(_source_request(item) for item in plan["requests"])
    observer = _StrictObserver(AttemptJournal(attempt, requests))
    cutoff = datetime.fromisoformat(str(plan["as_of"])).astimezone(UTC)
    products = tuple(sorted({str(item["symbol"]) for item in plan["requests"]}))
    results: list[dict[str, object]] = []
    stop_reason: str | None = None
    with SessionLocal() as session:
        lease = None
        try:
            lease = build_market_data_service(session).catalog.acquire_maintenance_lock()
            if lease is None:
                raise SourceVerifyError("MAINTENANCE_LOCK_UNAVAILABLE")
            with readonly_transaction(session, timeout_seconds=600):
                revision = catalog_revision(session, products, cutoff.date(), ("1d", "1w"))
                if revision != plan["catalog_revision"]:
                    raise SourceVerifyError("CATALOG_REVISION_CHANGED")
                market = build_market_data_service(session)
                adapter = RQDataMarketAdapter(session=session, source_observer=observer)
                for item, request in zip(plan["requests"], requests, strict=True):
                    stored_daily, stored_weekly = _stored_week(market, item, cutoff)
                    key = DatasetKey(
                        DatasetKind.CONTRACT, str(item["symbol"]),
                        str(item["contract"]), BarFrequency.D1,
                    )
                    try:
                        rows = adapter._exchange_daily_rows(
                            key, request.expected_dates, cache={},
                        )
                        provider_daily = _provider_bars(rows, stored_daily)
                        classified = classify_conflict_week(
                            provider_daily=provider_daily,
                            stored_daily=stored_daily,
                            stored_weekly=stored_weekly,
                        )
                    except SourceVerifyError as exc:
                        classified = {
                            "classification": "INCONCLUSIVE",
                            "repair_target": "NONE",
                            "stop_queue": True,
                            "reason": exc.code,
                        }
                    except RecoveryError as exc:
                        classified = {
                            "classification": "INCONCLUSIVE",
                            "repair_target": "NONE",
                            "stop_queue": True,
                            "reason": str(exc),
                        }
                    except Exception:
                        classified = {
                            "classification": "INCONCLUSIVE",
                            "repair_target": "NONE",
                            "stop_queue": True,
                            "reason": "SOURCE_QUERY_FAILED",
                        }
                    results.append({
                        "symbol": item["symbol"],
                        "contract": item["contract"],
                        "week_end": item["week_end"],
                        "iso_year": item["iso_year"],
                        "iso_week": item["iso_week"],
                        "request_sha256": item["request_sha256"],
                        "stored_w1_partition": item["stored_w1_partition"],
                        "d1_partitions": item["d1_partitions"],
                        **classified,
                    })
                    if classified["stop_queue"]:
                        stop_reason = str(classified["reason"])
                        break
        finally:
            if lease is not None:
                lease.release()
    outcome = read_attempt_outcome(attempt)
    payload = {
        "schema_version": "newow_weekly_conflict_source_verify_result_v1",
        "status": "completed" if stop_reason is None else "stopped",
        "stop_reason": stop_reason,
        "plan_sha256": plan["plan_sha256"],
        "catalog_revision": plan["catalog_revision"],
        "code_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True,
            cwd=Path(__file__).resolve().parents[1],
        ).strip(),
        "attempt_id": args.attempt_id,
        "provider_request_limit": plan["request_count"],
        "retries": 0,
        "canonical_writes": 0,
        "database_writes": 0,
        "attempt": {
            "responses_saved": outcome.get("responses_saved"),
            "outcome_unknown": outcome.get("outcome_unknown"),
        },
        "weeks": results,
        "classification_counts": {
            name: sum(item["classification"] == name for item in results)
            for name in sorted({str(item["classification"]) for item in results})
        },
        "repair_target_counts": {
            name: sum(item["repair_target"] == name for item in results)
            for name in sorted({str(item["repair_target"]) for item in results})
        },
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if _HASH.fullmatch(args.expected_plan_sha256) is None:
        raise SourceVerifyError("SOURCE_PLAN_HASH_INVALID")
    plan = load_plan(Path(args.plan), args.expected_plan_sha256)
    if args.mode == "preflight":
        payload = _preflight(plan)
        code = 0
    else:
        payload = _execute(args, plan)
        code = 0 if payload["status"] == "completed" else 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        key: payload[key]
        for key in payload
        if key in {
            "status", "stop_reason", "plan_sha256", "request_count",
            "classification_counts", "repair_target_counts",
            "provider_requests", "writes", "canonical_writes", "database_writes",
            "maintenance_lock_available", "catalog_revision",
        }
    }, sort_keys=True))
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        code = exc.code if isinstance(exc, SourceVerifyError) else type(exc).__name__
        print(json.dumps({"status": "failed", "error_code": code}))
        raise SystemExit(1)
