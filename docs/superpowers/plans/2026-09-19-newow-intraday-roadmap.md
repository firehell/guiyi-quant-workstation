# 牛哇四周期开发计划（Implementation Plan）

> **For agentic workers:** 使用 `superpowers:executing-plans` 按任务实施。共享 reader、planner、quality、capability 默认由一个执行者串行修改；高风险部分独立 Review。流程与任务授权统一遵守 [AGENTS.md](../../../AGENTS.md)，不重复设置审批步骤。

**Goal:** 将原 60m 专项扩展为 1m、15m、30m、60m 四周期期货历史产品，覆盖三策略、适用指标与页面参考交易，随后独立交付盘中 completed observation。

**Architecture:** 复用可信物理合约 Canonical 1m；三个派生周期直接从该来源按 Session 生成，通过 Catalog/MainContractMap/MDS 读取。计算、参考交易、快照和开放状态逐周期独立，沿用模块化单体与统一参考交易链。

**Tech Stack:** 现有 Python/Decimal、FastAPI/Pydantic、Canonical Parquet、PostgreSQL Catalog/Reference、Redis Live，以及 Vue/TypeScript/Lightweight Charts；不新增基础设施。

**Spec:** 本会话 2026-09-26 的四周期设计，关键决策完整收敛在下方“设计合同”；active 业务合同以 [Newow canonical](../../../openspec/specs/newow-product-reference-trading/spec.md)、[数据合同](../../DATA_CENTER.md)、[参考交易 canonical](../../../openspec/specs/reference-trading/spec.md) 为准。计划新增部分先在 P1 同步相应 canonical，不把规划当已实现事实。

创建：2026-09-19；本次修订：2026-09-26。保留此文件作为唯一未完成的四周期开发计划，替代其中旧 P0–P9 描述，不另建平行计划。当前只完成计划编写；下列实现复选框全部保持未完成。

## 基线、现场观察与证据边界

- 本轮源码基线 `develop@74526ffcaf04a7ecbcfc7ca3a88bfeb4f6d3e1f7`。主树有其他任务的 `NewowReferencePanel.vue`、`newowReferencePanel.test.ts` 修改和 outputs；本次只改本计划。执行开始重新读取 Git/worktree 和共享文件归属。
- [STATUS.md](../../../STATUS.md) 最新记录日周 `v1.10.36` 已发布并切换，本机自然运行证据仍待验；P9 持久化面板 503 与部分周审计问题未收尾。本轮未重新探测生产，不能把文档记录当新的现场回读。
- develop 已有综合解释、跨周期价格和独立双策略参考。保留既有身份与合同；不再按“均不存在”安排重建，也不推定它们已发布或支持新分钟周期。
- 底层已有 1m → 5m/15m/30m/60m 聚合；Newow 正式能力仍须按实际 capability 核对，枚举扩展不能自动开放页面。
- [旧四周期盘点](../../tasks/newow-four-period-audit-20260924.md) 的 240 项历史逻辑窗口可读，不证明物理前缀、720 项策略、页面或当前新鲜度。旧 9/24 rank1 缺失是历史快照结论；STATUS 后续已记七周期单日读回通过，不再沿用旧缺口开补数单。原始矩阵与证据不改写。
- 2026-09-26 经 Chrome 查看牛哇 v3.3.59、盛科通信-U：四周期趋势记录数依次 72/61/62/29；15m 震荡为 29 笔且持有，趋势为空仓；上方继续显示周日背景；分时有独立均价/买卖参考。完整统计窗口、成本与公式未核验，主升浪分钟页面未观察。上述事实仅用于交互设计，不用于收益排名或公式 parity 声明。

## 设计合同（Global Constraints）

1. 本轮分钟范围固定 `1m/15m/30m/60m`；三策略为趋势、震荡、主升浪。保持现有 D1/W1、其他消费者 5m；不包含分时、120m、新做空规则、通知、Paper 或自动交易，`auto_order=false` 不变。
2. 1m 直接读取，15m/30m/60m 分别由同物理合约可信 1m 派生，不逐层聚合。消费者只读 MDS，不另建 resolver、缺口权威或页面聚合器。
3. Session `(start,end]`、首分钟标签转换一次、不跨休市拼桶；合法短尾 completed，真缺分钟失败。Calendar/Session/Map 不足不推断为行情缺失；分钟不继承 D1/W1 缺价豁免。
4. 计算前缀、owner 有效区段、图表窗口、统计窗口分开。历史展示验收自 `max(2023-01-01, 品种上市日)`；同合约预热依公式完整前缀核验，不跨合约借值。
5. 参数仍按所选周期 Bar 数，不换算钟表时长、不寻优；新周期复用公式不等于原站分钟 parity。回看重绘与当时可知 Action 分开，不把所有绘图点都要求成因果事件。
6. 主力切换、同合约 owner 重入、质量断点按稳定身份处理；预热 HOLD 不补造 BUILD。震荡同 Bar CLEAR 后 BUILD，初始无入场 CLEAR、OPEN、换月/数据中断分别保持原合同。
7. 单策略参考价继续分别使用趋势慢线 B、震荡 BUILD Low/CLEAR High、主升浪 MA45；价格/收益 Decimal 字符串。零费用零滑点 long/flat 页面参考不变，不新增账户年化/资金回撤，也不制造样本末尾清仓。
8. 主图、辅助、参考绑定同一快照；quote 与策略时间分开；跨周期背景显示来源周期、bar_end/as_of。时区统一 Asia/Shanghai，夜盘另列 trading_day，负收益保留负号。
9. 最新综合解释/跨周期价格/双策略模型先做兼容，分钟扩展默认不启用。没有分钟适用证据时显式 EVIDENCE_REQUIRED 或 UNOPENED，不把周日评分重新映射为分钟评分。双策略仍独立身份，不并入单策略 720 分母。
10. 历史与 Live 分离，先历史产品后盘中观察；checkpoint、快照不能跨 source/formula/adapter/period 身份复用。来源 1m 修订要检查已有 5m 及其他派生/Reference 消费者。
11. 所有后续生产动作只在交办目标覆盖时执行；本次“列开发计划”不启动下载、apply、build、migration、发布或 Runtime。授权存在时在机器校验通过后连续执行，不要求逐批次重复批准。

## 模块与职责

下列目录缩写仅用于路径说明，不是环境变量：Core=`packages/quant-core/guiyi_quant/newow/`；API=`services/quant-api/app/market_data/newow/`；Web=`apps/quant-web/src/`；NT=`services/quant-api/tests/newow/`；RT=`services/quant-api/tests/reference_trading/`。

| 入口 | 本轮职责 |
| --- | --- |
| Core `product_contracts.py`、`product_identity.py`、`product_adapters.py`、`product_auxiliary.py` | 周期身份、分钟校验、三策略/副图输入与分段，不复制公式 |
| API `product_query.py`、`product_reader.py`、`readiness.py`、`readiness_composition.py` | 精确窗口、完整前缀、只读依赖矩阵 |
| `services/quant-api/app/market_data/aggregation.py`、`session_clock.py`、`historical_data_manager.py` | 唯一分桶、来源/派生计划、恢复与维护 |
| Core `reference_trades.py`、`reference_statistics.py`；`services/quant-api/app/reference_trading/` 现有模块 | 参考投影、bounded build/checkpoint、持久化查询 |
| API `product_service.py`、`product_release.py`；`services/quant-api/app/schemas/market_newow_product.py`、`app/api/market_newow.py` | 同快照响应、能力与开关，旧版本拒绝/兼容 |
| Web `api/newowProduct.ts`、`types/newowProduct.ts`、`utils/newowProductTypes.ts`、`composables/useNewowProduct.ts`、`components/market/detail/newow/` | 周期切换、分页、请求取消、时间/状态/统计展示 |
| `scripts/newow_four_period_readonly_audit.py`、Newow readiness CLI | 复用报告入口，不新增第二套数据审计真相 |

不预设 migration；P5b 先核对既有 schema 对周期和 stream 的表达能力，仅在无法表达本合同且有具体证据时纳入必要迁移及恢复测试。

## Review Focus

- 同一 trading_day 多根分钟 Bar：P3/P5a 允许有序分钟，不放松 D1 日期约束；新增重复/乱序、同日分页回归。
- owner 重入与预热时间回退：P5a 每个 owner/calculation segment 独立定位已发生断点，验证初始 HOLD 与无入场 CLEAR。
- 一个源 revision 改变、其他周期尚未重建：P4/P5b/P5c 阻止旧 token/资产混读，验证 5m 消费者影响与部分成功恢复。
- 同 Bar CLEAR/BUILD 与历史/实时交界：P5a/P5b/P9 验证顺序、身份、重启幂等及无入场时不造交易。
- 切周期后迟到响应和巨大 1m 窗口：P5b/P5c 验证取消、游标、完整统计与分页独立，不以截断计算换取性能。

## 顺序与执行方式

`P0 → P1 → P2 初盘 → P3 → P2 完整依赖复核 → P4 → P5a → P5b → P5c → P6 → P7 → P8`；P9 后续独立交付。

P2 的初盘只证明现有可读窗口/元数据，完整依赖结论必须使用 P3 的权威窗口和 P5a 的实际公式要求。P4 无缺口时只验证工具及复用现有产物，不为了任务完整重复下载。P0 的自然运行证据收集可与隔离开发并行，但共享代码与生产维护默认串行。普通小改动自审；数据时序、策略状态、参考配对、checkpoint 和生产计划独立 Review。

每个代码任务按“先补行为回归 → 运行并确认目标失败 → 最小实现 → 定向验证 → diff/静态检查 → 按风险 Review → 范围内提交”的顺序执行。提交只暂存该任务路径；P0/审计/操作记录不机械执行 TDD。后续命令均是待执行入口，本计划不声称任何代码测试已通过。

## P0：确认现场与共享依赖

**范围：** 只读 Git、STATUS、P9/日周 evidence 和当前配置身份，不修改产品代码。

- [ ] 重新核对 branch/HEAD/worktree/dirty、develop 依赖，确认 ReferencePanel 等其他任务改动的集成状态；实施代码需要隔离时再建立 worktree，本轮文档不为此创建额外树。
- [ ] 从当前生产只读身份确认 Canonical 根、Catalog、正式版本、Reference reader/worker；不输出凭据。
- [ ] 将 P9 503、旧 unknown、周审计问题按“分钟共享依赖 / 无关旧问题 / 需现场核对”分类；只把实际影响试点的项列为前置。
- [ ] 确定首个试点候选 RB，记录输入量、当前窗口读取/构建的耗时、内存与预算，固定后续容量对比环境；不能以旧 240 可读推定 RB 可直接开通。

**出口：** 当前依赖与共享文件归属清楚；不重跑已经完成的日周工作。源码开发不等待尚未发生的 9/28 自然事件；影响正式切换的证据留到 P8。

## P1：周期、身份与能力合同

**修改：** Core `product_contracts.py`、`product_identity.py`；API `product_release.py`；Newow canonical；相应 schema/type 定义。
**测试：** NT `test_product_contracts.py`、`test_market_newow_product_api.py`、`test_product_readonly_compatibility.py`；Web `tests/newowCapabilities.test.ts`、`tests/newowProductTypes.test.ts`。
**接口：** `ProductFrequency` 扩展 1m/15m/30m；既有 `build_product_identity(product, strategy, frequency, *, input_quality_policy) -> ProductIdentity` 接受新周期并保持旧身份；四周期集合显式传递，不能靠 `tuple(ProductFrequency)` 意外扩大默认查询/开放范围。

- [ ] 补测试：1m/15m/30m/60m 身份不同，旧 D1/W1/60m ID 稳定；非法周期拒绝；新周期正式请求保持关闭，候选入口可显式选择。
- [ ] 建立 3×4 主策略与适用 section 表，分别标记工程支持、原站 parity、预热/重绘、是否正式开放；杯柄仍沿用既有适用范围。
- [ ] 实现枚举、adapter/schema/capability 版本传递与验证，不改变公式参数；分钟质量/适配版本按既有命名登记，旧 token 不得伪装新合同。
- [ ] 运行上述定向测试及 OpenSpec 校验，自审合同与 API 一致后提交。

**出口：** 新周期可以被严格识别与候选测试，正式能力不因枚举自动开启。

## P2：来源盘点与精确依赖矩阵

**修改：** API `readiness.py`、`readiness_composition.py`；`scripts/newow_four_period_readonly_audit.py`；`services/quant-api/app/guiyi_cli/data_commands.py`。
**测试：** NT `test_readiness.py`；`services/quant-api/tests/data_foundation/test_newow_readiness_cli.py`。
**接口：** `NewowReadinessAudit.run(ReadinessRequest(..., frequencies=四周期)) -> dict` 显式枚举 240 输入项/720 主策略项；未计算项保留 NOT_EVALUATED，附窗口、owner、source identity、预算及 consumer 关联。

- [ ] 补测试：晚上市起点裁定不制造上市前缺口；同合约重叠源窗口去重；Map 缺失不变成 provider 目标；预算超限的未检查项不填零。
- [ ] 实现初盘及复用量/缺源/缺派生/元数据/冲突/预热/未支持分类，区分逻辑 owner 窗口与完整物理前缀。
- [ ] P3 完成后重算精确端点依赖；P5a 确认公式预热后补齐策略级证据，不拼接异日快照冒充同截点矩阵。
- [ ] 运行定向测试；后续任务包含真实审计时再固定数据身份和 as_of 执行只读矩阵，报告实际请求/写入均为零。

**出口：** 来源请求、派生目标、物理前缀与资源预算可以逐项解释；未知没有被包装成 SOURCE_READY。

## P3：Session、完成端点和分钟分页

**修改：** API `product_query.py`、`product_reader.py`；必要时修正共享 `aggregation.py`、`session_clock.py`；API/schema 游标传递。
**测试：** `services/quant-api/tests/data_foundation/test_aggregation.py`、`test_historical_session_window.py`、`test_session_anchor_repair.py`；NT `test_product_reader.py`、`test_older_chart_windows.py`、`test_product_snapshot_cache.py`。
**接口：** 保留现有按日期查询的 D1/W1 合同；分钟图表新增可选、带时区且严格排他的 `chart_before: datetime | None`，与 snapshot identity 绑定。日期范围仅用于权威存储读取，最终裁剪按 Bar 端点；独立 reference `history_before` 游标不混用。

- [ ] 补测试：09:00–10:15 Session 的 60m 端点恰为 10:00/10:15；09:01 不丢失；删除应有 1m 则失败；不会跨休市拼桶。
- [ ] 补测试：长夜盘跨日/月/年、假日无夜盘、历史 Session 变化、未完成/未发布桶和乱序重复；使用权威预期端点，不写死每天根数。
- [ ] 用 `expected_bar_ends` 替换 reader 的“60m 每天 4 根”估算，分开图表、统计、prefix、completed cutoff。
- [ ] 实现 `chart_before` 的 schema、reader 与 cursor 校验：同日多页无重无漏；错周期/旧快照 token 拒绝；翻页不改变计算和统计。
- [ ] 运行上述组，独立 Review 数据时序；如果现有聚合器满足合同，保留实现，只追加必要回归，不顺手重构。

**出口：** 分钟读取有完整时间合同，当前合法尾桶和真正缺分钟可区别。

## P4：去重维护、来源修订和失败恢复

**修改：** `services/quant-api/app/market_data/historical_data_manager.py`、`app/guiyi_cli/data_commands.py`；相关维护 canonical。
**测试：** `services/quant-api/tests/data_foundation/test_historical_data_manager.py`、`test_daily_maintenance.py`；NT `test_readiness.py`。
**接口：** 复用 `ContractWarmupRequest/Plan/Result` 和 `HistoricalDataManager.contract_warmup`。保留旧单频 request/hash 的校验；先支持显式 1m/30m，再以明确 consumer scope 合并同批来源窗口，计划继续区分 direct/derived count、source/target frequencies 与精确 hash。

- [ ] 补测试：四周期同源只获取一次；仅派生缺失零 provider；不再将 60m 目标数乘 60 当来源缺口量。
- [ ] 实现来源去重、冻结端点、预算与维护互斥；1m 修订后定位所有受影响派生和参考依赖，包括已有 5m。
- [ ] 补故障测试：源提交成功/派生失败、提交后结果未知、进程中断、重跑复用已提交项、锁竞争及预算耗尽；不声称跨周期/分区整体原子成功。
- [ ] 运行离线/隔离测试与 dry-run 校验，独立 Review。生产恢复保留旧不可变版本、指针 preimage 与幂等边界；unknown 必须只读查明，不能盲重试。

**出口：** 工具能按精确计划复用、派生、恢复；实际下载/apply 留在目标覆盖的 P6/P7 阶段。

## P5a：三策略与辅助指标的四周期计算

**修改：** Core `product_adapters.py`、`product_auxiliary.py`；API reader 与辅助输出适配；仅在真实调用路径需要时调整 `engine.py`。
**测试：** NT `test_product_adapters.py`、`test_product_replay_invariants.py`、`test_engine_causality.py`、`test_main_rise_page_v1.py`、`test_reference_interruptions.py`。
**接口：** 复用 `replay_step(identity: ProductIdentity, state: ProductReplayState, product_bar: ProductBar, *, verified_lifecycle: bool=False) -> tuple[ProductReplayState, StrategyFrame | None, tuple[str, ...]]` 与 batch replay；不创建第二套策略公式。

- [ ] 补测试：同交易日连续分钟可推进；重复相同输入幂等，重复身份不同内容和乱序失败。分钟适配不得放松独立 D1 Engine 的日期约束，也不把 D1 专属能力整体移入分钟。
- [ ] 逐策略/副图冻结实际 warm-up、完整 prefix 与适用项；在真实短段上分别验证当前可计算和历史 WARMING。
- [ ] 验证 owner 重入、物理切换、断点时间回退；预热 HOLD 不造 BUILD，初始 CLEAR 证据不跨 owner/cutoff 重用。
- [ ] 验证同 Bar CLEAR→BUILD、Hint 不改变参考持有、批量/增量/checkpoint 恢复一致；对因果输出验证 prefix invariance，对重绘图层验证确认时间及独立标签。
- [ ] 运行定向与原公式金样回归，独立 Review；把实际策略输入要求回填 P2 依赖矩阵。

**出口：** 12 个主策略组合可独立计算，预热/适用性如实报告；不以原站截图宣称数值一致。

## P5b：统一参考流、快照构建与容量

**修改：** Core `reference_trades.py`、`reference_statistics.py`；`services/quant-api/app/reference_trading/contracts.py`、`planning.py`、`service.py`、`inputs.py`、`persisted_newow.py`、`presentation.py`、`source_identity.py`；复用既有 checkpoint 模块。
**测试：** NT `test_reference_trades.py`、`test_reference_statistics.py`；RT `test_newow_historical_driver.py`、`test_newow_persisted_query.py`、`test_checkpoint_parity.py`、`test_revision_rebuild.py`、`test_multi_owner_historical.py`。
**接口：** 既有 stream identity 增加新 frequency 取值，strategy/formula/reference_model/adapter/source proof 继续完整绑定；输入为 P5a 的确定 replay，输出为同 cutoff 的 reference revision、summary、cursor，保持原交易 ID 稳定规则。

- [ ] 补测试：不同周期隔离；entry identity 在 OPEN→CLOSED 和翻页时稳定；换月/中断不造退出，非 CLOSED 不计 CLOSED 统计。
- [ ] 接入 bounded historical build 与恢复，复用既有 projector/reducer；旧 source/formula/period checkpoint 必须拒绝。分钟正式查询不增加 on-request 全历史重放路径。
- [ ] 扩展实际统计起止、样本量、OPEN/CLOSED/interrupted/unpaired 分类及来源截止；保留当前窗口计入和累计算法，不改收益语义。
- [ ] 核对 P9 reader/build 的实际阻塞并处理本轮必需部分；既有 schema 能表达则不新增 migration。读回成功后才切换声明范围 reader，不默认切全局旧流。
- [ ] 容量验证分别跑 RB 完整四周期构建、500 根图表读取、200 条参考分页；记录固定环境的输入量、耗时/峰值内存、冷/热请求与取消行为。请求预算/上限沿用已冻结合同，若不足先据测量说明取舍，不能截断 prefix/统计以通过。
- [ ] 运行离线及必要的一次性 PostgreSQL 隔离测试、独立 Review；skip 或基线失败单列。现有 fusion 按需全窗计算不自动扩展到 1m，分钟 fusion 默认关闭且旧周期回归。

**出口：** 一个周期的构建/恢复/分页不污染其他周期；完整统计不依赖图表长度，分钟规模可承受且有实测。

## P5c：API 与 Web 四周期页面

**修改：** API `product_service.py`、`product_release.py`，`services/quant-api/app/api/market_newow.py`、`app/schemas/market_newow_product.py`；Web 模块表所列文件及 `NewowProductWorkspace.vue`、`NewowReferencePanel.vue`、`NewowExplanationPanel.vue`。
**测试：** NT `test_product_service.py`、`test_market_newow_product_api.py`、`test_product_snapshot_cache.py`；Web `tests/useNewowProduct.test.ts`、`tests/newowProductTypes.test.ts`、`tests/newowCapabilities.test.ts`、`tests/newowReferencePanel.test.ts`、`tests/newowExplanationPanel.test.ts`；`e2e/newow-product.spec.mjs`。
**接口：** product/strategy/frequency/as_of/source proof 绑定同 snapshot token；主图、辅助、参考共享它。quote/context 使用独立且显式的 source period/bar_end；P3 的 chart cursor 与 P5b reference cursor 分离。

- [ ] 补测试：1m→60m 切换时迟到旧响应被丢弃；错 token/版本/cursor 失败；刷新失败保留有标识的旧快照，冷启动无可信数据则不可用。
- [ ] 实现周期切换、分钟日期时间轴与详情、夜盘 trading_day、显式负号；同周期主状态优先，周日背景独立标识。
- [ ] 页面分别显示数据/计算/辅助/参考/新鲜度/正式开放状态，WARMING 不清空正常主图，背景缺失不阻断已经证明的当前主策略。
- [ ] 显示统计实际起止与计数，标注零成本页面参考；图表 Marker 可定位精确记录，不按相邻标签猜配对。
- [ ] 兼容既有综合解释、跨周期价格和双策略身份；新分钟 capability 对无证据 section 明确关闭，不隐藏请求其他周期或沿用旧得分。
- [ ] 运行定向前后端测试、Web build（含 typecheck/topology）和候选 fixture E2E；独立真实浏览器验收留 P6，fixture/HTTP 200 不代替真实完成。

**出口：** 候选页面完成四周期交互且错误状态可解释，正式开关仍只按已验收范围开放。

## P6：首个品种与边界样本纵向验收

**范围：** 优先 RB 经 fresh audit 确认可做首试点；之后 AP（日盘）、AU/AG/SC 选实际覆盖所需 Session 的样本、AO（上市边界）、PD/PT（短历史）。品种只是候选，历史标签不能代替当前物理段长度。

- [ ] 固定代码、配置、Canonical/Catalog 身份、产品集合与 as_of，先 dry-run；缺源才按精确计划补源，缺派生才派生。目标不包含生产修复时只使用隔离输入验收。
- [ ] 对实际 mutation 独立读回源/派生/指针/剩余目标，再构建参考资产；已有结果不重复提交，恢复范围与旧数据可核验。
- [ ] 首试点完成 4×3 主策略、全部适用 section、参考记录、首屏、切周期、同日翻页和错误态；其他品种只扩边界，不代替首个完整闭环。
- [ ] 增加 metadata 缺失、缺分钟、短尾、owner 重入、预热不足、源修订反例，并核对最新价格与历史策略截点分离。
- [ ] 独立 Review 数据计划/时序结果；定向回归 D1/W1 和旧 60m，记录代码通过、数据通过、页面通过各自状态。

**出口：** RB 或 fresh audit 选定替代试点有完整 12 组合证据；其余边界覆盖明确，不能外推 60 品种全完成。

## P7：60 品种扩大与维护接续

- [ ] 复用 P2/P4 依赖队列逐品种执行，单个未知结果只阻断受影响 mutation；共享源/维护锁串行，独立只读盘点可继续。
- [ ] 形成 240 输入项和 720 主策略项的同版本、共同 as_of 矩阵；逐 section 列 READY/WARMING/NOT_APPLICABLE/BLOCKED/UNOPENED/NOT_EVALUATED，明确完成及未完品种。
- [ ] 双策略/解释若以后纳入分钟，额外列验收矩阵与范围，不替代 720 项，不因既有代码存在而自动扩入。
- [ ] 在任务覆盖时验证后续盘后增量、新主力预热与派生接续；自然事件尚未发生则保留待验，不能手工补跑伪装自然证据。
- [ ] 部分范围可独立候选，但 capability 必须与实际品种×周期×策略证据一致；保持已有日周能力。

**出口：** 明确可交付范围和剩余阻塞，不用单日 MDS 成功或历史窗口可读代替全量产品验收。

## P8：历史分钟版集成、发布与自然验收

- [ ] 对冻结候选完成直接相关回归、静态检查与必要高风险独立 Review；按范围集成 develop，不覆盖其他任务改动。
- [ ] 目标包含发布/上线时读取 release-agent skill 与 deploy 合同，连续完成精确候选发布、Runtime preflight/切换及真实读回；只交办编码/候选时在该范围结束，不扩大生产操作。
- [ ] 读回 exact 版本、capability、首屏、主图/参考一致性及关键样本；旧 reader/schema/URI 的兼容性经过证明后才可作为回退。
- [ ] 记录新版本自然盘后、派生更新和后续维护；未发生保持 pending，不能用启动健康声明自然 RUNTIME_READY。

**出口：** CODE/TEST/REVIEW、RELEASED、已切换和自然验收分别有证据；开放失败可关闭新分钟能力，数据恢复按精确提交边界处理，不全库/全湖回滚。

## P9：盘中 completed observation（历史版之后）

**修改入口：** `services/quant-api/app/reference_trading/forward_inputs.py`、`forward_authority.py`、`newow_forward.py`、`reconciliation.py`、`runtime.py`；API reader 既有 `forward_incremental_bar` 及 Live 权威入口。
**测试：** RT `test_forward_inputs.py`、`test_forward_authority.py`、`test_newow_forward.py`、`test_forward_reconciliation.py`、`test_newow_worker_recovery.py`。

- [ ] 冻结历史末端/当日 rank1/Live completed 接缝，历史 replay 与首次 forward 使用不同 stream/统计身份；未完成 Bar 仅 Preview。
- [ ] 补测试：同合约接缝重叠/缺失、迟到/修订、断线与午夜、换主力、同 Bar 多动作；内容冲突阻断，不任意选历史或 Live 覆盖。
- [ ] 复用既有 Live 聚合器、状态恢复与完成水位；断线后通过既有受控恢复路径证明连续，不能跨缺口推进或将 Live 直接晋升 Canonical。
- [ ] 验证历史时点只见当时已完成的大周期输入、首次观察不补造入场，batch/增量/重启一致；小范围真实自然观察通过后才扩大。
- [ ] 显示周期独立水位/延迟/断线状态；Scope、Rule、真实通知和订单不因页面接入自动改变。

**出口：** 可以单独声明盘中观察的精确范围、延迟及自然证据；不进入 Paper/Shadow/实盘执行。

## 验证命令与记录方式

全部从仓库根运行；Python 使用本树已验证环境。以下命令是开发时选择的组，按任务先取相应文件，不在本次计划编写中执行。

```bash
# P1/P2/P3：合同、只读审计、聚合与分钟窗口
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow/test_product_contracts.py \
  services/quant-api/tests/newow/test_readiness.py \
  services/quant-api/tests/data_foundation/test_newow_readiness_cli.py \
  services/quant-api/tests/data_foundation/test_aggregation.py \
  services/quant-api/tests/data_foundation/test_historical_session_window.py \
  services/quant-api/tests/data_foundation/test_session_anchor_repair.py \
  services/quant-api/tests/newow/test_product_reader.py \
  services/quant-api/tests/newow/test_older_chart_windows.py

# P4：维护与恢复（隔离测试，不运行生产 apply）
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/data_foundation/test_historical_data_manager.py \
  services/quant-api/tests/data_foundation/test_daily_maintenance.py

# P5a/P5b：计算、配对、checkpoint 与持久化查询
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow/test_product_adapters.py \
  services/quant-api/tests/newow/test_product_replay_invariants.py \
  services/quant-api/tests/newow/test_reference_trades.py \
  services/quant-api/tests/newow/test_reference_statistics.py \
  services/quant-api/tests/newow/test_reference_interruptions.py \
  services/quant-api/tests/reference_trading/test_newow_historical_driver.py \
  services/quant-api/tests/reference_trading/test_newow_persisted_query.py \
  services/quant-api/tests/reference_trading/test_checkpoint_parity.py \
  services/quant-api/tests/reference_trading/test_revision_rebuild.py

# P5c：页面状态、请求隔离、类型与构建
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/useNewowProduct.test.ts tests/newowProductTypes.test.ts tests/newowCapabilities.test.ts tests/newowReferencePanel.test.ts tests/newowExplanationPanel.test.ts
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build

# canonical 修改后；当前只改规划文字，不机械运行这些业务检查
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

期望：新增回归先证明目标行为失败，实现后对应组全部通过；skip、环境错误、基线失败独立报告。PostgreSQL/Redis 隔离规则、Ruff/Mypy、fixture E2E 与真实浏览器入口按 [TESTING.md](../../../TESTING.md) 和 [DEVELOPMENT.md](../../DEVELOPMENT.md)，不连接生产跑可写测试。

每包只在既有任务记录中补充精确 SHA、命令/结果、真实 readback 与剩余 Gate，不再复制多套 manifest/receipt。代码集成前同步 canonical，任务进度有证据后才更新 STATUS；规划完成不勾实现项。

## 本次计划检查

本次仅更新本文件，进行本地引用/代码路径、P0–P9 与 P5a/b/c 结构、未完成清单、占位项和 diff 格式检查。未执行上述业务测试、来源查询/下载、生产写入、Reference build、发布或 Runtime 操作。下一步从 P0 基线和 P1 候选周期合同开始，不先全量补数或开放四周期按钮。
