# RQAlpha 苏冰 JM 日线策略实验

## 项目摘要（2026-07-05）

归一量化当前是 **V1-B 研究闭环**，主链路：

```text
RQData / Local Parquet → DuckDB → vn.py 回测 → PostgreSQL → FastAPI → Vue Web
```

| 项 | 状态 |
|---|---|
| 数据主链路 | RQData / primary parquet；TqSdk 旧数据已移除 |
| 后端测试 | 183 passed |
| 当前分支 | `codex/data-001-rqdata-slimdown`（DATA-001 已完成） |
| JM 数据 | 2023-01-03 ~ 2025-12-31，1d/15m/5m/1m |
| 主回测引擎 | **vn.py**（正式报告入库） |
| 本实验引擎 | **RQAlpha Plus**（独立 PoC，不入库） |

### 苏冰策略线（主项目）

| 策略 | 版本 | 说明 |
|---|---|---|
| `su_bing_jm_daily_ema21_macd_volume` | v0.2.0-daily | 日线 EMA21 + MACD 零轴附近交叉 + 量能，冻结基线 |
| `su_bing_jm_daily_ema21_macd_volume` | v0.3 score2of4 | 研究版，trusted 指标需审查 |
| `su_bing_jm_v1b_short_hold` | v0.1.1-spec | 15m/5m 短持有 |
| `jm_v1b_daily_direction_fast_entry` | v1b.0 | V1-B 固定任务 |

本实验移植的是 **v0.2.0-daily 规则**，供你在 RQAlpha 上快速验证苏冰日线思路。

---

## 策略规则（与主项目 v0.2.0-daily 对齐）

**入场（收盘确认，次日开盘成交）**

- 多头：`close > EMA21` + MACD 近零区金叉 + `volume > 前一日 volume`
- 空头：`close < EMA21` + MACD 近零区死叉 + 量能放大

**出场**

- 多头：收盘跌破 EMA21 → 次日开盘平
- 空头：收盘站上 EMA21 → 次日开盘平

**参数**

- EMA21 / MACD(12,26,9) / 零轴带宽 25 / 固定 1 手

**PoC 限制**

- 使用 `JM88` 连续合约（RQAlpha bundle），**不是**主项目 rollover-safe 具体合约映射。
- 结果不能与 `report_id=10` 直接对比，仅供 RQAlpha 引擎冒烟与规则体感验证。

---

## 运行前准备

复用 `experiments/rqalpha_jm_buy_hold/.venv`（已装 rqalpha-plus + bundle 已更新）。

```bash
cd experiments/rqalpha_jm_buy_hold
source .venv/bin/activate
python check_bundle.py   # 应显示 bundle 检查通过
```

---

## 运行回测

```bash
cd experiments/rqalpha_su_bing_jm_daily
chmod +x run.sh
./run.sh
```

默认区间：**2023-01-03 ~ 2025-12-31**（与项目 JM 3 年窗口一致）。

自定义：

```bash
START_DATE=2024-01-01 END_DATE=2024-12-31 ./run.sh
```

或手动：

```bash
source ../rqalpha_jm_buy_hold/.venv/bin/activate

rqalpha-plus run \
  -f su_bing_jm_daily_ema21_macd_volume.py \
  -s 2023-01-03 \
  -e 2025-12-31 \
  -fq 1d \
  --account future 1000000 \
  --report output \
  -o output/result.pkl
```

加收益曲线图：

```bash
PLOT=1 ./run.sh
```

图片保存到 `output/backtest_plot.png`（同时会尝试弹出 matplotlib 窗口）。

或手动：

```bash
rqalpha-plus run ... --plot --plot-save output/backtest_plot.png
```

---

## 输出

- `output/trades.csv` — 成交明细
- `output/portfolio.csv` — 资金曲线
- `output/result.pkl` — 完整结果

---

## 相关文件

| 文件 | 说明 |
|---|---|
| `su_bing_jm_daily_ema21_macd_volume.py` | RQAlpha 策略 |
| `run.sh` | 一键回测 |
| `../rqalpha_jm_buy_hold/` | 环境、bundle 检查、买入持有 PoC |

主项目规格：`docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/`
