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
