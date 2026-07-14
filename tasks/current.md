# 当前任务：HTDY-FORMAL-BACKTEST-CANDIDATE-DRY-RUN

生成时间：2026-07-11

Worktree：`/Volumes/扩展盘/guiyi-parallel/htdy-core`

分支：`codex/htdy-indicator-core`

状态：`FORMAL_BACKTEST_CANDIDATE_DRY_RUN_READY`

## 背景

浏览器 GPT 对 `Indicator Kernel V1-D` 的安全复核结论为：有条件通过。

允许关闭 V1-D，但只能定义为：

```text
MACD/ATR compatibility draft and migration design completed
```

不能表述为：

- `MACD/ATR unified`
- `Indicator Kernel fully adopted`
- `Strategy kernel migration completed`

本轮进入 V1-E，但严格限定为：

- 只迁移 Market 页面 MACD 只读展示。
- 固定 `web_macd_legacy_v1` policy。
- 后端公共内核作为权威计算源，前端只渲染。
- `KlineChart.vue` 通过可选 `macdOverride` 接收后端 MACD；Backtest / Review 不传该字段，继续使用原前端计算。

## 本轮允许修改

第 4 步补充允许：

- `experiments/htdy_indicator/golden_sample.py`
- `experiments/htdy_indicator/golden_sample_manifest.json`
- `services/quant-api/tests/test_htdy_golden_sample.py`
- `apps/quant-web/src/utils/indicators.ts`
- `apps/quant-web/tests/htdyGoldenSample.test.ts`
- `docs/strategy_specs/htdy/GOLDEN_SAMPLE_ACCEPTANCE.md`
- HTDY 相关 spec / README / task 状态文档

- `docs/INDICATOR_KERNEL.md`
- `docs/INDICATOR_KERNEL_V1D_MIGRATION_PLAN.md`
- `docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md`
- `tasks/current.md`
- `services/quant-api/app/api/market.py`
- `services/quant-api/app/schemas/market.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`
- `services/quant-api/tests/test_market_macd_indicator_api.py`
- `apps/quant-web/src/api/market.ts`
- `apps/quant-web/src/types/market.ts`
- `apps/quant-web/src/utils/macdOverride.ts`
- `apps/quant-web/src/components/kline/KlineChart.vue`
- `apps/quant-web/src/pages/market/chart.vue`
- `apps/quant-web/src/utils/indicators.ts`
- `apps/quant-web/tests/indicators.test.ts`
- `apps/quant-web/tests/macdOverride.test.ts`
- `docs/strategy_specs/htdy/INDICATOR_SPEC.md`

## 本轮禁止修改

- `packages/quant-core/guiyi_quant/strategies/`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `services/quant-api/app/signal/`
- `data/`
- 数据库 migration
- 回测报告、`strategy_signals`、`signal_events`、企业微信通知链路
- `report_id=14` 历史基线

## 已完成

- [x] V1-D：补充 golden vector 证明范围，不把 V1-D 写成生产迁移完成。
- [x] V1-D：记录稳定 policy 名称 `web_macd_legacy_v1`。
- [x] V1-E：新增 `/api/v1/market/indicators/macd` 只读接口。
- [x] V1-E：接口复用 `/api/v1/market/bars` 同一批 bars，并调用公共 `macd_series()`。
- [x] V1-E：API response 对 Web policy 做旧 Web 对齐裁剪，DIF / DEA / HIST 只在 DEA ready bar 一起输出。
- [x] V1-E：Market 页面请求后端 MACD 并传入 `KlineChart` 的 `macdOverride`。
- [x] V1-E：Backtest / Review 不传 `macdOverride`，保持原前端 `calculateMACD()`。
- [x] V1-E：请求失败时 Market 页面 warning，并回退前端展示计算。
- [x] V1-E：新增后端 API / prefix invariance / NaN / short window 测试。
- [x] V1-E：新增前端 override 转换测试。

## 当前测试证据

已通过：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py services/quant-api/tests/test_market_macd_indicator_api.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_indicator_kernel_v1b_diff.py services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py services/quant-api/tests/test_live_signal_evaluator.py
pnpm --dir apps/quant-web exec node --test tests/macdOverride.test.ts
pnpm --dir apps/quant-web build
git diff --check
uv run --project services/quant-api ruff check services/quant-api/app/api/market.py services/quant-api/app/schemas/market.py services/quant-api/app/services/market_workbench.py services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py services/quant-api/tests/test_market_macd_indicator_api.py
git diff --name-only -- packages/quant-core/guiyi_quant/strategies services/quant-api/app/services/live_signal_evaluator.py services/quant-api/app/signal data .env .env.example
```

结果：

- V1-C + V1-E API：12 passed
- Indicator Kernel V1-A/B/C/D：27 passed
- JM V1-B + live evaluator：13 passed
- 前端 MACD override：2 passed
- `pnpm --dir apps/quant-web build`：passed，存在 Vite chunk size warning，不阻塞本轮
- `git diff --check`：passed
- targeted ruff：passed
- 禁止链路 diff 核对：无输出

## 附加交付：HTDY 原始公式规范阻塞解除

本轮按用户提供的火天大有通达信公式，完成公式规范归档：

- [x] 新增 `docs/strategy_specs/htdy/INDICATOR_SPEC.md`，归档完整原始公式和变量拆解。
- [x] 新增 `docs/strategy_specs/htdy/INDICATOR_RISK_REVIEW.md`，明确 `XMA`、`ZK1/ZD1/ZD2`、`VAR23`、三连提示、`XG`、`XG2` 的未来函数 / 重绘边界。
- [x] 新增 `docs/strategy_specs/htdy/STRATEGY_SPEC.md`，只定义 `huotian_dayou_original_v0` observation-only 骨架。
- [x] 新增 `services/quant-api/tests/test_htdy_indicator_risk.py`，锁定风险分类和禁止接入边界。
- [x] 更新 `docs/strategy_specs/htdy/README.md` 和 `docs/INDICATOR_KERNEL.md`。

结论：

- “缺少原始公式”阻塞已解除。
- “可回测 / 可 live / 可预警”阻塞未解除。
- 原始 `买多预警` / `卖空预警` 只翻译为 observation 字段，不写 `signal_events`，不进企业微信。
- 本次不改 Web、不改正式策略、不改 live evaluator、不写 DB、不改企业微信链路。

已通过：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_indicator_risk.py services/quant-api/tests/test_tdx_xma_indicator_risk.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py
```

- HTDY + XMA 风险回归：8 passed
- Indicator Kernel 回归：7 passed

## 附加交付：HTDY 原始 observation-only PoC

本轮继续完成剩余路径第 1 步：

- [x] 新增 `experiments/htdy_indicator/htdy_original_core.py`，复刻完整原始公式数值输出。
- [x] 新增 `experiments/htdy_indicator/export_htdy_original.py`，支持 synthetic sample 与本地 CSV 导出 JSON / CSV。
- [x] 新增 `experiments/htdy_indicator/README.md`，记录 observation-only、重绘风险和运行方式。
- [x] 新增 `services/quant-api/tests/test_htdy_original_poc.py`，覆盖字段完整性、三连提示、XMA future-tail repaint 和 XG/XG2 风险 metadata。

PoC 输出字段：

```text
ZK1, ZD1, ZD2, 黄K, 白K, 买多信号, 卖空信号,
VAR23, 回调买, XG, DDX, V2, V5, V10, V20, DY, DY2, XG2, XG2_DRAWTEXT
```

结论：

- 原始 XMA 版本仍是 `observation_only`。
- PoC 仅作为 Web 观察层对齐和 Golden Sample 的数值基准。
- 不改 Web、不改正式策略、不改 scanner / live evaluator、不写 DB、不写 `signal_events`、不触发企业微信。
- `DDX/V2/V5/V10/V20` 仅标为 `candidate_after_rewrite`，不能自动升级为正式信号。

已通过：

```bash
uv run --project services/quant-api python experiments/htdy_indicator/export_htdy_original.py --format json --synthetic-length 72
uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_indicator_risk.py services/quant-api/tests/test_tdx_xma_indicator_risk.py services/quant-api/tests/test_htdy_original_poc.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py
uv run --project services/quant-api ruff check experiments/htdy_indicator services/quant-api/tests/test_htdy_indicator_risk.py services/quant-api/tests/test_htdy_original_poc.py
git diff --check
git diff --name-only -- packages/quant-core/guiyi_quant/strategies services/quant-api/app/services/live_signal_evaluator.py services/quant-api/app/signal data .env .env.example
```

- HTDY CLI synthetic smoke：passed，`row_count=72`、`status=observation_only`
- HTDY + XMA + 原始 PoC：13 passed
- Indicator Kernel 回归：7 passed
- targeted ruff：passed
- `git diff --check`：passed
- 禁止链路 diff 核对：无输出

## 附加交付：HTDY Web Observation-Only 对齐

本轮继续完成剩余路径第 2 步：

- [x] 黄K 按原公式三个严格条件判断，补齐 `ZD1>HIGH`。
- [x] 白K 按实体 `BODYH>ZK1 AND BODYH>OVERLOW` 判断，不再以影线 `high>=ZK1` 代替。
- [x] SVG 覆盖层按原 `STICKLINE` 分段绘制，同根 K 先白后黄。
- [x] 前端完整复刻 `VAR23 -> 回调买 -> XG`，只显示去指令化 `XG观察`。
- [x] `XG2` 因 `CURRBARSCOUNT` 历史语义未定不进入 Web。
- [x] 常驻风险提示明确 `observation_only` / 会重绘 / XG-XG2 取舍。

边界：

- `XG观察` 只存在于共享 K 线组件的 SVG 观察覆盖层，不加入正式 `KlineMarker` 点击链。
- 不改 FastAPI、DB、migration、strategy、scanner、live evaluator、`strategy_signals`、`signal_events`、企业微信和 `report_id=14`。
- 不进入 strict backward-looking、Golden Sample 或正式候选接入。

前端定向测试：

```bash
pnpm --dir apps/quant-web exec node --test tests/indicators.test.ts
pnpm --dir apps/quant-web build
```

- HTDY / EMA / MACD / ATR 前端指标：13 passed
- 前端 build：passed，仅保留已知 Vite chunk size warning

浏览器验收：

- `/market/chart?symbol=jm&contract=JM2609&period=15m` 实际加载 1,471 根 primary/passed K 线。
- `1440/1280/1024` 三档均无页面水平溢出，HTDY SVG 覆盖层存在，可见分段数分别为 `643/567/613`。
- 常驻文案为“火天大有：观察专用 · 会重绘 · XG 已显示 · XG2 未展示”。
- 三档可见 `XG观察` 数分别为 `6/5/6`，`XG2` 始终为 `0`。
- 点击主图后 linked crosshair 出现，hover 时间从最新 bar 变为 `2026-05-15 10:15`。
- HTDY 本身未产生 console error/warn。整页 console 仍有 1 条与本步无关的 V1-E MACD 404：当前可用 `8000` API 旧进程未包含本 worktree 尚未提交的 `/market/indicators/macd`；本 worktree 无 `.env`，未绕过 DB 凭据 Gate 启动同版 API。

## 附加交付：HTDY Strict Backward-Looking V1 方案

本轮继续完成剩余路径第 3 步：

- [x] 新增 `docs/strategy_specs/htdy/STRICT_V1_SPEC.md`，定义 `huotian_dayou_strict_v1` 独立研究候选。
- [x] 新增 `experiments/htdy_indicator/htdy_strict_core.py`，使用 `double_trailing_ema` 替代原始双层 `XMA`。
- [x] 新增 `services/quant-api/tests/test_htdy_strict_core.py`，覆盖 future-tail 不重绘、逐 bar / 批量一致性、warm-up/NaN、空输入/短序列/非法参数和字段白名单。
- [x] 更新 `docs/strategy_specs/htdy/README.md`、`INDICATOR_SPEC.md`、`INDICATOR_RISK_REVIEW.md`、`STRATEGY_SPEC.md` 和 `experiments/htdy_indicator/README.md`。

strict v1 输出字段：

```text
zk1, zd1, zd2, yellow_candle, white_candle,
buy_observation, sell_observation, var23, callback_buy, xg_observation
```

边界：

- `huotian_dayou_original_v0` 不被覆盖，仍是 `observation_only` 且会重绘。
- `huotian_dayou_strict_v1` 仅是 `strict_research_candidate`，不是 validated 指标或正式策略。
- `XG2`、`DY/DY2`、`DDX/V2/V5/V10/V20` 暂不进入 strict v1。
- 不改 Web、不改 FastAPI 业务接口、不改 DB / migration、不改正式 strategy / scanner / live evaluator、不写 `strategy_signals` / `signal_events`、不触发企业微信。

已通过：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_strict_core.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_indicator_risk.py services/quant-api/tests/test_htdy_original_poc.py services/quant-api/tests/test_htdy_strict_core.py
uv run --project services/quant-api ruff check experiments/htdy_indicator services/quant-api/tests/test_htdy_strict_core.py
```

- HTDY strict v1 专项：6 passed
- HTDY original + strict 回归：15 passed
- targeted ruff：passed

剩余步骤：

```text
4. Golden Sample 验收
5. 正式候选接入评估
```

## 后续 Gate

### 2026-07-12 HTDY Step 4 Golden Sample

- [x] 固定 `JM.MAIN 15m` 256 根真实 `primary/passed` 样本。
- [x] 校验 source/input SHA256、lineage、时间范围和 row_count。
- [x] 冻结 original v0 / strict v1 输出摘要和事件计数。
- [x] Python original 与 Web observation-only 全字段数值对照通过。
- [x] strict 真实样本 prefix/batch、future-tail、warm-up 和能力边界通过。
- [x] `1440/1280/1024` 三档无水平溢出，HTDY overlay、风险文案和 linked crosshair 可见。
- [x] 用户提供 `JM8 焦煤主连 15分钟` 通达信截图，覆盖固定窗口，外部视觉 oracle Gate 已关闭。

当前定义为 `GOLDEN_SAMPLE_PASS_VISUAL_ORACLE`。未提供通达信数值导出，因此不声明逐点数值 oracle pass。真实 RQData Parquet 不提交；正式策略、backtest runner、scanner、live evaluator、DB/migration、信号事件和企业微信均未修改。

### 2026-07-12 HTDY Step 5 Offline Candidate Eval

- [x] 新增 `docs/strategy_specs/htdy/OFFLINE_CANDIDATE_EVAL.md`，固定第 5 步离线候选评估范围。
- [x] 新增 `experiments/htdy_indicator/offline_candidate_eval.py`，只读 JM 15m `primary/passed` parquet，输出 strict v1 candidate events、lineage、checksum 和能力边界。
- [x] 新增 `services/quant-api/tests/test_htdy_offline_candidate_eval.py`，覆盖版本命名、能力边界、下一根开盘拟对照时点、数据 lineage、短窗口和 Markdown 输出。
- [x] 更新 `docs/strategy_specs/htdy/README.md`、`STRICT_V1_SPEC.md`、`INDICATOR_RISK_REVIEW.md` 和 `experiments/htdy_indicator/README.md`。

离线候选命名：

```text
strategy_code=huotian_dayou_strict
strategy_version=v0.1.0-offline
candidate_policy=strict_v1_15m_offline_v0
fill_policy=signal_on_close_fill_next_bar_open
execution_scope=offline_comparison_only
```

边界：

- 只输出 `candidate_events_only`，不计算可信 PnL。
- `buy_observation/xg_observation` 只解释为 long entry candidate。
- `sell_observation` 只解释为 short or exit candidate。
- 当前 bar 收盘确认，下一根 open 仅作为拟对照时点。
- 不创建 backtest task，不写 `BacktestReport`，不写 `strategy_signals` / `signal_events`，不接 scanner、live evaluator、DB/migration 或企业微信。

第 5 步允许结论：

```text
huotian_dayou_strict_v1 offline backtest candidate evaluated
```

不授权正式策略或可信回测报告接入。

下一轮若继续迁移，只能另开单调用方任务。

建议顺序：

```text
Web MACD 展示复核
-> 非 P0 API 展示调用方
-> ATR 单独迁移
-> 策略对照迁移
-> 最后才考虑 live evaluator
```

禁止一口气替换整条策略链。任何策略、扫描、live evaluator 或报告口径变化都必须另开 Plan，并固定兼容 policy、迁移前后输出、回归测试和必要的策略版本升级规则。

### 2026-07-13 HTDY Formal Backtest Candidate Dry-Run

- [x] 新增 `docs/strategy_specs/htdy/FORMAL_BACKTEST_CANDIDATE_PLAN.md`，固定正式可信回测候选边界、版本命名、撮合口径、成本口径、Report Gate 和 GPT 外部复核标准。
- [x] 新增 `packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/`，实现 `huotian_dayou_strict / v0.1.0-backtest-candidate` 独立策略候选。
- [x] 新增 `experiments/htdy_indicator/formal_backtest_candidate.py`，提供只读 dry-run helper，输出 normalized `trades / orders / strategy_execution_events / summary`，不创建 task/report。
- [x] 新增 `services/quant-api/tests/test_htdy_formal_backtest_candidate.py`，覆盖参数冻结、future-tail、不提前成交、止损优先、时间退出、反手先平、冲突跳过、缺成本字段拒绝、lineage Gate 和 trust audit 消费。
- [x] 更新 `docs/strategy_specs/htdy/README.md`。

候选命名：

```text
indicator_version=huotian_dayou_strict_v1
strategy_code=huotian_dayou_strict
strategy_version=v0.1.0-backtest-candidate
candidate_policy=strict_v1_15m_formal_candidate_v0
fill_policy=signal_on_close_fill_next_bar_open
execution_scope=formal_backtest_candidate
```

边界：

- 本轮只实现 dry-run formal candidate，不写真实 `BacktestReport`。
- 不写 `strategy_signals` / `signal_events`，不接 scanner、live evaluator、数据库 migration 或企业微信。
- 不修改 RQData / parquet / manifest / data quality report。
- 不修改、不复用、不覆盖 `report_id=14`；后续如需写报告，必须新建独立 task/report 并立即运行 trust audit。
