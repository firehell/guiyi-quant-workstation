> 当前计划（2026-09-28）：**1m 仅聚合来源，分钟显示/指标/牛哇策略仅 5m/15m/30m/60m**。RB、HC、I、J、JM 五品种已各自完成 12/12 历史候选闭环；本轮只规划剩余 **21 品种逐个闭环**，执行队列及验收标准见 P7。取消全品种预审和板块整批收尾前置。下文 P0–P6 保留历史实现依据，不重做；历史 1m 页面验收不计入本轮。发布、Runtime、观察范围不因本计划扩大。

> 执行状态（2026-09-27）：P0–P6 首品种 RB 历史候选已完成代码、数据、容量、真实浏览器与独立 Review；已快进集成 develop并完成集成后定向读回。4输入/8基础/4融合/12页面模式，未执行 P7、发布、Runtime、通知或订单。实际 SHA、证据与限制统一见 `docs/tasks/newow-intraday-pilot-20260927.md`。下文“当前缺口”是原始实施基线，已完成能力不得重做。

# 牛哇四周期开发计划（Implementation Plan）

> **For agentic workers:** 使用 `superpowers:executing-plans` 按任务实施。共享 reader、planner、quality、capability 默认由一个执行者串行修改；高风险部分独立 Review。流程与任务授权统一遵守 [AGENTS.md](../../../AGENTS.md)，不重复设置审批步骤。

**Goal:** 复用五个已闭环品种的能力，按 P7 队列逐个完成剩余 21 品种的 5m、15m、30m、60m 历史候选，覆盖趋势、震荡、双策略三种页面模式、适用指标与页面参考交易。独立数据问题记录后暂缓，先交付可闭环品种。双策略复用两个基础 kernel，融合是独立参考模型；主升浪保留既有能力，本轮不扩分钟。

**Architecture:** 复用可信物理合约 Canonical 1m；四个派生周期分别直接从该来源按 Session 生成，通过 Catalog/MainContractMap/MDS 读取。一次只推进一个品种的来源、资产、API、页面和证据；计算、参考交易、快照和开放状态逐周期独立，沿用模块化单体与统一参考交易链。

**Tech Stack:** 现有 Python/Decimal、FastAPI/Pydantic、Canonical Parquet、PostgreSQL Catalog/Reference、Redis Live，以及 Vue/TypeScript/Lightweight Charts；不新增基础设施。

**Spec:** 本会话 2026-09-28 的四个派生周期、数据问题可暂缓、剩余品种逐个推进要求，替代旧批次安排；active 业务合同以 [Newow canonical](../../../openspec/specs/newow-product-reference-trading/spec.md)、[数据合同](../../DATA_CENTER.md)、[参考交易 canonical](../../../openspec/specs/reference-trading/spec.md) 为准。不修改公式或收益语义，不把规划当已实现事实。

创建：2026-09-19；本次修订：2026-09-28。保留此文件作为唯一四周期开发计划，不另建平行计划。P0–P6 已实现，P7 是当前执行入口；P8/P9/R1/R2 保留为后续独立范围。本次只更新计划，不执行数据维护、资产构建或新候选验收。

## 当前逐品种基线

- 本次只读核对：`develop@019514fd6158515755f90cbcf8968a9985532664`，领先 `origin/develop` 一个提交，修改前工作区干净；已有多个候选预览工作树，后续执行先核对占用再复用空闲环境。
- 五个完成品种：[RB](../../tasks/rb-minute-closeout-20260928.md)、[HC](../../tasks/hc-minute-closeout-20260928.md)、[I](../../tasks/i-minute-closeout-20260928.md)、[J](../../tasks/j-minute-closeout-20260928.md)、[JM](../../tasks/jm-minute-closeout-20260928.md)。本次核对 STATUS 与任务记录，不重复执行它们的验收；完成指历史候选，不代表正式发布或 Runtime Ready。
- 原优先清单有 25 品种，其中已完成 JM/J/HC/I 四个，另一个完成品种 RB 不在原清单，因此剩余 **21**；SS 不在本轮队列，保留原失败事实与暂缓状态。队列 21 个代码均已核对存在于 `data/universe/operational_products.txt`，不需要扩 Scope。
- STATUS 当前记录正式版本为 `v1.10.39@653e736f5952146a2ea401634d32a605e7b9a0d5`；正式分钟入口、reference worker 仍关闭。本次未重新探测 Runtime，实际运行状态仍需现场读回。

## 历史基线、现场观察与证据边界（2026-09-26/27）

- 任务拆分基线 `develop@b48ffe0e504ee3d0850a2e75c2820dca26f9aefe`。已复核自前轮 `0a2977429` 起的变更：综合决策展示、日周状态卡、UI 验证及参考记录近一年。工作树仅本计划有 tracked 修改，另有用户 outputs；只更新本计划。执行者仍须重新读取 Git/worktree 与最新依赖。
- [STATUS.md](../../../STATUS.md) 最新记录日周 `v1.10.38@18b29c985` 已切换至扩展盘 linked release worktree，新根自然运行证据仍待验；P9 与部分周审计问题未收尾。本轮未重新探测生产，不能把文档记录当新的现场回读。按最新约定向前修复，不要求常驻保留旧 Runtime 树。
- develop 已有综合解释、跨周期价格、独立双轨图、融合参考曲线/近一年卡片及日周 AI 分析。保留既有身份与合同；不重新开发这些能力，也不推定 develop 新增项已发布或支持新分钟周期。
- 底层已有 1m → 5m/15m/30m/60m 聚合；Newow 正式能力仍须按实际 capability 核对，枚举扩展不能自动开放页面。
- [旧四周期盘点](../../tasks/newow-four-period-audit-20260924.md) 的 240 项历史逻辑窗口可读，不证明物理前缀、720 项策略、页面或当前新鲜度。旧 9/24 rank1 缺失是历史快照结论；STATUS 后续已记七周期单日读回通过，不再沿用旧缺口开补数单。原始矩阵与证据不改写。
- 2026-09-26 经 Chrome 查看牛哇 v3.3.59、盛科通信-U：四周期趋势记录数依次 72/61/62/29；15m 震荡为 29 笔且持有，趋势为空仓；上方继续显示周日背景；分时有独立均价/买卖参考。完整统计窗口、成本与公式未核验，主升浪分钟页面未观察。上述事实仅用于交互设计，不用于收益排名或公式 parity 声明。
- 2026-09-27 重新在 Chrome 查看同一详情页：菜单包含分时、1/5/15/30/60/120 分及日周月。双策略 15m 融合区显示 67 笔、累计 +111.82%；1m 选择后显示 73 笔、累计 +35.60%，顶部仍是周日背景。未验证两者全量输入与统计窗口；只证明页面切换和展示差异，不能判定哪个周期更优，也不能仅凭按钮证明服务端返回真实 1m。来源为 [牛哇详情页](https://www.v8848.cn/stock_detail.html?code=688702.SH)。

### 原始实施基线缺口（P0–P6 已处理）

| 位置 | 当前事实 | 分钟方案 |
| --- | --- | --- |
| `product_contracts.py`、`market_newow.py`、Web 类型 | Newow 只枚举 1w/1d/60m；正式开放日周 | 新增三个周期身份；按品种、周期、模式、section 开放 |
| `product_reader.py::_resolve_chart_window` | 60m 固定每天 4 根，历史窗口按 date 翻页 | 用 Session 预期端点定位窗口，分钟游标精确到 bar_end |
| `product_service.py` coverage / explanation | 同日多根只特判 HOURLY；部分上下文枚举所有周期；CDV2 非周即日 | 显式 intraday 集合；明确背景角色，分钟不得误用日线当前角色 |
| `fusion_reference.py` | 完整重放后仅返回最近 200 条记录 | 保留融合 reducer，输出完整统计/曲线和独立分页 |
| `NewowFusionPanel.vue` | 从返回记录生成曲线；截断时拒绝绘图；部分窗口按北京时间自然日期筛选，非周标日K | 后端提供权威窗口 membership；夜盘用 trading_day；统一周期标签 |
| `product_service.py` fusion 分支 | include_fusion 绕过 persisted reader，按需全窗计算 | 构建时复用两套输入，分钟查询读取已验证快照，不请求时全历史重放 |

手册按最新 [公式目录](../../research/newow-v3.2.82/FORMULA_CATALOG_20260926.md)、[双策略任务](../../tasks/newow-dual-entry-20260927.md)、[融合展示任务](../../tasks/newow-fusion-reference-ui-20260927.md) 与当前代码交叉判断；旧手册“尚未实现”描述不能覆盖新代码事实。

## 设计合同（Global Constraints）

1. 本轮分钟范围固定 `5m/15m/30m/60m`；页面为趋势、震荡、双策略。基础策略只有 trend/oscillation，dual 沿用 `strategy=trend&newow_mode=dual`，不新增第三个计算 kernel；fusion 使用独立参考模型身份。保持现有 D1/W1、主升浪及其他消费者行为；不包含 Newow 1m 页面/策略、分时、120m、新做空规则、通知、Paper 或自动交易，`auto_order=false` 不变。
2. 1m 仅承担聚合输入，5m/15m/30m/60m 分别由同物理合约可信 1m 派生，不逐层聚合。只核对当前品种所需来源、完整物理计算前缀和聚合质量；不做 Newow 1m 全链路、参考收益或页面验收。消费者只读 MDS，不另建 resolver、缺口权威或页面聚合器。
3. Session `(start,end]`、首分钟标签转换一次、不跨休市拼桶；合法短尾 completed，真缺分钟失败。Calendar/Session/Map 不足不推断为行情缺失；分钟不继承 D1/W1 缺价豁免。
4. 计算前缀、owner 有效区段、图表窗口、统计窗口分开。历史展示验收自 `max(2023-01-01, 品种上市日)`；同合约预热依公式完整前缀核验，不跨合约借值。
5. 参数仍按所选周期 Bar 数，不换算钟表时长、不寻优；新周期复用公式不等于原站分钟 parity。回看重绘与当时可知 Action 分开，不把所有绘图点都要求成因果事件。
6. 主力切换、同合约 owner 重入、质量断点按稳定身份处理；预热 HOLD 不补造 BUILD。震荡同 Bar CLEAR 后 BUILD，初始无入场 CLEAR、OPEN、换月/数据中断分别保持原合同。
7. 单策略参考价继续使用趋势慢线 B、震荡 BUILD Low/CLEAR High；价格/收益 Decimal 字符串。零费用零滑点 long/flat 页面参考不变，不制造样本末尾清仓。当前页面已有年化展示，保留既有版本与有效性条件并标明页面外推，不能称账户年化；不因分钟窗口很短自动宣称高收益。
8. 主图、辅助、参考绑定同一快照；quote 与策略时间分开；跨周期背景显示来源周期、bar_end/as_of。时区统一 Asia/Shanghai，夜盘另列 trading_day，负收益保留负号。
9. 双策略是本轮正式设计范围，与单策略共用相同 completed 输入和 cutoff。综合解释默认分为当前分钟状态及带来源时间的日周背景；没有分钟适用证据的评分/价格显示 EVIDENCE_REQUIRED 或 UNOPENED，不把周日评分改名为分钟评分。日周 AI 四组合保持原范围，扩展候选会改变归一化评分，分钟 AI 另行研究。
10. 历史与 Live 分离，先历史产品后盘中观察；checkpoint、快照不能跨 source/formula/adapter/period 身份复用。来源 1m 修订要检查已有 5m 及其他派生/Reference 消费者。
11. 所有后续生产动作只在交办目标覆盖时执行；本次“列开发计划”不启动下载、apply、build、migration、发布或 Runtime。授权存在时在机器校验通过后连续执行，不要求逐批次重复批准。
12. 每品种固定 4 输入、8 基础策略、4 融合、12 页面组合；剩余 21 品种总计 84 输入、168 基础策略、84 融合、252 页面组合，仅用于进度汇总，不作为整批运行任务。暂缓项仍留在 21 的分母中。旧 60 品种及黑色批次矩阵保留历史身份，不能改写成新四周期的完成证据。

### 双策略与原站差异合同

- 双轨图分别显示趋势与震荡 Marker、参考价及来源；图例可见标签数不是完整事件数，更不是融合交易数。遮挡或缩放不得改变后台事件和收益。
- 融合维持一份 long/flat 参考状态：已有参考仓且任一来源 CLEAR 则清；随后空仓且任一来源 BUILD 则建；同向优先震荡，允许跨策略配对，不重复加仓。同根两个动作使用稳定 action 顺序和独立 ID。
- 不跨物理合约、owner 或 calculation segment 配对；无自身入场的来源 CLEAR 是否可退出另一来源建立的融合仓，继续沿用现有融合合同。OPEN 保留，不能用样本末端或新主力价格伪造退出。
- 原站普通回测末根强制估值，本地 ReferenceTrade 不强平；原站收益窗口按退出日，本地维持 `entry_in_window_v1`。披露差异，不以逐页收益相等作为本地参考模型验收。
- 原站震荡图表路径有 `soldThisBar` 限制，`runOscBacktest` 可同根 CLEAR→BUILD；本地保持 accepted 公式合同。若以后调整可见图表 parity，另立展示证据/版本，不能静默改变交易配对。
- 单策略已实现的事后理论值按现有独立版本保留；融合理论值本轮不新增，明确不适用，不能套用普通融合结果冒充。做空/双向交易需独立候选、公式及研究证据，不由期货能做空推导。

## 模块与职责

下列目录缩写仅用于路径说明，不是环境变量：Core=`packages/quant-core/guiyi_quant/newow/`；API=`services/quant-api/app/market_data/newow/`；Web=`apps/quant-web/src/`；NT=`services/quant-api/tests/newow/`；RT=`services/quant-api/tests/reference_trading/`。

| 入口 | 本轮职责 |
| --- | --- |
| Core `product_contracts.py`、`product_identity.py`、`product_adapters.py`、`product_auxiliary.py` | 周期身份、分钟校验、两套基础策略/副图输入与分段，不复制公式 |
| API `product_query.py`、`product_reader.py`、`readiness.py`、`readiness_composition.py` | 精确窗口、完整前缀、只读依赖矩阵 |
| `services/quant-api/app/market_data/aggregation.py`、`session_clock.py`、`historical_data_manager.py` | 唯一分桶、来源/派生计划、恢复与维护 |
| Core `reference_trades.py`、`reference_statistics.py`、`fusion_reference.py`；`services/quant-api/app/reference_trading/` 现有模块 | 两套参考投影与融合、bounded build/checkpoint、完整曲线和持久化分页 |
| API `product_service.py`、`product_release.py`；`services/quant-api/app/schemas/market_newow_product.py`、`app/api/market_newow.py` | 同快照响应、能力与开关，旧版本拒绝/兼容 |
| Web `api/newowProduct.ts`、`types/newowProduct.ts`、`utils/newowProductTypes.ts`、`composables/useNewowProduct.ts`、`components/market/detail/newow/` | 周期切换、分页、请求取消、时间/状态/统计展示 |
| `scripts/newow_four_period_readonly_audit.py`、Newow readiness CLI | 复用报告入口，不新增第二套数据审计真相 |

不预设 migration；P5b 先核对既有 schema 对周期和 stream 的表达能力，仅在无法表达本合同且有具体证据时纳入必要迁移及恢复测试。

## Review Focus

- 同一 trading_day 多根分钟 Bar：P3/P5a 允许有序分钟，不放松 D1 日期约束；新增重复/乱序、同日分页回归。
- owner 重入与预热时间回退：P5a 每个 owner/calculation segment 独立定位已发生断点，验证初始 HOLD 与无入场 CLEAR。
- 一个源 revision 改变、其他周期尚未重建：P4/P5b/P5c 阻止旧 token/资产混读，验证 5m 消费者影响与部分成功恢复；双策略两来源必须同 revision。
- 同 Bar CLEAR/BUILD 与历史/实时交界：P5a/P5b/P9 验证顺序、身份、重启幂等及无入场时不造交易。
- 切周期后迟到响应和大规模 5m 结果：P5b/P5c/P7 验证取消、游标、完整统计与分页独立，不以截断计算换取性能。

## 顺序与执行方式

当前只执行 `P7-01 → P7-02 → … → P7-21`：一个品种完成或安全暂缓后才进入下一个。复用 P0–P6 已完成能力；每个品种只核对自身必要依赖，不重跑整套研发阶段。P8/P9/R1/R2 仍为后续独立交付，不作为本轮历史候选收尾前置。

### 能力阶段索引（P0–P6 已完成，不作为新任务重派）

本表保留原能力拆分和代码定位；P0–P6 的旧周期/大矩阵数值是历史实施依据。当前品种任务、周期及分母统一看 P7，不需要为每个品种再建 Spec/Plan。

| 编号 / 任务名称 | 必需依赖 | 本任务交付及完成判定 | 建议执行档位 |
| --- | --- | --- | --- |
| P0 基线与共享阻塞核对 | 无 | 冻结源码/数据身份、确认文件归属，列出 RB 与本轮相关阻塞；每个阻塞有证据，不沿用旧矩阵结论 | Sol Medium |
| P1 四周期身份与能力合同 | P0 | 新周期端到端可识别；旧身份稳定；候选入口与正式开放分离；确定以下接口表 | Sol High |
| P2 四周期数据依赖审计 | P1；最终复核还需 P3/P5a | 初盘列现存数据及未知；复核输出 240/480/240 分母、精确缺口与共享源计划；零生产写入 | Sol High |
| P3 Session 与分钟窗口 | P1、P2 初盘 | Session 精确端点、同日时间游标、合法短尾和真实缺分钟区分；日周分页不回归 | Sol High |
| P4 同源维护与恢复工具 | P2 初盘、P3 | 同源去重、只补真实缺口、revision 失效与失败恢复；隔离测试和 dry-run 通过；不执行正式补数 | Sol High |
| P5a 趋势震荡分钟计算 | P1、P3 | 8 个基础组合及适用副图，分段/预热/同根动作正确；batch/增量/恢复一致 | Sol High |
| P5b 参考构建与查询容量 | P2 最终复核、P4、P5a | 分钟单策略完整参考、快照、分页、恢复与容量实测；不请求时全历史重算 | Sol High |
| P5b-F 双策略融合完整化 | P5b | 4 个融合组合，完整统计/曲线不受 200 条限制；两来源同快照，近一年列表独立分页 | Sol High |
| P5c API 与四周期页面 | P1/P3/P5a/P5b/P5b-F | 趋势/震荡/双策略、分钟标签、背景角色、记录/曲线/主图独立，迟到请求隔离 | Sol Medium；时序部分 High |
| P6 RB 与期货边界纵向验收 | P2 最终复核、P4、P5c | 首品种 12 个模式结果逐项有证据；日盘/长夜盘/上市/换月/质量断点样本覆盖 | Sol High |
| P7 逐品种闭环 | 已完成能力与当前品种依赖 | 剩余 21 品种串行；每次 4 输入、8 基础、4 融合、12 页面；完成或安全暂缓后继续下一项 | Sol Medium；时序/恢复问题 High |
| P8 历史分钟版交付 | P7；先行小范围交付可依 P6 | 冻结声明范围，测试/Review/集成；任务包含发布时完成发布与切换，自然证据单列 | Sol High |
| P9 盘中 completed 观察 | P8 历史正式交付 | 历史/Live 接缝、增量/重启/修订、实际水位与自然观察；不自动增加通知或订单 | Sol High |
| R1 分钟因果研究适配 | P5a/P5b-F、P6 冻结样本 | 独立融合因果模型、执行/成本事实、逐笔差异归因和无未来性证据 | Sol High |
| R2 OOS 与 Walk-forward | R1、所评估样本数据通过审计 | 冻结实验和留出窗口，形成品种×周期×模式研究结论；证据不足允许不出收益 | Sol High |

模型档位按 `docs/DEVELOPMENT.md`：高风险时序、配对、数据恢复、撮合和研究方法做独立 Review，建议 Astra Medium/High；普通 UI/文档自审或按风险安排。无需为本计划创建任何线程，owner 可按编号自行分派。

### 三条交付线及里程碑

| 里程碑 | 包含任务 | 达成后可以声明 | 仍不能声明 |
| --- | --- | --- | --- |
| M1 候选计算闭环 | P0–P5a，P2 最终复核 | 四周期输入与基础算法候选成立 | 已有完整页面/全量数据 |
| M2 首品种历史产品 | P5b、P5b-F、P5c、P6 | RB 或经审计替代品种的 12 个模式结果完成验收 | 60 品种完成/因果盈利 |
| M3 优先品种候选收尾 | P7 | 分别报告已闭环、部分完成、暂缓和未开始品种；正式交付另按 P8 | 全 60 品种完成/正式分钟开放/自然盘中闭环 |
| M4 盘中观察 | P9 | 已完成分钟的实时观察范围和新鲜度有证据 | Paper/Shadow/真实下单 |
| MR 因果研究 | R1、R2 | 对冻结研究集合给出合格、淘汰、继续观察或证据不足结论 | 自动晋升或修改 active 策略 |

历史页不等待 OOS 才能作为非执行参考交付；研究通过也不跳过页面、数据或 Runtime 验收。P8 可先发布通过 M2 的精确范围，其余品种继续 P7；不能把这个先行版本写成 M3 完成。

### 接口交接表（拟实现合同，不代表已有 API）

| 合同 | 所属任务 | 下游需要的保证 |
| --- | --- | --- |
| 周期/模式/section capability | P1 | 显式 `1m/15m/30m/60m`，trend/oscillation 与 dual/fusion 区分；支持、数据就绪、正式开放分开表达 |
| 分钟窗口与 chart cursor | P3 | 带时区严格排他 `chart_before`，绑定频率、快照和 bar_end；日周原合同保留 |
| Source plan / revision | P2/P4 | 物理合约、owner 范围、Session/Calendar/Map 身份、源 revision/hash、派生版本；同批源请求去重 |
| StrategyReplay | P5a | 同源确定 frames/actions，明确 warmup、observation eligibility、physical/calculation segment 与确认时间 |
| 单策略 reference snapshot | P5b | 稳定 trade ID、完整 summary、曲线、独立 records cursor、cutoff；同根动作按稳定次序排列 |
| 融合 reference snapshot | P5b-F | 两个源策略版本、fusion model、input hash、共同 cutoff；完整结果与列表分离；条目有 entry/exit trading_day |
| Web response identity | P5c | 图/副图/参考不混快照；背景可独立缺失并显示来源；窗口规则后端权威，UI 不重算资格 |
| Forward seam | P9 | historical/observation 分离，重复幂等、冲突失败、缺口不推进；新 observed_at 不伪装旧时点可知 |
| Research result | R1/R2 | dataset/run/formula/execution/cost/roll 身份齐全，独立于页面 reference_model；无执行事实则显式不足 |

P1 固定 schema 名称、字段类型与版本；P3/P5b/P5b-F 各自提供机器可解析示例和合同行为测试供下游使用。游标使用既有项目机制，须包含稳定排序平局键并校验身份；不可按页面位置或自然日期猜下一页。

### 并行限制与任务交接

- 默认一个任务修改共享核心代码或正式数据。P1、P3、P4、P5a、P5b、P5b-F 都会影响共享身份/输入，不安排多个会话同时修改这些实现。
- P1 接口冻结后，P5c 可提前做独立 UI fixture 和测试准备；P2 可做只读盘点。与实现并行的 Review 只读，不各自修同一文件。原站证据、文档核对也可并行。
- P5c 的 `product_service.py`、schema、capability 修改须等 P5b-F 交接后进行。任何真实维护、Canonical/Catalog 更新和 release/Runtime 切换串行，避免审计使用混合 revision。
- 研究线可以在 P6 冻结数据快照后与 P7 并行，只读引用冻结输入；不能因 P7 补数让进行中的 OOS 自动换数据。
- 每个任务交接只需：精确 commit、修改路径、实际测试命令及结果、接口/样例、相关数据 snapshot/hash、剩余阻塞。复用本计划和既有任务记录，不为每次交接再建多套报告。
- 接收者核对依赖 commit 已进入所用分支，再开始。数据修订使既有 evidence 失效时重跑受影响验证，不把老测试结果移植到新 SHA。

### 通用分派文本

> 执行本文件的【任务编号和名称】，先读取设计合同及该任务依赖，核对最新 develop、worktree、dirty state 和交接证据。仅完成该任务的修改范围、行为测试、自审及必要独立 Review；保留无关修改。交付精确代码身份、实际测试与剩余项，不把计划中的命令写成已执行。默认本任务是代码/隔离验证；P6/P7 的正式数据操作、P8 的发布切换、P9 的运行启用，按本次交办明确的目标执行，未交办部分不自行扩大。任务内已授权步骤不重复请示；重要合同歧义先列证据和选项。

分派 P6/P7 时注明“隔离验收”或“包含精确缺口的正式维护与读回”；分派 P8 时注明“候选交付”或“发布并切换”；分派 P9 时注明“实现与隔离验证”或“启用小范围观察并自然验收”。这些说明定义任务范围，不要求执行途中再次指定已可由证据推导的 hash/commit。

P2 的初盘只证明现有可读窗口/元数据，完整依赖结论必须使用 P3 的权威窗口和 P5a 的实际公式要求。P4 无缺口时只验证工具及复用现有产物，不为了任务完整重复下载。P0 的自然运行证据收集可与隔离开发并行，但共享代码与生产维护默认串行。普通小改动自审；数据时序、策略状态、参考配对、checkpoint 和生产计划独立 Review。

每个代码任务按“先补行为回归 → 运行并确认目标失败 → 最小实现 → 定向验证 → diff/静态检查 → 按风险 Review → 范围内提交”的顺序执行。提交只暂存该任务路径；P0/审计/操作记录不机械执行 TDD。后续命令均是待执行入口，实际执行结果见任务记录，下方命令清单仍为可重用入口。

## P0：确认现场与共享依赖

**范围：** 只读 Git、STATUS、P9/日周 evidence 和当前配置身份，不修改产品代码。

- [x] 重新核对 branch/HEAD/worktree/dirty、develop 依赖，确认 ReferencePanel 等其他任务改动的集成状态；实施代码需要隔离时再建立 worktree，本轮文档不为此创建额外树。
- [x] 从当前生产只读身份确认 Canonical 根、Catalog、正式版本、Reference reader/worker；不输出凭据。
- [x] 将 P9 503、旧 unknown、周审计问题按“分钟共享依赖 / 无关旧问题 / 需现场核对”分类；只把实际影响试点的项列为前置。
- [x] 确定首个试点候选 RB，记录输入量、当前窗口读取/构建的耗时、内存与预算，固定后续容量对比环境；不能以旧 240 可读推定 RB 可直接开通。

**出口：** 当前依赖与共享文件归属清楚；不重跑已经完成的日周工作。源码开发不等待尚未发生的自然事件；影响正式切换的证据留到 P8。

## P1：周期、身份与能力合同

**修改：** Core `product_contracts.py`、`product_identity.py`；API `product_release.py`；Newow canonical；相应 schema/type 定义。
**测试：** NT `test_product_contracts.py`、`test_market_newow_product_api.py`、`test_product_readonly_compatibility.py`；Web `tests/newowCapabilities.test.ts`、`tests/newowProductTypes.test.ts`。
**接口：** `ProductFrequency` 扩展 1m/15m/30m；既有 `build_product_identity(product, strategy, frequency, *, input_quality_policy) -> ProductIdentity` 接受新周期并保持旧身份；四周期集合显式传递，不能靠 `tuple(ProductFrequency)` 意外扩大默认查询/开放范围。

- [x] 补测试：1m/15m/30m/60m 身份不同，旧 D1/W1/60m ID 稳定；非法周期拒绝；新周期正式请求保持关闭，候选入口可显式选择。
- [x] 建立 2×4 基础策略与 1×4 融合参考表，分别标记工程支持、原站 parity、预热/重绘、是否正式开放；杯柄仍沿用既有适用范围，主升浪分钟不纳入本轮。
- [x] 实现枚举、adapter/schema/capability 版本传递与验证，不改变公式参数；分钟质量/适配版本按既有命名登记，旧 token 不得伪装新合同。
- [x] 运行上述定向测试及 OpenSpec 校验，自审合同与 API 一致后提交。

**出口：** 新周期可以被严格识别与候选测试，正式能力不因枚举自动开启。

## P2：来源盘点与精确依赖矩阵

**修改：** API `readiness.py`、`readiness_composition.py`；`scripts/newow_four_period_readonly_audit.py`；`services/quant-api/app/guiyi_cli/data_commands.py`。
**测试：** NT `test_readiness.py`；`services/quant-api/tests/data_foundation/test_newow_readiness_cli.py`。
**接口：** `NewowReadinessAudit.run(ReadinessRequest(..., frequencies=四周期)) -> dict` 显式枚举 240 输入项/480 基础策略项/240 融合参考项；未计算项保留 NOT_EVALUATED，附窗口、owner、source identity、预算及 consumer 关联。基础输入 READY 不自动推出融合 READY。

- [x] 补测试：晚上市起点裁定不制造上市前缺口；同合约重叠源窗口去重；Map 缺失不变成 provider 目标；预算超限的未检查项不填零。
- [x] 实现初盘及复用量/缺源/缺派生/元数据/冲突/预热/未支持分类，区分逻辑 owner 窗口与完整物理前缀。
- [x] P3 完成后重算精确端点依赖；P5a 确认公式预热后补齐策略级证据，不拼接异日快照冒充同截点矩阵。
- [x] 运行定向测试；后续任务包含真实审计时再固定数据身份和 as_of 执行只读矩阵，报告实际请求/写入均为零。

**出口：** 来源请求、派生目标、物理前缀与资源预算可以逐项解释；未知没有被包装成 SOURCE_READY。

## P3：Session、完成端点和分钟分页

**修改：** API `product_query.py`、`product_reader.py`；必要时修正共享 `aggregation.py`、`session_clock.py`；API/schema 游标传递。
**测试：** `services/quant-api/tests/data_foundation/test_aggregation.py`、`test_historical_session_window.py`、`test_session_anchor_repair.py`；NT `test_product_reader.py`、`test_older_chart_windows.py`、`test_product_snapshot_cache.py`。
**接口：** 保留现有按日期查询的 D1/W1 合同；分钟图表复用可选、绑定 snapshot 且严格排他的 `chart_before: str | None` opaque cursor，内部端点为带时区 datetime，与 snapshot identity 绑定。日期范围仅用于权威存储读取，最终裁剪按 Bar 端点；独立 reference `history_before` 游标不混用。

- [x] 补测试：09:00–10:15 Session 的 60m 端点恰为 10:00/10:15；09:01 不丢失；删除应有 1m 则失败；不会跨休市拼桶。
- [x] 补测试：长夜盘跨日/月/年、假日无夜盘、历史 Session 变化、未完成/未发布桶和乱序重复；使用权威预期端点，不写死每天根数。
- [x] 用 `expected_bar_ends` 替换 reader 的“60m 每天 4 根”估算，分开图表、统计、prefix、completed cutoff。
- [x] 实现 `chart_before` 的 schema、reader 与 cursor 校验：同日多页无重无漏；错周期/旧快照 token 拒绝；翻页不改变计算和统计。
- [x] 运行上述组，独立 Review 数据时序；如果现有聚合器满足合同，保留实现，只追加必要回归，不顺手重构。

**出口：** 分钟读取有完整时间合同，当前合法尾桶和真正缺分钟可区别。

## P4：去重维护、来源修订和失败恢复

**修改：** `services/quant-api/app/market_data/historical_data_manager.py`、`app/guiyi_cli/data_commands.py`；相关维护 canonical。
**测试：** `services/quant-api/tests/data_foundation/test_historical_data_manager.py`、`test_daily_maintenance.py`；NT `test_readiness.py`。
**接口：** 复用 `ContractWarmupRequest/Plan/Result` 和 `HistoricalDataManager.contract_warmup`。保留旧单频 request/hash 的校验；先支持显式 1m/30m，再以明确 consumer scope 合并同批来源窗口，计划继续区分 direct/derived count、source/target frequencies 与精确 hash。

- [x] 补测试：四周期同源只获取一次；仅派生缺失零 provider；不再将 60m 目标数乘 60 当来源缺口量。
- [x] 实现来源去重、冻结端点、预算与维护互斥；1m 修订后定位所有受影响派生和参考依赖，包括已有 5m。
- [x] 补故障测试：源提交成功/派生失败、提交后结果未知、进程中断、重跑复用已提交项、锁竞争及预算耗尽；不声称跨周期/分区整体原子成功。
- [x] 运行离线/隔离测试与 dry-run 校验，独立 Review。生产恢复保留旧不可变版本、指针 preimage 与幂等边界；unknown 必须只读查明，不能盲重试。

**出口：** 工具能按精确计划复用、派生、恢复；实际下载/apply 留在目标覆盖的 P6/P7 阶段。

## P5a：趋势、震荡与辅助指标的四周期计算

**修改：** Core `product_adapters.py`、`product_auxiliary.py`；API reader 与辅助输出适配；仅在真实调用路径需要时调整 `engine.py`。
**测试：** NT `test_product_adapters.py`、`test_product_replay_invariants.py`、`test_engine_causality.py`、`test_main_rise_page_v1.py`、`test_reference_interruptions.py`。
**接口：** 复用 `replay_step(identity: ProductIdentity, state: ProductReplayState, product_bar: ProductBar, *, verified_lifecycle: bool=False) -> tuple[ProductReplayState, StrategyFrame | None, tuple[str, ...]]` 与 batch replay；不创建第二套策略公式。

- [x] 补测试：同交易日连续分钟可推进；重复相同输入幂等，重复身份不同内容和乱序失败。分钟适配不得放松独立 D1 Engine 的日期约束，也不把 D1 专属能力整体移入分钟。
- [x] 逐策略/副图冻结实际 warm-up、完整 prefix 与适用项；在真实短段上分别验证当前可计算和历史 WARMING。
- [x] 验证 owner 重入、物理切换、断点时间回退；预热 HOLD 不造 BUILD，初始 CLEAR 证据不跨 owner/cutoff 重用。
- [x] 验证同 Bar CLEAR→BUILD、Hint 不改变参考持有、批量/增量/checkpoint 恢复一致；对因果输出验证 prefix invariance，对重绘图层验证确认时间及独立标签。
- [x] 运行定向与原公式金样回归，独立 Review；把实际策略输入要求回填 P2 依赖矩阵。

**出口：** 8 个基础策略组合可独立计算，预热/适用性如实报告；主升浪测试仅回归既有行为，不新增分钟能力；不以原站截图宣称数值一致。

## P5b：统一参考流、快照构建与容量

**修改：** Core `reference_trades.py`、`reference_statistics.py`；`services/quant-api/app/reference_trading/contracts.py`、`planning.py`、`service.py`、`inputs.py`、`persisted_newow.py`、`presentation.py`、`source_identity.py`；复用既有 checkpoint 模块。
**测试：** NT `test_reference_trades.py`、`test_reference_statistics.py`；RT `test_newow_historical_driver.py`、`test_newow_persisted_query.py`、`test_checkpoint_parity.py`、`test_revision_rebuild.py`、`test_multi_owner_historical.py`。
**接口：** 既有 stream identity 增加新 frequency 取值，strategy/formula/reference_model/adapter/source proof 继续完整绑定；输入为 P5a 的确定 replay，输出为同 cutoff 的 reference revision、summary、cursor，保持原交易 ID 稳定规则。

- [x] 补测试：不同周期隔离；entry identity 在 OPEN→CLOSED 和翻页时稳定；换月/中断不造退出，非 CLOSED 不计 CLOSED 统计。
- [x] 接入 bounded historical build 与恢复，复用既有 projector/reducer；旧 source/formula/period checkpoint 必须拒绝。分钟正式查询不增加 on-request 全历史重放路径。
- [x] 扩展实际统计起止、样本量、OPEN/CLOSED/interrupted/unpaired 分类及来源截止；保留当前窗口计入和累计算法，不改收益语义。
- [x] 核对 P9 reader/build 的实际阻塞并处理本轮必需部分；既有 schema 能表达则不新增 migration。读回成功后才切换声明范围 reader，不默认切全局旧流。
- [x] 容量验证分别跑 RB 完整四周期构建、500 根图表读取、200 条参考分页；记录固定环境的输入量、耗时/峰值内存、冷/热请求与取消行为。请求预算/上限沿用已冻结合同，若不足先据测量说明取舍，不能截断 prefix/统计以通过。
- [x] 运行离线及必要的一次性 PostgreSQL 隔离测试、独立 Review；skip 或基线失败单列。分钟 fusion 在下述完整曲线和分页验收前保持关闭，旧周期回归。

### P5b-F：融合结果完整化（分钟双策略必需）

**修改：** Core `fusion_reference.py`；API `product_service.py`、schema、现有 reference 构建/查询模块；Web `api/newowFusion.ts`、`NewowFusionPanel.vue`。
**测试：** NT `test_fusion_reference.py`、`test_reference_statistics.py`、`test_product_snapshot_cache.py`；RT `test_newow_persisted_query.py`、`test_checkpoint_parity.py`；Web `tests/newowFusionPanel.test.ts`、`tests/newowReferenceCurve.test.ts`、`tests/newowReferenceWindows.test.ts`。
**接口设计：** 在既有融合 API 增量提供 `summary`、`curve`、`items`、`next_cursor`、`reference_revision`；都绑定 product/frequency、两个 source formula/profile、fusion model、input hash、cutoff 和统计窗口。同一构建输入只读取一次，趋势/震荡 replay 各一次；融合依既有 reducer 消费确定事件。复用既有快照存储，不另建数据库或第二套行情链。

上述输出已实现并在首品种独立读回；传输 schema/投影版本随接口升级；不改变配对及算术时保留融合业务 model 版本。若实际实现改变业务语义，则先更新 canonical 和 model 版本，不能用传输升级掩盖。

- [x] 先补超过 200 条（至少 201/1000 条）融合记录的回归：完整统计与曲线末点一致；列表 page_size 不改变 summary；跨页同一时刻 CLEAR→BUILD 不重复、不漏项。
- [x] 保持 `fusion_reference_comparison` 旧调用结果兼容；抽出内部完整结果供构建使用，分页只作用于 delivery，不再让 `[:200]` 决定曲线可用性。日周调用也回归，不建立永久双 reducer。
- [x] 曲线读取完整 CLOSED 集合；大规模展示可采用有误差说明的显示抽样，但精确统计、极值和原始记录定位始终来自完整投影，缩放不重算交易。图表页只读 bounded 可视窗口。
- [x] 记录返回 entry/exit trading_day 与 bar_end；窗口 membership 由后端依既有合同计算，前端不再用自然日期重算。补周五夜盘归属下一交易日、跨月夜盘及窗口边界回归。
- [x] 近一年列表独立分页；曲线点可按稳定 ID 读取未加载记录；统计窗口变化不改主图与固定列表范围。OPEN/中断单列，断点不伪造 CLOSED。
- [x] 融合复用已保存的两基础流；checkpoint 保存融合状态，manifest 冻结两个来源 stream/revision/seq 和完整输入证明，不重复保存基础 kernel 状态；双源缺任一、revision 不同或截止不一致时融合不可用，仍可单独显示已验证单策略。
- [x] 用同一 input hash 对比完整重算、分块、增量、重启恢复；冷热查询测量证明不会每次 1m 页面请求重算全历史。未通过则保持该模式未开放，不用缩短样本替代。

**出口：** 4 个融合组合与 8 个基础组合形成首品种 12 个模式结果；完整收益不再受 200 条列表限制。

**出口：** 一个周期的构建/恢复/分页不污染其他周期；完整统计不依赖图表长度，分钟规模可承受且有实测。

## P5c：API 与 Web 四周期页面

**修改：** API `product_service.py`、`product_release.py`，`services/quant-api/app/api/market_newow.py`、`app/schemas/market_newow_product.py`；Web 模块表所列文件及 `NewowProductWorkspace.vue`、`NewowReferencePanel.vue`、`NewowExplanationPanel.vue`。
**测试：** NT `test_product_service.py`、`test_market_newow_product_api.py`、`test_product_snapshot_cache.py`；Web `tests/useNewowProduct.test.ts`、`tests/newowProductTypes.test.ts`、`tests/newowCapabilities.test.ts`、`tests/newowReferencePanel.test.ts`、`tests/newowExplanationPanel.test.ts`；`e2e/newow-product.spec.mjs`。
**接口：** product/strategy/frequency/as_of/source proof 绑定同 snapshot token；主图、辅助、参考共享它。quote/context 使用独立且显式的 source period/bar_end；P3 的 chart cursor 与 P5b reference cursor 分离。

- [x] 补测试：1m→60m 切换时迟到旧响应被丢弃；错 token/版本/cursor 失败；刷新失败保留有标识的旧快照，冷启动无可信数据则不可用。
- [x] 实现周期切换、分钟日期时间轴与详情、夜盘 trading_day、显式负号；同周期主状态优先，周日背景独立标识。
- [x] 页面分别显示数据/计算/辅助/参考/新鲜度/正式开放状态，WARMING 不清空正常主图，背景缺失不阻断已经证明的当前主策略。
- [x] 显示统计实际起止与计数，标注零成本页面参考；图表 Marker 可定位精确记录，不按相邻标签猜配对。
- [x] 实现双轨显示与独立融合面板；统一 `1分/15分/30分/60分/日K/周K` 格式，消除非周即日的标签分支。清理切出 dual 后的副图层与旧响应，图例抽样不改变融合统计。
- [x] 综合解释显式传递日周背景角色，替换 `tuple(ProductFrequency)` 隐式扩围和非周即日的当前角色判断；按 as_of 取已完成且当时可用的背景输入，同一端点保留明确先后顺序，不见未完成日周数据。新分钟 capability 对无证据 section 明确关闭。
- [x] 运行定向前后端测试、Web build（含 typecheck/topology）和候选 fixture E2E；独立真实浏览器验收留 P6，fixture/HTTP 200 不代替真实完成。

**出口：** 候选页面完成四周期交互且错误状态可解释，正式开关仍只按已验收范围开放。

## P6：首个品种与边界样本纵向验收

**范围：** 优先 RB 经 fresh audit 确认可做首试点；之后 AP（日盘）、AU/AG/SC 选实际覆盖所需 Session 的样本、AO（上市边界）、PD/PT（短历史）。品种只是候选，历史标签不能代替当前物理段长度。

- [x] 固定代码、配置、Canonical/Catalog 身份、产品集合与 as_of，先 dry-run；缺源才按精确计划补源，缺派生才派生。目标不包含生产修复时只使用隔离输入验收。
- [x] 对实际 mutation 独立读回源/派生/指针/剩余目标，再构建参考资产；已有结果不重复提交，恢复范围与旧数据可核验。
- [x] 首试点完成 4×2 基础策略加 4 个融合结果、全部适用 section、参考记录、首屏、切周期、同日翻页和错误态；其他品种只扩边界，不代替首个完整闭环。
- [x] 增加 metadata 缺失、缺分钟、短尾、owner 重入、预热不足、源修订反例，并核对最新价格与历史策略截点分离。
- [x] 独立 Review 数据计划/时序结果；定向回归 D1/W1 和旧 60m，记录代码通过、数据通过、页面通过各自状态。

**出口：** RB 或 fresh audit 选定替代试点有完整 12 组合证据；其余边界覆盖明确，不能外推 60 品种全完成。

## P7：剩余 21 品种逐个闭环（当前执行入口）

### 队列与工作量

沿用 owner 原清单顺序，移除已完成的 JM/J/HC/I；RB 作为额外完成品种保留。旧 JM 记录中的“下一步 SF”属于当时交接，本次统一队列从 FU 开始。**同时只推进一个品种，不先批量补数据、再批量建资产、最后批量验页面。** 下表状态是本次计划初始状态，不表示不存在历史数据或资产；轮到该项时现场核对。

| 任务 | 品种 | 代码 | 本轮初始状态 |
| --- | --- | --- | --- |
| P7-01 | 燃料油 | FU | DEFERRED_DATA_BLOCKED，0/12；会话 `01a0e788-a1d4-7b82-9446-b72f5f4815ae`；[处理记录](../../tasks/fu-minute-closeout-20260928.md) |
| P7-02 | 甲醇 | MA | CANDIDATE_CLOSED，12/12；会话 `01a0e7ac-e302-7c61-bf58-828470f9c986`；[处理记录](../../tasks/ma-minute-closeout-20260928.md) |
| P7-03 | 尿素 | UR | CANDIDATE_CLOSED，12/12；会话 `01a0e81f-3f72-7c11-984a-49d28065be8e`；[处理记录](../../tasks/ur-minute-closeout-20260928.md) |
| P7-04 | PTA | TA | CANDIDATE_CLOSED，12/12；会话 `01a0e854-76a8-7b12-b6ba-4ce7dc562341`；[处理记录](../../tasks/ta-minute-closeout-20260928.md) |
| P7-05 | 烧碱 | SH | CANDIDATE_CLOSED，12/12；会话 `01a0e895-159e-70b0-aa88-df1d96fad51a`；[处理记录](../../tasks/sh-minute-closeout-20260928.md) |
| P7-06 | PVC | V | CANDIDATE_CLOSED；12/12，48/48 DATA_READY，12 disabled候选资产，API/Chrome/日周与49原图独立Review通过；[处理记录](../../tasks/v-minute-closeout-20260929.md) |
| P7-07 | 纯碱 | SA | CANDIDATE_CLOSED；12/12，48/48 DATA_READY，12 disabled候选资产，API/Chrome/日周与49原图独立Review通过；[处理记录](../../tasks/sa-minute-closeout-20260929.md) |
| P7-08 | 黄金 | AU | CANDIDATE_CLOSED；12/12，88/88 DATA_READY，12 disabled候选资产，API/Chrome/日周与49原图独立Review通过；[处理记录](../../tasks/au-minute-closeout-20260929.md) |
| P7-09 | 白银 | AG | CANDIDATE_CLOSED；12/12，80/80 DATA_READY，12 disabled候选资产，API/Chrome/日周与61原图独立Review通过；[处理记录](../../tasks/ag-minute-closeout-20260929.md) |
| P7-10 | 镍 | NI | DEFERRED_DATA_BLOCKED，0/12；首单NI2302/5m原子发布失败停止，14部分分区保留、无重试；[处理记录](../../tasks/ni-minute-closeout-20260929.md) |
| P7-11 | 硅铁 | SF | COMPLETED，12/12；四输入/八基础/四融合disabled，独立数值及61图Review通过；原生预览/日周边界保留，见[SF处理记录](../../tasks/sf-minute-closeout-20260929.md) |
| P7-12 | 锰硅 | SM | COMPLETED，12/12；4输入/8基础/4融合disabled，独立数值与61原图Review通过；自身日周/预览边界及失败证据保留，见[SM处理记录](../../tasks/sm-minute-closeout-20260929.md) |
| P7-13 | 红枣 | CJ | COMPLETED，12/12；4输入/8基础/4融合disabled，独立数值与61原图Review通过；自身日周/预览边界保留，见[CJ处理记录](../../tasks/cj-minute-closeout-20260929.md) |
| P7-14 | 鸡蛋 | JD | COMPLETED，12/12；31 owner/124 依赖READY，4输入/8基础/4融合disabled；一次维护/一次19场Chrome采集，独立数值与49原图Review通过，原生W1/报价/较早副图边界保留；[首次实测](../../tasks/jd-candidate-pilot-20260929.md) |
| P7-15 | 苹果 | AP | COMPLETED，12/12；12 owner/48 依赖READY，4输入/8基础/4融合disabled；一次维护/一次19场Chrome，独立数值及49原图Review完成，P3标注重叠及原生预热/副图/报价边界保留；[处理记录](../../tasks/ap-candidate-pilot-20260930.md) |
| P7-16 | 玉米 | C | CANDIDATE_CLOSED，12/12；21 owner/84 依赖 READY、12 disabled 候选资产；当前源码 Chrome 19 场、49 原图、独立数值/视觉审查通过；旧 OOM/409 及未证实的间歇性原因保留；[恢复闭环](../../tasks/c-candidate-recovery-20260930.md)、[原暂缓](../../tasks/c-candidate-pilot-20260930.md) |
| P7-17 | 生猪 | LH | CANDIDATE_CLOSED，12/12；21 owner/84 单元 READY、12 disabled 候选资产，API/Chrome/日周与49原图审查通过；第10场采集器故障及续采证据保留；[处理记录](../../tasks/lh-candidate-pilot-20260930.md) |
| P7-18 | 豆粕 | M | CANDIDATE_CLOSED，12/12；12 owner/48 单元 READY、12 disabled 候选资产；真实分块 Chrome 19 场、49 原图、独立数值/视觉审查通过，OOM 与续采失败证据保留；[处理记录](../../tasks/m-candidate-pilot-20260930.md) |
| P7-19 | 菜粕 | RM | CANDIDATE_CLOSED，12/12；13 owner/52 单元 READY、12 disabled 候选资产；一次 Chrome 19 场、49 原图、独立数值/视觉审查通过，审查脚本身份错误及修正证据保留；[处理记录](../../tasks/rm-candidate-pilot-20260930.md) |
| P7-20 | 花生 | PK | CANDIDATE_CLOSED，12/12；18 owner/72 单元 READY、12 disabled 候选资产；一次 Chrome 19 场、49 原图、独立数值/视觉审查通过；API wrapper 重复 coverage 失败证据保留；[处理记录](../../tasks/pk-candidate-pilot-20260930.md) |
| P7-21 | 白糖 | SR | CANDIDATE_CLOSED，12/12；14 owner/56 单元 READY、12 disabled 候选资产；一次 Chrome 19 场、49 原图、独立数值/视觉审查通过；密集标签、hover 遮挡和 W1 预热边界保留；[处理记录](../../tasks/sr-candidate-pilot-20260930.md) |

每行同一交付规格：`5m/15m/30m/60m × trend/oscillation/dual`，4 输入、8 基础流、4 融合流、12 页面组合。252 页面组合只是累计分母，禁止以“先全部跑完才能关闭一个品种”组织工作。已有五品种不并入本轮分母；剩余清单中没有 SS，也不新增其他品种。

### 单品种任务边界与复用入口

**执行授权（2026-09-29）：** owner 交办单品种历史候选闭环即覆盖必要 RQData 下载、Canonical/Catalog
修复和候选资产构建。执行者自行冻结精确合约、周期、窗口、预算、hash、attempt 和恢复边界，完成
校验后连续执行，不再等待“本次精确维护授权”。跨会话重新核对现场，不复用失败 attempt、不重做
已成功对象；未知提交、质量失败和宿主拒绝分别处理。该规则按 [AGENTS.md](../../../AGENTS.md)
长期执行，不扩大 P8/P9/R1/R2、正式 Scope、Runtime、通知或交易范围；旧拒绝与证据保留。

**文件：** 复用本计划“模块与职责”中的唯一实现；主要任务通常是数据/资产准备和真实验收，不预设每个品种都必须修改代码。事实记录复用 `docs/tasks/<code>-minute-closeout-<YYYYMMDD>.md` 和 `outputs/<code>-minute-closeout-<YYYYMMDD>/`；品种代码按项目既有大小写规范传递，输出目录小写。一个品种只保留一份任务记录和必要原始证据，完成后更新本队列与 STATUS，不提前宣布完成。

**已验证样板：** [JM](../../tasks/jm-minute-closeout-20260928.md) 的来源/派生/资产读回、API、真实 Chrome、局部回归与独立 Review；[J](../../tasks/j-minute-closeout-20260928.md) 的融合请求队列和翻主图后参考面板状态修复。`outputs/jm-minute-closeout-20260928/` 中的 `source_assets.py`、`aggregation_full_prefix.py`、`api/readback.py`、`snapshot_recovery.py`、`browser/verify_jm12.py`、`regression_recovery.py` 可作为现有验收样板，运行前必须核对本机文件和硬编码身份。改用当前品种、owner、端口、日期、hash 和 schema，不能原样执行 JM 的 apply/recovery 命令。缺少脚本时按任务记录及当前服务接口恢复最小验收入口，不自建行情 resolver。

**输入：** 当前 develop 精确 SHA、单品种白名单、显式四周期、Calendar/Session/MainContractMap、MDS 来源身份及完整计算前缀。复用 `NewowReadinessAudit.run(ReadinessRequest(...))`、`HistoricalDataManager.contract_warmup`、现有 reference planning/build/query；函数签名以当前代码为准，参数中不得使用全品种默认集合或枚举隐式包含 1m。

**输出：** 当前品种 12 项来源与资产身份、实际 API/页面读回和逐项状态，或具有精确边界的暂缓记录。候选默认关闭、固定历史时点、`realtime=false`；预览 API/Web 地址必须来自该任务环境，不接错正式服务或其他品种预览。

### 每个品种都走完这一条闭环

- [ ] **1. 冻结现场和验收范围。** 核对 branch/HEAD/dirty、已有依赖和预览进程归属；复用空闲 worktree/端口，不停其他任务进程。历史起点为 `max(2023-01-01, 权威上市日)`，首轮沿用已完成五品种的 `2026-09-24` 截止基准、`as_of=2026-09-24T07:00:00.000001+00:00`，再由权威 Session 解析该品种实际 completed 端点。不随执行日期每天追新而使已验收结果失效；新截止需要独立登记并重验受影响部分。新鲜度/盘后增量留后续目标，页面明确历史日期。
- [ ] **2. 只审当前品种的精确依赖。** 从 MDS/Map 获取 owner 和同物理合约完整计算前缀，列出已有可复用、缺派生、缺 1m、元数据冲突、质量不足。四周期同源检查去重；不验 Newow 1m 策略或页面，不对 21/60 品种做全历史预审。先核对已有 15m/30m/60m 和历史参考资产，身份一致才复用，不能照搬 JM“九条可复用”的结论。
- [ ] **3. 只处理可证明的缺口。** 缺派生且来源可信时只聚合，provider 请求为零；确实缺源时才在后续实施任务已覆盖维护的范围内生成精确源计划。维护前完成 dry-run、目标/hash/预算/锁、恢复办法校验；提交后独立读回。源修订只失效实际依赖该源的派生/资产。遇到独立难以闭合的数据问题，按下面的暂缓规则结束当前项。
- [ ] **4. 完成四频资产。** 聚合按 `(start,end]` 与当前合约历史 Session 验证；逐周期保存两基础流及一融合流。复用资产须匹配公式、参考模型、owner、source revision、输入 hash、cutoff、计算前缀与当前 schema；否则只重建失效项。融合两来源必须一致；四频 12 流全部独立读回，不用 build 返回成功替代落盘事实。统计覆盖完整冻结历史，图表窗口与列表分页不裁掉计算输入。
- [ ] **5. 验收 12 个 API/页面组合。** 每个组合实际检查主图、适用副图、Marker、完整参考统计/累计曲线、OPEN/中断、记录分页、时间/合约/快照身份。执行四周期切换、趋势/震荡/双策略切换及返回；有后续页时检查稳定 ID 无重漏、原前缀不变，主图与参考游标独立。较早主图分页单列实测状态，不能把未测写成通过；新出现的正常使用阻塞必须修复或明确保留部分完成。候选拒绝错频/旧 token 并能重新获取正确快照；实际取消/超时后恢复，不接受只有 HTTP200、空图或截图占位的验收。
- [ ] **6. 按影响验证、复核、收尾。** 当前品种日周三模式做兼容读回，背景 WARMING/NOT_APPLICABLE 如实显示，不以预热不足伪造 READY，也不把不适用副图当主策略失败。没有共用源码变化时不重跑前五品种、全量 Web 或全仓库测试；发生修复时只补对应行为回归、受影响模块与最小代表品种，风险涉及共用时序/公式/数据恢复时做独立 Review。已通过且输入/代码身份未变的证据复用，Review 可核对原始证据而不重复全部浏览器请求。完成本品种记录、必要代码集成和队列状态后，再启动下一项。

### 期货差异与定向验证

这些是需核对的边界，不是按品种名硬编码交易时间；均读取对应历史有效 Calendar/Session/合约元数据。

| 触发条件 | 验证重点 | 对应入口 |
| --- | --- | --- |
| 当前品种有夜盘或跨午夜 Session；AU/AG/NI 等重点核对 | 夜盘归属 trading_day、长夜盘完成端点、节假日无夜盘、历史 Session 变更 | 步骤 2–4；`test_aggregation.py`、`test_historical_session_window.py` |
| 日盘休市、短尾桶或某时段没有夜盘 | 不跨休市凑足根数；合法尾桶 completed；不为不存在的 Session 补数据 | 步骤 2–4；`test_session_anchor_repair.py`、`test_product_reader.py` |
| 上市较晚或新主力历史不足；SH 等重点核对 | 权威上市起点、实际完整物理预热、当前可计算与历史 WARMING 分开 | 步骤 2/4/6；`test_readiness.py`、`test_product_replay_invariants.py` |
| 主力切换、owner 重入、缺分钟、重复冲突 | 不跨合约配对、不借新主力价清旧仓、数据断点显式中断；零量与缺 Bar 不混淆，不填充价格 | 步骤 2–4；`test_reference_interruptions.py`、`test_aggregation.py` |
| 5m 记录多、同根双动作、分页后再切换 | 全量曲线/统计不受列表截断；同根次序与 ID 稳定；迟到响应不串图，主图翻页不重置参考状态 | 步骤 5–6；`test_fusion_reference.py`、`test_product_snapshot_cache.py`、Web `tests/useNewowProduct.test.ts`、`tests/newowReferencePanel.test.ts` |

测试路径前缀见“模块与职责”和下方“验证命令”；这些是出现相应代码变更时的选测入口，不要求每个品种机械重跑全部。新发现问题先补能复现该问题的定向测试，再做最小修复。

### 完成、部分完成与暂缓

- **CANDIDATE_CLOSED：** 4 输入、8 基础、4 融合及 12 页面全部有当前冻结身份下的证据；适用性、预热、原有基线风险与未测子项明确，核心闭环无阻塞，风险所需 Review 完成。不能只验 60m 后宣布整个品种闭环，不能用既有品种证据替代本品种事实。
- **PARTIAL：** 已完成的周期/模式保留，但未达到 12/12；列出实际分子及缺项，不抹掉进度，也不计入闭环品种数。
- **DEFERRED_DATA_BLOCKED：** 记录品种、物理合约、周期、owner/日期范围、错误类别、原始 evidence/attempt、已提交与未知状态、恢复前提和已完成部分。无法安全闭合时结束当前任务，转下一品种，不自动循环重试或扩大到全湖修复。SS 按这一原则继续暂缓。
- **共享故障：** `ATOMIC_PUBLISH_FAILED`、提交结果未知、锁/预算状态不清时，先停受影响写入并只读核对；确认当前失败不会污染下一品种的源、共享表、锁和预算后才能继续其 mutation。不能把“跳过”当成忽略未知写入。共用聚合器/身份/公式缺陷则先修根因，验证受影响范围；独立只读工作可以继续。
- 恢复暂缓项需要新的事实：来源问题已修复、身份可证明、失败结果已厘清或安全恢复路径已验证。没有这些变化不重新排到队首。同一失败不靠改 plan hash、重置 attempt 或缩短历史窗口绕过。

**进度记录：** 每次只报告“本品种结果；12 项完成数；新增/复用资产；真实验证；阻塞或基线限制；下一品种”。本轮汇总保留闭环/部分/暂缓/未开始之和等于 21，不以移除失败项提高完成率。不预建 21 个线程、计划文件或后台任务；不把历史候选、代码集成、正式发布、自然增量验收混为一项。

**出口：** 能闭环的品种逐个交付；其余有可续接的精确记录。本轮全部走完可声明“21 项已处理，闭环 X / 部分 Y / 暂缓 Z”，只有 X=21 才声明剩余品种全部闭环。P8 发布、P9 实时及 R1/R2 研究另按后续交办推进，不阻塞本轮已满足标准的候选收尾。

## P7 扩展：第二轮 13 品种串行历史候选闭环

owner 于 2026-09-30 交办：复用原 21 品种经验，以目标模式和新方法逐品种完成下表。
本轮独立固定分母为 **13 品种 / 52 输入 / 104 基础 / 52 融合 / 156 页面组合**；
原 21 品种队列及失败恢复证据保持，不将其暂缓项计入本轮，也不推定其已恢复。

沿用上文单品种闭环、暂缓与共享故障合同；历史窗口为
`max(2023-01-01, 权威上市日)..2026-09-24`，
`as_of=2026-09-24T07:00:00.000001+00:00`。1m 只作可信聚合来源，
分钟验收为 `5m/15m/30m/60m × trend/oscillation/dual`，保留自身日周三模式兼容核对。
复用 `scripts/newow_candidate_tools/` 的参数化身份冻结、preflight、19 场连续采集、
完整响应分块传输、index 和离线 audit；原生维护/构建、全物理前缀独立 Decimal 核对、
保存流依赖核对及逐张原图 Review 仍分别执行，工具数值 PASS 不等于闭环完成。

一次只启动下表一个品种。完成或安全暂缓、核清实际 mutation/锁/预算，释放本品种专属
API/Web/Chrome 后，再启动下一项；不预建 13 个任务或后台监控。真实下载、派生发布和
候选构建已由本次历史候选闭环目标覆盖，精确对象、计划/hash、预算和恢复证明仍须通过。
候选保持 disabled/generation=0；正式分钟开放、发布、Runtime、Scope、通知和交易不在本轮。
全部代码已存在时不为每个品种制造源码修改；实际结果与证据进入对应单品种记录和 STATUS。

owner 于 2026-10-01 续交办四品种，当前执行顺序改为 **LC → FG → AO → CU**。
四项仍归属下表原有行号，不新增或缩减原 13 品种和原 21 品种分母；其余未开始品种不因本轮自动启动。
LC已候选闭环、资源释放并集成推送develop；FG已候选闭环、资源释放并集成develop，通过303 API工具/130 Web/build，普通push/远端8777b167c读回一致；AO唯一维护出现源Decimal无法无损发布，已停批，独立安全暂缓完成、0/12；记录4640ecceb已普通集成develop150ad5e5b、308 API工具/130 Web/build通过，普通push/远端a9a8c2a3e读回一致，CU已安全暂缓0/12、记录ff23a287普通集成developca64b256，313 API工具/130 Web/build及diff/secret通过，普通push/远端1f647ba08读回一致；本轮实际2闭环+2安全暂缓，其余品种不启动；AO/CU实际候选仍阻塞，须先确定无损成交额表示与精确恢复合同。

owner 新交办的本轮优先顺序为 **PS 多晶硅 → Y 豆油 → SI 工业硅**；当前PS历史候选12/12闭环，已普通集成develop054326223并通过318 API/工具、130 Web和生产构建，push与远端精确读回一致；Y历史候选12/12闭环并普通集成develop e04cb424，323 API/工具、130 Web与生产构建通过，push/远端精确读回一致，SI已因账户配额保护安全暂缓0/12。旧AO/CU失败不重试；PS/Y沿用原13行号，SI单列补充，不改变原13/21分母。

| 顺序 | 品种 | 代码 | 当前状态 |
| --- | --- | --- | --- |
| P7B-01 | 原油 | SC | CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12；增量差分验收，见 [SC收尾](../../tasks/sc-candidate-closeout-20261005.md)，旧失败原件保持 |
| P7B-02 | 棉花 | CF | CANDIDATE_CLOSED，12/12；见 [CF记录](../../tasks/cf-candidate-pilot-20260930.md) |
| P7B-03 | 菜籽油 | OI | CLOSED；52/52维护、306621 Bar完整前缀核对；新源12 native rebuild/fresh reader通过，API12/12与152 HTTP200；Chrome19场/49原图/631索引独立核验，21213 CLOSED收益/21249 SVG点无差异；取消恢复通过、source稳定、资源与维护锁0，disabled/generation0；失败证据保留，见[处理记录](../../tasks/oi-candidate-pilot-20260930.md) |
| P7B-04 | 棕榈油 | P | COMPLETED / CANDIDATE_CLOSED 12/12；12 owner/48单元一次维护、88实际请求/360派生目标；283612 Bar根Decimal完整前缀核对，906旧文件前像/60246旧Bar/373日周保留；12 READY disabled/generation0；7f6c8fda最终API12/152、Chrome19场/49新原图/630索引、21278 CLOSED收益/21314 SVG点独立核验；两旧LEGACY_HTTP_ERROR失败保留，最终native audit与root closeout通过，source三读回一致、专属资源退出/锁0；按owner要求P后停止，未启动Y；已审修复与记录集成develop，189工具/106 Web定向测试及build通过 |
| P7B-05 | 豆油 | Y | CANDIDATE_CLOSED / DEVELOP_INTEGRATED，12/12；冻结0e7aab990双轴134 API/122 Web；页面2023-01-01..2026-09-24，12owner/48unit=45读回+3无缺口，88真实源请求/360派生；904旧bytes/70763旧Bar/371日周与Catalog保持，397新增/51扩展/0删；四频各141物理月、280580 Bar独立Decimal200全字段端点通过。8基础+4融合/current12完整state/summary/4对伙伴READY关闭generation0，complete_window_proven=false；API12/152矩阵GET/UTC7、Chrome19场49新原图/640索引、21759 CLOSED价格回报/21795 SVG独审通过，source三份55b424f6整字节一致；真实abort/timeout0.2534/409/fresh恢复通过（不证明自然TTL或完整卡片身份）、专属3PID退出/端口空闲/锁0。四趋势四震荡分钟FULL，W1转折35/120预热/震荡4交易小样本/OPEN与rollover浮动不计CLOSED保持；native VISUAL_PENDING原件保留、独立最终CLOSED及独审通过。root首次只读PS10owner模板断言失败保留，v2按Y12修正后fresh PASS，不改业务hash/window或重试生产attempt；普通merge e04cb424后323 API/工具、130 Web与build通过，push/远端精确读回一致，无OOS/可执行收益/完整fusion状态机证明；见[Y记录](../../tasks/y-candidate-pilot-20261001.md) |
| P7B-06 | 氧化铝 | AO | CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12；2026-10-06新forward88/88、154源/627派生、19条18位截断，627341Bar/22owner独审；旧1204文件/74711Bar/544日周保持。12READY disabled/generation0；API12/152、一次Chrome19场49图、28379 CLOSED/全部曲线SVG独审通过，专属资源退出/端口空闲/锁0；末轮仅12状态读回不重复全源扫描，预热PARTIAL/日周及视口局限保留。历史49/60、正式45/60；[恢复闭环](../../tasks/ao-candidate-closeout-20261005.md)，旧失败attempt不复用，无正式开放或Runtime |
| P7B-07 | 锌 | ZN | NOT_STARTED |
| P7B-08 | 锡 | SN | NOT_STARTED |
| P7B-09 | 铝 | AL | NOT_STARTED |
| P7B-10 | 铜 | CU | DEFERRED_DATA_BLOCKED / SAFE_DEFERRED，0/12；冻结准入e81693c7、独审124 API/122 Web；45owner/180单元唯一81392首CU2302/5m源Aug2022 scale24不能无损decimal128(38,18)，payload937bca9a封存；0完成/1knownfailedpartial/179未尝试，7started请求，实际12新增1m+5m各Feb-Jul2022六个月，1952旧bytes/1173日周保持，51360源端点/10272派生Bar独立Decimal200通过；failedsource active0/目录空、private0/锁0/端口释放、最终独立safe-defer通过，禁止重试/roundzero/schema绕过；记录ff23a287普通集成ca64b256、313 API工具/130 Web/build及diff/secret通过，普通push/远端1f647ba08读回一致 |
| P7B-11 | 碳酸锂 | LC | CANDIDATE_CLOSED / DEVELOP_INTEGRATED，12/12；48维护41读回+7无缺口/87请求/356派生；819旧文件29997旧Bar346日周保持，179653 Bar独立Decimal；12 READY disabled/gen0；71198 clock修复后API12/149、Chrome19/49/461索引、12399 CLOSED/12433 SVG通过；source三fresh一致/资源锁0，首失败保留；上市预热PARTIAL/DD不可用/W1震荡0交易保留；任务a01ce928→develop2b25cec63，298 API工具/130 Web/build通过，push读回d2362b0bf；见[LC记录](../../tasks/lc-candidate-pilot-20261001.md) |
| P7B-12 | 多晶硅 | PS | CANDIDATE_CLOSED / DEVELOP_INTEGRATED，12/12；develop739644666→冻结c214b9d5，独审129 API/122 Web；窗口2024-12-26..2026-09-24、10owner/40unit=33读回+7无缺口，68真实源请求/282派生；545旧bytes/24290旧Bar/244日周保持，309新增/41扩展/0删；四频各100物理月、130232 Bar独立Decimal200通过；8基础+4融合/current12完整state/summary/4对依赖READY关闭generation0，complete_window_proven=false。API12/149GET/UTC7、Chrome19场49原图/358索引、6864CLOSED价格回报/6898SVG独审通过，source三份264d9f84整字节一致；原生cancel/timeout0.251/409与fresh恢复通过（不证明TTL/完整卡片身份），专属3PID退出/端口空闲/锁0；四趋势FULL/四震荡PARTIAL和W1转折44/120、震荡0CLOSED指标—保持，未声明OOS或可执行收益；独立最终REVIEW_COMPLETE_CANDIDATE_CLOSED；普通merge054326223后318 API/工具、130 Web与生产构建通过，push/远端精确读回一致 |
| P7B-13 | 玻璃 | FG | CANDIDATE_CLOSED / DEVELOP_INTEGRATED，12/12；6fd1da613 singleton双轴Review/114API/122Web；窗口2023-01-01..Sept24；12owner/48维护45读回+3无缺口/88请求/360派生，906旧bytes/58989旧Bar/373日周保持，397新增/51扩展/0删；四频各141物理月/284389 Bar独立Decimal；12完整state/summary/4伙伴READY disabled/gen0/completewindowfalse，分钟基础页面覆盖FULL；API12/152/UTC7，Chrome19/49原图/675索引、23557 CLOSED/23593 SVG独审通过，source三fresh443f2a77一致/资源锁0；W1 35/120与震荡11预热区段/1交易及显示、融合、取消TTL局限保留，原生维护/build/API/采集无失败重试；任务b7d204ccd→develop2de2e2f7f，合并态303 API工具/130 Web/build及diff/secret通过，普通push/远端8777b167c读回一致；见[FG记录](../../tasks/fg-candidate-pilot-20261001.md) |

逐项记录完成分子及闭环/部分/暂缓/未开始，总和始终等于 13。仅完成 12/12 且必要
独立 Review 通过才记 CANDIDATE_CLOSED；安全暂缓只代表本项已处理，不代表闭环。

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

## 独立研究出口（不与页面上线混为一项）

已有研究模块继续按品种×周期×趋势/震荡/融合分别评估。页面支持不是 OOS 通过，也不自动进入 Runtime 策略候选。融合需使用同一事件规则建立独立因果研究身份，不把两套回测收益相加。

- 完成 Bar 产生信号后，只能在下一可执行时点按物理合约研究成交；同分钟高低价同时触及不能推导真实先后，按已有撮合合同保守处理，缺少执行事实则明确不足。
- 成本含具体合约乘数、tick、手续费（含平今/平昨差异）、滑点；涨跌停、零成交量与缺盘口不得假定总能成交。换月中断或显式换月规则独立版本化。
- 比较窗口、截止、可用历史与成本假设保持一致，同时报告频率各自样本量、换手、收益百分点/研究净值的不同口径、回撤、成本敏感性及中断比例。不能凭原站一页累计或分钟年化选最佳周期。
- 按时间滚动 OOS/Walk-forward；分钟样本按交易日/持有区间隔离，跨分割边界的交易及标签不得泄漏。参数仍以 Bar 数计，寻优或分钟 AI 排名另立研究，不从已看过的高收益区间选择最终测试集。

### R1：分钟因果研究适配与逐笔归因

**修改：** Core `research_backtest.py`、`research_evidence.py`；API `futures_validation.py`、`futures_evidence_plan.py`、`futures_evidence_service.py`。仅当现有独立模块无法容纳融合意图时抽出小型适配器，不复制撮合引擎。
**测试：** NT `test_research_backtest.py`、`test_futures_validation.py`、`test_futures_evidence_plan.py`、`test_futures_evidence_service.py`、`test_engine_causality.py`。
**输入：** P6 冻结的物理合约分钟与 owner/quality segment、P5a 的两策略事件、P5b-F 融合规则、具有生效时间和来源的执行/成本事实。
**输出：** 固定 run_id 的研究结果与逐笔差异表；reference return、next-executable return、cost/slippage impact、interruption/exclusion 分列，不写回 ReferenceTrade。

- [ ] 先补同日多根研究输入、夜盘、同根双事件、下一可执行 Session、涨跌停/零量、事实缺失回归；确认旧日周研究结果不变。
- [ ] 复用既有事件与撮合入口，补分钟及融合研究身份。真实执行结果反馈给研究持仓，不能用页面假定全部成交的仓位替代；未成交后不得继续生成虚假的平仓成交。
- [ ] 将 observed_at、confirmed_at、effective_after、模拟执行时间和估值时间分开。成本/限价规则按对应时点有效事实读取，缺事实报告 EXECUTION_FACTS_MISSING，不以零费用兜底。
- [ ] 验证信号因果前缀不变性；对展示重绘输出只验证其确认时间和标记，不把它当历史已知信号。聚合端点已完成仍须满足执行严格先后。
- [ ] 按同一输入生成逐笔差异表，解释未闭合、换月、缺失执行事实与成本导致的样本差异；不要求因果交易逐笔等于页面乐观交易。
- [ ] 运行上述定向测试及高风险独立 Review，交接版本、固定样本和完整 exclusions。

**出口：** 三种模式均能在执行事实足够时产生可复算因果结果；缺事实时明确拒绝，没有“为填矩阵而补收益”。

### R2：OOS / Walk-forward 与成本敏感性

**修改：** Core `research_walk_forward.py`、`research_evidence.py`；复用 API futures evidence 入口和已有研究输出结构。
**测试：** NT `test_research_walk_forward.py`、`test_research_evidence.py`、`test_rank1_causality.py`、`test_futures_evidence_service.py`。
**输入：** R1 固定候选公式、参数、成交/成本/换月版本和经审计数据；P7 未完成时只能使用已经冻结并明确列出的子集。
**输出：** 品种×周期×模式×fold 的样本/排除项、成本敏感性、研究结果与结论，记录所有尝试过的候选，不覆盖失败实验。

- [ ] 在读取测试集收益前固定 train/validation/test 时间边界和滚动规则；新增同交易日多根数据不会被拆到不同 fold、持有期跨边界不得泄漏的测试。
- [ ] 预热仅使用当时可获得的前缀；换月、终端未闭合和缺执行事实按冻结规则归类。测试窗口不足不得缩短要求后仍声称原方案通过。
- [ ] 运行固定公式 Walk-forward，不在当前任务中自动寻优参数；如后续获准寻优，训练选择与最终留出检验须独立，并登记所有比较。
- [ ] 报告换手、交易数、成本前后、回撤、成本敏感性和分段稳定性；比较四周期时列明共同窗口与各自样本数，不能按累计收益直接排名。
- [ ] 对实验设计和无泄漏证据做独立 Review；输出“证据不足/继续观察/淘汰/可提请候选评审”，不修改 active、Scope、通知或自动晋升。

**出口：** 研究结论有冻结方法和可重算证据；盈利不是完成标准，无结果也必须有明确原因。

## 全计划验收用例归属

| 必验情形 | 负责任务 | 必须观察到的结果 |
| --- | --- | --- |
| 09:00–10:15 Session 的 60m 短尾；10:15–10:30 休市 | P3 | 10:00/10:15 合法端点，休市不拼桶、不判成缺分钟 |
| 周五夜盘、跨月/跨年、节日前无夜盘 | P3/P5b-F | Calendar/Session 与 trading_day 权威；记录窗口不按自然日期错分 |
| 缺失一个应有 1m、重复、乱序、非交易端点 | P3/P4/P5a | 明确错误；不插值、不跨频回退、不计算正式信号 |
| 同一合约离开主力后再进入；新主力历史很短 | P5a/P5b | 分段重置、正确预热、无伪造 BUILD；不使用新合约清旧仓 |
| 震荡同根 CLEAR→BUILD；双源同向及反向事件 | P5a/P5b-F | 顺序、优先价、trade/action ID、跨来源配对符合冻结合同 |
| 201/1000 条融合记录、同一时刻多动作、近一年分页 | P5b-F/P5c | 全量统计曲线不变、分页无重漏、曲线定位可读未加载记录 |
| 1m 源修订，15m 已重建而 30m/60m 未完成 | P4/P5b/P5b-F | 依赖分别失效，拒绝旧快照混读；部分结果不冒充四周期成功 |
| 进程在提交前/后终止、结果未知、锁被占用 | P4/P5b/P9 | 独立读回、稳定幂等、既有预算/次数合同；不盲重试 |
| 快速切品种/周期/dual、后台旧响应返回 | P5c | 无串图/串收益，旧图层清理；已验证当前主图不因背景缺失消失 |
| 自然 completed、断线后恢复、历史/Live 重叠冲突 | P9 | 未完成不晋升、冲突不覆盖、缺口不推进、重启结果一致 |
| 同分钟上下沿均触及、不能成交、成本事实缺失 | R1 | 不推断价内先后或保证成交；保守撮合/不足原因可解释 |
| fold 边界前后存在夜盘/持仓/预热 | R2 | 不跨分割泄漏，不借未来主力/费用/输入，实验可重放 |

性能验收使用 P0 冻结环境与既有资源预算，记录完整输入规模、构建峰值内存/耗时、500 根图表、200 条记录分页、完整曲线、冷/热请求及取消；以查询不重放全历史、分页不重算交易、超预算明确失败为硬条件。不能在未测量前承诺毫秒延迟，也不能通过截短计算前缀或统计历史达标。

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
  services/quant-api/tests/newow/test_fusion_reference.py \
  services/quant-api/tests/reference_trading/test_newow_historical_driver.py \
  services/quant-api/tests/reference_trading/test_newow_persisted_query.py \
  services/quant-api/tests/reference_trading/test_checkpoint_parity.py \
  services/quant-api/tests/reference_trading/test_revision_rebuild.py

# P5c：页面状态、请求隔离、类型与构建
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/useNewowProduct.test.ts tests/newowProductTypes.test.ts tests/newowCapabilities.test.ts tests/newowReferencePanel.test.ts tests/newowExplanationPanel.test.ts tests/newowFusionPanel.test.ts tests/newowReferenceCurve.test.ts tests/newowReferenceWindows.test.ts tests/newowDualChartDisplay.test.ts
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build

# R1/R2：仅隔离研究验证，不执行真实交易或自动晋升
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core services/quant-api/.venv/bin/python -m pytest -q -p no:cacheprovider \
  services/quant-api/tests/newow/test_research_backtest.py \
  services/quant-api/tests/newow/test_futures_validation.py \
  services/quant-api/tests/newow/test_research_walk_forward.py \
  services/quant-api/tests/newow/test_research_evidence.py \
  services/quant-api/tests/newow/test_rank1_causality.py

# canonical 修改后；当前只改规划文字，不机械运行这些业务检查
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

期望：新增回归先证明目标行为失败，实现后对应组全部通过；skip、环境错误、基线失败独立报告。PostgreSQL/Redis 隔离规则、Ruff/Mypy、fixture E2E 与真实浏览器入口按 [TESTING.md](../../../TESTING.md) 和 [DEVELOPMENT.md](../../DEVELOPMENT.md)，不连接生产跑可写测试。

每包只在既有任务记录中补充精确 SHA、命令/结果、真实 readback 与剩余 Gate，不再复制多套 manifest/receipt。代码集成前同步 canonical，任务进度有证据后才更新 STATUS；规划完成不勾实现项。

## 当前交接与实施裁定

P0–P6 已按依赖连续完成，P2 分初盘/最终复核；所有首轮勾选项以任务记录中的实际证据为准。既有 opaque chart cursor、维护恢复与基础 replay 被复用；融合复用基础保存流而非重复计算两 kernel。P0–P6 首轮实际无数据缺口，因此当时没有 provider 下载、Canonical/Catalog mutation 或全历史补数；8基础/4融合资产仅在隔离 schema 构建。P7 首批的精确缺口维护另见本批任务记录，不能沿用首轮的零缺口结论。fixture E2E 与真实 Chrome 分列，旧7项fixture失败在未修改develop逐项复现，不把旧失败包装成通过。全spec9/10，既有reference-trading段落结构失败单列，本轮Newow spec有效。

P7 首批 black + steel 正在执行，实际证据见本批任务交接；不得按本文件旧基线重新实施 P0–P6。P8发布、P9观察启用、R1/R2因果研究与OOS不属于本轮完成声明。首轮 aef3 版本的100k完整曲线与有限队列有有限样本实测预算，不能代替本批 c576 板块规模验收；SQL/hydrate不保证即时取消，正式扩展前继续验证并发/冷读预算。

2026-10-03 起处理此前未入队的品种，A 豆一已普通合入 develop `99f6c89e5`：19 owner / 76 维护单元、80 次真实请求 / 580 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 287712、15m 95904、30m 50056、60m 29236。资产身份 `0f3551c45`，页面白名单 `0a0a36f16`。W1 趋势 44/120 预热、W1 震荡 1 笔 CLOSED 保留。不计入原 13/21 分母。见 [A 记录](../../tasks/a-candidate-pilot-20261003.md)。

同日 B 豆二已普通合入 develop `9694a75a9`：27 owner / 108 维护单元、268 次真实请求 / 1072 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 416325、15m 138775、30m 72432、60m 42305。资格 `b73b5d9c5`。W1 趋势 44/120 预热、W1 震荡 1 笔 CLOSED 保留。不计入原 13/21 分母。见 [B 记录](../../tasks/b-candidate-pilot-20261003.md)。

同日 BU 沥青在 `BU2307` 5m 遇到 `ArrowInvalid` / `ATOMIC_PUBLISH_FAILED`，`BU2306` 四频已读回，该单元及之后未重试，资格未合入 develop。不计入原 13/21 分母。

同日 BZ 纯苯已普通合入 develop `2750a4263`：上市日 2025-07-08 起，8 owner / 32 维护单元、0 次新源请求 / 60 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 109185、15m 36395、30m 18996、60m 11095。资格 `9d8d3507b`。震荡上市当日 WARMING，W1 趋势 27/120 预热、W1 震荡 1 笔 CLOSED 保留。不计入原 13/21 分母。见 [BZ 记录](../../tasks/bz-candidate-pilot-20261003.md)。

同日 EB 苯乙烯已普通合入 develop `64a7c24df`：46 owner / 184 维护单元、484 次真实请求 / 1980 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 684372、15m 228124、30m 119068、60m 69546。资格 `9ef3b5aee`。W1 趋势 43/120 预热、W1 震荡 0 笔 CLOSED 保留。周线双策略首次采集未在时限内稳定，续采后收齐。不计入原 13/21 分母。见 [EB 记录](../../tasks/eb-candidate-pilot-20261003.md)。

同日 EC 欧线集运已普通合入 develop `099afa538`：上市日 2023-08-18 起，17 owner / 68 维护单元、148 次真实请求 / 602 派生月；12 条流 READY 且 disabled/generation0；API 12/12、149 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 159390、15m 53130、30m 28336、60m 17710。资格 `4d19119b8`。震荡上市段 WARMING，W1 趋势 47/120 预热、W1 震荡 2 笔 CLOSED 且历史覆盖不完整。不计入原 13/21 分母。见 [EC 记录](../../tasks/ec-candidate-pilot-20261003.md)。

同日 EG 乙二醇已普通合入 develop `887120410`：窗口 2023-01-01 起，12 owner、88 次真实请求 / 363 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 续采 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 178620、15m 59540、30m 31076、60m 18150。资格 `03cfae884`。趋势和震荡覆盖 FULL，W1 趋势 47/120 预热、W1 震荡 3 笔已完成且历史覆盖不完整。15 分钟震荡首次采集在切频时遇到快照代际冲突，续采后收齐。不计入原 13/21 分母。见 [EG 记录](../../tasks/eg-candidate-pilot-20261004.md)。

同日 L 塑料已普通合入 develop `fe671d3f8`：窗口 2023-01-01 起，12 owner、88 次真实请求 / 360 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 177102、15m 59034、30m 30812、60m 17996。资格 `93401a410`。趋势和震荡覆盖 FULL，W1 趋势 35/120 预热、W1 震荡 0 笔已完成。不计入原 13/21 分母。见 [L 记录](../../tasks/l-candidate-pilot-20261004.md)。

同日 PB 铅在 `PB2302` 5m 遇到 `ArrowInvalid` / `ATOMIC_PUBLISH_FAILED`，未重试，资格未合入。

同日 PD 钯已普通合入 develop `b9d7eb136`：上市日 2025-11-27 起，4 owner、0 次新源请求 / 60 派生月；12 条流 READY 且 disabled/generation0；API 12/12、149 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 29925、15m 9975、30m 5320、60m 3325。资格 `3ce872cd0`。趋势覆盖 FULL，震荡上市段 PARTIAL，W1 趋势 24/120 预热、W1 震荡 0 笔已完成。不计入原 13/21 分母。见 [PD 记录](../../tasks/pd-candidate-pilot-20261004.md)。

同日 PF 短纤已普通合入 develop `03614a33d`：窗口 2023-01-01 起，40 owner、409 次真实请求 / 1647 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 续采 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 589305、15m 196435、30m 102528、60m 59885。资格 `5b5438261`。趋势和震荡覆盖 FULL，W1 趋势 30/120 预热、W1 震荡 0 笔已完成。60 分钟双策略首次采集在切到 30 分钟时遇到快照代际冲突，续采后收齐。不计入原 13/21 分母。见 [PF 记录](../../tasks/pf-candidate-pilot-20261004.md)。

同日 PG 液化气已普通合入 develop `51b2abac0`：窗口 2023-01-01 起，41 owner、425 次真实请求 / 1743 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 610458、15m 203486、30m 106208、60m 62034。资格 `affe8e452`。趋势和震荡覆盖 FULL，W1 趋势 30/120 预热、W1 震荡 0 笔已完成。不计入原 13/21 分母。见 [PG 记录](../../tasks/pg-candidate-pilot-20261004.md)。

同日 PL 丙烯已普通合入 develop `3591312ef`：上市日 2025-07-22 起，7 owner、41 次真实请求 / 174 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 77871、15m 25957、30m 13548、60m 7913。资格 `06ff38992`。趋势覆盖 FULL，震荡上市日 PARTIAL，W1 趋势 18/120 预热、W1 震荡 1 笔已完成。不计入原 13/21 分母。见 [PL 记录](../../tasks/pl-candidate-pilot-20261004.md)。

同日 PR 瓶片已普通合入 develop `5c9cfb2f7`：上市日 2024-08-30 起，16 owner、140 次真实请求 / 570 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 续采 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 213879、15m 71293、30m 37212、60m 21737。资格 `ba67b8c35`。趋势覆盖 FULL，震荡上市日 PARTIAL，W1 趋势 28/120 预热、W1 震荡 1 笔已完成。聚丙烯 PP 在 `PP2405` 5m 因 `UNIT_FAILED_STOP` / `MARKET_DATA_CONTRACT_INVALID` 跳过，资格未合入。不计入原 13/21 分母。见 [PR 记录](../../tasks/pr-candidate-pilot-20261004.md)。

同日 PT 铂已普通合入 develop `5b0b56cbb`：上市日 2025-11-27 起，4 owner、0 次新源请求 / 40 派生月；12 条流 READY 且 disabled/generation0；API 12/12、149 GET；Chrome 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 29700、15m 9900、30m 5280、60m 3300。资格 `890edbb34`。趋势覆盖 FULL，震荡上市日 PARTIAL，W1 趋势 40/120 预热、W1 震荡 0 笔已完成。不计入原 13/21 分母。见 [PT 记录](../../tasks/pt-candidate-pilot-20261004.md)。

同日 PX 对二甲苯已普通合入 develop `b051262ea`：上市日 2023-09-15 起，13 owner、100 次真实请求 / 410 派生月；12 条流 READY 且 disabled/generation0；API 12/12、152 GET；Chrome 第二次续采 19 场 49 原图，离线审计 `NUMERICAL_PASS_VISUAL_PENDING`。独立四频前缀 5m 183009、15m 61003、30m 31840、60m 18597。资格 `ac2bf537a`。趋势覆盖 FULL，震荡上市日 PARTIAL，W1 趋势 30/120 预热、W1 震荡 1 笔已完成。不计入原 13/21 分母。见 [PX 记录](../../tasks/px-candidate-pilot-20261004.md)。

本轮新增补充品种：SI 工业硅，**SAFE_DEFERRED_QUOTA_GUARD，0/12**；30主力区段/27物理合约/108维护单元。首单元原生发布成功后账户级delta2576409超过冻结估算1612800停止，归属未知；0campaign完成+1发布后停止+107未尝试，PENDING禁重试。仅新增SI2308/2022-12 1m1575与5m315，旧1257文件及636日周保持，局部独立Decimal200验证通过；private0/锁0，无资产/API/页面验收，不称闭环。资格代码76d23ab4及事实记录已普通合入develop7cb91ff98，328 API/工具、130 Web与生产构建通过，正常push/远端精确读回一致；安全暂缓不变，详见[任务记录](../../tasks/si-candidate-pilot-20261001.md)。不计入原13/21分母，不触碰PS/Y闭环和AO/CU失败现场。


## 2026-10-04：14品种独立终验及45品种发布包

A、B、BZ、EB、EC、EG、L、PD、PF、PG、PL、PR、PT、PX 已完成独立终验，
均为 **CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12**。原采集的VISUAL_PENDING和失败/续采记录保持；
19场×14品种的686张原图逐张审查、7,308份索引SHA、215,585笔CLOSED和216,077个SVG点核对通过。

与此前未发布的P、Y、LC、PS、FG共19品种组成v1.11.1包，使正式候选名单从26扩为45、共540个分钟页面组合。
180来源窗口匹配，540流disabled/generation0；360基础响应及180融合结果的834,443笔CLOSED独立Decimal核算通过。
190份UTC/null与范围拒绝原始JSON独审通过；共同融合到期修复经两轴独审、776 Web/61浏览器回归及
PL60m真实335.6秒闲置后409→一次原窗口重建→新token融合200终验通过。

原13/21队列分母保持；本节14品种不挪入原队列，其他失败项不重试。1m仅聚合，持续分钟更新、
分钟主升浪、Runtime自然验收和因果/OOS均不因历史候选闭环而成立。正式发布及运行身份只看STATUS.md。
详见[v1.11.1说明](../../releases/v1.11.1.md)与上述14品种任务记录。

2026-10-06 **RU 橡胶 CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12**。owner按同类精度问题继续收尾，RU作为补充品种，不改原13/21分母。资格ce6186722、6API/1Web/4guard/类型build通过；旧4完成/1失败/43未尝试及40已提交分区保留。新48/48=41读回+7无缺口、78源/320派生/1截断，277659四频全前缀/各139物理月独审；938旧前像/68981Bar/365日周保持。12READY disabled/generation0、分钟基础覆盖均FULL；APIv2 12/152、一次Chrome19场49图、22534 CLOSED/全曲线SVG独审通过，API旧helper身份键失败保留不计通过。精确资源退出/端口free/锁0，最后仅12状态读回不重源扫描。历史50/60、正式45/60；W1warming/0CLOSED与视口限制保持，无Release/Runtime或交易。见[RU恢复闭环](../../tasks/ru-candidate-closeout-20261006.md)，下一BU。


2026-10-06 **BU 沥青 CANDIDATE_CLOSED / REVIEW_COMPLETE，12/12**。资格冻结12e97e9c9，5API/1Web/4guard及类型/build通过；保留旧4完成/1失败/115未尝试及1811前像。新forward120/120=111读回+9无缺口、396真实源/1623派生/84成交额18位截断，1811→3697文件、1886新增/133扩展、161272旧Bar/1052日周保持。四频1002052Bar/各484物理月/30owner独审通过；12READY disabled/generation0、趋势震荡覆盖FULL。API12/152保存HTTP200、一次Chrome19场49原图、22179 CLOSED/完整曲线SVG独审通过，无失败重试。专属API/Web/Chrome退出、端口free/锁0，最后仅12状态不重源扫描。当前**历史51/60、正式45/60**；W1真实44/120预热与7/1/10 CLOSED、视口局限保留，无Release/Runtime/通知/交易。见[BU收尾记录](../../tasks/bu-candidate-closeout-20261006.md)。下一项CU铜。 BU作为补充品种，不改变原13/21分母。
