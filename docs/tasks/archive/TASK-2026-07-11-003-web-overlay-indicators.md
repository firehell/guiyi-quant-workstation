# TASK-2026-07-11-003：Web C 线主图指标与统一 EMA 接入

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-003-web-overlay-indicators |
| GitHub Issue | #11 |
| Branch | codex/web-overlay-indicators |
| Worktree | /Volumes/扩展盘/guiyi-parallel/web-indicators |
| Status | C2_CLOSEOUT_FIX_READY_FOR_GPT_REVIEW |
| Baseline | main @ f29de0dd（含 WEB-VISUAL-REFACTOR） |

## 1. 任务状态

C2_CLOSEOUT_FIX_READY_FOR_GPT_REVIEW

## 2. 任务类型

前后端功能开发 / K 线工作台主图指标展示框架 / 统一 EMA 只读接入

## 3. 背景与当前数据流

GPT 已将方向 C 定义为两层：

1. Web 展示框架、指标选择器、图表状态和实时轮询可以先做。
2. EMA 和火天大有的正式计算必须接入 B 线统一指标内核，Web 不能复制一套正式公式。

当前仓库现状：

- `apps/quant-web/src/pages/market/chart.vue` 负责读取 historical/live bars、coverage、信号 marker 和回测 marker。
- `apps/quant-web/src/components/kline/KlineChart.vue` 被 Market / Backtest / Review 共享，负责 Lightweight Charts 主图、副图、marker、linked crosshair 和 hover context。
- 原实现固定创建 EMA21 LineSeries，`HoverKlineContext` 固定暴露 `ema21`。
- MACD 保持副图固定显示，本轮不进入主图多选。

## 4. 目标

本任务已完成 C0+C1+C2：

1. 对齐当前任务源和文档。
2. 建立主图指标定义模型和 registry。
3. 支持 EMA10 / EMA21 / EMA60 主图多选，默认 EMA21 可见。
4. 主图 hover strip 和右侧十字线快照显示 active indicator values。
5. Market 页提供“主图指标”弹出多选面板和“趋势均线”快捷入口。
6. 使用版本化 localStorage 保存 UI 偏好。
7. 火天大有以 disabled 占位展示，明确等待 B 线冻结。
8. C2 新增只读 `GET /api/v1/market/indicators`，后端复用 `quant-core` 统一 EMA 内核。
9. C2 前端消费后端指标 series，只渲染 `ready && valid` 的点；warm-up / invalid 点在 hover 和右侧快照显示为 `-`。
10. C2 closeout fix 修正 EMA 能力语义、完整 active asset 计算锚点、API 语义字段和稳定性测试。

## 5. 不做事项

- 不修改 `data/`。
- 不改 PostgreSQL、Alembic、DuckDB、Parquet 或 active 数据入口。
- 不改策略、回测、信号、风控、企业微信。
- 不实现火天大有公式。
- 不做 Market WebSocket。
- 不把 live 数据混入 historical active。
- 不做自动交易、账户、委托或实盘能力。

## 6. 关键实现

### 6.1 主图指标定义

新增统一描述结构，字段包括：

- `id`
- `name`
- `displayName`
- `pane`
- `renderer`
- `defaultVisible`
- `color`
- `parameters`
- `lookbackBars`
- `alertCapable`
- `available`
- `unavailableReason`

固定 registry：

| 指标 | 默认 | 状态 | 说明 |
|---|---:|---|---|
| EMA10 | 关闭 | available | display only，不提供预警 |
| EMA21 | 开启 | available | 保持现有默认主图语义 |
| EMA60 | 关闭 | available | display only，不提供预警 |
| 火天大有 | 关闭 | disabled | 等待 B 线统一指标内核冻结 |

### 6.2 图表生命周期

- `KlineChart.vue` 不再围绕单个 `emaSeries` 写死。
- 改为按 active indicator definitions 维护 `mainIndicatorSeries` map。
- 切换指标时只更新 series data/options，不销毁整个 chart，不重建 linked crosshair 控制器。
- `HoverKlineContext.ema21` 保留兼容字段，但新增 `mainIndicators` 通用结构。

### 6.3 偏好持久化

localStorage key：

```text
guiyi.market.chart.preferences.v1
```

保存：

- `visibleMainIndicators`
- `period`
- `realtimeFollow` 预留字段

不保存：

- K 线数据
- 指标值
- live bar
- quality status
- 监控订阅状态

配置损坏、版本不匹配或字段类型错误时恢复默认 EMA21；空数组是合法选择，表示主图指标全关。

## 7. 后续 Gate

### C2：统一 EMA 接入与 warm-up（closeout fix 已完成，待 GPT 复审）

- 已引入 `packages/quant-core/guiyi_quant/indicators/`。
- EMA10 / EMA21 / EMA60 由 `guiyi_quant.indicators.ema.ema_series` 统一计算。
- 新增 `GET /api/v1/market/indicators`。
- 后端从 active data asset 覆盖起点读取到 `display_end` / coverage end，先完整计算 EMA，再裁剪 display window。
- 不再使用 `display_bar_count + max(warmup_bars)` 作为正式计算输入起点。
- API 返回 `seed_policy`、`calculation_start`、`warmup_bars`、`confirmed_only`、`data_version`。
- 同一 `symbol/contract/period/end` 下请求 100 根和 500 根，重叠区间 EMA10 / EMA21 / EMA60 必须一致。
- Live 模式暂不接统一 EMA，显示“Live 指标待 C3”。

### C3：实时跟随与增量轮询

只追加 canonical 截止点之后的 confirmed live bars；保留 historical/live 语义分离，不登记 active，不写 historical。

### C4：火天大有接入

等待 B 线完成公式解析、风险审查和 observation-only 结论。若存在未来函数或重绘，只能 observation-only，不能进入正式提醒。

### C5：联调、性能与文档

完成三页统一 smoke、浏览器截图、文档和 GPT 同步材料。

## 8. 涉及模块

允许修改：

- `packages/quant-core/guiyi_quant/indicators/`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_indicators.py`
- `services/quant-api/tests/test_indicator_kernel.py`
- `services/quant-api/tests/test_market_indicators_api.py`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/utils/mainIndicators.ts`
- `apps/quant-web/tests/mainIndicators.test.ts`
- `docs/INDICATOR_KERNEL.md`
- `docs/tasks/TASK-2026-07-11-003-web-overlay-indicators.md`
- `tasks/current.md`

禁止修改：

- `services/quant-api` 中除 Market indicators API / schema / service / tests 外的模块
- `data/`
- Alembic
- `.env`

## 9. 测试清单

### 自动化

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_market_indicators_api.py services/quant-api/tests/test_market_data_api.py
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
git diff --check
```

### 浏览器 smoke

页面：

```text
/market/chart?symbol=jm&contract=JM2609&period=15m
```

检查：

- EMA21 默认可见。
- EMA10 / EMA60 打开后主图、hover strip、右侧快照同步出现。
- 关闭任一指标后主图线和 hover 值同步消失或显示 `-`。
- “趋势均线”一次打开 EMA10 / EMA21 / EMA60。
- 火天大有 disabled，不生成线、不生成信号、不显示可用铃铛。
- linked crosshair、marker click、MACD 副图不回退。
- 1440×900、1280×800、1024×768 无整页横向溢出，console 0 error / 0 warning。

## 10. 验收标准

- C1 完成后，用户能在 Market K 线页自由组合 EMA10 / EMA21 / EMA60。
- C2 完成后，主图 EMA10 / EMA21 / EMA60 来自后端统一指标结果，而不是 Web 本地正式计算。
- 默认行为仍等价于现有页面：EMA21 和 MACD 可见，K 线不空白。
- 火天大有以 disabled 占位存在，清楚表达“等待 B 线冻结”。
- 没有数据链路、策略、回测和 live 写入改动。
- 自动化测试、build、diff check 和浏览器 smoke 通过。
- 文档清楚记录 C2/C3/C4 Gate，不提前宣称完成。

## 11. 执行记录

- [x] 更新 `tasks/current.md` 到当前任务。
- [x] 将任务单升级为 C0+C1 入口。
- [x] 新增主图指标 registry 与 localStorage 偏好工具。
- [x] `KlineChart.vue` 改为主图指标 series map。
- [x] `market/chart.vue` 新增主图指标选择面板和趋势均线快捷入口。
- [x] 新增 `mainIndicators.test.ts`。
- [x] Node tests。
- [x] Vite build。
- [x] `git diff --check`。
- [x] Browser smoke。
- [x] C2：引入 `quant-core` EMA 指标内核与 registry。
- [x] C2：新增只读 Market indicators API 与 warm-up 裁剪服务。
- [x] C2：前端切换为后端指标 series，KlineChart 仅渲染 `ready && valid` 点。
- [x] C2：补充指标内核、Market indicators API、前端 mainIndicators 测试。
- [x] C2 收尾：生成浏览器 GPT 审查包，明确 C3 必须单独开题。
- [x] C2 closeout fix：修正 EMA 能力语义、完整 active asset 计算锚点、API 语义字段和稳定性测试。

## 12. 验收证据

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_market_indicators_api.py services/quant-api/tests/test_market_data_api.py
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
git diff --check
git diff --check 442aa70e^..442aa70e
```

- Node tests：31 passed。
- C2 Node tests：34 passed。
- C2 closeout backend tests：21 passed。
- C2 closeout frontend Node tests：34 passed。
- Vite production build：passed；仍有既有约 650.95 kB chunk warning。
- EMA 稳定性测试：同一 `symbol/contract/period/end` 下请求 100 根和 500 根，重叠区间 EMA10 / EMA21 / EMA60 的 `time/value/ready/valid/reason` 完全一致。
- API 语义字段：`seed_policy`、`calculation_start`、`warmup_bars`、`confirmed_only`、`data_version` 已返回并有测试覆盖。
- Browser smoke：本次使用 `http://127.0.0.1:5175` Web + `http://127.0.0.1:8001` API；API 环境来自本机运行时 `project.env`，未打印任何凭据。
- Market：`/market/chart?symbol=jm&contract=JM2609&period=15m`，趋势均线打开 EMA10 / EMA21 / EMA60，hover strip 与右侧十字线快照同步显示三项指标值，MACD 副图保留，21 个 canvas。
- Backtest：`/backtest?report_id=14`，K 线报告视图打开，成交 marker 页面路径可渲染，23 个 canvas。
- Review：`/review` 选中 `#3106`，K 线定位、交易点备注、MACD 显示可见，21 个 canvas。
- Console / pageerror：三页面均为 0 error / 0 warning。
- Hover / snapshot：warm-up / invalid 点显示 `-`，不伪造成有效 EMA。
- localStorage：仅保存 `visibleMainIndicators`、`period`、`realtimeFollow`，未保存 K线、指标值、live bar、quality status 或订阅状态。
- C2 closeout 截图：`output/playwright/web-main-indicators-c2-market.png`、`output/playwright/web-main-indicators-c2-backtest.png`、`output/playwright/web-main-indicators-c2-review.png`。

## 13. 浏览器 GPT 审查包

已新增：

- `docs/gpt/WEB_INDICATORS_C2_REVIEW_PACKAGE.md`

审查包用途：

- 给浏览器 GPT 审 C2 diff、测试结果、只读边界和 C3 Gate。
- 明确 C2 当前为 `C2_CLOSEOUT_FIX_READY_FOR_GPT_REVIEW`，等待浏览器 GPT 复审。
- 明确 C3 只能在 C2 审查通过后单独开任务/会话/Plan。

浏览器 GPT 必审命令：

```bash
git show --stat --name-only 442aa70e
git show --patch 442aa70e
git diff --check HEAD~1..HEAD
git status --short --branch
```

C3 允许范围仅限：

- Live 指标跟随。
- 增量计算。
- 实时状态语义。
- 断线/缺口可观测性。

C3 禁止混入：

- PostgreSQL、Alembic、Parquet、DuckDB active 数据入口变更。
- live 数据登记为 historical active。
- 火天大有正式公式。
- 策略、回测、风控、交易执行。
- 当前 C2 `C2_CLOSEOUT_FIX_READY_FOR_GPT_REVIEW` 任务的混合开发。
