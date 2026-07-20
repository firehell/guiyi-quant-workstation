from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PRODUCT = "jm"
CONTINUOUS_CONTRACT = "jm.MAIN"
CONTINUOUS_DIRECT_PERIODS = ("1m", "1d", "1w")
CONTINUOUS_DERIVED_PERIODS = ("5m", "15m", "30m", "60m", "1d")
ACTUAL_DIRECT_PERIODS = ("1m", "1d")
ACTUAL_DERIVED_PERIODS = ("5m", "15m", "30m", "60m")
DIRECT_LOOKBACK_DAYS = {"1m": 2, "1d": 5, "1w": 14}


class CatchupBlockedError(RuntimeError):
    """Raised when a JM catch-up precondition cannot be proven."""


class ApprovalPacketDriftError(CatchupBlockedError):
    """Raised when current facts no longer match a bound approval packet."""


@dataclass(frozen=True)
class TradingDayState:
    day: date
    is_trading_day: bool
    final_close_at: datetime | None


@dataclass(frozen=True)
class CatchupItem:
    product: str
    contract: str
    period: str
    source_role: str
    start: date
    end: date
    mapping_start: date | None = None
    mapping_end: date | None = None


@dataclass(frozen=True)
class CatchupPlan:
    product: str
    target: date
    weekly_target: date
    status: str
    items: tuple[CatchupItem, ...]


def resolve_latest_completed_trading_day(
    *,
    calendar: Sequence[TradingDayState],
    now: datetime,
    provider_final_days: set[date] | frozenset[date],
) -> date:
    rows = sorted(calendar, key=lambda item: item.day)
    if not rows or rows[-1].day < now.date():
        raise CatchupBlockedError("trading_calendar_stale")

    closed: list[date] = []
    for row in rows:
        if not row.is_trading_day or row.day > now.date():
            continue
        if row.final_close_at is None:
            if row.day in provider_final_days:
                raise CatchupBlockedError(f"trading_session_close_missing:{row.day.isoformat()}")
            continue
        if row.final_close_at < now:
            closed.append(row.day)

    eligible = sorted(set(closed).intersection(provider_final_days))
    if not eligible:
        raise CatchupBlockedError("provider_final_trading_day_missing")
    return eligible[-1]


def latest_completed_week_end(calendar: Sequence[TradingDayState], *, target: date) -> date:
    rows = {item.day: item for item in calendar if item.day <= target + timedelta(days=2)}
    target_monday = target - timedelta(days=target.weekday())
    target_sunday = target_monday + timedelta(days=6)
    target_week_complete = all(target_monday + timedelta(days=offset) in rows for offset in range(7))

    if target_week_complete:
        trading = [item.day for item in rows.values() if item.is_trading_day and target_monday <= item.day <= min(target, target_sunday)]
        if trading:
            return max(trading)

    previous_monday = target_monday - timedelta(days=7)
    previous_sunday = target_monday - timedelta(days=1)
    previous = [item.day for item in rows.values() if item.is_trading_day and previous_monday <= item.day <= previous_sunday]
    if previous:
        return max(previous)
    raise CatchupBlockedError("completed_trading_week_missing")


def build_gap_plan(
    *,
    product: str,
    trading_days: Sequence[date],
    target: date,
    weekly_target: date,
    active_ends: Mapping[tuple[str, str, str], date],
    rank1_mapping: Mapping[date, str],
) -> CatchupPlan:
    normalized_product = str(product).strip().lower()
    if normalized_product != PRODUCT:
        raise CatchupBlockedError("jm_only")

    days = sorted(set(day for day in trading_days if day <= target))
    if target not in days:
        raise CatchupBlockedError(f"target_not_trading_day:{target.isoformat()}")
    for day in days:
        if day not in rank1_mapping:
            raise CatchupBlockedError(f"rank1_mapping_missing:{day.isoformat()}")

    items: list[CatchupItem] = []
    for period in CONTINUOUS_DIRECT_PERIODS:
        item_target = weekly_target if period == "1w" else target
        _append_gap(
            items,
            product=normalized_product,
            contract=CONTINUOUS_CONTRACT,
            period=period,
            source_role="direct",
            days=days,
            active_end=active_ends.get((CONTINUOUS_CONTRACT, period, "direct")),
            target=item_target,
        )
    for period in CONTINUOUS_DERIVED_PERIODS:
        _append_gap(
            items,
            product=normalized_product,
            contract=CONTINUOUS_CONTRACT,
            period=period,
            source_role="derived_from_1m",
            days=days,
            active_end=active_ends.get((CONTINUOUS_CONTRACT, period, "derived_from_1m")),
            target=target,
        )

    for contract, segment_start, segment_end in _mapping_segments(days, rank1_mapping):
        for period in ACTUAL_DIRECT_PERIODS:
            _append_gap(
                items,
                product=normalized_product,
                contract=contract,
                period=period,
                source_role="direct",
                days=days,
                active_end=active_ends.get((contract, period, "direct")),
                target=segment_end,
                floor=segment_start,
                mapping_start=segment_start,
                mapping_end=segment_end,
            )
        for period in ACTUAL_DERIVED_PERIODS:
            _append_gap(
                items,
                product=normalized_product,
                contract=contract,
                period=period,
                source_role="derived_from_1m",
                days=days,
                active_end=active_ends.get((contract, period, "derived_from_1m")),
                target=segment_end,
                floor=segment_start,
                mapping_start=segment_start,
                mapping_end=segment_end,
            )

    ordered = tuple(sorted(items, key=lambda item: (item.contract, item.period, item.source_role, item.start)))
    return CatchupPlan(
        product=normalized_product,
        target=target,
        weekly_target=weekly_target,
        status="up_to_date" if not ordered else "catchup_required",
        items=ordered,
    )


def _append_gap(
    items: list[CatchupItem],
    *,
    product: str,
    contract: str,
    period: str,
    source_role: str,
    days: Sequence[date],
    active_end: date | None,
    target: date,
    floor: date | None = None,
    mapping_start: date | None = None,
    mapping_end: date | None = None,
) -> None:
    eligible = [day for day in days if day <= target and (floor is None or day >= floor)]
    if active_end is not None:
        eligible = [day for day in eligible if day > active_end]
    if not eligible:
        return
    items.append(
        CatchupItem(
            product=product,
            contract=contract,
            period=period,
            source_role=source_role,
            start=eligible[0],
            end=eligible[-1],
            mapping_start=mapping_start,
            mapping_end=mapping_end,
        )
    )


def _mapping_segments(days: Sequence[date], mapping: Mapping[date, str]) -> tuple[tuple[str, date, date], ...]:
    segments: list[tuple[str, date, date]] = []
    contract = ""
    start: date | None = None
    previous: date | None = None
    for day in days:
        current = str(mapping[day]).strip().upper()
        if not current or current.endswith(".MAIN"):
            raise CatchupBlockedError(f"rank1_mapping_not_actual:{day.isoformat()}")
        if current != contract:
            if contract and start is not None and previous is not None:
                segments.append((contract, start, previous))
            contract = current
            start = day
        previous = day
    if contract and start is not None and previous is not None:
        segments.append((contract, start, previous))
    return tuple(segments)


def build_approval_packet(
    *,
    git_commit: str,
    git_branch: str,
    git_status_sha256: str,
    output_root: Path,
    output_root_identity: Mapping[str, Any],
    database_target: str,
    database_identity: Mapping[str, Any],
    binding_snapshot_sha256: str,
    metadata_snapshot_sha256: str,
    target: date,
    request_plan: Mapping[str, Any],
    expected_outputs: Iterable[Path],
    expected_versions: Sequence[str],
    expected_database_rows: Mapping[str, int],
    rollback_plan: Mapping[str, Any],
) -> dict[str, Any]:
    outputs = sorted(str(Path(path).resolve(strict=False)) for path in expected_outputs)
    bound_facts = {
        "git_commit": git_commit,
        "git_branch": git_branch,
        "git_status_sha256": git_status_sha256,
        "output_root": str(output_root.resolve(strict=False)),
        "output_root_identity": dict(output_root_identity),
        "database_target": database_target,
        "database_identity": dict(database_identity),
        "binding_snapshot_sha256": binding_snapshot_sha256,
        "metadata_snapshot_sha256": metadata_snapshot_sha256,
        "latest_completed_trading_day": target.isoformat(),
        "rqdata_request_plan": dict(request_plan),
        "expected_outputs": outputs,
        "expected_versions": sorted(str(item) for item in expected_versions),
        "expected_database_rows": {key: int(value) for key, value in sorted(expected_database_rows.items())},
        "rollback_plan": dict(rollback_plan),
    }
    packet: dict[str, Any] = {
        "schema_version": 1,
        "task_id": "JM-HISTORICAL-CATCHUP-S6-03",
        "status": "approval_required",
        "product": PRODUCT,
        "writes_authorized": False,
        "bound_facts": bound_facts,
        "invalidation_rule": "any bound fact drift invalidates this packet",
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def build_rqdata_request_plan(
    plan: CatchupPlan,
    *,
    calendar_start: date,
    calendar_end: date,
) -> dict[str, Any]:
    if plan.product != PRODUCT:
        raise CatchupBlockedError("jm_only")
    direct_items = [item for item in plan.items if item.source_role == "direct"]
    bar_requests: list[dict[str, Any]] = []
    seen: set[tuple[str, str, date, date]] = set()
    for item in direct_items:
        lookback = DIRECT_LOOKBACK_DAYS[item.period]
        request_start = item.start - timedelta(days=lookback)
        if item.mapping_start is not None:
            request_start = max(request_start, item.mapping_start)
        identity = (item.contract, item.period, request_start, item.end)
        if identity in seen:
            continue
        seen.add(identity)
        bar_requests.append(
            {
                "product": PRODUCT,
                "contract": item.contract,
                "period": item.period,
                "source_role": "direct",
                "start": request_start.isoformat(),
                "end": item.end.isoformat(),
            }
        )

    actual_contracts = sorted({item.contract for item in plan.items if item.contract != CONTINUOUS_CONTRACT})
    parameter_ranges = []
    for contract in actual_contracts:
        rows = [item for item in plan.items if item.contract == contract]
        parameter_ranges.append(
            {
                "contract": contract,
                "start": min(item.start for item in rows).isoformat(),
                "end": max(item.end for item in rows).isoformat(),
            }
        )
    return {
        "product": PRODUCT,
        "reference": {
            "calendar": [calendar_start.isoformat(), calendar_end.isoformat()],
            "sessions": [PRODUCT],
            "rank1_mapping": [(plan.target - timedelta(days=21)).isoformat(), plan.target.isoformat()],
            "trading_parameters": parameter_ranges,
        },
        "bars": sorted(bar_requests, key=lambda row: (row["contract"], row["period"], row["start"])),
        "derived_periods_are_local_only": True,
    }


def build_artifact_plan(plan: CatchupPlan, *, output_root: Path, batch_id: str) -> dict[str, Any]:
    if plan.product != PRODUCT:
        raise CatchupBlockedError("jm_only")
    normalized_batch = _safe_slug(batch_id)
    root = output_root.resolve(strict=False)
    rows: list[dict[str, Any]] = []
    for item in plan.items:
        contract_slug = _safe_slug(item.contract)
        role_slug = _safe_slug(item.source_role)
        version = (
            f"{normalized_batch}_{PRODUCT}_{contract_slug}_{item.period}_{role_slug}_"
            f"{item.start:%Y%m%d}_{item.end:%Y%m%d}_v1"
        )
        filename = f"{contract_slug}_{item.period}_{item.start:%Y%m%d}_{item.end:%Y%m%d}_{role_slug}_{normalized_batch}.parquet"
        canonical_path = (
            root
            / "parquet"
            / "canonical"
            / "bars"
            / "provider=rqdata"
            / f"period={item.period}"
            / "exchange=DCE"
            / "symbol=jm"
            / f"contract={item.contract}"
            / f"batch={normalized_batch}"
            / filename
        )
        raw_path = None
        if item.source_role == "direct":
            raw_path = (
                root
                / "raw"
                / "rqdata"
                / "jm_historical_catchup"
                / f"batch={normalized_batch}"
                / f"contract={item.contract}"
                / f"period={item.period}"
                / filename
            )
        rows.append(
            {
                **asdict(item),
                "start": item.start.isoformat(),
                "end": item.end.isoformat(),
                "mapping_start": item.mapping_start.isoformat() if item.mapping_start else None,
                "mapping_end": item.mapping_end.isoformat() if item.mapping_end else None,
                "data_version": version,
                "raw_path": str(raw_path) if raw_path else None,
                "canonical_path": str(canonical_path),
                "write_mode": "create_only",
            }
        )
    return {
        "batch_id": normalized_batch,
        "product": PRODUCT,
        "target": plan.target.isoformat(),
        "bars": rows,
        "manifest_path": str(root / "manifests" / f"jm_historical_catchup_{normalized_batch}.csv"),
        "audit_root": str(root / "reports" / "jm_historical_catchup_s6_03" / normalized_batch),
    }


def build_profile_binding_plan(artifacts: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = list(artifacts.get("bars") or [])
    eligible: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["contract"]), str(row["period"]), str(row["source_role"]))
        current = eligible.get(key)
        if current is None or str(row["end"]) > str(current["end"]):
            eligible[key] = row

    rules = {
        "intraday_research_v1": {
            (CONTINUOUS_CONTRACT, "1m", "direct"),
            *((CONTINUOUS_CONTRACT, period, "derived_from_1m") for period in CONTINUOUS_DERIVED_PERIODS),
            *(("actual", period, role) for period, role in (("1m", "direct"), ("5m", "derived_from_1m"), ("15m", "derived_from_1m"))),
        },
        "live_observation_v1": {
            (CONTINUOUS_CONTRACT, "1m", "direct"),
            (CONTINUOUS_CONTRACT, "5m", "derived_from_1m"),
            (CONTINUOUS_CONTRACT, "15m", "derived_from_1m"),
            *(("actual", period, role) for period, role in (("1m", "direct"), ("5m", "derived_from_1m"), ("15m", "derived_from_1m"))),
        },
        "long_horizon_daily_v1": {
            (CONTINUOUS_CONTRACT, "1d", "direct"),
            (CONTINUOUS_CONTRACT, "1w", "direct"),
            ("actual", "1d", "direct"),
        },
    }
    result: list[dict[str, Any]] = []
    for profile_id, profile_rules in rules.items():
        for (contract, period, role), row in eligible.items():
            rule_contract = CONTINUOUS_CONTRACT if contract == CONTINUOUS_CONTRACT else "actual"
            if (rule_contract, period, role) not in profile_rules:
                continue
            result.append(
                {
                    "profile_id": profile_id,
                    "product": PRODUCT,
                    "contract": contract,
                    "contract_role": "dominant_main" if contract == CONTINUOUS_CONTRACT else "actual_contract",
                    "period": period,
                    "source_role": role,
                    "data_version": row["data_version"],
                    "canonical_path": row["canonical_path"],
                    "required_quality_status": "passed",
                    "apply_mode": "compare_and_switch",
                }
            )
    return sorted(result, key=lambda row: (row["profile_id"], row["contract"], row["period"]))


def build_s6_03_approval_packet(
    *,
    plan: CatchupPlan,
    batch_id: str,
    git_commit: str,
    git_branch: str,
    git_status_sha256: str,
    output_root: Path,
    output_root_identity: Mapping[str, Any],
    database_target: str,
    database_identity: Mapping[str, Any],
    binding_snapshot_sha256: str,
    metadata_snapshot_sha256: str,
    calendar_start: date,
    calendar_end: date,
) -> dict[str, Any]:
    request_plan = build_rqdata_request_plan(
        plan,
        calendar_start=calendar_start,
        calendar_end=calendar_end,
    )
    artifacts = build_artifact_plan(plan, output_root=output_root, batch_id=batch_id)
    binding_candidates = build_profile_binding_plan(artifacts)
    expected_outputs: list[Path] = []
    for row in artifacts["bars"]:
        expected_outputs.append(Path(row["canonical_path"]))
        if row["raw_path"]:
            expected_outputs.append(Path(row["raw_path"]))
    expected_outputs.extend(
        (
            Path(artifacts["manifest_path"]),
            Path(artifacts["audit_root"]) / "quality_gate.json",
            Path(artifacts["audit_root"]) / "final_audit.json",
        )
    )
    return build_approval_packet(
        git_commit=git_commit,
        git_branch=git_branch,
        git_status_sha256=git_status_sha256,
        output_root=output_root,
        output_root_identity=output_root_identity,
        database_target=database_target,
        database_identity=database_identity,
        binding_snapshot_sha256=binding_snapshot_sha256,
        metadata_snapshot_sha256=metadata_snapshot_sha256,
        target=plan.target,
        request_plan=request_plan,
        expected_outputs=expected_outputs,
        expected_versions=[str(row["data_version"]) for row in artifacts["bars"]],
        expected_database_rows={
            "data_download_tasks": 1,
            "market_data_files": len(artifacts["bars"]),
            "data_quality_reports": len(artifacts["bars"]),
            "profile_binding_candidates": len(binding_candidates),
        },
        rollback_plan={
            "existing_assets": "immutable",
            "active_binding": "restore_bound_snapshot_before_removing_candidate_rows",
            "new_files": "remove_only_paths_listed_in_expected_outputs_after_checksum_identity_check",
            "new_database_rows": "delete_only_rows_bound_to_batch_id_after_binding_restore",
            "failure_before_binding": "leave_previous_active_binding_unchanged",
        },
    )


def canonical_packet_hash(packet: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in packet.items() if key != "packet_hash"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_approval_packet(packet: Mapping[str, Any], *, current_facts: Mapping[str, Any]) -> None:
    expected_hash = str(packet.get("packet_hash") or "")
    if not expected_hash or canonical_packet_hash(packet) != expected_hash:
        raise ApprovalPacketDriftError("packet_hash")
    bound = packet.get("bound_facts")
    if not isinstance(bound, Mapping):
        raise ApprovalPacketDriftError("bound_facts")
    for key, expected in bound.items():
        if current_facts.get(key) != expected:
            raise ApprovalPacketDriftError(key)


def validate_create_only_outputs(paths: Iterable[Path]) -> None:
    collisions = sorted(str(Path(path)) for path in paths if Path(path).exists())
    if collisions:
        raise CatchupBlockedError(f"output_already_exists:{','.join(collisions)}")


def binding_quality_eligible(status: str) -> bool:
    return str(status).strip().lower() == "passed"


def plan_payload(plan: CatchupPlan) -> dict[str, Any]:
    return {
        "product": plan.product,
        "target": plan.target.isoformat(),
        "weekly_target": plan.weekly_target.isoformat(),
        "status": plan.status,
        "items": [asdict(item) for item in plan.items],
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported packet value: {type(value).__name__}")


def _safe_slug(value: str) -> str:
    slug = "".join(character if character.isalnum() else "_" for character in str(value).strip())
    slug = "_".join(part for part in slug.split("_") if part)
    if not slug:
        raise CatchupBlockedError("empty_path_token")
    return slug


__all__ = [
    "ApprovalPacketDriftError",
    "CatchupBlockedError",
    "CatchupItem",
    "CatchupPlan",
    "TradingDayState",
    "binding_quality_eligible",
    "build_approval_packet",
    "build_artifact_plan",
    "build_gap_plan",
    "build_profile_binding_plan",
    "build_rqdata_request_plan",
    "build_s6_03_approval_packet",
    "canonical_packet_hash",
    "latest_completed_week_end",
    "plan_payload",
    "resolve_latest_completed_trading_day",
    "validate_create_only_outputs",
    "verify_approval_packet",
]
