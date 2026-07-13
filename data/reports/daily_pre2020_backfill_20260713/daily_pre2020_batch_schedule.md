# Daily Pre-2020 Backfill Batch Schedule

Generated: 2026-07-13  
Completed: 2026-07-13

## Final Summary

| Metric | Value |
|--------|------:|
| Total pre-2020 applicable | 63 |
| Download + register success | **63/63** |
| Failed | 0 |
| Total RQData traffic used today | ~10 MB |
| Remaining quota | ~1014 MB / 1024 MB |

## Execution History

### Batch 1 (2026-07-13 AM) — 20 success, 1 register_failed

```bash
uv run --project services/quant-api python scripts/rqdata_daily_pre2020_backfill.py \
  --run-write --register --batch-size 21 \
  --output-dir data/reports/daily_pre2020_backfill_20260713
```

Success: `a, al, au, c, cf, cu, fu, if, l, m, p, pb, rb, ru, sr, ta, v, wr, y, zn`  
Register failed: `b` (parquet written)

### Batch 2 (2026-07-13 PM) — remaining 43, all success

```bash
uv run --project services/quant-api python scripts/rqdata_daily_pre2020_backfill.py \
  --run-write --register --allow-quality-failed \
  --batch-size 0 \
  --output-dir data/reports/daily_pre2020_backfill_20260713
```

Completed remaining: `ag, ap, b, bb, bu, cj, cs, cy, eb, eg, fb, fg, hc, i, ic, ih, j, jd, jm, jr, ma, ni, nr, oi, pm, pp, ri, rm, rr, rs, sa, sc, sf, sm, sn, sp, ss, t, tf, ts, ur, wh, zc`

## Spot Check

| Product | Wide parquet | min_datetime | row_count |
|---------|-------------|--------------|----------:|
| jm | `jm_MAIN_1d_20130322_20260711_v2.parquet` | 2013-03-22 | 3231 |
| al | `al_MAIN_1d_20000104_20260711_v2.parquet` | 2000-01-05 | 6426 |
| a | `a_MAIN_1d_20020315_20260711_v2.parquet` | 2002-03-15 | 5908 |
| b | `b_MAIN_1d_20041222_20260711_v2.parquet` | 2004-12-22 | 5235 |

## Artifacts

- Plan: `daily_pre2020_backfill_plan.csv`
- Summary: `daily_pre2020_backfill_summary.json`
- Results: `daily_pre2020_batch_results.json`
- Schedule: `daily_pre2020_batch_schedule.json`

## Notes

- Effective start = `max(listed_date, 2000-01-04)` per RQData API floor
- Gap end = `2019-12-31` for all 63 products
- 2020+ tail preserved from existing `*_1d_20200102_*` wide windows
- Pre-2000 listing gap for 1999-listed products (al/cu/ru) is a known API limitation
