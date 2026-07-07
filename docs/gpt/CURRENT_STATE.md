# 当前项目状态

生成时间：2026-07-07

用途：上传到浏览器 GPT，作为当前项目状态速览。事实优先级为当前仓库代码和数据证据，其次是本文件、`PROJECT_SNAPSHOT.md`、`tasks/current.md`。

## 1. 当前阶段

当前已进入：

```text
Stage 8.5：数据主链路扩展 Gate
```

已完成：

```text
8.5-0 Stage 8 输出审查
8.5-1 数据新口径冻结与文档更新
8.5-2 schema / model 变更 Plan
8.5-3 schema / model 最小实现
8.5-4 RQData 元数据与目标品种池只读 Plan
8.5-5 主连 + 当前真实主力合约 historical bars 设计冻结
8.5-6 写入试点代码 + dry-run + fixture 测试闭环
```

下一步建议：

```text
Stage 8.5-6B：DATA-UNIVERSE-8_5F-HISTORICAL-BARS-PILOT-REAL-WRITE
```

Stage 9 企业微信只读提醒暂时 blocked。`signal_events` / `strategy_signals` 已显式支持 product、continuous contract、actual contract、dominant mapping date、confirmed bar boundary、trigger price、provider/source、data_role 和 quality_status，但 `actual_contract` 在缺少真实主力映射证据时保持 `NULL`，JM V1-B historical trigger price 仍来自主连 bar close。8.5-4 已冻结 `actual_contract` 只能来自 `MainContractMap.rank=1`，`dominant_mapping_date` 对应 `MainContractMap.trade_date`。8.5-5 已冻结：`jm.MAIN` 只作为研究主连资产，当前真实主力合约 historical bars 后续必须独立写入和独立过质量 Gate。8.5-6 已新增 dry-run / fake fixture 写入 Gate，但没有运行真实 RQData historical write，也没有登记真实 active。

## 2. 数据链路约束

V1 active 数据入口只允许：

```text
source/provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究优先 `quality_status=passed`。

旧 TqSdk / 天勤、交易练习者、validation、legacy_reference、candidate、failed 数据不得进入正式回测、默认 Market API 或信号输入。

Stage 8.5 新增口径：

- `continuous_contract` 用于研究、回测背景、连续图和日线方向。
- `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 active historical。
- 盘后归档必须单独通过质量 Gate 后才能进入 historical active。
- V1-B 默认目标品种池先锁定为 `jm`，不在 8.5-4 扩成全品种。
- metadata 源复用 `FuturesContractUniverse`、`MainContractMap`、`FuturesContinuousContractMap`、`FuturesTradingParameter` 和 `FeeMarginRule`。
- `jm.MAIN` historical bars 只作为研究主连资产；真实 `actual_contract` historical bars 必须作为独立 canonical bars 资产。
- `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close。
- 8.5-6 dry-run 默认不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。

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
- `strategy_signals` / `signal_events` contract context 显式字段与 API 过滤。
- 从回测成交创建复盘 note。
- WebSocket 进度与信号通道。
- `/health`、`/api/health`、`/healthz` 健康检查。

## 5. Stage 8.5 审查结论

当前 `signal_events` 已完成：

- `signal_created`
- `signal_changed`
- `signal_status_changed`
- `GET /api/signals/events`
- `GET /api/signals/{signal_id}/events`

Stage 8.5-3 已补齐 Stage 9 前置所需显式字段：

- `product`
- `continuous_contract`
- `actual_contract`
- `dominant_mapping_date`
- `bar_start` / `bar_end`
- `trigger_price`
- `provider` / `source`

当前 JM V1-B historical scan 仍以 `jm.MAIN` 为扫描合约，`actual_contract` 缺少真实映射证据时保持 `NULL`，`trigger_price` 仍来自主连 bar close，不足以作为真实主力合约提醒价格。

Stage 8.5-4 已完成 docs-level 元数据只读方案：

- `continuous_contract=jm.MAIN` 仍只作为研究主连 / 连续视图。
- `actual_contract` 只能来自 `MainContractMap.rank=1` 的真实主力映射。
- trading params 必须覆盖 `price_tick`、`contract_multiplier`、margin、commission；缺任一关键字段时不能进入 Stage 9。
- 真实 `rqdata_realtime_poc.py --run-readonly` 仍需单独授权。

Stage 8.5-5 已完成 docs-level historical bars 方案：

- `continuous_contract=jm.MAIN` 继续用于研究主连、连续图、日线方向和 historical scan 背景。
- 当前真实主力合约 historical bars 后续必须使用真实合约代码作为 `contract`，独立于 `jm.MAIN` 文件和语义。
- 首批 periods 与 JM v2 对齐：`1m / 5m / 15m / 30m / 60m / 1d`。
- 8.5-6 写入试点建议优先下载真实主力 `1m` 标准 bars，再聚合生成更高周期；如改用 RQData 直接多周期下载，必须在代码计划中说明取舍并补测试。
- 只有明确授权写入且质量报告通过后，才允许登记 `market_data_files` 和 `data_role=primary`。

Stage 8.5-6 已完成 code-level dry-run / fixture 闭环：

- 新增 `actual_contract_bars_pilot.py` 和 `rqdata_actual_contract_bars_pilot.py`。
- fake client / SQLite 测试覆盖缺主力映射、`.MAIN` 误用、缺交易参数、quality failed 不登记 primary、quality passed 登记真实 `actual_contract`。
- 真实 `--run-write` 仍需另行明确授权。

## 6. 未完成能力

- JM-only 当前真实主力合约 historical bars 真实写入试点。
- Web Data / Web Market 数据消费扩展。
- live 监听目标合约池 + evaluator 数据源收敛。
- 盘后归档 Gate。
- 企业微信只读提醒。
- Dashboard 真实数据接入。
- 策略管理页面实用化。
- Settings 持久化。
- 本地长期运行、worker、scheduler、health check 完整验收。
- Cloudflare Access 本地 Web 访问部署验收。
- 可信回测主线复核。

## 7. 当前禁止事项

- 不运行新的 RQData 写入、下载、sync、asset 或 ingest 任务，除非另开任务明确授权。
- 不运行真实 RQData `--run-readonly`，除非另开任务明确授权。
- 不运行真实 historical bars 写入试点，除非另开任务明确授权。
- 不覆盖 JM v1 或 JM v2 历史数据文件。
- 不把当前真实主力合约 bars 写入 `jm.MAIN` 文件或复用 `jm.MAIN` 的 `contract` 语义。
- 不把 live DB 或 live 聚合 DB 直接登记为 trusted historical active。
- 不接企业微信，不读取或打印 `QYWX_WEBHOOK_URL`。
- 不接实盘，不自动下单，不生成订单草稿。
- Stage 9 前必须先完成 Stage 8.5 Gate。
