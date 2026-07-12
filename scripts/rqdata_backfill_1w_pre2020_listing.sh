#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UV=(uv run --project services/quant-api python)
PRODUCTS_FILE="${PRODUCTS_FILE:-data/universe/products_pre2020_listed_63.txt}"
STARTS_FILE="${STARTS_FILE:-data/universe/product_1w_start_from_listing.csv}"
GAP_END_DATE="${GAP_END_DATE:-2020-01-02}"
GLOBAL_END="${GLOBAL_END:-2026-07-10}"
TRADE_DATE="${TRADE_DATE:-2026-07-10}"
LAYER="${LAYER:-all}"
PERIODS="${PERIODS:-1w}"
REPORT_PATH="${REPORT_PATH:-data/reports/backfill_1w_pre2020_listing_report.csv}"
PROGRESS_PATH="${PROGRESS_PATH:-data/reports/backfill_1w_pre2020_listing_progress.md}"
FAILURES_PATH="${FAILURES_PATH:-data/reports/backfill_1w_pre2020_listing_failures.csv}"

BACKFILL_EXTRA_ARGS=()
if [[ "${ALLOW_QUALITY_FAILED:-0}" == "1" ]]; then
  BACKFILL_EXTRA_ARGS+=(--allow-quality-failed)
fi

_get_product_start() {
  local p="$1"
  "${UV[@]}" - "$STARTS_FILE" "$p" <<'PY'
import sys
import pandas as pd

starts_file, product = sys.argv[1], sys.argv[2].strip().lower()
df = pd.read_csv(starts_file)
row = df[df["product"].str.lower() == product]
if row.empty:
    raise SystemExit(f"product not found in starts file: {product}")
print(row.iloc[0]["effective_1d_start"])
PY
}

run_layer0_product() {
  local p="$1"
  local start_date
  start_date="$(_get_product_start "$p")"
  echo "=== layer0 trading_params: $p ($start_date..$GAP_END_DATE) ==="
  "${UV[@]}" scripts/rqdata_trading_params_sync.py run \
    --product "$p" --start-date "$start_date" --end-date "$GAP_END_DATE" \
    || echo "WARN layer0 trading_params failed: $p"
}

run_layer1() {
  echo "=== layer1 dominant MAIN 1w prepend ==="
  "${UV[@]}" scripts/rqdata_dominant_v2_backfill.py \
    --products-file "$PRODUCTS_FILE" \
    --starts-file "$STARTS_FILE" \
    --periods "$PERIODS" \
    --global-end "$GLOBAL_END" \
    --report-path "$REPORT_PATH" \
    --run-write --register "${BACKFILL_EXTRA_ARGS[@]}" \
    || echo "WARN layer1 backfill completed with failures"
}

run_layer2_product() {
  local p="$1"
  local start_date
  start_date="$(_get_product_start "$p")"
  echo "=== layer2 actual_contract roll 1w: $p ($start_date..$GAP_END_DATE) ==="
  "${UV[@]}" scripts/rqdata_actual_contract_bars_pilot.py \
    --product "$p" \
    --trade-date "$TRADE_DATE" \
    --start-date "$start_date" \
    --end-date "$GAP_END_DATE" \
    --periods "$PERIODS" \
    --roll-segments --run-write \
    || echo "WARN layer2 actual_contract failed: $p"
}

run_layer2_batch() {
  while IFS= read -r p; do
    [[ -z "$p" || "$p" =~ ^# ]] && continue
    run_layer2_product "$p"
  done < "$PRODUCTS_FILE"
}

run_dry_run() {
  echo "=== dry-run dominant MAIN 1w prepend (63 products) ==="
  "${UV[@]}" scripts/rqdata_dominant_v2_backfill.py \
    --products-file "$PRODUCTS_FILE" \
    --starts-file "$STARTS_FILE" \
    --periods "$PERIODS" \
    --global-end "$GLOBAL_END" \
    --report-path "$REPORT_PATH" \
    --dry-run
  echo "=== verify dry-run gap_end ~= $GAP_END_DATE ==="
  "${UV[@]}" - "$REPORT_PATH" "$GAP_END_DATE" <<'PY'
import sys
from datetime import date
from pathlib import Path

import pandas as pd

report_path = Path(sys.argv[1])
gap_end_target = date.fromisoformat(sys.argv[2])
if not report_path.exists():
    raise SystemExit(f"report missing: {report_path}")

df = pd.read_csv(report_path)
if df.empty:
    raise SystemExit("dry-run report is empty")

bad = []
for _, row in df.iterrows():
    gap_end_raw = row.get("gap_end")
    if pd.isna(gap_end_raw):
        bad.append((row.get("product"), row.get("period"), "missing gap_end"))
        continue
    gap_end = date.fromisoformat(str(gap_end_raw)[:10])
    if abs((gap_end - gap_end_target).days) > 7:
        bad.append((row.get("product"), row.get("period"), gap_end.isoformat()))

if bad:
    print("WARN dry-run gap_end mismatches:")
    for item in bad[:20]:
        print(" ", item)
    if len(bad) > 20:
        print(f"  ... and {len(bad) - 20} more")
    raise SystemExit(1)

print(f"ok dry-run {len(df)} rows gap_end ~= {gap_end_target}")
PY
}

run_audit() {
  echo "=== final audit: MAIN 1w + actual roll pre-2020 ==="
  "${UV[@]}" - \
    "$PRODUCTS_FILE" \
    "$STARTS_FILE" \
    "$REPORT_PATH" \
    "$PROGRESS_PATH" \
    "$FAILURES_PATH" \
    "$GAP_END_DATE" \
    <<'PY'
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
import sys

import pandas as pd

products_file = Path(sys.argv[1])
starts_file = Path(sys.argv[2])
report_path = Path(sys.argv[3])
progress_path = Path(sys.argv[4])
failures_path = Path(sys.argv[5])
gap_end_target = date.fromisoformat(sys.argv[6])

products = [
    line.strip().lower()
    for line in products_file.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#")
]
meta = pd.read_csv(starts_file)
meta["product"] = meta["product"].str.lower()
meta = meta.set_index("product")

canonical_root = Path("data/parquet/canonical/bars/provider=rqdata/period=1w")
main_rows: list[dict] = []
actual_rows: list[dict] = []
failures: list[dict] = []

for product in products:
    listed = date.fromisoformat(str(meta.loc[product, "effective_1d_start"])[:10])
    main_glob = list(canonical_root.glob(f"exchange=*/symbol={product}/contract={product}.MAIN/*.parquet"))
    main_mins: list[date] = []
    main_maxs: list[date] = []
    for path in main_glob:
        try:
            df = pd.read_parquet(path, columns=["datetime"])
        except Exception:
            continue
        if df.empty:
            continue
        dt = pd.to_datetime(df["datetime"])
        main_mins.append(dt.min().date())
        main_maxs.append(dt.max().date())
    main_min = min(main_mins) if main_mins else None
    main_max = max(main_maxs) if main_maxs else None
    main_ok = (
        main_min is not None
        and main_max is not None
        and main_min <= listed + timedelta(days=14)
        and main_max >= date(2026, 7, 10)
    )
    main_rows.append(
        {
            "product": product,
            "listed_date": listed.isoformat(),
            "main_min": main_min.isoformat() if main_min else "",
            "main_max": main_max.isoformat() if main_max else "",
            "main_ok": main_ok,
        }
    )
    if not main_ok:
        failures.append(
            {
                "product": product,
                "layer": "main_1w",
                "reason": "coverage_check_failed",
                "listed_date": listed.isoformat(),
                "main_min": main_min.isoformat() if main_min else "",
                "main_max": main_max.isoformat() if main_max else "",
            }
        )

    actual_glob = list(canonical_root.glob(f"exchange=*/symbol={product}/contract!=*.MAIN/*.parquet"))
    seg_mins: list[date] = []
    seg_count = 0
    for path in actual_glob:
        name = path.name
        if not name.endswith(".parquet"):
            continue
        seg_count += 1
        try:
            df = pd.read_parquet(path, columns=["datetime"])
        except Exception:
            continue
        if df.empty:
            continue
        seg_mins.append(pd.to_datetime(df["datetime"]).min().date())
    pre2020 = any(item < date(2020, 1, 3) for item in seg_mins)
    actual_ok = pre2020 and seg_count > 0
    actual_rows.append(
        {
            "product": product,
            "segment_files": seg_count,
            "pre2020_segments": sum(1 for item in seg_mins if item < date(2020, 1, 3)),
            "earliest_segment_min": min(seg_mins).isoformat() if seg_mins else "",
            "actual_ok": actual_ok,
        }
    )
    if not actual_ok:
        failures.append(
            {
                "product": product,
                "layer": "actual_1w_roll",
                "reason": "no_pre2020_segment",
                "segment_files": seg_count,
            }
        )

main_ok_count = sum(1 for row in main_rows if row["main_ok"])
actual_ok_count = sum(1 for row in actual_rows if row["actual_ok"])

if report_path.exists():
    report_df = pd.read_csv(report_path)
else:
    report_df = pd.DataFrame()

lines = [
    "# 1w 上市日前缀补齐进度",
    "",
    f"- 品种数: {len(products)}",
    f"- 主连 1w 覆盖: {main_ok_count}/{len(products)}",
    f"- 真实主力 1w pre-2020: {actual_ok_count}/{len(products)}",
    f"- gap_end 目标: {gap_end_target.isoformat()}",
    f"- backfill 报告: `{report_path}`",
    "",
]
if not report_df.empty and "gap_end" in report_df.columns:
  wrong_gap = []
  for _, row in report_df.iterrows():
      raw = row.get("gap_end")
      if pd.isna(raw):
          continue
      gap_end = date.fromisoformat(str(raw)[:10])
      if abs((gap_end - gap_end_target).days) > 7:
          wrong_gap.append((row.get("product"), gap_end.isoformat()))
  lines.append(f"- dry-run/plan gap_end 异常: {len(wrong_gap)}")
  lines.append("")

lines.extend(
    [
        "## 主连 1w",
        "",
        "| product | listed | min | max | ok |",
        "| --- | --- | --- | --- | --- |",
    ]
)
for row in main_rows:
    lines.append(
        f"| {row['product']} | {row['listed_date']} | {row['main_min']} | {row['main_max']} | {row['main_ok']} |"
    )
lines.extend(
    [
        "",
        "## 真实主力 1w",
        "",
        "| product | files | pre2020 | earliest | ok |",
        "| --- | --- | --- | --- | --- |",
    ]
)
for row in actual_rows:
    lines.append(
        f"| {row['product']} | {row['segment_files']} | {row['pre2020_segments']} | {row['earliest_segment_min']} | {row['actual_ok']} |"
    )

progress_path.parent.mkdir(parents=True, exist_ok=True)
progress_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

if failures:
    pd.DataFrame(failures).to_csv(failures_path, index=False)
else:
    failures_path.write_text("product,layer,reason\n", encoding="utf-8")

print(f"audit main_ok={main_ok_count}/{len(products)} actual_ok={actual_ok_count}/{len(products)}")
print(f"progress={progress_path}")
print(f"failures={failures_path} count={len(failures)}")
if main_ok_count < len(products) or actual_ok_count < len(products):
    raise SystemExit(1)
PY
}

case "$LAYER" in
  dry-run)
    run_dry_run
    ;;
  layer0)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer0_product "$p"
    done < "$PRODUCTS_FILE"
    ;;
  layer1)
    run_layer1
    ;;
  layer2)
    run_layer2_batch
    ;;
  audit)
    run_audit
    ;;
  all)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer0_product "$p"
    done < "$PRODUCTS_FILE"
    run_layer1
    run_layer2_batch
    run_audit
    ;;
  *)
    echo "Unknown LAYER=$LAYER (dry-run|layer0|layer1|layer2|audit|all)" >&2
    exit 1
    ;;
esac

echo "done layer=$LAYER report=$REPORT_PATH progress=$PROGRESS_PATH"
