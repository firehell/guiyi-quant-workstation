# NEXT_STEPS.md

生成时间：2026-07-07
用途：冻结当前阶段顺序，供浏览器 GPT 持续拆 Codex 任务。

## 1. 总原则

```text
先数据，后信号；
先事件，后提醒；
先后端稳定，后 Web 美化；
先只读观察，后考虑交易辅助；
V1 不自动下单。
```

## 2. 阶段路线

| 阶段 | 名称 | 状态 | 建议新会话 |
|---|---|---|---|
| 阶段 0 | 重构基线冻结 | done | 否 |
| 阶段 1 | RQData 权限与接口能力 PoC | done / partial accepted | 是 |
| 阶段 2 | JM 历史数据更新到最新交易日 | done | 是 |
| 阶段 3A | active 数据过滤测试 | done | 是 |
| 阶段 3B | Web Data 页面 smoke | done / code-level smoke | 是 |
| 阶段 4A | RQData 实时 1m 入库设计 | done / design complete | 是 |
| 阶段 4B | RQData 实时 1m 最小入库实现 | done / code-level complete | 是 |
| 阶段 5 | 1m 聚合多周期 | next | 是 |
| 阶段 6 | 策略中心重构，苏冰策略 live_evaluator 接入 | pending | 是 |
| 阶段 7 | 通达信指标本地化，标注未来函数 / 重绘风险 | pending | 是 |
| 阶段 8 | `signal_events` 信号事件化 | pending | 是 |
| 阶段 9 | 企业微信只读提醒 | pending | 是 |
| 阶段 10 | Web Market 策略展示增强 | pending | 是 |
| 阶段 11 | 本地长期运行 / worker / scheduler / health check | pending | 是 |
| 阶段 12 | Cloudflare Access 本地 Web 访问部署验收 | pending | 是 |
| 阶段 13 | Codex git commit / push 自动化 | optional | 可选 |
| 阶段 14 | 可信回测主线复核 | pending | 是 |

## 3. 最近完成阶段

Stage 2 已完成：

- `JM-UPDATE-2B-PLAN-VERIFY`
- `JM-UPDATE-2B-FIX-PLAN-GAPS`
- `JM-UPDATE-2C-WRITE-PARQUET`
- `JM-UPDATE-2D-REGISTER-QUALITY`
- `JM-UPDATE-2E-COVERAGE-AUDIT`

完成结果：

- JM v2 六周期 `1m/5m/15m/30m/60m/1d` 已写入 raw / standard parquet。
- data_version 为全窗口 `20230103_20260707_v2`。
- 六周期均登记为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`。
- coverage audit 结论为 `can_enter_stage3=true`。

Stage 3 已完成代码级闭环：

- `DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS`：补强后端读取层测试，确认默认读取只允许 `rqdata/local_parquet + primary + quality_status != failed`。
- `WEB-DATA-3B-DATA-PAGE-SMOKE`：Web Data 页面新增“数据文件”页签，可查看覆盖、质量、行数、data_version 和文件路径。

Stage 4A 已完成设计闭环：

- 新增 `docs/LIVE_1M_INGEST_DESIGN.md`。
- 明确 4B 第一版使用 `RqDataClient.contract_bars(..., frequency="1m")` 做准实时 confirmed 1m 拉取。
- 明确 `LiveMarketDataClient`、`get_live_ticks`、`current_snapshot` 仅作为后续候选入口。
- 明确 live 数据先进入 PostgreSQL 独立 live 层，不复用 `market_data_files`，不自动混入默认 Market / Backtest / Signal 读取。
- 明确 live 表、checkpoint、bar 状态、补漏去重、夜盘 trading_day、历史 parquet 与 live DB 拼接边界。

Stage 4B 已完成代码级闭环：

- 新增 Alembic migration：`services/quant-api/alembic/versions/20260707_0013_live_1m_ingest.py`。
- 新增 SQLAlchemy models：`LiveMinuteBar`、`LiveIngestCheckpoint`。
- 新增最小 ingest service：`services/quant-api/app/services/live_1m_ingest.py`。
- 新增 dry-run / once CLI：`scripts/rqdata_live_1m_ingest.py`。
- 新增单元测试：`services/quant-api/tests/test_live_1m_ingest.py`。
- dry-run 确认不构造 RQData client、不打开 DB session、不写 DB、不写 parquet、不触发策略、不发企业微信。
- 默认 Market / Backtest / Signal 读取行为保持不变。
- `MarketDataReader` 只补充同一 `datetime` 下的确定性 provider 排序，active 过滤条件不变。

Stage 4B 未做：

- 未执行真实 RQData 非 dry-run 写库。
- 未做多周期聚合。
- 未接 Web live 展示。
- 未接企业微信、策略、回测或交易。

## 4. 下一步任务

### LIVE-1M-5-MULTI-TF-AGGREGATION-PLAN

目标：基于 4B 已入库的 confirmed 1m live rows，先设计 5m / 15m / 30m / 60m 聚合口径和状态边界。

建议先 Plan，不直接实现：

- 明确聚合是否写新表、视图还是按需查询。
- 明确只聚合 `bar_status=confirmed` 且 `quality_status != failed` 的 live rows。
- 明确如何避免与 historical standard parquet 重叠。
- 明确 Web 显示和策略扫描仍需显式参数，不改变默认 active 读取。
- 明确断线、缺口、当前未完成周期和夜盘 `trading_day` 的处理规则。

建议测试方向：

- 1m -> 5m / 15m 聚合边界。
- 当前未收盘周期不输出 confirmed 聚合 bar。
- 缺 1m bar 时聚合状态为 warning。
- rejected / failed live rows 不参与聚合。
- 默认 Market / Backtest / Signal 读取仍不读取 live DB。

## 5. 后续阶段边界

- Stage 5 才做 1m 聚合多周期。
- Stage 8 才做 `signal_events` 信号事件化。
- Stage 9 才做企业微信只读提醒。
- Stage 11 才做本地长期运行、worker、scheduler 和 health check 完整验收。
- 任何涉及数据库 schema、数据主链路、回测口径、策略逻辑重大变化的任务都应先 Plan。
- V1 不接实盘，不自动下单。

## 6. 下一轮 GPT 上传文件

- `docs/LIVE_1M_INGEST_DESIGN.md`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `services/quant-api/alembic/versions/20260707_0013_live_1m_ingest.py`
- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/services/market_data_reader.py`
- `services/quant-api/app/services/live_1m_ingest.py`
- `scripts/rqdata_live_1m_ingest.py`
- `services/quant-api/tests/test_live_1m_ingest.py`
