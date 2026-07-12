from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


MODE = "reference_metadata_gap_apply_plan"
APPLY_CLASSIFICATIONS = {
    "needs_contract_universe_sync",
    "needs_continuous_contract_sync",
}
DATASET_ORDER = {
    "contract_universe": 1,
    "continuous_contract_map": 2,
}
DATASET_TABLES = {
    "contract_universe": "futures_contract_universe",
    "continuous_contract_map": "futures_continuous_contract_map",
}


def build_reference_metadata_gap_apply_plan(
    *,
    project_root: Path,
    gap_ledger: Path,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    ledger_path = _resolve_path(project_root, gap_ledger)
    rows = [
        row
        for row in _read_records(ledger_path)
        if _clean(row.get("classification")) in APPLY_CLASSIFICATIONS
    ]
    candidate_rows = [_candidate_row(row) for row in rows]
    batches = _build_batches(candidate_rows)
    counts = Counter(row["classification"] for row in candidate_rows)
    return {
        "mode": MODE,
        "gap_ledger": str(ledger_path),
        "candidate_row_count": len(candidate_rows),
        "batch_count": len(batches),
        "classification_counts": dict(sorted(counts.items())),
        "writes_database": False,
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "requires_human_gate_before_apply": True,
        "allowed_apply_tables": sorted(set(DATASET_TABLES.values())),
        "candidate_rows": candidate_rows,
        "batches": batches,
    }


def write_reference_metadata_gap_apply_plan(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = output_dir / "apply_candidate_rows.csv"
    batches_path = output_dir / "apply_batches.csv"
    summary_path = output_dir / "REFERENCE_METADATA_GAP_APPLY_PLAN.md"
    pd.DataFrame(result["candidate_rows"]).to_csv(candidates_path, index=False, lineterminator="\n")
    pd.DataFrame(result["batches"]).to_csv(batches_path, index=False, lineterminator="\n")
    summary_path.write_text(_render_summary(result), encoding="utf-8")
    return {"candidates": candidates_path, "batches": batches_path, "summary": summary_path}


def _candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    dataset = _clean(row.get("dataset"))
    product = _clean(row.get("product")).lower()
    year = int(_clean(row.get("year")))
    start = _clean(row.get("candidate_start_date")) or f"{year}-01-01"
    end = _clean(row.get("candidate_end_date")) or f"{year}-12-31"
    classification = _clean(row.get("classification"))
    script = "scripts/rqdata_contract_universe_sync.py" if dataset == "contract_universe" else "scripts/rqdata_continuous_contracts_sync.py"
    command = (
        "uv run --env-file /Volumes/扩展盘/guiyi-quant-workstation/.env --project services/quant-api "
        f"python {script} run --product {product} --start-date {start} --end-date {end}"
    )
    return {
        "classification": classification,
        "dataset": dataset,
        "target_table": DATASET_TABLES.get(dataset, ""),
        "product": product,
        "year": year,
        "candidate_start_date": start,
        "candidate_end_date": end,
        "db_row_count_for_year": _clean(row.get("db_row_count_for_year")),
        "apply_unit": "product_year",
        "apply_order": DATASET_ORDER.get(dataset, 99) * 10000 + year,
        "dry_run_command": f"{command} --dry-run",
        "apply_command": command,
        "human_gate": "required_before_rqdata_or_db_write",
    }


def _build_batches(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in candidate_rows:
        grouped.setdefault((row["dataset"], int(row["year"])), []).append(row)
    batches = []
    for index, ((dataset, year), rows) in enumerate(
        sorted(grouped.items(), key=lambda item: (DATASET_ORDER.get(item[0][0], 99), item[0][1])),
        start=1,
    ):
        products = sorted({row["product"] for row in rows})
        start = min(row["candidate_start_date"] for row in rows)
        end = max(row["candidate_end_date"] for row in rows)
        batches.append(
            {
                "batch_id": f"batch_{index:02d}_{dataset}_{year}",
                "apply_order": index,
                "dataset": dataset,
                "target_table": DATASET_TABLES.get(dataset, ""),
                "year": year,
                "candidate_rows": len(rows),
                "product_count": len(products),
                "candidate_start_date": start,
                "candidate_end_date": end,
                "products": "|".join(products),
                "execution_mode": "one_product_year_command_per_candidate",
                "writes_database_if_approved": True,
                "calls_rqdata_if_approved": True,
                "writes_parquet_if_approved": False,
                "writes_market_data_files_if_approved": False,
                "writes_quality_status_if_approved": False,
                "human_gate": "required_before_apply",
            }
        )
    return batches


def _render_summary(result: dict[str, Any]) -> str:
    counts = result["classification_counts"]
    lines = [
        "# Reference Metadata Gap Apply Plan",
        "",
        "## Result",
        "",
        f"- candidate_rows: {result['candidate_row_count']}",
        f"- batch_count: {result['batch_count']}",
        *(f"- {name}: {counts[name]}" for name in sorted(counts)),
        "",
        "## Safety Boundary",
        "",
        "- writes_database=False",
        "- writes_parquet=False",
        "- writes_manifest=False",
        "- calls_rqdata=False",
        "- This is an apply plan only. It does not run generated commands.",
        "- Human approval is required before any RQData call or PostgreSQL metadata write.",
        "",
        "## Allowed Future Apply Scope",
        "",
        "- May write only `futures_contract_universe` and `futures_continuous_contract_map` plus related task/manifest metadata after approval.",
        "- Must not write K-line Parquet, `market_data_files`, `data_quality_reports`, quality status, strategy, signal, live runtime, or trading logic.",
        "",
        "## Batch Strategy",
        "",
        "- Run `contract_universe` years first, oldest to newest.",
        "- Then run `continuous_contract_map` years, oldest to newest.",
        "- Execute one product-year command at a time, with per-command logging and rerunnable manifests.",
        "- After each dataset or year batch, rerun reference metadata gap reconcile and target coverage audit.",
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
