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
- **零副作用的纯函数**：绩效计算等工具函数必须是纯函数
- **类型安全**：所有公开接口必须有完整的类型注解

## 包结构（待初始化）

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

## 开发状态

🚧 **待初始化** — 参见 `docs/ROADMAP.md` Phase 3 和 `docs/V1_REFACTOR_VNPY_RQDATA.md`
