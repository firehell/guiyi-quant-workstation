# Minute Pre-2020 Backfill Batch Schedule

Generated: 2026-07-13  
Last updated: 2026-07-13  
**Status: COMPLETE 63/63**

## Final Summary

| Metric | Value |
|--------|------:|
| Total pre-2020 applicable | 63 |
| Download + register success | **63/63** |
| Failed | 0 |
| Day 1 (800 MB budget) | 20 success |
| Day 2 (955 MB budget + remainder) | 43 success |
| Total estimated traffic | ~8489 MB |

## Execution History

### Day 1 (2026-07-13 AM) — 20/20 success (~787 MB)

```bash
uv run --project services/quant-api python scripts/rqdata_1m_pre2020_backfill.py \
  --run-write --register --allow-quality-failed \
  --traffic-budget-mb 800 \
  --output-dir data/reports/minute_pre2020_backfill_20260713
```

Success: `ap, cj, cs, cy, eb, eg, ic, ih, ni, nr, rr, sa, sc, sn, sp, ss, t, ts, ur, zc`

### Day 2 (2026-07-13 PM) — 43/43 success

**Batch A** — 955 MB budget (9 products):

```bash
uv run --project services/quant-api python scripts/rqdata_1m_pre2020_backfill.py \
  --run-write --register --allow-quality-failed \
  --traffic-budget-mb 955 \
  --output-dir data/reports/minute_pre2020_backfill_20260713
```

Success: `sf, sm, ma, hc, pp, bb, fb, jr, jd`

**Batch B** — remaining 34 products:

```bash
uv run --project services/quant-api python scripts/rqdata_1m_pre2020_backfill.py \
  --run-write --register --allow-quality-failed \
  --batch-size 34 \
  --output-dir data/reports/minute_pre2020_backfill_20260713
```

Success: `i, bu, tf, jm, rm, rs, fg, ri, wh, oi, ag, pm, j, pb, if, v, rb, wr, au, p, l, zn, ta, y, sr, b, c, fu, cf, a, m, al, cu, ru`

## Spot Check

| Product | Wide parquet | min_datetime | row_count |
|---------|-------------|--------------|----------:|
| jm | `jm_MAIN_1m_20130322_20260711_v2.parquet` | 2013-03-22 09:01:00 | 1091235 |
| sa | `sa_MAIN_1m_20191206_20260711_v2.parquet` | 2019-12-06 09:01:00 | 538335 |
| al | `al_MAIN_1m_20000104_20260711_v2.parquet` | 2010-01-04 09:01:00 | 1598970 |
| ru | `ru_MAIN_1m_20000104_20260711_v2.parquet` | 2010-01-04 09:01:00 | 1221570 |

## Artifacts

- Plan: `minute_pre2020_backfill_plan.csv`
- Traffic batches: `minute_pre2020_traffic_batches.json`
- Results: `minute_pre2020_batch_results.json`
- Logs: `day1_run.log`, `day2_run.log`, `day2_remaining_run.log`

## Next Step

Run 1m incremental tail to today:

```bash
END_DATE=2026-07-13 PERIODS=1m \
  PRODUCTS_FILE=data/universe/full_products_90.txt \
  bash scripts/rqdata_incremental_tail_universe.sh
```

## Notes

- Effective start = `max(listed_date, 2000-01-04)` per RQData API floor
- Gap end = `2019-12-31` for all 63 products
- 1999-listed products (al/cu/ru) 1m min may start ~2010 due to RQData 1m history availability (wider than daily 2000-01-04 floor)
- JM acceptance: `min_datetime < 2020-01-02` ✓
