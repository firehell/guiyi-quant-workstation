# GY-DATA-CORE-V2 Task 07 evidence ledger

更新时间：2026-08-03

本文件只保存脱敏摘要与 digest。完整分片 JSONL 位于受控临时 evidence 目录，未提交仓库；
其中不包含凭据。下述 v8 snapshot 以 `develop@39d1002d1051e0ccb6ffc7f480bdc236d9930edc`
为起点，但采集时 Task 07 worktree 含未提交实现，现已被后续代码修改 supersede；它只保留为
阻塞诊断历史，不能代表当前分类、不能生成或替代 exact approval packet。clean exact
Task 07 HEAD `e01784ff` 的 v9 已重采，并证明 active-reference Gate 仍阻断。

## 0. Current implementation checkpoint

Task 07 CLI 的 inventory/plan/preflight/apply/verify/retirement plan/apply 已实现。Canonical apply
绑定 clean HEAD、DB revision、source/plan/batch digest、staging/canonical roots、脱敏 PostgreSQL
target 和 protected roots；多来源 batch 使用 fsync durable intent/partial journal，崩溃恢复只允许
当前 intent source 的 target state 漂移，并由 Canonical exact-overlap readback 判定 reuse 或 conflict。
Web Profile selector 和 queued legacy batch worker 已退出 active path。

checkout 引用分类逐条保存 classification reason；detached Runtime 的可执行 services/packages/apps
引用优先判 active/review，不能被 retired/frozen/read-only 分类提前隐藏。当前 worktree 的
checkout-only 开发扫描为 `active=0 / review_required=0`。detached Runtime 和 production DB
的 v9 blocker diagnosis 已重采。项目所有者已确认删除的 GuiyiApprovals root 不再是必需范围；
v9 不是最终 approval inventory，是因为其 base SHA 已被后续 hardening supersede 且 Runtime
active-reference Gate 尚未关闭。

## 1. Safety envelope

```text
postgresql_revision=20260802_0031
postgresql_transaction=REPEATABLE READ READ ONLY
calls_rqdata=false
writes_postgresql=false
writes_canonical=false
writes_runtime=false
deletion_authorized=false
```

扫描范围为 Task 07 checkout、生产 PostgreSQL metadata、项目 data root、Data Core V2 canonical
root，以及 detached Runtime checkout。未修改 Runtime、scheduler、通知、交易、旧 Parquet 或历史行。

## 2. Clean-head v9 blocker evidence

```text
base_sha=e01784ff91395f6519bd13d62e72aa9d8c7515b9
database_revision=20260802_0031
asset_count=103481
shards=11
truncated=false
inventory_digest=ce47184a0db06c1b14e7fb0794d8e27153f9b723673c143afbb73a89dc96b048
assets_digest=30e5f1aa096ed1c5e5543651d36ba18d7f69b5c52fbcde561f3821df2eb8550f
```

disposition 为 85 `KEEP_CANONICAL_VERIFIED`、7,232 `REUSE_TRUSTED_SOURCE`、2,817
`REGISTER_DATA_GAP`、0 `CONFLICT_BLOCKED`、14,402 `EXCLUDE_DERIVED` 与 78,945
`RETIREMENT_CANDIDATE`。migration plan 含 411 batches / 7,232 sources：

```text
plan_digest=c27121384b6408db7db9b7fc68e318dff182c30d593f623e0d546e8212c0fa1a
gate_status=BLOCKED_ACTIVE_REFERENCE
approval_eligible=false
writes_authorized=false
calls_rqdata=false
```

checkout 为 active=0 / review-required=0 / historical=2,170。detached Runtime `10351ccd`
正在提供 `/health=200` API，扫描为
300 active、967 historical 与 1,581 review-required；references digest 为
`36739f34c090261f0ed14ae019238852ab122116cef9ee46ceeaf18f688741d7`。这些命中不能
在 Runtime 未变更的情况下降级为历史引用。

retirement before-image 为 4,297 rows（4,279 bindings、8 download tasks、2 scan tasks、8
active signals），`before_image_digest=556679b55fcdf552d569099662cfb9ce68e0897dcb92a943d1bd1d605a3c59dd`，
`plan_digest=4d8fc15fd312b199361f57244cb6ab636889ea84e370d294db53601ac5a00af4`，
`approval_packet_hash=550601379c9d831ef8b18b0109aee120cb501dc22b909367def24c8cd9e05623`。
该 packet 未获 owner approval，也不得在 Runtime Gate 未解决时使用。

项目所有者于 2026-08-03 确认 `/Volumes/扩展盘/GuiyiApprovals` 已主动删除且不再作为必需
protected root；仓库不会恢复、创建或依赖该目录。后续合同改为把必填的 `--evidence-root`
永久自动加入 protected scope，额外存在的证据目录才通过可重复的 `--protected-root` 加入。
因此不存在空 protected scope，同时也不会把已退出的外部路径误报为生产 Gate。分类同时
比较登记的 lexical path 与解析后的 physical path；回归测试确认 protected root 内指向
approved data root 的 symbolic link 仍为 `PROTECTED_EVIDENCE_SOURCE`，不会进入 migration。

## 3. Superseded v8 inventory summary

```text
asset_count=103481
assets_digest=87ede418cf128d085f3a11f79bcd3d120621c02f025ad310906c3a7a5a9ae720
inventory_digest=611493315e40cff99e68fd8976ceef9972926c2890598289a2d6430ce67ba760
KEEP_CANONICAL_VERIFIED=85
REUSE_TRUSTED_SOURCE=7232
PROTECTED_EVIDENCE_SOURCE=0
REGISTER_DATA_GAP=26
CONFLICT_BLOCKED=2791
EXCLUDE_DERIVED=14402
RETIREMENT_CANDIDATE=78945
truncated=false
```

完整 inventory 为 11 个 assets JSONL shard 加一个 references JSONL；每个文件均有 SHA-256，index
另有可重算 digest。来源路径只有在 approved data/canonical root 或显式 protected evidence root
内才会读取和 hash；其他路径直接归为 retirement candidate。

## 4. Superseded v8 K-line diagnosis

确定性 plan：

```text
batch_count=411
migration_source_count=7232
verified_partition_count=85
plan_digest=b7cfaaa29aad83a2e37f30d0e7a2a446824cb6688b0a9b4f7de1d907662b586d
approval_eligible=false
gate_status=BLOCKED_AT_KLINE_DATA_GATE
```

2,791 个冲突全部是 `provider=rqdata / data_type=bars / quality_status=passed /
dataset_kind=actual_dominant`，其中 2,730 个为 1m、61 个为 1d，覆盖 56 个品种；每个文件至少
包含一个周末 `trading_day`。ID 范围为 `33868..103996`，冲突行集 digest 为
`da5acddc8771a0caf827b9ad1b9a622f2c2fdcd6189daf22ac7d0dbb90e10d85`。不得把这些文件自动
晋级为可信来源，也不得让 metadata 的 `quality_status=passed` 绕过内容 Gate。

在最终内容 Gate 前完成的 62 个 checksum-drift raw 子样本只读逐 bar 对照中，62/62 均找到
同合约/频率/row-count 的 passed 标准化 bars；这些子样本
的 datetime 与 OHLCV/turnover/open-interest 完全一致，但只有 17 个 trading-day 全部一致；其余
45 个文件共 78,210 根 bar 的标准化 `trading_day` 与 raw provider `trading_date` 不同，典型差异
是周五夜盘被标成周六而不是下一交易日。对照摘要 digest 为
`67bf2aa61f6f9daf8bc55bf176a080e20ae46d505cd38af815c4c4d4cbaaa65f`。这证明冲突不只是
metadata checksum 陈旧，也包含 session/trading-day identity 冲突；不能以数值字段相同为由复用。

26 个 DataGap disposition 均为物理文件仍存在的 `quality_status=warning`，不会自动晋级或补数；
行集 digest 为 `2979308527f97e455f5af00b3adc7566f03a533554a904c271e6adaa1e10721d`。

planner 已为 2,791 个 trading-day conflict 生成 2,791 项独立 provider request
proposal；proposal digest 为
`2f707376101098cfcba466fef3d54879e147668706daab47aa721820c894d4c1`。该 proposal 明确
`calls_rqdata=false / provider_call_authorized=false / writes_authorized=false`；26 个 warning
资产不自动进入补数范围，继续人工分类。实际 provider 请求必须重新绑定 clean task HEAD、当前
revision、inventory/plan digest 和 exact window，并获得 owner 批准。

## 5. Superseded v8 active-reference diagnosis

不截断文本扫描读取 2,486 个文件，形成 5,162 条 hash-only 命中：

```text
references_digest=efa61f7e27c27a06c701d2d56381ef40f61b571ddcb13f923b6b181405dc0112
active=1059
historical_non_active=1490
review_required=2613
truncated=false
active_reference_gate=BLOCKED_ACTIVE_REFERENCE
```

通用 `profile_id / market_data_file_id` lineage 命中不自动判 active，而进入 historical 或
review-required；真正的 `ProfileActiveBinding`、旧 reader、active switch、legacy bar path 和
Parquet glob 在可执行 checkout/Runtime 中保持 fail-closed active 分类。扫描结果是引用清理的
保守候选清单，不把历史快照误当作删除授权。

## 6. Superseded v8 retirement before-image

生产只读 before-image：

```text
profile_active_bindings active=4279
data_download_tasks pending/running/retrying=8
signal_scan_tasks pending/running/retrying=2
strategy_signals is_active=true=8
update_candidate_count=4297
before_image_digest=9f88abdc79c5e923dfbeee3e7ef80e45f6d83d697edf9489de19f8aad21e7476
retirement_plan_digest=fcf355df420ffc402f01f4ba40c27106262e48744efdf91ac44af1e7f9acddfe
deletes=0
deletion_authorized=false
```

retirement apply 只允许 hash-bound packet manifest 中的逐表主键和 before-image 精确匹配更新；
任一 row drift 回滚整个事务。receipt 生成 after-image 与 rollback digest，但 rollback 本身仍需
单独授权。当前没有 owner exact approval，未执行上述 4,297 行更新。

78,945 个 deletion candidates 的行集 digest 为
`c696fac14748b5281cc60e924e5b2d8da7afd9a840406c1cd940da00be528e11`；此 manifest 明确
`deletion_authorized=false`。report 14/15、Task 04--07 receipts、S6 历史 Gate、Git 历史和
任何现存 protected evidence root 均不在删除范围；已退出且不存在的 `GuiyiApprovals` 不作为候选。

## 7. Current result

```text
Task_07=BLOCKED_ACTIVE_REFERENCE
Kline_Gate=BLOCKED_BY_ACTIVE_REFERENCE_AND_EXACT_APPROVAL
Active_Reference_Gate=RUNTIME_300_ACTIVE_1581_REVIEW_DB_4297_PENDING
Review_Gate=CODE_REVIEW_PASS
READY_FOR_TASK_08=false
```

只有冲突资产获得逐项 disposition、重新在 clean exact task HEAD 采集 inventory、每个 batch
分别通过 exact approval/preflight/apply/readback、legacy active code/DB reference 归零且独立
Review 无阻塞后，才能改为 `READY_FOR_TASK_08`。

K-line `apply/verify` 已实现 staging、Decimal/UTC、duplicate、OHLCV、coverage、MainContractMap
rank=1、overlap、Catalog/Manifest publish、durable partial journal/resume 与 readback；但未获得任何
production exact approval，未执行 Canonical/PostgreSQL 写入。代码与测试完成不能替代 v9 inventory、
逐 batch owner approval、生产 readback、retirement approval 或 develop integration。
