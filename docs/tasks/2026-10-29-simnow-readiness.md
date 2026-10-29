# SimNow晚盘前只读就绪

## 21:35后：账户接管核验与固定trade候选准备

Owner继续交办第一步账户接管条件核验、第二步固定trade候选准备与部署。v1.16.35
exact `82a8031470009249acccb83b9911a374af70ca00` 的相关执行代码与develop一致，发布树干净；
无新版本发布、正式十服务切换或Broker报撤单。

- 两个不同新鲜原生来源通过原账本重放、交易入口归属检查及内存 `Recover`；权益/可用均100043.92，
  原生和账本持仓/委托/成交、发送claims、待核回调/成交、未释放预留均为0。未把恢复写入运行账本；
  60个品种的新输入门禁保留，不能称trade宿主已接管。
- 已生成0600固定schema2/trade配置及同label `--trade` plist候选，绑定既有账户anchor与原四库；
  现役observe配置、plist、监控绑定已留前像。候选 `enabled=true` 仅为部署目标，文件只落于output，
  未安装或启动，不改变现役 `auto_order=false`。
- SDK无Broker `--trade --check`、四库身份与scope、render/preflight通过；`writer_idle=false`，
  现役observe PID76693独占全局账户锁和原host.lock。账户/dispatch及attempts/blocks摘要未改变。
- 固定候选相关Python回归654 passed（41.18秒），真实SDK结构/假API无网络31 passed；
  独立Review另跑service/recovery ownership 13 passed，未发现确认问题。其结论为准备通过、部署未完成。
- 初次只读窗口脚本提前导入数据库模块导致未携带安全配置；按现役supervisor加载后re-exec修正，
  未改生产配置，未消耗Broker连接预算。21:40权威读回45 TRADING/15 CLOSED，不允许切换。

Owner随后明确选择“仍等夜盘品种全部收盘后切换；无夜盘品种不参与窗口判断”。独立SimNow部署窗口
改为 `simnow_night_only_deployment_window_v1`，以权威Session夜盘元数据确定集合，不放宽夜盘收盘、
账户恢复、双锁或品种新输入门禁。当前夜盘最后Session计划于10/30 02:30北京时间结束；这只是窗口预测，
必须届时新鲜核验，不能当成部署完成或自动启动许可；本次未新增定时任务。

证据：`output/simnow-trade-deployment-20261029/`，第一步原件在
`output/simnow-observe-readiness-20261029/trade-takeover-*.json`。本轮状态为候选已准备、
实际部署等待夜盘收盘窗口。切换前重新核对账户/预算/配置前像，协作停observe、证明双锁释放并取得
`writer_idle=true`，然后同label切换；失败保留四库/claims/block，以兼容同账本的observe或manage恢复，
不重置预算、不补历史信号。真实新信号和开平成交仍属后续独立验收。

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


## 发布与闭市现场（18:26—19:00）

PR540已集成develop，PR541选择性合main；annotated v1.16.35和GitHub Release exact
`82a8031470009249acccb83b9911a374af70ca00`。候选不含develop研究；自身604项Python（56.27秒）、
SDK31及Web生产构建/拓扑再验通过。core五模块mypy及定向Ruff通过；SDK动态import的四项mypy
错误已在v34原样复跑确认，不宣称该脚本全量类型通过。

独立observe通过原安装器更新到v35：旧PID27497协作退出、双锁空闲后安装，新PID76693/run
`b49075a59e01438a9f18bcee7e3223c9`，真实ps、两锁唯一holder与占用、状态时点均读回。
完整账户配置及监控绑定仅改project_root；account/dispatch逻辑hash及旧attempts/blocks不变。
新日20261030尚无连接，WAITING_SESSION/UNKNOWN，auto_order/opening false。

18:05自然源更新18:13:09 passed，60品种一次成功；消费核验进程持续运行至约18:45，旧安装器
plan在installed阶段正确拒绝，未执行停服。其终态newow_d1=incomplete/newow_w1=audited保留。
待进程自然退出后，全新原生cohort `c81c3400d151ab3c50f09f55a1c38f7d6190be8f0d657e1625d0d01116a19e2a`
重新证明60 CLOSED、grace结束和维护互斥，实际switched到十服务gen41。

两次独立读回：API版本35、Web200、十身份matched，六新owner active；Reference 1140/1140 READY，
pending/BLOCKED/UNKNOWN/dependency_wait为0。本次旧gen40六个精确drain经独立Review后取消，
新owner同PID仍active，没有新drain或重启。

全局仍degraded：DB/Redis/Live/盘后源更新正常，但保留苏冰Alert覆盖evaluation_failed与weekly历史
not_run；这不是HTDY偶发推送失败，也不据此宣称全量数据/历史资产健康。本任务不扩展为历史补建或推送补发。

现场证据在主树output/simnow-observe-readiness-20261029/；部署、原生cohort、精确控制收尾和
私有验收读取脚本均分开留存。20:58前未做Broker连接，真实账户双轮新鲜证据仍待发生。


## 19:50 工作树清理（owner明确交办）

- 旧v34按原生计划`801bc174…`完成31个已闭合attempt、71份原件和6个运行标记封存，
  两次一致零引用检查后non-force移除；删除后历史身份验证通过。现役发布树仅release-v1.16.35。
- 已合并Reference/AL任务树由Codex原生归档，246份忽略output原件事先私有迁存并逐SHA256核验；
  只关闭精确闲置工具引用，未停止正式服务。对应本地已合并任务分支已删除。
- SimNow版本源及现场文档经PR542合入develop，主树已快进；133份任务忽略原件也已逐SHA迁存。
  归档工具因“The task's primary checkout cannot be removed.”拒绝移除本会话主工作区，
  不通过Git命令绕过该保护；该树暂留，无未合并代码，不是正式服务源码根。
- JM30 Notion/苏冰研究树保留8个未合并提交，含独立JM30模型、风险2000场景比较、
  冻结案例及Notion规则映射，不属于本次可清理的已完成工程。
- 本次只删已退役源码/已合并分支，tag、Git历史、恢复原件、Canonical、账户和生产配置保持。
