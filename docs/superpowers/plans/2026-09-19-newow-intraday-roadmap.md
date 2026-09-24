# 牛哇四周期后续工作规划

日期：2026-09-19；基线复核：2026-09-24。本文是四周期唯一实施路线图，不是已执行结果或生产操作授权。
执行时遵守 AGENTS.md；当前状态只看 STATUS.md 和 fresh readback。

## 目标与基线

将原 60m 专项扩展为共享 Canonical 1m 底座的 1m、15m、30m、60m 历史产品能力，覆盖趋势、震荡、主升浪、适用指标与参考交易；随后独立建设盘中 completed observation。

2026-09-24 复核 `develop@ff4e50bfb65ab6d60e6d97412406c06369defe44`，任务树从该提交建立。`STATUS.md` 记录 `v1.10.33` 已发布并切换本机六项服务，但自然 completed Bar/盘后验收未完成，不能称 `RUNTIME_READY`。develop 的 Newow 产品合同仍仅枚举 1w/1d/60m，正式开放 1d/1w，60m 关闭；1m/15m/30m 尚无 Newow 产品身份。P8/P9 已进入 develop，生产 Reference 的 migration、全范围历史构建、persisted reader 切换和 worker activation 仍须 fresh readback，不能由代码存在推定。

沿用上一轮已读取的方案和证据：
- [原 W1/60m 逐品种方案](2026-09-17-newow-w1-60m-per-product.md)
- [数据合同](../../DATA_CENTER.md)
- [Newow 产品合同](../../../openspec/specs/newow-product-reference-trading/spec.md)
- [当前状态](../../../STATUS.md)

此规划更新分钟工作的目标，不取消 W1 任务，不扩展既有下载、写入、发布或 Runtime 授权。现有 60m 成果经当前身份核验后复用，不重新下载全部来源。原方案中的历史状态、哈希和授权不能直接用于本轮执行。

四周期共用**同一物理合约、已校验的 Canonical 1m**：1m 直接读取，15m/30m/60m 由唯一 Session 聚合器生成。每个周期有独立 dataset、完成水位、产品身份、公式计算、预热、质量判定、Reference stream、页面能力和开放 Gate。Catalog/MDS 是唯一消费者入口；既有 5m 消费者也受 1m revision 变化影响。历史重放和首次 forward 观察使用不同 stream 与统计身份。

本轮只读盘点与报告见 [2026-09-24 四周期盘点](../../tasks/newow-four-period-audit-20260924.md)。240/720 是固定分母。以 2026-09-25 00:00:33 CST 数据库快照读 9/24 已完成日，240/240 均因 `MAIN_CONTRACT_MAP_MISSING` 受阻；独立回读该日 rank1=0/60，Calendar=5 交易所、Session=60 品种。截至 9/23 的固定 2023 历史窗口 196/240 可读（49 品种），44/240 因 11 个品种在 2023 起点前尚未上市而受阻；11 个上市后窗口 44/44 可读。三策略 720 项均未计算，当前无四周期全就绪品种。49 个历史输入可读者并列，试点工程顺序推荐 RB → AU/AG/SC（长夜盘）与 AP（日盘），PD/PT 仅作短历史边界。这个顺序以最新报告为准，不把复选框勾选冒充已实现；补齐 9/24 Map/新鲜度亦不自动打开产品能力。

## 工作包与完成标准

### P0：收敛依赖与既有工作

- [ ] 核对 W1 工作树剩余差异与最新 develop，列出 reader、quality、capability、recovery 的共享文件归属及集成先后。
- [ ] 分别回读已部署版本的 Live、自然盘后、weekly audit 与 Alert 证据，不因改进分钟能力而手工重跑或补发。
- [ ] 以当前 60 品种盘点选择试点，不预设 AP/PD/PT 最优；对旧 unknown、原子发布失败及 Session 缺失，先确定当前实际对象和状态。

出口：已有成果、剩余缺口、共享阻塞、可独立推进工作各自明确。W1 交付和纯 Web 改善不必等待全部分钟数据；Runtime 未完成证据不阻塞隔离开发，但受影响的正式上线仍需证据。

### P1：冻结四周期产品与输入合同

- [ ] 在 `product_contracts.py` 增加 1m/15m/30m 身份并保留既有 D1/W1/60m 身份稳定性；`product_identity.py`、quality policy、`product_adapters.py` 与 Reference stream identity 同步审查，新增周期不静默改变旧结果。
- [ ] 复用已接受策略公式，参数按所选周期 Bar 数解释，不擅自按等时长换算或重新寻优。
- [ ] 按三策略分别冻结每周期的计算前缀、Bar 数预热、适用副图、重绘与原站证据状态；公式参数按该周期 Bar 数，不作等时长换算或重新寻优。D1/W1 缺价与 NO_TRADE 豁免不自动扩入分钟。
- [ ] 明确历史快照先交付，盘中 completed Live 后交付；分时专属公式、120m、Newow 5m、自动做空及通知不在本轮范围。
- [ ] 更新受影响的 Newow canonical、API/capability schema 和输入适配版本；公式版本只在公式语义变化时更新。不同周期 `as_of` 下分别求 completed cutoff，大周期背景只使用该时点已完成输入。

入口文件：packages/quant-core/guiyi_quant/newow/product_contracts.py、product_identity.py；services/quant-api/app/market_data/newow/product_release.py；openspec/specs/newow-product-reference-trading/spec.md。
出口：三策略 × 四周期的能力和非适用项明确，候选支持与正式开放分开声明。

### P2：四周期只读依赖盘点和资源估算

- [ ] 扩展 readiness 对 1m/15m/30m 的显式选择；保持无 provider、无写入的审计 composition。
- [ ] 分别枚举图表窗口、参考统计窗口、计算所需完整物理合约前缀与 rank1 owner 展示窗口；按合约及来源窗口合并 1m 依赖并保留 consumer 关联。同合约预热可早于 owner，不能跨合约拼信号或参考交易。
- [ ] 将来源 1m 缺失、仅派生缺失、Calendar/Session/Map/lifecycle 不足、来源身份或重复冲突、物理完整性、预热不足、产品未支持与未读取分别列出；多标签可并存，未知计数为未知，不填零。
- [ ] 输出存量复用量、需下载来源、需派生目标和磁盘/内存/请求预算；数据不足时不能生成可执行的精确 hash。

入口文件：services/quant-api/app/market_data/newow/readiness.py、readiness_composition.py 和既有 native planner/CLI。
出口：能按品种给出四周期依赖清单，预算完整且没有因重复消费者重复计入源请求。

### P3：完善分钟时间窗口与质量边界

- [ ] `product_reader.py` 的 60m 每天约 4 根估算改为权威 `expected_bar_ends` 窗口；分别处理 chart、reference statistics、物理计算 prefix 和各周期 completed cutoff。分钟分页必须用带时区 `bar_end` 严格游标与快照身份，不能沿用 `before: date` 导致同日漏 Bar/重复。
- [ ] 复用唯一 session 锚点和聚合器，不再次减一分钟，不按自然小时 resample，不跨休市拼桶。
- [ ] 验证合法短尾桶、真正缺分钟、首末分钟、跨午夜/月/年/周末、节假日无夜盘、各品种夜盘结束差异、历史 Session 变更及同日多 Bar 分页。Session 首分钟 adapter 仅转换一次；不按自然小时 resample，不跨休市拼桶。
- [ ] 验证精确端点集合、重复冲突、order_book_id、trading_day、rank1 owner、上市/到期生命周期及来源修订；1m revision 变化使 5m/15m/30m/60m 派生及下游已存 Reference snapshot 失效，须按依赖摘要重建与回读。
- [ ] 分钟非正价和 NO_TRADE 按已接受分钟合同处理；未覆盖样本明确阻断。不得把 D1/W1 缺价回执作为分钟缺价依据；如需新的分钟质量语义，单独提交具体样本和取舍。

入口文件：services/quant-api/app/market_data/aggregation.py、session_clock.py、newow/product_reader.py；现有 MDS/coverage 入口。不创建新的缺口权威。
出口：数据链正反例通过，证明合法尾桶不会被误删、真实缺分钟不会被掩盖。共享数据时序改动需独立 Review。

### P4：扩展现有维护与恢复编排

- [ ] 扩展现有 native 维护和必要的 campaign/acceptance 显式范围，区分来源 1m 与四个目标。当前 `contract-warmup` 显式只支持 1d/1w/15m/60m，先扩展合同和对应测试，不能假定已有四周期批次入口。
- [ ] 保持旧 60m 单频合同可验证，四周期使用明确新范围及身份；不得放宽旧校验来接受混频旧回执。
- [ ] 在一个明确批次内去重来源，源通过后分别派生；已有源变化时核对受影响派生及共享消费者，包括现有 5m。
- [ ] 计划、hash、来源/目标 scope、预算、冻结 expected_bar_ends、分区提交、独立读回和终态使用同一精确范围；明确来源去重、分区部分成功及幂等恢复。
- [ ] 验证维护锁、已有提交复用、预算耗尽、发布前失败、提交后结果未知及恢复；不宣称跨分区/跨周期天然原子成功。

出口：离线测试和 dry-run 可证明不会重复下载、越权派生或把部分成功算整批通过。生产批次须另有匹配目标、环境、预算、异常和重试边界的授权。

### P5：完成四周期策略、参考交易和页面

- [ ] 后端产品类型、输入 adapter、三策略与适用副图支持四周期；接入统一 Reference Trading 的历史 stream、bounded build/checkpoint、持久化 presentation 与快照分页。参考交易身份包含周期且不跨合约、owner 或质量断点配对；不新增第二套页面交易投影，不在每次页面请求全历史重算。
- [ ] 新主力预热 HOLD 不补造 BUILD；历史 `INITIAL_CLEAR_NO_ENTRY`、短历史 `WARMING`、零笔 CLOSED、`DATA_BLOCKED` 分别解释。forward 首次观察不得借历史回放制造入场或 `INITIAL_CLEAR_NO_ENTRY`。
- [ ] 前端类型、周期切换、API/capability、快照 token、分页、请求取消和缓存键统一更新；旧响应不能污染新周期或新快照。`persisted` reader 仅在实际 migration/build/覆盖/身份读回通过后切换，当前生产默认 `legacy` 需 fresh evidence 核实。
- [ ] 页面区分报价、所选周期策略、统计截止和周日背景。未开放解释继续保持未开放，不重新映射原周日评分成分钟评分。
- [ ] 完整前缀通过有界构建与 checkpoint 处理；验证 1m 容量、冷请求、取消、超时、内存、重启和重复请求。不得通过截短计算/统计或每次请求重放全历史制造性能通过。
- [ ] 参考收益沿用独立统计窗口和既有口径；不新增账户净值、年化、资金回撤，不将原站展示称为期货执行收益。

入口文件：packages/quant-core/guiyi_quant/newow/product_adapters.py、reference_trades.py；services/quant-api/app/market_data/newow/product_reader.py、product_service.py、product_release.py；apps/quant-web/src/api/newowProduct.ts、types/newowProduct.ts、composables/useNewowProduct.ts 和 components/market/detail/newow/。
出口：隔离候选有真实四周期页面，数据错误与产品未开放可区分，策略及时间语义完成独立 Review。

### P6：代表品种纵向验收

- [ ] 从本轮完整 60 品种真实盘点的最优数据条件选首个试点；再覆盖权威 Session 证明的长夜盘、短历史和换月样本；无四周期全就绪者时只选择最接近者并保留缺口。
- [ ] 增加源缺失、冲突、metadata 缺失和未完成桶反例；D1 缺价品种不能自动充当分钟缺价样本。
- [ ] 同一代码、配置、来源身份与带时区 as_of 下，逐周期验证 MDS、三策略、适用 section 和真实自然首次加载。
- [ ] 验证前缀不变性、批量/增量一致、重启一致、分页不改变统计，保留旧 D1/W1/60m 定向回归。

出口：首个品种 4 周期 × 3 策略闭环通过，代表性边界通过；不靠第二次刷新、fixture 或 HTTP 200 替代真实输入验收。

### P7：按品种扩大到 60 个并验证维护接续

- [ ] 保留原方案品种队列，结合 fresh audit 将已验证试点记为已完成，逐品种继续；不重跑旧批准批次。
- [ ] 每品种完成审计、精确 prepare、已授权补缺/派生、独立读回、三策略/页面验收及剩余事项记录。
- [ ] 保留 240 个品种×周期、720 个品种×周期×策略的完整分母；按 section 分列 READY、WARMING、NOT_APPLICABLE、BLOCKED、UNOPENED、未验证。
- [ ] 查验后续日常增量、新主力预热及下一交易日维护能接续四周期，不能只依赖一次性补数。
- [ ] 发布前用共同截止重验声明范围；异日证据用于进度，不拼成同截点全量验收。

出口：明确完成/未完成品种及周期；允许按明确声明范围准备候选，但不能凭少量试点默认全 60 品种开放。

### P8：历史分钟版正式交付

- [ ] 完成定向回归、共享数据/公式/时间边界独立 Review、develop 集成和范围一致性检查。
- [ ] 在精确版本发布授权后完成 main/tag/release；Runtime promotion 使用独立明确授权和 fresh preflight。
- [ ] 读回正式版本、能力范围、真实页面和新版本自然维护；验证恢复方案与当前数据/schema 兼容，不假定任意旧版本可回退。

出口：分别记录 RELEASED、Runtime 已切换及自然业务证据状态，不把页面通过称为 RUNTIME_READY。

### P9：盘中 completed observation 独立建设

- [ ] 另行定义 Historical/Live 接缝、当日 rank1、完成水位、未完成 preview、延迟和断线状态。
- [ ] 复用既有 Live 1m 与派生权威；验证跨接缝无重无漏、同合约、恢复和批量/增量/重启一致。
- [ ] 验证分钟历史时点只使用当时已完成的大周期输入；重绘展示与正式 Action 分开。
- [ ] 小范围自然运行验收后再扩大，Live enable、Scope/Rule、通知和恢复范围分别遵守明确授权；四周期历史页面不隐含预警开放。

出口：可声明盘中观察能力的精确范围与延迟；不自动进入 Paper、Shadow 或真实交易。

## 顺序与可并行部分

P0 的只读证据收尾与 P1 可同时推进。P1 完成后进入 P2；P2 暴露的缺口驱动 P3/P4，避免凭旧结果编排下载。
P3/P4 的必要公共能力与 P5 汇合后做 P6；试点通过后 P7，再按实际授权进入 P8。P9 是下一阶段。
共享 reader、planner、quality、capability 同时只由一个任务负责修改。生产补数/发布和共享维护锁操作串行。
W1 的已批准工作及独立 Web 改善继续，不扩大成新的总阻塞条件。

## 验证入口与本轮状态

执行时从 TESTING.md 选择受影响检查，不机械跑全量测试。已有相关入口：
- services/quant-api/tests/data_foundation/test_aggregation.py
- services/quant-api/tests/data_foundation/test_newow_readiness_cli.py
- services/quant-api/tests/newow/test_readiness.py
- services/quant-api/tests/newow/test_weekly_recovery.py
- services/quant-api/tests/newow/test_weekly_recovery_campaign.py
- services/quant-api/tests/newow/test_weekly_acceptance.py
- services/quant-api/tests/newow/test_product_reader.py
- services/quant-api/tests/newow/test_product_replay_invariants.py
- apps/quant-web/tests/useNewowProduct.test.ts
- apps/quant-web/e2e/newow-product.spec.mjs

本轮更新此规划并进行只读盘点；具体证据与限制见盘点报告。聚合器旧有 9 项通过仅是基础回归，不是四周期实现。文档检查与一天 MDS 探针不关闭完整历史、三策略、产品、发布或 Runtime Gate。
