# Indicator Kernel V1-C Development Plan

更新时间：2026-07-11

执行状态：`DELIVERY_READY`

已实现：

- `packages/quant-core/guiyi_quant/indicators/macd.py`
- `packages/quant-core/guiyi_quant/indicators/atr.py`
- `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`

已验证：V1-A、V1-B、V1-C、JM V1-B、XMA 风险回归、`git diff --check`、targeted ruff 均通过。

## 1. Gate 调整

用户已取消“浏览器 GPT 必须先通过”的硬 Gate。V1-A / V1-B checkpoint 仍可交给外部 GPT 做可选安全审查，但 V1-C 允许由 Codex 直接执行。

本阶段仍保留强边界：

- 只实现公共函数、测试和文档。
- 不迁移策略、扫描、live evaluator、Web、数据库、报告或通知链路。
- 不把 MACD / ATR 注册为 `validated`。
- 不影响 `report_id=14`、JM V1-B 策略、`signal_events`、企业微信或火天大有 observation-only 边界。

## 2. 目标

V1-C 只设计并实现可复刻多口径的公共 MACD / ATR 函数：

- `packages/quant-core/guiyi_quant/indicators/macd.py`
- `packages/quant-core/guiyi_quant/indicators/atr.py`
- `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`

本阶段仍不迁移：

- `packages/quant-core/guiyi_quant/strategies/`
- `services/quant-api/app/strategy/`
- `services/quant-api/app/services/signal_scanner.py`
- `services/quant-api/app/services/live_signal_evaluator.py`
- `apps/quant-web/`
- 数据库、数据文件、回测报告、`signal_events`、企业微信

## 3. 公共接口

MACD：

```text
macd_series(
    closes,
    fast,
    slow,
    signal,
    *,
    ema_seed_policy,
    histogram_scale,
    bar_ends=None,
    round_digits=6,
)
```

要求：

- `ema_seed_policy` 支持 `sma_window` 和 `first_value`。
- `histogram_scale` 支持 `1` 和 `2`。
- 输出 DIF / DEA / histogram 与输入长度对齐。
- warm-up、invalid 输入、短序列必须显式标记，不补 0。
- 不改变未来尾部前的历史输出。

ATR：

```text
atr_series(
    highs,
    lows,
    closes,
    period,
    *,
    smoothing_policy,
    bar_ends=None,
    round_digits=6,
)
```

要求：

- `smoothing_policy` 支持 `wilder_sma_seed`、`wilder_first_tr`、`ema_first_tr`。
- 输出 ATR 与输入长度对齐。
- `high/low/close` 长度不一致必须报错。
- invalid 输入不得静默补 0。
- 不改变未来尾部前的历史输出。

## 4. 注册表策略

V1-C 不把 MACD / ATR 注册为 `validated`。

当前选择：暂不写入 `indicator_registry`，只保留公共函数和测试。V1-B / V1-C 测试继续断言 `macd` / `atr` 未进入正式注册表。

## 5. 测试计划

必须新增 `services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py`，覆盖：

- MACD 复刻 Web 口径：`sma_window` seed + `histogram_scale=2`。
- MACD 复刻 Python strategy 口径：`first_value` seed + `histogram_scale=1`。
- ATR 复刻三类口径：`wilder_sma_seed`、`wilder_first_tr`、`ema_first_tr`。
- 短序列、invalid 输入、长度不一致、非法 policy。
- future-tail perturbation 不改变既有输出。
- `macd` / `atr` 未进入正式注册表。
- 策略/API/Web/data 目录无 diff。

必跑命令：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1b_diff.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
uv run --project services/quant-api ruff check packages/quant-core/guiyi_quant/indicators services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

## 6. 验收标准

- MACD / ATR 公共函数可以复刻现有多口径输出。
- 未修改策略、API、Web、live、信号、数据库、报告或通知链路。
- JM V1-B 和 XMA 风险回归不退化。
- 如任何迁移目标输出不同，V1-C 必须停止在公共函数阶段，不得继续迁移。

## 7. 后续

V1-C 完成后，若要迁移调用方，必须另开迁移 Plan：

- 逐策略选择兼容 policy。
- 对比迁移前后输出。
- 输出一致才能迁移；不一致则升策略版本并重跑回测/信号审查。
