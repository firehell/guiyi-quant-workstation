## Purpose

定义历史维护和查询共享的八表 metadata/Catalog 当前事实。

## ADDED Requirements

### Requirement: 八表 active 模型
系统 SHALL 仅以 `exchanges`、`instruments`、`contracts`、`trading_calendars`、
`trading_sessions`、`main_contract_map`、`market_datasets`、`market_partitions` 作为 active 数据基础表；
PostgreSQL MUST NOT 保存 Bar 行、合约参数、内容摘要、发布清单或运行历史。

#### Scenario: 0036 隔离升级
- **WHEN** 空数据库或 `20260808_0035` 隔离数据库升级到最终 head
- **THEN** ORM metadata 与数据库仅包含规定的 active 表，不创建退出表

### Requirement: 当前交易元数据和主力映射
MetadataSynchronizer SHALL 维护 69 品种、真实 contract identity、实际交易所 Calendar、
product-specific Session 和 RQData `rule=2` 的 rank1 MainContractMap；Map 对 `(symbol,trade_date)`
唯一，维护范围为 `effective_start→fixed through`。

#### Scenario: 主力修订
- **WHEN** 同一 symbol/trade_date 的 rank1 合约被 RQData 修订
- **THEN** 系统替换该唯一当前事实并使后续查询使用修订值

### Requirement: 最小月度 Catalog
`market_datasets` SHALL 对四字段 DatasetKey 唯一；`market_partitions` SHALL 对
`(dataset_id,year,month)` 唯一，只保存 coverage、file URI、row count 和创建时间。查询和维护 MUST
以 Catalog identity、coverage 与物理可读性判断可用月。

#### Scenario: 原子月替换
- **WHEN** 校验通过的新月文件发布
- **THEN** Catalog 只发现该 Dataset 的唯一当前月分区
