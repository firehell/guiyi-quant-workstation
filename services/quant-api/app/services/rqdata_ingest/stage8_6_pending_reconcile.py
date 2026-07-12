from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

DISPOSITIONS = (
    "accepted_warning",
    "metadata_mismatch",
    "registration_not_needed",
    "requires_apply_gate",
    "blocked_needs_manual_review",
)

WARNING_PRODUCTS = frozenset({"bb", "rs", "wh", "wr", "zc"})
LPV_MISPARSED_PRODUCTS = frozenset({"l", "pp", "v"})
LPV_CANONICAL_PRODUCTS = {"l": "l_f", "pp": "pp_f", "v": "v_f"}


def reconcile_stage8_6_pending(
    *,
    matrix_file: Path,
    lpv_reconcile_summary: Path | None = None,
) -> dict[str, Any]:
    matrix_file = matrix_file.resolve()
    frame = pd.read_csv(matrix_file)
    pending = frame[frame["gate_status"].astype(str) == "audit_pending"].copy()
    if len(pending) != 8:
        raise ValueError(f"expected 8 audit_pending rows, got {len(pending)} in {matrix_file}")

    all_rows = {(_clean(row["product"]), _clean(row["contract"]), _clean(row["period"])): row for _, row in frame.iterrows()}
    lpv_eligible = _lpv_eligible_count(lpv_reconcile_summary)
    ledger: list[dict[str, Any]] = []
    for _, row in pending.iterrows():
        ledger.append(_classify_pending_row(row, all_rows=all_rows, lpv_eligible=lpv_eligible))

    disposition_counts = Counter(item["disposition"] for item in ledger)
    return {
        "mode": "stage8_6_pending_reconcile_dry_run",
        "matrix_file": str(matrix_file),
        "pending_count": len(ledger),
        "disposition_counts": {name: disposition_counts.get(name, 0) for name in DISPOSITIONS},
        "requires_apply_gate_count": disposition_counts.get("requires_apply_gate", 0),
        "writes_database": False,
        "writes_parquet": False,
        "calls_rqdata": False,
        "ledger": ledger,
    }


def write_stage8_6_pending_reconcile_reports(result: dict[str, Any], *, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "stage8_6_pending_reconcile_ledger.csv"
    summary_path = output_dir / "STAGE8_6_PENDING_RECONCILE.md"
    pd.DataFrame(result["ledger"]).to_csv(ledger_path, index=False, lineterminator="\n")
    summary_path.write_text(_render_summary(result), encoding="utf-8")
    return {"ledger": ledger_path, "summary": summary_path}


def _classify_pending_row(
    row: pd.Series,
    *,
    all_rows: dict[tuple[str, str, str], pd.Series],
    lpv_eligible: int,
) -> dict[str, Any]:
    product = _clean(row["product"])
    contract = _clean(row["contract"])
    period = _clean(row["period"])
    blocked_reasons = _clean(row.get("blocked_reasons"))
    gate_status = _clean(row.get("gate_status"))
    db_quality = _clean(row.get("db_quality_status"))
    manifest_quality = _clean(row.get("manifest_quality_status"))

    disposition = "blocked_needs_manual_review"
    rationale = "unclassified pending row"

    if product in WARNING_PRODUCTS and "quality_report_abnormal_price" in blocked_reasons:
        disposition = "accepted_warning"
        rationale = "dominant_main 1d quality warning / abnormal price; keep warning, do not upgrade to passed"
    elif product in LPV_MISPARSED_PRODUCTS:
        canonical = LPV_CANONICAL_PRODUCTS[product]
        sibling = all_rows.get((canonical, contract, period))
        if sibling is not None and _clean(sibling.get("gate_status")) == "active_passed":
            disposition = "registration_not_needed"
            rationale = (
                f"Stage 8.6 snapshot uses product={product} but canonical product={canonical} "
                f"already active_passed with DB registration; LPV dry-run eligible={lpv_eligible}"
            )
        elif sibling is not None:
            disposition = "metadata_mismatch"
            rationale = f"snapshot product={product} mismatches canonical sibling product={canonical}"
        else:
            disposition = "metadata_mismatch"
            rationale = f"missing canonical sibling row for product={canonical}"
    elif "missing_market_data_file" in blocked_reasons and db_quality == "passed":
        disposition = "metadata_mismatch"
        rationale = "manifest/db evidence exists but snapshot flags missing_market_data_file on mis-parsed product key"

    return {
        "product": product,
        "asset_scope": _clean(row.get("asset_scope")),
        "contract": contract,
        "period": period,
        "gate_status": gate_status,
        "blocked_reasons": blocked_reasons,
        "manifest_quality_status": manifest_quality,
        "db_quality_status": db_quality,
        "standard_path": _clean(row.get("standard_path")),
        "disposition": disposition,
        "rationale": rationale,
    }


def _lpv_eligible_count(summary_file: Path | None) -> int:
    if summary_file is None or not summary_file.exists():
        return 0
    text = summary_file.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "eligible_for_registration" in line.lower():
            digits = "".join(ch for ch in line if ch.isdigit())
            if digits:
                return int(digits)
    return 0


def _render_summary(result: dict[str, Any]) -> str:
    lines = [
        "# Stage 8.6 Pending Reconcile",
        "",
        f"- matrix_file: `{result['matrix_file']}`",
        f"- pending_count: {result['pending_count']}",
        f"- writes_database: {result['writes_database']}",
        f"- writes_parquet: {result['writes_parquet']}",
        f"- calls_rqdata: {result['calls_rqdata']}",
        "",
        "## Disposition Counts",
        "",
    ]
    for name, count in result["disposition_counts"].items():
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Ledger", ""])
    for item in result["ledger"]:
        lines.append(
            f"- `{item['product']}/{item['contract']}/{item['period']}` -> "
            f"`{item['disposition']}`: {item['rationale']}"
        )
    lines.append("")
    return "\n".join(lines)


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()
