from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.data_center import FuturesContinuousContractMap, FuturesContractUniverse


CLASSIFICATIONS = (
    "needs_contract_universe_sync",
    "needs_continuous_contract_sync",
    "partial_year_rows",
    "not_applicable_review",
)
SUPPORTED_DATASETS = {"contract_universe", "continuous_contract_map"}


def reconcile_reference_metadata_gaps(
    *,
    session: Session,
    project_root: Path,
    metadata_matrix: Path,
    audit_end: date = date(2026, 7, 10),
) -> dict[str, Any]:
    project_root = project_root.resolve()
    matrix_path = _resolve_path(project_root, metadata_matrix)
    rows = [
        row
        for row in _read_records(matrix_path)
        if _clean(row.get("status")) == "metadata_gap" and _clean(row.get("dataset")) in SUPPORTED_DATASETS
    ]
    output_rows = [_classify_row(session=session, row=row, audit_end=audit_end) for row in rows]
    classifications = Counter(row["classification"] for row in output_rows)
    return {
        "mode": "reference_metadata_gap_reconcile",
        "metadata_matrix": str(matrix_path),
        "input_gap_rows": len(rows),
        "classification_counts": {name: classifications.get(name, 0) for name in CLASSIFICATIONS},
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "ledger": output_rows,
    }


def write_reference_metadata_gap_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "reference_metadata_gap_ledger.csv"
    commands_path = output_dir / "reference_metadata_sync_commands.csv"
    summary_path = output_dir / "REFERENCE_METADATA_GAP_RECONCILE.md"
    ledger = pd.DataFrame(result["ledger"])
    ledger.to_csv(ledger_path, index=False, lineterminator="\n")
    command_rows = _command_rows(result["ledger"])
    pd.DataFrame(command_rows).to_csv(commands_path, index=False, lineterminator="\n")
    summary_path.write_text(_render_summary(result, command_rows), encoding="utf-8")
    return {"ledger": ledger_path, "commands": commands_path, "summary": summary_path}


def _classify_row(*, session: Session, row: dict[str, Any], audit_end: date) -> dict[str, Any]:
    product = _clean(row.get("product")).lower()
    dataset = _clean(row.get("dataset"))
    year = int(_clean(row.get("year")))
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), audit_end)
    if start > end:
        classification = "not_applicable_review"
        count = 0
        min_date = max_date = None
    elif dataset == "contract_universe":
        count, min_date, max_date = _bounds(
            session,
            FuturesContractUniverse,
            product=product,
            year_start=start,
            year_end=end,
        )
        classification = "needs_contract_universe_sync" if count == 0 else "partial_year_rows"
    elif dataset == "continuous_contract_map":
        count, min_date, max_date = _bounds(
            session,
            FuturesContinuousContractMap,
            product=product,
            year_start=start,
            year_end=end,
        )
        classification = "needs_continuous_contract_sync" if count == 0 else "partial_year_rows"
    else:
        classification = "not_applicable_review"
        count = 0
        min_date = max_date = None
    return {
        "classification": classification,
        "product": product,
        "year": year,
        "dataset": dataset,
        "issue_type": _clean(row.get("issue_type")),
        "db_row_count_for_year": count,
        "db_min_trade_date": min_date.isoformat() if min_date else "",
        "db_max_trade_date": max_date.isoformat() if max_date else "",
        "candidate_start_date": start.isoformat(),
        "candidate_end_date": end.isoformat() if start <= end else "",
        "suggested_command": _suggested_command(product, dataset, start, end) if start <= end else "",
        "recommended_action": "metadata_only_sync_requires_human_gate",
    }


def _bounds(
    session: Session,
    model: type[FuturesContractUniverse] | type[FuturesContinuousContractMap],
    *,
    product: str,
    year_start: date,
    year_end: date,
) -> tuple[int, date | None, date | None]:
    row = session.execute(
        select(func.count(model.id), func.min(model.trade_date), func.max(model.trade_date)).where(
            func.lower(model.instrument_symbol) == product,
            model.provider == "rqdata",
            model.trade_date >= year_start,
            model.trade_date <= year_end,
        )
    ).one()
    return int(row[0] or 0), row[1], row[2]


def _command_rows(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in ledger:
        if not row["suggested_command"]:
            continue
        grouped.setdefault((row["dataset"], row["classification"]), []).append(row)
    commands = []
    for (dataset, classification), rows in sorted(grouped.items()):
        products = ",".join(sorted({row["product"] for row in rows}))
        commands.append(
            {
                "dataset": dataset,
                "classification": classification,
                "row_count": len(rows),
                "products": products,
                "human_gate": "required_before_rqdata_or_db_write",
                "example_command": rows[0]["suggested_command"],
            }
        )
    return commands


def _suggested_command(product: str, dataset: str, start: date, end: date) -> str:
    if dataset == "contract_universe":
        return (
            "uv run --env-file /Volumes/扩展盘/guiyi-quant-workstation/.env --project services/quant-api "
            f"python scripts/rqdata_contract_universe_sync.py run --product {product} "
            f"--start-date {start.isoformat()} --end-date {end.isoformat()}"
        )
    return (
        "uv run --env-file /Volumes/扩展盘/guiyi-quant-workstation/.env --project services/quant-api "
        f"python scripts/rqdata_continuous_contracts_sync.py run --product {product} "
        f"--start-date {start.isoformat()} --end-date {end.isoformat()}"
    )


def _render_summary(result: dict[str, Any], command_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Reference Metadata Gap Reconcile",
        "",
        "## Result",
        "",
        f"- input_gap_rows: {result['input_gap_rows']}",
        *(f"- {name}: {result['classification_counts'][name]}" for name in CLASSIFICATIONS),
        f"- command_groups: {len(command_rows)}",
        "",
        "## Safety Boundary",
        "",
        "- writes_database=False",
        "- writes_parquet=False",
        "- writes_manifest=False",
        "- calls_rqdata=False",
        "- Suggested sync commands are not authorization to run them.",
    ]
    return "\n".join(lines) + "\n"


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, dtype=str).fillna("").to_dict("records")


def _resolve_path(project_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (project_root / path).resolve()


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()
