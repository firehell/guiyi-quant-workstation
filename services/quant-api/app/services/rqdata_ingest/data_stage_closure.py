from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any

import pandas as pd
from pandas.errors import EmptyDataError


ALLOWED_DOCUMENT_ACTIONS = {"keep", "update", "merge", "archive", "delete_candidate"}
CANONICAL_DOCS = {
    "README.md",
    "AGENTS.md",
    "STATUS.md",
    "PROJECT_SOURCE.md",
    "DECISIONS.md",
    "TESTING.md",
    "docs/ARCHITECTURE.md",
    "docs/DATA_CENTER.md",
    "docs/SIGNAL_EVENTS.md",
    "docs/INDICATOR_KERNEL.md",
}


@dataclass(frozen=True)
class ClosureInputs:
    input_dir: Path
    project_root: Path
    generated_at: datetime


def build_data_stage_closure_package(*, input_dir: Path, output_dir: Path, project_root: Path) -> dict[str, Path]:
    inputs = ClosureInputs(input_dir=input_dir, project_root=project_root, generated_at=datetime.now(UTC))
    tables = _load_input_tables(input_dir)

    outputs = {
        "asset_inventory": build_asset_inventory(tables),
        "product_period_coverage": build_product_period_coverage(tables),
        "contract_role_matrix": build_contract_role_matrix(tables),
        "manifest_db_consistency": build_manifest_db_consistency(tables),
        "duplicate_or_conflicting_assets": build_duplicate_or_conflicting_assets(tables),
        "document_inventory": build_document_inventory(project_root),
    }
    summary = render_closure_summary(inputs=inputs, tables=tables, outputs=outputs)

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, frame in outputs.items():
        path = output_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path
    summary_path = output_dir / "data_stage_closure_summary.md"
    summary_path.write_text(summary, encoding="utf-8")
    paths["data_stage_closure_summary"] = summary_path
    return paths


def build_asset_inventory(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    physical = tables["asset_physical_inventory"].copy()
    if physical.empty:
        return pd.DataFrame(columns=_asset_inventory_columns())

    physical["active_status"] = physical.apply(_active_status, axis=1)
    physical["file_count"] = 1
    physical["schema_version"] = ""
    physical["source_interval"] = ""
    physical["instrument"] = physical.get("product", "")
    physical["contract"] = physical.get("symbol_or_contract", "")
    physical["data_version"] = ""
    physical["db_registration_status"] = physical.get("db_market_data_file_id", "").map(_db_registration_status)

    columns = {
        "product": "product",
        "instrument": "instrument",
        "contract": "contract",
        "contract_role": "contract_role",
        "period": "period",
        "provider": "provider",
        "source_interval": "source_interval",
        "data_version": "data_version",
        "start_date": "start_datetime",
        "end_date": "end_datetime",
        "manifest_or_db_row_count": "row_count",
        "file_count": "file_count",
        "schema_version": "schema_version",
        "manifest_status": "manifest_status",
        "checksum_status": "checksum_status",
        "quality_status": "quality_status",
        "db_registration_status": "db_registration_status",
        "active_status": "active_status",
        "physical_path": "file_path",
        "physical_exists": "physical_exists",
        "duckdb_row_count": "duckdb_row_count",
        "row_count_status": "row_count_status",
    }
    result = physical.reindex(columns=list(columns)).rename(columns=columns)
    return result.reindex(columns=_asset_inventory_columns()).sort_values(["product", "period", "contract_role", "contract"])


def build_product_period_coverage(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    coverage = tables["target_coverage_matrix"].copy()
    if coverage.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    group_cols = ["product", "period"]
    for (product, period), group in coverage.groupby(group_cols, dropna=False):
        statuses = Counter(_clean(item) for item in group["status"])
        rows.append(
            {
                "product": product,
                "period": period,
                "target_rows": len(group),
                "covered_passed": statuses.get("covered_passed", 0),
                "covered_warning": statuses.get("covered_warning", 0),
                "metadata_gap": statuses.get("metadata_gap", 0),
                "not_applicable": statuses.get("not_applicable", 0),
                "other_status_rows": len(group)
                - statuses.get("covered_passed", 0)
                - statuses.get("covered_warning", 0)
                - statuses.get("metadata_gap", 0)
                - statuses.get("not_applicable", 0),
                "coverage_status": _coverage_status(statuses),
                "min_start_date": _min_text_date(group.get("start_date")),
                "max_end_date": _max_text_date(group.get("end_date")),
                "unique_contracts": group["symbol_or_contract"].nunique(dropna=True),
            }
        )
    return pd.DataFrame(rows).sort_values(["product", "period"])


def build_contract_role_matrix(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    coverage = tables["target_coverage_matrix"].copy()
    if coverage.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for (product, contract_role, period), group in coverage.groupby(["product", "contract_role", "period"], dropna=False):
        statuses = Counter(_clean(item) for item in group["status"])
        rows.append(
            {
                "product": product,
                "contract_role": contract_role,
                "period": period,
                "target_rows": len(group),
                "covered_passed": statuses.get("covered_passed", 0),
                "covered_warning": statuses.get("covered_warning", 0),
                "metadata_gap": statuses.get("metadata_gap", 0),
                "not_applicable": statuses.get("not_applicable", 0),
                "coverage_status": _coverage_status(statuses),
                "unique_symbols_or_contracts": group["symbol_or_contract"].nunique(dropna=True),
            }
        )
    return pd.DataFrame(rows).sort_values(["product", "contract_role", "period"])


def build_manifest_db_consistency(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    physical = tables["asset_physical_inventory"].copy()
    metadata = tables["metadata_consistency_matrix"].copy()
    rows: list[dict[str, Any]] = []

    if not physical.empty:
        physical["db_registration_status"] = physical.get("db_market_data_file_id", "").map(_db_registration_status)
        for (product, period), group in physical.groupby(["product", "period"], dropna=False):
            rows.append(
                {
                    "product": product,
                    "period": period,
                    "dataset": "market_data_files",
                    "row_count": len(group),
                    "db_registered": int((group["db_registration_status"] == "registered").sum()),
                    "db_unregistered": int((group["db_registration_status"] != "registered").sum()),
                    "manifest_missing": int((group.get("manifest_status", "").map(_clean) == "missing").sum()),
                    "checksum_matched": int((group.get("checksum_status", "").map(_clean).isin({"matched", "match", "passed"})).sum()),
                    "row_count_matched": int((group.get("row_count_status", "").map(_clean).isin({"matched", "match", "passed"})).sum()),
                    "quality_warning": int((group.get("quality_status", "").map(_clean) == "warning").sum()),
                    "quality_failed": int((group.get("quality_status", "").map(_clean) == "failed").sum()),
                    "consistency_status": _physical_consistency_status(group),
                }
            )

    if not metadata.empty:
        for (product, dataset), group in metadata.groupby(["product", "dataset"], dropna=False):
            statuses = Counter(_clean(item) for item in group["status"])
            rows.append(
                {
                    "product": product,
                    "period": "",
                    "dataset": dataset,
                    "row_count": len(group),
                    "db_registered": statuses.get("covered_passed", 0),
                    "db_unregistered": statuses.get("metadata_gap", 0),
                    "manifest_missing": 0,
                    "checksum_matched": 0,
                    "row_count_matched": 0,
                    "quality_warning": 0,
                    "quality_failed": 0,
                    "consistency_status": _coverage_status(statuses),
                }
            )

    return pd.DataFrame(rows).sort_values(["product", "dataset", "period"]) if rows else pd.DataFrame()


def build_duplicate_or_conflicting_assets(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    duplicate = tables["duplicate_active_assets"].copy()
    coverage = tables["target_coverage_matrix"].copy()
    rows: list[dict[str, Any]] = []

    if not duplicate.empty:
        for _, row in duplicate.iterrows():
            rows.append(
                {
                    "product": row.get("product", ""),
                    "contract_role": row.get("contract_role", ""),
                    "symbol_or_contract": row.get("contract_code", row.get("symbol_or_contract", "")),
                    "period": row.get("period", ""),
                    "issue_class": row.get("issue_class", "duplicate_active"),
                    "conflict_count": row.get("duplicate_group_size", ""),
                    "status": row.get("disposition", "requires_review"),
                    "evidence": row.get("file_path", ""),
                }
            )

    if not coverage.empty:
        active = coverage[coverage["status"].isin(["covered_passed", "covered_warning", "metadata_gap"])].copy()
        group_cols = ["product", "contract_role", "symbol_or_contract", "period", "year"]
        for keys, group in active.groupby(group_cols, dropna=False):
            paths = sorted({_clean(path) for path in group.get("standard_path", []) if _clean(path)})
            statuses = sorted({_clean(status) for status in group.get("status", []) if _clean(status)})
            if len(paths) > 1 or ("covered_passed" in statuses and "metadata_gap" in statuses):
                product, contract_role, symbol, period, year = keys
                rows.append(
                    {
                        "product": product,
                        "contract_role": contract_role,
                        "symbol_or_contract": symbol,
                        "period": period,
                        "issue_class": "conflicting_target_evidence",
                        "conflict_count": len(paths),
                        "status": ",".join(statuses),
                        "evidence": f"year={year}; paths={';'.join(paths[:5])}",
                    }
                )

    columns = ["product", "contract_role", "symbol_or_contract", "period", "issue_class", "conflict_count", "status", "evidence"]
    return pd.DataFrame(rows, columns=columns).sort_values(["product", "contract_role", "period"]) if rows else pd.DataFrame(columns=columns)


def build_document_inventory(project_root: Path) -> pd.DataFrame:
    docs = _markdown_files(project_root)
    contents = {path: _safe_read(path) for path in docs}
    rows: list[dict[str, Any]] = []
    for path in docs:
        rel = path.relative_to(project_root).as_posix()
        text = contents[path]
        action, reason = _document_action(rel, text)
        rows.append(
            {
                "path": rel,
                "title": _markdown_title(text, path.name),
                "last_updated": _last_updated(text),
                "purpose": _document_purpose(rel),
                "current_status": _document_status(text),
                "canonical_source": _canonical_source(rel),
                "action": action,
                "reason": reason,
                "referenced_by": _referenced_by(rel, contents, project_root),
            }
        )
    return pd.DataFrame(rows).sort_values(["path"])


def render_closure_summary(*, inputs: ClosureInputs, tables: dict[str, pd.DataFrame], outputs: dict[str, pd.DataFrame]) -> str:
    coverage_counts = _status_counts(tables["target_coverage_matrix"], "status")
    weekly = tables["weekly_history_audit"]
    pre2020_applicable = int((weekly.get("pre_2020_applicable", pd.Series(dtype=str)).map(_truthy)).sum()) if not weekly.empty else 0
    pre2020_covered = int((weekly.get("pre_2020_status", pd.Series(dtype=str)).map(_clean) == "covered").sum()) if not weekly.empty else 0
    direct_1w_present = int((weekly.get("direct_1w_present", pd.Series(dtype=str)).map(_truthy)).sum()) if not weekly.empty else 0
    dominant_passed = _contract_period_passed(tables["target_coverage_matrix"], contract_role="dominant_main")
    actual_passed = _contract_period_passed(tables["target_coverage_matrix"], contract_role="actual_contract")
    quality_warning = int((tables["target_coverage_matrix"].get("status", pd.Series(dtype=str)).map(_clean) == "covered_warning").sum())
    duplicate_rows = len(outputs["duplicate_or_conflicting_assets"])

    return "\n".join(
        [
            "# 数据阶段收口审计汇总",
            "",
            f"生成时间：`{inputs.generated_at.isoformat()}`",
            "",
            "## 结论",
            "",
            "当前结论：`DATA_LAYER_PARTIAL`。本轮是只读收口审计与文档事实源整理，不代表数据层最终封板完成。",
            "",
            "关键边界：`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论；更新的 Phase 3 数据层验收仍显示 manifest/DB 对齐、pre-2020 周线和 actual contract 缺口，因此不得宣称 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。",
            "",
            "## 覆盖统计",
            "",
            f"- covered_passed: `{coverage_counts.get('covered_passed', 0)}`",
            f"- covered_warning: `{coverage_counts.get('covered_warning', 0)}`",
            f"- missing_db_registration: `{coverage_counts.get('missing_db_registration', 0)}`",
            f"- metadata_gap: `{coverage_counts.get('metadata_gap', 0)}`",
            f"- not_applicable: `{coverage_counts.get('not_applicable', 0)}`",
            f"- other_status_rows: `{_other_status_count(coverage_counts)}`",
            f"- quality_warning: `{quality_warning}`（不升级为 passed）",
            f"- duplicate/conflicting rows: `{duplicate_rows}`",
            "",
            "## 周线完整性",
            "",
            f"- direct 1w present products: `{direct_1w_present}`",
            f"- pre-2020 applicable products: `{pre2020_applicable}`",
            f"- pre-2020 covered products: `{pre2020_covered}`",
            "",
            "逐品种明细见 `product_period_coverage.csv`、`contract_role_matrix.csv` 和上游 `weekly_history_audit.csv`。当前不能宣称“全品种周线从上市以来完整”。",
            "",
            "## 合约角色",
            "",
            f"- dominant_main covered_passed rows: `{dominant_passed}`",
            f"- actual_contract covered_passed rows: `{actual_passed}`",
            "",
            "主连、主力和实际合约仍需以 `contract_role_matrix.csv` 与 `main_contract_mapping_audit.csv` 为准，不得把研究连续合约当成可交易合约。",
            "",
            "## 输出文件",
            "",
            "- `asset_inventory.csv`",
            "- `product_period_coverage.csv`",
            "- `contract_role_matrix.csv`",
            "- `manifest_db_consistency.csv`",
            "- `duplicate_or_conflicting_assets.csv`",
            "- `document_inventory.csv`",
            "- `data_stage_closure_summary.md`",
            "",
            "## 安全声明",
            "",
            "- writes_database=False",
            "- writes_parquet=False",
            "- writes_manifest=False",
            "- calls_rqdata=False",
            "- 不涉及策略、回测参数、live scheduler、企业微信或自动交易。",
            "",
        ]
    )


def _load_input_tables(input_dir: Path) -> dict[str, pd.DataFrame]:
    required = {
        "target_coverage_matrix": "target_coverage_matrix.csv",
        "asset_physical_inventory": "asset_physical_inventory.csv",
        "metadata_consistency_matrix": "metadata_consistency_matrix.csv",
        "weekly_history_audit": "weekly_history_audit.csv",
    }
    optional = {
        "duplicate_active_assets": "duplicate_active_assets.csv",
        "quality_issue_register": "quality_issue_register.csv",
        "main_contract_mapping_audit": "main_contract_mapping_audit.csv",
    }
    tables: dict[str, pd.DataFrame] = {}
    for name, filename in required.items():
        path = input_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"required audit input missing: {path}")
        tables[name] = pd.read_csv(path, dtype=str).fillna("")
    for name, filename in optional.items():
        path = input_dir / filename
        tables[name] = _read_optional_csv(path)
    return tables


def _read_optional_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.stat().st_size:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str).fillna("")
    except EmptyDataError:
        return pd.DataFrame()


def _asset_inventory_columns() -> list[str]:
    return [
        "product",
        "instrument",
        "contract",
        "contract_role",
        "period",
        "provider",
        "source_interval",
        "data_version",
        "start_datetime",
        "end_datetime",
        "row_count",
        "file_count",
        "schema_version",
        "manifest_status",
        "checksum_status",
        "quality_status",
        "db_registration_status",
        "active_status",
        "file_path",
        "physical_exists",
        "duckdb_row_count",
        "row_count_status",
    ]


def _active_status(row: pd.Series) -> str:
    if _clean(row.get("data_role")) != "primary":
        return "excluded_with_reason"
    quality = _clean(row.get("quality_status"))
    if quality == "passed":
        return "verified_complete"
    if quality == "warning":
        return "warning"
    if quality == "failed":
        return "failed"
    return "partial"


def _db_registration_status(value: Any) -> str:
    return "registered" if _clean(value) else "unregistered"


def _coverage_status(statuses: Counter[str]) -> str:
    if statuses.get("metadata_gap", 0):
        return "partial"
    if statuses.get("covered_warning", 0):
        return "warning"
    if statuses and statuses.get("covered_passed", 0) + statuses.get("not_applicable", 0) == sum(statuses.values()):
        return "verified_complete"
    return "partial"


def _physical_consistency_status(group: pd.DataFrame) -> str:
    if (group.get("quality_status", pd.Series(dtype=str)).map(_clean) == "failed").any():
        return "failed"
    if (group.get("quality_status", pd.Series(dtype=str)).map(_clean) == "warning").any():
        return "warning"
    if (group.get("row_count_status", pd.Series(dtype=str)).map(_clean).isin({"mismatch", "failed"})).any():
        return "partial"
    return "verified_complete"


def _status_counts(frame: pd.DataFrame, column: str) -> Counter[str]:
    if frame.empty or column not in frame.columns:
        return Counter()
    return Counter(_clean(item) for item in frame[column])


def _contract_period_passed(frame: pd.DataFrame, *, contract_role: str) -> int:
    if frame.empty:
        return 0
    subset = frame[(frame["contract_role"].map(_clean) == contract_role) & (frame["status"].map(_clean) == "covered_passed")]
    return len(subset)


def _other_status_count(statuses: Counter[str]) -> int:
    known = {"covered_passed", "covered_warning", "missing_db_registration", "metadata_gap", "not_applicable"}
    return sum(count for status, count in statuses.items() if status not in known)


def _min_text_date(series: pd.Series | None) -> str:
    if series is None:
        return ""
    values = sorted(value for value in (_clean(item) for item in series) if value)
    return values[0] if values else ""


def _max_text_date(series: pd.Series | None) -> str:
    if series is None:
        return ""
    values = sorted(value for value in (_clean(item) for item in series) if value)
    return values[-1] if values else ""


def _markdown_files(project_root: Path) -> list[Path]:
    skipped_parts = {".git", ".venv", "node_modules", "dist", "__pycache__"}
    files: list[Path] = []
    for path in project_root.rglob("*.md"):
        if any(part in skipped_parts for part in path.relative_to(project_root).parts):
            continue
        files.append(path)
    return sorted(files)


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _last_updated(text: str) -> str:
    match = re.search(r"(更新时间|生成时间)：?\\s*`?([0-9]{4}-[0-9]{2}-[0-9]{2}[^`\\n]*)`?", text)
    return match.group(2).strip() if match else ""


def _document_purpose(rel: str) -> str:
    if rel in CANONICAL_DOCS:
        return "canonical_source"
    if rel.startswith("docs/tasks/"):
        return "task_evidence"
    if rel.startswith("data/reports/"):
        return "audit_report"
    return "project_document"


def _document_status(text: str) -> str:
    for marker in ["DATA_LAYER_PARTIAL", "DELIVERY_READY", "MERGED_TO_MAIN", "passed", "failed"]:
        if marker in text:
            return marker
    return ""


def _canonical_source(rel: str) -> str:
    if rel in CANONICAL_DOCS:
        return rel
    if rel.startswith("docs/tasks/"):
        return "docs/tasks/"
    if rel.startswith("data/reports/"):
        return "data/reports/"
    return "STATUS.md"


def _document_action(rel: str, text: str) -> tuple[str, str]:
    if rel == "docs/DATA_CENTER.md":
        return "update", "current data closure facts must reflect DATA_LAYER_PARTIAL"
    if "DATA-PART-TARGET-CLOSURE" in text and "DATA_LAYER_PARTIAL" not in text:
        return "merge", "contains earlier delivery-ready evidence that now needs partial-state caveat"
    if rel.startswith(".pytest_cache/") or rel.startswith(".ai/results/codex_plan_"):
        return "delete_candidate", "cache or temporary plan export; keep as candidate only, no hard delete in this task"
    if rel.startswith("docs/tasks/") or rel.startswith("data/reports/"):
        return "keep", "stage evidence must be preserved"
    return "keep", "no cleanup action selected"


def _referenced_by(rel: str, contents: dict[Path, str], project_root: Path) -> str:
    basename = Path(rel).name
    refs: list[str] = []
    for path, text in contents.items():
        other = path.relative_to(project_root).as_posix()
        if other == rel:
            continue
        if rel in text or basename in text:
            refs.append(other)
        if len(refs) >= 5:
            break
    return ";".join(refs)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _truthy(value: Any) -> bool:
    return _clean(value).lower() in {"true", "1", "yes", "y"}
