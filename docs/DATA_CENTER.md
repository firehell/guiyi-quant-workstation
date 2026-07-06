# DATA_CENTER.md — 归一量化数据中心设计

> 版本：V1 重构版  
> 当前路线：米筐 RQData 为 V1 主数据源  
> 数据仓：PostgreSQL + Parquet + DuckDB  
> 阶段边界：V1 不做实盘，不做 tick 高频回测。

---

## 1. 数据中心定位

数据中心是归一量化的底层，不只是 K线存储。

它必须支撑：

```text
数据下载
→ raw 留底
→ 字段标准化
→ 数据质量检查
→ 本地数据仓
→ K线工作台
→ vn.py 回测
→ 信号扫描
→ 单笔复盘
```

核心原则：

1. 外部数据源不能直接给回测和 Web 使用。
2. 回测默认读取本地标准化数据。
3. 前端不能直接调用外部数据 SDK。
4. 大体量行情不写入 PostgreSQL。
5. PostgreSQL 只存业务事实、索引、报告和结构化元数据。
6. Parquet 存历史 K线和 raw 留底。
7. DuckDB 做本地研究查询和回测前读取。
8. Redis / RQ 只做任务队列和临时状态。
9. 所有凭据只从环境变量或本地配置读取。
10. 没有质量报告的数据不能进入默认正式回测。

---

## 2. V1 数据源策略

### 2.1 主数据源

V1 主数据源：

```text
RQData / 米筐
```

用途：

- 历史 1分钟及以上 K线。
- 合约基础信息。
- 主力映射。
- 复权因子。
- 交易参数。
- 合约乘数。
- 手续费。
- 保证金。
- 日线基准。
- 仓单等研究数据。

### 2.2 数据源角色表

| 数据源 | data_role | V1 用途 |
|---|---|---|
| RQData 新下载数据 | primary | V1 正式回测和信号扫描 |
| 标准 Parquet | primary | 本地正式数据湖 |
| 早期米筐旧数据 | primary / validation | 质量通过后可并入正式数据 |
| 天勤旧数据 | removed from active | 已删除当前本地旧数据；后续如需只作为 future backup 单独重引入 |
| 交易练习者数据 | removed from active | 已从当前 active 数据体系移除，不再作为 V1 数据入口 |
| TuShare | candidate | later auxiliary，V1 不作为主链路 |
| TqSdk / 天勤专业版 | future backup candidate | 当前不是主链路、validation source、realtime source 或 trading provider |

正式回测默认只读取：

```text
data_role = primary
quality_status != failed
```

### 2.3 当前 V1-B 数据口径

当前阶段：

```text
V1-B：焦煤 JM 3 年真实数据短持有策略闭环
```

V1-B 数据验收只围绕焦煤 JM 最近 3 年真实 RQData / local standard parquet 数据。旧的 V1-A “焦煤 1 年验收样板”只作为历史参考，不再作为当前目标。

V1-B 必须具备：

```text
JM 1d standard bars
JM 15m standard bars
JM 5m standard bars
```

数据规则：

1. 正式回测默认只读取 `data_role=primary`。
2. `quality_status=failed` 的数据不得进入 V1-B 正式回测。
3. 天勤旧数据和 TqSdk 临时下载数据已从当前 active 数据体系移除，不得作为 V1-B 数据入口。
4. 交易练习者数据已从当前 active 数据体系移除，不再用于页面测试、正式回测或信号扫描。
5. 多周期 K线必须能追溯到 RQData / local standard parquet 来源。

---

## 3. 数据总流

```text
RQData API
    |
    v
raw parquet
    |
    v
Normalize Layer
    |
    v
standard parquet
    |
    v
market_data_files + data_quality_reports
    |
    v
DuckDB / MarketDataReader
    |
    v
vn.py Backtesting Adapter / K线工作台 / 信号扫描
```

---

## 4. 存储分层

### 4.1 PostgreSQL

PostgreSQL 是业务事实库。

存储：

- 数据源登记。
- 交易所。
- 品种。
- 合约。
- 交易日历。
- 交易时段。
- 主力映射。
- 复权因子。
- 交易参数。
- 手续费保证金规则。
- 数据下载任务。
- 数据文件索引。
- 数据质量报告。
- 策略。
- 策略版本。
- 回测任务。
- 回测报告。
- 交易明细。
- 信号。
- 复盘记录。
- 风控配置。

不存：

- 全量分钟 K线。
- tick 明细。
- 大体量行情。
- 外部账号密码。

---

### 4.2 Parquet

Parquet 是大体量数据湖。

目录建议：

```text
data/
  raw/
    rqdata/
  parquet/
    standard/
      bars/
        source=rqdata/
          interval=1m/
          exchange=SHFE/
          symbol=rb/
          year=2024/
      daily/
      metadata/
```

### 4.3 DuckDB

DuckDB 只做：

- 本地研究查询。
- 批量统计。
- Parquet 查询。
- 回测前数据读取。
- 数据质量抽检。

DuckDB 不作为权威业务库。

---

## 5. 标准 K线 schema

standard bars 至少包含：

| 字段 | 说明 |
|---|---|
| source | rqdata / local_parquet |
| data_role | primary |
| symbol | 品种代码，如 rb |
| contract | 合约代码，如 RB2405 或 rb.MAIN |
| exchange | 交易所，如 SHFE |
| vt_symbol | vn.py 标准代码 |
| datetime | K线开始时间 |
| trading_day | 交易日 |
| interval | 周期 |
| open | 开盘价 |
| high | 最高价 |
| low | 最低价 |
| close | 收盘价 |
| volume | 成交量 |
| turnover | 成交额 |
| open_interest | 持仓量 |
| is_main_contract | 是否主力 |
| continuous_symbol | 连续合约标识 |
| adjusted | 是否复权 |
| data_version | 数据版本 |
| created_at | 创建时间 |
| updated_at | 更新时间 |

说明：旧 `tq_old`、`trader_trainer`、TqSdk 临时下载和交易练习者数据不得作为当前 active 数据入口。历史枚举如仍存在于代码中，只作为兼容字段或旧数据识别，不代表允许新建正式入口。

---

## 6. 周期合成

V1 必须支持：

```text
1m
5m
15m
30m
60m
120m
240m
1d
```

规则：

1. 以 1m 数据为基础。
2. 夜盘不能按自然日简单聚合。
3. 日线必须处理夜盘归属。
4. 2H / 4H 必须按交易时段合成。
5. 未完成 K线不能作为确认信号。
6. 周期合成后必须写入 `market_data_files`。
7. 周期合成后必须生成 `data_quality_reports`。

---

## 7. PostgreSQL 核心表

### 7.1 基础表

```text
data_sources
exchanges
instruments
contracts
trading_calendars
trading_sessions
```

### 7.2 文件和任务表

```text
data_download_tasks
market_data_files
data_quality_reports
```

`market_data_files` 建议字段：

```text
id
source
data_role
data_type
symbol
contract
exchange
interval
start_time
end_time
row_count
file_path
checksum
data_version
quality_status
created_at
updated_at
```

`data_role` 枚举：

```text
primary
validation
historical inactive roles, if present in old reports, are display-only and not active data inputs
candidate
```

`quality_status` 枚举：

```text
pending
passed
warning
failed
```

### 7.3 RQData 研究表

```text
main_contract_map
futures_ex_factors
futures_trading_parameters
fee_margin_rules
futures_warehouse_stocks
futures_contract_universe
```

可保留但 V1 不强依赖：

```text
futures_continuous_contract_map
futures_roll_yields
futures_basis
```

---

## 8. RQData 下载链路

推荐模块：

```text
services/quant-api/app/data_sources/rqdata_provider.py
services/quant-api/app/services/rqdata_ingest/
```

下载流程：

```text
读取任务配置
→ 初始化 RQData client
→ 下载原始数据
→ raw parquet 原子写入
→ 字段标准化
→ standard parquet 写入
→ upsert PostgreSQL 结构化表
→ 记录 market_data_files
→ 生成 data_quality_reports
→ 更新任务状态
```

要求：

1. 支持断点续传。
2. 支持按品种分批。
3. 支持按年份分批。
4. 支持失败重试。
5. 支持流量限制下的低频下载。
6. 不重复请求已缓存数据。
7. 不把账号密码写入代码。

### 8.1 RQData 小样本验收

第 9 步新增小样本验收链路，默认只下载一个具体合约的小范围数据：

```text
RB2405
2024-01-02 至 2024-01-31
1m
```

用途是验证链路，不是形成策略结论：

```text
RQData 环境变量凭据
→ raw parquet
→ standard parquet
→ market_data_files
→ data_quality_reports
→ DuckDB
→ MarketDataReader / RQDataProvider
→ 可选 vn.py smoke 回测
```

运行命令：

```bash
uv run --project services/quant-api python experiments/rqdata_sample_acceptance/run_sample.py --check-credentials
uv run --project services/quant-api python experiments/rqdata_sample_acceptance/run_sample.py --contract RB2405 --exchange SHFE --symbol rb --frequency 1m --start 2024-01-02 --end 2024-01-31 --use-app-db
```

输出目录：

```text
experiments/rqdata_sample_acceptance/output/
```

该目录被 `.gitignore` 覆盖，真实 RQData parquet、SQLite 和 JSON 验收输出不得提交到 Git。

质量报告字段至少包含：

| 字段 | 说明 |
|---|---|
| status | passed / warning / failed |
| missing_bars | 按周期推断的缺失 bar 数 |
| duplicated_bars | 重复 datetime 数 |
| abnormal_price_count | OHLC 不合法数量 |
| abnormal_volume_count | 负成交量数量 |
| abnormal_open_interest_count | 负持仓量数量 |
| gap_samples | 时间断点样例 |
| duplicate_samples | 重复时间样例 |
| check_rule_version | 当前 canonical bar 检查规则版本 |

边界：

- 凭据只从环境变量读取，不写入命令行、代码或文档。
- 不下载全市场，不做大范围历史下载。
- 不调用 CTP / TqSdk 交易接口。
- 不做自动下单。
- 若质量状态为 `failed`，不得进入默认回测读取。

---

## 9. 旧数据处理

### 9.1 早期米筐数据

处理流程：

```text
读取旧米筐数据
→ 字段映射
→ 时间规范化
→ 质量检查
→ 写入 standard parquet
→ 标记 source=rqdata
→ 标记 data_role=primary
```

如果质量状态为 `failed`，不得进入 active 回测、信号或行情查询入口；严格研究优先只使用 `quality_status=passed`。

### 9.2 天勤 / TqSdk 旧数据

处理方式：

```text
removed from current active data system
```

用途：

- 当前不作为 validation source。
- 当前不作为 realtime source。
- 当前不作为 trading provider。
- 如 RQData 后续出现问题，必须以单独任务重新设计 future backup 引入方案。

禁止默认用于正式回测。

### 9.3 交易练习者数据

处理方式：

```text
removed from current active data system
```

用途：

- 当前不再作为 V1 数据入口。

禁止用于：

- 页面 K线测试。
- 正式回测。
- 参数优化。
- 策略绩效判断。
- 信号扫描主数据。

---

## 10. MarketDataReader

所有模块读取行情必须走统一读取层：

```text
MarketDataReader
```

职责：

1. 查询 `market_data_files`。
2. 过滤 `quality_status != failed`。
3. 默认只取 `data_role=primary`。
4. 使用 DuckDB 读取 Parquet。
5. 返回统一 bar schema。
6. 支持 Web K线、回测、信号扫描共用。

禁止：

- 策略直接读 raw parquet。
- 回测直接调用 RQData API。
- 前端直接读 Parquet。
- Web 直接访问外部数据源。

---

## 11. 与 vn.py 的数据衔接

V1 用 `LocalParquetProvider` 给 vn.py adapter 提供数据。

推荐流程：

```text
BacktestTask
→ MarketDataReader
→ pandas DataFrame
→ vn.py BarData 序列 / 数据库缓存
→ BacktestingEngine
```

注意：

1. vn.py 格式代码映射放在 `symbol_mapper.py`。
2. 数据源差异不能散落在策略代码里。
3. 策略只接收 vn.py 标准 BarData。
4. 回测结果必须转回归一量化标准格式。

---

## 12. 数据质量检查

基础检查：

- 空数据。
- 缺字段。
- 重复 K线。
- 时间断点。
- OHLC 关系异常。
- 成交量为负。
- 持仓量为负。
- 时间区间不连续。
- 日线夜盘归属异常。
- 主力映射缺失。
- 合约参数缺失。

质量结果写入：

```text
data_quality_reports
```

质量等级：

```text
passed
warning
failed
```

正式回测禁止使用 failed 数据。

---

## 13. 常用命令

### 13.1 迁移和测试

```bash
uv run --project services/quant-api python -m alembic current
uv run --project services/quant-api python -m alembic upgrade head
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
```

### 13.2 RQData 审计

```bash
uv run --project services/quant-api python scripts/rqdata_audit.py
uv run --project services/quant-api python scripts/rqdata_field_audit.py run
uv run --project services/quant-api python scripts/rqdata_coverage_audit.py run
```

### 13.3 数据质量检查

```bash
uv run --project services/quant-api python scripts/data_quality_check.py run
```

---

## 14. V1 验收标准

```text
[ ] RQData 可以下载目标品种数据
[ ] raw parquet 可落地
[ ] standard parquet 可落地
[ ] market_data_files 有文件索引
[ ] data_quality_reports 有质量报告
[ ] DuckDB 可查询标准 K线
[ ] MarketDataReader 可返回统一 bar schema
[ ] Web K线工作台可展示数据
[ ] vn.py adapter 可读取标准数据进行回测
[ ] 旧数据有 data_role 隔离
```

---

## 15. 开发边界

必须遵守：

1. 新数据源先落 raw，再标准化。
2. 大体量行情优先 Parquet。
3. 业务事实进 PostgreSQL。
4. 数据查询走 MarketDataReader。
5. 回测读取本地标准数据。
6. 前端不直接接数据源。
7. 凭据不入库、不入文档、不入 Git。
8. 旧数据不能污染正式回测。
