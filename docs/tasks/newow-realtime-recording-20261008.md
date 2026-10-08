# 牛哇四策略三周期持续记录

用户于2026-10-08批准实施会话中的完整方案。目标为 operational 60 × trend/oscillation/main_rise/dual × 1d/1w/60m 共720组合：数据追平、completed-only持续记录、动作与逐Bar状态、查询与Web、正式部署，无通知、无订单。

基线：develop c6c4d5b2e86b9ca40d4e220ac8488715e34430d5；独立worktree newow-realtime-recording。当前正式运行v1.13.0；历史60m固定截至2026-09-24，reference worker关闭。

实施顺序：现场只读审计 → 策略与记录/调度实现 → 定向与集成验证/独立Review → 精确数据追平与读回 → 历史资产及forward初始化 → 查询/Web验收 → 集成发布/Runtime → 自然周期验收。

## 执行记录

- 工作树已创建；原树未提交outputs和其他任务工作树保留。
- 生产reference health HTTP500，正在只读核对schema；不把接口失败视为已开始迁移。
- 分派data只读审计、fusion计算、worker调度三个有明确修改归属的任务；生产mutation由主代理串行执行。
- 范围口径：日周仅确认完成的Canonical，60m仅completed Live；历史与forward独立。J等保留Hint身份，未增加成交或风险语义。
- 首轮基础记录25项通过；新增state缺失用例真实RED3→GREEN；health720容量用例真实RED512截断→GREEN6条set-based SQL。
- 18:05自然盘后任务18:06:34 passed/attempt1；独立短事务读回60主力到10/8，1m/60m/1d到当日15:00，RM发生主力切换，W1当前周未完成。
- 独立早期Review确认fusion延迟捕获>256饥饿与gap传播两Important，正在TDD修复，未发布或启用。
- 独立PostgreSQL测试首轮暴露既有未执行测试fixture的D1 V1身份与生产V2合同不一致，以及子进程用redacted URL连接失败；按生产identity构造fixture，测试子进程凭据只经env传递。分组缓存减少来源读数，容量验收保持全记录数并核对读取上下界。
- 生产迁移0047→0048：完整reference preimage gzip及SQL dry-run保留，旧六表count/旧字段逐行摘要前后相等，activation receipt为0；health恢复HTTP200。证据`outputs/newow-realtime-recording-20261008/migration/`。
- 14项current-owner预热维护串行完成，84次真实provider请求；独立读回D1/60m各60 DATA_READY，W1 59 DATA_READY及RM2701无已完成owner Bar NOT_APPLICABLE。198分区内容/身份验证、9合约最新整日1m→60m逐值复算匹配，锁0；不把数据完整说成策略均READY。
- 隔离PostgreSQL720路真实kernel记录与重启幂等通过(28.56s)，300路五轮1500记录容量回归通过(54.87s)。Web800 passed/1 skipped，build/typecheck/topology通过(已有大chunk warning)。
- 首轮扩大后端3285 passed/9 failed/2 skipped；失败含stdin测试launcher导致spawn找不到main、fixture旧contract及capability旧断言，按真实新版合同修正后相关332 passed；待最终候选回归。
- 第二轮独立Review Important：pending capture绕过mismatch guard。已补所有计算入口及事务内source guard，基/dual入口+rollback9项通过，待复核。
- public RB九基础历史资产已实际完成到最新确认数据。D/W双策略发现boundary fingerprint含stream身份，已改同策略完整manifest验证并保留共同market lineage，正在真实只读计划复核；未启用任何forward或通知。
- 同一worker生命周期的单受控历史刷新线程正在补齐；独立session、exact plan/resume持久状态及失效阻断，不新增job/通知，不将历史刷新冒充自然实时观察。

- 最新develop 77b160b65已无冲突引入。其苏冰六周期/0049未进入本轮上线范围；最终牛哇release从现役main构建，只引入本任务提交，保留苏冰15m及0048。
- 最终扩大后端3322 passed/2 skipped；同步develop后的Web808 passed/1 skipped。RB12组历史资产完成，AL已开始真实初始化。
- 第二轮Review发现history receipt落盘前中断可重复rebuild，已补唯一durable intent、file/directory fsync、product flock和未知结果阻断；定向独立Review50 passed/7 skipped，允许继续串行初始化。
- 通用rebuild改先pin/验证frozen snapshot再invalidate，SOURCE_BUSY/SOURCE_CHANGED保留旧active；42 passed/5 skipped。
- Runtime仍未启用。剩余验收风险是历史回放持全局维护锁，需要实测持锁时长与取消/调度边界，不以提前释放锁削弱一致性。
