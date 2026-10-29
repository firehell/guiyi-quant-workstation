# SimNow晚盘前只读就绪

## 10/30 02:35一次性执行：v36已发布，切换阻断并恢复observe

本次按owner明确授权执行，未提前切换。02:35:44权威读回为全部60 CLOSED，其中45个夜盘全部结束、
15无夜盘排除，交易日20261030及下一时段窗口通过。main和远端基线仍v35，无其他并发修改。

### 发布与SDK恢复

从origin/main隔离准备release-v1.16.36，仅移植811df7602审查过的12文件及APP_VERSION=1.16.36。
API依赖离线独立构建，API/core来源均为新候选；Web依赖离线安装、类型/生产构建及bundle拓扑通过。
候选695项相关Python通过（48.16秒），固定SDK33通过，四核心mypy、Ruff、offline lock、diff-check通过。
独立发布Review验证12/12文件与工程提交逐字节一致，无其他develop研究，另跑41项测试通过。

SDK第一次检查发现原临时venv缺pyvenv.cfg及METADATA、__init__.py、两份SWIG Python包装，native二进制仍在。
先独占补PEP405元数据，进一步验证发现包文本也缺失；从公开PyPI暂存相同6.7.7.1，写入前按原RECORD
逐文件SHA256核验，只补4个缺文件，原11个有hash文件（含.so/dylib）未改。独立复算15文件全匹配、
无缺失/差异，SDK33重跑通过；未读取凭据、建立Broker连接或改账户。修复原件见sdk-metadata-repair.json。

release PR [543](https://github.com/firehell/guiyi-quant-workstation/pull/543)已合main，annotated v1.16.36
与远端main及peeled commit一致，GitHub Release非草稿，exact
`74d01145f4bcda1192b702f4760c9c0ce73e531a`。main已正常回合并develop，仅带来版本35→36。
发布不代表独立trade部署；正式十服务仍v1.16.35/gen41，旧发布树因仍有真实引用保留。

### 切换、阻断与恢复

为新固定候选生成0600新trade配置/plist，account/state_root/anchor/SDK不变，project_root及API环境绑定v36。
新SDK无Broker检查、四库和60scope预检通过，独立对象Review通过；writer_idle=false与旧observe持双锁一致。
使用正式工具生成60秒计划，02:49:42显式apply，旧PID76693协作退出、STOPPED及双锁释放已证明。
停止过程中最后一轮既有只读账户查询完成，于02:49:54.256追加一份原生快照，历史前缀3247条未变；
offline严格比较完整前像不再相等，返回PREIMAGE_CHANGED，阶段停在STOPPED。
没有进入INSTALLING/START_REQUESTED，没有安装/启动trade、提交订单或改写账户账本。

未重试apply或删除新增证据。按工具既有受限恢复路径，对同一attempt显式--recover-observe，重核
旧release/SDK、原四库前缀/账户预算、配置前像和双锁后恢复原observe。持久阶段RECOVERED，结果
OBSERVE_HOST_RESTORED，retry_permitted=false，原PREIMAGE_CHANGED记录保留。

02:53和02:54独立读回：v35 observe新PID71132/run、同PID双锁、LOGGED_IN/OBSERVING_CLOSED及新鲜只读
核验通过；原账户/dispatch逻辑摘要和原plist内容一致，权益/可用100043.92、持仓/委托/成交均0。
当日连接预算从1到2/3，是正常observe恢复启动，未重置旧预算/block。正式十服务bindings原字节hash不变，
仍v35/gen41；API /health200/version35。auto_order/opening保持false，不宣称trade账户接管或自然交易闭环。

证据在`output/simnow-trade-release-20261030/`，包括SDK修复、candidate-preflight、switch-attempt1的
plan/持久意图及两次readback。结论PARTIAL：发布已完成，第二步trade部署未完成。下一步应在保留
稳定历史前缀、完整账户/预算及新鲜来源验证的前提下，修复停止边界合法在途快照的核验，再做新的候选；
不能复用本次意图或盲目再次切换。原一次性任务执行结束后删除，不新增重试任务。
02:56第二份独立readback保持同一PID/双锁、账户、预算及十服务身份；独立Review对原3247条历史前缀及
account/dispatch摘要复算一致，确认PARTIAL与安全恢复结论。automation simnow-trade已实际删除，未新增任务。

## 22:42：明确授权与一次性任务更新

Owner在已列明“02:35发布本轮最小补丁main/tag/GitHub Release并仅切独立SimNow trade、保留全部门禁
与原账户、正式十服务不动”的选项后，直接回复“授权处理”。携带此新增明确授权证据的原任务更新已成功，
automation `simnow-trade` 保持ACTIVE，时间仍为10/30 02:35北京时间、一次性。其执行范围为已审查工程
811df76022cd86116247ba7847a736485dd16fe4及必要版本元数据，不包含develop无关研究。
任务先现场证明权威夜盘窗口，再准备新固定补丁并通过正式切换工具部署；不得用旧v35冒充新成功证据。
宿主逐项审批、账户/预算/双锁/前像/时间有效期等条件继续适用，未知结果不重试。此前审批拒绝记录保留，
成功更新自动任务不等于未来每项真实操作已经通过审批或已经执行。本次未发布/切Runtime，仍observe。

## 22:35后：三项提前工程交付，发布与切换受宿主审批阻断

Owner明确交办盘口过期定位、一次性切换流程及逐品种执行输入成功证据。工程提交
`811df7602` 仅包含相关源码、测试、执行合同与TESTING，不含develop其他研究；尚无新tag/Release/Runtime。

- 根因调查确认旧NATIVE_BOOK_STALE合并了source age>8和未来时间；旧记录缺ActionDay/源时间及
  book目标回调/终止/返回时点，不能追溯确定AG/J/PB/ZN当时的真实柜台原因。新诊断区分源在查询前已旧、
  查询等待跨8秒及源时间在未来；保留UTC调用/发送/目标回调/终止/返回时点和含节流总耗时。
  未修改ActionDay、8秒门限、3秒TTL、SDK请求、连接预算或重试规则，不宣称盘口问题已现场修复。
- 新simnow_execution_input_check_v1逐品种保留成功/失败、物理身份、五类来源与采样时点、checked/expiry。
  明确只是输入事实，不是订单资格；持久文件不保存current fresh布尔。正式只读reader每次按当前时间/
  宿主状态重算，过期/断线/未来宿主时点不显示fresh。旧v35实际读取为60 NOT_CHECKED，而非60失败或成功。
- 新simnow-trade-switch.py有真实MacBackend与plan/apply/readback/有界recover-observe；冻结新旧release/SDK、
  同账户四库、预算/block、全部native历史rowid/source/payload前缀、配置/绑定、PID/双锁和权威夜盘窗口。
  计划60秒，停止前再验TTL；STOPPED后的offline使用冻结proof但仍要求<30秒新鲜，只有恢复observe允许
  过期证明用于历史绑定。START_REQUESTED后结果未知不自动恢复、不重复apply。具体合同统一见SIMNOW_EXECUTION。
- 最终相关回归695 passed（39.38秒），真实SDK结构/假API无网络33 passed；四核心模块mypy、Ruff、
  diff-check、变更路径秘密模式扫描0通过。两路独立Review的确认问题均修正；覆盖TTL跨界、历史前缀改写/
  删除、STOPPED清proof、过期成功误新鲜、旧SDK/runner恢复漂移及真实临时60品种四库接线。
- 真实机器只运行默认只读plan，SDK/四库/账户/双锁后正确在WINDOW_UNPROVEN退出2；没有生成intent、
  没有执行apply/recover/停启/Broker连接。账户/dispatch逻辑摘要及现役plist与此前前像一致。

原件 `output/simnow-trade-preflight-evidence-20261029/validation.json` 及 `legacy-input-readback.json`。
现役仍为v1.16.35 observe，新的诊断与成功证据需要新固定向前补丁才能现场生效，不能修改旧tag源码。

将“新补丁main/tag/GitHub Release及trade切换”加入02:35任务的更新被自动审批拒绝，理由为现有授权
未明确覆盖将发布和真实切换合并自动执行。未绕过或原样重试；后续更保守的任务更新已成功：保留原02:35
一次性时刻，只读核对并在缺少后续明确授权及宿主认可时报告HOST_APPROVAL_BLOCKED/NEW_FIXED_CANDIDATE_REQUIRED，
不发布、不切换，不退回部署缺少新证据的旧v35。该阻断与用户交办、代码测试、窗口和自然业务证据分别成立。
需要明确确认的后续范围仅为：把已审查811df7602最小补丁形成新固定版本main/tag/Release，再只切独立SimNow；
正式十服务、账户anchor/原四库、数据、风险语义、Scope及通知受众均不扩大。

## 22:01：第三步部署前输入核验

Owner交办开始第三步验证，本次仅只读，不扩大为提前trade部署或下单。用固定v1.16.35的
`scripts/data/htdy_input_admission.py`，经安全配置加载后re-exec执行，冻结cutoff为
2026-10-29 22:01:29北京时间；原件在`output/simnow-step3-20261029/admission-20261029T140129/`。

- 全60历史32根60m预热通过。45夜盘当前1m及22:00完成60m连续、实际主力物理合约、计算32根窗口、
  底层1m聚合逐值一致通过，状态为INPUTS_VERIFIED_WAIT_NEW_OBSERVATION；审计自身不是首见信号。
- 独立只读原signals.sqlite：既有observe自然冻结22:00的45项评估（40项无方向、5项buy），
  状态均OBSERVED，payload hash、product/bar/observed时间身份及bar_end严格早于observed通过，
  品种集合与45夜盘完全一致。无方向同样是合法评估；buy不是订单、Fill或交易授权。
  这些记录来自部署前observe，不能复用为之后trade的新开仓信号。
- AP/CJ/EC/JD/LC/LH/PD/PK/PS/PT/RS/SF/SI/SM/UR历史预热通过，当前1m为WAIT_NEXT_SESSION。
  旧日原始Live不足/订阅不可用，合并计算窗口MARKET_READ_CONTRACT_UNAVAILABLE，仍BLOCKED；
  下一时段应重新自然验收，不能以闭市或Canonical已有历史将旧Live标为通过。
- 22:01:29读取observe留存执行输入诊断：上述15品种及AG/J/PB/ZN最近检查为NATIVE_BOOK_STALE，
  其检查时点在13:44—14:01 UTC范围，不把它们描述为全部当前仍失败。
  无错误条目的其他品种缺少带来源/时点的成功证据，不能以absence推导费率/保证金/盘口通过。
- 定向回归实际执行：HTDY input_admission、closed_source_conflicts、execution_signal及
  SimNow trade_inputs四组，59 passed（3.05秒）；跨原件scope/数量/时间/hash核对通过。
  provider_requests=0、production_writes=0；未建立Broker连接、改变配置/预算/账本或交易开关。

第三步状态为PARTIAL：行情/计算前置45通过，15待下一交易时段；第二步部署后仍须实际trade宿主
新鲜账户恢复、逐品种新输入门禁和即时合约费率/保证金/盘口核验。不能因此宣称只剩15或第三步完成。
02:35第二步一次性任务按本聊天已有授权执行，两步证据分别成立，不将今晚旧信号补开。

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
