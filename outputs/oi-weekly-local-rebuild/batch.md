# OI2611 W1 本地重建候选批次

- 冻结截点：`2026-09-18T07:00:00.000001+00:00`；Catalog OI D1/W1 revision：`6857967fe6d45bd8daea6aa17ccb8ba1dd46cc2abadd4e4a79ee1720640d1f86`。
- 精确计划：[prepare.json](prepare.json)，SHA-256 `9889ae0c7a4f1eefbfafa3cd24e5db4a8dc95309d26dd8ddb3ee3f9be62f166d`。计划记录聚合版本及源码 hash、10 个 D1 active 分区完整 Catalog 身份及文件 hash、37 个交易周端点及聚合值、10 个 W1 原/候选分区身份、目标 URI 和完整目标 Catalog 字段。首次执行前必须重新比对整个计划；身份漂移则废弃旧包。
- 仅 `OI2611`，只新增 2025-11-28 至 2026-08-14 的 37 根 W1。2025-11 至 2026-07 的 9 个月当前无 W1 分区；2026-08 原有 2 行，候选 4 行，原有两行逐值保留。provider 预算 0，D1 写入 0，其他合约写入 0。
- 2025-11-21 所属周的 2025-11-17、18、21 三个 `NONPOSITIVE_CLOSE` 事实保留，不生成该周价格。候选验收中 OI2611 为 41 个预期周、40 根价格 W1、1 次来源中断。
- [candidate-acceptance.json](candidate-acceptance.json) 是只读内存 Catalog/Store overlay，三策略主状态与 chart、reference 均为 `READY`。震荡 comparator 为 `NEWOW_PAGE_COMPARATOR_INSUFFICIENT_BARS`，属独立研究证据，不改变主策略结论。该证据不是生产 Catalog READY 或页面发布验收。

## 授权后的执行与恢复

执行范围仅限上述 10 个 OI2611 W1 月分区的不可变候选文件发布与 Catalog 指针事务。正式执行前核对批次授权、代码及计划 hash、D1/W1 当前身份、维护锁和生产连接目标；执行中不下载、不修改 D1、不改 Scope。调用 `scripts/oi_weekly_local_rebuild.py apply` 必须同时提供 `--prepared`、`--expected-prepared-sha256` 和 `--apply`。CLI 首先只读检查指针状态，仅 `old` 状态才尝试提交；维护锁内再次完整 prepare，差异即拒绝。

文件发布使用内容寻址的不可变 URI；10 个 Catalog 指针在一个事务中提交。旧 URI 均保留。若文件发布后事务未提交，候选文件可作为无主文件保留，旧指针仍有效。若提交结果不明，停止 mutation，使用独立只读 `inspect` 判定所有月为 `old`、`candidate` 或 `mixed_or_unknown`；混合或未知状态不得自动重试。需要恢复时，在核实旧文件完整、影响及新授权后通过受控 Catalog 事务恢复精确旧指针；原本不存在的 9 个分区须删除对应新指针。不要删除候选或旧物理文件来代替指针恢复。

提交后独立回读 37 根新增 W1、2026-08 原两行不变、合法中断仍无价格、D1 hash 不变、其余合约不变，再对生产 revision 重跑 OI 三策略和页面/API 验收。Scope、release、Runtime 是独立 Gate。
