# WEB-V1-00：只读盘点与最终 Plan

更新时间：2026-07-21  
分支：`cursor/web-v1-final`  
基线 commit：`07b446495a2f451d475c6f1e820c66c3e02b75c1`（手册审查基线 `115101e3` 之后已合入 S6-05/S6-06）  
Worktree：`/Volumes/扩展盘/GuiyiWorktrees/guiyi-web-v1-final`

```text
WEB_V1_BASELINE_INVENTORIED
NO_CODE_CHANGE
```

---

## 1. 页面与路由清单

| Path | Name | Component |
|------|------|-----------|
| `/dashboard` | dashboard | `pages/dashboard/index.vue` |
| `/data` | data | `pages/data/index.vue` |
| `/market` | market | `pages/market/index.vue` |
| `/market/chart` | market-chart | `pages/market/chart.vue` |
| `/strategy` | strategy | `pages/strategy/index.vue` |
| `/backtest` | backtest | `pages/backtest/index.vue` |
| `/backtest/batch` | backtest-batch | `pages/backtest/batch.vue` |
| `/signal` | signal | `pages/signal/index.vue` |
| `/runtime` | runtime | `pages/runtime/index.vue` |
| `/review` | review | `pages/review/index.vue` |
| `/settings` | settings | `pages/settings/index.vue` |

侧栏分组（`MainLayout.vue`）：研究分析 / 策略回测 / 数据运维 / 系统。  
`market-chart`、`backtest-batch` 不在侧栏，经子页进入。

---

## 2. 各页面真实 API（摘要）

| 页面 | 主要 API |
|------|----------|
| Dashboard | `/api/v1/dashboard/*`、runtime/health 摘要 |
| Data | `/data/sources|exchanges|instruments|contracts|download-tasks|quality-reports|coverage`（挂载时 7 路并行、无界） |
| Market list | instruments/contracts/quote readiness |
| Market chart | bars、coverage、indicators、live refresh、signal markers、runtime observation |
| Strategy | `GET /strategies/registry` |
| Backtest | tasks/reports/trades/orders/equity；JM quick tasks |
| Batch | batch backtest create/status/WS |
| Signal | scan、JM scan、signals list、SignalEvents、WS、lifecycle ack |
| Review | reviews CRUD、lineage bars、attachments |
| Runtime | `/api/runtime/health` |
| Settings | 本地 preference；测试连接应走 health |

---

## 3. 能力分类（当前事实）

| 能力 | 分类 | 说明 |
|------|------|------|
| 已有报告 / Review / Market historical bars | formal research 展示 | 只读消费已冻结 lineage |
| JM V1-B 历史扫描 / 通用扫描 | research-only | 非 live-confirmed |
| 前端 EMA21「多头观察」 | observation-only（当前误标为策略状态） | 非 StrategySignal |
| HTDY original | observation-only / rejected candidate | 仅 Historical/Browser |
| Live confirmed bars / SignalEvent live_confirmed | live-confirmed | 不得与 replay 混淆 |
| Batch suitability / 苏冰模板 | research-only / legacy（待 07 裁定） | 非自动调参 |
| Stage 5 rejected | rejected | 不得写成 validated |
| 无 machine capability 的 registry 项 | 默认 research-only | Registry ≠ validated |

---

## 4. 现有测试清单

前端 `apps/quant-web/tests/`（`node --test`，14 文件）：

- network、barTime、chartInit、indicators、macdOverride、mainIndicators
- htdyGoldenSample、marketChartWindow、marketSignalSelection
- marketRuntimeObservation、runtimeHealth、runtimeObservationAdapter
- reviewDeepLink、reviewFoundation

基线运行：`85 tests / 84 pass / 1 skipped / 0 fail`。

无 Playwright / `test:e2e`。根 `tests/` 仅工程 pytest。

---

## 5. 性能风险

1. Data 首屏 `Promise.all` 全量加载（含无界 coverage）。
2. coverage/quality/tasks 前端假分页，DOM/内存无界。
3. Market Live 20s 刷新需验证无重叠、hidden 暂停。
4. 大表一次渲染风险（Data/Signal/Batch）。

---

## 6. 交互风险

1. Market 列表过度依赖双击进 K 线。
2. URL 状态：`signal_layer` 等未完整 sync。
3. Signal 多 source_mode 同页无强隔离。
4. Review `report_id` 解析但未用于自动选中。
5. 快速切换可能 stale async 覆盖（Market/Review）。
6. 无统一 PageShell / route fallback。

---

## 7. 数据 / Profile / lineage / quality 边界风险

1. Data 展示物理 `file_path`；Market quality failed 文案可拼接 path。
2. Research 缺 Profile 需 fail-closed（待 03 强化）。
3. Live 指标「待 C3」——未复用 `historical_live_context_v1`。
4. Batch 是否满足 formal Profile/passed/lineage 待 07 证据裁定。

---

## 8. 错误与敏感信息风险

1. `apiError` 原样透传后端 detail。
2. Data coverage / task error_message 可能含路径。
3. Production API 成功日志需收敛。
4. Settings 不得显示 token；attachment 不得暴露本机任意路径。

---

## 9. 拟修改文件（后续步骤）

```text
apps/quant-web/src/layouts/MainLayout.vue
apps/quant-web/src/components/common/**
apps/quant-web/src/api/request.ts
apps/quant-web/src/utils/network.ts
apps/quant-web/src/pages/data/**
apps/quant-web/src/pages/market/**
apps/quant-web/src/pages/strategy/**
apps/quant-web/src/pages/backtest/**
apps/quant-web/src/pages/signal/**
apps/quant-web/src/pages/review/**
apps/quant-web/src/pages/runtime/**
apps/quant-web/src/pages/dashboard/**
apps/quant-web/src/pages/settings/**
apps/quant-web/tests/**
apps/quant-web/package.json  # e2e scripts
docs/tasks/WEB-V1-*.md
```

必要时最小只读后端：

```text
services/quant-api/app/api/data_center.py
services/quant-api/app/schemas/data_center.py
services/quant-api/app/repositories/data_center.py
services/quant-api/app/api/strategies.py / schemas（capability 只读）
services/quant-api/tests/**（定向）
```

---

## 10. 后续顺序 Plan

| Step | Gate |
|------|------|
| WEB-V1-01 | `WEB_GLOBAL_FOUNDATION_READY` / `WEB_ERROR_REDACTION_READY` |
| WEB-V1-02 | `WEB_DATA_CENTER_BOUNDED` / `NO_PHYSICAL_PATH_EXPOSURE` |
| WEB-V1-03 | `WEB_MARKET_STATE_MACHINE_READY` / `WEB_MARKET_LINEAGE_FAIL_CLOSED` |
| WEB-V1-04 | `WEB_MARKET_LIVE_OBSERVATION_READY` / `NO_FRONTEND_SIGNAL_OVERCLAIM` |
| WEB-V1-05 | `WEB_STRATEGY_CAPABILITY_BOUNDARY_READY` / `NO_REGISTRY_EQUALS_VALIDATED` |
| WEB-V1-06 | `WEB_BACKTEST_REPORT_CLOSED_LOOP_READY` / `WEB_BACKTEST_FORMAL_RESEARCH_BOUNDARY_READY` |
| WEB-V1-07 | `BATCH_BACKTEST_FORMAL_READY` 或 `BATCH_BACKTEST_RESEARCH_ONLY` |
| WEB-V1-08 | `WEB_SIGNAL_EVENT_TIMELINE_READY` / `NO_HISTORICAL_LIVE_CONFUSION` |
| WEB-V1-09 | `WEB_REVIEW_EXACT_LINEAGE_READY` / `WEB_REPORT_TRADE_REVIEW_ROUNDTRIP_READY` |
| WEB-V1-10 | `WEB_RUNTIME_OBSERVABILITY_READY` / `WEB_CONNECTION_SETTINGS_READY` |
| WEB-V1-11 | `WEB_BROWSER_SMOKE_READY` / `WEB_READONLY_REAL_BACKEND_SMOKE_READY` |
| WEB-V1-12 | `WEB_V1_READY` 或 `WEB_V1_PARTIAL` |

---

## 11. 需要最小只读后端 API 补差的地方

1. **Data coverage/quality/tasks**：服务端分页 + 筛选；`file_path` 默认不返回或可关闭（保持旧 endpoint 兼容）。
2. **Strategy registry**：只读 capability / validation outcome 字段（无可靠 machine source 则前端默认 research-only）。
3. **Live 指标 C3**：优先复用已有 `historical_live_context_v1`；不足再加只读 endpoint。
4. **Runtime**：scheduler/archive 已在 health schema；前端补展示即可，后端通常无需改。

禁止：migration、写 DB/Parquet、改策略/回测 Gate、真实通知发送。

---

## 12. 必须保持不改

- `data/raw/`、report 14/15 历史结论、task 23 冻结项
- 策略公式、回测撮合与成本口径
- Stage 6 T4/T5/T6/T7 状态（Web 只准确显示 pending）
- `.env`、凭据、真实部署配置
- `main` 直接修改；自动 push/merge/deploy
- 提前宣称 `JM_RUNTIME_READY` / 策略盈利 / 可实盘

---

## 基线检查原始结果

| 检查 | 结果 |
|------|------|
| `git status` | clean，`cursor/web-v1-final` |
| `preflight.sh --json` | passed=7，warn=1（`data/parquet` missing，worktree 预期） |
| `npm test` | 84 pass / 1 skipped |
| `npm run build` | **阻塞**：worktree 无 `node_modules`，`vue-tsc: command not found`（未安装、未伪造通过） |
| `git diff --check` | clean |

后续实现步骤将在 worktree 内执行 `npm install` 以解除 build 阻塞。
