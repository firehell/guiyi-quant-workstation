"""Rewrite inconclusive weekly turnover from one fresh exchange-daily snapshot.

For each frozen INCONCLUSIVE week, re-read those trading days, overlay turnover
onto stored D1 only when every other field matches, then set the stored W1
turnover to that corrected daily sum. A week whose prices, volume or open
interest differ is refused and nothing in the batch is written.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from app.market_data.domain import BarFrequency, CanonicalBar, DatasetKey, DatasetKind
from app.market_data.market_home_projection import (
    MarketHomeProjectionStore,
    market_home_projection_path,
)
from app.market_data.storage import PublishRequest
from scripts.newow_weekly_d1_then_w1_repair import (
    RepairError,
    _align_provider_bar_ends,
    _sha256_bytes,
    _sha256_file,
    _write_json,
    overlay_provider_turnover,
    realign_weekly_turnover,
)
from scripts.newow_weekly_conflict_source_verify import (
    SourceVerifyError,
    _provider_bars,
)
from scripts.newow_weekly_recovery import (
    RecoveryError,
    _current_code_commit,
    _open_execution_environment,
    _require_clean_execution_checkout,
    create_attempt_directory,
)


_PREPARE_SCHEMA = "newow_weekly_provider_turnover_realign_prepare_v1"
_RESULT_SCHEMA = "newow_weekly_provider_turnover_realign_result_v1"
_TARGET_COUNT = 19


def _money(value: Decimal | None) -> str:
    if value is None:
        raise RepairError("PROVIDER_TURNOVER_MISSING")
    return format(value, "f")


def _targets(decision: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    if decision.get("schema_version") != "newow_weekly_conflict_repair_side_decision_v1":
        raise RepairError("DECISION_SCHEMA_INVALID")
    weeks = decision.get("weeks")
    if not isinstance(weeks, list):
        raise RepairError("DECISION_WEEKS_INVALID")
    selected = [
        week for week in weeks
        if isinstance(week, dict)
        and week.get("classification") == "INCONCLUSIVE"
        and week.get("repair_target") == "NONE"
    ]
    if len(selected) != _TARGET_COUNT or len(selected) != len(weeks) - 2:
        raise RepairError("INCONCLUSIVE_TARGET_COUNT_INVALID")
    return tuple(selected)


def _partition(catalog, key: DatasetKey, year: int, month: int):
    found = next(
        (
            item for item in catalog.all_partitions(key)
            if item.year == year and item.month == month
        ),
        None,
    )
    if found is None:
        raise RepairError("PARTITION_MISSING")
    return found


def _plan_week(env, week: dict[str, Any]) -> dict[str, Any]:
    symbol = str(week["symbol"])
    contract = str(week["contract"])
    expected_days = tuple(date.fromisoformat(item) for item in week["daily_trading_days"])
    week_end = datetime.fromisoformat(str(week["week_end"]).replace("Z", "+00:00")).astimezone(UTC)
    d1_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.D1)
    w1_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.W1)
    d1_parts = []
    month_bars: dict[tuple[int, int], tuple[CanonicalBar, ...]] = {}
    for meta in week["d1_partitions"]:
        year, month = int(meta["year"]), int(meta["month"])
        part = _partition(env.manager.catalog, d1_key, year, month)
        if part.file_path.name != meta["file_name"]:
            raise RepairError("D1_PREIMAGE_MISMATCH")
        bars, quality = env.manager.store.read_catalog_partition_quality(part)
        if quality:
            raise RepairError("D1_SOURCE_QUALITY_PRESENT")
        d1_parts.append(part)
        month_bars[(year, month)] = bars
    w1_meta = week["stored_w1_partition"]
    w1_part = _partition(env.manager.catalog, w1_key, int(w1_meta["year"]), int(w1_meta["month"]))
    if w1_part.file_path.name != w1_meta["file_name"]:
        raise RepairError("W1_PREIMAGE_MISMATCH")
    w1_bars, w1_quality = env.manager.store.read_catalog_partition_quality(w1_part)
    if w1_quality:
        raise RepairError("W1_SOURCE_QUALITY_PRESENT")
    stored_weekly = next((bar for bar in w1_bars if bar.bar_end == week_end), None)
    if stored_weekly is None:
        raise RepairError("STORED_W1_BAR_MISSING")
    stored_week = tuple(
        bar
        for bars in month_bars.values()
        for bar in bars
        if bar.trading_day in set(expected_days)
    )
    stored_week = tuple(sorted(stored_week, key=lambda bar: bar.trading_day))
    if tuple(bar.trading_day for bar in stored_week) != expected_days:
        raise RepairError("STORED_WEEK_DATES_MISMATCH")
    try:
        rows = env.adapter._exchange_daily_rows(
            d1_key, expected_days, cache={},
        )
        provider = _align_provider_bar_ends(
            _provider_bars(rows, stored_week), stored_week,
        )
    except SourceVerifyError as exc:
        raise RepairError(exc.code) from exc
    corrected_months: dict[tuple[int, int], tuple[CanonicalBar, ...]] = {}
    changed_by_month: dict[tuple[int, int], tuple[date, ...]] = {}
    for key, bars in month_bars.items():
        month_provider = tuple(
            bar for bar in provider
            if (bar.trading_day.year, bar.trading_day.month) == key
        )
        if not month_provider:
            raise RepairError("PROVIDER_MONTH_EMPTY")
        try:
            corrected, changed = overlay_provider_turnover(bars, month_provider)
        except RepairError as exc:
            if exc.code != "NO_STALE_TURNOVER_DAY":
                raise
            corrected, changed = bars, ()
        corrected_months[key] = corrected
        changed_by_month[key] = changed
    corrected_week = tuple(
        bar
        for bars in corrected_months.values()
        for bar in bars
        if bar.trading_day in set(expected_days)
    )
    corrected_week = tuple(sorted(corrected_week, key=lambda bar: bar.trading_day))
    aligned = realign_weekly_turnover(stored_weekly, corrected_week)
    changed_days = tuple(
        day for days in changed_by_month.values() for day in days
    )
    if aligned.turnover == stored_weekly.turnover and not changed_days:
        status = "already_applied"
    else:
        status = "planned"
    return {
        "symbol": symbol,
        "contract": contract,
        "status": status,
        "iso_year": week["iso_year"],
        "iso_week": week["iso_week"],
        "week_end": week_end.isoformat(),
        "daily_trading_days": [day.isoformat() for day in expected_days],
        "changed_trading_days": [day.isoformat() for day in sorted(changed_days)],
        "d1_partitions": [
            {
                "year": part.year,
                "month": part.month,
                "preimage_file_name": part.file_path.name,
                "preimage_sha256": _sha256_file(part.file_path),
                "row_count": len(month_bars[(part.year, part.month)]),
                "corrected_turnovers": {
                    day.isoformat(): _money(next(
                        bar.turnover for bar in corrected_months[(part.year, part.month)]
                        if bar.trading_day == day
                    ))
                    for day in changed_by_month[(part.year, part.month)]
                },
            }
            for part in d1_parts
        ],
        "w1": {
            "year": w1_part.year,
            "month": w1_part.month,
            "preimage_file_name": w1_part.file_path.name,
            "preimage_sha256": _sha256_file(w1_part.file_path),
            "row_count": len(w1_bars),
            "turnover": _money(aligned.turnover),
            "rewritten": aligned.turnover != stored_weekly.turnover,
        },
    }


def prepare(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parents[1]
    code_commit = _current_code_commit(project_root)
    _require_clean_execution_checkout(code_commit, project_root=project_root)
    decision = json.loads(Path(args.decision).read_text(encoding="utf-8"))
    targets = _targets(decision)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    env = _open_execution_environment(Path(args.project_env))
    try:
        units = [_plan_week(env, week) for week in targets]
        planned = [unit for unit in units if unit["status"] == "planned"]
        if not planned:
            raise RepairError("NO_PLANNED_UNITS")
        prepared = {
            "schema_version": _PREPARE_SCHEMA,
            "code_commit": code_commit,
            "decision_sha256": _sha256_file(Path(args.decision)),
            "unit_count": len(units),
            "planned_count": len(planned),
            "units": units,
            "canonical_writes": "d1_turnover_overlay_and_w1_turnover",
            "readonly": True,
        }
        out = output_root / f"{args.name}.prepare.json"
        digest = _write_json(out, prepared)
        print(json.dumps({
            "status": "prepared",
            "prepared_file": str(out),
            "prepared_sha256": digest,
            "unit_count": len(units),
            "planned_count": len(planned),
            "writes": 0,
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        env.close()


def _publish(env, key: DatasetKey, year: int, month: int, bars: tuple[CanonicalBar, ...]):
    published = env.manager.store.publish(PublishRequest(
        dataset=key,
        year=year,
        month=month,
        bars=bars,
        expected_bar_ends=tuple(bar.bar_end for bar in bars),
    ))
    env.manager.catalog.register_partition(published)
    env.manager.catalog.session.commit()
    return published


def _with_prepared_turnovers(
    bars: tuple[CanonicalBar, ...],
    corrected_turnovers: dict[str, str],
) -> tuple[CanonicalBar, ...]:
    by_day = {bar.trading_day: bar for bar in bars}
    if len(by_day) != len(bars):
        raise RepairError("MONTH_BARS_DUPLICATE_DAY")
    for day_text, turnover_text in corrected_turnovers.items():
        day = date.fromisoformat(day_text)
        current = by_day.get(day)
        if current is None:
            raise RepairError("PREPARED_DAY_MISSING")
        by_day[day] = replace(current, turnover=Decimal(turnover_text))
    return tuple(sorted(by_day.values(), key=lambda bar: bar.bar_end))


def _prepared_turnovers_present(
    bars: tuple[CanonicalBar, ...],
    corrected_turnovers: dict[str, str],
) -> bool:
    by_day = {bar.trading_day: bar for bar in bars}
    for day_text, turnover_text in corrected_turnovers.items():
        current = by_day.get(date.fromisoformat(day_text))
        if current is None or current.turnover != Decimal(turnover_text):
            return False
    return True


def _preimage_matches(part, meta: dict[str, Any]) -> bool:
    return (
        part.file_path.name == meta["preimage_file_name"]
        and _sha256_file(part.file_path) == meta["preimage_sha256"]
    )


def _readback_turnovers(env, key: DatasetKey, year: int, month: int, expected: dict[str, str]) -> None:
    part = _partition(env.manager.catalog, key, year, month)
    bars, quality = env.manager.store.read_catalog_partition_quality(part)
    if quality:
        raise RepairError("POST_COMMIT_QUALITY_PRESENT")
    for day_text, turnover_text in expected.items():
        day = date.fromisoformat(day_text)
        got = next((bar for bar in bars if bar.trading_day == day), None)
        if got is None or got.turnover != Decimal(turnover_text):
            raise RepairError("POST_COMMIT_TURNOVER_MISMATCH")


def apply(args: argparse.Namespace) -> int:
    project_root = Path(__file__).resolve().parents[1]
    prepared_path = Path(args.prepared)
    prepared_bytes = prepared_path.read_bytes()
    if _sha256_bytes(prepared_bytes) != args.expected_prepared_sha256:
        raise RepairError("PREPARED_SHA256_MISMATCH")
    prepared = json.loads(prepared_bytes.decode("utf-8"))
    if prepared.get("schema_version") != _PREPARE_SCHEMA:
        raise RepairError("PREPARE_SCHEMA_INVALID")
    _require_clean_execution_checkout(prepared["code_commit"], project_root=project_root)
    if _current_code_commit(project_root) != prepared["code_commit"]:
        raise RecoveryError("EXECUTION_IDENTITY_CHANGED")
    if not args.apply:
        raise RepairError("APPLY_FLAG_REQUIRED")
    attempt_dir = create_attempt_directory(Path(args.output_root), args.attempt_id)
    env = _open_execution_environment(Path(args.project_env))
    lease = None
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
            if unit["status"] == "already_applied":
                applied.append({
                    "contract": unit["contract"],
                    "status": "already_applied",
                    "writes": 0,
                })
                continue
            symbol, contract = unit["symbol"], unit["contract"]
            d1_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.D1)
            w1_key = DatasetKey(DatasetKind.CONTRACT, symbol, contract, BarFrequency.W1)
            expected_days = {date.fromisoformat(item) for item in unit["daily_trading_days"]}
            corrected_week: list[CanonicalBar] = []
            d1_jobs: list[tuple[dict[str, Any], tuple[CanonicalBar, ...]]] = []
            for meta in unit["d1_partitions"]:
                part = _partition(env.manager.catalog, d1_key, meta["year"], meta["month"])
                bars, quality = env.manager.store.read_catalog_partition_quality(part)
                if quality or len(bars) != meta["row_count"]:
                    raise RepairError("D1_PARTITION_CHANGED")
                if _preimage_matches(part, meta):
                    corrected = _with_prepared_turnovers(bars, meta["corrected_turnovers"])
                    if meta["corrected_turnovers"]:
                        d1_jobs.append((meta, corrected))
                elif _prepared_turnovers_present(bars, meta["corrected_turnovers"]):
                    corrected = tuple(bars)
                else:
                    raise RepairError("D1_PREIMAGE_CHANGED")
                corrected_week.extend(
                    bar for bar in corrected if bar.trading_day in expected_days
                )
            if {bar.trading_day for bar in corrected_week} != expected_days:
                raise RepairError("STORED_WEEK_DATES_MISMATCH")
            w1_meta = unit["w1"]
            w1_part = _partition(env.manager.catalog, w1_key, w1_meta["year"], w1_meta["month"])
            w1_bars, w1_quality = env.manager.store.read_catalog_partition_quality(w1_part)
            if w1_quality or len(w1_bars) != w1_meta["row_count"]:
                raise RepairError("W1_PARTITION_CHANGED")
            week_end = datetime.fromisoformat(unit["week_end"]).astimezone(UTC)
            current_weekly = next((bar for bar in w1_bars if bar.bar_end == week_end), None)
            if current_weekly is None:
                raise RepairError("STORED_W1_BAR_MISSING")
            updated = realign_weekly_turnover(
                current_weekly,
                tuple(sorted(corrected_week, key=lambda item: item.trading_day)),
            )
            if _money(updated.turnover) != w1_meta["turnover"]:
                raise RepairError("W1_TURNOVER_DRIFT")
            w1_matches = current_weekly.turnover == updated.turnover
            if not w1_matches and not _preimage_matches(w1_part, w1_meta):
                raise RepairError("W1_PREIMAGE_CHANGED")
            rewritten = tuple(
                updated if bar.bar_end == week_end else bar for bar in w1_bars
            )
            for meta, corrected in d1_jobs:
                invalidate()
                _publish(env, d1_key, meta["year"], meta["month"], corrected)
                _readback_turnovers(
                    env, d1_key, meta["year"], meta["month"], meta["corrected_turnovers"],
                )
                writes += 1
            if w1_meta["rewritten"] and not w1_matches:
                invalidate()
                _publish(env, w1_key, w1_meta["year"], w1_meta["month"], rewritten)
                _readback_turnovers(
                    env,
                    w1_key,
                    w1_meta["year"],
                    w1_meta["month"],
                    {updated.trading_day.isoformat(): w1_meta["turnover"]},
                )
                writes += 1
            applied.append({
                "contract": contract,
                "status": "passed",
                "changed_trading_days": unit["changed_trading_days"],
                "w1_turnover": w1_meta["turnover"],
            })
        result = {
            "schema_version": _RESULT_SCHEMA,
            "status": "passed",
            "attempt_id": args.attempt_id,
            "prepared_sha256": args.expected_prepared_sha256,
            "applied": applied,
            "canonical_writes": writes,
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
        if lease is not None:
            lease.release()
        env.close()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(allow_abbrev=False)
    commands = value.add_subparsers(dest="command", required=True)
    prepare_cmd = commands.add_parser("prepare", allow_abbrev=False)
    prepare_cmd.add_argument("--project-env", required=True)
    prepare_cmd.add_argument("--decision", required=True)
    prepare_cmd.add_argument("--output-root", required=True)
    prepare_cmd.add_argument("--name", required=True)
    apply_cmd = commands.add_parser("apply", allow_abbrev=False)
    apply_cmd.add_argument("--project-env", required=True)
    apply_cmd.add_argument("--prepared", required=True)
    apply_cmd.add_argument("--expected-prepared-sha256", required=True)
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
    except (RepairError, RecoveryError) as exc:
        code = getattr(exc, "code", None) or str(exc)
        print(json.dumps({"status": "failed", "code": code}, ensure_ascii=False))
        return 1
    raise RepairError("COMMAND_INVALID")


if __name__ == "__main__":
    raise SystemExit(main())
