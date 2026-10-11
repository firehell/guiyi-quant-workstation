# 盘中发布与连续交接实现

用户交办三包实现；基线 develop f363d3b8777f1cab8fa89b490eddd6af2561211b。
仅既有 operational、Rule/Scope/audience、720路记录；不改公式、收益或交易阶段，auto_order=false。

## 工程落点

1. runtime_bindings/deployment/retention：逐服务 exact tag/commit/root/generation、内容依赖计划、合同兼容、稳定dispatcher、逐服务health/维护身份及引用清理计划。
2. market_feed/observation_stream：唯一采集连接、source/completed有界journal、Lua原子提交、连续cursor前缀、原时间、跨日旧分区排空；Canonical不变。
3. runtime_handover/bootstrap/scheduled：只读预热、旧进程协作收尾、OS锁与代次、现场ready/输入frontier读回、首次休息段迁移与空基线、定时任务idle注册。
4. Alert/Reference/Newow：持久触发、typed cutoff、既有唯一身份/claim、原始30秒预算及EXPIRED_NO_SEND，0051增量迁移；线程完成后交权。

合同入口为 deploy/README.md、docs/DATA_CENTER.md、3份更新OpenSpec；验证入口 TESTING.md。

## 已验证证据

- 专用 Redis16389/DB11，隔离 PostgreSQL15479随机schema；无生产连接或真实推送。
- 联合身份/Live/Alert/通知/部署：500 passed，0 skipped。
- 扩展Reference全模块、Live recovery：706 passed，44 skipped；skip是其他可选隔离/资产条件，不能冒充通过。
- 新0051与one-shot专用PostgreSQL6通过，Stream及bootstrap专用Redis均真实执行。
- Ruff通过；全部29个变动app源文件联合Mypy通过，相关测试与迁移Ruff通过。
- OpenSpec 11通过、secret0、bash -n与git diff --check通过。
- 跨实现包独立Review发现并修正：revision/restart前缀、跨日积压、窗口冲突误ack、所有权丢失后写入、跨根共享锁、candidate监督/cwd、旧loaded身份与missing/unknown、清理cwd引用。

## 限制与生产验收

2026-10-10 已发布 v1.14.10@6cf781fc9347b798d02620d4d45c3b3030c4646f，PR #424、annotated tag及GitHub Release读回一致；merge树与候选一致。发布候选核心564 passed/0 skipped、Reference571项通过、补充109项及独立部署19项通过，31源文件Mypy与Web/锁/OpenSpec/secret/diff通过。旧fixture两失败在现役基线复现后已修正，不放宽生产门禁。专用测试容器与自身卷已精确清理。
本次只发布，未执行0051生产迁移或切换正式Runtime；现役仍v1.14.9，自然连续性验收待执行。

v1混合版本兼容只接受相等共享合同指纹：合同代码变化会明确阻止；不把这种保守限制表述为任意业务补丁都可无缝升级。
Reference只读warmup缺真实capture/checkpoint preimage时阻断，不伪造capture。旧canonical Alert缺发送收尾保护时首次迁移阻断。
未知交接/迁移保留精确journal及preimage，只能先readback，不恢复旧发送权或盲重试。

首次生产候选应从 exact现役tag叠加本任务，不能将develop尚未发布的Newow公式/UI修改混入。
全部权威Session确认休息、末根收尾且发送锁空闲后才执行一次首次拓扑迁移。之后分别自然盘中切换Live/Alert/Reference，
读取60品种端点、已有启用预警范围与720流；尚未自然发生信号时保留待验收，不制造广播，不宣布RUNTIME_READY。

## 2026-10-10 生产迁移与宿主启动阻断

v1.14.13@f49f54da0c908fc39ba33d3557a447f736579667已通过PR427/main、annotated tag及Release。239本次隔离测试全通过，新增恢复10项通过；工程检查与独立Review通过。v1.14.11/12预检问题仅以新tag前向修正，旧tag未移动。

owner要求直接迁移且不做DB备份。旧KeepAlive局部停用已通过精确文件/身份、完整发送锁和pre-schema/pre-install事实恢复（plan18d8a9d3a98e9860ff3910c3f09b5c8c1ea03e414318e4cf3b429cdee22cbb9c），原unknown bytes保留。随后新plan d2cf8d8fe7446d1dad6c7b958d7f4bfcdfc1184391bb0fbf065cae033b016e54实际提交旧版退出、0051迁移、显式0-0基线、plist和registry。

新启动均在取得正式owner之前exit126：macOS对launchd读取外置盘版本脚本报Operation not permitted。停止mutation并独立读回：旧Event/Rule/delivery/policy摘要完全相同，720路及启用时间/cursor保持；新增来源列全NULL，source/completed空，3cursor均0-0，未知claim0。已持6个owner锁卸载失败连续定义停止KeepAlive空重启；定时任务禁用，journal保留outcome_unknown/5个已提交步骤。API/Web和业务服务当前停驻，迁移成功不能表述为切换完成。

剩余唯一阻断为宿主权限；不能修改用户级/全局权限或借其他路径绕过。权限解决后先读取上述schema/registry/cursor/所有权及通知事实证明，再恢复已提交版本启动，不重复migration或初始化buffer，不恢复旧版或补发。自然连续性/通知仍待真实市场事件，不能声明RUNTIME_READY。

## 宿主权限解决后的恢复检查点

owner自行完成macOS管理员认证后，系统设置已添加并读回 `/bin/bash` 完全磁盘访问开关开启；不是修改TCC数据库或绕过宿主控制。0051迁移和显式观察基线不重跑。v1.14.13实际一次恢复启动后API/Web正常，业务服务ready未收敛而协作停驻；当前仅API/Web运行，原unknown恢复journal保留。

Live真实CLOSED解析结果没有trading_day，先前v1.14.14 fixture带day的假设与现场不一致，因此v1.14.14虽然已发布但未部署。v1.14.15通过唯一Session resolver解析下一真实session，保留当前CLOSED事实，不用日历加一天，不造TRADING或初始化cursor；现场60品种预检通过后发布，仍未切换生产。v1.14.15独审相关30项通过，Web构建与工程检查通过。

现场还核实v13正式weekly label传manual入口，周六小时调度反复只读扫描并持Canonical维护锁。独立Review确认该路径只有READ ONLY事务、Parquet读及本地状态文件，没有RQData请求/数据写入/通知。只在精确核对label/root/tag/commit/PID53129和禁用状态后发SIGTERM，并证明PID退出；这不是优雅审计完成，原running诊断已保留于 `output/intraday-v11414-runtime-20261010/weekly-audit-interrupted-preimage.json`。未终止另一历史资产任务或解除其维护租约。

v1.14.16候选修复唯一argv入口及bootstrap/scheduled两writer：正式weekly使用scheduled，candidate参数不变，其他任务不变。联合89项通过/1项可选Redis跳过，另入口/审计/所有权54项通过；独立46项通过/1项可选Redis跳过，Ruff/Mypy/secret/diff通过。一次性generation2恢复脚本独立31项通过，仅本次v16，旧v13源码SHA和精确身份限定旧manual参数，input/launcher差异限定已审查文件及冻结blob，DB/Live/formula/reference相等。必须所有旧进程退出或scheduled idle，再持10owner锁一次性绑定新代次，不混合同，不重置通知/消费进度。

恢复attempt尚未创建；维护锁可用、现场事实不漂移才能apply。API/Web保持HTTP200，业务服务停驻；自然盘中切换、60品种/720路连续性与新自然通知均未验收，不能声明RUNTIME_READY。

当前发布读回：v1.14.16@53434f5e5391e53bbaa9c78905da83f3b0fba548，PR430 MERGED，annotated tag peeled identity匹配，GitHub Release非draft/非prerelease；exact发布树detached/clean，锁定venv及Web typecheck/build/topology通过。额外54项在独立HOME中测试以隔离现场registry；生产HOME下合成weekly health fixture会被实际registry重定向，不能当作本补丁回归，未修改生产或伪造fixture。

只读generation2计划已冻结：ddf5964284276b88dcac89d8f3897e9ad33bd1bfe095b621547a818b6fcef1af，所有identity/schema/Session/DB/Stream检查通过，source_busy=true。未执行apply、未创建新的生产恢复attempt；API/Web仍旧v13 HTTP200，业务4停驻。待维护锁可用后按同一恢复边界核对，不盲重试未知结果。

## generation2实际切换与ready阻断

旧weekly空闲卸载经最终独审40项通过后执行，实际audit状态锁/owner/deployment锁内二次exact检查，单次bootout后权威absence写入unloaded证书；旧running诊断原字节未改。新计划baa2ea91741bc6ebd327fed1fe4062665e345ccaaf1b36a6adbb6d357232f8d2冻结时维护锁已自然释放。apply在重验后证明旧进程退出，原子提交十个服务到v16/gen2，实际启动六连续服务。API/Web/Live/Alert/market-feed均曾读回ready，Reference在120秒未ready，未注册定时任务即进入安全收尾。

当前gen2journal outcome_unknown，failure_code STARTUP_READY_TIMEOUT，current_step continuous_generation2_ready。API/Web exact ready得以保留；业务4已parked，日历disabled，未重复apply。失败后只读data_proof/unchanged_data_facts=true：事件/规则/delivery/policy摘要、六通知事实、新增Alert列NULL及source/completed/三个cursor0-0均保持。v16已绑定不等于业务恢复完成，不宣布RUNTIME_READY。下一步仅只读定位Reference阻断，后续恢复须重新证明同代次身份、所有权和无未知发送；原journal不能覆盖成成功。


## 同版本输入服务恢复

完整同版本恢复只读重验在Reference canonical_guard遇到SOURCE_BUSY，尚未创建attempt或修改drain。为推进独立服务，增加显式inputs-only模式，冻结与执行都验证Reference原PID/parked/drain SHA、四scheduled disabled/absent、exact身份及数据/发送事实。仅该模式跳过永不加载日历的due eligibility；完整恢复保留原检查。独立samegen/helper共66 passed，root复跑66 passed，Ruff/Mypy/diff通过。

新计划84d6a48a43e27749cc06fcc9434811b671c10bdc55bc868c62919b5276418d21实际一次取消market-feed/Live/Alert的drain，同代次journal phase=inputs_resumed_reference_parked。三个输入服务保留原PID61466/61454/61457并active，API/Web继续61446/61450；Reference61460继续parked，日历四项disabled且未加载。无新bootstrap、CAS、migration或cursor初始化。后续只读unchanged_data_facts=true，原unknown journal及archive字节保留，通知和范围未变。

Live/feed的checked_poll每轮先mark_not_ready、成功再mark_ready，所以单瞬间owner.ready缺失不能证明服务失败，也不能作为持续ready证据；恢复完成回读和后续自然运行分别验收。Reference和scheduled恢复仍待维护资源可用与独立恢复边界证明，不能宣称全运行恢复或RUNTIME_READY。

独立只读现场验收：三次有界采样确认feed ready null→true→null来自成功轮询窗口，取得整体checked_ready=true；Live/feed available heartbeat约2.7/2.3秒，operational60全CLOSED，无inputfailure。Reference原PID/drain、四日历disabled/absent及原unknown字节再次相同；事件/规则/delivery/policy、发送六事实、unknownclaim0、新Alert列NULL、source/completed 10/12空分区/cursor0-0、720=60×4×3均未变。仅inputs-only恢复现场验收通过；完整恢复及自然连续性仍未完成。

## v17/v18前向修复与generation4恢复边界

宿主10/10重启后，Redis/PostgreSQL晚于原Live/feed启动，原内存对象启动结果未知；一次独立inputs重建合作停驻后重新组合对象，未迁移、初始化进度或改变通知事实。Reference同代次续接仍超时，旧unknown journal保持。

v17@dc79e00ac7d3ad33b44fba5867ab1d4c1c341b10 / PR431新增安全有界Reference诊断；预热复用原不可变capture全文及关联checkpoint而非简略计算source proof。实际480路纯计算预热通过，未产生补捕获或发送。generation3独立新计划e89d2bd7cef676dcdb0ef3e4667b7aaf344afc4d2ca043e980ced5cecaafb95d一次换代；Reference仍120秒未ready，读回4路SOURCE_BUSY。后台历史刷新先于首个前台周期启动形成自争用风险，且容量预算退出。队列真实模拟证明112pending是正常轮转，不应清空；首轮blocked在第16轮才重检，不能用测试清零冒充恢复。

v18@8d8904e9bdc962f167f5f330eb90343f7640178c / PR432只在首个健康前台周期/进度证明之后启动历史刷新一次，停驻不启动、未知启动不重试；安全close完成后报告drained实际线程alive。APP_VERSION/tag/Release/exact干净发布树一致；相关81 passed/3隔离条件skip、独审48 passed，发布树48 passed、480路只读warmup48.42秒、Web build/typecheck/topology、OpenSpec11/11及工程检查通过。六种恢复helper联合128 passed，新增gen4 controller17 passed。旧正式Live225keys/9205bars摘要983dc88b2019f3423014a78b7d42b50c033958281c699fd6467e5bafe6d4ef44保持，不能当作新source观察；历史刷新199routes/0inflight/63,999,968bytes/SHA548b8b9a2a68495ce00b56dd6ae5f5aeaadc4fc0884e5881e8fbccf977ea620f保持，未清理历史刷新pending/blocked或加预算。

generation4计划59c7fe0a355f6ae72d6bc6da1bf7f1ba3bff0f927adfd4c5310e4fa2ce48dc79经过独立实际freeze相等后一次执行。旧6进程合作收尾/真实owner锁后退出，10绑定与plist换为v18/gen4，原6连续服务启动，首次全ready已通过。然而日历前再次采样报CONTINUOUS_READY_CHANGED，未加载任何日历；控制器安全停驻4业务，parked_verified=true。Reference停驻读回blocked0/通知线程False/历史线程False，原历史容量错误仍保留。API31920/Web31923继续active；Live31928/Alert31931/Reference31934/feed31937停驻。DB事件/规则/delivery/policy、六发送事实、720路范围、10/12空Stream及cursor0-0、10份旧journal均保持；无未知claim、无测试provider调用或补发。

只读独立复核完整facts约2.066秒，尚不含identity/HTTP；Reference扫描720路时ready暂清空而在健康周期后恢复，因此10秒要求同瞬间全部ready可能错过真实成功周期。新同代次恢复必须是独立attempt，先证明当前停驻所有权、线程关闭和无未知发送，再采集本次恢复后实际成功周期的时间戳；保留30秒新鲜度和120秒总上限、exact身份/heartbeat/当前blocked与保护事实。不复用generation4未知attempt、不重跑migration/CAS/初始化，不能据首次ready声明日历或自然业务已验收。

### 同代次周期证明恢复实际完成

新计划a927b5468e6bb2c8419c886cf2d4a5595aeed21ccee0fe6e3e30dc5ecba0a44f冻结当前v18/gen4六原PID/四业务parked与原control SHA、原unknown/source bytes、历史preimage及所有保护事实。锁内完成证明后必须先释放owner/refresh/maintenance锁，再在deployment序列化下逐项重验PID/parked/control并取消drain：原supervisor取owner锁为LOCK_NB，不能在取消时继续持其锁。真实子进程flock行为测试及27恢复定向通过，全部七恢复helper联合155 passed；Ruff/Mypy/diff通过、独立Review通过。任何未知取消、日历或最终journal结果均不重试，失败禁日历并合作停驻。

实际一次执行取消四drain，记录本次取消后的真实owner.ready=True时间戳，保持≤30秒新鲜度及120秒总上限；最终current stage/blocked/身份/心跳/所有日历再次读回。journal phase=generation4_cycles_resumed_calendars_idle，failure=null；六原PID31920/31923/31928/31931/31934/31937同gen4运行，原四日历after-market、late-provider-recovery、weekly-audit、log-rotate注册idle，没有kickstart或追跑错过任务。原generation4 unknown SHAfe9ad735772755b75d9150ab5b4f47199a4fcb94065665ae7b710a63b34f305b保持，独立source.bytes归档与原文件字节相同；没有迁移、CAS、观察初始化、测试provider、补发或改变启用时间/策略范围。

恢复成功不删除既有历史刷新容量/覆盖阻断和旧盘后失败诊断，不证明自然完成60品种/720路业务或真实通知。自然盘中独立切换及连续性仍待真实市场事件验收；不能提前声明RUNTIME_READY。

独立现场只读验收：六exact owner原PID/gen4 active，11:48:16.86–11:48:20.36Z采集各真实健康周期，最终≤30秒；identity matched/HTTP/Live及feed available heartbeat/Reference当前scan blocked0通过，四日历原enabled idle。schema0051、发送六事实/DB摘要/unknownclaim0、source/completed tail与cursor0-0、旧Bar/input证明、10原journal、unknown SHA/归档字节、historypreimage均一致；forward scope exact60×4×{1d,1w,60m}=720，旧activation/history资产原字节保持。此为恢复工程读回，不是自然盘中连续性或收件人收到证明。

收尾仅清理精确无引用旧v17发布树（cleanup plan c4322c586268209e7bd4b68d3c30adbbb3b972c1936bb74c23b4fb83e7370b98），删除前再次完整引用扫描相等，五个旧.run资产在v18逐字节相同；non-force git worktree remove成功。已合入main/develop的exact94fa145补丁任务树也在clean/ancestor/全引用证明后non-force移除。当前仅develop及最新v18运行树；未删除tag/Release/Git历史、生产数据、Scope或安全配置。
