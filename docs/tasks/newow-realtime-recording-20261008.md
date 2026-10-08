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

- 历史执行补充唯一durable intent及product flock，未知提交不重试。新上市品种仅新计划使用权威product_start，不缩掉上市后缺口。B旧失败候选仅精确invalidate，17批次/50动作/23交易/82 marks完整保持。
- D1新合约预热期的quality boundary不再投射为旧owner参考中断，raw gap/calculation事实保持；新policy hash绑定基础/双策略，bootstrap及audit拒绝旧D1policy。已完成六品种24日线按新policy重建，B/AO实际重建通过；其他品种串行推进中。
- 第二轮定向独立Review92 passed/2 PostgreSQL skip，ruff/diff通过，代码允许集成develop。最终720及自然运行验收未完成。
- 启动只读核对：45品种首夜60m端点22:00，15品种次日10:00；Oct9 MainContractMap尚缺，必须先补权威metadata。不得用昨日owner、回填recording_start或伪造seed watermark。

- 正常日切新增Market Fact Live preparation hook，非交易poll提前30min按既有phase resolver准备；Catalog完整后Live使用同一Catalog rank1。failed recovery Gate保持。单次intent/snapshot/exactplan、全局lease、insert-or-equal、unknownstop及跨release稳定state；逐日不可变proof归档避免整体16MB约五日满，10×3MB证据保留/index<20KB。独立99 passed及Review通过。
- Oct9正常source计划2f648c39…/e027b40e…实际apply passed：60MainMap新增、5Calendar/225Session新增，15Calendar/225Session equal保持。独立530事实逐值相等、fresh diff新增0、60owner可解析。先前failedRecovery命令在provider初始化前status unsupported正确停止，不弱化它。
- 候选真实Web发现合法null matrix被前端拒绝并挡历史tab，实际RED→GREEN12；已修复。RB/B/AO36正式组合API+RB12策略周期浏览器历史状态/动作通过，临时服务已退出。
- 当前v32日周60m解释仍旧固定as-of缺口已修，沿用chart meta.as_of及same-snapshot合同，48相关+17邻接测试/typecheck通过；短分钟及explicit旧asof保持。
- scoped候选reference模块499 passed/1 skip；此前完整Newow/reference3273 passed/2 skip、Web800 passed/1skip、SuBing/Alert138 passed。release草稿PR#413已建，尚未发布/切换。
