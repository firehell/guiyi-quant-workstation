# Web Indicators C2 Review Package

更新时间：2026-07-12

用途：给浏览器 GPT 审查 `TASK-2026-07-11-003-web-overlay-indicators` 的 C2 closeout fix diff、测试结果和 C3 Gate。本文是审查包，不是 C3 开发任务单。

## 1. 当前结论

- 当前分支：`codex/web-overlay-indicators`
- C2 commit：`442aa70e`
- C2 closeout fix 基线：`cf935f56`
- 当前状态：`C2_CLOSEOUT_FIX_READY_FOR_GPT_REVIEW`
- 本轮只修 C2 阻塞项，不继续修改 C3 产品代码。
- C3 必须等浏览器 GPT 审 C2 通过后，另开任务/会话/Plan。

## 2. 浏览器 GPT 审查输入

请把以下文件和命令输出同步给浏览器 GPT：

- `tasks/current.md`
- `docs/tasks/TASK-2026-07-11-003-web-overlay-indicators.md`
- `docs/INDICATOR_KERNEL.md`
- `docs/gpt/WEB_INDICATORS_C2_REVIEW_PACKAGE.md`
- `output/playwright/web-main-indicators-c2-market.png`
- `output/playwright/web-main-indicators-c2-backtest.png`
- `output/playwright/web-main-indicators-c2-review.png`

需要附带的 diff/test 命令：

```bash
git show --stat --name-only 442aa70e
git show --patch 442aa70e
git diff --stat cf935f56..HEAD
git diff cf935f56..HEAD
git diff --check
git diff --check 442aa70e^..442aa70e
git status --short --branch
```

## 3. GPT 重点审查问题

请浏览器 GPT 重点判断：

- `GET /api/v1/market/indicators` 是否保持只读，不写 DB、不改 active 数据入口。
- EMA10 / EMA21 / EMA60 是否统一来自 `packages/quant-core`，前端不再复制正式 EMA 公式。
- EMA registry 是否满足 `web_capable=true`、`live_capable=true`、`alert_capable=false`。
- EMA 是否从 active data asset 覆盖起点完整计算后再裁剪 display window，而不是使用 `display_bar_count + warmup` 作为正式计算输入起点。
- 100 根和 500 根请求的重叠区间 EMA10 / EMA21 / EMA60 是否稳定一致。
- API 是否返回 `seed_policy`、`calculation_start`、`warmup_bars`、`confirmed_only`、`data_version`。
- Live 模式是否明确显示“Live 指标待 C3”，没有把 live bars 混入 C2 统一 EMA。
- 火天大有是否仍为 disabled / observation-only 占位，没有提前计算、提醒或回测。
- `KlineChart.vue` 被 Market / Backtest / Review 共享后，默认 EMA21、MACD、linked crosshair 是否没有回退风险。

## 4. C2 测试结果口径

向浏览器 GPT 明确区分 closeout fix 后的新证据：

- C2 closeout backend tests：21 passed。
- C2 closeout Node tests：34 passed。
- Vite production build：passed；仍有既有约 650.95 kB chunk warning。
- EMA 稳定性测试：同一 `symbol/contract/period/end` 下请求 100 根和 500 根，重叠区间 EMA10 / EMA21 / EMA60 的 `time/value/ready/valid/reason` 完全一致。
- Playwright 三页面 smoke：使用 `http://127.0.0.1:5175` Web + `http://127.0.0.1:8001` API；Market 21 canvas、Backtest `report_id=14` 23 canvas、Review 选中 `#3106` 后 21 canvas，三页面 console / pageerror 均为 0。
- 截图见 `output/playwright/` 下三个 `web-main-indicators-c2-*` 文件。

如浏览器 GPT 要求强验收，重新运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_market_indicators_api.py services/quant-api/tests/test_market_data_api.py
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
git diff --check
git diff --check 442aa70e^..442aa70e
```

## 5. C3 独立开题边界

只有浏览器 GPT 审 C2 通过，才允许单独开 C3。C3 不复用 C2 收尾任务，不混入当前 C2 diff。

C3 目标限定：

- Live 指标跟随：confirmed live bars 到达后，指标状态在 UI 上跟随更新。
- 增量计算：只基于 canonical cutoff 之后的 confirmed live bars 做增量，不重写 historical。
- 实时状态语义：清楚区分 `historical`、`live_confirmed`、`live_pending`、`stale`、`disconnected`。
- 断线/缺口可观测性：页面和日志可见 latest bar time、lag、gap、reconnect/error reason。
- 继续只提醒/观察，不自动下单，不接账户，不触发企业微信批量发送。

C3 明确不做：

- 不改 PostgreSQL、Alembic、Parquet、DuckDB active 数据入口。
- 不把 live 数据登记为 historical active。
- 不实现火天大有正式公式。
- 不改策略、回测、风控、交易执行。
- 不把 C2 的 `C2_CLOSEOUT_FIX_READY_FOR_GPT_REVIEW` 重新打开做混合开发。

## 6. 给浏览器 GPT 的审查 Prompt

BEGIN GPT REVIEW PROMPT

你是归一量化项目的浏览器 GPT 审查员。请只审查 Web C2：主图指标与统一 EMA 接入，不要规划或实现 C3。

仓库事实：

- Worktree：`/Volumes/扩展盘/guiyi-parallel/web-indicators`
- Branch：`codex/web-overlay-indicators`
- C2 commit：`442aa70e`
- C2 closeout fix 基线：`cf935f56`
- 当前状态：`C2_CLOSEOUT_FIX_READY_FOR_GPT_REVIEW`
- C2 目标：新增只读 `GET /api/v1/market/indicators`，后端复用 `packages/quant-core` EMA 内核，前端消费统一指标结果，并实现 active asset 完整计算后裁剪 display window 的规则。

请审查以下文件和命令输出：

- `tasks/current.md`
- `docs/tasks/TASK-2026-07-11-003-web-overlay-indicators.md`
- `docs/INDICATOR_KERNEL.md`
- `docs/gpt/WEB_INDICATORS_C2_REVIEW_PACKAGE.md`
- `output/playwright/web-main-indicators-c2-market.png`
- `output/playwright/web-main-indicators-c2-backtest.png`
- `output/playwright/web-main-indicators-c2-review.png`
- `git show --stat --name-only 442aa70e`
- `git show --patch 442aa70e`
- `git diff --stat cf935f56..HEAD`
- `git diff cf935f56..HEAD`
- `git diff --check`
- `git diff --check 442aa70e^..442aa70e`

请重点判断：

1. C2 是否保持只读，不写 DB、不改 active 数据入口。
2. EMA10 / EMA21 / EMA60 是否统一来自 `quant-core`，前端没有复制正式 EMA 公式。
3. EMA registry 是否满足 `web_capable=true`、`live_capable=true`、`alert_capable=false`。
4. EMA 是否从 active data asset 覆盖起点完整计算后再裁剪 display window。
5. 100 根和 500 根请求的重叠区间 EMA10 / EMA21 / EMA60 是否稳定一致。
6. API 是否返回 `seed_policy`、`calculation_start`、`warmup_bars`、`confirmed_only`、`data_version`。
7. Live 模式是否仍等待 C3，没有把 live bars 混入 C2 统一 EMA。
8. 火天大有是否仍是 disabled / observation-only 占位。
9. `KlineChart.vue` 共享给 Market / Backtest / Review 后是否有默认 EMA21、MACD、linked crosshair 回退风险。
10. 已记录测试结果是否足以进入 C2 closeout；如果不足，请列出必须补跑的最小命令。

输出格式：

### 审查结论

通过 / 有阻塞 / 仅有非阻塞建议。

### 阻塞问题

只列会影响 C2 可信交付的问题；没有则写“无”。

### 非阻塞建议

列出可以留到 C3/C4/C5 的建议。

### 是否允许开 C3

是 / 否。若否，请说明必须先修的 C2 问题。

END GPT REVIEW PROMPT
