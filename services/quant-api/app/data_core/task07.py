"""Fail-closed Task 07 K-line manifest, migration, and Runtime contracts.

The public Task 07 data path is limited to the exact seven historical bar
frequencies. Manifest and planning never call a provider or mutate business
data. Production writes remain separately approval-gated.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.data_core.bar_schema import CanonicalBar
from app.data_core.canonical_store import (
    CANONICAL_MANIFEST_FORMAT_V2,
    CANONICAL_PARQUET_SCHEMA,
    _validate_stored_manifest_document,
)
from app.data_core.contracts import (
    BarFrequency,
    DatasetKey,
    DatasetKind,
    DatasetOrigin,
    ManifestLineage,
)
from app.data_core.quality import decimal_profile_reason


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TASK_HEAD = re.compile(r"[0-9a-f]{40}\Z")
_DIRECT_FREQUENCIES = {"1m", "1d", "1w"}
_DERIVED_FREQUENCIES = {"5m", "15m", "30m", "60m"}
_SUPPORTED_FREQUENCIES = _DIRECT_FREQUENCIES | _DERIVED_FREQUENCIES
_KLINE_DATA_TYPES = {"bars", "contract_bars_raw", "daily_baseline", "v2_canonical"}
_ACTUAL_CONTRACT = re.compile(r"([A-Z]+)[0-9]{3,4}\Z")
_UNADJUSTED_CONTINUOUS = re.compile(r"([A-Z]+)88\Z")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TASK07_AGGREGATE_MANIFEST_VERSION = "task07-aggregate-migration-v1"
_TASK07_PLAN_RECORD_LIMIT = 50_000
_TASK07_RUNTIME_DATABASE_REVISION = "20260803_0032"
_TASK07_DISABLED_FEATURE_FLAGS = (
    "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED",
    "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED",
    "GUIYI_DATA_CORE_V2_EOD_ENABLED",
    "GUIYI_DATA_CORE_V2_LIVE_DECISION_ENABLED",
    "GUIYI_DATA_CORE_V2_RETENTION_SCHEDULER_ENABLED",
    "GUIYI_DATA_CORE_V2_REVIEW_ENABLED",
    "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED",
    "GUIYI_LIVE_RUNTIME_ENABLED",
    "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
    "GUIYI_WECHAT_AUTOSEND_ENABLED",
)
_REFERENCE_PATTERNS = {
    "profile_active_binding": re.compile(r"\b(?:ProfileActiveBinding|profile_active_bindings)\b"),
    "legacy_reader": re.compile(r"\bMarketDataReader\b"),
    "legacy_active_switch": re.compile(r"\bswitch_profile_active_binding\b"),
    "legacy_selector": re.compile(r"\b(?:profile_id|market_data_file_id)\b"),
    "legacy_bar_path": re.compile(r"(?:data/parquet/canonical/bars|data/raw/rqdata)"),
    "parquet_glob": re.compile(
        r"(?:glob|rglob)\(\s*(?:[rubfRUBF]{0,2})?[\"'][^\"'\n]*\*[^\"'\n]*\.parquet[\"']"
    ),
}
_REFERENCE_SUFFIXES = {
    ".cjs", ".conf", ".html", ".ini", ".js", ".json", ".md", ".mjs",
    ".mts", ".py", ".service", ".sh", ".sql", ".toml", ".ts", ".tsx",
    ".txt", ".vue", ".yaml", ".yml",
}
_REFERENCE_IGNORED_DIRS = {
    ".git", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__", "dist",
    "node_modules",
}
_REFERENCE_SELF_PATHS = {
    "services/quant-api/app/data_core/task07.py",
    "services/quant-api/app/data_core/task07_migration.py",
    "services/quant-api/app/services/derived_reference_inventory.py",
    "services/quant-api/tests/data_core/test_task07_orchestration.py",
    "services/quant-api/tests/test_derived_reference_inventory.py",
}
_RETIRED_LEGACY_MODULES = {
    "services/quant-api/app/data_sources/local_parquet_provider.py",
    "services/quant-api/app/repositories/data_center.py",
    "services/quant-api/app/services/active_dataset.py",
    "services/quant-api/app/services/active_dataset_resolver.py",
    "services/quant-api/app/services/data_profile_registry.py",
    "services/quant-api/app/services/market_data_reader.py",
    "services/quant-api/app/services/market_workbench.py",
    "services/quant-api/app/services/multi_primary_rulebook.py",
    "services/quant-api/app/services/profile_active_switch.py",
    "services/quant-api/app/services/profile_binding_candidate_generator.py",
    "services/quant-api/app/services/profile_binding_rollout.py",
    "services/quant-api/app/services/profile_binding_validator.py",
    "services/quant-api/app/services/profile_lineage.py",
    "services/quant-api/app/services/profile_target_resolver.py",
}
_READONLY_LINEAGE_PATHS = {
    "apps/quant-web/src/components/market/MarketEvidenceDrawer.vue",
    "apps/quant-web/src/components/market/MarketRuntimeObservationPanel.vue",
    "apps/quant-web/src/pages/data/index.vue",
    "apps/quant-web/src/pages/market/chart.vue",
    "apps/quant-web/src/utils/marketRuntimeObservation.ts",
    "packages/quant-core/guiyi_quant/strategies/indicator_policy.py",
    "services/quant-api/app/cli.py",
    "services/quant-api/app/api/data_center.py",
    "services/quant-api/app/api/backtests.py",
    "services/quant-api/app/backtest/runner.py",
    "services/quant-api/app/backtest/service.py",
    "services/quant-api/app/backtest/v1b_jm_tasks.py",
    "services/quant-api/app/data_core/canonical_store.py",
    "services/quant-api/app/data_core/cli_service.py",
    "services/quant-api/app/data_core/historical_migration.py",
    "services/quant-api/app/guiyi_cli/main.py",
    "services/quant-api/app/services/backtest_validation_context.py",
    "services/quant-api/app/services/batch_backtest.py",
    "services/quant-api/app/services/canonical_market_data.py",
    "services/quant-api/app/services/core_cli.py",
    "services/quant-api/app/services/market_indicators.py",
    "services/quant-api/app/services/review_lineage.py",
    "services/quant-api/app/services/runtime_health.py",
    "services/quant-api/app/services/signal_lineage.py",
    "services/quant-api/app/services/signal_scanner.py",
    "services/quant-api/app/signal/events.py",
    "services/quant-api/app/signal/scanner.py",
}
_FROZEN_OBSERVATION_PREFIXES = (
    "services/quant-api/app/backtest/htdy_",
    "services/quant-api/app/services/after_market_",
    "services/quant-api/app/services/htdy_",
    "services/quant-api/app/services/live_",
    "services/quant-api/app/services/s607_",
    "services/quant-api/app/signal/jm_",
    "services/quant-api/app/signal/stage9_",
)
_OFFLINE_DATA_TOOL_PREFIXES = (
    "services/quant-api/app/services/rqdata_ingest/",
    "services/quant-api/scripts/",
)
_EXACT_HISTORICAL_SCRIPT_PATHS = frozenset(
    {
        "scripts/consumer_contract_final_closeout_006.py",
        "scripts/jm_htdy_s6_08_schema_v3_gate.py",
        "scripts/profile_binding_rollout_closeout_008b.py",
        "scripts/rqdata_full_history_residual_closure_apply.py",
        "scripts/s607_database_recovery_gate.py",
        "scripts/signal_review_lineage_gate_003.py",
    }
)
_EXACT_OFFLINE_ADMIN_SCRIPT_PATHS = frozenset(
    {
        "scripts/full_history_audit_v2_closure.py",
        "scripts/rqdata_audit.py",
        "scripts/rqdata_backfill_1w_pre2020_listing.sh",
        "scripts/rqdata_coverage_audit.py",
        "scripts/rqdata_field_audit.py",
        "scripts/rqdata_full_history_residual_closure.py",
        "scripts/rqdata_full_universe_download.sh",
        "scripts/rqdata_v1b_jm_asset.py",
    }
)
_OPERATIONAL_HISTORICAL_SCHEMA_LINES = {
    "scripts/backup/core.py": frozenset(
        {
            ("legacy_selector", "66baf50d803c3f21011c390184e208c2a2c5aade825b1bef63742f446bc4dc98"),
            ("legacy_selector", "fc7acb70303fa4bc316cca1d4dfd45afcc6f35070671ac4973e078b442ac4de7"),
            ("legacy_selector", "ac6979634231292735b28ff31c47d87e25474415b47bf1483bd7faddaab215ef"),
            ("legacy_selector", "76a46700a203fad8683cacf6be8e5eb89fe29a1ae83bd312c2920540edc08e3d"),
            ("legacy_selector", "aed0896a1c3ef2c992e288c49be3e9b195a81b93f984f005e396cd421774f08b"),
            ("legacy_selector", "3e20ca5fc3ae014ebd3c4e40640a019c361c2d2ebd806357bbdbad778f455d49"),
            ("legacy_selector", "a0980f1264acf5c03e2f4d5f99d196f2c0f0a47386675aff46a9de9c15ca9710"),
            ("profile_active_binding", "ac1d284335e8205f755cf8906cc97c039bef6a984be2d32f6c001e93358108f5"),
            ("legacy_selector", "3f58cab2e78f89a071a5c4f943a0f9d447038adcccff8fe6f77b649eae786193"),
            ("legacy_selector", "3355a84e4b9fadaf9b077352daae5db59ad53c4ee54ba938dca324f1b9f84bc8"),
            ("legacy_selector", "58cc18f6dfc525c99be8c2c8a8051f1eab34ea56f786bfcc2bacdb1a4a180355"),
        }
    ),
    "scripts/restore/core.py": frozenset(
        {
            ("profile_active_binding", "f94a9a8a44e7a635bb04f23741f4af00f2848f78c5df8e697e57c10a52d86898"),
            ("legacy_selector", "7765ace4d5b1d55a9b720e5f40e4dca37a69ab9e405d8b03f3363fcb7403e2d6"),
            ("profile_active_binding", "53cefda05f629aa15ec9ee90d49700f918a09d7b4dd6c2bb1c1926c3fb49949d"),
            ("legacy_selector", "4118886f5b42fcef17dc1c883a44438bba75a9f621f27603cd8720fddc35f4de"),
            ("legacy_selector", "43be53e81e731d3db3be81fc55950efbcd32ab56ed1b0ff501db4e34d48a1748"),
            ("legacy_selector", "e216d8bd684a87db18556c9ea00987145ea5a490ee8a465ebe9f9214143e2818"),
            ("legacy_selector", "1290dc1422575e8198dfe104ef7e0fe851d5b6386407833a3d9c39c15b901140"),
            ("legacy_selector", "fa5b631dab7293be21db75d1007f8fd1b9a5ada16b7bb93c04da7e008ff9c5a9"),
        }
    ),
}


class AssetDisposition(StrEnum):
    KEEP_CANONICAL_VERIFIED = "KEEP_CANONICAL_VERIFIED"
    REUSE_TRUSTED_SOURCE = "REUSE_TRUSTED_SOURCE"
    REUSE_VERIFIED_AGGREGATE = "REUSE_VERIFIED_AGGREGATE"
    PROTECTED_EVIDENCE_SOURCE = "PROTECTED_EVIDENCE_SOURCE"
    REGISTER_DATA_GAP = "REGISTER_DATA_GAP"
    CONFLICT_BLOCKED = "CONFLICT_BLOCKED"
    EXCLUDE_DERIVED = "EXCLUDE_DERIVED"
    RETIREMENT_CANDIDATE = "RETIREMENT_CANDIDATE"


@dataclass(frozen=True, slots=True)
class Task07Asset:
    market_data_file_id: int
    provider: str
    data_type: str
    symbol: str
    contract_or_series: str
    frequency: str
    data_role: str
    quality_status: str
    file_path: str
    source_scope: str
    content_gate_status: str
    checksum: str | None
    file_size_bytes: int | None
    physical_exists: bool
    physical_checksum: str | None
    catalog_checksum: str | None
    dataset_kind: str | None
    coverage_start: str | None
    coverage_end: str | None
    row_count: int | None = None
    data_version: str | None = None
    registration_symbol: str | None = None
    registration_contract_or_series: str | None = None
    physical_is_symlink: bool = False
    physical_row_count: int | None = None
    physical_min_datetime: str | None = None
    physical_max_datetime: str | None = None
    declared_periods: tuple[str, ...] = ()
    source_intervals: tuple[str, ...] = ()
    registration_wall_clock_matches: bool | None = None
    quality_evidence_digest: str | None = None
    quality_evidence_count: int = 0
    quality_evidence_statuses: tuple[str, ...] = ()
    main_map_digest: str | None = None
    canonical_partition_id: int | None = None
    manifest_format: str | None = None
    manifest_version: str | None = None
    manifest_uri: str | None = None
    manifest_digest: str | None = None
    source_lineage: Mapping[str, str] | None = None
    canonical_readback_status: str | None = None
    canonical_file_uri: str | None = None
    adjustment: str = "none"
    schema_version: str = "canonical-bar-v1"


def canonical_digest(value: Any) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def classify_asset(asset: Task07Asset) -> AssetDisposition:
    # Protected approvals/evidence are immutable regardless of metadata
    # quality. They cannot enter migration, repair, retirement, or deletion.
    if asset.source_scope == "protected_evidence_root":
        return AssetDisposition.PROTECTED_EVIDENCE_SOURCE
    if asset.source_scope == "outside_approved_roots":
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.data_type == "v2_canonical":
        identity_valid = (
            asset.provider == "rqdata"
            and asset.data_role == "primary"
            and asset.dataset_kind in {"continuous", "actual_dominant"}
            and (
                asset.dataset_kind != "continuous"
                or asset.contract_or_series == f"{asset.symbol.upper()}.MAIN"
            )
        )
        if (
            identity_valid
            and asset.source_scope == "approved_canonical_root"
            and asset.physical_exists
            and asset.checksum
            and asset.checksum == asset.physical_checksum
            and asset.catalog_checksum == asset.physical_checksum
            and asset.content_gate_status in {"passed", "not_inspected"}
            and (
                asset.frequency not in _DERIVED_FREQUENCIES
                or (
                    asset.canonical_readback_status == "passed_aggregate_v2"
                    and asset.manifest_format == CANONICAL_MANIFEST_FORMAT_V2
                    and asset.manifest_version
                    == _TASK07_AGGREGATE_MANIFEST_VERSION
                    and asset.source_lineage is not None
                )
            )
        ):
            return AssetDisposition.KEEP_CANONICAL_VERIFIED
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.frequency in _DERIVED_FREQUENCIES:
        if asset.provider != "rqdata" or asset.data_type != "bars":
            return AssetDisposition.CONFLICT_BLOCKED
        if asset.data_role != "primary" or asset.quality_status != "passed":
            return AssetDisposition.CONFLICT_BLOCKED
        if not asset.physical_exists or asset.quality_evidence_count < 1:
            return AssetDisposition.CONFLICT_BLOCKED
        if asset.quality_evidence_statuses != ("passed",):
            return AssetDisposition.CONFLICT_BLOCKED
        if asset.physical_is_symlink:
            return AssetDisposition.CONFLICT_BLOCKED
        if (
            asset.content_gate_status == "passed"
            and asset.checksum
            and asset.physical_checksum
            and asset.checksum == asset.physical_checksum
            and asset.dataset_kind in {"continuous", "actual_dominant"}
            and asset.declared_periods == (asset.frequency,)
            and asset.source_intervals == ("1m",)
            and asset.physical_row_count == asset.row_count
            and asset.registration_wall_clock_matches is True
            and asset.quality_evidence_digest is not None
            and (
                asset.dataset_kind != "actual_dominant"
                or asset.main_map_digest is not None
            )
        ):
            return AssetDisposition.REUSE_VERIFIED_AGGREGATE
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.frequency == "1d" and asset.source_intervals == ("1m",):
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.provider != "rqdata" or asset.data_type not in _KLINE_DATA_TYPES:
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.data_role != "primary":
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.frequency not in _DIRECT_FREQUENCIES:
        return AssetDisposition.CONFLICT_BLOCKED
    if not asset.symbol or not asset.contract_or_series:
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.dataset_kind not in {"continuous", "actual_dominant"}:
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.dataset_kind == "continuous" and asset.contract_or_series != f"{asset.symbol.upper()}.MAIN":
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.dataset_kind == "actual_dominant":
        match = _ACTUAL_CONTRACT.fullmatch(asset.contract_or_series)
        if match is None or match.group(1) != asset.symbol.upper():
            return AssetDisposition.CONFLICT_BLOCKED
    if asset.content_gate_status in {
        "trading_day_null_conflict",
        "trading_day_weekend_conflict",
        "night_session_trading_day_conflict",
        "day_session_trading_day_conflict",
    }:
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.content_gate_status.endswith("_conflict"):
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.quality_status != "passed":
        return AssetDisposition.CONFLICT_BLOCKED
    if not asset.physical_exists:
        return AssetDisposition.REGISTER_DATA_GAP
    if (
        not asset.checksum
        or not asset.physical_checksum
        or asset.checksum != asset.physical_checksum
        or asset.catalog_checksum is not None
        and asset.catalog_checksum != asset.physical_checksum
    ):
        return AssetDisposition.CONFLICT_BLOCKED
    if asset.catalog_checksum == asset.physical_checksum:
        return AssetDisposition.KEEP_CANONICAL_VERIFIED
    return AssetDisposition.REUSE_TRUSTED_SOURCE


def _asset_record(asset: Task07Asset) -> dict[str, Any]:
    record = asdict(asset)
    record["disposition"] = classify_asset(asset).value
    return record


def _validated_kline_assets(assets: Iterable[Task07Asset]) -> Iterable[Task07Asset]:
    for asset in assets:
        disposition = classify_asset(asset)
        if (
            asset.frequency not in _SUPPORTED_FREQUENCIES
            or asset.data_type not in _KLINE_DATA_TYPES
            or disposition
            in {
                AssetDisposition.PROTECTED_EVIDENCE_SOURCE,
                AssetDisposition.RETIREMENT_CANDIDATE,
                AssetDisposition.EXCLUDE_DERIVED,
            }
        ):
            raise ValueError("TASK07_KLINE_MANIFEST_SCOPE_INVALID")
        yield asset


def build_kline_manifest_index(
    assets: Iterable[Task07Asset],
    *,
    base_sha: str,
    database_revision: str,
    include_assets: bool = True,
) -> dict[str, Any]:
    """Build the exact seven-frequency K-line-only manifest."""

    if not _TASK_HEAD.fullmatch(base_sha):
        raise ValueError("TASK07_BASE_SHA_INVALID")
    digest = sha256()
    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    previous_id = 0
    for asset in _validated_kline_assets(assets):
        if asset.market_data_file_id <= previous_id:
            raise ValueError("TASK07_KLINE_MANIFEST_ORDER_INVALID")
        previous_id = asset.market_data_file_id
        record = _asset_record(asset)
        line = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode() + b"\n"
        digest.update(line)
        counts[str(record["disposition"])] += 1
        if include_assets:
            records.append(record)
    body = {
        "schema_version": 1,
        "command": "data.task07.kline-manifest",
        "status": "complete",
        "readonly_business_data": True,
        "base_sha": base_sha,
        "database_revision": database_revision,
        "supported_frequencies": sorted(_SUPPORTED_FREQUENCIES),
        "asset_count": sum(counts.values()),
        "assets_digest": digest.hexdigest(),
        "classification_counts": dict(sorted(counts.items())),
        "assets": records,
        "truncated": False,
        "calls_rqdata": False,
    }
    return {**body, "manifest_digest": canonical_digest(body)}


def collect_task07_assets(
    session: Session,
    *,
    data_root: Path,
    canonical_root: Path,
    protected_roots: Iterable[Path] = (),
    page_size: int = 1_000,
    inspect_content: bool = True,
) -> Iterable[Task07Asset]:
    """Yield a stable keyset-paginated snapshot of registered physical assets."""

    if page_size < 1:
        raise ValueError("TASK07_PAGE_SIZE_INVALID")
    data_root = _require_inventory_root(data_root, "DATA")
    canonical_root = _require_inventory_root(canonical_root, "CANONICAL")
    protected_aliases: list[Path] = []
    for path in protected_roots:
        protected_aliases.extend(
            (path.absolute(), _require_inventory_root(path, "PROTECTED"))
        )
    protected = tuple(dict.fromkeys(protected_aliases))
    begin_task07_readonly_snapshot(session)
    data = data_root.absolute()
    canonical = canonical_root.absolute()

    cursor = 0
    while True:
        rows = session.execute(
            text(
                "SELECT id, provider, data_type, instrument_symbol, contract_code, period, start_time, end_time, "
                "file_path, file_size_bytes, checksum, data_version, row_count, data_role, quality_status "
                "FROM market_data_files WHERE id > :cursor "
                "AND data_type IN ('bars', 'contract_bars_raw', 'daily_baseline') "
                "AND period IN ('1m', '5m', '15m', '30m', '60m', '1d', '1w') "
                "ORDER BY id LIMIT :page_size"
            ),
            {"cursor": cursor, "page_size": page_size},
        ).mappings().all()
        if not rows:
            break
        catalog_matches = _catalog_matches_for_market_page(
            session,
            rows=rows,
            canonical_root=canonical,
            page_size=page_size,
        )
        hash_cache: dict[str, tuple[bool, str | None]] = {}
        quality_evidence = _quality_evidence_for_file_range(
            session,
            first_file_id=int(rows[0]["id"]),
            last_file_id=int(rows[-1]["id"]),
            page_size=page_size,
        )
        for row in rows:
            cursor = int(row["id"])
            path_text = str(row["file_path"])
            registered_path = Path(path_text).absolute()
            source_path = registered_path.resolve(strict=False)
            source_scope = _source_scope(
                registered_path,
                physical_path=source_path,
                data_root=data,
                canonical_root=canonical,
                protected_roots=protected,
            )
            physical = hash_cache.get(path_text)
            if physical is None:
                physical = (
                    _physical_identity(source_path)
                    if source_scope != "outside_approved_roots"
                    else (False, None)
                )
                hash_cache[path_text] = physical
            identity = _normalize_legacy_dataset_identity(
                str(row["instrument_symbol"] or ""),
                str(row["contract_code"] or ""),
            )
            if identity is None:
                continue
            symbol, contract, dataset_kind = identity
            frequency = str(row["period"] or "")
            content_gate_status = "not_applicable"
            physical_inspection: dict[str, Any] = {}
            if (
                inspect_content
                and physical[0]
                and str(row["provider"]) == "rqdata"
                and str(row["data_role"]) == "primary"
                and str(row["quality_status"]) == "passed"
                and frequency in _DIRECT_FREQUENCIES | _DERIVED_FREQUENCIES
                and str(row["data_type"]) in {"bars", "contract_bars_raw"}
            ):
                if frequency in _DERIVED_FREQUENCIES and str(row["data_type"]) == "bars":
                    physical_inspection = _aggregate_parquet_content_gate(
                        session,
                        registered_path=registered_path,
                        physical_path=source_path,
                        frequency=frequency,
                        registered_row_count=(
                            int(row["row_count"])
                            if row["row_count"] is not None
                            else None
                        ),
                        registered_start=row["start_time"],
                        registered_end=row["end_time"],
                        dataset_kind=_dataset_kind(contract),
                        symbol=symbol,
                        contract=contract,
                    )
                    content_gate_status = str(physical_inspection["status"])
                elif frequency == "1d" and str(row["data_type"]) == "bars":
                    source_intervals = _parquet_declared_values(
                        source_path,
                        "source_interval",
                    )
                    physical_inspection = {"source_intervals": source_intervals}
                    if source_intervals == ("1m",):
                        content_gate_status = "derived_daily_source_interval_1m"
                    else:
                        content_gate_status = _parquet_content_gate(
                            source_path,
                            data_type=str(row["data_type"]),
                            frequency=frequency,
                        )
                else:
                    content_gate_status = _parquet_content_gate(
                        source_path,
                        data_type=str(row["data_type"]),
                        frequency=frequency,
                    )
            reports = quality_evidence.get(cursor, ())
            quality_digest = canonical_digest(reports) if reports else None
            quality_statuses = tuple(
                sorted({str(item["status"]).strip().lower() for item in reports})
            )
            match_key = (
                str(row["provider"]),
                symbol,
                contract,
                frequency,
                str(Path(path_text).absolute()),
            )
            matches = catalog_matches.get(match_key, ())
            catalog_checksum: str | None = None
            if matches:
                kinds = {item[0] for item in matches}
                if len(kinds) == 1:
                    dataset_kind = next(iter(kinds))
                path_checksums = {item[1] for item in matches}
                if path_checksums:
                    catalog_checksum = next(iter(path_checksums)) if len(path_checksums) == 1 else "CATALOG_CONFLICT"
            yield Task07Asset(
                market_data_file_id=cursor,
                provider=str(row["provider"]),
                data_type=str(row["data_type"]),
                symbol=symbol,
                contract_or_series=contract,
                frequency=frequency,
                data_role=str(row["data_role"]),
                quality_status=str(row["quality_status"]),
                file_path=path_text,
                source_scope=source_scope,
                content_gate_status=content_gate_status,
                checksum=str(row["checksum"]) if row["checksum"] else None,
                file_size_bytes=int(row["file_size_bytes"]) if row["file_size_bytes"] is not None else None,
                physical_exists=physical[0],
                physical_checksum=physical[1],
                catalog_checksum=catalog_checksum,
                dataset_kind=dataset_kind,
                coverage_start=_iso(row["start_time"]),
                coverage_end=_iso(row["end_time"]),
                row_count=(int(row["row_count"]) if row["row_count"] is not None else None),
                data_version=(str(row["data_version"]) if row["data_version"] else None),
                registration_symbol=str(
                    row["instrument_symbol"] or ""
                ).strip().lower(),
                registration_contract_or_series=str(
                    row["contract_code"] or ""
                ).strip().upper(),
                physical_is_symlink=registered_path.is_symlink(),
                physical_row_count=physical_inspection.get("physical_row_count"),
                physical_min_datetime=physical_inspection.get("physical_min_datetime"),
                physical_max_datetime=physical_inspection.get("physical_max_datetime"),
                declared_periods=tuple(physical_inspection.get("declared_periods", ())),
                source_intervals=tuple(physical_inspection.get("source_intervals", ())),
                registration_wall_clock_matches=physical_inspection.get(
                    "registration_wall_clock_matches"
                ),
                quality_evidence_digest=quality_digest,
                quality_evidence_count=len(reports),
                quality_evidence_statuses=quality_statuses,
                main_map_digest=physical_inspection.get("main_map_digest"),
            )
    for catalog_row in _iter_task07_catalog_rows(session, page_size=page_size):
        partition_id = catalog_row["id"]
        provider = catalog_row["provider"]
        kind = catalog_row["dataset_kind"]
        symbol = catalog_row["symbol"]
        contract = catalog_row["contract_or_series"]
        frequency = catalog_row["frequency"]
        adjustment = catalog_row["adjustment"]
        schema_version = catalog_row["schema_version"]
        file_uri = catalog_row["file_uri"]
        checksum = catalog_row["checksum"]
        start = catalog_row["coverage_start"]
        end = catalog_row["coverage_end"]
        row_count = catalog_row["row_count"]
        manifest_version = catalog_row["manifest_version"]
        manifest_uri = catalog_row["manifest_uri"]
        manifest_digest = catalog_row["manifest_digest"]
        relative = Path(str(file_uri))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        physical_path = canonical / relative
        exists, physical_checksum = _physical_identity(physical_path)
        try:
            size = physical_path.stat().st_size if exists else None
        except OSError:
            size = None
        canonical_readback = _canonical_partition_readback(
            canonical_root=canonical,
            dataset_kind=str(kind),
            symbol=str(symbol).lower(),
            contract=str(contract).upper(),
            frequency=str(frequency),
            adjustment=str(adjustment),
            schema_version=str(schema_version),
            file_uri=str(file_uri),
            checksum=str(checksum),
            coverage_start=start,
            coverage_end=end,
            row_count=int(row_count),
            manifest_version=str(manifest_version),
            manifest_uri=str(manifest_uri),
            manifest_digest=str(manifest_digest),
        )
        yield Task07Asset(
            market_data_file_id=2_000_000_000 + int(partition_id),
            provider=str(provider),
            data_type="v2_canonical",
            symbol=str(symbol).lower(),
            contract_or_series=str(contract).upper(),
            frequency=str(frequency),
            data_role="primary",
            quality_status="passed",
            file_path=str(physical_path.absolute()),
            source_scope="approved_canonical_root",
            content_gate_status=(
                str(canonical_readback["content_gate_status"])
                if inspect_content
                else "not_inspected"
            ),
            checksum=str(checksum),
            file_size_bytes=size,
            physical_exists=exists,
            physical_checksum=physical_checksum,
            catalog_checksum=str(checksum),
            dataset_kind=str(kind),
            coverage_start=_iso(start),
            coverage_end=_iso(end),
            row_count=int(row_count),
            data_version=None,
            canonical_partition_id=int(partition_id),
            manifest_format=canonical_readback.get("manifest_format"),
            manifest_version=str(manifest_version),
            manifest_uri=str(manifest_uri),
            manifest_digest=str(manifest_digest),
            source_lineage=canonical_readback.get("source_lineage"),
            canonical_readback_status=canonical_readback.get("status"),
            canonical_file_uri=str(file_uri),
            adjustment=str(adjustment),
            schema_version=str(schema_version),
        )


def begin_task07_readonly_snapshot(session: Session) -> None:
    """Start the PostgreSQL snapshot before any Task 07 query."""

    if session.info.get("task07_readonly_snapshot"):
        return
    if session.in_transaction():
        raise ValueError("TASK07_READONLY_SNAPSHOT_STARTED_TOO_LATE")
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )
    session.info["task07_readonly_snapshot"] = True


def _iter_task07_catalog_rows(
    session: Session,
    *,
    page_size: int,
) -> Iterable[Mapping[str, Any]]:
    cursor = 0
    while True:
        rows = session.execute(
            text(
                "SELECT p.id, d.provider, d.dataset_kind, d.symbol, "
                "d.contract_or_series, d.frequency, d.adjustment, "
                "d.schema_version, p.file_uri, p.checksum, p.coverage_start, "
                "p.coverage_end, p.row_count, p.manifest_version, "
                "p.manifest_uri, p.manifest_digest "
                "FROM market_datasets d JOIN market_partitions p "
                "ON p.dataset_id = d.id WHERE p.id > :cursor "
                "AND d.frequency IN ('1m', '5m', '15m', '30m', '60m', '1d', '1w') "
                "ORDER BY p.id LIMIT :page_size"
            ),
            {"cursor": cursor, "page_size": page_size},
        ).mappings().all()
        if not rows:
            return
        for row in rows:
            cursor = int(row["id"])
            yield row


def _catalog_matches_for_market_page(
    session: Session,
    *,
    rows: Sequence[Mapping[str, Any]],
    canonical_root: Path,
    page_size: int,
) -> dict[tuple[str, str, str, str, str], tuple[tuple[str, str], ...]]:
    canonical = canonical_root.absolute()
    keys = sorted(
        {
            (
                str(row["provider"]),
                str(row["instrument_symbol"] or "").lower(),
                str(row["contract_code"] or "").upper(),
                str(row["period"] or ""),
                Path(str(row["file_path"])).absolute().relative_to(canonical).as_posix(),
            )
            for row in rows
            if Path(str(row["file_path"])).absolute().is_relative_to(canonical)
        }
    )
    matches: dict[
        tuple[str, str, str, str, str], set[tuple[str, str]]
    ] = {}
    for offset in range(0, len(keys), 100):
        chunk = keys[offset : offset + 100]
        clauses: list[str] = []
        parameters: dict[str, Any] = {"page_size": page_size}
        for index, (provider, symbol, contract, frequency, file_uri) in enumerate(chunk):
            clauses.append(
                "(d.provider = :provider_{0} AND lower(d.symbol) = :symbol_{0} "
                "AND upper(d.contract_or_series) = :contract_{0} "
                "AND d.frequency = :frequency_{0} "
                "AND p.file_uri = :file_uri_{0})".format(index)
            )
            parameters.update(
                {
                    f"provider_{index}": provider,
                    f"symbol_{index}": symbol,
                    f"contract_{index}": contract,
                    f"frequency_{index}": frequency,
                    f"file_uri_{index}": file_uri,
                }
            )
        cursor = 0
        while clauses:
            parameters["cursor"] = cursor
            catalog_rows = session.execute(
                text(
                    "SELECT p.id, d.provider, d.dataset_kind, d.symbol, "
                    "d.contract_or_series, d.frequency, p.file_uri, p.checksum "
                    "FROM market_datasets d JOIN market_partitions p "
                    "ON p.dataset_id = d.id WHERE p.id > :cursor AND ("
                    + " OR ".join(clauses)
                    + ") ORDER BY p.id LIMIT :page_size"
                ),
                parameters,
            ).mappings().all()
            if not catalog_rows:
                break
            for catalog_row in catalog_rows:
                cursor = int(catalog_row["id"])
                relative = Path(str(catalog_row["file_uri"]))
                if relative.is_absolute() or ".." in relative.parts:
                    continue
                key = (
                    str(catalog_row["provider"]),
                    str(catalog_row["symbol"]).lower(),
                    str(catalog_row["contract_or_series"]).upper(),
                    str(catalog_row["frequency"]),
                    str((canonical_root / relative).absolute()),
                )
                matches.setdefault(key, set()).add(
                    (
                        str(catalog_row["dataset_kind"]),
                        str(catalog_row["checksum"]),
                    )
                )
    return {
        key: tuple(sorted(values)) for key, values in matches.items()
    }


def begin_task07_serializable_apply(session: Session) -> None:
    """Start the retirement write transaction before its first database query."""

    if session.info.get("task07_serializable_apply"):
        return
    if session.get_bind().dialect.name == "postgresql":
        if session.in_transaction():
            raise ValueError("TASK07_SERIALIZABLE_APPLY_STARTED_TOO_LATE")
        # PostgreSQL SERIALIZABLE predicate locks make a concurrent insertion
        # into the active row-set conflict with this transaction instead of
        # silently escaping the approved manifest.
        session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
    session.info["task07_serializable_apply"] = True


def _dataset_kind(contract: str) -> str | None:
    if contract.endswith(".MAIN"):
        return "continuous"
    if _ACTUAL_CONTRACT.fullmatch(contract):
        return "actual_dominant"
    return None


def _normalize_legacy_dataset_identity(
    symbol: str,
    contract: str,
) -> tuple[str, str, str] | None:
    """Map only exact V2 target identities; unsupported legacy series stay out."""

    normalized_symbol = str(symbol or "").strip().lower()
    normalized_contract = str(contract or "").strip().upper()
    actual = _ACTUAL_CONTRACT.fullmatch(normalized_contract)
    if actual is not None:
        derived_symbol = actual.group(1).lower()
        if normalized_symbol and normalized_symbol != derived_symbol:
            return None
        return derived_symbol, normalized_contract, "actual_dominant"
    if normalized_contract.endswith(".MAIN"):
        derived_symbol = normalized_contract[: -len(".MAIN")].lower()
        if not derived_symbol or (
            normalized_symbol and normalized_symbol != derived_symbol
        ):
            return None
        return derived_symbol, normalized_contract, "continuous"
    continuous = _UNADJUSTED_CONTINUOUS.fullmatch(normalized_contract)
    if continuous is not None:
        derived_symbol = continuous.group(1).lower()
        if normalized_symbol and normalized_symbol != derived_symbol:
            return None
        return derived_symbol, f"{derived_symbol.upper()}.MAIN", "continuous"
    return None


def _source_scope(
    registered_path: Path,
    *,
    physical_path: Path,
    data_root: Path,
    canonical_root: Path,
    protected_roots: tuple[Path, ...],
) -> str:
    if any(
        registered_path.is_relative_to(root) or physical_path.is_relative_to(root)
        for root in protected_roots
    ):
        return "protected_evidence_root"
    if physical_path.is_relative_to(canonical_root):
        return "approved_canonical_root"
    if physical_path.is_relative_to(data_root):
        return "approved_data_root"
    return "outside_approved_roots"


def _require_inventory_root(path: Path, label: str) -> Path:
    absolute = path.absolute()
    if not absolute.is_dir() or absolute.is_symlink():
        raise ValueError(f"TASK07_{label}_ROOT_INVALID")
    try:
        return absolute.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"TASK07_{label}_ROOT_INVALID") from exc


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    method = getattr(value, "isoformat", None)
    return str(method() if callable(method) else value)


def _physical_identity(path: Path) -> tuple[bool, str | None]:
    try:
        if not path.is_file() or path.is_symlink():
            return False, None
        digest = sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return True, digest.hexdigest()
    except OSError:
        return False, None


def _parquet_content_gate(path: Path, *, data_type: str, frequency: str) -> str:
    try:
        # Read the physical file directly. ``pq.read_table(path)`` treats a file
        # below Hive-style directories as a dataset and can merge inferred
        # partition columns with same-named columns stored in legacy bar files.
        parquet_file = pq.ParquetFile(path)
        schema_names = set(parquet_file.schema_arrow.names)
        day_column = "trading_day" if "trading_day" in schema_names else "trading_date"
        time_column = (
            "bar_end"
            if "bar_end" in schema_names
            else "datetime"
            if "datetime" in schema_names
            else "date"
        )
        if day_column not in schema_names or time_column not in schema_names:
            return "schema_conflict"
        table = parquet_file.read(columns=[time_column, day_column])
        times = table.column(time_column).to_pylist()
        days = table.column(day_column).to_pylist()
    except (OSError, ValueError, TypeError):
        return "schema_conflict"
    if not times or len(times) != len(days):
        return "schema_conflict"
    for timestamp, raw_day in zip(times, days, strict=True):
        if timestamp is None or raw_day is None:
            return "trading_day_null_conflict"
        trading_day = raw_day.date() if hasattr(raw_day, "date") else raw_day
        if not hasattr(trading_day, "weekday") or trading_day.weekday() >= 5:
            return "trading_day_weekend_conflict"
        if frequency != "1m":
            continue
        if not hasattr(timestamp, "hour"):
            return "schema_conflict"
        local = timestamp
        if getattr(timestamp, "tzinfo", None) is not None:
            local = timestamp.astimezone(_SHANGHAI)
        local_day = local.date()
        if local.hour >= 21 and trading_day <= local_day:
            return "night_session_trading_day_conflict"
        if 3 <= local.hour < 21 and trading_day != local_day:
            return "day_session_trading_day_conflict"
    return "passed"


def _canonical_partition_readback(
    *,
    canonical_root: Path,
    dataset_kind: str,
    symbol: str,
    contract: str,
    frequency: str,
    adjustment: str,
    schema_version: str,
    file_uri: str,
    checksum: str,
    coverage_start: object,
    coverage_end: object,
    row_count: int,
    manifest_version: str,
    manifest_uri: str,
    manifest_digest: str,
) -> dict[str, Any]:
    failed = {
        "status": "canonical_readback_conflict",
        "content_gate_status": "canonical_readback_conflict",
        "manifest_format": None,
        "source_lineage": None,
    }
    try:
        dataset = DatasetKey(
            provider="rqdata",
            dataset_kind=DatasetKind(dataset_kind),
            symbol=symbol,
            contract_or_series=contract,
            frequency=BarFrequency(frequency),
            adjustment=adjustment,
            schema_version=schema_version,
        )
        root = canonical_root.resolve(strict=True)
        relative_file = Path(file_uri)
        relative_manifest = Path(manifest_uri)
        if (
            relative_file.is_absolute()
            or relative_manifest.is_absolute()
            or ".." in relative_file.parts
            or ".." in relative_manifest.parts
        ):
            return failed
        file_path = root / relative_file
        manifest_path = root / relative_manifest
        if (
            not file_path.is_file()
            or file_path.is_symlink()
            or not manifest_path.is_file()
            or manifest_path.is_symlink()
            or _physical_identity(file_path) != (True, checksum)
        ):
            return failed
        parquet = pq.ParquetFile(file_path)
        if (
            parquet.schema_arrow != CANONICAL_PARQUET_SCHEMA
            or int(parquet.metadata.num_rows) != row_count
        ):
            return failed
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            return failed
        partition = document.get("partition")
        if not isinstance(partition, Mapping):
            return failed
        validated_document = _validate_stored_manifest_document(
            document,
            dataset=dataset,
            coverage_start=_catalog_utc_datetime(coverage_start),
            coverage_end=_catalog_utc_datetime(coverage_end),
            row_count=row_count,
            data_version=str(partition["data_version"]),
            manifest_version=manifest_version,
            file_uri=file_uri,
            manifest_uri=manifest_uri,
            file_checksum=checksum,
            canonical_logical_fingerprint=str(
                document["canonical_logical_fingerprint"]
            ),
            overlap_reason=(
                str(partition["overlap_reason"])
                if partition.get("overlap_reason") is not None
                else None
            ),
        )
        if validated_document.get("manifest_digest") != manifest_digest:
            return failed
        manifest_format = document.get("manifest_format")
        lineage_payload = document.get("source_lineage")
        if dataset.frequency.value in _DERIVED_FREQUENCIES:
            if (
                manifest_format != CANONICAL_MANIFEST_FORMAT_V2
                or manifest_version != _TASK07_AGGREGATE_MANIFEST_VERSION
            ):
                return failed
            lineage = ManifestLineage.from_payload(lineage_payload)
            lineage.validate_dataset(dataset)
            if (
                lineage.origin is not DatasetOrigin.PREAGGREGATED_FROM_1M
                or lineage.source_frequency is not BarFrequency.M1
            ):
                return failed
            status = "passed_aggregate_v2"
        else:
            status = "passed_direct"
            lineage_payload = None
        return {
            "status": status,
            "content_gate_status": "passed",
            "manifest_format": str(manifest_format),
            "source_lineage": lineage_payload,
        }
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return failed


def _catalog_utc_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError("datetime required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _quality_evidence_for_file_range(
    session: Session,
    *,
    first_file_id: int,
    last_file_id: int,
    page_size: int,
) -> dict[int, tuple[dict[str, Any], ...]]:
    by_file: dict[int, list[dict[str, Any]]] = {}
    file_cursor = first_file_id - 1
    report_cursor = 0
    while True:
        rows = session.execute(
            text(
                "SELECT id, file_id, task_id, provider, data_type, instrument_symbol, "
                "contract_code, period, start_time, end_time, status, missing_bars, "
                "duplicated_bars, abnormal_price_count, abnormal_volume_count, details, "
                "created_at FROM data_quality_reports "
                "WHERE file_id BETWEEN :first_file_id AND :last_file_id "
                "AND (file_id > :file_cursor OR "
                "(file_id = :file_cursor AND id > :report_cursor)) "
                "ORDER BY file_id, id LIMIT :page_size"
            ),
            {
                "first_file_id": first_file_id,
                "last_file_id": last_file_id,
                "file_cursor": file_cursor,
                "report_cursor": report_cursor,
                "page_size": page_size,
            },
        ).mappings().all()
        if not rows:
            break
        for row in rows:
            file_id = int(row["file_id"])
            report_id = int(row["id"])
            by_file.setdefault(file_id, []).append(
                _quality_evidence_record(row)
            )
            file_cursor = file_id
            report_cursor = report_id
    return {
        file_id: tuple(records)
        for file_id, records in by_file.items()
    }


def read_task07_quality_evidence(
    session: Session,
    *,
    market_data_file_id: int,
    page_size: int = 1_000,
) -> tuple[dict[str, Any], ...]:
    """Re-read one source's complete linked quality evidence without an ID list."""

    if market_data_file_id < 1 or page_size < 1:
        raise ValueError("TASK07_QUALITY_EVIDENCE_SCOPE_INVALID")
    return _quality_evidence_for_file_range(
        session,
        first_file_id=market_data_file_id,
        last_file_id=market_data_file_id,
        page_size=page_size,
    ).get(market_data_file_id, ())


def _quality_evidence_record(row: Mapping[str, Any]) -> dict[str, Any]:
    details: Any = row["details"]
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            pass
    return {
        "id": int(row["id"]),
        "file_id": int(row["file_id"]),
        "task_id": int(row["task_id"]) if row["task_id"] is not None else None,
        "provider": str(row["provider"] or ""),
        "data_type": str(row["data_type"] or ""),
        "instrument_symbol": str(row["instrument_symbol"] or ""),
        "contract_code": str(row["contract_code"] or ""),
        "period": str(row["period"] or ""),
        "start_time": _iso(row["start_time"]),
        "end_time": _iso(row["end_time"]),
        "status": str(row["status"] or "").strip().lower(),
        "missing_bars": int(row["missing_bars"] or 0),
        "duplicated_bars": int(row["duplicated_bars"] or 0),
        "abnormal_price_count": int(row["abnormal_price_count"] or 0),
        "abnormal_volume_count": int(row["abnormal_volume_count"] or 0),
        "details": details,
        "created_at": _iso(row["created_at"]),
    }


def _aggregate_parquet_content_gate(
    session: Session,
    *,
    registered_path: Path,
    physical_path: Path,
    frequency: str,
    registered_row_count: int | None,
    registered_start: object,
    registered_end: object,
    dataset_kind: str | None,
    symbol: str,
    contract: str,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "status": "schema_conflict",
        "physical_row_count": None,
        "physical_min_datetime": None,
        "physical_max_datetime": None,
        "declared_periods": (),
        "source_intervals": (),
        "registration_wall_clock_matches": False,
        "main_map_digest": None,
    }
    if registered_path.is_symlink():
        return {**evidence, "status": "symlink_conflict"}
    try:
        parquet = pq.ParquetFile(physical_path)
        names = set(parquet.schema_arrow.names)
        day_column = (
            "trading_day" if "trading_day" in names else "trading_date"
        )
        required = {
            "datetime",
            day_column,
            "open",
            "high",
            "low",
            "close",
            "volume",
            "period",
            "source_interval",
        }
        if not required <= names:
            return evidence
        columns = [
            "datetime",
            day_column,
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "open_interest",
            "period",
            "source_interval",
        ]
    except (OSError, TypeError, ValueError):
        return evidence
    physical_row_count = int(parquet.metadata.num_rows)
    if registered_row_count != physical_row_count:
        return {
            **evidence,
            "physical_row_count": physical_row_count,
            "status": "row_count_conflict",
        }
    declared_period_values: set[str] = set()
    source_interval_values: set[str] = set()
    physical_min: datetime | None = None
    physical_max: datetime | None = None
    previous_bar_end: datetime | None = None
    processed_row_count = 0
    trading_days: set[date] = set()
    try:
        target_frequency = BarFrequency(frequency)
        target_kind = DatasetKind(dataset_kind)
        for batch in parquet.iter_batches(
            batch_size=65_536,
            columns=[item for item in columns if item in names],
        ):
            for row in batch.to_pylist():
                processed_row_count += 1
                declared_period_values.add(
                    str(row.get("period") or "").strip().lower()
                )
                source_interval_values.add(
                    str(row.get("source_interval") or "").strip().lower()
                )
                raw_bar_end = row.get("datetime")
                if not isinstance(raw_bar_end, datetime) or (
                    raw_bar_end.tzinfo is not None
                    and raw_bar_end.utcoffset() is not None
                ):
                    return {
                        **evidence,
                        "physical_row_count": physical_row_count,
                        "status": "datetime_timezone_conflict",
                    }
                if previous_bar_end is not None and raw_bar_end <= previous_bar_end:
                    return {
                        **evidence,
                        "physical_row_count": physical_row_count,
                        "status": "duplicate_or_order_conflict",
                    }
                previous_bar_end = raw_bar_end
                physical_min = (
                    raw_bar_end
                    if physical_min is None
                    else min(physical_min, raw_bar_end)
                )
                physical_max = (
                    raw_bar_end
                    if physical_max is None
                    else max(physical_max, raw_bar_end)
                )
                trading_day = _source_trading_day(row[day_column])
                trading_days.add(trading_day)
                values = {
                    field: (
                        None
                        if row.get(field) is None
                        and field in {"turnover", "open_interest"}
                        else Decimal(str(row.get(field)))
                    )
                    for field in (
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "turnover",
                        "open_interest",
                    )
                }
                if any(
                    value is not None
                    and decimal_profile_reason(value) is not None
                    for value in values.values()
                ):
                    return {
                        **evidence,
                        "physical_row_count": physical_row_count,
                        "status": "canonical_profile_conflict",
                    }
                CanonicalBar(
                    provider="rqdata",
                    dataset_kind=target_kind,
                    symbol=symbol,
                    contract_or_series=contract,
                    frequency=target_frequency,
                    bar_end=raw_bar_end.replace(tzinfo=_SHANGHAI).astimezone(UTC),
                    trading_day=trading_day,
                    open=values["open"],
                    high=values["high"],
                    low=values["low"],
                    close=values["close"],
                    volume=values["volume"],
                    turnover=values["turnover"],
                    open_interest=values["open_interest"],
                    adjustment="none",
                    schema_version="canonical-bar-v1",
                )
    except (ArithmeticError, OSError, TypeError, ValueError):
        return {
            **evidence,
            "physical_row_count": physical_row_count,
            "status": "canonical_profile_conflict",
        }
    declared_periods = tuple(sorted(declared_period_values))
    source_intervals = tuple(sorted(source_interval_values))
    evidence.update(
        {
            "physical_row_count": physical_row_count,
            "physical_min_datetime": (
                physical_min.isoformat() if physical_min is not None else None
            ),
            "physical_max_datetime": (
                physical_max.isoformat() if physical_max is not None else None
            ),
            "declared_periods": declared_periods,
            "source_intervals": source_intervals,
        }
    )
    if (
        processed_row_count == 0
        or processed_row_count != physical_row_count
        or physical_min is None
        or physical_max is None
    ):
        return {**evidence, "status": "row_count_conflict"}
    if declared_periods != (frequency,):
        return {**evidence, "status": "period_conflict"}
    if source_intervals != ("1m",):
        return {**evidence, "status": "source_interval_conflict"}
    try:
        registered_min = _registration_wall_clock_component(registered_start)
        registered_max = _registration_wall_clock_component(registered_end)
    except (TypeError, ValueError):
        return {**evidence, "status": "registration_coverage_conflict"}
    registration_matches = (
        physical_min == registered_min and physical_max == registered_max
    )
    evidence["registration_wall_clock_matches"] = registration_matches
    if not registration_matches:
        return {**evidence, "status": "registration_coverage_conflict"}
    if dataset_kind not in {"continuous", "actual_dominant"}:
        return {**evidence, "status": "identity_conflict"}
    if dataset_kind == "continuous" and contract != f"{symbol.upper()}.MAIN":
        return {**evidence, "status": "identity_conflict"}
    if dataset_kind == "actual_dominant":
        main_map_digest = _aggregate_main_map_digest(
            session,
            symbol=symbol,
            contract=contract,
            trading_days=trading_days,
        )
        if main_map_digest is None:
            return {**evidence, "status": "main_map_conflict"}
        evidence["main_map_digest"] = main_map_digest
    return {**evidence, "status": "passed"}


def _parquet_declared_values(path: Path, column: str) -> tuple[str, ...]:
    try:
        parquet = pq.ParquetFile(path)
        if column not in parquet.schema_arrow.names:
            return ()
        values = parquet.read(columns=[column]).column(column).to_pylist()
    except (OSError, TypeError, ValueError):
        return ()
    return tuple(
        sorted({str(item).strip().lower() for item in values if item is not None})
    )


def _registration_wall_clock_component(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError("registration datetime required")
    if parsed.tzinfo is not None and parsed.utcoffset() is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _source_trading_day(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _aggregate_main_map_digest(
    session: Session,
    *,
    symbol: str,
    contract: str,
    trading_days: set[date],
) -> str | None:
    if not trading_days:
        return None
    rows = session.execute(
        text(
            "SELECT id, trade_date, contract_code, data_version "
            "FROM main_contract_map WHERE lower(instrument_symbol) = :symbol "
            "AND provider = 'rqdata' AND rule = 'volume_open_interest' "
            "AND rank = 1 AND trade_date BETWEEN :start_day AND :end_day "
            "ORDER BY trade_date, data_version, id"
        ),
        {
            "symbol": symbol,
            "start_day": min(trading_days),
            "end_day": max(trading_days),
        },
    ).mappings().all()
    records = [
        {
            "id": int(row["id"]),
            "trading_day": _source_trading_day(row["trade_date"]).isoformat(),
            "contract": str(row["contract_code"] or "").strip().upper(),
            "data_version": str(row["data_version"] or ""),
        }
        for row in rows
        if _source_trading_day(row["trade_date"]) in trading_days
    ]
    contracts_by_day = {
        day: {
            item["contract"]
            for item in records
            if item["trading_day"] == day.isoformat()
        }
        for day in trading_days
    }
    if any(values != {contract} for values in contracts_by_day.values()):
        return None
    return canonical_digest(records)


def _scan_task07_references(roots: Iterable[tuple[str, Path]]) -> dict[str, Any]:
    """Scan checkout/runtime text surfaces without file-count or finding truncation."""

    records: list[dict[str, Any]] = []
    root_manifest: list[dict[str, str]] = []
    scanned_files = 0
    for root_kind, raw_root in roots:
        root = raw_root.absolute()
        if root_kind not in {"checkout", "detached_runtime"} or not root.is_dir() or root.is_symlink():
            raise ValueError("TASK07_REFERENCE_ROOT_INVALID")
        resolved_root = root.resolve(strict=True)
        root_record = {"root_kind": root_kind, "path": str(resolved_root)}
        if root_record in root_manifest:
            raise ValueError("TASK07_REFERENCE_ROOT_DUPLICATE")
        root_manifest.append(root_record)
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root)
            if relative.as_posix() in _REFERENCE_SELF_PATHS:
                continue
            if any(part in _REFERENCE_IGNORED_DIRS for part in relative.parts):
                continue
            if relative.parts[:1] == ("data",) or relative.parts[:2] == ("backtests", "results"):
                continue
            if path.suffix.lower() not in _REFERENCE_SUFFIXES and path.name not in {"Dockerfile", "Makefile"}:
                continue
            scanned_files += 1
            try:
                file_matches: list[dict[str, Any]] = []
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, 1):
                        line_digest = sha256(line.encode()).hexdigest()
                        for marker, pattern in _REFERENCE_PATTERNS.items():
                            if pattern.search(line):
                                file_matches.append(
                                    {
                                        "line": line_number,
                                        "marker": marker,
                                        "line_sha256": line_digest,
                                    }
                                )
                expected_snapshot = _OPERATIONAL_HISTORICAL_SCHEMA_LINES.get(
                    relative.as_posix()
                )
                snapshot_intact = (
                    root_kind == "checkout"
                    and expected_snapshot is not None
                    and Counter(
                        (item["marker"], item["line_sha256"])
                        for item in file_matches
                    )
                    == Counter(expected_snapshot)
                )
                for item in file_matches:
                    state, reason = _reference_classification(
                        root_kind,
                        relative,
                        item["marker"],
                        item["line_sha256"],
                        operational_snapshot_intact=snapshot_intact,
                    )
                    records.append(
                        {
                            "root_kind": root_kind,
                            "path": relative.as_posix(),
                            **item,
                            "reference_state": state,
                            "classification_reason": reason,
                        }
                    )
            except OSError as exc:
                raise ValueError("TASK07_REFERENCE_READ_FAILED") from exc
    records.sort(
        key=lambda item: (
            item["root_kind"], item["path"], item["line"], item["marker"]
        )
    )
    root_manifest.sort(key=lambda item: (item["root_kind"], item["path"]))
    state_counts = {
        state: sum(item["reference_state"] == state for item in records)
        for state in ("active", "historical_non_active", "review_required")
    }
    return {
        "schema_version": 2,
        "roots": root_manifest,
        "scanned_file_count": scanned_files,
        "record_count": len(records),
        "state_counts": state_counts,
        "records": records,
        "references_digest": canonical_digest(records),
        "truncated": False,
    }


def _reference_snapshot(
    report: Mapping[str, Any],
    *,
    require_complete_scope: bool = True,
) -> dict[str, Any]:
    roots = report.get("roots")
    state_counts = report.get("state_counts")
    if (
        report.get("schema_version") != 2
        or report.get("truncated") is not False
        or not isinstance(roots, list)
        or not isinstance(state_counts, Mapping)
    ):
        raise ValueError("TASK07_REFERENCE_REPORT_INVALID")
    normalized_roots: list[dict[str, str]] = []
    for item in roots:
        if not isinstance(item, Mapping):
            raise ValueError("TASK07_REFERENCE_REPORT_INVALID")
        kind = item.get("root_kind")
        path = item.get("path")
        if (
            kind not in {"checkout", "detached_runtime"}
            or not isinstance(path, str)
            or not Path(path).is_absolute()
        ):
            raise ValueError("TASK07_REFERENCE_REPORT_INVALID")
        normalized_roots.append({"root_kind": str(kind), "path": path})
    if normalized_roots != sorted(
        normalized_roots,
        key=lambda item: (item["root_kind"], item["path"]),
    ) or len({(item["root_kind"], item["path"]) for item in normalized_roots}) != len(
        normalized_roots
    ):
        raise ValueError("TASK07_REFERENCE_REPORT_INVALID")
    kinds = {item["root_kind"] for item in normalized_roots}
    scope_complete = kinds == {"checkout", "detached_runtime"}
    if require_complete_scope and not scope_complete:
        raise ValueError("TASK07_REFERENCE_SCOPE_INCOMPLETE")
    counts: dict[str, int] = {}
    for state in ("active", "historical_non_active", "review_required"):
        value = state_counts.get(state)
        if type(value) is not int or value < 0:
            raise ValueError("TASK07_REFERENCE_REPORT_INVALID")
        counts[state] = value
    record_count = report.get("record_count")
    scanned_file_count = report.get("scanned_file_count")
    references_digest = report.get("references_digest")
    if (
        type(record_count) is not int
        or record_count < 0
        or sum(counts.values()) != record_count
        or type(scanned_file_count) is not int
        or scanned_file_count < 0
        or not isinstance(references_digest, str)
        or not _SHA256.fullmatch(references_digest)
    ):
        raise ValueError("TASK07_REFERENCE_REPORT_INVALID")
    records = report.get("records")
    if records is not None and (
        not isinstance(records, list)
        or len(records) != record_count
        or canonical_digest(records) != references_digest
    ):
        raise ValueError("TASK07_REFERENCE_REPORT_INVALID")
    return {
        "schema_version": 2,
        "roots": normalized_roots,
        "scope_complete": scope_complete,
        "scanned_file_count": scanned_file_count,
        "record_count": record_count,
        "state_counts": counts,
        "references_digest": references_digest,
        "truncated": False,
    }


def build_migration_envelope(
    batches: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    manifest: list[dict[str, str]] = []
    for batch in batches:
        batch_key = batch.get("batch_key")
        batch_digest = batch.get("batch_digest")
        if (
            not isinstance(batch_key, str)
            or not batch_key
            or "\x00" in batch_key
            or not isinstance(batch_digest, str)
            or not _SHA256.fullmatch(batch_digest)
        ):
            raise ValueError("TASK07_MIGRATION_ENVELOPE_INVALID")
        manifest.append(
            {"batch_key": batch_key, "batch_digest": batch_digest}
        )
    manifest.sort(key=lambda item: item["batch_key"])
    if len({item["batch_key"] for item in manifest}) != len(manifest):
        raise ValueError("TASK07_MIGRATION_ENVELOPE_INVALID")
    level = [
        sha256(
            b"\x00"
            + item["batch_key"].encode("utf-8")
            + b"\x00"
            + bytes.fromhex(item["batch_digest"])
        ).digest()
        for item in manifest
    ]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            sha256(b"\x01" + level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    body = {
        "schema_version": 2,
        "hash_algorithm": "sha256",
        "leaf_domain": "00",
        "node_domain": "01",
        "empty_domain": "02",
        "odd_leaf_rule": "duplicate_last_at_each_level",
        "batch_count": len(manifest),
        "batch_manifest": manifest,
        "merkle_root": level[0].hex() if level else sha256(b"\x02").hexdigest(),
    }
    return {**body, "envelope_digest": canonical_digest(body)}


def _migration_write_targets_valid(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) != {
        "staging_root",
        "canonical_root",
        "postgresql_target",
        "protected_roots",
    }:
        return False
    staging_text = value.get("staging_root")
    canonical_text = value.get("canonical_root")
    database = value.get("postgresql_target")
    protected = value.get("protected_roots")
    if (
        not isinstance(staging_text, str)
        or not Path(staging_text).is_absolute()
        or not isinstance(canonical_text, str)
        or not Path(canonical_text).is_absolute()
        or not isinstance(database, Mapping)
        or not isinstance(protected, list)
        or not all(isinstance(item, str) and Path(item).is_absolute() for item in protected)
    ):
        return False
    if set(database) != {"drivername", "username", "host", "port", "database"}:
        return False
    if (
        database.get("drivername") != "postgresql+psycopg"
        or not all(
            isinstance(database.get(key), str) and bool(database.get(key))
            for key in ("username", "host", "database")
        )
        or type(database.get("port")) is not int
        or not 1 <= int(database["port"]) <= 65535
    ):
        return False
    staging = Path(staging_text)
    canonical = Path(canonical_text)
    if _paths_overlap(staging, canonical):
        return False
    protected_paths = [Path(item) for item in protected]
    return not any(
        _paths_overlap(target, root)
        for target in (staging, canonical)
        for root in protected_paths
    )


def _reference_classification(
    root_kind: str,
    relative: Path,
    marker: str,
    line_digest: str,
    *,
    operational_snapshot_intact: bool,
) -> tuple[str, str]:
    parts = relative.parts
    path = relative.as_posix()
    if (
        parts[:2] == (".superpowers", "sdd")
        and re.fullmatch(r"task-[0-9]+-(?:brief|report)\.md", relative.name)
    ):
        return "historical_non_active", "sdd_task_evidence"
    if "tests" in parts or "e2e" in parts:
        return "historical_non_active", "test_or_fixture_reference"
    if path.startswith("services/quant-api/alembic/") or "migrations" in parts:
        return "historical_non_active", "immutable_schema_history"
    if parts[:1] in {(".agents",), ("configs",), ("docs",), ("experiments",)}:
        return "historical_non_active", "documentation_or_frozen_evidence"
    if root_kind == "detached_runtime" and parts[:1] in {
        ("services",),
        ("packages",),
        ("apps",),
    }:
        if marker == "legacy_selector":
            return "review_required", "detached_runtime_selector_requires_reachability_review"
        return "active", "detached_runtime_executable_reference"
    if path in _RETIRED_LEGACY_MODULES:
        return "historical_non_active", "retired_legacy_module_not_runtime_selected"
    if path.startswith(_OFFLINE_DATA_TOOL_PREFIXES):
        return "historical_non_active", "offline_data_tool_not_runtime_wired"
    if path.startswith(_FROZEN_OBSERVATION_PREFIXES):
        return "historical_non_active", "task06_frozen_observation_lineage_not_data_selection"
    if root_kind == "checkout" and path in _EXACT_HISTORICAL_SCRIPT_PATHS:
        return "historical_non_active", "exact_historical_gate_script"
    if root_kind == "checkout" and path in _EXACT_OFFLINE_ADMIN_SCRIPT_PATHS:
        return "historical_non_active", "exact_offline_admin_script"
    if (
        root_kind == "checkout"
        and operational_snapshot_intact
        and (marker, line_digest)
        in _OPERATIONAL_HISTORICAL_SCHEMA_LINES.get(path, frozenset())
    ):
        return "historical_non_active", "exact_operational_historical_schema_line"
    if path in _READONLY_LINEAGE_PATHS:
        return "historical_non_active", "readonly_historical_lineage_or_retired_cli"
    if path.startswith("services/quant-api/app/models/") or path.startswith(
        "services/quant-api/app/schemas/"
    ):
        return "historical_non_active", "retained_database_or_response_schema"
    if path.startswith("apps/quant-web/src/types/") and marker == "legacy_selector":
        return "historical_non_active", "readonly_frontend_snapshot_type"
    if root_kind == "detached_runtime":
        return "review_required", "detached_runtime_unclassified_reference"
    if marker == "legacy_selector":
        return "review_required", "selector_requires_manual_reachability_review"
    if parts[:1] in {("services",), ("packages",), ("apps",)}:
        return "active", "executable_source_reference"
    return "review_required", "unclassified_reference"


def _build_inventory_index(
    assets: Iterable[Task07Asset],
    *,
    base_sha: str,
    database_revision: str,
    include_assets: bool = True,
) -> dict[str, Any]:
    if not _TASK_HEAD.fullmatch(base_sha):
        raise ValueError("TASK07_BASE_SHA_INVALID")
    digest = sha256()
    records: list[dict[str, Any]] = []
    counts = {item.value: 0 for item in AssetDisposition}
    asset_count = 0
    previous_id = 0
    for asset in assets:
        if asset.market_data_file_id <= previous_id:
            raise ValueError("TASK07_INVENTORY_ORDER_INVALID")
        previous_id = asset.market_data_file_id
        record = _asset_record(asset)
        digest.update(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
        counts[record["disposition"]] += 1
        asset_count += 1
        if include_assets:
            records.append(record)
    eligible = (
        counts[AssetDisposition.KEEP_CANONICAL_VERIFIED]
        + counts[AssetDisposition.REUSE_TRUSTED_SOURCE]
        + counts[AssetDisposition.REUSE_VERIFIED_AGGREGATE]
    )
    return {
        "schema_version": 1,
        "command": "data.task07.inventory",
        "status": "complete",
        "readonly_business_data": True,
        "base_sha": base_sha,
        "database_revision": database_revision,
        "asset_count": asset_count,
        "eligible_asset_count": eligible,
        "blocked_asset_count": counts[AssetDisposition.CONFLICT_BLOCKED],
        "disposition_counts": counts,
        "assets_digest": digest.hexdigest(),
        "assets": records,
        "truncated": False,
        "deletion_authorized": False,
        "calls_rqdata": False,
    }


def _write_inventory_evidence(
    assets: Iterable[Task07Asset],
    *,
    evidence_root: Path,
    base_sha: str,
    database_revision: str,
    shard_size: int = 10_000,
    reference_report: Mapping[str, Any] | None = None,
    inventory_scope: Mapping[str, Any] | None = None,
    evidence_command: str = "data.task07.inventory",
    index_name: str = "inventory-index.json",
    scope_name: str = "inventory_scope",
    supported_frequencies: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Create exact, chunked evidence without modifying business data."""

    if shard_size < 1:
        raise ValueError("TASK07_SHARD_SIZE_INVALID")
    root = evidence_root.absolute()
    if root.exists() and root.is_symlink():
        raise ValueError("TASK07_EVIDENCE_ROOT_SYMLINK")
    root.mkdir(parents=True, exist_ok=True)
    if Path(index_name).name != index_name or scope_name not in {
        "inventory_scope",
        "manifest_scope",
    }:
        raise ValueError("TASK07_EVIDENCE_CONTRACT_INVALID")
    index_path = root / index_name
    if index_path.exists():
        raise ValueError("TASK07_EVIDENCE_ALREADY_EXISTS")

    asset_digest = sha256()
    counts = {item.value: 0 for item in AssetDisposition}
    shards: list[dict[str, Any]] = []
    rows: list[str] = []
    row_count = 0
    previous_id = 0

    def flush() -> None:
        nonlocal rows
        if not rows:
            return
        number = len(shards) + 1
        name = f"assets-{number:06d}.jsonl"
        path = root / name
        payload = "".join(rows).encode()
        if path.exists():
            raise ValueError("TASK07_EVIDENCE_ALREADY_EXISTS")
        path.write_bytes(payload)
        shards.append({"path": name, "row_count": len(rows), "sha256": sha256(payload).hexdigest()})
        rows = []

    for asset in assets:
        if asset.market_data_file_id <= previous_id:
            raise ValueError("TASK07_INVENTORY_ORDER_INVALID")
        previous_id = asset.market_data_file_id
        record = _asset_record(asset)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        asset_digest.update(line.encode())
        counts[record["disposition"]] += 1
        row_count += 1
        rows.append(line)
        if len(rows) == shard_size:
            flush()
    flush()
    reference_index: dict[str, Any] | None = None
    if reference_report is not None:
        records = reference_report.get("records")
        if not isinstance(records, list) or reference_report.get("truncated") is not False:
            raise ValueError("TASK07_REFERENCE_REPORT_INVALID")
        reference_path = root / "references.jsonl"
        if reference_path.exists():
            raise ValueError("TASK07_EVIDENCE_ALREADY_EXISTS")
        reference_payload = "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for item in records
        ).encode()
        reference_path.write_bytes(reference_payload)
        reference_index = {
            key: value
            for key, value in reference_report.items()
            if key != "records"
        }
        reference_index.update(
            {
                "path": reference_path.name,
                "file_sha256": sha256(reference_payload).hexdigest(),
            }
        )
    body = {
        "schema_version": 1,
        "command": evidence_command,
        "status": "complete",
        "readonly_business_data": True,
        "base_sha": base_sha,
        "database_revision": database_revision,
        "asset_count": row_count,
        "assets_digest": asset_digest.hexdigest(),
        "disposition_counts": counts,
        "shards": shards,
        "truncated": False,
        "calls_rqdata": False,
        "deletion_authorized": False,
        "reference_index": reference_index,
        scope_name: dict(inventory_scope or {}),
    }
    if supported_frequencies is not None:
        body["supported_frequencies"] = list(supported_frequencies)
    index = {**body, "inventory_digest": canonical_digest(body)}
    temporary = root / f".{index_name}.tmp"
    temporary.write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(index_path)
    return index


def write_kline_manifest_evidence(
    assets: Iterable[Task07Asset],
    *,
    evidence_root: Path,
    base_sha: str,
    database_revision: str,
    shard_size: int = 10_000,
    manifest_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically publish an exact K-line-only evidence bundle."""

    if shard_size < 1 or not _TASK_HEAD.fullmatch(base_sha):
        raise ValueError("TASK07_KLINE_MANIFEST_CONTRACT_INVALID")
    requested_root = evidence_root.absolute()
    if requested_root.exists() or requested_root.is_symlink():
        raise ValueError("TASK07_KLINE_MANIFEST_EVIDENCE_ROOT_INVALID")
    parent = requested_root.parent.resolve(strict=True)
    root = parent / requested_root.name
    scope = dict(manifest_scope or {})
    scope_paths: list[Path] = []
    for key in ("project_root", "data_root", "canonical_root"):
        value = scope.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("TASK07_KLINE_MANIFEST_SCOPE_INVALID")
        scope_paths.append(Path(value).resolve(strict=False))
    if (
        any(_paths_overlap(root, path) for path in scope_paths)
    ):
        raise ValueError("TASK07_KLINE_MANIFEST_EVIDENCE_ROOT_INVALID")
    staging = Path(
        tempfile.mkdtemp(prefix=f".{root.name}.tmp-", dir=parent)
    )
    published = False
    try:
        asset_digest = sha256()
        classification_counts: Counter[str] = Counter()
        shards: list[dict[str, Any]] = []
        rows: list[bytes] = []
        row_count = 0
        previous_id = 0

        def flush() -> None:
            nonlocal rows
            if not rows:
                return
            name = f"kline-assets-{len(shards) + 1:06d}.jsonl"
            payload = b"".join(rows)
            _write_fsync_file(staging / name, payload)
            shards.append(
                {
                    "path": name,
                    "row_count": len(rows),
                    "sha256": sha256(payload).hexdigest(),
                }
            )
            rows = []

        for asset in _validated_kline_assets(assets):
            if asset.market_data_file_id <= previous_id:
                raise ValueError("TASK07_KLINE_MANIFEST_ORDER_INVALID")
            previous_id = asset.market_data_file_id
            record = _asset_record(asset)
            line = (
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
            asset_digest.update(line)
            classification_counts[str(record["disposition"])] += 1
            row_count += 1
            rows.append(line)
            if len(rows) == shard_size:
                flush()
        flush()
        body = {
            "schema_version": 1,
            "command": "data.task07.kline-manifest",
            "status": "complete",
            "readonly_business_data": True,
            "base_sha": base_sha,
            "database_revision": database_revision,
            "supported_frequencies": sorted(_SUPPORTED_FREQUENCIES),
            "asset_count": row_count,
            "assets_digest": asset_digest.hexdigest(),
            "classification_counts": dict(sorted(classification_counts.items())),
            "shards": shards,
            "truncated": False,
            "calls_rqdata": False,
            "manifest_scope": scope,
        }
        manifest = {**body, "manifest_digest": canonical_digest(body)}
        _write_fsync_file(
            staging / "kline-manifest-index.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        )
        _fsync_directory(staging)
        staging.replace(root)
        published = True
        _fsync_directory(parent)
        return manifest
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)


def _write_fsync_file(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _migration_source_record(
    item: Mapping[str, Any],
    *,
    aggregate: bool,
) -> dict[str, Any]:
    registration_snapshot = {
        "id": int(item["market_data_file_id"]),
        "provider": item["provider"],
        "data_type": item["data_type"],
        "symbol": item["symbol"],
        "contract_or_series": item["contract_or_series"],
        "frequency": item["frequency"],
        "data_role": item["data_role"],
        "quality_status": item["quality_status"],
        "file_path": item["file_path"],
        "file_size_bytes": item.get("file_size_bytes"),
        "checksum": item.get("checksum"),
        "coverage_start": item["coverage_start"],
        "coverage_end": item["coverage_end"],
        "row_count": item.get("row_count"),
        "data_version": item.get("data_version"),
    }
    record = {
        "market_data_file_id": int(item["market_data_file_id"]),
        "contract_or_series": item["contract_or_series"],
        "file_path": item["file_path"],
        "physical_checksum": item["physical_checksum"],
        "disposition": item["disposition"],
        "coverage_start": item["coverage_start"],
        "coverage_end": item["coverage_end"],
        "row_count": item.get("row_count"),
        "data_version": item.get("data_version"),
        "dataset_origin": (
            "preaggregated_from_1m" if aggregate else "provider_direct"
        ),
        "registration_snapshot": registration_snapshot,
        "registration_snapshot_digest": canonical_digest(
            registration_snapshot
        ),
    }
    if not aggregate:
        return record
    return {
        **record,
        "source_frequency": "1m",
        "quality_evidence_digest": item.get("quality_evidence_digest"),
        "main_map_digest": item.get("main_map_digest"),
        "manifest_format": "canonical-manifest-v2",
        "manifest_version": "task07-aggregate-migration-v1",
        "registered_row_count": item.get("row_count"),
        "physical_row_count": item.get("physical_row_count"),
        "registered_min_datetime": item.get("coverage_start"),
        "registered_max_datetime": item.get("coverage_end"),
        "physical_min_datetime": item.get("physical_min_datetime"),
        "physical_max_datetime": item.get("physical_max_datetime"),
        "declared_periods": list(item.get("declared_periods", ())),
        "source_intervals": list(item.get("source_intervals", ())),
        "registration_wall_clock_matches": item.get(
            "registration_wall_clock_matches"
        ),
    }


def _verified_partition_record(item: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "canonical_partition_id",
        "canonical_file_uri",
        "manifest_format",
        "manifest_version",
        "manifest_uri",
        "manifest_digest",
    )
    if any(item.get(key) is None for key in required) or (
        item.get("frequency") in _DERIVED_FREQUENCIES
        and item.get("source_lineage") is None
    ):
        raise ValueError("TASK07_VERIFIED_PARTITION_EVIDENCE_INVALID")
    body = {
        "inventory_asset_id": int(item["market_data_file_id"]),
        "partition_id": int(item["canonical_partition_id"]),
        "provider": item["provider"],
        "dataset_kind": item["dataset_kind"],
        "symbol": item["symbol"],
        "contract_or_series": item["contract_or_series"],
        "frequency": item["frequency"],
        "adjustment": item.get("adjustment"),
        "schema_version": item.get("schema_version"),
        "file_path": item["file_path"],
        "file_uri": item["canonical_file_uri"],
        "physical_checksum": item["physical_checksum"],
        "coverage_start": item["coverage_start"],
        "coverage_end": item["coverage_end"],
        "row_count": item["row_count"],
        "manifest_format": item["manifest_format"],
        "manifest_version": item["manifest_version"],
        "manifest_uri": item["manifest_uri"],
        "manifest_digest": item["manifest_digest"],
        "source_lineage": item["source_lineage"],
    }
    return {**body, "record_digest": canonical_digest(body)}


def build_migration_plan(
    index: Mapping[str, Any],
    *,
    write_targets: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if index.get("status") != "complete" or index.get("truncated") is not False:
        raise ValueError("TASK07_INVENTORY_INCOMPLETE")
    eligible = {
        AssetDisposition.KEEP_CANONICAL_VERIFIED.value,
        AssetDisposition.REUSE_TRUSTED_SOURCE.value,
        AssetDisposition.REUSE_VERIFIED_AGGREGATE.value,
    }
    manifest_digest = str(
        index.get("manifest_digest")
        or index.get("inventory_digest")
        or index["assets_digest"]
    )
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    repair_actions: list[dict[str, Any]] = []
    eligible_record_count = 0
    for raw in _iter_inventory_assets(index):
        if raw.get("disposition") not in eligible:
            continue
        if (
            raw.get("disposition")
            == AssetDisposition.KEEP_CANONICAL_VERIFIED.value
            and raw.get("data_type") != "v2_canonical"
        ):
            continue
        if eligible_record_count >= _TASK07_PLAN_RECORD_LIMIT:
            raise ValueError("TASK07_PLAN_SOURCE_SHARDING_REQUIRED")
        eligible_record_count += 1
        key = (str(raw["symbol"]).lower(), str(raw["dataset_kind"]), str(raw["frequency"]))
        grouped.setdefault(key, []).append(dict(raw))
    provider_requests = []
    for raw in _iter_inventory_assets(index):
        if raw.get("disposition") == AssetDisposition.CONFLICT_BLOCKED.value:
            aggregate = raw.get("frequency") in _DERIVED_FREQUENCIES
            registration_snapshot = {
                "id": int(raw["market_data_file_id"]),
                "provider": raw["provider"],
                "data_type": raw["data_type"],
                "symbol": raw.get("registration_symbol") or raw["symbol"],
                "contract_or_series": raw.get(
                    "registration_contract_or_series"
                )
                or raw["contract_or_series"],
                "frequency": raw["frequency"],
                "data_role": raw["data_role"],
                "quality_status": raw["quality_status"],
                "file_path": raw["file_path"],
                "file_size_bytes": raw.get("file_size_bytes"),
                "checksum": raw.get("checksum"),
                "coverage_start": raw["coverage_start"],
                "coverage_end": raw["coverage_end"],
                "row_count": raw.get("row_count"),
                "data_version": raw.get("data_version"),
            }
            identity = {
                "provider": "rqdata",
                "dataset_kind": raw["dataset_kind"],
                "symbol": raw["symbol"],
                "contract_or_series": raw["contract_or_series"],
                "frequency": raw["frequency"],
                "adjustment": raw.get("adjustment") or "none",
                "schema_version": raw.get("schema_version") or "canonical-bar-v1",
            }
            action_body: dict[str, Any] = {
                "market_data_file_id": int(raw["market_data_file_id"]),
                "action": (
                    "canonical_1m_reaggregate" if aggregate else "rqdata_redownload"
                ),
                "original_provider": raw["provider"],
                **identity,
                "window": {
                    "start": raw["coverage_start"],
                    "end": raw["coverage_end"],
                },
                "source_evidence": {
                    "registration_snapshot": registration_snapshot,
                    "registration_snapshot_digest": canonical_digest(
                        registration_snapshot
                    ),
                    "observed_checksum": raw["physical_checksum"],
                    "physical_exists": raw["physical_exists"],
                    "source_scope": raw["source_scope"],
                },
                "base_sha": index["base_sha"],
                "manifest_digest": manifest_digest,
                "source_dataset": (
                    {**identity, "frequency": "1m"} if aggregate else None
                ),
                "validation_gates": [
                    "schema",
                    "bar_end_strictly_increasing",
                    "duplicate_identity",
                    "trading_session",
                    "partition_readability",
                ],
                "failure_policy": {
                    "preserve_existing_canonical": True,
                    "register_data_gap": True,
                    "delete_existing": False,
                },
                "authorized": False,
            }
            repair_actions.append(
                {**action_body, "action_digest": canonical_digest(action_body)}
            )
        if raw.get("frequency") in _DERIVED_FREQUENCIES:
            continue
        disposition = raw.get("disposition")
        if disposition == AssetDisposition.CONFLICT_BLOCKED.value or (
            disposition == AssetDisposition.REGISTER_DATA_GAP.value
            and raw.get("physical_exists") is False
        ):
            if len(provider_requests) >= _TASK07_PLAN_RECORD_LIMIT:
                raise ValueError("TASK07_PLAN_SOURCE_SHARDING_REQUIRED")
            provider_requests.append(
                {
                    "market_data_file_id": int(raw["market_data_file_id"]),
                    "provider": "rqdata",
                    "original_provider": raw["provider"],
                    "symbol": raw["symbol"],
                    "contract_or_series": raw["contract_or_series"],
                    "dataset_kind": raw["dataset_kind"],
                    "frequency": raw["frequency"],
                    "adjustment": raw.get("adjustment") or "none",
                    "schema_version": raw.get("schema_version")
                    or "canonical-bar-v1",
                    "window": {
                        "start": raw["coverage_start"],
                        "end": raw["coverage_end"],
                    },
                    "reason": disposition,
                    "registered_checksum": raw["checksum"],
                    "observed_checksum": raw["physical_checksum"],
                }
            )
    provider_requests.sort(
        key=lambda item: (
            str(item["symbol"]),
            str(item["dataset_kind"]),
            str(item["frequency"]),
            str(item["window"]["start"]),
            int(item["market_data_file_id"]),
        )
    )
    repair_actions.sort(
        key=lambda item: (
            str(item["symbol"]),
            str(item["dataset_kind"]),
            str(item["frequency"]),
            str(item["window"]["start"]),
            int(item["market_data_file_id"]),
        )
    )
    migration_batches = []
    for key in sorted(grouped):
        aggregate = key[2] in _DERIVED_FREQUENCIES
        rows = sorted(grouped[key], key=lambda item: (str(item.get("coverage_start")), int(item["market_data_file_id"])))
        migration_rows = [
            item
            for item in rows
            if item["disposition"]
            in {
                AssetDisposition.REUSE_TRUSTED_SOURCE.value,
                AssetDisposition.REUSE_VERIFIED_AGGREGATE.value,
            }
        ]
        verified_rows = [
            item
            for item in rows
            if item["disposition"] == AssetDisposition.KEEP_CANONICAL_VERIFIED.value
        ]
        body = {
            "batch_key": ":".join(key),
            "operation": "migrate_same_frequency",
            "symbol": key[0],
            "dataset_kind": key[1],
            "frequency": key[2],
            "dataset_origin": (
                "preaggregated_from_1m" if aggregate else "provider_direct"
            ),
            "required_database_revision": (
                "20260803_0032" if aggregate else index["database_revision"]
            ),
            "source_ids": [int(item["market_data_file_id"]) for item in migration_rows],
            "source_checksums": [item["physical_checksum"] for item in migration_rows],
            "sources": [
                _migration_source_record(item, aggregate=aggregate)
                for item in migration_rows
            ],
            "verified_partition_ids": [
                int(item["market_data_file_id"]) for item in verified_rows
            ],
            "verified_partitions": [
                _verified_partition_record(item) for item in verified_rows
            ],
            "coverage_start": min(str(item["coverage_start"]) for item in rows),
            "coverage_end": max(str(item["coverage_end"]) for item in rows),
        }
        migration_batches.append({**body, "batch_digest": canonical_digest(body)})
    repair_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for action in repair_actions:
        key = (
            str(action["action"]),
            str(action["symbol"]),
            str(action["dataset_kind"]),
            str(action["frequency"]),
        )
        repair_groups.setdefault(key, []).append(action)
    repair_batches: list[dict[str, Any]] = []
    for key in sorted(repair_groups):
        operation, symbol, dataset_kind, frequency = key
        actions = repair_groups[key]
        aggregate = frequency in _DERIVED_FREQUENCIES
        body = {
            "batch_key": ":".join(("repair", *key)),
            "operation": operation,
            "symbol": symbol,
            "dataset_kind": dataset_kind,
            "frequency": frequency,
            "dataset_origin": (
                "preaggregated_from_1m" if aggregate else "provider_direct"
            ),
            "required_database_revision": (
                "20260803_0032" if aggregate else index["database_revision"]
            ),
            "source_ids": [],
            "source_checksums": [],
            "sources": [],
            "verified_partition_ids": [],
            "verified_partitions": [],
            "repair_action_ids": [
                int(action["market_data_file_id"]) for action in actions
            ],
            "repair_action_digests": [
                str(action["action_digest"]) for action in actions
            ],
            "coverage_start": min(
                str(action["window"]["start"]) for action in actions
            ),
            "coverage_end": max(
                str(action["window"]["end"]) for action in actions
            ),
        }
        repair_batches.append({**body, "batch_digest": canonical_digest(body)})
    batches = sorted(
        [*migration_batches, *repair_batches],
        key=lambda item: str(item["batch_key"]),
    )
    migration_envelope = build_migration_envelope(batches)
    disposition_counts = dict(
        index.get("classification_counts")
        or index.get("disposition_counts", {})
    )
    blocked = int(disposition_counts.get(AssetDisposition.CONFLICT_BLOCKED.value, 0))
    gap_count = int(disposition_counts.get(AssetDisposition.REGISTER_DATA_GAP.value, 0))
    provider_request_proposal = {
        "schema_version": 1,
        "command": "data.task07.provider-request",
        "base_sha": index["base_sha"],
        "database_revision": index["database_revision"],
        "manifest_digest": manifest_digest,
        "request_count": len(provider_requests),
        "requests": provider_requests,
        "calls_rqdata": False,
        "provider_call_authorized": False,
        "writes_authorized": False,
    }
    provider_request_proposal["proposal_digest"] = canonical_digest(
        provider_request_proposal
    )
    write_targets_value = dict(write_targets or {})
    target_valid = _migration_write_targets_valid(write_targets_value)
    revision_ready = all(
        batch.get("required_database_revision") == index["database_revision"]
        for batch in batches
    )
    approval_eligible = (
        migration_envelope["batch_count"] > 0
        and target_valid
        and revision_ready
    )
    gate_status = (
        "exact_owner_approval_required"
        if approval_eligible
        else "BLOCKED_MIGRATION_BATCH_EMPTY"
        if migration_envelope["batch_count"] == 0
        else "BLOCKED_MIGRATION_WRITE_TARGET"
        if not target_valid
        else "BLOCKED_DATABASE_REVISION"
        if not revision_ready
        else "BLOCKED_AT_KLINE_DATA_GATE"
    )
    facts = {
        "base_sha": index["base_sha"],
        "database_revision": index["database_revision"],
        "manifest_digest": manifest_digest,
        "assets_digest": index["assets_digest"],
        "write_targets": write_targets_value,
        "provider_requests": provider_requests,
        "repair_actions": repair_actions,
        "repair_batch_count": len(repair_batches),
        "batches": batches,
        "migration_envelope": migration_envelope,
        "classification_counts": disposition_counts,
        "blocked_asset_count": blocked,
        "data_gap_count": gap_count,
        "migration_target_gate": (
            "exact_write_targets_bound"
            if target_valid
            else "BLOCKED_MIGRATION_WRITE_TARGET"
        ),
        "migration_revision_gate": (
            "required_database_revision_bound"
            if revision_ready
            else "BLOCKED_DATABASE_REVISION"
        ),
        "migration_approval_eligible": approval_eligible,
        "approval_eligible": approval_eligible,
        "migration_gate_status": gate_status,
        "gate_status": gate_status,
        "runtime_cutover_eligible": False,
        "migration_verification_gate": "pending_all_batch_verification",
        "calls_rqdata": False,
        "writes_authorized": False,
        "deletion_authorized": False,
    }
    return {
        "schema_version": 2,
        "command": "data.task07.plan",
        "status": "planned",
        **facts,
        "plan_digest": canonical_digest(facts),
        "provider_request_proposal": provider_request_proposal,
    }


def _load_inventory_evidence(index_path: Path) -> dict[str, Any]:
    index = _load_json(index_path, "TASK07_INVENTORY_INDEX_INVALID")
    stored_digest = index.get("inventory_digest")
    body = {key: value for key, value in index.items() if key != "inventory_digest"}
    if stored_digest != canonical_digest(body) or index.get("status") != "complete" or index.get("truncated") is not False:
        raise ValueError("TASK07_INVENTORY_INDEX_MISMATCH")
    asset_count = 0
    asset_digest = sha256()
    for shard in index.get("shards", []):
        name = shard.get("path")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("TASK07_INVENTORY_SHARD_PATH_INVALID")
        payload = (index_path.parent / name).read_bytes()
        if sha256(payload).hexdigest() != shard.get("sha256"):
            raise ValueError("TASK07_INVENTORY_SHARD_HASH_MISMATCH")
        lines = payload.splitlines(keepends=True)
        if len(lines) != shard.get("row_count"):
            raise ValueError("TASK07_INVENTORY_SHARD_COUNT_MISMATCH")
        for line in lines:
            asset_digest.update(line)
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("TASK07_INVENTORY_SHARD_JSON_INVALID") from exc
            if not isinstance(value, dict):
                raise ValueError("TASK07_INVENTORY_SHARD_JSON_INVALID")
            asset_count += 1
    if asset_count != index.get("asset_count") or asset_digest.hexdigest() != index.get("assets_digest"):
        raise ValueError("TASK07_INVENTORY_ASSETS_MISMATCH")
    reference_index = index.get("reference_index")
    if reference_index is not None:
        name = reference_index.get("path")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("TASK07_REFERENCE_PATH_INVALID")
        payload = (index_path.parent / name).read_bytes()
        if sha256(payload).hexdigest() != reference_index.get("file_sha256"):
            raise ValueError("TASK07_REFERENCE_HASH_MISMATCH")
        try:
            references = [json.loads(line) for line in payload.splitlines()]
        except json.JSONDecodeError as exc:
            raise ValueError("TASK07_REFERENCE_JSON_INVALID") from exc
        if (
            len(references) != reference_index.get("record_count")
            or canonical_digest(references) != reference_index.get("references_digest")
        ):
            raise ValueError("TASK07_REFERENCE_CONTENT_MISMATCH")
        index = {**index, "references": references}
    return {**index, "_inventory_index_path": str(index_path.resolve(strict=True))}


def load_kline_manifest_evidence(index_path: Path) -> dict[str, Any]:
    manifest = _load_json(index_path, "TASK07_KLINE_MANIFEST_INDEX_INVALID")
    stored_digest = manifest.get("manifest_digest")
    body = {
        key: value for key, value in manifest.items() if key != "manifest_digest"
    }
    if (
        stored_digest != canonical_digest(body)
        or manifest.get("command") != "data.task07.kline-manifest"
        or manifest.get("status") != "complete"
        or manifest.get("truncated") is not False
        or manifest.get("supported_frequencies") != sorted(_SUPPORTED_FREQUENCIES)
        or "inventory_digest" in manifest
        or "reference_index" in manifest
        or "deletion_authorized" in manifest
    ):
        raise ValueError("TASK07_KLINE_MANIFEST_SCOPE_INVALID")
    loaded = {
        **manifest,
        "_manifest_index_path": str(index_path.resolve(strict=True)),
    }
    for asset in _iter_inventory_assets(loaded):
        if (
            asset.get("frequency") not in _SUPPORTED_FREQUENCIES
            or asset.get("data_type") not in _KLINE_DATA_TYPES
            or asset.get("disposition")
            in {
                AssetDisposition.PROTECTED_EVIDENCE_SOURCE.value,
                AssetDisposition.RETIREMENT_CANDIDATE.value,
                AssetDisposition.EXCLUDE_DERIVED.value,
            }
        ):
            raise ValueError("TASK07_KLINE_MANIFEST_SCOPE_INVALID")
    return loaded


def _iter_inventory_assets(index: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    inline = index.get("assets")
    if inline is not None:
        if not isinstance(inline, list):
            raise ValueError("TASK07_INVENTORY_ASSETS_MISMATCH")
        for item in inline:
            if not isinstance(item, dict):
                raise ValueError("TASK07_INVENTORY_SHARD_JSON_INVALID")
            yield item
        return
    index_path_value = index.get("_manifest_index_path") or index.get(
        "_inventory_index_path"
    )
    if not isinstance(index_path_value, str):
        raise ValueError("TASK07_INVENTORY_ASSETS_MISSING")
    index_path = Path(index_path_value)
    asset_count = 0
    assets_digest = sha256()
    for shard in index.get("shards", []):
        name = shard.get("path")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("TASK07_INVENTORY_SHARD_PATH_INVALID")
        shard_count = 0
        shard_digest = sha256()
        with (index_path.parent / name).open("rb") as handle:
            for line in handle:
                shard_digest.update(line)
                assets_digest.update(line)
                shard_count += 1
                asset_count += 1
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "TASK07_INVENTORY_SHARD_JSON_INVALID"
                    ) from exc
                if not isinstance(item, dict):
                    raise ValueError("TASK07_INVENTORY_SHARD_JSON_INVALID")
                yield item
        if shard_digest.hexdigest() != shard.get("sha256"):
            raise ValueError("TASK07_INVENTORY_SHARD_HASH_MISMATCH")
        if shard_count != shard.get("row_count"):
            raise ValueError("TASK07_INVENTORY_SHARD_COUNT_MISMATCH")
    if (
        asset_count != index.get("asset_count")
        or assets_digest.hexdigest() != index.get("assets_digest")
    ):
        raise ValueError("TASK07_INVENTORY_ASSETS_MISMATCH")


def build_approval_packet(
    plan: Mapping[str, Any],
    *,
    command: str,
) -> dict[str, Any]:
    if command != "data.task07.apply":
        raise ValueError("TASK07_APPROVAL_COMMAND_INVALID")
    _validate_migration_plan_integrity(plan)
    if plan.get("approval_eligible") is not True:
        raise ValueError("TASK07_KLINE_GATE_BLOCKED")
    facts = build_migration_approval_facts(
        plan,
        current_base_sha=str(plan["base_sha"]),
        current_database_revision=str(plan["database_revision"]),
        current_write_targets=plan.get("write_targets", {}),
    )
    return {
        "schema_version": 1,
        "command": command,
        "writes_authorized": True,
        "deletion_authorized": False,
        "bound_facts": facts,
    }


def build_migration_approval_facts(
    plan: Mapping[str, Any],
    *,
    current_base_sha: str,
    current_database_revision: str,
    current_write_targets: Mapping[str, Any],
) -> dict[str, Any]:
    if not _migration_write_targets_valid(current_write_targets):
        raise ValueError("TASK07_WRITE_TARGETS_REQUIRED")
    return {
        "base_sha": current_base_sha,
        "database_revision": current_database_revision,
        "plan_digest": plan.get("plan_digest"),
        "manifest_digest": plan.get("manifest_digest"),
        "migration_envelope": plan.get("migration_envelope"),
        "write_targets": dict(current_write_targets),
    }


def build_migration_batch_facts(
    plan: Mapping[str, Any],
    batch: Mapping[str, Any],
    *,
    migration_approval_hash: str,
    current_base_sha: str,
    current_database_revision: str,
    current_write_targets: Mapping[str, Any],
) -> dict[str, Any]:
    if not _SHA256.fullmatch(migration_approval_hash):
        raise ValueError("TASK07_APPROVAL_HASH_INVALID")
    return {
        **build_migration_approval_facts(
            plan,
            current_base_sha=current_base_sha,
            current_database_revision=current_database_revision,
            current_write_targets=current_write_targets,
        ),
        "migration_approval_hash": migration_approval_hash,
        "batch_key": batch["batch_key"],
        "batch_digest": batch["batch_digest"],
    }


def build_preflight_receipt(
    plan: Mapping[str, Any],
    *,
    packet_path: Path,
    approval_hash: str,
    current_base_sha: str,
    current_database_revision: str,
    batch_key: str,
    current_write_targets: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_migration_plan_integrity(plan)
    batch = _task07_batch(plan, batch_key)
    approval_facts = build_migration_approval_facts(
        plan,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_write_targets=current_write_targets,
    )
    verify_exact_approval(
        packet_path,
        approval_hash=approval_hash,
        expected_command="data.task07.apply",
        current_facts=approval_facts,
    )
    facts = build_migration_batch_facts(
        plan,
        batch,
        migration_approval_hash=approval_hash,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_write_targets=current_write_targets,
    )
    sources = list(batch.get("sources", []))
    for source in sources:
        exists, checksum = _physical_identity(Path(str(source["file_path"])))
        if not exists or checksum != source.get("physical_checksum"):
            raise ValueError("TASK07_SOURCE_DRIFT")
    body = {
        "schema_version": 1,
        "command": "data.task07.preflight",
        "status": "passed",
        "readonly": True,
        "bound_facts": facts,
        "source_count": len(sources),
        "migration_envelope_digest": plan["migration_envelope"][
            "envelope_digest"
        ],
        "migration_approval_hash": approval_hash,
        "batch_key": batch["batch_key"],
        "batch_digest": batch["batch_digest"],
        "calls_rqdata": False,
        "writes_postgresql": False,
        "writes_canonical": False,
    }
    return {**body, "preflight_digest": canonical_digest(body)}


def verify_task07_preflight_receipt(
    path: Path,
    *,
    receipt_hash: str,
    plan: Mapping[str, Any],
    batch_key: str,
    current_base_sha: str,
    current_database_revision: str,
    current_write_targets: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_migration_plan_integrity(plan)
    if not _SHA256.fullmatch(receipt_hash):
        raise ValueError("TASK07_PREFLIGHT_HASH_INVALID")
    receipt = _load_json(path, "TASK07_PREFLIGHT_RECEIPT_INVALID")
    if canonical_digest(receipt) != receipt_hash:
        raise ValueError("TASK07_PREFLIGHT_HASH_MISMATCH")
    stored_digest = receipt.get("preflight_digest")
    body = {key: value for key, value in receipt.items() if key != "preflight_digest"}
    batch = _task07_batch(plan, batch_key)
    migration_approval_hash = receipt.get("migration_approval_hash")
    if not isinstance(migration_approval_hash, str):
        raise ValueError("TASK07_PREFLIGHT_RECEIPT_DRIFT")
    expected_facts = build_migration_batch_facts(
        plan,
        batch,
        migration_approval_hash=migration_approval_hash,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_write_targets=current_write_targets,
    )
    if (
        stored_digest != canonical_digest(body)
        or receipt.get("command") != "data.task07.preflight"
        or receipt.get("status") != "passed"
        or receipt.get("readonly") is not True
        or receipt.get("bound_facts") != expected_facts
        or receipt.get("source_count") != len(batch.get("sources", []))
        or receipt.get("migration_envelope_digest")
        != plan["migration_envelope"]["envelope_digest"]
        or receipt.get("batch_key") != batch["batch_key"]
        or receipt.get("batch_digest") != batch["batch_digest"]
        or receipt.get("calls_rqdata") is not False
        or receipt.get("writes_postgresql") is not False
        or receipt.get("writes_canonical") is not False
    ):
        raise ValueError("TASK07_PREFLIGHT_RECEIPT_DRIFT")
    return receipt


def _task07_batch(plan: Mapping[str, Any], batch_key: str | None) -> Mapping[str, Any]:
    if not isinstance(batch_key, str) or not batch_key:
        raise ValueError("TASK07_BATCH_KEY_REQUIRED")
    matches = [
        item
        for item in plan.get("batches", [])
        if isinstance(item, Mapping) and item.get("batch_key") == batch_key
    ]
    if len(matches) != 1:
        raise ValueError("TASK07_BATCH_KEY_INVALID")
    return matches[0]


def _validate_migration_plan_integrity(plan: Mapping[str, Any]) -> None:
    if (
        plan.get("schema_version") != 2
        or plan.get("command") != "data.task07.plan"
        or plan.get("status") != "planned"
    ):
        raise ValueError("TASK07_PLAN_SCHEMA_INVALID")
    batches = plan.get("batches")
    if not isinstance(batches, list):
        raise ValueError("TASK07_PLAN_INVALID")
    repair_batches: list[Mapping[str, Any]] = []
    for batch in batches:
        if not isinstance(batch, Mapping):
            raise ValueError("TASK07_PLAN_INVALID")
        body = {key: value for key, value in batch.items() if key != "batch_digest"}
        if batch.get("batch_digest") != canonical_digest(body):
            raise ValueError("TASK07_BATCH_DIGEST_MISMATCH")
        aggregate = batch.get("frequency") in _DERIVED_FREQUENCIES
        expected_origin = (
            "preaggregated_from_1m" if aggregate else "provider_direct"
        )
        expected_revision = (
            "20260803_0032" if aggregate else plan.get("database_revision")
        )
        operation = batch.get("operation")
        if (
            batch.get("dataset_origin") != expected_origin
            or batch.get("required_database_revision") != expected_revision
        ):
            raise ValueError("TASK07_BATCH_ORIGIN_INVALID")
        if operation != "migrate_same_frequency":
            expected_operation = (
                "canonical_1m_reaggregate" if aggregate else "rqdata_redownload"
            )
            action_ids = batch.get("repair_action_ids")
            action_digests = batch.get("repair_action_digests")
            if (
                operation != expected_operation
                or batch.get("batch_key")
                != ":".join(
                    (
                        "repair",
                        expected_operation,
                        str(batch.get("symbol")),
                        str(batch.get("dataset_kind")),
                        str(batch.get("frequency")),
                    )
                )
                or batch.get("dataset_kind")
                not in {"continuous", "actual_dominant"}
                or not isinstance(batch.get("symbol"), str)
                or not batch.get("symbol")
                or not isinstance(action_ids, list)
                or not isinstance(action_digests, list)
                or not action_ids
                or len(action_ids) != len(action_digests)
                or batch.get("sources") != []
                or batch.get("source_ids") != []
                or batch.get("source_checksums") != []
                or batch.get("verified_partitions") != []
                or batch.get("verified_partition_ids") != []
            ):
                raise ValueError("TASK07_REPAIR_BATCH_INVALID")
            repair_batches.append(batch)
            continue
        for source in batch.get("sources", []):
            if not isinstance(source, Mapping) or source.get(
                "dataset_origin"
            ) != expected_origin:
                raise ValueError("TASK07_BATCH_ORIGIN_INVALID")
            registration = source.get("registration_snapshot")
            if (
                not isinstance(registration, Mapping)
                or source.get("registration_snapshot_digest")
                != canonical_digest(registration)
            ):
                raise ValueError("TASK07_SOURCE_REGISTRATION_INVALID")
            if aggregate and (
                source.get("source_frequency") != "1m"
                or source.get("manifest_format")
                != CANONICAL_MANIFEST_FORMAT_V2
                or source.get("manifest_version")
                != _TASK07_AGGREGATE_MANIFEST_VERSION
                or not _SHA256.fullmatch(
                    str(source.get("quality_evidence_digest") or "")
                )
                or source.get("registration_wall_clock_matches") is not True
            ):
                raise ValueError("TASK07_BATCH_ORIGIN_INVALID")
        verified_partitions = batch.get("verified_partitions", [])
        if not isinstance(verified_partitions, list):
            raise ValueError("TASK07_VERIFIED_PARTITION_EVIDENCE_INVALID")
        verified_ids: list[int] = []
        for partition in verified_partitions:
            if not isinstance(partition, Mapping):
                raise ValueError("TASK07_VERIFIED_PARTITION_EVIDENCE_INVALID")
            record_body = {
                key: value
                for key, value in partition.items()
                if key != "record_digest"
            }
            try:
                partition_id = int(partition["partition_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "TASK07_VERIFIED_PARTITION_EVIDENCE_INVALID"
                ) from exc
            if (
                partition_id < 1
                or partition.get("record_digest") != canonical_digest(record_body)
                or partition.get("provider") != "rqdata"
                or partition.get("dataset_kind") != batch.get("dataset_kind")
                or partition.get("symbol") != batch.get("symbol")
                or partition.get("frequency") != batch.get("frequency")
                or (
                    aggregate
                    and (
                        partition.get("manifest_format")
                        != CANONICAL_MANIFEST_FORMAT_V2
                        or partition.get("manifest_version")
                        != _TASK07_AGGREGATE_MANIFEST_VERSION
                        or not isinstance(
                            partition.get("source_lineage"), Mapping
                        )
                    )
                )
            ):
                raise ValueError("TASK07_VERIFIED_PARTITION_EVIDENCE_INVALID")
            verified_ids.append(
                int(partition.get("inventory_asset_id", -1))
            )
        if verified_ids != list(batch.get("verified_partition_ids", [])) or (
            not batch.get("sources") and not verified_partitions
        ):
            raise ValueError("TASK07_VERIFIED_PARTITION_EVIDENCE_INVALID")
    batch_manifest = [
        {"batch_key": batch["batch_key"], "batch_digest": batch["batch_digest"]}
        for batch in batches
    ]
    if batch_manifest != sorted(
        batch_manifest,
        key=lambda item: item["batch_key"],
    ):
        raise ValueError("TASK07_BATCH_ORDER_INVALID")
    expected_envelope = build_migration_envelope(batches)
    if plan.get("migration_envelope") != expected_envelope:
        raise ValueError("TASK07_MIGRATION_ENVELOPE_MISMATCH")
    requests = plan.get("provider_requests")
    repair_actions = plan.get("repair_actions")
    proposal = plan.get("provider_request_proposal")
    if (
        not isinstance(requests, list)
        or not isinstance(repair_actions, list)
        or not isinstance(proposal, Mapping)
    ):
        raise ValueError("TASK07_PLAN_INVALID")
    for action in repair_actions:
        if not isinstance(action, Mapping):
            raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
        action_body = {
            key: value for key, value in action.items() if key != "action_digest"
        }
        frequency = action.get("frequency")
        aggregate = frequency in _DERIVED_FREQUENCIES
        expected_action = (
            "canonical_1m_reaggregate" if aggregate else "rqdata_redownload"
        )
        source_dataset = action.get("source_dataset")
        expected_source_dataset = (
            {
                "provider": action.get("provider"),
                "dataset_kind": action.get("dataset_kind"),
                "symbol": action.get("symbol"),
                "contract_or_series": action.get("contract_or_series"),
                "frequency": "1m",
                "adjustment": action.get("adjustment"),
                "schema_version": action.get("schema_version"),
            }
            if aggregate
            else None
        )
        source_evidence = action.get("source_evidence")
        if (
            frequency not in _SUPPORTED_FREQUENCIES
            or action.get("action") != expected_action
            or action.get("provider") != "rqdata"
            or not isinstance(action.get("original_provider"), str)
            or not action.get("original_provider")
            or action.get("base_sha") != plan.get("base_sha")
            or action.get("manifest_digest") != plan.get("manifest_digest")
            or action.get("authorized") is not False
            or action.get("action_digest") != canonical_digest(action_body)
            or source_dataset != expected_source_dataset
            or not isinstance(source_evidence, Mapping)
            or set(source_evidence)
            != {
                "registration_snapshot",
                "registration_snapshot_digest",
                "observed_checksum",
                "physical_exists",
                "source_scope",
            }
            or not isinstance(source_evidence.get("registration_snapshot"), Mapping)
            or source_evidence.get("registration_snapshot_digest")
            != canonical_digest(source_evidence.get("registration_snapshot"))
            or not isinstance(
                source_evidence.get("registration_snapshot", {}).get("file_path"),
                str,
            )
            or not Path(
                str(
                    source_evidence.get("registration_snapshot", {}).get(
                        "file_path"
                    )
                )
            ).is_absolute()
            or type(source_evidence.get("physical_exists")) is not bool
        ):
            raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
    action_by_id = {
        int(action["market_data_file_id"]): action for action in repair_actions
    }
    if len(action_by_id) != len(repair_actions):
        raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
    bound_repair_actions = [
        (identifier, digest)
        for batch in repair_batches
        for identifier, digest in zip(
            batch["repair_action_ids"],
            batch["repair_action_digests"],
            strict=True,
        )
    ]
    if (
        len(bound_repair_actions) != len(repair_actions)
        or len({int(identifier) for identifier, _digest in bound_repair_actions})
        != len(bound_repair_actions)
        or {
            (int(identifier), str(digest))
            for identifier, digest in bound_repair_actions
        }
        != {
            (identifier, str(action["action_digest"]))
            for identifier, action in action_by_id.items()
        }
        or plan.get("repair_batch_count") != len(repair_batches)
    ):
        raise ValueError("TASK07_REPAIR_BATCH_INVALID")
    request_ids: set[int] = set()
    request_action_identity_fields = (
        "provider",
        "original_provider",
        "symbol",
        "contract_or_series",
        "dataset_kind",
        "frequency",
        "adjustment",
        "schema_version",
        "window",
    )
    for request in requests:
        if not isinstance(request, Mapping):
            raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
        identifier = request.get("market_data_file_id")
        if type(identifier) is not int or identifier in request_ids:
            raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
        request_ids.add(identifier)
        action = action_by_id.get(identifier)
        if (
            request.get("provider") != "rqdata"
            or not isinstance(request.get("original_provider"), str)
            or not request.get("original_provider")
            or request.get("frequency") not in _DIRECT_FREQUENCIES
            or request.get("reason")
            not in {
                AssetDisposition.CONFLICT_BLOCKED.value,
                AssetDisposition.REGISTER_DATA_GAP.value,
            }
            or (
                request.get("reason") == AssetDisposition.CONFLICT_BLOCKED.value
                and (
                    not isinstance(action, Mapping)
                    or action.get("action") != "rqdata_redownload"
                    or any(
                        action.get(field) != request.get(field)
                        for field in request_action_identity_fields
                    )
                )
            )
        ):
            raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
    redownload_action_ids = {
        identifier
        for identifier, action in action_by_id.items()
        if action.get("action") == "rqdata_redownload"
    }
    conflict_request_ids = {
        int(request["market_data_file_id"])
        for request in requests
        if request.get("reason") == AssetDisposition.CONFLICT_BLOCKED.value
    }
    if redownload_action_ids != conflict_request_ids:
        raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
    proposal_body = {
        key: value for key, value in proposal.items() if key != "proposal_digest"
    }
    if (
        proposal.get("proposal_digest") != canonical_digest(proposal_body)
        or proposal.get("requests") != requests
        or proposal.get("schema_version") != 1
        or proposal.get("command") != "data.task07.provider-request"
        or proposal.get("base_sha") != plan.get("base_sha")
        or proposal.get("database_revision") != plan.get("database_revision")
        or proposal.get("request_count") != len(requests)
        or proposal.get("provider_call_authorized") is not False
        or proposal.get("writes_authorized") is not False
        or proposal.get("calls_rqdata") is not False
        or proposal.get("manifest_digest") != plan.get("manifest_digest")
    ):
        raise ValueError("TASK07_PROVIDER_PROPOSAL_DIGEST_MISMATCH")
    disposition_counts = plan.get("classification_counts")
    if not isinstance(disposition_counts, Mapping):
        raise ValueError("TASK07_PLAN_INVALID")
    expected_controls = {
        "blocked_asset_count": int(
            disposition_counts.get(AssetDisposition.CONFLICT_BLOCKED.value, 0)
        ),
        "data_gap_count": int(
            disposition_counts.get(AssetDisposition.REGISTER_DATA_GAP.value, 0)
        ),
    }
    if any(plan.get(key) != value for key, value in expected_controls.items()):
        raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
    if len(repair_actions) != expected_controls["blocked_asset_count"]:
        raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
    target_valid = _migration_write_targets_valid(plan.get("write_targets"))
    revision_ready = all(
        batch.get("required_database_revision") == plan.get("database_revision")
        for batch in batches
    )
    expected_eligible = (
        expected_envelope["batch_count"] > 0
        and target_valid
        and revision_ready
    )
    expected_gate = (
        "exact_owner_approval_required"
        if expected_eligible
        else "BLOCKED_MIGRATION_BATCH_EMPTY"
        if expected_envelope["batch_count"] == 0
        else "BLOCKED_MIGRATION_WRITE_TARGET"
        if not target_valid
        else "BLOCKED_DATABASE_REVISION"
        if not revision_ready
        else "BLOCKED_AT_KLINE_DATA_GATE"
    )
    if (
        plan.get("migration_target_gate")
        != (
            "exact_write_targets_bound"
            if target_valid
            else "BLOCKED_MIGRATION_WRITE_TARGET"
        )
        or plan.get("migration_approval_eligible") is not expected_eligible
        or plan.get("migration_revision_gate")
        != (
            "required_database_revision_bound"
            if revision_ready
            else "BLOCKED_DATABASE_REVISION"
        )
        or plan.get("approval_eligible") is not expected_eligible
        or plan.get("migration_gate_status") != expected_gate
        or plan.get("gate_status") != expected_gate
        or plan.get("runtime_cutover_eligible") is not False
        or plan.get("migration_verification_gate")
        != "pending_all_batch_verification"
        or plan.get("calls_rqdata") is not False
        or plan.get("writes_authorized") is not False
        or plan.get("deletion_authorized") is not False
    ):
        raise ValueError("TASK07_PLAN_CONTROL_DRIFT")
    facts = {
        "base_sha": plan.get("base_sha"),
        "database_revision": plan.get("database_revision"),
        "manifest_digest": plan.get("manifest_digest"),
        "assets_digest": plan.get("assets_digest"),
        "write_targets": plan.get("write_targets"),
        "provider_requests": requests,
        "repair_actions": repair_actions,
        "repair_batch_count": len(repair_batches),
        "batches": batches,
        "migration_envelope": expected_envelope,
        "classification_counts": dict(disposition_counts),
        **expected_controls,
        "migration_target_gate": (
            "exact_write_targets_bound"
            if target_valid
            else "BLOCKED_MIGRATION_WRITE_TARGET"
        ),
        "migration_revision_gate": (
            "required_database_revision_bound"
            if revision_ready
            else "BLOCKED_DATABASE_REVISION"
        ),
        "migration_approval_eligible": expected_eligible,
        "approval_eligible": expected_eligible,
        "migration_gate_status": expected_gate,
        "gate_status": expected_gate,
        "runtime_cutover_eligible": False,
        "migration_verification_gate": "pending_all_batch_verification",
        "calls_rqdata": False,
        "writes_authorized": False,
        "deletion_authorized": False,
    }
    if plan.get("plan_digest") != canonical_digest(facts):
        raise ValueError("TASK07_PLAN_DIGEST_MISMATCH")


def build_write_targets(
    *,
    staging_root: Path,
    canonical_root: Path,
    postgresql_target: Mapping[str, Any],
    inventory_scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind exact, non-secret write destinations and reject protected overlap."""

    staging = staging_root.resolve(strict=False)
    canonical = canonical_root.resolve(strict=False)
    approved_canonical = inventory_scope.get("canonical_root")
    if not isinstance(approved_canonical, str) or canonical != Path(approved_canonical).resolve(strict=False):
        raise ValueError("TASK07_CANONICAL_ROOT_SCOPE_DRIFT")
    protected_values = inventory_scope.get("protected_roots", [])
    if not isinstance(protected_values, list):
        raise ValueError("TASK07_PROTECTED_ROOT_SCOPE_INVALID")
    protected = sorted({str(Path(value).resolve(strict=False)) for value in protected_values})
    if staging == canonical or _paths_overlap(staging, canonical):
        raise ValueError("TASK07_WRITE_ROOTS_OVERLAP")
    for value in protected:
        protected_path = Path(value)
        if _paths_overlap(staging, protected_path) or _paths_overlap(canonical, protected_path):
            raise ValueError("TASK07_PROTECTED_WRITE_TARGET")
    database = dict(postgresql_target)
    required = {"drivername", "username", "host", "port", "database"}
    if set(database) != required:
        raise ValueError("TASK07_POSTGRESQL_TARGET_INVALID")
    return {
        "staging_root": str(staging),
        "canonical_root": str(canonical),
        "postgresql_target": database,
        "protected_roots": protected,
    }


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def resolve_git_tag(project_root: Path, tag: str) -> str:
    if (
        not isinstance(tag, str)
        or not tag
        or tag.startswith("-")
        or ".." in tag
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", tag)
    ):
        raise ValueError("TASK07_RUNTIME_CUTOVER_TAG_INVALID")
    root = project_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("TASK07_RUNTIME_CUTOVER_PROJECT_ROOT_INVALID")
    check = subprocess.run(
        ["git", "check-ref-format", f"refs/tags/{tag}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        raise ValueError("TASK07_RUNTIME_CUTOVER_TAG_INVALID")
    resolved = subprocess.run(
        ["git", "rev-list", "-n", "1", f"refs/tags/{tag}^{{}}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    sha = resolved.stdout.strip()
    if resolved.returncode != 0 or not _TASK_HEAD.fullmatch(sha):
        raise ValueError("TASK07_RUNTIME_CUTOVER_TAG_UNRESOLVED")
    return sha


def build_runtime_cutover_plan(
    *,
    target_release_tag: str,
    previous_release_tag: str,
    tag_resolver: Callable[[str], str],
) -> dict[str, Any]:
    target_sha = tag_resolver(target_release_tag)
    previous_sha = tag_resolver(previous_release_tag)
    if (
        not _TASK_HEAD.fullmatch(str(target_sha))
        or not _TASK_HEAD.fullmatch(str(previous_sha))
        or target_release_tag == previous_release_tag
        or target_sha == previous_sha
    ):
        raise ValueError("TASK07_RUNTIME_CUTOVER_TAG_DRIFT")
    facts = {
        "target_release": {"tag": target_release_tag, "sha": target_sha},
        "previous_release": {"tag": previous_release_tag, "sha": previous_sha},
        "required_database_revision": _TASK07_RUNTIME_DATABASE_REVISION,
        "required_feature_flags": {
            name: False for name in _TASK07_DISABLED_FEATURE_FLAGS
        },
        "required_auto_order": False,
        "required_health_status": "passed",
        "required_smoke_status": "passed",
        "required_post_cutover_reference_assertion": {
            "scope": "checkout_and_runtime",
            "complete": True,
            "active": 0,
            "review_required": 0,
        },
        "calls_rqdata": False,
        "writes_canonical": False,
        "writes_database": False,
        "switches_runtime": False,
        "apply_available": False,
    }
    return {
        "schema_version": 1,
        "command": "data.task07.runtime-cutover-plan",
        "status": "planned",
        "readonly": True,
        **facts,
        "plan_digest": canonical_digest(facts),
    }


def verify_runtime_cutover_receipt(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    tag_resolver: Callable[[str], str],
) -> dict[str, Any]:
    try:
        target = plan["target_release"]
        previous = plan["previous_release"]
        expected_plan = build_runtime_cutover_plan(
            target_release_tag=str(target["tag"]),
            previous_release_tag=str(previous["tag"]),
            tag_resolver=tag_resolver,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("TASK07_RUNTIME_CUTOVER_PLAN_DRIFT") from exc
    if dict(plan) != expected_plan:
        raise ValueError("TASK07_RUNTIME_CUTOVER_PLAN_DRIFT")
    expected_fields = {
        "schema_version",
        "command",
        "status",
        "target_release",
        "database_revision",
        "feature_flags",
        "auto_order",
        "health",
        "smoke",
        "rollback",
        "post_cutover_reference_assertion",
        "plan_digest",
        "canonical_receipt_digest",
    }
    if set(receipt) != expected_fields:
        raise ValueError("TASK07_RUNTIME_CUTOVER_RECEIPT_DRIFT")
    body = {
        key: value
        for key, value in receipt.items()
        if key != "canonical_receipt_digest"
    }
    rollback = receipt.get("rollback")
    if (
        receipt.get("canonical_receipt_digest") != canonical_digest(body)
        or receipt.get("schema_version") != 1
        or receipt.get("command") != "data.task07.runtime-cutover"
        or receipt.get("status") != "passed"
        or receipt.get("target_release") != expected_plan["target_release"]
        or receipt.get("database_revision")
        != expected_plan["required_database_revision"]
        or receipt.get("feature_flags")
        != expected_plan["required_feature_flags"]
        or receipt.get("auto_order") is not False
        or receipt.get("health") != {"status": "passed"}
        or receipt.get("smoke") != {"status": "passed"}
        or not isinstance(rollback, Mapping)
        or dict(rollback)
        != {
            **expected_plan["previous_release"],
            "ready": True,
        }
        or receipt.get("post_cutover_reference_assertion")
        != expected_plan["required_post_cutover_reference_assertion"]
        or receipt.get("plan_digest") != expected_plan["plan_digest"]
    ):
        raise ValueError("TASK07_RUNTIME_CUTOVER_RECEIPT_DRIFT")
    verification = {
        "schema_version": 1,
        "command": "data.task07.runtime-cutover-verify",
        "status": "passed",
        "readonly": True,
        "plan_digest": expected_plan["plan_digest"],
        "runtime_cutover_receipt_digest": receipt[
            "canonical_receipt_digest"
        ],
        "retirement_unlocked": False,
        "deletion_unlocked": False,
    }
    return {**verification, "verification_digest": canonical_digest(verification)}


_TASK07_RUNTIME_CUTOVER_RECEIPT_CONTRACT = {
    "schema_version": 1,
    "command": "data.task07.runtime-cutover",
    "required_fields": [
        "schema_version",
        "command",
        "status",
        "target_release",
        "database_revision",
        "feature_flags",
        "auto_order",
        "health",
        "smoke",
        "rollback",
        "reference_scan",
        "plan_digest",
        "canonical_receipt_digest",
    ],
    "database_revision": _TASK07_RUNTIME_DATABASE_REVISION,
    "all_features_disabled": True,
    "apply_available": False,
}


def _build_retirement_plan(
    *,
    base_sha: str,
    database_revision: str,
    reference_report: Mapping[str, Any],
    relations: Iterable[Mapping[str, Any]],
    retirement_at: str | datetime | None = None,
) -> dict[str, Any]:
    if not _TASK_HEAD.fullmatch(base_sha):
        raise ValueError("TASK07_BASE_SHA_INVALID")
    reference_snapshot = _reference_snapshot(
        reference_report,
        require_complete_scope=False,
    )
    state_counts = reference_snapshot["state_counts"]
    reference_eligible = (
        reference_snapshot["scope_complete"] is True
        and state_counts["active"] == 0
        and state_counts["review_required"] == 0
    )
    reference_gate = (
        "BLOCKED_REFERENCE_EVIDENCE_INCOMPLETE"
        if reference_snapshot["scope_complete"] is not True
        else "zero_active_references"
        if reference_eligible
        else "BLOCKED_ACTIVE_REFERENCE"
    )
    runtime_cutover_gate = "BLOCKED_TASK07_RUNTIME_CUTOVER_REQUIRED"
    runtime_cutover_validated = False
    retirement_eligible = (
        reference_eligible
        and runtime_cutover_validated
    )
    retirement_timestamp = _retirement_timestamp(retirement_at)
    before = sorted((dict(item) for item in relations), key=lambda item: (str(item["table"]), int(item["id"])))
    updates: list[dict[str, Any]] = []
    historical = 0
    for item in before:
        table = item["table"]
        if table == "profile_active_bindings" and item.get("binding_status") == "active":
            updates.append(
                {
                    **item,
                    "set": {
                        "binding_status": "superseded",
                        "superseded_at": retirement_timestamp,
                    },
                }
            )
        elif table in {"signal_scan_tasks", "data_download_tasks"} and item.get("status") in {"pending", "running", "retrying"}:
            updates.append({**item, "set": {"status": "cancelled"}})
        elif table == "strategy_signals" and item.get("is_active") is True:
            updates.append({**item, "set": {"is_active": False}})
        else:
            historical += 1
    facts = {
        "base_sha": base_sha,
        "database_revision": database_revision,
        "reference_snapshot": reference_snapshot,
        "reference_gate": reference_gate,
        "runtime_cutover_receipt_contract": dict(
            _TASK07_RUNTIME_CUTOVER_RECEIPT_CONTRACT
        ),
        "runtime_cutover_receipt_digest": None,
        "runtime_cutover_validated": runtime_cutover_validated,
        "runtime_cutover_gate": runtime_cutover_gate,
        "retirement_eligible": retirement_eligible,
        "retirement_at": retirement_timestamp,
        "before_image": before,
        "before_image_digest": canonical_digest(before),
        "updates": updates,
    }
    return {
        "schema_version": 2,
        "command": "data.task07.retirement-plan",
        "status": "planned",
        **facts,
        "plan_digest": canonical_digest(facts),
        "historical_non_active_count": historical,
        "gate_status": (
            reference_gate
            if not reference_eligible
            else runtime_cutover_gate
        ),
        "deletes": [],
        "writes_authorized": False,
        "deletion_authorized": False,
    }


def _collect_retirement_relations(
    session: Session,
    *,
    readonly: bool = True,
) -> list[dict[str, Any]]:
    """Collect only currently active legacy rows; completed history is preserved."""

    if readonly:
        begin_task07_readonly_snapshot(session)

    specifications = (
        (
            "profile_active_bindings",
            ("id", "binding_status", "superseded_at"),
            "binding_status = :active",
            {"active": "active"},
        ),
        (
            "signal_scan_tasks",
            ("id", "status"),
            "status IN (:pending, :running, :retrying)",
            {"pending": "pending", "running": "running", "retrying": "retrying"},
        ),
        (
            "data_download_tasks",
            ("id", "status"),
            "status IN (:pending, :running, :retrying)",
            {"pending": "pending", "running": "running", "retrying": "retrying"},
        ),
        (
            "strategy_signals",
            ("id", "status", "is_active"),
            "is_active = :active",
            {"active": True},
        ),
    )
    relations: list[dict[str, Any]] = []
    for table, columns, predicate, parameters in specifications:
        selected = ", ".join(f'"{column}"' for column in columns)
        rows = session.execute(
            text(f'SELECT {selected} FROM "{table}" WHERE {predicate} ORDER BY id'),
            parameters,
        ).mappings()
        for row in rows:
            record = {"table": table, **dict(row)}
            if table == "profile_active_bindings" and record.get("superseded_at") is not None:
                record["superseded_at"] = _retirement_timestamp(record["superseded_at"])
            if table == "strategy_signals":
                record["is_active"] = bool(record["is_active"])
            relations.append(record)
    return sorted(relations, key=lambda item: (str(item["table"]), int(item["id"])))


_RETIREMENT_COLUMNS = {
    "profile_active_bindings": {"binding_status", "superseded_at"},
    "signal_scan_tasks": {"status"},
    "data_download_tasks": {"status"},
    "strategy_signals": {"status", "is_active"},
}


def _apply_retirement_plan(
    session: Session,
    plan: Mapping[str, Any],
    *,
    packet_path: Path,
    approval_hash: str,
    current_base_sha: str,
    current_database_revision: str,
    current_reference_report: Mapping[str, Any],
) -> dict[str, Any]:
    begin_task07_serializable_apply(session)
    _validate_retirement_plan_integrity(plan)
    current_reference_snapshot = _reference_snapshot(current_reference_report)
    if current_reference_snapshot != plan.get("reference_snapshot"):
        raise ValueError("TASK07_RETIREMENT_REFERENCE_DRIFT")
    if plan.get("retirement_eligible") is not True:
        if plan.get("reference_gate") == "zero_active_references":
            raise ValueError("TASK07_RUNTIME_CUTOVER_GATE_REQUIRED")
        raise ValueError("TASK07_RETIREMENT_REFERENCE_GATE_BLOCKED")
    current_plan = _build_retirement_plan(
        base_sha=current_base_sha,
        database_revision=current_database_revision,
        reference_report=current_reference_report,
        relations=_collect_retirement_relations(session, readonly=False),
        retirement_at=plan.get("retirement_at"),
    )
    if current_plan["plan_digest"] != plan.get("plan_digest"):
        raise ValueError("TASK07_RETIREMENT_ROW_SET_DRIFT")
    facts = _retirement_approval_facts(
        plan,
        current_base_sha=current_base_sha,
        current_database_revision=current_database_revision,
        current_reference_snapshot=current_reference_snapshot,
    )
    verify_exact_approval(
        packet_path,
        approval_hash=approval_hash,
        expected_command="data.task07.retirement-apply",
        current_facts=facts,
    )
    updates = list(plan.get("updates", []))
    if plan.get("deletes") != [] or plan.get("deletion_authorized") is not False:
        raise ValueError("TASK07_RETIREMENT_DELETE_SCOPE_INVALID")
    after: list[dict[str, Any]] = []
    rollback_updates: list[dict[str, Any]] = []
    try:
        for item in updates:
            table = str(item.get("table"))
            allowed = _RETIREMENT_COLUMNS.get(table)
            identifier = item.get("id")
            changes = item.get("set")
            if allowed is None or type(identifier) is not int or not isinstance(changes, dict):
                raise ValueError("TASK07_RETIREMENT_SCOPE_INVALID")
            before = {
                key: value
                for key, value in item.items()
                if key not in {"table", "id", "set"}
            }
            if (
                not before
                or not set(before) <= allowed
                or not set(changes) <= allowed
                or not set(changes) <= set(before)
            ):
                raise ValueError("TASK07_RETIREMENT_SCOPE_INVALID")
            predicates = ["id = :row_id"]
            parameters: dict[str, Any] = {"row_id": identifier}
            for position, (column, value) in enumerate(sorted(before.items())):
                if value is None:
                    predicates.append(f'"{column}" IS NULL')
                    continue
                name = f"before_{position}"
                predicates.append(f'"{column}" = :{name}')
                parameters[name] = value
            assignments = []
            for position, (column, value) in enumerate(sorted(changes.items())):
                name = f"after_{position}"
                assignments.append(f'"{column}" = :{name}')
                parameters[name] = value
            result = session.execute(
                text(
                    f'UPDATE "{table}" SET {", ".join(assignments)} '
                    f'WHERE {" AND ".join(predicates)}'
                ),
                parameters,
            )
            if result.rowcount != 1:
                raise ValueError("TASK07_RETIREMENT_ROW_DRIFT")
            selected = ", ".join(f'"{column}"' for column in sorted(allowed))
            readback = session.execute(
                text(f'SELECT {selected} FROM "{table}" WHERE id = :row_id'),
                {"row_id": identifier},
            ).mappings().one()
            actual = {
                column: _retirement_value(readback[column])
                for column in sorted(allowed)
            }
            expected = {
                column: _retirement_value(changes.get(column, before.get(column)))
                for column in sorted(allowed)
            }
            if actual != expected:
                raise ValueError("TASK07_RETIREMENT_READBACK_DRIFT")
            after.append({"table": table, "id": identifier, **actual})
            rollback_updates.append({"table": table, "id": identifier, "set": before, "expected": changes})
        session.commit()
    except Exception:
        session.rollback()
        raise
    body = {
        "schema_version": 1,
        "command": "data.task07.retirement-apply",
        "status": "passed",
        "plan_digest": plan["plan_digest"],
        "before_image_digest": plan["before_image_digest"],
        "after_image_digest": canonical_digest(after),
        "updated_row_count": len(after),
        "deleted_row_count": 0,
        "deletion_authorized": False,
        "rollback": {
            "authorized": False,
            "updates": rollback_updates,
            "digest": canonical_digest(rollback_updates),
        },
    }
    return {**body, "receipt_digest": canonical_digest(body)}


def _validate_retirement_plan_integrity(plan: Mapping[str, Any]) -> None:
    if (
        plan.get("schema_version") != 2
        or plan.get("command") != "data.task07.retirement-plan"
        or plan.get("status") != "planned"
    ):
        raise ValueError("TASK07_RETIREMENT_PLAN_SCHEMA_INVALID")
    before = plan.get("before_image")
    updates = plan.get("updates")
    if not isinstance(before, list) or not isinstance(updates, list):
        raise ValueError("TASK07_RETIREMENT_PLAN_INVALID")
    before_digest = canonical_digest(before)
    if before_digest != plan.get("before_image_digest"):
        raise ValueError("TASK07_RETIREMENT_BEFORE_IMAGE_MISMATCH")
    reference_snapshot = plan.get("reference_snapshot")
    if not isinstance(reference_snapshot, Mapping):
        raise ValueError("TASK07_RETIREMENT_PLAN_INVALID")
    expected_reference_snapshot = _reference_snapshot(
        reference_snapshot,
        require_complete_scope=False,
    )
    counts = expected_reference_snapshot["state_counts"]
    expected_reference_eligible = (
        expected_reference_snapshot["scope_complete"] is True
        and counts["active"] == 0
        and counts["review_required"] == 0
    )
    expected_reference_gate = (
        "BLOCKED_REFERENCE_EVIDENCE_INCOMPLETE"
        if expected_reference_snapshot["scope_complete"] is not True
        else "zero_active_references"
        if expected_reference_eligible
        else "BLOCKED_ACTIVE_REFERENCE"
    )
    expected_runtime_gate = "BLOCKED_TASK07_RUNTIME_CUTOVER_REQUIRED"
    expected_eligible = False
    if (
        plan.get("retirement_eligible") is not expected_eligible
        or plan.get("reference_gate") != expected_reference_gate
        or plan.get("runtime_cutover_receipt_contract")
        != _TASK07_RUNTIME_CUTOVER_RECEIPT_CONTRACT
        or plan.get("runtime_cutover_receipt_digest") is not None
        or plan.get("runtime_cutover_validated") is not False
        or plan.get("runtime_cutover_gate") != expected_runtime_gate
        or plan.get("gate_status")
        != (
            expected_reference_gate
            if not expected_reference_eligible
            else expected_runtime_gate
        )
    ):
        raise ValueError("TASK07_RETIREMENT_REFERENCE_GATE_DRIFT")
    facts = {
        "base_sha": plan.get("base_sha"),
        "database_revision": plan.get("database_revision"),
        "reference_snapshot": expected_reference_snapshot,
        "reference_gate": expected_reference_gate,
        "runtime_cutover_receipt_contract": dict(
            _TASK07_RUNTIME_CUTOVER_RECEIPT_CONTRACT
        ),
        "runtime_cutover_receipt_digest": None,
        "runtime_cutover_validated": False,
        "runtime_cutover_gate": expected_runtime_gate,
        "retirement_eligible": expected_eligible,
        "retirement_at": plan.get("retirement_at"),
        "before_image": before,
        "before_image_digest": before_digest,
        "updates": updates,
    }
    if plan.get("plan_digest") != canonical_digest(facts):
        raise ValueError("TASK07_RETIREMENT_PLAN_DIGEST_MISMATCH")


def _retirement_approval_facts(
    plan: Mapping[str, Any],
    *,
    current_base_sha: str,
    current_database_revision: str,
    current_reference_snapshot: object,
) -> dict[str, Any]:
    if current_reference_snapshot != plan.get("reference_snapshot"):
        raise ValueError("TASK07_RETIREMENT_REFERENCE_DRIFT")
    return {
        "base_sha": current_base_sha,
        "database_revision": current_database_revision,
        "plan_digest": plan.get("plan_digest"),
        "before_image_digest": plan.get("before_image_digest"),
        "reference_snapshot": current_reference_snapshot,
    }


def _retirement_timestamp(value: str | datetime | None) -> str:
    if value is None:
        parsed = datetime.now(UTC)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("TASK07_RETIREMENT_TIMESTAMP_INVALID") from exc
    else:
        raise ValueError("TASK07_RETIREMENT_TIMESTAMP_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TASK07_RETIREMENT_TIMESTAMP_INVALID")
    return parsed.astimezone(UTC).isoformat()


def _retirement_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _retirement_timestamp(value)
    return value


def verify_exact_approval(
    path: Path,
    *,
    approval_hash: str,
    expected_command: str,
    current_facts: Mapping[str, Any],
) -> dict[str, Any]:
    if not _SHA256.fullmatch(approval_hash):
        raise ValueError("TASK07_APPROVAL_HASH_INVALID")
    try:
        packet = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("TASK07_APPROVAL_PACKET_INVALID") from exc
    if canonical_digest(packet) != approval_hash:
        raise ValueError("TASK07_APPROVAL_HASH_MISMATCH")
    if packet.get("command") != expected_command or packet.get("writes_authorized") is not True:
        raise ValueError("TASK07_APPROVAL_SCOPE_INVALID")
    if packet.get("bound_facts") != dict(current_facts):
        raise ValueError("TASK07_APPROVAL_FACTS_DRIFT")
    return packet


verify_exact_approval.digest_packet = canonical_digest  # type: ignore[attr-defined]
