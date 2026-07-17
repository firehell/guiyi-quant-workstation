# FULL-HISTORY-RESIDUAL-REPAIR-004B

生成时间：2026-07-17

状态：`COMPLETED / FULL_HISTORY_RESIDUAL_REPAIR_004B`

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
local_data_rebuild=EXECUTED_VERIFIED_252_OF_252
rqdata=EXECUTED_VERIFIED_479_OF_479
profile_binding_changed=false
final_physical_inventory=FULL_HISTORY_PHYSICAL_INVENTORY_READY
final_checksum_mismatch_rows=0
final_checksum_declared_conflict_rows=0
final_missing_physical_rows=0
final_path_drift_rows=0
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

## Closure 004B dry-run（2026-07-17）

对剩余项重新做 direct PostgreSQL、full-checksum inventory 和冻结队列交叉验证后，当前独立修复范围为：

```text
db-stale-retirement-002: 389 MarketDataFile + 389 DataQualityReport
  - 385 条 stale registration 均有同路径 actual-checksum replacement
  - 4 条缺失物理文件的 JM 实验 candidate 无 Profile binding
local-rebuild-tf-002: 1 个原子单元，生成 TF 1m prerequisite + 5m/15m/30m/60m candidate
rqdata-missing-actual-002: 71 actions
  - 36 份 raw 已验证可复用
  - 35 条才需要调用 RQData
```

TF 原 8 条 abnormal price 均为约 `1.42e-14` 的二进制浮点误差。统一 OHLC Gate 现在使用相对/绝对 `1e-12` 容差；真实越界仍失败。旧 warning 和旧 Parquet 不改写，新 1m prerequisite 与四个派生周期均使用新 candidate data version，且不切换 Profile。

RQData 阻断根因是 manifest 文件名不包含 period：既有 manifest 保存其他周期，而目标周期不存在。closure writer 只允许 `validate_reuse` raw 和 `merge_existing` manifest；合并前验证 schema/identity、保存 before hash/backup，并使用临时文件原子替换。

不可变 dry-run 位于：

```text
data/reports/full_history_residual_repair_20260710/closure_004b/
```

当前尚未执行三个 closure 生产批次，必须分别取得该目录中记录的精确 ledger 批准。批准前仍保持 `PARTIAL`。

执行更新：`db-stale-retirement-002` 与 `local-rebuild-tf-002` 已按批准 ledger 完成并验证。`rqdata-missing-actual-002` 在首条复用 raw 的 hard OHLC Gate fail-closed，未产生 DB、canonical、raw 或 manifest 变化。全量复核发现 36 份旧 raw 中仅 4 份 passed，32 份存在真实的 provider settlement-close/OHLC envelope 冲突；原 dry-run 的“36 份可复用”判断不完整。

修订批次 `rqdata-missing-actual-003` 获得精确批准后执行，但 RQData direct daily 仍返回相同的 settlement-close/OHLC envelope 冲突，首条 action 再次被 hard quality Gate 阻断。raw、canonical、manifest 和 DB 均已核验回滚到 before 状态，生产变化为 0。

根因复核确认：受影响合约的 RQData 1m 端点可重建合法日线，不能通过放宽 OHLC Gate 接受 direct daily 冲突。代码现已支持单独的 `periods=("1d",), local_daily=true`，从新建 1m raw 聚合 1d；32/32 个受影响区间均完成只读内存预检并通过质量 Gate。

新批次 `rqdata-missing-actual-004` 已冻结：4 份 passed daily raw 复用、32 份新 1m raw 本地重建日线、35 份正常 direct daily 下载，共 71 个目标和 67 次 RQData 调用。它不覆盖旧 raw、不切换 Profile，等待新的精确 ledger 批准。

`rqdata-missing-actual-004` 随后获得精确批准并完成 71/71：71 个 canonical candidate、71 条 passed quality report、67 份新 raw，4 份 passed raw 复用。第一次执行在首条 action 已 commit 后组装 ledger 时暴露缺失 `data_version` 字段；该 action 的 2 条 file registration、1 条 quality report、1 条 download task、raw、canonical 和 manifest 均按 before evidence 精确回滚。修复后证据组装移入 commit 前事务边界，完整重跑成功。

最终 full-checksum inventory 使用 direct PostgreSQL，27,837 行全部 `matched + readable + schema_ok`，checksum mismatch、declared conflict、missing physical、path drift 均为 0。90 品种 Audit V2 输出 720/720 physical covered、720/720 registered、720/720 reference metadata passed，`gap_count=0`。质量层保留 693 passed 与 27 warning，没有把 warning 升级为 passed。B2-04B 至此符合验收；`DATA_LAYER_REAUDIT_REQUIRED` 仍作为更高层数据 Gate 状态保留，本任务不擅自宣布 data layer final ready。
