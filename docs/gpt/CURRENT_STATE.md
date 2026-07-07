# 当前项目状态

生成时间：2026-07-07

用途：上传到浏览器 GPT，作为当前项目状态速览。事实优先级为当前仓库代码和数据证据，其次是本文件、`PROJECT_SNAPSHOT.md`、`tasks/current.md`。

## 1. 当前阶段

当前已完成到：

```text
Stage 8：signal_events 信号事件化
```

下一步建议：

```text
Stage 9：企业微信只读提醒
```

Stage 9 应基于 `signal_events` 做只读提醒，不自动下单，不生成订单草稿，不把信号表达成实盘交易指令。

## 2. 数据链路约束

V1 active 数据入口只允许：

```text
source/provider in ("rqdata", "local_parquet")
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

关键证据：

- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json`
- `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv`
- `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json`

## 4. 已具备功能

- RQData ingest、JM v2 parquet、manifest、quality report、DB 登记。
- DuckDB 读取 standard parquet。
- FastAPI 数据中心、Market、Backtest、Signal、Review API。
- RQData live 1m 最小入库骨架。
- live 1m 聚合 5m / 15m / 30m / 60m。
- Web Market 显式 historical / live 查看。
- JM V1-B live evaluator preview-only 接口。
- vn.py CTA 回测任务、JM V1-B 固定任务、报告、曲线、交易明细。
- Vue Web 的 Data、Market、Backtest、Signal、Review 页面。
- K 线图、指标、回测买卖点 marker。
- JM V1-B 信号扫描，只提醒不下单。
- `signal_events` append-only 信号事件账本。
- 从回测成交创建复盘 note。
- WebSocket 进度与信号通道。
- `/health`、`/api/health`、`/healthz` 健康检查。

## 5. Stage 8 新增能力

`signal_events` 已完成：

- `signal_created`
- `signal_changed`
- `signal_status_changed`
- `GET /api/signals/events`
- `GET /api/signals/{signal_id}/events`

边界：

- 不接企业微信。
- 不读取或打印 `QYWX_WEBHOOK_URL`。
- 不自动下单。
- 不生成订单草稿。
- 不把 live evaluator preview 自动持久化为正式事件。
- 不把原始 XMA PoC 或 XMA 派生信号接入正式事件。

## 6. 未完成能力

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
- 不接实盘，不自动下单。
- 不写敏感信息。
- Stage 9 前不要接企业微信。
