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
| 阶段 5 | 1m 聚合多周期 | done / code-level complete | 是 |
| 阶段 6A | Web Market 显式 live 查看 | done / code-level complete | 是 |
| 阶段 6B | 策略中心 live_evaluator 只读接入 | done / code-level complete | 是 |
| 阶段 7 | 通达信指标本地化，标注未来函数 / 重绘风险 | done / code-doc risk review | 是 |
| 阶段 8 | `signal_events` 信号事件化 | done / code-level complete | 是 |
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

Stage 5 已完成代码级闭环：

- 新增 Alembic migration：`services/quant-api/alembic/versions/20260707_0014_live_multi_tf_aggregation.py`。
- 新增 SQLAlchemy models：`LiveAggregatedBar`、`LiveAggregationCheckpoint`。
- 新增聚合 service：`services/quant-api/app/services/live_multi_tf_aggregation.py`。
- 新增 dry-run / once CLI：`scripts/rqdata_live_multi_tf_aggregate.py`。
- 新增单元测试：`services/quant-api/tests/test_live_multi_tf_aggregation.py`。
- 只聚合 `bar_status=confirmed` 且 `quality_status != failed` 的 live 1m rows。
- 支持 `5m/15m/30m/60m`，最新正在形成的 bucket 不输出。
- closed partial bucket 输出 `quality_status=warning`，不伪装为 passed。
- live 聚合 DB 不登记 `market_data_files`，默认 Market / Backtest / Signal 读取行为保持不变。

Stage 5 未做：

- 未执行真实 live 1m 非 dry-run 聚合。
- 未接 Web live 展示。
- 未接策略扫描、企业微信、回测或交易。

Stage 6A 已完成代码级闭环：

- 新增 `services/quant-api/app/services/live_market_reader.py`。
- 新增 `GET /api/v1/market/live/coverage` 和 `GET /api/v1/market/live/bars`。
- `period=1m` 显式读取 `live_minute_bars`。
- `period=5m/15m/30m/60m` 显式读取 `live_aggregated_bars`。
- chart bars 默认排除 `quality_status=failed` 或 `bar_status=rejected` rows，但 quality summary 保留 `failed_count` / `rejected_count`。
- warning / partial live bar 在 API 和 UI 中可见，不伪装为 `passed`。
- Web Market 新增 `historical` / `live` 数据模式；默认仍为 `historical`，只有 `data_mode=live` 才请求 live endpoints。
- 默认 Market / Backtest / Signal 读取行为保持不变。

Stage 6A 未做：

- 未做 historical/live 拼接。
- 未执行策略 live evaluator。
- 未触发策略扫描、企业微信、回测或交易。

Stage 6B 已完成代码级闭环：

- 新增 `services/quant-api/app/services/live_signal_evaluator.py`。
- 新增 `POST /api/signals/live-evaluator/preview`。
- 新增 `LiveSignalEvaluationRequest` / `LiveSignalEvaluationResponse`。
- 第一版只支持 JM V1-B live `15m/5m` entry evaluator。
- entry bars 显式读取 live DB；日线方向仍读取 active primary historical `1d`。
- preview result 只作为临时 evaluation result 返回。
- 默认 `/api/signals/scan` 仍只读 active standard parquet。
- evaluator 不写 `StrategySignal` / `SignalNotification` / `SignalScanTask`。
- evaluator 不推送 WebSocket，不接企业微信，不生成订单。

Stage 6B 未做：

- 未做前端页面。
- 未做 `signal_events`。
- 未接企业微信。
- 未执行真实 live 非 dry-run 数据验证。
- 未把 preview result 当作可信回测或正式信号记录。

Stage 7 已完成代码 / 文档级闭环：

- 新增 `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`。
- `experiments/rqalpha_tdx_xma_bands/xma_core.py` 新增 `indicator_risk_catalog()` 静态风险元数据，不改变指标计算结果。
- 新增 `services/quant-api/tests/test_tdx_xma_indicator_risk.py`，证明 `XMA` 对未来 bar 敏感，且风险目录明确标记 XMA 及派生信号风险。
- 原始 `XMA`、`ZK1/ZD1/ZD2`、`VAR23` 标记为 `forbidden_for_backtest_signal`。
- `XG`、`XG2`、`CURRBARSCOUNT` 标记为 `observation_only`。
- `DDX`、`REF`、`MA`、`EMA` 标记为 `candidate_after_rewrite`。
- Stage 7 没有把通达信 XMA PoC 接入正式策略、回测、signal scanner、live evaluator、`signal_events`、企业微信或 Web Market。

Stage 8 已完成代码级闭环：

- 新增 Alembic migration：`services/quant-api/alembic/versions/20260707_0015_signal_events.py`。
- 新增 SQLAlchemy model：`SignalEvent` / `signal_events`。
- 新增事件服务：`services/quant-api/app/signal/events.py`。
- 新增只读 API：`GET /api/signals/events` 和 `GET /api/signals/{signal_id}/events`。
- 扫描创建正式信号时写入 `signal_created`。
- 扫描发现同一信号变化时写入 `signal_changed`。
- 人工状态真实变化时写入 `signal_status_changed`。
- 重复扫描同一未变化信号不会重复写 `signal_created`。
- 相同状态重复提交不会重复写 `signal_status_changed`。
- `live_signal_evaluator` 保持 preview-only，不写 `StrategySignal` / `SignalNotification` / `SignalEvent`。
- Stage 8 没有接企业微信，没有读取或打印 `QYWX_WEBHOOK_URL`，没有生成订单或自动下单。

## 4. 下一步任务

### Stage 9：企业微信只读提醒

目标：基于 `signal_events` 做只读提醒，不生成订单，不自动下单。

建议先 Plan：

- 明确从哪些 `signal_events` 读取可提醒事件。
- 明确提醒过滤条件、去重键、失败记录和重试边界。
- webhook 只能读取环境变量 `QYWX_WEBHOOK_URL`，不能写入文档、日志或 payload。
- 提醒文案必须表达“观察 / 复盘 / 人工确认”，不得表达自动交易指令。
- 不把原始 XMA PoC 接入企业微信提醒。

## 5. 后续阶段边界

- Stage 6A 已完成 Web Market 显式 live 查看。
- Stage 6B 已完成后端 live evaluator 只读 preview。
- Stage 7 已完成通达信 XMA PoC 风险审查，但原始 XMA / XMA 派生信号不得直接进入正式信号链路。
- Stage 8 已完成 `signal_events` 信号事件化。
- Stage 9 才做企业微信只读提醒。
- Stage 11 才做本地长期运行、worker、scheduler 和 health check 完整验收。
- 任何涉及数据库 schema、数据主链路、回测口径、策略逻辑重大变化的任务都应先 Plan。
- V1 不接实盘，不自动下单。

## 6. 下一轮 GPT 上传文件

- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/SIGNAL_EVENTS.md`
- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/app/api/signals.py`
- `services/quant-api/tests/test_signal_events.py`
