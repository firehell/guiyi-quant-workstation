# 牛哇周线与 60m 逐品种恢复、策略与页面验收方案

日期：2026-09-17。状态：设计提案，供 owner 审阅后交 Cursor Grok 4.6 High 执行。
本轮仅核对代码、合同、历史回执并编写方案；没有新一轮全品种数据库审计、RQData 请求、正式数据写入、产品开放或发布。

## 1. 结论和推荐范围

可以同步推进 W1 和 60m。推荐组织方式是：**同一品种一起盘点，W1 和 60m 分别计划、串行写入、分别验收，D1 做回归基准。**

比较三种安排：

| 安排 | 收益与代价 | 选择 |
| --- | --- | --- |
| 每品种先 W1、再 60m，再核对 D1 | 上下文集中，能复用身份、页面与旧证据；一个周期阻塞时保留另一个的进度 | 推荐 |
| 全 60 品种先做完 W1，再开始 60m | 单周期容易组织，但迟迟发现不了分钟链问题，需要重新进入每个品种 | 作为额度不足时的后备安排 |
| 两个周期、多品种同时真实补数 | 共享锁、Canonical/Catalog、资源预算和失败收尾相互影响 | 不采用 |

本次目标是既有趋势、震荡、主升浪的行情输入、主图、副图、参考交易、既有 comparator 和页面正确显示。
不改变策略公式、建仓清仓规则和收益模型；跨周期综合解释继续单列，不随 W1/60m 数据准备自动开放。
页面参考交易继续 page_parity=true、executable=false，不引入模拟成交、账户或策略通知。

W1 先达到候选条件就可单独准备发布，不必等待全部 60m 完成。正式开放、main/tag/release、Runtime promotion
仍按 AGENTS.md 和当时 STATUS.md 的独立授权执行；逐品种验收不是逐品种擅改正式 Scope。

## 2. 本轮已经核实的事实

检查起点为 develop@3aa21367ec80c642fd2eff12e310f3075ff917a8；有用户暂存文件及大量未跟踪 evidence。
其他工作树包括 alert-live-prefix、newow-w1-partial-source-exception、release-v1.10.13，必须在开工时重新核对。
本方案不改动它们，也不把该 HEAD 固定成未来执行版本。

交付前其他任务将 develop 推进至 7694df45779584b9551404bca39d0b757e70cc78：正式 Release 记录为
v1.10.13@39e463f8d，Runtime 仍 v1.10.12；新增
[周线质量设计](../../tasks/newow-weekly-quality-completion/design.md) 和
[周线实施计划](../../tasks/newow-weekly-quality-completion/implementation-plan.md)。两文档记录 owner 已认可周线分段方向，
并计划交独立 Sol medium 任务实施。本方案复用其 W1 业务合同，补充 60m、Grok 逐品种执行及跨任务协调；
不替换那份已认可设计、不取消既有任务、不再要求重复批准同一周线设计。
执行前核对该 W1 任务是否已经开始：如正在修改共享模块，Grok 先做独立只读核对，待共同依赖完成验收后复用，
不得同时让两个任务修改 reader、planner、recovery 或 capability。具体当前执行分工以 owner 最新安排为准。

| 证据 | 本轮核实的含义 |
| --- | --- |
| STATUS.md | 交付时正式 Release 为 v1.10.13，Runtime 仍 v1.10.12；D1 的 180/180 首载来自 v1.10.12 固定截点，W1/60m 关闭，Runtime 自然业务 Gate 未通过 |
| outputs/market-home-quality-20260917/CLOSEOUT.md | 更新后的 D1 候选首页 60/60；三策略 chart/reference 综合 360/360，来自同轮完整基线加五品种复验；仅 PT/SS 六页本轮重新首载，不冒充全 60 品种重新逐页验收 |
| product_release.py、test_candidate_preview.py | 正式 capability 和当前 preview 都是 D1-only，不能拿 public UNOPENED 当物理缺数据 |
| product_reader.py | PRICE_UNAVAILABLE 的质量读取和物理前缀分段入口明确限定 DAILY，W1/60m 没有自动继承 |
| newow_weekly_recovery.py、campaign.py | 当前 recovery profile 仅支持 1w/1d；native contract-warmup 支持显式 60m，但不等于当前总包编排支持 60m |
| 旧 60m 回执 | 代码身份为 0ae5fce776d9eefc193dd10aaacfa849ad057e73；该版本确实有 W1/60m profile，不能直接与当前 W1/D1 编排混用 |
| hourly-six-20260915-rest2-001/campaign-result.json | 当次 101 单元：9 成功、1 已知停止失败、91 未尝试；AO2403 报 ATOMIC_PUBLISH_FAILED。此前两个 campaign 为 unknown；以上只是历史回执，不是当前剩余缺口 |
| 周线旧工作树 | 0f58680fe 不是当前 HEAD 的祖先；但 partial-source 实现提交 6b6f99406 已包含于 HEAD。应比较剩余差异，不能称整个修复未合入，也不能盲合旧分支 |

当前合同以 docs/DATA_CENTER.md 为准：**W1 来自同一物理合约的完整交易所 D1 聚合**，不是旧长指引中所称的直接 RQData 1w。
60m 仍为 RQData 1m → Canonical 1m → 同合约、正式 Session 聚合 → Canonical 60m → Catalog/MDS。

## 3. 日线踩坑怎样转成这次的检查

| 踩坑或误判 | 这次必须落实的控制 |
| --- | --- |
| 页面已有几百根 K 线，实际物理合约预热前缀不完整 | 同时枚举主图、副图、独立 reference 统计窗口、每个所涉合约 lifecycle prefix；不只补可见 K 线或主力期间 |
| 旧 43/60、180/180 等名单被当成实时状态 | 每份结果绑定代码、as_of、输入身份和实际范围；旧名单只帮助排序，不能过滤当前原生缺口 |
| 首页正常、策略 READY、浏览器通过混成一个指标 | 分别记录报价、输入、三个策略的 section、真实首次加载；分母不互换 |
| PRICE_UNAVAILABLE 被当普通缺失反复下载 | 保留权威缺价事实，不造 OHLC；D1 分段恢复经验需经过 W1 专项合同设计才能扩展 |
| 零成交、缺价、损坏数据混在一起 | 严格 NO_TRADE 不推进有效观测计数；已验证 PRICE_UNAVAILABLE 是中断；未知零价、部分零价、身份冲突仍失败 |
| 数据中断前的 OPEN 跨断点继续配对 | DATA_INTERRUPTED 保留原 entry，不能伪造 exit/收益；恢复后重做预热，不能借旧 HOLD 制造新 OPEN |
| 先出现 CLEAR 就补造一笔入场交易 | INITIAL_CLEAR_NO_ENTRY 是合法无入场清仓，零交易或样本不足不代表页面错误 |
| 只确认首尾存在、行数差不多 | 用 Calendar/Session 的 expected endpoints 检查完整集合、重复、额外端点、排序与文件 hash；同一来源响应禁止重复覆盖 |
| 配置退回仓库 .env 导致几乎全品种完整性失败 | 通过既有配置加载器绑定 config/Canonical identity；不打印凭据；与当前工作站身份不符立即停止推断 |
| 收盘端点被排除、当周未完成 Bar 被纳入、夜盘请求错日期 | 明确 as_of、排他上界、completed period 和 trading_day，使用现有时间 authority；不以本机日历时间猜测 |
| complete=true 或退出 0 被当成验收通过 | 检查所有状态和分母，budget_exhausted=false，JSON 非空且可解析；UNOPENED/WARMING/NOT_APPLICABLE 单列 |
| 少数分区成功就称整个批次完成 | 保存单元/分区回执；独立进程 replan/readback；已提交、失败、未尝试、未知分别闭合 |
| 前端刷新第二次才正常仍称首载通过 | 新浏览器上下文第一次自然加载就验收，记录请求失败、耗时及截图；不靠 retry/刷新/预热造绿 |
| 60m 少多少根直接换算下载量 | 真实计划枚举 1m 基础与 60m 派生目标；资源以 provider 用量与原生计划估算，不乘固定 60 |

## 4. 公共前置工作：先做一次，之后复用

### P0：基线和旧事故只读核对

1. 重读 AGENTS.md、STATUS.md、DATA_CENTER.md、相关 Newow canonical；记录 branch/HEAD/worktree/dirty 和现役身份。
2. 从最新 develop 建立确需隔离的任务工作树，避开现有 recovery/release/Alert 任务；不得在旧 Runtime 中开发。
3. 对旧 W1 partial-source 工作树做精确 diff/patch 对照：复用已经合入的实现，剩余有效修复必须在当前合同上测试。
4. 核对旧六品种 60m 的所有已开始单元、原生 journal、Catalog active pointer、Canonical hash、MDS 读取和当前 replan。
   重点查 AO2403 原子发布失败；历史 unknown 不凭后续某次成功自动清账。
5. 对结果不明的单元先读回，不发新 provider 请求，不重跑旧 campaign。范围内既有分区应由当前 planner 自然识别；
   不能删除成功记录，也不能按旧成功列表强行排除新缺口。

P0 出口：明确哪些问题仅是旧包装回执不足、哪些有已提交分区、哪些是仍存在的共享发布错误。
未定位且可能影响所有品种的原子发布错误，会阻塞全部新的 60m 写入；只读审计、W1 分析仍可继续。
若已证明仅涉及一个历史对象，应精确隔离该对象，其余操作仍须落在新授权范围内。

### P1：恢复入口具备当前版本的 60m 合同

先做离线工程核对，不接 provider。当前单合约 native contract-warmup 已存在，优先复用。
若逐品种执行所需的记录、预算和终态能由现有 native 命令覆盖，允许先以单合约方式完成试点；
不要为了批量编排推迟可验证的最小闭环。

需要恢复编排时，在现有 scripts/newow_weekly_recovery.py / campaign.py 内补齐明确的 60m profile，
复用旧实现中经过验证的部分，不整份回退旧脚本、不创建另一套 publisher 或缺口算法。
实现后文档说明脚本历史命名即可，不为命名做大规模重构。

必须一次覆盖：parser → native plan → manifest/hash → execution digest → apply → exception → readback → terminal result。

- 1d profile 只允许 [1d]；1w profile 只允许 [1d,1w]；60m profile 只允许 [1m,60m]。
- 三种 profile 的 schema、plan hash、invocation、旧结果导入和验证不能跨频冒用。
- 60m 默认无来源异常继续策略、无自动 retry；W1/D1 的零提交隔离和 W1 partial receipt 不能套用。
- prepare 不初始化 provider；apply 在既有维护锁内重算；任意频率或执行代码身份漂移拒绝。
- 若支持多个单元，成功后可自动推进同一个已批准总包；首次来源、锁、预算、提交、读回或结果未知错误停受影响执行。
- 失败必须产出可解析且脱敏的 terminal；回执保存失败本身不能被报告为成功。

独立 Review 聚焦跨频 identity、分钟日期窗口、部分提交、恢复幂等和来源归属；不是再要一份泛化架构文档。

### P2：W1 质量中断和候选验收入口

W1 普通有效数据路径可以先做；要复用 D1 的“历史缺价不拖垮后续有效段”，需明确一个小的合同扩展。
**该扩展已由上述周线专项设计明确。本段是执行摘要；复用专项实现与验证，未完成前受影响 W1 保持阻塞。**

建议语义：

1. 某个完整 ISO 周所需的物理 D1 有已验证 PRICE_UNAVAILABLE，不能生成或展示该周有效 W1 OHLC。
2. 由既有 D1 质量事实、同一 weekly owner 和 Calendar 映射计算周线中断；携带来源身份，不建立人工周线缺口表。
3. 在该周完成、且该源事实对当前 as_of 可见后，才成为 completed W1 的断点。禁止提前使用未来周内事实。
4. 断点切断对应合约的 W1 计算/参考交易段，包括成为 rank1 前所需的预热；后续只用完整、有效的 W1 重新预热。
5. 缺某日文件、未知来源、错合约、损坏 hash 不属于这个例外，仍 fail-closed。
6. 后续完整周恢复必须同时证明 weekly owner、同合约完整 D1 和独立统计前缀；不能简单过滤坏周后把两段接在一起。
7. 更新对应 Newow 输入适配身份和 canonical；保留公式版本，除非业务公式本身改变。参考模型版本是否变化按合同差异决定。
8. D1 已合法跳过的 NO_TRADE 不等于允许 W1 聚合任意缺失日；周线聚合继续遵守完整同源合同。

按周线专项设计，缺价周也必须满足逐端点证明：正常 D1 与合法质量端点互斥，其并集恰好等于全周应有端点。
同周还有未知缺日时不能整周豁免。保持正常 W1 从 Canonical 读取，不在查询时用 D1 临时聚合替代 Bar。
当前状态 READY 与历史统计 PARTIAL 分别表示；最新完成周缺价或新段未完成预热时，不能显示断点前的旧 READY。
reader、core 的 label_calculation_segments、replay 返回值、历史定位和 reference 必须传递同一 calculation segment 标签；
W1 专属版本不得无意更改已发布 D1 Trade ID。混合 NO_TRADE/有效日导致部分零价周时，先按现有异常规则阻断，
改变周 OHLC 的聚合算法需要具体样本和独立业务决定，不能由 Grok 自行删除零值。

60m 的质量事实必须由 1m 链独立验证。不能把 D1 缺价回执推导成 1m 同样缺价，也不能用正常 D1 证明分钟完整。
如分钟源出现现有合同不覆盖的价格异常，本期先停止并报告，不新增“分钟也按日线规则归一化”的捷径。

当前 public API 和 app.preview 都受 D1-only capability 约束。复用周线专项的隔离候选能力方案和 app.preview：
先在候选工作树按正式代码路径声明 W1，完成工程验证后再明确增加候选 60m 范围及其拒绝/接收测试。
候选 capability、schema、前端解析和实际 service 一致，API identity 公开 code/as_of；当前任务只验收指定品种。
正式 Runtime 的 D1-only 代码、配置不变。不能在正式运行副本改 OPEN_FREQUENCIES，不能删除 guard、
monkeypatch 或模拟 HTTP 成功造验收；不另建生产品种白名单系统、迁移表或新的 preview 框架。

在候选入口未完成前，只能宣称未开放周期的数据依赖结果，不可宣称真实 W1/60m 页面 READY。
验收汇总脚本可以显式接收 symbol/frequency/as_of 并复用当前查询；旧 weekly_acceptance.py 的 PT/固定截点逻辑
不能只换文件名就当成所有品种验收器。保留原回归样本，新增单品种检验功能及负例。

### P3：先验证正常样本和反例

- AU、PD：历史审计曾显示三个周期输入齐备，适合优先只读验证普通流程；现在仍必须刷新状态。
- PT：INITIAL_CLEAR_NO_ENTRY、短历史、WARMING、NO_TRADE/零交易展示；新补 D1 不能推定 W1 也更新。
- EB/BZ/PG：作为提前的已知缺价反例，检查不会补造周线、不跨断点计算、日线仍正常。
- EC：跨月 ISO 周源窗口不能从月初截断，复验历史 2026-03-30 到 04 月上下文问题。
- AO2403：旧 ATOMIC_PUBLISH_FAILED 只读收尾与离线故障测试。
- AG：夜盘、跨自然日/月和较长 Session 的 60m 端点。

这些反例检查不是提前执行其全部恢复，也不新增写入授权。公共修复与对应测试通过后冻结候选版本，再进入逐品种队列。

## 5. 每一个品种固定走这七步

### S1. 冻结当前品种身份

指定一个 operational symbol；固定带时区 as_of、代码 SHA、配置/Canonical identity 和 scope hash。
业务 cutoff 由实际 Calendar/Session 算出，W1、D1、60m 各自只读已完成周期。
每品种内部 audit、apply 后复验、三策略和页面使用相同 cutoff；不同日期处理的品种可各有 cutoff，
但最终全品种发布验收需要再用一个共同 cutoff，不能汇总异日证据当同版同截点矩阵。

### S2. 一次发现完整依赖，三周期各留结果

调用原生 readiness 检查 W1/60m，加 D1 基准；先 dependency-only，以完整 JSON 保存。
下例是已存在的只读 CLI 模板，执行者必须填本轮真实值，不能原样执行占位符：

```text
PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/guiyi data newow-readiness \
  --symbol <小写品种> --frequency 1w --frequency 60m --frequency 1d \
  --as-of <固定带时区时间> --max-work 10000 --timeout-seconds 300
```

若一个品种仍耗尽预算，可按频率有界执行后组合，但每个原生报告需完整，不能删异常、缩窗、漏合约后称完成。
逐项明确 display/performance/warmup 窗口，不能把截图窗口硬设成全部需求，也不能自行扩大至全部上市合约。
相同 physical contract 和 source frequency 的需求按原生合并规则去重，保留 consumer provenance。

分类至少区分：已就绪、普通缺失、仅派生缺失、metadata 不足、来源异常、完整性异常、正常 WARMING/NOT_APPLICABLE、未知/未启动。
不是每一种分类都能进入补数。public matrix 的 UNOPENED 另列，不改变 dependency 原因。

### S3. W1 原生计划和执行

对确实需要修复的合约生成显式 frequency=1w 的原生 contract-warmup 计划。
将所需 1d + 1w、跨月周两侧日线刷新、每月分区、精确端点、requested/effective through 一起列出。
W1 planner 当前可能要求 D1 refresh context，因此不能承诺“周线只本地聚合、绝不请求日线”。
只复用通过当前 source/identity 校验的已有事实，不用跨频 fallback 替代已声明的同源流程。

合并对同一 D1 依赖的重复目标；不能再叠加一个单独 D1 全生命周期恢复包重复执行。
如预计会改变已验收 D1 的事实值、质量分类或正式消费者行为，先列差异/影响并确认在授权范围内。
数据量、source response 和执行身份符合批准包后，一次一个合约执行并保存原生回执。

### S4. 60m 原生计划和执行

显式 frequency=60m：先检查同合约 1m 完整性，再补缺/派生 60m。禁止省略频率落入默认七周期。
分钟请求使用 Calendar/Session 所属交易日；60m 桶边界、休市和末段规则按既有聚合器，不能直接 pandas.resample('60min')。
source identity、order_book_id、重复端点、OHLC、量额与 open_interest 都纳入验证；Decimal 聚合使用项目确定的精度规则。

资源预算在 S2/S3 后形成精确包：请求数、源行数、磁盘预估、provider 实际可用额度、为自然维护预留额度和最长执行窗口。
旧任务的 1GB/100MB 额度只作历史参考，需核对当前 owner 约束和实际 quota，不能沿用成无限授权。
试点先一个最小合约单元，根据真实 quota delta 与耗时估计后续，不以 Parquet 文件体积冒充 provider 用量。

默认一个 worker、一个完整合约单元。大品种可在同品种内按已冻结的原生单元分多个连续批次；
不得为了变小擅改 contract-warmup 的生命周期合同或截短统计窗口。
若最小 native 单元超预算，先提交有界分包工具改进/新范围决定，不能拆成临时 SQL/Parquet 写入。

W1 与 60m 可以在一个 owner 批次批准中列两个精确子范围，但分别持有各自 plan/hash/receipt；
执行串行，第二项执行前重算验证，不能把 W1 hash 用于 60m，也不需对已批准正常子单元重复询问。

### S5. 独立数据读回

每个周期执行结束后由独立只读进程：

- 核对 receipt、Catalog active pointer、真实文件 hash、物理行数、MDS 身份和完整 endpoint 集合。
- 原生 replan：普通目标应归零；已知质量异常原分类保留，不能手动排除后写“零缺口”。
- 同 cutoff 重做该品种完整 consumer 依赖检查；旧成功和新增分区都纳入。
- W1 同时检查 D1 回归和完整周源身份，60m 同时检查 1m、60m 与源桶一致。

只读核对如果遇到自然维护造成的输入 revision 变化，报告不一致；不能把两个不同快照拼在同一条成功证据中。

### S6. 三策略和真实页面

每个品种至少有 W1 × 三策略、60m × 三策略共 6 个新验收组合，再加 D1 × 三策略 3 个回归组合。
每个组合都覆盖 chart、辅助指标、reference 和既有 comparator 的适用项；跨周期 explanation 保持关闭并显示原因。

检查具体值/关系，而不只检查 HTTP 200：

- 原生主图和实际合约 prefix 的 Bar/owner/周期/as_of 一致；hash/snapshot token 贯通相关 section。
- 趋势、震荡、主升浪遵守各自既有公式、warm-up、同 Bar 规则；没有因清洗输入改变公式参数。
- Marker 与 ReferenceTrade 身份配对；不跨物理合约、质量段或版本。合法初始 CLEAR/无交易保留，不伪造结果。
- OPEN/CLOSED/DATA_INTERRUPTED/ROLLOVER_INTERRUPTED 按适用事实显示；中断项不混入 CLOSED 收益。
- 第一行动、指标、参考卡片和图表对应同一响应身份；无可验证数值的项显示现有证据状态，不能补 0。
- 在真实只读候选 API/Web 的新 browser context 中首次直接进入每个组合；不先用 API 预热页面 cache。
- 首次图表/参考统计可见、无自动刷新才成功、无控制台及请求错误；记录首载耗时，沿用当前既有性能门槛。
- 首载之后检查周期切换、快速切换时旧响应失效、缩放/翻历史、Marker 点击、一次刷新复读的一致性；首载结果不被重试覆盖。
- W1 完整周/跨月/换主力，60m 午休/夜盘/未完成桶在 P3 做反例；逐品种再检查其真实边界样本。

不能把一次“正确显示不可用”统计成 READY。展示质量和数据可用性分开记录，允许明确的正常 WARMING、
NOT_APPLICABLE、EVIDENCE_REQUIRED 与已知中断，但“正常策略可用”计数仅来自真正符合 READY 合同的组合。

### S7. 单品种收尾和下一品种

只维护一份简短品种结论，链接原生 evidence，不再复制多套 manifest/report。
字段包括 symbol、code_sha、as_of、输入身份、W1/60m/D1 各结果、普通剩余目标、已知质量中断、三策略/页面计数、
provider 请求/额度变化、已提交/失败/未知、允许继续的范围和唯一下一步。

无阻塞则结束本品种，按队列换下一品种；不为同一品种生成三份策略任务。
一个周期阻塞时保留另一个的独立验收结果。来源特有问题可在结清当前提交状态后移到后置队列；
共享发布错误、环境不明或无法结清的提交结果阻塞受影响写入，不能简单“跳过继续”。
日线回归失败时暂停后续可能触碰同一 D1/W1 源的数据操作，先定位影响。

## 6. 60 个品种的建议操作顺序

以下是**建议队列，不是当前 READY 名单或精确下载量排序**。参考 2026-09-15 全周期审计、后续六品种回执、
日线异常经验和当前 operational 名单；本轮没有重跑全量 W1/60m 库审计。
前置只读检查发现真实资源或阻塞不同，可按明确原因调整队列，但必须保留完整 60 品种分母。

| 顺序 | 品种 | 安排原因 |
| --- | --- | --- |
| 1 | AU 黄金 | 正常对照，历史三周期输入齐备；先验证工具和候选入口 |
| 2 | PD 钯金 | 第二正常对照，兼顾较短产品历史 |
| 3 | PT 铂金 | 复用既有补齐成果，验证短历史、初始 CLEAR 和本轮 D1 补齐后的 W1 状态 |
| 4 | AP 苹果 | 既有六品种恢复，日盘路径，旧分钟范围较小 |
| 5 | A 豆一 | 复用已提交的分钟历史，再检查跨合约前缀 |
| 6 | AO 氧化铝 | 旧 AO2403 失败须先由 P0 查明，不能盲重试 |
| 7 | AG 白银 | 既有恢复成果、夜盘边界与长 Session |
| 8 | AL 铝 | 既有日周基础；分钟长历史用于验证大品种分包 |
| 9 | PL 瓶片 | 旧分钟依赖范围较小 |
| 10 | PS 多晶硅 | 较短历史，检验合法预热状态 |
| 11 | LC 碳酸锂 | 日盘和较小历史范围 |
| 12 | CJ 红枣 | 日盘普通补缺 |
| 13 | UR 尿素 | 旧分钟范围较小 |
| 14 | RB 螺纹钢 | 有既有分钟修复经验，重查当前映射与窗口 |
| 15 | M 豆粕 | 常规组 |
| 16 | I 铁矿石 | 常规组 |
| 17 | HC 热轧卷板 | 常规组 |
| 18 | CF 棉花 | 常规组 |
| 19 | SA 纯碱 | 常规组 |
| 20 | Y 豆油 | 常规组 |
| 21 | L 聚乙烯 | 常规组 |
| 22 | TA PTA | 常规组 |
| 23 | PP 聚丙烯 | 常规组 |
| 24 | FG 玻璃 | 常规组 |
| 25 | RU 天然橡胶 | 常规组 |
| 26 | P 棕榈油 | 常规组 |
| 27 | EG 乙二醇 | 常规组，重新检查日线旧问题是否影响周线 |
| 28 | V PVC | 常规组 |
| 29 | J 焦炭 | 常规组，Session 与物理合约独立验证 |
| 30 | JM 焦煤 | 单列既有物理历史问题；15m 旧缺口不直接推定为 60m 结果 |
| 31 | SH 烧碱 | 常规组 |
| 32 | MA 甲醇 | 常规组 |
| 33 | OI 菜籽油 | 常规组 |
| 34 | RM 菜粕 | 常规组 |
| 35 | PX 对二甲苯 | 常规组 |
| 36 | SR 白糖 | 常规组 |
| 37 | PK 花生 | 常规组 |
| 38 | EC 集运欧线 | 跨月 ISO 周上下文重点，前置已做反例 |
| 39 | LH 生猪 | 较大统计历史 |
| 40 | PR 丙烯 | 较大待验证依赖 |
| 41 | SM 锰硅 | 日线旧验收问题已知，需要本周期重验 |
| 42 | C 玉米 | 较长分钟历史 |
| 43 | SF 硅铁 | 较长分钟历史 |
| 44 | FU 燃料油 | 较长分钟历史 |
| 45 | JD 鸡蛋 | 较长分钟历史 |
| 46 | BU 沥青 | 大历史组 |
| 47 | NI 镍 | 大历史组 |
| 48 | PB 铅 | 大历史组 |
| 49 | CU 铜 | 大历史组 |
| 50 | ZN 锌 | 大历史组 |
| 51 | SN 锡 | 大历史组 |
| 52 | SS 不锈钢 | 大历史组；近期补的是 D1，不冒充 W1/60m 已补 |
| 53 | SC 原油 | 旧分钟依赖最大的一组，资源估算与分包成熟后执行 |
| 54 | B 豆二 | 已知历史零 OHL/来源异常，逐合约分类 |
| 55 | BZ 纯苯 | 缺分区与已知缺价同时存在，不能混修 |
| 56 | EB 苯乙烯 | W1 缺价周/断点传播重点 |
| 57 | PG 液化石油气 | 长前缀与缺价断点混合 |
| 58 | PF 短纤 | 历史 SOURCE_NONPOSITIVE_PRICE 需当前来源身份核对 |
| 59 | SI 工业硅 | 历史分区、端点、Session 多类问题 |
| 60 | RS 油菜籽 | 来源异常、稀疏交易、物理缺口复合情况，依赖前面成熟流程 |

第 54～60 位是完整恢复顺序，不是让共性问题拖到最后才发现；其必要异常样本已在 P3 提前验证。
普通组内部排序用于稳定执行，不宣称精确的当前成本优先级。

## 7. 按 Grok 4.6 High 组织任务

Cursor 官方说明 Grok 4.6 支持工具使用和长期编码任务，提供 low/medium/high/xhigh，high 为默认。
本方案继续使用用户指定的 High，不凭模型名字推断本仓库成功率，也不要求换模型或修改全局设置。
来源：[Cursor Grok 4.6 文档](https://prod.cursor.com/docs/models/grok-4-6)，2026-09-17 查阅。

实际安排：

- 公共前置工作分为 P0、P1、P2/P3 三个有明确出口的任务；每个完成即保存代码身份、测试结果和仍阻塞的边界。
- 之后一个 Cursor 会话处理一个品种；同会话内按 S1～S7 完成 W1、60m、D1 回归，不给它一个无人值守 60 品种长循环。
- 给当前任务的上下文只包含：本方案对应步骤、当前仓库规则、前置完成记录、当前品种原生审计/计划/回执。
  不粘贴全部旧聊天或整个 outputs；历史证据显式按路径读取，不由文件名猜“最新”。
- 每个阶段先生成机器可验证结果，再由模型解释；symbol/contract/frequency/cutoff/hash/count/状态分母由代码校验。
- 禁止为了一个品种修共享模块后继续悄悄扩散。若发现共享缺陷，先在该任务定位并单独提交修复、回归、独立 Review，
  更新候选身份；按影响范围使旧验收失效，再继续品种队列。并非每个品种都应产生源码 commit。
- 工程失败自主修正；连续两次对同一根因修改仍失败时，停止继续试错，提交最小复现、真实输出和待判断点。
  这条是建议的任务节奏；生产 mutation 遵守更严格的首次失败停止/只读核对合同。
- 共性高风险代码用独立会话审查固定 diff、测试、反例；不把原实现者重述自己的结论称独立 Review。
  审查者只读，不运行真实 provider/apply，也不按 finding 数量评分。
- 大合约任务可以跨额度周期暂停；恢复先核对未完成授权和现场状态，已完成单元不能因换会话重复执行。

### 给 Cursor 的首个任务文本

```text
请按 docs/superpowers/plans/2026-09-17-newow-w1-60m-per-product.md 的 P0 执行只读前置核对。
先读取当前 AGENTS.md、STATUS.md 和数据合同，确认最新 develop、工作树、dirty 与现役身份。
核对旧 W1 partial-source 修复已合入部分，以及旧六品种 60m 的已开始单元与当前数据状态，
重点定位 AO2403 ATOMIC_PUBLISH_FAILED 的真实原因、已提交分区和结果是否已结清。
输出可复用/需修复/需新外部授权三类结论，并提出 AU 第一个试点的只读范围。
本任务只读；不要修改实现、恢复旧脚本、初始化真实 provider、重跑旧包、写 Canonical/DB、
开放正式周期、切 Runtime、发通知或发布。不要接着自动执行 60 品种。
```

### 前置通过后的单品种任务模板

```text
本任务仅处理 <品种>，按方案 S1～S7 做 W1、60m 数据与三策略/页面验收，D1 做回归。
先核对前置任务的精确候选 commit 和当前现场，保存本品种固定 as_of 的完整原生审计。
明确普通缺口、质量异常、正常 WARMING/NOT_APPLICABLE 与产品 UNOPENED，不能合并成 READY。
允许只读调查、隔离测试、确定性验收与已明确授权的工程工作；若需真实下载或正式写入，
先给本品种的精确合约/周期/窗口/预算/hash/恢复边界，确认已有未完成授权是否覆盖。
授权覆盖后，串行完成其正常子单元和读回，不重复逐命令询问；失败先按合同停止并只读核对。
只用当前支持的原生工具，不盲改命令频率、不重用旧 receipt、不自行修改公式或豁免质量校验。
完成后给出 W1 3 策略、60m 3 策略和 D1 3 回归的实际结果及真实首载证据，
写入一份单品种结论并结束本任务；不要擅自开始下一个品种或执行发布/Runtime/通知。
```

## 8. 工程验证和最终交付

只改数据的品种无需机械重跑全仓测试；执行 native 验证、完整 consumer 读回与页面验收。
改共享代码时按改动运行以下已有测试入口，新增能复现实际缺陷的用例；命令从执行副本根运行。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core \
services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/newow/test_weekly_recovery.py \
  services/quant-api/tests/newow/test_weekly_recovery_campaign.py \
  services/quant-api/tests/newow/test_recovery_partial_exception.py \
  services/quant-api/tests/newow/test_daily_recovery_verification.py \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_aggregation.py
```

上组用于实际修改恢复链时；按影响追加 hourly profile 的新用例。质量传播/候选入口修改运行：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:services/quant-api:packages/quant-core \
services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_product_replay_invariants.py \
  services/quant-api/tests/newow/test_reference_interruptions.py \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/newow/test_candidate_preview.py \
  services/quant-api/tests/newow/test_market_newow_product_api.py \
  services/quant-api/tests/newow/test_weekly_acceptance.py \
  services/quant-api/tests/data_foundation/test_newow_readiness_cli.py
```

前端按 TESTING.md 的类型/Hook/参考卡片测试和 newow-product、detail-light、chart-panes E2E 执行；
fixture E2E 与真实页面验收分开，禁止用更新截图阈值消除未解释差异。
更改 canonical 时验证对应 OpenSpec；所有修改运行 diff check 和适用 secret scan，不触碰用户已有暂存。

最终发布候选在同一候选版本、共同截止与稳定输入身份上核验：

- 品种清单 60/60，W1 新组合 180、60m 新组合 180、D1 回归 180；不能把合计 540 个主组合和 section 数混用。
- 每个周期分别列正常 READY、合法非 READY、阻塞、未验收，三策略和页面有明确证据；不是承诺强行 540/540 READY。
- 逐品种异日证据仅作过程结果；最终受影响范围重跑，主图/参考/辅助窗口与自然首载不能只用静态 schema 验证。
- 共享修复后先复验所有受影响品种，必要时重跑完整矩阵，不把旧 commit 的绿色结果贴到新版本。
- 真实写入统计、失败/未知、普通剩余缺口和来源中断闭合；没有未解释数据差异或未结清 mutation。
- 周线和分钟的后续维护能力分别验证。盘后更新成功不等于本方案全部历史齐备；不新增后台下载或补数计划。
- 进入发布/Runtime 后还需按 exact tag 做真实服务读回和自然业务验收；不能用本方案数据、代码或页面通过替代。

数据恢复保持当前单分区可见点和旧 lineage；W1 同源组不具备跨分区事务原子性，因此失败后必须读回已提交项。
无自动删除、覆盖恢复、指针回退或 provider 重试；确需恢复时给精确目标、影响、dry-run、可验证恢复办法和授权范围。

本方案的最小下一步是 P0，只读查清旧 60m 执行与当前共享入口，再进入 AU 试点。
