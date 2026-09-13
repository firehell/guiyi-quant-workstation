# Newow 周线剩余工程与验收收口设计

状态：owner 已要求综合设计后直接交由 Sol high 实施。本任务不设计、不执行最终发布。

## 目标与边界

在已实现 CLEAR v2 的基础上，收口 PT 验收记录、补齐可重复的验收检查、整合现有 UI 改进、完成 operational
60 品种周线三策略的最新只读盘点和 180 组合结果，修复复现的工程缺陷，并形成真实数据缺口的精确处理方案。
工程完成、审计遍历完成、业务 READY 必须分别报告，不承诺在缺数据时得到 180/180 READY。

本轮允许源码/隔离测试、现有 Catalog/Canonical 有界只读查询、文档/evidence、独立 Review、本地 commit 与
条件满足的 develop 集成。生产下载或写入仍需拿到精确目标后单独批准：不把“发布以外都处理”解释为对未知
contract/window/plan hash 的批量 apply 授权。发布、tag、Release、Runtime 切换与其设计全部不在本任务内；
也不改变自然运行任务、Scope、通知、账户、公式或产品开放频率。

## 当前事实与不可变输入

- develop `9604a0d720cc31f2ac39d281a6613378c0bd2cd5` 已含 CLEAR v2 最终实现 `f32bac897`，工作树干净。
- 前任务本地复验：Core/API 483 passed、Web 定向 138 passed；完整测试与 Review 见实施任务记录。
- 固定 PT `as_of=2026-09-13T06:36:13+00:00` CLI 原始输出：三策略 chart/reference READY，退出 0。
  后续手写补充检查器误将 `FeatureRuntimeStatus.READY.value == "ready"` 与大写 `READY` 比较，退出 1，
  未产出 accepted JSON。其余 action 断言未报错，不等于全部验收程序已通过。
- 最新 PT 原始任务：`01a09a1b-610d-7a91-b3c8-9dd4c8f0d69c`；仓库 STATUS 和旧 readiness 摘要未同步。
- 原全量审计为 incomplete、未完成 matrix；旧 907 repair/494 metadata 等数字只是历史证据，不能用于当前执行。
- PT2608/PT2610 原两次 apply 已成功，意图耗尽，不重做；零写后重规划和 quota evidence 保留。
- UI 分支 `codex/ui-unification` 正在将 develop 合入自己的工作树；预检先看到 `ce33c9d1a`，随后
  `be6021f8ff0809edda3ca2a08bbf39956414d0b3`。`0460` 工作树出现过未解决的共享 primitive 冲突。
  这是其他任务进行中的工作，不是本任务可清理的 dirt。

完整行情唯一 authority 仍是 MDS/Catalog。周线及其 D1 companion 必须走既有同源与完整 ISO 周合同；
不得使用 synthetic actual-dominant 成交、provider get_price 替代交换所日行情、补默认 Bar 或缩窗口造 READY。

## 方案选择

采用“稳定工程验收 → 单次全量只读盘点 → 分类收尾”。它能先排除检查器/UI 漂移，再用同一代码身份评估数据。
不采用“先按旧 907 个目标批量补数”，因为目标已过期且还混有 metadata/source/integrity 阻断；
不采用“只修 STATUS 就算结束”，因为 180 组合和未集成 UI 仍缺真实验证。

## 1. 验收工具：复用既有查询，只增加确定性检查

新增一个小型 `scripts/newow_weekly_acceptance.py`，配一个离线测试模块；不新建后台任务、数据库表或审计服务。
脚本提供两个明确模式，所有命令归 TESTING.md：

- `pt`：在现有 `readonly_transaction` 中调用既有 `NewowProductService`，固定 PT/1w/上述 as-of，
  chart 与 reference 使用同一 snapshot token。入口复用既有配置/Session factory，不读出或打印凭据值。
  无 provider/download/repair 能力。每次执行单次有界查询，不在失败后自动重试。
- `summary`：只读取显式给定的完整 readiness JSON 与冻结 operational scope，生成脱敏摘要，不连接数据库。
  不根据文件名、glob 或“最近一个报告”选择事实；不把 compact 报告当缺口 authority。

纯检查函数 `validate_pt_initial_clear(chart_result, reference_result) -> dict` 返回成功或失败事实：
使用 typed `FeatureRuntimeStatus.READY`，不用大小写字符串猜测。两份 result 的 section 必须分别为 chart/reference，
对应 delivery=delivered、value 非空；meta identity 均精确为 pt/main_rise/1w/actual_dominant，公式/profile
为既有主升浪合同，as_of 均等于冻结截点，v2 schema/reference 与未变的 futures-adaptation 合同组必须兼容。
snapshot token 相等且非空，按现有 generation 合同验证数据版本字段；目前 data_revision_identity 为 None，
不能伪造 revision。两层 input_content_sha256 可因真实输入窗口不同而不同，不用强制相等替代 token/proof 合同；
PT2610 的目标初始 CLEAR 唯一、sequence=0、related_build_id=None、新资格；投影不存在以该 signal 为 entry/exit
的交易，预期诊断存在。BUILD 排除限定目标 owner/segment，不误伤其他物理合约正常历史，也不从可见图表裁剪片段
重建完整生命周期证明。成功检查序列化已读结果，不能再查询一次获取输出。失败先输出脱敏 violations 再退出 1。
总 trade count 可非零，不能把“无虚构交易”偷换成“全历史无交易”。

纯检查函数 `summarize_readiness(report, expected_products, expected_as_of) -> dict`：

- 验证完整 schema、command、readonly、as-of、frequency_scope=[1w]、matrix=true、产品数与 exact scope；
  原生 report 没有 code/scope hash 字段，这些由捕获时的本地执行上下文保存、摘要引用，不要求虚构原生字段。
  scope 文件 bytes hash 和规范化产品集合 hash 分开，不把集合相等冒充文件 bytes 一致；
- cases 必须恰为冻结 60×3 的唯一键集合，每个 main 与 chart 状态一致，不接受重复/缺项/跨频/跨截点；
- provider_requests/writes 必须为 0；missing/null/字符串 "0" 不能冒充确定的数字 0；
- 从实际 rows 重算 main/reference READY 和联合 READY 数，核对报告计数；保留每个失败/UNSTARTED 原因；
- 按现有 readiness 规则从枚举、dependency、repair 和 case section rows 重算未决状态，并与顶层
  complete/status/budget_exhausted 核对：UNKNOWN/UNSTARTED 或预算耗尽不能配 complete=true；
  known DATA_UNAVAILABLE 不是 audit incomplete 的同义词。错误类型/状态组合拒绝，不信任自报 complete；
- 区分 audit_complete（无未决枚举/预算中断）、scope_covered、main_ready、reference_ready、联合 READY，
  known DATA_UNAVAILABLE 不因 audit complete 而转 READY；UNKNOWN 不能改写成可下载；
- auxiliary WARMING、comparator NOT_APPLICABLE/样本不足、explanation UNOPENED 单列，不能改成正常信号或
  为追求 180/180 而启用 D1/60m/explanation。联合 READY 只声称 chart/reference，不代表辅助或跨周期全开放。

输入不合法时拒绝成功摘要。不要把 pure summarizer 变成第二份 gap resolver；repair/metadata 只投影原生行与身份。

## 2. UI 集成：先等作者完成，再固定树

新任务开始时先检查 UI source 的当前 HEAD、MERGE_HEAD、dirty state 和 Review 状态。
若仍在 merge/修改，记录 `UI_IMPORT_PENDING`，不 cherry-pick 其暂存内容、不修改 source tree、不并行修改同一
共享 UI 文件。独立 acceptance 工具和离线测试继续。使用任务列表定位实际作者任务，不能复用已过期 task ID。

作者完成且树干净后，固定最新提交和 Review 证据：若 develop 已包含则直接使用，否则在新隔离任务树中引入
该完整依赖，与当前 develop 集成。最小已知 UI 需求集合是 be6021f8 的已提交变更；不得自行挑掉该集合中功能。
如作者未完成，仅保留依赖 pending，不接管他的冲突。作者已完成但双方合并产生本任务的新冲突可按下列合同修复：

- 统一导航/壳状态、策略独立 overlay、参考文字改进保留；
- CLEAR v2 eligibility、marker label、详情、零伪 Trade、snapshot/cursor fail-closed 保留；
- 趋势点保持 display-only，不转成主动作；不恢复已退役 Trend legacy UI；
- fixture、unit、E2E 必须同时验证两组语义；不能整文件选 ours/theirs 丢掉另一侧功能。

最终本地 develop 集成前复验受冲突影响路径，并确认没有新的其他任务修改。不能用旧 UI Review 代替合并后 Review。

## 3. 全 60 品种只读审计与 180 组合

冻结 operational_products.txt 的内容/hash、product_window_starts.csv hash、代码 commit、合同组及固定 as-of。
只用 `guiyi data newow-readiness --universe operational --frequency 1w --matrix` 现有入口，一次串行审计。
本次预算 max_work=100000、timeout_seconds=1800（均在现有参数范围），不使用 `weekly-audit` 定时任务入口。
stdout 保存唯一完整 JSON；compact 必须从同一完整结果离线派生，不能另跑一次审计获取 compact。

通过现有 PostgreSQL 只读事务和 MDS 精确 Catalog 路径，不调用 provider。先只读确认 maintenance/after-market
是否忙；忙时不抢锁、不停止正式任务，等待自然空闲或记录 FIELD_GATE_PENDING。遵守宿主权限，不打开 credential
文件查看值或绕过读取限制。本轮只读目标已明确，但新任务的宿主拒绝不能用旧授权重试。

矩阵与数据盘点可在同一请求产生；缺数据仍保留全部 180 个 case 及可诊断状态，不先假定“必须全补齐才允许矩阵”。
超时/未开始项必须保持 incomplete，不能用更小 universe 或删 case 伪装完成；不得自动扩大预算或循环重跑。
如果代码导致错误分类/中断，先离线复现并修复；此前失败的现场尝试不因修复自动得到重试授权。

报告绑定 code/as-of/scope，不把 Canonical 每月 pointer 的原子性宣称为全局 snapshot；如果审计期间有已知
正式数据变更，明确报告跨读漂移并不得宣称全局一致。当前非生产工程操作不主动启动数据 writer。

## 4. 缺口处理：工程修复与真实操作分开

逐项保留主键、消费者、原始安全 code/reason 和原生 plan hash，分为：

| 类型 | 本任务处理 | 停止点 |
|---|---|---|
| 工程缺陷 | 在隔离 fixture 重现，TDD 修复、Review、回归 | 新发现要改公式/收益/完整性定义时停该项 |
| 缺行情 | 复用 ContractWarmupPlanner 生成最新精确目标，去重并关联消费者 | provider/Canonical apply 前要单次批准 |
| 缺 Calendar/Session | 复用 metadata 合同形成精确日范围方案，保留 UNKNOWN | 真实抓取/生产 metadata mutation 前批准 |
| source/integrity 异常 | PF/RS 等用现存数据和安全诊断定位，明确不可自动修复 | 不把异常零价改正价、不降级、不自动覆盖 |
| 正常样本不足/未开放 | 原状披露，明确影响范围 | 不开 D1/60m/explanation、不改参数制造信号 |

只选一个最小、依赖已齐的下一数据批次作为 approval candidate：精确 symbol/physical contract/frequency/日期、
plan hash、预期 bars/请求数、影响范围、dry-run、幂等/失败恢复/回滚边界。原 PT batch 不再列入待 apply。
900,000,000 bytes/日是以后真实下载批次的上限，不是当前只读调用的下载预算；旧 PT 样本不能用来按 Bars 简单
线性外推全量耗时或流量。source/integrity 与缺 metadata 不混入普通补数批次；无安全 candidate 就如实报告无。

## 5. Evidence 与完成判定

复用 outputs/newow-weekly-60-20260913/ 的 README/readiness-summary.json 作为当前索引，旧状态通过 Git 历史
追溯，保留已完成 PT apply 的不可变事实。新完整报告与 PT probe 输出在本次唯一的显式本地 evidence 目录保存、
绑定 hash；摘要只记录脱敏信息。不要覆盖既有原始文件，不新增多份平行 manifest/receipt，不把 /tmp 易失文件的
hash 冒充长期可恢复证据。持久目录须在本任务可写范围，若生产证据不能上传，文件留本地且明确标识未提交。

STATUS、旧 CLEAR implementation-plan 结尾和 README 同步真实的新结论；检查器退出 1 的原记录不能改成 0。
记录“旧误报已离线回归关闭”和“新现场检查实际输出”两个事实。生产连接未获准时同样可完成离线开发和 Review，
但现场/矩阵维持待验，不编造 accepted 输出。

完成出口分别为 CODE_COMPLETE、TEST_COMPLETE、REVIEW_COMPLETE、DEVELOP_INTEGRATED、
PT_ACCEPTANCE、AUDIT_COMPLETE、MATRIX_COVERED、DATA_GAPS_PENDING。整体仍有数据写入 Gate 时报告 PARTIAL，
不要写 60 品种全部 READY。这里不生成 release plan、tag/version 编号、部署方案或 Runtime promotion 方案。

远端上传曾在相关任务被宿主拒绝：普通干净源码 develop push 按当前权限处理，含生产 evidence 的历史/新分支不
自动重试上传；不可改 remote/全局配置绕过限制。全部本地工程仍连续完成，不把 push 拒绝扩大成全任务停止。
