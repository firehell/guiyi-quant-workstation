# Cursor Review Foundation Gap Report（C5-06A）

生成时间：2026-07-19  
任务：`CURSOR-REVIEW-FOUNDATION-C506A`  
Cursor Gate：`CURSOR_REVIEW_FOUNDATION_PREPARED`

**不得**宣称 `STRATEGY_REVIEW_CLOSED_LOOP_READY`。

## 1. 本轮已交付（PREPARED）

| 能力 | 位置 |
|---|---|
| ReviewFoundation 类型 / 纯函数 | `apps/quant-web/src/types/reviewFoundation.ts`、`utils/reviewFoundation.ts` |
| 正式上下文面板 | `apps/quant-web/src/components/review/ReviewFoundationPanel.vue` |
| Review 页挂载 + deep-link 解析复用 | `apps/quant-web/src/pages/review/index.vue` |
| Backtest 元数据轻量扩展 | `apps/quant-web/src/pages/backtest/index.vue`（policy/profile/execution） |
| 四态 fixture | `apps/quant-web/tests/fixtures/reviewFoundation/` |
| 前端单测 | `reviewFoundation.test.ts`、`reviewDeepLink.test.ts`（9 passed） |
| 可选 API 透传 | `BacktestReportOut` + `report_api_payload` / `_review_foundation_passthrough` |
| 后端单测 | `test_review_foundation_c506a.py`（4 passed） |

## 2. 字段矩阵

| 字段 | UI | API | 说明 |
|---|---|---|---|
| strategy / version | PREPARED | PREPARED | 来自 report 顶层 / metadata |
| indicator policy | PREPARED | PREPARED | status/snapshot/reason；legacy → warning + unavailable snapshot |
| Profile binding | PREPARED | PREPARED | profile_id + binding_snapshot 有无 |
| signal bar | PREPARED | 部分 | 依赖 trade `entry_signal_time`；Review source 未必有 |
| next bar fill | PREPARED | 部分 | open_time / fill_policy；缺则 unavailable |
| cost model | PREPARED | 部分 | metadata `cost_model_version` |
| execution timing | PREPARED | PREPARED | metadata |
| OOS window id | PREPARED(UI/透传) | GAP(写入) | 可展示/透传；无真实 OOS report 写入 |
| walk-forward fold id | PREPARED(UI/透传) | GAP(写入) | 同上 |
| candidate status | PREPARED(UI/透传) | GAP(写入) | 同上 |
| hard reject reason | PREPARED(UI/透传) | GAP(写入) | 同上 |
| SKIPPED_BY_FROZEN_HARD_REJECT | PREPARED(UI/fixture) | GAP(写入) | fixture + 透传键；无运行时判定落库 |
| lineage unavailable / warning | PREPARED | PREPARED | exact-bars / lineage error fail-closed |

## 3. 明确 GAP（留给 Codex X5-06B）

1. 真实 HTDY candidate / OOS / WF report 与 fold 绑定。
2. 运行时 hard reject → `review_skip_status=SKIPPED_BY_FROZEN_HARD_REJECT` 写入。
3. Review source trade 统一暴露 `entry_signal_time`。
4. 用真实 report/trade/window 做 closed-loop 复验（不得在前端重算策略）。

## 4. 边界

- 未写 DB / 未改 report14 / 未硬编码未来 report id
- 缺失字段永不伪造，只显示 unavailable
- 复用现有 exact-bars，不重构设计系统
