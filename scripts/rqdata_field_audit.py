from __future__ import annotations

from pathlib import Path
import argparse
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


DATASET_RULES = {
    "futures_ex_factor": {
        "path": "futures_ex_factor",
        "required": ["ex_date", "product"],
        "any_of": [["ex_factor", "prev_close_spread"], ["ex_cum_factor", "prev_close_ratio"]],
    },
    "trading_parameters": {
        "path": "trading_parameters",
        "required": ["date", "contract", "long_margin_ratio", "short_margin_ratio", "open_commission", "close_commission", "close_commission_today"],
        "any_of": [["client_limit", "max_order_quantity", "non_member_limit"]],
    },
    "daily_baseline": {
        "path": "futures_daily_provider",
        "required": ["date", "contract", "open", "high", "low", "close", "volume", "settlement", "prev_settlement", "open_interest"],
        "any_of": [["turnover", "total_turnover"]],
    },
    "warehouse_stocks": {
        "path": "warehouse_stocks",
        "required": ["date", "product"],
        "any_of": [["quantity", "on_warrant", "volume"]],
    },
    "market_sample": {
        "path": "market_samples",
        "required": ["datetime", "product", "frequency", "open", "high", "low", "close", "volume", "open_interest"],
        "any_of": [],
    },
    "contract_universe": {
        "path": "contract_universe",
        "required": ["date", "product"],
        "any_of": [["contract", "order_book_id"]],
    },
    "continuous_contracts": {
        "path": "continuous_contracts",
        "required": ["date", "product", "continuous_type"],
        "any_of": [["contract", "order_book_id", "front_month", "next_month"]],
    },
    "dominant_daily_baseline": {
        "path": "dominant_daily_baseline",
        "required": ["date", "product", "dominant_id", "open", "high", "low", "close", "volume", "open_interest"],
        "any_of": [["limit_up", "limit_down"]],
    },
}


def _field_gaps(frame: pd.DataFrame, rule: dict[str, object]) -> tuple[list[str], list[str]]:
    columns = set(frame.columns)
    missing = [field for field in rule["required"] if field not in columns]  # type: ignore[index]
    missing_any = []
    for group in rule["any_of"]:  # type: ignore[index]
        if not any(field in columns for field in group):
            missing_any.append("|".join(group))
    return missing, missing_any


def _audit_dataset(name: str, rule: dict[str, object]) -> dict[str, object]:
    root = PROJECT_ROOT / "data/raw/rqdata" / str(rule["path"])
    files = sorted(root.rglob("*.parquet")) if root.exists() else []
    sample_path: Path | None = None
    sample_frame = pd.DataFrame()
    bad_path: Path | None = None
    bad_missing: list[str] = []
    bad_missing_any: list[str] = []
    non_empty_files = 0
    good_files = 0
    bad_files = 0
    empty_files = 0
    for path in files:
        frame = pd.read_parquet(path)
        if frame.empty:
            empty_files += 1
            sample_path = sample_path or path
            sample_frame = sample_frame if not sample_frame.empty else frame
            continue
        non_empty_files += 1
        missing, missing_any = _field_gaps(frame, rule)
        if missing or missing_any:
            bad_files += 1
            if bad_path is None:
                bad_path = path
                bad_missing = missing
                bad_missing_any = missing_any
                sample_path = path
                sample_frame = frame
        else:
            good_files += 1
            if sample_path is None or sample_frame.empty:
                sample_path = path
                sample_frame = frame

    if not files:
        status = "missing_raw"
    elif non_empty_files == 0:
        status = "empty_raw"
    elif bad_files and good_files:
        status = "partial_bad_raw"
    elif bad_files:
        status = "needs_rerun"
    else:
        status = "ok"
    return {
        "dataset": name,
        "status": status,
        "files": len(files),
        "non_empty_files": non_empty_files,
        "good_files": good_files,
        "bad_files": bad_files,
        "empty_files": empty_files,
        "sample_file": "" if sample_path is None else str(sample_path.relative_to(PROJECT_ROOT)),
        "bad_sample_file": "" if bad_path is None else str(bad_path.relative_to(PROJECT_ROOT)),
        "sample_rows": len(sample_frame),
        "columns": ",".join(sample_frame.columns),
        "missing_required": ",".join(bad_missing),
        "missing_any_of": ",".join(bad_missing_any),
    }


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for record in frame.astype(str).to_dict("records"):
        lines.append("| " + " | ".join(record[column].replace("|", "\\|") for column in columns) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit RQData raw Parquet fields")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--table", dest="dataset")
    args = parser.parse_args()

    rules = DATASET_RULES
    if args.dataset:
        rules = {args.dataset: DATASET_RULES[args.dataset]}
    rows = [_audit_dataset(name, rule) for name, rule in rules.items()]
    reports = PROJECT_ROOT / "data/reports"
    reports.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    csv_path = reports / "rqdata_field_audit.csv"
    md_path = reports / "rqdata_field_audit.md"
    frame.to_csv(csv_path, index=False)
    md_path.write_text("# RQData Field Audit\n\n" + _markdown_table(frame) + "\n", encoding="utf-8")
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    print(frame[["dataset", "status", "missing_required", "missing_any_of"]].to_string(index=False))


if __name__ == "__main__":
    main()
