---
name: futures-data
description: 期货数据采集与处理技能 — AKShare/Tushare/CTP 数据采集、清洗、Parquet 存储。
agent_created: false
tags: [data, pandas, parquet, akshare, futures]
---

# futures-data 技能

## 适用场景
- 采集期货历史行情数据
- 数据清洗与格式标准化
- Parquet 文件生成与管理
- 数据质量检查

## 数据源优先级
1. CTP（实时，需开户）
2. Tushare Pro（日线/分钟线，付费）
3. AKShare（日线，免费）

## 数据存储规范
```
data/raw/       原始数据（只写不删）
data/processed/ 清洗后数据
data/parquet/   分析用格式
data/sample/    测试小数据集
```

## 字段规范
```python
columns = ["datetime", "symbol", "open", "high", "low", 
           "close", "volume", "open_interest", "turnover"]
dtypes = {"datetime": "datetime64[ns]", "volume": "int64", ...}
```

## 常用命令
```bash
# 采集某品种日线数据
python scripts/data/fetch_daily.py --symbol IF --start 2020-01-01

# 转换为 Parquet
python scripts/data/to_parquet.py --input data/raw/ --output data/parquet/
```
