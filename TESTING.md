# 测试与验证入口

只记录当前可运行的命令。历史通过数量和一次性 Gate 结果以相应 receipt、报告与 Git 提交为准。

## 快速检查

```bash
git diff --check
bash scripts/engineering/check-secrets.sh
bash scripts/engineering/test.sh engineering
bash scripts/engineering/test.sh docs
```

`preflight.sh` 适用于新会话、高风险任务或环境诊断；它不是每个普通改动的业务 Gate。

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

`guiyi data migrate inventory/plan` 为零写入命令；plan 必须同时显式传入 task worktree
`--project-root`、旧资产 `--legacy-root`、新 `--canonical-root/--staging-root` 与 exact window。
worktree 不 clean 时只返回 `task_worktree_not_clean`，不生成 approval packet。

### Task 05 derived/reference inventory

下列 CLI 只输出稳定 JSON；不加载 RQData、不含 delete/apply/repair mode。真实 DB 只允许通过
显式 `--database-url-env NAME` 外部只读 Gate 注入，绝不输出 URL；PostgreSQL 精确使用
`BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`。`--max-files` 同时限制目录、文件、匹配和
输出记录；`--max-file-bytes`、`--max-total-bytes` 与 `--max-ids` 均有安全默认值。任何预算、
symlink、非 UTF-8、TOCTOU、缺表/缺列或读取错误都会返回 incomplete diagnostics，绝不把截断
或猜测结果当作完整 inventory。`market_data_files` 逐行只在 provider/role/quality/period 与
Catalog partition 的 path、manifest、checksum linkage 均可验证时标为 KEEP；derived 为
REBUILD_ONLY，raw/standard/canonical 而无 linkage 一律 REVIEW_REQUIRED。

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_derived_reference_inventory.py

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/derived_reference_inventory.py \
  --repo-root /path/to/fixture-repo --data-root /path/to/fixture-data
```

真实 PostgreSQL/data root 只读盘点是 external Gate；它不授权重建、迁移、删除、Runtime、通知或交易。

生产 migration、真实 RQData/Parquet/PostgreSQL apply 与创建/删除隔离 PostgreSQL 数据库
都需要精确授权。Task 04 的专用临时库已在用户授权后完成测试并删除；这不授权生产 apply，
也不得用未设置 isolated URL 时的 skipped 用例冒充 upgrade/downgrade/upgrade 通过。

## 数据、回测与运行时只读验证

```bash
bash scripts/engineering/runtime-health.sh --json

PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown
```

真实数据、RQData、PostgreSQL、Runtime 或企业微信操作只能使用对应任务合同与专项 Gate；通用测试、health 或 receipt 文件存在均不构成授权。

## 专项 Gate 定位

- 数据、quality、profile、manifest：`docs/DATA_CENTER.md` 与对应受控任务/receipt。
- 回测口径与报告可信度：`docs/BACKTEST_ENGINE.md`。
- SignalEvent、通知与 HTDY exact policy：`docs/SIGNAL_EVENTS.md`、`docs/INDICATOR_KERNEL.md`。
- S6-10：`docs/tasks/JM-LIVE-STABILITY-S6-10.md`。
- worktree/release：`docs/WORKTREE_RELEASE_WORKFLOW.md` 与现行 ADR。

## 解释规则

- 文档或单元测试通过不等于真实外部 Gate 通过。
- 单次 historical replay、通知或 health smoke 不等于 long-running、策略盈利或自动交易 Ready。
- 任何真实写入前必须重新核对 commit、数据/Runtime 身份、packet/hash、scope 与 receipt。
