from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.data_center import ProfileActiveBinding
from app.services.data_profile_registry import ACTIVE_BINDING_STATUS, DataProfileRegistry
from app.services.market_data_reader import ACTIVE_PRIMARY_PROVIDERS, MarketDataReader
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_optional_int(row: dict[str, Any], field: str) -> tuple[bool, int | None]:
    if field not in row:
        return False, None
    raw = _clean_text(row[field])
    if not raw:
        return True, None
    parsed = _parse_int(raw)
    return parsed is not None, parsed


def _strict_required_int(row: dict[str, Any], field: str) -> tuple[bool, int | None]:
    present, value = _strict_optional_int(row, field)
    return present and value is not None, value


def _identity(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _clean_text(row.get("profile_id")),
        _clean_text(row.get("instrument_symbol")),
        _clean_text(row.get("contract_code")),
        _clean_text(row.get("period")),
    )


def _active_bindings_for_identity(session: Session, row: dict[str, Any]) -> list[ProfileActiveBinding]:
    profile_id, symbol, contract, period = _identity(row)
    return list(
        session.scalars(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == profile_id,
                ProfileActiveBinding.instrument_symbol == symbol,
                ProfileActiveBinding.contract_code == contract,
                ProfileActiveBinding.period == period,
                ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
            )
        )
    )


def _validate_apply_before_state(
    session: Session,
    candidates: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
    *,
    expected_before_required: bool,
) -> list[dict[str, Any]]:
    expected_by_identity: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    candidate_identities = [_identity(row) for row in candidates]
    if len(candidate_identities) != len(set(candidate_identities)):
        errors.append({"identity": (), "error": "duplicate_candidate_identity"})
    for row in expected_rows:
        identity = _identity(row)
        if identity in expected_by_identity:
            errors.append({"identity": identity, "error": "duplicate_expected_before_identity"})
        expected_by_identity[identity] = row
    if expected_before_required and set(expected_by_identity) != set(candidate_identities):
        errors.append(
            {
                "identity": (),
                "error": "expected_before_identity_set_mismatch",
                "missing": sorted(set(candidate_identities) - set(expected_by_identity)),
                "extra": sorted(set(expected_by_identity) - set(candidate_identities)),
            }
        )
    for candidate in candidates:
        identity = _identity(candidate)
        active = _active_bindings_for_identity(session, candidate)
        if len(active) > 1:
            errors.append({"identity": identity, "error": "multiple_active_bindings"})
            continue
        if not expected_before_required:
            continue
        expected = expected_by_identity.get(identity)
        if expected is None:
            errors.append({"identity": identity, "error": "missing_expected_before_state"})
            continue
        current = active[0] if active else None
        prior_binding_ok, expected_binding_id = _strict_optional_int(expected, "previous_binding_id")
        prior_file_ok, expected_file_id = _strict_optional_int(expected, "previous_market_data_file_id")
        next_file_ok, expected_next_file_id = _strict_required_int(expected, "next_market_data_file_id")
        required_text_fields = {field: field in expected for field in ("previous_data_version", "next_data_version")}
        if not prior_binding_ok or not prior_file_ok or not next_file_ok or not all(required_text_fields.values()):
            errors.append({"identity": identity, "error": "invalid_expected_before_schema"})
            continue
        expected_version = _clean_text(expected["previous_data_version"])
        expected_next_version = _clean_text(expected["next_data_version"])
        if not expected_next_version:
            errors.append({"identity": identity, "error": "invalid_expected_next_version"})
            continue
        candidate_file_id = _parse_int(candidate.get("market_data_file_id"))
        candidate_version = _clean_text(candidate.get("data_version"))
        if (expected_next_file_id, expected_next_version) != (candidate_file_id, candidate_version):
            errors.append({"identity": identity, "error": "expected_after_candidate_mismatch"})
            continue
        actual = (
            current.id if current else None,
            current.market_data_file_id if current else None,
            current.data_version if current else "",
        )
        expected_values = (expected_binding_id, expected_file_id, expected_version)
        if actual != expected_values:
            errors.append(
                {
                    "identity": identity,
                    "error": "before_state_drift",
                    "expected": expected_values,
                    "actual": actual,
                }
            )
    return errors


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
    expected_before_path: Path | None = None,
    expected_before_sha256: str | None = None,
    expected_candidates_sha256: str | None = None,
    expected_operation_count: int | None = None,
    commit: bool = False,
    operator: str = "profile_binding_rollout",
) -> dict[str, Any]:
    candidates, rejected_schema_rows = _filter_candidates(
        _read_csv(candidates_path), profile_ids=profile_ids, products=products
    )
    candidate_sha256 = _sha256_file(candidates_path) if candidates_path.is_file() else ""
    expected_rows = _read_csv(expected_before_path) if expected_before_path else []
    before_sha256 = _sha256_file(expected_before_path) if expected_before_path and expected_before_path.is_file() else ""
    expected_by_identity = {_identity(row): row for row in expected_rows}
    before_state_errors = _validate_apply_before_state(
        session,
        candidates,
        expected_rows,
        expected_before_required=expected_before_path is not None,
    )
    if rejected_schema_rows:
        before_state_errors.append({"identity": (), "error": "rejected_candidate_schema_rows"})
    if commit:
        if not candidates:
            before_state_errors.append({"identity": (), "error": "zero_candidates"})
        if expected_before_path is None:
            before_state_errors.append({"identity": (), "error": "expected_before_path_required"})
        if not expected_before_sha256:
            before_state_errors.append({"identity": (), "error": "expected_before_sha256_required"})
        elif before_sha256 != expected_before_sha256:
            before_state_errors.append({"identity": (), "error": "expected_before_sha256_mismatch"})
        if not expected_candidates_sha256:
            before_state_errors.append({"identity": (), "error": "expected_candidates_sha256_required"})
        elif candidate_sha256 != expected_candidates_sha256:
            before_state_errors.append({"identity": (), "error": "candidate_sha256_mismatch"})
        if expected_operation_count is None:
            before_state_errors.append({"identity": (), "error": "expected_operation_count_required"})
        elif len(candidates) != expected_operation_count:
            before_state_errors.append({"identity": (), "error": "candidate_operation_count_mismatch"})
        if any(row.get("batch_id") == batch_id for row in _read_csv(output_dir / "apply_ledger.csv")):
            before_state_errors.append({"identity": (), "error": "batch_id_already_used"})
    if before_state_errors:
        session.rollback()
        output_dir.mkdir(parents=True, exist_ok=True)
        apply_path = output_dir / "apply_ledger.csv"
        now = datetime.now(UTC).isoformat()
        rows = [
            {
                "batch_id": batch_id,
                "status": "error",
                "error": item["error"],
                "identity": json.dumps(item["identity"], ensure_ascii=False),
                "details": json.dumps(item, ensure_ascii=False),
                "applied_at": now,
                "operator": operator,
                "committed": False,
                "candidate_sha256": candidate_sha256,
                "candidate_count": len(candidates),
            }
            for item in before_state_errors
        ]
        _append_csv(apply_path, rows)
        return {
            "batch_id": batch_id,
            "candidate_count": len(candidates),
            "rejected_schema_rows": rejected_schema_rows,
            "applied": 0,
            "skipped": 0,
            "errors": len(before_state_errors),
            "committed": False,
            "transaction_rolled_back": True,
            "apply_ledger": str(apply_path),
        }
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
            expected = expected_by_identity.get(_identity(row), {})
            previous_binding_id = _parse_int(expected.get("previous_binding_id"))
            previous_file_id = _parse_int(expected.get("previous_market_data_file_id"))
            previous_version = _clean_text(expected.get("previous_data_version"))
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
                expected_previous_binding_id=previous_binding_id,
                expected_previous_market_data_file_id=previous_file_id,
                expected_previous_data_version=previous_version,
                enforce_expected_previous=commit,
            )
            changed = (
                switch_result.get("previous_market_data_file_id") != switch_result.get("next_market_data_file_id")
                or switch_result.get("previous_data_version") != switch_result.get("next_data_version")
            )
            if not changed:
                skipped += 1
                continue
            new_binding = session.get(ProfileActiveBinding, switch_result.get("binding_id"))
            if (
                new_binding is None
                or new_binding.market_data_file_id != file_id
                or new_binding.data_version != data_version
                or new_binding.binding_status != ACTIVE_BINDING_STATUS
            ):
                raise ValueError("applied binding does not match the approved after file/version")
            applied += 1
            apply_rows.append(
                {
                    "batch_id": batch_id,
                    "profile_id": profile_id,
                    "instrument_symbol": symbol,
                    "contract_code": contract,
                    "period": period,
                    "binding_id": switch_result.get("binding_id"),
                    "previous_binding_id": switch_result.get("previous_binding_id"),
                    "previous_market_data_file_id": switch_result.get("previous_market_data_file_id"),
                    "next_market_data_file_id": switch_result.get("next_market_data_file_id"),
                    "previous_data_version": switch_result.get("previous_data_version"),
                    "next_data_version": switch_result.get("next_data_version"),
                    "applied_at": datetime.now(UTC).isoformat(),
                    "operator": operator,
                    "committed": False,
                    "candidate_sha256": candidate_sha256,
                    "expected_before_sha256": before_sha256,
                    "candidate_count": len(candidates),
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
                    "candidate_sha256": candidate_sha256,
                    "expected_before_sha256": before_sha256,
                    "candidate_count": len(candidates),
                }
            )

    if commit and applied > 0 and errors == 0:
        session.commit()
        for row in apply_rows:
            if row.get("status") != "error":
                row["committed"] = True
    elif errors > 0:
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
        "committed": commit and errors == 0 and applied > 0,
        "transaction_rolled_back": errors > 0,
        "candidate_sha256": candidate_sha256,
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
    ledger_errors: list[str] = []
    if batch_id:
        apply_rows = [row for row in _read_csv(output_dir / "apply_ledger.csv") if row.get("batch_id") == batch_id]
        committed_rows = [row for row in apply_rows if row.get("status") != "error" and _is_true(row.get("committed"))]
        if not committed_rows:
            ledger_errors.append("no_committed_apply_rows")
        if any(row.get("status") == "error" or not _is_true(row.get("committed")) for row in apply_rows):
            ledger_errors.append("batch_contains_error_or_uncommitted_rows")
        keys = [_identity(row) for row in committed_rows]
        if len(keys) != len(set(keys)):
            ledger_errors.append("duplicate_committed_identity")
        candidates = [row for row in candidates if _identity(row) in set(keys)]

    candidate_identities = [_identity(row) for row in candidates]
    if not candidates:
        ledger_errors.append("zero_candidates")
    if len(candidate_identities) != len(set(candidate_identities)):
        ledger_errors.append("duplicate_candidate_identity")
    if rejected_schema_rows:
        ledger_errors.append("rejected_candidate_schema_rows")

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
            active = _active_bindings_for_identity(session, row)
            if len(active) != 1:
                raise ProfileBindingValidationError(
                    "active_binding_count_mismatch",
                    f"expected exactly one active binding, found {len(active)}",
                )
            if active[0].market_data_file_id != file_id or active[0].data_version != data_version:
                raise ProfileBindingValidationError(
                    "active_binding_candidate_mismatch",
                    "active binding does not point to the frozen candidate file/version",
                )
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
                    "checksum_ok": bool(checksum) and checksum == validated.checksum,
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

    passed = (
        not ledger_errors
        and not duplicate_active
        and not validator_errors
        and bool(checksum_rows)
        and all(row.get("checksum_ok") for row in checksum_rows)
    )
    verify_report = {
        "batch_id": batch_id,
        "candidate_count": len(candidates),
        "rejected_schema_rows": rejected_schema_rows,
        "duplicate_active_groups": len(duplicate_active),
        "validator_errors": len(validator_errors),
        "checksum_checked": len(checksum_rows),
        "ledger_errors": ledger_errors,
        "passed": passed,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "verify_report.json").write_text(json.dumps(verify_report, indent=2, ensure_ascii=False), encoding="utf-8")
    if validator_errors:
        _write_csv(output_dir / "verify_validator_errors.csv", validator_errors)
    if checksum_rows:
        _write_csv(output_dir / "verify_checksum.csv", checksum_rows)
    return verify_report


def _parse_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(_clean_text(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _coverage_contains(*, start: datetime, end: datetime, coverage_start: datetime, coverage_end: datetime, period: str) -> bool:
    if period in {"1d", "1w"}:
        return coverage_start.date() <= start.date() and coverage_end.date() >= end.date()
    return _as_utc(coverage_start) <= start and _as_utc(coverage_end) >= end


def run_golden_query_mode(
    session: Session,
    *,
    queries_path: Path,
    output_dir: Path,
    project_root: Path,
) -> dict[str, Any]:
    """Run historical Profile reads through the canonical registry and reader only."""

    queries = _read_csv(queries_path)
    registry = DataProfileRegistry(session, project_root=project_root)
    reader = MarketDataReader(session, project_root=project_root)
    results: list[dict[str, Any]] = []
    for query in queries:
        profile_id, symbol, contract, period = _identity(query)
        query_id = _clean_text(query.get("query_id")) or ":".join((profile_id, symbol, contract, period))
        row: dict[str, Any] = {
            "query_id": query_id,
            "profile_id": profile_id,
            "instrument_symbol": symbol,
            "contract_code": contract,
            "period": period,
            "historical_only": True,
            "status": "error",
        }
        try:
            start = _parse_datetime(query.get("start"))
            end = _parse_datetime(query.get("end"))
            if start > end:
                raise ValueError("golden query start is after end")
            market_file = registry.resolve_active_market_file(
                profile_id=profile_id,
                instrument_symbol=symbol,
                contract_code=contract,
                period=period,
            )
            if market_file is None:
                raise ValueError("profile active binding did not resolve a market data file")
            expected_file_id = _parse_int(query.get("expected_market_data_file_id"))
            expected_version = _clean_text(query.get("expected_data_version"))
            path = Path(market_file.file_path)
            resolved_path = path if path.is_absolute() else project_root / path
            checksum_actual = sha256_file(resolved_path) if resolved_path.is_file() else ""
            bars = reader.load_bars(
                symbol=symbol,
                contract=contract,
                period=period,
                start=start,
                end=end,
                profile_id=profile_id,
                passed_only=True,
            )
            boundary_fields = (
                "expected_first_datetime",
                "expected_last_datetime",
                "expected_first_trading_day",
                "expected_last_trading_day",
            )
            boundary_schema_ok = all(field in query and _clean_text(query[field]) for field in boundary_fields)
            actual_first_datetime = bars[0]["datetime"] if bars else None
            actual_last_datetime = bars[-1]["datetime"] if bars else None
            actual_first_trading_day = bars[0]["trading_day"] if bars else None
            actual_last_trading_day = bars[-1]["trading_day"] if bars else None
            datetime_boundary_ok = bool(
                bars
                and boundary_schema_ok
                and _as_utc(actual_first_datetime) == _parse_datetime(query["expected_first_datetime"])
                and _as_utc(actual_last_datetime) == _parse_datetime(query["expected_last_datetime"])
            )
            trading_day_boundary_ok = bool(
                bars
                and boundary_schema_ok
                and str(actual_first_trading_day) == _clean_text(query["expected_first_trading_day"])
                and str(actual_last_trading_day) == _clean_text(query["expected_last_trading_day"])
            )
            binding = session.scalar(
                select(ProfileActiveBinding).where(
                    ProfileActiveBinding.profile_id == profile_id,
                    ProfileActiveBinding.instrument_symbol == symbol,
                    ProfileActiveBinding.contract_code == contract,
                    ProfileActiveBinding.period == period,
                    ProfileActiveBinding.binding_status == ACTIVE_BINDING_STATUS,
                )
            )
            checks = {
                "binding_lineage_ok": binding is not None and binding.market_data_file_id == market_file.id,
                "expected_file_ok": expected_file_id is None or expected_file_id == market_file.id,
                "expected_version_ok": not expected_version or expected_version == market_file.data_version,
                "provider_ok": market_file.provider in ACTIVE_PRIMARY_PROVIDERS,
                "data_role_ok": market_file.data_role == "primary",
                "quality_ok": market_file.quality_status == "passed",
                "coverage_ok": _coverage_contains(
                    start=start,
                    end=end,
                    coverage_start=market_file.start_time,
                    coverage_end=market_file.end_time,
                    period=period,
                ),
                "checksum_ok": bool(checksum_actual) and checksum_actual == market_file.checksum,
                "nonempty_bars": bool(bars),
                "boundary_schema_ok": boundary_schema_ok,
                "datetime_boundary_ok": datetime_boundary_ok,
                "trading_day_boundary_ok": trading_day_boundary_ok,
            }
            row.update(
                {
                    "resolved_market_data_file_id": market_file.id,
                    "resolved_data_version": market_file.data_version,
                    "provider": market_file.provider,
                    "data_role": market_file.data_role,
                    "quality_status": market_file.quality_status,
                    "coverage_start": market_file.start_time.isoformat(),
                    "coverage_end": market_file.end_time.isoformat(),
                    "checksum_actual": checksum_actual,
                    "row_count": len(bars),
                    "actual_first_datetime": actual_first_datetime.isoformat() if actual_first_datetime else "",
                    "actual_last_datetime": actual_last_datetime.isoformat() if actual_last_datetime else "",
                    "actual_first_trading_day": str(actual_first_trading_day) if actual_first_trading_day else "",
                    "actual_last_trading_day": str(actual_last_trading_day) if actual_last_trading_day else "",
                    **checks,
                    "status": "passed" if all(checks.values()) else "failed",
                }
            )
        except (OSError, TypeError, ValueError) as exc:
            row["error"] = str(exc)
        results.append(row)

    passed = bool(results) and all(row.get("status") == "passed" for row in results)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "golden_query_results.csv"
    _write_csv(path, results)
    return {
        "query_count": len(results),
        "passed": passed,
        "results": results,
        "golden_query_results": str(path),
        "reads_live_table": False,
        "writes_database": False,
    }


def run_rollback_batch_mode(
    session: Session,
    *,
    output_dir: Path,
    batch_id: str,
    commit: bool = False,
    restore_absent: bool = False,
    expected_candidates_path: Path | None = None,
    expected_candidates_sha256: str | None = None,
    expected_operation_count: int | None = None,
    operator: str = "profile_binding_rollout",
) -> dict[str, Any]:
    apply_rows = [row for row in _read_csv(output_dir / "apply_ledger.csv") if row.get("batch_id") == batch_id]
    rollback_path = output_dir / "rollback_ledger.csv"
    existing_rollback_rows = [row for row in _read_csv(rollback_path) if row.get("batch_id") == batch_id]
    preflight_errors: list[str] = []
    required_fields = {
        "profile_id",
        "instrument_symbol",
        "contract_code",
        "period",
        "binding_id",
        "previous_binding_id",
        "previous_market_data_file_id",
        "next_market_data_file_id",
        "previous_data_version",
        "next_data_version",
        "committed",
        "candidate_sha256",
        "candidate_count",
    }
    if not apply_rows:
        preflight_errors.append("no_apply_ledger_rows")
    approved_rows = _read_csv(expected_candidates_path) if expected_candidates_path else []
    approved_hash = (
        _sha256_file(expected_candidates_path) if expected_candidates_path and expected_candidates_path.is_file() else ""
    )
    approved_identities = [_identity(row) for row in approved_rows if row.get("candidate_status") == "current"]
    if commit:
        if expected_candidates_path is None:
            preflight_errors.append("expected_candidates_path_required")
        if not expected_candidates_sha256 or approved_hash != expected_candidates_sha256:
            preflight_errors.append("expected_candidates_sha256_mismatch")
        if expected_operation_count is None or len(approved_identities) != expected_operation_count:
            preflight_errors.append("expected_operation_count_mismatch")
    if existing_rollback_rows:
        preflight_errors.append("rollback_batch_id_already_used")
    identities = [_identity(row) for row in apply_rows]
    if len(identities) != len(set(identities)):
        preflight_errors.append("duplicate_committed_identity")
    if commit and set(identities) != set(approved_identities):
        preflight_errors.append("approved_identity_set_mismatch")
    hashes = {_clean_text(row.get("candidate_sha256")) for row in apply_rows}
    counts = {_parse_int(row.get("candidate_count")) for row in apply_rows}
    if (
        len(hashes) != 1
        or "" in hashes
        or len(counts) != 1
        or None in counts
        or next(iter(counts), None) != len(apply_rows)
        or (commit and next(iter(hashes), None) != expected_candidates_sha256)
    ):
        preflight_errors.append("invalid_candidate_hash_or_count")

    parsed_rows: list[tuple[dict[str, Any], int, int | None, bool]] = []
    for row in apply_rows:
        identity = _identity(row)
        if not required_fields.issubset(row):
            preflight_errors.append(f"missing_ledger_fields:{identity}")
            continue
        if row.get("status") == "error" or not _is_true(row["committed"]):
            preflight_errors.append(f"uncommitted_or_error_row:{identity}")
            continue
        binding_ok, binding_id = _strict_required_int(row, "binding_id")
        previous_binding_ok, previous_binding_id = _strict_optional_int(row, "previous_binding_id")
        previous_file_ok, previous_file_id = _strict_optional_int(row, "previous_market_data_file_id")
        next_file_ok, next_file_id = _strict_required_int(row, "next_market_data_file_id")
        previous_version = _clean_text(row["previous_data_version"])
        next_version = _clean_text(row["next_data_version"])
        prior_absent = previous_binding_id is None and previous_file_id is None and not previous_version
        prior_complete = previous_binding_id is not None and previous_file_id is not None and bool(previous_version)
        if (
            not binding_ok
            or not previous_binding_ok
            or not previous_file_ok
            or not next_file_ok
            or not next_version
            or not (prior_absent or prior_complete)
        ):
            preflight_errors.append(f"invalid_ledger_values:{identity}")
            continue
        active = _active_bindings_for_identity(session, row)
        if (
            len(active) != 1
            or active[0].id != binding_id
            or active[0].market_data_file_id != next_file_id
            or active[0].data_version != next_version
        ):
            preflight_errors.append(f"current_active_drift:{identity}")
            continue
        parsed_rows.append((row, binding_id, previous_binding_id, prior_absent))

    if preflight_errors:
        session.rollback()
        output_dir.mkdir(parents=True, exist_ok=True)
        error_rows = [
            {
                "batch_id": batch_id,
                "status": "error",
                "error": error,
                "committed": False,
                "rolled_back_at": datetime.now(UTC).isoformat(),
                "operator": operator,
            }
            for error in preflight_errors
        ]
        _append_csv(rollback_path, error_rows)
        return {
            "batch_id": batch_id,
            "rolled_back": 0,
            "restored_absent": 0,
            "skipped": 0,
            "errors": len(preflight_errors),
            "committed": False,
            "rollback_ledger": str(rollback_path),
        }

    rolled_back = 0
    restored_absent = 0
    skipped = 0
    errors = 0
    pending_rollbacks: list[dict[str, Any]] = []
    for row, binding_id, previous_binding_id, ledger_proves_absent in reversed(parsed_rows):
        profile_id = _clean_text(row.get("profile_id"))
        symbol = _clean_text(row.get("instrument_symbol"))
        contract = _clean_text(row.get("contract_code"))
        period = _clean_text(row.get("period"))
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
                restore_absent=restore_absent and ledger_proves_absent,
                expected_previous_binding_id=previous_binding_id,
                enforce_expected_previous=True,
            )
            if result.get("status") == "no_previous_binding":
                skipped += 1
                continue
            rolled_back += 1
            if result.get("status") in {"restore_absent_ready", "restored_absent"}:
                restored_absent += 1
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
    elif errors > 0:
        session.rollback()
        rolled_back = 0
        restored_absent = 0

    _append_csv(rollback_path, pending_rollbacks)
    return {
        "batch_id": batch_id,
        "rolled_back": rolled_back,
        "restored_absent": restored_absent,
        "skipped": skipped,
        "errors": errors,
        "committed": commit and errors == 0 and rolled_back > 0,
        "rollback_ledger": str(rollback_path),
    }


__all__ = [
    "DEFAULT_PROFILE_IDS",
    "run_apply_mode",
    "run_dry_run_mode",
    "run_generate_mode",
    "run_golden_query_mode",
    "run_rollback_batch_mode",
    "run_verify_mode",
]
