# 测试与验证入口

更新时间：2026-07-20

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
  README.md PROJECT_SOURCE.md STATUS.md DECISIONS.md TESTING.md docs --glob '*.md'
```

Stage 6 / Gate 关键词扫描：

```bash
rg -n "DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL|DATA_LAYER_REAUDIT_REQUIRED|D4-00|HTDY|OOS|Stage 6|S6-|JM Data Continuity|T3_REAL|JM_ARCHIVE|LIVE_SIGNAL_EVENT|LIVE_WECOM|JM_RUNTIME_READY|LONG_RUNNING" \
  PROJECT_SOURCE.md STATUS.md DECISIONS.md TESTING.md docs --glob '*.md'
```

敏感信息扫描：

```bash
rg -n -i "password|passwd|token|secret|webhook|api[_-]?key|authorization|cookie" \
  README.md PROJECT_SOURCE.md STATUS.md DECISIONS.md TESTING.md docs/*.md --glob '*.md'
```

说明：上述扫描会命中文档中的安全规则、环境变量名和脱敏说明。验收时需确认没有真实密钥值、真实 webhook URL、账号或 cookie。

## WEB-V1-13 品牌与个人研究操控台

代码与 mock 浏览器矩阵：

```bash
cd apps/quant-web
npm test
npm run build
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5177 npm run test:e2e
```

当前结果：Web `119 passed / 1 skipped`，build passed，mock browser `14 passed`。

后端兼容式只读接口回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_backtest_task_api.py \
  services/quant-api/tests/test_signal_events.py \
  services/quant-api/tests/test_review_center_api.py \
  services/quant-api/tests/test_signal_review_profile_lineage.py
```

当前结果：`41 passed`；覆盖 Dashboard/Signal/Review/Backtest 只读补差、旧数组与新分页兼容、event/source/trade 精确查询和无写入边界。

真实只读 Gate 不使用 `dev-up.sh`，不执行 Alembic，不启动 worker/scheduler。候选 API 必须以 PostgreSQL `PGOPTIONS='-c default_transaction_read_only=on'` 启动，并在运行前确认 `transaction_read_only=on`：

```bash
cd apps/quant-web
PLAYWRIGHT_API_BASE=http://127.0.0.1:8010 \
PLAYWRIGHT_BASE_URL=http://127.0.0.1:5177 \
npm run test:e2e:readonly
```

当前结果：10 项真实 API/浏览器检查通过，网络仅 GET/HEAD/OPTIONS，console error=0。report `15` / trade `3199` / review `9` 真实往返通过；真实库 `event_review_pairs=[]`，所以 SignalEvent 只验收“尚无复盘”降级往返，最终状态为 `WEB_V1_13_PARTIAL`，不得发布 Signal round-trip Ready。

## S6-03 JM 历史追平

代码回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_jm_historical_catchup_execution.py \
  services/quant-api/tests/test_jm_historical_catchup.py \
  services/quant-api/tests/test_live_target_freshness.py \
  services/quant-api/tests/test_market_data_api.py \
  services/quant-api/tests/test_after_market_archive.py \
  services/quant-api/tests/test_actual_contract_bars_pilot.py \
  services/quant-api/tests/test_live_runtime_scheduler.py \
  services/quant-api/tests/test_runtime_health.py
```

当前结果：`75 passed`。真实 apply 后还必须核对 completion receipt、14 行 manifest/checksum、19 个 MarketDataFile、14 个 quality report、18 个 active Profile binding、旧 binding 文件 checksum、consumer latest bar、live target required-date freshness 和重复 apply `already_completed`。

## S6-04 historical/live context

定向回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_live_market_reader.py \
  services/quant-api/tests/test_live_signal_context.py \
  services/quant-api/tests/test_live_signal_evaluator.py \
  services/quant-api/tests/test_signal_review_profile_lineage.py \
  services/quant-api/tests/test_notification_worker.py
```

当前结果：`51 passed`。合并后端全量为 `1089 passed, 3 skipped`；Web tests 为 `76 passed, 1 skipped`，production build passed。该矩阵覆盖冷启动、仅一根 live、重启、exact duplicate、OHLCV conflict、主力切换、historical stale/calendar missing/file drift、confirmed passed trigger 和双来源 lineage；全程只使用临时 SQLite/Parquet，不运行真实 live 或写 canonical 数据。

## S6-05 T3 单次真实 JM live Gate

Provider readiness 与 T3/T4 解阻回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_provider_readiness.py \
  services/quant-api/tests/test_rqdata_client.py \
  services/quant-api/tests/test_jm_historical_catchup.py \
  services/quant-api/tests/test_jm_historical_catchup_execution.py \
  services/quant-api/tests/test_after_market_archive_gate.py \
  services/quant-api/tests/test_after_market_archive_cli.py \
  services/quant-api/tests/test_after_market_archive.py \
  services/quant-api/tests/test_live_t3_gate.py
```

当前结果：`54 passed`；真实 RQData 只读 smoke 验证 `rqdatac 3.5.6.1` 与 pandas 3.0.3 可调用 `is_data_ready`。S6-05 已在 `2026-07-21 / JM2609` 完成两次真实 bounded run，最终 receipt 为 `T3_REAL_PASSED`；该结论来自真实 receipt，不来自代码测试通过数。

代码回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_live_1m_ingest.py \
  services/quant-api/tests/test_live_multi_tf_aggregation.py \
  services/quant-api/tests/test_live_target_freshness.py \
  services/quant-api/tests/test_live_runtime_scheduler.py \
  services/quant-api/tests/test_runtime_health.py \
  services/quant-api/tests/test_trading_session_clock.py \
  services/quant-api/tests/test_live_t3_gate.py
```

当前代码结果：`47 passed`；审计覆盖两次 bounded `--once`、confirmed 1m、六周期 checkpoint、幂等 unchanged、historical/Profile/signal/notification 零增量和命令级开关恢复。真实 evidence 位于 `data/reports/jm_live_t3_s6_05/main_28d667e6_20260720/t3_receipt.json`。

## S6-06 T4 单交易日盘后归档 Gate

代码回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_after_market_archive_gate.py \
  services/quant-api/tests/test_after_market_archive.py \
  services/quant-api/tests/test_jm_historical_catchup_execution.py \
  services/quant-api/tests/test_jm_historical_catchup.py \
  services/quant-api/tests/test_actual_contract_bars_pilot.py \
  services/quant-api/tests/test_live_target_freshness.py
```

当前代码结果：`71 passed`；后端全量为 `1130 passed, 3 skipped`。该矩阵覆盖 bounded preflight 状态、actual-only 版本计划、completed-week-only 1w、精确分钟 key、两次 provider hash 稳定性、Profile candidate/consumer smoke、旧 active 资产 checksum、provider/live 缺失/重复/revision/OHLCV reconciliation、commit 后 receipt 恢复、旧 archive 幂等与失败证据，以及 S6-03 registration/materialization 回归。真实 `JM_ARCHIVE_PASSED` 仍要求已关闭交易日 provider-final 数据、独立 packet hash 批准、Profile apply、consumer smoke、旧资产审计和重复执行。

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

## R45-05 阶段 4/5 最终验收

阶段 4 affected tests 使用本文件的 X4-06 矩阵。阶段 5 与 R45 closeout 回归：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_stage5_acceptance_v2_r4504.py \
  services/quant-api/tests/test_htdy_trusted_candidate_x503.py \
  services/quant-api/tests/test_htdy_oos_validation_x504.py \
  services/quant-api/tests/test_htdy_rolling_oos_x505.py \
  services/quant-api/tests/test_htdy_strategy_review_x506b.py \
  services/quant-api/tests/test_htdy_stage5_acceptance_x507.py \
  services/quant-api/tests/test_htdy_frozen_data_completion_r4501b.py \
  services/quant-api/tests/test_htdy_sample_end_audit_r4502.py \
  services/quant-api/tests/test_htdy_rolling_decision_r4503.py
```

Review exact-bars / trust audit 与 Web Review/Market：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_strategy_review_x506b.py \
  services/quant-api/tests/test_review_foundation_c506a.py \
  services/quant-api/tests/test_review_center_api.py \
  services/quant-api/tests/test_backtest_trust_audit.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

正式验收还必须用 PostgreSQL `REPEATABLE READ READ ONLY` 前后快照复核 report 14、report 15 / task 23、active binding 和绑定 Parquet 实体 SHA256，并对全部 X5/R45 packet、protocol、parameters 和策略 source 做执行前后哈希对账。通过证据固定在 `data/reports/stage45_final_acceptance_r4505/`。

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

阶段 5 candidate 只读 trust audit 使用同一命令的 `--report-id 15`；两个报告都通过只代表报告事实可信，不代表候选盈利或可实盘。

## Gate 说明

- 文档验证通过不等于代码测试通过。
- 单元测试通过不等于真实运行 Gate 通过。
- Stage 9-B2 historical replay single-send smoke 不等于 live-confirmed smoke。
- `report_id=14` trust audit passed 不等于策略盈利、稳定或可实盘。
- `REJECTED_RESEARCH_CANDIDATE` 是阶段 5 验证管道的合法终态，不等于工程失败，也不允许自动调参或重跑翻转。
- `DATA-PART-TARGET-CLOSURE DELIVERY_READY` 不等于 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
- C2-05 final Gate 的可复查证据固定在 `data/reports/consumer_golden_query_final_gate_20260718_rerun/`：12/12 Golden Query 样本、49 条消费者矩阵、13/13 hard gate、direct PostgreSQL read-only snapshot；其报告中的 `174 passed / 0 failed / 0 skipped` 与 Web `59 passed / 0 failed / 1 existing optional skip` 是该 Gate 的测试记录。该证据不替代 live runtime、真实通知或长稳验证。
- `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 是 strict formal consumer Gate；`DATA_LAYER_REAUDIT_REQUIRED` 是全历史 residual 维护 backlog。两者可并存，且都不替代 OOS、T3/T4、live signal、企业微信或长稳 Gate。
- D4-00 证据落盘不等于 `HTDY_XMA_SEMANTICS_AUDITED`；仓库最终 Gate 为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。`CURSOR_CANONICAL_SYNC_PREPARED` 只表示历史文档入口曾对齐，不宣布指标契约、策略管道或 JM live Ready。
- Stage 6 当前下一入口为 `S6-06` T4；`T3_REAL_PASSED` 已有真实 receipt，`JM_ARCHIVE_PASSED` 仍必须由已关闭交易日的独立审批和真实 archive receipt 证明。

## 工程入口验证

正式工程 Gate 使用固定 profiles 与 Makefile 目标：

```bash
# profiles（scripts/engineering/test.sh；禁止自由 shell 字符串）
bash scripts/engineering/test.sh engineering
bash scripts/engineering/test.sh docs
bash scripts/engineering/test.sh backend-health
bash scripts/engineering/test.sh all-safe

# Makefile
make engineering-preflight
make engineering-test                              # 默认 ENGINEERING_TEST_PROFILE=engineering
make engineering-test ENGINEERING_TEST_PROFILE=docs
make engineering-test ENGINEERING_TEST_PROFILE=backend-health
make engineering-test ENGINEERING_TEST_PROFILE=all-safe
make engineering-secrets
make engineering-ci                                # preflight --ci + engineering + fail-closed secrets

# 等价显式调用
bash scripts/engineering/preflight.sh
bash scripts/engineering/preflight.sh --ci
bash scripts/engineering/check-secrets.sh
bash scripts/engineering/runtime-health.sh --json
git diff --check
```

Runtime/Web 部署修复的定向回归：

```bash
PYTHONPATH="$PWD/services/quant-api:$PWD/packages/quant-core" \
  uv run --project services/quant-api pytest -q \
  tests/engineering/test_after_market_service_scripts.py \
  tests/engineering/test_engineering_entrypoints.py \
  services/quant-api/tests/test_jm_eod_automation_gate_cli.py \
  services/quant-api/tests/test_after_market_scheduler.py \
  services/quant-api/tests/test_runtime_health.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

Web production build 会自动执行 `checkProductionBundleTopology.mjs`，阻断 ECharts/ZRender vendor chunks 的静态循环依赖。服务 runner 测试同时约束 launchd 直接监管 Runtime venv Python，并验证解释器缺失时 fail-closed。

S6-08 live-confirmed SignalEvent Gate 定向回归（不执行真实 T5）：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests -k "live_signal_event or live_signal or signal_event or stage9"

uv run --project services/quant-api pytest -q \
  tests/engineering/test_live_signal_event_service_scripts.py
```

CI workflow：`.github/workflows/engineering-test.yml`。已删除：`make workstation-doctor` / `make workstation-test`、通用 `production-write-check.sh`。

验收口径：

- 旧多入口控制面脚本已退出 active tree，不得作为正式架构入口。
- 工程验证唯一入口：`scripts/engineering/*` 与 `tests/engineering`。
- `test.sh` 仅接受固定 profile（`engineering` / `docs` / `backend-health` / `all-safe`）；其它套件由 Codex 直接跑 pytest/npm。
- `check-secrets.sh` 默认 fail-closed；`--warn-only` 仅本地排障，CI 禁用。
- 高风险真实写入必须使用业务专用、hash-bound、scope-bound approval packet / Gate；没有专用 Gate 就禁止真实写入，先独立设计 Gate。Issue 中用户批准是决策记录，但不能替代代码层 hash 校验。
