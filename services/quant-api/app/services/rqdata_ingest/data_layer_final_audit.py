from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime
import json
import subprocess
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.data_center import MainContractMap, MarketDataFile
from app.services.rqdata_ingest.target_coverage_audit import (
    DEFAULT_AUDIT_END,
    DEFAULT_MINUTE_START,
    ProductWindow,
    load_product_windows,
)


MODE = "data_layer_final_audit"
ARCHITECTURE_1M_START = DEFAULT_MINUTE_START
CLAIM_1M_START = date(2020, 1, 2)
PRE_2020_WEEKLY_END = date(2019, 12, 31)


def run_extended_final_audit(
    *,
    session: Session | None,
    project_root: Path,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    audit_end: date,
    target_coverage_result: dict[str, Any],
    stage8_6_1d_result: dict[str, Any],
    jm_six_period_result: dict[str, Any],
    git_commit: str,
    db_snapshot_time: str,
) -> dict[str, Any]:
    registered_paths = _collect_registered_paths(session, project_root, products)
    market_files = _load_market_files(session)

    duplicate_active = build_duplicate_active_assets(market_files)
    orphan_files = build_orphan_files(project_root=project_root, products=products, registered_paths=registered_paths)
    main_contract_mapping = build_main_contract_mapping_audit(
        session=session,
        project_root=project_root,
        products=products,
        market_files=market_files,
    )
    reference_data = build_reference_data_audit(
        products=products,
        metadata_matrix=target_coverage_result.get("metadata_consistency_matrix") or [],
    )
    weekly_history = build_weekly_history_audit(
        project_root=project_root,
        products=products,
        product_windows=product_windows,
        market_files=market_files,
        coverage_matrix=target_coverage_result.get("target_coverage_matrix") or [],
        audit_end=audit_end,
    )
    daily_intraday = build_daily_intraday_crosscheck(
        project_root=project_root,
        products=products,
        market_files=market_files,
        audit_end=audit_end,
    )
    quality_issue_register = build_quality_issue_register(target_coverage_result.get("issue_register") or [])
    claim_verdicts = build_claim_verdicts(
        products=products,
        product_windows=product_windows,
        coverage_matrix=target_coverage_result.get("target_coverage_matrix") or [],
        weekly_history=weekly_history,
        stage8_6_1d_result=stage8_6_1d_result,
        audit_end=audit_end,
    )
    stale_metrics = build_stale_metrics_verdict(stage8_6_1d_result=stage8_6_1d_result)

    evidence = build_audit_evidence(
        git_commit=git_commit,
        audit_end=audit_end,
        project_root=project_root,
        db_snapshot_source=target_coverage_result.get("db_snapshot_source", ""),
        db_snapshot_time=db_snapshot_time,
        products=products,
        target_coverage_result=target_coverage_result,
        stage8_6_1d_result=stage8_6_1d_result,
        jm_six_period_result=jm_six_period_result,
        duplicate_active=duplicate_active,
        orphan_files=orphan_files,
        weekly_history=weekly_history,
        claim_verdicts=claim_verdicts,
        stale_metrics=stale_metrics,
    )
    markdown = render_final_audit_markdown(
        audit_end=audit_end,
        git_commit=git_commit,
        project_root=project_root,
        evidence=evidence,
        target_coverage_result=target_coverage_result,
        stage8_6_1d_result=stage8_6_1d_result,
        jm_six_period_result=jm_six_period_result,
        claim_verdicts=claim_verdicts,
        stale_metrics=stale_metrics,
        quality_issue_register=quality_issue_register,
    )

    return {
        "mode": MODE,
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "duplicate_active_assets": duplicate_active,
        "orphan_files": orphan_files,
        "main_contract_mapping_audit": main_contract_mapping,
        "reference_data_audit": reference_data,
        "weekly_history_audit": weekly_history,
        "daily_intraday_crosscheck": daily_intraday,
        "quality_issue_register": quality_issue_register,
        "audit_evidence": evidence,
        "final_audit_markdown": markdown,
        "claim_verdicts": claim_verdicts,
        "stale_metrics": stale_metrics,
    }


def write_final_audit_reports(
    *,
    output_dir: Path,
    target_coverage_result: dict[str, Any],
    extended_result: dict[str, Any],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    core_mapping = {
        "target_asset_catalog": "target_asset_catalog.csv",
        "asset_physical_inventory": "asset_physical_inventory.csv",
        "target_coverage_matrix": "target_coverage_matrix.csv",
        "metadata_consistency_matrix": "metadata_consistency_matrix.csv",
    }
    for key, filename in core_mapping.items():
        path = output_dir / filename
        pd.DataFrame(target_coverage_result[key]).to_csv(path, index=False)
        outputs[key] = path

    extended_mapping = {
        "duplicate_active_assets": "duplicate_active_assets.csv",
        "orphan_files": "orphan_files.csv",
        "main_contract_mapping_audit": "main_contract_mapping_audit.csv",
        "reference_data_audit": "reference_data_audit.csv",
        "weekly_history_audit": "weekly_history_audit.csv",
        "daily_intraday_crosscheck": "daily_intraday_crosscheck.csv",
        "quality_issue_register": "quality_issue_register.csv",
    }
    for key, filename in extended_mapping.items():
        path = output_dir / filename
        pd.DataFrame(extended_result[key]).to_csv(path, index=False)
        outputs[key] = path

    evidence_path = output_dir / "audit_evidence.json"
    evidence_path.write_text(json.dumps(extended_result["audit_evidence"], indent=2, ensure_ascii=False), encoding="utf-8")
    outputs["audit_evidence"] = evidence_path

    markdown_path = output_dir / "DATA_LAYER_FINAL_AUDIT.md"
    markdown_path.write_text(extended_result["final_audit_markdown"], encoding="utf-8")
    outputs["final_audit_markdown"] = markdown_path

    summary_path = output_dir / "coverage_summary.md"
    summary_path.write_text(target_coverage_result["coverage_summary"], encoding="utf-8")
    outputs["coverage_summary"] = summary_path

    return outputs


def build_duplicate_active_assets(market_files: list[Any]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in market_files:
        if _clean_text(getattr(row, "data_role", "")) != "primary":
            continue
        if _clean_text(getattr(row, "quality_status", "")) == "failed":
            continue
        if _clean_text(getattr(row, "data_type", "")) != "bars":
            continue
        product = _clean_text(getattr(row, "instrument_symbol", "")).lower()
        period = _clean_text(getattr(row, "period", ""))
        contract = _clean_text(getattr(row, "contract_code", ""))
        contract_role = "dominant_main" if contract.endswith(".MAIN") or contract == f"{product}.MAIN" else "actual_contract"
        groups[(product, contract, period)].append(
            {
                "product": product,
                "contract_role": contract_role,
                "contract_code": contract,
                "period": period,
                "market_data_file_id": getattr(row, "id", None),
                "data_version": _clean_text(getattr(row, "data_version", "")),
                "quality_status": _clean_text(getattr(row, "quality_status", "")),
                "file_path": _clean_text(getattr(row, "file_path", "")),
                "start_time": _iso(getattr(row, "start_time", None)),
                "end_time": _iso(getattr(row, "end_time", None)),
            }
        )

    rows: list[dict[str, Any]] = []
    for (product, contract, period), items in sorted(groups.items()):
        if len(items) <= 1:
            continue
        contract_role = "dominant_main" if contract.endswith(".MAIN") or contract == f"{product}.MAIN" else "actual_contract"
        for item in items:
            rows.append(
                {
                    **item,
                    "duplicate_group_size": len(items),
                    "issue_class": "duplicate_active",
                    "disposition": "requires_supersede_decision",
                }
            )
    return rows


def build_orphan_files(*, project_root: Path, products: list[str], registered_paths: set[str]) -> list[dict[str, Any]]:
    product_set = set(products)
    canonical_root = project_root / "data" / "parquet" / "canonical" / "bars"
    rows: list[dict[str, Any]] = []
    if not canonical_root.exists():
        return rows

    for path in sorted(canonical_root.rglob("*.parquet")):
        resolved = str(path.resolve())
        if resolved in registered_paths:
            continue
        product = _product_from_parquet_path(path)
        if product and product not in product_set:
            continue
        rows.append(
            {
                "physical_path": resolved,
                "product": product,
                "period": _period_from_parquet_path(path),
                "contract": _contract_from_parquet_path(path),
                "file_size_bytes": path.stat().st_size if path.exists() else 0,
                "issue_class": "orphan_file",
                "disposition": "register_or_archive",
            }
        )
    return rows


def build_main_contract_mapping_audit(
    *,
    session: Session | None,
    project_root: Path,
    products: list[str],
    market_files: list[Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    bars_by_contract: dict[str, list[str]] = defaultdict(list)
    for row in market_files:
        contract = _clean_text(getattr(row, "contract_code", ""))
        path = _clean_text(getattr(row, "file_path", ""))
        if contract and path:
            bars_by_contract[contract.lower()].append(path)

    if session is None:
        for product in products:
            rows.append(
                {
                    "product": product,
                    "audit_status": "db_unavailable",
                    "issue_class": "metadata_gap",
                    "detail": "main_contract_map requires database snapshot",
                }
            )
        return rows

    for product in products:
        mappings = list(
            session.scalars(
                select(MainContractMap)
                .where(MainContractMap.instrument_symbol == product)
                .where(MainContractMap.rank == 1)
                .where(MainContractMap.provider == "rqdata")
                .order_by(MainContractMap.trade_date)
            )
        )
        if not mappings:
            rows.append(
                {
                    "product": product,
                    "mapping_rows": 0,
                    "audit_status": "missing_mapping",
                    "issue_class": "mapping_defect",
                    "detail": "no rank=1 main_contract_map rows",
                }
            )
            continue

        dates = [item.trade_date for item in mappings]
        contracts = [_clean_text(item.contract_code) for item in mappings]
        main_misuse = [contract for contract in contracts if contract.upper().endswith(".MAIN") or contract.upper() == f"{product.upper()}.MAIN"]
        duplicate_dates = [day for day, count in Counter(dates).items() if count > 1]
        gap_count = _count_date_gaps(dates)
        missing_bars = sorted({contract for contract in contracts if contract and contract.lower() not in bars_by_contract and not contract.upper().endswith(".MAIN")})

        status = "passed"
        issue_class = ""
        details: list[str] = []
        if main_misuse:
            status = "failed"
            issue_class = "mapping_defect"
            details.append("main_used_as_actual_contract")
        if duplicate_dates:
            status = "failed"
            issue_class = "mapping_defect"
            details.append("duplicate_trade_date")
        if gap_count > 0:
            status = "warning" if status == "passed" else status
            issue_class = issue_class or "mapping_defect"
            details.append(f"date_gaps={gap_count}")

        rows.append(
            {
                "product": product,
                "mapping_rows": len(mappings),
                "min_trade_date": dates[0].isoformat(),
                "max_trade_date": dates[-1].isoformat(),
                "unique_contracts": len(set(contracts)),
                "main_misuse_count": len(main_misuse),
                "duplicate_trade_dates": len(duplicate_dates),
                "date_gap_count": gap_count,
                "mapped_contracts_missing_bars": len(missing_bars),
                "audit_status": status,
                "issue_class": issue_class or "confirmed_passed",
                "detail": ";".join(details) if details else "rank1_mapping_present",
            }
        )
    return rows


def build_reference_data_audit(*, products: list[str], metadata_matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in metadata_matrix:
        by_product[_clean_text(item.get("product")).lower()].append(item)

    for product in products:
        items = by_product.get(product, [])
        if not items:
            rows.append(
                {
                    "product": product,
                    "dataset": "all",
                    "audit_status": "metadata_gap",
                    "issue_class": "metadata_inconsistent",
                    "detail": "no metadata matrix rows",
                }
            )
            continue
        for item in items:
            rows.append(
                {
                    "product": product,
                    "year": item.get("year"),
                    "dataset": item.get("dataset"),
                    "status": item.get("status"),
                    "row_count": item.get("row_count"),
                    "audit_status": item.get("status"),
                    "issue_class": "confirmed_passed" if item.get("status") == "covered_passed" else str(item.get("status")),
                    "detail": item.get("detail", ""),
                }
            )
    return rows


def build_weekly_history_audit(
    *,
    project_root: Path,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    market_files: list[Any],
    coverage_matrix: list[dict[str, Any]],
    audit_end: date,
) -> list[dict[str, Any]]:
    weekly_files = _index_dominant_files(market_files, period="1w")
    rows: list[dict[str, Any]] = []

    for product in products:
        window = product_windows.get(product)
        listed = window.listed_date if window else None
        pre_2020_end = min(PRE_2020_WEEKLY_END, audit_end)
        pre_2020_applicable = listed is not None and listed <= pre_2020_end

        file_info = weekly_files.get(product)
        physical = _duckdb_summary(_resolve_path(project_root, file_info["file_path"])) if file_info else {"exists": False}

        pre_2020_status = "not_applicable"
        if pre_2020_applicable:
            if file_info and physical.get("exists"):
                min_dt = _to_date(physical.get("min_datetime"))
                pre_2020_status = "covered" if min_dt and min_dt <= listed else "partial_or_missing_pre2020"
            else:
                pre_2020_status = "missing_pre2020"

        post_2020_rows = [
            row
            for row in coverage_matrix
            if _clean_text(row.get("product")).lower() == product
            and _clean_text(row.get("period")) == "1w"
            and _clean_text(row.get("contract_role")) == "dominant_main"
            and int(row.get("year") or 0) >= 2020
            and _matrix_status(row) != "not_applicable"
        ]
        post_2020_passed = sum(1 for row in post_2020_rows if _matrix_status(row) in {"covered_passed", "covered_warning"})
        post_2020_expected = len(post_2020_rows)

        incomplete_week_excluded = audit_end.weekday() < 4  # Thu or earlier in week ending audit_end Fri
        seam_status = "unchecked"
        if file_info and physical.get("exists"):
            min_dt = _to_date(physical.get("min_datetime"))
            max_dt = _to_date(physical.get("max_datetime"))
            if min_dt and min_dt.year <= 2020 <= (max_dt.year if max_dt else 2020):
                seam_status = "continuous_file_spans_2020"
            elif min_dt and min_dt.year > 2020:
                seam_status = "possible_2020_seam_gap"

        rows.append(
            {
                "product": product,
                "listed_date": listed.isoformat() if listed else "",
                "pre_2020_applicable": pre_2020_applicable,
                "pre_2020_status": pre_2020_status,
                "post_2020_passed_years": post_2020_passed,
                "post_2020_expected_years": post_2020_expected,
                "direct_1w_present": bool(file_info),
                "direct_1w_row_count": file_info.get("row_count") if file_info else "",
                "duckdb_row_count": physical.get("row_count", ""),
                "min_datetime": physical.get("min_datetime", ""),
                "max_datetime": physical.get("max_datetime", ""),
                "incomplete_week_excluded": incomplete_week_excluded,
                "seam_2020_status": seam_status,
                "issue_class": _weekly_issue_class(pre_2020_status, post_2020_passed, post_2020_expected, bool(file_info)),
            }
        )
    return rows


def build_daily_intraday_crosscheck(
    *,
    project_root: Path,
    products: list[str],
    market_files: list[Any],
    audit_end: date,
) -> list[dict[str, Any]]:
    direct_1d = _index_dominant_files(market_files, period="1d")
    direct_1m = _index_dominant_files(market_files, period="1m")
    direct_1w = _index_dominant_files(market_files, period="1w")
    rows: list[dict[str, Any]] = []

    for product in products:
        d1d = direct_1d.get(product)
        d1m = direct_1m.get(product)
        d1w = direct_1w.get(product)

        derived_1d_path = _find_derived_1d_from_1m(project_root, product)
        derived_1d = _duckdb_summary(derived_1d_path) if derived_1d_path else {"exists": False}

        direct_1d_physical = _duckdb_summary(_resolve_path(project_root, d1d["file_path"])) if d1d else {"exists": False}
        direct_1w_physical = _duckdb_summary(_resolve_path(project_root, d1w["file_path"])) if d1w else {"exists": False}

        row_count_diff = ""
        crosscheck_status = "not_applicable"
        if d1d and derived_1d.get("exists"):
            direct_count = direct_1d_physical.get("row_count")
            derived_count = derived_1d.get("row_count")
            if direct_count is not None and derived_count is not None:
                row_count_diff = str(int(direct_count) - int(derived_count))
                crosscheck_status = "match" if int(direct_count) == int(derived_count) else "row_count_diff"
        elif d1d and d1m:
            crosscheck_status = "direct_1d_only_no_derived_1d"
        elif derived_1d.get("exists"):
            crosscheck_status = "derived_1d_only"

        weekly_from_1d_status = "not_run"
        if direct_1w_physical.get("exists") and direct_1d_physical.get("exists"):
            weekly_from_1d_status = "both_present_manual_review"

        rows.append(
            {
                "product": product,
                "direct_1d_present": bool(d1d),
                "derived_1d_from_1m_present": derived_1d.get("exists", False),
                "direct_1m_present": bool(d1m),
                "direct_1w_present": bool(d1w),
                "direct_1d_row_count": direct_1d_physical.get("row_count", ""),
                "derived_1d_row_count": derived_1d.get("row_count", ""),
                "row_count_diff_direct_minus_derived": row_count_diff,
                "crosscheck_status": crosscheck_status,
                "weekly_from_1d_status": weekly_from_1d_status,
                "issue_class": "crosscheck_diff" if crosscheck_status == "row_count_diff" else crosscheck_status,
                "primary_source_decision": "unchanged_readonly_audit",
            }
        )
    return rows


def build_quality_issue_register(issue_register: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in issue_register:
        issue_type = _clean_text(item.get("issue_type"))
        status = _matrix_status(item)
        issue_class = issue_type or status or "unknown_error"
        rows.append(
            {
                **item,
                "issue_class": issue_class,
                "upgrade_to_passed_allowed": "false" if issue_type == "quality_warning" else "",
            }
        )
    return rows


def build_claim_verdicts(
    *,
    products: list[str],
    product_windows: dict[str, ProductWindow],
    coverage_matrix: list[dict[str, Any]],
    weekly_history: list[dict[str, Any]],
    stage8_6_1d_result: dict[str, Any],
    audit_end: date,
) -> list[dict[str, Any]]:
    claims = [
        ("claim_1", "全品种已经下载2020年至今的1m数据", _verdict_claim_1m(products, coverage_matrix, architecture=False)),
        ("claim_1_arch", "架构口径：主力1m自2023-01-03起", _verdict_claim_1m(products, coverage_matrix, architecture=True)),
        ("claim_2", "全品种已经下载2020年至今的1d数据", _verdict_claim_1d(products, coverage_matrix)),
        ("claim_3", "全品种已经下载2020年至今的1w数据", _verdict_claim_1w_recent(products, weekly_history)),
        ("claim_4", "全品种从上市以来到2019年末的1w数据也已经下载", _verdict_claim_pre2020_1w(products, weekly_history)),
        ("claim_5", "全品种1w候选覆盖范围为上市以来至最新完成周", _verdict_claim_full_1w(products, weekly_history, audit_end)),
        ("claim_6", "已下载主连、历史主力真实合约及相关附加数据", _verdict_claim_main_and_actual(stage8_6_1d_result)),
    ]
    return [{"claim_id": claim_id, "statement": statement, **verdict} for claim_id, statement, verdict in claims]


def build_stale_metrics_verdict(*, stage8_6_1d_result: dict[str, Any]) -> dict[str, Any]:
    matrix = stage8_6_1d_result.get("matrix") or []
    product_summary = stage8_6_1d_result.get("product_summary") or []
    passed_assets = sum(1 for row in matrix if _clean_text(row.get("gate_status")) == "active_passed")
    pending_assets = sum(1 for row in matrix if _clean_text(row.get("gate_status")) == "audit_pending")
    passed_products = sum(1 for row in product_summary if _clean_text(row.get("product_status")) == "active_passed")
    partial_products = sum(1 for row in product_summary if _clean_text(row.get("product_status")) == "active_partial")
    return {
        "stage8_6_product_active_passed": passed_products,
        "stage8_6_product_active_partial": partial_products,
        "stage8_6_asset_active_passed": passed_assets,
        "stage8_6_asset_audit_pending": pending_assets,
        "legacy_82_90_still_valid": passed_products == 82 and partial_products == 8,
        "legacy_1326_still_valid": passed_assets == 1326,
        "legacy_8_pending_still_valid": pending_assets == 8,
    }


def build_audit_evidence(
    *,
    git_commit: str,
    audit_end: date,
    project_root: Path,
    db_snapshot_source: str,
    db_snapshot_time: str,
    products: list[str],
    target_coverage_result: dict[str, Any],
    stage8_6_1d_result: dict[str, Any],
    jm_six_period_result: dict[str, Any],
    duplicate_active: list[dict[str, Any]],
    orphan_files: list[dict[str, Any]],
    weekly_history: list[dict[str, Any]],
    claim_verdicts: list[dict[str, Any]],
    stale_metrics: dict[str, Any],
) -> dict[str, Any]:
    coverage_matrix = target_coverage_result.get("target_coverage_matrix") or []
    coverage_counts = Counter(_matrix_status(row) for row in coverage_matrix)
    return {
        "mode": MODE,
        "audit_time": datetime.now(UTC).isoformat(),
        "git_commit": git_commit,
        "audit_end": audit_end.isoformat(),
        "data_root": str(project_root / "data"),
        "db_snapshot_source": db_snapshot_source,
        "db_snapshot_time": db_snapshot_time,
        "products": len(products),
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "coverage_status_counts": dict(coverage_counts),
        "issue_register_rows": len(target_coverage_result.get("issue_register") or []),
        "duplicate_active_rows": len(duplicate_active),
        "orphan_file_rows": len(orphan_files),
        "weekly_pre2020_missing": sum(1 for row in weekly_history if row.get("pre_2020_status") in {"missing_pre2020", "partial_or_missing_pre2020"}),
        "weekly_direct_present": sum(1 for row in weekly_history if row.get("direct_1w_present")),
        "claim_verdicts": claim_verdicts,
        "stale_metrics": stale_metrics,
        "stage8_6_1d_profile": stage8_6_1d_result.get("profile"),
        "jm_six_period_profile": jm_six_period_result.get("profile"),
    }


def render_final_audit_markdown(
    *,
    audit_end: date,
    git_commit: str,
    project_root: Path,
    evidence: dict[str, Any],
    target_coverage_result: dict[str, Any],
    stage8_6_1d_result: dict[str, Any],
    jm_six_period_result: dict[str, Any],
    claim_verdicts: list[dict[str, Any]],
    stale_metrics: dict[str, Any],
    quality_issue_register: list[dict[str, Any]],
) -> str:
    coverage_matrix = target_coverage_result.get("target_coverage_matrix") or []
    status_counts = Counter(_matrix_status(row) for row in coverage_matrix)
    warning_rows = [row for row in quality_issue_register if _clean_text(row.get("issue_type")) == "quality_warning"]

    lines = [
        "# DATA LAYER FINAL AUDIT",
        "",
        f"- audit_time: `{evidence['audit_time']}`",
        f"- git_commit: `{git_commit}`",
        f"- audit_end: `{audit_end.isoformat()}`",
        f"- data_root: `{project_root / 'data'}`",
        f"- db_snapshot_source: `{evidence['db_snapshot_source']}`",
        f"- db_snapshot_time: `{evidence['db_snapshot_time']}`",
        f"- products: `{evidence['products']}`",
        "- writes_database: `False`",
        "- writes_parquet: `False`",
        "- calls_rqdata: `False`",
        "",
        "## Coverage Status",
        "",
        "| status | count |",
        "|---|---:|",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"| {status} | {count} |")

    lines.extend(
        [
            "",
            "## Candidate Claim Verdicts",
            "",
            "| claim | verdict | detail |",
            "|---|---|---|",
        ]
    )
    for item in claim_verdicts:
        lines.append(f"| {item['statement']} | {item['verdict']} | {item.get('detail', '')} |")

    lines.extend(
        [
            "",
            "## Legacy Metric Re-check",
            "",
            f"- stage8_6 product active_passed / active_partial: `{stale_metrics['stage8_6_product_active_passed']}` / `{stale_metrics['stage8_6_product_active_partial']}`",
            f"- stage8_6 asset active_passed / audit_pending: `{stale_metrics['stage8_6_asset_active_passed']}` / `{stale_metrics['stage8_6_asset_audit_pending']}`",
            f"- legacy `82/90` still valid: `{stale_metrics['legacy_82_90_still_valid']}`",
            f"- legacy `1326` still valid: `{stale_metrics['legacy_1326_still_valid']}`",
            f"- legacy `8 pending` still valid: `{stale_metrics['legacy_8_pending_still_valid']}`",
            "",
            "## quality_warning (must not upgrade to passed)",
            "",
            f"- count: `{len(warning_rows)}`",
            "",
            "## JM Six-Period Snapshot",
            "",
        ]
    )
    jm_summary = jm_six_period_result.get("product_summary") or []
    if jm_summary:
        lines.append(f"- jm product_status: `{jm_summary[0].get('product_status', '')}`")
    else:
        lines.append("- jm product_status: `missing`")

    lines.extend(
        [
            "",
            "## Phase 1 Conclusion",
            "",
            "本报告为只读审计产物，**不代表数据层最终封板完成**。",
            "若 claim 与架构口径冲突、1w 历史覆盖不足或 crosscheck 存在差异，须进入 Phase 2 受控补齐。",
            "",
            "## Evidence Files",
            "",
            "- `audit_evidence.json`",
            "- `target_coverage_matrix.csv`",
            "- `weekly_history_audit.csv`",
            "- `duplicate_active_assets.csv`",
            "- `orphan_files.csv`",
            "- `main_contract_mapping_audit.csv`",
            "- `daily_intraday_crosscheck.csv`",
            "",
        ]
    )
    return "\n".join(lines)


def resolve_git_commit(project_root: Path) -> str:
    try:
        output = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project_root, text=True, stderr=subprocess.DEVNULL)
        return output.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _verdict_claim_1m(products: list[str], coverage_matrix: list[dict[str, Any]], *, architecture: bool) -> dict[str, str]:
    min_year = ARCHITECTURE_1M_START.year if architecture else CLAIM_1M_START.year
    rows = [
        row
        for row in coverage_matrix
        if _clean_text(row.get("period")) == "1m"
        and _clean_text(row.get("contract_role")) == "dominant_main"
        and int(row.get("year") or 0) >= min_year
        and _matrix_status(row) != "not_applicable"
    ]
    passed = sum(1 for row in rows if _matrix_status(row) == "covered_passed")
    expected = len(rows)
    if expected == 0:
        return {"verdict": "rejected", "detail": "no expected 1m rows"}
    ratio = passed / expected
    if ratio >= 0.99:
        verdict = "confirmed"
    elif ratio >= 0.5:
        verdict = "partial"
    else:
        verdict = "rejected"
    return {"verdict": verdict, "detail": f"passed={passed}/{expected} years since {min_year}"}


def _verdict_claim_1d(products: list[str], coverage_matrix: list[dict[str, Any]]) -> dict[str, str]:
    rows = [
        row
        for row in coverage_matrix
        if _clean_text(row.get("period")) == "1d"
        and _clean_text(row.get("contract_role")) == "dominant_main"
        and int(row.get("year") or 0) >= 2020
        and _matrix_status(row) != "not_applicable"
    ]
    passed = sum(1 for row in rows if _matrix_status(row) in {"covered_passed", "covered_warning"})
    expected = len(rows)
    verdict = "confirmed" if passed == expected and expected > 0 else "partial" if passed > 0 else "rejected"
    return {"verdict": verdict, "detail": f"passed_or_warning={passed}/{expected}"}


def _verdict_claim_1w_recent(products: list[str], weekly_history: list[dict[str, Any]]) -> dict[str, str]:
    ok = sum(1 for row in weekly_history if int(row.get("post_2020_passed_years") or 0) == int(row.get("post_2020_expected_years") or 0) and row.get("post_2020_expected_years"))
    return {"verdict": "confirmed" if ok == len(products) else "partial", "detail": f"products_full_post2020={ok}/{len(products)}"}


def _verdict_claim_pre2020_1w(products: list[str], weekly_history: list[dict[str, Any]]) -> dict[str, str]:
    applicable = [row for row in weekly_history if row.get("pre_2020_applicable")]
    covered = [row for row in applicable if row.get("pre_2020_status") == "covered"]
    if not applicable:
        return {"verdict": "not_applicable", "detail": "no product listed before 2020 in windows file"}
    ratio = len(covered) / len(applicable)
    verdict = "confirmed" if ratio >= 0.99 else "partial" if ratio >= 0.5 else "rejected"
    return {"verdict": verdict, "detail": f"pre2020_covered={len(covered)}/{len(applicable)}"}


def _verdict_claim_full_1w(products: list[str], weekly_history: list[dict[str, Any]], audit_end: date) -> dict[str, str]:
    present = sum(1 for row in weekly_history if row.get("direct_1w_present"))
    verdict = "confirmed" if present == len(products) else "partial" if present > 0 else "rejected"
    return {"verdict": verdict, "detail": f"direct_1w_present={present}/{len(products)}; audit_end={audit_end.isoformat()}"}


def _verdict_claim_main_and_actual(stage8_6_1d_result: dict[str, Any]) -> dict[str, str]:
    matrix = stage8_6_1d_result.get("matrix") or []
    main_rows = [row for row in matrix if _clean_text(row.get("asset_scope")) == "dominant_main"]
    actual_rows = [row for row in matrix if _clean_text(row.get("asset_scope")) == "actual_contract"]
    main_passed = sum(1 for row in main_rows if _clean_text(row.get("gate_status")) == "active_passed")
    actual_passed = sum(1 for row in actual_rows if _clean_text(row.get("gate_status")) == "active_passed")
    verdict = "partial" if main_passed > 0 else "rejected"
    return {
        "verdict": verdict,
        "detail": f"dominant_main_passed={main_passed}/{len(main_rows)}; actual_contract_passed={actual_passed}/{len(actual_rows)}",
    }


def _weekly_issue_class(pre_2020_status: str, post_passed: int, post_expected: int, direct_present: bool) -> str:
    if not direct_present:
        return "coverage_missing"
    if pre_2020_status in {"missing_pre2020", "partial_or_missing_pre2020"}:
        return "coverage_missing"
    if post_expected and post_passed < post_expected:
        return "coverage_missing"
    return "confirmed_passed"


def _collect_registered_paths(session: Session | None, project_root: Path, products: list[str]) -> set[str]:
    paths: set[str] = set()
    manifest_root = project_root / "data" / "manifests"
    for manifest in manifest_root.glob("rqdata_*.csv"):
        for row in _read_csv_records(manifest):
            path = _resolve_path(project_root, _clean_text(row.get("standard_path")))
            if path:
                paths.add(str(path.resolve()))
    if session is not None:
        for row in session.scalars(select(MarketDataFile)):
            path = _resolve_path(project_root, _clean_text(getattr(row, "file_path", "")))
            if path:
                paths.add(str(path.resolve()))
    return paths


def _load_market_files(session: Session | None) -> list[Any]:
    if session is None:
        return []
    return list(session.scalars(select(MarketDataFile)))


def _index_dominant_files(market_files: list[Any], *, period: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in market_files:
        if _clean_text(getattr(row, "data_type", "")) != "bars":
            continue
        if _clean_text(getattr(row, "period", "")) != period:
            continue
        if _clean_text(getattr(row, "data_role", "")) != "primary":
            continue
        if _clean_text(getattr(row, "quality_status", "")) == "failed":
            continue
        product = _clean_text(getattr(row, "instrument_symbol", "")).lower()
        contract = _clean_text(getattr(row, "contract_code", ""))
        if not product or not contract.endswith(".MAIN"):
            continue
        current = indexed.get(product)
        candidate = {
            "file_path": _clean_text(getattr(row, "file_path", "")),
            "row_count": getattr(row, "row_count", None),
            "data_version": _clean_text(getattr(row, "data_version", "")),
        }
        if current is None or _clean_text(candidate["data_version"]) > _clean_text(current.get("data_version", "")):
            indexed[product] = candidate
    return indexed


def _find_derived_1d_from_1m(project_root: Path, product: str) -> Path | None:
    summary_dir = project_root / "data" / "processed" / "v1b" / product
    if not summary_dir.exists():
        return None
    summaries = sorted(summary_dir.glob(f"{product}_v2_parquet_*.json"), reverse=True)
    for summary_path in summaries:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        period_summary = (payload.get("periods") or {}).get("1d") or {}
        derivation = _clean_text(period_summary.get("derivation_mode"))
        if derivation and "aggregat" in derivation.lower():
            standard = period_summary.get("standard") or {}
            path = _resolve_path(project_root, _clean_text(standard.get("path")))
            if path and path.exists():
                return path
    canonical = project_root / "data" / "parquet" / "canonical" / "bars"
    matches = sorted(canonical.glob(f"**/symbol={product}/**/{product}_MAIN_1d_*_v2.parquet"), reverse=True)
    for path in matches:
        return path
    return None


def _count_date_gaps(dates: list[date]) -> int:
    if len(dates) < 2:
        return 0
    gaps = 0
    ordered = sorted(dates)
    for previous, current in zip(ordered, ordered[1:]):
        if (current - previous).days > 5:
            gaps += 1
    return gaps


def _duckdb_summary(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"exists": False, "row_count": None, "min_datetime": "", "max_datetime": "", "error": "missing_file"}
    try:
        frame = duckdb.sql(
            """
            select
                count(*) as row_count,
                min(datetime) as min_datetime,
                max(datetime) as max_datetime
            from read_parquet(?)
            """,
            params=[str(path)],
        ).df()
        row = frame.iloc[0]
        return {
            "exists": True,
            "row_count": int(row["row_count"]) if row["row_count"] is not None else None,
            "min_datetime": str(row["min_datetime"]),
            "max_datetime": str(row["max_datetime"]),
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001
        return {"exists": True, "row_count": None, "min_datetime": "", "max_datetime": "", "error": f"{type(exc).__name__}: {exc}"}


def _read_csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return pd.read_csv(path).fillna("").to_dict("records")


def _resolve_path(project_root: Path, value: str) -> Path | None:
    text = _clean_text(value)
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = project_root / path
    return path


def _product_from_parquet_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("symbol="):
            return part.split("=", 1)[1].lower()
    name = path.name
    return name.split("_", 1)[0].lower()


def _period_from_parquet_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("period="):
            return part.split("=", 1)[1]
    match = path.stem.split("_")
    return match[2] if len(match) > 2 else ""


def _contract_from_parquet_path(path: Path) -> str:
    for part in path.parts:
        if part.startswith("contract="):
            return part.split("=", 1)[1]
    return ""


def _to_date(value: Any) -> date | None:
    text = _clean_text(value)
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")[:10]).date()


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _matrix_status(row: dict[str, Any]) -> str:
    return _clean_text(row.get("status") or row.get("coverage_status"))


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


__all__ = [
    "DEFAULT_AUDIT_END",
    "MODE",
    "build_claim_verdicts",
    "load_product_windows",
    "resolve_git_commit",
    "run_extended_final_audit",
    "write_final_audit_reports",
]
