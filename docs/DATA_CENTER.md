# DATA_CENTER.md — 数据中心设计

> 版本：v0.1 · 状态：草稿 · 更新日期：2026-06-22

---

## 1. 数据目录结构

```
data/
├── raw/                    原始数据（只写不删）
│   ├── ctp/               CTP 实盘 tick 数据
│   ├── akshare/           AKShare 历史数据
│   └── tushare/           Tushare 数据
│
├── processed/             预处理后数据
│   ├── daily/             日线 OHLCV
│   ├── hourly/            小时线 OHLCV
│   └── minute/            分钟线 OHLCV
│
├── parquet/               分析用 Parquet 格式
│   ├── <symbol>/          按品种分目录
│   │   ├── daily.parquet
│   │   ├── hourly.parquet
│   │   └── minute_1.parquet
│   └── _metadata/         元数据
│
└── sample/                测试用小数据集（入库）
    ├── IF_daily.parquet
    └── rb_minute_1.parquet
```

---

## 2. 数据格式规范

### OHLCV 标准字段

```python
# Parquet 列定义
schema = {
    "datetime": "datetime64[ns]",   # 时间戳（北京时间）
    "symbol": "str",                # 合约代码，如 IF2412
    "open": "float64",              # 开盘价
    "high": "float64",              # 最高价
    "low": "float64",               # 最低价
    "close": "float64",             # 收盘价
    "volume": "int64",              # 成交量（手）
    "open_interest": "int64",       # 持仓量（手）
    "turnover": "float64",          # 成交额（元）
}
```

---

## 3. 数据源优先级

| 优先级 | 数据源 | 类型 | 延迟 | 成本 |
|---|---|---|---|---|
| 1 | CTP 实盘 | Tick | 实时 | 需开户 |
| 2 | Tushare Pro | 日线/分钟线 | T+1 | 付费积分 |
| 3 | AKShare | 日线 | T+1 | 免费 |

---

## 4. 数据管理规则

- `data/raw/` 只追加，**严禁删除或覆盖**
- 处理脚本放 `scripts/data/` 目录
- 新品种数据入库后更新本文档的品种列表
- 数据质量异常（缺失、异常值）记录到 `data/_quality_report.md`
