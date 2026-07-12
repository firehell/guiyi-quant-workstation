# 1m Backfill Progress

Generated: 2026-07-12T12:51:30.482434+00:00

## Today batch (47 products, ~919 MB API)

- Layer1 1m prepend: **47** success / **0** failed
- Aggregate 5m/15m/30m/60m: **completed** for today batch
- Extended 1m files: **44/47**
- Extended 15m files: **44/47**

### jm 验收

| 周期 | 文件 | 行数 | min |
|------|------|------|-----|
| 1m | jm_MAIN_1m_20200102_20260711_v2.parquet | 532155 | 2020-01-02 09:01 |
| 5m | jm_MAIN_5m_20200102_20260711_v2.parquet | 106431 | 2020-01-02 09:05 |
| 15m | jm_MAIN_15m_20200102_20260711_v2.parquet | 35477 | 2020-01-02 09:15 |

## Tomorrow remaining (~286 MB, 24 products)

`lu t tf ts pf ic if ih bb cj fb jd jr pm ri rs sf sm ur wh wr lh pk im`

## Commands

```bash
LAYER=dry-run BATCH=today bash scripts/rqdata_full_universe_backfill_1m.sh
ALLOW_QUALITY_FAILED=1 LAYER=layer1 BATCH=09 bash scripts/rqdata_full_universe_backfill_1m.sh
LAYER=aggregate BATCH=09 bash scripts/rqdata_full_universe_backfill_1m.sh
```
