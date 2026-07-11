# TASK-2026-07-11-003：Web 主图多指标切换（EMA overlay）

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-003-web-overlay-indicators |
| GitHub Issue | #11 |
| Branch | codex/web-overlay-indicators |
| Worktree | /Volumes/扩展盘/guiyi-parallel/web-indicators |
| Status | REQUIREMENT_READY |
| Baseline | main @ f29de0dd（含 WEB-VISUAL-REFACTOR） |

## 1. 任务状态

REQUIREMENT_READY

## 2. 任务类型

普通功能开发 / 交互视觉规范

## 3. 参与角色

- 必须：前端开发、测试专家
- 不需要：数据工程师、live runtime

## 4. 背景

`KlineChart.vue` 主图固定渲染 EMA21 曲线与 price line overlays；行情页副图仅 `['macd']`。本轮只做 **Step 1**：主图 overlay 开关（EMA21 曲线、price lines），默认保持现有可见行为。

## 5. 目标

1. 主图工具栏：EMA21 曲线 on/off、price line overlays on/off
2. 默认状态与当前生产一致（全部开启）
3. 保持十字线联动、hover 读数、1440/1280/1024 布局
4. **不做** Step 2：副图泛化、volume_ratio、signal_score

## 6. 不做事项

- 不修改 `services/`、`packages/`、`data/`
- 不改 API、回测/信号/风控计算
- 不恢复 ATR Tab 或实现 volume_ratio（后续任务）
- 不自动 push/merge/deploy

## 7. 涉及模块

**允许修改**：

- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/components/kline/`（可新增小组件）
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/src/utils/indicators.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/tests/`
- `docs/tasks/TASK-2026-07-11-003-web-overlay-indicators.md`
- `tasks/current.md`

**禁止修改**：

- `services/`、`packages/`、`data/`
- `Alembic/`、`.env`

## 8. 产品需求

- 工具栏控件清晰、不挤占 K 线区域
- 关闭 EMA 后 crosshair 快照不再显示 EMA 或显示 N/A
- 开关状态可 URL 或 localStorage 持久化（可选，非必须）

## 9. 量化业务规则

无（纯展示）

## 10. 数据影响

无

## 11. 技术方案

1. 新增 props：`showEmaLine`、`showPriceLineOverlays`（或统一 `mainIndicatorToggles`）
2. `KlineChart.vue`：条件渲染 EMA LineSeries；overlays 过滤
3. `chart.vue`：工具栏 checkbox/toggle + 绑定 props
4. 扩展 `indicators.test.ts` 如有新纯函数

## 12. 交互视觉要求

- 遵循现有 tokens / 暗色主题
- 工具栏与 WEB-VISUAL-REFACTOR 两行工具栏风格一致

## 13. 安全权限要求

- 无 `.env` 变更

## 14. 开发步骤

1. Plan：组件 props 与 UI 位置
2. 实现 toggle + 条件渲染
3. Node tests + build
4. 浏览器 smoke：`/market/chart?symbol=jm&contract=JM2609&period=15m`

## 15. Codex Plan Prompt

```
只读 Plan。必读 apps/quant-web/src/components/kline/KlineChart.vue、pages/market/chart.vue、utils/indicators.ts。
任务：主图 EMA/price line overlay 开关，Step 1 only。
输出：props 设计、UI 位置、测试计划。不改后端。
```

## 16. Codex Dev Prompt

```
按 Plan 实现 overlay 开关。默认全开。跑 node tests 与 npm build。
禁止改 services/packages/data。
```

## 17. CodeBuddy 执行 Prompt

```
worktree: /Volumes/扩展盘/guiyi-parallel/web-indicators
branch: codex/web-overlay-indicators
不 push/merge/deploy。
```

## 18. 测试清单

### 18.0 自动化测试命令

```bash
for f in apps/quant-web/tests/*.test.ts; do node --test "$f"; done
npm --prefix apps/quant-web run build
git diff --check
```

- [ ] Node tests passed
- [ ] Vite build passed
- [ ] EMA 开关关闭后主图无 EMA 线
- [ ] 十字线联动仍正常

## 19. 验收标准

- 默认行为与改前一致
- console 0 error on market chart smoke
- 仅修改 apps/quant-web/

## 20. 风险点

- 破坏 linked-crosshair 联动
- toggle 后未 resize 导致 chart 空白

## 21. 交付记录

- 合并目标：main（四条线中 **第一个** PR）
