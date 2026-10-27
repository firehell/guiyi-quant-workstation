# 主力切换准备与Reference连续恢复实施

Owner批准完整方案：自动预算内预热；顺序恢复真实原件并标记延迟；不补发过期通知。
基线6ca3c3cc337421b30487cb050b814fef0ee28fda，独立feature/rollover-readiness-inbox。
原develop两处Web修改不属于本任务。

- [x] 统一权威新主力数据准备：64 requests/2M bars per contract、256/8M per trading day、1200s准入，独立线程和原生维护锁。
- [x] 两表持久接收与逐流完成事务、120000/day与6GiB未完成容量；DB确认后才ACK。
- [x] 逐流公平调度及延迟时间、原生协议边界切换和健康接口。
- [x] 单元/隔离PG+Redis/故障注入、独立Review。
- [x] 生产0053单次迁移、独立schema读回；兼容代码发布至v1.16.13。
- [ ] Runtime/v2独占交接、EG自动准备与原件顺序恢复、重启一致性及自然业务验收（维护锁竞争阻断）。

当前根因原件：原workspace output/reference-stall-diagnosis-20261026。
真实操作串行；schema/protocol推进后只能兼容恢复或前向修复，不删除数据回滚。

实现与验证记录：
- 新增 contract_preparation / contract_preparation_runtime：稳定状态、预算预留、原生锁内权威复验、后台线程；逐消费者结果与只读缓存健康分离。
- 新增 inbox / inbox_protocol 与0053：不可变原件和冻结路由；DB提交先于ACK；逐流有界轮转，缺历史/原件冲突/未知提交分开。
- retained replay经唯一MarketDataService验证，不用provider替代缺失原件；原始时间及delivery_timing_v2随计算保存，通知有效期不刷新。
- 整组切换仅新增精确0053已预装兼容证明；停服前/CAS前重新校验schema、plan期限及停机预算。
- 独立storage Review：22真实PG用例通过；Runtime/Market Review修正后无Confirmed Issue，允许集成develop。
- 旧720容量测试原分支已是1440路；exact基线复现1440!=1260后，仅更新六周期1440路断言，真实PG容量/重启幂等用例通过。
- 409项最终合跑曾有1项fixture导入顺序污染，最小修正仅涉及测试别名patch；整份host65通过，扩大回归进行中。
- Market/切换专项最终446通过；Web type/build/capability/topology通过；OpenSpec12/12、secret0、Ruff与diff通过。
- 0052→0053离线DDL dry-run：5125 bytes，sha256 18f3f74d83b441c863938363c127469f78ad1764318047637deac3ab7dd38f98。
- 当前尚无生产迁移、补数、协议推进、发布或Runtime切换；v1.16.11仅候选版本标记。
- 回滚：DDL失败事务回滚；原件非空禁止downgrade；首个v2接收后仅兼容恢复/前向修复。不开启额外通知或交易。

最终冻结核心回归：带隔离PG/Redis运行 inbox/protocol/runtime/wake/retained-replay、contract-preparation、runtime-health/schema/cohort/host共315 passed/7.97s。最终逐品种authority等待隔离独立Review通过，无新增Confirmed Issue；公开health增加同一有界字段，120项健康测试通过。扩大Reference回归仍运行，尚无新失败。

扩大回归最终1553 passed/664.96s（Reference全模块、准备/HDM、schema/cohort/host/runtime-health，真实隔离PG/Redis）；fixture污染已修正。合并origin/develop后的精确候选86ec793eb定向324 passed/11.35s，Web重新build/type/topology通过，secret0/diff通过。独立Review允许集成。

23:25 PR497集成develop31628cfa1；生产0052→0053单次migration已confirmed。独立schema proof f822759925d99fe3ff125adc6630f7f1e4bdba3ff666db0a7455484348df337b（数据库身份hash独立保存），两表0行。唯一intent、结果保存在output/rollover-readiness-20261026/migration-{intent,result}.json；未启用协议或改游标，Runtime仍v1.16.10/gen30。

10/27凌晨续办：03:05现场复核0053 schema完整，原有十服务仍v1.16.10/gen30，binding hash16d0b1aa...，两表未接收。追加develop改动定向104 passed。PR498已正式发布v1.16.11 exact397fbd1423fac4d5a6257121631852332a04d3a6；正式树依赖与Web构建通过且editable来源重绑新树。
原生cohort v1计划17a27cc3f2ae0c3c2dceeebe46844788155a61379e10f629d1f18283804f1c8b在prewarm阶段cancelled，effects={}，COHORT_CANDIDATE_WARMUP_FAILED；未停服/未CAS，不复用该attempt。独立Alert只读诊断继续定位，未改scope、游标或发通知。
另已确认P1：凌晨CLOSED不创建历史准备需求，等到08:30才触发，不满足启动恢复。已在forward修复分支使用既有latest-started Session owner，严格cutoff<owner才准入，不用civil day推断；两文件91项通过，独立Review进行中，候选版本1.16.12，尚未发布。

凌晨向前修复最终完成：CLOSED通过latest-started权威Session owner准入；初始flatseed完整校验计initialized而非calculated；v2 receiving_cycle在完整有界轮结束报告，原计算ready/blocked不变，owner失权/排空不写错误状态或发布可接受报告。新原生运行证明全head精确验证、当前StreamIdentity/原件channel/revision/gen/receipt/hash、合法waiting与blocked全等、普通pending无error、active protocol/0053独立复验；legacy和原native时限不变。
独立Review修正identity漂移P1、无效proof误标owner ready的P2后，225 passed/0 skipped。最终冻结父级组合387 passed/11.42s，含真实PG/Redis；Ruff、OpenSpec12/12、secret0、uv lock及diff通过。1.16.12待集成/发布，未提前声明运行切换。
保留原件：retained-originals-20261027/2026-10-27.jsonl共8956条、sha256925267707e10651a88e195fda640f707c14594a40650966cb37e3e7cc6060e57；cursor1793019905299-0前后不变，tail1793039404268-4。导出仅证据，不替代正式入口或用于伪造回放。

后续真实结果：PR501/502已发布v1.16.12 exact3426d89763bb107ef00ee6381b0a3e1e7da66997，正式树依赖、source roots、Web重新构建通过。原失败M/1w真实seed只读验证initialized且computed_bars=0。被动v2 request在03:58登记，旧游标前后相同；协议尚非active。
新native cohort计划0d5754d32595e5a0ce27aa4d5332096af38b72acc09d93cf5b74c1827a684e4b在04:03仍prewarm取消，effects={}，未停服/CAS；actual-env只读Reference诊断定位REFERENCE_WARMUP_TIMEOUT。旧attempt保留不复用。
独立Review又确认warmup遗漏现有分组input cache；现按distinct工作键begin/finallyend，逐流验证和120s不减，实际effective policy加入缓存键，未知policy不缓存。217项独立回归/0skip通过，source仅worker_entry/input_cache两文件；候选1.16.13。
实际只读候选计时：120.033s后REFERENCE_WARMUP_TIMEOUT，lease_attempts1066、lease_busy985（约98s既有0.1s等待），cache_misses27、cache_hits54；确认缓存生效但维护锁竞争仍阻断，不延长期限、不减Scope/跳锁。并行另一个已交办历史参考资产更新进程仍运行，不干预它。
8956条原始envelope、精确journal ID及游标证据已复制到主仓库稳定私有output/rollover-readiness-20261026/retained-originals-20261027；导出不是第二正式输入源。生产0053不重复，Runtime仍v1.16.10/gen30；新协议仅requested，尚无EG补数或过期推送。

共享输入候选最终227 passed/16.20s，含实际隔离PG/Redis相关恢复；独立Review217 passed/0skip，Ruff/secret0/diff通过。实际120s预热仍因985次锁忙终止，故Runtime gate未通过；候选代码验证不替代现场运行证据。

收尾现场：PR503/504已集成并发布v1.16.13 exactbe9c1a8dde70aa5db4716304aad33d7a7e7241ad，annotated tag与GitHub Release target一致，正式树Python metadata/app/core来源及Web build/type/topology通过。未再重试过期或失败native计划。04:42独立readback确认十服务仍旧v1.16.10/gen30，protocol requested，inputs/deliveries均0且唯一计数相等，准备state/budget无attempt，游标仍1793019905299-0（tail1793039404268-4）。这只证明没有误切换/误接收，不证明业务恢复。
稳定只读证据：主仓库output/rollover-readiness-20261026/prewarm-sharing-timing.json及runtime-readback-blocked-final.json；8956条原件在其retained-originals-20261027内。两份原生失败attempt保持私有稳定目录原样。当前PARTIAL / Runtime gate pending，不是等待重复人工批准；须维护资源释放后新建精确计划。
按精确retention dry-run哈希1f6da9e68b989dc58a6abdd420f81063c687ce52ccc53ba58429136becbb8a38并二次同像核对，v11/v12无任何binding/plist/进程引用且新v13依赖不指向它们，已non-force移除两棵从未运行的旧树；保留现役v10、最新v13、所有tag及控制/原件证据。任务隔离PG/Redis已精确停止，不影响生产或另一任务。

10/27 08:05 owner再次交办Runtime切换。维护锁独立读回0，fresh原生计划a95c301ee550e7d1ecbbf0fe0584800bf20d667061899c8a634646963b342ba6通过全预热：Alert413计算/7warming、Reference480计算/120initialized、其余服务通过。drain在旧COHORT_OBSERVATION_BACKLOG取消并恢复gen30，未CAS。只读复核enabled pending_capture=0，不放宽该Gate。
定位为已批准协议交接步骤与旧“所有consumer必须追尾”条件冲突；正实现专用Reference v2 backlog handover proof：仅目标能力+实际intent+完整已停驻原件后缀证明可接纳积压，其他consumer/pending capture/owner/锁/时间Gate不变，stop前和CAS前重证。候选v1.16.14，不改v13标签或原件/游标。

08:36候选只读现场扫描通过：2分区8956未ACK原件、5,185,538 bytes、1080 enabled；复用完整ingest envelope及identity id/content/payload校验。content_sha256=ef675b18a5f01fe9934af1e464277fc740fe9c69cfd553506ce912da72b9a6c2；progress_sha256=bfcc3406862c85b02d64f6060f347d49e8be3faba24717ed07c1a9b3686479fa。首轮环境bootstrap缺Redis URL的blocked摘要保留，使用既有安全bootstrap后的独立scan通过；零ACK/协议/DB写。候选定向121及扩展126通过，Ruff/diff检查通过；PR505待独立Review结论后集成。

08:40 PR505/506完成集成发布，v1.16.14 annotated tag/GitHub Release exact5587cd1483a43ef591ee686ebd4cc53606d201b0，正式树构建/来源通过；独立Review207 passed/0 skipped，Ruff/diff通过，无Confirmed Issue。新原生计划ac053cb4df214a5b9864f5cd8a9af1a087f364f7aa102e452e4e2648656ee260通过完整预热与停服/CAS前schema/原件复验，已CAS十服务至v14/gen31，实际新Reference独占启用v2。
08:49到达Session>660秒边界，consumers_ready仍要求8956原件全部接收追尾而实际约5条/s，原生以COHORT_WINDOW_TOO_SHORT_OR_UNKNOWN进入outcome_unknown并停驻；未启动Feed，未注册日历，不能声明switched/RUNTIME_READY，禁止旧语义回滚。独立停驻读回：Reference parked，protocol active无intake_error，completed1031、WAITING4、BLOCKED35（NO_CALCULATION29/FUSION_SOURCE_ACTION_CORRUPT6）、PENDING336；原始游标前像保留，当前接收游标1793025126212-0、尾1793039404268-4。准备43READY/15WAITING_DEPENDENCY/8READBACK_REQUIRED、来源预算0。证据runtime-readback-switch-v14-{initial,progress,stopped}.json独立保留。下一步需接收存活/积压追尾分离的向前契约与可审计postCAS恢复；先只读定位计算及准备失败，旧attempt不改成功、不盲重试。

10/27 当前owner明确交办：完成接收证明及当前版本恢复入口，先恢复正常采集。receiving_liveness已完成并独立Review通过：37 passed/0 skipped，含真实隔离PG16/Redis7、LuaACK、READ ONLY RR、跨chunk[128,128,4]；原生cohort/schema/protocol/health扩展237 passed。新append及ACK跨旧tail仍逐条验证新增DB前缀，原件计算BLOCKED不冒充intake失败。新恢复控制器候选v1.16.15仅用于恢复已安装v1.16.14/gen31，不重新CAS/install/改配置。
真实分组件只读preflight确认：8956原SourceProof完整，DB原件5120（与1406投递不是同一粒度），pending capture0/UNKNOWN0、60品种权威samegen startup Session/rank1/订阅/注册日均通过。09:15:37 Live exactgen31固定drain下active、launchd runs156/last exit1且PID持续变，其余消费者parked、Feed absent；公开日志只有CLI_INTERNAL_ERROR/RuntimeError，不能断言内部具体异常。独立Review认可新增严格单次native Live bootout→整个label absent/所有观察PID退出/owner锁空闲→原件/DB/身份重验→原binding startup分支；候选仍待最终Review/正式controller发布及独立恢复验收，未执行新production mutation。

恢复控制器最终冻结：324项扩大回归通过（含真实隔离PG/Redis），implementer组合206通过；独立Review两P1（未owned在途PID退出集合、两份预冻结计划unknown后禁重试）均关闭，定向72通过、接收证明独立37通过；Ruff/diff通过。候选待正式v1.16.15 controller发布；目标运行仍v1.16.14/gen31，不把控制器发布冒充消费者切换。

09:38 controller v1.16.15已由PR508集成develop、PR509选择性发布main exact78c04ab04cdaabc29762b34678eb38258261e43a，annotated tag/Release/干净正式树及构建来源验证通过。真实freeze只读预检以COHORT_FORWARD_PROTECTED_DRIFT拒绝，forward-recovery-01.json未创建，无attempt/bootout/启动/游标mutation。已独立证明old protected完整不变、old/new DBScope相同、34/34 files共同路径无变化；仅oldroot10与newroot14各自5个.run绝对路径不同。不得抹平或忽略，向前修正为old完整前像保留+new独立保护快照冻结/逐阶段pin；准备controller16，运行目标仍v14/gen31。独立Review已确认此根因及最小修复边界。

controller16 protected修复最终334项组合回归通过；实现方179、独立Review178通过，Ruff/diff通过，无未关闭Confirmed Issue。真实old/new保护helper及new冻结值再次读回通过；正式15实际_fixed不调用通用installed(new)，单独诊断该通用入口的Live转换态错误不属于恢复执行路径，未为其扩大补丁。只修保护前像绑定，现仍未创建新恢复plan或执行生产mutation。

controller16 PR511/512已集成/选择性发布main exact73051b85650a3a203b3696c87b225b36b69b6718，annotated tag/Release/干净正式树和构建来源通过。新plan94f864cbbbed9bdfecf3efc614dc3851bf857cccbcb3780a839137b614b325a0成功freeze；apply仅记录live_stop/bootout_requested后进入新outcome_unknown，error_code=COHORT_FORWARD_STEP_FAILED，未存异常类，不能倒推原异常原因。停止mutation，未重试。10:14父端原生独立readback：Live label absent、7已观察PID均退出、owner锁free；Feed absent，其余4consumer精确gen31 parked。10:16数据库completed1031/PENDING336/WAITING4/BLOCKED35/UNKNOWN0，prep43READY/80READBACK/159WAITDEP。原cohort unknown和新recovery unknown原字节保留；经独立Review认可，准备仅此已确认前缀的controller17 continuation，绑定两层字节hash+effect，从consumers继续、不调用bootout、不泛放宽unknown Gate。

controller17 continuation最终冻结：357项扩大回归通过（含真实隔离PG/Redis），实现方202、独立Review201/冻结后83通过，无未关闭Confirmed Issue，Ruff/diff通过。唯一A94f的target/Live binding、六字段proof及两层字节关联、额外effects/unknown/Live再现/锁/PID/receipt漂移与重复B反证完整。真实readonly load前驱→唯一未决Gate→native确认前缀PASS，SHA6f50762afd544e74a21d1ed86ce4074ebb2c40813f76d1684b2ffded5f0dcab6；formal17 fullfreeze/apply仍待，未重试A。

### 10/27 11:50 owner交办恢复前的新鲜核对：阻塞，未重试

本轮按“先恢复采集、再补历史”交办核对，实际绑定仍v1.16.14/gen31。已发布controller17 exact
43bcd12a5仅为控制器版本，不是当前消费者版本。发现状态正文之后的两个真实恢复attempt：
94f864cb仅记录live_stop/bootout_requested后unknown；3f493c8d在10:53记录consumers/resumed_generation31，
失败阶段intake、公开代码COHORT_FORWARD_STEP_FAILED、异常类REDACTED，随后原生halt重新停驻。
不能由脱敏信息推断失败根因；旧plan/attempt不改写、不重跑。

11:46生产只读readback：Reference原件8956，10/27 cursor=tail=1793039404268-4；
completed2118、PENDING487、WAITING_HISTORY4、BLOCKED44、UNKNOWN0，末次计算10:53:32北京时间。
BLOCKED分为REFERENCE_INBOX_NO_CALCULATION38、REFERENCE_FUSION_SOURCE_ACTION_CORRUPT6。
11:48/11:50独立原生snapshot校验8956已ACK原件及冻结routes完整、旧尾已达；这不证明实时采集或计算恢复。
60品种same-generation startup Session/rank1/订阅/注册交易日通过（BREAK）。
原生未决恢复Gate明确拒绝COHORT_FORWARD_RECOVERY_READBACK_REQUIRED；当前controller17不支持直接闭合
第二个consumers→intake失败前缀。未生成第三份plan，未执行bootout、启动、配置变更、ACK或下载。
launchd只读确认Feed、after-market、late-provider-recovery、weekly-audit、log-rotate均未加载；
18:05盘后任务不能假定会自然运行。API/Web HTTP检查未通过，整体保持BLOCKED，不声明RUNTIME_READY。

现场原件：output/rollover-readiness-20261026/runtime-readback-recovery-owner1149.json及
owner-recovery-preflight-20261027-1150.json。控制器正式树运行
`./services/quant-api/.venv/bin/python -m pytest services/quant-api/tests/test_runtime_cohort_forward_recovery.py -q`
实际81 passed/1.39s；该结果只证明控制器定向测试，不证明生产恢复。下一步为定位intake失败并实现、独立Review
精确当前停驻前缀的向前恢复证明，再用全新计划恢复；不能靠等收盘、补历史或清除unknown替代。


### 10/27 controller18发布及真实恢复：接收通过，综合验证失败后停驻

owner交办“处理下一步”后完成窄范围confirmed_intake_halt：只接纳A Live-stop unknown→B
confirmed_live_stop/consumers完成且intake失败，重新核对当前全部消费者parked、锁、配置/Scope、
Session及完整当前ACK尾部。schema2接收快照增加current_tail/final_tail；两轮真实追齐可在盘中证明idle，
合法零进展保留原预算等待，错误/回退不吞。旧schema1摘要以完整源/DB/routes和当前尾部证明处理。
独立Review发现冻结context未在首样本和Feed前固定的P2，已用真实协议activated_at变更反证红→绿修复；
复核无未关闭Confirmed Issue，恢复模块99 passed，最终扩大真实隔离PG/Redis329 passed/0 skipped/6.55s，
独立141 passed/1 skipped（PG由主端另验）、OpenSpec12/12、uv lock/Ruff/format/diff通过，secret0。

任务提交4725077fd，精确集成develop7e9626363并推送；PR517已合并main、annotated v1.16.18及GitHub Release
exact762b4f39b323bc8e2627968132c8c0bad05be89f。宿主首次拒main merge（授权范围理解为仅修复/PR）；
补充owner明确实施计划中的“控制器发布”原文及项目发布授权后复核允许，未绕过控制。
正式18树干净，离线依赖重绑、API/core实际来源、Web type/build/topology通过；只发布控制器，不CAS现役服务。

12:14左右新原生计划425ab52431be579089217f0ede09955e10b36dba6891dab12c10b5e6953f2f86
（forward-recovery-03.json）freeze通过。一次apply记录consumers/resumed_generation31、intake成功
schema2/durable_receiving_caught_up_idle/advanced0/remaining0及Feed bootstrapped。
随后failed_stage=verified、COHORT_FORWARD_STEP_FAILED、error_type=REDACTED，原生outcome_unknown并halt。
未写成功receipt、未更新全局成功指针，未注册日历，未重试C。不能把intake/Feed启动冒充恢复完成。

12:19独立readback：绑定仍v1.16.14/gen31；原件8956/唯一8956、cursor=tail=1793039404268-4；
COMPLETED2489/PENDING116/WAITING_HISTORY4/BLOCKED44/UNKNOWN0。原cohort/A/B公共plan和状态及binding
七份SHA前像逐一不变。证据output/rollover-readiness-20261026/runtime-readback-recovery18-stopped.json、
recovery18-immutable-before.json，以及原生C私有attempt目录；不重复制造原生receipt。

独立只读诊断未见loopback代理或Web静态根误配证据。纯隔离已复现另一确定性缺陷：_await的旧before为t0、
下一有效轮为t31时会在原240秒预算尚余209秒时抛ReceivingLivenessError，而同context的t31/t32可证明存活。
C未保留verified子阶段/完整采样时间，不能据异常兼容性断言历史原因。尚未修复此采样窗口缺陷，也未发布controller19。
当前BLOCKED：需保留完整context/ACK非回退链并独立刷新活性样本，增加verified安全分步骤诊断；
C包含Feed effect，已超出仅A/B continuation，必须先有精确已停驻Feed与输入关闭证明，才能规划新的恢复。
现有C不能复用，也不能递归塞入A/B入口；自然新Bar、18:05调度与今日历史缺口仍未验收。

### 10/27 控制器活性采样窗口及verified诊断修复（未发布、未执行恢复）

Owner本轮仅交办采样过期提前失败修复、verified子步骤诊断及上次Feed停驻证明。
基线58a56e69a；独立fix/recovery-validation-sampling实现，不重跑C、不新增恢复前缀模式、不改变生产配置。

真实隔离snapshot复现t0→t31：原`_await`仍在120/240秒预算内，却因一直持有t0活性样本抛
`REFERENCE_RECEIVING_LIVENESS_UNPROVEN`。回归先失败后通过。现将完整连续性与活性新鲜度分离：
每次snapshot（包括同owner cycle）保留静态context、完整原件/routes及ACK/数据库前缀非回退链；
样本过期只在该链验证后滚动活性窗口，必须再取得两轮不同且新鲜的cycle。最终身份检查后再次核验
freshness，不返回检查期间已经过期的证明。完整性错误仍立即失败，120/240/600秒预算和计划期限不扩。

新attempt的verified失败仅记录固定子步骤、合法带时区的样本/cycle时间；覆盖来源采样、连续性/活性、
身份、API/Web、预算和步骤后保护复验。精确ReceivingLivenessError只保留固定公开码/类型，任意异常
原文、SQL、回溯和自由诊断标签不进入记录。旧C未保留相应子阶段及完整采样时间，仍不能断言其实际失败
就是此次已复现缺陷；原plan/state/unknown不改。

12:46:50–12:47:00独立只读Feed证明：binding/installed/loaded均v1.16.14 exact5587cd/gen31，
实际PID40577与parked owner一致、精确drain固定、OS owner锁free；source/completed各交易日tail/ACK
两次读回稳定且追齐。exact v14的正常关闭路径先完成`close_verified`、listener退出及有界buffer处理，
成功返回后才由ownership写parked，因此确认其已按既有合同完成协作停驻。原证据
`output/rollover-readiness-20261026/feed-park-independent-20261027T044700Z.json`，SHA256
765aaa7c36f2662b1227a39a2dbffda7cb1373a99cf9183909b86e909cc4eea6。
短TTL关闭heartbeat当前缺失，未留存可读取的关闭快照；读取null不单独证明其消失原因。
独立socket核对仍有一项非loopback CLOSE_WAIT；不将其误称active provider，
也不声明所有socket FD已释放或已取得当前provider/subscription/pending完整typed快照。
该协作停驻证明不替代下一次恢复的新鲜精确前置证明，C含Feed effect的未决边界仍保留。

扩大回归369 passed/0 skipped（本次新建无持久卷、非生产端口PostgreSQL/Redis），覆盖整组恢复、
handover/deployment/schema、诊断隐私及接收前缀；初轮无隔离依赖的skip不计入该结果。
测试Redis fixture改为显式本次`GUIYI_TEST_REDIS_PORT`，不再复用旧任务固定端口。
独立Review无Confirmed Issue，允许集成develop；独立真实隔离PG/Redis定向175 passed/0 skipped。
Ruff/format、secret scan 0、diff通过。CODE_COMPLETE / TEST_COMPLETE / REVIEW_COMPLETE；
Feed当前typed关闭快照与C精确恢复前缀仍是后续运行验证范围，不以本补丁关闭。
本轮零生产数据写入、零启动/停止/恢复命令、零通知，不发布、不切换Runtime。

### 10/27 含Feed启动失败前缀的精确关闭与恢复入口

Owner交办补齐C精确恢复入口及新鲜关闭证明；基线09af79416，独立fix/feed-halt-recovery。
本轮实际操作终点仅关闭已parked的Feed并取证，不启动消费者/采集、不切现役v14/gen31；
控制器候选v1.16.19用于执行此次原生关闭，后续整组恢复仍是独立动作。

新增`confirmed_feed_halt`严格验证A→B→C公共/私有plan、state、effects及保护前像。C只能是已确认
intake halt后完成consumers/intake/Feed且在verified失败，不能递归接纳额外unknown。
`--close-feed-only`把`stop_after=feed_close`写入plan hash；先落盘单次bootout意图，再核验所有观察PID
及后代退出、label absent、锁free和两次完整source原件/identity索引及completed DB/routes前缀不变。
关闭成功仅写feed_close_readback和feed_closed终态，不写全恢复指针、不解析A/B/C为已恢复。
正常恢复计划必须显式引用该关闭计划，重新现场核验，并在每阶段保护D的公共/私有plan、state、receipt字节。
失败D保留unknown并阻断，不补发卸载、不把第四unknown变成新前驱。

独立Review发现两项P1（阶段间未重验D字节、卸载等待未覆盖新增PID）及一项P2（历史intake mode/tail
不可能组合），均先以反证测试复现，再修正。主端扩大真实一次性PG/Redis回归395 passed/0 skipped，
独立初轮四模块200 passed/1 skipped；该skip仅真实依赖未并发使用，不计为生产验收。
候选真实只读feed_close_intent预检7.13秒：全部source原件/identity索引和completed DB/routes双读通过，
实际观察PID40577，frontiers_sha256=802e87444d50586cbd7bdfe0cd23f0acd50f294e414aa0f051e9c74a1fed391b。
诊断原件`output/rollover-readiness-20261026/feed-close-intent-preflight-20261027.json`；它不是关闭receipt。
本节编写时尚未发布controller19或执行bootout，生产结果待后续实际回读。

controller19后续由PR519发布，main/tag/Release exactd7fb9122f77127fd9f41152c5b0553349ad9cf24；
正式候选395 passed/0 skipped及Web type/build/topology、API/core新根来源、Ruff/format/secret0/diff通过。
最终独立四模块真实PG/Redis201 passed/0 skipped；无未关闭Confirmed Issue。仅控制器发布，无消费者CAS。

初次只读freeze因外部包装未继承现役OBSERVATION_STREAM开关拒绝，无plan/attempt；安全绑定既有Feed
plist两开关到本进程后，13:46:44新D plan3c8496a9301636d97856c5ff68c4c288e4d542bf7a65d4d1a610242074810d68
成功freeze，stop_after=feed_close。一次apply记录唯一bootout_requested后以SERVICE_IDENTITY_INVALID/
RuntimeIdentityError停为outcome_unknown，failed_stage=feed_stop_intent，无成功receipt。没有重跑D。
13:52:23独立确认label absent、PID40577退出、OS锁free、drain未变及完整双前缀SHA802e...391b等于意图。
D public/private SHA c95272a13822fcaf9081decadac9985d3c84a931b27f25bab6f896d2314153a2，
state SHA2cbb853b50a17875d9ea25c43503a911b8e7bae7d06581ceff5192540bb95819；全程原字节保留。
诊断`output/rollover-readiness-20261026/feed-close-unknown-independent-20261027T055223Z.json`，
SHAe7de0af7fe46d7b7e51efccb75658ec617ea77f8d553d6d3d55acad8baab014d，不冒充成功receipt。

controller20向前候选：隔离exiting-state样本复现旧ready式身份解析过严；仅卸载后的PID观察改为精确
静态root/commit/tag/generation/args及header PID校验，最终仍要求label absent及PID全集退出。
实际D未保存完整过渡state，不能据此断言其具体历史状态。新增confirm-feed-close只对该精确D及CBA
进行历史身份校验和新鲜OS/锁/双前缀读回，不调用launch、不执行过期计划、不创建新attempt；只写一次
精确关联D公共/私有plan和state原字节的feed-close-confirmation。D unknown不改，额外unknown继续拒绝，
E每阶段pin确认字节，D不能变成第五层递归前驱。此处尚未执行新确认，不宣称全组恢复。
controller20最终扩大真实隔离PG/Redis406 passed/0 skipped，独立四模块212 passed/0 skipped；
Ruff/format、uv lock offline、secret0及diff通过，独立Review无Confirmed Issue，允许进入release candidate。


### 10/27 15:00后恢复及单发布树收敛计划（待执行）

Owner本轮目标：北京时间今日15:00收盘后开始修复，先让整站服务恢复可用，再将发布树及正式服务版本统一到一个。
本节是执行方案，不是恢复成功记录。14:40现场：十服务绑定v14/gen31；五消费者parked；Feed及四日历absent；
API/Web不可达；生产PG/Redis可读；原件8956/唯一8956，Reference cursor=tail；COMPLETED2489/PENDING116/
WAITING_HISTORY4/BLOCKED44/UNKNOWN0。控制器v20已发布，14:11完成D新鲜只读关闭确认；D原unknown保留。
14:13冻结但未执行的E(64b6c383...)已在14:28过期，禁止apply。STATUS旧正文尚未反映以上完成项，执行时先对齐。

**选择的路线**：已发布v20恢复当前v14 → 可用性验收 → 精确恢复链收尾、发布树依赖脱离和切换验收修复 →
一个最终补丁版本整组切换 → 删除全部无引用旧发布树。最终版本在执行时核对远端后分配，不提前宣称v21已存在。
不选直接强启各进程：会绕过当前unknown、drain、owner及接收协议关联。不选先写完所有收敛改动再恢复：延长停服。
15:00是开始现场检查时间，不是固定切换/完成时间；正式promotion仍需逐品种权威Session和原窗口校验，不能由钟点替代。

#### 1. 15:00先冻结现场并恢复现有服务（最高优先）

- [ ] 核对task/develop/main、工作区dirty及其他任务；不混入SimNow独立修改。读取当前binding、plists、loaded/PID、
  owner/锁、cohort全局指针、C/B/A/D原件及D确认字节；核对数据库/Redis、Scope、协议和原件/ACK/routes完整连续性。
- [ ] 只读确认过期E没有attempt/effect（不能仅凭聊天推断）；保留E原文件。确认D关闭证明仍可独立重证，生产重启或
  新writer导致漂移时立即定位，不复用旧快照或改写原unknown。对齐STATUS真实当前状态。
- [ ] 在v20精确干净树下，使用现有`app.runtime_cohort_recovery plan`（原cohort + C前驱 + D关闭引用）冻结全新计划，
  使用全新输出名；TTL15分钟、总预算600秒不变。新鲜预检通过后立即一次apply，不再次bootout已关闭Feed。
- [ ] 严格按现有`consumers → intake → feed → verified → calendars`次序恢复；不能为先开页面手工取消单个drain。
  verified固定子步骤、时间和安全错误码留证；真实错误停止相关mutation，禁止重复apply/递归增加unknown链。
- [ ] 独立核对recovered receipt、全局switched及原失败字节不变。API版本/health、Web及真实数据页可用，
  五消费者active且fresh、Feed在休市可合法idle但身份/订阅/Session正确、原四日历重新注册且时间正确。
  连续两次读回跨至少两轮，不以进程存在、单次200或数据库存活代替闭环。

**失败边界**：若这次新尝试不能完成，用本次诊断定位一个具体阻断，先在隔离依赖复现/测试/Review，再形成精确向前
修复；不移动tag、不重试effect、不不断套新前驱。该阶段未通过，不启动正式整组promotion和旧树删除。

#### 2. 在已恢复服务基础上准备一次最终版本

- [ ] 修复`runtime_cohort_host.py`版本交接的验收口径：复用receiving_liveness完整context/原件/routes/ACK非回退与双fresh
  cycle证明；区分接收活性、历史积压、计算质量。核对`consumers_ready`及最终verify都使用正确合同，不能只修恢复入口。
  合法WAITING/BLOCKED不伪装ready；未知提交、原件缺失和身份漂移仍阻断。原时间/资源预算不放宽。
- [ ] 解决恢复历史对旧源码根的永久依赖。现`_closed_predecessors`/`_feed_close_attempt`仍会通过
  `_feed_predecessor → _intake_predecessor → _predecessor`逐个verify_release，即恢复成功也不能直接删旧树。
  在已有成功receipt及现场终态证明基础上，增加最小终态收尾合同：绑定原cohort/A/B/C/D/confirmation/成功计划与receipt
  的精确字节哈希、历史tag/commit及成功时current binding；保存实际仍需读取的非Git证据于既有私有Runtime目录。
  原始失败记录不改、不删除，不把unknown本身改成success；只将有完整成功关联的事故标记为已被该成功结果闭合。
  以后历史闭合校验不要求旧checkout存在；当前实际部署身份仍必须验证真实checkout。未闭合或不匹配的unknown继续拒绝。
  覆盖`_closed_predecessors`、`_feed_close_attempt`、`_source`/global指针及`_protected_preimages`等全部旧根读取路径；
  最终cohort切换新增的old=v14前像也须在成功后闭合，不以旧A/B/C/D闭合作为可删v14的充分条件。
  只做本事故和现有恢复合同需要的最小变更，不建立新的通用证据平台。
- [ ] `runtime_retention.py`清理计划增加实际未闭合恢复根依赖检查：服务引用为零但仍有恢复依赖时保留；
  终态已闭合且证据校验有效才解除依赖。扫描不能通过忽略unknown/不认识label放行；SimNow已有兼容修复保留。
- [ ] 定向反证：旧checkout不存在后终态仍可校验；篡改任何关联字节、未闭合事故、额外unknown、归档缺失、
  错tag/commit、并发新增effect/绑定漂移均拒绝；收尾原子写/fsync、重复调用同一结果幂等、故障注入不误关事故。
  覆盖t0/t31活性回归、原pending/blocked不清零、新generation原件接收和最终校验，避免重现v14失败。
- [ ] 在原有隔离PG/Redis验证上述合同，退出时删除本任务容器。做一次高风险独立Review；统一canonical、TESTING及STATUS。
  无关Web/Broker/策略改动不纳入候选；commit/push/develop后集中形成一个最终补丁release，不按每个小修分别发布。

#### 3. 处理影响真实使用的数据阻断，避免带病切换

- [ ] 逐项核对4 WAITING及44 BLOCKED（38 NO_CALCULATION、6 FUSION_SOURCE_ACTION_CORRUPT）的当前真实原因；
  通过既有MDS/maintenance入口核对EG2701主力映射、物理历史、周期/窗口、Canonical/Catalog与原件关系。
- [ ] 先用精确dry-run冻结请求/Bar/窗口/预算/维护锁、原attempt及幂等恢复边界，再执行任务目标必需的真实修复；
  不清表、不强移游标、不reset未知提交、不删原件、不用Live替代Canonical，不补发过期通知。
  数据维护与Runtime mutation串行，避免再次用维护锁把交接预热拖死；18:05自然盘后任务的锁与运行边界优先核对。
- [ ] 原件恢复后分别验计算进展、缺口、错误、历史修复与新自然输入，不把已有8956原件追齐当作停采时段完整。
  不将所有数据准备完成设成API/Web保持停驻的条件。确有无法收敛的质量项按品种如实展示，不能以伪造ready结案。

#### 4. 同一最终版本整组上线，再减到一棵树

- [ ] 最终候选一次性完成定向/扩大验证、独立Review、main/tag/Release及新树构建/真实导入来源与Web版本校验。
  freeze后只收交付阻断，不再混入新需求。核对官方远端和其他任务变化，按需最小集成。
- [ ] 对当前运行整组先render/preflight及完整warmup；全部通过且Session/维护窗口允许时才使用原生cohort单次CAS。
  候选未通过不停止已恢复的v14；CAS前失败保持/恢复现有服务；CAS后结果不明停止相关mutation并独立读回，不盲回滚协议。
- [ ] 核对十服务binding、磁盘plist、loaded代码、PID来源、generation与版本相同（定时服务允许合法idle），
  API/Web同版本且主要页面有真实行情/参考数据；共享PG/Redis仍为原正式数据，SimNow独立宿主不混入十服务版本切换。
- [ ] 将恢复链精确终态收尾，解除历史旧树依赖。枚举全部release-*根，保留唯一现役最终根；逐棵检查
  binding/plist/loaded/进程及恢复依赖、dirty/untracked/ignored与非Git证据。先保全必要原件/SHA和最小重建办法。
- [ ] 生成精确删除计划、dry-run、独立复核后再读回同像，普通树逐个non-force移除，不force、不删tag/Release/行情/
  数据库/私有配置。反查旧绝对路径不再有active引用；从最终唯一树再跑正常状态、`_no_unresolved_recovery`及
  下一次部署只读preflight（包括本次最终cohort记录），证明无隐性旧根依赖。

#### 验收与交付

1. **服务可用**：API/Web和主要真实数据页面、五消费者与Feed身份/活性、原四定时服务注册分别通过；新自然Bar休市待验。
2. **版本统一**：十服务绑定及实际执行来源统一最终exact tag/commit/root/generation；无候选残留writer或旧代码进程。
3. **树唯一**：release-*仅剩最终一棵，恢复历史可读且不依赖旧checkout；临时测试容器已清理。
4. **数据可信**：旧原件、ACK、配置/Scope、账户语义不丢不改；数据阻断/停采缺口分别给出实际处理结果，不能用服务200掩盖。
5. **证据边界**：收盘后的技术可用性验收与18:05自然盘后、夜盘首根自然completed及Alert/Reference业务验收分开；
   没发生的保持待验，不人为重放/发送制造证据。auto_order=false，不启用新Scope、Broker或通知受众。

执行方式：主代理串行控制生产恢复/维护/切换/删除，代码及证据做必要独立Review；不启动重复恢复任务。
15:00到点只触发本线程一次续办，不新增周期监控。实际耗时按每阶段结果汇报，不承诺固定恢复完成时刻。


计划独立Review：无Confirmed Issue；已纳入最终CAS新增v14前像及全部旧根reader脱离的风险检查。
调度边界：创建本线程15:00一次自动执行的heartbeat被宿主自动审批拒绝，原因为本轮先规划与未来后台生产操作的授权区分；
没有创建成功的恢复自动任务，不能宣称已预约执行。该拒绝不影响本文方案和只读准备，不以其他路径绕过。


### 10/27 15:02 owner指定第一步完成：新鲜核对及计划冻结，未apply

本轮授权范围为上条五阶段表格第一步，未进入服务恢复、最终promotion或清树。task/develop同556fc7c0e、
初始工作区干净，main为v20 exact3230936803；未混入SimNow任务。使用正式干净v20原生plan，安全加载既有配置，
重证binding/installed/owner/锁、Session、CBA/D完整前驱、关闭确认及source/DB/routes/ACK前缀。
旧E64b6c383…过期且其私有attempt目录不存在；保留旧E原字节。15:02:37全新计划
09f310e603791fbd0a368916d0a0553450e165a271f79dfc363f45695f37d12e冻结成功，15:17:37到期，
TTL15分钟、预算600秒；public bytes SHA5509a8af9dc7d64fb8c3876ac0ad90d1a4311cbaf1a2a4dc644b2e67963a4dc7。
新文件forward-after-feed-close-20261027T070236Z.json，新attempt不存在。全体先存public/private JSON、
binding、global及关闭确认字节SHA逐份前后比对，无变化。程序没有apply/启动/停止/ACK/配置及数据写入入口调用。
五消费者仍v14/gen31 parked，Feed及四日历absent。状态正文补齐v20已发布、14:11关闭确认成功及当前未恢复。
现场报告output/recovery-preflight-20261027/preflight-20261027T070249Z.json；新原生plan exit0，
不是生产恢复receipt，不冒充服务已可用。下一步是计划有效期内的新鲜复核后执行服务恢复；若过期须另冻新计划。

15:03:26独立只读Review用exact v20原生reader复核通过：新plan/public/controller/source及全部v14/gen31目标一致，
CBA/D descriptor与未决Gate有效、D state及confirmation/binding/global SHA不变，新旧计划均无attempt，
Feed label absent、PID40577已退出、OS锁free。技术允许进入第二步，但本轮停在第一步，不调用apply。


### 10/27 第二步单次apply失败：F intake超时，未恢复服务

Owner明确交办第二步。15:08左右exact v20对15:02新计划09f310e6…执行一次原生apply；有效期与公共字节SHA、
无attempt、controller精确来源均在入口校验。原生前置复验通过，consumers/resumed_generation31完成；
之后intake在原240秒预算COHORT_FORWARD_READY_TIMEOUT，phase outcome_unknown、type CohortError；
无Feed/verified/calendars effect及成功receipt。原生halt完成，未重试。F state SHA
9d45e27a42f43ffa791536096fccf0eff8e8966d3855e9b16661a5fb7c73fad0。

15:15:05独立停驻证据：五消费者真实PID均parked、六OS owner锁free，Feed及四日历absent，
A/B/C/D、binding/global字节未变；source/completed两日尾部及各ACK相等。主仓库稳定私有证据
recovery-f-stopped-independent-20261027T071505Z.json SHAba637dbced6d6eb8cfb1ca53e35ae759ffec7c1c36e09252d95412dc6d63f218。
15:15:40独立DB读回8956/唯一8956；COMPLETED2489→2508、PENDING116→97、WAITING4/BLOCKED44/UNKNOWN0；
最后计算15:09:52.641999。runtime-readback-f-stopped1516.json SHAde3447a8e3cfceaff320a045257d80d18edf686a7aced94641ac4438ed5be42b。

隔离生命周期控制流比较（不连接生产，身份/双fresh/前缀等检查用测试替身固定成功）仅stage不同：receiving_cycle两snapshot通过，
cycle零snapshot至虚拟240.2秒超时。真实v14 worker在poll接收/计算后报告receiving_cycle，serve再覆盖scan/cycle；
接收活性依赖计算耗时和瞬间stage，存在结构风险。该隔离结果不能断言F实际失败子条件，因为intake没有持久该诊断。
只读事后完整接收快照1.499秒、fixed_identity1.467秒；Session探针未继承Stream开关失败，不把包装问题当生产故障。

halt已生成新drain IDs，D controls旧证明无法再次当作fresh前置；F unknown也不能直接放入C/B/A恢复模式。
本轮到此停止生产mutation，未发布新controller或执行新plan。需先解决生命周期判定、intake可诊断性及经验证的停驻收尾，
不能继续堆叠递归恢复模式或绕过unknown。第二步BLOCKED，服务仍停驻；版本升级和清树未开始。


### 第二步修订实施：统一接收证明及非递归停驻收尾（控制器候选v21）

Owner批准完整修订方案后实现shared completed-report/双fresh窗口，正常cohort与forward共用；v14 cycle和
receiving_cycle按各自窗口形成双轮，跨stage仍核对全局原件/routes/ACK连续性。pending/blocked不再阻止接收，
UNKNOWN及前缀错误仍拒绝；intake/verified保留安全子步骤、固定原因/服务/时间，不逐轮日志。
新增reconcile-stopped只接纳consumers完成、intake READY_TIMEOUT且Feed未启动的同generation失败；
锁内证明当前parked/Feed与日历absent/观察PID退出/双前缀完整，固定原安装与protected前像但用当前drain。
原unknown字节保留，确认文件以扁平证据集合关联历史角色，新plan直接引用确认；成功receipt闭合已关联事故。
同一状态确认幂等，额外unknown/effect、schema/身份/前像漂移、模式混用、原子写失败均拒绝。

一次真实一次性PG16/Redis7定向组合295 passed/0 skipped/9.52s，容器已停止自动移除；后续review小修仅补测
readiness22 passed、stopped20 passed，不机械重复全套。Ruff/uv offline lock/diff/secret0通过。
独立高风险Review无未关闭Confirmed Issue。只读真实历史布局复核5 attempts/18 files通过；原cohort只保存public
plan和private state，已修正不能假设其额外保存private plan的测试布局。此记录不代表已发布或已恢复。
