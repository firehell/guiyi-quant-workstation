# TASK-2026-07-11-002：火天大有指标与策略规范

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-002-htdy-indicator-core |
| GitHub Issue | #10 |
| Branch | codex/htdy-indicator-core |
| Worktree | /Volumes/扩展盘/guiyi-parallel/htdy-core |
| Status | FORMAL_BACKTEST_CANDIDATE_DRY_RUN_READY |
| 公式输入路径 | `private_sources/htdy/`（用户提供的通达信公式，gitignore） |

## 1. 任务状态

FORMAL_BACKTEST_CANDIDATE_DRY_RUN_READY

说明：

- Web 火天大有观察层已交付，见 `TASK-2026-07-11-003-web-main-indicators.md`。
- HTDY 通达信原始公式已由用户提供，并已归档到 tracked docs。
- 公式级 Spec / 风险审查 / observation-only 策略骨架、原始 PoC、strict backward-looking 改写、Golden Sample 和 Offline Candidate Eval 均已完成。
- 本轮已新增 `FORMAL_BACKTEST_CANDIDATE_PLAN.md`、`huotian_dayou_strict` 策略候选和只读 dry-run helper，把 `huotian_dayou_strict_v1` 推进到正式可信回测候选 dry-run 就绪状态。
- 本轮已推进 `Indicator Kernel V1-A/V1-B/V1-C/V1-D`：EMA 公共内核、MACD/ATR 差异审计、MACD/ATR 多口径 draft 公共函数，以及逐调用方迁移设计 / golden vector 对照。
- MACD / ATR 仍未注册为 `validated`，未迁移任何策略、扫描、live、Web、数据库、报告或通知链路。
- HTDY 仍不是正式策略、live 信号或企业微信提醒；后续开发必须另开任务并通过 trust audit / 外部安全复核 Gate。

## 2. 任务类型

策略研究与验证 / 指标规范

## 3. 参与角色

- 必须：策略研究员、量化架构师、安全专家
- 不需要：前端、live runtime、企业微信

## 4. 背景

用户已提供「火天大有」通达信公式。需对照 `tdx_xma_bands` 风险审查模板，产出 observation-only 规范，**不接** vn.py 主链、信号扫描、企业微信。

## 5. 目标

1. 整理 `docs/strategy_specs/htdy/INDICATOR_SPEC.md`（参数、IO、公式逐步解释）
2. 编写 `INDICATOR_RISK_REVIEW.md`（lookahead、未来函数、过拟合、期货适配）
3. 编写 `STRATEGY_SPEC.md` 骨架（入场/出场/止损/过滤/周期），标记 `observation-only`
4. 可选：`experiments/htdy_indicator/` PoC（strictly backward-looking 改写优先）

## 6. 不做事项

- 不接入 `packages/quant-core/guiyi_quant/strategies/` 正式策略
- 不接入 PostgreSQL 报告、信号扫描、企业微信、vn.py Runner 主路径
- 不自动交易、不 live 提醒
- 本次用户已授权完整公式进入 tracked docs；后续如另有私有公式材料，仍不得提交 `private_sources/`

## 7. 涉及模块

**允许修改**：

- `docs/strategy_specs/htdy/`
- `experiments/htdy_indicator/`
- `services/quant-api/tests/test_htdy_indicator_risk.py`
- `docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md`
- `tasks/current.md`
- `.ai/results/TASK-2026-07-11-002-htdy-indicator-core/`

**禁止修改**：

- `packages/quant-core/guiyi_quant/strategies/`
- `services/quant-api/app/` 信号/扫描/通知业务
- `apps/`、`data/`、`.env`

## 8. 产品需求

- 规范足够让外部审查（ChatGPT）判断能否进入 Stage 7.5 向后看改写
- 明确与 V1-B 苏冰主线的关系：并行研究，不替换

## 9. 量化业务规则

- 期货：注明合约乘数、夜盘、主力/actual 合约假设
- 任何 XMA/偏移均线必须标注 lookahead 风险

## 10. 数据影响

- 无 RQData 写入；PoC 仅用本地实验数据或 synthetic bars

## 11. 技术方案

1. 读取用户提供的 HTDY 原始公式
2. 参照 `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
3. 若 PoC：参照 `experiments/rqalpha_tdx_xma_bands/xma_core.py` 结构
4. 风险测试：未来函数/重绘检测 stub

## 12. 交互视觉要求

无 Web 变更（后续 Web overlay 属会话 C）

## 13. 安全权限要求

- 不提交 API Key；private_sources 已在 .gitignore

## 14. 开发步骤

1. 确认用户提供的公式可进入 tracked docs
2. Plan：公式解析与风险框架
3. Dev：编写三份 spec + 最小风险测试
4. 标注 `observation-only`

## 15. Codex Plan Prompt

```
只读 Plan。必读 AGENTS.md、docs/strategy_specs/tdx_xma_bands/、private_sources/htdy/（若存在）。
任务：火天大有指标规范与风险审查。不得接入正式策略或信号链路。
输出：公式拆解计划、风险清单、Spec 目录结构、PoC 是否必要。
```

## 16. Codex Dev Prompt

```
按已批准 Plan 编写 docs/strategy_specs/htdy/ 三份文档。
可选 experiments/htdy_indicator/ 与 test_htdy_indicator_risk.py。
标记 observation-only。禁止改 packages/quant-core 正式策略。
```

## 17. CodeBuddy 执行 Prompt

```
worktree: /Volumes/扩展盘/guiyi-parallel/htdy-core
branch: codex/htdy-indicator-core
启动前确认 private_sources/htdy/ 有公式。不 push/merge/deploy。
```

## 18. 测试清单

### 18.0 自动化测试命令

```bash
uv run --project services/quant-api pytest services/quant-api/tests/test_htdy_indicator_risk.py -q
git diff --check
```

- [x] 三份 spec 文件存在且互相引用一致
- [x] 风险审查含 lookahead/未来函数章节
- [x] 最小 pytest passed

## 19. 验收标准

- `docs/strategy_specs/htdy/` 三文件齐全
- 文档明确 `observation-only`
- 未修改正式策略与信号扫描

## 20. 风险点

- 通达信 XMA 类未来函数直接进入回测
- 用户公式误入 git 提交

## 21. 交付记录

- 合并目标：main（在 data-audit 之后、jm-live-gate 之前）

### 2026-07-11 Indicator Kernel V1-A

新增范围：

- `packages/quant-core/guiyi_quant/indicators/`：公共指标模型、EMA 实现和注册表。
- `docs/INDICATOR_KERNEL.md`：EMA seed policy、warm-up、NaN、confirmed bar 和用途能力边界。
- `services/quant-api/tests/test_indicator_kernel.py`：公共内核回归测试。

边界：

- 不修改 `packages/quant-core/guiyi_quant/strategies/`。
- 不修改 FastAPI 业务代码、数据库、数据链路、live evaluator、信号扫描或企业微信。
- 火天大有仍是 `observation_only`，`backtest_capable=false`、`live_capable=false`、`alert_capable=false`。

测试结果：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
uv run --project services/quant-api ruff check packages/quant-core/guiyi_quant/indicators services/quant-api/tests/test_indicator_kernel.py
```

- Indicator Kernel：7 passed
- JM V1-B 策略回归：7 passed
- XMA 风险回归：4 passed
- diff whitespace 与 targeted ruff 均通过

### 2026-07-11 Indicator Kernel V1-B

新增范围：

- `docs/INDICATOR_KERNEL_V1B_DIFF.md`：MACD / ATR 差异审计报告。
- `services/quant-api/tests/test_indicator_kernel_v1b_diff.py`：synthetic golden vector 差异测试。
- `docs/INDICATOR_KERNEL.md`：追加 V1-B 摘要和 V1-C Gate。

结论：

- MACD / ATR 暂不注册为 `validated` 公共指标。
- 不新增正式 `macd.py` / `atr.py`。
- 不修改策略、扫描、live evaluator、Web、数据库、报告或通知链路。
- 后续如进入 V1-C，必须显式支持 seed / smoothing / histogram policy，并逐策略做 golden vector 对照。

测试结果：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1b_diff.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
uv run --project services/quant-api ruff check services/quant-api/tests/test_indicator_kernel_v1b_diff.py
```

- Indicator Kernel V1-A 回归：7 passed
- Indicator Kernel V1-B 差异审计：5 passed
- JM V1-B 策略回归：7 passed
- XMA 风险回归：4 passed
- `git diff --check`：passed
- targeted ruff：passed

### 2026-07-12 HTDY Golden Sample Step 4

新增只读 Golden Sample 工具与 tracked manifest，固定 `JM.MAIN 15m` 的 256 根 `primary/passed` 样本、source/input checksum、original/strict 输出摘要及事件计数；新增 Python/Web 跨语言数值测试和真实样本 prefix/future-tail 回归。

自动数值 Gate 已通过；用户已提供 `JM8 焦煤主连 15分钟` 通达信截图，覆盖固定窗口，外部视觉 oracle Gate 已关闭。当前状态为：

```text
GOLDEN_SAMPLE_PASS_VISUAL_ORACLE
```

本次 oracle 是截图视觉通过，不是通达信数值导出逐点通过。第 5 步正式候选接入仍未授权；正式策略、backtest、scanner、live、数据库、信号事件和企业微信链路均未修改。

### 2026-07-11 GPT Review Checkpoint + V1-C Plan

新增范围：

- `docs/gpt/INDICATOR_KERNEL_REVIEW_PROMPT.md`：浏览器 GPT 复核 Prompt。
- `docs/INDICATOR_KERNEL_V1C_PLAN.md`：V1-C 条件计划。

当前状态：

- 该 hard Gate 已被用户后续指令取代：GPT 外部安全审查改为可选，不再阻塞 V1-C。
- V1-C 仍只允许实现多口径公共函数和测试，不迁移任何调用方。

### 2026-07-11 Indicator Kernel V1-C

Gate 调整：

- 用户已取消“GPT 必须先通过”的硬 Gate，外部 GPT 审查改为可选。
- V1-C 直接进入开发，但严格限定为公共函数、测试和文档。

新增范围：

- `packages/quant-core/guiyi_quant/indicators/macd.py`：多口径 MACD 公共函数。
- `packages/quant-core/guiyi_quant/indicators/atr.py`：多口径 ATR 公共函数。
- `packages/quant-core/guiyi_quant/indicators/models.py`：新增 `MacdSeries`、`HistogramScale`、`AtrSmoothingPolicy`。
- `packages/quant-core/guiyi_quant/indicators/__init__.py`：导出 draft 公共函数。
- `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`：V1-C golden vector 和边界测试。
- `docs/INDICATOR_KERNEL.md`、`docs/INDICATOR_KERNEL_V1C_PLAN.md`、`packages/quant-core/README.md`：同步 V1-C 边界。

口径：

- MACD 支持 `ema_seed_policy=sma_window|first_value` 和 `histogram_scale=1|2`。
- ATR 支持 `smoothing_policy=wilder_sma_seed|wilder_first_tr|ema_first_tr`。
- invalid 输入不补 0；warm-up、invalid、future-tail 不重绘均有测试覆盖。

边界：

- 不把 MACD / ATR 写入 `indicator_registry`，不注册为 `validated`。
- 不修改 `packages/quant-core/guiyi_quant/strategies/`、`services/quant-api/app/`、`apps/`、`data/`、数据库、报告、`signal_events`、live evaluator 或企业微信。
- 后续任何调用方迁移必须另开 Plan，逐策略选择兼容 policy 或升策略版本。

测试结果：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_indicator_kernel_v1b_diff.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
uv run --project services/quant-api ruff check packages/quant-core/guiyi_quant/indicators services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

- Indicator Kernel V1-C：10 passed
- Indicator Kernel V1-A + V1-B：12 passed
- JM V1-B 策略回归：7 passed
- XMA 风险回归：4 passed
- `git diff --check`：passed
- targeted ruff：passed
- 禁止目录 diff 核对：`packages/quant-core/guiyi_quant/strategies`、`services/quant-api/app`、`apps`、`data`、`.env`、`.env.example` 无 diff

### 2026-07-11 Indicator Kernel V1-D

新增范围：

- `docs/INDICATOR_KERNEL_V1D_MIGRATION_PLAN.md`：逐调用方迁移矩阵、兼容 policy、P0 风险边界和后续 Gate。
- `docs/gpt/INDICATOR_KERNEL_REVIEW_PROMPT.md`：V1-D 浏览器 GPT 安全审查 Prompt。
- `services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py`：synthetic golden vector 对照测试。
- `docs/INDICATOR_KERNEL.md`、`packages/quant-core/README.md`、`docs/gpt/README.md`、`tasks/current.md`：同步 V1-D 状态和边界。

结论：

- V1-D 只证明公共内核可复刻现有调用方口径，不替换任何生产调用链。
- `jm_v1b_daily_direction_fast_entry` 与 `live_signal_evaluator` 属 P0 可信链路，只做对照，不迁移。
- Web 口径只登记为 `sma_window` / histogram `2` / `wilder_sma_seed`，不修改 `apps/`，后续由 `web-indicators` worktree 单独处理。
- MACD / ATR 仍不写入 `indicator_registry`，不注册为 `validated`。

测试结果：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_indicator_kernel_v1b_diff.py services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py services/quant-api/tests/test_live_signal_evaluator.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_ema21_vnpy_draft.py services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py services/quant-api/tests/test_su_bing_jm_daily_score2of4.py services/quant-api/tests/test_su_bing_jm_daily_trend_cross_score2.py
uv run --project services/quant-api ruff check services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
git diff --check
git diff --name-only -- packages/quant-core/guiyi_quant/strategies services/quant-api/app apps data .env .env.example
```

- V1-D golden vector：5 passed
- Indicator Kernel V1-A/B/C/D：27 passed
- JM V1-B + live evaluator：13 passed
- 策略族回归：33 passed
- V1-D targeted ruff：passed
- `git diff --check`：passed
- 禁止目录 diff 核对：无输出

### 2026-07-11 V1-D Browser GPT Safety Review Handoff

新增范围：

- `docs/gpt/INDICATOR_KERNEL_REVIEW_PROMPT.md`：从 V1-A/V1-B 旧审查 Prompt 更新为 V1-D 安全审查 Prompt。
- `docs/gpt/README.md`：同步浏览器 GPT 专项复核文件清单和 V1-E 后续边界。
- `tasks/current.md`：记录 V1-D 浏览器 GPT 安全审查交付包。

结论：

- 本轮停止在 V1-D 安全审查交付，不继续迁移策略、扫描、live evaluator、Web 或报告链路。
- 若后续继续，必须另开 `INDICATOR-KERNEL-V1-E-SINGLE-CALLER-MIGRATION` 或同等单调用方迁移任务。
- V1-E 只能选择一个调用方，固定兼容 policy，并对比迁移前后 golden vector、策略输出和必要回归。
- 不允许一口气替换整条策略链；如输出差异影响信号、时点或报告指标，必须升策略版本并重跑审查。

### 2026-07-11 Indicator Kernel V1-E Web MACD Readonly

外部审查收口：

- 浏览器 GPT 对 V1-D 给出“有条件通过”，允许关闭为 `MACD/ATR compatibility draft and migration design completed`。
- V1-D golden vector 只证明指定输入和指定 legacy policy 下可复刻，不证明真实调用方可安全替换。
- MACD / ATR 仍为 `v1-draft`，不进入 `indicator_registry`，不能写成 `MACD/ATR unified`。

新增范围：

- `services/quant-api/app/api/market.py`：新增 `/api/v1/market/indicators/macd` 只读接口。
- `services/quant-api/app/services/market_workbench.py`：复用 `get_market_bars()` 读取同一批 bars，并以 `web_macd_legacy_v1` 调用公共 `macd_series()`。
- `services/quant-api/app/schemas/market.py`：新增 Market MACD response schema。
- `services/quant-api/tests/test_market_macd_indicator_api.py`：覆盖 synthetic vector、固定 JM fixture、NaN/null、短窗口、prefix invariance、只读 API 和 unsupported policy。
- `apps/quant-web/src/api/market.ts`、`apps/quant-web/src/types/market.ts`：新增 Market MACD API 类型和请求函数。
- `apps/quant-web/src/utils/macdOverride.ts`、`apps/quant-web/tests/macdOverride.test.ts`：新增后端 MACD override 转换和测试。
- `apps/quant-web/src/components/kline/KlineChart.vue`：新增可选 `macdOverride`，有后端 MACD 时优先渲染，否则保留原 `calculateMACD()`。
- `apps/quant-web/src/pages/market/chart.vue`：仅 Market 页面请求并传入后端 MACD，失败时 warning 并回退前端展示计算。

边界：

- 只迁移 Market 页面 MACD 只读展示。
- Backtest / Review 不传 `macdOverride`，继续使用旧前端计算。
- 不迁移 ATR、FastAPI strategy、`quant-core` strategy、JM V1-B、historical scan、live evaluator。
- 不修改 `report_id=14` 基线，不写 DB，不写 `strategy_signals` / `signal_events`，不发送企业微信。
- API response 对 Web policy 做旧 Web 对齐裁剪，DIF / DEA / HIST 只在 DEA ready bar 一起输出，避免比旧 Web 多画早期 DIF。

测试结果：

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

- V1-C + V1-E API：12 passed
- Indicator Kernel V1-A/B/C/D：27 passed
- JM V1-B + live evaluator：13 passed
- 前端 MACD override：2 passed
- 前端 build：passed，Vite chunk size warning 不阻塞
- `git diff --check`：passed
- targeted ruff：passed
- 禁止链路 diff 核对：无输出

### 2026-07-12 HTDY 原始公式阻塞解除

新增范围：

- `docs/strategy_specs/htdy/INDICATOR_SPEC.md`：归档用户提供的完整通达信公式，拆解 `ZK1/ZD1/ZD2`、黄K/白K、三连 `买多/卖空`、`VAR23/回调买/XG`、`DDX/XG2`。
- `docs/strategy_specs/htdy/INDICATOR_RISK_REVIEW.md`：逐项标记 `XMA`、双 XMA 通道、`VAR23`、三连提示、`XG`、`XG2` 的未来函数和重绘风险。
- `docs/strategy_specs/htdy/STRATEGY_SPEC.md`：新增 `huotian_dayou_original_v0` observation-only 策略骨架。
- `services/quant-api/tests/test_htdy_indicator_risk.py`：新增最小文档风险回归测试。
- `docs/strategy_specs/htdy/README.md`、`docs/INDICATOR_KERNEL.md`、`tasks/current.md`：同步阻塞解除、剩余 Gate 和后续步骤。

结论：

- “缺少原始公式”阻塞已解除。
- “可回测 / 可 live / 可预警”阻塞未解除。
- 原始 `买多预警` / `卖空预警` 只翻译为 observation 字段，不写 `signal_events`，不进企业微信。
- 当前不修改 Web、正式策略、扫描、live evaluator、数据库、报告或通知链路。

测试结果：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_indicator_risk.py services/quant-api/tests/test_tdx_xma_indicator_risk.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py
```

- HTDY + XMA 风险回归：8 passed
- Indicator Kernel 回归：7 passed

### 2026-07-12 HTDY 原始 Observation-Only PoC

新增范围：

- `experiments/htdy_indicator/htdy_original_core.py`：复刻 `huotian_dayou_original_v0` 原始公式完整数值输出。
- `experiments/htdy_indicator/export_htdy_original.py`：支持 synthetic sample 和本地 CSV 输入，导出 JSON / CSV。
- `experiments/htdy_indicator/README.md`：记录运行方式、输出字段和 observation-only 边界。
- `services/quant-api/tests/test_htdy_original_poc.py`：覆盖字段完整性、三连提示、XMA future-tail repaint、XG/XG2 风险 metadata。
- `docs/strategy_specs/htdy/README.md`、`tasks/current.md`：同步 PoC 状态和剩余 Gate。

PoC 输出：

```text
ZK1, ZD1, ZD2, 黄K, 白K, 买多信号, 卖空信号,
VAR23, 回调买, XG, DDX, V2, V5, V10, V20, DY, DY2, XG2, XG2_DRAWTEXT
```

结论：

- 第 1 步“原始 observation-only PoC”已完成。
- 原始公式仍保留 `XMA` 未来函数和重绘风险，不能用于可信回测、live evaluator、`signal_events` 或企业微信。
- `CAPITAL` 默认按期货 `0` 分支，`FROMOPEN` PoC 默认 `1.0`，`CURRBARSCOUNT` 只按 PoC 图表末端语义处理。
- 本轮不做 Web 观察层对齐、不做 strict backward-looking 改写、不做 Golden Sample、不做正式候选接入评估。

测试结果：

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

### 2026-07-12 HTDY Web Observation-Only Alignment

新增范围：

- `apps/quant-web/src/utils/indicators.ts`：按原公式三条黄色 `STICKLINE`、白色实体越轨和 `VAR23/回调买/XG` 重建 Web observation-only 输出，中间数值不提前舍入。
- `apps/quant-web/src/components/kline/KlineChart.vue`：从整根 K 覆盖改为分段 SVG 绘制，并显示去指令化 `XG观察`。
- `apps/quant-web/tests/indicators.test.ts`：覆盖黄K/白K严格边界、先白后黄、三连首次提示、确定性 XG、XG2 排除和 future-tail 重绘。
- `docs/strategy_specs/htdy/INDICATOR_SPEC.md` 与 `tasks/current.md`：记录第 2 步完成和 XG/XG2 决策。

决策与边界：

- 显示 `XG观察`，但只存在于 SVG 观察覆盖层，不进入正式 marker、信号、回测或通知。
- 不显示 `XG2`，因为 `CURRBARSCOUNT` 的历史图表语义未定。
- 页面明示“观察专用·会重绘·XG 已显示·XG2 未展示”。
- 本步不改 FastAPI、DB、migration、strategy、scanner、live evaluator、`strategy_signals`、`signal_events`、企业微信或 `report_id=14`。
- strict backward-looking、Golden Sample 和正式候选接入仍为独立后续 Gate。

测试结果：

```bash
pnpm --dir apps/quant-web exec node --test tests/indicators.test.ts
pnpm --dir apps/quant-web build
```

- 前端指标：13 passed
- 前端 build：passed，仅存在已知 Vite chunk size warning

浏览器结果：

- Market JM2609 15m 成功加载 1,471 根 primary/passed bars。
- `1440/1280/1024` 三档均无水平溢出，HTDY 分段 SVG、风险文案和 XG 标记可见，XG2 标记为 0。
- 主图点击后 linked crosshair 和 hover 时间更新正常。
- HTDY 本身无 console error/warn；整页仍有旧 `8000` API 缺少本 worktree V1-E MACD endpoint 产生的 1 条 404。由于当前 worktree 无 `.env`，未绕过 DB 凭据 Gate，本轮不将整页 console 标记为 full green。

### 2026-07-12 HTDY Strict Backward-Looking V1

新增范围：

- `docs/strategy_specs/htdy/STRICT_V1_SPEC.md`：新增 `huotian_dayou_strict_v1` 独立研究候选方案。
- `experiments/htdy_indicator/htdy_strict_core.py`：新增 strict 纯函数实现，使用 `double_trailing_ema` 替代原始双层 `XMA`。
- `services/quant-api/tests/test_htdy_strict_core.py`：新增 future-tail、append consistency、warm-up、空输入、短序列、非法参数和字段白名单测试。
- `docs/strategy_specs/htdy/README.md`、`INDICATOR_SPEC.md`、`INDICATOR_RISK_REVIEW.md`、`STRATEGY_SPEC.md`、`experiments/htdy_indicator/README.md`、`tasks/current.md`：同步第 3 步完成状态。

决策与边界：

- strict v1 是 `strict_research_candidate`，不是 `validated` 指标或正式策略。
- strict v1 不覆盖 `huotian_dayou_original_v0`；原始版本仍为 `observation_only` 且会重绘。
- `XG2`、`DY/DY2`、`DDX/V2/V5/V10/V20` 暂不进入 strict v1。
- 不改 Web、FastAPI 业务接口、DB、migration、正式策略、scanner、live evaluator、`strategy_signals`、`signal_events`、企业微信或 `report_id=14`。
- Golden Sample 验收和正式候选接入评估仍是后续独立 Gate。

测试结果：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_strict_core.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_htdy_indicator_risk.py services/quant-api/tests/test_htdy_original_poc.py services/quant-api/tests/test_htdy_strict_core.py
uv run --project services/quant-api ruff check experiments/htdy_indicator services/quant-api/tests/test_htdy_strict_core.py
```

- HTDY strict v1 专项：6 passed
- HTDY original + strict 回归：15 passed
- targeted ruff：passed

### 2026-07-12 HTDY Step 5 Offline Candidate Eval

新增范围：

- `docs/strategy_specs/htdy/OFFLINE_CANDIDATE_EVAL.md`：定义第 5 步离线候选评估边界、版本命名和验收标准。
- `experiments/htdy_indicator/offline_candidate_eval.py`：新增只读 runner，读取 JM 15m `primary/passed` parquet 并输出 strict v1 candidate events。
- `services/quant-api/tests/test_htdy_offline_candidate_eval.py`：新增版本、能力边界、lineage、下一根 open 拟对照时点、短窗口和 Markdown 输出测试。
- `docs/strategy_specs/htdy/README.md`、`STRICT_V1_SPEC.md`、`INDICATOR_RISK_REVIEW.md`、`experiments/htdy_indicator/README.md`、`tasks/current.md`：同步第 5 步状态。

固定命名：

```text
strategy_code=huotian_dayou_strict
strategy_version=v0.1.0-offline
candidate_policy=strict_v1_15m_offline_v0
fill_policy=signal_on_close_fill_next_bar_open
execution_scope=offline_comparison_only
```

决策与边界：

- 第 5 步只允许输出 `candidate_events_only`。
- `buy_observation/xg_observation` 只解释为 long entry candidate；`sell_observation` 只解释为 short or exit candidate。
- 当前 bar 收盘确认，下一根 open 仅作为拟对照时点。
- 不计算可信 PnL，不创建 backtest task，不写 `BacktestReport`。
- 不修改正式策略、FastAPI backtest API、DB/migration、scanner、live evaluator、`strategy_signals`、`signal_events`、企业微信或 `report_id=14`。

允许结论：

```text
huotian_dayou_strict_v1 offline backtest candidate evaluated
```

### 2026-07-13 HTDY Formal Backtest Candidate Dry-Run

新增范围：

- `docs/strategy_specs/htdy/FORMAL_BACKTEST_CANDIDATE_PLAN.md`：定义 `huotian_dayou_strict_v1` 进入正式可信回测候选的完整设计边界。
- `packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/`：新增 `huotian_dayou_strict / v0.1.0-backtest-candidate` 策略候选。
- `experiments/htdy_indicator/formal_backtest_candidate.py`：新增只读 dry-run helper，输出 normalized `trades / orders / strategy_execution_events / summary`。
- `services/quant-api/tests/test_htdy_formal_backtest_candidate.py`：新增策略规则、数据 Gate、成本、撮合和 trust audit 消费回归。
- `docs/strategy_specs/htdy/README.md`、`experiments/htdy_indicator/README.md`：增加 Formal Backtest Candidate 索引与边界说明。
- `tasks/current.md`、`docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md`：同步当前状态。

固定命名：

```text
indicator_version=huotian_dayou_strict_v1
strategy_code=huotian_dayou_strict
strategy_version=v0.1.0-backtest-candidate
candidate_policy=strict_v1_15m_formal_candidate_v0
fill_policy=signal_on_close_fill_next_bar_open
execution_scope=formal_backtest_candidate
```

实现结论：

- 当前已实现 dry-run formal candidate，不写真实 `BacktestReport`。
- 必须新建 task/report，不覆盖、不回填、不修改 `report_id=14`。
- 数据入口固定为 `rqdata/local_parquet + primary + passed`，默认 `jm.MAIN / 15m`。
- 成交口径固定为当前 bar 收盘确认，下一根 bar open 拟成交。
- 第一版使用 signal bar extreme 加减 `1` tick 止损、`1.5R` 止盈、最大持有 8 根。
- 同 bar 多空冲突空仓时跳过并记录 `conflict_candidate_skipped`；有持仓时先平仓，不允许同 bar 反手。
- dry-run 输出可被 `BacktestService.persist_result()` 消费，并在内存库中通过 trust audit 回归。
- 后续若新 report 生成后，必须执行 trust audit，并同时复查 `report_id=14` 不退化。

允许结论：

```text
huotian_dayou_strict / v0.1.0-backtest-candidate implemented as dry-run formal candidate
```

边界：

- 本步不写真实 `BacktestReport`，不写数据库。
- 不接 scanner、live evaluator、`strategy_signals`、`signal_events`、企业微信或实盘。
- 不把 HTDY 表述为 `validated`、正式策略、live-ready、alert-ready 或 trading-ready。
