from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable
import uuid

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
import duckdb
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding
from app.services.market_data_reader import MarketDataReader
from app.services.rqdata_ingest.data_layer_final_audit import run_extended_final_audit
from app.services.rqdata_ingest.full_universe_active_gate import audit_full_universe_active_gate
from app.services.rqdata_ingest.schema_contract import CANONICAL_BAR_CONTRACT_V1, validate_canonical_bar_contract
from app.services.rqdata_ingest.target_coverage_audit import ProductWindow, audit_target_coverage


MODE = "direct_db_baseline_audit"
READY_GATE = "DIRECT_DB_BASELINE_READY"
BLOCKED_GATE = "BLOCKED_DIRECT_DB_UNAVAILABLE"
AUDIT_FAILED_GATE = "BLOCKED_DIRECT_DB_BASELINE_AUDIT_FAILED"
ENVIRONMENT_FAILED_GATE = "BLOCKED_B01_ENVIRONMENT_GATE_FAILED"
FINAL_CLASSIFICATIONS = frozenset({"covered_passed", "covered_warning", "not_applicable", "blocked_with_reason"})
UNIFIED_MATRIX_COLUMNS = (
    "product",
    "contract_role",
    "contract",
    "period",
    "year/window",
    "profile",
    "physical_status",
    "metadata_status",
    "quality_status",
    "binding_status",
    "gap_candidate",
    "final_classification",
    "classification_source",
)
REQUIRED_SUCCESS_FILENAMES = frozenset(
    {
        "DIRECT_DB_BASELINE_AUDIT.md",
        "environment_evidence.json",
        "target_coverage_matrix.csv",
        "metadata_consistency_matrix.csv",
        "weekly_gaps.csv",
        "actual_roll_gaps.csv",
        "profile_bindings.csv",
        "cross_file_conflicts.csv",
        "blocked_items.csv",
        "baseline_summary.json",
    }
)
PHASE3_METRICS = {
    "covered_passed": 15350,
    "covered_warning": 105,
    "metadata_gap": 1853,
    "not_applicable": 1943,
    "pre_2020_weekly_missing": 34,
}
DERIVED_FROM_1M_PERIODS = frozenset({"5m", "15m", "30m", "60m", "1d"})


class DirectDatabaseGateError(RuntimeError):
    pass


class AuditInputGateError(RuntimeError):
    pass


class AuditEnvironmentGateError(RuntimeError):
    pass


def validate_full_universe_scope(
    *, products: list[str], canonical_products: list[str], window_products: set[str]
) -> None:
    product_set = set(products)
    canonical_set = set(canonical_products)
    if not products or len(products) != len(product_set):
        raise AuditInputGateError("products file must contain a non-empty unique product list")
    if product_set != canonical_set:
        raise AuditInputGateError(
            "products must match canonical full universe "
            f"missing={sorted(canonical_set - product_set)} extra={sorted(product_set - canonical_set)}"
        )
    if len(canonical_products) != 90 or len(canonical_set) != 90:
        raise AuditInputGateError(f"canonical full universe must contain exactly 90 unique products, got {len(canonical_set)}")
    if window_products != product_set:
        raise AuditInputGateError(
            f"product windows mismatch missing={sorted(product_set - window_products)} extra={sorted(window_products - product_set)}"
        )


def sanitize_error(value: object) -> str:
    message = str(value)
    message = re.sub(
        r"(?i)((?:password|passwd|token|secret|authorization)\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s;]+(?:\s+[^\s;]+)?)",
        r"\1<redacted>",
        message,
    )
    message = re.sub(r"(?i)(password|passwd|token|secret)=([^\s;]+)", r"\1=<redacted>", message)
    message = re.sub(r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+):[^@\s]+@", r"\1:<redacted>@", message)
    return message[:2000]


def collect_direct_database_evidence(
    session: Session,
    *,
    project_root: Path,
    data_project_root: Path | None = None,
    audit_end: date,
    git_commit: str,
    branch: str,
    worktree: str,
) -> dict[str, Any]:
    bind = session.get_bind()
    dialect = bind.dialect.name
    if dialect != "postgresql":
        raise DirectDatabaseGateError(f"direct database must be PostgreSQL, got {dialect}")

    session.execute(text("set transaction isolation level repeatable read, read only"))
    database_name, schema_name, read_only, isolation = session.execute(
        text(
            "select current_database(), current_schema(), "
            "current_setting('transaction_read_only'), current_setting('transaction_isolation')"
        )
    ).one()
    if read_only != "on":
        raise DirectDatabaseGateError(f"database transaction is not read-only: {read_only}")
    if isolation != "repeatable read":
        raise DirectDatabaseGateError(f"database transaction is not repeatable-read: {isolation}")
    connection = session.connection()
    current_heads = sorted(filter(None, [MigrationContext.configure(connection).get_current_revision()]))
    alembic_ini = project_root / "services" / "quant-api" / "alembic.ini"
    config = Config(str(alembic_ini))
    expected_heads = sorted(ScriptDirectory.from_config(config).get_heads())
    if current_heads != expected_heads:
        raise DirectDatabaseGateError(f"Alembic mismatch current={current_heads} expected={expected_heads}")

    resolved_data_project_root = data_project_root or project_root
    data_root = resolved_data_project_root / "data"
    parquet_root = data_root / "parquet"
    if not data_root.is_dir() or not parquet_root.is_dir():
        raise DirectDatabaseGateError(f"data root unavailable: {data_root}")

    return {
        "mode": MODE,
        "gate": READY_GATE,
        "db_snapshot_source": "database",
        "database_dialect": dialect,
        "database_name": database_name,
        "database_schema": schema_name,
        "transaction_read_only": read_only,
        "transaction_isolation": isolation,
        "alembic_current": current_heads,
        "alembic_heads": expected_heads,
        "git_commit": git_commit,
        "branch": branch,
        "worktree": worktree,
        "project_root": str(project_root),
        "code_project_root": str(project_root),
        "data_project_root": str(resolved_data_project_root),
        "data_root": str(data_root),
        "audit_end": audit_end.isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
        "uses_api_fallback": False,
        "uses_manifest_only": False,
        "write_flags_present": False,
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "writes_quality": False,
        "writes_profile_binding": False,
        "calls_rqdata": False,
    }


def coverage_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("product") or "").lower(),
        str(row.get("contract_role") or ""),
        str(row.get("symbol_or_contract") or row.get("contract") or row.get("contract_code") or ""),
        str(row.get("period") or ""),
    )


def build_unified_target_matrix(
    coverage_rows: Iterable[dict[str, Any]],
    *,
    conflict_keys: set[tuple[str, ...]] | None = None,
    physical_status_by_path: dict[str, str] | None = None,
    profile_by_key: dict[tuple[str, str, str, str], list[dict[str, str]]] | None = None,
) -> list[dict[str, Any]]:
    conflict_keys = conflict_keys or set()
    physical_status_by_path = physical_status_by_path or {}
    profile_by_key = profile_by_key or {}
    output: list[dict[str, Any]] = []
    for original in coverage_rows:
        key = coverage_key(original)
        profiles = profile_by_key.get(key) or [{"profile": "", "binding_status": "not_profile_scoped"}]
        for profile in profiles:
            row = dict(original)
            status = str(row.get("actual_status") or row.get("status") or "")
            path = str(row.get("standard_path") or "")
            physical_status = physical_status_by_path.get(path) or _physical_status_from_coverage(status, row)
            metadata_status = "registered" if row.get("db_market_data_file_id") else "missing_registration"
            binding_status = profile.get("binding_status", "not_profile_scoped")
            classification, source = _classify_final(
                row=row,
                status=status,
                physical_status=physical_status,
                metadata_status=metadata_status,
                binding_status=binding_status,
                has_conflict=key in conflict_keys or (*key, str(row.get("year") or "")) in conflict_keys,
            )
            normalized = {
                **row,
                "contract": key[2],
                "year/window": row.get("year") or _window_text(row),
                "profile": profile.get("profile", ""),
                "physical_status": physical_status,
                "metadata_status": metadata_status,
                "binding_status": binding_status,
                "gap_candidate": "" if classification in {"covered_passed", "not_applicable"} else (row.get("issue_type") or source),
                "final_classification": classification,
                "classification_source": source,
            }
            if classification not in FINAL_CLASSIFICATIONS:
                raise ValueError(f"invalid final classification: {classification}")
            output.append(normalized)
    return output


def _classify_final(
    *,
    row: dict[str, Any],
    status: str,
    physical_status: str,
    metadata_status: str,
    binding_status: str,
    has_conflict: bool,
) -> tuple[str, str]:
    if status == "not_applicable":
        return "not_applicable", "target_status:not_applicable"
    if int(row.get("duplicate_active_count") or 0) > 1:
        return "blocked_with_reason", "duplicate_active"
    if status not in {"covered_passed", "covered_warning", "approved_warning"}:
        return "blocked_with_reason", f"coverage_status:{status or 'missing'}"
    if physical_status in {"missing", "unreadable", "schema_invalid", "row_count_mismatch", "checksum_mismatch"}:
        return "blocked_with_reason", f"physical_status:{physical_status}"
    if metadata_status != "registered":
        return "blocked_with_reason", f"metadata_status:{metadata_status}"
    if binding_status not in {"active_valid", "not_profile_scoped"}:
        return "blocked_with_reason", f"binding_status:{binding_status}"
    if has_conflict:
        return "covered_warning", "cross_file_conflict"
    if bool(row.get("is_partial_window")):
        return "covered_warning", "partial_current_window"
    if status in {"covered_warning", "approved_warning"} or str(row.get("quality_status")) != "passed":
        return "covered_warning", f"quality_status:{row.get('quality_status') or status}"
    if physical_status in {"checksum_unverified", "schema_unverified", "schema_warning"}:
        return "covered_warning", f"physical_status:{physical_status}"
    return "covered_passed", "coverage+physical+metadata+quality"


def _physical_status_from_coverage(status: str, row: dict[str, Any]) -> str:
    if status == "not_applicable":
        return "not_applicable"
    issue = str(row.get("issue_type") or "")
    if "missing_physical" in issue or not row.get("standard_path"):
        return "missing"
    if "duckdb_read_failed" in issue:
        return "unreadable"
    if "row_count_mismatch" in issue:
        return "row_count_mismatch"
    return "passed"


def _window_text(row: dict[str, Any]) -> str:
    return f"{row.get('expected_start') or ''}..{row.get('expected_end') or ''}"


def build_profile_binding_rows(
    *, profiles: Iterable[Any], bindings: Iterable[Any], market_files: Iterable[Any], project_root: Path | None = None
) -> list[dict[str, Any]]:
    profiles_by_id = {item.profile_id: item for item in profiles}
    files_by_id = {item.id: item for item in market_files}
    rows: list[dict[str, Any]] = []
    for binding in bindings:
        problems: list[str] = []
        profile = profiles_by_id.get(binding.profile_id)
        market_file = files_by_id.get(binding.market_data_file_id)
        if profile is None:
            problems.append("profile_missing")
        elif not getattr(profile, "is_active", True):
            problems.append("profile_inactive")
        elif binding.contract_role not in set(getattr(profile, "contract_roles", None) or []):
            problems.append("profile_contract_role_mismatch")
        elif binding.period not in set(getattr(profile, "periods", None) or []):
            problems.append("profile_period_mismatch")
        if market_file is None:
            problems.append("market_data_file_missing")
        elif market_file.data_role != "primary" or market_file.provider not in {"rqdata", "local_parquet"} or market_file.quality_status == "failed":
            problems.append("market_data_file_ineligible")
        elif (
            str(getattr(market_file, "instrument_symbol", "")).lower() != str(binding.instrument_symbol).lower()
            or str(getattr(market_file, "contract_code", "")) != str(binding.contract_code)
            or str(getattr(market_file, "period", "")) != str(binding.period)
            or str(getattr(market_file, "data_version", "")) != str(binding.data_version)
        ):
            problems.append("binding_file_identity_mismatch")
        elif profile is not None and getattr(profile, "provider", None) and market_file.provider != profile.provider:
            problems.append("profile_provider_mismatch")
        elif profile is not None and profile.quality_policy == "passed_only" and market_file.quality_status != "passed":
            problems.append("profile_quality_policy_mismatch")
        elif project_root is not None:
            file_path = Path(str(market_file.file_path))
            if not file_path.is_absolute():
                file_path = project_root / file_path
            if not file_path.is_file():
                problems.append("market_data_file_missing_physical")
        status = ";".join(problems) if problems else "active_valid"
        rows.append(
            {
                "binding_id": binding.id,
                "profile": binding.profile_id,
                "product": binding.instrument_symbol,
                "contract": binding.contract_code,
                "contract_role": binding.contract_role,
                "period": binding.period,
                "data_version": binding.data_version,
                "market_data_file_id": binding.market_data_file_id,
                "binding_status": status,
                "quality_policy": getattr(profile, "quality_policy", "") if profile else "",
                "final_classification": "blocked_with_reason" if problems else "covered_passed",
                "classification_source": f"profile_binding:{status}",
            }
        )
    return rows


def build_profile_binding_audit(
    *,
    profiles: Iterable[Any],
    bindings: Iterable[Any],
    market_files: Iterable[Any],
    coverage_rows: Iterable[dict[str, Any]],
    project_root: Path,
) -> list[dict[str, Any]]:
    profiles_list = list(profiles)
    bindings_list = list(bindings)
    market_files_list = list(market_files)
    existing = build_profile_binding_rows(
        profiles=profiles_list,
        bindings=bindings_list,
        market_files=market_files_list,
        project_root=project_root,
    )
    by_identity = {
        (row["profile"], str(row["product"]).lower(), row["contract_role"], row["contract"], row["period"]): row
        for row in existing
    }
    coverage_identities = {
        coverage_key(row)
        for row in coverage_rows
        if str(row.get("actual_status") or row.get("status") or "") != "not_applicable"
    }
    output: list[dict[str, Any]] = []
    used: set[tuple[str, str, str, str, str]] = set()
    for profile in profiles_list:
        if not getattr(profile, "is_active", True):
            continue
        config = _load_profile_config(profile, project_root)
        roles = set(getattr(profile, "contract_roles", None) or config.get("contract_roles") or [])
        periods = set(getattr(profile, "periods", None) or config.get("periods") or [])
        products = _profile_products(config, project_root, coverage_identities)
        for product, role, contract, period in sorted(coverage_identities):
            if product not in products or role not in roles or period not in periods:
                continue
            identity = (profile.profile_id, product, role, contract, period)
            used.add(identity)
            row = by_identity.get(identity)
            if row is not None:
                output.append(row)
                continue
            output.append(
                {
                    "binding_id": None,
                    "profile": profile.profile_id,
                    "product": product,
                    "contract": contract,
                    "contract_role": role,
                    "period": period,
                    "data_version": "",
                    "market_data_file_id": None,
                    "binding_status": "binding_missing",
                    "quality_policy": getattr(profile, "quality_policy", ""),
                    "final_classification": "blocked_with_reason",
                    "classification_source": "profile_binding:binding_missing",
                }
            )
    output.extend(row for identity, row in by_identity.items() if identity not in used)
    return sorted(output, key=lambda row: (str(row["profile"]), str(row["product"]), str(row["contract"]), str(row["period"])))


def _load_profile_config(profile: Any, project_root: Path) -> dict[str, Any]:
    raw_path = getattr(profile, "config_path", None)
    if not raw_path:
        return {}
    path = Path(raw_path)
    if not path.is_absolute():
        path = project_root / path
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditInputGateError(f"profile config unavailable: {path}: {sanitize_error(exc)}") from exc


def _profile_products(
    config: dict[str, Any], project_root: Path, coverage_identities: set[tuple[str, str, str, str]]
) -> set[str]:
    scope = config.get("binding_scope") or {}
    if scope.get("products"):
        return {str(item).lower() for item in scope["products"]}
    if scope.get("products_file"):
        path = Path(str(scope["products_file"]))
        if not path.is_absolute():
            path = project_root / path
        try:
            return {
                line.strip().lower()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            }
        except OSError as exc:
            raise AuditInputGateError(f"profile products file unavailable: {path}: {sanitize_error(exc)}") from exc
    pilots = config.get("pilots") or []
    if pilots:
        return {str(item).lower() for item in pilots}
    return {identity[0] for identity in coverage_identities}


def build_profile_scope_index(
    *, profiles: Iterable[Any], binding_rows: list[dict[str, Any]], project_root: Path
) -> dict[tuple[str, str, str, str], list[dict[str, str]]]:
    bindings = defaultdict(list)
    for row in binding_rows:
        key = (str(row["product"]).lower(), str(row["contract_role"]), str(row["contract"]), str(row["period"]))
        bindings[key].append({"profile": str(row["profile"]), "binding_status": str(row["binding_status"])})
    return dict(bindings)


def inspect_physical_evidence(
    rows: Iterable[dict[str, Any]], *, project_root: Path, expected_checksum_by_path: dict[str, str]
) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_path = str(row.get("physical_path") or row.get("standard_path") or "")
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_root / path
        unique.setdefault(str(path.resolve()), row)

    output: list[dict[str, Any]] = []
    for path_text, source in sorted(unique.items()):
        path = Path(path_text)
        evidence: dict[str, Any] = {
            "source_path": str(source.get("physical_path") or source.get("standard_path") or ""),
            "physical_path": path_text,
            "exists": path.is_file(),
            "schema_status": "unverified",
            "checksum_expected": expected_checksum_by_path.get(path_text, ""),
            "checksum_actual": "",
            "checksum_status": "checksum_unverified",
            "row_count_expected": source.get("manifest_or_db_row_count", ""),
            "row_count_actual": source.get("duckdb_row_count", ""),
            "row_count_status": source.get("row_count_status", ""),
            "physical_status": "missing",
            "error": "",
        }
        if path.is_file():
            try:
                period = str(source.get("period") or "")
                contract_role = str(source.get("contract_role") or "") or None
                schema = validate_canonical_bar_contract(path, period=period, contract_role=contract_role)
                with duckdb.connect(database=":memory:") as connection:
                    columns = {
                        str(item[0]): str(item[1])
                        for item in connection.execute("describe select * from read_parquet(?)", [path_text]).fetchall()
                    }
                    source_intervals = (
                        {
                            str(item[0])
                            for item in connection.execute(
                                "select distinct cast(source_interval as varchar) from read_parquet(?)",
                                [path_text],
                            ).fetchall()
                            if item[0] is not None
                        }
                        if period in DERIVED_FROM_1M_PERIODS and "source_interval" in columns
                        else set()
                    )
                dtype_mismatches = _canonical_dtype_mismatches(columns, period=period)
                source_interval_valid = period not in DERIVED_FROM_1M_PERIODS or source_intervals == {"1m"}
                schema_failed = schema.get("embedded_status") == "failed" or bool(dtype_mismatches) or not source_interval_valid
                evidence["schema_columns"] = sorted(columns)
                evidence["schema_version"] = schema.get("schema_version", "")
                evidence["schema_fingerprint"] = schema.get("fingerprint", "")
                evidence["schema_missing"] = schema.get("missing_embedded", [])
                evidence["schema_dtype_mismatches"] = dtype_mismatches
                evidence["schema_sidecar_status"] = schema.get("sidecar_status", "")
                evidence["source_interval_values"] = sorted(source_intervals)
                evidence["schema_status"] = "schema_invalid" if schema_failed else ("schema_warning" if schema.get("status") == "warning" else "passed")
                actual = _sha256(path)
                expected = evidence["checksum_expected"]
                evidence["checksum_actual"] = actual
                evidence["checksum_status"] = "passed" if expected and actual == expected else ("checksum_mismatch" if expected else "checksum_unverified")
                if evidence["schema_status"] == "schema_invalid":
                    evidence["physical_status"] = "schema_invalid"
                elif evidence["row_count_status"] == "mismatch":
                    evidence["physical_status"] = "row_count_mismatch"
                elif evidence["checksum_status"] == "checksum_mismatch":
                    evidence["physical_status"] = "checksum_mismatch"
                elif evidence["schema_status"] == "schema_warning":
                    evidence["physical_status"] = "schema_warning"
                elif evidence["checksum_status"] == "checksum_unverified":
                    evidence["physical_status"] = "checksum_unverified"
                else:
                    evidence["physical_status"] = "passed"
            except Exception as exc:  # noqa: BLE001
                evidence["physical_status"] = "unreadable"
                evidence["error"] = sanitize_error(exc)
        output.append(evidence)
    return output


def _canonical_dtype_mismatches(columns: dict[str, str], *, period: str) -> list[str]:
    required = {
        name: spec["dtype"]
        for name, spec in CANONICAL_BAR_CONTRACT_V1.items()
        if spec["storage"] == "parquet"
        and (
            spec.get("required")
            or (name == "trading_day" and period != "1m")
            or (name == "source_interval" and period in DERIVED_FROM_1M_PERIODS)
        )
    }
    mismatches = []
    for name, expected in required.items():
        observed = columns.get(name, "").upper()
        if not observed or _dtype_matches(observed, str(expected)):
            continue
        mismatches.append(f"{name}:expected={expected}:observed={observed}")
    return sorted(mismatches)


def _dtype_matches(observed: str, expected: str) -> bool:
    if expected == "timestamp":
        return "TIMESTAMP" in observed
    if expected == "date":
        return observed == "DATE" or "TIMESTAMP" in observed
    if expected == "string":
        return observed in {"VARCHAR", "STRING"}
    if expected == "int":
        return "INT" in observed
    if expected == "float":
        return any(token in observed for token in ("FLOAT", "DOUBLE", "DECIMAL", "REAL", "INT"))
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_expected_checksum_index(*, project_root: Path, market_files: Iterable[Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in market_files:
        if item.file_path and item.checksum:
            path = Path(item.file_path)
            if not path.is_absolute():
                path = project_root / path
            result[str(path.resolve())] = str(item.checksum)
    for manifest in sorted((project_root / "data" / "manifests").glob("*.csv")):
        try:
            with manifest.open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    raw_path = row.get("standard_path") or row.get("file_path") or row.get("path") or ""
                    checksum = row.get("checksum") or row.get("sha256") or ""
                    if raw_path and checksum:
                        path = Path(raw_path)
                        if not path.is_absolute():
                            path = project_root / path
                        result.setdefault(str(path.resolve()), checksum)
        except (OSError, UnicodeError, csv.Error):
            continue
    return result


def detect_cross_file_conflicts(
    *, session: Session, project_root: Path, duplicate_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in duplicate_rows:
        grouped[coverage_key(row)].append(row)
    reader = MarketDataReader(session, project_root=project_root)
    output: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        starts = [_to_datetime(row.get("start_time")) for row in rows]
        ends = [_to_datetime(row.get("end_time")) for row in rows]
        valid_starts = [item for item in starts if item is not None]
        valid_ends = [item for item in ends if item is not None]
        if not valid_starts or not valid_ends:
            output.append(
                {
                    "product": key[0],
                    "contract_role": key[1],
                    "contract": key[2],
                    "period": key[3],
                    "final_classification": "blocked_with_reason",
                    "classification_source": "cross_file_conflict_window_missing",
                }
            )
            continue
        start = min(valid_starts)
        end = max(valid_ends)
        for detail in reader.get_cross_file_conflicts(
            key[0], key[2], key[3], start, end, data_role="primary", max_details=1_000_000
        ):
            output.append(
                {
                    "product": key[0],
                    "contract_role": key[1],
                    "contract": key[2],
                    "period": key[3],
                    **detail,
                    "final_classification": "covered_warning",
                    "classification_source": "cross_file_conflict",
                }
            )
    return output


def _to_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif value:
        result = datetime.fromisoformat(str(value))
    else:
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result


def run_direct_db_audit(
    *, session: Session, project_root: Path, products: list[str], product_windows: dict[str, ProductWindow], audit_end: date, environment: dict[str, Any]
) -> dict[str, Any]:
    target = audit_target_coverage(
        session=session,
        project_root=project_root,
        product_windows=product_windows,
        audit_end=audit_end,
        db_snapshot_source="database",
    )
    stage8 = audit_full_universe_active_gate(session=session, project_root=project_root, products=products, profile="stage8_6_1d_first")
    jm = audit_full_universe_active_gate(session=session, project_root=project_root, products=["jm"], profile="jm_main_six_period_latest")
    extended = run_extended_final_audit(
        session=session,
        project_root=project_root,
        products=products,
        product_windows=product_windows,
        audit_end=audit_end,
        target_coverage_result=target,
        stage8_6_1d_result=stage8,
        jm_six_period_result=jm,
        git_commit=str(environment["git_commit"]),
        db_snapshot_time=str(environment["captured_at"]),
    )
    market_files = list(session.scalars(select(MarketDataFile)))
    profiles = list(session.scalars(select(DataProfile).order_by(DataProfile.profile_id)))
    bindings = list(session.scalars(select(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == "active")))
    profile_rows = build_profile_binding_audit(
        profiles=profiles,
        bindings=bindings,
        market_files=market_files,
        coverage_rows=target["target_coverage_matrix"],
        project_root=project_root,
    )
    conflicts = detect_cross_file_conflicts(session=session, project_root=project_root, duplicate_rows=extended["duplicate_active_assets"])
    physical = inspect_physical_evidence(
        target["asset_physical_inventory"],
        project_root=project_root,
        expected_checksum_by_path=build_expected_checksum_index(project_root=project_root, market_files=market_files),
    )
    physical_by_path = {
        key: row["physical_status"]
        for row in physical
        for key in {str(row["physical_path"]), str(row.get("source_path") or "")}
        if key
    }
    conflict_keys = {
        (*coverage_key(row), str(row.get("dedupe_key") or "")[:4])
        for row in conflicts
        if row.get("dedupe_key")
    }
    conflict_keys.update(coverage_key(row) for row in conflicts if not row.get("dedupe_key"))
    duplicate_counts = Counter(coverage_key(row) for row in extended["duplicate_active_assets"])
    coverage_rows = [
        {**row, "duplicate_active_count": duplicate_counts.get(coverage_key(row), 0)}
        for row in target["target_coverage_matrix"]
    ]
    base_matrix = build_unified_target_matrix(
        coverage_rows,
        conflict_keys=conflict_keys,
        physical_status_by_path=physical_by_path,
    )
    matrix = build_unified_target_matrix(
        coverage_rows,
        conflict_keys=conflict_keys,
        physical_status_by_path=physical_by_path,
        profile_by_key=build_profile_scope_index(profiles=profiles, binding_rows=profile_rows, project_root=project_root),
    )
    metadata = [_normalize_metadata_row(row) for row in target["metadata_consistency_matrix"]]
    weekly = _build_weekly_gaps(extended["weekly_history_audit"], base_matrix)
    actual_roll = _build_actual_roll_gaps(matrix, extended["main_contract_mapping_audit"])
    orphan_rows = [
        {
            **row,
            "final_classification": "blocked_with_reason",
            "classification_source": "orphan_physical_file",
            "next_task": "B-02",
        }
        for row in extended["orphan_files"]
    ]
    blockers = _build_blocked_items(matrix, metadata, weekly, actual_roll, profile_rows, conflicts, orphan_rows)
    return {
        "environment_evidence": environment,
        "target_coverage_matrix": matrix,
        "base_target_coverage_matrix": base_matrix,
        "metadata_consistency_matrix": metadata,
        "weekly_gaps": weekly,
        "actual_roll_gaps": actual_roll,
        "profile_bindings": profile_rows,
        "cross_file_conflicts": conflicts,
        "blocked_items": blockers,
        "physical_evidence": physical,
        "duplicate_active_assets": extended["duplicate_active_assets"],
        "orphan_files": orphan_rows,
        "partial_window_audit": extended["partial_revision_policy"],
    }


def _normalize_metadata_row(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("status") or "")
    classification = status if status in {"covered_passed", "not_applicable"} else "blocked_with_reason"
    return {**row, "final_classification": classification, "classification_source": f"database:{row.get('dataset')}:{status}"}


def _build_weekly_gaps(rows: list[dict[str, Any]], matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warning_products = {
        str(row.get("product") or "")
        for row in matrix
        if row.get("period") == "1w" and row.get("final_classification") == "covered_warning"
    }
    output = []
    for row in rows:
        pre = str(row.get("pre_2020_status") or "")
        post_ok = int(row.get("post_2020_passed_years") or 0) >= int(row.get("post_2020_expected_years") or 0)
        product = str(row.get("product") or "")
        if pre in {"covered", "not_applicable"} and post_ok and row.get("direct_1w_present") and product not in warning_products:
            continue
        classification = "covered_warning" if product in warning_products else ("not_applicable" if pre == "not_applicable" and post_ok else "blocked_with_reason")
        output.append(
            {
                **row,
                "final_classification": classification,
                "classification_source": "weekly_coverage_warning" if product in warning_products else f"weekly_history:{pre or 'missing'}",
                "next_task": "B-03",
            }
        )
    return output


def _build_actual_roll_gaps(matrix: list[dict[str, Any]], mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = [
        {**row, "gap_type": "actual_contract_coverage", "next_task": "B-04"}
        for row in matrix
        if row.get("contract_role") == "actual_contract"
        and row.get("final_classification") not in {"covered_passed", "not_applicable"}
    ]
    output.extend(
        {**row, "gap_type": "rank1_mapping_or_roll", "next_task": "B-04", "final_classification": "blocked_with_reason"}
        for row in mappings
        if row.get("audit_status") not in {"passed", "not_applicable"} or int(row.get("mapped_contracts_missing_bars") or 0) > 0
    )
    return output


def _build_blocked_items(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for group in groups:
        for row in group:
            if row.get("final_classification") != "blocked_with_reason":
                continue
            output.append(
                {
                    "source": row.get("next_task") or row.get("recommended_next_task") or "B-02/B-03/B-04/B-05",
                    "product": row.get("product", ""),
                    "contract": row.get("contract") or row.get("symbol_or_contract") or "",
                    "period": row.get("period", ""),
                    "reason": row.get("classification_source") or row.get("issue_type") or row.get("binding_status") or "blocked",
                    "final_classification": "blocked_with_reason",
                }
            )
    return output


def write_blocked_environment_package(output_dir: Path, *, evidence: dict[str, Any]) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=False)
    safe = {**evidence, "db_error": sanitize_error(evidence.get("db_error", ""))}
    gate = str(safe.get("gate") or BLOCKED_GATE)
    environment_path = output_dir / "environment_evidence.json"
    environment_path.write_text(json.dumps(safe, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    blocked_path = output_dir / "blocked_items.csv"
    pd.DataFrame(
        [{"gate": gate, "reason": safe.get("db_error", "direct database unavailable"), "recommended_action": "repair the reported Gate failure and rerun B-01"}]
    ).to_csv(blocked_path, index=False)
    summary_path = output_dir / f"{gate}.md"
    summary_path.write_text(
        "# B-01 Direct PostgreSQL Baseline\n\n"
        f"Gate: `{gate}`\n\n"
        "未生成任何覆盖完成度或 gap 结论。请修复 direct PostgreSQL 连接或 Alembic head 后重跑。\n",
        encoding="utf-8",
    )
    return {"environment_evidence": environment_path, "blocked_items": blocked_path, "blocked_summary": summary_path}


def write_success_reports(output_dir: Path, *, payload: dict[str, Any], audit_end: date) -> dict[str, Path]:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing report directory: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_dir.parent / f".{output_dir.name}.tmp-{uuid.uuid4().hex}"
    try:
        temporary_paths = _write_success_reports_in_place(
            temporary,
            payload=payload,
            audit_end=audit_end,
            published_output_dir=output_dir,
        )
        temporary.rename(output_dir)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return {key: output_dir / path.name for key, path in temporary_paths.items()}


def _write_success_reports_in_place(
    output_dir: Path,
    *,
    payload: dict[str, Any],
    audit_end: date,
    published_output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=False)
    mappings = {
        "target_coverage_matrix": ("target_coverage_matrix.csv", list(UNIFIED_MATRIX_COLUMNS)),
        "metadata_consistency_matrix": ("metadata_consistency_matrix.csv", ["product", "year", "dataset", "status", "final_classification", "classification_source"]),
        "weekly_gaps": ("weekly_gaps.csv", ["product", "pre_2020_status", "final_classification", "classification_source", "next_task"]),
        "actual_roll_gaps": ("actual_roll_gaps.csv", ["product", "contract", "period", "gap_type", "final_classification", "next_task"]),
        "profile_bindings": ("profile_bindings.csv", ["profile", "product", "contract", "period", "binding_status", "final_classification", "classification_source"]),
        "cross_file_conflicts": ("cross_file_conflicts.csv", ["product", "contract", "period", "dedupe_key", "final_classification", "classification_source"]),
        "blocked_items": ("blocked_items.csv", ["source", "product", "contract", "period", "reason", "final_classification"]),
        "physical_evidence": (
            "physical_evidence.csv",
            [
                "source_path",
                "physical_path",
                "physical_status",
                "schema_status",
                "checksum_status",
                "row_count_expected",
                "row_count_actual",
                "row_count_status",
                "error",
            ],
        ),
        "duplicate_active_assets": ("duplicate_active_assets.csv", ["product", "contract_role", "contract_code", "period", "duplicate_group_size"]),
        "orphan_files": ("orphan_files.csv", ["product", "physical_path", "period", "final_classification", "classification_source"]),
        "partial_window_audit": ("partial_window_audit.csv", ["product", "contract_code", "audit_end", "day_status", "week_status"]),
    }
    paths: dict[str, Path] = {}
    for key, (filename, required_columns) in mappings.items():
        path = output_dir / filename
        _write_csv(path, payload.get(key, []), required_columns)
        paths[key] = path
    environment_path = output_dir / "environment_evidence.json"
    environment_path.write_text(json.dumps(payload["environment_evidence"], indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    paths["environment_evidence"] = environment_path

    metrics = _current_metrics(
        payload.get("base_target_coverage_matrix", payload["target_coverage_matrix"]),
        payload["metadata_consistency_matrix"],
        payload["weekly_gaps"],
    )
    summary = {
        "gate": READY_GATE,
        "db_snapshot_source": "database",
        "audit_end": audit_end.isoformat(),
        "current_metrics": metrics,
        "phase3_canonical_metrics": PHASE3_METRICS,
        "phase3_delta": {key: metrics.get(key, 0) - value for key, value in PHASE3_METRICS.items()},
        "next_inputs": {
            "B-02": str(published_output_dir / "metadata_consistency_matrix.csv"),
            "B-03": str(published_output_dir / "weekly_gaps.csv"),
            "B-04": str(published_output_dir / "actual_roll_gaps.csv"),
            "B-05": str(published_output_dir / "profile_bindings.csv"),
        },
    }
    summary_json = output_dir / "baseline_summary.json"
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["baseline_summary"] = summary_json
    markdown = output_dir / "DIRECT_DB_BASELINE_AUDIT.md"
    markdown.write_text(_render_summary_markdown(summary, payload), encoding="utf-8")
    paths["summary_markdown"] = markdown
    return paths


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], required_columns: list[str]) -> None:
    materialized = list(rows)
    extras = sorted({str(key) for row in materialized for key in row} - set(required_columns))
    pd.DataFrame(materialized, columns=[*required_columns, *extras]).to_csv(path, index=False)


def _current_metrics(matrix: list[dict[str, Any]], metadata: list[dict[str, Any]], weekly: list[dict[str, Any]]) -> dict[str, int]:
    deduped = {}
    for row in matrix:
        key = (*coverage_key(row), str(row.get("year/window") or row.get("year") or ""))
        deduped.setdefault(key, row)
    counts = Counter(str(row.get("final_classification")) for row in deduped.values())
    counts["metadata_gap"] = sum(1 for row in metadata if row.get("final_classification") == "blocked_with_reason")
    counts["pre_2020_weekly_missing"] = sum(1 for row in weekly if row.get("pre_2020_status") in {"missing_pre2020", "partial_or_missing_pre2020"})
    return dict(counts)


def _render_summary_markdown(summary: dict[str, Any], payload: dict[str, Any]) -> str:
    lines = [
        "# B-01 Direct PostgreSQL Final Baseline Audit",
        "",
        f"Gate: `{READY_GATE}`",
        "",
        "- db_snapshot_source: `database`",
        "- writes_database: `False`",
        "- writes_parquet: `False`",
        "- writes_manifest/quality/profile_binding: `False`",
        "- calls_rqdata: `False`",
        "",
        "## 当前真实指标与旧 Phase 3 差异",
        "",
        "| metric | current | phase3 | delta |",
        "|---|---:|---:|---:|",
    ]
    for key, old_value in PHASE3_METRICS.items():
        current = summary["current_metrics"].get(key, 0)
        lines.append(f"| {key} | {current} | {old_value} | {current - old_value:+d} |")
    lines.extend(
        [
            "",
            "差异来源必须按 CSV 中的 `classification_source` 逐行追溯；旧 Phase 3 数字保留为历史 canonical，不在本报告中改写。",
            "",
            "## 阻塞与下一步输入",
            "",
            f"- blocked_items: {len(payload.get('blocked_items', []))}",
            f"- weekly_gaps: {len(payload.get('weekly_gaps', []))}",
            f"- actual_roll_gaps: {len(payload.get('actual_roll_gaps', []))}",
            f"- profile_bindings: {len(payload.get('profile_bindings', []))}",
            f"- cross_file_conflicts: {len(payload.get('cross_file_conflicts', []))}",
            "- B-02: `metadata_consistency_matrix.csv`",
            "- B-03: `weekly_gaps.csv`",
            "- B-04: `actual_roll_gaps.csv`",
            "- B-05: `profile_bindings.csv`",
            "",
        ]
    )
    return "\n".join(lines)


def resolve_git_context(project_root: Path) -> tuple[str, str, str]:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project_root, check=True, capture_output=True, text=True).stdout.strip()
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=project_root, check=True, capture_output=True, text=True).stdout.strip()
    worktree = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=project_root, check=True, capture_output=True, text=True).stdout.strip()
    return commit, branch, worktree


def build_source_lineage(project_root: Path, relative_paths: Iterable[str]) -> dict[str, Any]:
    commit, branch, worktree = resolve_git_context(project_root)
    status = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    fingerprints = {}
    for relative in relative_paths:
        path = project_root / relative
        if path.is_file():
            fingerprints[relative] = _sha256(path)
    return {
        "git_commit": commit,
        "branch": branch,
        "worktree": worktree,
        "git_status_short": status,
        "source_fingerprints_sha256": fingerprints,
    }


__all__ = [
    "BLOCKED_GATE",
    "AUDIT_FAILED_GATE",
    "ENVIRONMENT_FAILED_GATE",
    "AuditEnvironmentGateError",
    "AuditInputGateError",
    "DirectDatabaseGateError",
    "FINAL_CLASSIFICATIONS",
    "READY_GATE",
    "REQUIRED_SUCCESS_FILENAMES",
    "UNIFIED_MATRIX_COLUMNS",
    "build_profile_binding_audit",
    "build_profile_binding_rows",
    "build_unified_target_matrix",
    "collect_direct_database_evidence",
    "coverage_key",
    "resolve_git_context",
    "build_source_lineage",
    "run_direct_db_audit",
    "sanitize_error",
    "write_blocked_environment_package",
    "write_success_reports",
    "validate_full_universe_scope",
]
