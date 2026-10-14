# 10月13日盘中故障修复与补丁发布

Owner交办：按影响顺序修复收盘审计问题，全部修复后发布一个版本；授权覆盖必要精确数据恢复、生产读回、发布和运行切换。范围保持60品种、既有规则/收件人，苏冰外部推送关闭、auto_order=false。

基线develop aa3896e0840694fff17ca3abd211d67a060c83a5；现役v1.15.5 dc32c020d328ab81d4d65a959603f4ab66965f52/gen18。

- [ ] Reference：真实冲突保留，明确隔离故障品种/周期；每观察持久终止事实才能ack，未知提交继续阻塞；恢复采用独立明确中断边界，禁止跨旧参考链配对。
- [ ] SA：定位10:12缺口与恢复失败根因，修复稳定诊断及安全恢复；原Source/Completed及首次时间不改写，恢复数据不冒充自然观察，预算与失败attempt不删除。
- [ ] Alert：固定30秒有效期，减少重复权威读取/计算，验证同轮多品种延迟；不补发过期信号、不改变公式。日周coverage基于当前身份/输入证明，质量事实不造正常价。
- [ ] Web：首页价格与策略摘要独立可用，读取有界且可取消；展示真实滞后/冲突/不可用，无第二行情resolver。
- [ ] 运行诊断：总health纳入Reference，稳定公开错误码代替unclassified；日历not_due/休市正常区别实际缺口。
- [ ] 定向回归、相关集成、Web类型/build、lint/type、secret、diff及独立高风险Review。
- [ ] 精确补丁main/tag/Release与正式运行切换，保护原journal/Scope/receipt/发送事实；冷启动独立readback。

修复、发布、身份切换与新版本自然业务验收分别记录。未知提交停止相应mutation并只读核对；不放宽质量、时序、维护锁或幂等校验。必要恢复前冻结精确对象、前像、预算、hash与恢复办法，串行生产操作。

## 当前取证与验证（尚未发布）

SA一次性精确provider诊断已真实完成（1次、SA2701、2026-10-13、1m），捕获345行；
10:12 total_turnover=-916520、volume=588。源码严格拒绝RQDATA_TURNOVER_INVALID，原Source/Completed此分钟不存在。
不改成0、不伪造金额、不删除旧预算；当时提出是否采用字段级不可用合同的决策，后续现场事实已消除该取舍。
证据在主工作区output/runtime-intraday-repair-20261013/sa-provider-{attempt,response,outcome}-001.json。

自然盘后任务2026-10-13 18:05:05→18:07:22第一次执行passed，覆盖原60品种并实际cleanup bars=0/subscription=false。
正式MDS只读读回SA2701 10:12分钟，成交额0、volume588；独立新attempt002仅一次provider查询确认原始
total_turnover已由源自行更新为0（无本地金额填值），与正式Canonical一致。保留严格质量校验，未修改任何金额语义。
盘中原始Live缺口/失败budget仍是历史事实，不补发旧信号。SA数据口径选择已不再需要owner答复。

60品种10:00小时输入纯评估同hash/同策略结果：旧cold16.810785s/warm16.462727s；
候选cold12.089472s/warm11.662910s。此测量未包含完整到达批次、同向分析或Event/transport，不能称实时30秒验收通过；
正在补完整原始顺序批次测量，禁止补发或改变有效期。

完整300条整点producer顺序输入SHA d5b4a32f52aa7c13a88e7e17b373dd3af693acd1060b9a4cc85860745424b41b：
旧cold85.582104s/warm86.337394s；共享window候选cold74.171825s/warm73.372481s；
追加facts缓存cold73.506777s/warm74.329910s。300条两轮outputs与旧实现逐项一致，
但耗时仍超过30秒有效期，延迟修复尚未验收；正在profile真实热点。

Reference发布前输入诊断（2026-10-13 16:55，生产只读）：固定60条D1/W1源读取，
原24条MAPPED_CONTRACT_DATASET_MISSING现全部no_input，正确等待当天Canonical发布。
Reference定向145 passed/5 skipped；隔离、恢复新revision和发布窗口正进行独立Review，未执行生产恢复。
恢复historical源现场扫描发现14条历史OPEN和SF/SM6条已invalid旧revision；不得绕过_source检查。

Root定向命令均使用主工作区services/quant-api/.venv/bin/python及task的PYTHONPATH：
- live_recovery + queue + concurrency：78 passed / 32隔离Redis未配置skip。
- deployment_identity + runtime_scheduled：33 passed；补齐log-rotate合法idle身份校验。
- live_recovery_guard：10 passed；测试显式使用隔离目录，生产共享锁规则不变。
- root修改Ruff、git diff --check、secret_scan均通过。

## 收尾验证补充（20:00 前，生产恢复仍未执行）

候选APP_VERSION=1.15.6；独立Review已通过 Reference/Web/CLOSED_CLEANED及部署准备，
最新增量suffix和真实恢复caller待独审。正式版本仍v1.15.5/gen18，不提前声明已发布或Runtime ready。

- 真实隔离Redis恢复/队列/并发/guard：120 passed；CLOSED_CLEANED独立47 passed。
- 真实隔离PostgreSQL冲突提交/新段恢复：7 passed，独立schema，不写生产。
- 首页定向35 passed，版本一致性1 passed；Web类型/build/topology通过，uv lock --check --offline通过。
- Canonical历史计算测量：240条同输入，baseline 88.196786/84.524775秒；
  候选充分预热后的原读取43.594853/43.719377秒，新suffix29.325923/28.539880秒。
  两轮240条输出逐项相等（只排除耗时），未生成Event/通知、无provider/生产写入。
  这不是自然Live突发批次或收件人30秒验收；原300条Live证据仍保留，盘后Live已清理。
- 两个不可变输入缓存各200000 Bars/128条，合计最坏400000个不同Bars；
  alignment缓存只保留384组输入digest和解释facts，不保留Bars，不缓存错误。

生产恢复限定10品种60m×四策略，历史Source重建30base+10fusion；
旧69次冲突及参考交易完整保留，新forward段空仓、未来21:00开始、不继承旧OPEN。
实际执行必须持真实PG维护锁和既有OS/owner锁、精确park token、
当前CLOSED/自然清理证明、逐副作用持久intent及独立readback；20:55 expiry，未知不重试。

Root最后联合回归实际完成：1613 passed / 3 skipped，480.28秒；命令为主venv
`python -m pytest -q -p no:cacheprovider --tb=short`，task PYTHONPATH，
显式隔离Redis端口16393与隔离PG15463/guiyi_reference_isolated_test，
覆盖Reference全目录、Catalog/Storage/CLOSED_CLEANED/Feed/Live recovery/队列/并发、
Alert Runtime/Evaluator/Readiness/MarketRead/health/identity/guard/alignment、Newow reader/home cards。
3项既有可选隔离项跳过，不把skip计为通过；新增7项真实PG冲突测试已另实际通过。
Web35项及home_cards16项复验、版本一致性1项通过；
Mypy11个Alert/数据Runtime source + 9个API/Reference/identity source通过
（--follow-imports=silent --ignore-missing-imports，不称全仓类型检查）。
Ruff实际生产改动通过、秘密扫描0 findings、OpenSpec 11/11、diff check通过。

独立高风险Review最终：suffix406项复验通过，MDS SHA3fa3a3bea81b；无Confirmed Issue，允许此范围集成。API类型标注/cast复核为纯类型变化。Reference/Web/CLOSED_CLEANED此前已独审通过。实际恢复caller独审仍单独待验，不以工程Review代替真实恢复。

补丁release branch基于精确v1.15.5，工程commit64fdaa024只移植本轮60文件；
全部改动生产代码前像与v1.15.5相同，STATUS按正式基线保留历史并加入本轮证据，不带develop无关研究功能。
精确补丁树543项定向复验通过（含实际隔离Redis/PG），Web35项、type/build/topology、
uv lock离线校验通过；真实恢复caller及发布/切换仍分别待验。

## 22:53现场：候选已集成，生产恢复与发布未完成

工程提交64fdaa02464288575acc0e6a9e6a74c052589c90已集成并推送develop。
从正式v1.15.5提取的独立补丁候选bd3c2b7cc4f26f054ce9d220f12ca636de6bb172已推送，
草稿PR https://github.com/firehell/guiyi-quant-workstation/pull/447 。该候选隔离Redis/PG回归543 passed，
Web35项、类型/build/topology、版本/lock/OpenSpec/secret检查通过；尚未main merge/tag/Release。
恢复helper定向112 passed（4项真实隔离PG），不代替生产执行。

原计划20:55 expiry已过；两次只读freeze预检失败，未创建one-recovery-attempt-001，
未执行停驻、数据库修复、游标修改或通知。旧计划不延长，不复用其attempt。

22:53生产只读读回：45品种TRADING、15 CLOSED；目标10品种仍CLOSED，下一时段09:00。
Day14元数据20:30已passed，但订阅不存在、Source/Completed均0。
Day13 Source13499条，Live游标到尾；Completed17875条，Alert到尾；
Reference游标1791856805416-3落后尾1791874804726-4，4组REFERENCE_CANONICAL_MISMATCH。
Feed旧PID62811仍active但ready=false，心跳TTL=-2，不足以证明pending/subscription为零；
Live明确OBSERVATION_SUBSCRIPTION_MISSING。不能把旧日静态尾部或Reference单独停驻当作producer停写证明。

下一恢复采用独立双停驻证明准备：Feed正规drain/同PID parked、真实owner锁及新鲜实际close heartbeat，
再冻结完整旧日前缀、等待Live/Alert自然到尾，之后Reference正规停驻并持维护锁。
provider=None无fresh heartbeat时仍拒绝生产数据写入；不伪造心跳、不手工ACK、不补发旧事件。
安装器ALL60CLOSED条件不改变；权威Calendar下个全闭市窗口02:35，下一开盘09:00。
当前仍v1.15.5/gen18，不声明RUNTIME_READY；新恢复准备和运行切换仍待实际执行及读回。


2026-10-14 候选续接：002业务提交已独立核对，正常Reference恢复后剩余CF旧冲突阻塞。
新增original_observation_conflict_v1保留原始观察及最终Canonical差异，四路原子终止；
匹配的后续观察依靠明确关联终止，不伪称其数值冲突。新段使用真实Canonical策略预热，
先PENDING_WARMUP允许旧日消费，完成Day14 Live尾部后独立新revision final；无交易/Marker/通知。
独立Review75 passed含真实PG4，无Confirmed；root五文件回归51 passed，
Ruff、五source Mypy、OpenSpec11/11、secret scan0、diff通过。
上述为当时检查点；后续实际结果见下方10/14恢复记录。

## 10/14 09:30恢复状态：PARTIAL，尚未发布

正式运行仍为v1.15.5/gen18（dc32c020d328ab81d4d65a959603f4ab66965f52）。
v1.15.6保持草稿PR #447，未main merge/tag/Release，未执行gen19 promotion。
以下为各独立attempt的实际结果，不把前序停止记录改写为成功，不复用已到期计划。

- 003b：39组原始观察终止与15条Historical COW基线全部提交，共54项真实效果；
  预热前受控停止，原intent、receipt和事实保留。
- 003c：39组156路PENDING_WARMUP新段全部提交，加恢复Reference共40项效果。
  旧日正常ACK超过120秒时限后安全重新停驻，没有重做已提交业务步骤。
- 003d：两项控制续接完成。Reference正常ACK Day13至真实尾部，Feed按原合同初始化
  Day14的60个订阅，Reference随后以新token重新停驻；无手工ACK。
- 004：新增三个协作停驻完成，与已有Reference构成四停驻；journal校验将官方identity
  JSON值误当Redis Stream ID而停止，未调用provider。
- 004b：独立续接采用同四停驻和完整journal摘要严格相等。在08:50时限到达后停止，
  a、ag、al、ao、AU五个Live前缀真实提交；AU原子提交由独立读回证明，旧本地committed receipt缺失
  如实保留，不补造原receipt。其余40个品种预算仍absent，不能称45个全部恢复。
- 006与005c未apply；28路夜盘中断及156路最终预热未完成，Reference保持停驻。
- 008c到期前没有取消任何停驻。009b已提交MarketFeed、Live、Alert三个精确取消请求，
  约09:22三个服务恢复active；后置校验因旧Completed identity两字段合同报错。
  三个已提交控制操作不重试；010仅做独立只读核验，不取消停驻、不查询provider、不写业务数据。

010只读后验在SQL AlertEvent.bar_end的原生aware datetime被ISO字符串解析器拒绝后停止，
未修改控制或业务数据。独立011保留原010文件，在RESTORE9_NIGHT_PREFIX_CHANGED停止：
五个品种的RecoveryState revision从1推进至2，recoveredThrough变为09:23:37。
独立逐字段核对确认a/ag/al/ao五周期原夜盘Bar JSON逐条字节一致，原价量未改；
五个品种的夜盘预算仍保留原count=1及lastAt。旧Runtime的正常recovery会推进该状态，
不能把可变recovery状态当作永久不变的Bar证据。AU没有旧本地receipt的事实仍保留。
后续013独立核对当前45品种覆盖、预算与AU原封存摘要；不把08:50的40个absent冒充当前状态。
Root约09:25独立读回Day14 Source 120条、Completed 180条自然追加；Feed/Live心跳均60订阅，
无输入或元数据错误，owner ready=false；Alert ready=true。Reference仍park。
三个取消已提交及三个服务active的事实已确认，011停止不是控制未恢复。

013首轮实际只读命令的session 94225、chunk 016863返回exit 0，状态为THREE_NORMAL_SERVICES_RESTORED_REFERENCE_PARKED，
完整JSON未保存；以上为实际工具输出证据。没有控制变更或业务数据写入。三个服务恢复与自然采集读回通过，Feed/Live均60订阅且心跳新鲜，
Reference仍park。当前45品种检查仍有40个夜盘前缀缺失，night_prefix_verified=false、
reference_business_ready=false；28路中断未处理、156路仍为PENDING_WARMUP，006/005c未apply。
a/ag/al/ao原夜盘五周期Bar的字节与数值均精确相等；AU以原state revision 1及原recoveredThrough
重构七key摘要，与原封存SHA匹配，证明旧raw未改。五个品种RecoveryState 1→2为既有自然运行
元数据推进，不能据此认定夜盘完整或Reference业务READY。
随后第二次新鲜只读采样（session 3913）exit 2、RESTORE10_HEARTBEAT_UNIVERSE_DRIFT。
其O_EXCL文件output/runtime-intraday-repair-20261013/runtime-v1156-day14/normal-control-readback-013.json
是后次失败样本，不是成功receipt，SHA256为3fc518f9fb8d9c6378824683b7b49d86031e31c05bc3d320c6609f62b0f86c6f。
10:30:25轻量心跳读回再次为Feed/Live订阅60/60、输入及元数据错误为空，两者available=false，
Alert available=true。第二次失败原因尚未独立证明，不推断为Session转换。
三服务active与订阅存在不证明缺失夜盘已补齐，也不证明全720路READY或自然业务RUNTIME_READY。
余下修复验收范围为40个夜盘Live前缀、28路中断、156路最终预热、发布与Runtime promotion；
需依据当前权威Session、实际数据和已有预算制定新的有界计划，不延长或重用过期attempt。
Scope、公式、质量、固定30秒时效、既有收件人、苏冰推送关闭及auto_order=false保持不变。
