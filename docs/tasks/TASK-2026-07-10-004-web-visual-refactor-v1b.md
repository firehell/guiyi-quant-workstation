# TASK-2026-07-10-004：Web V1-B 视觉与信息架构重构

## 元信息

| 字段 | 值 |
|---|---|
| Task ID | `TASK-2026-07-10-004-web-visual-refactor-v1b` |
| Branch | `codex/web-visual-refactor-v1b` |
| Baseline | `a7df3aaca38d7f66445102538c1ae3ddfc0e4a17` |
| Status | `DELIVERY_READY` |
| Scope | Vue/Naive UI 模板、样式、图表主题、视觉文档 |

## 交付结论

已从“基础暗色页面”升级为克制科技感、高密度、可扫描的桌面研究工作站；不改 API、路由语义、数据链路或交易边界。

## 关键变更

1. 设计系统：分层 tokens、方向/状态分离、Naive UI 具体色值适配、CSS 图表主题桥接。
2. 全局框架：四组导航、折叠侧栏、无新依赖 SVG 图标、边界徽章、面包屑、快捷入口和时钟。
3. Dashboard：只使用现有 Dashboard API 真实字段，重组指标、最近报告/扫描、系统边界和 Live Target。
4. Signal：扫描参数可折叠，宽表固定关键列并内部滚动，行操作收敛为“详情 + 更多”，多/空使用 `DirectionTag`。
5. Market Chart：两行工具栏、provider/data_role/quality/data_version/last bar lineage、容器查询 Live Target、1024px 右栏下移。
6. 可信研究页：Backtest/Review 将盈亏方向色与审计/风险状态分开；Market/Data 保留 actual/continuous/provider/quality 语义；Runtime 保持只读。

## 变更范围

- 生产前端：`apps/quant-web/src/`
- 视觉参考：`apps/quant-web/mockups/`
- 规范与交接：`workstation/team/UX_VISUAL_SPEC.md`、`tasks/current.md`、`docs/gpt/*`、`docs/CODEX_HANDOFF.md`

本任务未修改 `services/`、`packages/`、`data/`、Alembic、`.env` 或任何运行凭据。

## 测试

| 检查 | 结果 |
|---|---|
| 6 个 Node test files / 27 tests | passed |
| `npm --prefix apps/quant-web run build` | passed |
| `git diff --check` | passed |
| 11 路由只读 browser smoke | passed |
| 1440/1280/1024 K 线浏览器验收 | passed |
| Browser console | 0 errors / 0 warnings |

## 证据

- `output/playwright/web-refactor-dashboard-1440.png`
- `output/playwright/web-refactor-dashboard-1024.png`
- `output/playwright/web-refactor-signal-1280.png`
- `output/playwright/web-refactor-market-chart-1440.png`
- `output/playwright/web-refactor-market-chart-1280.png`
- `output/playwright/web-refactor-market-chart-1024.png`

## 风险与后续

- 当前 build 仍提示约 651 kB 公共 chunk；本轮未引入新运行依赖，拆包需独立性能任务。
- 界面已通过工程验收，仍建议用户以本地长时间使用感受完成最终主观验收。
- `research_only` 字段的 schema/API 语义拆分继续后置，本轮没有伪装完成。
