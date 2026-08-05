# 测试与验证入口

只记录当前可运行的命令。历史通过数量和一次性 Gate 结果以相应 receipt、报告与 Git 提交为准。

## 快速检查

Windows / PowerShell 7 为当前工程入口（canonical）：

```powershell
git diff --check
pwsh -NoProfile -File .\scripts\engineering\preflight.ps1
pwsh -NoProfile -File .\scripts\engineering\secret-scan.ps1
pwsh -NoProfile -File .\scripts\engineering\validate.ps1 -Profile Engineering
pwsh -NoProfile -File .\scripts\engineering\validate.ps1 -Profile Docs
```

`preflight.ps1` 适用于新会话、高风险任务或环境诊断；它不是每个普通改动的业务 Gate。`develop` 是日常开发分支，默认允许。脏工作区默认警告；release/tag 使用 `-RequireClean`。

专用套件仍可直接使用项目原生命令，例如 `uv run --project services/quant-api pytest ...` 与 `pnpm --dir apps/quant-web ...`。CI（`.github/workflows/optional-ci.yml`）仅作补充，不授权本地完成声明。

## 后端

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests

uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests scripts packages/quant-core/guiyi_quant
```

定向修改优先运行相关测试文件；需要数据库的测试必须使用仓库规定的隔离环境，禁止对 Runtime 数据库执行 destructive migration。

### GY-CORE-02 active dataset Facade

下列命令使用受控 SQLite/`tmp_path` fixtures，验证 JM compatibility Facade 的 response
equivalence、冻结 lineage 及 zero-write 边界；它们不构成真实 PostgreSQL、canonical
Parquet、RQData 或 Runtime Gate。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_active_dataset_resolver.py \
  services/quant-api/tests/test_market_data_service.py \
  services/quant-api/tests/test_market_data_facade_equivalence.py
```

Market/Profile 回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_actual_contract_semantics.py \
  services/quant-api/tests/test_data_profile_registry.py \
  services/quant-api/tests/test_profile_target_resolver.py \
  services/quant-api/tests/test_market_data_reader.py \
  services/quant-api/tests/test_market_data_api.py \
  services/quant-api/tests/test_market_dual_mode_contract.py \
  services/quant-api/tests/test_market_indicators_api.py \
  services/quant-api/tests/test_market_macd_indicator_api.py \
  services/quant-api/tests/test_live_market_reader.py \
  services/quant-api/tests/test_live_target_freshness.py
```

legacy Profile/lineage compatibility 回归（不证明 active selector）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_backtest_profile_contract.py \
  services/quant-api/tests/test_signal_review_profile_lineage.py \
  services/quant-api/tests/test_review_center.py
```

### GY-CORE-03 unified CLI 与兼容 Shim

`guiyi` 由 `services/quant-api` package 提供。首轮命令均为只读或 dry-run；
`runtime plan` 不打开 DB/Redis/RQData，`runtime status` 只读取既有 health service，
`data verify` 的 JM 请求复用 GY-CORE-02 Facade。

```bash
uv run --project services/quant-api guiyi --help
uv run --project services/quant-api guiyi runtime plan --product jm

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_guiyi_cli.py \
  services/quant-api/tests/test_core_cli_service.py \
  services/quant-api/tests/test_guiyi_legacy_shims.py
```

旧 `guiyi-data check-bars` 与
`scripts/rqdata_reference_metadata_gap_apply_plan.py` 仍是兼容入口；等价性测试只证明参数、
stdout/stderr、退出码和共享 service 转调，不授权运行真实数据、Runtime 或通知写入。

### GY-CORE-04 ObservationPlanRegistry 与 StrategyAdapter

定向合同、真实 HTDY evaluator 对照与零写入边界：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_observation_plan_registry.py \
  services/quant-api/tests/test_strategy_adapter.py \
  services/quant-api/tests/test_htdy_realtime_evaluator.py \
  services/quant-api/tests/test_htdy_production_kernel_policy.py \
  services/quant-api/tests/test_htdy_golden_sample.py
```

该组测试不打开正式数据库、不写 SignalEvent/notification、不调用 Runtime 或企业微信。

## Web

```bash
pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

涉及页面交互时，再运行对应 mock 或只读浏览器 smoke，并检查 console error。

### GY-DATA-CORE-V2 新任务 04（Gate 前）

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests/data_core

# 获准的 Task 04 临时库实测结果：35 passed；库在 finally 中删除。
# GUIYI_ISOLATED_MIGRATION_DATABASE_URL 必须指向与 DATABASE_URL 不同 OID 的
# PostgreSQL 16 isolated/test database。
PYTHONPATH=services/quant-api \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/alembic/test_data_core_migration.py

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_guiyi_cli.py \
  services/quant-api/tests/test_market_data_service.py \
  services/quant-api/tests/test_market_canonical_api.py \
  services/quant-api/tests/test_market_indicators_api.py \
  services/quant-api/tests/test_market_macd_indicator_api.py \
  services/quant-api/tests/test_market_data_api.py \
  services/quant-api/tests/test_market_data_facade_equivalence.py \
  services/quant-api/tests/test_market_data_reader.py \
  services/quant-api/tests/test_market_dual_mode_contract.py

VITE_JM_DATA_CORE_V2_ENABLED=true pnpm --dir apps/quant-web dev \
  --host 127.0.0.1 --port 5174
EXPECT_CANONICAL_MARKET=1 pnpm --dir apps/quant-web test:e2e
```

`guiyi data migrate` / `task07` 旧路由已从 active CLI 移除。历史迁移验收改走
`guiyi data download|aggregate|audit` 与 Data Core V2 服务测试；receipt/report/evidence
仅作历史事实，不再作为执行授权。

### GY-DATA-CORE-V2 Task 07 Stage C 精简验收

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/data_core/test_task07_target_canonical.py \
  services/quant-api/tests/data_core/test_catalog.py \
  services/quant-api/tests/test_market_data_service.py \
  services/quant-api/tests/test_guiyi_cli.py \
  services/quant-api/tests/test_scripts_cli_consolidation_properties.py
```

该组验证 JM target config、MainContractMap、七周期 MarketDataService，以及统一
`guiyi data download|aggregate|sync|audit|live|verify` 合同。测试不调用 RQData，
不写正式 Parquet/PostgreSQL。

旧 `guiyi data task07 assess` 生产只读 Gate 已从 active CLI 移除；如需对正式
canonical root 做只读验收，应另开精确范围的一次性执行意图，并通过
`guiyi data audit` / Data Core 服务测试路径完成。

### Task 05 derived/reference inventory

下列 CLI 只输出稳定 JSON；不加载 RQData、不含 delete/apply/repair mode。真实 DB 只允许通过
显式 `--database-url-env NAME` 外部只读 Gate 注入，绝不输出 URL；PostgreSQL 精确使用
`BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`。`--max-files` 限制文件、匹配和输出记录，
`--max-directories` 单独限制目录；`--max-file-bytes`、`--max-total-bytes` 与 `--max-ids` 均有安全默认值。任何预算、
symlink、非 UTF-8、TOCTOU、缺表/缺列或读取错误都会返回 incomplete diagnostics，绝不把截断
或猜测结果当作完整 inventory。`market_data_files.file_path` 必须为绝对路径、containment 于显式
`--canonical-root`（默认 data root）后转为 POSIX 相对 URI，并与唯一 `Catalog partition.file_uri`
精确一致；provider、symbol、contract、period、checksum、manifest/version 证据任一漂移或 URI
歧义均为 REVIEW_REQUIRED。legacy `bars` 的 5m/15m/30m/60m 和明确 derived 均为 REBUILD_ONLY。
Task 05 inventory 当前未实现对 manifest/Parquet 的完整物理 proof reader；因此即使 Catalog
字段一致的 direct candidate 也必须保持 REVIEW_REQUIRED 并输出
`PHYSICAL_KEEP_PROOF_REQUIRED`，绝不产生弱 `KEEP_TRUSTED_CANONICAL`。
Catalog 表中没有可与 `MarketDataFile.data_version` 直接对照的 source-data-version 字段；
`manifest_version` 不是 data version，故 inventory 只可标记
`metadata_aligned_partial_data_version_unverified`，不能声称 data version 已对齐。

以下 zero-reference 描述仅保留为 superseded historical Task 07 inventory 测试说明，
不再是 active Stage C 验收或完成条件。旧 Task 07 曾要求 repository active/review
references 为零，且
27 条显式数据库 relation rule 的 active/review count 为零。规则覆盖 active/unknown Profile
Binding、quality report→file、file→download task、active/unknown download task、Backtest
task/report/trade/order、StrategySignal/SignalEvent/scan/notification、Review note/attachment/tag
与 live/EOD 表；每条输出 `table/predicate/count/row_ids/target_ids/status/reason`。查询只使用固定
allowlist、参数化 predicate、精确 count 和受 `--max-ids` 限制的 identifier read；缺表、缺列、
未知状态或 identifier 超限均 fail-closed，不能产生 zero-reference 资格。

repository source/doc scan 包含 `.mjs/.mts/.cjs` 及 Makefile/GNUmakefile、extensionless README、
Dockerfile。其他未知无扩展名 regular file 会输出 `REPO_UNKNOWN_EXTENSIONLESS_FILE`，未知 suffix
输出 `REPO_UNKNOWN_FILE_TYPE`，并令结果 incomplete；CSV、binary/data、compiled/cache 类型只可按
`explicit_file_type_exclusions` 中的显式理由跳过，不能静默漏掉潜在 consumer reference。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_derived_reference_inventory.py
```

`scripts/derived_reference_inventory.py` 已按 scripts-cli-consolidation 从仓库移除；
inventory 行为由对应服务测试与 `guiyi data audit` 覆盖。真实 PostgreSQL/data root
只读盘点仍是 external Gate，不授权重建、迁移、删除、Runtime、通知或交易。

生产 migration、真实 RQData/Parquet/PostgreSQL apply 与创建/删除隔离 PostgreSQL 数据库
都需要精确授权。Task 04 的专用临时库已在用户授权后完成测试并删除；这不授权生产 apply，
也不得用未设置 isolated URL 时的 skipped 用例冒充 upgrade/downgrade/upgrade 通过。

### GY-DATA-CORE-V2 Task 06 clean-start live/review loop

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_live_review_loop_models.py \
  services/quant-api/tests/test_live_review_loop_contracts.py \
  services/quant-api/tests/test_live_review_loop_eod_sample_retention.py \
  services/quant-api/tests/test_live_review_loop_api_and_event_gate.py \
  services/quant-api/tests/test_runtime_health.py

PYTHONPATH=services/quant-api \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/alembic/test_live_review_loop_migration.py
```

迁移测试必须提供 `GUIYI_ISOLATED_MIGRATION_DATABASE_URL`，并由 safety guard 证明与 Runtime
`DATABASE_URL` 的 database/OID 均不同；实际完成 `0027 -> head(0031) -> 0027 -> head(0031)`。
未配置时的
skip 只证明 offline SQL/head tests，不满足 Task 06 migration 验收。所有 Task 06 flags 默认 false；
disabled smoke 不读取 RQData、不写业务表、不启动 scheduler、不创建 SignalEvent/notification。
合同测试同时冻结 trusted builder 的 EMA21 identity/parameters/digest/fingerprint golden vector、
long/short/equal 三态，以及 Runtime/EOD 不允许注入其他 evaluator 的边界。

## 数据、回测与运行时只读验证

```bash
bash scripts/engineering/runtime-health.sh --json

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown
```

真实数据、RQData、PostgreSQL、Runtime 或企业微信操作在执行前必须由用户的一次明确请求标识操作类别和精确范围，并通过对应业务合同的质量与安全检查。通用测试、health、dry-run、旧 packet/hash 或 historical receipt 均不构成 mutation 授权，也不能跨会话复用。

## 专项业务边界定位

- 数据、quality、profile、manifest：`docs/DATA_CENTER.md` 与对应 active business contract。
- 回测口径与报告可信度：`docs/BACKTEST_ENGINE.md`。
- SignalEvent、通知与 HTDY exact policy：`docs/SIGNAL_EVENTS.md`、`docs/INDICATOR_KERNEL.md`。
- S6-10 historical/runtime contract：`docs/tasks/JM-LIVE-STABILITY-S6-10.md`。
- 个人开发、普通删除与外部操作边界：`docs/PERSONAL_DEVELOPMENT_WORKFLOW.md`。

## 解释规则

- 文档、单元测试、CI 或 dry-run 通过不等于真实外部操作已经执行或获得授权。
- 单次 historical replay、通知或 health smoke 不等于 long-running、策略盈利或自动交易 Ready。
- 任何真实 mutation 前重新校验当前输入、认证、质量、安全开关及精确 scope；完成、失败、重试、scope 变化或后续会话均需要新的明确请求。
