from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.data_center import ProfileActiveBinding
from app.services.data_profile_registry import ACTIVE_BINDING_STATUS
from app.services.multi_primary_rulebook import infer_contract_role
from app.services.profile_active_switch import rollback_profile_active_binding, switch_profile_active_binding
from app.services.profile_binding_candidate_generator import (
    DEFAULT_PROFILE_IDS,
    generate_profile_binding_candidates,
    load_products_file,
    write_candidate_generation_outputs,
)
from app.services.profile_binding_validator import ProfileBindingValidationError, validate_profile_binding_target
from app.services.profile_target_resolver import ProfileEvidencePaths, ProfileTargetRange
from app.services.rqdata_ingest.parquet import sha256_file


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        if path.exists():
            return
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


def _append_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    existing = _read_csv(path)
    merged = existing + rows
    _write_csv(path, merged)


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


def _enforce_read_only_transaction(session: Session) -> bool:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))
    return True


TARGET_AWARE_FIELDS = {
    "target_start",
    "target_end",
    "target_ranges",
    "coverage_start",
    "coverage_end",
    "covers_target",
    "checksum_status",
    "sealing_status",
    "lineage_status",
}


def _is_true(value: Any) -> bool:
    return _clean_text(value).lower() in {"true", "1", "yes"}


def _parse_target_ranges(value: Any) -> tuple[ProfileTargetRange, ...]:
    try:
        raw = json.loads(_clean_text(value))
        return tuple(
            ProfileTargetRange(
                start=datetime.fromisoformat(item[0]).date(),
                end=datetime.fromisoformat(item[1]).date(),
                source="binding_candidates",
            )
            for item in raw
        )
    except (TypeError, ValueError, json.JSONDecodeError, IndexError):
        return ()


def _filter_candidates(
    candidates: list[dict[str, Any]],
    *,
    profile_ids: list[str],
    products: set[str],
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    rejected_schema_rows = 0
    for row in candidates:
        if row.get("candidate_status") != "current":
            continue
        if row.get("profile_id") not in profile_ids:
            continue
        symbol = _clean_text(row.get("instrument_symbol")).lower()
        if products and symbol not in products:
            continue
        if not TARGET_AWARE_FIELDS.issubset(row) or not _is_true(row.get("covers_target")):
            rejected_schema_rows += 1
            continue
        if not _parse_target_ranges(row.get("target_ranges")):
            rejected_schema_rows += 1
            continue
        if _clean_text(row.get("checksum_status")) not in {"matched", "checksum_matched"}:
            rejected_schema_rows += 1
            continue
        if _clean_text(row.get("sealing_status")) != "verified":
            rejected_schema_rows += 1
            continue
        if _clean_text(row.get("lineage_status")) not in {"verified", "not_required"}:
            rejected_schema_rows += 1
            continue
        rows.append(row)
    return rows, rejected_schema_rows


def run_generate_mode(
    session: Session,
    *,
    profile_ids: list[str],
    products_file: Path,
    sealing_dir: Path,
    project_root: Path,
    output_dir: Path,
    multi_primary_csv: Path | None = None,
    residual_dir: Path | None = None,
    evidence_paths: ProfileEvidencePaths,
) -> dict[str, Any]:
    transaction_read_only = _enforce_read_only_transaction(session)
    products = load_products_file(products_file)
    result = generate_profile_binding_candidates(
        session,
        profile_ids=profile_ids,
        products=products,
        sealing_dir=sealing_dir,
        project_root=project_root,
        residual_dir=residual_dir,
        multi_primary_csv=multi_primary_csv,
        evidence_paths=evidence_paths,
    )
    result.summary["transaction_read_only"] = transaction_read_only
    paths = write_candidate_generation_outputs(output_dir, result)
    return {"summary": result.summary, "output_paths": {key: str(path) for key, path in paths.items()}}


def run_dry_run_mode(
    session: Session,
    *,
    profile_ids: list[str],
    products: set[str],
    candidates_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    transaction_read_only = _enforce_read_only_transaction(session)
    candidates, rejected_schema_rows = _filter_candidates(
        _read_csv(candidates_path), profile_ids=profile_ids, products=products
    )
    results: list[dict[str, Any]] = []
    would_change = 0
    errors = 0
    for row in candidates:
        profile_id = _clean_text(row.get("profile_id"))
        symbol = _clean_text(row.get("instrument_symbol"))
        contract = _clean_text(row.get("contract_code"))
        period = _clean_text(row.get("period"))
        data_version = _clean_text(row.get("data_version"))
        file_id = _parse_int(row.get("market_data_file_id"))
        contract_role = _clean_text(row.get("contract_role")) or infer_contract_role(contract)
        try:
            validate_profile_binding_target(
                session,
                profile_id=profile_id,
                instrument_symbol=symbol,
                contract_code=contract,
                period=period,
                contract_role=contract_role,
                data_version=data_version,
                market_data_file_id=file_id,
                project_root=project_root,
                target_ranges=_parse_target_ranges(row.get("target_ranges")),
                require_target_coverage=True,
                require_checksum=True,
            )
            switch_result = switch_profile_active_binding(
                session,
                profile_id=profile_id,
                instrument_symbol=symbol,
                contract_code=contract,
                period=period,
                data_version=data_version,
                market_data_file_id=file_id,
                contract_role=contract_role,
                dry_run=True,
                commit=False,
                project_root=project_root,
            )
            changed = (
                switch_result.get("previous_market_data_file_id") != switch_result.get("next_market_data_file_id")
                or switch_result.get("previous_data_version") != switch_result.get("next_data_version")
            )
            if changed:
                would_change += 1
            results.append(
                {
                    "profile_id": profile_id,
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "status": "would_change" if changed else "unchanged",
                    "previous_market_data_file_id": switch_result.get("previous_market_data_file_id"),
                    "next_market_data_file_id": switch_result.get("next_market_data_file_id"),
                }
            )
        except (ProfileBindingValidationError, ValueError) as exc:
            errors += 1
            results.append(
                {
                    "profile_id": profile_id,
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "status": "error",
                    "error": str(exc),
                }
            )
    return {
        "candidate_count": len(candidates),
        "rejected_schema_rows": rejected_schema_rows,
        "would_change": would_change,
        "unchanged": len(candidates) - would_change - errors,
        "errors": errors,
        "results": results,
        "transaction_read_only": transaction_read_only,
    }


def run_apply_mode(
    session: Session,
    *,
    profile_ids: list[str],
    products: set[str],
    candidates_path: Path,
    output_dir: Path,
    batch_id: str,
    project_root: Path,
    commit: bool = False,
    operator: str = "profile_binding_rollout",
) -> dict[str, Any]:
    candidates, rejected_schema_rows = _filter_candidates(
        _read_csv(candidates_path), profile_ids=profile_ids, products=products
    )
    apply_rows: list[dict[str, Any]] = []
    applied = 0
    skipped = 0
    errors = 0
    for row in candidates:
        profile_id = _clean_text(row.get("profile_id"))
        symbol = _clean_text(row.get("instrument_symbol"))
        contract = _clean_text(row.get("contract_code"))
        period = _clean_text(row.get("period"))
        data_version = _clean_text(row.get("data_version"))
        file_id = _parse_int(row.get("market_data_file_id"))
        contract_role = _clean_text(row.get("contract_role")) or infer_contract_role(contract)
        try:
            validate_profile_binding_target(
                session,
                profile_id=profile_id,
                instrument_symbol=symbol,
                contract_code=contract,
                period=period,
                contract_role=contract_role,
                data_version=data_version,
                market_data_file_id=file_id,
                project_root=project_root,
                target_ranges=_parse_target_ranges(row.get("target_ranges")),
                require_target_coverage=True,
                require_checksum=True,
            )
            switch_result = switch_profile_active_binding(
                session,
                profile_id=profile_id,
                instrument_symbol=symbol,
                contract_code=contract,
                period=period,
                data_version=data_version,
                market_data_file_id=file_id,
                contract_role=contract_role,
                dry_run=False,
                commit=False,
                project_root=project_root,
            )
            changed = (
                switch_result.get("previous_market_data_file_id") != switch_result.get("next_market_data_file_id")
                or switch_result.get("previous_data_version") != switch_result.get("next_data_version")
            )
            if not changed:
                skipped += 1
                continue
            applied += 1
            apply_rows.append(
                {
                    "batch_id": batch_id,
                    "profile_id": profile_id,
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "binding_id": switch_result.get("binding_id"),
                    "previous_market_data_file_id": switch_result.get("previous_market_data_file_id"),
                    "next_market_data_file_id": switch_result.get("next_market_data_file_id"),
                    "previous_data_version": switch_result.get("previous_data_version"),
                    "next_data_version": switch_result.get("next_data_version"),
                    "applied_at": datetime.now(UTC).isoformat(),
                    "operator": operator,
                    "committed": False,
                }
            )
        except (ProfileBindingValidationError, ValueError) as exc:
            session.rollback()
            errors += 1
            apply_rows.append(
                {
                    "batch_id": batch_id,
                    "profile_id": profile_id,
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "status": "error",
                    "error": str(exc),
                    "applied_at": datetime.now(UTC).isoformat(),
                    "operator": operator,
                    "committed": False,
                }
            )

    if commit and applied > 0 and errors == 0:
        session.commit()
        for row in apply_rows:
            if row.get("status") != "error":
                row["committed"] = True
    elif commit and errors > 0:
        session.rollback()

    output_dir.mkdir(parents=True, exist_ok=True)
    apply_path = output_dir / "apply_ledger.csv"
    _append_csv(apply_path, apply_rows)
    return {
        "batch_id": batch_id,
        "candidate_count": len(candidates),
        "rejected_schema_rows": rejected_schema_rows,
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "committed": commit,
        "apply_ledger": str(apply_path),
    }


def run_verify_mode(
    session: Session,
    *,
    output_dir: Path,
    batch_id: str | None,
    candidates_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    candidates, rejected_schema_rows = _filter_candidates(
        _read_csv(candidates_path), profile_ids=list(DEFAULT_PROFILE_IDS), products=set()
    )
    if batch_id:
        apply_rows = [row for row in _read_csv(output_dir / "apply_ledger.csv") if row.get("batch_id") == batch_id]
        if apply_rows:
            keys = {(row.get("profile_id"), row.get("instrument_symbol"), row.get("contract_code"), row.get("period")) for row in apply_rows}
            candidates = [
                row
                for row in candidates
                if (row.get("profile_id"), row.get("instrument_symbol"), row.get("contract_code"), row.get("period")) in keys
            ]

    duplicate_active = session.execute(
        select(
            ProfileActiveBinding.profile_id,
            ProfileActiveBinding.instrument_symbol,
            ProfileActiveBinding.contract_code,
            ProfileActiveBinding.period,
            func.count(ProfileActiveBinding.id),
        )
        .where(ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS)
        .group_by(
            ProfileActiveBinding.profile_id,
            ProfileActiveBinding.instrument_symbol,
            ProfileActiveBinding.contract_code,
            ProfileActiveBinding.period,
        )
        .having(func.count(ProfileActiveBinding.id) > 1)
    ).all()

    validator_errors: list[dict[str, Any]] = []
    checksum_rows: list[dict[str, Any]] = []
    for row in candidates:
        profile_id = _clean_text(row.get("profile_id"))
        symbol = _clean_text(row.get("instrument_symbol"))
        contract = _clean_text(row.get("contract_code"))
        period = _clean_text(row.get("period"))
        data_version = _clean_text(row.get("data_version"))
        file_id = _parse_int(row.get("market_data_file_id"))
        contract_role = _clean_text(row.get("contract_role")) or infer_contract_role(contract)
        try:
            validated = validate_profile_binding_target(
                session,
                profile_id=profile_id,
                instrument_symbol=symbol,
                contract_code=contract,
                period=period,
                contract_role=contract_role,
                data_version=data_version,
                market_data_file_id=file_id,
                project_root=project_root,
                target_ranges=_parse_target_ranges(row.get("target_ranges")),
                require_target_coverage=True,
                require_checksum=True,
            )
            file_path = Path(validated.file_path)
            resolved = file_path if file_path.is_absolute() else project_root / file_path
            checksum = sha256_file(resolved) if resolved.is_file() else ""
            checksum_rows.append(
                {
                    "profile_id": profile_id,
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "market_data_file_id": file_id,
                    "checksum": checksum,
                    "checksum_ok": bool(checksum),
                }
            )
        except ProfileBindingValidationError as exc:
            validator_errors.append(
                {
                    "profile_id": profile_id,
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "code": exc.code,
                    "message": str(exc),
                }
            )

    passed = not duplicate_active and not validator_errors and all(row.get("checksum_ok") for row in checksum_rows)
    verify_report = {
        "batch_id": batch_id,
        "candidate_count": len(candidates),
        "rejected_schema_rows": rejected_schema_rows,
        "duplicate_active_groups": len(duplicate_active),
        "validator_errors": len(validator_errors),
        "checksum_checked": len(checksum_rows),
        "passed": passed,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "verify_report.json").write_text(json.dumps(verify_report, indent=2, ensure_ascii=False), encoding="utf-8")
    if validator_errors:
        _write_csv(output_dir / "verify_validator_errors.csv", validator_errors)
    if checksum_rows:
        _write_csv(output_dir / "verify_checksum.csv", checksum_rows)
    return verify_report


def run_rollback_batch_mode(
    session: Session,
    *,
    output_dir: Path,
    batch_id: str,
    commit: bool = False,
    operator: str = "profile_binding_rollout",
) -> dict[str, Any]:
    apply_rows = [row for row in _read_csv(output_dir / "apply_ledger.csv") if row.get("batch_id") == batch_id]
    rollback_rows: list[dict[str, Any]] = []
    rolled_back = 0
    skipped = 0
    errors = 0
    pending_rollbacks: list[dict[str, Any]] = []
    for row in reversed(apply_rows):
        if row.get("status") == "error":
            skipped += 1
            continue
        profile_id = _clean_text(row.get("profile_id"))
        symbol = _clean_text(row.get("instrument_symbol"))
        contract = _clean_text(row.get("contract_code"))
        period = _clean_text(row.get("period"))
        binding_id = _parse_int(row.get("binding_id"))
        try:
            result = rollback_profile_active_binding(
                session,
                profile_id=profile_id,
                binding_id=binding_id,
                instrument_symbol=symbol or None,
                contract_code=contract or None,
                period=period or None,
                dry_run=not commit,
                commit=False,
            )
            if result.get("status") == "no_previous_binding":
                skipped += 1
                continue
            rolled_back += 1
            pending_rollbacks.append(
                {
                    "batch_id": batch_id,
                    "profile_id": profile_id,
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "rollback_from_binding_id": result.get("current_binding_id"),
                    "rollback_to_binding_id": result.get("rollback_to_binding_id"),
                    "status": result.get("status"),
                    "rolled_back_at": datetime.now(UTC).isoformat(),
                    "operator": operator,
                    "committed": False,
                }
            )
        except ValueError as exc:
            session.rollback()
            errors += 1
            pending_rollbacks.append(
                {
                    "batch_id": batch_id,
                    "profile_id": profile_id,
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "status": "error",
                    "error": str(exc),
                    "committed": False,
                }
            )

    if commit and rolled_back > 0 and errors == 0:
        session.commit()
        for row in pending_rollbacks:
            if row.get("status") != "error":
                row["status"] = "rolled_back"
                row["committed"] = True
    elif commit and errors > 0:
        session.rollback()

    rollback_rows = pending_rollbacks

    rollback_path = output_dir / "rollback_ledger.csv"
    _append_csv(rollback_path, rollback_rows)
    return {
        "batch_id": batch_id,
        "rolled_back": rolled_back,
        "skipped": skipped,
        "errors": errors,
        "committed": commit,
        "rollback_ledger": str(rollback_path),
    }


__all__ = [
    "DEFAULT_PROFILE_IDS",
    "run_apply_mode",
    "run_dry_run_mode",
    "run_generate_mode",
    "run_rollback_batch_mode",
    "run_verify_mode",
]
