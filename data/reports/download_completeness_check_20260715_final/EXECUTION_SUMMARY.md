# Download Completeness Summary — 2026-07-15

## Scope / policy
- Audit end: `2026-07-10`
- Earliest start: **1d/1w = max(listed, 2000-01-04)**; **1m = max(listed, 2010-01-04)**

## Today finished
1. Remaining 4: `wr,y,zc,zn` roll **1m** — 4/4 done, 0 fail (~70 MB)
2. Retry yesterday Quota-interrupted **39** roll **1m** products — 39/39 done (~404 MB)
3. Re-audited inventory (+ physical parquet cross-check)

Traffic left after today: ~550 MB

## MAIN (dominant) — COMPLETE under RQ earliest floor

| Period | Covered |
|--------|---------|
| 1d | **90/90** |
| 1w | **90/90** |
| 1m | **90/90** |

## ROLL — physical disk coverage (filename window)

| Period | All RQ-floor | From 2010-01-04 | Notes |
|--------|--------------|-----------------|-------|
| 1d | 90.5% | **99.3%** | Pre-2010 still missing (download window was 2010+) |
| 1w | 90.3% | **98.2%** | Short legs / no weekly bars on some segments |
| 1m | **99.9%** | **99.9%** | Only `tf` has a few quality-failed segments |

## DB inventory vs physical
DB `primary` registry lags disk for some roll files (e.g. palm `p` 1m exists on disk but inventory still lists gaps). Prefer **physical** numbers for completeness.

## Verdict
- **主连：完整**（米筐有效最早起点）
- **Roll 1m：基本完整（99.9%）**
- **Roll 1d/1w：2010 后基本完整（≥98%）；2000–2009 日/周 roll 未在本次窗口下载**
- **不完全 100%**：极少数质量失败段（如 `tf` 1m）+ 短主力周线段无 RQData 数据 + 2010 前 1d/1w roll

## Optional next (if want full 2000 floor for roll 1d)
```bash
PRODUCTS_FILE=data/universe/full_products_90.txt \
PERIODS=1d START_DATE=2000-01-04 END_DATE=2009-12-31 \
LOG_DIR=data/reports/roll_1d_pre2010_incremental \
./scripts/rqdata_roll_incremental.sh
```
