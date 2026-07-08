# 当前任务同步：STAGE-8.5-DATA-CHAIN-GATE

生成时间：2026-07-07

## 最新状态

`STAGE-8.5-DATA-CHAIN-GATE` 已完成 8.5-0 / 8.5-1 / 8.5-2 文档级闭环、8.5-3 schema 最小代码闭环、8.5-4 RQData 元数据只读方案冻结、8.5-5 主连 + 当前真实主力合约 historical bars 设计冻结、8.5-6 写入试点代码 + dry-run + fixture 测试闭环、8.5-6B JM-only 当前真实主力合约 historical bars 真实最小写入试点、8.5-7 Web Data / Web Market actual-contract 只读消费扩展、8.5-8 live 监听目标合约池 + evaluator 数据源收敛，以及 8.5-9 盘后归档设计与 Stage 9 前 final Gate。

8.5-6B 已同步 `jm / 2026-07-07 / rank=1` 主力映射，解析 `actual_contract=JM2609`，同步 `JM2609` 当日交易参数，并执行真实 `--run-write`。六周期 `1m/5m/15m/30m/60m/1d` canonical bars 已登记为 `provider=rqdata`、`contract_code=JM2609`、`data_role=primary`、`quality_status=passed`。

Stage 9-A guarded preview / dry-run adapter 已完成；Stage 9-B1 受控发送 / 通知记录 / 失败重试框架已完成，但真实企业微信 smoke 仍需 Stage 9-B2 单独指定 eligible `event_id` 并授权运行。8.5-7 只让 Web Data / Web Market 看见 `jm.MAIN` 与 `JM2609` 的 coverage、quality、data_version、file_path 和 latest bar boundary；8.5-8 已让 live target resolver 和 live evaluator preview 显式对齐 `MainContractMap.rank=1` actual-contract，省略 contract 时自动解析，`.MAIN` 或错配合约返回 422，并在 preview response 输出 `bar_end` 和 entry-signal-only `trigger_price`。8.5-9 已新增 `evaluate_stage9_signal_event_gate()`，只有通过 Gate 的 entry signal 事件才可作为企业微信只读提醒候选。Stage 9-A `GET /api/signals/events/{event_id}/stage9-wechat/preview` 仍只返回 markdown payload preview，不读取 webhook、不发送通知、不写 `SignalNotification`；Stage 9-B1 新增 `GET /api/signals/events/{event_id}/stage9-wechat/notification` 只读查询通知状态。

2026-07-07 文档路线修正补充：

- Web 托管当前主线改为阿里云方案，Cloudflare Access 降级为历史备选 / 暂停。
- Web Market 已新增「品种研究」只读面板，读取本地 PostgreSQL 的 RQData 结构化元数据，不改变 K 线 active 读取入口。
- 全品种下载已出现一批 manifest / processed summary，但仍按“进行中 / 待审计 / 可进入 active”分层，不能直接写成全部可信完成。
- 当前后续路线为：Stage 9-B2 企业微信单条真实 smoke 授权、Stage 10 Web Market 策略展示增强、Stage 11 本地长期运行、Stage 12 阿里云 Web 托管设计、Stage 13 可信回测复核、Stage 14 Web 复盘增强、Stage 15 可选 Codex git 自动化。

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

## 关键输出

更新：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `tasks/current.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ALIYUN_WEB_HOSTING_PLAN.md`
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
- `services/quant-api/app/services/live_target_contracts.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/tests/test_live_signal_evaluator.py`
- `services/quant-api/app/signal/stage9_gate.py`
- `services/quant-api/tests/test_stage9_signal_event_gate.py`
- `services/quant-api/tests/test_signal_events.py`

本轮新增/调整 Market 只读 API coverage 字段、Web Data / Web Market 展示、live target resolver、Stage 9 只读准入 Gate 和对应测试；没有新增 migration，没有运行真实 RQData 写入，没有新增全新页面。

## 已完成结论

### 8.5-0 Stage 8 输出审查

- `signal_events` 已具备 append-only 事件账本基础。
- Stage 8 输出不足以直接承接 Stage 9。
- JM V1-B historical scan 当前仍以 `jm.MAIN` 为扫描合约。
- `live_signal_evaluator` 仍是 preview-only，不写正式信号或事件。

### 8.5-1 数据新口径冻结

- `continuous_contract` 用于研究、回测背景、连续图和日线方向。
- `actual_contract` 用于 live 触发、trigger price、企业微信 payload 和复盘入口。
- live DB 只做盘中观察和 preview，不登记 `market_data_files`，不自动进入 active historical。
- 盘后归档必须单独经过 quality Gate 后才能进入 historical active。

### 8.5-2 schema / model 变更 Plan

- 推荐在 `strategy_signals` 和 `signal_events` 中显式支持真实合约绑定字段。
- 不依赖任意 JSON payload 约定承接 Stage 9。
- 不在 Stage 9 中临时解析合约映射。

### 8.5-3 schema / model 最小实现

- `strategy_signals` 和 `signal_events` 已新增显式 contract context 字段。
- 普通信号扫描和 JM V1-B 扫描会写入 `product`、`continuous_contract`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source`、`data_role`。
- `.MAIN` 主连只写入 `continuous_contract`，不伪装为 `actual_contract`。
- `/api/signals/latest` 和 `/api/signals/events` 输出新增字段并支持新增过滤参数。

### 8.5-4 RQData 元数据只读 Plan

已冻结：

- V1-B 默认目标品种池先锁定为 `jm`，不扩成全品种。
- metadata 源复用现有模型：
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

### 8.5-5 historical bars 设计冻结

已冻结：

- `continuous_contract=jm.MAIN` 继续用于研究主连、连续图、日线方向和 historical scan 背景。
- `actual_contract` 必须来自 `MainContractMap.rank=1`；缺少映射证据时不能用样例合约替代。
- 当前真实主力合约 historical bars 后续必须作为独立 canonical bars 资产，不混入 `jm.MAIN` 文件，不复用 `jm.MAIN` 的 `contract` 语义。
- 首批 periods 与 JM v2 对齐：`1m / 5m / 15m / 30m / 60m / 1d`。
- 8.5-6 写入试点建议优先下载真实主力 `1m` 标准 bars，再聚合生成更高周期；如改用 RQData 直接多周期下载，必须说明取舍并补测试。
- `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close。
- 8.5-5 不授权写 parquet、manifest、checksum、DB rows 或 active 登记。

### 8.5-6 写入试点代码 + dry-run

已完成：

- 新增 `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`。
- 新增 `scripts/rqdata_actual_contract_bars_pilot.py`。
- 新增 `services/quant-api/tests/test_actual_contract_bars_pilot.py`。
- dry-run 默认不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- fake client / SQLite 测试覆盖缺主力映射、`.MAIN` 误用、缺交易参数、quality failed 不登记 primary、quality passed 登记真实 `actual_contract`。
- 真实 `--run-write` 入口已在 8.5-6B 明确授权后使用。

### 8.5-6B 真实写入试点

已完成：

- `actual_contract=JM2609`
- `dominant_mapping_date=2026-07-07`
- window：`2026-07-06..2026-07-07`
- raw rows：690
- manifest：`data/manifests/rqdata_actual_contract_bars_jm_JM2609_20260706_20260707.csv`
- row_count：`1m=690`、`5m=138`、`15m=46`、`30m=24`、`60m=14`、`1d=3`
- 六周期 canonical `market_data_files` / `data_quality_reports` 均为 passed。
- 文件路径均使用真实合约 `JM2609`，没有写入 `jm.MAIN` 路径。
- DuckDB 可读性检查通过。

质量口径：

- 自然午休、夜盘、节假日和周末间隔记录为 `gap_samples`，不计入 `missing_bars`。
- 重复 bar、OHLC 异常、负 volume、负 open_interest 仍阻断 primary 登记。

### 8.5-7 Web Data / Web Market actual-contract 只读消费扩展

已完成：

- Market coverage 输出 `view_role`、`continuous_contract`、`actual_contract`、`latest_bar_time`、`data_version`、`data_role`、`file_path`。
- Web Market 普通行情模式使用真实合约；回测深链才允许主连研究视图。
- Web Market 当前主力卡片和数据质量卡片显示主连研究合约、真实合约、quality、data_version、file_path、latest bar boundary。
- Web Data 数据文件表新增“视图”和“最新边界”，用于区分 `jm.MAIN` 与 `JM2609`。
- 新增 TDD API 行为测试，覆盖 `jm.MAIN` 与 `JM2609` 同时出现在 coverage，且 `JM2609` 不被硬编码为长期主力。

### 8.5-8 live 监听目标合约池 + evaluator 数据源收敛

已完成：

- 新增 `services/quant-api/app/services/live_target_contracts.py`。
- 新增 `GET /api/v1/market/live/targets`，只读输出 live target readiness、actual-contract coverage、live coverage 和 blocked reasons。
- `LiveSignalEvaluator` 的 `contract` 可省略；省略时解析当前 actual-contract，`.MAIN` 或错配合约返回 422。
- evaluator preview response 输出 `continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_end` 和 entry-signal-only `trigger_price`。
- evaluator entry bars 读取 actual-contract live DB；daily direction 继续读取 `jm.MAIN` active standard parquet，并在 `source` 中显式区分。
- 没有写 `StrategySignal` / `SignalEvent` / `SignalNotification`，没有企业微信，没有真实 RQData 写入。

### 8.5-9 盘后归档设计与 Stage 9 前 final Gate

已完成：

- 新增 `services/quant-api/app/signal/stage9_gate.py`。
- 新增 `services/quant-api/tests/test_stage9_signal_event_gate.py`。
- 修复 `services/quant-api/tests/test_signal_events.py` 的 live evaluator preview fixture，补齐 8.5-8 readiness metadata 后继续验证 preview 不写 `SignalEvent`。
- `evaluate_stage9_signal_event_gate()` 只读返回 `allowed`、`blocked_reasons` 和脱敏 `payload_basis`。
- Gate 要求 `signal_created` / `signal_changed`、`entry_signal`、真实 `actual_contract`、`dominant_mapping_date`、`bar_end`、正数 `trigger_price`、`provider in (rqdata, local_parquet)`、`data_role=primary`、`quality_status.status=passed`。
- payload basis 固定表达 `observation_only` 和 `not_trading_instruction`，并过滤 webhook / token / password / cookie / secret。
- 盘后归档设计冻结：RQData after-market direct data 是主输入，live DB 仅作为 verification / discrepancy evidence；真实归档写入、worker、scheduler 另开任务授权。

### Stage 9-A 企业微信只读 preview / dry-run adapter

已完成：

- 新增 `services/quant-api/app/signal/stage9_wechat.py`。
- 新增 `GET /api/signals/events/{event_id}/stage9-wechat/preview`。
- 新增 `Stage9WechatPreviewOut`。
- Gate 通过时生成企业微信 robot markdown payload preview；Gate 阻断时只返回 `blocked_reasons`，不生成可发送 payload。
- response 固定 `would_send=false`、`channel=enterprise_wechat`、`notification_recorded=false`。
- 新增 `services/quant-api/tests/test_stage9_wechat_adapter.py`，覆盖 allowed / blocked / API 404 / 脱敏 / 不写 `SignalNotification`。

### Stage 9-B1 企业微信受控发送 / 通知记录 / 失败重试框架

已完成：

- 新增 `services/quant-api/app/signal/stage9_wechat_delivery.py`。
- 新增 `scripts/stage9_wechat_send_once.py`，默认 dry-run 不读取 webhook、不写通知、不发送。
- 新增 migration `services/quant-api/alembic/versions/20260708_0018_stage9_wechat_notifications.py`，扩展 `signal_notifications` 的 `event_id`、attempt、retry 和 HTTP 状态字段。
- 新增 `GET /api/signals/events/{event_id}/stage9-wechat/notification`，只读查询最近企业微信通知记录。
- 发送前必须通过 `evaluate_stage9_signal_event_gate()`；Gate 阻断写 `skipped`，缺 webhook 写 `failed/missing_webhook`，失败未达 3 次写 `retry_pending`。
- 同一事件幂等键为 `enterprise_wechat:signal_event:{event.id}`。

边界：

- 没有执行真实企业微信 smoke。
- 没有批量发送历史事件，没有 worker / scheduler。
- 没有自动下单，没有订单草稿。
- `QYWX_WEBHOOK_URL` 只允许从环境变量读取，不进入日志、DB、文档或测试输出。

验证：

- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage9_wechat_delivery.py`：8 passed。
- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage9_wechat_adapter.py services/quant-api/tests/test_stage9_signal_event_gate.py services/quant-api/tests/test_stage9_wechat_delivery.py`：18 passed。
- `uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py services/quant-api/tests/test_signal_scanner_api.py`：10 passed。
- `uv run --project services/quant-api ruff check ...`：passed。
- `cd services/quant-api && uv run python -m alembic upgrade head`：已升级到 `20260708_0018`。
- Stage 9-B 文件范围 `git diff --check`：passed；全局 `git diff --check` 受无关 `services/quant-api/app/main.py` 尾部空白阻断。

## 验证结果

已运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_actual_contract_bars_pilot.py
uv run --project services/quant-api python scripts/rqdata_actual_contract_bars_pilot.py --product jm --trade-date 2026-07-07 --start-date 2026-07-06 --end-date 2026-07-07 --dry-run
uv run --project services/quant-api python scripts/rqdata_main_mapping_sync.py run --product jm --start-date 2026-07-07 --end-date 2026-07-07 --ranks 1
uv run --project services/quant-api python scripts/rqdata_trading_params_sync.py run --contract JM2609 --start-date 2026-07-07 --end-date 2026-07-07
uv run --project services/quant-api python scripts/rqdata_actual_contract_bars_pilot.py --product jm --trade-date 2026-07-07 --start-date 2026-07-06 --end-date 2026-07-07 --run-write
uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_jm_v2_parquet.py services/quant-api/tests/test_rqdata_structured_ingest.py services/quant-api/tests/test_market_data_reader.py
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
- JM v2 parquet、RQData structured ingest 与 MarketDataReader 回归通过：`21 passed`。
- dry-run 输出确认不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- metadata sync 成功：`success jm: rows=1 files=1`、`success JM2609: rows=1 files=1`。
- real write 成功：`quality_gate=passed`。
- 8.5-7 Market API / dominant reader / MarketDataReader / actual-contract pilot 回归通过：`21 passed`。
- 8.5-7 `ruff check` 通过。
- 8.5-8 live evaluator + live market reader 回归通过：`9 passed`。
- 8.5-8 Market API + dominant reader 回归通过：`13 passed`。
- 8.5-8 `ruff check` 通过。
- 8.5-9 Stage 9 Gate 测试通过：`5 passed`。
- Stage 9-A 企业微信 preview adapter 测试通过：`5 passed`。
- 8.5-9 signal events / scanner 回归通过：`10 passed`。
- 8.5-9 live evaluator + selected live target 回归通过：`8 passed`。
- Stage 9-A `ruff check` 通过。
- Web build 通过，Vite 仅保留已有 chunk size warning。
- `git diff --check` 通过。

## 本轮没有做

- 没有真实发送企业微信，也没有读取或打印 `QYWX_WEBHOOK_URL`。
- 没有自动下单或生成订单草稿。
- 没有把 live DB 登记为 historical active。
- 没有修改策略核心逻辑或回测口径。
- 没有把 `JM2609` 硬编码为长期真实主力。
- 没有把 JM V1-B scanner 的 `trigger_price` 切换为真实合约 close。
- 8.5-7 没有修改已生成 parquet / manifest / checksum。
- Stage 9-A 没有读取或打印 `QYWX_WEBHOOK_URL`，没有发送企业微信，没有写 `SignalNotification`。
- 8.5-9 没有实现盘后归档 worker、scheduler 或真实归档写入。

## 下一步建议

下一步进入：

```text
Stage 9-B：企业微信真实发送授权 / 通知记录 / 失败重试设计
```

Stage 9-A 已具备只读 preview adapter。Stage 9-B 若继续推进，必须单独授权读取 `QYWX_WEBHOOK_URL`，并设计通知记录写入、失败状态、重试策略和脱敏日志；默认仍不自动下单、不生成订单草稿。

## 建议 GPT 上传文件

- `tasks/current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/CODEX_HANDOFF.md`
- `services/quant-api/app/signal/stage9_wechat.py`
- `services/quant-api/tests/test_stage9_wechat_adapter.py`
- `docs/DATA_CENTER.md`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/app/services/market_dominant_reader.py`
- `services/quant-api/app/services/live_target_contracts.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/tests/test_market_data_api.py`
- `services/quant-api/tests/test_live_signal_evaluator.py`
- `services/quant-api/app/signal/stage9_gate.py`
- `services/quant-api/tests/test_stage9_signal_event_gate.py`
- `services/quant-api/tests/test_signal_events.py`
- `services/quant-api/tests/test_market_dominant_reader.py`
- `apps/quant-web/src/pages/data/index.vue`
- `apps/quant-web/src/pages/market/index.vue`
- `apps/quant-web/src/types/data.ts`
- `apps/quant-web/src/types/market.ts`
- `services/quant-api/app/services/rqdata_ingest/actual_contract_bars_pilot.py`
- `scripts/rqdata_actual_contract_bars_pilot.py`
- `services/quant-api/tests/test_actual_contract_bars_pilot.py`
