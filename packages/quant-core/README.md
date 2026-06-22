# quant-core — 量化核心库

## 职责

`quant-core` 是所有策略和服务共享的基础库，提供：

- `BaseStrategy`：策略基类（回测与实盘共用）
- `RiskManager`：风控模块
- `PerformanceCalculator`：绩效计算
- `DataLoader`：数据加载工具
- `OrderManager`：订单管理

## 设计原则

- **回测实盘同一套代码**：BaseStrategy 同时支持历史回放和实盘运行
- **零副作用的纯函数**：绩效计算等工具函数必须是纯函数
- **类型安全**：所有公开接口必须有完整的类型注解

## 包结构（待初始化）

```
quant_core/
├── __init__.py
├── base/
│   ├── strategy.py    BaseStrategy
│   └── broker.py      经纪商抽象
├── risk/
│   └── manager.py     风控管理器
├── performance/
│   └── metrics.py     绩效指标计算
├── data/
│   └── loader.py      数据加载工具
└── utils/
    └── decimal_utils.py  Decimal 工具
```

## 开发状态

🚧 **待初始化** — 参见 `docs/ROADMAP.md` Phase 2
