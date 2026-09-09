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

#### Scenario: 主力修订
- **WHEN** 同一 symbol/trade_date 的 rank1 合约被 RQData 修订
- **THEN** 系统替换该唯一当前事实并使后续查询使用修订值

#### Scenario: 规范化 Session 标签
- **WHEN** RQData 返回 `09:01-10:15` 的 1m Session
- **THEN** active metadata 保存 `09:00-10:15`，Historical expected bars 与 Live 首分钟都以同一边界解析

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

#### Scenario: 单键冲突处理
- **WHEN** 已获准捕获的 AU2304 时段证明该日期有夜盘，而本地已核实前像为无夜盘
- **THEN** dry-run 仅规划一个字段更正，零数据库写入；真正 apply 仍等待新的单次执行意图

#### Scenario: 已有事实漂移
- **WHEN** apply 时 Calendar、来源身份或当日 Session 与计划不一致
- **THEN** 在任何写入前拒绝，不覆盖并发事实，也不重新请求 RQData
