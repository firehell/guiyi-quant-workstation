# TASK-2026-07-11-002：火天大有指标与策略规范

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-002-htdy-indicator-core |
| GitHub Issue | #10 |
| Branch | codex/htdy-indicator-core |
| Worktree | /Volumes/扩展盘/guiyi-parallel/htdy-core |
| Status | DELIVERY_READY |
| 公式输入路径 | `private_sources/htdy/`（用户提供的通达信公式，gitignore） |

## 1. 任务状态

DELIVERY_READY

说明：

- Web 火天大有观察层已交付，见 `TASK-2026-07-11-003-web-main-indicators.md`。
- 私有 HTDY 通达信公式仍未提供，公式级 Spec / PoC / backward-looking 改写继续保持 Gate。
- 本轮已推进 `Indicator Kernel V1-A/V1-B/V1-C/V1-D`：EMA 公共内核、MACD/ATR 差异审计、MACD/ATR 多口径 draft 公共函数，以及逐调用方迁移设计 / golden vector 对照。
- MACD / ATR 仍未注册为 `validated`，未迁移任何策略、扫描、live、Web、数据库、报告或通知链路。

## 2. 任务类型

策略研究与验证 / 指标规范

## 3. 参与角色

- 必须：策略研究员、量化架构师、安全专家
- 不需要：前端、live runtime、企业微信

## 4. 背景

用户将提供「火天大有」通达信公式。仓库内尚无 HTDY 实现。需对照 `tdx_xma_bands` 风险审查模板，产出 observation-only 规范，**不接** vn.py 主链、信号扫描、企业微信。

## 5. 目标

1. 整理 `docs/strategy_specs/htdy/INDICATOR_SPEC.md`（参数、IO、公式逐步解释）
2. 编写 `INDICATOR_RISK_REVIEW.md`（lookahead、未来函数、过拟合、期货适配）
3. 编写 `STRATEGY_SPEC.md` 骨架（入场/出场/止损/过滤/周期），标记 `observation-only`
4. 可选：`experiments/htdy_indicator/` PoC（strictly backward-looking 改写优先）

## 6. 不做事项

- 不接入 `packages/quant-core/guiyi_quant/strategies/` 正式策略
- 不接入 PostgreSQL 报告、信号扫描、企业微信、vn.py Runner 主路径
- 不自动交易、不 live 提醒
- 不提交 `private_sources/` 内用户私有公式到 git（若含敏感内容）

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

1. 读取 `private_sources/htdy/` 用户公式
2. 参照 `docs/strategy_specs/tdx_xma_bands/INDICATOR_RISK_REVIEW.md`
3. 若 PoC：参照 `experiments/rqalpha_tdx_xma_bands/xma_core.py` 结构
4. 风险测试：未来函数/重绘检测 stub

## 12. 交互视觉要求

无 Web 变更（后续 Web overlay 属会话 C）

## 13. 安全权限要求

- 不提交 API Key；private_sources 已在 .gitignore

## 14. 开发步骤

1. 确认 `private_sources/htdy/` 有公式文件（用户放入）
2. Plan：公式解析与风险框架
3. Dev：编写三份 spec + 可选 PoC/测试
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

- [ ] 三份 spec 文件存在且互相引用一致
- [ ] 风险审查含 lookahead/未来函数章节
- [ ] 可选 pytest passed

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
- `services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py`：synthetic golden vector 对照测试。
- `docs/INDICATOR_KERNEL.md`、`packages/quant-core/README.md`、`tasks/current.md`：同步 V1-D 状态和边界。

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
