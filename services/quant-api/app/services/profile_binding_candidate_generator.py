from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import DataProfile, MarketDataFile
from app.services.multi_primary_rulebook import (
    CandidateEvidence,
    GroupKey,
    ProfileRuleContext,
    classify_identity_groups,
    infer_contract_role,
)
from app.services.profile_target_resolver import (
    ProfileEvidencePaths,
    ProfileTargetWindow,
    resolve_profile_targets,
)

DEFAULT_PROFILE_IDS = (
    "intraday_research_v1",
    "long_horizon_daily_v1",
    "live_observation_v1",
)


@dataclass(frozen=True)
class SealingEvidenceIndex:
    disposition_by_path: dict[str, str]
    disposition_by_file_id: dict[int, str]
    checksum_by_path: dict[str, str]
    physical_exists_by_path: dict[str, bool]
    sealing_db_file_id_by_identity: dict[tuple[str, str, str], int]
    duplicate_paths: dict[str, dict[str, Any]]
    canonical_file_id_by_path: dict[str, int]
    metadata_mismatch_paths: set[str]
    verified_file_ids: set[int]


@dataclass(frozen=True)
class CandidateGenerationResult:
    target_matrix: list[dict[str, Any]]
    binding_candidates: list[dict[str, Any]]
    blocked_ledger: list[dict[str, Any]]
    apply_ledger: list[dict[str, Any]]
    rollback_ledger: list[dict[str, Any]]
    summary: dict[str, Any]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_int(value: Any) -> int | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def load_products_file(path: Path) -> set[str]:
    if not path.exists():
        return set()
    products: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        product = line.strip().lower()
        if product and not product.startswith("#"):
            products.add(product)
    return products


def load_profile_rule_context(
    session: Session,
    *,
    profile_id: str,
    project_root: Path,
    products: set[str] | None = None,
) -> ProfileRuleContext:
    profile = session.scalar(select(DataProfile).where(DataProfile.profile_id == profile_id, DataProfile.is_active.is_(True)))
    if profile is None:
        raise ValueError(f"active profile not found: {profile_id}")

    config: dict[str, Any] = {}
    if profile.config_path:
        config_path = Path(profile.config_path)
        if not config_path.is_absolute():
            config_path = project_root / config_path
        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))

    excluded_paths = tuple(config.get("excluded_paths") or ["experiments/"])
    frozen_suffix = None
    frozen_baselines = config.get("frozen_baselines") or {}
    report_14 = frozen_baselines.get("report_14_reference") or {}
    frozen_suffix = _clean_text(report_14.get("data_version_suffix")) or None

    return ProfileRuleContext(
        profile_id=profile_id,
        periods=tuple(profile.periods or []),
        contract_roles=tuple(profile.contract_roles or []),
        quality_policy=profile.quality_policy,
        provider=profile.provider,
        excluded_path_fragments=excluded_paths,
        frozen_baseline_suffix=frozen_suffix,
    )


def load_profile_config(session: Session, *, profile_id: str, project_root: Path) -> dict[str, Any]:
    profile = session.scalar(select(DataProfile).where(DataProfile.profile_id == profile_id, DataProfile.is_active.is_(True)))
    if profile is None:
        raise ValueError(f"active profile not found: {profile_id}")
    if not profile.config_path:
        return {}
    config_path = Path(profile.config_path)
    if not config_path.is_absolute():
        config_path = project_root / config_path
    if not config_path.is_file():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def build_sealing_evidence_index(
    *,
    sealing_dir: Path,
    residual_dir: Path | None = None,
    physical_inventory_path: Path | None = None,
) -> SealingEvidenceIndex:
    disposition_by_path: dict[str, str] = {}
    disposition_by_file_id: dict[int, str] = {}
    for row in _read_csv(sealing_dir / "disposition_register.csv"):
        path = _clean_text(row.get("standard_path"))
        disposition = _clean_text(row.get("disposition"))
        if path:
            disposition_by_path[path] = disposition

    checksum_by_path: dict[str, str] = {}
    for row in _read_csv(sealing_dir / "checksum_matrix.csv"):
        path = _clean_text(row.get("physical_path"))
        checksum_by_path[path] = _clean_text(row.get("checksum_status"))

    physical_exists_by_path: dict[str, bool] = {}
    for row in _read_csv(sealing_dir / "asset_physical_inventory.csv"):
        path = _clean_text(row.get("physical_path"))
        physical_exists_by_path[path] = _clean_text(row.get("physical_exists")).lower() == "true"

    sealing_db_file_id_by_identity: dict[tuple[str, str, str], int] = {}
    for row in _read_csv(sealing_dir / "target_coverage_matrix.csv"):
        if _clean_text(row.get("sealing_status")) != "sealing_passed":
            continue
        symbol = _clean_text(row.get("product")).lower()
        contract = _clean_text(row.get("symbol_or_contract"))
        period = _clean_text(row.get("period"))
        file_id = _parse_int(row.get("db_market_data_file_id"))
        if symbol and contract and period and file_id is not None:
            sealing_db_file_id_by_identity[(symbol, contract, period)] = file_id

    duplicate_paths: dict[str, dict[str, Any]] = {}
    for row in _read_csv(sealing_dir / "duplicate_inventory.csv"):
        path = _clean_text(row.get("physical_path"))
        if path:
            duplicate_paths[path] = row

    canonical_file_id_by_path: dict[str, int] = {}
    metadata_mismatch_paths: set[str] = set()
    verified_file_ids: set[int] = set()
    repair_path = (residual_dir / "repair_classification.csv") if residual_dir else None
    if repair_path and repair_path.exists():
        for row in _read_csv(repair_path):
            path = _clean_text(row.get("physical_path"))
            canonical_id = _parse_int(row.get("canonical_file_id"))
            if path and canonical_id is not None:
                canonical_file_id_by_path[path] = canonical_id
            if _clean_text(row.get("anomaly_type")) == "metadata_mismatch_requires_review" and path:
                metadata_mismatch_paths.add(path)

    if physical_inventory_path and physical_inventory_path.is_file():
        for row in _read_csv(physical_inventory_path):
            path = _clean_text(row.get("physical_path"))
            if not path:
                continue
            physical_ok = _clean_text(row.get("physical_exists")).lower() == "true"
            checksum_ok = _clean_text(row.get("checksum_status")) in {"matched", "checksum_matched"}
            schema_ok = _clean_text(row.get("schema_status")) == "schema_ok"
            consistency_ok = _clean_text(row.get("schema_consistency_status")) in {"", "consistent"}
            identity_ok = _clean_text(row.get("identity_conflict")).lower() != "true"
            physical_exists_by_path[path] = physical_ok
            if checksum_ok:
                checksum_by_path[path] = "checksum_matched"
            if physical_ok and checksum_ok and schema_ok and consistency_ok and identity_ok:
                try:
                    file_ids = json.loads(_clean_text(row.get("market_data_file_ids")) or "[]")
                except json.JSONDecodeError:
                    file_ids = []
                verified_file_ids.update(int(item) for item in file_ids if str(item).isdigit())

    return SealingEvidenceIndex(
        disposition_by_path=disposition_by_path,
        disposition_by_file_id=disposition_by_file_id,
        checksum_by_path=checksum_by_path,
        physical_exists_by_path=physical_exists_by_path,
        sealing_db_file_id_by_identity=sealing_db_file_id_by_identity,
        duplicate_paths=duplicate_paths,
        canonical_file_id_by_path=canonical_file_id_by_path,
        metadata_mismatch_paths=metadata_mismatch_paths,
        verified_file_ids=verified_file_ids,
    )


def _market_file_to_evidence(
    market_file: MarketDataFile,
    *,
    evidence: SealingEvidenceIndex,
    project_root: Path,
    lineage_by_file_id: dict[int, bool] | None = None,
) -> CandidateEvidence:
    file_path = _clean_text(market_file.file_path)
    resolved = Path(file_path)
    if not resolved.is_absolute():
        resolved = project_root / resolved
    normalized_path = str(resolved)
    duplicate_row = evidence.duplicate_paths.get(normalized_path) or evidence.duplicate_paths.get(file_path)
    is_duplicate = duplicate_row is not None
    canonical_hint = evidence.canonical_file_id_by_path.get(normalized_path) or evidence.canonical_file_id_by_path.get(file_path)
    disposition = evidence.disposition_by_path.get(normalized_path) or evidence.disposition_by_path.get(file_path, "")
    if not disposition and duplicate_row:
        disposition = _clean_text(duplicate_row.get("disposition"))
    identity = (
        _clean_text(market_file.instrument_symbol).lower(),
        _clean_text(market_file.contract_code),
        _clean_text(market_file.period),
    )
    return CandidateEvidence(
        market_data_file_id=market_file.id,
        instrument_symbol=identity[0],
        contract_code=identity[1],
        period=identity[2],
        contract_role=infer_contract_role(identity[1]),
        data_version=_clean_text(market_file.data_version),
        file_path=file_path,
        quality_status=_clean_text(market_file.quality_status),
        provider=_clean_text(market_file.provider),
        data_role=_clean_text(market_file.data_role),
        start_time=market_file.start_time,
        end_time=market_file.end_time,
        row_count=market_file.row_count,
        disposition=disposition,
        checksum_status=evidence.checksum_by_path.get(normalized_path)
        or evidence.checksum_by_path.get(file_path, ""),
        physical_exists=evidence.physical_exists_by_path.get(normalized_path, evidence.physical_exists_by_path.get(file_path, True)),
        sealing_db_file_id=market_file.id
        if market_file.id in evidence.verified_file_ids
        else evidence.sealing_db_file_id_by_identity.get(identity),
        duplicate_disposition=_clean_text(duplicate_row.get("disposition")) if duplicate_row else "",
        canonical_file_id_hint=canonical_hint,
        metadata_passed=normalized_path not in evidence.metadata_mismatch_paths and file_path not in evidence.metadata_mismatch_paths,
        is_duplicate_path_member=is_duplicate,
        checksum=_clean_text(market_file.checksum),
        normalized_path=normalized_path,
        lineage_verified=(lineage_by_file_id or {}).get(market_file.id, market_file.period == "1m"),
        source_interval_verified=(lineage_by_file_id or {}).get(market_file.id, market_file.period == "1m"),
    )


def _profile_product_scope(profile_id: str, products: set[str]) -> set[str] | None:
    if profile_id == "live_observation_v1":
        return {"jm"}
    return products


def load_market_files_for_products(
    session: Session,
    *,
    products: set[str],
) -> list[MarketDataFile]:
    if not products:
        return []
    return list(
        session.scalars(
            select(MarketDataFile).where(
                MarketDataFile.provider == "rqdata",
                MarketDataFile.data_role == "primary",
                MarketDataFile.quality_status != "failed",
                MarketDataFile.instrument_symbol.in_(sorted(products)),
            )
        )
    )


def generate_profile_binding_candidates(
    session: Session,
    *,
    profile_ids: list[str],
    products: set[str],
    sealing_dir: Path,
    project_root: Path,
    evidence_paths: ProfileEvidencePaths,
    residual_dir: Path | None = None,
    multi_primary_csv: Path | None = None,
) -> CandidateGenerationResult:
    evidence = build_sealing_evidence_index(
        sealing_dir=sealing_dir,
        residual_dir=residual_dir,
        physical_inventory_path=evidence_paths.physical_inventory,
    )
    lineage_by_file_id: dict[int, bool] = {}
    if evidence_paths.derived_inventory and evidence_paths.derived_inventory.is_file():
        for row in _read_csv(evidence_paths.derived_inventory):
            file_id = _parse_int(row.get("derived_file_id"))
            if file_id is not None:
                lineage_by_file_id[file_id] = (
                    _clean_text(row.get("lineage_status")) == "verified"
                    and _clean_text(row.get("source_interval")) == "1m"
                    and _clean_text(row.get("source_1m_quality")) == "passed"
                    and _clean_text(row.get("checksum_status")) in {"matched", "checksum_matched"}
                )
    market_files = load_market_files_for_products(session, products=products)
    grouped: dict[GroupKey, list[CandidateEvidence]] = defaultdict(list)
    for market_file in market_files:
        candidate = _market_file_to_evidence(
            market_file,
            evidence=evidence,
            project_root=project_root,
            lineage_by_file_id=lineage_by_file_id,
        )
        if not candidate.instrument_symbol or not candidate.contract_code or not candidate.period:
            continue
        grouped[candidate.group_key()].append(candidate)

    binding_candidates: list[dict[str, Any]] = []
    blocked_ledger: list[dict[str, Any]] = []
    target_matrix: list[dict[str, Any]] = []
    target_resolution_issue_count = 0

    for profile_id in profile_ids:
        profile = load_profile_rule_context(session, profile_id=profile_id, project_root=project_root, products=products)
        config = load_profile_config(session, profile_id=profile_id, project_root=project_root)
        target_resolution = resolve_profile_targets(
            profile_id=profile_id,
            config=config,
            evidence_paths=evidence_paths,
            products=_profile_product_scope(profile_id, products) or products,
        )
        for issue in target_resolution.issues:
            target_resolution_issue_count += 1
            blocked_ledger.append(
                {
                    "profile_id": issue.profile_id,
                    "instrument_symbol": issue.product,
                    "contract_code": issue.contract,
                    "period": issue.period,
                    "group_key": "|".join((issue.product, issue.contract, issue.period)),
                    "block_reason": issue.reason,
                    "market_data_file_id": "",
                    "evidence_source": issue.evidence_source,
                }
            )
        targets: dict[GroupKey, ProfileTargetWindow] = {
            GroupKey(*key): value for key, value in target_resolution.windows.items()
        }
        for identity, target in sorted(targets.items(), key=lambda item: item[0].as_tuple()):
            target_matrix.append(
                {
                    "profile_id": profile_id,
                    "instrument_symbol": identity.instrument_symbol,
                    "contract_code": identity.contract_code,
                    "period": identity.period,
                    "contract_role": target.contract_role,
                    "target_start": target.target_start.isoformat(),
                    "target_end": target.target_end.isoformat(),
                    "target_ranges": json.dumps(
                        [(item.start.isoformat(), item.end.isoformat()) for item in target.ranges],
                        separators=(",", ":"),
                    ),
                    "lineage_required": target.lineage_required,
                    "evidence_source": target.source,
                }
            )
        for identity in sorted(targets, key=lambda item: item.as_tuple()):
            target = targets[identity]
            group_candidates = grouped.get(identity, [])
            if not group_candidates:
                blocked_ledger.append(
                    {
                        "profile_id": profile_id,
                        "instrument_symbol": identity.instrument_symbol,
                        "contract_code": identity.contract_code,
                        "period": identity.period,
                        "group_key": "|".join(identity.as_tuple()),
                        "block_reason": "no_primary_candidates",
                        "evidence_source": target.source,
                    }
                )
                continue
            classified = classify_identity_groups(
                {identity: group_candidates},
                profile=profile,
                targets={identity: target},
            )
            for row in classified:
                payload = {
                    "profile_id": row.profile_id,
                    "instrument_symbol": row.instrument_symbol,
                    "contract_code": row.contract_code,
                    "period": row.period,
                    "contract_role": row.contract_role,
                    "candidate_status": row.candidate_status,
                    "market_data_file_id": row.market_data_file_id or "",
                    "data_version": row.data_version,
                    "rulebook_rank": row.rulebook_rank,
                    "block_reason": row.block_reason,
                    "file_path": row.file_path,
                    "quality_status": row.quality_status,
                    "disposition": row.disposition,
                    "evidence_source": row.evidence_source,
                    "target_start": row.target_start,
                    "target_end": row.target_end,
                    "target_ranges": json.dumps(row.target_ranges, separators=(",", ":")),
                    "coverage_start": row.coverage_start,
                    "coverage_end": row.coverage_end,
                    "covers_target": row.covers_target,
                    "selection_reason": row.selection_reason,
                    "checksum_status": row.checksum_status,
                    "sealing_status": row.sealing_status,
                    "lineage_status": row.lineage_status,
                }
                binding_candidates.append(payload)
                if row.candidate_status == "blocked":
                    blocked_ledger.append(
                        {
                            "profile_id": row.profile_id,
                            "instrument_symbol": row.instrument_symbol,
                            "contract_code": row.contract_code,
                            "period": row.period,
                            "group_key": "|".join(identity.as_tuple()),
                            "block_reason": row.block_reason,
                            "market_data_file_id": row.market_data_file_id or "",
                            "evidence_source": row.evidence_source,
                        }
                    )

    if multi_primary_csv and multi_primary_csv.exists():
        for row in _read_csv(multi_primary_csv):
            symbol = _clean_text(row.get("instrument_symbol")).lower()
            contract = _clean_text(row.get("contract_code"))
            period = _clean_text(row.get("period"))
            if symbol and contract and period:
                continue
            blocked_ledger.append(
                {
                    "profile_id": "*",
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "group_key": "|".join((symbol, contract, period)),
                    "block_reason": "invalid_multi_primary_identity",
                    "market_data_file_id": "",
                    "evidence_source": str(multi_primary_csv),
                }
            )

    current_rows = [row for row in binding_candidates if row.get("candidate_status") == "current"]
    summary = {
        "status": "PROFILE_FULL_HISTORY_SELECTION_READY"
        if target_resolution_issue_count == 0 and current_rows
        else "PROFILE_TARGET_EVIDENCE_BLOCKED",
        "profile_ids": profile_ids,
        "products_count": len(products),
        "binding_candidate_rows": len(binding_candidates),
        "current_rows": len(current_rows),
        "blocked_rows": len(blocked_ledger),
        "target_rows": len(target_matrix),
        "current_covering_rows": sum(
            1 for row in current_rows if row.get("covers_target") is True
        ),
        "incomplete_coverage_rows": sum(
            1 for row in binding_candidates if row.get("block_reason") == "target_coverage_incomplete"
        ),
        "conflict_rows": sum(
            1
            for row in binding_candidates
            if row.get("block_reason") in {"conflicting_duplicate_candidates", "duplicate_canonical_conflict"}
        ),
        "frozen_reference_rows": sum(
            1 for row in binding_candidates if row.get("block_reason") == "frozen_baseline_reference"
        ),
        "by_profile": {
            profile_id: sum(1 for row in current_rows if row.get("profile_id") == profile_id)
            for profile_id in profile_ids
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "target_resolution_issue_count": target_resolution_issue_count,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "binding_apply_executed": False,
        "calls_rqdata": False,
        "report_id_14_modified": False,
    }
    return CandidateGenerationResult(
        target_matrix=target_matrix,
        binding_candidates=binding_candidates,
        blocked_ledger=blocked_ledger,
        apply_ledger=[],
        rollback_ledger=[],
        summary=summary,
    )


def write_candidate_generation_outputs(output_dir: Path, result: CandidateGenerationResult) -> dict[str, Path]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"profile candidate output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "target_matrix": output_dir / "target_matrix.csv",
        "binding_candidates": output_dir / "binding_candidates.csv",
        "blocked_ledger": output_dir / "blocked_ledger.csv",
        "apply_ledger": output_dir / "apply_ledger.csv",
        "rollback_ledger": output_dir / "rollback_ledger.csv",
        "summary_json": output_dir / "generation_summary.json",
        "summary_md": output_dir / "PROFILE-BINDING-GENERATION-SUMMARY.md",
    }
    _write_csv(paths["target_matrix"], result.target_matrix)
    _write_csv(paths["binding_candidates"], result.binding_candidates)
    _write_csv(paths["blocked_ledger"], result.blocked_ledger)
    _write_csv(paths["apply_ledger"], result.apply_ledger)
    _write_csv(paths["rollback_ledger"], result.rollback_ledger)
    paths["summary_json"].write_text(json.dumps(result.summary, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_lines = [
        "# Profile Binding Generation Summary",
        "",
        f"- binding_candidate_rows: {result.summary['binding_candidate_rows']}",
        f"- current_rows: {result.summary['current_rows']}",
        f"- blocked_rows: {result.summary['blocked_rows']}",
        f"- by_profile: `{json.dumps(result.summary['by_profile'], ensure_ascii=False)}`",
        f"- status: `{result.summary['status']}`",
        "",
    ]
    paths["summary_md"].write_text("\n".join(summary_lines), encoding="utf-8")
    return paths


__all__ = [
    "CandidateGenerationResult",
    "SealingEvidenceIndex",
    "build_sealing_evidence_index",
    "generate_profile_binding_candidates",
    "load_products_file",
    "load_profile_config",
    "load_profile_rule_context",
    "write_candidate_generation_outputs",
]
