# GY-DATA-CORE-V2 Task 06 Migration Incident and Recovery Gate

更新时间：2026-08-02

## 事实

- task branch：`feature/live-review-loop-clean-start`
- base：`b64453eab89692e5250a4275f04cac1bd26f02d4`
- migration：`20260802_0028`
- migration file SHA-256：`f09fc15ef09f260ebff1aa0b5065bbe8386e4670db96adbb12b23e54bfa095e5`
- 触发原因：Task 06 隔离迁移测试设置了 Alembic `sqlalchemy.url`，但 `alembic/env.py` 又从
  `DATABASE_URL` 覆盖该值，导致第一次测试将项目数据库从 `0027` 升级到 `0028`。
- 当前项目数据库 revision：`20260802_0028`。
- 五张 Task 06 新表行数均为 0；`signal_events.decision_id` 已存在。
- live decision、EOD、retention scheduler、SignalEvent、WeCom autosend flags 均为 false。
- 未调用 RQData，未写 live/decision/EOD/sample 业务行，未启动 scheduler/Runtime，未发送通知。
- 隔离测试已修复为同时覆盖测试进程的 `DATABASE_URL`；独立临时库随后实际完成
  `0027 -> 0028 -> 0027 -> 0028`，3 tests passed。临时库已删除。

该事实不等于事前批准，也不得改写为合规 production migration receipt。

## 后续 branch-local 修正（未应用生产）

验收复核发现 live identity 必须显式包含 `revision + confirmed`。为保留已经执行的 `0028`
文件与上述 SHA 证据，候选分支没有改写 `0028`，而是新增 `20260802_0029` 修正唯一约束。
独立临时库随后实际完成 `0027 -> head(0029) -> 0027 -> head(0029)`，4 tests passed，临时库已删除。
后续审查再新增未应用生产的 `20260802_0030` create-only trigger 与 `20260802_0031`
provider-final lineage；最终隔离库已对 head `0031` 完成
`0027 -> 0031 -> 0027 -> 0031`，6 passed / 19 条既有 deprecation warnings，临时库已删除。
项目数据库未执行 `0029..0031`，
当前仍为 empty/disabled `0028`。

## 根因修复

`test_live_review_loop_migration.py` 现在用 migration safety guard 比较 Runtime 与隔离库 database/OID，
并在 Alembic 执行前把测试进程 `DATABASE_URL` 明确绑定到隔离库。测试不能再只设置会被
`env.py` 覆盖的 `sqlalchemy.url`。

## Owner 处置决定与当前 Gate

Owner 于 2026-08-02 明确选择保留并追认当前 additive、empty、disabled `0028`，且选择在后续
`0028 -> 0031` 前生成系统数据卷上的 fresh 最小数据库备份。该决定只处置事故后的当前状态，
不把未事前批准的操作改写为合规 migration receipt。

未采用的恢复选项：

1. 先使用仓库现行业务数据库备份流程生成新备份证据；
2. 再在 flags 全 false、新表全空、migration hash 精确匹配时执行
   `alembic downgrade 20260730_0027`；
3. 回读 revision=`20260730_0027`、五张表不存在、`signal_events.decision_id` 不存在；
4. 待 Task 06 exact-head Review/CI 与正式 approval packet 通过后重新 apply 到 head `0031`。

已采用处置：保留当前 additive/empty/disabled `0028`；随后仍需对 exact reviewed `0029..0031`
单独批准并回读。该 ratification 不授权真实业务
写入、scheduler、Runtime、通知、release 或 Task 06 完成。

## 停止条件

以下任一事实漂移均停止 downgrade/ratification：

- 项目数据库 revision 不再是 `20260802_0028`；
- 任一 Task 06 新表非空；
- 任一 Task 06/SignalEvent/WeCom flag 为 true；
- migration file SHA-256 不再等于上述值；
- Runtime、release 或数据库备份事实无法确认。
