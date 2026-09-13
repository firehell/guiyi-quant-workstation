# Newow 周线数据与异常统一恢复设计

日期：2026-09-13。版本：剩余工作 R1。状态：REVIEW_COMPLETE，允许交付单个 Sol high 实施。
本文定义当前设计；实施计划中的早期记录仅保留历史，不覆盖本版边界。

## 目标与当前事实

在一个恢复任务中完成元数据、普通历史缺口和异常归因的闭环；不混合三者的写入权限与成功标准。
现有工具足够承担规划、抓取、校验、发布和只读验收，暂不新建批量调度器或第二套缺口系统。

本次读取的最新 develop 为 `74d7a71fcd061d25eb23d7d2142a075420125886`。设计文件所在任务树仍为
`c60e147fad34f24f8874ef50ac83f2131cc2c626`，只新增文档，不从旧树运行生产修复。实际执行须重新固定
最新 develop 及导入身份。开发任务由一个 Sol high 独立任务统筹；与现有开盘前维护工作共享
Calendar/Session，真实 provider/DB/Canonical 操作不能并行抢占共享维护链路。

依据已恢复并验证 hash 的完整原始报告 `outputs/newow-weekly-data-recovery-20260913/isolated-5b31cf7c/full-readiness.json`
（采集早于 batch-03 写入，以下是历史基线，不是当前剩余计数）：

| 项目 | 已记录事实 | 不代表什么 |
|---|---|---|
| 普通修复 | 896 个 PROPOSED 合约/频率候选 | 不是已批准的 896 次 apply，也不是当前仍有效的缺口清单 |
| 元数据 | 494 行提案、247 个唯一合约/频率/through 目标 | 不是 247 个 Session 日期，更不是 494 条待插入数据库行 |
| PF2611 | 1w，2025-11-21，SOURCE_NONPOSITIVE_PRICE | 不证明重新下载能修复 |
| RS | 9 个 REVIEW_REQUIRED，REPAIR_SCOPE_SOURCE_OR_INTEGRITY | 不证明九个目标有同一个根因 |
| 全矩阵 | 180 个 case，联合 READY 6；审计 incomplete | 不能承诺补完普通缺口后必然 180/180 |

23:20:56 CST 只读重规划确认：batch-03 的 63 个目标已完成 6,065 行 Session 一次写入，1,696 个
日期缺键及全部请求归零；不得重新下载或重复 apply。剩余 184 个目标、7,012 个 Session 日期缺键，
Calendar 缺键 0；batch-04/02/01 分别为 6,036/7,366/10,135 个元数据请求，原 plan hash 未变。
本轮 parent 按 owner 直接下载意图对这三批串行各尝试一次，23:40:49 CST 全部 prepared，合计
23,537 个响应、27,159 行 Session 快照；原生校验与逐项 journal 对照通过，无重试、无显式额度查询，
本轮 DB/Canonical 写入为 0。详细 hash 与终态见实施计划交接记录；这三批不再下载。
这些请求是交易时段元数据，不是分钟 OHLC 下载；下载完成不等于 Session 已入库。

最新代码已包含 `INITIAL_CLEAR_NO_ENTRY`、API `newow_product_detail_v2` 和参考模型
`newow_marker_reference_zero_cost_v2` 及 Web 消费校验。显示 CLEAR 而不制造 BUILD/ReferenceTrade
不是待重新实现的需求。剩余工作是数据与来源异常收口、必要的已复现缺陷修正及真实只读页面验收。

RS 专项名单：RS2407、RS2409、RS2411、RS2507、RS2509、RS2511、RS2607、RS2608、RS2609。
规划初稿时完整审计引用文件在旧摘要所指路径下未找到；不能只凭摘要恢复精确缺失日期、分区和 scope diagnostics。
2026-09-13 经新意图批准的固定副本重采集已恢复相同 hash 的完整报告，详见实施计划的重采集终态。
这仅关闭原始报告缺失问题，不关闭元数据、补数或来源异常 Gate；后续继续从同一原始文件提取明细。

## 唯一链路与范围

仅 operational 60 品种的 1w 和其必要的同源 1d companion，冻结截点
`2026-09-13T06:36:13+00:00`。同一轮不悄悄延长 through、不开放独立 D1/60m 产品或 explanation。
行情仍经 RQData、staging/硬校验、Canonical、Catalog/MainContractMap、MDS；元数据走既有
`metadata-repair`。不新增行情 resolver，不改策略、初始 CLEAR、ReferenceTrade 或收益口径。
不执行 main/tag/release、Runtime 切换、通知、migration 或账户操作。

逻辑顺序为：证据恢复 → 元数据精确规划/补齐 → 普通缺口重新规划/补齐 → 最终统一验收。
PF/RS 归因可以与只读规划交错进行，但真实 provider/DB/Canonical 操作全部串行。一次性处理指一个任务
统筹、有界分批收口，不是一个跨 provider、文件和数据库的全局事务，也不是无限持续写入授权。

## 元数据：按业务键补事实

从原始提案提取明确 symbol/physical contract/owner-through；去掉 frequency 的重复时保留原始关联，
不擅自把同合约不同 through 合并扩大窗口。提交给既有 planner 的单批 targets 最多 64 条。
由 planner 的实际输出去重 Calendar `(exchange, date)` 和 Session `(symbol, exchange, date)`；
跨批共享键在前批成功后重新规划，不能用一批旧 hash 执行后续重叠批。

未知交易日先走分类 fetch；分类后如果新增 Session 请求，必须生成新 plan 并另获 fetch 意图。
Session 只插入完整缺失的日期，不覆盖已有日期，不缩短原模板的有效区间；已有但疑似不完整的 Session
进入异常调查，不能把“已占用”计为修复成功。夜盘缺失不是无夜盘证据，证据不足维持阻断。
fetch 和 apply 是两个独立 Gate；额外供证合约或 inventory 请求也必须显式列入并批准，不能临时扩展。

元数据结束后重新读 Calendar、Session 与 MDS 依赖；MainContractMap UNKNOWN 必须按新的具体原因
重新归类。真实映射缺失不能通过 Session 插入制造 rank1，需要单独有界设计与执行批准。

## 普通补数：先重算，再小批推进

元数据变化使旧 896 候选及旧 hash 失效。重新规划完整依赖集合，含原先因元数据失败未形成候选的目标。
只有完整 scope diagnostics 无来源/完整性冲突的目标才能进入普通队列；W1 连带的 D1 同样检查。
按物理合约和 companion 分区消除重复工作，不把 W1 和其 D1 companion 当成两个独立下载任务。
不扩大通过日期以实现去重；同一合约多个需求仍保留原关联并逐次 replan。
既有 readiness planner 已将同合约修复需求归并到明确需求中的最新 through；沿用这一原生结果，
不拆成重复执行，也不在该最新需求之外延长日期。每批执行前 replan，而非每条重复消费者依赖执行一次。

先选依赖齐全、可独立验收的小批作为试点，然后按品种闭环优先串行推进。历史 EC2607 1w、through
2026-06-30（曾估 84 bars/8 requests）仅是试点线索，不复用旧 hash；旧 EC dry-run 失败/被宿主拒绝
不视为已运行或授权可重试。PT2608、PT2610 已完成 apply 不重跑。

每个 apply 明确单一物理合约、1w+D1、through、分区集合、plan hash、请求身份、影响和恢复方式。
owner 最新明确接受流量不确定性：本恢复任务取消原 900 MB 预测门槛，不做额度探测、流量估算、样本
校准或下载前后额度核算，不因无法计算预算而阻止已获准下载。原生计划中的请求数只是范围证据。
不改变 SDK 自身许可初始化；真实配额/权限错误仍按既有错误分类停止，不自动等重置、重试或切换账户。
维护锁忙、plan 漂移、失败、权限拒绝或结果不明，停止当前执行链，不自动重试或切换入口。

## PF 与 RS：独立隔离及处置判定

每个异常保留现有 reason 和 scope_conflicts；只沿 Catalog 指定的对象检查分区 hash、数据集身份、
物理生命周期、映射应有端点、实际端点、交易日、OHLCV 以及必要的 D1/W1 同源关联。禁止 glob 猜 active。
观察到的异常不能直接归因为 provider；来源证据不足写“未判定”。必要源核验列出精确接口、合约、日期
与落盘范围，按当前有效单次下载意图执行，不加流量 Gate；不把源核验捆绑为正式覆盖授权。

| 证据结果 | 处置 | 通过标准 |
|---|---|---|
| 权威源本身非正价格 | 保留源事实，维持 Newow 阻断，记录不可按普通缺口修复 | 来源事实可验证；不造价、不删 Bar、不以结算价/前收替换 |
| 本地适配或聚合代码错误 | 最小复现 → 新失败测试 → 修正代码 → 独立 Review；语义变化更新 canonical/版本 | 测试通过后另批精确重建与写入，不凭离线通过宣布数据已修复 |
| hash/对象身份损坏、生命周期或映射冲突 | 列精确受损分区与根因，冻结修复前指针/证据，专项方案批准后重建 | MDS 读回、hash/身份/端点一致，恢复既有合法窗口 |
| 仅普通端点缺失，其他证据均健康 | 经逐项审查和新 replan 后转入普通队列 | 新 diagnostics 无冲突且精确缺口可补；不批量解禁全部 RS |
| 来源证据不足或互相矛盾 | 明确 BLOCKED 和缺少的最小事实 | 不降低正价、完整性或 Session Gate |

PF2611 从 2025-11-21 的原始 source/Canonical/必要 companion 定位；未证明九个 RS 根因前不选择覆盖。
源异常如需 provider 核验，只批准明确合约、日期、接口与响应存储，不捆绑生产发布。
若发现需改变数据政策才能显示该段历史，本任务停在证据充分的阻断状态，另请 owner 决定合同变更。

## 原子性、幂等与恢复

- Metadata apply 使用新事务、5 秒 lock timeout 及 exchanges/instruments/contracts/trading_calendars/
  trading_sessions 五表 SHARE ROW EXCLUSIVE 锁，再重核 baseline；短时阻塞这些表的 writer，不阻塞普通读取。
  提交前异常回滚，提交后保留已插入事实，重新规划。不能误称其内部持有全局 maintenance advisory lease。
- Canonical 发布仅按既有分区事务原子，不承诺整个合约或整个恢复任务全有全无。成功分区保留，不回滚其他成功批次。
- 文件写入/DB commit 结果不明时先只读核对 Catalog 指针、hash、既有 receipt 和物理对象，再请求新的执行意图。
- 不自动删除对象、回退 Catalog 指针或撤销 Session。确需修复已提交错误，提供精确目标、dry-run、回滚与恢复方案另批。
- 前后使用相同窗口及版本读回，成功后 replan 确认所批准缺口归零；“可重复规划”不等于允许自动重复 apply。
- 证据放在不会随 task worktree 清理丢失的经批准本地持久目录。完整 JSON 为唯一原始记录，摘要派生于同一文件；
  提交脱敏摘要和引用，不创建重复 manifest/receipt 体系，不暴露凭据。

## 验收与终态

每批验收自己的写入和缺口；最后只做一次全量 60×3 W1 审计，固定原截点，完整输出后离线生成摘要。
列出 READY、普通缺口、元数据不足、来源异常、完整性异常和 UNKNOWN，避免重复计算消费者依赖行。
普通队列完成与异常已归因分别计数；来源真实异常可算“调查闭环”，仍不算 DATA_READY。
没有全量审计终态或存在未判定异常时整个数据任务保持 PARTIAL；因真实下载错误/自然任务窗口停止也不宣布全部补齐。
代码/测试/Review、数据写入、全量验收、发布与 Runtime 是独立状态，后两项不在本任务范围。

## 一个开发任务的交付边界

设计为现有架构内的有界恢复，不新增调度平台、resume 数据库、任意元数据编辑器或重复 resolver。
一个新 Sol high 任务从最新 develop 隔离开发，接收本版设计、实施计划和持久证据；先对照已完成项再处理
剩余工作，不 cherry-pick 旧 parent 全部历史，不从正在变动的 primary 导入长时执行源码。
只在复现根因后修改对应现有模块并补失败测试；如缺少安全的精确修复入口，可先形成最小设计和隔离实现，
不能以广域 synchronize/update/refresh 替代有界方案。任何改变源事实接受政策或策略语义的新决策须另审。

本轮明确开发意图可支持范围内实现、验证、独立 Review 与合入 develop；不会转为发布许可。
下载免额度估算的偏好随任务保留，但已消费、失败或跨会话的受控操作意图不随文档转移；新任务先完成
不依赖写入的工程与只读工作，再向 owner 汇总精确写入批次，不把旧 snapshot/hash 当作许可。生产 DB/Canonical
apply、结果不明后的继续仍按当前 AGENTS 的单次意图合同处理；不得据此让无关安全工作停摆。
真实页面验收使用隔离候选和空闲端口、固定 as_of，仅消费数据；不停止现有服务、不切 Runtime、不发送通知。
