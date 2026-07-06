# RQData PoC Report

生成时间：2026-07-06
阶段：阶段 1-A，RQData PoC 审计与报告模板
性质：docs-only / read-only audit

## 1. Status

当前状态：`Stage 1-A audit/template only`。

本报告只审计当前仓库中 RQData 相关代码、依赖、配置、脚本和测试覆盖，建立后续 PoC 报告模板。

本轮没有运行 RQData，没有读取真实凭据，没有写入 `data/`，没有写数据库，没有启动服务，也没有把 RQData 权限、JM 数据更新、实时 1m 入库、`signal_events` 或企业微信提醒写成已完成能力。

结论口径：

- 后端代码中已有 RQData client、结构化 ingest、Parquet 写入、DB 登记、质量检查和读取边界。
- `rqdatac` 已是后端依赖，当前 lockfile 记录版本为 `3.2.5`。
- active 行情读取边界已收敛为 `local_parquet` / `rqdata` + `primary` + `quality_status != failed`。
- 真实 RQData 权限、字段形态、数据可用性、限制和错误类型尚未通过本轮验证。

## 2. Scope and Non-goals

本轮允许：

- 审计 RQData 相关代码、依赖、脚本和测试。
- 更新本报告。
- 更新 `tasks/current.md`。
- 运行不访问真实 RQData 的隔离测试。

本轮禁止：

- 不修改业务代码、前端代码、策略代码、回测代码或 migration。
- 不运行 RQData，不初始化真实下载任务。
- 不读取、打印、记录 RQData 账号、密码、license、token 或 key。
- 不写 `data/`，不写数据库，不启动服务。
- 不提交 `.env` 或任何敏感配置。
- 不把阶段 1 写成已经通过。
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

## 5. RQData Capability Matrix

本矩阵只记录当前代码入口，不代表真实 RQData 权限或字段已经通过验证。

| 能力 | 代码入口 | 当前状态 |
|---|---|---|
| 期货合约基础信息 | `RqDataClient.all_future_instruments()` / `CatalogIngestor` | 代码有入口，真实权限未验证。 |
| 交易日历 | `RqDataClient.trading_dates()` / `CatalogIngestor` | 代码有入口，真实权限未验证。 |
| 交易时段 | `RqDataClient.trading_periods()` / `CatalogIngestor` | 代码有入口，真实权限未验证。 |
| 主力映射 | `RqDataClient.dominant_contracts()` / `MainMappingIngestor` | 代码有入口，真实权限未验证。 |
| 连续合约 | `RqDataClient.continuous_contracts()` / `continuous_contract_by_type()` | 代码有入口，真实权限未验证。 |
| 复权因子 | `RqDataClient.ex_factor()` / `ExFactorIngestor` | 代码有入口，真实权限未验证。 |
| 交易参数 | `RqDataClient.trading_parameters()` / `TradingParameterIngestor` | 代码有入口，真实权限未验证。 |
| tick size | `RqDataClient.price_tick()` | 代码有入口，真实权限未验证。 |
| 合约乘数 | `RqDataClient.contract_multiplier()` | 代码有入口，真实权限未验证。 |
| 日线 | `RqDataClient.exchange_daily()` / `dominant_daily_price()` | 代码有入口，真实权限未验证。 |
| 分钟 bar | `RqDataClient.contract_bars()` / `main_price()` / `bar_sample.py` | 代码有入口，真实权限未验证。 |
| 仓单 | `RqDataClient.warehouse_stocks()` / `ResearchEnhancerIngestor` | 代码有入口，真实权限未验证。 |
| 期限结构 | `RqDataClient.roll_yield()` / `ResearchEnhancerIngestor` | 代码有入口，真实权限未验证。 |
| 基差 | `RqDataClient.basis()` / `ResearchEnhancerIngestor` | 代码有入口，真实权限未验证。 |

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

## 7. Risks and Gaps

- `tasks/current.md` 在本轮开始前仍停留在阶段 0，需要本轮更新为阶段 1-A。
- 真实 RQData 环境、权限、字段形态、频率限制、访问限制和错误类型尚未验证。
- `scripts/*sync.py` 的 `--dry-run` 通常不会写 manifest，但部分脚本仍会打开 DB session 或依赖 DB 中的产品/合约状态，后续运行前应单独确认。
- `rqdata_field_audit.py` 会写 `data/reports`，不适合本轮执行。
- `rqdata_audit.py` 会读 `data/` 和 DB，适合后续数据资产审计，不适合当前权限 PoC。
- `rqdata_v1b_jm_asset.py` 和各类 sync 脚本存在真实写入能力，必须等阶段 1-B / 阶段 2 明确授权后再运行。
- 仓库仍有部分旧文档描述历史路线，后续如作为当前事实使用，需要按 `PROJECT_SNAPSHOT.md`、`CURRENT_STATE.md` 和当前代码重新核对。

## 8. Next Stage 1-B Recommendation

建议下一步进入阶段 1-B：真实 RQData 只读权限与字段 PoC。

阶段 1-B 建议先确认：

- 只读运行命令清单。
- 是否允许初始化 RQData client。
- 是否允许读取本地环境变量，但不打印真实值。
- 是否允许输出脱敏 JSON / Markdown 报告。
- 输出目录策略：优先写 `docs/` 报告；如必须写 `data/`，需要用户单独授权。
- 错误类型记录口径：只记录异常类型、接口名、脱敏消息和是否可重试。

阶段 1-B 不应做：

- 不写正式 JM 数据资产。
- 不写 PostgreSQL。
- 不生成 active market data entry。
- 不启动 worker / scheduler / 服务。
- 不把只读 PoC 结论升级为数据链路已完成。
