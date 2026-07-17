# FULL-HISTORY-RESIDUAL-REPAIR-004B

生成时间：2026-07-17

状态：`PARTIAL / APPROVED_BATCHES_EXECUTED_AND_VERIFIED`

## 目标与冻结输入

本任务只接受 B2-04A 的四个冻结队列，不允许自行扩大目标。队列 SHA-256 固定为：

```text
code_fix_queue.csv=7a2ce118c94ec560d0542a8b89025531ddecb0dbd9bca556e0d6aa198e557e8e
metadata_repair_queue.csv=672dcfee33fa7151688157fab30694a0cbd3dafca727d7fdf9cf9491c1876f15
local_data_rebuild_queue.csv=57c1bea01a425fd2acbe1e146ce848d24ae2b94d64542ce3365cc5f1ac29de6e
rqdata_download_candidate_queue.csv=38b0370013f2085843bcede306e8fa58ad6c2246be50a14bc781af8ddc9daf98
```

代码 Gate 通过后，用户已按精确 ledger SHA-256 批准 5 个 metadata 批次、1 个 local rebuild 批次和 1 个 RQData 批次。本记录反映已执行的生产写入；Profile binding 始终未切换。

## 批准批次执行结果

```text
metadata-manifest-checksum-001: 1377 / 1377 manifest rows updated and verified
metadata-processed-summary-001: 23 / 23 verified no-op; original failed evaluator provenance preserved
metadata-registration-reconcile-001: 2467 verified no-op; 4 manual_review_checksum_not_registered
metadata-registration-missing-001: 18 MarketDataFile + 18 DataQualityReport inserted; 17 manifest rows
metadata-trading-calendar-001: 39984 rows inserted for 6 exchanges x 6664 RQData trading dates
local-rebuild-derived-001: 248 / 252 candidate assets rebuilt and verified; tf 4 blocked by warning source
rqdata-missing-actual-001: 408 / 479 candidate assets downloaded and verified; 71 blocked because output existed
profile_binding_changed=false
```

metadata DB 写入使用事务；trading calendar 首次超过 PostgreSQL parameter limit 的尝试已整批 rollback，后续在同一事务内分块插入成功。local rebuild 仅从 direct DB `passed` 的 1m source 生成新 data version；`tf` 因唯一全历史 source 为 `warning` 而 fail-closed。RQData 预检证明 71 条目标路径已存在，因此未覆盖、未重下。

## 已实施代码修复

1. actual rank=1 目标按 `product + period` 的 direct supported start 裁剪；裁剪后为空的区间不生成目标。
2. actual rank=1 相同目标在裁剪后稳定去重。
3. 静态 `trading_sessions` 不再作为全历史逐年 reference metadata 要求；Audit V2 输出 `not_applicable`，不生成 `trading_session_gap`。
4. physical inventory 分开输出 DB、manifest、processed summary 的 quality evidence；Audit V2 Gate 优先 direct DB，仍保留 processed summary 的原始失败证据，不把 warning 升级为 passed。

## 受控队列框架

`full_history_residual_repair.py` 和薄 CLI 提供：

- 固定 schema、SHA-256 和 action type allowlist 校验；
- 显式 action ID 选择，空选择不代表全量；
- deterministic ledger SHA-256；
- 精确匹配 task、batch、queue、ledger、action IDs 和 approval statement；
- RQData 独立 `rqdata_allowed=true` Gate；
- dry-run 输出不覆盖已存在目录；
- 报告明确 `writes_database=false`、`writes_parquet=false`、`writes_manifest=false`、`calls_rqdata=false`。

CLI 只开放 `plan` 和 `verify-approval`，没有无边界的通用 apply 子命令。本轮真实写入仅通过已冻结 selected actions 与用户给出的精确 ledger 批准执行。

## 队列边界

```text
code actions=3
metadata actions=3979
local rebuild actions=252
rqdata candidates=479
```

processed summary 的 23 条 `quality.status=failed` 是原始 evaluator 证据；direct DB 当前 warning 记录包含原状态 provenance，因此不得机械改写为 warning。后续 metadata batch 必须逐条验证其 action 是否仍适用。

## 写入批准语义

每个 dry-run plan 会生成唯一语句：

```text
APPROVE FULL-HISTORY-RESIDUAL-REPAIR-004B <batch_id> <ledger_sha256>
```

RQData 批次使用：

```text
APPROVE RQDATA FULL-HISTORY-RESIDUAL-REPAIR-004B <batch_id> <ledger_sha256>
```

批准只覆盖 ledger 中列出的 action IDs；不授权其他队列、其他行或 Profile binding 切换。

## 当前 Gate

```text
code_fix=IMPLEMENTED_TESTED
metadata_repair=EXECUTED_VERIFIED
local_data_rebuild=VERIFIED_PARTIAL_248_OF_252
rqdata=VERIFIED_PARTIAL_408_OF_479
profile_binding_changed=false
final_physical_inventory=FULL_HISTORY_PHYSICAL_INVENTORY_READY
final_audit_v2=FULL_HISTORY_AUDIT_V2_READY
final_audit_v2_gap_count=0
data_gate_status=DATA_LAYER_REAUDIT_REQUIRED
```

## 验证证据

```text
pytest targeted and related regression: 82 passed
ruff changed Python files: passed
git diff --check: passed
frozen queue verification: 3 / 3979 / 252 / 479 actions, all hashes matched
direct PostgreSQL four-product Audit V2 smoke: FULL_HISTORY_AUDIT_V2_SMOKE_READY
direct PostgreSQL 90-product Audit V2 rerun: FULL_HISTORY_AUDIT_V2_READY
actual_rank1_rows=9927
pre_supported_start_violations=0
duplicate_actual_targets=0
trading_session_rows=90, all not_applicable
trading_session_gaps=0
code residual delta: supported-boundary 483->0; duplicate-target 140->0; static-session-gap 90->0
data_gate_status=DATA_LAYER_REAUDIT_REQUIRED
```

第一次实际 smoke 因主工程下指定 inventory 目录不存在而 `AUDIT_V2_BLOCKED_INVENTORY`；第二次在未加载 project `.env` 时因无密码认证而 `ENV_BLOCKED_DB`。两次均 fail-closed。随后仅在进程内加载所选 Mac mini 项目配置（未读取或打印敏感值），使用实际 inventory 路径和 direct PostgreSQL 成功完成只读 smoke。

最终 quick 与 full-checksum physical inventory 均返回 `FULL_HISTORY_PHYSICAL_INVENTORY_READY`，direct PostgreSQL Audit V2 返回 `FULL_HISTORY_AUDIT_V2_READY` 且 `gap_count=0`。但 full-checksum inventory 仍报告 382 条 DB declared checksum mismatch、7 条 declared conflict、4 条 DB-only missing physical/path drift；它们不在本轮已批准 ledger 内，本任务未自行扩大写入。因此整体状态是 `PARTIAL`，不声明数据层 final ready。
