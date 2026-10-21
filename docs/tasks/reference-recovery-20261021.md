# 10/21 Reference 第五、六步恢复

状态：执行中，完成结论以末次现场验收为准。

## 范围与原像

owner交办完成Reference积压及H1冲突/滞后恢复。正式Runtime为v1.15.16 / gen22 / `c559eb7a594dea5189c7a630b010a284032e89f4`，应用代码、公式、Scope、Rule、audience与交易阶段不变。

20:04现场：720 enabled，480 READY、200 DATA_CONFLICT、40 OBSERVATION_LAGGING，pending Capture0。completed/2026-10-21尾为`1792566005587-4`，Reference原游标`1792564204050-3`，积压2601条；当时没有SOURCE_BUSY。40滞后与200冲突均在60m。

240路历史种子的原active checkpoint均到10/16：172 READY/active、68 STALE_INVALID/invalid。68路均有既有candidate及持久resume，不能抹掉重建进度。逐路重新验证旧固定窗口：匹配则原生resume；不匹配则保存旧控制状态与candidate，生成新鲜精确计划。m样本仅source evidence变化也不允许改旧token续跑；PX、ZN样本通过旧源原生校验。

40滞后剩余20个原件中17个与最终Canonical匹配，LC/PD的14:30与CU的15:00成交量/成交额不等，价格相同也不豁免。正常消费后形成的真实mismatch需另作精确版本恢复，不把只读比较冒充数据库核对。

40滞后均通过JournalRecoveryAuthority原生缺前缀验证，跨日checkpoint亦通过实际权威端点检查。缺口是缺失原始观察，不以Canonical冒充原始观察；BoundedForwardRecovery显式记录观察中断，由正常消费者处理边界和剩余原件。

## 执行与恢复边界

- 证据与caller位于`output/reference-recovery-20261021/`。所有attempt、失败、旧计划与原观察保留。
- 首轮历史修复以原生drain停驻Reference，同PID/gen/token、deployment/after-market/owner OS锁及原生Canonical PG lease核验。20:45协作截止；安全结束后释放写入锁、核对身份和锁释放，再取消自有drain。
- 首轮于20:45:00安全结束，100路历史计算完成，原PID52242/gen22恢复active且无inflight。后续历史维护仅写historical身份，持同RefreshStateStore互斥排除内置历史后台，原生每source lease不取消；foreground正常运行。优先原200冲突源，以及剩余原件确有数值差异的LC/PD/CU三品种12路，共212源；其余28源后置。两集合恰覆盖原240路。
- 前向恢复先处理40路gap，原生freeze/plan/apply/readback全程持Reference与PG fence，要求所有保留原件ID严格位于原游标之后，不调用replay。
- 冲突按品种完整4路，重新验证全前缀历史manifest后，用ConflictRevisionRecovery创建独立FLAT新版本；旧revision失效，旧Capture、核对、动作和参考交易事实保留。首个新H1之前必须完成精确未来起点的激活。
- 不直接写游标/ACK、不重放、不补发、不下载行情。未知提交、存储未知、receipt冲突或inflight未读回时保留drain，不复用旧attempt。
- Feed新交易日日切要求旧消费者追尾，因此首轮优先gap并在夜盘前恢复正常消费，未ready冲突组defer，不能等待全量历史再恢复。

## 已执行验证

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=../..:../../packages/quant-core .venv/bin/python -m pytest tests/reference_trading/test_historical_refresh.py tests/reference_trading/test_conflict_recovery.py tests/reference_trading/test_bounded_recovery.py -q`

在正式release的`services/quant-api`执行：48 passed、6 skipped。首次未设置仓库PYTHONPATH的收集失败保留为环境错误，修正入口后测试通过，不计为业务失败。

独立Review已修正未知提交后错误恢复writer、无差别替换blocked状态、覆盖同代未决drain、gap PG lease和夜盘日切时限问题。更新后caller复审通过。原生gap只生成boundary，没有BUILD/CLEAR通知动作；积压保留原始时间，过期记录EXPIRED_NO_SEND。

恢复前逐条冻结H1旧事实：18,352批次、5,721核对记录、611动作，摘要`a1f1e9430b911aaf7c1750c80f97c4fae6b5cc7168f4fd1afe41331b54c48346`。最终必须逐条验证无缺失、无改写；追加新边界/批次与既有事实分别核对。

## 实际中间读回与异常恢复

20:47:48首轮前向恢复完成40路gap边界与88路冲突版本；原Reference PID52242/gen22恢复。40份原生readback及consumed_calculation全部成立，原2601条积压由正常消费者清零，19/20/21三天游标均追尾，无手工ACK/replay。随后LC、PD、CU的真实原生reconciliation均形成mismatch，按实际证据处理，不以只读预测替代。

第二轮历史attempt于20:58:28在PF/main_rise组件入口遭遇SOURCE_BUSY安全退出，新增30路完成，生产state无inflight。已完成的240路中有130路通过checkpoint、manifest哈希和21日07UTC端点核验。旧attempt保留；新attempt3仅在原生组件进入前、尚未planning或写入时，等待Canonical维护锁最多60秒；任何业务体或未知结果不重试。额外5项资源边界单元测试与独立复审通过。

夜盘验收另发现Live原PID52223/gen22锁存OBSERVATION_SUBSCRIPTION_MISSING，Feed原生完成22交易日日切并保留源原件。单次原生gentle drain/park/cancel恢复消费者，持部署/after-market/Live owner锁，冻结现存源前缀及逐条身份，允许Feed正常追加。PID未变，旧事实不变，无进程重启、手工ACK或重放。

21:12:18独立验收：source22共540条且Live追尾，completed22共630条且Alert/Reference追尾；Feed及Live心跳新鲜available=true，45夜盘订阅，operational仍60；225条恢复前source前缀哈希不变。630条completed身份唯一且索引id/payload对应，raw_received_at/source_observed_at原时间保留，未重置为恢复时间。详见independent-live-recovery-verified.json。

## 最终读回

待实际执行后填写。测试、历史重算或新版本激活均不能替代正常消费者追尾、自然新Bar和通知实际送达证据。

## 10/22 凌晨续接

03:00重新核对develop HEAD为8879cd871，正式Runtime仍v1.15.16/gen22；Reference同PID52242。昨晚history-attempt-3于21:41正常结束，原生只读确认216/240历史源完成。当前720 enabled中596 READY、124 DATA_CONFLICT、pending Capture0，source/completed四天所有消费者均追尾。

启动全新history-gap-attempt-2，沿用已复审原生恢复入口，只更新时间窗口与attempt目录；修复剩余24历史源，不下载、不改游标、不通知。定向pytest实际48 passed/6 skipped。

独立Review阻止把旧15:00 seed直接切到次日09:00：有夜盘组将遗漏kernel输入并在首晨Bar再次OBSERVATION_GAP。已用M2701实际原生Session端点重现。新caller仅允许完整4路逐一证明09前无expected端点、首未来端点单一且owner/contract相同的日盘组；夜盘组明确defer。

夜盘普通retained originals不具有现有v1 warm要求的actual repair plan/readback；不能伪造字段、改称Canonical或制造无必要下载。须版本化补齐正常原件的typed warm authority与对应canonical/测试，之后方可收口夜盘组。独立依据见output/reference-recovery-20261021/independent-0300-recovery-review.md。

### 凌晨实际结果

03:09历史gap新attempt正常HISTORY_STAGE_ENDED，独立240/240历史源READY/active，checkpoint文本及manifest摘要均通过，端点21日15:00。

03:10前向attempt2完成LC/LH/PD共12路后，在PG下一组建plan前原生OWNER_IDENTITY_CONFLICT停驻；三plan三result与累计100冲突/40gap原生读回完全匹配，无未知提交。按独立Review完成持久恢复intent、binding/PID/gen/token/游标/无inflight复核后取消自有drain，同PID恢复active。旧失败不改写。

新attempt3仅把无副作用interval预检的精确OWNER_IDENTITY_CONFLICT记defer；不捕获plan/apply失败。03:13完成PK/SF/SM/UR共16路，正常结束并取消自有drain。累计冲突恢复116/212（凌晨新增28），40gap均已消费。116冲突+40gap完整独立读回通过。

剩余96冲突：CU/M/MA/NI/OI/P/PF/PL/PP/PR/PX/RB/RM/RU/SA/SC/SH/SN/SR/SS/TA/V/Y共23组92路需完整夜盘原件暖机；PG4路原生owner身份冲突，须先证明seed到当日物理owner的明确边界。没有用新主力替换旧checkpoint规避检查。

旧18352批次、5721核对、611动作逐条比较missing=0/changed=0；新增事实独立保留。凌晨新增28路未来起点为22日09:00，首个自然H1尚未发生，不声明自然验收通过。第六步仍PARTIAL，不声明全局RUNTIME_READY。

03:14最终完整health读回624 READY/96 DATA_CONFLICT、pending Capture0；source/completed四天全部消费者追尾。Reference仍同PID52242/gen22 active，通知worker存活，无自有drain；owner ready=false与pending_keys112如实保留，不能用blocked_count短暂0代替完整矩阵。原生历史后台已恢复alive=true。
