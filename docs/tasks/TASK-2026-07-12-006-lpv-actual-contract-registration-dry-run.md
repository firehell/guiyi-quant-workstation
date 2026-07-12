# TASK-2026-07-12-006：LPV Actual Contract Registration Dry-run

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-12-006-lpv-actual-contract-registration-dry-run |
| Work Level | L1 |
| GitHub Issue | 不创建 |
| Branch | codex/lpv-actual-contract-registration-dry-run |
| Worktree | /Volumes/扩展盘/guiyi-parallel/lpv-actual-contract-registration-dry-run |
| Status | REQUIREMENT_READY |
| Created At | 2026-07-12 |
| Base Checkpoint | de9ef54d |

## 1. 目标

1. 对已有 `missing_db_registration` 108 个 target rows 做只读 dry-run reconcile。
2. 按 `standard_path` 去重后逐文件核对 Parquet、manifest、DuckDB 与 PostgreSQL metadata。
3. 修正 actual-contract manifest 文件名中 `l_f/pp_f/v_f` 被错误解析为 `l/pp/v` 的审计误报。
4. 重跑 target coverage audit，根据证据决定是否存在真实 DB 登记候选。

## 2. 已知基线

- 108 target rows 对应 93 个唯一 Parquet 文件。
- 93 个文件均存在，93 个 manifest rows 均有 `market_data_file_id`。
- live DB 对 93 个精确 `file_path` 均有登记，共返回 99 行。
- `L2609F` 六周期各有两个不同 `data_version` 指向同一物理路径，本任务只报告，不删除、不归档、不修改。

## 3. 允许修改

- `services/quant-api/app/services/rqdata_ingest/actual_contract_registration_reconcile.py`
- `scripts/rqdata_actual_contract_registration_reconcile.py`
- `services/quant-api/tests/test_actual_contract_registration_reconcile.py`
- `services/quant-api/app/services/rqdata_ingest/target_coverage_audit.py`
- `services/quant-api/tests/test_target_coverage_audit.py`
- `data/reports/lpv_actual_contract_registration_dry_run_20260712/`
- `data/reports/target_coverage_audit_20260712_after_lpv_reconcile/`
- 本任务文档、`tasks/current.md`、`docs/DATA_CENTER.md`、`docs/gpt/CURRENT_STATE.md`

## 4. 禁止修改

- 不写 PostgreSQL；不提供 apply flag。
- 不写 raw / processed / canonical Parquet。
- 不修改 manifest、checksum、`data_version`、`data_role`、`quality_status`。
- 不调用 RQData，不新增 Alembic migration 或 schema。
- 不删除或合并六条同路径多版本 DB 记录。
- 不修改策略、回测、信号、live runtime、scheduler、企业微信或交易执行。

## 5. 实现要求

- dry-run 输入为 `data/reports/target_coverage_gap_triage_20260711/missing_db_registration_candidates.csv`。
- 按 `standard_path` 去重，保留 target row count 和 covered years。
- 逐文件核对：file exists、DuckDB row_count/min/max、manifest row/checksum/data_version/primary/passed、DB exact path 及唯一键冲突。
- 分类固定为 `already_registered`、`eligible_for_registration`、`duplicate_path_versions`、`blocked_metadata_mismatch`。
- 输出 `registration_reconcile_ledger.csv` 和 `LPV_ACTUAL_CONTRACT_REGISTRATION_DRY_RUN.md`。
- 输出必须显式声明 `writes_database=False`、`writes_parquet=False`、`calls_rqdata=False`。
- actual-contract manifest 产品以行内 `product` 为主，仅在缺失时才从文件名可靠解析。

## 6. 人工 Gate

- 预期 `eligible_for_registration=0`：不做 DB 写入，任务以 dry-run 关闭。
- 如出现真实 eligible assets：只输出候选清单并暂停，等待用户显式授权新的受控 DB 登记步骤。

## 7. 测试

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_actual_contract_registration_reconcile.py \
  services/quant-api/tests/test_target_coverage_audit.py

uv run --project services/quant-api ruff check \
  services/quant-api/app/services/rqdata_ingest/actual_contract_registration_reconcile.py \
  services/quant-api/app/services/rqdata_ingest/target_coverage_audit.py \
  scripts/rqdata_actual_contract_registration_reconcile.py \
  services/quant-api/tests/test_actual_contract_registration_reconcile.py \
  services/quant-api/tests/test_target_coverage_audit.py

python -m py_compile \
  services/quant-api/app/services/rqdata_ingest/actual_contract_registration_reconcile.py \
  scripts/rqdata_actual_contract_registration_reconcile.py

git diff --check
```

## 8. 验收标准

- 108 target rows 正确去重为 93 个物理文件。
- dry-run 前后 `market_data_files` 和 `data_quality_reports` 行数不变。
- 93 个文件全部有明确分类，预期 `eligible_for_registration=0`。
- 6 个同路径多版本资产单独报告，不触发新增登记。
- 重跑审计后不再报告这 108 条 `missing_db_registration`。
- 报告不包含 DB/RQData/Webhook 凭据。
