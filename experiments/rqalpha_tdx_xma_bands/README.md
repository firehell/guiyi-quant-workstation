# 通达信 XMA 通道策略 — RQAlpha Plus 实验

> **警告：`XMA` 为通达信偏移移动平均，使用当前 bar 之后约 N/2 根 K 线，存在未来函数 / 重绘风险。**
> 本实验 **故意保留** 该设计，结果 **不可** 作为无未来函数的可信回测结论，不得写入主项目正式报告链路。

独立 PoC，验证通达信 XMA 通道 + 回调买 / 黑马暴涨 信号在 RQAlpha Plus 上的可运行性。不入 PostgreSQL，不走 vn.py 主链路。

## 策略规则

| 项 | 规则 |
|---|---|
| 标的 | `JM88` 焦煤主力连续，日线 |
| 入场 | `XG（回调买）` 或 `XG2（黑马暴涨）` 任一触发 |
| 出场 | 收盘跌破 `ZD2`（绿色慢线） |
| 成交 | 收盘确认信号，**下一交易日开盘** 开/平 1 手 |
| 方向 | 仅做多 |

### 指标要点

- `ZK1 / ZD1 / ZD2`：双 XMA(25) 通道，`ZD2 = EMA(ZD1, 25)`
- `XG`：`ZD1 > HIGH` + VAR23 回调买条件 + `L <= ZD1`
- `XG2`：阳线 + 涨幅 ≥ 2% + `MA5 > MA60` + `H < ZK1` + `L < ZD1` + DDX 衍生 `DY2 < 0.02`
- `XG2 / CURRBARSCOUNT`：PoC 将当前 bar 视为图表末 bar（恒为 1），与通达信滚动图表略有差异；见 `xma_core.py` 注释

## 环境

复用 [`experiments/rqalpha_jm_buy_hold/.venv`](../rqalpha_jm_buy_hold/.venv)。若未初始化：

```bash
cd experiments/rqalpha_jm_buy_hold
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip rqsdk h5py numpy
rqsdk license
rqsdk install rqalpha_plus
rqsdk download-data --sample   # 或 update-data --base
```

## 运行

```bash
cd experiments/rqalpha_tdx_xma_bands
chmod +x run.sh

# 默认 2023-01-03 ~ 2025-12-31，带 --plot
PLOT=1 ./run.sh

# 自定义区间
START_DATE=2023-01-03 END_DATE=2024-12-31 CAPITAL=1000000 PLOT=1 ./run.sh

# 无 GUI 时仍可保存曲线图
PLOT=1 ./run.sh
# 输出: output/backtest_plot.png
```

`--plot` 展示 **账户收益曲线**，不绘制通达信式 K 线色带。

## 文件说明

| 文件 | 说明 |
|---|---|
| `xma_core.py` | XMA / 通道 / VAR23 / DDX / 信号预计算 |
| `load_bundle_bars.py` | 从 `~/.rqalpha-plus/bundle/futures.h5` 读 JM88 |
| `tdx_xma_bands_strategy.py` | RQAlpha 策略入口 |
| `run.sh` | 回测脚本，默认 `PLOT=1` |

## 本地 smoke

```bash
# 指标单元
../rqalpha_jm_buy_hold/.venv/bin/python xma_core.py

# 回测
PLOT=1 ./run.sh
# 期望: output/trades.csv, output/backtest_plot.png, output/result.pkl
```

## 与主项目关系

| 项 | 本实验 | 归一量化 V1 主链路 |
|---|---|---|
| 引擎 | RQAlpha Plus | vn.py |
| 数据 | RQAlpha bundle | Parquet + DuckDB |
| 结论 | 指标复刻 PoC | 正式研究与 Web 报告 |

## 风险

1. XMA 未来函数 + 全序列预计算 → 历史信号随回测终点变化
2. JM88 连续合约 ≠ 主项目 rollover-safe 映射
3. XG2 的 CURRBARSCOUNT 语义与通达信实盘图表可能不一致
