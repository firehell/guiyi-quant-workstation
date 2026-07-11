# Indicator Kernel V1-A

更新时间：2026-07-11

## 1. 定位

`Indicator Kernel` 是 `packages/quant-core` 下的纯 Python 指标公共层，V1-A 冻结 EMA 和指标注册表，V1-B 完成 MACD / ATR 差异审计，V1-C 新增可复刻多口径的 MACD / ATR 公共函数，V1-D 完成逐调用方迁移设计和 golden vector 对照。

本阶段目标：

- 让 Web、回测、历史扫描和 live evaluator 后续可以复用同一套指标口径。
- 先提供可测试、无副作用、无外部依赖的基础函数。
- 保持现有 JM V1-B 策略、信号链和历史报告不变。

本阶段不做：

- 不改 FastAPI API。
- 不改 PostgreSQL / Alembic / DuckDB / Parquet。
- 不迁移 `jm_v1b_daily_direction_fast_entry`。
- 不接入 `signal_events`、企业微信、live scheduler 或自动交易。
- 不把火天大有升级为正式回测或提醒指标。

## 2. 代码位置

```text
packages/quant-core/guiyi_quant/indicators/
├── __init__.py
├── atr.py
├── ema.py
├── macd.py
├── models.py
└── registry.py
```

`ema_series()`、`macd_series()`、`atr_series()` 只依赖 Python 标准库，输出与输入一一对齐。

## 3. EMA V1 口径

默认口径：

```text
alpha = 2 / (period + 1)
seed_policy = sma_window
first_ready_index = period - 1
seed_value = average(close[0:period])
ema[i] = (close[i] - ema[i-1]) * alpha + ema[i-1]
```

说明：

- `sma_window` 是默认口径，用于对齐当前 Web `calculateEMA(bars, period)`。
- warm-up 区间返回 `ready=false`，不返回数值。
- `close` 为 `None`、`NaN` 或无限值时，该 bar 输出 `valid=false`，不静默补 0。
- 遇到无效输入后，后续必须重新取得一个完整的 `period` 有效窗口才能恢复输出。
- EMA 只使用当前和过去 bar，`repainting_risk=none`。
- 正式策略、扫描和 live evaluator 只能使用 confirmed bar 输出；未确认 bar 只能作为 Web 临时预览。

兼容口径：

- `seed_policy=first_value` 仅为后续兼容旧策略或实验代码预留。
- 旧策略若迁移到公共内核，必须显式选择 seed policy，并通过回归测试证明历史输出差异可接受；否则升策略版本。

## 4. 指标注册表

当前注册项：

| indicator_code | status | repainting_risk | web | backtest | live | alert |
|---|---|---|---|---|---|---|
| `ema10` | `validated` | `none` | yes | yes | yes | yes |
| `ema21` | `validated` | `none` | yes | yes | yes | yes |
| `ema60` | `validated` | `none` | yes | yes | yes | yes |
| `huo_tian_da_you` | `observation_only` | `known` | yes | no | no | no |

火天大有当前只登记风险边界：

- Web 观察层基于 XMA 风格居中窗口，存在未来函数和重绘风险。
- 不得写入 `StrategySignal`、`strategy_signals`、`signal_events`、正式报告或通知链路。
- 不得接入历史扫描、live evaluator、vn.py 正式回测或企业微信。
- 若用户补充 `private_sources/htdy/formula.txt`，也必须先做公式 Spec、风险审查和 backward-looking 改写 Plan。

## 5. 验收

最小验证命令：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
```

通过标准：

- EMA10/21/60 使用同一份 Python 算法。
- EMA21 默认 seed 口径与当前 Web EMA 对齐。
- 未来尾部变化不会改变既有 EMA 输出。
- 火天大有仍被注册为 observation-only，且 `alert_capable=false`。
- JM V1-B 现有策略测试不退化。

## 6. V1-B MACD / ATR 差异审计

V1-B 不把 MACD / ATR 纳入正式公共内核，只完成只读差异对照。

结论：

- Web MACD 使用 `sma_window` seed，histogram 为 `(DIF - DEA) * 2`。
- 多个 Python 策略使用 `first_value` seed，histogram 为 `DIF - DEA` 或不直接输出。
- Web ATR 使用 Wilder + SMA seed。
- 现有 Python 策略存在 Wilder first-TR seed 和 EMA(first TR) 风格 ATR。
- 这些差异会影响信号、止损和回测结果，不能静默替换。

详见：

```text
docs/INDICATOR_KERNEL_V1B_DIFF.md
services/quant-api/tests/test_indicator_kernel_v1b_diff.py
```

## 7. V1-C MACD / ATR 多口径公共函数

V1-C 已取消 GPT 强制前置 Gate，外部审查改为可选；本阶段只新增公共函数、测试和文档，不迁移任何调用方。

新增接口：

```text
macd_series(closes, fast, slow, signal, *, ema_seed_policy, histogram_scale, bar_ends=None, round_digits=6)
atr_series(highs, lows, closes, period, *, smoothing_policy, bar_ends=None, round_digits=6)
```

MACD 支持：

- `ema_seed_policy=sma_window` + `histogram_scale=2`：复刻当前 Web 展示口径。
- `ema_seed_policy=first_value` + `histogram_scale=1`：复刻当前 Python strategy 风格口径。

ATR 支持：

- `smoothing_policy=wilder_sma_seed`：复刻当前 Web ATR。
- `smoothing_policy=wilder_first_tr`：复刻 FastAPI 策略 ATR。
- `smoothing_policy=ema_first_tr`：复刻当前 `quant-core` 策略 ATR。

安全边界：

- MACD / ATR 当前是 `v1-draft` 公共函数，不写入 `indicator_registry`，不注册为 `validated`。
- 不修改 `packages/quant-core/guiyi_quant/strategies/`、`services/quant-api/app/`、`apps/`、`data/`、数据库、报告、`signal_events`、live evaluator 或企业微信。
- invalid 输入返回 `valid=false` 或 warm-up 状态，不补 0。
- future-tail perturbation 不改变既有输出。

V1-D / 迁移 Gate：

- 每个迁移目标必须显式选择 MACD `ema_seed_policy`、`histogram_scale` 和 ATR `smoothing_policy`。
- 每个迁移目标必须有迁移前后的 golden vector 和策略回归测试。
- 任何输出差异都必须升策略版本或保持旧链路不变。

V1-C 最小验证命令：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1b_diff.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_tdx_xma_indicator_risk.py
git diff --check
uv run --project services/quant-api ruff check packages/quant-core/guiyi_quant/indicators services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py
```

## 8. V1-D 迁移设计与 golden vector 对照

V1-D 只做 `Migration Plan + Compatibility Vectors`，不做真实迁移。

新增：

```text
docs/INDICATOR_KERNEL_V1D_MIGRATION_PLAN.md
services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
```

调用方 policy：

| 调用方 | EMA / MACD policy | histogram | ATR policy | V1-D 结论 |
|---|---|---|---|---|
| Web `apps/quant-web/src/utils/indicators.ts` | `sma_window` | `2` | `wilder_sma_seed` | 仅文档登记，不改 `apps/` |
| FastAPI `app/strategy/su_bing_ema21.py` | `first_value` | `1` | `wilder_first_tr` | golden vector 一致才允许后续迁移 |
| `quant-core` `su_bing_ema21` | `first_value` | `1` | `ema_first_tr` | golden vector 一致才允许后续迁移 |
| `jm_v1b_daily_direction_fast_entry` | `first_value` | 不直接输出 | `ema_first_tr` | P0 可信链路，只对照不迁移 |
| `live_signal_evaluator.py` | 继承 JM V1-B | 不直接输出 | 继承 JM V1-B | P0 预览链路，只回归不迁移 |
| 日线 MACD / score 策略族 | `first_value` | `1` | 不使用 | golden vector 一致才允许后续迁移 |

V1-D 后续 Gate：

- MACD / ATR 仍不进入 `indicator_registry`，不注册为 `validated`。
- 任何真实替换必须另开 V1-E 或单独策略版本任务。
- 若迁移后策略输出、信号时点或报告指标有差异，必须升策略版本并重跑回测 / 信号审查。
