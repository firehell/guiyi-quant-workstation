# 当前项目状态

生成时间：2026-07-07

用途：上传到浏览器 GPT，作为当前项目状态速览。事实优先级为当前仓库代码和数据证据，其次是本文件、`PROJECT_SNAPSHOT.md`、`tasks/current.md`。

## 1. 当前阶段

当前处于 Stage 3 前置状态。

Stage 2C / 2D / 2E 已完成：

- JM v2 raw / standard parquet 已写入。
- 六周期为 `1m/5m/15m/30m/60m/1d`。
- data_version 使用全窗口 `20230103_20260707_v2`。
- manifest、checksum、quality report 已生成。
- PostgreSQL `market_data_files` / `data_quality_reports` 已登记。
- 覆盖审计结论为 `can_enter_stage3=true`。

下一步：

```text
DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS
WEB-DATA-3B-DATA-PAGE-SMOKE
```

## 2. 数据链路约束

V1 active 数据入口只允许：

```text
source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先 `quality_status=passed`。

旧 TqSdk / 天勤、交易练习者、validation、legacy_reference、candidate、failed 数据不得进入正式回测、默认 Market API 或信号输入。

## 3. JM v2 数据状态

分钟 bar 最大自然时间为夜盘 `2026-07-06 23:00:00`，对应最大 `trading_day=2026-07-07`。日线最大自然时间为 `2026-07-06 00:00:00`。

| timeframe | rows | min datetime | max datetime | max trading_day | data_version |
|---|---:|---|---|---|---|
| 1m | 289455 | 2023-01-03 09:01 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_1m_20230103_20260707_v2` |
| 5m | 57891 | 2023-01-03 09:05 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_5m_20230103_20260707_v2` |
| 15m | 19297 | 2023-01-03 09:15 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_15m_20230103_20260707_v2` |
| 30m | 10072 | 2023-01-03 09:30 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_30m_20230103_20260707_v2` |
| 60m | 5883 | 2023-01-03 10:00 | 2026-07-06 23:00 | 2026-07-07 | `rqdata_jm_standard_60m_20230103_20260707_v2` |
| 1d | 847 | 2023-01-03 00:00 | 2026-07-06 00:00 | 2026-07-06 | `rqdata_jm_standard_1d_20230103_20260707_v2` |

## 4. 关键证据

- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json`
- `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv`
- `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json`
- DB `market_data_files` id：`33205` 至 `33210`
- DB `data_quality_reports` id：`34804` 至 `34809`

## 5. 已具备功能

- RQData ingest、JM v2 parquet、manifest、quality report、DB 登记。
- DuckDB 读取 standard parquet。
- FastAPI 数据中心、Market、Backtest、Signal、Review API。
- vn.py CTA 回测任务、JM V1-B 固定任务、报告、曲线、交易明细。
- Vue Web 的 Data、Market、Backtest、Signal、Review 页面。
- K 线图、指标、回测买卖点 marker。
- 信号扫描只读提醒入口。
- 从回测成交创建复盘 note。
- WebSocket 进度与信号通道。
- `/health`、`/api/health`、`/healthz` 健康检查。

## 6. 未完成能力

- RQData 实时 1m 入库。
- 1m 聚合多周期。
- `signal_events` 信号事件化。
- 企业微信只读提醒。
- Dashboard 真实数据接入。
- 策略管理页面实用化。
- Settings 持久化。
- 本地长期运行、worker、scheduler、health check 完整验收。
- Cloudflare Access 本地 Web 访问部署验收。
- 可信回测主线复核。

## 7. 当前禁止事项

- 不运行新的 RQData 写入、下载、sync、asset 或 ingest 任务，除非另开任务明确授权。
- 不覆盖 JM v1 或 JM v2 历史数据文件。
- 不新增 migration。
- 不接实盘，不自动下单。
- 不写敏感信息。
