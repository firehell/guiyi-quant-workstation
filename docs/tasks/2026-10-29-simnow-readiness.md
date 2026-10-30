# SimNow晚盘前只读就绪

Owner明确交办修复SimNow未就绪，目标10/29晚盘21:00前；保留observe、旧账户/dispatch、旧attempts/block，无结算确认、报撤单、Adapter或auto_order。行情/Reference/Scope不改，不用重置预算或账本取得表面就绪。

当前v34/gen40、独立observe PID27497；日29预算3已用尽，日30原生preopen20:58起允许连接，柜台可用性和双轮新鲜快照必须实测。当前只准备工程，不提前绕过连接窗口。

## 根因与最小设计

- prepare/cycle已用project_readback→a.apply在内存核验observe，但只保存native证据；Monitor仍按旧账本readback来源判断complete，因此observe新快照也可能一直partial。
- 新增monitor.json内可选版本化观察核验证明，绑定本run、account、products、native_source_id、当前账本state digest和原30秒有效期；先Evidence.append成功，再原子发布证明。无Evidence schema迁移或新账本。
- Reader核对全部绑定；坏证明明确不可用，缺失保持兼容待核。新增observe_reconciliation_ready/status单独显示，不OR进原complete、不改变预算、position_projection_complete或旧readback_status。
- UI分开显示只读核验、账本投影、执行输入；等待Session不能伪装Broker已连接。断线、停止、重启、trade/manage模式、过期和未知回报都不能显示observe ready。
- 两条旧失败：10:15 positions第二轮零回调超时；10:30标记ACCOUNT_SNAPSHOT但inventory八项完整、gateway为NATIVE_FACT_QUERY_FAILED，不能推断具体回调根因。只修可证明且隔离测试复现的路径，不抹去历史诊断。
- 产品查询已知拒绝/流控与全局连接错误需严格区分；未知ErrorID、身份/账号/作用域、超时/断线仍fatal，不新增重登/即时重试。

## 执行与验证

隔离开发→定向回归/固定SDK无网络→独立执行安全Review→选择性向前补丁及部署；避开18:05自然盘后任务，正式切换须原生窗口/维护门禁通过。20:58由既有宿主原生连接日30，双轮不同新source账户对账成功才报告观察就绪；新盘口/自然信号另验。柜台不可用保留具体阻断，不降门禁。

Owner最新口径：偶发推送失败/过期在事件及结果已落库时只保留记录，不作为影响行情、计算或整体就绪的故障；不补发，本任务不处理这些推送。


## 最终隔离验证

- SimNow credentials/supervisor/host/execution/HTDY/monitor及三个API测试：604 passed（47.95秒）。
- 固定真实SDK结构、假API无网络：31 passed；Web监控定向：12 passed。
- 独立安全Review发现并已修正TTL后假就绪及同轮gateway fatal吞没，复核无未解决Confirmed Issue。
- 今日18:05盘后任务自然运行，18:13:09 passed、一次成功；本任务没有重跑。
- 以上不证明今晚柜台可用或真实账户核验完成；20:58窗口另验。

## 12:55 统一发布与待恢复trade实际执行

Owner明确批准本轮完整方案：十服务和独立SimNow统一固定版本、单发布树，
SimNow允许带待接管状态部署，仅对冻结day20261030预算block作本次唯一许可例外。
这项新授权替代此前“正式十服务不动”的范围；不改变策略/账户/风险及输入年龄门禁。

- PR545已合main，annotated v1.16.38/GitHub Release exact
  `e026ad367f341a2e08df4a47b229b951c9acefd3`，候选090808bb1与发布tree相同。
  固定发布树`.worktrees/release-v1.16.38` clean detached，main回合并develop。
- plan v4/permit v2冻结四库/原生历史前缀/配置/SDK/预算block；全账户独占stamp和首次run/attempt持久领取，
  不支持旧plan混用。pending从Supervisor/Host/Adapter分别阻止订单类操作；同连接结算、归属、
  资金/持仓/委托/成交及新鲜Recover通过前不解除。旧native仅历史锚，不证明当前账户为空。
- 源841 passed(58.76s)、固定最终树841 passed(66.06s)、真实SDK结构假API无网络33 passed、
  mypy8模块、Ruff、cohort/retention/bindings299 passed(20.06s)、Web14/类型/构建/拓扑通过；
  两路独立安全复核及固定候选Review无未解决Confirmed Issue。移动后重建离线venv，旧v37路径残留0，
  config/SDK与service preflight复验通过。实际摘要在validation.json。

### 分开执行结果

新鲜午间全60无Session、下一下午13:30且>=660秒条件通过。正式cohort计划
`405f1d68e5c3584a99857185989b0fc29b84db91c7bc442716214bd6a409cc6c`
仅apply一次，在claimed/prewarm取消，effects={}、未停止或安装任何正式服务，未CAS。
该计划已消耗/过期，不得再apply。十服务12:55实际身份均matched v35/gen41，API/Web通过，
Runtime健康失败，不能称RUNTIME_READY。

Reference预热失败已由两路只读诊断确认是HTDY FU60m `OBSERVATION_GAP`。
checkpoint seq8/expected8、32根窗口的31个移位重叠端点一致，合约/交易日/owner/calculation segment相同；
10/29 03:30Z close5418→5420、volume122620→122629，06:30Z volume110773→110764。
两份原件均completed_live/realtime，均未保存dataset_revision；不是Decimal格式差异或缺Bar端点。
当前physical MDS查询DATASET_OR_PARTITION_MISSING，不能猜测Canonical与任一窗口一致。
`rqdata_live_history_revision_v1`的逐对修订证据不豁免原窗口冲突，现实现有适用身份亦不含HTDY；
不得忽略volume、数值容差、reset窗口、制造中断、改原件或重放通知来强行过门禁。

SimNow部分按独立失败边界继续：正式switch plan
`c49f2326982b482fbf06a2a3771ee01a082d524cc95e112c2a002a86f5f3dffe`
只apply一次，intent COMPLETE/HOST_SWITCH_VERIFIED。原observe PID71132协作退出后双锁释放，
锁内历史前缀/账本/budget/前像通过；安装同label并启动v38 --trade，两轮真实读回成功。
12:54复核PID57727、同PID双锁、run `7c4ff0253c1b420cb055d847ec5c4cb0`、实际exact版本/配置/plist绑定，
mode=trade、WAITING_SESSION/UNKNOWN、account_takeover_pending=true、opening_enabled=false。
API source只读身份配置已指新发布根，实际模式从实时index读取。原四库/SDK/外置账户anchor保持。
两日原计数各3及预算block均保留；许可run-claim已领取、attempt-claim尚无，未新增连接。
权威下午连接准入13:28–13:32；许可过期/失败/断线/重启不返还，不由本任务另建定时器或手工probe。
部署结论仅TRADE_HOST_DEPLOYED，未通过新鲜账户接管、trade首见执行输入、真实策略开平或恢复验收。

### 发布树收拢

v37原候选树按原生Git worktree move成为v38；v36无非Git必要运行原件且无有效引用，
两次一致cleanup-plan `a4192f3a1e160e41106f9f8f2a2f3aa04daa317064adeba3495f8a731a3f8998`
均eligible/references=[]，正常non-force git worktree remove完成。
未移动旧tag、删Git历史、账户、行情或日志；develop与JM30研究树保留。
仍有v35/v38两棵发布树，v35承载正式十服务，不得为单树目标强删。

总体PARTIAL：发布完成、SimNow待恢复trade部署完成；正式十服务切换及最终单树阻塞于Reference源冲突。
最小下一步是基于保留原件和权威来源解决HTDY窗口改值，再在有效休市窗口生成新的cohort计划。
证据统一在`output/simnow-unified-takeover-20261030/`，失败、发布、SimNow及Reference诊断各自留存。

## 13:33 下午开盘保障及自然账户接管

Owner要求先保障13:30开盘，未进行Reference park/恢复或发布切换。正式十服务v35/gen41身份均matched，
所有常驻owner仍active，无当前代际drain；API/Web、DB/Redis正常，v35/v38固定源码tracked clean。
13:31首根自然1m及13:33连续性检查均60/60真实收到，订阅60、TRADING60、Live coverage60ok。
日内Alert无失败项；周线60条既有evaluation_failed与日线1条warming未冒充通过，整体Runtime仍degraded。

SimNow保持同PID57727/run `7c4ff0253c1b420cb055d847ec5c4cb0`；13:28:02.849771
按既有许可唯一消费额外attempt，未手工Broker probe/重连/重启。
13:30后账户接管pending已由真实同连接恢复清除。13:31原账本只读重放通过，phase READY/readback_valid=true，
新native13:30:59、有效期30秒，订单/成交/预留/未核订单/blocked products均0。
13:33:28独立复核global SimNowLocks和原host.lock真实排他锁均为PID57727，monitor/runclaim/attemptclaim
同PID/run；native13:33:19约8秒且持仓/委托/成交0，TRADING/LOGGED_IN、pending=false、opening=true。
普通day30次数仍3，原CONNECTION_BUDGET_EXHAUSTED block未清，grant不返还/迁移。

结论：开盘行情链路和SimNow新鲜账户恢复已真实取证；逐品种trade新输入、自然60m信号与真实策略
开平成交仍待发生，不能以opening=true或账户恢复代替第四/第五步。
Reference48旧窗口冲突仍独立阻断。Owner已选择冲突处中断20笔参考OPEN、保留旧原件并以48条
新修订FLAT/未来起点恢复；实现仍只在开发分支，未生产执行，交易期间不强切。
本轮证据 `output/opening-service-check-20261030/`，没有新增自动任务或通知受众。

## HTDY冲突中断重建：实现及候选验证

Owner明确选择中断重建，保留所有旧记录，20笔参考OPEN明确数据冲突，48受影响流以空仓、
未来起点的新修订恢复。原始差异不是时间缺口：158根/213字段变化全部等于新捕获窗口与当前Canonical，
48路1m/60m物理hash、质量和发布来源通过；此前MISSING系游标超已发布coverage，未认作分区损坏。
真正未解决Inbox为238条（48 BLOCKED/OBSERVATION_GAP、190 PENDING），另5条真实CALCULATED独立保留。

新增正式`htdy_conflict_recovery_v1`模块、原生MDS验证器及独占计划CLI；固定48流和20个OPEN stream
digest，并冻结20笔稳定trade ID/旧revision/checkpoint/open payload hash，拒绝漏项/第21笔/等数量替换。
旧OPEN通过真实typed控制边界追加DATA_INTERRUPTED版本并记录DATA_CONFLICT原因，无退出价格、收益、
新action、旧capture消费或Inbox CALCULATED。旧trade全版本及新增MVCC整行严格绑定；新修订FLAT、
空策略窗口、未来共同起点、普通block策略。旧原件/状态不改，typed退役独立验证后仅退出未处理排序，
新修订正常依赖推进后仍保持历史证明有效。UNKNOWN、晚于未来起点的原件、receipt/源/前像漂移均拒绝。

CLI默认无动作，不加载凭据。真实park/plan/apply需干净annotated exact tag、全60休市且fresh clock
距下一Session>660秒、Reference stopped writer真FD锁和MDS维护lease；单次持久claim前无业务写入，
unknown只读核对，不重试。恢复成功仍保持Reference parked，交由支持typed退役的新cohort接管。
SimNow38当前run/已消费许可不迁移、不返还；代码修复不授权或制造额外账户连接。

定向最终64 passed，独立安全Review81 passed且无剩余Confirmed Issue；来源13项、CLI21项通过。
扩大Reference1281 passed/10 skipped/113 deselected（非本次隔离/人工Gate不冒充通过），
cohort/部署/retention286 passed。初次扩大两项worker日志路径不隔离导致RUNTIME_LOG_UNSAFE，
显式任务私有测试日志目录后worker45项及扩大回归均通过，未修改生产日志权限。
真实PG任务隔离16489的既有0053/0054触发器上8 passed，验证48路原子/全回滚/UNKNOWN/原件不可变、
真实OPEN中断及价格/holding/旧valid_to篡改拒绝。4模块mypy、Ruff、diff检查通过。
当前仅CODE_COMPLETE/TEST_COMPLETE/REVIEW_COMPLETE，允许集成develop/进入候选，未发布v39、未生产恢复。
新候选从main/v38仅移植本次补丁及必要版本元数据，不带develop其他UI/研究。
交易期间保留现役35/38；正式切换仍须现场休市与cohort/新鲜接收证明，不能用实现完成替代。
