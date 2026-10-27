# 当前状态

本轮控制器采样窗口及verified诊断修复已通过测试和独立Review，未发布或执行恢复。运行现场仍为10/27停驻态：controller v1.16.18已发布，原生恢复通过intake并启动Feed，在verified失败后重新停驻；实际绑定仍v1.16.14/gen31，原定时服务未恢复。下方旧任务记录是历史证据，不代替本轮现场。
历史发布、失败 attempt、数据修复和候选验收原件继续保留于 `docs/releases/`、`docs/tasks/`、
`docs/research/` 与原 output/outputs。旧版状态正文可从 Git `3bc2db867:STATUS.md` 追溯，
不将旧检查点的“未发布”“下一品种”或旧 PID 当作当前状态。
产品与能力见 [PROJECT_SOURCE](PROJECT_SOURCE.md)，合同和验证见 [架构](docs/ARCHITECTURE.md)、
[TESTING](TESTING.md)。开发完成、发布、Runtime 切换与自然业务验收分别成立。

## 10/27 控制器采样及诊断修复验证完成，正式服务仍停驻

已复现并修复t0活性样本到t31提前失败：逐次保留全部context/原件/routes及ACK/数据库非回退链后滚动采样，
仍须两轮不同且30秒内新鲜的cycle，最终身份校验后再次核对freshness；原120/240/600秒预算不延长。
verified新增固定子步骤及合法时间诊断，不记录任意异常原文、不改旧unknown；上次C真实失败原因仍未确定。
扩大369项含本次隔离PG/Redis无跳过通过；独立175项含真实依赖无跳过通过，Review允许集成develop。
12:46–12:47独立确认Feed同v14/gen31/PID40577、parked、drain固定、锁free及两次tail/ACK稳定；
exact v14正常parked必经reader关闭路径。关闭heartbeat当前缺失，未留存可读取的关闭快照，不冒充当前provider/订阅/缓冲的typed证明。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；本轮未发布、未启停服务或重跑恢复，不声明RUNTIME_READY。
下一步是补齐上次含Feed effect的C失败前缀及新鲜关闭证明，再生成新的精确恢复计划；不能递归套用原A/B入口。
证据和限制见[唯一恢复记录](docs/tasks/2026-10-26-rollover-readiness-inbox.md#1027-控制器活性采样窗口及verified诊断修复未发布未执行恢复)。

## 10/27 当前版本恢复尚未闭环：已确认Live卸载，待从消费者启动继续

controller v1.16.15/16已独立发布，运行绑定仍v1.16.14/gen31。controller16新计划94f864cb完成freeze后，单次Live bootout后的读回进入outcome_unknown，未进入消费者/Feed启动。10:14原生独立读回确认Live/Feed定义缺席、7个已观察PID全部退出、owner锁空闲；其余Alert/Reference/API/Web仍gen31 parked。旧owner文件中Live active是过期记录，不代表实际进程仍运行。
10:16数据库读回：completed1031、PENDING336、WAITING_HISTORY4、BLOCKED35、UNKNOWN0；准备READY43/READBACK_REQUIRED80/WAITING_DEPENDENCY159。原件、游标、两层unknown记录均保留，尚未恢复正常采集。
最小下一步：完成绑定此精确已确认前缀的continuation入口及反证测试/Review，发布controller17，新计划从consumers开始，禁止重复bootout；真实新Bar与完整业务验收另列。


## 10/27 SimNow账户只读实测通过，只读等待服务已启动

实现一个账户锁/进程/CTP连接、共享60品种信号inbox及原账户资金预留，启动/日切/断线先完整原生读回，
持久连接次数预算与未知结果阻断，不初始化或复制旧AL账本。只读observe默认；manage只接管既有平仓/撤单，
ManagedTickV1在生成OPEN及预留前禁新仓，auto_order=false。Keychain隐藏本机配置与独立observe LaunchAgent已实现，
自动入口固定--observe-only，不改既有十服务、不发布或切换正式Runtime。

初版PR507已集成develop。现场向前修复launchd扩展卷stdout的EX_CONFIG，以及默认Redis URL漏补认证；
私有用户日志可用、真实Redis及60品种权威Session计划通过。前台与同一launchd label的后台Keychain加载均通过，
零Broker探针exit0，原plist已逐字节恢复。首次接管的attempt1泛化故障保留，未取得完整快照。
09:34:43显式有界账户只读诊断消耗attempt2：客户端认证通过，柜台LOGIN_REJECTED/ErrorID=3，auth/login各一次，
四类查询均未开始。诊断原件在Release前落盘，连接已释放；旧AL账本SHA与block行完全不变，native快照仍192。
以上拒绝记录保留，不能被后续成功覆盖。owner在本机更新Keychain后，10:15:38显式attempt3已认证/登录成功，
资金、持仓、委托、成交各两轮完整且内容一致：权益/可用均100000、保证金/手续费0、持仓/委托/成交返回0条。
原件SHA f60800ca66c40ef4c6f51ea04edfab28765fa050751287536a8b904dd7130dc2已绑定同账户Evidence/source，
独立复核通过；Release成功，native快照增至193，账户文件SHA及原block不变。

独立Review允许激活已交办observe-only等待服务；已安装label单进程running，enabled=true/opening_enabled=false。
10:25只读读回为WAITING_SESSION/connection UNKNOWN，day27 attempt3及原block保留，没有追加第四次连接。
依当前权威Calendar/Session预测，今晚20:58进入TD20261028允许连接窗口、21:00开盘；预测不是自然运行证据。
新日仍须重新完整原生读回，旧信号不补开；本次未启用管理/新开仓，不声明持续接管或交易闭环已通过。

当前357项定向/扩大回归、Ruff/format、secret0、diff通过，分阶段独立Review允许集成；真实SDK无网络23项及既有
账本只读重放证据保留：实际317条journal commands，另1条initial receipt，合计318 receipts（修正先前混称318条命令）。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；一次柜台完整只读核验及本机等待启动已验。
持续宿主的新交易日自然接管、全品种新输入、断线/重启及首笔订单分别待验；未确认结算、未报撤单，
未变更正式十服务Runtime，不声明整体RUNTIME_READY。
合同与验证见[SIMNOW_EXECUTION](docs/SIMNOW_EXECUTION.md#全品种持续宿主simnow_continuous_v1)、
[任务记录](docs/tasks/2026-10-27-simnow-continuous-host.md)。


## 10/27 v1.16.14已发布且绑定已切换，postCAS验收阻断并停驻

PR505/506已发布v1.16.14 exact5587cd1483a43ef591ee686ebd4cc53606d201b0；247项回归与独立207项/0跳过通过，8956原件完整只读扫描通过。
全新原生计划完成预热/原件/schema复验并CAS十服务至v14/gen31，v2已由新owner独占active。08:49达到下一Session>660秒边界，因旧验收仍要求全部原件接收追尾，原生outcome_unknown并停驻；Feed未启动、日历未恢复，不声明Runtime切换闭环或RUNTIME_READY。
已接收原件/游标保留：completed1031、WAITING4、BLOCKED35、PENDING336；接收无intake_error。计算阻断与准备READBACK_REQUIRED分别只读定位，不清记录、不盲重试、不回退旧语义。
唯一下一步：完成接收存活与积压追尾分离的验证合同及postCAS独立恢复证明，按原生流程向前恢复。详见唯一任务记录。

## 10/27 主力切换向前修复已发布，Runtime交接受维护锁竞争阻断

v1.16.12经PR501/502已发布exact3426d89763bb107ef00ee6381b0a3e1e7da66997；0053及原件保留事实不变。
第二份原生计划仍在停服前prewarm取消、effects为空。新协议仅requested，未active；十服务仍v1.16.10/gen30。
已实测分组共享输入候选的真实预热：120.033秒、985次维护锁忙（约98秒等待）、54次缓存命中，仍按原期限拒绝。
分组缓存及真实policy隔离修复最终227项/独立217项通过，PR503/504已发布v1.16.13 exact
be9c1a8dde70aa5db4716304aad33d7a7e7241ad；正式树构建和来源验证通过；不减少Scope、延长Gate或中断另一项历史更新。
04:42独立读回十服务仍v1.16.10/gen30、两张inbox表均0行、准备预算/attempt为空，旧游标1793019905299-0与原件尾1793039404268-4未改。
原件接收/EG自动准备/逐流追上及重启业务验收仍未完成，未声明RUNTIME_READY。
唯一下一步：维护资源释放后，重新读回现场并生成全新原生计划完成交接；旧失败attempt不复用。

## 10/27 凌晨主力切换方案已发布，原生交接预热发现正常启动边界待向前修复

v1.16.11已通过PR498发布，exact397fbd1423fac4d5a6257121631852332a04d3a6；正式树构建与依赖来源已核对。
03:05生产0053独立读回完整，无重复迁移；十服务仍v1.16.10/gen30。原生cohort v1在停服前cancelled，
effects为空，COHORT_CANDIDATE_WARMUP_FAILED；不能把发布当作切换。独立Alert预热413计算/7 warming通过；
Reference失败精确定位为M/苏冰1w只有原始seed、尚无自然计算时错误要求两批前像。

向前候选1.16.12修复闭市权威Session owner准备及完整flat seed初始化证明；接收运行与计算健康分层的
v2原生只读证明已完成独立Review；最终冻结387 passed（真实隔离PG/Redis），候选待集成发布。原件8956条只读私有导出留存，10/27游标仍1793019905299-0，前后相同。
EG2701已只读冻结当前需求：owner10/27、历史截止10/26、上市1/28；首5m原生计划10次provider、72414预期Bar，
尚未执行下载。新协议未启用、Runtime未切换，无通知补发或账户变化。详见唯一任务记录。

## 10/26 主力切换准备及Reference耐久接收候选验证完成

已实现正常换主力的预算准备、逐品种权威等待隔离、不可变原件与冻结投递、DB确认后ACK、
逐流公平计算和延迟原件恢复。0053仅新增两张表与不可变保护；兼容默认旧接收协议，原生独占交接后才激活v2。
不改变公式、换月交易、账户、通知时效或Scope。现役1080路：苏冰六周期360、Newow三周期720；HTDY未启用。

CODE_COMPLETE／TEST_COMPLETE／REVIEW_COMPLETE；任务提交69420d5a5，已合并最新develop依赖，
合并候选定向324 passed（真实隔离PG/Redis）、扩大Reference等1553 passed；独立Review允许集成develop。
Web type/build/topology、OpenSpec12/12、secret0、Ruff及diff通过。1553扩大回归与最终324核心回归分别留证，不混称生产验收。
PR497已集成develop exact31628cfa1；23:25生产0052→0053单次迁移成功，独立schema/约束/触发器读回确认，两表均0行。
接收仍为旧协议，兼容发布、Runtime及v2切换、EG真实历史/原件恢复与自然新Bar验收待执行；正式运行仍为下方v1.16.10/gen30。
休市cohort要求60品种权威休市且下一Session>660秒，夜盘中不能绕过。首个v2持久接收后仅兼容恢复或前向修复，保留原件及游标。
详情见[任务记录](docs/tasks/2026-10-26-rollover-readiness-inbox.md)。

## 10/26 苏冰六周期已发布并激活，完整历史构建与自然记录待收尾

正式PR489／annotated v1.16.10／GitHub Release exact `a80753c3cf32fb2759920d26f88a1ba6cbc8ea02`，
十服务统一 `/Volumes/扩展盘/guiyi-quant-workstation/.worktrees/release-v1.16.10`／gen30。
v6原生switched；独立identity十项matched，API/Web200／1.16.10；两次读回间132.5秒六常驻PID不变。
全局runtime health仍degraded，不声明整体RUNTIME_READY。旧v3/v4/v5取消及恢复原件保留。

operational60×六周期v2已原子激活，360receipt、每周期60路；20:55开始只接受之后自然confirmed输入。
20:11独立DB读回capture/action/trade均0、flat初始化；不将health=READY或激活当作自然记录验收。
剔除授权新增身份后，Alert/通知policy/schema/其他ReferenceScope保护hash与v6前像相同；无推送、订单或交易阶段变更。

完整历史自2023（新上市按权威起点）继续：日线60/60截至10/26完成；周线39原件保留＋JD新增完成，
共40有资产／20路原生来源不足显式阻断，不补造缺价周；其余分钟按精确计划顺序构建，20:45前取消并留resume。
AL日线真实43批／42compact引用完整digest校验通过；正式历史API在既有<=366天查询窗200/persisted，
全量资产query_since仍2023-01-01、cutoff10/26。范围未缩短。原AL15m candidate不覆盖。

开发8002/5175已重载1.16.10，消息苏冰仅六周期及全部周期、无1m，页面保留。
验证与精确结果见[任务记录](docs/tasks/2026-10-26-subing-six-periods.md)，真实计划/原生报告在
`output/subing-six-periods-20261026/`。下一步是完成可证明的剩余历史及其控制状态核对，等待20:55后自然新Bar；
周线新自然记录须等待下一根已确认周线，不通过回放制造实时记录。

## 10/26 苏冰六周期及完整历史存储已发布，正式切换受盘后任务占用阻断

苏冰参考支持5m/15m/30m/60m/1d/1w，新增5m/W1历史身份；新持续记录策略使用
`subing_physical_prefix_forward_v2`，只预热指标、不继承历史持仓，沿用耐久journal、原子激活和原后台刷新线程。
六周期页面已可读取实时参考面板，消息移除1m；不回退历史重算，不启用推送或订单。

独立高风险Review通过并已集成develop `7bd191c41`。非PG回归995 passed/9 skipped/78 deselected，
隔离PG/Redis78 passed/0 skipped；补充周线service/API49 passed；Web1240 passed/3 skipped、
六周期浏览器1 passed；type/build/topology、Ruff、OpenSpec12/12、secret0和diff通过。

operational60×六周期完整扫描：296份计划、64路源/预算阻断，另46份计划超过原生CLI16MiB。
owner已选定保留2023年以来完整历史。新增有界分片计划与同版本来源清单锚点，
保留原逻辑hash、交易口径及旧inline资产；隔离PostgreSQL等102项回归通过，独立Review允许集成。
新格式正式写入前先升级读取端，不绕过CLI边界、不静默缩窗。CJ2305已分类NONPOSITIVE_CLOSE周线前缀保持数据不足，不补造Bar。

39个W1历史资产按精确原生计划构建并独立读回READY，统一截至10/23 15:00；RB/JM历史API读回200/persisted。
已完成项不重复构建。其余历史未写入，苏冰forward启用数独立读回为0；本地develop8002/5175已加载代码，
正式十服务仍保持v1.16.7/gen29；v1.16.8已由PR487/main与annotated tag发布，
exact `9b559ce80b968f214347aa49abdb4d649aff915d`。正式树依赖与Web build/type/topology已验证。
原生v1计划先因盘后进程运行拒绝；该自然进程随后退出，消费者结果incomplete。
v2计划放在公共临时目录，在安全读取前拒绝，未创建attempt；改为0700私有目录后，
全新v3计划通过，但Reference只读预热等待Canonical维护锁120秒超时。v3 attempt
`3fe300223ac7ae36cdd2a1ef567cc94e942bedaacdb482c76d15da3da857469d`
已cancelled、effects={}，未停服/未CAS，不复用。锁由现有
`output/data-complete-audit-20261026/parallel-full-audit.py`全量只读审计持有，最近59/60。
45路只读重新规划均SOURCE_BUSY，无新历史写入。360路持续记录精确计划已生成但未apply；
尚未生效的20:55开始意图不能当作已启用，过期需重做。新存储表示必须等正式读端切换后再生产。
合并候选1206 passed/9 skipped/79 deselected、隔离PG/Redis102 passed、canonical一致性18 passed；
独立Review另验后端69 passed/9 skipped、Web103 passed。开发预览8002已读回1.16.8，5175保留。
不声明自然六周期记录验收完成。
证据：[任务记录](docs/tasks/2026-10-26-subing-six-periods.md)，实际扫描/构建原件在`output/subing-six-periods-20261026/`。
并行审计已最终60/60 passed且锁为空。全新v4完整预热通过（Alert413/7warming、Reference480、
其余四服务通过），日历暂停后drain步骤取消、未CAS；原日历已恢复。十项现场matched仍v1.16.7/gen29，
Feed恢复PID40179，其余五常驻PID不变。原控制器未保留具体拒绝码，先补齐安全诊断；
1.16.9候选191部署回归及独立Review通过，仅增加失败阶段/协议码留证，不声称已修复drain。
下一步：发布已验证诊断补丁，用全新计划定位并解决排空拒绝，再切换读端、完整历史及六周期激活。

## 10/27 AL有界恢复运行正常结束；自然新Bar无方向，订单成交验收待信号

本次原账户AL2612恢复通过，未重新initialize；run fc5b135dde5948ef98adabf585eb93f2 在00:14:08正常退出，
CONTROLLED_RUN_ENDED、监控STOPPED/RELEASED。00:00自然完成60m Bar于00:00:17.768813首次处理，
持久Signal directions=[]，没有买卖方向；没有补开23:00或历史方向，没有人为制造测试信号。

累计账本317条命令（Readback190/Tick124/Disconnect1/Recover1/Signal1）纯重放与投影逐值/摘要一致，
累计192份原生快照（包含此前初始化运行的13份）逐来源hash和非重叠时间核验通过。全部原生持仓/委托/成交零行，
权益及可用100000、保证金/手续费/净现金流0；dispatch claim0、订单/成交/预留/待核事实及清仓义务均0。
本轮179次循环中66次空账户旧报价等待，没有使用旧价或延长执行期限，其余正常Tick；8秒上限保持。

退出时phase READY、position_projection_complete=true，最后原生快照00:13:59.053031、账户读回有效期至00:14:29，
不代表之后当前读回有效或可以复用报价下单。代码及补丁仅develop，无发布/正式Runtime切换或持续自动交易。
独立只读Review复核317命令、192快照、同run监控及有效期通过，0个执行effects；
恢复/自然输入/无方向保持空仓/账本对账已实测，真实报单、撤单、成交及实际成交费用仍未发生，broker_e2e_passed=false。
不能将本次无成交的零收益当作策略表现或订单端到端通过；后续需要新合格买卖信号窗口，不自动延长或创建新任务。

原件output/simnow-controlled/run-20261026-161408-821871.json，SHA256
0efea7fa60ec7a62528eed45b38a53523b19a2a694d3c0db4b454f838bc2bc86；独立核对
output/simnow-controlled-al-20261026/final-independent-readback.json。此前失败和初始化账本保留，不能删除重建。

## 10/26 AL恢复在账户稳定快照前置再次停止，追加协议诊断待定位

23:21:44实际恢复入口返回FAILED_NO_EXECUTION_PROOF / NATIVE_STABLE_SNAPSHOT_REQUIRED，
native_failed=true、原生合约/费率查询记录为空，尚未到原run的账本接管及结算/发送分支；旧监控仍22:48 RELEASED。
现有journal不得删除或重新initialize。此报告未保存内部资金/持仓/委托/成交失败阶段，不能猜测柜台原因或判空仓。
新增纯只读inventory_diagnostics保存固定状态/阶段、SDK码、回调/终态及超时计数，无账户行或凭据，
请求和等待/失败/恢复规则不改。218模块、23SDK、Ruff/secret0/diff及独立Review通过；故障原因仍待新观测定位。
没有宣称已恢复运行、已报单或端到端通过，不发布/切Runtime。

## 10/26 AL实际初始化/结算确认后零报单退出，接管恢复待验

22:45:36已创建原专用账户本地journal，必要结算确认一次完整返回；运行在22:48因AL2612盘口年龄8.174443秒
超过owner确定的8秒停止，CONTROLLED_RUN_REQUIRES_RECOVERY。订单预算使用0、dispatch claim0；
只读重放24条命令（Readback12/Tick11/Disconnect1）与投影逐值一致，阶段RECOVERY_REQUIRED、readback_valid=false。
13份原生快照中最后一份22:48:14：权益/可用100000，保证金/手续费0，持仓/委托/成交完整零行。
没有订单、成交、预留或本地持仓，不能把已有账本当成已完成真实报单；不能再次initialize或删除重建。

owner已改选23:20后恢复AL单品种，等待00:00新合格信号；仍最多45分钟、一手、一次提交。
新增simnow_bounded_host_v2，只在完整已核验且无任何账户义务时，旧盘口跳过Tick/发送，继续有界对账；
不放宽8秒、不使用旧价、不延长期限，初始预检/恢复保持严格，有订单/持仓/预留/未知事实则原恢复处理。
218模块、21SDK、Ruff/secret0/diff及独立Review通过，额外WORKING订单旧盘口验证保持预留并退出恢复。
原报告run-20261026-144817-734034.json、独立账本核对output/simnow-controlled-al-20261026/first-run-independent-readback.json保留。
新恢复候选未执行，00:00自然信号/实际订单/成交对账待验，未发布/切Runtime或启用持续交易。

## 10/26 AL一手受控尝试在前置停止；owner将来源年龄上限调整为8秒

owner明确选择AL单品种、最多一手一次提交，权威主力AL2612，下一H1端点23:00、夜盘至次日01:00。
22:39原候选在前置以NATIVE_BOOK_STALE停止：AL2612精确唯一、交易日匹配，但来源年龄5.922269秒超过原5秒。
实际尚无账户/发送SQLite、监控索引、结算确认或订单；不能把它当完成受控运行或失败报单。

owner随后明确接受来源年龄不超过8秒。新simnow_native_input_v2 / simnow_ctp_controlled_v2采用接收年龄<=8，
未来或>8拒绝，原接收后3秒有效期及所有其他门槛保持，版本/参数进入来源及动作hash，旧证据不改写。
212项模块、21项SDK及Ruff通过；新候选实际结算/报撤单/成交仍待现场，不启用持续交易或发布切Runtime。

## 10/26 RB2701单品种只读预检现场验收通过

22:26实际报告READ_ONLY_PREFLIGHT_COMPLETE，原生交易日20261027；与前序原生/Python核验同一账户，
再次观察10万元初始基线。合约资料12行、保证金1行、手续费1行、盘口33行均完整终态返回。
RB2701/SHFE盘口唯一匹配、交易日正确，来源年龄2.306244秒；当次买一3021/卖一3022，
多空保证金率0.16，一手开仓手续费预算3.02200。原生费率空ExchangeID保留，以完整QUERY_SCOPE绑定，
没有改写原始回报或金融数值。独立读回核对账户身份、完整性、报价有效期、费率和Decimal预算，全部通过。

代码已由PR492/493测试及独立Review后集成develop，未发布或切Runtime。实际结算仍未确认，
orders_sent=0、auto_order=false、broker_e2e_passed=false，未初始化交易账户。此为当时观察，
报价有效期仅至22:26:02.806244；不能复用旧报价报单，也不能视为全品种或持续自动交易验收。
真实报告SHA256：0c444cdbcddb586032b33b6847838bbe17d5935c6c47383227235ca1122d93f5；
本地原件output/simnow-controlled/run-20261026-142608-788384.json，独立核对在
output/simnow-host-preflight-20261026/accepted-preflight-independent-readback.json。
下一步为明确交办后的受控一手端到端验证，含新的执行预检、必要结算确认及新合格信号，不自动启动。

## 10/26 RB2701盘口现场通过，费率空交易所已定位并修复待验

22:12/22:16两次只读观测均证明RB2701在33条盘口中唯一匹配、交易日正确，年龄分别1.961831/1.950599秒，
盘口选择与原新鲜度校验实际通过；随后NATIVE_RATE_IDENTITY阻断，尚未完整预检。
脱敏费率观测确认margin/commission合约rb2701与Broker均匹配，但原生ExchangeID均空；
绝对投机保证金率多空0.16、按手0，手续费按金额0.0001、按手0。原始值保留，不据此启用交易。

新增native_rate_query_scope_v1，在显式交易所/合约请求及完整回报后绑定上下文，仅此可解释空ExchangeID；
原生字段不填造，非空错交易所、错合约/Broker/上下文仍失败。预检及循环同口径，来源hash包含上下文。
21项SDK及208项模块、Ruff通过，现场完整预检仍待新观测；没有报撤单、结算确认、初始化、发布或Runtime变更。

## 10/26 RB2701盘口批次精确筛选完成，单品种预检待现场

21:50实际只读预检：合约12行、保证金1行、手续费1行均完整返回；结算确认状态查询完整零行，
盘口33行完整返回，旧宿主按总行数!=1误报NATIVE_BOOK_MISSING，未进入执行，不把它解释为完全没有行情。
新增完整批次按绑定InstrumentID+ExchangeID唯一筛选，缺失/重复拒绝；预检与运行循环共用，
原交易日、ActionDay、5秒新鲜度、价格/数量及物理绑定校验保持。结果记录匹配数和事件年龄，
合格输入报告明确为当时观察，并保留有效期，不能把完成后已过期的预检报价用于报单。
198项模块、17项SDK、Ruff/secret0/diff及独立高风险Review通过；真实目标及新鲜盘口仍待验。
未报撤单、未确认结算、未初始化交易账户、未发布/切Runtime，auto_order=false。

## 10/26 宿主合约查询超时已定位，范围收窄后现场待验

21:42预检诊断：instrument请求SDK返回0，15.002937秒收到6360条回调和有效行，未见终态；
因此不是合约查询零回调，失败发生于全市场合约资料读取，尚未进入保证金/手续费/盘口校验。
新增按权威交易所+CTP产品代码限定资料请求，拒绝无scope及范围外回报；保留完整终态和物理交割年月绑定，
不延长等待、不重试/fallback、不把部分资料当成功。查询最终失败检查、请求状态发布与SDK发送共用锁，等待回报在锁外；间隔或构造期间已断线则不发送。
17项SDK及186项模块测试、Ruff通过；现场修复效果仍须新的只读观测，不宣称预检已通过。
无报撤单、结算确认、账户初始化、发布或Runtime切换，旧失败原件保留。

## 10/26 夜盘第一套账户读回通过，执行宿主预检仍待定位

21:19第一套Python四类查询各两轮全部完整返回且逐值一致，独立重算哈希通过；与原生C++及日盘
同一账户，原生交易日20261027，权益及可用均100000，保证金/冻结0，持仓/委托/成交均完整零行。
10万元资金生效实际观察通过。此前C++持仓和资金亦完整返回，Python可用，日盘超时根因仍未知；
不能因夜盘成功归因某个绑定或后台。结果仅只读验收，ledger_reconciled=false、execution_eligible=false。

21:32 rb/RB2701宿主默认只读预检返回NATIVE_FACT_QUERY_FAILED，尚未通过合约/费率/盘口完整链。
旧报告未保存具体失败阶段，不猜测来源，不重跑旧结果；追加白名单原生事实查询诊断支持后续单次定位。
无报撤单、结算确认、账户初始化、发布、Runtime切换或自动交易启用。原始失败和成功原件均保留本地。

## 10/26 原生 C++ 只读对照准备完成，第一套查询可行性仍待现场

新增独立诊断入口，保持相同Mac6.7.7动态库、30001前置、认证及无topic初始化，绕过Python/SWIG。
只持仓→资金各查一次，45秒等待、超时即停；不重发、不切前置、不确认结算、不报撤单。
结果仅计数/身份/错误，明确account_acceptance=false、execution_eligible=false，不替代两轮四类账户验收。

10个C++离线回调案例、实际SDK加载/版本检查、原Python只读40项通过，独立高风险Review通过。
编译头身份固定，账号按最窄InvestorID限长；日志屏蔽失败连接前停止，写盘失败非0，末刻断线失败关闭。
这些仅为本地支持证据，不证明实际ABI/柜台回调或根因。15:16已闭市，未发起无解释力的重复登录；
后续在第一套正常服务时段做一次用户TTY输入的原生对照。此前失败原件保留，资金及空仓未知，
10万元20261027生效仍待验，auto_order=false；本次未发布/切Runtime。

## 10/26 第一套持仓首查对照完成：持仓与资金均零回调，账户仍未验收

14:17同一账户第一套认证及登录通过，资金请求返回0但45.002秒零回调（ZERO_QUERY_CALLBACKS），
增加等待未解决；资金、持仓及10万元生效未知，未自动重试。不能据此归因具体后台或传输故障。

新增显式 --query-order positions-first，仅将同四类只读查询调整为持仓→资金→委托→成交，各两轮；
默认funds-first和执行宿主行为保持。持仓超时立即停止不发送资金，完整零行持仓但资金未核清不判整个账户空仓。
顺序仅为诊断元数据，不进入经济事实哈希；不改前置、认证、查询参数、结算或订单，不做自动fallback。

只读40 passed（真实SDK结构及实际SPI跨线程覆盖两种顺序）、账户/执行200 passed、SDK网关8 passed；
Ruff/秘密扫描0/diff及独立高风险Review通过。14:31实际对照：同一账户认证/登录通过，持仓请求返回0，
45.006秒零回调后停止，未发送资金查询，订单请求0。与14:17资金首查共同证明至少两类查询无响应，
不能只归因资金字段，也不能断定后台故障或本地SDK无误；不再自动重复登录。持仓/资金/账户空仓均未验收。
代码可集成develop；未发布或切Runtime，不宣称资金查询超时已修复，不改变auto_order=false。

## 10/26 SimNow第一套资金查询超时：诊断代码完成，现场根因待证

13:43只读原件证明第一套认证/登录通过，原生交易日20261026；唯一资金查询SDK返回0，15秒未完成，
未获得资金行、未继续持仓/委托/成交查询、订单请求0。不能据此判空仓、零资金、密码错误或10万元生效。

新增脱敏回调计数、终态及单调耗时诊断，区分零回调/缺结束回调/超时边界已收到终态。
CLI查询等待默认15秒保持，可显式设1..60秒；一次只发送一条，超时停止不重发，晚到终态不升级为成功。
不改资金查询参数、前置、认证或结算；diagnostics不进入原生Snapshot身份/内容哈希，也不能覆盖不完整查询。

真实Mac SDK结构与实际SPI方法跨线程两轮8查询离线走通；只读协议36 passed、账户/执行200 passed、
原生网关smoke8 passed、Ruff/secret0/diff通过，独立高风险Review关闭超时边界分类问题。
本地处理路径未复现现场超时，不宣称柜台或传输根因已定位、超时已修好。

已准备用户隐藏输入的单次45秒只读观测；实际结果另验，不自动重试。代码经验证允许集成develop，未发布/切Runtime、
未报撤单或确认结算；原v1.16.7持续服务保持。本节不替代10万元20261027生效及原生账户完整性验收。

## 10/26 v1.16.7已发布，十服务统一gen29，唯一发布树保留

RELEASED / 十服务切换与生命周期读回完成；**自然业务验收仍pending，不声明整体RUNTIME_READY**。
PR483/main/annotated `v1.16.7` exact `44de0c4a8f7208a5da71b9c0b4ce26c0249b14fa`，与已测试候选完整树相同，[GitHub Release](https://github.com/firehell/guiyi-quant-workstation/releases/tag/v1.16.7)已公开。
正式十项均绑定 `.worktrees/release-v1.16.7` / exact commit / gen29，Scope、启用、日历、配置哈希保持。

- 常驻PID：API56434、Web56441、Feed57330、Live56417、Alert56422、Reference56428；三次读回稳定307秒，旧树清理后第四次仍相同（1523秒）。
- 四项日历仅注册、无PID，RunAtLoad/KeepAlive=false；未手动触发业务。
- actual API与Web代理均返回1.16.7，Web字节与发布dist一致；十项deployment identity全部matched，消费边界未回退。
- 正式SimNow监控返回not_connected，未连接Broker/创建账户/下单，auto_order=false。
- 闭市Alert420路中413完成计算，7路保留warming：BZ/EC/PD/PL/PR周线及RS日线/周线；不计入calculated或自然信号就绪。首根自然completed Bar、Event及送达另验。

实际验证：部署组合231 passed/0 skipped，精确候选165 passed，独立高风险Review70 passed；Web1237 passed/3 skipped、关键五组70 passed、详情交互10 passed，type/build/topology、Ruff、OpenSpec12/12、secret0。
旧SuBing1440/Free390金图及Newow旧pane断言保持明确历史例外，不宣称完整七组浏览器全绿。

四旧发布树v1.16.1/.4/.5/.6已在native零引用dry-run（SHA `a31b32109e6139bcb2c2e7bdf06d5883fb701e5690823ec53728e7821b540656`）和再次核对后non-force移除；三份旧候选plist先保全再退休，30份非缓存原件（19492字节）已私有归档并验证SHA。Git tags/Release及共享数据、配置、失败原件未删除；需要恢复时从exact tag重建，不常驻保留回滚树。
当前仅一棵发布树；develop保留。另一个已合并任务树 `/Volumes/扩展盘/worktree/htdy-60m-execution-rules/guiyi-quant-workstation` 仍有Codex/node_repl及5176/8003预览进程引用，因此保留，未强删或终止其他会话。

发布过程保留：v1.16.5仅预检阻断；v1.16.6的旧plan52190...未CAS，原attempt/state.json仍为restore_unknown原字节。原态恢复后经v7精确只读审计，receipt SHA `8a762ce9b8ba9ddc2d44a9b4471abfd8bbfe4e829f355c2dce8f9898eba32893`，仅global checkpoint cancelled；随后全新plan `57dd3cd5e7af11bc1f2393898f2a155b6826a340e7beccb124b9e74a91e08f83` 一次CAS switched。未重跑过期plan、回滚CAS或伪造自然证据。
完整现场evidence与原件索引：`output/full-release-cohort-20261026/`；私有attempt留于既有稳定Runtime目录。实施过程见[记录](docs/superpowers/plans/2026-10-26-full-release-cohort.md)。
下一最小步骤：释放占用该任务树的旧会话后，再做其零引用清理；自然业务Gate等待开盘，不新增定时监控。

## 10/26 首页5项旧E2E失配已清理

修正旧micro尺寸图标、已移除刷新按钮及快照summary的测试断言，保留原行为目标：
预热不得生成目标价/建仓图标、行情后台重验失败保留旧快照、目录自动重试及24小时到期失败保留选项、
1440/390缺价原因与报价/策略状态分离。使用语义化图标和Playwright虚拟时钟，未增加产品按钮、skip或放宽截图容差。

最新develop基线的原5项均已失败复现；修复后完整首页39项+模拟交易4项合计43 passed，
无grep排除、无retry、无金图更新。Node语法、diff检查和秘密扫描0通过，自审完成。
修复验证首轮有一次独立Chrome launch 180秒超时，其余4项通过；单项诊断及随后完整43项均通过，旧日志保留。

改动仅E2E及验证/状态文档；本次不发布、不切Runtime、不改行情、策略、账户或交易语义。
先前第六步记录的5项旧选择器例外在本节关闭；其他真实SimNow、自然输入及运行切换待验事项保持。

## 10/25 其余8项服务切换：5项完成，Alert/Feed/Live现场校验阻塞

Owner交办其余8项切至已发布v1.16.4。4项定时服务（after-market、late-provider-recovery、weekly-audit、log-rotate）及Reference已切至exact `bc7a91621ddaae6ad3ee915662994227496ccac6`/gen26。
API/Web保留v1.16.4/gen28及原PID；最终十项身份均matched。Reference原生交接结果switched、新PID13658持续存活超过两分钟、消费边界未回退；启动后扫描和自然业务验收另验，不声明整体RUNTIME_READY。

原生自动影响计划为空，按owner明确指定范围冻结独立重绑定计划，复用同版本原生warmup/drain/CAS/verify及日历更新API；未改写原生plan、tag或发布源码。
52项runtime binding/handover/deployment/scheduled回归及独立执行Review通过。定时服务仅注册日历，RunAtLoad/KeepAlive=false、PID均空；原日历、非身份配置及6份原启用/盘后状态文件逐项SHA保持。
新旧状态复制在原生idle guard内、旧任务卸载后、CAS前完成；失败attempt及新Reference独立计划保留，不重试失败Alert候选。

- Alert：候选预热失败`MARKET_READ_CONTRACT_UNAVAILABLE`，已取消并保留原PID6203/v1.16.1。只读复核A的5m/15m/30m最新历史为10/23，该日Live订阅为空；不伪造订阅或回填信号以通过预检。
- Feed：`MARKET_FEED_SESSION_BREAK_REQUIRED`；Live：`CANDIDATE_SESSION_UNKNOWN`。60品种现场均CLOSED但trading_day=None，原生交接/预热不能证明，不改Gate；原PID6228/6197及v1.16.1保持。

Scope摘要、Event3921条/max_id3923、流状态及两日观察cursor/tail读回保持；没有手动触发盘后/周审、通知重发或订单。
旧v1.16.1仍被三项常驻服务引用，必须保留。现场evidence：`output/runtime-all-v1164-20261025/`。
下一最小步骤：有效Session和对应Live订阅事实具备后，重新生成精确计划并预检剩余三项；没有新增定时监控或自动重试。

## 10/25 消息页缓存与分页优化，v1.16.4已发布并切换API/Web

消息首屏与续页20条；类型查询缓存30秒免请求、5分钟保留，恢复已加载分页与滚动；搜索350ms防抖/回车立即提交。
后端固定120秒、16份/32MiB有界快照复用，续页不重扫消息批次，Newow来源身份变化/过期仍409；partial覆盖和快照时间保持明确。
后台变化点击后替换，手动刷新失败保留旧列表；不改策略、Scope、通知、行情或账户。

先经PR478发布v1.16.3；正式实测发现全部首次46.827秒超过旧客户端30秒，随后PR479最小补丁仅将消息请求超时设60秒。
最终main/annotated v1.16.4 exact `bc7a91621ddaae6ad3ee915662994227496ccac6`，API/Web已独立读回同tag/commit/gen28；其余八项仍exact v1.16.1且与前值相同。
两次原生plan均仅API/Web、共享合同相等、单次apply switched；旧失败及各阶段原件保留，不重复切换或发送。

本轮真实全部续页39.637秒→0.039秒、趋势5.848秒→0.034秒；首次全部仍约47秒，并未秒开。
最终正式内置浏览器重载验证全部20→40条、类型往返恢复40条、消息错误提示0，覆盖不完整如实显示。
候选后端44 passed、Web1228 passed/3 skipped、消息浏览器9 passed、build/type/topology、offline lock、Ruff、secret0、OpenSpec12/12及独立Review通过。
既有390px市场截图断言在原v1.16.2和候选均差527像素，未更新金图、不宣称该完整用例通过。

现役v1.16.4发布树保留；已无引用的v1.16.2/v1.16.3经精确只读扫描和再次核对后non-force清理，v1.16.3九份.run原件/SHA及原移动端失败图保留。
v1.16.1仍被八项服务引用，保留。全局health原有degraded及自然业务待验不因本次UI/API切换关闭，不声明整体RUNTIME_READY。
现场evidence：`output/message-loading-20261025/`。下一最小改进是针对全部消息首次冷扫描定位耗时；本次缓存、分页及发布切换已验收。

## 10/25 第六步首页模拟交易监控工程完成，真实账户数据待验

CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE：首页第三Tab“模拟交易”及详情共用返回、
原生权益与可证明净收益曲线、持仓/执行链/待核、筛选分页、手机全屏明细完成。
可见时5秒读取，隐藏/卸载暂停；翻页或明细期间仅提示新快照，迟到请求不得污染新筛选/账户。
复用现有财务/预留口径，跨日现金流无法证明时净收益断开；异常持仓保留实际数量并撤下完整预算声明。

单一显式根及私有原子索引绑定账户/来源/运行阶段，API仅SQLite只读，不构造执行Store、
不连接Broker、不恢复或创建账本；WAL在连接前拒绝以避免只读SQLite创建sidecar。
宿主监控发布异常已注入实测，不影响受控执行且监控状态明确unavailable；账户未知不当零资金或空仓。
GUIYI_SIMNOW_MONITOR_ROOT仅为API选取既有宿主固定根，不改变宿主输出位置。

实际验证：后端/账户/执行199 passed；合入同期消息页优化后Web单测1237 passed/3 skipped（含本任务新9项）；
原生SDK结构无网络smoke8 passed；类型检查/构建、Ruff、secret scan0、独立高风险Review通过。
新增监控4项和相关首页导航/视觉34项浏览器回归合计38 passed，覆盖桌面/375手机及共享首页1280/1440/1920/2560/390。
扩展40项首轮10失败：5张导航截图随第三Tab更新后通过；另5个旧选择器失败在未修改HEAD归档同样复现
（旧micro图标、已移除刷新按钮、已移除快照summary），未修改其无关行为，不宣称整套旧E2E全绿。

本地开发页面5176/API8003独立启动，真实GET读回not_connected及全部金额null，浏览器已核验空态。
未修改既有5175/8002或正式服务；主develop工作区其他消息任务修改保留，不覆盖同步。
本次仅开发集成，不发布/切Runtime、不启用持续交易、不新增后台采集/推送；第一套原生资金10万元
20261027生效、自然输入与真实受控订单仍待独立现场验收。监控截图fixture不是真实账户绩效。

## 10/25 SimNow前五步工程闭环完成，真实账户与订单仍待现场验收

按owner要求完成：原生账户对账、实际费用与账户收益、真实执行输入、一次性受控入口、故障验证及独立Review。
`inventory/finance/evidence/host`复用既有两轮只读协议，核验资金/今昨仓/委托/成交并映射Readback；对锁、超一手、外部未知事实、有保证金无仓或冻结无挂单明确阻断。
实际费用仅在同日稳定非重叠快照间唯一一笔新成交、原生Commission差额及订单身份可证明时归属；多笔/跨日不猜。收益以原生权益和实际现金流调整，跨日连续性不足时净收益保持待核。

新增一次性 `scripts/broker/simnow_controlled.py` 与原生gateway：默认只读preflight，显式execute才限定一品种、每单一手、10..3600秒及1..3次submit。
首次initialize须实际第一套10万元空账户、无委托/冻结且交易日>=20261027；重开接管不覆写旧账本。结算确认仅execute且先通过前置检查后发生。
owner明确批准SimNow盘口仅供执行，Calendar/Session/主力及策略行情仍共用RQData链；自然新完成60m原件、startup/恢复隔离、不补历史信号。

修复实际接线暴露的边界：源回读完成与激活时间分离但必须仍在有效期；正常FILLED等待核验不丢反手目标；已知迟到成交即使缺费用也先重新锁定预留；从未领取发送claim的本地提案可在账户writer内记LOCAL_ABORTED，已领取或未知禁止该路径。
退出先注销/释放原生回调、消费尾部事实再关闭journal；报告逐单、预留、成交、持仓完整性和平仓义务，未知/缺费/未核清非0退出，不能将空列表当空账户。

完整定向212 passed，隔离真实Mac SDK gateway8项、原只读32项通过（共252）；SDK请求结构smoke、同ABI隔离SDK/API依赖实际导入均无网络通过。
Ruff/secret scan0/diff通过；独立高风险Review已关闭退出分类等问题并完成最终聚焦复核，允许集成develop。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；真实第一套、10万元生效、自然输入和原生报撤单分别EXTERNAL_GATE_PENDING。
本次未读取实际凭据、未创建原生交易API实例、未真实报撤单、未发布/切Runtime，auto_order=false保持；没有持续自动交易或监控UI。
唯一下一步是在实际服务时段运行默认只读preflight并读回结果，再按真实事实推进有界柜台验收。合同见[SIMNOW_EXECUTION](docs/SIMNOW_EXECUTION.md)。


## 10/25 Web参考交易面板按周期显示（develop，未发布）

按owner要求，HTDY仅60m显示参考交易，苏冰仅15m/30m/60m/1d显示；其余周期不渲染参考面板、说明或不支持占位，也不查询参考流。图表与独立Event审计保留，不改Scope、信号、推送或参考交易后端能力。共同显示规则由单一Web策略函数管理。

最新develop集成后Web单测1222 passed/3 skipped、浏览器21 passed（含苏冰各周期及15→5→30切换）、显示矩阵3 passed，typecheck/build/topology、OpenSpec12/12、secret0、diff及自审通过。CODE_COMPLETE / TEST_COMPLETE；尚未发布或切Runtime，正式API/Web仍按下节记录的v1.16.2。

## 10/25 HTDY实时信号统一60分钟，v1.16.2已发布并切换API/Web

按owner批准计划，通过既有Scope API关闭JM5m/15m并开启60m，逐次及最终独立读回：operational60品种均且仅60m（60组合）。JM旧5m/15m Event及发送字段前后相等，无补发、回填或周期转换。

HTDY仅60m查询/显示实时Event及已有参考交易流；其他周期保留历史研究图表并提示统一60m。未新增参考交易流，不将Event冒充开平仓成交。develop已集成3bc2db867；正式v1.16.1最小回移经PR475发布annotated v1.16.2，peeled/main d143143099f1dbc4b153eae4a2dcea927fb85f4c。原生release plan共享合同全相等、仅API+Web，单次apply两项switched；独立正式HTTP/API和十项身份读回通过，API/Web为v1.16.2，其余八项仍exact v1.16.1，未切Alert/Feed/Live/Reference。

候选Web1222 passed/3 skipped、alerts定向25 passed、浏览器9 passed（非60m六旧链接、空流/失败、SPA切换和迟到响应）、健康接口6 passed；build/typecheck/topology、offline lock、OpenSpec12/12、secret0、diff和独立Review通过。develop另一套页面亦经13项浏览器及补充SPA集9项验证。初次浏览器fixture及回移模板适配失败保留，修正后才冻结。

正式Chrome只读实测：JM15m零实时查询，原地切60m仅两项60m实时读取、缺流状态明确、pageerror0；截图留证。现场历史动作读取仍有失败提示，本任务未修改其后端或用实时Event替代历史事实。

独立配置/版本读回在本地 `output/htdy-60m-unification-20261025/`；旧发布树仍被八项服务引用，保留。全局health仍degraded；JM60m新的自然completed评估、Event、provider accepted与手机送达分别待验，不声明整体RUNTIME_READY，不新增监控或制造信号。

## 10/25 48路闭市收尾完成：历史44已验，L4恢复，Runtime v1.16.1/gen25

本节为 gen25 全量切换检查点；随后 API/Web 已单独升级 v1.16.2，当前组合以上节为准。

Owner交办当前能处理部分并明确批准发布/正式切换。33基础+11融合Canonical历史原生重建44/44完成，新进程逐项来源manifest/checkpoint/正式HTTP44/44验收通过；16组旧事实全行摘要及4组journal/index/cursor保持，Reference原PID正常恢复。33项已知纯前置刷新失败精确解决，其余74控制项保留。L四路真实观察端点已齐，修正只读健康投影，不改持久旧health或原件。

PR469/main/annotated tag/Release v1.16.1 exact bc2c43dab2a8ce67038ca3998e74ac6b4a16b3c9已发布；十项身份已统一gen25。cold001在CAS后因新树缺Vite依赖导致Web启动验收超时，旧失败保留；仅离线frozen补依赖（0下载），由既有KeepAlive启动，未重复stop/install/CAS。独立final-readback-003验收全部binding/loaded/六owner/四calendar及旧Scope配置、选定forward字段和原journal一致，Web实际index=dist；60秒PID稳定、Reference cycle ready、日志FD匹配。当前Feed6228/Live6197/Alert6203/Reference6210/API6216/Web10198；旧v1.16.0已确认零引用，保留5个.run原件/SHA后按精确计划非force清理，tag/Release及其他任务树保留。

正式Reference **676 READY/44 OBSERVATION_LAGGING**，L4 READY、44独立Canonical历史CURRENT；pending Capture/消费积压/PG维护占用均0，文件锁空闲。全局仍degraded，剩余44为真实观察缺失，不能靠历史计算消除；下一Session采集/H1/Event/Push及18:05增量另验，七路暖机和后置苏冰全量资产保留。1153关联回归/81明确跳过、183维护回归、exact候选339及独立Review通过。详见[48路收尾记录](docs/tasks/reference-lag-closeout-20261025.md)。

## 10/25 D1历史75条修复完成：全部逐项验收，历史720端点CURRENT

Owner交办前次审计的75条D1历史修复。18基础（AL/PG/PS/PX/SI/ZN各三策略）先、57融合后，使用正式exact v1.16.1/gen25原生fresh rebuild；75/75由独立进程逐条来源manifest/checkpoint/正式HTTP核验到10/23 15:00 CST，旧18个503入口恢复、57个滞后追齐。旧18个partial candidate/94已提交批次结果已独立核清，依赖改变后不复用旧plan/resume；ZN旧advance明确首写前REBUILD_REQUIRED。全部旧候选与经济事实保留。

单次attempt001完成，18组旧事实全行摘要及所有journal/index/cursor前后保持；成功后精确解决74旧控制，原文保留，当前控制队列0。15:19独立最终Review通过，75新revision及旧候选/批次/App事实一致。正式启用历史720/720 CURRENT（D1由165/240至240/240）；非目标645的CURRENT仅端点级，本次75另有完整来源验收。

Reference同PID6210/gen25已恢复，六常驻原PID均active、十binding仍exact v1.16.1；pending Capture/积压/PG维护占用0，文件锁空闲。Forward仍676 READY/44真实观察滞后，global degraded、旧2565+611原件限制、暖机及苏冰全量后置保留；下一自然采集/计算/Event及18:05增量另验。首轮定向144 passed/2 skipped、补强维护30 passed（含重叠）、独立代码和实际结果Review通过；provider/Canonical/forward/通知写入0，无版本切换。详见[D1历史修复记录](docs/tasks/d1-history-repair-20261025.md)。

## 10/25 SimNow受控订单适配代码及离线端到端完成，真实柜台待验

新增 `simnow_ctp_controlled_v1`：固定第一套会话/账户/交易日绑定、最多60秒精确单次Permit、
持久发送领取与OrderRef/RequestID、平今/平昨、撤单、原生回报stage/drain、未知结果不重发。
账户writer guard覆盖SDK请求受理；回调先到独立journal，避免同步回调嵌套账户事务。
CTP秒级回报用独立NativeFill保留精度、dispatch因果及SystemID；缺实际手续费或SystemID不一致保留待核，
未知成交quarantine，前日已知单迟到回报保留，unresolved状态在全部事实分支保持BLOCKED。

155项适配/账户/HTDY回归通过；隔离SDK环境32项只读回归通过；Mac ARM64 openctp-ctp6.7.7.1真实结构与SPI mixin无网络smoke通过。
Ruff、secret scan0及diff通过；独立高风险Review所指秒精度、恢复顺序、SystemID和跨日关联问题均已失败回归复现并修复，聚焦复审允许集成develop。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；真实端到端EXTERNAL_GATE_PENDING，SDK结构成功不等于柜台实测。

未创建原生交易API实例、未读凭据、未真实报撤单、未发布或切Runtime，auto_order=false保持。
第一套及10万元20261027生效仍待原生读回；完整原生Readback/实际费用投影与受控交易宿主尚未接线，无交易启动CLI。
后续须在这些事实与可交易Session具备后验收精确一手报撤单，不能将测试副本/离线fixture当自然实测。
合同见[SIMNOW_EXECUTION](docs/SIMNOW_EXECUTION.md)，验证见[TESTING](TESTING.md#simnow-受控订单适配)。

## 10/25 HTDY账户风控、预留与订单状态机离线实现完成

`htdy_60m_account_execution_v2` 已实现70%权益保证金准入、冻结去重与本地资金/费用预留、资金拒绝永久消费信号、
信号先后处理、对手价、原生受理后自然180秒撤后核对再跟进、收盘前60秒放弃开仓但保留平仓义务。
SQLite命令/状态/惰性提案原子提交、幂等、未知提交只读核对、重启恢复和真实迟到成交保留均有回归。
原v1政策、公式、Alert与参考收益保持；新入口不连接Broker transport或持续Runtime，没有真实报单/撤单。

定向完整命令见[TESTING](TESTING.md#htdy-60分钟离线执行规则)：124 passed；Ruff通过、secret scan 0、diff check通过。
独立高风险Review发现的离线成交恢复、错误合约恢复方向及连续未知成交问题均已由回归复现并修复，聚焦复核允许集成。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；不是发布、Runtime或账户自动交易Ready。
真实第一套环境及10万元资金生效仍待下节原生读回；下一步为Broker订单适配及端到端受控验收，不能直接循环发送effects。
合同见[HTDY_SIMNOW_V1](docs/HTDY_SIMNOW_V1.md#账户风控与报单决策2026-10-25确认)。

## 10/25 SimNow测试环境只读已实测；10万元重置申请受理，20261027生效待验

按owner交办完成固定测试环境的资金/持仓/委托/成交两轮串行只读CLI；复用已实测的Mac CTP登录ABI，
不接入持续服务或执行政策。查询必须完整收尾、身份和交易日一致；保留今昨多空/冻结/订单原生事实，
两轮变化或未完成不报空仓，资金仍有保证金占用/冻结时也不能报空账户。

24项离线测试、原生四查询无网络参数核对、Ruff/secret0/diff及独立Review完成；Review所指保证金空账户
判断已由失败回归复现并修复。CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE。16:56用户本机隐藏输入后实际四类查询均两轮完整，
独立读回确认两轮逐值/摘要一致、测试环境空仓无未完成委托，交易日20261023；原始结果仅本地私有output保留。
这不是第一套环境验收或账本对账；前序失败及登录记录不改写。

后续按owner交办准备显式 `--environment first`，固定官网30001，不自动fallback，新增4项离线回归先失败后通过，
总28项通过。17:05第一套匿名连接12秒未返回成功回调，未认证/登录/查询；第一套仍按官网实际交易服务时段待验。
Owner随后完成官网登录并明确接受清除全部模拟持仓。agent单次提交被官网验证码拒绝，未重试；owner自行重新
提交后提供官网成功截图，目标10万元，明确生效交易日 **20261027**。这是申请受理，不是资金已到账；旧失败
及截图保留本地，不推算为20261026、不重提、不修改旧账户快照。first原生读回仍未完成。
新增成对可选资金验收参数，只在first核对两轮目标余额/空仓/无单/无冻结及柜台生效交易日；测试副本、旧日或
查询未完成均不得通过，且始终无执行资格。定向32项测试通过，真实资金生效另验。
未请求订单、撤单或结算确认，未写行情/生产数据库，未发布或切Runtime；官网资金重置由owner自行提交，
不把测试环境副本当作第一套环境或Ledger对账。
合同见 [SIMNOW_READONLY](docs/SIMNOW_READONLY.md)，交付记录见 [任务记录](docs/tasks/simnow-readonly-20261025.md)。

## 10/25 HTDY九品种闭市来源差异：已核验分类，下一交易日自然验收待发生

按owner交办复核AP/CJ/JD/LH/PK/RS/SF/SM/UR；Canonical32根60m预热及底层1m完整，旧原件也完整，
两套各自1m→60m聚合精确一致；逐端点证实123根1m、17根60m数值差异，保留旧原件和历史事实，不反推provider修订原因。
新增只读 `htdy_closed_day_source_difference_v1` 分类，完整交易日闭市、物理来源/质量、旧/新owner与新合约生命周期、
Calendar/Session及旧/新恢复身份均须可证明；不是盘中fallback，不改变原生冲突reader或执行政策。

fresh全60复核：历史60通过，当前计算51通过/9旧冲突阻断、原Live42完整/18阻断均保留；
总体40等待新观察、11历史已补齐但原件缺失、9已核验闭市差异等待新交易日。9项下一日均10/26、首H1日程10:00 CST，
尚无该自然Bar；所有审计eligible_now/first_seen均false。本次零下载/生产写入/Runtime切换/信号重放/通知，18个原件键前后hash一致。
独立Review验证9份证据hash及原件前像，关闭next ContractFact/next recovery两项边界缺口；定向执行/reader回归221通过，
Ruff/OpenSpec12/secret0/diff通过。证据在 `output/htdy-source-conflicts-20261025/`，该审计当时Runtime为exact v1.15.18；现役记录见本页顶部。

## 仍需分别验收的运行与交付事项

- 最新记录为 API/Web v1.16.2、其余八项 v1.16.1；Reference 676 READY/44 OBSERVATION_LAGGING；global degraded、
  7 路短有效历史 warming、原 2,565 + 611 条自然原件缺失保留。历史输入补齐不能补造原观察或消除真实观察滞后。
- 下一自然 Session 的采集、H1/计算、Event、通知和 18:05 增量须分别验收；不由测试、历史端点 CURRENT
  或进程 active 推导整体 RUNTIME_READY。10/25 闭市修复记录见
  [健康恢复](docs/tasks/runtime-data-health-recovery-20261024.md)、[原件缺口历史补齐](docs/tasks/original-gap-history-repair-20261024.md)。
- Newow 正式品种范围已为 60/60；历史 720/720 CURRENT 的非本次目标部分仅为端点级检查，
  不外推所有来源、辅助指标、自然观察或 OOS 完整性。当前产品开放仍由 capability 合同决定。
- 苏冰全量历史资产按 owner 优先级后置。10/24 初次清点 240 身份中 236 缺失、RB4 仅到9/22；
  JM4 已完整验收，A/AG 各4已构建。该数值是旧盘点，不能当作当前新鲜覆盖数。
  AL15m 原生 INTERRUPTED 位置225792/320074与token保留；RB4 exact append已通过前置校验，
  本页尚无随后完整 apply/验收记录，不宣称苏冰全量闭环。
- 苏冰推送关闭、既有 Rule/Scope/受众和 `auto_order=false` 保持；不启用Paper持续运行、Shadow或自动订单。
  最新夜盘通知口径为4批平台accepted、2批failed或unknown，owner未打开微信，实际收件未验。
  历史 AO2701 10/14 23:00 HTDY 的 owner 收件确认只证明该次事件，不外推其他事件或受众。
- 生产 schema、精确配置与当前 PID 应现场只读核对；本次清理不执行 migration、配置变更、重启、
  replay、backfill、补发、发布或 Runtime promotion。

## 10/24 苏冰历史续算/追加：前置连接失败已修复

AL15m续算及RB四周期追加脚本原先先导入应用、后加载私有配置，数据库连接池提前缓存开发配置。已调整初始化顺序，默认离线行为保留；新增只读check-only和安全错误定位。18项定向测试通过、独立Review无Confirmed Issue。正式v18现场只读：AL225792/320074原生续算位置一致、RB四周期exact append/旧事实校验全部PREFLIGHT_PASSED，production_writes=0。旧失败目录不重写，修复版v2目录独占；本步未执行apply，不代表全量历史计算完成。下一步仍须确认旧writer退出、现场锁和来源后精确续算/追加。详见[修复记录](docs/tasks/subing-history-preflight-fix-20261024.md)。

## 期货双向研究：已随v1.15.16发布，未晋升

已推送并集成develop 757c09ae37；数值实现冻结5ad16d06b。保留牛哇默认原版，新增独立futures_bidir_v1内核、参考投影、10万元分层研究账户、冻结结果只读API及详情页开关；八策略名称和六周期入口保持，主图动作/目标保护线、方向、持有周期、参考与账户收益及记录分别切换。
JM/RB/AL/TA × 六周期 × 八策略 × 三成本场景576格全部落盘并独立核验：260完整、225资金不足、73换月中断、6预热不足、12不适用。基线192格中88个完整账户为12正/69负/7零；不证明普遍盈利或OOS。TA另有3格参考路径DATA_INTERRUPTED，保留未知收益。中断不拼成完整年度收益，资金拒绝不吞并参考交易。
全量104411条模拟Fill的费用/现金/层级PnL/整数仓位/tick及strict-later核对通过；首轮332重叠格数值逐字一致，仅59处参考快照原因修正。后端及原版回归445 passed，Web1165 passed/3 skipped，build/type/topology、secret零发现及独立Review通过；实际5183/8004八策略/六周期、往返刷新、旧响应隔离、精确定位/窗外提示及最终真实价格逐项读回通过。
上述为实现验收检查点；其后已随v1.15.16发布并被现役v1.16.1包含，不因此晋升策略或启用持续Paper/通知/Shadow/Broker/订单。冻结主图最近2000根，窗外历史记录明确不可定位；全窗记录和曲线独立保留。实际统计、身份、文件与命令入口见[首轮研究记录](docs/research/newow-futures-bidir-v1-20261021.md)。发布证据见 [期货研究交付记录](docs/tasks/newow-futures-bidir-v1.md)，当前Runtime记录见本页顶部。

## 新苏冰固定参数研究版：工程与历史回放验收完成，未晋升

新增独立 `new_subing_v1`，规则见 [策略合同](docs/NEW_SUBING_STRATEGY.md)，
交付记录见 [任务验收](docs/tasks/new-subing-v1-20261012.md)。独立只读页面 `/research/new-subing`
和 API 读取显式任务结果根；不恢复旧苏冰策略、不改变现役 Alert/JM Paper；此段记录研究验收，发布与Runtime见顶部。

精确计算候选 `2d7069b1be746cb80656f95fd3a576eb6b97ed53`，AL/RB/TA 各自100000元，
2024-10-14..2026-10-09的9个成本场景包与54个独立窗口摘要均完成。基线两年净收益
AL -0.312%（2笔）、RB -0.305%（1笔）、TA 0%（0笔）；双手续费/滑点未改善结论。
后一年及四季度所有场景均无成交，样本不足，**不证明策略有效或独立OOS通过**，不自动晋升。

定向552项、Web1090项（3项既有跳过）、类型/构建/规范/秘密扫描及独立代码审查通过。
真实结果独立哈希、18笔Fill、9轮成本变体交易和117条权益的资金/费用/PnL/回撤复算通过；
54个独立窗口仅核对摘要，未在独立读回中重新逐笔重放。
原 Notion 经典案例截图尚未逐图解析，案例一致性待验；旧失败采集和两次停止回放记录保留。
CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE，未进入Paper持续运行、Shadow或Broker。
下一最小步骤：原案例逐图对照，核对新策略触发与笔记交易的差异；不得据少量交易扩大运行范围。

## JM 固定 Paper 口径：七策略六周期复核完成，未晋升

2026-10-11按owner要求，沿用前三步的50000元、最多一手LONG、日初权益亏损2%停开清仓规则，
复核趋势、震荡、双策略及测试1–4，覆盖5m/15m/30m/60m/1d/1w。
42组共用2025-10-13..2026-10-09的82305根物理1m执行行情与逐日成本事实。
22组完整年度账户可比，20组因持仓或挂单跨主力换月而中断，不纳入全年排名；
另有168个各自50000元起步的合约段诊断，不拼成全年账户。证据见
[完整矩阵与排名](output/jm-causal-matrix-20261011/report.md)。

完整年度收益最高为周线测试3：+14.30%、3笔已平仓交易，样本过少且集中单一合约。
60m测试2：+9.78%、35笔、最大回撤13.91%，四个独立合约段均盈利，列为未见数据验证优先项。
8个盈利组合完成双手续费与双滑点压力；60m测试2仍为+10.32%/+8.04%，
30m震荡与测试1在双滑点下转为-1.54%/-7.47%。本年已参与选择，不是独立OOS。

定向Paper/研究测试192 passed（含隔离PostgreSQL），工程合同29 passed，Ruff/Mypy通过，
独立审查无阻断问题。新增研究适配复用原公式与Paper事件内核，不写生产数据，不新增正式账户，
不连接SimNow、不启用Shadow/自动订单、不发布或切换Runtime。
下一最小步骤：冻结60m测试2研究身份，在未参与筛选的数据上验证；本次不自动晋升。

## JM 前三步：因果验证与本地 Paper 工程完成，策略不晋升

2026-10-11 owner交办前三步，风险固定50000元、一手long、较交易日初权益亏损2%停开并安排清仓。
新增版本化双策略因果目标、开/平今/平昨费用、纯Paper状态机、独立PostgreSQL不可变账本与历史回放CLI。
合同见 [Paper试点](docs/PAPER_PILOT.md)，证据见 [验收结果](output/jm-paper-first-three-20261011/acceptance.md)。

近一年JM5m双策略1430笔已平仓因果交易，1tick滑点基线复利净回报 **-79.1812%**，
双手续费 **-84.6940%**，双滑点 **-93.4562%**。这是closed-trade研究口径，不是50000元账户收益；
一笔换月中断和一笔期末未平仓单列排除。筛选年与诊断WF重叠，不能称独立未见OOS。
因此页面赢家不满足进入执行阶段的研究证据，不自动换候选或启用策略。

独立本地Paper实例端口15462（未改生产5432），账户`jm-dual-5m-20260928`完成
2026-09-28..2026-10-09真实Canonical历史回放：1551命令/事件、55次模型成交、
期末权益49364.702元、保留JM2701一手及一个未完成平仓意图。9月29日触发2%停机并平仓，当日未再开仓。
相同计划重复执行事件/成交数不变，新进程独立重放一致。这是HISTORICAL_REPLAY，不是实时Paper/Shadow。

Paper/研究116项（含真实隔离PostgreSQL）及工程合同29项通过；独立高风险Review问题已修复。
没有发布、运行切换、Broker接入、通知、真实资金订单或后台自动执行。`auto_order=false`。
该检查点之后已完成上节同口径矩阵复核；当前5m双策略不进入SimNow自动交易。

## 旧P9未知结果与恢复边界（不得据新闭环自动关闭）

P0–P8 工程和隔离验收已经集成；**P9 生产闭环未完成**。Newow 页面参考投影验收不等于持久化统一参考交易验收。

- 460 个 SuBing D1 质量候选已一次性原子发布；生产读回 `already_applied=460/460`、`old_count=0`。
  3,113 个源 Close=0 分类为 `NONPOSITIVE_CLOSE_SOURCE_FACT`，保留 5,175 根有效 Bar 与显式质量事实。
  精确备份及 journal：`outputs/reference-p9-d1-quality-20260925/`。
- 首波 175 单元 warm-up 中前 6 单元已提交、读回 80 个分区，已知 provider 请求 21 次。
  第 7 单元 `al/AL2302/15m` 为 `UNIT_OUTCOME_UNKNOWN`：22 个目标仍未发布、请求次数无法证明，
  **未重试，余 168 单元未启动**。结果不明保持阻断，不用重规划缺失证明请求可安全重试。
- 最近一次 600 流只读审计为 `SOURCE_READY=387 / BLOCKED=213`；之后 15 条 W1 流复核中 SC/SI 六条
  SOURCE_READY，PL/PX/RS 九条仍为 `REFERENCE_BOUNDARY_CONTEXT_MISSING`。这些是对应旧精确提交的审计，
  当前版本完整矩阵、历史构建与持续更新须重新绑定 exact code/input identity，不能沿用旧结论。
- 0048 migration及本轮Newow720历史构建、记录worker启用已完成；全局persisted reader与其他P9范围须按各自证据验收，不能由Newow闭环推定完成。
  2026-10-08历史检查点：v1.14.3 worker恢复85条旧阻塞；该检查点worker为v1.14.5（当前身份见顶部），136条23:00遗漏已恢复，自然验收见顶部。旧P9未知结果与恢复边界保留。
- A2611 旧来源请求已按 `SOURCE_RESPONSE_IDENTITY_INVALID` 停止且禁止重试；后续 D1 修复后重审无新恢复目标，
  不是对旧请求的重试。六个 W1 新批次共 64 个 W1 与 64 个 D1 同源上下文目标通过，来源 journal 64 次请求。

完整 P9 证据与恢复边界见 [rollout](docs/tasks/unified-reference-trading-p9/rollout.md)，
`outputs/reference-p9-warmup-wave1-20260925/`、`outputs/reference-p9-source-inventory-20260925/`。
旧盘后 D/E/F 已关闭，不重跑；旧事故未证明的生产归因继续保持证据不足。

## 已接受的后续交付规划

日周交付 → 关闭已记录页面缺口与自然维护验收 → Web 体验改善与分钟数据准备 → 分钟产品独立验收开放。
当前日周交付已发布；不能再按旧 v1.10.8/v1.10.9 检查点把该阶段重开，或把最新切换认定为自然验收通过。

- Web 正确性随对应版本验收，纯 Web 改善不等待分钟补数；不顺带改变公式、参考收益或数据来源。
- 分钟准备由同物理合约 Canonical 1m 派生，复用 Catalog/MDS、Session、质量校验、维护锁与预算；
  去重窗口、有源先派生，只对明确缺失安排恢复，失败按合同停止。补数完成不自动开放产品。
- 分钟开放分别验预热、Session 聚合、换主力、completed Bar、参考记录、分页与故障状态；
  跨周期解释保留 bar_end/as_of，不用未来完成周线回填历史决策。
- 策略公式、页面参考、因果研究、OOS/Walk-forward、Shadow 和账户事实分别验收；解释评分不自动成为执行 Gate。

## 唯一下一步

按本页顶部最新发布、Runtime 身份及未完成事项推进；本节不另存版本号或复制阶段待办，
避免历史检查点覆盖当前结论。自然 completed Bar、发送及 Live→Canonical 验收分别保留真实证据，
不制造 Bar、不盲目重试，也不扩大现役运行范围。

### 苏冰交付所需交接修复：1.16.10候选

诊断补丁v1.16.9已发布PR488，exact `cb6836a4abe3f733f59161242c0e4d9756acda20`。
全新v5完整预热、日历暂停、旧所有者排空退出均通过，停在preserve（ValueError）并恢复旧gen29，未CAS。
已现场只读定位：稳定历史刷新控制约2.27MB，交接普通配置读取默认1MiB，而该控制读取器本身既有64MB上限。
1.16.10候选仅对稳定目录下精确控制文件名复用同一既有上限，fd/权限/owner/nlink/链接/读前后校验全保留；
现场修正读取完整2.65MB成功，不改文件。256相关回归/2明确跳过、Review后109/2、独立141/2、
版本/前端构建/Ruff/secret/diff通过，不声明正式切换成功。下一步发布该最小修复，再生成全新计划。
