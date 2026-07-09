# 当前任务：STAGE-8.5-DATA-CHAIN-GATE

生成时间：2026-07-07
任务性质：Stage 9 企业微信前的数据主链路 Gate、schema 最小实现、元数据只读方案、historical bars 设计冻结、8.5-6 写入试点代码 dry-run、8.5-6B JM 真实主力合约 bars 写入试点、8.5-7 Web 只读消费、8.5-8 live/evaluator 数据源收敛与 8.5-9 盘后归档设计 / Stage 9 final Gate

## 当前结论

`STAGE-8.5-DATA-CHAIN-GATE` 已完成 8.5-0 / 8.5-1 / 8.5-2 的文档级闭环，完成 8.5-3 的 schema / model / API / tests 最小代码闭环，完成 8.5-4 的 RQData 元数据只读方案冻结，完成 8.5-5 的主连 + 当前真实主力合约 historical bars 设计冻结，完成 8.5-6 写入试点的代码 + dry-run + fixture 测试闭环，完成 8.5-6B JM-only 当前真实主力合约 historical bars 真实最小写入试点，完成 8.5-7 Web Data / Web Market actual-contract 只读消费扩展，完成 8.5-8 live 监听目标合约池 + evaluator 数据源收敛，并完成 8.5-9 盘后归档设计与 Stage 9 前 final Gate。

2026-07-09 Stage 11-B 补充：

- 已完成本地开发运行脚本增强：
  - `scripts/dev-status.sh`
  - `scripts/dev-healthcheck.sh`
  - `scripts/dev-down.sh`
- `dev-status` 只读展示 API、Web、RQ worker PID 状态、端口状态、Docker PostgreSQL / Redis 状态和日志路径，支持 `--json`。
- `dev-healthcheck` 只读检查 `/healthz`、`/api/health`、Web 首页、PostgreSQL readiness 和 Redis ping，支持 `--json` 与 `--no-start`。
- `dev-down` 停止 PID 前会校验 PID 命令行必须包含当前项目路径和对应服务标识，避免误杀非本项目进程。
- Stage 11-B 没有新增 scheduler，没有运行 live ingest / aggregation loop，没有运行真实 RQData 写入，没有读取或打印 `QYWX_WEBHOOK_URL`，没有运行企业微信 retry-pending 或真实发送，没有修改策略、回测、scanner 或 active 数据入口。

2026-07-09 Stage 11-C 补充：

- 已新增只读 runtime health API：
  - `GET /api/runtime/health`
  - `services/quant-api/app/api/runtime.py`
  - `services/quant-api/app/services/runtime_health.py`
  - `services/quant-api/app/schemas/runtime.py`
- runtime health 覆盖 PostgreSQL、Redis、RQ queue、RQ worker、live ingest / aggregation checkpoints、企业微信 notification retry summary。
- response 固定声明 `readonly=true`、`would_start_services=false`、`would_enqueue_jobs=false`、`would_send_notifications=false`。
- DB 或 Redis 不可用会返回结构化 `failed`，RQ 无 worker、live checkpoint failed、notification due retry 会返回 `degraded`；接口仍返回 HTTP 200，便于 Web runtime dashboard 只读展示。
- `scripts/dev-healthcheck.sh` 已新增 `${API_BASE_URL}/api/runtime/health` HTTP 只读检查。
- Stage 11-C 没有新增 migration，没有新增 scheduler / worker / loop，没有运行 live ingest / aggregation，没有运行真实 RQData 写入，没有读取或打印 `QYWX_WEBHOOK_URL`，没有运行企业微信 retry-pending 或真实发送，没有修改策略、回测、scanner、MarketDataReader 或 active 数据入口。
- 本轮验证命令：
  - `uv run --project services/quant-api pytest -q services/quant-api/tests/test_runtime_health.py services/quant-api/tests/test_health.py`：6 passed。
  - `uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage9_wechat_delivery.py services/quant-api/tests/test_live_1m_ingest.py services/quant-api/tests/test_live_multi_tf_aggregation.py`：23 passed。
  - `uv run --project services/quant-api ruff check services/quant-api/app/api/runtime.py services/quant-api/app/services/runtime_health.py services/quant-api/app/schemas/runtime.py services/quant-api/tests/test_runtime_health.py`：passed。
  - `bash -n scripts/dev-healthcheck.sh`：passed。
  - `curl -sS --max-time 3 http://127.0.0.1:8000/api/runtime/health`：未执行成功，原因是本地 API 服务未启动，连接 `127.0.0.1:8000` 失败。

2026-07-07 文档路线修正补充：

- Web 托管当前主线改为阿里云方案，Cloudflare Access 降级为历史备选 / 暂停。
- Web Market 已新增「品种研究」只读面板，读取本地 PostgreSQL 的 RQData 结构化元数据，不改变 K 线 active 读取入口。
- 全品种下载已出现一批 manifest / processed summary，但仍按“进行中 / 待审计 / 可进入 active”分层，不能直接写成全部可信完成。
- 当前后续路线为：Stage 9-B 企业微信真实发送授权 / 通知记录 / 重试设计、Stage 10 Web Market 策略展示增强、Stage 11 本地长期运行、Stage 12 阿里云 Web 托管设计、Stage 13 可信回测复核、Stage 14 Web 复盘增强、Stage 15 可选 Codex git 自动化。

2026-07-08 Stage 8.6 补充：

- 已新增 Stage 8.6 全品种下载结果 active Gate 只读审计入口：
  - `services/quant-api/app/services/rqdata_ingest/full_universe_active_gate.py`
  - `scripts/rqdata_full_universe_active_gate_audit.py`
  - `services/quant-api/tests/test_full_universe_active_gate.py`
- 审计器只读取已有 manifest、DB 登记、quality report 和 canonical parquet，并用 DuckDB 核对 row_count / datetime 边界。
- 审计输出为 `data/reports/stage8_6_active_gate_matrix.csv`、`stage8_6_product_summary.csv`、`stage8_6_stage9_readiness.csv`、`stage8_6_active_gate_summary.md`。
- Stage 8.6 不调用 RQData、不写 parquet / manifest / DB、不登记 active、不修改 `MarketDataReader` 默认读取规则、不接企业微信。
- Cursor 全量下载完成后，再运行只读审计命令生成最终 active Gate 分层报告。
- 本轮验证命令：
  - `uv run --project services/quant-api pytest -q services/quant-api/tests/test_full_universe_active_gate.py`：7 passed。
  - `uv run --project services/quant-api pytest -q services/quant-api/tests/test_actual_contract_bars_batch.py services/quant-api/tests/test_actual_contract_bars_pilot.py services/quant-api/tests/test_market_data_reader.py services/quant-api/tests/test_stage9_signal_event_gate.py`：22 passed。
  - `uv run --project services/quant-api ruff check services/quant-api/app/services/rqdata_ingest/full_universe_active_gate.py scripts/rqdata_full_universe_active_gate_audit.py services/quant-api/tests/test_full_universe_active_gate.py`：passed。
  - `git diff --check`：passed。
  - Stage 8.6 只读 smoke：90 products，`active_passed=82`，`active_partial=8`，asset `active_passed=1486`、`audit_pending=21`、`failed=5`，Stage 9 `stage9_blocked=90`。

2026-07-08 Stage 9-B1 补充：

- 已新增 Stage 9-B 企业微信真实发送能力的受控代码框架，但未执行真实 smoke：
  - `services/quant-api/app/signal/stage9_wechat_delivery.py`
  - `scripts/stage9_wechat_send_once.py`
  - `services/quant-api/tests/test_stage9_wechat_delivery.py`
  - `services/quant-api/alembic/versions/20260708_0018_stage9_wechat_notifications.py`
- `signal_notifications` 扩展 `event_id`、`attempt_count`、`max_attempts`、`last_attempt_at`、`next_retry_at`、`last_error_type`、`response_status_code`，兼容旧 WebSocket 通知记录。
- 新增只读 API：`GET /api/signals/events/{event_id}/stage9-wechat/notification`，只查询最近企业微信通知状态，不触发发送。
- 发送前必须通过 `evaluate_stage9_signal_event_gate()`；Gate 阻断写 `skipped`，缺 `QYWX_WEBHOOK_URL` 写 `failed/missing_webhook`，失败最多 3 次，未达上限写 `retry_pending`。
- 真实发送只允许通过 CLI 显式执行：`--run-send --confirm-observation-only --event-id <id>`；默认 dry-run 不读 webhook、不写 DB、不发送。
- Stage 9-B1 没有执行真实企业微信 smoke，没有批量发送历史事件，没有 worker / scheduler，没有自动下单或订单草稿。
- 本轮验证命令：
  - `uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage9_wechat_delivery.py`：8 passed。
  - `uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage9_wechat_adapter.py services/quant-api/tests/test_stage9_signal_event_gate.py services/quant-api/tests/test_stage9_wechat_delivery.py`：18 passed。
  - `uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py services/quant-api/tests/test_signal_scanner_api.py`：10 passed。
  - `uv run --project services/quant-api ruff check services/quant-api/app/signal/stage9_wechat.py services/quant-api/app/signal/stage9_wechat_delivery.py services/quant-api/app/api/signals.py services/quant-api/app/models/signal.py services/quant-api/app/schemas/signal.py scripts/stage9_wechat_send_once.py services/quant-api/tests/test_stage9_wechat_delivery.py`：passed。
  - `cd services/quant-api && uv run python -m alembic upgrade head`：已升级 `20260707_0017 -> 20260708_0018`。
  - 本轮 Stage 9-B 文件范围 `git diff --check`：passed。
  - 全局 `git diff --check`：blocked by unrelated `services/quant-api/app/main.py:55 new blank line at EOF`；该文件属于当前工作区其他 dashboard / frontend 变更，不属于本轮 Stage 9-B 修改范围。

2026-07-08 Stage 9-B2 补充：

- 已新增 Stage 9-B2 单条真实历史回放 eligible `SignalEvent` 生成入口：
  - `services/quant-api/app/signal/stage9_jm_v1b_replay.py`
  - `scripts/stage9_jm_v1b_replay_event_once.py`
  - `services/quant-api/tests/test_stage9_jm_v1b_replay.py`
- replay 入口默认 dry-run，不写 `StrategySignal` / `SignalEvent` / `SignalNotification`，不读取 webhook，不发送企业微信。
- `--run-write --confirm-historical-replay --confirm-observation-only` 才允许写入一条历史回放事件；事件明确标记 `source_mode=jm_v1b_historical_replay`、`historical_replay=true`、`observation_only=true`、`not_trading_instruction=true`。
- 本轮真实库 dry-run 找到候选：
  - `event_type=signal_created`
  - `strategy=jm_v1b_daily_direction_fast_entry / v1b.0`
  - `actual_contract=JM2609`
  - `continuous_contract=jm.MAIN`
  - `period=15m`
  - `bar_end=2026-07-03T14:30:00`
  - `trigger_price=1279.5`
  - `direction=short`
  - `provider=rqdata`
  - `source=historical_actual_contract_replay`
  - `data_role=primary`
  - `quality_status.status=passed`
  - `evaluate_stage9_signal_event_gate()` 返回 `allowed=true`、`blocked_reasons=[]`。
- 已执行单条写入，返回 `event_id=1`、`signal_id=3`；重复执行按固定 dedupe key 幂等返回既有事件。
- 已执行 Stage 9-B2 dry-run preview：`allowed=true`、`blocked_reasons=[]`、`would_read_webhook=false`、`would_send_wechat=false`。
- 已在本轮后续单条重试中临时注入 `QYWX_WEBHOOK_URL` 进程环境并执行一次真实 smoke；`signal_notifications.id=1` 更新为 `status=sent`、`attempt_count=1`、`response_status_code=200`、`last_error_type=NULL`、`sent_at=2026-07-08T15:25:01.328589+00:00`。
- 本轮没有批量发送历史事件，没有运行 retry-pending，没有 worker / scheduler，没有自动下单或订单草稿，没有输出 webhook / token / password / cookie / secret。
- 该历史回放事件只用于验证 Stage 9 企业微信发送链路，不代表当前实时 / 前向提醒绩效。

2026-07-08 Stage 10-A 补充：

- 已完成 Web Market 策略展示只读增强：
  - `apps/quant-web/src/pages/market/chart.vue`
  - `apps/quant-web/src/components/market/MarketStrategySidebar.vue`
  - `apps/quant-web/src/components/kline/KlineChart.vue`
- K 线信号层改为按当前 `product/symbol`、真实 `actual_contract`、`period`、`provider=rqdata`、`data_role=primary` 读取并二次过滤 `/api/signals/latest`，避免只按品种误叠其他合约或周期的信号。
- 右侧策略侧栏新增当前图匹配信号数量、策略/版本、信号阶段、方向、触发价、止损价、风险金额、合约口径和质量状态；无匹配信号时显示空状态。
- 浏览器 smoke 发现 `JM2609 / 15m` bars 因多个 file path 合并存在重复时间戳，已在 `KlineChart.vue` 渲染前按 chart time 去重并升序排序，避免 Lightweight Charts 因重复时间崩溃；该处理只影响前端展示，不修改 API、DB 或 parquet。
- Stage 10-A 没有修改策略逻辑、回测口径、signal scanner 核心逻辑，没有写 `SignalEvent` / `SignalNotification`，没有读取或打印 `QYWX_WEBHOOK_URL`，没有触发企业微信发送、retry、worker 或 scheduler。
- 本轮验证命令：
  - `npm --prefix apps/quant-web run build`：passed，仅保留 Vite chunk size warning。
  - `uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_scanner_api.py services/quant-api/tests/test_stage9_wechat_delivery.py`：15 passed。
  - `git diff --check`：passed。
  - 浏览器 smoke：`http://127.0.0.1:5173/market/chart?symbol=jm&contract=JM2609&period=15m` 可显示 `latest_price=1273.00`、`quality=passed`、`matched_signal_count=1`，本次刷新后无 fresh console error。

2026-07-09 Stage 10-B 补充：

- 已完成 Web Market 信号 marker 点击联动与 notification 只读状态展示：
  - `apps/quant-web/src/components/kline/KlineChart.vue`
  - `apps/quant-web/src/pages/market/chart.vue`
  - `apps/quant-web/src/components/market/MarketStrategySidebar.vue`
  - `apps/quant-web/src/api/signal.ts`
  - `apps/quant-web/src/types/signal.ts`
  - `apps/quant-web/src/utils/marketSignalSelection.ts`
  - `apps/quant-web/tests/marketSignalSelection.test.ts`
- K 线图新增 `marker-click` emit，优先使用 Lightweight Charts `hoveredInfo.objectKind=series-marker` 的 object id，失败时按当前 bar 时间 fallback 到信号 marker；同一时间可保留多个 marker，避免 trade marker 与 signal marker 互相覆盖。
- Market Chart 选中 `signal-${id}` marker 或右侧当前信号列表后，会高亮 marker，读取 `/api/signals/{signal_id}/events`，优先选择当前图匹配的 `signal_created` / `signal_changed` 事件，再只读读取 `/api/signals/events/{event_id}/stage9-wechat/notification`。
- 右侧策略侧栏新增关联事件和企业微信 notification 状态展示，覆盖 `event_id`、`event_type`、`bar_end`、`trigger_price`、`quality_status`、`status`、`attempt_count/max_attempts`、`response_status_code`、`last_error_type`、`sent_at`、`next_retry_at`；notification 404 显示为“尚无企业微信通知记录”。
- Stage 10-B 没有新增后端写入、migration、worker、scheduler、retry-pending，没有写 `SignalEvent` / `SignalNotification`，没有读取或打印 `QYWX_WEBHOOK_URL`，没有发送企业微信，没有修改策略、回测、scanner 核心逻辑或 active 数据入口。
- 本轮已通过：
  - `node --test apps/quant-web/tests/marketSignalSelection.test.ts`：3 passed。
  - `npm --prefix apps/quant-web run build`：passed，仅保留 Vite chunk size warning。
  - `uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage9_wechat_delivery.py services/quant-api/tests/test_signal_events.py`：11 passed。
  - `git diff --check`：passed。
  - 浏览器 smoke：`http://127.0.0.1:5173/market/chart?symbol=jm&contract=JM2609&period=15m` 可显示当前信号列表与 `Stage9 通知状态`；点击右侧当前信号后显示 `事件 #1 / signal_created / sent / 1/3 / 200 / sent_at=2026-07-08 15:25`，console error 为 0。

8.5-6B 已在明确授权后同步 `jm / 2026-07-07 / rank=1` 主力映射，解析 `actual_contract=JM2609`，同步 `JM2609` 当日交易参数，并执行真实 `--run-write`。本轮写入真实 raw parquet、六周期 canonical parquet、manifest、checksum、`market_data_files` 和 `data_quality_reports`；六周期均为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`。

8.5-6B 没有接企业微信，没有读取或打印 `QYWX_WEBHOOK_URL`，没有触发策略扫描，没有运行回测，没有生成订单或自动下单，没有把 live DB 登记为 trusted historical active，也没有扩大到全品种或多合约池。8.5-7 只读消费已登记的 `market_data_files` / `data_quality_reports`，没有运行真实 RQData 写入，没有修改 parquet / manifest 资产，没有修改策略逻辑或回测口径。8.5-8 只新增 live target readonly resolver、只读 API 和 live evaluator preview 字段收敛，没有写 `StrategySignal` / `SignalEvent` / `SignalNotification`，没有企业微信，没有真实 RQData 写入。8.5-9 只新增 Stage 9 事件准入 helper、测试和文档 Gate，不读取 webhook、不发送通知、不写通知记录、不执行真实归档写入。Stage 9-A 已新增企业微信只读 preview / dry-run adapter，不读取 webhook、不发送通知、不写通知记录。

阶段顺序保持为：

```text
Stage 8 signal_events 完成
-> Stage 8.5 数据主链路扩展
-> Stage 9 企业微信只读提醒
```

Stage 9-A guarded preview adapter 已完成；Stage 9-B1 受控发送 / 通知记录 / 失败重试框架已完成；Stage 9-B2 已通过单条历史回放生成 eligible `event_id=1` 并完成 dry-run preview。随后已对 `event_id=1` 执行一次 observation-only 真实 smoke，通知记录为 `sent / HTTP 200 / attempt_count=1`。8.5-9 已明确：只有通过 `evaluate_stage9_signal_event_gate()` 的 `signal_created` / `signal_changed` entry signal 事件，才可作为企业微信只读提醒候选；普通历史 scanner 仍以 `jm.MAIN` 为扫描合约且缺真实 `actual_contract` / trigger price 证据的事件不会被准入。

## 本轮完成

### 1. 8.5-0：Stage 8 输出审查

新增审查结论见：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`

核心判断：

- Stage 8 已具备 append-only `signal_events` 事件账本。
- Stage 8.5-3 前缺少企业微信前置所需的显式字段。
- JM V1-B historical scan 仍以 `jm.MAIN` 为扫描合约，不能直接表达真实主力合约触发价。
- `live_signal_evaluator` 仍是 preview-only，不写正式信号或事件。

结论：

```text
Stage 8 可作为事件账本基础，但不能直接进入 Stage 9。
```

### 2. 8.5-1：数据新口径冻结与文档更新

冻结口径：

- `continuous_contract` 用于研究、回测背景、连续图和日线方向。
- `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- live DB 只做盘中观察和 preview，不登记为 `market_data_files`，不自动进入 active historical。
- 盘后归档必须单独通过 quality Gate 后才能进入 historical active。
- Stage 9 企业微信 payload 必须能显示真实合约，且不表达实盘交易指令。

### 3. 8.5-2：schema / model 变更 Plan

已在 `docs/DATA_UNIVERSE_AND_ARCHIVE.md` 固化 schema Plan。

推荐最小方向：

- 在 `strategy_signals` 和 `signal_events` 中显式支持 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`、`data_role`、`quality_status`。

不推荐方向：

- 不建议只依赖 JSON payload。
- 不建议 Stage 9 临时解析不同来源 payload。
- 不建议把 live evaluator preview 直接持久化为正式事件。

### 4. 8.5-3：schema / model 最小实现

已完成：

- `strategy_signals` 新增 contract context 显式字段。
- `signal_events` 新增 contract context 显式字段。
- 普通信号扫描和 JM V1-B 扫描会把显式 contract context 写入 `StrategySignal`，再投影到 append-only `SignalEvent`。
- `/api/signals/latest` 与 `/api/signals/events` 输出新增字段，并支持 `product`、`continuous_contract`、`actual_contract`、`provider`、`source`、`data_role` 过滤。
- `jm.MAIN` / `*.MAIN` 仅作为 `continuous_contract`，在没有真实主力映射证据时不写入 `actual_contract`。

### 5. 8.5-4：RQData 元数据与目标品种池只读 Plan

已在 `docs/DATA_UNIVERSE_AND_ARCHIVE.md` 冻结：

- V1-B 默认目标品种池先锁定为 `jm`，不扩成全品种。
- metadata 源复用现有模型，不新增数据宇宙表：
  - `FuturesContractUniverse`
  - `MainContractMap`
  - `FuturesContinuousContractMap`
  - `FuturesTradingParameter`
  - `FeeMarginRule`
- `continuous_contract=jm.MAIN` 仍只作为研究主连 / 连续视图。
- `actual_contract` 只能来自 `MainContractMap.rank=1` 的真实主力映射；缺少映射证据时必须保持 `NULL`。
- `dominant_mapping_date` 对应 `MainContractMap.trade_date`。
- trading params 必须覆盖 `price_tick`、`contract_multiplier`、margin、commission；缺任一关键字段时不能进入 Stage 9。
- 真实 `rqdata_realtime_poc.py --run-readonly` 仍需单独授权。

### 6. 8.5-5：主连 + 当前真实主力合约 historical bars 设计冻结

已在 `docs/DATA_UNIVERSE_AND_ARCHIVE.md` 冻结：

- `continuous_contract=jm.MAIN` 继续用于研究主连、连续图、日线方向和 historical scan 背景，不作为真实交易合约。
- `actual_contract` 必须从 `MainContractMap` 按 `instrument_symbol=jm`、`rank=1`、目标交易日解析；缺少映射证据时必须保持缺失并阻断 Stage 9。
- 当前真实主力合约 historical bars 后续必须作为独立 canonical bars 资产，不得混入 `jm.MAIN` 文件或复用 `jm.MAIN` 的 `contract` 语义。
- 全品种 90 池执行阶段：**1d 已完成** → **1w 进行中** → 下一步 **1m + 本地聚合 5m/15m/30m/60m**（禁止从米筐直拉多分钟周期）。
- historical bars 周期策略（已代码冻结）：`1d/1w/1m` 米筐直连；`5m/15m/30m/60m` 只从本地 `1m` 聚合；actual-contract 的 `1d/1w` 与分钟 bundle 必须分两次 run。
- 共享聚合模块：`services/quant-api/app/services/rqdata_ingest/bar_aggregation.py`。
- JM 参考资产重跑脚本（需 RQData 配额恢复后执行）：`scripts/regenerate_jm_aggregated_bars.sh`。
- 已有六周期资产保留；1d 已存在则 skip。JM 旧版直拉 5m~60m 资产待 `--force` 重聚合后替换登记。
- `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close；`jm.MAIN` close 不能宣称为真实合约提醒价。
- 质量 Gate 必须覆盖 duplicate、gap、时间顺序、OHLC、空值、volume/open_interest、min/max datetime、row_count、data_version、checksum、manifest 和 DuckDB 可读性。
- 只有 8.5-6 明确授权写入且质量报告通过后，才允许登记 `market_data_files` 和 `data_role=primary`；8.5-5 不授权任何 active 登记。

### 7. 8.5-6：写入试点代码 + dry-run + fixture 测试闭环

已完成受控代码入口：

- `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`
- `scripts/rqdata_actual_contract_bars_pilot.py`
- `services/quant-api/tests/test_actual_contract_bars_pilot.py`

核心行为：

- dry-run 默认不构造 RQData client、不打开 DB session、不写 parquet、不写 manifest、不写 DB、不登记 primary、不触发策略 / 回测 / 企业微信。
- 写入 service 会从 `MainContractMap.rank=1` 解析 `actual_contract`，并阻断缺映射、`.MAIN` 主连伪装真实合约、缺交易参数关键字段的情况。
- 写入路径以真实合约 `1m` bars 为源，本地聚合 `5m / 15m / 30m / 60m`；`1d/1w` 只走米筐直连，不得与分钟 bundle 混跑。
- fake client / SQLite 测试验证只有 `quality_status=passed` 才登记 `data_role=primary`，且 `MarketDataFile.contract_code` 使用真实 `actual_contract`。
- `bar_sample.py` 的频率 helper 已扩展到 `5m / 15m / 30m`，用于 8.5-6 聚合质量检查。

边界：

- 本轮没有运行真实 RQData 写入。
- 本轮没有登记真实 `market_data_files`、`data_quality_reports` 或 active 数据。
- `--run-write` 入口仍需另行明确授权后才能执行。

### 8. 8.5-6B：JM 当前真实主力合约 historical bars 真实写入试点

已完成真实写入：

- `product=jm`
- `continuous_contract=jm.MAIN`
- `actual_contract=JM2609`
- `dominant_mapping_date=2026-07-07`
- `start_date=2026-07-06`
- `end_date=2026-07-07`
- `source_period=1m`
- `raw_rows=690`
- `quality_gate=passed`

输出资产：

- raw parquet：`data/raw/rqdata/actual_contract_bars/product=jm/contract=JM2609/frequency=1m/JM2609_1m_raw_20260706_20260707.parquet`
- manifest：`data/manifests/rqdata_actual_contract_bars_jm_JM2609_20260706_20260707.csv`
- canonical parquet：
  - `1m`：690 rows
  - `5m`：138 rows
  - `15m`：46 rows
  - `30m`：24 rows
  - `60m`：14 rows
  - `1d`：3 rows

DB 登记结果：

- 六条 canonical `market_data_files` 均为 `provider=rqdata`、`data_type=bars`、`instrument_symbol=jm`、`contract_code=JM2609`、`data_role=primary`、`quality_status=passed`。
- 六条 canonical `data_quality_reports` 均为 `status=passed`。
- 文件路径均使用真实合约 `JM2609`，未写入 `jm.MAIN` 路径。
- DuckDB 可读性检查通过，row_count 与 manifest / DB 摘要一致。

质量口径说明：

- 本轮沿用 JM v2 已采用的无交易时段日历检查口径：自然午休、夜盘、节假日和周末间隔记录为 `gap_samples`，不计入 `missing_bars`，避免把合法非交易时段误判为缺口。
- 重复 bar、OHLC 异常、负 volume、负 open_interest 仍会阻断 primary 登记。
- 后续若需要区分真实盘中缺口和自然非交易间隔，应单独补交易时段日历质量 Gate。

### 9. 8.5-7：Web Data / Web Market actual-contract 只读消费扩展

已完成：

- `GET /api/v1/market/workbench/coverage` 与 `GET /api/v1/market/bars` 的 coverage 输出新增只读字段：
  - `view_role`
  - `continuous_contract`
  - `actual_contract`
  - `latest_bar_time`
  - `data_version`
  - `data_role`
  - `file_path`
- Web Market 普通行情模式继续使用 `quote_mode=true`，主连 `*.MAIN` 只允许在回测深链中作为研究视图读取；真实行情视图默认选择 actual-contract。
- Web Market 当前主力卡片和数据质量卡片可显示 `jm.MAIN` 主连研究合约、`JM2609` 真实合约、quality、data_version、file_path、latest bar boundary。
- Web Data 数据文件表新增“视图”和“最新边界”，可直接区分 `jm.MAIN` 主连研究视图与 `JM2609` 真实合约视图。

边界：

- 8.5-7 只读消费已登记的 `market_data_files` / `data_quality_reports`。
- 没有运行真实 RQData 写入。
- 没有修改本次已生成 parquet / manifest / checksum。
- 没有修改策略逻辑、回测口径、signal scanner 或 live evaluator。
- 没有接企业微信。

### 10. 8.5-8：live 监听目标合约池 + evaluator 数据源收敛

已完成：

- 新增 `LiveTargetContractResolver`，只读解析 Stage 8.5 live 目标合约池。
- 新增 `GET /api/v1/market/live/targets`，输出 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、required historical periods、trading parameter gate、historical actual-contract coverage、live DB coverage、`readiness_status` 和 `blocked_reasons`。
- resolver 默认仅支持 `jm`，真实合约来自 `MainContractMap.rank=1/provider=rqdata`，不硬编码 `JM2609`。
- resolver 复用 `FuturesTradingParameter` / `FeeMarginRule` gate，要求 `price_tick`、`contract_multiplier`、margin、open/close/close_today commission。
- resolver 要求 actual-contract historical coverage 至少具备 `1m / 5m / 15m` 的 `primary / passed` active bars；缺失时只读 API 返回 blocked reason。
- `LiveSignalEvaluator` 的 `contract` 请求字段改为可选；省略时自动解析 actual-contract，传入 `.MAIN` 或与当前 live target 不一致的合约时返回 422。
- evaluator entry bars 只读 actual-contract live DB；日线方向继续读取 `jm.MAIN` active standard parquet，并在 response `source` 中显式区分。
- evaluator preview item / response 增加 `continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_end`、`trigger_price`；`trigger_price` 只在 `entry_signal` 时来自 actual-contract confirmed live bar close，no-signal preview 不伪装触发价。

边界：

- 8.5-8 仍是 readonly / preview-only。
- 没有新增数据库表或 Alembic migration。
- 没有运行真实 RQData 写入，没有修改已生成 parquet / manifest / checksum。
- 没有写 `StrategySignal`、`SignalEvent` 或 `SignalNotification`。
- 没有接企业微信，没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单或订单草稿。

### 11. 8.5-9：盘后归档设计与 Stage 9 前 final Gate

已完成：

- 新增 `services/quant-api/app/signal/stage9_gate.py`，提供纯只读 `evaluate_stage9_signal_event_gate()`。
- 新增 `services/quant-api/tests/test_stage9_signal_event_gate.py`，覆盖 eligible event、缺真实合约、`.MAIN` 误用、缺 bar / trigger price、quality 非 passed 和 payload basis 脱敏。
- 修复 `services/quant-api/tests/test_signal_events.py` 的 live evaluator preview fixture，补齐 `MainContractMap.rank=1`、`FuturesTradingParameter` 和 `JM2609` 的 `1m / 5m / 15m primary passed` historical coverage，使测试继续验证 preview 不写 `SignalEvent`。
- 盘后归档边界冻结为：RQData after-market direct data 是归档主输入，live DB 只能做 verification / discrepancy evidence；只有 quality Gate passed 才允许后续登记 `data_role=primary`。
- Stage 9 准入 Gate 要求事件为 `signal_created` / `signal_changed`、`signal_status=entry_signal`、具备真实 `actual_contract`、`dominant_mapping_date`、`bar_end`、正数 `trigger_price`、`provider in (rqdata, local_parquet)`、`data_role=primary`、`quality_status.status=passed`。
- payload basis 固定包含 `notice_scope=observation_only`、`trading_instruction=not_trading_instruction`、`auto_order=false`，并过滤 webhook / token / password / cookie / secret 等敏感键或值。

边界：

- 8.5-9 没有新增 migration、表或 API。
- 没有运行真实 RQData 写入、sync 或 readonly 探测。
- 没有修改 parquet / manifest / checksum。
- 没有接企业微信，没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有写 `SignalNotification`，没有发送通知。
- 没有自动下单或订单草稿。

### 12. Stage 9-A：企业微信只读提醒 preview / dry-run adapter

已完成：

- 新增 `services/quant-api/app/signal/stage9_wechat.py`，在 `evaluate_stage9_signal_event_gate()` 之后构造企业微信 robot markdown payload preview。
- 新增 `GET /api/signals/events/{event_id}/stage9-wechat/preview`，只读返回 Gate 结果、blocked reasons、`would_send=false`、`channel=enterprise_wechat`、`notification_recorded=false` 和脱敏 `wechat_payload`。
- 新增 `Stage9WechatPreviewOut` 响应 schema。
- 新增 `services/quant-api/tests/test_stage9_wechat_adapter.py`，覆盖 allowed event、blocked event、API 404、API allowed/blocked、脱敏和不写 `SignalNotification`。

边界：

- Stage 9-A 不读取或打印 `QYWX_WEBHOOK_URL`。
- 不真实发送企业微信。
- 不写 `SignalNotification`。
- 不新增 migration、表或 worker。
- 不修改策略逻辑、回测口径、live evaluator 写入边界或任何 RQData / parquet / manifest 资产。

## 本轮没有做

- 没有真实发送企业微信，也没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单。
- 没有生成订单草稿。
- 没有发送企业微信，也没有写 `SignalNotification`。
- 没有修改策略核心逻辑。
- 没有修改回测口径。
- 没有把 live DB 登记为 trusted historical active。
- 没有新增 ORM 表、migration 或全新前端页面。
- 没有扩大到全品种或多合约池。
- 没有把 `JM2609` 硬编码为长期主力；它只是 `2026-07-07` 的 `MainContractMap.rank=1` 解析结果。
- 没有把 JM V1-B historical scanner 的 `trigger_price` 改为真实合约 close；该绑定仍是后续 Gate。
- 没有实现盘后归档 worker、scheduler 或真实归档写入。
- 没有执行阿里云部署。
- 没有继续推进 Cloudflare Tunnel。
- 没有把全品种下载产物直接标记为全部 active passed。

## 验证计划与结果

本轮验证命令包括：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_actual_contract_bars_pilot.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_jm_v2_parquet.py services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api ruff check services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py services/quant-api/tests/test_actual_contract_bars_pilot.py scripts/rqdata_actual_contract_bars_pilot.py services/quant-api/app/services/rqdata_ingest/bar_sample.py
uv run --project services/quant-api python scripts/rqdata_actual_contract_bars_pilot.py --product jm --trade-date 2026-07-07 --start-date 2026-07-06 --end-date 2026-07-07 --dry-run
uv run --project services/quant-api python scripts/rqdata_main_mapping_sync.py run --product jm --start-date 2026-07-07 --end-date 2026-07-07 --ranks 1
uv run --project services/quant-api python scripts/rqdata_trading_params_sync.py run --contract JM2609 --start-date 2026-07-07 --end-date 2026-07-07
uv run --project services/quant-api python scripts/rqdata_actual_contract_bars_pilot.py --product jm --trade-date 2026-07-07 --start-date 2026-07-06 --end-date 2026-07-07 --run-write
uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_jm_v2_parquet.py services/quant-api/tests/test_rqdata_structured_ingest.py services/quant-api/tests/test_market_data_reader.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_api.py::test_market_workbench_coverage_exposes_actual_contract_view_metadata
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_api.py services/quant-api/tests/test_market_dominant_reader.py services/quant-api/tests/test_market_data_reader.py services/quant-api/tests/test_actual_contract_bars_pilot.py
uv run --project services/quant-api ruff check services/quant-api/app/api/market.py services/quant-api/app/schemas/market.py services/quant-api/app/services/market_workbench.py services/quant-api/app/services/market_dominant_reader.py services/quant-api/tests/test_market_data_api.py services/quant-api/tests/test_market_dominant_reader.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_live_market_reader.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_market_data_api.py services/quant-api/tests/test_market_dominant_reader.py
uv run --project services/quant-api ruff check services/quant-api/app/services/live_target_contracts.py services/quant-api/app/services/live_signal_evaluator.py services/quant-api/app/api/market.py services/quant-api/app/schemas/market.py services/quant-api/app/schemas/signal.py services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_market_data_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage9_signal_event_gate.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_market_data_api.py::test_live_targets_api_resolves_actual_contract_target_and_coverage services/quant-api/tests/test_market_data_api.py::test_live_targets_api_reports_blocked_actual_contract_coverage
uv run --project services/quant-api ruff check services/quant-api/app/signal/stage9_gate.py services/quant-api/app/signal/events.py services/quant-api/app/schemas/signal.py services/quant-api/tests/test_stage9_signal_event_gate.py services/quant-api/tests/test_signal_events.py
npm --prefix apps/quant-web run build
git diff --check
```

结果：

- 8.5-6 / 8.5-6B fixture 测试通过：`8 passed`。
- JM v2 parquet、RQData structured ingest 与 MarketDataReader 相关回归通过：`21 passed`。
- `ruff check` 通过。
- dry-run 输出确认不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- metadata sync 真实写入成功：`success jm: rows=1 files=1`、`success JM2609: rows=1 files=1`。
- real write 输出 `quality_gate=passed`，六周期 `market_data_files` / `data_quality_reports` 登记完成。
- 8.5-7 新增 API 行为测试先按 TDD 失败于缺少 `view_role`，实现后通过：`1 passed`。
- Market API / dominant reader / MarketDataReader / actual-contract pilot 回归通过：`21 passed`。
- 8.5-7 `ruff check` 通过。
- 8.5-8 live evaluator + live market reader 回归通过：`9 passed`。
- 8.5-8 Market API + dominant reader 回归通过：`13 passed`。
- 8.5-8 `ruff check` 通过。
- 8.5-9 Stage 9 signal event Gate 测试通过：`5 passed`。
- Stage 9-A 企业微信 preview adapter 测试通过：`5 passed`。
- 8.5-9 signal events / scanner 回归通过：`10 passed`。
- 8.5-9 live evaluator + live target selected 回归通过：`8 passed`。
- Stage 9-A `ruff check` 通过。
- Web build 通过，Vite 仅保留已有 chunk size warning。
- `git diff --check` 通过。

## 风险与未完成项

- `actual_contract` 仍依赖真实主力映射证据；没有证据时写入 service 会阻断。
- `JM2609` 只是 `2026-07-07` 的真实映射结果，不能硬编码成长期真实主力。
- 主连 bars 与真实合约 bars 若共用 `contract` 语义，会污染 trigger price、提醒 payload 和复盘口径；8.5-6 已在路径和 `MarketDataFile.contract_code` 上强制使用真实合约。
- 本轮没有允许 `quality_status=warning` 进入 primary；自然非交易时段 gap 只作为 `gap_samples` 保留，真实交易时段缺口识别需要后续交易日历 Gate 增强。
- RQData 只读探测也可能触发外部账号权限或连接错误，输出必须继续脱敏。
- Stage 9-A 已完成 guarded preview / dry-run adapter；真实企业微信发送仍需另开任务授权；提醒候选事件必须先通过 `evaluate_stage9_signal_event_gate()`。
- 8.5-7 已让 Web 可见 actual-contract bars，但 Web 可见性不等同于 signal scanner / live evaluator 已绑定真实合约触发价。
- 盘后归档、更多日期窗口和更多合约池必须另开任务并明确授权写入。
- 当前 historical scanner 仍以 `jm.MAIN` 为扫描合约，相关事件会被 Stage 9 Gate 阻断，直到后续显式绑定真实合约 confirmed bar close。

## 下一步

建议进入：

```text
Stage 9-B：企业微信真实发送授权 / 通知记录 / 失败重试设计
```

Stage 9-A 已具备只读 preview adapter。下一步如要推进真实企业微信 smoke，必须单独授权读取 `QYWX_WEBHOOK_URL`，并设计通知记录写入、失败状态、重试策略和脱敏日志；默认仍不自动下单、不生成订单草稿。

## GPT 同步文件

- `tasks/current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/tasks_current.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `services/quant-api/app/signal/stage9_gate.py`
- `services/quant-api/app/signal/stage9_wechat.py`
- `services/quant-api/app/signal/stage9_wechat_delivery.py`
- `services/quant-api/app/signal/stage9_jm_v1b_replay.py`
- `scripts/stage9_wechat_send_once.py`
- `scripts/stage9_jm_v1b_replay_event_once.py`
- `services/quant-api/tests/test_stage9_signal_event_gate.py`
- `services/quant-api/tests/test_stage9_wechat_adapter.py`
- `services/quant-api/tests/test_stage9_wechat_delivery.py`
- `services/quant-api/tests/test_stage9_jm_v1b_replay.py`
- `services/quant-api/tests/test_signal_events.py`
- `services/quant-api/app/services/live_target_contracts.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/tests/test_live_signal_evaluator.py`
- `services/quant-api/tests/test_market_data_api.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/app/services/market_dominant_reader.py`
- `services/quant-api/tests/test_market_data_api.py`
- `services/quant-api/tests/test_market_dominant_reader.py`
- `apps/quant-web/src/pages/data/index.vue`
- `apps/quant-web/src/pages/market/index.vue`
- `apps/quant-web/src/types/data.ts`
- `apps/quant-web/src/types/market.ts`
- `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`
- `scripts/rqdata_actual_contract_bars_pilot.py`
- `services/quant-api/tests/test_actual_contract_bars_pilot.py`
