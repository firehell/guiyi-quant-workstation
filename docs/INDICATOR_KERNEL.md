# Indicator Kernel V1-A

更新时间：2026-07-11

## 定位

`Indicator Kernel V1-A` 是 `packages/quant-core` 下的纯 Python 指标公共层，第一版只冻结 EMA 和指标注册表。

本阶段目标：

- 让 Web、回测、历史扫描和 live evaluator 后续可以复用同一套指标口径。
- 先提供可测试、无副作用、无外部依赖的基础函数。
- 保持现有 JM V1-B 策略、信号链和历史报告不变。

本阶段不做：

- 不改 PostgreSQL / Alembic / DuckDB / Parquet。
- 不迁移现有策略、扫描、回测或 live evaluator。
- 不把火天大有升级为正式回测或提醒指标。

## EMA V1 口径

默认口径：

```text
alpha = 2 / (period + 1)
seed_policy = sma_window
first_ready_index = period - 1
seed_value = average(close[0:period])
ema[i] = (close[i] - ema[i-1]) * alpha + ema[i-1]
```

说明：

- `sma_window` 是默认口径，用于对齐 C1 前 Web `calculateEMA(bars, period)`。
- warm-up 区间返回 `ready=false`，不返回数值。
- `close` 为 `None`、`NaN` 或无限值时，该 bar 输出 `valid=false`，不静默补 0。
- 遇到无效输入后，后续必须重新取得一个完整的 `period` 有效窗口才能恢复输出。
- EMA 只使用当前和过去 bar，`repainting_risk=none`。
- 正式策略、扫描和 live evaluator 只能使用 confirmed bar 输出；未确认 bar 只能作为 Web 临时预览。

## 指标注册表

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

## 验收

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py
git diff --check
```
