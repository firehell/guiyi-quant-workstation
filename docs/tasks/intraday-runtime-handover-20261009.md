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

当前代码交付不表示已执行0051生产迁移、已创建tag/Release或切换正式Runtime。现役身份以STATUS现场记录为准。

v1混合版本兼容只接受相等共享合同指纹：合同代码变化会明确阻止；不把这种保守限制表述为任意业务补丁都可无缝升级。
Reference只读warmup缺真实capture/checkpoint preimage时阻断，不伪造capture。旧canonical Alert缺发送收尾保护时首次迁移阻断。
未知交接/迁移保留精确journal及preimage，只能先readback，不恢复旧发送权或盲重试。

首次生产候选应从 exact现役tag叠加本任务，不能将develop尚未发布的Newow公式/UI修改混入。
全部权威Session确认休息、末根收尾且发送锁空闲后才执行一次首次拓扑迁移。之后分别自然盘中切换Live/Alert/Reference，
读取60品种端点、已有启用预警范围与720流；尚未自然发生信号时保留待验收，不制造广播，不宣布RUNTIME_READY。
