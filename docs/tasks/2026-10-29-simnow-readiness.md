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


## 2026-10-30 午间切换准备

Owner明确要求“你把可以先完成的完成下，等中午十一点半收盘我们一次性发布切换”。
不在上午发布或切换；安排11:35重新核验权威午间窗口后执行。源补丁4a8dff27b已集成develop，
范围只有switch工具、其测试、SIMNOW_EXECUTION与TESTING；v1.16.37候选基于main74d01145，
额外仅version.py。此前v36已发布但trade切换未完成，旧意图RECOVERED且禁止复用。

修复包含：真实STOPPED及双FD锁内核验新增原生尾部，所有十项资金/身份/时序/空仓义务逐条验证，
旧native前缀及其余保护状态不变；最新停止证明必须新鲜，不能用过期证明代替。schema v2显式
--window midday，与夜盘政策互斥、不自动fallback。all60权威上午Session结束、当前无Session、
下一实际下午Session>=660秒，才允许计划/应用；day30预算剩余>=1且无block，停服前再次核对。
真实只读发现Calendar ORM detached错误，已在事务内复制不可变facts，并加真实SQLAlchemy回归。

源回归762 passed(40.40s)，固定SDK离线33，独立定向100无skip，Ruff/diff通过，独立安全Review无未解决Confirmed Issue。
证据output/simnow-midday-preparation-20261030/validation-final.json。08:35真实只读midday --check
成功返回WINDOW_PREFLIGHT/窗口未开，非RESULT_UNKNOWN；只是预报，execution_permitted=false，无Broker I/O。
权威预报11:30/11:35 all60 BREAK、下一Session13:30，现场执行必须重新取证。

午间从新固定候选正常main merge、annotated新tag、GitHub Release，再只切独立SimNow同label --trade；
正式十服务v35/gen41不动，原账户anchor/四库/SDK不变，不清budget/block，不造信号订单，不补旧开仓。
新0600私有schema2配置和plist、新0700独占state-dir及60秒内新plan；使用新tag自带正式工具，
显式--window midday。单次持久意图不复用；START_REQUESTED之后结果未知只读核对，不自动恢复/重试。
之前阶段失败按工具有界recover-observe，禁止换工具绕过。宿主拒绝则HOST_APPROVAL_BLOCKED。
成功两轮核验真实ps/exact版本/配置/同PID双锁/run/mode/monitor；只报告TRADE_HOST_DEPLOYED，
账户新恢复、自然输入、真实策略成交仍分别待验，AG/J/PB/ZN根因等待新鲜时序样本。

午间候选已固定推送f99fea8989a1d5aefc9d924f80def54be5c3651f，PR544已准备未合并；候选自身762 passed(49.64s)、离线依赖/SDK退出0、Web构建/拓扑通过，独立候选Review通过。一次性heartbeat simnow已ACTIVE，2026-10-30 11:35北京时间执行；现场失败不盲重试，结束删除。当前未main/tag发布v37、未切服务。

10/30 10:12现场全60品种历史/计算32根、Live与当前1m连续性均通过，closed-source差异0；10:00自然60m的60项observe inbox逐条codec/hash/身份/时间通过，全部OBSERVED。仍非trade首次接收及费率/保证金/盘口通过。当前day30 attempts=3、无block，午间新连接预算不足；保留既有门禁，不清预算、不停服试切。09:25:17原件failure-93d4bb3789bf451d88e444530ed3f998-1902.json记录CONTINUOUS_RECOVERY_REQUIRED，尚不足以单凭此认定第三次连接根因。新只读审计及inbox证据分开留存。

10/30 连接预算只读定位：09:25:17第二轮funds查询SDK接受但0回调、无terminal，15.028096秒超时，
inventory QUERY_TIMEOUT/stage ACCOUNT_SNAPSHOT。现役规则将其视为transport failure，断开后退避60秒；
同PID71132（02:51:44启动，未重启）09:26:29取得新快照，与day30计数3/3且无block一致。
可证明直接触发为资金查询零回调超时，不能据此断言柜台/网络/SDK底层根因。下一权威交易日20261102
预算当前0、无block；10/30今晚21:00开夜盘，现役连接准入最早20:58，不是民用午夜重置。
该预报不证明届时Broker实际TradingDay或登录成功。现有v37切换计划/账户证明/预算硬绑定20261030，
不能直接复用至新交易日，且20:58仅距开盘120秒不满足部署间隔660秒；下一连接窗口不等于可切换窗口。
午间day30预算不足仍阻断，不能清预算/借新日预算/停服试切。证据output/simnow-step3-20261030/connection-budget-cause.json。


## 20261030午间部署额外连接授权

Owner在已完整呈现两个互斥选项后直接回复“方案1”：仅本次午间部署额外1次连接，绑定固定候选和唯一意图，
原day30计数3保持，失败不再重连，全部其他账户/盘口/风险/订单门禁保持。此为次数上限的一次明确例外，
不等于永久改为4次或清预算。正在完成端到端消费路径、定向回归和独立Review，未验收前不得使用。

11:03本轮额外1次端到端实现通过源800项相关回归(48.58s)、SDK33、4模块mypy、Ruff、diff及独立192项安全Review。
初次全套796passed/2failed：observe_bootstrap的asdict误序列化新内部字段；已改严格9字段导出并保持loader严格。
另修startup用民用日期误阻周五夜盘下一交易日，改权威plan交易日，真实run测试通过。
单次grant绑定exact release/config/SDK/account/day/plan/intent/state-dir；START_REQUESTED后才可activate，
首次run独占claim，连接前独占attemptclaim；慢取证/慢fsync/慢factory均重核窗口，过期不触发SDK。
午间原run等待下午PM-120至PM+120的首次连接，VERIFYING/COMPLETE后资格仍绑定同run；原attempts3保持，
block不豁免，失败/重启/重复apply无第二次额度，次日普通3次规则不改。
监控source保留原observe只读身份锚（旧API只支持旧格式），新真实mode从index读取；真实4库兼容回归通过，
没有修改正式API源码或十服务。新候选私有config/plist/state-dir在output/simnow-midday-switch-20261030/，
尚未生成grant或执行意图、未安装启动。等待候选重新固定验证与11:35现场窗口。

11:10最终v37候选2b5c7c8de09b9beabb8223392f99770ef4c72a6c已commit/push，干净，PR544 ready且mergeable。
相对main74d01145恰12文件，11工程文件与37cb281075逐字一致，额外仅version.py37。候选自身800passed52.13s、
SDK33、mypy4、Ruff、uv离线锁、Web类型/构建/拓扑通过；独立候选110及最终exact身份Review通过。
私有config --trade --check与正式service --preflight-trade通过：60/candidate_valid，writer_idle=false因原observe持锁，
broker_io/execution_permitted=false。v37尚无tag前正式工具CANDIDATE_UNPROVEN为预期门禁，不提前造tag绕过；
11:08新工具绑定现有固定v36仅--window midday --check已真实返回全60 TRADING/窗口未开，下一下午13:30。
一次性heartbeat simnow已更新，11:35现场通过后发布新tag及只切独立服务，绑定新config/plist/attempt1与planv3。
此时grant/intent/claim/plan均不存在，未新增Broker连接、未安装启动；候选发布与自然验收仍分开。


## 11:31立即执行及实际阻断

Owner要求取消11:35任务立即处理，automation simnow已删除，不再等待定时。新鲜权威窗口all60 BREAK、
下一13:30通过，距下一Session>660秒。发布前只读_account返回ACCOUNT_UNPROVEN：最后native10:28:04已过期、
实时observe proof无，host WAITING_SESSION/UNKNOWN；10:28:21 NATIVE_MARGIN/NATIVE_FACT_QUERY_FAILED后
断开，10:29:24 CONNECTION_BUDGET_EXHAUSTED形成day30持久block（此前10:12无block为当时快照）。
已批准单次例外不能豁免现有block或新鲜账户门禁，未继续切换、未clear预算/block、未新增连接。

独立发布已完成：PR544 main merge、annotated v1.16.37与GitHub Release exact
5b4bc2004c3cce73d82757816eca9cbfdb978f25，发布tree与已800回归候选2b5c7c8de完全一致，发布树clean detached。
新固定版本正式默认只读plan再次返回ACCOUNT_UNPROVEN、exit2，无plan文件/intent/grant/claim，未调用apply。
原observe PID71132保留、原启动项仍observe，正式10服务v35/gen41不动，独立只读Review同结论。
本次状态PARTIAL/RELEASED_SWITCH_BLOCKED，额外一次仍未用，不报告TRADE_HOST_DEPLOYED。
必须先确定受控账户恢复及预算block处理合同，不能用旧快照或额外1次授权静默放宽门禁。

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
