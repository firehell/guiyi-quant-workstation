# 前四步夜间交付

Owner已批准完整实施；截止北京时间2026-10-29 08:00，明早09:00开盘稳定优先。
开发基线900f0da265cb64e62563c3677b3bc3a25c11a686，隔离分支codex/overnight-observe-bootstrap。
现役v1.16.31/gen37；开盘期间不发布/切换/重启/修改生产Scope，只允许独立SimNow只读登录查询。
全部收盘预计02:30，必须fresh Calendar/Session及确认宽限证明；06:30不再发起正式切换，07:00冻结功能/初始化/部署，08:00暂停。

## 实施与验收

1. 补齐独立observe bootstrap：显式只读和仅观察初始化，schema3仍纯准备；复用SDK/账户快照/初始化/同账户锁。
2. 已完成夜盘接收补丁择取发布；只含本任务必要依赖，不整体发布develop研究改动。
3. 闭市fresh完整快照证明空仓/无活动委托/无未解释冻结后，四库临时创建验证再原子发布，生成schema2 observe配置。
4. 唯一observe宿主连续两轮对账通过后切监控来源；只读、无Adapter/结算确认/报撤单。
5. 定向TDD、真实隔离PG/SDK验证、完整分支独立安全Review；正式版本/owner/游标/水位/积压至少两次读回，实测drain/resume。

真实资金严格来自柜台；旧UNKNOWN历史不继承不覆盖。账户非空/快照不完整/锁冲突/柜台不可用则仅保留事实，禁止猜空仓或启用。
未验收的新SimNow在截止前停用且保留已提交状态；市场服务优先，不因赶时间降低提交/恢复条件。
自然输入/信号/参考交易的验收留待09:00后；隔离真实原件回放不能代替自然证据。

## 进度

- 已核对干净基线、正式v31、既有夜盘接收与schema3实现；任务工作树已隔离。
- 开发与隔离验证进行中；已完成授权的真实只读核验，尚未初始化、发布或改动正式服务。

- 基线准备/settings/service 57项通过；bootstrap首轮12红后实现，新增CLI7红后实现；supervisor组合153通过，继续扩展闭市观察测试。
- 已创建本任务单次02:35续接automation-2，COUNT=1；并非生产维护或交易任务，完成后停用。
- Ruling: 闭市observe需账户只读连接——既有宿主仅交易/开盘前120秒连接会将验收推迟到08:58——仅observe在fresh全部CLOSED时允许账户读取，不授予manage/trade或报价执行权限；错误放行风险由模式隔离/权威反证测试与独立Review约束。

- bootstrap/CLI/闭市observe组合172项已通过；测试均使用隔离账户锁及临时四库，无SDK网络。
- 真实只读attempt1成功，两轮一致、flat_verified=true；从既有Keychain安全加载，仅四类原生查询，API白名单禁止确认/报撤单。
  配置与真实快照位于本任务output/overnight-first-four-20261028，0600；未初始化账本、未启动observe或改正式服务。
- 旧SimNow标签存在但无PID，旧runner/config均缺失，无SDK宿主进程；本次未卸载旧定义，将在闭市启动阶段处理。
- 首次只读CLI旧字段account_reconciled=true仅代表双轮原生一致，并未建立账本；已用红绿测试修正后续摘要为account_read_complete=true、account_reconciled=false，原attempt证据不改写。
- 原生诊断失败的连接释放、过期next Session拒绝均RED→GREEN；同账户四库/锁/CLI/Host/执行/市场回归537 passed（43.70秒），Ruff、secret scan 0及diff检查通过。
- 独立Review确认并修复三项：CLOSED提前毒化下一交易日预算、资金Available残差未解释、慢闭市证明跨截止仍可rename；均新增失败复现后转绿。
- Ruling: 监控来源使用现有严格schema2配置的私有只读绑定文件——API原入口只接受启动env，若等两轮后切换需再次重启正式API——改为缺文件沿用旧源、无效503、原子发布后逐请求校验；风险为私有绑定漂移导致监控暂不可用，不影响账户及行情计算。
- 真实隔离PG回归4 passed；扩大Reference/Alert/health组合1446 passed/115 skipped的两项失败定位为任务测试日志目录缺失，创建0700隔离目录后worker_entry全45项通过，候选上再跑组合。
- 23:12现场只读：十服务仍v31/gen37、Session49 CLOSED/11 TRADING，pending284、BLOCKED/UNKNOWN0，completed9683，维护持锁无干预；无新增输入错误或停服。
- Review修正及监控绑定新增后完整SimNow/账户/Host/市场/API组合548 passed（43.39秒）；新增三项均先失败再转绿，Ruff/secret0/diff通过。
