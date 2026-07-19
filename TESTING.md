# 测试与验证入口

更新时间：2026-07-19

## 文档任务必跑

```bash
git status --short --branch
git diff --check
git diff --stat
git diff --name-only
```

状态词扫描：

```bash
rg -n "2020|2023|82/90|8 partial|metadata_gap|READY|PARTIAL|PENDING|阿里云|腾讯云|JM2609|report_id=14|Stage 9|五个交易日" \
  README.md PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md docs tasks --glob '*.md'
```

下一轮 canonical 同步 Gate（含 D4-00 / Cursor Wave 关键词）：

```bash
rg -n "DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL|DATA_LAYER_REAUDIT_REQUIRED|D4-00|HTDY|OOS|T3_REAL|JM_RUNTIME_READY" \
  PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md tasks/current.md docs --glob '*.md'
```

敏感信息扫描：

```bash
rg -n -i "password|passwd|token|secret|webhook|api[_-]?key|authorization|cookie" \
  README.md PROJECT_SOURCE.md STATUS.md DECISIONS.md CODEX_TASKS.md TESTING.md docs/gpt docs/*.md tasks --glob '*.md'
```

说明：上述扫描会命中文档中的安全规则、环境变量名和脱敏说明。验收时需确认没有真实密钥值、真实 webhook URL、账号或 cookie。

## X4-06 指标契约验收

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1b_diff.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_strategy_indicator_policy_c404.py \
  services/quant-api/tests/test_htdy_strict_core.py \
  services/quant-api/tests/test_tdx_xma_indicator_risk.py \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py \
  services/quant-api/tests/test_backtest_profile_contract.py \
  services/quant-api/tests/test_htdy_validation_protocol_c501.py \
  services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py

cd apps/quant-web && npm run test:indicators
```

该组测试只使用临时 Parquet 与内存 SQLite；不写 canonical DB、Parquet、Profile binding、正式报告、OOS 或 live。

## 后端常用验证

V1 全历史数据契约：

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_full_history_contract.py \
  services/quant-api/tests/test_target_coverage_audit.py \
  services/quant-api/tests/test_data_layer_final_audit.py \
  services/quant-api/tests/test_schema_contract.py
```

该命令只运行纯契约与 legacy 回归测试，不需要 RQData 凭据或真实 PostgreSQL。

Audit V2 定向与回归：

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_full_history_contract.py \
  services/quant-api/tests/test_full_history_reference_metadata.py \
  services/quant-api/tests/test_full_history_audit_v2.py \
  services/quant-api/tests/test_full_history_physical_inventory.py \
  services/quant-api/tests/test_target_coverage_audit.py \
  services/quant-api/tests/test_data_layer_final_audit.py \
  services/quant-api/tests/test_schema_contract.py \
  services/quant-api/tests/test_multi_primary_rulebook.py
```

正式 CLI 只读运行需要 direct PostgreSQL；`--product` 过滤只能产生 smoke 状态，正式输出不得覆盖已有 V2 文件：

```bash
uv run --project services/quant-api python scripts/rqdata_full_history_audit_v2.py \
  --project-root /Volumes/扩展盘/guiyi-quant-workstation \
  --inventory-dir data/reports/full_history_audit_v2_20260710 \
  --audit-end 2026-07-10 \
  --output-dir data/reports/full_history_audit_v2_20260710
```

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q services/quant-api/tests
```

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app services/quant-api/tests scripts packages/quant-core/guiyi_quant
```

Alembic：

```bash
cd services/quant-api
uv run python -m alembic current
uv run python -m alembic heads
```

## 前端常用验证

```bash
for f in apps/quant-web/tests/*.test.ts; do node --test "$f" || exit 1; done
npm --prefix apps/quant-web run build
```

## 数据与回测只读验证

数据层 final audit 只读运行示例：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --project-root /Volumes/扩展盘/guiyi-quant-workstation \
  --output-dir data/reports/data_layer_final_audit_manual
```

回测 trust audit：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/backtest_trust_audit.py \
  --report-id 14 --format markdown
```

## Gate 说明

- 文档验证通过不等于代码测试通过。
- 单元测试通过不等于真实运行 Gate 通过。
- Stage 9-B2 historical replay single-send smoke 不等于 live-confirmed smoke。
- `report_id=14` trust audit passed 不等于策略盈利、稳定或可实盘。
- `DATA-PART-TARGET-CLOSURE DELIVERY_READY` 不等于 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
- C2-05 final Gate 的可复查证据固定在 `data/reports/consumer_golden_query_final_gate_20260718_rerun/`：12/12 Golden Query 样本、49 条消费者矩阵、13/13 hard gate、direct PostgreSQL read-only snapshot；其报告中的 `174 passed / 0 failed / 0 skipped` 与 Web `59 passed / 0 failed / 1 existing optional skip` 是该 Gate 的测试记录。该证据不替代 live runtime、真实通知或长稳验证。
- `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 是 strict formal consumer Gate；`DATA_LAYER_REAUDIT_REQUIRED` 是全历史 residual 维护 backlog。两者可并存，且都不替代 OOS、T3/T4、live signal、企业微信或长稳 Gate。
- D4-00 证据落盘不等于 `HTDY_XMA_SEMANTICS_AUDITED`；仓库最终 Gate 为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。`CURSOR_CANONICAL_SYNC_PREPARED` 只表示 Cursor Wave 文档入口已对齐，不宣布指标契约、策略管道或 JM live Ready。

## WorkBuddy V3 工作站验证

Demo 前至少运行：

```bash
bash -n scripts/ai/*.sh
python3 -m pytest -q tests/workstation
make workstation-doctor
git diff --check
git ls-files '.ai/**'
git ls-files '.workbuddy/**'
```

文档卫生检查：

```bash
git grep -n "CodeBuddy" -- ':!docs/workstation/archive/**' ':!docs/tasks/archive/**' ':!data/**' ':!.ai/**' ':!.workbuddy/**'
git grep -n "V1.1主流程\\|workstation/team\\|scripts/ai/.out\\|.workbuddy/memory" -- ':!docs/workstation/archive/**' ':!docs/tasks/archive/**' ':!data/**' ':!.ai/**' ':!.workbuddy/**'
```

验收口径：

- `CodeBuddy` 只能作为 compatibility-only、历史 archive、旧任务只读回退或标签兼容出现。
- `.ai/results/` 是 local-first 证据路径，可以被脚本和文档引用，但运行产物不得被 Git 追踪。
- `.workbuddy/memory/` 只能作为 gitignore / inventory / document map 等非状态源说明出现，不得成为 active contract。
- `WORKBUDDY_V3_CODE_COMPLETE_DEMO_PENDING` 不等于 `FROZEN`。
