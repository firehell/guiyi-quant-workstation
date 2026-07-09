# NEXT_STEPS.md

生成时间：2026-07-08
用途：冻结当前阶段顺序，供浏览器 GPT 持续拆 Codex 任务。

## 1. 总原则

```text
先数据，后信号；
先事件，后提醒；
先真实合约绑定，后企业微信；
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
| 阶段 8.5 | 数据主链路扩展 Gate | done / 8.5-0..8.5-9 complete | 是 |
| 阶段 8.6 | 全品种下载结果审计与 active Gate 分层 | code-level readonly audit ready / Cursor download pending | 是 |
| 阶段 9-A | 企业微信只读提醒 preview / dry-run adapter | done / real send still unauthorized | 是 |
| 阶段 9-B | 企业微信真实发送 / 通知记录 / 失败重试 | B2 historical replay event written / real send blocked by missing webhook | 是 |
| 阶段 10 | Web Market 策略展示增强 | 10-A/10-B done / code-level readonly | 是 |
| 阶段 11 | 本地长期运行 / worker / scheduler / runtime dashboard | 11-B/11-C/11-D done / Web dashboard readonly complete | 是 |
| 阶段 12 | 阿里云 Web 托管设计与远程 health smoke | pending | 是 |
| 阶段 13 | 可信回测主线复核 | 13-A/B/D done / 13-E blocked by JM2609 trading parameter gap | 是 |
| 阶段 14 | Web 复盘闭环增强 | pending | 是 |
| 阶段 15 | Codex git commit / push 自动化 | optional | 可选 |

## 3. 最近完成阶段

Stage 2 已完成：

- JM v2 六周期 `1m/5m/15m/30m/60m/1d` 已写入 raw / standard parquet。
- data_version 为全窗口 `20230103_20260707_v2`。
- 六周期均登记为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`。
- coverage audit 结论为 `can_enter_stage3=true`。

Stage 3 已完成代码级闭环：

- `DATA-CONVERGE-3A-ACTIVE-FILTER-TESTS`：默认读取只允许 `rqdata/local_parquet + primary + quality_status != failed`。
- `WEB-DATA-3B-DATA-PAGE-SMOKE`：Web Data 页面可查看覆盖、质量、行数、data_version 和文件路径。

Stage 4A / 4B / 5 已完成 live 数据骨架：

- live 1m 入库设计与最小实现已完成。
- live 多周期聚合已完成。
- live 表不登记 `market_data_files`，默认 Market / Backtest / Signal 读取行为保持不变。
- live 数据不自动混入 historical active。

Stage 6A / 6B 已完成显式 live 查看和只读 evaluator：

- Web Market 支持 `historical` / `live` 显式模式，默认仍为 historical。
- `live_signal_evaluator` 只返回 preview，不写 `StrategySignal` / `SignalNotification` / `SignalEvent`。
- entry bars 来自 live DB，日线方向来自 active primary historical `1d`。

Stage 7 已完成通达信 XMA 风险审查：

- 原始 `XMA`、`ZK1/ZD1/ZD2`、`VAR23` 标记为 `forbidden_for_backtest_signal`。
- Stage 7 没有把 XMA PoC 接入正式策略、回测、signal scanner、live evaluator、`signal_events`、企业微信或 Web Market。

Stage 8 已完成 `signal_events`：

- 新增 `SignalEvent` / `signal_events` append-only 事件账本。
- 支持 `signal_created`、`signal_changed`、`signal_status_changed`。
- 新增只读 API：`GET /api/signals/events` 和 `GET /api/signals/{signal_id}/events`。
- Stage 8 没有接企业微信，没有读取或打印 `QYWX_WEBHOOK_URL`，没有生成订单或自动下单。

Stage 8.5-0 / 8.5-1 / 8.5-2 / 8.5-3 / 8.5-4 / 8.5-5 / 8.5-6 / 8.5-6B / 8.5-7 / 8.5-8 / 8.5-9 已完成数据主链路 Gate 的审查、口径冻结、schema Plan、schema 最小实现、RQData 元数据只读方案、historical bars 设计冻结、JM2609 真实写入试点、Web 只读消费扩展、live/evaluator 数据源收敛和 Stage 9 前 final Gate：

- `strategy_signals` 与 `signal_events` 已具备显式 contract context 字段。
- `.MAIN` 主连只写入 `continuous_contract`，不伪装为 `actual_contract`。
- API 已输出并支持过滤 `product`、`continuous_contract`、`actual_contract`、`provider`、`source`、`data_role`。
- 8.5-4 已锁定 V1-B 默认目标品种池为 `jm`，metadata 源复用 `FuturesContractUniverse`、`MainContractMap`、`FuturesContinuousContractMap`、`FuturesTradingParameter` 和 `FeeMarginRule`。
- 8.5-5 已锁定 `jm.MAIN` 只作为研究主连资产；当前真实主力合约 historical bars 后续必须独立写入、独立质量报告、独立 active Gate。
- 8.5-8 已新增 `GET /api/v1/market/live/targets` 和 live target resolver，`LiveSignalEvaluator` 默认解析 `MainContractMap.rank=1` actual-contract，拒绝 `.MAIN` 或错配合约。
- 8.5-9 已新增 `evaluate_stage9_signal_event_gate()`，只读判断 Stage 9 提醒候选事件，不读取 webhook、不发送通知、不写通知记录。

当前额外事实：

- Web Market 已新增「品种研究」只读面板：`/api/v1/market/research/*` 读取本地 PostgreSQL 的 RQData 结构化元数据，不改变 K 线 active 读取入口。
- 全品种下载已出现一批主连 historical manifest、actual-contract manifest 和 processed summary；这些产物仍属于“进行中 / 待审计”，不能直接等同于全部通过 active Gate。
- Stage 8.6 已新增只读审计器和 CLI：`full_universe_active_gate.py` / `rqdata_full_universe_active_gate_audit.py`。该入口只读已有 manifest、DB 登记、quality report 和 canonical parquet，输出 `data/reports/stage8_6_*` 报告，不调用 RQData、不写 parquet、不登记 active。
- Web 托管当前主线改为阿里云；`docs/CLOUDFLARE_WORKSTATION_ACCESS.md` 保留为历史备选，当前主线见 `docs/ALIYUN_WEB_HOSTING_PLAN.md`。

## 4. 当前阶段：Stage 13-E 被交易参数缺口阻断

Stage 8.5 数据主链路 Gate 已完成。Stage 8.6 全品种 active Gate 只读审计已完成代码级闭环。Stage 9-A 企业微信只读 preview / dry-run adapter 已完成。Stage 9-B1 受控发送 / 通知记录 / 失败重试框架已完成。Stage 9-B2 单条历史回放 eligible event 生成 + observation-only 真实 smoke 已完成（`event_id=1`, HTTP 200, sent）。Stage 10-A / 10-B 已完成 Web Market 策略展示增强的只读闭环。Stage 11-B / 11-C / 11-D 已完成本地运行脚本增强、runtime health API 和 Web runtime dashboard。Stage 13-A/B 已完成可信回测主线文档审计和只读 trust audit service / CLI。Stage 13-D 已完成报告可信 lineage 修复。Stage 13-E 已尝试重跑一份 `JM V1-B fast-entry 15m` 新报告，但被 `JM2609` 交易参数 `price_tick` 缺口阻断。

当前实际处于两条推进线：

1. Stage 13-F：只读审计 `JM2609` / `2026-04-24` 附近 trading parameters 覆盖，必要时设计受控 metadata repair；完成后重跑 Stage 13-E。
2. Stage 12：阿里云 Web 托管设计与远程 health smoke。

Stage 13-A/B/D 当前能力：

- 新增 `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`。
- 新增 `services/quant-api/app/backtest/trust_audit.py` 和 `scripts/backtest_trust_audit.py`。
- 审计器按 `report_id` 或 `task_no` 只读读取已入库 BacktestReport / Trade / Order。
- 输出 `audit_status=passed / warning / failed`，覆盖 data lineage、execution policy、trade/order、equity/drawdown、fee/slippage、contract multiplier、trusted metrics、reproducibility 和 sensitive output。
- Stage 13-D 新增 `lineage_mapping` 审计；`BacktestTrade` 显式记录 `entry_signal_source`、`entry_order_no`、`exit_order_no`、`lineage_status`，`BacktestOrder` 显式记录 `trade_no`、`leg`、`lineage_source`、`mapping_status`。
- `result_converter` / `BacktestService.persist_result()` 会基于显式 trade 字段、`strategy_execution_events` 和 vn.py order rows 写入 `lineage_summary`，不从 `open_time - interval` 倒推信号时间。
- 旧报告不自动回填 Stage 13-D lineage 字段；真实复核应优先重跑一份新报告再 audit。
- Stage 13-E 已新建 `task_id=21`、`task_no=BTV-20260709131810-c9905541`，但没有生成新 `report_id`；失败类型为 `TradingParameterMissingError`，原因是 `JM2609` 在 `2026-04-24` 缺 `FuturesTradingParameter.price_tick`。
- CLI 默认 `readonly=true`、`would_write_db=false`、`would_run_rqdata=false`、`would_run_backtest=false`、`would_send_notifications=false`。
- Stage 13-A/B/D 没有新增策略、没有调参、没有运行 RQData 写入、没有修改 parquet / manifest / quality report、没有改 Web、没有接企业微信、没有接实盘或自动下单。

Stage 9 目标仍是让提醒事件能明确表达 product、研究主连、真实主力合约、触发价、数据源、质量状态和 confirmed bar 边界。

Stage 10-B 当前能力：

- `/market/chart` 信号 marker 可点击并高亮选中。
- 右侧当前信号列表可作为 marker 点击 fallback。
- 选中信号后只读查询 `/api/signals/{signal_id}/events` 与 `/api/signals/events/{event_id}/stage9-wechat/notification`。
- notification 404 显示为空状态，不触发发送。
- Stage 10-B 不写 `SignalEvent` / `SignalNotification`，不读取 webhook，不发送企业微信，不接 worker / scheduler。

Stage 11-C 当前能力：

- 新增只读 `GET /api/runtime/health`，覆盖 PostgreSQL、Redis、RQ queue、RQ worker、live ingest / aggregation checkpoints、企业微信 notification retry summary。
- response 固定声明 `readonly=true`、`would_start_services=false`、`would_enqueue_jobs=false`、`would_send_notifications=false`。
- DB 或 Redis 不可用返回结构化 `failed`；RQ 无 worker、live checkpoint failed、notification due retry 返回 `degraded`；live checkpoint / notification 无记录返回 `unknown`，不视为失败。
- `scripts/dev-healthcheck.sh` 已新增 runtime health HTTP 检查。
- Stage 11-C 不新增 migration、scheduler、worker 或 loop，不运行 live ingest / aggregation，不运行 retry-pending，不读取 webhook，不修改策略、回测、scanner 或 active 数据入口。

Stage 11-D 当前能力：

- 新增 Web `/runtime` 页面和左侧菜单「运行状态」。
- 前端只读消费 `GET /api/runtime/health`，展示 overall、PostgreSQL、Redis、RQ queue、RQ worker、live ingest / aggregation checkpoint、企业微信 notification retry summary。
- 页面显式展示 `readonly=true`、`would_start_services=false`、`would_enqueue_jobs=false`、`would_send_notifications=false`。
- 页面只提供手动刷新，不提供启动服务、入队任务、retry-pending 或企业微信发送入口。
- Stage 11-D 不修改后端 API 契约，不新增 migration、scheduler、worker 或 retry 逻辑，不运行 live ingest / aggregation，不读取 webhook，不发送企业微信，不修改策略、回测、scanner 或 active 数据入口。
- 验证已通过：前端 runtime helper 测试、前端 build、后端 runtime health 回归、`scripts/dev-healthcheck.sh` 语法检查和 `git diff --check`。
- 浏览器 smoke 已补齐：仅启动 API + Web，不启动 worker；Playwright 打开 `http://127.0.0.1:5173/runtime` 成功，`GET /api/runtime/health` 返回 HTTP 200，console error/warn 为 0，页面无“启动 / 入队 / 重试 / 发送”动作按钮。smoke 时本机 PostgreSQL / Redis 未运行，因此页面真实展示 failed 状态而非加载失败。

已完成：

- `8.5-0 Stage 8 输出审查`：done / docs-level。
- `8.5-1 数据新口径冻结与文档更新`：done / docs-level。
- `8.5-2 schema / model 变更 Plan`：done / docs-level。
- `8.5-3 schema / model 最小实现`：done / code-level。
- `8.5-4 RQData 元数据与目标品种池只读 Plan`：done / docs-level。
- `8.5-5 主连 + 当前真实主力合约 historical bars 设计冻结`：done / docs-level。
- `8.5-6 historical 数据写入最小闭环代码 + dry-run`：done / code-level dry-run。
- `8.5-6B JM-only 当前真实主力合约 historical bars 真实写入试点`：done / real write complete。
- `8.5-7 Web Data / Web Market actual-contract 数据消费扩展`：done / code-level readonly。
- `8.5-8 live 监听目标合约池 + evaluator 数据源收敛`：done / code-level readonly。
- `8.5-9 盘后归档设计与 Stage 9 前 final Gate`：done / code-level readonly gate + docs-level archive design。

关键文档：

- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `tasks/current.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`

当前结论：

- 当前 `signal_events` 已具备 `product`、`continuous_contract`、`actual_contract`、`dominant_mapping_date`、`bar_start`、`bar_end`、`trigger_price`、`provider`、`source` 等显式字段。
- JM V1-B historical scan 当前仍以 `jm.MAIN` 为扫描合约，`actual_contract` 缺少真实映射证据时保持 `NULL`，`trigger_price` 仍来自主连 bar close，不足以承接 Stage 9。
- 8.5-4 已明确 `actual_contract` 只能来自 `MainContractMap.rank=1`，`dominant_mapping_date` 对应 `MainContractMap.trade_date`，trading params 必须覆盖 `price_tick`、`contract_multiplier`、margin、commission。
- 8.5-5 已明确 `trigger_price` 后续只能来自 `actual_contract` 的 confirmed historical / live bar close；`jm.MAIN` close 只能作为研究背景。
- 8.5-6 已完成代码 + dry-run + fixture 测试闭环；默认 dry-run 不构造 RQData client、不打开 DB、不写 parquet / manifest / DB、不登记 primary。
- 8.5-6B 已完成 JM-only 当前真实主力合约 historical bars 真实最小写入试点：`actual_contract=JM2609`、`dominant_mapping_date=2026-07-07`、`1m/5m/15m/30m/60m/1d` 六周期均已登记为 `provider=rqdata`、`data_role=primary`、`quality_status=passed`。
- 8.5-7 已完成 Web Data / Web Market actual-contract 只读消费扩展：Market coverage 输出 `view_role`、`continuous_contract`、`actual_contract`、`latest_bar_time`、`data_version`、`data_role`、`file_path`，Web Data / Web Market 已显式展示 `jm.MAIN` 与 `JM2609` 的视图差异和覆盖边界。
- 8.5-8 已完成 live/evaluator 数据源收敛：live target resolver 只读输出 target readiness、coverage 和 blocked reasons；evaluator preview 可省略 `contract` 自动解析 actual-contract，并显式输出 `bar_end` 与 entry-signal-only `trigger_price`。
- 8.5-9 已完成 Stage 9 前 final Gate：事件必须通过 `evaluate_stage9_signal_event_gate()` 才能成为企业微信只读提醒候选。
- Stage 9-A 已完成 guarded preview / dry-run adapter；Stage 9-B1 已完成受控发送 / 通知记录 / 失败重试框架；Stage 9-B2 已完成历史回放 eligible event 写入、dry-run preview 和单条 observation-only 真实 smoke。

## 5. 下一步任务

### 阶段路线对齐

用户规划的 0-23 任务按当前仓库状态归并如下：

| 用户任务 | 当前归属 | 处理口径 |
|---|---|---|
| 0 文档路线修正：移除 Cloudflare 当前主线 | 当前文档修正 | 阿里云为主线，Cloudflare 降级历史备选 |
| 1 通达信指标风险审查 | Stage 7 done | 原始 XMA 禁入正式信号 |
| 2 通达信指标 Python 本地实现 | 后续 Stage 7.5 | 只允许 strictly backward-looking 重写 |
| 3 通达信指标 Web 副图展示 | Web Market 增强 | 仅 observation-only，不作为信号 |
| 4-6 signal_events 模型 / 写入 / API WebSocket | Stage 8 done + later WS enhancement | 事件账本已具备，WS 增强后置 |
| 7-9 企业微信通知设计 / 只读提醒 / 记录重试 | Stage 9 | 必须走 `evaluate_stage9_signal_event_gate()` |
| 10-13 Web Market 策略展示 / marker / 侧栏 / 联动 | Stage 10 | 先只读展示，再接信号联动 |
| 14-17 本地长期运行 / worker / scheduler / dashboard / 脚本 | Stage 11 | 独立 Plan，避免影响数据可信度 |
| 18-20 真实交易时段观察 / 多周期观察 / 策略版本治理 | Stage 11-12 后 | 先 observability，再治理 |
| 21 可信回测主线复核 | Stage 13 | 优先修指标、trade、equity 对齐 |
| 22 Web 复盘闭环增强 | Stage 14 | 基于可信回测和 marker |
| 23 Codex git commit / push 自动化 | Stage 15 optional | 只做受控辅助，不替代人工 checkpoint |

### Stage 9-A：企业微信只读提醒 preview / dry-run adapter

目标是在 `evaluate_stage9_signal_event_gate()` 后面实现受控提醒 preview adapter。Stage 9-A 已完成第一版，只做 preview / dry-run，不真实发送，不读取 `QYWX_WEBHOOK_URL`，不写 `SignalNotification`。

已完成：

- 新增 `services/quant-api/app/signal/stage9_wechat.py`。
- 新增 `GET /api/signals/events/{event_id}/stage9-wechat/preview`。
- Gate 通过时生成企业微信 robot markdown payload preview。
- Gate 阻断时返回 `blocked_reasons`，不生成可发送 payload。
- response 固定 `would_send=false`、`channel=enterprise_wechat`、`notification_recorded=false`。
- payload 固定表达观察提醒 / 非交易指令 / 不自动下单，并显示真实合约、bar_end、trigger_price、quality_status 和数据源。
- 新增 `services/quant-api/tests/test_stage9_wechat_adapter.py`。

仍禁止：

- 不运行真实 RQData 写入。
- 不修改已生成 parquet / manifest 资产。
- 不把 `jm.MAIN` close 当作真实合约 trigger price。
- 未授权前不真实发送企业微信。
- 不修改策略逻辑和回测口径。
- 不把 live evaluator preview 直接持久化为正式事件。
- 不读取或打印 `QYWX_WEBHOOK_URL`。
- 不写 `SignalNotification`。
- 不把 `JM2609` 硬编码为长期真实主力。
- 不自动下单，不生成订单草稿。

Stage 9-B1 已完成：

- 新增 `services/quant-api/app/signal/stage9_wechat_delivery.py`。
- 新增 `scripts/stage9_wechat_send_once.py`，默认 dry-run 不读 webhook、不写 DB、不发送。
- 扩展 `signal_notifications`，记录 `event_id`、尝试次数、失败类型、HTTP 状态、下次重试时间。
- 新增 `GET /api/signals/events/{event_id}/stage9-wechat/notification`，只读查询企业微信通知状态。
- 使用 fake sender 覆盖 sent / skipped / missing webhook / retry_pending / failed / retry due / 幂等。

Stage 9-B2 已完成的前置与 smoke 结果：

- 新增 `services/quant-api/app/signal/stage9_jm_v1b_replay.py`。
- 新增 `scripts/stage9_jm_v1b_replay_event_once.py`，默认 dry-run 不写库、不读 webhook、不发送。
- replay dry-run 找到 `JM2609 / 15m / 2026-07-03T14:30:00 / short / trigger_price=1279.5`，Gate `allowed=true`。
- `--run-write --confirm-historical-replay --confirm-observation-only` 写入 `event_id=1`、`signal_id=3`，事件 `source_mode=jm_v1b_historical_replay`。
- `scripts/stage9_wechat_send_once.py --event-id 1` dry-run 返回 `allowed=true`、`blocked_reasons=[]`。
- 已对 `event_id=1` 执行一次 observation-only 真实 smoke，通知记录 `status=sent`、`response_status_code=200`、`attempt_count=1`、`sent_at=2026-07-08T15:25:01.328589+00:00`。
- 该事件仅用于 Stage 9 企业微信链路 smoke，不代表实时 / 前向提醒绩效。

后续 Stage 9 复核：

- 只做只读状态查询或单条事件级验证。
- 不批量发送历史事件，不启用 worker / scheduler，不运行 retry-pending。

建议测试：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage9_wechat_adapter.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_stage9_signal_event_gate.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_signal_events.py services/quant-api/tests/test_signal_scanner_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_live_signal_evaluator.py services/quant-api/tests/test_market_data_api.py::test_live_targets_api_resolves_actual_contract_target_and_coverage services/quant-api/tests/test_market_data_api.py::test_live_targets_api_reports_blocked_actual_contract_coverage
uv run --project services/quant-api ruff check services/quant-api/app/signal/stage9_wechat.py services/quant-api/app/signal/stage9_gate.py services/quant-api/app/api/signals.py services/quant-api/app/schemas/signal.py services/quant-api/tests/test_stage9_wechat_adapter.py
git diff --check
```

## 6. Stage 9 前置 Gate

进入企业微信真实发送前必须满足：

- `signal_events` 能显式区分 product / continuous contract / actual contract。
- `trigger_price` 明确来自 actual contract。
- `bar_end` 已确认。
- `quality_status != failed`，严格场景优先 `passed`。
- Stage 9-A preview payload 已能显示真实合约，不表达实盘指令。
- 进入 Stage 9-B 真实发送前，仍必须单独授权 webhook 读取和发送 smoke。
- webhook 只从环境变量读取，不进文档、DB、日志或 payload。
- V1 仍不自动下单。
- 真实 RQData `--run-readonly` 或 historical write 均需单独授权。
- 事件必须通过 `evaluate_stage9_signal_event_gate()`。

## 7. 下一轮 GPT 上传文件

- `tasks/current.md`
- `docs/DATA_UNIVERSE_AND_ARCHIVE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/ALIYUN_WEB_HOSTING_PLAN.md`
- `docs/PROJECT_INVENTORY.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/gpt/tasks_current.md`
- `docs/gpt/CURRENT_STATE.md`
- `services/quant-api/app/signal/stage9_gate.py`
- `services/quant-api/app/signal/stage9_wechat.py`
- `services/quant-api/tests/test_stage9_signal_event_gate.py`
- `services/quant-api/tests/test_stage9_wechat_adapter.py`
- `services/quant-api/app/services/signal_scanner.py`
- `services/quant-api/app/services/live_target_contracts.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/app/services/live_market_reader.py`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/schemas/signal.py`
- `services/quant-api/tests/test_live_signal_evaluator.py`
- `services/quant-api/tests/test_market_data_api.py`
- `services/quant-api/alembic/versions/20260707_0016_signal_contract_context.py`
