# Indicator Kernel V1-A

更新时间：2026-07-20

## 1. 定位

`Indicator Kernel` 是 `packages/quant-core` 下的纯 Python 指标公共层，V1-A 冻结 EMA 和指标注册表，V1-B 完成 MACD / ATR 差异审计，V1-C 新增可复刻多口径的 MACD / ATR 公共函数，V1-D 完成逐调用方迁移设计和 golden vector 对照。X4-06 已补全 Registry V1 全生命周期 capability invariant 和 formal consumer allow/block；R45-05 最终只读复核确认阶段 4 为 `STAGE4_COMPLETED / INDICATOR_CONTRACT_READY`，并保持 `INDICATOR_REGISTRY_V1_READY / STRATEGY_INDICATOR_POLICY_READY / HTDY_STRICT_FORMAL_REPORT_READY / STRATEGY_VALIDATION_PROTOCOL_FROZEN`。

本阶段目标：

- 让 Web、回测、历史扫描和 live evaluator 后续可以复用同一套指标口径。
- 先提供可测试、无副作用、无外部依赖的基础函数。
- 保持现有 JM V1-B 策略、信号链和历史报告不变。

本阶段不做：

- 不改 FastAPI API。
- 不改 PostgreSQL / Alembic / DuckDB / Parquet。
- 不迁移 `jm_v1b_daily_direction_fast_entry`。
- 不接入 `signal_events`、企业微信、live scheduler 或自动交易。
- 不把火天大有 original 升级为正式回测或提醒指标；strict 仅允许 formal historical backtest/report 输入。

## 2. 代码位置

```text
packages/quant-core/guiyi_quant/indicators/
├── __init__.py
├── atr.py
├── ema.py
├── macd.py
├── models.py
├── policy.py
└── registry.py
```

`ema_series()`、`macd_series()`、`atr_series()` 只依赖 Python 标准库，输出与输入一一对齐。数值算法与 `MACD_VERSION` / `ATR_VERSION` 字符串在 C4-02 中未改动。

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

## 4. 指标注册表（Registry V1）

生命周期 status：

```text
draft
compatibility_validated
validated
strategy_candidate
live_candidate
alert_capable
observation_only
retired
```

硬规则：

- `draft / compatibility_validated` 不得 `backtest/live/alert`。
- `observation_only` 不得 `backtest/live/alert`。
- `strategy_candidate` 必须 confirmed-only、无重绘并显式 `backtest_capable=True`，不得拥有 `live/alert`。
- `validated` 必须 `repainting_risk=none` 且 `confirmed_only=True`。
- `live_candidate` 必须 confirmed-only、无重绘并显式 live capable，不得 alert。
- `alert_capable` 必须 confirmed-only、无重绘，同时具备 live 与 alert capability。
- `retired` 不得保留任何 consumer capability。
- unknown `indicator_code` / `formal_policy_id` fail-closed。
- formal consumer 必须同时满足 `allowed_consumers` 且不命中 `blocked_consumers`。

当前注册项：

| indicator_code | status | formal_policy_id | web | backtest | live | alert |
|---|---|---|---|---|---|---|
| `ema10` / `ema21` / `ema60` | `validated` | `ema_sma_window_v1` | yes | yes | yes | no |
| `macd` | `compatibility_validated` | `web_macd_legacy_v1` | yes | no | no | no |
| `atr` | `compatibility_validated` | `web_atr_wilder_sma_seed_v1` | yes | no | no | no |
| `huotian_dayou_original_v0` | `observation_only` | `huotian_dayou_original_v0` | yes | no | no | no |
| `huotian_dayou_strict_v1` | `strategy_candidate` | `huotian_dayou_strict_v1` | no | yes | no | no |

说明：

- `huo_tian_da_you` 仅为 alias，解析到 `huotian_dayou_original_v0`；不得与 strict 共用含混 code/version。
- MACD/ATR 的 `compatibility_validated` 不等于可进 formal strategy/signal；Market EMA API 仍只服务 `validated` EMA。
- JM V1-B / report 14 冻结 policy：`jm_v1b_report14_frozen_v1`（`frozen_legacy=True`）。
- `definition_to_metadata()` 可供未来报告 metadata 持久化；C4-02 不写 DB。
- X4-06 正式 Gate：`INDICATOR_REGISTRY_V1_READY / STRATEGY_INDICATOR_POLICY_READY`。
- R45-05 canonical closeout：`STAGE4_COMPLETED / INDICATOR_CONTRACT_READY`；该结论不改变 original observation-only 或 strict historical-only 边界。

火天大有当前只登记风险边界：

- Web 观察层基于 XMA 风格居中窗口，存在未来函数和重绘风险。
- original 不得写入 `StrategySignal`、`strategy_signals`、`signal_events`、正式报告或通知链路。
- strict 已具 formal historical backtest/report 输入资格，但不得接历史扫描、live evaluator、alert 或企业微信。
- 原始公式已归档到 `docs/strategy_specs/htdy/INDICATOR_SPEC.md`，公式级风险审查见 `docs/strategy_specs/htdy/INDICATOR_RISK_REVIEW.md`。
- `huotian_dayou_original_v0` 仍只能 observation-only；若要进入回测、live 或提醒，必须另起 strict backward-looking 版本。

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

## 5.1 HTDY 原始公式阻塞解除

`TASK-2026-07-11-002-htdy-indicator-core` 已补齐火天大有原始通达信公式文档：

```text
docs/strategy_specs/htdy/INDICATOR_SPEC.md
docs/strategy_specs/htdy/INDICATOR_RISK_REVIEW.md
docs/strategy_specs/htdy/STRATEGY_SPEC.md
services/quant-api/tests/test_htdy_indicator_risk.py
```

结论：

- “缺少原始公式”阻塞已解除。
- “可回测 / 可 live / 可预警”阻塞未解除。
- 原始 `买多预警` / `卖空预警` 只翻译为 observation 字段，不映射为 `signal_events`。
- 后续剩余路径：原始 observation-only PoC -> Web 观察层对齐 -> strict backward-looking 方案 -> Golden Sample -> 正式候选接入评估。

## 5.2 D4-00 源码 / XMA 审计状态（2026-07-19）

手册 D4-00 / `HTDY-SOURCE-XMA-AUDIT-400` 的审计产物已落盘，**不再重开**通达信源码或 XMA 公式审计：

```text
data/reports/indicator_contract_v1/htdy_source_formula_map.csv
data/reports/indicator_contract_v1/htdy_xma_semantics.md
data/reports/indicator_contract_v1/htdy_original_vs_strict_diff.md
```

最终 Gate：`HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。

边界：

- source freeze、original/strict boundary、XMA(25) 对称窗口偏移与仓库 off-by-one 等仅为 evidence，不是 pass Gate。
- 不得宣称 `HTDY_XMA_SEMANTICS_AUDITED` 或 original formal 化。
- original 继续 `observation_only`；该 unresolved Gate 不再阻断独立 causal strict 的 formal historical backtest/report 输入资格。
- strict Gate 为 `HTDY_STRICT_FORMAL_REPORT_READY`；这不创建报告、不证明策略有效，也不授权 live/alert。

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
- V1-D golden vector 只证明指定输入和指定 legacy policy 下可复刻现有口径，不证明真实调用方可安全替换。
- V1-D 关闭表述只能是 `MACD/ATR compatibility draft and migration design completed`，不能写成 `MACD/ATR unified` 或 `Strategy kernel migration completed`。

## 9. V1-E Web MACD 只读展示迁移

V1-E 只迁移 Market 页面 MACD 展示调用方：

- 固定 policy 为 `web_macd_legacy_v1`。
- policy 口径为 `fast=12`、`slow=26`、`signal=9`、`ema_seed_policy=sma_window`、`histogram_scale=2`、`round_digits=6`。
- 后端 `/api/v1/market/indicators/macd` 复用 `/api/v1/market/bars` 同一批 bars，再调用 `macd_series()` 返回只读 DIF / DEA / histogram。
- `apps/quant-web/src/pages/market/chart.vue` 仅向共享 `KlineChart` 传入 `macdOverride`，Backtest / Review 不传该字段，继续使用原 TypeScript `calculateMACD()`。
- 请求失败时 Market 页面回退前端展示计算；不写 DB，不写 `strategy_signals` / `signal_events`，不发送企业微信。

V1-E 不迁移：

- ATR。
- FastAPI strategy。
- `quant-core` strategy。
- JM V1-B。
- historical scan。
- live evaluator。
- 回测报告和 `report_id=14` 基线。
