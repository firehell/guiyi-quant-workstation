from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import DataProfile, ProfileActiveBinding
from app.services.rqdata_ingest.full_history_contract import (
    DERIVED_FROM_1M_PERIODS,
    DIRECT_PERIODS,
    V1_AUDIT_END,
    ActualRank1Range,
    build_actual_rank1_targets,
)
from app.services.rqdata_ingest.full_history_reference_metadata import (
    ReferenceMetadataConfig,
    collect_reference_metadata,
)


READY = "FULL_HISTORY_AUDIT_V2_READY"
SMOKE_READY = "FULL_HISTORY_AUDIT_V2_SMOKE_READY"
INVENTORY_READY = "FULL_HISTORY_PHYSICAL_INVENTORY_READY"
V2_REPORT_FILES = (
    "audit_v2_expected_windows.csv",
    "audit_v2_target_year_matrix.csv",
    "audit_v2_actual_rank1_ranges.csv",
    "audit_v2_asset_layer_matrix.csv",
    "audit_v2_reference_metadata_matrix.csv",
    "audit_v2_profile_eligibility_matrix.csv",
    "audit_v2_gap_register.csv",
    "audit_v2_summary.json",
    "audit_v2_legacy_comparison.json",
    "FULL_HISTORY_AUDIT_V2.md",
)


@dataclass(frozen=True)
class AuditV2Config:
    project_root: Path
    inventory_dir: Path
    audit_end: date = V1_AUDIT_END
    provider_start_evidence: Path | None = None
    legacy_report_dir: Path | None = None
    products: tuple[str, ...] = ()
    require_postgresql: bool = True
    db_fetch_size: int = 10_000

    def __post_init__(self) -> None:
        if self.audit_end != V1_AUDIT_END:
            raise ValueError(f"audit_end must be {V1_AUDIT_END.isoformat()}")
        if self.db_fetch_size < 1:
            raise ValueError("db_fetch_size must be positive")


@dataclass(frozen=True)
class AuditV2Result:
    expected_windows: list[dict[str, Any]]
    target_year_matrix: list[dict[str, Any]]
    actual_rank1_ranges: list[dict[str, Any]]
    asset_layer_matrix: list[dict[str, Any]]
    reference_metadata_matrix: list[dict[str, Any]]
    profile_eligibility_matrix: list[dict[str, Any]]
    gap_register: list[dict[str, Any]]
    summary: dict[str, Any]
    legacy_comparison: dict[str, Any]


def run_full_history_audit_v2(config: AuditV2Config, session: Session) -> AuditV2Result:
    root = config.project_root.resolve()
    inventory_dir = _resolve(root, config.inventory_dir)
    physical_path = inventory_dir / "physical_inventory.csv"
    summary_path = inventory_dir / "inventory_summary.json"
    if not physical_path.is_file() or not summary_path.is_file():
        raise RuntimeError("AUDIT_V2_BLOCKED_INVENTORY: B2-01 inputs are missing")
    input_paths = [physical_path, summary_path]
    before_hashes = {str(path): _sha256(path) for path in input_paths}
    inventory_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if inventory_summary.get("status") != INVENTORY_READY or inventory_summary.get("db_snapshot_source") != "direct_postgresql":
        raise RuntimeError("AUDIT_V2_BLOCKED_INVENTORY: inventory is not direct PostgreSQL ready")
    inventory_rows = _read_csv(physical_path)
    product_filter = {item.strip().lower() for item in config.products if item.strip()}
    if product_filter:
        inventory_rows = [row for row in inventory_rows if str(row.get("product", "")).lower() in product_filter]
    products = tuple(sorted(product_filter or {str(row.get("product", "")).lower() for row in inventory_rows if row.get("product")}))
    provider_evidence = _load_provider_evidence(config.provider_start_evidence, root)

    try:
        reference = collect_reference_metadata(
            session,
            ReferenceMetadataConfig(
                products=products,
                audit_end=config.audit_end,
                require_postgresql=config.require_postgresql,
                actual_role_products=products,
                continuous_role_products=(),
                minute_scope_products=products,
            ),
        )
        if any(product not in reference.listing_dates for product in products):
            missing = sorted(set(products) - set(reference.listing_dates))
            raise RuntimeError(f"AUDIT_V2_BLOCKED_CONTRACT: missing listing metadata for {missing}")

        expected = build_expected_windows(
            inventory_rows,
            listing_dates=reference.listing_dates,
            audit_end=config.audit_end,
            provider_evidence=provider_evidence,
            trading_days_by_product=reference.trading_days_by_product,
        )
        years = _build_target_year_matrix(expected, config.audit_end)
        actual_ranges = _actual_range_rows(reference.rank1_ranges, config.audit_end, expected)
        asset_layers = _build_asset_layers(inventory_rows, expected, reference.matrix)
        profile_matrix = _build_profile_matrix(session, expected, asset_layers)
        gap_register = _merge_gaps(reference.gaps, asset_layers, profile_matrix)
    finally:
        session.rollback()

    after_hashes = {str(path): _sha256(path) for path in input_paths}
    if before_hashes != after_hashes:
        raise RuntimeError("AUDIT_V2_BLOCKED_INPUT: inventory changed during audit")

    authoritative = bool(provider_evidence) and all(
        row["boundary_status"] in {"resolved", "not_applicable"} for row in expected
    )
    strict_layers_passed = all(
        row["physical_coverage"] == "covered"
        and row["registration"] == "registered"
        and row["quality"] == "passed"
        and row["reference_metadata"] in {"passed", "not_applicable"}
        for row in asset_layers
        if row["boundary_status"] != "not_applicable"
    )
    data_gate_status = (
        "DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL"
        if authoritative and strict_layers_passed and not gap_register
        else "DATA_LAYER_REAUDIT_REQUIRED"
    )
    status = SMOKE_READY if product_filter else READY
    summary = {
        "task_id": "FULL-HISTORY-AUDIT-V2-ENGINE-002",
        "status": status,
        "data_gate_status": data_gate_status,
        "audit_end": config.audit_end.isoformat(),
        "scope": "filtered_smoke" if product_filter else "full",
        "products": list(products),
        "git_commit": _git_commit(root),
        "inventory_status": inventory_summary.get("status"),
        "db_snapshot_source": "direct_postgresql" if config.require_postgresql else "test_session",
        "expected_window_count": len(expected),
        "target_year_row_count": len(years),
        "actual_rank1_range_count": len(actual_ranges),
        "asset_layer_row_count": len(asset_layers),
        "reference_metadata_row_count": len(reference.matrix),
        "profile_eligibility_row_count": len(profile_matrix),
        "gap_count": len(gap_register),
        "gap_counts": _counts(gap_register, "gap_category"),
        "boundary_status_counts": _counts(expected, "boundary_status"),
        "layer_status_counts": {
            field: _counts(asset_layers, field)
            for field in ("physical_coverage", "registration", "quality", "reference_metadata")
        },
        "input_sha256_before": before_hashes,
        "input_sha256_after": after_hashes,
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "old_report_numbers_used_for_gate": False,
        "warnings_promoted_to_passed": False,
        "expected_years_dynamic": True,
    }
    legacy_comparison = {
        "status": "legacy_comparison_only",
        "participates_in_v2_gate": False,
        "historical_counts": {"metadata_gap": 1853, "pre_2020_weekly_missing": 34, "legacy_other": 45},
        "note": "Historical snapshots are retained for comparison and are not V2 expected targets.",
    }
    return AuditV2Result(
        expected_windows=expected,
        target_year_matrix=years,
        actual_rank1_ranges=actual_ranges,
        asset_layer_matrix=asset_layers,
        reference_metadata_matrix=reference.matrix,
        profile_eligibility_matrix=profile_matrix,
        gap_register=gap_register,
        summary=summary,
        legacy_comparison=legacy_comparison,
    )


def build_expected_windows(
    inventory_rows: Iterable[dict[str, Any]],
    *,
    listing_dates: dict[str, date],
    audit_end: date,
    provider_evidence: dict[tuple[str, str], dict[str, Any]],
    trading_days_by_product: dict[str, tuple[date, ...]],
) -> list[dict[str, Any]]:
    rows = list(inventory_rows)
    physical: dict[tuple[str, str], date] = {}
    for row in rows:
        if str(row.get("contract_role", "")) != "dominant_main" or str(row.get("data_role", "")) != "primary":
            continue
        product = str(row.get("product", "")).lower()
        period = str(row.get("period", "")).lower()
        minimum = _as_date(row.get("physical_min_datetime"))
        if minimum:
            physical[(product, period)] = min(physical.get((product, period), minimum), minimum)

    result: list[dict[str, Any]] = []
    for product, listing in sorted(listing_dates.items()):
        if listing > audit_end:
            for period in sorted(DIRECT_PERIODS | DERIVED_FROM_1M_PERIODS):
                source_role = "direct" if period in DIRECT_PERIODS else "derived_from_1m"
                result.append(_window_row(product, period, source_role, listing, None, None, None, "not_applicable", "listed_after_audit_end"))
            continue
        direct_starts: dict[str, date | None] = {}
        for period in sorted(DIRECT_PERIODS):
            evidence = provider_evidence.get((product, period))
            physical_min = physical.get((product, period))
            authoritative_start = _as_date(evidence.get("first_valid_bar")) if evidence and evidence.get("authoritative") else None
            target_start = max(listing, authoritative_start) if authoritative_start else physical_min
            if target_start is not None and target_start < listing:
                target_start = listing
            if authoritative_start:
                status = "resolved"
                reason = "authoritative_provider_start_and_listing"
            elif physical_min:
                status = "start_boundary_supported"
                reason = "physical_min_support_without_authoritative_provider_start"
            else:
                status = "start_boundary_unverified"
                reason = "provider_start_and_physical_support_missing"
            if period == "1w" and target_start:
                target_start, weekly_verified = _first_completed_week(
                    target_start,
                    trading_days_by_product.get(product, ()),
                )
                if not weekly_verified and status == "resolved":
                    status = "start_boundary_unverified"
                    reason = "trading_calendar_incomplete_for_first_completed_week"
            direct_starts[period] = target_start
            result.append(
                _window_row(product, period, "direct", listing, authoritative_start, physical_min, target_start, status, reason, audit_end)
            )
        minute_start = direct_starts.get("1m")
        for period in sorted(DERIVED_FROM_1M_PERIODS):
            status = "start_boundary_supported" if minute_start else "start_boundary_unverified"
            result.append(
                _window_row(
                    product,
                    period,
                    "derived_from_1m",
                    listing,
                    None,
                    physical.get((product, period)),
                    minute_start,
                    status,
                    "inherited_from_1m_boundary" if minute_start else "source_1m_boundary_unverified",
                    audit_end if minute_start else None,
                )
            )
    return sorted(result, key=lambda row: (row["product"], row["period"], row["source_role"]))


def write_full_history_audit_v2_reports(result: AuditV2Result, output_dir: Path) -> dict[str, Path]:
    output_dir = output_dir.resolve(strict=False)
    existing = [output_dir / name for name in V2_REPORT_FILES if (output_dir / name).exists()]
    if existing:
        raise FileExistsError(f"OUTPUT_EXISTS: {existing[0]}")
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets = {
        "expected_windows": ("audit_v2_expected_windows.csv", result.expected_windows),
        "target_year_matrix": ("audit_v2_target_year_matrix.csv", result.target_year_matrix),
        "actual_rank1_ranges": ("audit_v2_actual_rank1_ranges.csv", result.actual_rank1_ranges),
        "asset_layer_matrix": ("audit_v2_asset_layer_matrix.csv", result.asset_layer_matrix),
        "reference_metadata_matrix": ("audit_v2_reference_metadata_matrix.csv", result.reference_metadata_matrix),
        "profile_eligibility_matrix": ("audit_v2_profile_eligibility_matrix.csv", result.profile_eligibility_matrix),
        "gap_register": ("audit_v2_gap_register.csv", result.gap_register),
    }
    paths: dict[str, Path] = {}
    for key, (name, rows) in datasets.items():
        path = output_dir / name
        _write_csv(path, rows)
        paths[key] = path
    summary_path = output_dir / "audit_v2_summary.json"
    summary_path.write_text(json.dumps(result.summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["summary"] = summary_path
    legacy_path = output_dir / "audit_v2_legacy_comparison.json"
    legacy_path.write_text(json.dumps(result.legacy_comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["legacy_comparison"] = legacy_path
    markdown = output_dir / "FULL_HISTORY_AUDIT_V2.md"
    markdown.write_text(_markdown_summary(result.summary), encoding="utf-8")
    paths["markdown"] = markdown
    return paths


def _build_target_year_matrix(windows: list[dict[str, Any]], audit_end: date) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in windows:
        start = _as_date(row.get("target_start"))
        end = _as_date(row.get("target_end"))
        if not start or not end or row["boundary_status"] == "not_applicable":
            continue
        for year in range(start.year, min(end, audit_end).year + 1):
            result.append(
                {
                    "product": row["product"],
                    "contract_role": row["contract_role"],
                    "period": row["period"],
                    "source_role": row["source_role"],
                    "year": year,
                    "expected_start": max(start, date(year, 1, 1)).isoformat(),
                    "expected_end": min(end, date(year, 12, 31), audit_end).isoformat(),
                    "boundary_status": row["boundary_status"],
                }
            )
    return result


def _actual_range_rows(
    ranges: tuple[ActualRank1Range, ...],
    audit_end: date,
    expected_windows: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    supported_starts: dict[tuple[str, str], date] = {}
    for row in expected_windows:
        if row.get("source_role") != "direct":
            continue
        start = _as_date(row.get("target_start"))
        if start:
            supported_starts[(str(row.get("product", "")).lower(), str(row.get("period", "")))] = start
    targets = build_actual_rank1_targets(
        ranges,
        audit_end=audit_end,
        supported_starts=supported_starts,
    )
    return [
        {
            "product": target.product,
            "contract": target.contract,
            "contract_role": target.contract_role,
            "period": target.period,
            "expected_start": target.expected_start.isoformat(),
            "expected_end": target.expected_end.isoformat(),
            "target_reason": target.target_reason,
        }
        for target in targets
    ]


def _build_asset_layers(
    inventory: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    reference: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reference_by_product: dict[str, str] = {}
    for product in {str(row["product"]) for row in reference}:
        statuses = {str(row["status"]) for row in reference if row["product"] == product and row["applicability"] == "applicable"}
        reference_by_product[product] = "gap" if "gap" in statuses else "unverified" if "unverified" in statuses else "passed"
    result: list[dict[str, Any]] = []
    for window in windows:
        candidates = [
            row
            for row in inventory
            if str(row.get("product", "")).lower() == window["product"]
            and str(row.get("contract_role", "")) == "dominant_main"
            and str(row.get("period", "")).lower() == window["period"]
            and str(row.get("data_role", "")) == "primary"
        ]
        if window["boundary_status"] == "not_applicable":
            physical = registration = quality = reference_status = "not_applicable"
        else:
            physical = _physical_status(candidates, window)
            registration = "registered" if any(_as_int(row.get("db_record_count")) > 0 for row in candidates) else "missing"
            quality = _quality_status(candidates)
            reference_status = reference_by_product.get(window["product"], "gap")
        result.append(
            {
                **window,
                "physical_coverage": physical,
                "registration": registration,
                "quality": quality,
                "reference_metadata": reference_status,
                "evidence_path_count": len({str(row.get("physical_path", "")) for row in candidates}),
                "identity_conflict": _has_version_path_conflict(candidates),
            }
        )
    return result


def _build_profile_matrix(
    session: Session,
    expected: list[dict[str, Any]],
    asset_layers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    profiles = list(session.scalars(select(DataProfile).where(DataProfile.is_active.is_(True)).order_by(DataProfile.profile_id)))
    binding_counts = {
        profile_id: count
        for profile_id, count in session.execute(
            select(ProfileActiveBinding.profile_id, func.count())
            .where(ProfileActiveBinding.binding_status == "active")
            .group_by(ProfileActiveBinding.profile_id)
        )
    }
    layers = {(row["product"], row["period"], row["source_role"]): row for row in asset_layers}
    result: list[dict[str, Any]] = []
    products = sorted({row["product"] for row in expected})
    for profile in profiles:
        for product in products:
            for period in profile.periods or []:
                source_role = "direct"
                layer = layers.get((product, period, source_role)) or layers.get((product, period, "derived_from_1m"))
                role_supported = any(role in {"dominant", "dominant_main", "actual", "actual_contract"} for role in (profile.contract_roles or []))
                if not layer or not role_supported:
                    status = "not_applicable"
                    reason = "profile_scope_not_applicable"
                elif (
                    layer["physical_coverage"] == "covered"
                    and layer["registration"] == "registered"
                    and layer["quality"] == "passed"
                    and layer["reference_metadata"] in {"passed", "not_applicable"}
                    and binding_counts.get(profile.profile_id, 0) > 0
                ):
                    status = "eligible"
                    reason = "strict_layers_and_active_binding_passed"
                elif layer["quality"] == "warning" and profile.quality_policy == "active_entry":
                    status = "eligible_warning"
                    reason = "warning_visible_under_active_entry_policy"
                else:
                    status = "blocked"
                    reason = "one_or_more_required_layers_not_passed"
                result.append(
                    {
                        "profile_id": profile.profile_id,
                        "product": product,
                        "period": period,
                        "quality_policy": profile.quality_policy,
                        "active_binding_count": binding_counts.get(profile.profile_id, 0),
                        "profile_eligibility": status,
                        "reason": reason,
                    }
                )
    return result


def _merge_gaps(
    reference_gaps: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = [dict(row, layer="reference_metadata") for row in reference_gaps]
    for row in assets:
        if row["boundary_status"] == "not_applicable":
            continue
        if row["registration"] == "missing":
            result.append(
                {
                    "product": row["product"],
                    "gap_category": "asset_registration_gap",
                    "status": "gap",
                    "reason": "expected_asset_not_registered",
                    "start": row["target_start"],
                    "end": row["target_end"],
                    "layer": "registration",
                }
            )
    return sorted(result, key=lambda row: (row["product"], row["gap_category"], row.get("layer", "")))


def _load_provider_evidence(path: Path | None, root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if path is None:
        return {}
    resolved = _resolve(root, path)
    rows = _read_csv(resolved)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        required = {"product", "period", "first_valid_bar", "source_kind", "source_ref", "provider", "data_version", "checksum", "authoritative"}
        if not required <= set(row):
            raise RuntimeError("AUDIT_V2_BLOCKED_INPUT: provider evidence schema invalid")
        result[(str(row["product"]).lower(), str(row["period"]).lower())] = {
            **row,
            "authoritative": _as_bool(row["authoritative"]),
        }
    return result


def _window_row(
    product: str,
    period: str,
    source_role: str,
    listing: date,
    authoritative: date | None,
    physical_min: date | None,
    target_start: date | None,
    status: str,
    reason: str,
    target_end: date | None = None,
) -> dict[str, Any]:
    return {
        "product": product,
        "contract_role": "dominant_main",
        "period": period,
        "source_role": source_role,
        "listing_start": listing.isoformat(),
        "provider_authoritative_start": authoritative.isoformat() if authoritative else "",
        "provider_metadata_support": "authoritative" if authoritative else "absent",
        "physical_min": physical_min.isoformat() if physical_min else "",
        "target_start": target_start.isoformat() if target_start else "",
        "target_end": target_end.isoformat() if target_end else "",
        "boundary_status": status,
        "boundary_reason": reason,
    }


def _first_completed_week(start: date, trading_days: tuple[date, ...]) -> tuple[date, bool]:
    if not trading_days:
        return start, False
    candidates = [day for day in trading_days if day >= start and day.isocalendar()[:2] == start.isocalendar()[:2]]
    if not candidates:
        return start, False
    return max(candidates), True


def _physical_status(rows: list[dict[str, Any]], window: dict[str, Any]) -> str:
    if not rows:
        return "missing"
    if _has_version_path_conflict(rows):
        return "conflict"
    target_start = _as_date(window.get("target_start"))
    target_end = _as_date(window.get("target_end"))
    minimums = [_as_date(row.get("physical_min_datetime")) for row in rows]
    maximums = [_as_date(row.get("physical_max_datetime")) for row in rows]
    minimums = [item for item in minimums if item]
    maximums = [item for item in maximums if item]
    if target_start and target_end and minimums and maximums and min(minimums) <= target_start and max(maximums) >= target_end:
        return "covered"
    return "partial"


def _has_version_path_conflict(rows: list[dict[str, Any]]) -> bool:
    paths_by_version: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        key = (str(row.get("provider", "")), str(row.get("data_version", "")))
        paths_by_version.setdefault(key, set()).add(str(row.get("physical_path", "")))
        if str(row.get("schema_consistency_status", "")).lower() == "inconsistent":
            return True
    return any(len(paths) > 1 for paths in paths_by_version.values())


def _quality_status(rows: list[dict[str, Any]]) -> str:
    statuses: set[str] = set()
    for field in (
        "quality_statuses_db",
        "quality_statuses_manifest",
        "quality_statuses_processed",
        "quality_statuses",
    ):
        for row in rows:
            value = row.get(field, "")
            try:
                parsed = json.loads(str(value)) if value else []
            except json.JSONDecodeError:
                parsed = [str(value)]
            statuses.update(str(item).lower() for item in parsed if str(item).strip())
        if statuses:
            break
    for status in ("failed", "warning", "unchecked", "passed"):
        if status in statuses:
            return status
    return "unchecked"


def _counts(rows: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field, ""))
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = list(rows[0]) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows or [{"status": "no_rows"}])


def _resolve(root: Path, path: Path) -> Path:
    return (path if path.is_absolute() else root / path).resolve(strict=False)


def _as_date(value: Any) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def _as_bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"1", "true", "yes"}


def _as_int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _markdown_summary(summary: dict[str, Any]) -> str:
    return (
        "# Full History Audit V2\n\n"
        f"- Status: `{summary['status']}`\n"
        f"- Data gate: `{summary['data_gate_status']}`\n"
        f"- Audit end: `{summary['audit_end']}`\n"
        f"- Products: `{len(summary['products'])}`\n"
        f"- Expected windows: `{summary['expected_window_count']}`\n"
        f"- Gaps: `{summary['gap_count']}`\n\n"
        "This report is read-only evidence. It does not write DB or Parquet and does not call RQData.\n"
    )


__all__ = [
    "AuditV2Config",
    "AuditV2Result",
    "READY",
    "SMOKE_READY",
    "build_expected_windows",
    "run_full_history_audit_v2",
    "write_full_history_audit_v2_reports",
]
