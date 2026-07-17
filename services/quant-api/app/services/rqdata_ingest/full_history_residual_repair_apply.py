from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.data_center import DataQualityReport, MarketDataFile, ProfileActiveBinding
from app.services.rqdata_ingest.actual_contract_bars_pilot import _evaluate_actual_contract_bar_quality


class RepairApplyBlockedError(RuntimeError):
    pass


def build_stale_retirement_ledger(
    session: Session,
    inventory_rows: Iterable[dict[str, Any]],
    *,
    allowed_missing_ids: set[int] | frozenset[int] = frozenset({33197, 33198, 33199, 33200}),
) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for row in inventory_rows:
        path = str(row.get("physical_path") or "")
        actual_checksum = str(row.get("checksum_actual") or "")
        try:
            declared_ids = [int(item) for item in json.loads(str(row.get("market_data_file_ids") or "[]"))]
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RepairApplyBlockedError(f"INVENTORY_DB_IDS_INVALID: path={path}") from exc
        declared_files = [session.get(MarketDataFile, file_id) for file_id in declared_ids]
        if any(item is None for item in declared_files):
            raise RepairApplyBlockedError(f"INVENTORY_DB_ID_MISSING: path={path} ids={declared_ids}")
        files = [item for item in declared_files if item is not None]
        physical_readable = str(row.get("physical_status") or "") == "readable"
        if physical_readable:
            stale_files = [item for item in files if str(item.checksum or "") != actual_checksum]
            replacements = session.scalars(
                select(MarketDataFile).where(
                    MarketDataFile.file_path == path,
                    MarketDataFile.checksum == actual_checksum,
                )
            ).all()
            if len(stale_files) != 1 or len(replacements) != 1:
                raise RepairApplyBlockedError(
                    "RETIREMENT_PAIR_NOT_UNIQUE: "
                    f"path={path} stale_ids={[item.id for item in stale_files]} "
                    f"replacement_ids={[item.id for item in replacements]}"
                )
            stale = stale_files[0]
            replacement = replacements[0]
            if stale.data_role != "superseded":
                raise RepairApplyBlockedError(f"STALE_ROLE_INVALID: id={stale.id} role={stale.data_role}")
        else:
            if set(declared_ids) - set(allowed_missing_ids):
                raise RepairApplyBlockedError(f"MISSING_PHYSICAL_NOT_ALLOWLISTED: ids={declared_ids} path={path}")
            if len(files) != 1 or files[0].data_role != "candidate":
                raise RepairApplyBlockedError(f"MISSING_CANDIDATE_INVALID: ids={declared_ids} path={path}")
            stale = files[0]
            replacement = None
        binding_ids = session.scalars(
            select(ProfileActiveBinding.id).where(ProfileActiveBinding.market_data_file_id == stale.id)
        ).all()
        if binding_ids:
            raise RepairApplyBlockedError(f"PROFILE_BINDING_EXISTS: file_id={stale.id} binding_ids={binding_ids}")
        quality_report_ids = list(
            session.scalars(select(DataQualityReport.id).where(DataQualityReport.file_id == stale.id)).all()
        )
        operation = {
            "market_data_file_id": stale.id,
            "expected_path": stale.file_path,
            "expected_checksum": str(stale.checksum or ""),
            "expected_data_role": stale.data_role,
            "quality_report_ids": quality_report_ids,
        }
        if replacement is not None:
            operation.update(
                {
                    "replacement_market_data_file_id": replacement.id,
                    "replacement_checksum": str(replacement.checksum or ""),
                }
            )
        ledger.append(operation)
    ids = [int(item["market_data_file_id"]) for item in ledger]
    if len(ids) != len(set(ids)):
        raise RepairApplyBlockedError("DUPLICATE_RETIREMENT_ID")
    return sorted(ledger, key=lambda item: int(item["market_data_file_id"]))


def retire_stale_market_data_files(
    session: Session,
    retirements: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for retirement in retirements:
        file_id = int(retirement["market_data_file_id"])
        if file_id in seen_ids:
            raise RepairApplyBlockedError(f"DUPLICATE_RETIREMENT_ID: {file_id}")
        seen_ids.add(file_id)
        stale = session.get(MarketDataFile, file_id)
        if stale is None:
            raise RepairApplyBlockedError(f"MARKET_DATA_FILE_MISSING: {file_id}")
        expected = {
            "file_path": str(retirement.get("expected_path") or ""),
            "checksum": str(retirement.get("expected_checksum") or ""),
            "data_role": str(retirement.get("expected_data_role") or ""),
        }
        actual = {
            "file_path": stale.file_path,
            "checksum": str(stale.checksum or ""),
            "data_role": stale.data_role,
        }
        if actual != expected:
            raise RepairApplyBlockedError(f"RETIREMENT_EVIDENCE_DRIFT: id={file_id} expected={expected} actual={actual}")
        binding_ids = session.scalars(
            select(ProfileActiveBinding.id).where(ProfileActiveBinding.market_data_file_id == file_id)
        ).all()
        if binding_ids:
            raise RepairApplyBlockedError(f"PROFILE_BINDING_EXISTS: file_id={file_id} binding_ids={binding_ids}")

        replacement_id = retirement.get("replacement_market_data_file_id")
        if stale.data_role == "superseded" and replacement_id is None:
            raise RepairApplyBlockedError(f"REPLACEMENT_REQUIRED: file_id={file_id}")
        if replacement_id is not None:
            replacement = session.get(MarketDataFile, int(replacement_id))
            if replacement is None or replacement.id == stale.id:
                raise RepairApplyBlockedError(f"REPLACEMENT_INVALID: file_id={file_id} replacement_id={replacement_id}")
            if replacement.file_path != stale.file_path:
                raise RepairApplyBlockedError(f"REPLACEMENT_PATH_MISMATCH: file_id={file_id} replacement_id={replacement_id}")
            expected_replacement_checksum = str(retirement.get("replacement_checksum") or "")
            if str(replacement.checksum or "") != expected_replacement_checksum:
                raise RepairApplyBlockedError(
                    f"REPLACEMENT_CHECKSUM_DRIFT: replacement_id={replacement_id}"
                )

        quality_report_ids = session.scalars(
            select(DataQualityReport.id).where(DataQualityReport.file_id == file_id)
        ).all()
        if quality_report_ids:
            session.execute(delete(DataQualityReport).where(DataQualityReport.id.in_(quality_report_ids)))
        session.delete(stale)
        session.flush()
        results.append(
            {
                "market_data_file_id": file_id,
                "deleted_quality_report_ids": list(quality_report_ids),
                "deleted_quality_report_count": len(quality_report_ids),
                "replacement_market_data_file_id": replacement_id,
            }
        )
    return results


def classify_registration_reconcile(evidence: dict[str, Any]) -> str:
    actual = {str(item) for item in evidence.get("actual_checksums") or () if item}
    registered = {str(item) for item in evidence.get("db_checksums") or () if item}
    if actual and actual & registered:
        return "verified_existing_registration_no_write"
    return "manual_review_checksum_not_registered"


def repair_manifest_checksum_rows(
    actions: Iterable[dict[str, Any]],
    *,
    project_root: Path,
    backup_root: Path,
) -> list[dict[str, Any]]:
    root = project_root.resolve()
    backup_root = backup_root.resolve(strict=False)
    grouped: dict[Path, list[tuple[int, dict[str, Any], dict[str, Any]]]] = {}
    for action in actions:
        evidence = _evidence(action)
        physical = _resolve(root, str(action.get("physical_path") or ""))
        if not physical.is_file():
            raise RepairApplyBlockedError(f"PHYSICAL_MISSING: {physical}")
        actual = _sha256(physical)
        declared_actual = {str(item) for item in evidence.get("actual_checksums") or () if item}
        if declared_actual != {actual}:
            raise RepairApplyBlockedError(f"PHYSICAL_CHECKSUM_DRIFT: {physical}")
        sources = evidence.get("manifest_sources") or ()
        if not sources:
            raise RepairApplyBlockedError(f"MANIFEST_SOURCE_MISSING: {action.get('queue_action_id')}")
        for source in sources:
            path_text, marker, line_text = str(source).rpartition("#")
            if not marker or not line_text.isdigit():
                raise RepairApplyBlockedError(f"MANIFEST_SOURCE_INVALID: {source}")
            manifest = _resolve(root, path_text)
            grouped.setdefault(manifest, []).append((int(line_text), action, evidence))

    results: list[dict[str, Any]] = []
    for manifest, updates in sorted(grouped.items(), key=lambda item: str(item[0])):
        if not manifest.is_file():
            raise RepairApplyBlockedError(f"MANIFEST_MISSING: {manifest}")
        relative = manifest.relative_to(root)
        backup = backup_root / relative
        if backup.exists():
            raise RepairApplyBlockedError(f"BACKUP_EXISTS: {backup}")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest, backup)
        before_sha = _sha256(manifest)
        with manifest.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = tuple(reader.fieldnames or ())
            rows = list(reader)
        if "checksum" not in fieldnames or "standard_path" not in fieldnames:
            raise RepairApplyBlockedError(f"MANIFEST_SCHEMA_INVALID: {manifest}")
        updated = 0
        for line_number, action, evidence in updates:
            index = line_number - 2
            if index < 0 or index >= len(rows):
                raise RepairApplyBlockedError(f"MANIFEST_LINE_INVALID: {manifest}#{line_number}")
            row = rows[index]
            physical = _resolve(root, str(action.get("physical_path") or ""))
            if _resolve(root, str(row.get("standard_path") or "")) != physical:
                raise RepairApplyBlockedError(f"MANIFEST_PATH_DRIFT: {manifest}#{line_number}")
            expected_before = {str(item) for item in evidence.get("manifest_checksums") or () if item}
            if str(row.get("checksum") or "") not in expected_before:
                raise RepairApplyBlockedError(f"MANIFEST_CHECKSUM_BEFORE_DRIFT: {manifest}#{line_number}")
            row["checksum"] = _sha256(physical)
            updated += 1
        temporary = manifest.with_name(f".{manifest.name}.repair-004b-{os.getpid()}.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, manifest)
        results.append(
            {
                "manifest": str(relative),
                "backup": str(backup),
                "before_sha256": before_sha,
                "after_sha256": _sha256(manifest),
                "updated_rows": updated,
            }
        )
    return results


def register_existing_physical_actions(
    session: Session,
    actions: Iterable[dict[str, Any]],
    *,
    project_root: Path,
    repair_manifest_path: Path,
) -> list[dict[str, Any]]:
    root = project_root.resolve()
    repair_manifest_path = repair_manifest_path.resolve(strict=False)
    if repair_manifest_path.exists():
        raise RepairApplyBlockedError(f"REPAIR_MANIFEST_EXISTS: {repair_manifest_path}")
    results: list[dict[str, Any]] = []
    new_manifest_rows: list[dict[str, Any]] = []
    for action in actions:
        evidence = _evidence(action)
        path = _resolve(root, str(action.get("physical_path") or ""))
        if not path.is_file():
            raise RepairApplyBlockedError(f"PHYSICAL_MISSING: {path}")
        checksum = _sha256(path)
        if {checksum} != {str(item) for item in evidence.get("actual_checksums") or () if item}:
            raise RepairApplyBlockedError(f"PHYSICAL_CHECKSUM_DRIFT: {path}")
        frame = pd.read_parquet(path)
        if frame.empty:
            raise RepairApplyBlockedError(f"PHYSICAL_EMPTY: {path}")
        product = str(action.get("product") or "").lower()
        contract = str(action.get("contract") or "")
        period = str(action.get("period") or "")
        quality = _evaluate_actual_contract_bar_quality(frame, period)
        stored_quality = _single_value(frame, "quality_status")
        if quality.status != "passed" or stored_quality != "passed":
            raise RepairApplyBlockedError(f"QUALITY_NOT_PASSED: {path} evaluator={quality.status} stored={stored_quality}")
        data_version = _single_value(frame, "data_version")
        data_role = _single_value(frame, "data_role")
        provider = _single_value(frame, "provider") or "rqdata"
        start_time = pd.to_datetime(frame["datetime"], errors="raise").min().to_pydatetime()
        end_time = pd.to_datetime(frame["datetime"], errors="raise").max().to_pydatetime()
        existing = session.scalar(
            select(MarketDataFile).where(
                MarketDataFile.provider == provider,
                MarketDataFile.data_type == "bars",
                MarketDataFile.instrument_symbol == product,
                MarketDataFile.contract_code == contract,
                MarketDataFile.period == period,
                MarketDataFile.start_time == start_time,
                MarketDataFile.end_time == end_time,
                MarketDataFile.data_version == data_version,
            )
        )
        if existing is not None:
            raise RepairApplyBlockedError(f"REGISTRATION_ALREADY_EXISTS: {existing.id} {path}")
        market_file = MarketDataFile(
            provider=provider,
            data_type="bars",
            instrument_symbol=product,
            contract_code=contract,
            period=period,
            start_time=start_time,
            end_time=end_time,
            file_path=str(path),
            row_count=len(frame),
            file_size_bytes=path.stat().st_size,
            checksum=checksum,
            data_version=data_version,
            data_role=data_role,
            quality_status="passed",
        )
        session.add(market_file)
        session.flush()
        report = DataQualityReport(
            file_id=market_file.id,
            provider=provider,
            data_type="bars",
            instrument_symbol=product,
            contract_code=contract,
            period=period,
            start_time=start_time,
            end_time=end_time,
            status="passed",
            missing_bars=quality.missing_bars,
            duplicated_bars=quality.duplicated_bars,
            abnormal_price_count=quality.abnormal_price_count,
            abnormal_volume_count=quality.abnormal_volume_count,
            details={
                **quality.details,
                "full_history_residual_repair_004b": True,
                "queue_action_id": action.get("queue_action_id"),
                "checksum": checksum,
            },
        )
        session.add(report)
        session.flush()
        result = {
            "queue_action_id": action.get("queue_action_id"),
            "market_data_file_id": market_file.id,
            "quality_report_id": report.id,
            "physical_path": str(path),
            "checksum": checksum,
            "row_count": len(frame),
            "data_version": data_version,
            "data_role": data_role,
            "quality_status": "passed",
        }
        results.append(result)
        if not evidence.get("manifest_sources"):
            new_manifest_rows.append(
                {
                    "period": period,
                    "provider": provider,
                    "source": provider,
                    "product": product,
                    "actual_contract": contract,
                    "data_role": data_role,
                    "quality_status": "passed",
                    "row_count": len(frame),
                    "min_datetime": start_time.isoformat(),
                    "max_datetime": end_time.isoformat(),
                    "checksum": checksum,
                    "standard_path": str(path),
                    "market_data_file_id": market_file.id,
                    "data_quality_report_id": report.id,
                    "data_version": data_version,
                    "status": "success",
                    "repair_batch": "metadata-registration-missing-001",
                }
            )
    if new_manifest_rows:
        repair_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = repair_manifest_path.with_name(f".{repair_manifest_path.name}.{os.getpid()}.tmp")
        fieldnames = tuple(new_manifest_rows[0])
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(new_manifest_rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, repair_manifest_path)
    return results


def _evidence(action: dict[str, Any]) -> dict[str, Any]:
    value = action.get("current_evidence") or {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise RepairApplyBlockedError(f"CURRENT_EVIDENCE_INVALID: {action.get('queue_action_id')}") from exc
    if not isinstance(parsed, dict):
        raise RepairApplyBlockedError(f"CURRENT_EVIDENCE_INVALID: {action.get('queue_action_id')}")
    return parsed


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve(strict=False)


def _single_value(frame: pd.DataFrame, column: str) -> str:
    if column not in frame:
        raise RepairApplyBlockedError(f"COLUMN_MISSING: {column}")
    values = sorted({str(item) for item in frame[column].dropna().unique() if str(item)})
    if len(values) != 1:
        raise RepairApplyBlockedError(f"COLUMN_NOT_SINGLE_VALUE: {column}={values}")
    return values[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "RepairApplyBlockedError",
    "build_stale_retirement_ledger",
    "classify_registration_reconcile",
    "register_existing_physical_actions",
    "repair_manifest_checksum_rows",
    "retire_stale_market_data_files",
]
