# quant-core — 量化核心库

## 职责

`quant-core` 是归一量化研究闭环的共享库，当前优先承载 Indicator Kernel（指标计算、
formal policy、能力矩阵）与可复用的研究辅助结构。

- `indicators/`：EMA、MACD、ATR、火天大有 original/strict 等无副作用指标函数与 Registry。
- 旧 `strategies/` vn.py `CtaTemplate` 策略研究草稿已退役，仅 Git history 可追溯；未来策略/回测须按新任务重建。

## 设计原则

- **只服务研究闭环**：数据、指标、复盘和信号语义；**非 Web 入口**（当前 Web 仅 Market）。不写自动实盘下单逻辑。
- **Indicator Kernel 为权威**：算法与 formal policy 只在 `guiyi_quant/indicators/`；Web TS 仅为观察镜像。
- **外部数据源隔离**：指标与未来策略不得直接调用 RQData、TqSdk、TuShare 或读取 raw 文件，统一读取本地标准化数据。
- **依赖边界清晰**：RQData 是 V1 主数据源；TqSdk 仅是 V2 候选 / 历史 validation 工具；TuShare 仅是后期辅助数据候选。
- **零副作用的纯函数**：绩效/指标计算等工具函数必须是纯函数。
- **类型安全**：所有公开接口必须有完整的类型注解。

## 包结构

```
guiyi_quant/
├── indicators/
│   ├── __init__.py
│   ├── atr.py
│   ├── ema.py
│   ├── htdy_original.py
│   ├── htdy_strict.py
│   ├── macd.py
│   ├── models.py
│   ├── policy.py
│   ├── realtime_observation_policy.py
│   └── registry.py
```

## 已初始化指标

`Indicator Kernel` 已初始化：

- `guiyi_quant.indicators.ema.ema_series`：EMA10/21/60 共用的纯函数实现。
- `guiyi_quant.indicators.macd.macd_series`：V1-C draft，多口径 MACD 公共函数。
- `guiyi_quant.indicators.atr.atr_series`：V1-C draft，多口径 ATR 公共函数。
- `guiyi_quant.indicators.htdy_original`：original observation-only XMA kernel。
- `guiyi_quant.indicators.htdy_strict.compute_strict_fields`：causal strict kernel（`strategy_candidate`）。
- `guiyi_quant.indicators.registry`：Registry V1，登记 EMA / MACD / ATR / HTDY 双版本与能力边界。
- `guiyi_quant.indicators.policy`：formal policy 表与 `require_formal_policy` fail-closed 查询。
- 默认 EMA 口径为 `seed_policy=sma_window`，对齐当前 Web `calculateEMA`。
- MACD / ATR 已登记为 `compatibility_validated`（非正式 `validated`），不得据此静默迁移 live evaluator。
- 火天大有 original=`observation_only`；strict=`strategy_candidate`；不得进入 live / alert / 通知链路。

## 明确不做

- 不提供实盘 Broker / Gateway / OrderManager。
- 不接 CTP、TqSdk 实盘或无人值守自动交易。
- 不把交易练习者数据或旧天勤数据作为正式研究默认数据。
- 当前不提供回测引擎、adapter、策略包或兼容入口；未来重建回测/策略是全新任务。
- 指标包不直接读取 `.env`、外部账号、API Key 或交易密码。

## 开发状态

🚧 **部分初始化** — Indicator Kernel 与 HTDY 双版本已在 `indicators/`；策略研究源码已退役。详见
`STATUS.md`、`AGENTS.md` 和 `docs/INDICATOR_KERNEL.md`。
