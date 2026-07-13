# Minute Pre-2020 Backfill Batch Schedule

Generated: 2026-07-13  
Last updated: 2026-07-13

## Progress Summary

| Metric | Value |
|--------|------:|
| Total pre-2020 applicable | 63 |
| Download + register success | **20/63** |
| Failed | 0 |
| Day 1 estimated traffic | ~787 MB (budget 800 MB) |
| Remaining pending | 43 |

## Day 1 (2026-07-13) — 20/20 success

```bash
uv run --project services/quant-api python scripts/rqdata_1m_pre2020_backfill.py \
  --run-write --register --allow-quality-failed \
  --traffic-budget-mb 800 \
  --output-dir data/reports/minute_pre2020_backfill_20260713
```

Success: `ap, cj, cs, cy, eb, eg, ic, ih, ni, nr, rr, sa, sc, sn, sp, ss, t, ts, ur, zc`

## Remaining Schedule (traffic batches 2–12)

Resume with the same command daily until 63/63:

| Day | Batch | Products | Est. MB |
|-----|------:|----------|--------:|
| 2 | 2 | sf, sm, ma, hc, pp, bb, fb, jr | 799.53 |
| 3 | 3 | jd, i, bu, tf, jm, rm, rs | 790.52 |
| 4 | 4 | fg, ri, wh, oi, ag, pm | 779.01 |
| 5 | 5 | j, pb, if, v | 654.31 |
| 6 | 6 | rb, wr, au, p | 790.75 |
| 7 | 7 | l, zn, ta | 661.72 |
| 8 | 8 | y, sr, b | 744.05 |
| 9 | 9 | c, fu, cf | 799.94 |
| 10 | 10 | a, m | 644.97 |
| 11 | 11 | al, cu | 692.14 |
| 12 | 12 | ru | 346.07 |

## Spot Check (Day 1 completed products)

| Product | Wide parquet | min_datetime | row_count |
|---------|-------------|--------------|----------:|
| sa | `sa_MAIN_1m_20191206_20260711_v2.parquet` | 2019-12-06 09:01:00 | 538335 |
| ap | `ap_MAIN_1m_20171222_20260711_v2.parquet` | 2017-12-22 09:01:00 | 466200 |
| jm | `jm_MAIN_1m_20200102_20260711_v2.parquet` | 2020-01-02 09:01:00 (pending Day 3) | 532155 |

## Artifacts

- Plan: `minute_pre2020_backfill_plan.csv`
- Traffic batches: `minute_pre2020_traffic_batches.json`
- Results: `minute_pre2020_batch_results.json`
- Day 1 log: `day1_run.log`

## Notes

- Effective start = `max(listed_date, 2000-01-04)` per RQData API floor
- Gap end = `2019-12-31` for all 63 products
- Traffic budget default = 800 MB/day (conservative vs 1024 MB quota)
- Resume skips products with `status=success` in batch results
- After 63/63, run 1m incremental tail to today
