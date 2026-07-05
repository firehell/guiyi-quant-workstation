# RQAlpha Plus：焦煤 JM 一年日线买入持有

独立实验目录，用于验证**米筐 RQSDK / RQAlpha Plus 期货回测权限**，不接入归一量化主回测链路（主链路仍是 vn.py）。

策略逻辑与[官方 buy_and_hold 示例](https://www.ricequant.com/doc/rqsdk/manual-rqsdk#rqsdk-prep-backtest)一致：首日买入，持有到结束。标的改为焦煤主力连续 `JM88`（日线）。

## 1. 环境准备（一次性）

```bash
cd experiments/rqalpha_jm_buy_hold

# 建议 Python 3.9–3.12（3.13 上 TA-Lib 可能装不上，见下方说明）
python3 -m venv .venv
source .venv/bin/activate

pip install -U pip
pip install rqsdk
```

### 配置 license

任选其一：

```bash
# 方式 A：交互式（会写入 shell profile）
rqsdk license

# 方式 B：直接传入 key（与项目 .env 中 RQDATA_LICENSE_KEY 相同）
rqsdk license -l "<你的 license key>"
```

### 安装回测引擎

```bash
rqsdk install rqalpha_plus
```

若报 `ta-lib` 安装失败（macOS 常见）：

```bash
brew install ta-lib
pip install TA-Lib
rqsdk install rqalpha_plus
```

### 下载回测数据包

日线期货回测需要本地 bundle。首次建议用**不耗流量**的样例包试跑：

```bash
rqsdk download-data --sample
```

确认流程 OK 后，再按需增量更新（会消耗 RQData 流量）：

```bash
# 更新全部日线 + 基础数据（文档示例，流量较大）
rqsdk update-data --base
```

数据默认落在 `~/.rqalpha-plus/bundle`。

## 2. 检查是否有期货回测权限

```bash
source .venv/bin/activate
python check_license.py
```

期望输出包含：

- `rqsdk__mod_backtest_future: 有`
- `商品、股指、股债期货` 条目 `enable=True`

你当前 license（2026-07-03 实测）已包含该权限，剩余约 **361 天**，类型 **FULL**。

## 3. 运行回测

### 方式 A：命令行（推荐）

```bash
source .venv/bin/activate

# 若已用 rqsdk license 配置过，新开终端后需重新 source 或导出：
# export RQSDK_LICENSE="tcp://license:<key>@rqdatad-pro.ricequant.com:16011"

rqalpha-plus run \
  -f buy_and_hold_jm.py \
  -s 2018-01-01 \
  -e 2018-12-31 \
  -fq 1d \
  --account future 1000000 \
  --report output \
  -o output/result.pkl
```

参数说明：

| 参数 | 含义 |
|---|---|
| `-s / -e` | 回测区间。样例 bundle 约到 2020 年，**默认用 2018**；要跑 2024 需先 `rqsdk update-data --base` |
| `-fq 1d` | 日线频率 |
| `--account future 1000000` | 期货账户，初始资金 100 万 |
| `--report output` | 导出 csv 报告到 `output/` 目录（**必须带路径**） |
| `-o output/result.pkl` | 可选，导出 pickle 结果文件 |
| `--plot` | 可选，弹出收益曲线图（需 GUI） |

### 方式 B：脚本

```bash
chmod +x run.sh
./run.sh

# 自定义区间
START_DATE=2023-01-03 END_DATE=2023-12-29 CAPITAL=500000 ./run.sh
```

## 4. 策略文件说明

`buy_and_hold_jm.py` 核心逻辑：

- `init`：订阅 `JM88`（焦煤主力连续）
- `handle_bar`：第一个 bar 调用 `buy_open(..., 1)` 买入 1 手，之后不再交易

如需改用**真实合约**（非连续），可把 `context.s1` 改成具体合约，例如 `JM2405`，并确保 bundle 中有对应日线数据。

## 5. 与归一量化主项目的关系

| 项 | 本实验 | 归一量化 V1 主链路 |
|---|---|---|
| 回测引擎 | RQAlpha Plus（米筐官方） | vn.py CTA BacktestingEngine |
| 数据 | `~/.rqalpha-plus/bundle` | Local Standard Parquet + DuckDB |
| 用途 | 验证 RQSDK 回测权限 / PoC | 正式研究与 Web 报告 |

本实验**不会**写入 PostgreSQL，**不会**触发项目 Web 回测任务。

## 6. 常见问题

```bash
source .venv/bin/activate
python check_license.py   # 检查回测权限
python check_bundle.py    # 检查本地数据包是否可用
```

**`QuotaExceeded: Quota exceeded`（更新到 90%+ 失败）**  
→ RQData **流量配额用尽**，不是 license 过期、也不是权限被关。

你的 license 日流量上限约 **1 GB**；`rqsdk update-data --base` 会拉**全市场**日线，体积接近 1G，跑到 92% 时超额就会中断。

当前实测（更新失败后）：

```text
已用流量: ~1046 MB / 上限 1024 MB（超额）
license 剩余天数: 仍有效（约 360 天）
JM88 bundle: 已更新成功（含 open_interest，覆盖到 2026-07-03）
```

说明：**期货日线大概率已下完**，失败的是后面股票/指数等剩余品种；但配额用完后，回测若仍连 rqdatac 也会报同样错误。

处理建议：

1. **等流量配额重置**（通常按日重置，次日再试）
2. 第二天用增量补完，不要重复全量：
   ```bash
   rqsdk update-data --smart
   ```
3. 配额恢复后先自检再回测：
   ```bash
   python check_bundle.py
   ./run.sh
   ```
4. 若经常要做 `--base` 全量更新，需联系米筐**升级流量套餐**（报错里提示 0755-22676337）

以后只做 JM 期货 PoC，**避免频繁跑 `--base`**；首次用 `--sample` 验证流程，确认要跑近年数据再择机增量更新。

**`ValueError: Field open_interest does not appear in this type.`**  
→ 样例 bundle（`download-data --sample`）期货字段过旧，**缺少 `open_interest`**，与当前 `rqalpha-plus` 不兼容。不是策略代码问题，也不是 license 问题。

处理：

```bash
rqsdk update-data --base
python check_bundle.py    # 应显示「bundle 检查通过」
./run.sh
```

**`未在 xxx 和 xxx 区间内查询到数据，请检查并升级您的 data bundle`**  
→ **不是 license 权限问题**，是本地回测数据包（`~/.rqalpha-plus/bundle`）里没有这个日期区间的行情。

常见原因与处理：

| 情况 | 处理 |
|---|---|
| 只跑了 `rqsdk download-data --sample` | 样例包日线大约到 **2020 年初**，请把回测区间改到 **2018**（官方文档示例年份），或执行下方更新 |
| 想回测 **2024** 等近年数据 | 需要联网更新 bundle（会消耗 RQData 流量）：`rqsdk update-data --base` |
| bundle 目录不存在 | 先 `rqsdk download-data --sample` |

快速验证（用样例包能覆盖的区间）：

```bash
rqalpha-plus run -f buy_and_hold_jm.py -s 2018-01-01 -e 2018-12-31 -fq 1d --account future 1000000 --report output
```

要跑 2024 全年，先更新数据再改日期：

```bash
rqsdk update-data --base          # 耗时较长，消耗流量配额
# 完成后再跑 2024-01-01 ~ 2024-12-31
```

**`rqalpha-plus: command not found`**  
→ 先 `rqsdk install rqalpha_plus`，并 `source .venv/bin/activate`。

**`bundle 中找不到合约`**  
→ 先 `rqsdk download-data --sample` 或 `rqsdk update-data --base`。

**`AuthenticationFailed` / license 无效**  
→ 检查 `rqsdk license info` 或运行 `python check_license.py`。

**Python 3.13 + TA-Lib 装不上**  
→ 建议单独建 Python 3.11 的 venv 跑本实验，不影响 `services/quant-api`。
