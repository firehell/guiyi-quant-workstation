# Indicator Kernel V1-B MACD / ATR Difference Audit

更新时间：2026-07-11

## 1. 结论

V1-B 只做 MACD / ATR 差异审计，不把它们注册为 `validated` 公共指标，也不替换任何策略、扫描、live evaluator 或 Web 调用链。

原因：

- 当前 Web、FastAPI 策略和 `quant-core` 策略的 MACD / ATR seed、warm-up、histogram scale、ATR smoothing 口径不一致。
- 这些差异会影响 MACD 金叉/死叉、近零轴过滤、ATR 止损、EMA 距离过滤和回测结果。
- 静默替换会改变历史策略行为，破坏 `report_id=14` 一类可信回归基线。

## 2. 当前实现对照

| 位置 | MACD EMA seed | MACD histogram | ATR seed / smoothing | 当前角色 |
|---|---|---|---|---|
| `apps/quant-web/src/utils/indicators.ts` | `sma_window` | `(DIF - DEA) * 2` | Wilder，首值为 `period` 根 TR 的 SMA | Web 展示 |
| `services/quant-api/app/strategy/su_bing_ema21.py` | `first_value` | `DIF - DEA` | Wilder，首值为第一根 TR | 后端扫描策略 |
| `packages/quant-core/.../su_bing_ema21` | `first_value` | 未单独输出 histogram | EMA(first TR) 风格 ATR | vn.py 策略草稿 |
| `packages/quant-core/.../jm_v1b_daily_direction_fast_entry` | `first_value` | 未单独输出 histogram | EMA(first TR) 风格 ATR | JM V1-B 可信链路 |
| `packages/quant-core/.../su_bing_jm_daily_ema21_macd_volume` | `first_value` | `DIF - DEA` | 不使用 ATR | 独立日线策略 |
| `packages/quant-core/.../su_bing_jm_daily_score2of4` | `first_value` | `DIF - DEA` | 不使用 ATR | 独立日线策略 |

## 3. 风险分级

P0：

- 不得在本阶段把 MACD / ATR 公共函数接入策略、回测、历史扫描、live evaluator 或企业微信。
- 不得把 Web `histogram * 2` 展示口径误用于策略阈值或回测信号。
- 不得用 `sma_window` seed 静默替换 `first_value` seed 的历史策略。

P1：

- 若后续进入 V1-C，公共 MACD 必须显式支持 `ema_seed_policy` 和 `histogram_scale`。
- 公共 ATR 必须显式支持 `smoothing_policy`：`wilder_sma_seed`、`wilder_first_tr`、`ema_first_tr`。
- 策略迁移必须逐策略做 golden vector 对照，并记录是否升策略版本。

P2：

- 可以后续增加 TypeScript / Python shared golden fixture，减少 Web 与 Python 展示口径漂移。
- 可以后续统一文档命名：`DIF/DEA/histogram`、`macd_diff/macd_dea/macd_hist`。

## 4. Golden Vector 规则

本阶段新增 `services/quant-api/tests/test_indicator_kernel_v1b_diff.py`，只固化差异事实：

- EMA seed 差异会导致 MACD DIF / DEA 不同。
- Web histogram scale 为 `2`，策略 histogram scale 为 `1`。
- ATR 的 `wilder_sma_seed`、`wilder_first_tr`、`ema_first_tr` 输出不同。
- 修改未来尾部不会改变既有 MACD / ATR 输出，保持无未来函数底线。
- `macd` 和 `atr` 当前不在公共指标注册表中。

## 5. V1-C Gate

只有同时满足以下条件，才允许进入 MACD / ATR 公共内核实现：

1. 公共函数能通过显式 policy 复刻每一种现有口径。
2. 每个迁移目标都有 golden vector 对照。
3. JM V1-B 策略回归、XMA 风险回归和公共指标测试全部通过。
4. 不改变历史报告、不重跑可信基线、不写 `signal_events`。
5. 若输出不同，必须升策略版本并单独开回测/信号审查任务。

## 6. 本阶段不做

- 不新增 `macd.py` / `atr.py` 公共正式模块。
- 不修改 `packages/quant-core/guiyi_quant/strategies/`。
- 不修改 `services/quant-api/app/strategy/`、`signal_scanner.py` 或 `live_signal_evaluator.py`。
- 不修改 `apps/quant-web/`。
- 不修改数据库、数据资产、回测报告或通知链路。
