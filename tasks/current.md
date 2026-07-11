# 当前任务：TASK-2026-07-11-001-data-asset-audit

生成时间：2026-07-11

任务单：`docs/tasks/TASK-2026-07-11-001-data-asset-audit.md`

分支：`codex/data-asset-audit`

Worktree：`/Volumes/扩展盘/guiyi-parallel/data-audit`

状态：`DELIVERY_READY_WITH_CLI_ENV_NOTE`

## 目标

在不写 DB、Parquet、RQData、不修复 pending、不修改 `services/` 业务逻辑的前提下，完成 Stage 8.6 现有 active 资产只读快照，并输出独立报告目录：

```text
data/reports/data_audit_20260711/
```

本任务是全量历史数据资产盘点的第一阶段基线，不代表目标年份、目标周期和参考元数据覆盖已经完成。

## 执行结果

- 已尝试按计划运行 `scripts/rqdata_full_universe_active_gate_audit.py --profile stage8_6_1d_first`。
- 直接 CLI 在本 worktree 被 DB 环境 Gate 阻塞：根目录无 `.env` / `DATABASE_URL`，默认无密码连接 PostgreSQL 失败。
- 未读取 `.env`，未提取或打印任何 DB/RQData/Webhook 凭据。
- 改用本机已运行 API 的只读数据中心接口读取 DB metadata snapshot：
  - `/api/v1/data/coverage`
  - `/api/v1/data/quality-reports`
- manifest 与 canonical parquet 仍按当前 worktree 文件和 DuckDB 读取核对。

## 当前盘点结论

- 全品种产品层：82 `active_passed` / 8 `active_partial`。
- 当前 snapshot manifest-level discovered active records：1326 `active_passed` / 8 `audit_pending`。
- JM 最新主连六周期：6/6 `active_passed`。
- Stage 9：90 `stage9_blocked`；本任务不授权企业微信发送。

## 1326 口径

- 当前矩阵共 1334 行。
- 唯一键限定为 `product + asset_scope + contract + period + standard_path`。
- `actual_contract` 1244 行，其中 1241 passed / 3 pending。
- `dominant_main` 90 行，其中 85 passed / 5 pending。
- 当前 snapshot 全部为 `1d`，不是多周期全量覆盖。
- provider 从路径推断均为 `rqdata`。
- DuckDB row count 和 datetime boundary 已核对；checksum 未在本报告中逐文件独立证明。
- 1326 passed 记录均有 DB 登记；3 个 pending 缺 `market_data_files`；5 个 pending 是 quality warning。

## 8 个 pending

- `bb/rs/wh/wr/zc`：主连 `1d` 为 `quality warning`，阻塞原因为 abnormal price，需要另开只读根因审查，不能本轮升级为 passed。
- `L2609F/PP2609F/V2609F`：actual-contract `1d` manifest/parquet/DuckDB 可读，但缺 `market_data_files` 登记，需要另开受控登记任务。
- 这 8 个 pending 不是当前唯一可能缺口；它们只是当前 `stage8_6_1d_first` profile 发现的问题。下一步先做目标覆盖矩阵，不直接进入修复。

## 产物

- `data/reports/data_audit_20260711/DATA_ASSET_INVENTORY.md`
- `data/reports/data_audit_20260711/stage8_6_active_gate_matrix.csv`
- `data/reports/data_audit_20260711/stage8_6_product_summary.csv`
- `data/reports/data_audit_20260711/stage8_6_stage9_readiness.csv`
- `data/reports/data_audit_20260711/stage8_6_active_gate_summary.md`
- `data/reports/data_audit_20260711/jm_main_six_period_latest/stage8_6_active_gate_matrix.csv`
- `data/reports/data_audit_20260711/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
- `.ai/results/TASK-2026-07-11-001-data-asset-audit/RESULT.md`

## 硬边界

- 未写 DB、Parquet、manifest、checksum 或 RQData。
- 未修改 `services/`、`apps/`、`packages/`、Alembic 或策略/回测逻辑。
- 未启动 live runtime、scheduler、信号扫描或企业微信发送。
- 未读取或写入 `.env`。

## 验收证据

```bash
uv run --project services/quant-api python scripts/rqdata_full_universe_active_gate_audit.py --products-file data/universe/full_products_90.txt --profile stage8_6_1d_first --output-dir data/reports/data_audit_20260711
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest services/quant-api/tests/test_full_universe_active_gate.py -q
git diff --check
git status --short
```

第一条 direct CLI 因本 worktree 缺 DB 认证环境失败；报告采用 API snapshot fallback。测试和 diff check 结果见最终交付总结。

## 下一阶段

合并当前分支后，从最新 `main` 新建 `codex/data-target-coverage-audit`，进入 Plan 模式完成完整覆盖矩阵设计。

预期只读输出：

- `target_asset_catalog.csv`
- `asset_physical_inventory.csv`
- `target_coverage_matrix.csv`
- `metadata_consistency_matrix.csv`
- `issue_register.csv`
- `coverage_summary.md`

矩阵粒度固定为 `product × contract_role × symbol/contract × period × year × status`。

## GPT 同步清单

- `tasks/current.md`
- `docs/tasks/TASK-2026-07-11-001-data-asset-audit.md`
- `docs/gpt/CURRENT_STATE.md`
- `data/reports/data_audit_20260711/DATA_ASSET_INVENTORY.md`
- `data/reports/data_audit_20260711/stage8_6_active_gate_summary.md`
- `data/reports/data_audit_20260711/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
