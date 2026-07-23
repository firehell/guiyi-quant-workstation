# WEB-V1-13 品牌与个人研究操控台闭环

更新时间：2026-07-22

分支：`codex/web-v1-13-personal-workspace`

基线：`main@b442ed5a`

## 边界

本任务是 WEB-V1-12 之后的增量封板，不改写历史验收结论。Web 仍是单用户、本地优先、只读研究与人工复盘工作台，不增加自动交易、真实通知、数据写入、migration、worker、scheduler 或部署变更。

后端改动只允许落在 Dashboard、SignalEvent、Review、Backtest 的兼容式只读查询、schema 和测试；不得修改 Profile binding、行情资产、指标公式、策略语义、回测口径或 SignalEvent 生成。

## 顺序 Gate

| 步骤 | 目标 | 通过条件 |
|---|---|---|
| W13-00 | 最新 main 基线 | clean、unit/build/mock E2E/preflight/secrets 通过 |
| W13-01 | 品牌唯一入口 | 原件留存、Brand 组件、favicon、无临时 Logo |
| W13-02 | Workspace Shell | 工作/研究/系统保障导航，共享只读 System Pulse |
| W13-03 | 行动型 Dashboard | 明确事实驱动的建议动作与 JM 15m 快捷入口 |
| W13-04 | Market 收敛 | 上下文、证据、四 Tab 右栏分离且无行情语义回归 |
| W13-05 | 研究往返 | report/event 与 chart/review 的可刷新、可返回深链 |
| W13-06 | 状态与质量收口 | 服务端分页、无 token、错误脱敏、a11y/性能基线 |
| W13-07 | 真实只读验收 | 候选 API/Web、PostgreSQL read-only、仅 GET/HEAD/OPTIONS |

每步 Gate 全绿后建立本地 checkpoint commit。不得自动 push、merge 或 deploy。真实环境、数据关系或外部依赖不足时 fail-closed，并发布 `WEB_V1_13_PARTIAL`，不得用 mock 替代真实 Gate。

## 已确认前置事实

- W13-00 基线：Web unit 105 passed / 1 skipped，build passed，mock E2E 9 passed；preflight 0 failed / 1 warning；secrets passed。
- 用户已提供专业款几何字母 G 效果图，W13-01 可继续；原件保存在品牌目录，Web 使用可缩放派生 symbol。
- W13-07 不使用 `dev-up.sh`，不执行 Alembic，不启动 worker/scheduler。
- `CODEX_TASKS.md` 不属于当前 canonical，不重新创建。

## 当前进度

- W13-00 至 W13-06 已按顺序通过并建立本地 checkpoint。
- W13-07 已在候选 API `8010`、Vite `5177` 和 PostgreSQL `default_transaction_read_only=on` 下完成真实只读验收；API/浏览器网络仅出现 GET/HEAD/OPTIONS。
- report `15` / trade `3199` / review `9` 的真实往返通过；服务端分页后按 `trade_id` 精确恢复交易的缺口已修复并回归。
- 真实库没有任何 SignalEvent→ReviewNote 关联样本。event→chart→“尚无复盘”→event 的降级往返通过，但不能据此发布真实 Signal round-trip Ready。
- 最终状态为 `WEB_V1_13_PARTIAL`；WEB-V1-12 的 `WEB_V1_BROWSER_ACCEPTANCE_PASSED / WEB_V1_READY` 作为历史结论保留，不被本增量改写。

## 回滚

只按步骤 checkpoint 反向撤销，不使用 destructive reset，不清理或覆盖用户修改。品牌源、历史验收报告和真实 Gate 证据均保留可追溯性。
