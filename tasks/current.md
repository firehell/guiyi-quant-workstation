# 当前任务：INDICATOR-KERNEL-V1-D-MIGRATION-PLAN

生成时间：2026-07-11

Worktree：`/Volumes/扩展盘/guiyi-parallel/htdy-core`

分支：`codex/htdy-indicator-core`

状态：`DELIVERY_READY`

## 背景

`Indicator Kernel V1-A` 已新增公共 EMA 内核和注册表，`Indicator Kernel V1-B` 已完成 MACD / ATR 只读差异审计，`Indicator Kernel V1-C` 已新增可复刻多口径的 MACD / ATR draft 公共函数。

本轮进入 V1-D，但严格限定为：

- 逐调用方迁移设计。
- golden vector 对照测试。
- 不替换任何策略、扫描、live evaluator、Web 或报告链路。
- 不注册 MACD / ATR 为 `validated`。
- 不影响历史报告、策略、信号、live evaluator、Web、数据库、数据文件或企业微信。

## 本轮允许修改

- `services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py`
- `docs/INDICATOR_KERNEL.md`
- `docs/INDICATOR_KERNEL_V1D_MIGRATION_PLAN.md`
- `docs/gpt/INDICATOR_KERNEL_REVIEW_PROMPT.md`
- `docs/gpt/README.md`
- `docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md`
- `tasks/current.md`
- `packages/quant-core/README.md`

## 本轮禁止修改

- `packages/quant-core/guiyi_quant/strategies/`
- `services/quant-api/app/`
- `apps/`
- `data/`
- 数据库 migration
- 回测报告、`signal_events`、live evaluator、企业微信通知链路

## 已完成

- [x] V1-A：公共 EMA 内核和注册表。
- [x] V1-B：MACD / ATR 差异审计。
- [x] V1-C：MACD / ATR 多口径 draft 公共函数。
- [x] V1-D：新增迁移设计文档。
- [x] V1-D：新增逐调用方 golden vector 对照测试。
- [x] V1-D：跑完整必测命令。
- [x] V1-D：更新阶段交付记录。
- [x] V1-D：更新浏览器 GPT 安全审查 Prompt 与同步索引。

## 当前测试证据

V1-C 已通过：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_indicator_kernel_v1b_diff.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
uv run --project services/quant-api ruff check packages/quant-core/guiyi_quant/indicators services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

结果：

- V1-C MACD / ATR：10 passed
- V1-A + V1-B：12 passed
- JM V1-B 策略回归：7 passed
- XMA 风险回归：4 passed
- `git diff --check`：passed
- targeted ruff：passed
- 禁止目录 diff 核对：`packages/quant-core/guiyi_quant/strategies`、`services/quant-api/app`、`apps`、`data`、`.env`、`.env.example` 无 diff

V1-D 已通过：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_indicator_kernel_v1b_diff.py services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py services/quant-api/tests/test_live_signal_evaluator.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_ema21_vnpy_draft.py services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py services/quant-api/tests/test_su_bing_jm_daily_score2of4.py services/quant-api/tests/test_su_bing_jm_daily_trend_cross_score2.py
uv run --project services/quant-api ruff check services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
git diff --check
git diff --name-only -- packages/quant-core/guiyi_quant/strategies services/quant-api/app apps data .env .env.example
```

结果：

- V1-D golden vector：5 passed
- Indicator Kernel V1-A/B/C/D：27 passed
- JM V1-B + live evaluator：13 passed
- 策略族回归：33 passed
- V1-D targeted ruff：passed
- `git diff --check`：passed
- 禁止目录 diff 核对：无输出

## 后续 Gate

V1-D 完成后，若要把 MACD / ATR 迁移到任何策略、扫描、live evaluator 或 Web 调用方，必须另开 V1-E 或单独策略版本任务：

- 固定唯一调用方与兼容 policy。
- 对比迁移前后 golden vector 与策略输出。
- 现有策略输出若有差异，必须升策略版本并重跑回归。
- 不允许静默替换历史口径。

## 浏览器 GPT 安全审查交付包

请优先复制：

```text
docs/gpt/INDICATOR_KERNEL_REVIEW_PROMPT.md
```

同时附带：

```text
docs/INDICATOR_KERNEL.md
docs/INDICATOR_KERNEL_V1B_DIFF.md
docs/INDICATOR_KERNEL_V1C_PLAN.md
docs/INDICATOR_KERNEL_V1D_MIGRATION_PLAN.md
services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
docs/tasks/TASK-2026-07-11-002-htdy-indicator-core.md
tasks/current.md
```

审查结论未返回前，不继续 V1-E；若继续 V1-E，也只能选择单一调用方迁移，不允许一口气替换整条策略链。
