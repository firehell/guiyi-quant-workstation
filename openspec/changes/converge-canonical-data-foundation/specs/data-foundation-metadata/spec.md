## Purpose

定义个人量化工作站唯一 active 的期货元数据、主力映射与轻量行情目录，使历史数据维护和查询共享同一份当前事实并退出旧 Data Center 选择语言。

## ADDED Requirements

### Requirement: 最小 active 数据库模型
系统 SHALL 仅以 `exchanges`、`instruments`、`contracts`、`trading_calendars`、`trading_sessions`、`main_contract_map`、`contract_specs`、`market_datasets`、`market_partitions` 和 `data_gaps` 作为 active 数据基础表，且 PostgreSQL MUST NOT 保存历史 K 线行。

#### Scenario: 新 schema 升级
- **WHEN** 隔离数据库从既有 `20260808_0035` 或空数据库升级到新 head
- **THEN** ORM metadata 与数据库只包含上述 active 数据基础表且不会建议重建已退出表

### Requirement: 当前主力映射
系统 SHALL 显式使用 RQData `rule=2` 的 `volume_open_interest` 口径保存 active 69 品种的 rank1 当前事实，并 MUST 对每个 `symbol + trade_date` 保证唯一；RQData 修订 SHALL 在本次刷新窗口内替换当前事实而不是增加数据版本、保留已撤回事实或保存 raw payload。首个 provider rank1 事实之前允许仅存在 continuous 历史，actual_dominant 查询仍须 fail-closed。

#### Scenario: 重复同步同一交易日
- **WHEN** 相同品种、交易日和主力合约再次同步
- **THEN** 系统幂等保持一行且查询得到相同当前映射

#### Scenario: RQData 修订主力合约
- **WHEN** 同一品种和交易日的 rank1 合约被事实源修订
- **THEN** 系统更新该唯一行并使后续查询使用修订后的当前事实

### Requirement: 每日真实合约参数
系统 SHALL 为被 rank1 映射使用的真实合约按交易日保存最小价格变动、合约乘数、保证金率、开仓费、平仓费、平今费及费用类型，并 MUST NOT 保存 provider raw payload。

#### Scenario: 映射覆盖校验
- **WHEN** 审计 active universe 的 MainContractMap
- **THEN** 每个映射到的真实合约在对应交易日均存在唯一 contract_specs 记录

### Requirement: 实际交易所日历和交易时段
系统 SHALL 按合约所属实际交易所保存并解析交易日历和交易时段；某品种的期望交易日 SHALL 为实际交易所开市且至少一个该品种真实合约处于上市期的日期，不得把无上市合约的交易所开市日误判为数据缺口。缺失或不一致时 MUST fail-closed，且 MUST NOT 回退到 CNFE、CZCE 或通用默认时段。

#### Scenario: 交易时段缺失
- **WHEN** 标准化或查询需要的实际交易所时段不存在
- **THEN** 系统拒绝发布或读取并返回有界错误原因

### Requirement: 当前 Catalog 和 Gap
`market_datasets` SHALL 对四字段 DatasetKey 唯一，`market_partitions` SHALL 对 `dataset_id + year + month` 唯一；`data_gaps` SHALL 只保存当前未解决缺口，并在 repair 成功且复验通过后删除相交的已修复记录。

#### Scenario: 同月分区替换
- **WHEN** 当前月更新或显式 repair 发布通过验证的新分区
- **THEN** Catalog 原子指向该月唯一当前分区且不产生重叠 active 版本

#### Scenario: 缺口修复
- **WHEN** repair 覆盖一个已记录缺口且严格复验通过
- **THEN** 对应当前 DataGap 被删除而不是转为 resolved 历史状态

### Requirement: 旧表退出
迁移 SHALL 不可逆 drop `data_sources`、`data_download_tasks`、`market_data_files`、`data_quality_reports`、`fee_margin_rules`、`futures_trading_parameters`、`futures_ex_factors`、`futures_warehouse_stocks`、`futures_roll_yields`、`futures_member_ranks`、`futures_basis`、`futures_contract_universe` 和 `futures_continuous_contract_map`，且 active 代码 MUST NOT 重新创建兼容表或数据库运行历史表。

#### Scenario: 迁移完成后的模型扫描
- **WHEN** 新 head 的数据库和 ORM metadata 被检查
- **THEN** 所有列出的旧表均不存在且 active migrations 之后没有 recreation 建议
