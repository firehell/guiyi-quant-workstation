"""Exact D1_THEN_W1 repair for judged stale-D1 weekly turnover conflicts.

Only overlays verified exchange-daily turnover onto already-stored D1 month
partitions when non-turnover fields match. Does not invent scopes, rewrite W1
from a stale D1 aggregate, or touch INCONCLUSIVE weeks.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.market_home_projection import (
    MarketHomeProjectionStore,
    market_home_projection_path,
)
from app.market_data.rqdata_adapter import _aggregate_daily_rows, _canonical_bar, _row_date
from app.market_data.storage import PublishRequest
from scripts.newow_weekly_conflict_diagnosis import FIELDS
from scripts.newow_weekly_recovery import (
    RecoveryError,
    _current_code_commit,
    _open_execution_environment,
    _require_clean_execution_checkout,
    create_attempt_directory,
)


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_NON_TURNOVER = ("open", "high", "low", "close", "volume", "open_interest")
_PREPARE_SCHEMA = "newow_weekly_d1_then_w1_prepare_v1"
_RESULT_SCHEMA = "newow_weekly_d1_then_w1_result_v1"


class RepairError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def overlay_provider_turnover(
    month_bars: tuple[CanonicalBar, ...],
    provider_week_bars: tuple[CanonicalBar, ...],
) -> tuple[tuple[CanonicalBar, ...], tuple[date, ...]]:
    """Replace matching days' turnover only; keep the rest of the month intact."""
    if not month_bars or not provider_week_bars:
        raise RepairError("REPAIR_BARS_EMPTY")
    by_day = {bar.trading_day: bar for bar in month_bars}
    if len(by_day) != len(month_bars):
        raise RepairError("MONTH_BARS_DUPLICATE_DAY")
    provider_days = tuple(bar.trading_day for bar in provider_week_bars)
    if len(set(provider_days)) != len(provider_days):
        raise RepairError("PROVIDER_WEEK_DUPLICATE_DAY")
    changed: list[date] = []
    for provider in provider_week_bars:
        stored = by_day.get(provider.trading_day)
        if stored is None:
            raise RepairError("PROVIDER_DAY_MISSING_FROM_MONTH")
        if stored.bar_end != provider.bar_end:
            raise RepairError("BAR_END_MISMATCH")
        for field in _NON_TURNOVER:
            if getattr(stored, field) != getattr(provider, field):
                raise RepairError("BEYOND_TURNOVER_ASSUMPTION")
        if stored.turnover == provider.turnover:
            continue
        if provider.turnover is None:
            raise RepairError("PROVIDER_TURNOVER_MISSING")
        by_day[provider.trading_day] = replace(stored, turnover=provider.turnover)
        changed.append(provider.trading_day)
    if not changed:
        raise RepairError("NO_STALE_TURNOVER_DAY")
    corrected = tuple(sorted(by_day.values(), key=lambda bar: bar.bar_end))
    return corrected, tuple(changed)


def require_w1_matches_corrected_week(
    stored_weekly: CanonicalBar,
    corrected_week_bars: tuple[CanonicalBar, ...],
) -> None:
    """After D1 overlay, the existing W1 bar must already equal the new week sum."""
    if not corrected_week_bars:
        raise RepairError("CORRECTED_WEEK_EMPTY")
    aggregate = _aggregate_daily_rows(
        tuple(
            (bar.trading_day, {field: getattr(bar, field) for field in FIELDS})
            for bar in corrected_week_bars
        ),
        bar_end=stored_weekly.bar_end,
    )
    for field in _NON_TURNOVER:
        if getattr(aggregate, field) != getattr(stored_weekly, field):
            raise RepairError("W1_NON_TURNOVER_MISMATCH_AFTER_D1")
    if aggregate.turnover != stored_weekly.turnover:
        raise RepairError("W1_TURNOVER_MISMATCH_AFTER_D1")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RepairError("JSON_OBJECT_REQUIRED")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return _sha256_bytes(text.encode("utf-8"))


def _provider_bars_from_response(
    response: Mapping[str, Any],
    *,
    expected_days: tuple[date, ...],
) -> tuple[CanonicalBar, ...]:
    rows = response.get("rows")
    if not isinstance(rows, list) or not rows:
        raise RepairError("SOURCE_RESPONSE_ROWS_INVALID")
    bars: list[CanonicalBar] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise RepairError("SOURCE_RESPONSE_ROW_INVALID")
        trading_day = _row_date(raw)
        # Reuse stored bar_end from expected day alignment during overlay; here we
        # only need trading-day keyed provider facts. bar_end is filled later.
        bars.append(_canonical_bar(raw, datetime(trading_day.year, trading_day.month, trading_day.day, 7, tzinfo=UTC), trading_day))
    observed = tuple(bar.trading_day for bar in bars)
    if observed != expected_days:
        raise RepairError("SOURCE_RESPONSE_DATES_MISMATCH")
    return tuple(bars)


def _align_provider_bar_ends(
    provider_bars: tuple[CanonicalBar, ...],
    month_bars: tuple[CanonicalBar, ...],
) -> tuple[CanonicalBar, ...]:
    by_day = {bar.trading_day: bar for bar in month_bars}
    aligned: list[CanonicalBar] = []
    for provider in provider_bars:
        stored = by_day.get(provider.trading_day)
        if stored is None:
            raise RepairError("PROVIDER_DAY_MISSING_FROM_MONTH")
        aligned.append(replace(provider, bar_end=stored.bar_end))
    return tuple(aligned)


def _frozen_targets(decision: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    weeks = decision.get("weeks")
    if not isinstance(weeks, list):
        raise RepairError("DECISION_WEEKS_INVALID")
    targets: list[dict[str, Any]] = []
    for week in weeks:
        if not isinstance(week, dict) or week.get("repair_target") != "D1_THEN_W1":
            continue
        targets.append(week)
    if len(targets) != 2:
        raise RepairError("D1_THEN_W1_TARGET_COUNT_INVALID")
    return tuple(targets)


def prepare(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parents[1]
    code_commit = _current_code_commit(project_root)
    _require_clean_execution_checkout(code_commit, project_root=project_root)
    decision = _read_json(Path(args.decision))
    if decision.get("schema_version") != "newow_weekly_conflict_repair_side_decision_v1":
        raise RepairError("DECISION_SCHEMA_INVALID")
    targets = _frozen_targets(decision)
    attempt_root = Path(args.source_attempt)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    env = _open_execution_environment(Path(args.project_env))
    try:
        units: list[dict[str, Any]] = []
        for week in targets:
            contract = str(week["contract"])
            symbol = str(week["symbol"])
            expected_days = tuple(date.fromisoformat(item) for item in week["daily_trading_days"])
            response_name = None
            response_path = None
            for path in sorted(attempt_root.glob("source-response-*.json")):
                if _sha256_file(path) == week["source_response_sha256"]:
                    response_name = path.name
                    response_path = path
                    break
            if response_path is None:
                raise RepairError("SOURCE_RESPONSE_MISSING")
            response = _read_json(response_path)
            provider_raw = _provider_bars_from_response(response, expected_days=expected_days)
            d1_meta = week["d1_partitions"][0]
            year = int(d1_meta["year"])
            month = int(d1_meta["month"])
            d1_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.D1)
            w1_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.W1)
            d1_part = next(
                (
                    item for item in env.manager.catalog.all_partitions(d1_key)
                    if item.year == year and item.month == month
                ),
                None,
            )
            if d1_part is None:
                raise RepairError("D1_PARTITION_MISSING")
            month_bars, quality = env.manager.store.read_catalog_partition_quality(d1_part)
            if quality:
                raise RepairError("D1_SOURCE_QUALITY_PRESENT")
            provider = _align_provider_bar_ends(provider_raw, month_bars)
            try:
                corrected, changed = overlay_provider_turnover(month_bars, provider)
                unit_status = "planned"
            except RepairError as exc:
                if exc.code != "NO_STALE_TURNOVER_DAY":
                    raise
                corrected = month_bars
                changed = ()
                unit_status = "already_applied"
            if (
                unit_status == "planned"
                and d1_part.file_path.name != d1_meta["file_name"]
            ):
                raise RepairError("D1_PREIMAGE_MISMATCH")
            week_end = datetime.fromisoformat(str(week["week_end"]).replace("Z", "+00:00")).astimezone(UTC)
            w1_part = next(
                (
                    item for item in env.manager.catalog.all_partitions(w1_key)
                    if item.year == int(week["stored_w1_partition"]["year"])
                    and item.month == int(week["stored_w1_partition"]["month"])
                ),
                None,
            )
            if w1_part is None:
                raise RepairError("W1_PARTITION_MISSING")
            if (
                unit_status == "planned"
                and w1_part.file_path.name != week["stored_w1_partition"]["file_name"]
            ):
                raise RepairError("W1_PREIMAGE_MISMATCH")
            w1_bars, w1_quality = env.manager.store.read_catalog_partition_quality(w1_part)
            if w1_quality:
                raise RepairError("W1_SOURCE_QUALITY_PRESENT")
            stored_weekly = next(bar for bar in w1_bars if bar.bar_end == week_end)
            corrected_week = tuple(
                bar for bar in corrected if bar.trading_day in set(expected_days)
            )
            require_w1_matches_corrected_week(stored_weekly, corrected_week)
            units.append({
                "symbol": symbol,
                "contract": contract,
                "status": unit_status,
                "iso_year": week["iso_year"],
                "iso_week": week["iso_week"],
                "week_end": week_end.isoformat(),
                "daily_trading_days": [day.isoformat() for day in expected_days],
                "changed_trading_days": [day.isoformat() for day in changed],
                "source_response": response_name,
                "source_response_sha256": week["source_response_sha256"],
                "request_sha256": week["request_sha256"],
                "d1": {
                    "year": year,
                    "month": month,
                    "preimage_file_name": d1_part.file_path.name,
                    "preimage_sha256": _sha256_file(d1_part.file_path),
                    "row_count": len(month_bars),
                    "corrected_turnovers": {
                        day.isoformat(): format(
                            next(bar for bar in corrected if bar.trading_day == day).turnover,
                            "f",
                        )
                        for day in changed
                    },
                },
                "w1": {
                    "year": w1_part.year,
                    "month": w1_part.month,
                    "preimage_file_name": w1_part.file_path.name,
                    "preimage_sha256": _sha256_file(w1_part.file_path),
                    "action": "noop_after_d1",
                    "turnover": format(stored_weekly.turnover, "f"),
                },
            })
        if not any(unit["status"] == "planned" for unit in units):
            raise RepairError("NO_PLANNED_UNITS")
        if any(unit["status"] not in {"planned", "already_applied"} for unit in units):
            raise RepairError("UNIT_STATUS_INVALID")
        prepared = {
            "schema_version": _PREPARE_SCHEMA,
            "code_commit": code_commit,
            "decision_sha256": _sha256_file(Path(args.decision)),
            "source_attempt_id": decision.get("attempt_id"),
            "plan_sha256": decision.get("plan_sha256"),
            "catalog_revision": decision.get("catalog_revision"),
            "unit_count": len(units),
            "units": units,
            "canonical_writes": "d1_month_overlay",
            "catalog_writes": "register_partition",
            "w1_writes": 0,
            "readonly": True,
        }
        out = output_root / f"{args.name}.prepare.json"
        digest = _write_json(out, prepared)
        print(json.dumps({
            "status": "prepared",
            "prepared_file": str(out),
            "prepared_sha256": digest,
            "unit_count": len(units),
            "writes": 0,
            "readonly": True,
            "schema_version": _RESULT_SCHEMA,
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        env.close()


def apply(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parents[1]
    prepared_path = Path(args.prepared)
    prepared_bytes = prepared_path.read_bytes()
    if _sha256_bytes(prepared_bytes) != args.expected_prepared_sha256:
        raise RepairError("PREPARED_SHA256_MISMATCH")
    prepared = json.loads(prepared_bytes.decode("utf-8"))
    if prepared.get("schema_version") != _PREPARE_SCHEMA:
        raise RepairError("PREPARE_SCHEMA_INVALID")
    expected_commit = prepared["code_commit"]
    _require_clean_execution_checkout(expected_commit, project_root=project_root)
    if _current_code_commit(project_root) != expected_commit:
        raise RecoveryError("EXECUTION_IDENTITY_CHANGED")

    attempt_dir = create_attempt_directory(Path(args.output_root), args.attempt_id)
    env = _open_execution_environment(Path(args.project_env))
    try:
        lease = env.manager.catalog.acquire_maintenance_lock()
        if lease is None:
            raise RepairError("MAINTENANCE_LOCKED")
        invalidate = MarketHomeProjectionStore(
            market_home_projection_path(env.manager.catalog.canonical_root)
        ).invalidate
        applied: list[dict[str, Any]] = []
        writes = 0
        for unit in prepared["units"]:
            symbol = unit["symbol"]
            contract = unit["contract"]
            year = unit["d1"]["year"]
            month = unit["d1"]["month"]
            d1_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.D1)
            w1_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.W1)
            d1_part = next(
                item for item in env.manager.catalog.all_partitions(d1_key)
                if item.year == year and item.month == month
            )
            if (
                d1_part.file_path.name != unit["d1"]["preimage_file_name"]
                or _sha256_file(d1_part.file_path) != unit["d1"]["preimage_sha256"]
            ):
                raise RepairError("D1_PREIMAGE_CHANGED")
            month_bars, quality = env.manager.store.read_catalog_partition_quality(d1_part)
            if quality:
                raise RepairError("D1_SOURCE_QUALITY_PRESENT")
            response = _read_json(Path(args.source_attempt) / unit["source_response"])
            if _sha256_file(Path(args.source_attempt) / unit["source_response"]) != unit["source_response_sha256"]:
                raise RepairError("SOURCE_RESPONSE_CHANGED")
            expected_days = tuple(date.fromisoformat(item) for item in unit["daily_trading_days"])
            provider = _align_provider_bar_ends(
                _provider_bars_from_response(response, expected_days=expected_days),
                month_bars,
            )
            week_end = datetime.fromisoformat(unit["week_end"]).astimezone(UTC)
            w1_part = next(
                item for item in env.manager.catalog.all_partitions(w1_key)
                if item.year == unit["w1"]["year"] and item.month == unit["w1"]["month"]
            )
            if (
                w1_part.file_path.name != unit["w1"]["preimage_file_name"]
                or _sha256_file(w1_part.file_path) != unit["w1"]["preimage_sha256"]
            ):
                raise RepairError("W1_PREIMAGE_CHANGED")
            w1_bars, _ = env.manager.store.read_catalog_partition_quality(w1_part)
            stored_weekly = next(bar for bar in w1_bars if bar.bar_end == week_end)
            if unit.get("status") == "already_applied":
                require_w1_matches_corrected_week(
                    stored_weekly,
                    tuple(bar for bar in month_bars if bar.trading_day in set(expected_days)),
                )
                applied.append({
                    "contract": contract,
                    "d1_file": d1_part.file_path.name,
                    "d1_sha256": _sha256_file(d1_part.file_path),
                    "changed_trading_days": [],
                    "w1_action": "noop",
                    "status": "already_applied",
                })
                continue
            corrected, changed = overlay_provider_turnover(month_bars, provider)
            if tuple(day.isoformat() for day in changed) != tuple(unit["changed_trading_days"]):
                raise RepairError("CHANGED_DAYS_DRIFT")
            corrected_week = tuple(
                bar for bar in corrected if bar.trading_day in set(expected_days)
            )
            require_w1_matches_corrected_week(stored_weekly, corrected_week)
            if not args.apply:
                raise RepairError("APPLY_FLAG_REQUIRED")
            invalidate()
            expected_ends = tuple(bar.bar_end for bar in corrected)
            published = env.manager.store.publish(PublishRequest(
                dataset=d1_key,
                year=year,
                month=month,
                bars=corrected,
                expected_bar_ends=expected_ends,
            ))
            env.manager.catalog.register_partition(published)
            env.manager.catalog.session.commit()
            writes += 1
            refreshed = next(
                item for item in env.manager.catalog.all_partitions(d1_key)
                if item.year == year and item.month == month
            )
            read_bars, read_quality = env.manager.store.read_catalog_partition_quality(refreshed)
            if read_quality or len(read_bars) != len(corrected):
                raise RepairError("POST_COMMIT_D1_READBACK_INVALID")
            for day in changed:
                got = next(bar for bar in read_bars if bar.trading_day == day)
                expected_turnover = Decimal(unit["d1"]["corrected_turnovers"][day.isoformat()])
                if got.turnover != expected_turnover:
                    raise RepairError("POST_COMMIT_TURNOVER_MISMATCH")
            w1_again = next(
                bar for bar in env.manager.store.read_catalog_partition_quality(w1_part)[0]
                if bar.bar_end == week_end
            )
            require_w1_matches_corrected_week(
                w1_again,
                tuple(bar for bar in read_bars if bar.trading_day in set(expected_days)),
            )
            applied.append({
                "contract": contract,
                "d1_file": published.parquet_path.name,
                "d1_sha256": _sha256_file(published.parquet_path),
                "changed_trading_days": unit["changed_trading_days"],
                "w1_action": "noop",
                "status": "passed",
            })
        result = {
            "schema_version": _RESULT_SCHEMA,
            "status": "passed",
            "attempt_id": args.attempt_id,
            "prepared_sha256": args.expected_prepared_sha256,
            "applied": applied,
            "failed": None,
            "canonical_writes": writes,
            "catalog_writes": writes,
            "w1_writes": 0,
        }
        _write_json(attempt_dir / "batch-result.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        try:
            env.manager.catalog.session.rollback()
        except Exception:
            pass
        raise
    finally:
        env.close()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(allow_abbrev=False)
    commands = value.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare", allow_abbrev=False)
    prepare_cmd.add_argument("--project-env", required=True)
    prepare_cmd.add_argument("--decision", required=True)
    prepare_cmd.add_argument("--source-attempt", required=True)
    prepare_cmd.add_argument("--output-root", required=True)
    prepare_cmd.add_argument("--name", required=True)
    apply_cmd = commands.add_parser("apply", allow_abbrev=False)
    apply_cmd.add_argument("--project-env", required=True)
    apply_cmd.add_argument("--prepared", required=True)
    apply_cmd.add_argument("--expected-prepared-sha256", required=True)
    apply_cmd.add_argument("--source-attempt", required=True)
    apply_cmd.add_argument("--output-root", required=True)
    apply_cmd.add_argument("--attempt-id", required=True)
    apply_cmd.add_argument("--apply", action="store_true", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare":
            return prepare(args)
        if args.command == "apply":
            return apply(args)
        raise RepairError("COMMAND_INVALID")
    except (RepairError, RecoveryError) as exc:
        code = getattr(exc, "code", str(exc))
        print(json.dumps({"status": "failed", "error": code}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
