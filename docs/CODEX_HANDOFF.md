# CODEX_HANDOFF.md

生成时间：2026-07-07

## 1. 接手结论

当前可见分支为 `main`。接手时必须先运行 `git status --short --branch`，不要覆盖非本轮任务文件；当前工作区存在 Web 研究面板、RQData 结构化数据、全品种 manifest 和运行态 `.run/dev/*.pid` 等未提交改动。

Stage 2C / 2D / 2E 已完成，Stage 3A / 3B 已完成代码级闭环，Stage 4A `LIVE-1M-4A-DESIGN` 已完成设计落地，Stage 4B `LIVE-1M-4B-MINIMAL-INGEST` 已完成代码级闭环，Stage 5 `LIVE-1M-5-MULTI-TF-AGGREGATION` 已完成代码级闭环，Stage 6A `LIVE-1M-6A-EXPLICIT-LIVE-MARKET-VIEW` 已完成代码级闭环，Stage 6B `LIVE-1M-6B-LIVE-EVALUATOR-READONLY` 已完成代码级闭环，Stage 7 `STAGE-7-TDX-INDICATOR-RISK-REVIEW` 已完成代码 / 文档级闭环，Stage 8 `STAGE-8-SIGNAL-EVENTS` 已完成代码 / 文档级闭环，Stage 8.5 `STAGE-8.5-DATA-CHAIN-GATE` 已完成 8.5-0 / 8.5-1 / 8.5-2 文档级闭环、8.5-3 schema 最小代码闭环、8.5-4 RQData 元数据只读方案冻结、8.5-5 historical bars 设计冻结、8.5-6 写入试点代码 + dry-run + fixture 测试闭环、8.5-6B JM-only 当前真实主力合约 historical bars 真实写入试点、8.5-7 Web Data / Web Market actual-contract 只读消费扩展、8.5-8 live 监听目标合约池 + evaluator 数据源收敛，以及 8.5-9 盘后归档设计与 Stage 9 前 final Gate。

下一步建议进入独立新会话：

```text
Stage 9：企业微信只读提醒 guarded adapter 设计 / 实现
```

Stage 9 可进入 guarded adapter 设计 / 实现，但真实发送仍需单独授权。`signal_events` / `strategy_signals` 已具备 product、continuous contract、actual contract、dominant mapping date、confirmed bar boundary、trigger price、provider/source、data_role 和 quality_status 显式字段。8.5-9 已新增 `evaluate_stage9_signal_event_gate()`，只有通过 Gate 的 `signal_created` / `signal_changed` entry signal 事件才可作为企业微信只读提醒候选；Gate 会阻断缺真实合约、`*.MAIN` 误用、缺 bar / trigger price、quality 非 passed 和非 primary 数据。webhook 只能通过环境变量 `QYWX_WEBHOOK_URL` 获取，不能写入文档、日志或 payload。不要生成订单，不要自动下单，不要把原始 XMA PoC 接入提醒。

当前路线修正：

- Web 托管当前主线改为阿里云，见 `docs/ALIYUN_WEB_HOSTING_PLAN.md`。
- `docs/CLOUDFLARE_WORKSTATION_ACCESS.md` 仅作历史备选 / 暂停，不再作为默认执行路线。
- Web Market 已新增「品种研究」只读面板，读取本地 PostgreSQL 中的 RQData 结构化元数据。
- 全品种下载已出现一批 manifest / processed summary，仍需审计和 active Gate 核对，不能直接宣称全部可信完成。

## 2. 必读文件

1. `AGENTS.md`
2. `README.md`
3. `tasks/current.md`
4. `docs/LIVE_1M_INGEST_DESIGN.md`
5. `docs/gpt/CURRENT_STATE.md`
6. `docs/gpt/PROJECT_SNAPSHOT.md`
7. `docs/gpt/NEXT_STEPS.md`
8. `docs/ARCHITECTURE.md`
9. `docs/DATA_CENTER.md`
10. `docs/BACKTEST_ENGINE.md`
11. `docs/STRATEGY_CURRENT_STATE.md`
12. `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
13. `docs/SIGNAL_EVENTS.md`
14. `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
15. `docs/ALIYUN_WEB_HOSTING_PLAN.md`

## 3. 当前数据事实

JM v2 历史数据已完成：

```text
1m / 5m / 15m / 30m / 60m / 1d
20230103_20260707_v2
provider = rqdata
data_role = primary
quality_status = passed
```

关键证据：

- `data/manifests/rqdata_jm_v2_history_20230103_20260707.csv`
- `data/processed/v1b/jm/jm_v2_parquet_20230103_20260707.json`
- `data/processed/v1b/jm/jm_v2_coverage_audit_20230103_20260707.json`

全品种下载补充事实：

- `data/universe/full_products_90.txt` 定义 90 个候选品种。
- 当前已出现一批 `rqdata_*_v2_history_20230103_20260707.csv`、`rqdata_actual_contract_bars_*_20260401_20260707.csv` 和 `data/processed/v1b/*/*_v2_parquet_20230103_20260707.json`。
- 上述产物必须按“进行中 / 待审计 / 可进入 active”分层，不能仅凭文件存在就接入默认 Market / Backtest / Signal。

## 4. 当前主链路

```text
RQData / Local Standard Parquet
-> DuckDB
-> PostgreSQL
-> vn.py CTA BacktestingEngine / FastAPI
-> Vue Web
-> K线复盘 / 信号提醒 / 人工观察
```

active 数据入口：

```text
source/provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

默认 Market / Backtest / Signal 读取仍只读取 active standard parquet，不读取 live DB 或 live 聚合 DB。

## 5. Stage 4B 实现结论

新增代码：

- `services/quant-api/alembic/versions/20260707_0013_live_1m_ingest.py`
- `services/quant-api/app/services/live_1m_ingest.py`
- `scripts/rqdata_live_1m_ingest.py`
- `services/quant-api/tests/test_live_1m_ingest.py`

核心行为：

- 新增 `live_minute_bars` 和 `live_ingest_checkpoints`。
- `live_minute_bars` 唯一键为 `(provider, contract_code, period, bar_datetime)`。
- 使用 `RqDataClient.contract_bars(..., frequency="1m")` 作为后续真实拉取入口。
- 只处理当前分钟之前已经结束的 bar。
- 缺 `trading_day` 时标记 `quality_status=warning`，不硬推夜盘交易日。
- OHLC 等硬错误标记 `bar_status=rejected`、`quality_status=failed`。
- live DB 不登记 `market_data_files`，不进入默认 active 数据读取。

## 6. Stage 5 实现结论

新增代码：

- `services/quant-api/alembic/versions/20260707_0014_live_multi_tf_aggregation.py`
- `services/quant-api/app/services/live_multi_tf_aggregation.py`
- `scripts/rqdata_live_multi_tf_aggregate.py`
- `services/quant-api/tests/test_live_multi_tf_aggregation.py`

更新代码：

- `services/quant-api/app/models/data_center.py`
- `services/quant-api/app/models/__init__.py`

核心行为：

- 新增 `live_aggregated_bars` 和 `live_aggregation_checkpoints`。
- `live_aggregated_bars` 唯一键为 `(provider, contract_code, period, bar_datetime, source_mode)`。
- 只聚合 `bar_status=confirmed` 且 `quality_status != failed` 的 live 1m rows。
- 支持 `5m/15m/30m/60m`。
- `failed` / `rejected` 1m rows 不参与聚合。
- 最新正在形成的 bucket 不输出。
- closed partial bucket 输出 `quality_status=warning`，不伪装为 passed。
- 源 1m warning 会传导到聚合 warning。
- live 聚合 DB 不登记 `market_data_files`，不进入默认 active 数据读取。

已验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_multi_tf_aggregation.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_1m_ingest.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api python scripts/rqdata_live_multi_tf_aggregate.py --contract JM2609 --symbol jm --exchange DCE --periods 5m,15m,30m,60m --once --dry-run
cd services/quant-api && uv run python -m alembic upgrade head
uv run --project services/quant-api ruff check services/quant-api/app/services/live_multi_tf_aggregation.py services/quant-api/tests/test_live_multi_tf_aggregation.py scripts/rqdata_live_multi_tf_aggregate.py services/quant-api/app/models/data_center.py services/quant-api/app/models/__init__.py
git diff --check
```

结果：

- live aggregation 单测：`7 passed`。
- live ingest 回归：`8 passed`。
- MarketDataReader 回归：`4 passed`。
- CLI dry-run：通过，确认不打开 DB session、不写 DB、不写 parquet、不登记 `market_data_files`、不触发策略、不运行回测、不发企业微信。
- Alembic：已升级到 `20260707_0014`。
- `ruff check`：通过。
- `git diff --check`：通过。

## 7. 禁止事项

- 不接企业微信，不读取或打印 `QYWX_WEBHOOK_URL`。
- 不触发策略扫描。
- 不运行回测。
- 不自动下单，不生成订单草稿。
- 不运行长期 scheduler。
- 不把全品种下载中的 manifest 直接视为全部 active passed。
- 不把 Cloudflare 作为当前默认远程访问路线；当前默认路线是阿里云方案设计。
- 不把 live DB 或 live 聚合 DB 数据登记成 trusted standard parquet。
- 不恢复 TqSdk 为 V1 active 主链路。
- 不把 validation、legacy_reference、candidate、failed 数据作为正式默认读取。
- 不提交 `.env`、账号、密码、API Key、webhook、token、license。

## 8. Stage 6A 实现结论

新增代码：

- `services/quant-api/app/services/live_market_reader.py`
- `services/quant-api/tests/test_live_market_reader.py`

更新代码：

- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/tests/test_market_data_api.py`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/pages/market/index.vue`

核心行为：

- 新增 `GET /api/v1/market/live/coverage` 和 `GET /api/v1/market/live/bars`。
- `period=1m` 读取 `live_minute_bars`。
- `period=5m/15m/30m/60m` 读取 `live_aggregated_bars`。
- chart bars 默认排除 `quality_status=failed` 或 `bar_status=rejected` rows。
- response quality summary 保留 `failed_count` / `rejected_count` / `partial_count`。
- Market 工作台新增 `historical` / `live` 模式；默认仍为 `historical`。
- live 模式显示 `Live Observation`、`source_mode` 和 Live 质量摘要。
- 默认 Market / Backtest / Signal 读取仍不读取 live DB。

已验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_market_reader.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_1m_ingest.py services/quant-api/tests/test_live_multi_tf_aggregation.py
uv run --project services/quant-api ruff check services/quant-api/app/api/market.py services/quant-api/app/services/live_market_reader.py services/quant-api/app/schemas/market.py services/quant-api/app/services/market_workbench.py services/quant-api/tests/test_live_market_reader.py services/quant-api/tests/test_market_data_api.py
npm --prefix apps/quant-web run build
curl -sS http://127.0.0.1:8000/healthz
curl -sS -I http://127.0.0.1:5173/market
curl -sS http://127.0.0.1:5173/api/health
git diff --check
```

结果：

- `test_live_market_reader.py`：`3 passed`。
- `test_market_data_api.py`：`4 passed`。
- `test_market_data_reader.py`：`4 passed`。
- live ingest + aggregation 回归：`15 passed`。
- `ruff check`：通过。
- 前端 build：通过。
- HTTP smoke：`/healthz`、Vite `/market`、前端代理 `/api/health` 均通过。
- Browser smoke：Market 默认 historical 渲染成功；点击 `Live` 后 URL 变为 `data_mode=live`，页面显示 `Live Observation` 和 `Live 质量`，应用 console error 为 0。
- `git diff --check`：通过。

## 9. Stage 6B 实现结论

新增代码：

- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/tests/test_live_signal_evaluator.py`

更新代码：

- `services/quant-api/app/api/signals.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/tests/test_signal_scanner_api.py`

核心行为：

- 新增 `POST /api/signals/live-evaluator/preview`。
- 第一版只支持 JM V1-B live `15m/5m` entry evaluator。
- entry bars 显式读取 `live_aggregated_bars`。
- 日线方向仍读取 active primary historical `1d` standard parquet。
- 复用 JM V1-B 策略纯计算函数，只返回临时 preview DTO。
- warning / partial live bars 默认阻断可行动入场结论。
- 不创建 `SignalScanTask`，不写 `StrategySignal` / `SignalNotification`。
- 不入队 RQ，不推送 WebSocket，不接企业微信，不生成订单。
- 默认 `/api/signals/scan` historical active parquet 读取路径保持不变。

已验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_market_reader.py services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api ruff check services/quant-api/app/services/live_signal_evaluator.py services/quant-api/app/api/signals.py services/quant-api/app/schemas/signal.py services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_signal_scanner_api.py
git diff --check
```

结果：

- `test_live_signal_evaluator.py`：`4 passed`。
- `test_signal_scanner_api.py`：`7 passed`。
- live reader + historical reader 回归：通过。
- `ruff check`：通过。
- `git diff --check`：通过。

## 10. Stage 7 实现结论

新增代码 / 文档：

- `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
- `services/quant-api/tests/test_tdx_xma_indicator_risk.py`

更新代码：

- `experiments/rqalpha_tdx_xma_bands/xma_core.py`

核心行为：

- 新增 `indicator_risk_catalog()` 静态风险元数据，不改变任何 XMA / 信号计算结果。
- `XMA`、`ZK1_ZD1_ZD2`、`VAR23` 标记为 `forbidden_for_backtest_signal`。
- `XG`、`XG2`、`CURRBARSCOUNT` 标记为 `observation_only`。
- `DDX`、`REF`、`MA`、`EMA` 标记为 `candidate_after_rewrite`。
- 新增测试证明 `xma()` 会读取未来 bar，修改未来尾部数据会改变历史位置的 XMA 结果。

已验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api ruff check experiments/rqalpha_tdx_xma_bands/xma_core.py services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
```

结果：

- `test_tdx_xma_indicator_risk.py`：`4 passed`。
- `test_live_signal_evaluator.py` + `test_signal_scanner_api.py`：`11 passed`。
- `ruff check`：通过。
- `git diff --check`：通过。

禁止事项：

- 不把原始 XMA PoC 接入正式策略、回测、signal scanner、live evaluator、`signal_events`、企业微信或 Web Market。
- 不把 XMA PoC 结果当作 JM v2 active parquet 的可信回测结论。
- 不接 Cloudflare / Tunnel / Access / 远程访问。

## 11. GPT 同步文件

## 11. Stage 8 实现结论

新增代码 / 文档：

- `services/quant-api/alembic/versions/20260707_0015_signal_events.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/tests/test_signal_events.py`
- `docs/SIGNAL_EVENTS.md`

更新代码：

- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/models/__init__.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/app/api/signals.py`
- `services/quant-api/app/services/signal_scanner.py`
- `services/quant-api/app/signal/scanner.py`

核心行为：

- 新增 `SignalEvent` / `signal_events` append-only 事件账本。
- `signal_created`：扫描首次生成正式信号。
- `signal_changed`：扫描发现同一信号内容变化。
- `signal_status_changed`：人工查看、观察、忽略等生命周期变化。
- `source_mode` 区分 `historical_scan`、`jm_v1b_scan`、`manual_api`。
- 新增只读 API：`GET /api/signals/events` 和 `GET /api/signals/{signal_id}/events`。
- 重复扫描未变化信号不重复写 `signal_created`。
- 相同状态重复提交不重复写 `signal_status_changed`。
- `live_signal_evaluator` 仍是 preview-only，不写 `StrategySignal` / `SignalNotification` / `SignalEvent`。

已验证：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py
cd services/quant-api && uv run python -m alembic upgrade head
uv run --project services/quant-api ruff check services/quant-api/app/models/signal.py services/quant-api/app/signal/events.py services/quant-api/app/api/signals.py services/quant-api/app/schemas/signal.py services/quant-api/tests/test_signal_events.py services/quant-api/tests/test_signal_scanner_api.py
git diff --check
```

结果：

- `test_signal_events.py`：`3 passed`。
- `test_signal_scanner_api.py`：`7 passed`。
- `test_live_signal_evaluator.py`：`4 passed`。
- Alembic：已升级 `20260707_0014 -> 20260707_0015`。
- `ruff check`：通过。
- `git diff --check`：通过。

禁止事项：

- Stage 8 没有接企业微信，没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单，没有生成订单草稿。
- 没有把 live evaluator preview 自动持久化为正式事件。
- 没有把原始 XMA PoC 或 XMA 派生信号接入 `signal_events`。
- 没有修改策略核心逻辑、回测口径或 JM v2 parquet。

## 12. Stage 8.5 实现结论

新增文档：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`

更新文档：

- `tasks/current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/CURRENT_STATE.md`

核心行为：

- 完成 `8.5-0 Stage 8 输出审查`。
- 完成 `8.5-1 数据新口径冻结与文档更新`。
- 完成 `8.5-2 schema / model 变更 Plan`。
- 完成 `8.5-3 schema / model 最小实现`。
- 完成 `8.5-4 RQData 元数据与目标品种池只读 Plan`。
- 完成 `8.5-5 主连 + 当前真实主力合约 historical bars 设计冻结`。
- 完成 `8.5-6 historical bars pilot code + dry-run + fixture tests`。
- 完成 `8.5-6B JM-only 当前真实主力合约 historical bars real write`。
- 明确 Stage 9 企业微信前必须先通过 Stage 8.5 数据主链路 Gate。
- 冻结 `continuous_contract` 用于研究背景和连续图，`actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- 明确 live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 active historical。
- 明确后续优先复用 `MainContractMap`、`FuturesContinuousContractMap`、`FuturesContractUniverse`、`FuturesTradingParameter`、`MarketDataFile`、`DataQualityReport`、`LiveMinuteBar`、`LiveAggregatedBar`。
- 8.5-4 锁定 V1-B 默认目标品种池为 `jm`，不扩成全品种；真实 `rqdata_realtime_poc.py --run-readonly` 仍需单独授权。
- 8.5-5 锁定 `jm.MAIN` 与真实 `actual_contract` historical bars 分离，后续真实写入必须独立文件、独立质量报告、独立 active Gate。
- 8.5-6 已新增 `actual_contract_bars_pilot.py` 和 dry-run CLI；默认 dry-run 不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- 8.5-6B 已同步 `jm / 2026-07-07 / rank=1` 主力映射，解析 `actual_contract=JM2609`，同步 `JM2609` 当日交易参数，并执行真实 `--run-write`。
- 8.5-7 已完成 Web Data / Web Market actual-contract 只读消费扩展：Market coverage 输出 `view_role`、`continuous_contract`、`actual_contract`、`latest_bar_time`、`data_version`、`data_role`、`file_path`；Web Data / Web Market 可显式区分 `jm.MAIN` 主连研究视图与 `JM2609` 真实合约视图。
- 8.5-8 已完成 live 监听目标合约池 + evaluator 数据源收敛：新增 `LiveTargetContractResolver` 和 `GET /api/v1/market/live/targets`；`LiveSignalEvaluator` 的 `contract` 可省略，省略时解析 actual-contract，传入 `.MAIN` 或错配合约返回 422。
- 8.5-8 evaluator preview 输出 `continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_end` 和 entry-signal-only `trigger_price`，entry bars 来自 actual-contract live DB，daily direction 仍来自 `jm.MAIN` active standard parquet。

当前审查结论：

- 当前 `signal_events` 可作为事件账本基础，已具备显式 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`。
- JM V1-B historical scan 当前仍以 `jm.MAIN` 为扫描合约，`trigger_price` 仍来自主连 bar close，不足以直接承接 Stage 9；后续必须显式绑定 actual-contract confirmed bar close。
- `live_signal_evaluator` 仍是 preview-only，不写正式事件；8.5-8 已把 preview 数据源收敛到 actual-contract target。
- `actual_contract` 后续只能来自 `MainContractMap.rank=1`；`dominant_mapping_date` 对应 `MainContractMap.trade_date`；trading params 必须覆盖 `price_tick`、`contract_multiplier`、margin、commission。
- `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close；`jm.MAIN` close 不能宣称为真实合约提醒价。
- 8.5-6 fake fixture 已验证：缺 `MainContractMap.rank=1` 阻断、`.MAIN` 阻断、缺交易参数阻断、`quality_status != passed` 不登记 primary。
- 8.5-6B 真实写入结果：`JM2609` 六周期 row_count 为 `1m=690`、`5m=138`、`15m=46`、`30m=24`、`60m=14`、`1d=3`，manifest 为 `data/manifests/rqdata_actual_contract_bars_jm_JM2609_20260706_20260707.csv`。
- 8.5-7 已验证：Market API / dominant reader / MarketDataReader / actual-contract pilot 回归 `21 passed`，前端 build 通过，`ruff check` 通过。
- 8.5-8 已验证：live evaluator + live market reader 回归 `9 passed`，Market API + dominant reader 回归 `13 passed`，相关 Python 文件 `ruff check` 通过，`git diff --check` 通过。

禁止事项：

- Stage 8.5-3 修改了 `services/` 应用代码并创建 Alembic migration。
- 没有接企业微信，没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单，没有生成订单草稿。
- 没有把 live DB 登记为 trusted historical active。
- 8.5-4 没有修改代码、migration、API、测试或前端页面。
- 8.5-5 没有运行真实 RQData、没有写 parquet / manifest / checksum / DB rows、没有登记 active。
- 8.5-6B 没有把 `JM2609` 硬编码为长期主力，没有修改策略逻辑，没有把 scanner trigger price 切到真实合约 close。
- 8.5-7 没有运行真实 RQData 写入，没有修改已生成 parquet / manifest / checksum，没有修改策略逻辑或回测口径。
- 8.5-8 没有新增 migration，没有写正式 signal/event/notification，没有接企业微信，没有运行真实 RQData 写入，没有修改已生成 parquet / manifest / checksum。
- 8.5-9 没有新增 migration，没有读取或打印 `QYWX_WEBHOOK_URL`，没有发送企业微信，没有写 `SignalNotification`，没有运行真实 RQData 写入，没有实现盘后归档 worker / scheduler。

下一步：

```text
Stage 9：企业微信只读提醒 guarded adapter 设计 / 实现
```

目标是在 `evaluate_stage9_signal_event_gate()` 后实现只读提醒 adapter。真实发送、webhook 环境变量读取、通知记录写入和发送 smoke 必须在 Stage 9 中单独设计、单独授权；默认仍不自动下单、不生成订单草稿。

## 13. GPT 同步文件

- `tasks/current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/app/services/market_dominant_reader.py`
- `services/quant-api/app/services/live_target_contracts.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/app/signal/stage9_gate.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/tests/test_stage9_signal_event_gate.py`
- `services/quant-api/tests/test_signal_events.py`
- `services/quant-api/tests/test_market_data_api.py`
- `services/quant-api/tests/test_live_signal_evaluator.py`
- `services/quant-api/tests/test_market_dominant_reader.py`
- `apps/quant-web/src/pages/data/index.vue`
- `apps/quant-web/src/pages/market/index.vue`
- `apps/quant-web/src/types/data.ts`
- `apps/quant-web/src/types/market.ts`
- `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`
- `scripts/rqdata_actual_contract_bars_pilot.py`
- `services/quant-api/tests/test_actual_contract_bars_pilot.py`
- `docs/SIGNAL_EVENTS.md`
- `services/quant-api/app/models/signal.py`
- `services/quant-api/app/signal/events.py`
- `services/quant-api/app/signal/contract_context.py`
- `services/quant-api/app/signal/jm_v1b.py`
- `services/quant-api/app/services/signal_scanner.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/alembic/versions/20260707_0015_signal_events.py`
- `services/quant-api/alembic/versions/20260707_0016_signal_contract_context.py`
