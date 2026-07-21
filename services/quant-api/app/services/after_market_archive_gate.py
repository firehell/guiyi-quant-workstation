from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import time
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import (
    DataDownloadTask,
    DataQualityReport,
    LiveMinuteBar,
    MarketDataFile,
    ProfileActiveBinding,
    utc_now,
)
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.profile_lineage import ProfileLineageResolver
from app.services.provider_readiness import wait_for_provider_readiness
from app.services.rqdata_ingest.bar_sample import normalize_bar_frame
from app.services.rqdata_ingest.jm_historical_catchup import (
    CatchupItem,
    CatchupPlan,
    build_artifact_plan,
    build_profile_binding_plan,
    canonical_packet_hash,
)
from app.services.rqdata_ingest.jm_historical_catchup_execution import (
    active_baseline_start,
    apply_profile_binding_candidates,
    apply_reference_snapshot,
    collect_active_binding_snapshot,
    collect_provider_reference_snapshot,
    materialize_execution_assets,
    register_execution_assets,
    stable_bar_frame_hash,
    validate_execution_paths_create_only,
)
from app.services.rqdata_ingest.parquet import sha256_file
from app.services.trading_session_clock import TradingSessionClock


TASK_ID = "JM-AFTER-MARKET-ARCHIVE-S6-06"
PERIODS = ("1m", "5m", "15m", "30m", "60m", "1d")
PACKET_SCHEMA_VERSION = 2


class ArchiveGateError(RuntimeError):
    """Raised when a JM archive approval or execution contract fails."""


def build_archive_plan(
    *,
    output_root: Path,
    batch_id: str,
    trading_day: date,
    actual_contract: str,
    baseline_start: date,
    expected_source_rows: int,
    provider_final_1m_hash: str,
    include_week: bool,
) -> dict[str, Any]:
    actual = actual_contract.strip().upper()
    if not actual.startswith("JM") or actual.endswith(".MAIN"):
        raise ArchiveGateError("jm_actual_contract_required")
    derived = ["5m", "15m", "30m", "60m", "1d"]
    if include_week:
        derived.append("1w")
    items = [
        CatchupItem(
            product="jm",
            contract=actual,
            period="1m",
            source_role="direct",
            start=baseline_start,
            end=trading_day,
            mapping_start=trading_day,
            mapping_end=trading_day,
        ),
        *[
            CatchupItem(
                product="jm",
                contract=actual,
                period=period,
                source_role="derived_from_1m",
                start=baseline_start,
                end=trading_day,
                mapping_start=trading_day,
                mapping_end=trading_day,
            )
            for period in derived
        ],
    ]
    artifact = build_artifact_plan(
        CatchupPlan(
            product="jm",
            target=trading_day,
            weekly_target=trading_day,
            status="archive_required",
            items=tuple(items),
        ),
        output_root=output_root,
        batch_id=batch_id,
    )
    root = output_root.resolve(strict=False)
    artifact["task_id"] = TASK_ID
    artifact["expected_source_rows"] = int(expected_source_rows)
    artifact["provider_final_1m_hash"] = provider_final_1m_hash
    artifact["include_completed_week"] = include_week
    artifact["manifest_path"] = str(root / "manifests" / f"jm_after_market_archive_{batch_id}.csv")
    artifact["audit_root"] = str(root / "reports" / "jm_after_market_archive_s6_06" / batch_id)
    reference_root = root / "raw" / "rqdata" / "jm_historical_catchup" / f"batch={batch_id}" / "reference"
    artifact["reference_paths"] = [
        str(reference_root / name)
        for name in ("calendar.parquet", "rank1_mapping.parquet", "trading_parameters.parquet")
    ]
    for row in artifact["bars"]:
        row["output_start"] = row["start"]
        role = "d" if row["source_role"] == "direct" else "d1m"
        row["data_version"] = f"{batch_id}_{actual}_{row['period']}_{role}_v1"
        if row["source_role"] == "direct":
            row["request_start"] = trading_day.isoformat()
    _validate_versions(artifact)
    return artifact


def build_approval_packet(
    *,
    bound_facts: Mapping[str, Any],
    execution_plan: Mapping[str, Any],
    reference_snapshot: Mapping[str, Any],
    binding_snapshot: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    execution_contract = validate_execution_contract(execution_plan, output_root=output_root)
    packet: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "status": "approval_required",
        "product": "jm",
        "writes_authorized": False,
        "bound_facts": dict(bound_facts),
        "execution_plan": dict(execution_plan),
        "execution_contract": execution_contract,
        "reference_snapshot": dict(reference_snapshot),
        "binding_snapshot": dict(binding_snapshot),
        "rollback": {
            "active_binding": "compare-and-switch in one DB transaction",
            "existing_assets": "immutable",
            "new_files": "remove packet-listed create-only files after rollback",
            "live_rows": "comparison evidence only and never copied into historical",
        },
        "invalidation_rule": "any bound fact drift invalidates this packet",
    }
    validate_approval_packet(packet, output_root=output_root)
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def validate_execution_contract(
    execution_plan: Mapping[str, Any],
    *,
    output_root: Path,
) -> dict[str, Any]:
    plan = dict(execution_plan)
    if plan.get("product") != "jm":
        raise ArchiveGateError("execution_contract_jm_only")
    try:
        target = date.fromisoformat(str(plan["target"]))
        batch_id = str(plan["batch_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ArchiveGateError("execution_contract_header_invalid") from exc
    if not batch_id.startswith(f"s606_{target:%Y%m%d}_"):
        raise ArchiveGateError("execution_contract_batch_mismatch")
    if plan.get("task_id") != TASK_ID:
        raise ArchiveGateError("execution_contract_task_id_mismatch")
    if int(plan.get("expected_source_rows") or 0) <= 0:
        raise ArchiveGateError("execution_contract_expected_source_rows_invalid")
    provider_hash = str(plan.get("provider_final_1m_hash") or "")
    if len(provider_hash) != 64 or any(character not in "0123456789abcdef" for character in provider_hash.lower()):
        raise ArchiveGateError("execution_contract_provider_hash_invalid")

    bars = list(plan.get("bars") or [])
    include_week = bool(plan.get("include_completed_week"))
    expected_periods = {*PERIODS, *({"1w"} if include_week else set())}
    required_fields = (
        "product",
        "contract",
        "period",
        "source_role",
        "start",
        "output_start",
        "end",
        "mapping_start",
        "mapping_end",
        "data_version",
        "canonical_path",
        "write_mode",
    )
    if not bars:
        raise ArchiveGateError("execution_contract_bars_missing")
    for row in bars:
        for field in required_fields:
            if row.get(field) in (None, ""):
                raise ArchiveGateError(f"execution_contract_bar_field_missing:{field}")

    actual_contracts = {str(row["contract"]).strip().upper() for row in bars}
    if len(actual_contracts) != 1:
        raise ArchiveGateError("execution_contract_actual_contract_not_unique")
    actual = next(iter(actual_contracts))
    if not actual.startswith("JM") or actual.endswith(".MAIN"):
        raise ArchiveGateError("execution_contract_actual_contract_invalid")

    asset_keys: set[tuple[str, str, str]] = set()
    versions: set[str] = set()
    output_starts: set[str] = set()
    paths: list[Path] = []
    for row in bars:
        period = str(row["period"])
        role = str(row["source_role"])
        key = (actual, period, role)
        expected_role = "direct" if period == "1m" else "derived_from_1m"
        if row["product"] != "jm" or role != expected_role:
            raise ArchiveGateError(f"execution_contract_asset_role_invalid:{period}")
        if key in asset_keys:
            raise ArchiveGateError(f"execution_contract_asset_duplicate:{period}:{role}")
        asset_keys.add(key)
        version = str(row["data_version"])
        if version in versions:
            raise ArchiveGateError(f"execution_contract_data_version_duplicate:{version}")
        if len(version) > 64:
            raise ArchiveGateError("data_version_too_long")
        versions.add(version)
        if str(row["start"]) != str(row["output_start"]):
            raise ArchiveGateError(f"execution_contract_output_start_mismatch:{period}")
        output_starts.add(str(row["output_start"]))
        if str(row["end"]) != target.isoformat():
            raise ArchiveGateError(f"execution_contract_end_mismatch:{period}")
        if str(row["mapping_start"]) != target.isoformat() or str(row["mapping_end"]) != target.isoformat():
            raise ArchiveGateError(f"execution_contract_mapping_mismatch:{period}")
        if row["write_mode"] != "create_only":
            raise ArchiveGateError(f"execution_contract_write_mode_invalid:{period}")
        raw_path = row.get("raw_path")
        if period == "1m":
            if str(row.get("request_start") or "") != target.isoformat() or not raw_path:
                raise ArchiveGateError("execution_contract_direct_request_invalid")
        elif row.get("request_start") is not None or raw_path is not None:
            raise ArchiveGateError(f"execution_contract_derived_source_invalid:{period}")
        paths.append(Path(str(row["canonical_path"])))
        if raw_path:
            paths.append(Path(str(raw_path)))

    actual_periods = {period for _, period, _ in asset_keys}
    if actual_periods != expected_periods or len(asset_keys) != len(expected_periods):
        raise ArchiveGateError("execution_contract_asset_set_mismatch")
    if len(output_starts) != 1:
        raise ArchiveGateError("execution_contract_output_start_not_uniform")
    if date.fromisoformat(next(iter(output_starts))) > target:
        raise ArchiveGateError("execution_contract_output_start_after_target")

    reference_paths = [Path(str(value)) for value in plan.get("reference_paths") or []]
    if len(reference_paths) != 3:
        raise ArchiveGateError("execution_contract_reference_path_set_mismatch")
    if {path.stem for path in reference_paths} != {"calendar", "rank1_mapping", "trading_parameters"}:
        raise ArchiveGateError("execution_contract_reference_path_identity_mismatch")
    if not plan.get("manifest_path") or not plan.get("audit_root"):
        raise ArchiveGateError("execution_contract_output_path_missing")
    try:
        manifest_path = Path(str(plan["manifest_path"]))
        audit_root = Path(str(plan["audit_root"]))
    except KeyError as exc:
        raise ArchiveGateError("execution_contract_output_path_missing") from exc
    paths.extend([*reference_paths, manifest_path, audit_root])
    resolved_root = output_root.resolve(strict=False)
    resolved_paths = [path.resolve(strict=False) for path in paths]
    if any(not path.is_relative_to(resolved_root) for path in resolved_paths):
        raise ArchiveGateError("execution_contract_path_outside_output_root")
    if len(resolved_paths) != len(set(resolved_paths)):
        raise ArchiveGateError("execution_contract_output_path_duplicate")
    if any(batch_id not in str(path) for path in resolved_paths):
        raise ArchiveGateError("execution_contract_output_path_batch_mismatch")

    profile_candidates = build_profile_binding_plan(plan)
    asset_versions = {str(row["data_version"]) for row in bars}
    if any(str(row["data_version"]) not in asset_versions for row in profile_candidates):
        raise ArchiveGateError("execution_contract_profile_candidate_outside_assets")
    asset_identities = sorted(
        (
            {
                "contract": actual,
                "period": str(row["period"]),
                "source_role": str(row["source_role"]),
                "data_version": str(row["data_version"]),
            }
            for row in bars
        ),
        key=lambda row: (row["contract"], row["period"], row["source_role"], row["data_version"]),
    )
    candidate_identities = sorted(
        (
            {
                "profile_id": str(row["profile_id"]),
                "contract": str(row["contract"]),
                "period": str(row["period"]),
                "data_version": str(row["data_version"]),
            }
            for row in profile_candidates
        ),
        key=lambda row: (row["profile_id"], row["contract"], row["period"], row["data_version"]),
    )
    if len(candidate_identities) != len({tuple(row.values()) for row in candidate_identities}):
        raise ArchiveGateError("execution_contract_profile_candidate_duplicate")
    return {
        "status": "passed",
        "schema_version": PACKET_SCHEMA_VERSION,
        "product": "jm",
        "target": target.isoformat(),
        "actual_contract": actual,
        "include_completed_week": include_week,
        "output_root": str(resolved_root),
        "asset_count": len(asset_identities),
        "asset_identities": asset_identities,
        "profile_candidate_count": len(candidate_identities),
        "profile_candidate_identities": candidate_identities,
    }


def validate_approval_packet(packet: Mapping[str, Any], *, output_root: Path) -> dict[str, Any]:
    if packet.get("schema_version") != PACKET_SCHEMA_VERSION:
        raise ArchiveGateError("approval_packet_schema_version_invalid")
    if packet.get("task_id") != TASK_ID or packet.get("product") != "jm":
        raise ArchiveGateError("approval_packet_identity_invalid")
    contract = validate_execution_contract(packet.get("execution_plan") or {}, output_root=output_root)
    if packet.get("execution_contract") != contract:
        raise ArchiveGateError("approval_packet_execution_contract_mismatch")
    bound = packet.get("bound_facts") or {}
    reference = packet.get("reference_snapshot") or {}
    if str(bound.get("actual_contract") or "").upper() != contract["actual_contract"]:
        raise ArchiveGateError("approval_packet_bound_actual_contract_mismatch")
    if str(reference.get("actual_contract") or "").upper() != contract["actual_contract"]:
        raise ArchiveGateError("approval_packet_reference_actual_contract_mismatch")
    if bound.get("trading_day") is not None and str(bound["trading_day"]) != contract["target"]:
        raise ArchiveGateError("approval_packet_bound_trading_day_mismatch")
    if bound.get("include_completed_week") is not None and bool(bound["include_completed_week"]) != contract["include_completed_week"]:
        raise ArchiveGateError("approval_packet_bound_completed_week_mismatch")
    if bound.get("output_root") is not None and Path(str(bound["output_root"])).resolve(strict=False) != output_root.resolve(strict=False):
        raise ArchiveGateError("approval_packet_bound_output_root_mismatch")
    execution = packet.get("execution_plan") or {}
    if bound.get("execution_plan_sha256") is not None and bound["execution_plan_sha256"] != _stable_hash(execution):
        raise ArchiveGateError("approval_packet_bound_execution_plan_hash_mismatch")
    if bound.get("provider_final_row_count") is not None and int(bound["provider_final_row_count"]) != int(execution.get("expected_source_rows") or -1):
        raise ArchiveGateError("approval_packet_bound_provider_row_count_mismatch")
    if bound.get("provider_final_1m_hash") is not None and bound["provider_final_1m_hash"] != execution.get("provider_final_1m_hash"):
        raise ArchiveGateError("approval_packet_bound_provider_hash_mismatch")
    return contract


def collect_archive_packet(
    session: Session,
    *,
    client: Any,
    output_root: Path,
    trading_day: date,
    now: datetime,
    git_identity: Mapping[str, Any],
    database_identity: Mapping[str, Any],
    t3_receipt: Mapping[str, Any],
    readiness_timeout_seconds: float = 0,
    readiness_poll_seconds: float = 60,
    provider_stability_checks: int = 2,
    provider_stability_interval_seconds: float = 30,
) -> dict[str, Any]:
    if t3_receipt.get("gate") != "T3_REAL_PASSED":
        raise ArchiveGateError("t3_real_passed_receipt_required")
    if str(t3_receipt.get("trading_day")) != trading_day.isoformat():
        raise ArchiveGateError("t3_trading_day_mismatch")
    clock = TradingSessionClock(session)
    if not clock.trading_day_closed(trading_day, product="jm", exchange="DCE", now=now):
        raise ArchiveGateError("trading_day_not_closed")
    provider_readiness = wait_for_provider_readiness(
        client,
        expected_date=trading_day,
        observed_categories=("future_minbar", "future_daybar"),
        required_categories=("future_minbar",),
        timeout_seconds=readiness_timeout_seconds,
        poll_seconds=readiness_poll_seconds,
    )
    calendar_start = trading_day - timedelta(days=35)
    calendar_end = trading_day + timedelta(days=7)
    provider_days = sorted(client.trading_dates(calendar_start, calendar_end))
    eligible = [day for day in provider_days if day <= trading_day]
    if not eligible or eligible[-1] != trading_day:
        raise ArchiveGateError("provider_final_trading_day_missing")
    mapping_start = max(calendar_start, trading_day - timedelta(days=21))
    reference = collect_provider_reference_snapshot(
        client,
        calendar_start=calendar_start,
        calendar_end=calendar_end,
        mapping_start=mapping_start,
        target=trading_day,
    )
    actual = str(reference["actual_contract"])
    if actual != str(t3_receipt.get("actual_contract")):
        raise ArchiveGateError("t3_actual_contract_mismatch")
    expected_keys = _expected_minute_keys(clock, trading_day, product="jm", exchange="DCE")
    target_frame, provider_stability = _collect_stable_provider_final(
        client,
        actual_contract=actual,
        trading_day=trading_day,
        expected_keys=expected_keys,
        stability_checks=provider_stability_checks,
        stability_interval_seconds=provider_stability_interval_seconds,
    )
    expected_rows = len(expected_keys)
    week_days, complete_week = clock.week_trading_days(trading_day, exchange="DCE")
    include_week = bool(complete_week and week_days and week_days[-1] == trading_day)
    baseline_start = active_baseline_start(session, contract=actual, periods=("1m",))
    batch_id = f"s606_{trading_day:%Y%m%d}_{str(git_identity['commit'])[:8]}"
    execution = build_archive_plan(
        output_root=output_root,
        batch_id=batch_id,
        trading_day=trading_day,
        actual_contract=actual,
        baseline_start=baseline_start,
        expected_source_rows=expected_rows,
        provider_final_1m_hash=stable_bar_frame_hash(target_frame),
        include_week=include_week,
    )
    validate_execution_paths_create_only({"product": "jm", "files": _planned_files(execution)})
    binding = collect_active_binding_snapshot(session)
    live = _live_snapshot(session, actual=actual, trading_day=trading_day)
    bound = {
        "git": dict(git_identity),
        "database": dict(database_identity),
        "output_root": str(output_root.resolve(strict=False)),
        "trading_day": trading_day.isoformat(),
        "trading_day_closed": True,
        "actual_contract": actual,
        "dominant_mapping_date": trading_day.isoformat(),
        "provider_final_row_count": len(target_frame),
        "provider_final_1m_hash": execution["provider_final_1m_hash"],
        "provider_final_min_datetime": target_frame["datetime"].min().isoformat(),
        "provider_final_max_datetime": target_frame["datetime"].max().isoformat(),
        "provider_final_stability": provider_stability,
        "provider_readiness": provider_readiness,
        "rqdatac_version": client.rqdatac_version(),
        "reference_snapshot_sha256": _stable_hash(reference),
        "execution_plan_sha256": _stable_hash(execution),
        "active_binding_sha256": binding["sha256"],
        "live_snapshot": live,
        "t3_packet_hash": t3_receipt.get("packet_hash"),
        "t3_receipt_hash": _stable_hash(t3_receipt),
        "include_completed_week": include_week,
    }
    return build_approval_packet(
        bound_facts=bound,
        execution_plan=execution,
        reference_snapshot=reference,
        binding_snapshot=binding,
        output_root=output_root,
    )


def _expected_minute_keys(
    clock: TradingSessionClock,
    trading_day: date,
    *,
    product: str,
    exchange: str,
) -> tuple[datetime, ...]:
    keys: list[datetime] = []
    for window in clock.windows_for_trading_day(trading_day, product=product, exchange=exchange):
        current = window.start + timedelta(minutes=1)
        while current <= window.end:
            keys.append(current.replace(tzinfo=None))
            current += timedelta(minutes=1)
    if not keys:
        raise ArchiveGateError("expected_trading_minutes_missing")
    return tuple(keys)


def _collect_stable_provider_final(
    client: Any,
    *,
    actual_contract: str,
    trading_day: date,
    expected_keys: Sequence[datetime],
    stability_checks: int,
    stability_interval_seconds: float,
    sleep: Callable[[float], Any] = time.sleep,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    checks = max(2, int(stability_checks))
    interval = max(0.0, float(stability_interval_seconds))
    frames: list[pd.DataFrame] = []
    for index in range(checks):
        raw = client.contract_bars(actual_contract, trading_day, trading_day, "1m")
        normalized = normalize_bar_frame(
            raw,
            symbol="jm",
            contract=actual_contract,
            source_contract=actual_contract,
            exchange="DCE",
            frequency="1m",
            data_version="archive_preflight",
        )
        source_days = pd.to_datetime(normalized["trading_day"], errors="coerce").dt.date
        frames.append(normalized.loc[source_days == trading_day].copy())
        if index + 1 < checks:
            sleep(interval)
    return _validate_stable_provider_frames(frames, expected_keys=expected_keys)


def _validate_stable_provider_frames(
    frames: Sequence[pd.DataFrame],
    *,
    expected_keys: Sequence[datetime],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if len(frames) < 2:
        raise ArchiveGateError("provider_final_stability_checks_insufficient")
    expected = tuple(_naive_datetime(value) for value in expected_keys)
    expected_set = set(expected)
    observations: list[dict[str, Any]] = []
    normalized_frames: list[pd.DataFrame] = []
    for index, source in enumerate(frames, start=1):
        frame = source.copy()
        datetimes = pd.to_datetime(frame["datetime"], errors="raise")
        keys = tuple(_naive_datetime(value) for value in datetimes)
        duplicate_count = len(keys) - len(set(keys))
        missing = sorted(expected_set - set(keys))
        extra = sorted(set(keys) - expected_set)
        if duplicate_count:
            raise ArchiveGateError(f"provider_final_duplicate_bar:{duplicate_count}")
        if missing or extra or len(keys) != len(expected):
            raise ArchiveGateError(
                f"provider_final_minute_key_mismatch:missing={len(missing)}:extra={len(extra)}"
            )
        frame["datetime"] = list(keys)
        frame = frame.sort_values("datetime").reset_index(drop=True)
        frame_hash = stable_bar_frame_hash(frame)
        observations.append(
            {
                "check": index,
                "row_count": len(frame),
                "min_datetime": frame["datetime"].min().isoformat(),
                "max_datetime": frame["datetime"].max().isoformat(),
                "sha256": frame_hash,
            }
        )
        normalized_frames.append(frame)
    hashes = [str(item["sha256"]) for item in observations]
    if len(set(hashes)) != 1:
        raise ArchiveGateError("provider_final_unstable")
    return normalized_frames[-1], {
        "check_count": len(observations),
        "stable": True,
        "expected_minute_count": len(expected),
        "hashes": hashes,
        "observations": observations,
    }


def execute_archive(
    session: Session,
    *,
    client: Any,
    packet: Mapping[str, Any],
    approval_hash: str,
    current_packet: Mapping[str, Any],
    output_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    packet_hash = str(packet.get("packet_hash") or "")
    if approval_hash != packet_hash:
        raise ArchiveGateError("approval_hash_mismatch")
    if canonical_packet_hash(packet) != packet_hash:
        raise ArchiveGateError("packet_hash_invalid")
    validate_approval_packet(packet, output_root=output_root)
    if current_packet.get("bound_facts") != packet.get("bound_facts"):
        raise ArchiveGateError("bound_fact_drift")
    if current_packet.get("execution_contract") != packet.get("execution_contract"):
        raise ArchiveGateError("execution_contract_drift")
    execution = dict(packet["execution_plan"])
    audit_root = Path(str(execution["audit_root"]))
    receipt_path = audit_root / "completion_receipt.json"
    recovered = _recover_committed_archive(session, packet=packet, project_root=project_root)
    if recovered is not None:
        return recovered
    created_before = {path for path in _planned_files(execution) if Path(path).exists()}
    try:
        reference = apply_reference_snapshot(
            session,
            snapshot=packet["reference_snapshot"],
            batch_id=str(execution["batch_id"]),
            target=date.fromisoformat(str(execution["target"])),
        )
        materialized = materialize_execution_assets(
            session=session,
            client=client,
            plan=execution,
            reference_snapshot=packet["reference_snapshot"],
            output_root=output_root,
        )
        materialized = {**materialized, "packet_hash": packet_hash}
        registration = register_execution_assets(
            session=session,
            materialized=materialized,
            manifest_path=Path(str(execution["manifest_path"])),
        )
        registered_asset_smoke = _registered_asset_smoke(
            session,
            artifact_plan=execution,
            registration=registration,
            project_root=project_root,
        )
        bindings = apply_profile_binding_candidates(
            session,
            artifact_plan=execution,
            registration=registration,
            expected_snapshot=packet["binding_snapshot"],
            project_root=project_root,
        )
        trading_day = date.fromisoformat(str(execution["target"]))
        reconciliation = reconcile_live_provider(
            session,
            actual_contract=str(materialized["actual_contract"]),
            trading_day=trading_day,
            canonical_1m=next(
                Path(str(row["canonical_path"]))
                for row in registration["rows"]
                if row["period"] == "1m"
            ),
        )
        target = LiveTargetContractResolver(session).resolve_ready_actual_contract(
            product="jm",
            required_date=trading_day,
        )
        consumer_smoke = _consumer_profile_smoke(
            session,
            artifact_plan=execution,
            registration=registration,
            actual_contract=str(materialized["actual_contract"]),
            trading_day=trading_day,
            project_root=project_root,
        )
        immutable_assets = _verify_immutable_active_assets(
            session,
            snapshot=packet["binding_snapshot"],
            project_root=project_root,
        )
        quality = {
            "schema_version": PACKET_SCHEMA_VERSION,
            "status": "passed",
            "task_id": TASK_ID,
            "packet_hash": packet_hash,
            "reference": reference,
            "assets": registration["rows"],
            "registered_asset_smoke": registered_asset_smoke,
            "profile_switches": bindings["switches"],
            "consumer_target": target,
            "consumer_profile_smoke": consumer_smoke,
            "immutable_active_assets": immutable_assets,
            "reconciliation": reconciliation,
        }
        _write_json(audit_root / "quality_gate.json", quality)
        final = {**quality, "status": "success", "gate": "JM_ARCHIVE_PASSED", "database_committed": True}
        receipt = {
            "schema_version": PACKET_SCHEMA_VERSION,
            "status": "completed",
            "gate": "JM_ARCHIVE_PASSED",
            "packet_hash": packet_hash,
            "batch_id": execution["batch_id"],
            "trading_day": execution["target"],
            "actual_contract": materialized["actual_contract"],
            "manifest_path": registration["manifest_path"],
            "assets": registration["rows"],
            "registered_asset_smoke": registered_asset_smoke,
            "consumer_profile_smoke": consumer_smoke,
            "immutable_active_assets": immutable_assets,
            "reconciliation": reconciliation,
        }
        _stage_json(audit_root / "final_audit.json", final)
        _stage_json(receipt_path, receipt)
        session.commit()
    except Exception as exc:
        session.rollback()
        _cleanup_created(execution, existing=created_before)
        _record_failure(
            session,
            trading_day=date.fromisoformat(str(execution["target"])),
            actual_contract=str(packet["reference_snapshot"]["actual_contract"]),
            packet_hash=packet_hash,
            exc=exc,
        )
        raise
    try:
        _staged_path(audit_root / "final_audit.json").replace(audit_root / "final_audit.json")
        _staged_path(receipt_path).replace(receipt_path)
    except OSError as exc:
        raise ArchiveGateError("archive_receipt_publish_pending") from exc
    return final


def reconcile_live_provider(
    session: Session,
    *,
    actual_contract: str,
    trading_day: date,
    canonical_1m: Path,
) -> dict[str, Any]:
    frame = pd.read_parquet(canonical_1m)
    days = pd.to_datetime(frame["trading_day"], errors="coerce").dt.date
    provider = frame.loc[days == trading_day].copy()
    provider["datetime"] = pd.to_datetime(provider["datetime"], errors="raise")
    live = list(
        session.scalars(
            select(LiveMinuteBar).where(
                LiveMinuteBar.provider == "rqdata",
                LiveMinuteBar.contract_code == actual_contract,
                LiveMinuteBar.period == "1m",
                LiveMinuteBar.trading_day == trading_day,
                LiveMinuteBar.bar_status == "confirmed",
                LiveMinuteBar.quality_status != "failed",
            )
        )
    )
    return _reconcile_provider_live_rows(provider, live)


def _reconcile_provider_live_rows(provider: pd.DataFrame, live: Sequence[Any]) -> dict[str, Any]:
    provider = provider.copy()
    provider["datetime"] = pd.to_datetime(provider["datetime"], errors="raise")
    provider_keys = [_naive_datetime(value) for value in provider["datetime"]]
    provider_counts = Counter(provider_keys)
    provider_rows = {
        _naive_datetime(row["datetime"]): row
        for _, row in provider.sort_values("datetime").iterrows()
    }
    live_keys = [_naive_datetime(row.bar_datetime) for row in live]
    live_counts = Counter(live_keys)
    live_groups: dict[datetime, list[Any]] = {}
    for row, key in zip(live, live_keys, strict=True):
        live_groups.setdefault(key, []).append(row)
    live_rows = {
        key: max(rows, key=lambda row: (int(row.revision or 0), getattr(row, "id", 0) or 0))
        for key, rows in live_groups.items()
    }
    shared = sorted(set(provider_rows) & set(live_rows))
    mismatches = []
    fields = ("open", "high", "low", "close", "volume", "open_interest")
    for key in shared:
        provider_row = provider_rows[key]
        live_row = live_rows[key]
        changed = [field for field in fields if _number(getattr(live_row, field)) != _number(provider_row[field])]
        if changed:
            mismatches.append({"bar_datetime": key.isoformat(), "fields": changed})
    provider_duplicate_count = sum(count - 1 for count in provider_counts.values() if count > 1)
    live_duplicate_count = sum(count - 1 for count in live_counts.values() if count > 1)
    status = (
        "matched"
        if set(provider_rows) == set(live_rows)
        and not mismatches
        and provider_duplicate_count == 0
        and live_duplicate_count == 0
        else "differences_observed"
    )
    return {
        "status": status,
        "live_reference_only": True,
        "provider_row_count": len(provider_keys),
        "provider_unique_bar_count": len(provider_rows),
        "provider_duplicate_count": provider_duplicate_count,
        "live_row_count": len(live_keys),
        "live_unique_bar_count": len(live_rows),
        "live_duplicate_count": live_duplicate_count,
        "exact_match_count": len(shared) - len(mismatches),
        "live_missing_count": len(set(provider_rows) - set(live_rows)),
        "provider_missing_count": len(set(live_rows) - set(provider_rows)),
        "live_extra_count": len(set(live_rows) - set(provider_rows)),
        "revision_row_count": sum(1 for row in live if row.revision > 0),
        "ohlcv_mismatch_count": len(mismatches),
        "mismatch_samples": mismatches[:20],
    }


def _naive_datetime(value: Any) -> datetime:
    result = pd.Timestamp(value).to_pydatetime()
    if result.tzinfo is not None:
        result = result.replace(tzinfo=None)
    return result


def _verify_immutable_active_assets(
    session: Session,
    *,
    snapshot: Mapping[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    verified: list[dict[str, Any]] = []
    for binding in snapshot.get("bindings") or []:
        expected = binding.get("market_file")
        file_id = binding.get("market_data_file_id")
        if file_id is None:
            continue
        if not isinstance(expected, Mapping):
            raise ArchiveGateError(f"immutable_active_file_snapshot_missing:{file_id}")
        current = session.get(MarketDataFile, int(file_id))
        if current is None:
            raise ArchiveGateError(f"immutable_active_file_missing:{file_id}")
        fields = {
            "file_path": current.file_path,
            "checksum": current.checksum,
            "data_version": current.data_version,
            "data_role": current.data_role,
            "quality_status": current.quality_status,
        }
        drifted = sorted(key for key, value in fields.items() if value != expected.get(key))
        if drifted:
            raise ArchiveGateError(f"immutable_active_file_metadata_drift:{file_id}:{','.join(drifted)}")
        path = Path(current.file_path)
        physical = path if path.is_absolute() else project_root / path
        if not physical.is_file():
            raise ArchiveGateError(f"immutable_active_file_missing_on_disk:{file_id}")
        physical_checksum = sha256_file(physical)
        if physical_checksum != current.checksum:
            raise ArchiveGateError(f"immutable_active_file_checksum_drift:{file_id}")
        verified.append({"market_data_file_id": current.id, "checksum": physical_checksum, "file_path": current.file_path})
    return {
        "status": "passed",
        "binding_snapshot_sha256": snapshot.get("sha256"),
        "verified_file_count": len(verified),
        "files": verified,
    }


def _registered_asset_smoke(
    session: Session,
    *,
    artifact_plan: Mapping[str, Any],
    registration: Mapping[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    planned_rows = list(artifact_plan.get("bars") or [])
    registered_rows = list(registration.get("rows") or [])

    def identity(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(row.get("contract") or "").upper(),
            str(row.get("period") or ""),
            str(row.get("source_role") or ""),
            str(row.get("data_version") or ""),
        )

    expected = [identity(row) for row in planned_rows]
    observed = [identity(row) for row in registered_rows]
    if len(expected) != len(set(expected)) or len(observed) != len(set(observed)) or set(observed) != set(expected):
        raise ArchiveGateError("registered_asset_identity_mismatch")
    expected_by_version = {str(row["data_version"]): row for row in planned_rows}
    observed_by_version = dict(registration.get("by_version") or {})
    if set(observed_by_version) != set(expected_by_version):
        raise ArchiveGateError("registered_asset_version_set_mismatch")

    manifest_path = Path(str(registration.get("manifest_path") or artifact_plan.get("manifest_path") or ""))
    if not manifest_path.is_file():
        raise ArchiveGateError("registered_asset_manifest_missing")
    manifest_rows = pd.read_csv(manifest_path, dtype=str, keep_default_na=False).to_dict("records")
    if [identity(row) for row in manifest_rows] != sorted(expected):
        if set(identity(row) for row in manifest_rows) != set(expected) or len(manifest_rows) != len(expected):
            raise ArchiveGateError("registered_asset_manifest_identity_mismatch")

    manifest_by_version = {str(row["data_version"]): row for row in manifest_rows}
    verified: list[dict[str, Any]] = []
    for registered in registered_rows:
        version = str(registered["data_version"])
        planned = expected_by_version[version]
        target = observed_by_version.get(version)
        if target is not registered and target != registered:
            raise ArchiveGateError(f"registered_asset_by_version_mismatch:{version}")
        if registered.get("quality_status") != "passed":
            raise ArchiveGateError(f"registered_asset_quality_not_passed:{version}")
        file_id = registered.get("market_data_file_id")
        market_file = session.get(MarketDataFile, int(file_id)) if file_id is not None else None
        if market_file is None:
            raise ArchiveGateError(f"registered_asset_database_row_missing:{version}")
        matches = list(
            session.scalars(
                select(MarketDataFile).where(
                    MarketDataFile.provider == "rqdata",
                    MarketDataFile.data_type == "bars",
                    MarketDataFile.instrument_symbol == "jm",
                    MarketDataFile.contract_code == planned["contract"],
                    MarketDataFile.period == planned["period"],
                    MarketDataFile.data_version == version,
                )
            )
        )
        if len(matches) != 1 or matches[0].id != market_file.id:
            raise ArchiveGateError(f"registered_asset_database_identity_not_unique:{version}:{len(matches)}")
        if market_file.data_role != "primary" or market_file.quality_status != "passed":
            raise ArchiveGateError(f"registered_asset_database_policy_mismatch:{version}")
        quality_reports = list(
            session.scalars(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
        )
        if len(quality_reports) != 1:
            raise ArchiveGateError(f"registered_asset_quality_report_not_unique:{version}:{len(quality_reports)}")
        quality_report = quality_reports[0]
        if quality_report.status != "passed":
            raise ArchiveGateError(f"registered_asset_quality_report_not_passed:{version}")
        if registered.get("data_quality_report_id") != quality_report.id:
            raise ArchiveGateError(f"registered_asset_quality_report_identity_mismatch:{version}")
        if market_file.file_path != str(planned["canonical_path"]):
            raise ArchiveGateError(f"registered_asset_database_path_mismatch:{version}")
        path = Path(market_file.file_path)
        physical = path if path.is_absolute() else project_root / path
        if not physical.is_file():
            raise ArchiveGateError(f"registered_asset_file_missing:{version}")
        checksum = sha256_file(physical)
        if checksum != market_file.checksum or checksum != registered.get("checksum"):
            raise ArchiveGateError(f"registered_asset_checksum_mismatch:{version}")
        manifest = manifest_by_version.get(version)
        if manifest is None or manifest.get("checksum") != checksum or manifest.get("canonical_path") != market_file.file_path:
            raise ArchiveGateError(f"registered_asset_manifest_mismatch:{version}")
        if market_file.row_count != int(registered["row_count"]):
            raise ArchiveGateError(f"registered_asset_row_count_mismatch:{version}")
        manifest_fields = {
            "quality_status": "passed",
            "row_count": str(market_file.row_count),
            "market_data_file_id": str(market_file.id),
            "data_quality_report_id": str(quality_report.id),
            "min_datetime": str(registered["min_datetime"]),
            "max_datetime": str(registered["max_datetime"]),
        }
        drifted_manifest_fields = sorted(
            field for field, expected_value in manifest_fields.items() if manifest.get(field) != expected_value
        )
        if drifted_manifest_fields:
            raise ArchiveGateError(
                f"registered_asset_manifest_metadata_mismatch:{version}:{','.join(drifted_manifest_fields)}"
            )
        if _naive_datetime(registered["min_datetime"]) != _naive_datetime(market_file.start_time):
            raise ArchiveGateError(f"registered_asset_database_start_mismatch:{version}")
        if _naive_datetime(registered["max_datetime"]) != _naive_datetime(market_file.end_time):
            raise ArchiveGateError(f"registered_asset_database_end_mismatch:{version}")
        verified.append(
            {
                "contract": market_file.contract_code,
                "period": market_file.period,
                "source_role": registered["source_role"],
                "data_version": version,
                "market_data_file_id": market_file.id,
                "quality_status": market_file.quality_status,
                "checksum": checksum,
                "file_path": market_file.file_path,
            }
        )
    return {
        "status": "passed",
        "verified_asset_count": len(verified),
        "verified_periods": sorted(str(row["period"]) for row in verified),
        "asset_identities": sorted(verified, key=lambda row: (row["contract"], row["period"], row["source_role"])),
        "manifest_path": str(manifest_path),
    }


def _consumer_profile_smoke(
    session: Session,
    *,
    artifact_plan: Mapping[str, Any],
    registration: Mapping[str, Any],
    actual_contract: str,
    trading_day: date,
    project_root: Path,
) -> dict[str, Any]:
    actual = actual_contract.strip().upper()
    registered = dict(registration.get("by_version") or {})
    resolver = ProfileLineageResolver(session, project_root=project_root)
    rows: list[dict[str, Any]] = []
    candidates = [
        row
        for row in build_profile_binding_plan(artifact_plan)
        if str(row["contract"]).upper() == actual
    ]
    expected_identities = sorted(
        (
            str(row["profile_id"]),
            actual,
            str(row["period"]),
            str(row["data_version"]),
        )
        for row in candidates
    )
    if len(expected_identities) != len(set(expected_identities)):
        raise ArchiveGateError("consumer_profile_candidate_duplicate")
    for candidate in candidates:
        if str(candidate["contract"]).upper() != actual:
            continue
        version = str(candidate["data_version"])
        target = registered.get(version)
        if target is None or target.get("quality_status") != "passed":
            raise ArchiveGateError(f"consumer_registration_missing:{version}")
        active = list(
            session.scalars(
                select(ProfileActiveBinding).where(
                    ProfileActiveBinding.profile_id == candidate["profile_id"],
                    ProfileActiveBinding.instrument_symbol == "jm",
                    ProfileActiveBinding.contract_code == actual,
                    ProfileActiveBinding.period == candidate["period"],
                    ProfileActiveBinding.binding_status == "active",
                )
            )
        )
        if len(active) != 1:
            raise ArchiveGateError(
                f"consumer_active_binding_not_unique:{candidate['profile_id']}:{candidate['period']}:{len(active)}"
            )
        lineage = resolver.resolve(
            consumer="signal",
            symbol="jm",
            contract=actual,
            period=str(candidate["period"]),
            profile_id=str(candidate["profile_id"]),
        )
        if lineage.blocked:
            raise ArchiveGateError(f"consumer_profile_blocked:{candidate['period']}:{lineage.blocked_reason}")
        expected_file_id = int(target["market_data_file_id"])
        if lineage.market_data_file_id != expected_file_id or lineage.data_version != version:
            raise ArchiveGateError(f"consumer_profile_identity_mismatch:{candidate['period']}")
        if lineage.market_file is None or lineage.market_file.end_time.date() < trading_day:
            raise ArchiveGateError(f"consumer_profile_target_not_covered:{candidate['period']}")
        rows.append(
            {
                "profile_id": candidate["profile_id"],
                "contract": actual,
                "period": candidate["period"],
                "data_version": lineage.data_version,
                "market_data_file_id": lineage.market_data_file_id,
                "quality_status": lineage.market_file.quality_status,
                "end_time": lineage.market_file.end_time.isoformat(),
            }
        )
    verified_identities = sorted(
        (
            str(row["profile_id"]),
            str(row["contract"]),
            str(row["period"]),
            str(row["data_version"]),
        )
        for row in rows
    )
    if verified_identities != expected_identities:
        raise ArchiveGateError("consumer_profile_candidate_coverage_mismatch")
    verified_periods = sorted({str(row["period"]) for row in rows})
    return {
        "status": "passed",
        "verified_candidate_count": len(verified_identities),
        "verified_candidate_identities": [
            {
                "profile_id": profile_id,
                "contract": contract,
                "period": period,
                "data_version": version,
            }
            for profile_id, contract, period, version in verified_identities
        ],
        "verified_periods": verified_periods,
        "rows": rows,
    }


def _stage_json(path: Path, payload: Mapping[str, Any]) -> Path:
    staged = _staged_path(path)
    _write_json(staged, payload)
    return staged


def _recover_committed_archive(
    session: Session,
    *,
    packet: Mapping[str, Any],
    project_root: Path,
) -> dict[str, Any] | None:
    packet_hash = str(packet.get("packet_hash") or "")
    execution = dict(packet.get("execution_plan") or {})
    audit_root = Path(str(execution.get("audit_root") or ""))
    receipt_path = audit_root / "completion_receipt.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("packet_hash") != packet_hash:
            raise ArchiveGateError("completion_receipt_mismatch")
        return {
            "status": "already_archived",
            "writes_performed": False,
            "receipt_recovered": False,
            "receipt_path": str(receipt_path),
        }
    staged_receipt = _staged_path(receipt_path)
    final_path = audit_root / "final_audit.json"
    staged_final = _staged_path(final_path)
    if not staged_receipt.is_file() or (not staged_final.is_file() and not final_path.is_file()):
        return None

    expected_rows = list(execution.get("bars") or [])
    expected_by_version = {str(row["data_version"]): row for row in expected_rows}
    committed_tasks = []
    for task in session.scalars(select(DataDownloadTask).where(DataDownloadTask.status == "success")):
        result = task.result if isinstance(task.result, dict) else {}
        if result.get("packet_hash") == packet_hash and result.get("batch_id") == execution.get("batch_id"):
            committed_tasks.append(task)
    committed_versions = {
        str(task.result.get("data_version"))
        for task in committed_tasks
        if isinstance(task.result, dict) and task.result.get("data_version")
    }
    if committed_versions != set(expected_by_version):
        raise ArchiveGateError("committed_archive_task_set_incomplete")

    registration_by_version: dict[str, dict[str, Any]] = {}
    registration_rows: list[dict[str, Any]] = []
    for version, row in expected_by_version.items():
        market_files = list(
            session.scalars(
                select(MarketDataFile).where(
                    MarketDataFile.provider == "rqdata",
                    MarketDataFile.instrument_symbol == "jm",
                    MarketDataFile.contract_code == row["contract"],
                    MarketDataFile.period == row["period"],
                    MarketDataFile.data_version == version,
                    MarketDataFile.data_role == "primary",
                    MarketDataFile.quality_status == "passed",
                )
            )
        )
        if len(market_files) != 1:
            raise ArchiveGateError(f"committed_archive_file_not_unique:{version}:{len(market_files)}")
        market_file = market_files[0]
        path = Path(market_file.file_path)
        physical = path if path.is_absolute() else project_root / path
        if not physical.is_file() or sha256_file(physical) != market_file.checksum:
            raise ArchiveGateError(f"committed_archive_file_checksum_mismatch:{version}")
        quality_reports = list(
            session.scalars(select(DataQualityReport).where(DataQualityReport.file_id == market_file.id))
        )
        if len(quality_reports) != 1:
            raise ArchiveGateError(f"committed_archive_quality_report_not_unique:{version}:{len(quality_reports)}")
        registered_row = {
            "contract": row["contract"],
            "period": row["period"],
            "source_role": row["source_role"],
            "data_version": version,
            "canonical_path": market_file.file_path,
            "raw_path": row.get("raw_path"),
            "row_count": market_file.row_count,
            "min_datetime": market_file.start_time.isoformat(),
            "max_datetime": market_file.end_time.isoformat(),
            "checksum": market_file.checksum,
            "quality_status": market_file.quality_status,
            "market_data_file_id": market_file.id,
            "data_quality_report_id": quality_reports[0].id,
        }
        registration_by_version[version] = registered_row
        registration_rows.append(registered_row)
    registration = {
        "status": "passed",
        "rows": registration_rows,
        "by_version": registration_by_version,
        "manifest_path": str(execution["manifest_path"]),
    }
    _registered_asset_smoke(
        session,
        artifact_plan=execution,
        registration=registration,
        project_root=project_root,
    )
    actual_contract = str(packet.get("reference_snapshot", {}).get("actual_contract") or "")
    if not actual_contract:
        actual_contract = str(expected_rows[0]["contract"]) if expected_rows else ""
    _consumer_profile_smoke(
        session,
        artifact_plan=execution,
        registration=registration,
        actual_contract=actual_contract,
        trading_day=date.fromisoformat(str(execution["target"])),
        project_root=project_root,
    )
    if staged_final.is_file():
        staged_final.replace(final_path)
    staged_receipt.replace(receipt_path)
    return {
        "status": "already_archived",
        "writes_performed": False,
        "receipt_recovered": True,
        "receipt_path": str(receipt_path),
    }


def _staged_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.staged")


def _live_snapshot(session: Session, *, actual: str, trading_day: date) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(LiveMinuteBar).where(
                LiveMinuteBar.contract_code == actual,
                LiveMinuteBar.period == "1m",
                LiveMinuteBar.trading_day == trading_day,
            )
        )
    )
    values = [
        {
            "id": row.id,
            "bar_datetime": row.bar_datetime.isoformat(),
            "revision": row.revision,
            "bar_status": row.bar_status,
            "quality_status": row.quality_status,
        }
        for row in sorted(rows, key=lambda item: item.bar_datetime)
    ]
    return {"row_count": len(values), "sha256": _stable_hash(values)}


def _planned_files(plan: Mapping[str, Any]) -> list[str]:
    files = [
        *[str(row["canonical_path"]) for row in plan.get("bars") or []],
        *[str(row["raw_path"]) for row in plan.get("bars") or [] if row.get("raw_path")],
        *[str(path) for path in plan.get("reference_paths") or []],
        str(plan["manifest_path"]),
        str(Path(str(plan["audit_root"])) / "quality_gate.json"),
        str(Path(str(plan["audit_root"])) / "final_audit.json"),
        str(Path(str(plan["audit_root"])) / "completion_receipt.json"),
    ]
    return [*files, *[str(_staged_path(Path(value))) for value in files[-2:]]]


def _cleanup_created(plan: Mapping[str, Any], *, existing: set[str]) -> None:
    for value in reversed(_planned_files(plan)):
        path = Path(value)
        if value not in existing and path.is_file():
            path.unlink()


def _record_failure(
    session: Session,
    *,
    trading_day: date,
    actual_contract: str,
    packet_hash: str,
    exc: Exception,
) -> None:
    task_no = f"archive:s606:jm:{actual_contract}:{trading_day.isoformat()}:{packet_hash[:12]}"
    task = session.scalar(select(DataDownloadTask).where(DataDownloadTask.task_no == task_no))
    if task is None:
        task = DataDownloadTask(
            task_no=task_no,
            provider="rqdata",
            data_type="after_market_archive",
            instrument_symbol="jm",
            contract_code=actual_contract,
            period="1m_bundle",
            start_time=datetime.combine(trading_day, datetime.min.time()),
            end_time=datetime.combine(trading_day, datetime.max.time()),
            status="failed",
            progress=0,
            result={},
            started_at=utc_now(),
        )
        session.add(task)
    attempted_at = utc_now()
    error_message = _safe_error(exc)
    previous = dict(task.result) if isinstance(task.result, dict) else {}
    attempts = list(previous.get("attempts") or [])
    attempts.append(
        {
            "attempted_at": attempted_at.isoformat(),
            "error_type": type(exc).__name__,
            "error_message": error_message,
            "active_binding_changed": False,
        }
    )
    task.status = "failed"
    task.error_message = error_message
    task.finished_at = attempted_at
    task.result = {
        "task_id": TASK_ID,
        "packet_hash": packet_hash,
        "error_type": type(exc).__name__,
        "active_binding_changed": False,
        "attempt_count": len(attempts),
        "attempts": attempts,
    }
    try:
        session.commit()
    except Exception:
        session.rollback()


def _validate_versions(plan: Mapping[str, Any]) -> None:
    invalid = [row["data_version"] for row in plan.get("bars") or [] if len(str(row["data_version"])) > 64]
    if invalid:
        raise ArchiveGateError("data_version_too_long")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise ArchiveGateError(f"output_already_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _number(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return format(float(value), ".10g")


def _safe_error(exc: Exception) -> str | None:
    value = str(exc).strip()
    if not value:
        return None
    lowered = value.lower()
    if any(part in lowered for part in ("password", "secret", "token", "webhook", "license", "cookie", "key")):
        return None
    return value[:200]


__all__ = [
    "ArchiveGateError",
    "build_approval_packet",
    "build_archive_plan",
    "collect_archive_packet",
    "execute_archive",
    "reconcile_live_provider",
    "validate_approval_packet",
    "validate_execution_contract",
]
