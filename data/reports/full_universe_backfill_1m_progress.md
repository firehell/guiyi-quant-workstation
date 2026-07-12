# 1m Backfill Progress

Generated: 2026-07-12T12:59:03.346897+00:00

## 状态：全量完成

- 需补前缀品种：**71/71** 全部完成（1m 扩展）
- 15m 聚合扩展：**71/71**
- 跳过（晚上市，无需前缀）：**19** 品种

## Remainder 批次（24 品种，~286 MB）

- Layer1 1m prepend: **24** success / **0** failed
- Aggregate 5m/15m/30m/60m: **completed**
- 额度：821 MB 预算，实际消耗见 `full_universe_backfill_1m_report.csv`

## 累计

| 批次 | 品种数 | 状态 |
|------|--------|------|
| today | 47 | done |
| remainder | 24 | done |

## 抽样验收（扩展后 canonical 文件）

| 品种 | 1m 文件 | 行数 | min | max |
|------|---------|------|-----|-----|
| jm | jm_MAIN_1m_20200102_20260711_v2.parquet | 532155 | 2020-01-02 09:01:00 | 2026-07-10 15:00:00 |
| lu | lu_MAIN_1m_20200622_20260711_v2.parquet | 501195 | 2020-06-22 09:01:00 | 2026-07-10 15:00:00 |
| im | im_MAIN_1m_20220722_20260711_v2.parquet | 230640 | 2022-07-22 09:31:00 | 2026-07-10 15:00:00 |
| bb | bb_MAIN_1m_20200102_20260711_v2.parquet | 355275 | 2020-01-02 09:01:00 | 2026-07-10 15:00:00 |

## 命令备忘

```bash
LAYER=dry-run BATCH=remainder bash scripts/rqdata_full_universe_backfill_1m.sh
ALLOW_QUALITY_FAILED=1 LAYER=layer1 BATCH=remainder bash scripts/rqdata_full_universe_backfill_1m.sh
ALLOW_QUALITY_FAILED=1 LAYER=aggregate BATCH=remainder bash scripts/rqdata_full_universe_backfill_1m.sh
```

## 后续（不在本轮）

- Layer2 真实主力 1m roll（预估 3–6 GB API）
- 旧 `20230103_*` parquet 保留作 rollback，canonical 以扩展后文件为准
