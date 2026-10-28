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
- 最终补齐监控配置账户与索引账户exact匹配、fsync后快照TTL重验，均RED→GREEN；含monitor完整组合575 passed（43.23秒）。独立Review未发现其他Confirmed Issue，等待最终commit核对。
- 冻结90条原件/路由及2618恢复闭环在新临时PG实测身份摘要完全相同；1m/5m接收平均959.93/950.93ms→4.75/16.03ms，p95为7.65/38.37ms。证据主树output/reference-inbox-intake-20261028/benchmark-overnight-candidate-45.json（SHA05d16946…），临时容器已stop/remove。
- 独立Astra安全Review固定900f0da→d6ef03ec4：无未解决Confirmed Issue，无Optional Improvement，允许集成develop；现场柜台、发布/切换及自然验收由执行阶段另取实证，不以Review代替。六个生产模块定向Mypy通过。

## 候选准备与新发现的现场阻断

草稿发布PR535，初始候选c599845b7，root为主树.worktrees/release-v1.16.32；uv/pnpm离线依赖及Web构建、
候选Reference/Alert/health1454 passed/115 skipped、SimNow575 passed及SDK无网络准备均通过，未发布或切换。
02:35单次续接automation-2已更新精确对象与06:30/07:00/08:00边界。

23:32只读现场：十身份仍v31/gen37，行情心跳正常；pending575、UNKNOWN0，但新增1条AU60m
23:00 HTDY_WINDOW_UNAVAILABLE（23:28:52接收、23:29:39阻断），9条融合依赖等待，旧BLOCKED累计340。
唯一MDS只读定位：32根完整，合约/cutoff/末Bar逐值一致；原件notification_eligible=true，之后Live恢复
revision2/recovered_through=23:04:06.474307使当前窗口notification_eligible=false。
这违反已接受Inbox原件资格不可被后来快照替换的合同；只对已验证的60m原件保留冻结资格，仍逐次完整验证
当前32根、physical owner、末Bar及source/recovery-current；不改变Alert/通知时效、不接受恢复生成的不合格原件、
不放宽legacy/snapshot路径。失败复现后16项定向转绿，继续扩大回归与独立Review，作为本版交付阻断修正。
生产BLOCKED原记录未改，闭市必须用现有reference_inbox_recovery_v1停writer、精确计划及独立读回完成原件原生续接；
不重置状态、不伪造first_seen、不创建历史信号/通知、不直接SQL解锁。未证明恢复前不能宣称策略范围完全正常。
- Ruling: 原显式恢复allowlist未含HTDY_WINDOW_UNAVAILABLE——仅加入exact htdy_identity(product)的已接受60m身份识别，
  沿用原stopped-writer/原件hash/checkpoint/receipt/source/claim/原子闭合和未知禁重试，不加入自动重试或修改原BLOCKED。
  代价为该精确身份的维护入口新增一类可验证故障；完整来源及计算仍须通过，其他策略/周期不放行。
  临时SQLite真实HTDY内核和四类投影链已RED→GREEN，证明原BLOCKED保留且append closure后追尾、无AlertEvent。
- 追加修正扩大Reference/Alert/health1452 passed/116 skipped，真实隔离PG（接收+HTDY含闭合）9 passed；
  MDS/HTDY/恢复定向162 passed，Ruff、两模块Mypy、OpenSpec12、secret0/diff通过。Mypy暴露的已有
  snapshot.state=None注解不一致仅改为Optional以表达已存在原件路径，不改运行逻辑；等待独立Review。
- 追加HTDY修正独立Astra Review固定bc8163ddf→61f13712d：无未解决Confirmed Issue、无新增代码阻断，
  reviewer另实跑38 passed/5 deselected，允许集成；现场恢复/发布/自然验收仍待闭市与开盘事实。
- develop期间另一任务新增c09b1771c LMS研究文档，本任务保留并正常merge，不纳入选择性发布候选。

## 10/29凌晨阶段交接

- 精确候选`8963ae7151a52b3b17a6b8a701e44544dae1b917`，主树`.worktrees/release-v1.16.32`，
  branch`codex/overnight-release-v1.16.32`，草稿PR535；36文件，代码/测试按两次精确择取manifest核对来源。
  实现已合入develop7139515c1，其他任务研究保留且不在候选中。未merge main、tag、Release或Runtime切换。
- 候选Reference/Alert/health/MDS1591 passed/116 skipped，SimNow575 passed；真实隔离PG9 passed；
  离线锁定uv/pnpm、Web type/build/topology、SDK无网络准备、Ruff/Mypy/OpenSpec12/secret0/diff通过。
  两个一次性测试PG均已stop/remove，无后台压测/测试/额外账户连接。
- 23:58只读：十身份仍v31/gen37，维护锁空，pending0、blocked10、UNKNOWN0、completed10617；
  回收历史2618、原BLOCKED累计349保留，global degraded。十条均23:00 HTDY60m：SS/NI/CU/AL/SN/SC/ZN/PB/AO/AU。
  10/10唯一MDS窗口完整、原件eligible=true且合约/cutoff/末Bar同，当前window资格被后来的恢复through撤销。
  证据主树output/overnight-first-four-20261028/htdy-block-context-v2.private.json及htdy-all-window-diagnosis.private.json。
- primary output同目录已保留只读账户attempt1、两次选择性候选manifest及新schema3 release-source配置；
  未初始化四库、未启动observe、未发布私有monitor绑定。旧账户历史UNKNOWN不改变。
- automation-2为ACTIVE、单次02:35，已更新候选8963及10条原件恢复范围。只在fresh全部CLOSED及宽限结束后继续；
  先核对真实时间、最新分支/dirty、远端版本占用、原生未知结果及维护竞争，按原06:30/07:00/08:00截止处理。
- 剩余：正式发布和原生切换；10条有效原件逐条freeze计划/停writer fence/单次claim/原子闭合及独立readback，
  随后正常原生续接；新Reference drain/resume（finally撤销精确请求）、60品种30分钟隔离真实节奏容量；
  fresh SimNow初始化、唯一observe/两轮对账/重启/监控切源；最终服务和原日历读回，09:00后自然验收仍待发生。
- 旧output/reference-night-recovery-20261028/executor.py/continuation.py仅可读参考，硬编码v25/旧截止/已消费attempt，
  禁止直接执行或复用。新的原生维护须当前exact root/代次/日期与新私有attempt，未知提交先读回，不能盲重试。

## 02:35闭市续接与正式发布

- fresh Session证明60 CLOSED、确认宽限结束、注册交易日2026-10-29，维护锁空、未知部署guard通过。
- 02:35读回v31/gen37十身份一致，pending24/blocked10/UNKNOWN0；后续pending在十条阻断之后，未修改原记录。
- PR535按expected head合main，exact f489c4478a1af4a3888e78976b809a32e5423a57；annotated v1.16.32及GitHub Release已独立回读一致。
- exact发布树锁定依赖/Web build完成；新原生计划9dce1418b34d3f1b393905416a24d3943eaacdb85e4a16ab3d197c094557c39b，v31/gen37→v32/gen38，正在纯预热/交接，未声明Runtime成功。
