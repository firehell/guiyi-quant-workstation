# quant-core — 量化核心库

## 职责

`quant-core` 是归一量化 V1 研究闭环的共享库，优先承载可复用的策略规则、指标计算、参数 schema、风控计算和报告格式。

- `strategies/`：苏冰 EMA21、均线突破、N 字结构等策略规则和 vn.py `CtaTemplate` 草稿。
- `indicators/`：EMA、MACD、ATR、成交量等无副作用指标函数。
- `risk/`：单笔风险、保证金占用、最大回撤、连续亏损等研究风控计算。
- `PerformanceCalculator`：绩效计算
- `reports/`：回测结果标准化和复盘标签辅助结构。

## 设计原则

- **V1 只服务研究闭环**：数据、策略、回测、报告、复盘、信号，不写自动实盘下单逻辑。
- **vn.py 是回测底座**：V1 策略优先提供 vn.py `CtaTemplate` 版本；归一量化保留参数、风控、报告和复盘结构。
- **外部数据源隔离**：策略不直接调用 RQData、TqSdk、TuShare 或读取 raw 文件，统一读取本地标准化数据。
- **依赖边界清晰**：RQData 是 V1 主数据源；TqSdk 仅是 V2 候选 / 历史 validation 工具；TuShare 仅是后期辅助数据候选。
- **零副作用的纯函数**：绩效计算等工具函数必须是纯函数
- **类型安全**：所有公开接口必须有完整的类型注解

## 包结构

```
guiyi_quant/
├── __init__.py
├── strategies/
│   ├── su_bing_ema21/
│   │   ├── __init__.py
│   │   ├── vnpy_strategy.py
│   │   ├── config_schema.py
│   │   ├── default_params.json
│   │   ├── review_tags.json
│   │   └── README.md
│   ├── ma_breakout/
│   └── n_structure/
├── indicators/
├── risk/
├── reports/
└── utils/
```

## 已初始化策略

### `su_bing_ema21`

V1 已新增苏冰 EMA21 vn.py 策略草稿：

- 使用 vn.py `CtaTemplate` 兼容类。
- 只基于已完成 K 线计算 EMA21、MACD、ATR 和成交量过滤。
- 通过 `last_signal`、`signal_reason`、`trade_note` 输出复盘字段。
- 参数由 `config_schema.py` 和 `default_params.json` 统一维护。
- 当前不接正式回测 API，后续由 `vnpy_integration` adapter 负责接入。

```
guiyi_quant/strategies/su_bing_ema21/
├── __init__.py
├── vnpy_strategy.py
├── config_schema.py
├── default_params.json
├── review_tags.json
└── README.md
```

## 已初始化指标

```
guiyi_quant/
├── indicators/
```

`Indicator Kernel V1-A` 已初始化：

- `guiyi_quant.indicators.ema.ema_series`：EMA10/21/60 共用的纯函数实现。
- `guiyi_quant.indicators.macd.macd_series`：V1-C draft，多口径 MACD 公共函数，支持 Web 与 Python strategy 口径复刻。
- `guiyi_quant.indicators.atr.atr_series`：V1-C draft，多口径 ATR 公共函数，支持 Web、FastAPI strategy 和 quant-core strategy 口径复刻。
- `guiyi_quant.indicators.registry`：代码注册表，登记 EMA 和火天大有的能力边界。
- 默认 EMA 口径为 `seed_policy=sma_window`，对齐当前 Web `calculateEMA`。
- MACD / ATR 当前不写入 registry、不注册为 `validated`，不得据此迁移策略、扫描、live evaluator 或 Web 调用链。
- `Indicator Kernel V1-D` 仅新增迁移设计和 golden vector 对照，证明公共函数可复刻现有调用方口径；真实调用方迁移必须另开任务。
- 火天大有仅登记为 `observation_only`，不得进入回测、live evaluator、`signal_events` 或提醒链路。

历史规划中的完整目录如下，后续按任务逐步补齐：

```
guiyi_quant/
├── __init__.py
├── strategies/
│   ├── su_bing_ema21/
│   │   ├── vnpy_strategy.py
│   │   ├── config_schema.py
│   │   ├── default_params.json
│   │   └── review_tags.json
│   ├── ma_breakout/
│   └── n_structure/
├── indicators/
├── risk/
├── reports/
└── utils/
```

## 明确不做

- V1 不提供实盘 Broker / Gateway / OrderManager。
- V1 不接 CTP、TqSdk 实盘或无人值守自动交易。
- V1 不把交易练习者数据或旧天勤数据作为正式回测默认数据。
- V1 不从零自研完整回测引擎；回测执行交给 vn.py adapter。
- V1 策略包不直接读取 `.env`、外部账号、API Key 或交易密码。

## 开发状态

🚧 **部分初始化** — `su_bing_ema21` 已有 vn.py 策略草稿；其余模块参见 `docs/gpt/NEXT_STEPS.md` 和 `docs/ARCHITECTURE.md`
