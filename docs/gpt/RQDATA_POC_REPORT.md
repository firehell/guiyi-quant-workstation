# RQData PoC Report

生成时间：2026-07-06
阶段：阶段 1-C，真实 RQData 只读权限与字段 PoC
性质：readonly RQData PoC / docs update

## 1. Status

当前状态：`Stage 1-C readonly RQData PoC complete with PARTIAL decision`。

阶段 1-A 已完成 RQData 相关代码、依赖、配置、脚本和测试覆盖审计，并建立本报告模板。

阶段 1-B 新增默认 dry-run 的只读 PoC 脚本和 mock 测试。默认模式不构造 `RqDataClient`，不 import / 调用真实 RQData API，只输出跳过状态和安全边界。

阶段 1-C 在用户明确授权后运行真实只读 RQData PoC。结果只写入仓库外 `/tmp/guiyi-rqdata-poc-result.md`，未写入 `data/`，未写数据库，未写 parquet，未写 manifest，未启动服务，也没有把 RQData 权限 PoC 结论升级为 JM 数据更新、实时 1m 入库、`signal_events` 或企业微信提醒已完成。

结论口径：

- 后端代码中已有 RQData client、结构化 ingest、Parquet 写入、DB 登记、质量检查和读取边界。
- `rqdatac` 已是后端依赖，当前 lockfile 记录版本为 `3.2.5`。
- active 行情读取边界已收敛为 `local_parquet` / `rqdata` + `primary` + `quality_status != failed`。
- 真实 RQData import/auth、JM 合约、1d/1m 小样本、5m/15m 直取、主力映射和交易参数已通过只读 PoC。
- 阶段 1-C 判定为 `PARTIAL`：核心历史数据权限可支撑阶段 2 继续，但 sessions / continuous / ex_factor 空样本和 realtime wrapper 仍需后续确认。

## 2. Scope and Non-goals

阶段 1-A 允许：

- 审计 RQData 相关代码、依赖、脚本和测试。
- 更新本报告。
- 更新 `tasks/current.md`。
- 运行不访问真实 RQData 的隔离测试。

阶段 1-B 允许：

- 新增默认 dry-run 的只读 PoC CLI：`scripts/rqdata_realtime_poc.py`。
- 新增不访问真实 RQData 的 mock 合约测试：`services/quant-api/tests/test_rqdata_realtime_contract.py`。
- 更新本报告和 `tasks/current.md`。
- 运行 dry-run、mock 测试、ruff 和文本安全检查。

阶段 1-C 允许：

- 在用户授权后运行 `scripts/rqdata_realtime_poc.py --run-readonly --format markdown`。
- 将只读 PoC 输出保存到仓库外 `/tmp/guiyi-rqdata-poc-result.md`。
- 更新本报告和 `tasks/current.md`。

阶段 1-A / 1-B / 1-C 共同禁止：

- 不修改业务代码、前端代码、策略代码、回测代码或 migration。
- 不运行 RQData 写入、下载、sync、asset 或 ingest 任务。
- 不读取、打印、记录 RQData 账号、密码、license、token 或 key。
- 不写 `data/`，不写数据库，不写 parquet，不写 manifest，不启动服务。
- 不提交 `.env` 或任何敏感配置。
- 不把阶段 1 PoC 结论升级为数据链路已完成。
- 不把 JM 数据更新、实时 1m 入库、`signal_events` 或企业微信提醒写成已完成能力。

## 3. Dependency and Credential Boundary

依赖现状：

| 文件 | 发现 |
|---|---|
| `services/quant-api/pyproject.toml` | `dependencies` 中包含 `rqdatac`。 |
| `services/quant-api/uv.lock` | 当前锁定 `rqdatac 3.2.5`。 |
| `.env.example` | 仅提供 RQData 环境变量占位说明；真实值只能在本地未提交配置中维护。 |

凭据入口：

| 入口 | 代码位置 | 说明 |
|---|---|---|
| `RQDATAC2_CONF` / `RQDATAC_CONF` | `app/services/rqdata_ingest/client.py` | 作为 URI 方式初始化。 |
| `RQDATA_LICENSE_KEY` | `app/services/rqdata_ingest/client.py` | 作为 license 方式初始化。 |
| `RQDATA_USERNAME` + `RQDATA_PASSWORD` | `app/services/rqdata_ingest/client.py` | 作为用户名密码方式初始化，可选 `RQDATA_ADDR`。 |

安全边界：

- 文档和日志只能记录变量名，不能记录真实值。
- 本轮没有调用 `RqDataClient()` 访问真实环境。
- 后续真实 PoC 必须只输出字段、状态、错误类型和脱敏摘要。

## 4. Code Inventory

### 4.1 `services/quant-api/app/data_sources/`

| 文件 | 审计结论 |
|---|---|
| `base.py` | 定义 `MarketDataQuery` 和 `MarketDataProvider` 抽象读取边界。 |
| `roles.py` | 定义 `primary`、`validation`、`legacy_reference`、`candidate`；primary provider 当前为 `local_parquet` 和 `rqdata`。 |
| `local_parquet_provider.py` | 基于 `MarketDataReader` 读取标准化本地数据，并给返回行补充 `data_role` 和 `research_only`。 |
| `rqdata_provider.py` | `RQDataProvider` 只从本地标准化存储读取 RQData-origin bars，不直接调用 RQData API。 |
| `providers.py` / `__init__.py` | 提供兼容导出。 |

读取边界要点：

- active 读取默认只允许 `local_parquet` / `rqdata`。
- 默认只允许 `data_role = primary`。
- `quality_status = failed` 的文件会被排除。
- legacy / validation 数据不会进入默认 active 读取。

### 4.2 `services/quant-api/app/services/rqdata_ingest/`

| 文件 | 审计结论 |
|---|---|
| `client.py` | 封装 RQData client 初始化和期货接口：合约、交易日、交易时段、主力映射、连续合约、复权因子、交易参数、tick size、合约乘数、日线、分钟 bar、仓单、期限结构、基差。 |
| `ingestors.py` | 包含结构化 ingest：catalog、calendar、session、main mapping、continuous contracts、contract universe、ex factor、trading parameters、daily baseline、dominant daily baseline、market samples、research enhancers。会写 raw parquet 和 DB 表。 |
| `bar_sample.py` | 包含小样本 bar 下载、标准化、质量检查、DuckDB summary、market file 和 quality report 登记。会写 parquet 和 DB。 |
| `quality.py` | 提供结构化数据字段/重复检查，规则版本为 `rqdata_structured_v1`。 |
| `db.py` | 记录 `DataDownloadTask`、`MarketDataFile`、`DataQualityReport`，计算 checksum。 |
| `manifest.py` | CSV manifest 状态跟踪，会写 `data/manifests`。 |
| `parquet.py` | 原子写 parquet 和计算 sha256。 |
| `jm_update_plan.py` | 构建 JM 历史更新只读计划；返回推荐命令和安全标志，不直接写数据或 DB。 |
| `recovery.py` | 从已有 raw parquet 恢复结构化表，会读 `data/raw/rqdata` 并写 DB。 |

### 4.3 `scripts/`

| 脚本 | 风险分类 | 审计结论 |
|---|---|---|
| `rqdata_jm_update_plan.py` | RQData 只读计划；会初始化 RQData | 打印 JM 更新计划 JSON，不写 `data/` 或 DB；后续真实 PoC 才可运行。 |
| `rqdata_realtime_poc.py` | 默认 dry-run；真实只读必须显式授权 | 输出 RQData 能力检查矩阵到 stdout；默认不构造 client，不调用 RQData，不写 `data/` 或 DB。 |
| `rqdata_sync_common.py` | 公共库；可能读 DB / manifest | 提供产品池、合约选择、manifest 和 dry-run 逻辑；dry-run 通常不写 manifest，但选择范围可能依赖 DB state。 |
| `rqdata_catalog_sync.py` | 写 DB / raw parquet | 同步合约、日历、交易时段和 raw parquet。 |
| `rqdata_main_mapping_sync.py` | 写 DB / raw parquet / manifest | 同步主力和次主力映射。 |
| `rqdata_contract_universe_sync.py` | 写 DB / raw parquet / manifest | 同步每日可交易合约池。 |
| `rqdata_continuous_contracts_sync.py` | 写 DB / raw parquet / manifest | 同步 front / next continuous contracts。 |
| `rqdata_ex_factor_sync.py` | 写 DB / raw parquet / manifest | 同步复权因子。 |
| `rqdata_trading_params_sync.py` | 写 DB / raw parquet / manifest | 同步手续费、保证金、tick size、合约乘数等交易参数。 |
| `rqdata_daily_baseline_sync.py` | 写 DB / raw parquet / manifest | 同步实际合约日线基准数据。 |
| `rqdata_dominant_daily_baseline_sync.py` | 写 DB / raw parquet / manifest | 同步主力日线样本。 |
| `rqdata_market_samples_sync.py` | 写 DB / raw parquet / manifest | 同步有限行情样本。 |
| `rqdata_research_enhancers_sync.py` | 写 DB / raw parquet / manifest | 同步仓单、期限结构、基差等研究增强数据。 |
| `rqdata_recover_raw.py` | 读 raw parquet / 写 DB | 从已有 raw parquet 恢复结构化表。 |
| `rqdata_audit.py` | 读 `data/` / 读 DB | 审计 raw parquet、manifest、market file 和 quality report。 |
| `rqdata_field_audit.py` | 读 `data/` / 写 `data/reports` | 审计 raw parquet 字段并输出 CSV / Markdown 报告。 |
| `rqdata_coverage_audit.py` | 读 `data/` / 可能写报告 | 审计结构化覆盖情况。 |
| `rqdata_v1b_jm_asset.py` | 写 JM 标准资产 / DB | 构建并登记 V1-B JM RQData 样本资产；本轮禁止运行。 |
| `backfill_jm_price_tick.py` | 写 DB | 从审计来源回填价格跳动值；本轮不涉及。 |

### 4.4 Tests

相关测试位于 `services/quant-api/tests/`，仓库根目录没有 `tests/` 目录。

| 测试文件 | 覆盖点 |
|---|---|
| `test_rqdata_client.py` | RQData symbol / contract 规范化、主力价格起点限制、tick size 和合约乘数 fallback。 |
| `test_rqdata_structured_ingest.py` | fake RQData client 下的结构化 ingest、raw parquet、DB 表、quality report、真实字段形态兼容。 |
| `test_rqdata_jm_update_plan.py` | JM 更新计划分段、data_version、dry-run safety 标志。 |
| `test_rqdata_sync_common.py` | 默认研究品种池、DB 中产品/合约选择逻辑。 |
| `test_data_sources.py` | active provider / data_role / quality_status 边界。 |
| `test_market_data_reader.py` | DuckDB 读取标准 bars、active 数据过滤、质量状态聚合。 |
| `test_standard_parquet_fixture.py` | 标准 parquet schema、OHLC 合法性、DuckDB / provider 可读性。 |
| `test_rqdata_realtime_contract.py` | 覆盖 1-B PoC 脚本的默认 dry-run、脱敏、缺包结构化失败、mock 成功/异常、无数据/DB 写入引用和输出不含敏感值。 |

## 5. RQData Capability Matrix

本矩阵区分当前代码入口和阶段 1-C 真实只读 PoC 结果。阶段 1-C 只验证接口权限、字段形态和小样本返回，不代表 JM 数据已经更新，也不代表实时 1m 入库已经完成。

| 能力 | 代码入口 | 当前状态 |
|---|---|---|
| 期货合约基础信息 | `RqDataClient.all_future_instruments()` / `CatalogIngestor` | 1-C pass；JM/DCE 合约字段可用。 |
| 交易日历 | `RqDataClient.trading_dates()` / `CatalogIngestor` | 1-C pass；小样本返回 2 个日期值。 |
| 交易时段 | `RqDataClient.trading_periods()` / `CatalogIngestor` | 1-C partial；接口未报错但返回 0 行。 |
| 主力映射 | `RqDataClient.dominant_contracts()` / `MainMappingIngestor` | 1-C pass；返回 `date` / `dominant`。 |
| 连续合约 | `RqDataClient.continuous_contracts()` / `continuous_contract_by_type()` | 1-C partial；接口未报错但返回 0 行。 |
| 复权因子 | `RqDataClient.ex_factor()` / `ExFactorIngestor` | 1-C partial；返回字段但 0 行。 |
| 交易参数 | `RqDataClient.trading_parameters()` / `TradingParameterIngestor` | 1-C pass；保证金、手续费字段可用。 |
| tick size | `RqDataClient.price_tick()` | 代码有入口；1-C 未单独探测。 |
| 合约乘数 | `RqDataClient.contract_multiplier()` | 1-C pass；返回 scalar value。 |
| 日线 | `RqDataClient.exchange_daily()` / `dominant_daily_price()` | 1-C pass；1d 小样本含 OHLCV 和 `open_interest`。 |
| 分钟 bar | `RqDataClient.contract_bars()` / `main_price()` / `bar_sample.py` | 1-C pass；1m / 5m / 15m / 30m / 60m 小样本含 OHLCV 和 `open_interest`。 |
| 仓单 | `RqDataClient.warehouse_stocks()` / `ResearchEnhancerIngestor` | 代码有入口；1-C 未探测。 |
| 期限结构 | `RqDataClient.roll_yield()` / `ResearchEnhancerIngestor` | 代码有入口；1-C 未探测。 |
| 基差 | `RqDataClient.basis()` / `ResearchEnhancerIngestor` | 代码有入口；1-C 未探测。 |

## 6. Existing Test Coverage

本轮执行了隔离测试：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_client.py services/quant-api/tests/test_rqdata_structured_ingest.py services/quant-api/tests/test_rqdata_jm_update_plan.py services/quant-api/tests/test_rqdata_sync_common.py services/quant-api/tests/test_data_sources.py services/quant-api/tests/test_market_data_reader.py
```

结果：

```text
37 passed
```

测试说明：

- 这些测试使用 fake RQData client、SQLite in-memory database 和 `tmp_path`。
- 测试不访问真实 RQData。
- 测试不读取真实凭据。
- 测试不写项目 `data/`。
- 测试不写本地 PostgreSQL。

阶段 1-B 新增隔离测试：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_realtime_contract.py
```

结果：

```text
7 passed
```

新增测试说明：

- 默认 dry-run 不构造 `RqDataClient`。
- 错误信息会替换本地环境中的敏感值。
- 缺少 `rqdatac` 时返回结构化失败，不抛出未处理异常。
- mock client 成功和异常路径都能生成能力矩阵。
- 脚本源码不引用项目数据写入路径或 DB 连接入口。
- dry-run 输出只包含变量 present / missing，不包含真实值。

## 7. Risks and Gaps

- 阶段 1-C 判定为 `PARTIAL`，核心历史数据权限和字段 PoC 可支撑阶段 2，但不是 full pass。
- `trading_sessions` 状态为 `pass` 但 `sample_row_count=0`，后续需要确认是接口参数、产品代码还是 RQData 返回口径问题。
- `continuous_contracts` 状态为 `pass` 但 `sample_row_count=0`，阶段 2 不能依赖它直接作为合约切换依据。
- `ex_factor` 状态为 `pass` 但 `sample_row_count=0`，后续若需要复权口径必须单独确认。
- `realtime_snapshot_or_bar` 仍为 `skipped`，当前没有安全 realtime wrapper；不得把 1-C 写成实时 1m 入库能力已完成。
- `scripts/*sync.py` 的 `--dry-run` 通常不会写 manifest，但部分脚本仍会打开 DB session 或依赖 DB 中的产品/合约状态，后续运行前应单独确认。
- `rqdata_field_audit.py` 会写 `data/reports`，不适合只读固化任务执行。
- `rqdata_audit.py` 会读 `data/` 和 DB，适合后续数据资产审计，不适合当前 1-D docs-only 固化任务。
- `rqdata_v1b_jm_asset.py` 和各类 sync 脚本存在真实写入能力，必须等阶段 2 任务包明确授权后再运行。
- 仓库仍有部分旧文档描述历史路线，后续如作为当前事实使用，需要按 `PROJECT_SNAPSHOT.md`、`CURRENT_STATE.md` 和当前代码重新核对。

## 8. Stage 1-B Readonly PoC Script

新增脚本：

```bash
uv run --project services/quant-api python scripts/rqdata_realtime_poc.py --dry-run
```

真实只读入口：

```bash
uv run --project services/quant-api python scripts/rqdata_realtime_poc.py --run-readonly --format markdown
```

运行边界：

- 默认无参数等价于 `--dry-run`。
- `--dry-run` 不 import / 调用真实 RQData，不构造 `RqDataClient`。
- `--run-readonly` 必须等用户单独授权后执行。
- 输出只走 stdout，不写 `data/`、DB、parquet 或 manifest。
- 凭据变量只输出 `present` / `missing`，不输出真实值。
- 异常信息经过本地环境变量值替换后再输出。

结果结构：

| 字段 | 说明 |
|---|---|
| `capability` | 能力名称，例如 `historical_1m_sample`。 |
| `status` | `pass` / `fail` / `skipped`。 |
| `api_name` | 预期 RQData API 或底层接口名。 |
| `wrapper_name` | 当前仓库 wrapper 入口。 |
| `error_type` | 异常类型，不包含敏感值。 |
| `redacted_message` | 脱敏后的错误摘要。 |
| `sample_columns` | 最多记录小样本字段名。 |
| `sample_row_count` | 最多记录 5 行以内的样本行数摘要。 |
| `notes` | 安全边界、跳过原因或字段关注点。 |

dry-run 摘要：

- `mode = dry-run`。
- `writes_data = false`。
- `writes_database = false`。
- `writes_parquet = false`。
- `prints_secret_values = false`。
- 所有能力项状态为 `skipped`，原因是没有构造 client，也没有调用 RQData API。

能力项覆盖：

- `rqdatac_import`。
- `rqdata_auth_init`。
- `jm_contract_catalog`。
- `dce_jm_contract_list`。
- `historical_1d_sample`。
- `historical_1m_sample`。
- `frequency_5m_direct`、`frequency_15m_direct`、`frequency_30m_direct`、`frequency_1h_direct`。
- `trading_calendar`、`trading_sessions`。
- `dominant_mapping`、`continuous_contracts`。
- `ex_factor`、`contract_multiplier`、`margin`、`commission`。
- `realtime_snapshot_or_bar`：当前没有安全 wrapper，本轮记录为 skipped。
- `invalid_symbol_error`、`unsupported_frequency_error`。

## 9. Stage 1-D Consolidated Decision

阶段 1 已完成并固化为 `PARTIAL`。

允许进入阶段 2：

- 阶段 2 可以设计 JM 历史数据更新到最新交易日。
- 阶段 2 必须先使用 Plan 模式明确更新范围、输出路径、manifest、checksum、quality_status、最小质量检查和回滚策略。
- 阶段 2 不得直接运行 `rqdata_v1b_jm_asset.py` 或 sync 写入脚本，直到任务包明确授权。

不允许夸大的结论：

- 不得写成 JM 数据已经更新。
- 不得写成 active 数据链路已经完成。
- 不得写成实时 1m 入库已经完成。
- 不得写成 `signal_events` 或企业微信提醒已经完成。

阶段 1 保留缺口：

- `trading_sessions`、`continuous_contracts`、`ex_factor` 空样本。
- realtime snapshot / bar wrapper 未验证。
- 负向错误探针只确认 `ValueError` 类型，不代表完整错误分类已完成。

## 10. Stage 1-C Readonly Result

执行时间：2026-07-06。

结果文件：

```text
/tmp/guiyi-rqdata-poc-result.md
```

执行命令：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_rqdata_realtime_contract.py
uv run --project services/quant-api python scripts/rqdata_realtime_poc.py --dry-run --format markdown
uv run --project services/quant-api python scripts/rqdata_realtime_poc.py --run-readonly --format markdown > /tmp/guiyi-rqdata-poc-result.md
```

阶段 1-C 判定：`PARTIAL`。

核心能力结果：

| capability | status | sample_row_count | sample_columns_summary |
|---|---|---:|---|
| `rqdatac_import` | pass | 1 | `__version__=3.2.5` |
| `rqdata_auth_init` | pass | 0 | initialized `RqDataClient` |
| `jm_contract_catalog` | pass | 5 | `order_book_id`, `underlying_symbol`, `exchange`, `contract_multiplier`, `trading_hours` |
| `dce_jm_contract_list` | pass | 5 | `contract`, `date` |
| `historical_1d_sample` | pass | 2 | `open`, `high`, `low`, `close`, `volume`, `open_interest`, `settlement` |
| `historical_1m_sample` | pass | 5 | `datetime`, `trading_date`, `open`, `high`, `low`, `close`, `volume`, `open_interest` |
| `frequency_5m_direct` | pass | 5 | OHLCV + `open_interest` |
| `frequency_15m_direct` | pass | 5 | OHLCV + `open_interest` |
| `frequency_30m_direct` | pass | 5 | OHLCV + `open_interest` |
| `frequency_1h_direct` | pass | 5 | OHLCV + `open_interest` |
| `trading_calendar` | pass | 2 | date values |
| `dominant_mapping` | pass | 2 | `date`, `dominant` |
| `contract_multiplier` | pass | 1 | scalar value |
| `margin` | pass | 2 | `long_margin_ratio`, `short_margin_ratio`, order limits |
| `commission` | pass | 2 | `open_commission`, `close_commission`, `close_commission_today` |

缺口和注意事项：

- `trading_sessions` 状态为 `pass`，但 `sample_row_count=0`。
- `continuous_contracts` 状态为 `pass`，但 `sample_row_count=0`。
- `ex_factor` 状态为 `pass`，但 `sample_row_count=0`；返回字段包含 `ex_date`、`ex_factor`、`ex_end_date`、`ex_cum_factor`。
- `realtime_snapshot_or_bar` 状态为 `skipped`，因为当前没有安全 realtime wrapper。
- `invalid_symbol_error` 状态为 `fail`，错误类型为 `ValueError`，属于负向探针结果，不阻塞阶段 2。
- 真实只读命令 stderr 出现 RQData SDK warning：`unknown order_book_id: JM` 和 `invalid order_book_id: INVALID9999`。前者未阻止 JM 合约列表返回，后者来自负向探针。

安全检查：

- 输出只记录 credential source 的 `present` / `missing`，未记录真实值。
- `/tmp/guiyi-rqdata-poc-result.md` 敏感形态检查未命中。
- `writes_data=false`、`writes_database=false`、`writes_parquet=false`。
- 本阶段未写 `data/`、未写数据库、未写 parquet、未写 manifest、未启动服务。

后续建议：

- 阶段 2 可继续进入 JM 历史数据更新到最新交易日，但必须先单独制定写入任务包。
- 阶段 2 任务包需要明确输出路径、manifest、checksum、quality_status、最小数据质量检查和回滚策略。
- 不应直接运行 `rqdata_v1b_jm_asset.py` 或 sync 写入脚本，除非新任务明确授权。
