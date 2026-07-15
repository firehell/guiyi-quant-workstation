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
    ClassifiedCandidate,
    GroupKey,
    ProfileRuleContext,
    classify_identity_groups,
    infer_contract_role,
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


@dataclass(frozen=True)
class CandidateGenerationResult:
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


def build_sealing_evidence_index(
    *,
    sealing_dir: Path,
    residual_dir: Path | None = None,
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
    repair_path = (residual_dir / "repair_classification.csv") if residual_dir else None
    if repair_path and repair_path.exists():
        for row in _read_csv(repair_path):
            path = _clean_text(row.get("physical_path"))
            canonical_id = _parse_int(row.get("canonical_file_id"))
            if path and canonical_id is not None:
                canonical_file_id_by_path[path] = canonical_id
            if _clean_text(row.get("anomaly_type")) == "metadata_mismatch_requires_review" and path:
                metadata_mismatch_paths.add(path)

    return SealingEvidenceIndex(
        disposition_by_path=disposition_by_path,
        disposition_by_file_id=disposition_by_file_id,
        checksum_by_path=checksum_by_path,
        physical_exists_by_path=physical_exists_by_path,
        sealing_db_file_id_by_identity=sealing_db_file_id_by_identity,
        duplicate_paths=duplicate_paths,
        canonical_file_id_by_path=canonical_file_id_by_path,
        metadata_mismatch_paths=metadata_mismatch_paths,
    )


def _market_file_to_evidence(
    market_file: MarketDataFile,
    *,
    evidence: SealingEvidenceIndex,
    project_root: Path,
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
        sealing_db_file_id=evidence.sealing_db_file_id_by_identity.get(identity),
        duplicate_disposition=_clean_text(duplicate_row.get("disposition")) if duplicate_row else "",
        canonical_file_id_hint=canonical_hint,
        metadata_passed=normalized_path not in evidence.metadata_mismatch_paths and file_path not in evidence.metadata_mismatch_paths,
        is_duplicate_path_member=is_duplicate,
    )


def _profile_product_scope(profile_id: str, products: set[str]) -> set[str] | None:
    if profile_id == "live_observation_v1":
        return {"jm"}
    return products


def _identity_in_profile_scope(
    *,
    profile_id: str,
    instrument_symbol: str,
    contract_code: str,
    period: str,
    contract_role: str,
    products: set[str],
    profile: ProfileRuleContext,
) -> bool:
    scoped_products = _profile_product_scope(profile_id, products)
    if scoped_products is not None and instrument_symbol not in scoped_products:
        return False
    if period not in profile.periods:
        return False
    if contract_role not in profile.contract_roles:
        return False
    if profile_id == "intraday_research_v1":
        return contract_role == "dominant_main" and contract_code.endswith(".MAIN")
    return True


def _iter_target_identities(
    *,
    profile_id: str,
    profile: ProfileRuleContext,
    products: set[str],
    catalog_path: Path,
) -> set[GroupKey]:
    identities: set[GroupKey] = set()
    scoped_products = _profile_product_scope(profile_id, products)
    for row in _read_csv(catalog_path):
        product = _clean_text(row.get("product")).lower()
        if scoped_products is not None and product not in scoped_products:
            continue
        contract = _clean_text(row.get("symbol_or_contract"))
        period = _clean_text(row.get("period"))
        contract_role = _clean_text(row.get("contract_role")) or infer_contract_role(contract)
        if not _identity_in_profile_scope(
            profile_id=profile_id,
            instrument_symbol=product,
            contract_code=contract,
            period=period,
            contract_role=contract_role,
            products=products,
            profile=profile,
        ):
            continue
        identities.add(GroupKey(product, contract, period))
    return identities


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
    catalog_path: Path | None = None,
    residual_dir: Path | None = None,
    multi_primary_csv: Path | None = None,
) -> CandidateGenerationResult:
    evidence = build_sealing_evidence_index(sealing_dir=sealing_dir, residual_dir=residual_dir)
    catalog = catalog_path or (sealing_dir / "target_asset_catalog.csv")
    market_files = load_market_files_for_products(session, products=products)
    grouped: dict[GroupKey, list[CandidateEvidence]] = defaultdict(list)
    for market_file in market_files:
        candidate = _market_file_to_evidence(market_file, evidence=evidence, project_root=project_root)
        if not candidate.instrument_symbol or not candidate.contract_code or not candidate.period:
            continue
        grouped[candidate.group_key()].append(candidate)

    binding_candidates: list[dict[str, Any]] = []
    blocked_ledger: list[dict[str, Any]] = []

    for profile_id in profile_ids:
        profile = load_profile_rule_context(session, profile_id=profile_id, project_root=project_root, products=products)
        target_identities = _iter_target_identities(
            profile_id=profile_id,
            profile=profile,
            products=products,
            catalog_path=catalog,
        )
        for identity in sorted(target_identities, key=lambda item: item.as_tuple()):
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
                        "evidence_source": "target_asset_catalog",
                    }
                )
                continue
            classified = classify_identity_groups({identity: group_candidates}, profile=profile)
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
        "profile_ids": profile_ids,
        "products_count": len(products),
        "binding_candidate_rows": len(binding_candidates),
        "current_rows": len(current_rows),
        "blocked_rows": len(blocked_ledger),
        "by_profile": {
            profile_id: sum(1 for row in current_rows if row.get("profile_id") == profile_id)
            for profile_id in profile_ids
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    return CandidateGenerationResult(
        binding_candidates=binding_candidates,
        blocked_ledger=blocked_ledger,
        apply_ledger=[],
        rollback_ledger=[],
        summary=summary,
    )


def write_candidate_generation_outputs(output_dir: Path, result: CandidateGenerationResult) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "binding_candidates": output_dir / "binding_candidates.csv",
        "blocked_ledger": output_dir / "blocked_ledger.csv",
        "apply_ledger": output_dir / "apply_ledger.csv",
        "rollback_ledger": output_dir / "rollback_ledger.csv",
        "summary_json": output_dir / "generation_summary.json",
        "summary_md": output_dir / "PROFILE-BINDING-GENERATION-SUMMARY.md",
    }
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
    "load_profile_rule_context",
    "write_candidate_generation_outputs",
]
