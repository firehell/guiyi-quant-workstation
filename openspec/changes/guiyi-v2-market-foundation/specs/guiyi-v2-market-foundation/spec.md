## ADDED Requirements

### Requirement: MF01 Market authority and third-party reuse

Market SHALL 优先复用 RQData 与锁定 VeighNa 的适用组件，维持唯一正式 Market 历史权威、统一读取、现役 Calendar/Session/MainContractMap 与严格质量合同；仅在隔离测试证明正确性及维护价值后替换对应实现。RQAlpha 数据维护独立，不属于本 change。

#### Scenario: A candidate storage or adapter cannot preserve existing facts

- **GIVEN** 候选组件丢失精度、空值、物理身份、覆盖或来源修订，或需要大量自研定制
- **WHEN** 执行同一冻结数据的对照
- **THEN** 不批准该组件成为正式权威；保留或复用原实现，并记录差异及选型理由。

#### Scenario: RQAlpha has an existing isolated MDS dependency

- **GIVEN** 既有研究试验仍使用 MDS 冻结数据，而目标研究域自行维护数据
- **WHEN** 本 change 开发或迁移 Market
- **THEN** 不改 RQAlpha 数据、适配、引擎或历史结果，不新增耦合；保护既有读面，依赖未解除不退役其必要入口。不得宣称研究数据独立已实现。

### Requirement: MF02 Single-source Tick observation and completed bars

Market SHALL 在经验证的隔离 Tick 路径中用单源单代次、物理合约与交易日身份、适用的 VeighNa 组件和 Session 边界，增量生成活动/完成 Bar；已完成事件可恢复、幂等、不静默改写。未完成或无法证明的输入不得用于正式策略。

#### Scenario: Reconnect, cumulative volume, break or session tail

- **GIVEN** 夜盘跨日、短休/午休、累计量重置、断线或末根没有下一 Tick
- **WHEN** 生成分钟及派生周期
- **THEN** 使用已核实的累计基线、交易日与 Session 规则，证明完整端点；不虚构价格、不跨错误边界、不以时钟代替输入事实。

#### Scenario: Concurrent comparison and source handoff

- **GIVEN** Tick 候选与 RQData 1m 对照同时运行，或存在现役源代次
- **WHEN** 候选产生相同合约/端点的输出
- **THEN** 对照不写正式流；只有已授权且核实停旧、末水位与新源身份后才切换。重复、迟到和异值不触发补开仓或重放通知。

#### Scenario: Formal Tick owners start before the staged trading day opens

- **GIVEN** 跨 Redis 交接已建立正式 Tick 绑定、次日完整 rank1 订阅和空 source / completed 基线
- **WHEN** Live 和 Feed 在盘后启动，品种仍处于 CLOSED 且各自的下一场 Session 均证明属于该登记日
- **THEN** 两个写入者仅从已有基线恢复内存身份并发布休市心跳，开盘前不连接供应商、不生成 Bar、不改写订阅或游标
- **AND** 绑定、Session、订阅或基线冲突时拒绝就绪

#### Scenario: PD and PT leave the active Market universe

- **GIVEN** 旧 Bar 源的精确运行范围仍含 PD 和 PT
- **WHEN** 执行首次正式 Tick 交接
- **THEN** 旧源及盘后记录按旧范围校验、留存，目标订阅、历史维护、策略消费、页面及归档使用现役名单的 57 品种
- **AND** 旧盘后记录不得作为新版范围的成功凭证。涉及切换日且尚未确认的元数据或盘后提交须先核验结果


#### Scenario: A switched target is awaiting natural completed minutes

- **GIVEN** the exact handoff plan has a proven registry CAS, a target binding and frozen Session windows and rank1 owners for every subscribed product
- **WHEN** the operator reads the first completed minutes from the target
- **THEN** read back the first emitted 1m observation per product through the durable journal and its identity index, proving its Bar, Session endpoint, physical owner, source generation and confirmation time
- **AND** report any opening-minute gap separately; pending, missing, late or unproved observations do not qualify as timely completion and the readback does not advance any cursor

### Requirement: MF03 History lifecycle and unified reading

Market SHALL 初次校验历史后日常采用增量维护，保留只读审计及必要的定向修复；以 RQData 1m、交易所 D1 及完整 Session/周派生七周期，按身份组合已归档历史与 Live，区分活动 K 线、盘中已完成事实和盘后权威数据。

#### Scenario: Market closes before historical publication

- **GIVEN** 交易日已结束但供应商历史未就绪或归档失败
- **WHEN** Web 查询
- **THEN** 保留最后有效历史与未归档 Live，显示真实截至时间和状态；午休不清除当日 Live，归档成功后该范围不再依赖 Live。

#### Scenario: Historical revision and durable publication

- **GIVEN** RQData 盘后数值与盘中不同或某分区失败
- **WHEN** 维护任务校验、生成派生并发布
- **THEN** 合格历史按新版本原子可见，旧观察及决策/成交不被重写；不完整范围不签成功凭证，失败保留上次成功版本，提交未知先独立读回。只清理已归档且可重建缓存。

### Requirement: MF04 Consumer and workload isolation

Market SHALL 向 Web 提供报价和活动行情，向已启用的独立模拟提供各自合格的 completed 输入；Market 参考计算只由合格盘后发布触发。历史/实时查询、Tick/Bar 不得触发牛哇盘中参考计算；Market 盘后参考及后台维护均不得创建订单或真实策略通知，既有独立模拟和 Alert 按原合同运行。

#### Scenario: Concurrent night session and prior-day maintenance

- **GIVEN** 上一交易日更新仍进行，下一交易日 Tick 到达，快期 HTDY 与苏冰 Paper 各自消费
- **WHEN** 研究或维护作业失败/重启，Web 切换图层
- **THEN** 两账户输入、状态、水位和账目各自连续且无漏重；牛哇实时触发计数为零，上一日凭证只产生一次逻辑盘后触发，下一日数据不被清理。

### Requirement: MF05 Selection, capacity and controlled retirement

Market SHALL 在目标本机隔离对照真实代表性历史和实时负载，以正确性、稳定性、延迟、资源和维护复杂度为选择依据；按 design 测量 500/5000/100000 根与 57/70 品种负载，70 只作隔离容量，未经授权不扩大生产。正式迁移前 SHALL 完成对应 active delta、独立 Review、消费者验证和原件保护。

#### Scenario: Faster candidate lacks proof or operational permission

- **GIVEN** 候选性能更快但未验证完整数据/恢复，或无正式迁移/Runtime 授权
- **WHEN** 完成隔离试验
- **THEN** 只记录候选结果，不替换生产权威、不删除旧原件、不改变账户或 `auto_order=false`。最终仅一套 active 历史实现，仍有消费者或恢复引用的旧入口不得退役。
