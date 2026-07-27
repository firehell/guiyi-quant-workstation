# HTDY-FROZEN-DATA-IDENTITY-DRIFT-TRIAGE-R4501A

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | `HTDY-FROZEN-DATA-IDENTITY-DRIFT-TRIAGE-R4501A` |
| Parent Gate | `R45-00 / R45-01` |
| Work Level | `L1 read-only evidence task` |
| Branch | `codex/htdy-frozen-data-identity-drift-triage-r4501a` |
| Worktree | `/private/tmp/guiyi-htdy-frozen-data-identity-drift-triage-r4501a` |
| Base Commit | `b4dfd1083154f61b746bac51328634b20dc13026` |
| Status | `COMPLETED / HTDY_FROZEN_DATA_IDENTITY_DRIFT_ROOT_CAUSE_CONFIRMED` |
| Approval | 用户批准 R45-00/R45-01 只读验收；不含协议、数据或策略写操作 |

## 1. 目标

1. 解释 frozen 旧资产为何缺少 `2026-07-10` 日盘。
2. 核对旧资产生成、manifest/登记、Golden Sample、协议准备与最终冻结的时间线。
3. 判断问题属于物理资产 lineage 漂移，还是冻结契约声明与资产覆盖范围不一致。
4. 保持 R45 Gate 真实状态，不通过修改验收语义制造双 PASS。

## 2. 修改边界

允许新增：

- `docs/tasks/HTDY-FROZEN-DATA-IDENTITY-DRIFT-TRIAGE-R4501A.md`
- `data/reports/htdy_frozen_data_identity_drift_triage_r4501a/`

禁止修改或执行：

- `configs/oos/htdy_strict_validation_protocol_v1.json` 及其 schema/hash 证据；
- `data/raw/`、`data/parquet/`、`data/manifests/`、`data/processed/`；
- PostgreSQL、Profile binding、quality registration；
- X5-03/04/05/06B/07 原始证据、report14、report15、task23；
- 策略回测、OOS、rolling diagnostics、live、通知或订单；
- push、merge、deploy。

## 3. 当前事实与根因

- 旧 raw 与 1m 文件于 `2026-07-10 08:02 +08:00` 生成，当时只覆盖至 `2026-07-09T23:00:00`。
- 旧 15m 文件虽于当日 `15:21 +08:00` 写出，但 `scripts/regenerate_jm_aggregated_bars.sh` 明确从已有 passed 1m 本地聚合且不调用 RQData；其 Parquet `created_at` 仍为 `2026-07-10T00:02:11.050918Z`。
- 旧资产 manifest、物理文件、历史 DB inventory 与 quality snapshot 对 `row_count=19366`、`max_datetime=2026-07-09T23:00:00`、SHA-256、file `55793`、quality report `54552` 一致，未发现物理资产被截断或 hash 漂移。
- protocol prepared commit `f48e8203` 已把旧资产准确 path/hash 与超出其覆盖的 `full_window_end=2026-07-10T15:00:00` 同时写入；final frozen commit `d731083e` 只改变冻结状态/接受元数据，没有修改或重新校验 `frozen_data_policy`。
- 根因是协议准备/最终冻结阶段缺少“声明 full window 必须被绑定资产实际覆盖”的 invariant，不是旧资产 lineage 漂移。

## 4. Gate 结论

```text
HTDY_FROZEN_DATA_IDENTITY_DRIFT_ROOT_CAUSE_CONFIRMED
R45-00 = STAGE45_CLOSEOUT_BASELINE_READY
R45-01 = STRATEGY_VALIDATION_BLOCKED_DATA_IDENTITY_DRIFT
```

本调查 Gate 只表示根因与证据链闭合。它不表示 R45-01 已通过，不授权原地修改 frozen v1。若总体目标仍要求 R45-00/R45-01 双 PASS，须另立新版本协议和依赖证据链任务。

## 5. 验证

- R45 基线单测：`13 passed`。
- old/new SHA-256 与声明值一致。
- R45 baseline/equivalence packet hash 均可复算，重算 equivalence packet 与存档相同。
- 冻结窗口：old `19366`、new `19381`、共同 `19366`；共同 ordered bar hash 均为 `5354608feb3f512da99e21b9e61db26c66121faf82278dd08fcf18bf5a458d46`。
- old/new 重复 datetime 均为 `0`；旧侧没有 new 缺失，new 仅额外包含 `2026-07-10T09:15:00..15:00:00` 的 15 根 bar。
- 最终验收命令和禁止修改面检查记录于调查报告。

## 6. 风险与回滚

- 历史 DB/quality inventory 只证明快照时点，不冒充当前 live DB 查询结果。
- 文件名中的请求结束日期不等于物理 `max_datetime`。
- 回滚仅删除本 TASK 和 `data/reports/htdy_frozen_data_identity_drift_triage_r4501a/`；无数据、协议或数据库回滚。

