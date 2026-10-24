# 现有数据、计算及 Runtime 健康修复

Owner 10/24调整优先级：苏冰全量历史资产补建后置，先修现有数据缺失、实时采集、策略计算、推送和其他Runtime；不新增功能/需求。Owner随后明确接受偶发推送失败，本轮按近期存在成功记录、并非全部发送失败验收，不再追查旧失败或补发。发送线程、配置、Event及Scope仍按原合同检查。

## 日志：用户清理后重新恢复，连续读回通过

六常驻服务仍为exact v1.15.18/gen23，但stdout/stderr均指向NLINK=0的已删除inode。对应5个路径已不存在（Feed/Live共用一个），旧日志内容无法从现有路径恢复，删除发起者UNKNOWN，不能归因于既有copy-truncate轮转脚本。

按任务内精确计划、独立Review及原生正常park边界，逐服务使用原plist完成同版本重启。最终Feed28471、Live31503、Alert31548、Reference31593、API31612、Web31634；所有FD1/FD2均等于当前日志文件inode。十binding、原件journals、索引、消费游标、Rule/Event/通知旧记录摘要保持，0下载/0通知/0replay；旧日志标记UNLINKED_CONTENT_NOT_RECOVERED。

`log-recovery-attempt001`已成功恢复Feed，随后Live PRE_DRAIN的新鲜性门禁停止，Live没有intent；`attempt002`同样仅PRE_DRAIN/Live、tokens空/无intent。未保存当时HB，不宣称已证明具体失败字段。独立只读样本及锁内4秒采样均证明Feed正常可新鲜；`attempt003`仅将首mutation前门禁改为20秒有界只读等待，完整5秒条件不变，保存每次样本；剩5服务成功，Feed在加锁内与最终再次完整核对且未重复重启。旧失败目录不重试、不重写。

证据：`output/health-recovery-20261024/log-recovery-attempt003/completed.json`及Feed原成功verified记录；独立恢复后快照`output/runtime-step1-20261024/health-repair-after-logs-001.json`。消费者积压0、pending Capture0、文件锁释放；快照中的一个PG维护lease为本次已知只读全历史审计，不能当作遗留锁或强制解锁。

## 推送与预热检查

最近自然夜盘（10/23 21:00 CST起）已有4批PROVIDER_ACCEPTED、2批FAILED_OR_UNKNOWN（7个Event：4 accepted、3 failed/unknown），配置结构正常。符合owner本轮接受口径，旧失败原样保留；没有外部查询、测试发送或补发。证据：`output/health-recovery-20261024/push-readback-001.json`。

7个canonical评估暖机状态逐项重算有效但未ready：BZ/EC/PD/PL/PR周线26/22/28/20/26根，RS日线22根/周线6根。严格当前物理合约与质量中断后的有效segment不扩展，不跨合约/降低公式门槛；保留真实warming_up，不手工标绿。证据：`alert-diagnose-001.json`。

## 已完成：数据依赖修复与独立验收

对60品种10/23权威rank1的四分钟周期完整生命周期prefix独立核对，共240个唯一身份：228完整，12缺口精确为NI/PG/PS/SI2612 × 5m/15m/30m；H1均完整。12个原生计划每项derived11/direct0/provider0，合计132聚合分区，可使用既有合格Canonical1m，无需RQData请求。这是实时计算的物理预热依赖，不是苏冰全量历史参考资产补建。

证据与计划：`output/health-recovery-20261024/physical-prefix-001/completed.json`。精确执行器`intraday-derived-apply.py`通过scope、预算、未来日期、重复和缺失身份测试；独立Review无Confirmed Issue。本次60品种全历史只读审计于22:00:19–23:27:33 CST完成，60/60 passed、through10/23、findings0。自然释放PG维护lease后，12路均原生passed，各11发布，合计132，provider/failed/blocked均0；所有postplan0，旧文件SHA保持，独立review再次重算旧文件SHA验证通过。2小时是计划准入/前后fence，不是单次原生调用强制中断超时。

全历史manual审计报告只写`output/health-recovery-20261024/full-audit-001/status.json`，不覆盖正式weekly skipped_busy状态。已到passed终态，不以它覆盖正式weekly skipped_busy记录。

## 换主力补查：CU2612

对照10/26冻结订阅与10/23、10/26 MainContractMap，59品种相同，唯CU由CU2611切CU2612，且冻结订阅与10/26 rank1全60精确一致。上述240路初检的CU4为旧CU2611，不能冒充实际下一Session来源。新CU2612四分钟周期均DATASET_OR_PARTITION_MISSING。

原生full contract warmup精确规划CU2612上市日2025-12-16至已完成10/23，七既有正式周期，direct33（1m/1d/1w各11）、derived44（四分钟周期各11），33次RQData请求、77次发布、expected123907bars；不含未完成10/26数据，不扩大Scope或公式。独立Review和任务56测试通过；全历史审计及前一组132分区修复完成后已串行原生执行成功：77发布/provider33/failed0/blocked0，postplan0。CU此前没有旧分区，old_files_verified=0，不宣称恢复旧CU文件。

证据：`subscription-prefix-scope-001.json`、`next-cu-prefix-001/completed.json`、`cu-full-plan-001.json`（均在本任务output目录）。任务只读daily-recovery附加检查在RuntimeDataBinding身份/时效准入拒绝（RUNTIME_RECOVERY_IDENTITY_DRIFT），未产生维护计划、intent或生产效果；不更改门禁或用它冒充18:05自然增量验收。七周期warmup使用独立已完成历史合同和机器校验，不写自然盘后status。

## 最终独立读回与未完成项

fresh独立维护lease和MDS按10/26实际rank1重核，240个唯一身份全部COMPLETE_PHYSICAL_PREFIX、四周期各60，CU四路均CU2612，失败0。CU另独立检查1m93645根、D1 205根、W1 44根，截止均10/23 15:00 CST、quality interruption0；共享内核D1/W1有效且ready。没有生成苏冰历史参考资产。

全部13次原生维护进程exit0，合计209发布、33次RQData请求，失败/blocked0，所有postplan0；旧4合约文件完整保持。独立Reviewer核对实际publication七周期/月份身份和旧文件SHA通过。证据：`physical-prefix-002/completed.json`、`cu-independent-base-001.json`及13个attempt结果；汇总`verified-summary-002.json`（001保留当时日志未闭环状态）。

最终六PID仍active、十binding仍v18/gen23，保留journal消费者均追尾、pending Capture0。最终快照15:40 UTC的一个PG维护lease随后只读核对已自然释放，`final-pg-holder-001.json` holders空；不强制解锁。Rule/Event/policy/delivery的计数及全行摘要与恢复前保持，0新通知。

首次日志22:27恢复并逐FD验证成功后，再次变为NLINK0/路径缺失；001报告如实保留log_recovery_closed=false。LemonMonitor22:34记录项目目录，但没有足够进程级证据直接确认删除发起者；项目自身轮转为03:15 copy-truncate，未将其猜测为删除者。系统fs_usage要求root，本任务未提权或修改全局配置。

Owner随后明确回复“运行过清理工具”。按一次已结束的清理处理，生成新v4精确计划f6b59cc6d2ee54c64a0526b3d4713344f38ba71686da059c6af7b46a0f17899c及独占attempt004，重新正常排空并恢复六服务，无数据重跑/通知。56测试及增量独立Review通过。10/25凌晨00:08–00:09 CST连续60秒、多次逐PID/FD/路径inode验证稳定；00:12再次核对Rule/Event/policy/delivery全摘要保持、六owner active及日志FD匹配。当前Feed46503、Live46533、Alert46575、Reference46611、API46633、Web46651，仍v18/gen23。`final-protected-002.json` log_recovery_closed=true；原001和旧失败记录不改写。具体清理进程仍未归因，未修改用户全局清理器设置；此验收只证明该观察窗口稳定，今后人工清理须保留正在使用的项目日志目录。

当前结论PARTIAL_NATURAL_ACCEPTANCE_PENDING：闭市可执行的数据依赖和日志修复已验；611对应独立历史及夜盘三频派生已补齐（见下）；下一Session/盘后自然验收仍待。7路真实有效历史不足继续warming_up，不改公式、Scope或强制READY。全局degraded和672 READY/48观察滞后保留，不宣布全系统自然闭环正常。下一最小步骤为10/26自然采集/H1及18:05盘后增量验收；未新增定时或后台服务，苏冰全量历史资产仍按owner决定后置。

## 实际测试

- 任务内日志恢复/typed Feed边界与数据scope反例：56 passed（reviewer独立复跑通过）。
- exact v18原生HistoricalDataManager、Runtime handover/deployment、PushPlus及通知定向：278 passed。
- 未新增产品代码、策略公式、Scope/受众、定时任务或交易操作。

## 仍须自然验收

611条10/26交易日原件缺失没有恢复；并行已结束夜盘修复已完成对应独立历史替代，不再等待完整交易日；旧2565对应历史已齐，但原件缺失标签保留。44路H1中断修复已完成，新自然输入仍待10/26；全局672 READY/48观察滞后与degraded保持。保留10/23盘后UPDATE_FAILED及正式weekly skipped_busy，不以本次repair或manual audit覆盖自然运行证据。10/26真实采集、H1与18:05盘后增量分别验收；不新增后台监控或定时任务。


## 10/25 00:35追加：夜盘三个既有分钟周期补齐

并行任务已通过原生已结束夜盘入口完成11合约1m/60m共22分区发布，实际2910条1m和50条H1；正式v18独立读回VERIFIED、原Live缺失记录保持。证据`output/closed-night-repair-20261025/independent-readback-001.json`、`postrepair-replan-and-conflicts-002.json`。此处纠正先前“611对应独立历史须等10/26完整交易日”的旧结论；不是本任务重复下载或重写原件。

本任务随后用正式v18逐项检查11合约×5m/15m/30m，33路均实际报MARKET_READ_CUTOFF_BAR_MISSING。对既有原生ContractSessionRepairRequest增加显式derived_frequencies，严格非空/唯一/仅四个既有分钟周期；默认CLI仍只1m/60m，默认plan identity不变。扩展范围及端点进入hash，各候选全量质量和旧值检查在任何publish前完成，原生维护锁/旧文件/未知提交停止合同保持，D1/W1禁止。

精确11合约AG2612、AL2612、AO2701、AU2612、CU2612、NI2612、PB2612、SC2612、SN2611、SS2612、ZN2612，trading_day10/26，cutoff为权威已结束夜盘；冻结计划文件SHA e91ba1d59e0d6993e646bc33cadac1febd93afb4274d80a6ce29fc1234e3f33b，M1/60m missing0、provider budget0，5m582/15m194/30m97个端点。独立Review通过后单次原生执行，33个月分区全部published、provider0/failed0/blocked0，逐项postplan0、旧五周期文件SHA保持，无未知结果或重试。

正式v1.15.18新进程独立核对33路全部FULL_PHYSICAL_PREFIX_READABLE，包括夜盘最终端点和完整当前物理合约prefix；`closed-night-intraday-prefix-001.json`保留修前33失败，002保存修后33通过。`night-derived-attempt001/completed.json`及每合约preimage/intent/result/verified保存精确效果。本任务总计242发布/33次来源请求；另一个任务22发布/11请求分别归档，不混算成果。

增量session-repair38项通过，连同原HistoricalDataManager回归255 passed，Ruff及diff通过，独立Review核对计划/代码及实际读回。00:35再次独立核对六服务同PID、active、日志FD仍指向现文件，Rule2/Event3921/policy1/delivery10954全行摘要保持，0新发送；证据final-protected-003.json。

剩余边界：旧611和2565实时原件仍不可恢复，其对应历史补齐不改变缺失事实；七路有效历史不足保留warming_up。并行只读H1准入快照为历史60/60通过、混合历史/旧Live51/60通过，九路旧窗口阻断仍保留（AP/CJ/JD/LH/SF/SM/UR为MARKET_READ_LIVE_UNAVAILABLE，PK/RS为旧原件与Canonical修订冲突），不靠改旧Live、重放或强制READY消除。该旧窗口结果不证明下一新Session失败或成功；新自然输入、首H1与18:05增量须各自验收。本次不新增产品面、受众、调度或交易操作；最新发布v1.16.0和仍运行v1.15.18/gen23分别陈述，未擅自切换。
