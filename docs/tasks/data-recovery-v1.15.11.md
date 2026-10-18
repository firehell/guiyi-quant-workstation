# 全历史、计算与参考交易恢复及统一发布

目标：修复本轮确认的数据/运行阻断，包含 v1.15.10 已发布改动，形成一个新的正式运行发布树。用户2026-10-18交办覆盖必要数据修复、发布、切换及旧发布树清理；不改变策略公式、Scope、受众、交易阶段或 auto_order=false，不补发历史通知，不删除 tag/Release 历史。

基线：develop 7731bcd81；现役 v1.15.7/b84e723a8/gen19/schema0051；已发布 v1.15.10/79c6ed573。原工作区未跟踪研究/恢复证据保留。任务分支 codex/data-recovery-v11511 独立工作树。

顺序与验收：
1. 原生只读定位 weekly audit 19/60失败，修复根因及不透明诊断；完整60品种审计输出精确缺口，不用 finding_count=0冒充完整。
2. 按新鲜精确计划串行修复物理合约历史；重算hash、质量、维护锁、原值/不可变文件保护、已提交与未知attempt分类和独立MDS读回。旧过期/disabled准备不能直接执行。
3. 恢复 historical source、fusion依赖和212 forward冲突，保留旧观察/Event/发送事实；核对全720就绪和策略逐路覆盖，缺失自然信号不得伪造。
4. 定向测试、高风险独立Review、secret/diff/build/必要集成和真实页面/API回读；只集成已验证修复。
5. 新补丁版包含v1.15.10；验证后main/tag/Release、schema0052迁移与正式服务切换分别留证；自然验收未发生时如实保留。
6. exact binding/plist/loaded/PID引用全清零后，按原生retention cleanup-plan清理旧发布工作树，只保留新现役树；不删除行情、DB、研究证据或Git发布历史。

实际执行结果随进展补充；本文件不是完成声明。

## 10/18 数据修复与定位进度

原生contract_warmup真实执行49个精确scope全部COMPLETE，919个目标分区、443次逻辑provider请求；每个scope独立postplan零目标，旧文件不可变hash保持。证据位于主工作区output/data-recovery-v11511-20261018，各apply目录保留intent/provider/request/result/complete；无stopped mutation attempt。随后发起原生60品种全历史审计full-history-audit-001，运行中不计完整通过。按completed-observation确定的60个rank1物理合约，七周期历史边界截至10/16的final dry-run独立扫描全部零目标；10/19夜盘仍为独立Live observation，不自动晋升Canonical。

weekly audit原来吞异常且零finding易误读。补齐findings_complete、partial_finding_count、failed_symbol、error_stage及安全分类error_type；旧schema读取兼容。定向56+126测试通过，Ruff/secret/diff通过，OpenSpec strict11通过；独立Review无Confirmed Issue。旧I单品种审计44.29秒通过，原19/60失败技术原因尚未复现，不虚报修复历史失败。

额外定位historical refresh 240 blocked：177 H1 SOURCE_CHANGED为旧冻结plan与当前输入漂移，3 LH scope drift，60 D1 fusion为saved基础manifest与新鲜输入不符。独立只读A复现十项trend/osc公共lineage相同，但SavedFusionSources保存的base在四项输入/Session/rank1不符；不移除边界或源校验。恢复须native fresh advance/COW基础资产后再fusion，并保留旧refresh前像。当前active revision中original-conflict typed凭据为0；旧output49产品计数不可当当前已完成。新archive seal只读验证672个H1原始观察/60品种完整hash、length、tail、原始字节，未导入或replay。该存档未导入；后续复核已确认不应执行新Transfer，见下节。

## 当前冲突入口复核

53个受影响H1组均有当前active原生Capture mismatch（450条，均位于三个base，fusion依赖整组）。旧49产品OriginalTransfer key保留在inactive revisions，native防重复不限定revision，不能据active typed0重复插入。生产控制与资产操作尚未开始，已在执行前纠正准备方案。新增独立版本reference_capture_final_warm_recovery_v1，只沿用现有capture mismatch admission和完整四策略组，复用已验证的final materialized warm seed与原子future-flat revision；不新增OriginalTransfer、Capture/Reconciliation、action/trade/Event/通知或ACK。新旧typed源校验共用原有验证，无公式/收益/Scope/受众变化。测试先观察功能缺失RED，再观察单route误入场RED，修正后新旧恢复/warm/fusion/历史增量53项通过；独立Review无Confirmed Issue；新入口源漂移拒绝与四表前像保持测试9项通过，独立真实PostgreSQL原子成功/源漂移回滚2项通过，临时容器清理。发布候选原生恢复/融合/增量87项、审计/健康182项及冷切换caller88项通过；Ruff、secret、diff及OpenSpec strict11通过。0052真实隔离迁移兼容性证明旧ORM去重读写正常、all-null降级保留行、非空v2拒绝降级。现场完整审计仍运行中，生产参考维护未开始。

切换前补充只读取证：Alert coverage为35 ok、266 evaluation_lagging、75 pending、40 waiting_canonical、5 evaluation_failed；live覆盖正常。BZ2611 D1/W1和EG2611 D1/W1旧版读取物理历史分别报PRICE_UNAVAILABLE/DATASET_OR_PARTITION_MISSING，新版本同源纯kernel分别117/25/160/34根，除BZ W1仍warming外均READY。EC2611 W1仅21根、BZ W1仅25根，不跨物理合约拼接预热，也不将其当缺失Canonical。证据alert-quality-readonly-diagnostic-001.json；诊断未写Event/通知/Redis，不代替切换后coverage读回。新树weekly健康严格绑定root/commit，不能复制或改写旧结果身份；切换后应从新exact tag执行原生manual全60审计，保留旧scheduled失败记录。

## 新增现场阻断及已完成修复

第一轮完整原生审计full-history-audit-001已通过60/60、through=2026-10-16、findings_complete=true且零finding；独立核验60份七周期零targets。reference-native-apply-001随后在preflight因Alert owner stale停止，progress仅started/created，零effect intent，四控制前像逐字未变；preflight-closeout.json记录零影响，不复用该attempt。

现场定位completed 10/15旧journal仍保留但alert/reference旧cursor已按TTL过期，造成两进程启动循环。现场不补cursor、不跳journal、不重放、不提前删除，等待原TTL自然过期后核对全部仍存day/cursor。新增NEW_DAY v2保留已证明旧tail cursor的TTL、APPEND/COMMIT v2原子校验注册日，阻止旧日迟到事务再续旧journal；已排空空tick只在真实新日cursor存在时无写入NOOP。真实Redis先复现RED后修复，观察/闭市/休息/恢复/运行入口198项通过，安全固定错误码8项，Ruff/secret/OpenSpec11通过；独立Review确认并发缺口修正后允许集成。源码9957ad132，已集成并推送develop，发布候选已cherry-pick；正式Runtime仍v7。

对全部60品种D1/W1的120路只读纯kernel核验，发现新增PF2612/PK2612/PL2612原始全零行尚未登记typed质量事实，不能按NO_TRADE过滤。冻结13个D1月分区、120行(PF26/PK5/PL89)，3次真实原生RQData exchange-daily来源查询全部一次成功；原始request/response hash与Canonical七个字段逐一相等。native quality candidate/preflight/independent Review通过后，13个D1分区按现有NONPOSITIVE_CLOSE合同原子发布，旧文件hash不变、独立readback already_applied13。随后复用原生weekly quality repair v2，13个月38周(PF10/PK4/PL24)完成闭包，9空月仅撤Catalog指针、4月replace，旧immutable文件全部保留，零D1改写/额外provider，独立readback candidate13。

新revision的全120路只读核验quality-all-d1-w1-readonly-002已全部valid、110 ready、errors0；10路真实warming为BZ/EC/PD/PF/PG/PL/PR/PX周线及RS日/周线。三修复合约原生七周期postplan全部零targets。因正式数据revision已改变，已启动新的full-history-audit-002（实际task源码9957ad132身份）与operational-seven-plans-004，均只读，不复用旧审计冒充新revision；Reference720维护、v11发布/切换/现场manual audit/旧树清理仍待后续连续完成。新cold admission已要求全部retained journal days精确匹配16/19，避免漏掉15旧分区；caller90项通过。

17:36第二轮原生全历史审计full-history-audit-002完整PASSED：60/60、through10/16、findings_complete=true，finding/partial/provider/writes均0，实际进程exit0。独立核对ordered operational scope与七周期plans004全60零targets一致；audit SHA11c34620a69a6f5ecb191e3708d0819e554d12351dc28e7e5916e62c66bb0ba5。统一发布候选062dc5be7最终独立Review无Confirmed Issue，允许进入release candidate，草稿PR#459已建立。17:38只读现场15旧journal TTL1778秒，alert/reference游标仍MISSING，保持等待原TTL自然过期；未启动reference attempt002。

18:08旧15日journal按原TTL自然到期，全部现存16/19日journal/cursor与四owner新鲜身份通过。reference-native-apply-002仅Feed停领后因旧版不产生post-drain业务心跳而停止，caller资产intent0；原token经独立复核的精确closeout同PID恢复，cancel区间输入不变，其他三服务后台refresh cursor自然变化保留。新caller改用≤15秒真实闭市空输入前置样本+精确token/PID/native free FD及全部journal/current Live不变；003又在正常请求前更新的样本判定停止，仍caller资产intent0，精确closeout恢复同PID。丢失的003 post样本不补造，后续验证前持久保存post原字节；允许pre≤post≤request按request验证、post>request按now验证，时间倒退仍拒绝。两次早期closeout分别因队列自然新增pending或前像改名在cancel intent前零副作用停止，旧日志/目录保留；不复用attempt或恢复旧refresh字节。

共享前置证明、冷切换及native caller126项通过，包含原问题RED→GREEN、旧样本/非闭市/非零pending或订阅/错PID或token/FD未释放/输入漂移负测；独立Review允许唯一004。004四writer已全部park并持有持续fence，refresh在exclusive内冻结244条当前route（包含此前自然变化），实际SHA23b7a2a2a8b344b298210c287d87137d1ef947c5c8115d87825dc5f1391a3c63；720历史资产维护正在逐路原生执行并独立读回，未计完整通过。

004已完成全部720 historical unique stream：695 completed、25 noop，history-results.json SHA6f8d5e032034d377d9d23172902152162b0fc6c9ed106c39ee34f0ff57a9c4c6；244条已核验refresh控制完成原生清空。首组A4 native apply已提交，但外层receipt检查未限定current generation、把历史gen1/2/5计入而停止。004原progress保留revision:a intent而不补造committed；18份当时执行源码按frozen hash核对后seal保留。独立PG只读及reference-004-independent-readback-001.json确认720当前revision/端点、A4 gen7/plan/start、唯一current receipt、旧revision DATA_CONFLICT、专用boundary、旧batch payload/consumed hash与checkpoint hash、新flat checkpoint和READY全通过；五非Reference表hash完全不变。历史receipt不删除/禁用，剩余208 routes/52组；四writer保持原精确token/PID parked。接续只准备剩52组，重新取得真实FD/PG lease并逐步核验，不重跑720或A4，旧004不得冒充自然完整完成。

接续reference-forward-continuation-001完成52组208条原生revision提交与逐组readback；final-health保存720 enabled全部READY且pending Capture0，最终旧历史/A4和非Reference事实/输入保护检查均通过。原progress保留完整52对intent/committed；恢复reference同token/PID成功，但外层重复读取恰逢cycle→scan，且错误要求内存轮转pending_keys为0，报O18_RESTORED_REFERENCE_INVALID。pending_keys是max32 unit轮转后的调度队列，不等于未消费Capture/journal；不重复任何资产操作。Reference已active，剩余Alert/Live/Feed仍原token parked，采用独立精确closeout恢复并以单次cycle样本、720 pending_capture0及全部游标tail验收。

收尾001在任何intent之前因TASK新Alert ORM读取旧schema0051停止，目录仅保存真实cycle样本；未取消三条控制。002改用exact v7旧schema读取。实际只读完整snapshot又定位现有PG哈希源总量2,280,614,746字节，超原2GiB预算；保持完整查询/PG端大字段哈希、20万行及128MiB摘要上限，仅将有限source预算调整3GiB。完整旧schema快照实际通过：12类表，reference720 READY/pending0；cold105测试1.15秒全部通过，随后唯一restoration002执行中。

restoration002实际exit0：四个原gen19 owner全部恢复，原PID不变；Alert/Live/Feed保存各自新鲜业务heartbeat，Reference保存前后真实cycle单次样本。全部720 active READY、pending Capture0、全部journal游标tail；恢复前后完整12类数据库事实及Live/journal快照相等。旧004/continuation/早停001日志原样保留，不补造其完成状态；新独立closeout仅恢复控制、不重跑资产。当前允许进入统一v11发布与冷切换，正式版本/Runtime身份在实际操作后另记。
