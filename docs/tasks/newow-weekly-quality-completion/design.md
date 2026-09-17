# 牛哇周线质量分段与 60 品种补全设计

日期：2026-09-17。主体代码核对基线：`develop@3aa21367ec80c642fd2eff12e310f3075ff917a8`；
交付前刷新至 `e07fd58473471e2479229f58a0b2e7b5ce3a925f`，新增发布版本与状态记录，周线规则未变。

Owner 已认可本会话上一轮方案，并要求细化后交给一个 Sol medium 会话按顺序实施。本文件与
[实施计划](implementation-plan.md) 是该连续任务的输入；设计通过不等于数据、页面或发布验收通过。
实施会话开始时必须刷新仓库、共享数据与任务冲突事实，不把本文件中的历史数字当当前余额。

## 1. 目标、范围与授权

目标：使 operational 60 品种的牛哇趋势、震荡、主升浪 W1 在声明的窗口内拥有可信行情输入、
正确的预热和质量中断状态、可复算的区段参考交易，以及可靠的自然首次加载页面。
有效数据与样本充足的当前策略应 READY；真实缺价、未完成周、合法短生命周期、预热不足必须准确展示。
不能把 180 个组合全部强制标 READY 作为任务出口。

当前已授权连续进行：只读取证、原生盘点、代码与必要局部重构、对应 canonical/版本调整、隔离测试、
只读候选预览、独立 Review、普通 commit/push 和满足条件的 develop 集成。不重复申请本设计的实施批准。
范围为 W1 三策略主图、副图、ReferenceTrade、ReferencePerformance、独立比较器及 D1 回归。
完整跨周期 explanation、60m 产品开放、新公式/评分、因果回测、账户、订单、通知不属于本任务。

真实 RQData 请求/下载、Canonical/Catalog 或其他生产写入须先形成精确批次并取得本任务的对应授权。
main/tag/Release、Runtime promotion 与自然服务开关亦未获本轮授权。执行会话必须先完成可独立推进的
工程、测试和精确 prepare，再就所缺的生产动作请求批准；不能仅因未来存在数据 Gate 而停止工程。
沿用 AGENTS.md 的批次授权、已有授权核对和失败恢复规则，不复用已消费的历史日线/周线批准。

## 2. 当前证据与日线经验

| 当前已核对事实 | 证据 | 本轮约束 |
| --- | --- | --- |
| 正式 Release 已更新为 v1.10.13，Runtime 仍为 v1.10.12；W1/60m 均未开放 | STATUS.md 的当前身份与 v1.10.13 条目 | 执行从最新 develop 开始；不能把 Release 当本版 Runtime |
| v1.10.12 只开放 D1；固定截止日线首次加载 180/180 | STATUS.md；output/playwright/release-v1.10.12-merged/manifest.json | 保留 D1；W1 数据审计不得被 UNOPENED 冒充完成 |
| 9 月 17 日 PT2612/SS2611 又完成限定 D1 补齐；日线矩阵与局部首载另有证据 | outputs/market-home-quality-20260917/CLOSEOUT.md | 刷新数据基线；不把局部复验写成再次全量浏览器验收；不重做旧批次 |
| 旧 W1 全域报告仅 8 品种输入齐全，旧 matrix 曾有 27/180 联合 READY，但预算耗尽 | outputs/newow-period-audit-20260915-0813/；outputs/newow-weekly-recovery-attempts/weekly-matrix-acceptance-20260915-002/ | 都是历史参考；不能恢复旧补数队列或据此报告当前完成率 |
| 日线 reader 的质量读取、core 的 calculation segment 都显式限 D1 | product_reader.py；product_adapters.py::label_calculation_segments | 必须贯通 W1 质量合同，不能只改 capability |
| W1 来自同一交易所日行情完整 ISO 周；遇缺价日聚合失败 | docs/DATA_CENTER.md；rqdata_adapter.py::_weekly_bars | 缺价周不生成有效周 Bar；扩展的是显式中断合同 |
| 普通维护审计 60/60 与首页长前缀缺口曾同时存在 | docs/tasks/first-five-hardening/integration.md | 按实际消费者窗口枚举，包括主力前预热，不能只看映射日或 row_count |
| D1 缺价后曾因未返回已标记输入而丢失 replay；窗口间 owner proof 曾冲突 | commits 648826548、0afdf1144 | W1 同时验证区段标签传递和跨 section 稳定证明 |
| 部分恢复出现 stdout/终态证据问题，短写需单独处理 | docs/tasks/newow-daily-data-recovery/final-three-recovery.md | 来源、typed 原始结果、可靠终态和读回各有用途，不能用 shell 成功代替业务结算 |

以上是已经核对的设计依据，实施前仍需检查相关修复在新基线的存在与行为。旧任务文档内的单次流程、
固定机器/端口、旧频率开放顺序和审批条款不覆盖当前 AGENTS.md、本轮目标与当前 STATUS.md。

## 3. 方案选择

采用：完整周严格聚合，已证明缺价周形成计算中断，后续有效完整周重新预热。

另一可行方案是只开放全历史严格完整品种。它工程较少，但历史真实缺价会长期阻止品种恢复，
不能达到与日线一致的有效区段可用目标。Owner 已接受采用前一方案。
不采用删缺价日、缩短历史窗口、用日线状态冒充周线或直接放开 W1 开关的方法。

正常 W1 仍从 Canonical 读取；质量 reader 不在查询时临时聚合一套替代周线。不新增缺口数据库、
手工品种白名单或平行恢复框架。新增能力应收敛在既有覆盖、来源、维护、MDS 和 Newow 入口。

## 4. 周线时间、身份与覆盖合同

### 4.1 冻结时间与消费窗口

- 冻结一个带时区 `as_of`，由现有 Calendar/Session/coverage authority 解析各品种最后完成交易日和 W1 端点。
- 全部使用同一观察时刻；若不同交易所完成端点不同，逐品种记录，不自行造统一周五端点。
- 数据盘点使用 W1 实际需要的周截止及物理前缀；D1 回归截止独立记录，不能声称两个频率同一 bar_end。
- chart/auxiliary 采用当前默认展示窗口；reference 采用现有独立统计窗口；comparator 通过真实 service
  证明其 owner/prefix 与已枚举依赖的覆盖关系。分页、旧窗口、代表性自定义窗口另列承诺范围。
- 未完成本周不参与正式 W1 指标、Action、Trade 或收益；使用已有“最近完整区间”显式动作，不能静默缩窗。
- 冻结代码、scope 内容及 hash、窗口配置、数据/配置非秘密身份；记录每个实际读取的 Catalog revision/hash。
  不把同一 as_of 或数据库只读事务冒充整个 Parquet 数据湖的原子快照。遇数据漂移保留结果并阻止一致性结论。

### 4.2 周期归属与合约

- 通过现有完整 ISO 周算法取得预期交易日；节假日短周只要求权威日历中的应有交易日。
- actual_dominant W1 使用该完整周最后交易日 rank1 的物理合约及该合约整周来源，不拼接每日不同 owner。
- 非 rank1 日期可以作为同合约周内来源与预热，不因此进入 actual_dominant D1 的正式映射结果。
- 上市/到期、短 owner 和跨月周均按 lifecycle/Calendar 决定。合法零 W1 Bar owner 是 NOT_APPLICABLE，
  仍保留 owner 边界；不得构造周 Bar、漏掉换月中断或把该 owner 算数据 READY。
- 每个合约只在本次实际需要的最大 through 读取一次完整前缀，其他 owner 使用已验证前缀切片，避免重复重放。

### 4.3 三种核心数据分类

| 分类 | 证明条件 | 读取/维护结果 |
| --- | --- | --- |
| 正常完整周 | 全部应有 D1 端点存在，身份/唯一性/来源和原有价格规则通过 | 正常 Canonical W1；所有数值使用 Decimal |
| 已证实缺价周 | 确切 D1 PRICE_UNAVAILABLE 证据存在，且该周全部应有 D1 端点均由正常 Bar 或合法质量事实解释 | 无有效 W1 Bar；产生可重建的周线中断证明；不能计成正常完整周 |
| 未证实缺口/错误 | 尚有未解释缺日，或错合约、重复、损坏、缺元数据、其他来源异常 | 保留原始缺数/完整性/来源分类；不得仅因同周另有已知缺价就整周豁免 |

用集合不变量表达质量覆盖：应有端点 = 正常事实端点与已证明质量端点的互斥并集。
所有端点必须有且仅有一个合法解释；不能用首尾日期相同、根数相等或质量记录存在代替逐端点验证。

## 5. W1 质量证明的最小设计

保持 `PriceUnavailableFact` 为原始物理 D1 事实，不把周线中断伪装成一条带假价格的 D1 记录。
在既有 market_data 层增加一个有界纯转换，统一供 planner/readback/MDS 使用；必要时放入
`app/market_data/weekly_quality.py`，不再分别实现三套按周分类算法。

周中断值对象的职责字段为：product、physical_contract、ISO 周及周完成端点、预期 D1 端点集合、
已验证缺价日期和其来源 request/response hash、所读 D1 revision/内容证明、分类算法版本。
它不含替代 OHLC，不自称 RQData 的原始周线记录。正常周和中断周不能占用同一有效端点。

默认从已有 D1 正常/质量分区确定性重建周中断；不新增生产表或独立手工状态。若既有 Catalog/存储
必须增加最小版本化元信息以绑定依赖，先证明现有字段不足再修改对应 canonical；生产 migration 独立 Gate。
任何缓存或附属证明都必须可删除重建，并在上游 D1 revision、质量事实或算法版本变化后失效。

维护、写入验证与查询保持一致：

1. planner 同时检查目标 W1 和整周 D1 companion，预先区分正常待补周与已证明不能生成 Bar 的周。
2. 已证明缺价周不反复进入普通 W1 下载队列，但 retained classification 中仍明确未形成正常价格。
3. 月分区可以保存正常周的真实 Bar；真实 row_count 只数已存 Bar，不用缺价数量补大。
4. 允许省略某个 W1 端点的依据必须是上述完整质量证明；没有证明的漏周继续失败。
5. strict MDS 跨缺价周仍失败；Newow 专用 quality 路径同时返回正常周与中断，不放宽普通消费者。
6. 已有 W1 与当前 D1 来源数值/质量不一致时明确报冲突，不能拿旧 W1 当当前正常结果，也不能自动覆盖。
7. 同一重规划再次读取相同 revisions 必须得到相同目标与分类，重启后结果一致。

不新增“只靠本地 D1 就随手重建周线”的快捷 writer。现有周线 warm-up 的同源 refresh 范围保持显式；
若要减少 provider 请求，必须由既有 planner/来源一致性证明支持，不能将本任务扩大为数据重建架构改造。

## 6. NO_TRADE 与混合零价周

严格 NO_TRADE 继续要求 O/H/L/C=0、volume=0、turnover=0。它暂停有效观察，不推进指标预热或策略状态。
PRICE_UNAVAILABLE 是存在交易但无法确定价格的质量中断，不能归为 NO_TRADE。

现有 `_aggregate_daily_rows` 直接取 daily low 的最小值，混合严格 NO_TRADE 与有效交易日时可能产生
部分零价 W1。这是需要样本与回归确认的风险，不是本文件已证明的当前生产异常数量。

本次允许的默认行为：保持既有来源与聚合数值口径；严格整周 NO_TRADE 可按现有规则暂停；混合周若
产生不满足正常/严格 NO_TRADE 条件的结果，保留来源异常并阻断受影响组合，不能删零值后生成正常周。
从混合周中排除 NO_TRADE 日后改变 OHLC 的算法不在已批准规则内：只有实际出现并证明影响后，提交
具体真实样本、前后数值及波及消费者供 owner 决定。其余正常与已证明缺价分段工作继续。

## 7. 策略、参考交易与版本

- 扩展 `label_calculation_segments`、reader、readiness 等 D1-only 限定时必须逐个识别，不全局替换频率字符串。
- 每个质量中断只作用于对应 physical contract 和 owner 的计算前缀；成为主力前的同合约缺价也会影响预热。
  其他 owner/合约的异常不能污染当前完好段；多个缺价日落在同周只形成一个稳定周中断。
- W1 中断的策略生效时点为该周权威完成端点；完成前不能向历史正式 W1 重放注入未来事实。
  原 D1 缺价日期作为诊断保留；observed_at 仍是来源采集时间，不伪造历史当时已知证据。
- completed W1、strict-before、prefix invariance 必须保持；历史重算属于 page-parity，不能冒充 causal evidence。
- 后续完整有效周从新 calculation segment 重新预热所有指标及三策略状态。有效周计数不能用日数代替。
- 无可验证 BUILD 的初始 HOLD 不造 OPEN；初始无入场 CLEAR 继续使用已批准资格，不放宽任意孤立 CLEAR。
- 断点前 CLOSED 保留；断点时 OPEN 转 DATA_INTERRUPTED，entry 保留、exit/已完成收益为空。
  后段 CLEAR 不能与前段 BUILD 配对；中断记录不计入 CLOSED 收益、胜率或完整持有期统计。
- 图表、分页、参考历史定位必须使用带 calculation segment 标签的同一 replay 输出，防止重现 D1 丢标签问题。
- 当前可以 READY 而历史仍 PARTIAL；最新完成周是缺价或恢复预热不足时，不得返回断点前旧 Frame 作为当前 READY。
- 本次需版本化的是 W1 质量输入、区段适配、依赖证明以及受影响的参考/API 合同。不得覆盖已有 D1 版本，
  不因复用共享常量无意重命名所有 D1 Trade ID；若确需改变 D1 身份属于另一个需说明的业务影响。
  三策略公式、参数、参考价、费用/收益口径不改变。

## 8. 快照、页面与开放范围

主图与 reference、auxiliary、comparator 在同一请求身份、as_of 和 snapshot token 下读取。
输入内容 hash 可以随真实窗口不同，但交集上的同一 Bar/质量证明必须一致；owner 证明不借用另一个
section 才可见的 owner 起点。缓存键包含频率、公式/适配版本、窗口、owner/质量依赖和修订证明。

最终候选开放 D1/W1 的 chart、auxiliary、reference、comparator；60m 和完整跨周期 explanation 保持
UNOPENED。正式 Runtime 当前的 D1-only capability 在获得发布/切换授权前不动。
工程验收使用隔离只读候选：先证明周线 data/read/service，再启用候选 W1 capability 进行产品矩阵，
不让正式 UNOPENED 掩盖未运行，也不绕过路由安全校验伪造线上通过。

页面必须区分：正常可用、空仓/无参考交易、预热、数据中断、历史 PARTIAL、未完成周、真实错误。
合理状态显示通过不等于 READY；空参考收益不是 0% 盈利，缺价不是交易所休市。
历史跳转、图表缩放不改变统计范围或 Trade ID，趋势/震荡/主升浪切换必须替换互斥图层。
同时检查 D1/W1 切换、深链接、周期偏好、generation/Abort、旧响应污染、弹窗重开和动作键盘定位。

## 9. 顺序、资源与数据批次

阶段顺序：P0 基线与只读盘点 → P1 周线质量合同/覆盖 → P2 reader/策略/参考交易 →
P3 代表样本 API/页面 → P4 精确数据批次与读回 → P5 全量验收、集成与候选 → P6 外部交付 Gate。

初始盘点仅 `frequency=1w`、dependency-only，因产品 W1 当前关闭。全 60 品种串行、有界，
每品种原生 max_work=10000、timeout=300 秒作为起始上限；总串行 deadline 60 分钟，超出时明确未执行项。
该数值是上限，不是要求消耗；实际先以已保存的小样本耗时检查可行性。不能启动无限重试、并发轰击 DB
或为了图表 180/180 而提高 HTTP 压力。实施发现预算不足可在保持 60 品种分母与显式记录的前提下，
调整后续只读执行安排；读取预算调整不是生产授权，也不自动续跑任何 provider/写入。

单品种报告写入后即时验证可解析、终态与退出结果一致；总清单引用每个原始报告及 hash。
若 campaign 目前只接受单原生报告，必须使用其支持的全域原生输出，或在现有入口增加严密的分片
输入校验；不能把拼装摘要冒充原生完整报告。audit_complete 与 input_ready 独立计算。

代表样本覆盖成熟历史、上市较短、跨月周、周中换主力、缺价前后、最新缺价或仍预热；由新审计选 5–8
品种，一品种可覆盖多种场景。没有对应真实样本时用隔离测试证明工程，现场项注明不适用/待证。
普通写入及来源取证全部串行，避开现有盘后/其他恢复任务；维护锁忙则保留具体状态，不抢锁或停正式进程。

数据授权包必须明确：目标工作站与 Catalog/Canonical 身份、exact code、scope/报告/hash、品种/合约、
D1+W1 周期依赖、完整 source 窗口、待补/refresh 端点、既存事实保护、预期分区与请求、测量依据与
provider 字节预算、总时限、异常隔离/重试边界、读回与恢复方式。无新数据测量前不许沿用旧额度数字。
优先使用现有 campaign prepare；不新造一套与原生 plan 不一致的目标表。

按正常成功、已证实隔离失败、已知停止失败、未尝试、未知结果闭合完整执行分母。
W1 partial-source-exception 只有当前代码、完整来源/journal、attempt/batch/unit 身份与当前 plan 全部
验证后才可沿用对应合同；旧 D1 回执不能改 schema 变成 W1 回执，旧 source capture 也不是新下载批准。
未知来源/身份漂移/读回失败/额度/结果不明按获批边界停受影响 mutation，保留成功分区，无默认回滚或重试。

## 10. 验收合同

| 验收层 | 必须证明 | 不能替代它的结果 |
| --- | --- | --- |
| 盘点 | 全 60、所有已声明 consumer/owner/window 有确定结果；未开始与预算耗尽为 incomplete | 报告有 60 个名字、旧报告 complete=true |
| 普通恢复 | 实际成功单元/分区与来源、Catalog、Parquet、MDS、replan 相符 | 命令 exit 0、只有 stdout、剩余普通目标为 0 |
| 质量覆盖 | 每周及对应 D1 端点精确解释；普通 gap 与已证实中断无混淆 | 质量事实存在、月 row_count 一致 |
| 计算 | 180 个 W1 组合的 READY/WARMING/中断等正确；无跨断点/合约配对 | 全部强制 READY 或只看 HTTP 200 |
| 页面 | 180 个 W1 首次加载状态正确；D1 180 个组合回归；代表性交互/移动页面通过 | fixture 通过、刷新后成功、只有主图 DOM |
| 候选 | 集成后的 exact commit、正确 scope、测试与独立 Review、实际候选 API/Web 一致 | 分支旧测试、release 身份或 Runtime 启动 |
| 自然接续 | 获授权版本的下一完整周形成、相关维护/换主力与消费者自然读回 | 固定历史截图、手工重跑定时任务 |

必须单列：完整正常历史品种；含明确中断但当前已恢复品种；当前预热/中断品种；普通缺口未完成品种；
其他来源/完整性阻断品种。产品跨维度可能重叠，须另给互斥汇总规则或注明交叉，不能重复相加。
READY 计数、页面状态正确计数、完整历史计数分别报告，并给完成/未完成品种名单和明确下一阻断。

## 11. 交付物与保留 Gate

本目录只保留这份设计与一份可更新的实施计划。实际执行使用一个明确 evidence 根，逐阶段索引原始
结果，复用现有 result/summary/manifest 格式；不重复生成多套 receipt、task contract 或 parallel report。
执行记录以本轮原始输出为准；STATUS.md 仅在实际完成相应 Gate 后更新，历史 evidence 不改写。

高风险的时间/来源/质量/配对变更必须独立 Review；普通文档变更做引用与 diff 检查即可。
一个 Sol medium 主会话负责串行主线，独立 reviewer 只审边界明确的 diff；不能把任务拆成互不衔接的新会话。
本轮设计交付后，执行者可直接开始 P0–P3/P4 prepare，继续所有不依赖生产授权的工作。
P4 apply、P6 发布/Runtime 分别保留明确外部授权。自然未发生的事件保持待验，不为完成任务手工触发。
