# DATA_CENTER.md - 归一量化数据中心当前实现说明

> 版本：v1.2
> 状态：当前实现 + 设计边界 + 已知缺口
> 更新日期：2026-06-25
> 权威性：本文是归一量化数据部分的当前工程说明；早期草稿 `docs/guiyi_quant_database_design.md` 仅作历史参考。
> 阶段边界：V0 命令行原型 + V1 Web 研究闭环；不做无人值守实盘。

## 1. 数据中心定位

数据中心不是单纯的 K 线存储模块，而是本地期货研究闭环的底座。当前目标是让数据可追溯、可审计、可回放，支撑后续策略配置、回测、信号扫描和复盘。

核心链路：

```text
外部数据源
-> Source Adapter / Ingest Script
-> raw Parquet 留底
-> 字段标准化与质量检查
-> PostgreSQL 结构化事实 / Parquet 大体量行情
-> market_data_files 文件索引
-> DuckDB / MarketDataReader 统一读取
-> 回测、K线工作台、信号扫描、复盘
```

第一版原则：

- PostgreSQL 存元数据、结构化研究事实、任务、文件索引、质量报告。
- Parquet 存 raw 留底、历史 K 线、tick、日线明细等大体量数据。
- DuckDB 只做本地研究查询和回测前批量读取，不作为权威业务库。
- Redis / RQ 用于异步任务和临时状态，不存长期事实。
- 不把分钟线、tick 全量写入 PostgreSQL。
- 不让回测和前端直接调用外部 SDK。
- 不把主力连续合约当作真实可交易合约直接成交回测。
- 不把任何数据源凭据写入代码库或文档。

## 2. 当前数据源分层

| 数据源 | 当前角色 | 数据落地方式 | 状态 |
|---|---|---|---|
| `trader_future_data` | 本地 canonical 主连行情样本 | CSV -> 标准 bars Parquet -> `market_data_files` / `data_quality_reports` | 已实现 |
| RQData | 米筐结构化研究底稿和校验样本 | RQData API -> raw Parquet -> 结构化表 / 文件索引 / 质量报告 | 已实现主体 |
| TqSdk / 天勤专业版 | 后续长期行情与交易闭环目标源 | 计划接入为核心行情下载源 | 未宣称完成 |
| Tushare / AKShare | 元数据补充或交叉校验备选 | 仅作为补充方向 | 非主链路 |

当前口径：天勤后期负责长期行情、tick、任意周期 K 线和交易闭环；RQData 试用期主要沉淀天勤不方便结构化提供的研究底稿，例如主力映射、复权因子、交易参数、仓单、合约池和日线校验样本。

## 3. 存储分层

### 3.1 PostgreSQL

PostgreSQL 是业务事实库。当前模型集中在 `services/quant-api/app/models/data_center.py`，迁移通过 Alembic 管理。

主要职责：

- 数据源、交易所、品种、合约、交易日历、交易时段。
- 下载任务、文件索引、质量报告。
- RQData 结构化研究表。
- 手续费、保证金、合约乘数等回测成本模型基础数据。
- 策略、回测、信号、复盘等业务表由各自模块维护。

### 3.2 Parquet

Parquet 是大体量数据和 raw 留底层。

当前主要目录：

```text
data/raw/rqdata/
data/parquet/canonical/bars/
data/parquet/market/
```

RQData raw 示例：

```text
data/raw/rqdata/futures_ex_factor/product=rb/rb_2005_2026.parquet
data/raw/rqdata/trading_parameters/contract=RB2405/RB2405_2005_2026.parquet
data/raw/rqdata/market_samples/product=rb/frequency=1m/rb_1m_20100104_20260624.parquet
```

统一行情层 canonical bars 示例：

```text
data/parquet/canonical/bars/provider=trader_future_data/period=5m/exchange=SHFE/symbol=rb/contract=rb.MAIN/year=2024/part-000.parquet
```

### 3.3 DuckDB

DuckDB 负责读取 Parquet。`MarketDataReader` 先查 PostgreSQL 的 `market_data_files`，确认文件范围和质量状态，再用 DuckDB `read_parquet(..., union_by_name=true)` 读取数据。

当前读取入口：

- `services/quant-api/app/services/market_data_reader.py`
- `services/quant-api/app/services/market_workbench.py`
- `services/quant-api/app/api/data_center.py`
- `services/quant-api/app/api/market.py`

## 4. PostgreSQL 表设计

### 4.1 基础元数据表

| 表 | 用途 | 当前要点 |
|---|---|---|
| `data_sources` | 数据源登记 | 只保存非敏感元信息和本地配置说明 |
| `exchanges` | 交易所 | `SHFE`、`DCE`、`CZCE`、`INE`、`CFFEX`、`GFEX` 等 |
| `instruments` | 品种 | 品种代码统一小写为主，如 `rb`、`eg`；郑商所原始大小写保留在 raw |
| `contracts` | 合约 | 真实合约和研究用主连合约，包含乘数、交割日期、交易代码、交易时段等字段 |
| `trading_calendars` | 交易日历 | 当前 RQData 生成 `CNFE` 通用交易日历 |
| `trading_sessions` | 交易时段 | 按品种保存交易时段、是否跨午夜 |

`contracts` 是连接研究数据和回测成本模型的核心表。RQData catalog 同步会补充：

- `contract_multiplier`
- `trading_code`
- `maturity_date`
- `start_delivery_date`
- `end_delivery_date`
- `product`
- `trading_hours`
- `listed_date`
- `expired_date`
- `provider`

### 4.2 任务、文件和质量表

| 表 | 用途 | 关键字段 |
|---|---|---|
| `data_download_tasks` | 每次下载或导入任务 | `provider`、`data_type`、`instrument_symbol`、`contract_code`、`period`、`status`、`result` |
| `market_data_files` | Parquet 文件索引 | `provider`、`data_type`、`instrument_symbol`、`contract_code`、`period`、`start_time`、`end_time`、`checksum`、`data_version`、`quality_status` |
| `data_quality_reports` | 数据质量报告 | 缺失、重复、异常价格、异常成交量、检查细节 |

`market_data_files` 的唯一约束包含：

```text
provider + data_type + instrument_symbol + contract_code + period + start_time + end_time + data_version
```

这样不同品种在同一数据类型、同一周期、同一时间范围下不会互相覆盖文件索引。

### 4.3 RQData 结构化研究表

| 表 | 数据内容 | 入库来源 | 当前状态 |
|---|---|---|---|
| `main_contract_map` | 主力 / 次主力每日映射 | `futures.get_dominant(..., rank=1/2)` | 已落库 |
| `futures_ex_factors` | 主连复权因子 | `futures.get_ex_factor()` | 已落库 |
| `futures_trading_parameters` | 保证金、手续费、下单限制、乘数等历史参数 | `futures.get_trading_parameters()` | 已落库 |
| `futures_warehouse_stocks` | 仓单 | `futures.get_warehouse_stocks()` | 已落库 |
| `futures_contract_universe` | 每日可交易合约池 | `futures.get_contracts()` | 已落库 |
| `futures_continuous_contract_map` | 近月 / 次月等连续映射 | `futures.get_continuous_contracts()` | 当前环境接口不可用，表为空 |
| `futures_roll_yields` | 展期收益率 | `futures.get_roll_yield()` | 当前环境接口不可用，表为空 |
| `futures_basis` | 升贴水 | `futures.get_basis()` | 当前盲跑结果为空，默认不继续全合约跑 |

所有 RQData 结构化表都保留：

- `provider`
- `data_version`
- `raw_payload`
- 常用查询索引
- 以业务键 + provider + data_version 为核心的唯一约束

`futures_trading_parameters` 会同步一份回测常用字段到 `fee_margin_rules`，供后续回测成本模型读取。

### 4.4 手续费和保证金表

`fee_margin_rules` 是回测成本模型面向业务使用的统一表。当前主要由 RQData 交易参数同步生成。

字段包括：

- `provider`
- `exchange_code`
- `instrument_symbol`
- `contract_code`
- `price_tick`
- `volume_multiple`
- `margin_rate`
- `open_fee`
- `close_fee`
- `close_today_fee`
- `fee_type`
- `effective_date`
- `source`

设计意图：回测引擎不直接读取供应商原始字段，而读取统一成本规则表。供应商差异留在入库映射和 `raw_payload` 中。

## 5. RQData 结构化下载链路

RQData ingest 共享实现位于：

```text
services/quant-api/app/services/rqdata_ingest/
```

关键文件：

| 文件 | 职责 |
|---|---|
| `client.py` | 初始化 RQData、本地环境读取、API wrapper、字段形态兼容 |
| `ingestors.py` | 各类数据下载、raw 记录、结构化 upsert |
| `manifest.py` | CSV manifest，支持 `--resume`、`--retry-failed`、`--limit` |
| `parquet.py` | 原子写 Parquet、checksum |
| `db.py` | 任务、文件、质量报告、upsert、公用类型转换 |
| `quality.py` | 空数据、缺字段、重复键检查 |
| `recovery.py` | 从已有 raw 回灌结构化表 |

### 5.1 通用流程

```text
脚本解析参数
-> 选择 products / contracts / chunks
-> manifest 判断是否执行
-> RqDataClient 调 RQData API
-> reset_index(drop=False) 保留日期 / 时间 index
-> ingestor 标准化字段
-> raw Parquet 原子写入
-> PostgreSQL 结构化 upsert
-> data_download_tasks 记录任务
-> market_data_files 记录文件索引
-> data_quality_reports 记录质量结果
-> manifest 标记 success / failed
```

### 5.2 脚本入口

| 脚本 | 数据内容 | 默认分块 |
|---|---|---|
| `scripts/rqdata_catalog_sync.py` | 合约基础信息、品种、日历、交易时段 | 一次性 |
| `scripts/rqdata_main_mapping_sync.py` | 主力 / 次主力映射 | 品种 |
| `scripts/rqdata_ex_factor_sync.py` | 复权因子 | 品种 |
| `scripts/rqdata_trading_params_sync.py` | 交易参数历史 | 合约 |
| `scripts/rqdata_daily_baseline_sync.py` | 真实合约原始日线 | 合约，仅 Parquet / 文件索引 |
| `scripts/rqdata_research_enhancers_sync.py` | 仓单、展期收益率、可选 basis | 品种；basis 必须显式开启 |
| `scripts/rqdata_market_samples_sync.py` | 主连行情校验样本 | 品种 x 周期 |
| `scripts/rqdata_contract_universe_sync.py` | 每日可交易合约池 | 品种 x 年 |
| `scripts/rqdata_continuous_contracts_sync.py` | 近月 / 次月连续映射 | 品种；当前环境接口不可用 |
| `scripts/rqdata_dominant_daily_baseline_sync.py` | 主连日线校验样本 | 品种 |

审计脚本：

| 脚本 | 输出 |
|---|---|
| `scripts/rqdata_audit.py` | raw、manifest、DB 表、文件索引、质量报告一致性摘要 |
| `scripts/rqdata_coverage_audit.py` | 覆盖矩阵、缺口清单、产品覆盖摘要 |
| `scripts/rqdata_field_audit.py` | raw Parquet 字段完整性、坏样本路径 |
| `scripts/rqdata_recover_raw.py` | 从可恢复 raw 回灌结构化表 |

### 5.3 字段标准化规则

当前 ingestor 采用保守兼容：

- RQData 调用时品种转大写，入库统一小写。
- 合约代码入库统一大写。
- 日期字段兼容 `date`、`trade_date`、`trading_date`、`datetime`、`index`、`ex_date`。
- RQData 返回 DataFrame / Series 时统一 `reset_index(drop=False)`，避免丢失日期或时间 index。
- `get_contracts()` 返回 list 时规范为 `contract` 列。
- 复权因子兼容 `ex_factor`、`ex_cum_factor`、`prev_close_spread`、`prev_close_ratio`。
- 交易参数兼容 `close_commission_today`、`min_margin_ratio`、`non_member_limit`、`client_limit`。
- 日线兼容 `total_turnover`。
- 所有结构化表保留 `raw_payload`，便于追溯供应商原始字段。

### 5.4 质量检查

RQData 结构化质量检查当前是轻量版：

- 空 DataFrame 记 `warning`。
- 缺少 required field 记 `failed`。
- 重复键记 `warning`。
- 结果写入 `data_quality_reports.details`，包含 `check_rule_version`。

canonical bars 导入器的质量检查更偏行情：

- 时间断点。
- 重复 K 线。
- 高低开收价格关系异常。
- 成交量为负。
- 持仓量为负。

质量状态只作为入库审计，不会自动删除 raw 文件。旧试跑 raw 会保留为证据，字段审计用 `partial_bad_raw` 标识部分旧文件仍不干净。

## 6. 统一行情层

当前真正供 K 线工作台和后续回测读取的统一行情层是 canonical bars。

### 6.1 canonical bars 字段

标准字段至少包括：

```text
symbol
contract
exchange
datetime
trading_day
open
high
low
close
volume
open_interest
period
provider
turnover
data_version
created_at
```

`trader_future_data` CSV 导入时会把中文品种名映射到系统品种代码，例如：

- 螺纹 -> `rb`
- 热卷 -> `hc`
- 铁矿石 -> `i`
- 乙二醇 -> `eg`
- 原油 -> `sc`

主连研究合约用 `symbol.MAIN` 形式，例如 `rb.MAIN`。这类合约只用于研究展示和指标验证，不代表真实可成交合约。

### 6.2 文件索引和读取

`TraderFutureCsvImporter` 写入 canonical bars 后，会同步写：

- `data_download_tasks`
- `market_data_files`
- `data_quality_reports`

`MarketDataReader` 读取时：

1. 按 `symbol`、`contract`、`period`、时间范围查询 `market_data_files`。
2. 过滤 `quality_status != failed`。
3. 限定路径包含 `/canonical/bars/`。
4. 用 DuckDB 读取 Parquet。
5. 返回统一 bar dict 给 API / 前端。

这使得回测、K 线工作台、信号扫描后续可以只依赖统一读取层，而不关心数据来自本地 CSV、RQData 还是未来 TqSdk。

## 7. 当前数据完整度

以下数字来自 2026-06-25 本机审计结果。

| 表 | 行数 | 说明 |
|---|---:|---|
| `data_sources` | 4 | 本地数据源登记 |
| `exchanges` | 8 | 国内期货交易所和补充代码 |
| `instruments` | 134 | 品种层级 |
| `contracts` | 11184 | 真实合约和研究合约 |
| `trading_calendars` | 7845 | 交易日历 |
| `trading_sessions` | 98 | 交易时段 |
| `main_contract_map` | 575156 | 主力 / 次主力映射 |
| `futures_ex_factors` | 2099 | 复权因子 |
| `futures_trading_parameters` | 911831 | 交易参数历史 |
| `fee_margin_rules` | 911831 | 回测成本规则同步表 |
| `futures_warehouse_stocks` | 84188 | 仓单 |
| `futures_contract_universe` | 183876 | 每日可交易合约池 |
| `market_data_files` | 23450 | Parquet 文件索引 |
| `data_quality_reports` | 25044 | 质量报告 |
| `futures_continuous_contract_map` | 0 | 当前 RQData 环境缺少对应接口 |
| `futures_roll_yields` | 0 | 当前 RQData 环境缺少对应接口 |
| `futures_basis` | 0 | 旧盲跑为空，默认关闭全合约 basis |

RQData 覆盖审计结果：

| 数据集 | 状态 |
|---|---|
| 主力 / 次主力映射 | 25 个核心品种 OK，rank=1/2 |
| 复权因子 | 25 个核心品种 OK |
| 仓单 | 25 个核心品种 OK |
| 每日可交易合约池 | 25 个核心品种 OK，覆盖 2024-01-01 至 2026-06-24 |
| 主连日线校验样本 | 25 个核心品种 OK |
| 主连多周期样本 | 25 个核心品种 OK，1m/5m/15m/30m/60m |
| 连续合约映射 | 当前缺口 |

字段审计结果：

| 数据集 | 状态 | 说明 |
|---|---|---|
| `futures_ex_factor` | OK | raw 字段完整 |
| `trading_parameters` | OK | raw 字段完整 |
| `warehouse_stocks` | OK | raw 字段完整 |
| `market_sample` | OK | raw 保留分钟级 `datetime` |
| `contract_universe` | OK | raw 有 `date/product/contract` |
| `dominant_daily_baseline` | OK | raw 有日线校验字段 |
| `daily_baseline` | partial_bad_raw | 旧非核心 `a/ad` raw 有少量缺 `date`，核心目标数据不受影响 |
| `continuous_contracts` | empty_raw | 当前环境接口不可用 |

报告文件：

```text
data/reports/rqdata_field_audit.csv
data/reports/rqdata_field_audit.md
data/reports/rqdata_coverage_matrix.csv
data/reports/rqdata_missing_items.csv
data/reports/rqdata_product_coverage_summary.md
```

## 8. 已知缺口和后续处理

### 8.1 TqSdk 正式行情主链路

TqSdk / 天勤专业版是后续长期行情下载和交易辅助主链路。目前本文不宣称已完成 TqSdk 全量行情下载器。

后续需要实现：

- TqSdk DataDownloader 接入。
- 真实合约 1m / tick 按需下载。
- 主力映射与真实合约成交回测衔接。
- TqSdk 数据写入 canonical bars Parquet。
- 与 RQData 日线和样本行情做交叉校验。

### 8.2 连续合约映射

当前安装的 RQData futures 模块没有可用的 `get_continuous_contracts`，因此：

- `futures_continuous_contract_map` 表已建。
- `scripts/rqdata_continuous_contracts_sync.py` 已实现入口。
- 当前表为空，不包装成已完成。

后续可以选择：

- 升级或确认 RQData 接口包。
- 用每日合约池 + 主力映射 + 合约月份规则自行生成近月 / 次月映射。
- 等 TqSdk 数据链路完成后，用本地规则统一生成期限结构映射。

### 8.3 roll_yield 和 basis

当前环境没有可用的 roll yield 接口，basis 全合约盲跑为空。因此：

- `futures_roll_yields` 为空。
- `futures_basis` 为空。
- `research_enhancers` 默认不跑 basis，必须显式加参数。

后续如果要做期限结构和升贴水研究，建议单独确认接口适用对象，再按重点品种小样本开始，不继续全合约盲跑。

### 8.4 旧 raw 的处理

旧 raw 不删除，作为试跑证据保留。审计脚本会标记：

- `ok`
- `missing_raw`
- `empty_raw`
- `partial_bad_raw`
- `needs_rerun`

如果某类数据进入正式研究使用，应以最新审计报告为准，必要时按 manifest 补跑。

## 9. 常用命令

### 9.1 迁移和测试

```bash
uv run --project services/quant-api python -m alembic current
uv run --project services/quant-api python -m alembic upgrade head
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
```

### 9.2 RQData 审计

```bash
uv run --project services/quant-api python scripts/rqdata_audit.py
uv run --project services/quant-api python scripts/rqdata_field_audit.py run
uv run --project services/quant-api python scripts/rqdata_coverage_audit.py run
```

### 9.3 RQData 结构化补跑

```bash
uv run --project services/quant-api python scripts/rqdata_catalog_sync.py run --resume
uv run --project services/quant-api python scripts/rqdata_main_mapping_sync.py run --ranks 1 2 --resume
uv run --project services/quant-api python scripts/rqdata_ex_factor_sync.py run --resume
uv run --project services/quant-api python scripts/rqdata_trading_params_sync.py run --resume
uv run --project services/quant-api python scripts/rqdata_daily_baseline_sync.py run --resume
uv run --project services/quant-api python scripts/rqdata_research_enhancers_sync.py run --resume
uv run --project services/quant-api python scripts/rqdata_contract_universe_sync.py run --start-date 2024-01-01 --end-date 2026-06-24 --resume
uv run --project services/quant-api python scripts/rqdata_dominant_daily_baseline_sync.py run --resume
uv run --project services/quant-api python scripts/rqdata_market_samples_sync.py run --resume
```

### 9.4 只读 DB 计数查询

```bash
uv run --project services/quant-api python - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd() / "services/quant-api"))
from sqlalchemy import text
from app.db.session import SessionLocal

tables = [
    "instruments",
    "contracts",
    "main_contract_map",
    "futures_ex_factors",
    "futures_trading_parameters",
    "fee_margin_rules",
    "futures_warehouse_stocks",
    "futures_contract_universe",
    "market_data_files",
    "data_quality_reports",
]

with SessionLocal() as session:
    for table in tables:
        count = session.execute(text(f"select count(*) from {table}")).scalar_one()
        print(f"{table}: {count}")
PY
```

## 10. 开发边界

后续修改数据中心时必须遵守：

- 表结构变更走 SQLAlchemy 模型和 Alembic migration。
- 大体量行情明细优先 Parquet，不进 PostgreSQL。
- 新数据源必须先落 raw，再标准化，再写索引和质量报告。
- 新 Parquet 数据进入默认回测前，必须有 `market_data_files` 和 `data_quality_reports`。
- 回测读取统一走 `MarketDataReader` 或后续等价数据访问层。
- 供应商原始字段差异留在 adapter / ingestor，业务层读取统一字段。
- 任何凭据只从本地环境或本机配置读取，不写入代码、数据库或文档。
