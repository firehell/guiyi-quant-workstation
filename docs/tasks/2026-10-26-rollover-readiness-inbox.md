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
