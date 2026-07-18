from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


TargetKey = tuple[str, str, str]


@dataclass(frozen=True, order=True)
class ProfileTargetRange:
    start: date
    end: date
    source: str
    boundary_status: str = "verified"


@dataclass(frozen=True)
class ProfileTargetWindow:
    profile_id: str
    product: str
    contract: str
    period: str
    contract_role: str
    ranges: tuple[ProfileTargetRange, ...]
    target_start: date
    target_end: date
    lineage_required: bool
    source: str


@dataclass(frozen=True)
class ProfileTargetIssue:
    profile_id: str
    product: str
    contract: str
    period: str
    reason: str
    evidence_source: str


@dataclass(frozen=True)
class ProfileTargetResolution:
    windows: dict[TargetKey, ProfileTargetWindow]
    issues: tuple[ProfileTargetIssue, ...]


@dataclass(frozen=True)
class ProfileEvidencePaths:
    expected_windows: Path | None = None
    consumer_target_matrix: Path | None = None
    derived_inventory: Path | None = None
    actual_target_coverage: Path | None = None
    physical_inventory: Path | None = None


def _read_csv(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_date(value: Any) -> date | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _source_rows(source: str, evidence: ProfileEvidencePaths) -> list[dict[str, str]]:
    paths = {
        "audit_v2_expected_windows": evidence.expected_windows,
        "consumer_target_matrix": evidence.consumer_target_matrix,
        "actual_target_coverage": evidence.actual_target_coverage,
    }
    return _read_csv(paths.get(source))


def _row_matches_rule(row: dict[str, str], rule: dict[str, Any], products: set[str]) -> bool:
    product = _clean(row.get("product")).lower()
    if not product or product not in products:
        return False
    period = _clean(row.get("period")).lower()
    if period not in {_clean(item).lower() for item in rule.get("periods") or []}:
        return False
    role = _clean(row.get("contract_role")) or (
        "actual_contract" if _clean(row.get("contract")) else "dominant_main"
    )
    if role != _clean(rule.get("contract_role")):
        return False
    source_role = _clean(rule.get("source_role"))
    if source_role and _clean(row.get("source_role")) != source_role:
        return False
    required_status = _clean(rule.get("required_status"))
    if required_status and _clean(row.get("status")) != required_status:
        return False
    required_profile = _clean(rule.get("source_profile_id"))
    if required_profile and _clean(row.get("profile_id")) != required_profile:
        return False
    required_level = _clean(rule.get("requirement_level"))
    return not required_level or _clean(row.get("requirement_level")) == required_level


def _row_identity(row: dict[str, str], role: str) -> tuple[str, str, str]:
    product = _clean(row.get("product")).lower()
    contract = _clean(row.get("contract"))
    if not contract and role == "dominant_main":
        contract = f"{product}.MAIN"
    return product, contract, _clean(row.get("period")).lower()


def _row_range(row: dict[str, str], source: str) -> tuple[date | None, date | None]:
    if source == "actual_target_coverage":
        return _parse_date(row.get("start_date")), _parse_date(row.get("end_date"))
    return _parse_date(row.get("target_start")), _parse_date(row.get("effective_target_end") or row.get("target_end"))


def resolve_profile_targets(
    *,
    profile_id: str,
    config: dict[str, Any],
    evidence_paths: ProfileEvidencePaths,
    products: set[str],
) -> ProfileTargetResolution:
    grouped: dict[TargetKey, list[ProfileTargetRange]] = {}
    lineage_by_key: dict[TargetKey, bool] = {}
    source_by_key: dict[TargetKey, str] = {}
    role_by_key: dict[TargetKey, str] = {}
    issues: list[ProfileTargetIssue] = []

    policy = config.get("target_policy") or {}
    rules = policy.get("rules") or []
    if not rules:
        issues.append(ProfileTargetIssue(profile_id, "", "", "", "missing_target_policy", "profile_config"))
        return ProfileTargetResolution({}, tuple(issues))

    for rule in rules:
        source = _clean(rule.get("source"))
        rows = _source_rows(source, evidence_paths)
        if not rows:
            issues.append(ProfileTargetIssue(profile_id, "", "", "", "target_evidence_unavailable", source))
            continue
        role = _clean(rule.get("contract_role"))
        for row in rows:
            if not _row_matches_rule(row, rule, products):
                continue
            key = _row_identity(row, role)
            start, end = _row_range(row, source)
            if not key[1] or start is None or end is None:
                issues.append(ProfileTargetIssue(profile_id, *key, "missing_target_boundary", source))
                continue
            if start > end:
                issues.append(ProfileTargetIssue(profile_id, *key, "invalid_target_boundary", source))
                continue
            boundary_status = _clean(row.get("boundary_status") or row.get("calendar_boundary_status")) or "verified"
            grouped.setdefault(key, []).append(ProfileTargetRange(start, end, source, boundary_status))
            lineage_by_key[key] = bool(rule.get("lineage_required"))
            source_by_key[key] = source
            role_by_key[key] = role

    windows: dict[TargetKey, ProfileTargetWindow] = {}
    for key in sorted(grouped):
        ranges = tuple(sorted(set(grouped[key])))
        windows[key] = ProfileTargetWindow(
            profile_id=profile_id,
            product=key[0],
            contract=key[1],
            period=key[2],
            contract_role=role_by_key[key],
            ranges=ranges,
            target_start=min(item.start for item in ranges),
            target_end=max(item.end for item in ranges),
            lineage_required=lineage_by_key[key],
            source=source_by_key[key],
        )
    return ProfileTargetResolution(windows, tuple(issues))


__all__ = [
    "ProfileEvidencePaths",
    "ProfileTargetIssue",
    "ProfileTargetRange",
    "ProfileTargetResolution",
    "ProfileTargetWindow",
    "resolve_profile_targets",
]
