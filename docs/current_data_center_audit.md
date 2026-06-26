# 当前数据中心审计报告

版本：2026-06-25 Phase A  
范围：只审计当前实现，不修改业务逻辑，不启动 TqSdk 长下载。

## 1. 审计结论

当前数据中心已经具备可继续演进的底座：PostgreSQL 负责元数据、任务、文件索引、质量报告和 RQData 结构化事实表；Parquet 负责 raw 留底和 canonical 行情；DuckDB 通过 `MarketDataReader` 读取 Parquet 给研究、回测和 K 线工作台使用。

本阶段不建议先做数据库大迁移。`contracts` 已经包含合约乘数、交易代码、上市/退市、交割、交易时段、provider 等字段；`market_data_files` 已经包含 `instrument_symbol` 唯一约束、`row_count`、`checksum`、`quality_status`；`data_quality_reports` 已经可以用 `details` JSON 承载规则版本、差异摘要和来源信息。TqSdk V0 可以先通过约定使用现有字段，等 derived lineage 或 source_role 真正被多个调用方依赖时再迁移。

下一阶段的主要缺口不是 RQData，而是 TqSdk 历史 1m 主链路、交易时段感知聚合、多源校验和 `MarketDataReader` V2。

## 2. 当前存储分层

| 层 | 当前状态 | 说明 |
|---|---:|---|
| PostgreSQL | 已使用 | 管 `data_sources`、合约/品种、下载任务、文件索引、质量报告、RQData 结构化事实 |
| Parquet raw | 已使用 | `data/raw/rqdata/` 保留 RQData 原始接口返回；后续 TqSdk raw 也应先落这里 |
| Parquet canonical | 已使用 | `data/parquet/canonical/bars/provider=trader_future_data/...` 已有本地 canonical bars |
| Parquet derived | 未形成正式链路 | 目标由 TqSdk 1m 聚合得到 5m/15m/30m/60m/120m |
| DuckDB | 已使用 | `MarketDataReader` 通过 DuckDB 读取 Parquet |
| Redis/RQ | 架构预留 | 当前 Phase A 不审计异步下载执行器 |

## 3. PostgreSQL 当前行数

本机数据库只读计数结果：

| 表 | 行数 | 判断 |
|---|---:|---|
| `data_sources` | 4 | 已有 provider 元数据 |
| `exchanges` | 8 | 已覆盖国内主要交易所及补充项 |
| `instruments` | 134 | RQData 品种/标的层覆盖较全 |
| `contracts` | 11184 | RQData 合约基础库已落库 |
| `trading_calendars` | 7845 | 交易日历已落库 |
| `trading_sessions` | 98 | 交易时段已落库，可作为聚合基础但仍需校验夜盘规则 |
| `data_download_tasks` | 25037 | 下载任务可审计 |
| `market_data_files` | 23450 | 文件索引可审计 |
| `data_quality_reports` | 25044 | 质量报告可审计 |
| `main_contract_map` | 575156 | rank=1/2 主力映射覆盖较好 |
| `futures_ex_factors` | 2099 | 复权因子已回灌 |
| `futures_trading_parameters` | 911831 | 交易参数已落库 |
| `fee_margin_rules` | 911831 | 回测常用成本字段已同步 |
| `futures_warehouse_stocks` | 84188 | 仓单数据已落库 |
| `futures_contract_universe` | 183876 | 每日可交易合约 universe 已落库 |
| `futures_continuous_contract_map` | 0 | 当前为空，不应标记为完成 |
| `futures_roll_yields` | 0 | 当前为空，不应标记为完成 |
| `futures_basis` | 0 | 当前为空，不应标记为完成 |

## 4. 数据源状态

`data_sources` 当前状态：

| provider | 状态 | 优先级 | 当前定位 |
|---|---|---:|---|
| `trader_future_data` | enabled | 10 | 本地 canonical 行情样本和校验源 |
| `tqsdk` | planned | 20 | 下一阶段行情主源 |
| `tushare` | enabled | 30 | 元数据补充源 |
| `rqdata` | planned | 40 | 结构化研究底稿和校验源 |

这里有一个后续需要修正的语义问题：TqSdk 接入完成后，生产读取优先级应调整为 `tqsdk` 主源优先，`trader_future_data` 和 `rqdata` 只在开发/校验模式 fallback。当前表内优先级仍反映早期导入顺序，不应直接作为最终读取优先级。

## 5. RQData 链路审计

RQData 试用期沉淀目标基本完成，后续不应继续扩大行情下载范围。

已完成或可用：

| 数据 | 当前状态 |
|---|---|
| 主力/次主力映射 | `main_contract_map` 已有 575156 行 |
| 复权因子 | `futures_ex_factors` 已有 2099 行 |
| 合约基础信息 | `contracts` 已有 11184 行 |
| 交易参数历史 | `futures_trading_parameters` 和 `fee_margin_rules` 均有 911831 行 |
| 原始日线/主连日线样本 | 明细主要保留 Parquet，文件索引和质量报告已记录 |
| 交易日历/交易时段 | `trading_calendars`、`trading_sessions` 已落库 |
| 仓单 | `futures_warehouse_stocks` 已有 84188 行 |
| 每日可交易合约列表 | `futures_contract_universe` 已有 183876 行 |
| 行情校验样本 | `market_data_files` 中有 RQData `market_sample` 1m/5m/15m/30m/60m 文件索引 |

当前为空或不可用：

| 数据 | 当前状态 | 处理建议 |
|---|---|---|
| 连续合约映射 | DB 为 0；文件索引有少量记录 | 标记 unavailable/partial，不作为完成项 |
| roll_yield | DB 为 0；文件索引有空结果记录 | 保留空结果，不继续全量盲跑 |
| basis | DB 为 0；文件索引有空结果记录 | 需要重新确认接口适用对象，不继续全合约盲跑 |

## 6. 当前文件索引概况

`market_data_files` 主要分布：

| provider | data_type | period | 文件数 |
|---|---|---|---:|
| `rqdata` | `daily_baseline` | 1d | 9387 |
| `rqdata` | `trading_parameters` | 空 | 8618 |
| `rqdata` | `basis` | 空 | 4684 |
| `rqdata` | `main_contract_mapping` | 空 | 79 |
| `rqdata` | `contract_universe` | 空 | 76 |
| `rqdata` | `market_sample` | 1m | 29 |
| `rqdata` | `market_sample` | 5m/15m/30m/60m | 各 28 |
| `trader_future_data` | `main_continuous_kline` | 5m/1d | 各约 80 |
| `trader_future_data` | `main_continuous_kline` | 15m/30m/60m | 各 74 |

`data_quality_reports` 当前状态：

| provider | status | 数量 |
|---|---|---:|
| `rqdata` | passed | 17627 |
| `rqdata` | warning | 7035 |
| `trader_future_data` | passed | 370 |
| `trader_future_data` | warning | 12 |

## 7. 表结构是否需要迁移

本阶段判断：暂不需要迁移。

原因：

1. `market_data_files` 已经包含 `provider/data_type/instrument_symbol/contract_code/period/start_time/end_time/data_version` 唯一约束，可以表达 raw、canonical、derived 的文件版本。
2. `row_count/file_size_bytes/checksum/quality_status` 已经满足文件可审计要求。
3. `data_quality_reports.details` 可以承载 `check_rule_version`、`data_layer`、`source_role`、`base_provider`、`base_period`、`aggregation_rule_version`、跨源比较摘要等扩展字段。
4. `contracts` 已包含 TqSdk/RQData 合约元数据 V0 所需字段。

建议暂用约定：

| 语义 | 暂存位置 |
|---|---|
| raw/canonical/derived/validation | `market_data_files.data_type` 或 `file_path` 层级 + `details.data_layer` |
| 派生数据来源 | `data_version` + `data_quality_reports.details.base_*` |
| source_role | `data_quality_reports.details.source_role`，读取层通过 provider priority 控制 |
| 聚合规则版本 | `data_quality_reports.details.aggregation_rule_version` |

真正需要迁移的触发条件：

1. 多个服务开始频繁按 `data_layer/source_role/base_provider` 查询。
2. derived bars 需要强 lineage 追溯到多个源文件。
3. 质量报告需要按 severity/check_scope 做高频筛选。

## 8. `MarketDataReader` 当前限制

当前实现方向正确，但还不是 V2：

1. 只扫描 `file_path` 包含 `/canonical/bars/` 的文件。
2. `provider=None` 时会读取所有匹配 provider，存在混读风险。
3. 不支持 provider priority。
4. 不支持 derived bars 路径。
5. 不支持 `source_role` 或开发/校验模式开关。
6. `get_quality_status()` 目前依赖 `trader_future_data` 的 `canonical_bars_v0` 规则版本，后续 TqSdk 规则需要泛化。

V2 改造目标：

```python
load_bars(
    symbol: str,
    contract: str,
    period: str,
    start: datetime,
    end: datetime,
    provider: str | None = None,
    source_role: str = "main",
    allow_validation_source: bool = False,
    limit: int | None = None,
)
```

默认读取策略：

1. 优先读取 `provider=tqsdk` 的 canonical/derived bars。
2. 没有 TqSdk 数据时，只有在 `allow_validation_source=True` 时才 fallback 到 `trader_future_data` 或 `rqdata`。
3. 不直接读 raw。
4. 不直接调用 TqSdk/RQData SDK。

## 9. TqSdk V0 需要新增的实现

建议新增：

```text
services/quant-api/app/services/tqsdk_ingest/
  client.py
  downloader.py
  transformer.py
  quality.py
  manifest.py
  parquet.py
  db.py
```

职责：

| 模块 | 职责 |
|---|---|
| `client.py` | 从环境变量读取 TqSdk 凭据，创建/关闭 `TqApi`，不打印凭据 |
| `downloader.py` | 使用 `tqsdk.tools.DataDownloader` 按品种、月份下载主连 1m |
| `transformer.py` | 将 DataDownloader 输出转换为 canonical bars |
| `quality.py` | 检查重复、断点、OHLC、成交量、持仓、交易时段 |
| `manifest.py` | `--resume`、`--retry-failed`、`--limit` |
| `parquet.py` | 原子写 raw/canonical Parquet、checksum |
| `db.py` | 写 `data_download_tasks`、`market_data_files`、`data_quality_reports` |

新增脚本建议：

```text
scripts/tqsdk_bars_1m_sync.py
scripts/build_derived_bars.py
scripts/tqsdk_coverage_audit.py
scripts/cross_source_bar_validate.py
scripts/daily_baseline_validate.py
scripts/rqdata_backup_bundle.py
```

第一版只做：

```text
contract-mode = main
period = 1m
raw Parquet + canonical Parquet + 文件索引 + 质量报告
```

暂不做：

```text
全量 tick
全量真实合约 1m
前端直连 TqSdk
请求时动态聚合
自动实盘下单
```

## 10. TqSdk canonical bars 约定

建议 canonical 1m 路径：

```text
data/parquet/canonical/bars/
  provider=tqsdk/
    period=1m/
      exchange=SHFE/
        symbol=rb/
          contract=rb.MAIN/
            year=2024/
              month=01/
                part-000.parquet
```

建议字段：

```text
symbol
contract
exchange
datetime
trading_day
session_id
bar_index
open
high
low
close
volume
turnover
open_interest
period
provider
source_contract
is_main_continuous
adjust_type
data_version
created_at
```

注意：主连数据只能用于研究、信号和展示；真实合约成交回测仍要通过 `main_contract_map` 或 TqSdk/RQData 映射落到真实合约，不得把主连直接当可交易合约。

## 11. 1m 派生多周期

不能直接用普通 `resample()`，因为国内期货存在夜盘、午休、节假日、交易日与自然日不一致、品种交易时段不同等问题。

V0 聚合规则：

| 字段 | 聚合 |
|---|---|
| open | 第一根 1m |
| high | 最大值 |
| low | 最小值 |
| close | 最后一根 1m |
| volume | 求和 |
| turnover | 求和 |
| open_interest | 最后一根 1m |
| datetime | 派生周期结束时间 |
| trading_day | 组内交易日 |

聚合边界：

1. 基于 `trading_day/session_id/bar_index`。
2. 默认不跨 session 聚合。
3. 夜盘归属必须按交易日。
4. 派生日线不能替代供应商原始日线。

## 12. 多源校验

需要新增报告：

| 校验 | 目的 |
|---|---|
| TqSdk 1m -> 5m vs `trader_future_data` 5m | 校验聚合规则 |
| TqSdk 1m -> 15m/30m/60m vs `trader_future_data` | 校验中周期趋势周期 |
| TqSdk daily_from_1m vs RQData daily baseline | 校验日线 |
| TqSdk 主连换月 vs RQData `main_contract_map` | 识别换月规则差异，不要求完全一致 |
| TqSdk 成本参数 vs RQData `fee_margin_rules` | 校验手续费/保证金 |

报告落地：

```text
data/reports/cross_source_bar_diff.csv
data/reports/cross_source_bar_diff.md
data/reports/main_mapping_diff.csv
data/reports/daily_baseline_diff.csv
```

## 13. Phase A 验收命令

本审计阶段建议执行：

```bash
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
uv run --project services/quant-api python -m alembic current
uv run --project services/quant-api python scripts/rqdata_coverage_audit.py run
uv run --project services/quant-api python scripts/rqdata_field_audit.py run
```

如果 `ruff check .` 失败，应只记录失败原因；除非另行确认，不在 Phase A 顺手修改业务代码。

本次执行结果：

| 命令 | 结果 | 说明 |
|---|---|---|
| `cd services/quant-api && uv run pytest -q` | 通过 | 57 passed |
| `cd services/quant-api && uv run ruff check .` | 失败 | 2 个存量 F401：`app/db/session.py` 未使用 `PROJECT_ROOT`，`app/services/market_workbench.py` 未使用 `Instrument` |
| `cd services/quant-api && uv run python -m alembic current` | 通过 | 当前版本 `20260625_0007 (head)` |
| `uv run --project services/quant-api python scripts/rqdata_coverage_audit.py run` | 通过 | 刷新 `data/reports/rqdata_coverage_matrix.csv`、`rqdata_missing_items.csv`、`rqdata_product_coverage_summary.md` |
| `uv run --project services/quant-api python scripts/rqdata_field_audit.py run` | 通过 | 刷新 `data/reports/rqdata_field_audit.csv`、`rqdata_field_audit.md` |

执行注意：从仓库根目录直接运行 `uv run --project services/quant-api pytest -q` 当前会在测试收集阶段报 `ModuleNotFoundError: No module named 'app'`。本次通过的方式是在 `services/quant-api` 目录下执行 `uv run pytest -q`；后续可以统一测试命令或调整 pytest 的 import 路径配置。

审计脚本关键输出：

| 审计 | 结果 |
|---|---|
| 覆盖矩阵 | `contract_universe`、`dominant_daily_baseline`、`futures_ex_factors`、`futures_warehouse_stocks`、`market_sample` 均覆盖默认 25 品种；`main_contract_map` 覆盖 rank=1/2 共 50 项 |
| 连续合约 | `continuous_contracts` 24 项 `missing_download`、1 项 `needs_rerun`，不应标记为完成 |
| 字段审计 | `futures_ex_factor`、`trading_parameters`、`warehouse_stocks`、`market_sample`、`contract_universe`、`dominant_daily_baseline` 为 `ok` |
| 字段缺口 | `daily_baseline` 为 `partial_bad_raw`，存在旧 raw 缺 `date`；`continuous_contracts` 为 `empty_raw` |

## 14. 安全边界

1. TqSdk 凭据只从本地 `.env` 读取。
2. `.env.example` 只能保留占位符。
3. 不在日志、文档、提交信息或回复中输出任何凭证。
4. 不把 `.env` 加入 Git。
5. 真实下载先用单品种、小日期区间 smoke test，再扩大范围。

## 15. 后续建议执行顺序

1. 修正或记录当前 `ruff` 存量问题，保证后续新增代码不掩盖旧问题。
2. 实现 TqSdk 1m 主连下载器 V0，先跑 `rb` 单月 smoke test。
3. 将 TqSdk raw 转 canonical bars，并写入 `market_data_files` 和 `data_quality_reports`。
4. 升级 `MarketDataReader`，避免 provider 混读。
5. 实现交易时段感知派生周期。
6. 实现跨源校验报告。
7. 归档 RQData 结构化底稿备份。
