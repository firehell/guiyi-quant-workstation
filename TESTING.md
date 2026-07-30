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

下游尚未迁移，其 Profile/lineage 合同仍须回归：

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
