# WEB-V1-14-00 基线与冲突审计

日期：2026-07-26
任务：`WEB-V1-14-RESEARCH-WORKSPACE-POLISH`
分支：`codex/v1-web-research-workspace-polish`
基线：`origin/main@1805af2e0741381ba4ef16b89c59e5fe4d2a8267`

```text
WEB_V1_14_BASELINE_INVENTORIED
WEB_V1_14_COLLISION_MATRIX_READY
NO_PRODUCT_CODE_CHANGE
```

## 1. 执行边界

- 仅修改 Web 展示、交互、测试与本任务文档。
- 不修改 Market API 语义、Profile fail-closed、Browser/Research、historical/live、actual/continuous、lineage 对账或 `MAX_BARS_PER_REQUEST`。
- 不修改数据库、migration、Parquet、Profile binding、Runtime、scheduler、SignalEvent、通知、策略或指标公式。
- 不自动 push、merge、deploy，不切换正式 Runtime commit。
- HTDY original 始终是 historical/browser 下的 observation-only 重绘观察层；不进入严格研究、live、alert、notification 或交易。

## 2. 当前 Web 事实

当前 `apps/quant-web` 已具备 Vue 3、Naive UI、Lightweight Charts、全局 tokens、PageShell、共享状态组件、Dashboard、Market、Signal、Review、Backtest、Data、Runtime、Settings，以及 mock/readonly 浏览器 Gate。本任务不是重写 Web。

Market 已具备并必须保留：

- actual/continuous、historical/live、browser/research、Profile 状态机；
- research 缺 Profile fail-closed；
- bars/indicator lineage token 对账；
- viewport 有界加载、live 20 秒刷新与 visibility pause；
- EMA/MACD/ATR、HTDY observation-only、marker/deep-link；
- SignalEvent、Review、Runtime 只读上下文；
- error redaction 和非自动交易边界。

## 3. Worktree 与 HTDY 冲突矩阵

### 3.1 本任务

| 项 | 值 |
|---|---|
| Worktree | `/private/tmp/guiyi-v1-web-research-workspace-polish` |
| Branch | `codex/v1-web-research-workspace-polish` |
| HEAD | `1805af2e0741381ba4ef16b89c59e5fe4d2a8267` |
| Base | `origin/main@1805af2e0741381ba4ef16b89c59e5fe4d2a8267` |

手册建议的外置盘 worktree 可创建但当前 Codex 沙箱不能在其中写入；因此按隔离 worktree 的沙箱回退规则重建到 `/private/tmp`，Git 分支与基线不变。

### 3.2 HTDY Step 1 checkpoint

| 项 | 值 |
|---|---|
| Worktree | `/Volumes/扩展盘/GuiyiWorktrees/guiyi-v1-htdy-realtime-closure` |
| Branch | `codex/v1-htdy-realtime-closure` |
| HEAD | `4cbb769ec645211fbca372770de4c02be499763d` |
| Main ancestry | `origin/main` 是该 HEAD 的 ancestor |
| Commits | `d4f51314` contract freeze；`4cbb769e` production kernel |

与本任务的直接重叠：

| 路径 | HTDY 状态 | WEB-V1-14 处理 |
|---|---|---|
| `apps/quant-web/src/components/kline/KlineChart.vue` | Step 1 已修改 | Step 5 前吸收 `4cbb769e`，不覆盖 Golden/overlay |
| `apps/quant-web/src/utils/indicators.ts` | Step 1 已修改 | 不改变公式；仅随 checkpoint 集成 |
| `apps/quant-web/src/utils/mainIndicators.ts` | Step 1 已修改 | 保留 observation-only policy 与 preference 过滤 |
| `apps/quant-web/tests/htdyStep1Golden.test.ts` | Step 1 新增 | 纳入每轮 indicators 回归 |
| `apps/quant-web/tests/indicators.test.ts` | Step 1 已修改 | 不重写预期数值 |
| `apps/quant-web/tests/mainIndicators.test.ts` | Step 1 已修改 | 保留 mode/policy 回归 |

`/private/tmp/guiyi-htdy-original-realtime-alert@ebf172cc` 另有 `chart.vue`、`mainIndicators.ts`、Signal 页面和后端广泛改动。该分支不是本手册指定的 Step 1 checkpoint，且包含不同业务范围；本任务不吸收、不修改其后端或状态文档。最终集成必须由独立 review 重新比较，不在 Web polish commit 中顺手合并。

## 4. 基线验证

### 4.1 Unit

```text
command: cd apps/quant-web && npm test
exit_code: 0
tests: 121
passed: 120
failed: 0
skipped: 1
result: PASS
```

唯一 skip 为既有可选 `HTDY_GOLDEN_BUNDLE`，不代表 HTDY 语义通过或失败。

### 4.2 Production build

```text
command: cd apps/quant-web && npm run build
exit_code: 0
result: PASS
largest_chunk: charting-vendor 533.82 kB / gzip 180.54 kB
bundle_topology: acyclic
```

### 4.3 Mock E2E

首次直接运行因候选 Vite 未启动而得到 `ERR_CONNECTION_REFUSED`；启动隔离 `127.0.0.1:5174` 后重跑：

```text
command: cd apps/quant-web && npm run test:e2e
exit_code: 0
passed: 14
failed: 0
result: PASS
```

该初次失败是验收环境缺少 Web server，不是产品回归；失败输出保留，不改写为通过。

### 4.4 截图矩阵

使用 mock API 在以下 18 个组合截图：

```text
pages: Market / Signal / Review / Backtest / Data / Runtime
viewports: 1440x900 / 1280x720 / 1024x768
console_errors: 0
page_level_horizontal_overflow: 0
local_artifacts: apps/quant-web/output/playwright/baseline-*.png
```

截图属于本地验收证据，不是 Runtime 部署证据。

## 5. UI 问题分类

| 分类 | 页面/问题 | 处理 |
|---|---|---|
| KEEP | Browser/Research、Profile fail-closed、actual/continuous、historical/live | 不改变状态机 |
| KEEP | viewport、marker、live refresh、lineage token 对账 | 回归保护 |
| KEEP | HTDY observation-only 与 repaint 风险 | 独立风险提示 |
| POLISH | RadioButton selected 蓝底文字对比不足 | Step 2 统一 token/theme |
| POLISH | Context Bar 在 1024/1280 信息拥挤 | Step 3 分为上下文与资格 |
| POLISH | provider/primary/raw version 默认抢占主视觉 | Step 3 下沉 evidence drawer |
| POLISH | Quote strip 数字层级与间距不均 | Step 5 调整 |
| REWORK | 右栏首 Tab 名为“策略”，内容实际是确定性盘面事实 | Step 5 显示名改为“盘面” |
| REWORK | warning/冲突缺少“影响、允许、阻断、下一步” | Step 4 质量影响卡 |
| REWORK | 页面级 warning 与 Kline 内提示重复 | Step 4 完整卡 + 紧凑标记 |
| REWORK | mock Market 截图出现两条 `lineage_token` TypeError 可见 Alert | Step 3 补全真实形状的 mock lineage，并加 E2E 回归 |
| DEFER_V2 | AI 概率、历史相似、参数平台、Experiment | 本任务不做 |
| DEFER_V2 | 持仓、账户、下单、撤单、交易执行 | 永久不进入 V1 |
| BLOCKED_BY_HTDY | `KlineChart.vue`、`indicators.ts`、`mainIndicators.ts` | Step 5 前集成已提交 Step 1 checkpoint |
| BLOCKED_BY_DATA | 若 JM 1D research/Profile 仍冲突 | 另开 data/backend 任务，不在 Web 分支隐藏 |

## 6. 原型采用/拒绝矩阵

参考：

`/Users/zhangzhao/WorkBuddy/2026-07-18-21-31-14/prototypes/quant-web-redesign.html`

| 原型能力 | 结论 |
|---|---|
| `--gy-*` 暗色 token、分层密度、Context Bar、详情 Drawer | 采用设计思想，合并到现有体系 |
| selected/tab/focus 视觉、K 线居中、研究侧栏 | 改造后采用，必须通过对比度与语义 Gate |
| Dashboard 固定流程、快速继续 | 仅在真实 route/事实存在时采用 |
| Signal/Backtest 数值与状态 | 仅消费真实 API，不复制原型样例 |
| 持仓、账户、P&L、下单 | 拒绝 |
| RSI/KDJ/BOLL、AI score、历史相似度 | 未接入，V1 拒绝 |
| 原型内硬编码策略结论和胜率 | 拒绝，不得作为产品数据 |

## 7. 允许路径

- `apps/quant-web/src/styles/**`
- `apps/quant-web/src/style.css`
- `apps/quant-web/src/components/common/**`
- `apps/quant-web/src/components/market/**`
- `apps/quant-web/src/components/kline/**`
- `apps/quant-web/src/pages/market/**`
- `apps/quant-web/src/pages/{dashboard,signal,review,backtest,data,runtime}/**`
- `apps/quant-web/src/utils/market*`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/tests/**`
- `apps/quant-web/e2e/**`
- `docs/tasks/WEB-V1-14-*.md`
- `docs/superpowers/plans/2026-07-26-web-v1-14-research-workspace-polish.md`

## 8. 禁止路径

- `services/quant-api/app/models/**`
- `services/quant-api/alembic/versions/**`
- `packages/quant-core/**`
- `services/quant-api/app/services/live_*`
- `services/quant-api/app/signal/**`
- `services/quant-api/app/notification*`
- `services/quant-api/app/*scheduler*`
- `deploy/**`
- `data/**`
- `configs/data_profiles/**`
- report 14/15 与既有 Stage 6 receipt

## 9. 下一 Gate

严格按以下顺序继续：

```text
JM 1D 只读诊断
→ Design System 对比度
→ Market Context/Evidence
→ Quality Impact
→ HTDY checkpoint 集成
→ Kline/盘面右栏
→ 跨页面一致性
→ 性能/可访问/readonly
→ 最终验收
```
