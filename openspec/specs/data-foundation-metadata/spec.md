# data-foundation-metadata Specification

## Purpose

定义历史维护与查询共同依赖的八表 metadata/Catalog 当前事实，确保交易日历、Session、主力映射、Dataset 与月分区只有一个权威状态来源。

## Requirements

### Requirement: 八表 active 模型
系统 SHALL 仅以 `exchanges`、`instruments`、`contracts`、`trading_calendars`、
`trading_sessions`、`main_contract_map`、`market_datasets`、`market_partitions` 作为 active 数据基础表；
PostgreSQL MUST NOT 保存 Bar 行、合约参数、内容摘要、发布清单或运行历史。

#### Scenario: 0036 隔离升级
- **WHEN** 空数据库或 `20260808_0035` 隔离数据库升级到最终 head
- **THEN** ORM metadata 与数据库仅包含规定的 active 表，不创建退出表

### Requirement: 当前交易元数据和主力映射
MetadataSynchronizer SHALL 维护 60 品种、真实 contract identity、实际交易所 Calendar、
product-specific Session 和 RQData `rule=2` 的 rank1 MainContractMap；Map 对 `(symbol,trade_date)`
唯一，维护范围为 `effective_start→fixed through`。
RQData 1m Session 的 provider start 是首根 `bar_end` 标签；MetadataSynchronizer SHALL 在 adapter 边界
减一分钟后再写入 `trading_sessions`，使 DB 中 start 始终表示 `(start, end]` 的排他边界。分钟不对齐、
无效区间、重叠 session 与不可解释跨午夜布局 MUST fail closed。
历史 metadata 同步 SHALL 仅替换每个请求品种 `L <= effective_from <= U` 的 Session，其中
`L = snapshot.main_contract_starts[product]`、`U = through`，且请求 floor ≤ L ≤ U。adapter SHALL
将实际传入 provider snapshot 的各品种 starts 原样作为返回的 main_contract_starts；不得从返回行的
最早日期猜测完整覆盖。每个品种所属交易所在 [L,U] 内 MUST 有连续自然日 Calendar，provider 为
rqdata、交易日标记为严格 bool 且键唯一；前月和 through+7 的合法 Calendar context 可保留。
令 E 为窗口 Calendar 证明的交易日集合；E MUST 非空，Map 按 (symbol,date) 恰好覆盖 E 且每键一行，
Session 日期集合 MUST 恰好等于 E。Session MUST 是匹配品种、交易所、rqdata 来源的 active 按日事实，
允许同日多个合法时段，但不得有重复行身份、重叠或无效时段。
任一覆盖证明缺失、空或稀疏时 MUST 整事务回滚并报 `HISTORICAL_SESSION_REPLACEMENT_UNPROVEN`。
同步 SHALL 保留 L 之前的 warm-up 与 U 之后的明确按日事实。既有无结束日期、跨下界
`from < L <= to`、跨上界 `from <= U < to` 或 U 之后非按日的模板无法证明安全替换时 MUST
以同一错误整事务回滚，不得拆分模板或静默删除窗口外事实。

#### Scenario: 历史补齐保留窗口前 warm-up
- **WHEN** provider snapshot 明确从 2023 年开始，而 Catalog 已有 2022 年 contract warm-up Session
- **THEN** 同步仅在证明完整的 snapshot 窗口内替换，2022 年原 Session 身份和值保持不变

#### Scenario: 返回快照缺日或缺少明确下界
- **WHEN** snapshot 下界缺失、窗口 Calendar 缺自然日，或 Map、Session 未完整覆盖其交易日集合
- **THEN** 同步整事务回滚，不以返回行最早日期收缩替换窗口，也不删除旧事实后接受稀疏来源

#### Scenario: 历史补齐保留下一交易日
- **WHEN** 受限 metadata 已准备下一交易日 Session，随后 full update 或 refresh 需要补齐截至 through 的历史 metadata
- **THEN** 历史同步保留下一交易日的原按日 Session，后续历史维护不得清空该事实

#### Scenario: 历史模板跨越维护截点
- **WHEN** 请求品种既有无结束日期、跨越 through 或截点之后非按日的 Session 模板
- **THEN** 同步整事务回滚并明确失败，不截断、拆分或删除未来事实

#### Scenario: 主力修订
- **WHEN** 同一 symbol/trade_date 的 rank1 合约被 RQData 修订
- **THEN** 系统替换该唯一当前事实并使后续查询使用修订值

#### Scenario: 规范化 Session 标签
- **WHEN** RQData 返回 `09:01-10:15` 的 1m Session
- **THEN** active metadata 保存 `09:00-10:15`，Historical expected bars 与 Live 首分钟都以同一边界解析

### Requirement: Runtime-bound current-day metadata recovery separates source and write authority
系统 SHALL 提供 `guiyi data current-day-metadata-recovery --phase capture|plan|apply`。三阶段 MUST
绑定 exact Runtime root、lowercase commit、after-market status hash、显式 trading day，并只使用该
Runtime 的 operational products。`capture --apply` 表示一次外部 source capture 意图；它 MUST 恰好调用
一次既有 `fetch_current_day_metadata(products,trading_day)`，只输出严格 JSON snapshot、语义
`snapshot_sha256`、方法/参数身份与应用层调用摘要，不写 PostgreSQL、Canonical、Redis、status 或 projection。
P60 正常适配器边界的摘要为 64 次应用层调用：下一交易日探测 1、完整期货合约表 1、有界 Calendar 1、
rank1 dominant 60、批量 trading periods 1；该计数不得表述为 SDK 内部或 provider 计费请求数。

`plan` MUST 只消费 exact frozen snapshot/hash，不构造或调用 provider。它 SHALL 复用
`MetadataSynchronizer` 的 current-day 验证，逐行披露当天至 context end 的 Calendar、当天与下一交易日
Session、当天 rank1 MainContractMap 的 `equal|insert` 精确差异及 `plan_sha256`。既有 Calendar、当前/下一
交易日 Session 或当天 Map 的任何值变化、重叠或来源冲突 MUST block，不得以 Calendar 修订完成恢复。
未知、partial、malformed 或 future-not-ready snapshot MUST fail closed；窗口外 Session、Map、Dataset、
Partition 与 warm-up MUST 保持不变。

`apply --apply` MUST 同时绑定 exact snapshot/hash 与 plan hash；取得全局 maintenance lease 后重新检查
Runtime root/commit/status、依赖、Live/Alert heartbeat 和完整 diff。任一 drift 或 lock miss MUST 在写入前
阻断。通过后 SHALL 调用与自然 `synchronize_current_day` 共用的 validated writer，一次事务只插入计划缺失
事实；apply 路径不得构造 provider，并固定报告 `provider_requests=0`。commit 结果不明 MUST 报
`CURRENT_DAY_METADATA_COMMIT_OUTCOME_UNKNOWN`、停止且不得 retry；必须独立 readback 后再决定新动作。

#### Scenario: Frozen source is planned without provider capability
- **WHEN** operator supplies a matching current-day snapshot and hash to `--phase plan`
- **THEN** the command returns exact equal/insert facts and plan hash with zero provider or database writes

#### Scenario: Existing current-day fact differs
- **WHEN** any Calendar, current/next Session or current-day rank1 value differs from the captured source
- **THEN** planning/apply blocks before mutation and does not overwrite the existing fact

#### Scenario: Apply loses commit acknowledgement
- **WHEN** the shared transaction commit raises after submission
- **THEN** the result is commit-outcome-unknown, the lease is released, and no automatic retry occurs

### Requirement: 共享 Calendar 逐日夜盘证据
MetadataSynchronizer SHALL 将 Calendar 视为交易所共享事实。夜盘 true MUST 由同日 provider
Session 正证据支持；交易日 false MUST 由筛选请求品种之前的完整 provider 合约集合及逐日生命周期
确定交易所当日品种全集，并验证每个品种的当日 Session 完整覆盖且均无夜盘。生命周期或覆盖缺失
MUST 保持 UNKNOWN，非交易日可确定 false。UNKNOWN SHALL 只保留交易日身份一致的已有行，
缺键 MUST fail closed；已证实事实与既有 Calendar 冲突 MUST 整事务回滚，纠正须走显式有界来源更正。

#### Scenario: 子集仅日盘
- **WHEN** 同交易所只请求无夜盘品种，无法证明该交易所当日完整 Session 覆盖
- **THEN** 不把共享 Calendar 的已有 true 改为 false；缺键报 `CALENDAR_NIGHT_AUTHORITY_MISSING`

#### Scenario: 节假日边界
- **WHEN** 相邻日期有夜盘，而本日完整交易所品种 Session 均仅日盘
- **THEN** 本日源证据为 false；已有 true 时报 `CALENDAR_SOURCE_CONFLICT` 而非静默覆盖

### Requirement: 最小月度 Catalog
`market_datasets` SHALL 对四字段 DatasetKey 唯一；`market_partitions` SHALL 对
`(dataset_id,year,month)` 唯一，只保存 coverage、file URI、row count 和创建时间。查询和维护 MUST
以 Catalog identity、coverage 与物理可读性判断可用月；唯一性约束表示 active pointer 唯一，不限制保留的不可变物理文件数量。

#### Scenario: 原子月替换
- **WHEN** 校验通过的新月文件发布
- **THEN** Catalog 只发现该 Dataset 的唯一当前月分区；新 URI 只在现有事务 register/flush、真实 MarketDataService strict-read 后 commit 才可见

### Requirement: 已确认 AU 单键 Calendar 冲突更正
系统 SHALL 提供默认只读、零 provider 的受限入口，只允许已核实的 SHFE／2022-03-16 Calendar
id=46796 的 `has_night_session` 从 false 更正为 true。源响应内容、来源合约/日期、输入文件与
旧事实 MUST 精确绑定；不得扩展为任意日期/交易所编辑，不得修改其他 Calendar 字段或补入 Session。
Apply MUST 另获单次授权、匹配 dry-run hash、锁内核对旧事实，一次提交后独立只读验证。
任何提交不确定 MUST 明确停止、不自动重试；已有事实或证据变化 MUST 使旧计划失效。

#### Scenario: 有界元数据插入提交确认丢失
- **WHEN** 已验证的 insert-only metadata apply 在调用 commit 后抛出异常
- **THEN** 系统报告 `METADATA_REPAIR_COMMIT_OUTCOME_UNKNOWN`，停止后续写入；仅凭本地 rollback 不得宣称服务端未提交，必须独立只读核对精确行后才能决定后续操作

#### Scenario: 单键冲突处理
- **WHEN** 已获准捕获的 AU2304 时段证明该日期有夜盘，而本地已核实前像为无夜盘
- **THEN** dry-run 仅规划一个字段更正，零数据库写入；真正 apply 仍等待新的单次执行意图

#### Scenario: 已有事实漂移
- **WHEN** apply 时 Calendar、来源身份或当日 Session 与计划不一致
- **THEN** 在任何写入前拒绝，不覆盖并发事实，也不重新请求 RQData
