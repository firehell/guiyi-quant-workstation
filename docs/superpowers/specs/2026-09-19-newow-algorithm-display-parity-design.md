# 牛哇算法与三策略显示一致性设计

日期：2026-09-19。状态：按 owner 最新指令修订，授权交由 Terra medium 实施；实现尚未验收。

本轮目标是完成公开可核验的牛哇算法和三策略页面显示；月线目标升级不纳入，分钟与周线数据补全、
生产数据验收由 owner 后续独立推进。工程完成不要求生产全品种数据矩阵全绿。

调查基线：`develop@0bd8543fbcca51851e31f06e214bbebdb8e95d67`。主工作树已有统一参考交易设计与计划两份
未跟踪文件；另有 `codex/newow-ui-batch-two` UI 工作树。实施时重新核对依赖与重叠文件。
当前 release/runtime/scope 以 [STATUS](../../../STATUS.md) 为准，本设计不变更其完成状态。
执行检查基线：`develop@90f735462a886fbd95c02e7aee6ef598218915df`。本设计及
[执行计划](../plans/2026-09-19-newow-algorithm-display-parity-plan.md) 是本次交接的完整输入；
不依赖其他任务尚未提交的设计文件。执行者从包含这两份文档的 develop 建隔离工作树。
交接前复核：UI batch-two 已通过 `bad305ee8` 合入 develop；实施须保留其杯柄来源披露与参考交易身份修复，
不再把它列为未合并依赖。此时 STATUS 已记载 Runtime promotion 至 v1.10.17，仍不等于自然运行全部验收。

## 1. 已确定范围

- 一致性对象：趋势、震荡、主升浪页面中公开可验证的公式、状态、Marker、适用 Hint、副图、目标/吸筹、
  解释与页面参考统计。保留归一桌面布局，无需逐像素复制股票手机页面。
- 对比输入：冻结相同 OHLCV、信号事实、截止时间、参数和展示位置。不同股票/期货、不同截点不能直接比数值。
- 排除月线升级：目标价到周线即止；在原站会调用月线分支的位置，使用有效周线目标。
  同输入 oracle 固定月线目标缺失，验证原站自身回落周线的结果。只排除此项，不修改其他选择分支。
- 继续保留期货合同：completed-only、物理合约/owner 隔离、质量中断、同源读取。原站盘中改写末根的行为
  不进入正式 Historical 结果；本次不建设新的 Live preview。
- 数据工作排除：不下载、补数、修复 Canonical/Catalog、不扩品种/周期开放范围，不以数据缺口驱动本次修复。
- 缺数据的页面 case 标为 `DATA_BLOCKED / NOT_EVALUATED`，不计为算法失败，也不计为 parity 通过。
  合格输入下错误、已知缺价后仍画旧价格、跨合约借值、迟到响应污染属于本次代码问题，必须修复。
- 私有选股/排名、股票基本面/CANSLIM、未知杯柄公式和 AI 文案逐字复制继续按既有产品范围排除。

“完全一致”的声明限定为：除上述明确排除和期货输入合同外，指定版本、指定展示位置、同输入的公开行为一致。
源站自身不同模块冲突时分别记录，不能制造一个全站统一算法再声称原样复刻。

## 2. 本次核实的关键事实

1. 当前核心已有 HHV/LLV、日周目标选择、价格护栏及三策略 replay。
2. `product_service.py` 的 explanation 固定调用 `calculate_target_absorb(context, None)`。
   `source_facts.py` 将九类目标/吸筹输入固定列为 evidence gap。
3. `product_release.py` 关闭整个 explanation；Web 顶部价格依赖该 section 的 ready 与
   `ACTIVE_CODE_VERIFIED`，而现有目标选择器成功路径仅返回 `RESEARCH_EVIDENCE_ONLY`。
4. 牛哇公开页面有至少两种不同价格展示，不能共用一个没有 surface 身份的值：

| 显示位置 | 公开取值合同 | 依赖 |
|---|---|---|
| 主图图例的目标价/吸筹价 | 当前周期 HHV(high,10)/LLV(low,10) | 当前周期可信前缀 |
| 趋势/震荡右侧价格线 | 使用对应主图相同通道值 | 同上；主升浪不凭空增加源站没有的价格线 |
| 状态卡/进度条 | 日周 signal 与 target/cost 选择；周视图满10根的本地周通道覆盖；有具体 fallback 顺序 | 日周事实、当前价及各分支必要输入 |
| AI解释中的目标/吸筹字段 | 共享选择器后还有自身 fallback | 对应展示调用链，不能拿图例代验 |

2026-09-19 实测贵州茅台：日线图例 `1333.60 / 1254.00`，周线图例 `1363.35 / 1190.19`；
周线切到主升浪仍显示同一对通道价格，与该次读取的最后10根周 Bar 极值相等。
这只是取值位置和样本证据，不是三策略全部公式通过。

公开来源：[详情页](https://www.v8848.cn/stock_detail.html?code=600519.SH&period=day&strategy=huanglantai)、
[共享计算](https://www.v8848.cn/strategy-calc.js?v=3.3.46)。详情标题 v3.3.46，共享脚本内部 v1.1.0；
本次共享脚本 SHA-256：`bb9e630aa322464a535ccf4951a9c4728bff40e101bdb2a35dddc5d602536fbd`。
取证锚点：`updateLegendPrices`、`updatePriceLines`、`renderPriceProgress`、`calcTargetPrice`、
`calcAbsorbPrice`、`clampPriceGuard`。页面版本号相同也必须核对字节，不能覆盖既有冻结 evidence。

其他缺口依据 [当前审计](../../research/newow-v3.2.82/CURRENT_AUDIT.md) 和
[固定输入对比](../../research/newow-current-review.md)。其中旧发布状态不沿用；本次只复用算法差异记录。

## 3. 推荐结构

```text
MDS / 既有 ProductReader
  ├─ 同周期可信前缀 → 共享通道计算 → chart.price_reference → 三策略顶部/图例
  ├─ 日周可信事实   → 目标选择/卡片显示 → price_reference section → 跨周期卡片
  └─ 日周60m事实    → 新版综合解释 → explanation section → 综合面板
```

采用“主图带同周期价格 + 独立跨周期价格 section”。没有必要为了两项主图价格读取全量六组合解释。
相比直接打开现有 explanation，此结构可以在未准备60m数据时先交付日线图表价格；相比全部由前端重算，
仍然只有后端一个公式 authority。

### 3.1 同周期主图价格

- 在现有 chart 响应增加 `price_reference`，三策略必有该字段，状态和数值可为空。
- 后端复用 `oscillation_channel.calculate_channel_series` 的 HHV/LLV 算术和既有 owner/质量切分。
  趋势圆点、震荡通道与新增 summary 消费同一权威结果；不另写一套 max/min resolver。
- 使用完整计算前缀后裁剪显示窗口；不能只用当前加载的500根重算，也不因左翻分页改变顶部最新价格。
  显式进入历史快照时，以该快照截点重新锚定并标记“历史”；普通加载更多与切换历史快照不能混为一件事。
- 输出至少包含：`surface=chart_legend`、公式/适配版本、周期、`as_of`、锚定 `bar_end`、
  contract、owner segment、calculation segment、输入指纹、raw/display target/absorb、各项状态和原因。
- 同周期价格是否 ready 由通道输入决定，不依赖策略必须 BUILD/HOLD，也不依赖综合解释或 ReferenceTrade ready。
  空仓可以有目标/吸筹；主策略仍在预热但通道有完整且合法的短前缀时，可独立显示通道价格。
- 严格区分真实上市短前缀和历史缺口。源站 HHV/LLV 的合法短前缀使用已有1～9根；缺Bar、重复冲突、
  质量中断不得被解释成短前缀。质量断点后的恢复沿用项目已批准的计算段与重新预热规则。
- 主图图例不施加跨周期共享函数的昨收 clamp。保留 raw Decimal；display 值按对应原站 JS/toFixed
  规则输出。显示精度不反写交易参考价，不按 tick 四舍五入改变 parity 值。

### 3.2 跨周期目标/吸筹卡片

- 在现有 `strategy-detail` 增加显式 `section=price_reference`，按需读取，响应保持既有 section wrapper。
  不另建 HTTP 路由，不提供 `all`。schema、capability 与严格客户端解析器同步版本化。
- 新 section 只读必要的日/周和视图周期事实；日线卡片不读取无关60m，60m卡片在该频率尚未开放时仍不可请求。
- 替换固定 `evidence=None` 的占位路径为有类型的 source adapter；它消费既有 MDS/replay，构造有来源身份的
  日周价格和信号。不能把所有 `cost_*` 直接假定为 LLV，也不能将未证明的 `cross_weekly` 当普通 BUILD。
- 实现任务首先把原站 batch 字段与同输入公开输出、通道和状态逐项对照，确定 target/cost/cross 的可验证语义。
  未证明的角色只阻塞依赖它的分支，记录 `EVIDENCE_REQUIRED`；这类公式证据缺口不能按“数据后补”忽略。
- 选择器保留 day/week/best-available、buy/hold 优先级、突破升级、周线金叉、fallback 及无值行为。
  不输入月线；月线排除作为适配身份记录，不能对外称支持月线目标。
- 价格护栏按调用位置执行：共享函数读取到有效昨收才 clamp 到 `[0.5,2]`；周线卡片最终 local override
  必须遵循原站覆盖顺序，不能统一在末尾再 clamp 一次。
- 期货昨收优先复用 Market Fact 既有同物理合约、前一完整交易日收盘 authority；不是前一周Close、
  前一根60m Close、结算价或旧主力Close。通过交易日/Session定位，不做自然日减一。
  原站调用未携带昨收的 oracle case 按无基准分支验证；生产所需昨收缺失时明确标记，不静默伪造。
- 精确区分“原站算法允许的字段 fallback”和“我们缺少应有数据”：后者不能触发跨频、跨合约的静默替代。
- 卡片进度复刻风险方向、左右价格标签、已涨/已跌、距目标/距吸筹及0～100%位置；不把价格区间位置当概率。
  原站零宽区间处理与显示舍入纳入 golden。任一必需输入缺失则仅对应值/进度为空，不填默认50%。
- 所有来源需与快照和 owner 相容；上一完成周仍属于旧主力时，不把它与当前新主力日线拼成一个可用卡片。

### 3.3 证据状态与兼容性

- `ACTIVE_CODE_VERIFIED` 来自精确公式版本的独立测试/Review；请求运行状态另由实际输入验证产生。
  禁止通过把字符串统一改为 ACTIVE 或删除 frontend 检查来“开放”。
- 已有研究选择器版本保留历史身份；新 source/display 合同使用新版本。历史证据不自动覆盖新行为。
- 迁移后主图价格只有 chart 一处 authority，卡片价格只有 price_reference 一处 authority；
  explanation 消费同一计算结果/事实，不继续保留第二个固定为空的目标实现。
- 新 section 纳入 snapshot proof、缓存依赖、abort、迟到响应撤权和共同事实冲突失效；不同 section 的
  输入指纹可能不同，使用已有共同事实兼容校验，不能要求无条件 hash 相等，也不能只比较 as_of。
- capability 分开声明“代码支持”和“当前产品/频率允许请求”；本次不新增分钟周期或扩大生产频率 Scope。
  完整 explanation 保持自己的输入要求，不因主图价格已完成而默认开放。
  新 section 的公式与装配必须能在隔离完整输入下走通；生产未开放六路输入不能成为省略算法或UI实现的理由。
  实施时遍历所有 section 枚举、签名token、缓存key、read plan、resource gate及迟到响应逻辑，
  不能只修改路由和前端选项。

## 4. 三策略整页的一致性工作清单

目标/吸筹闭环是第一交付，不足以声明整页已全部复刻。后续算法/显示按以下独立交付推进：

| 交付 | 当前基础 | 需要完成 | 与生产补数关系 |
|---|---|---|---|
| A 目标/吸筹 | 通道、旧选择器存在；正式输入和显示被阻断 | 第3节结构、真实输入适配、图例/价格线/卡片逐位置验收 | 可用冻结输入完成工程验收 |
| B 三策略主图 | 三个内核、Marker、Hint、ReferenceTrade已有 | 冻结现版逐Bar对比，修已确认公式/状态/Marker差异；三策略切换和窗口行为一致 | 不跑全品种补数；真实缺口单列 |
| C 适用副图 | 控盘、照妖镜、动能、Magic11已有 | 新版取源和显示核对；补 WR20/MA120 趋势转折及3/97严格边界、零振幅和短前缀 | 同周期模块可单独验收 |
| D 综合解释 | 旧13格/四项版本已有 | 新版CDV2的R0–R4、MM1–MM4、计龄、五项+certExtra、方向/仓位与文案同源 | 六路完整fixture验算；现场缺周期保持不足 |
| E 页面统计与六组合推荐 | ReferenceTrade、五窗口比较器已有 | 冻结收益曲线/回撤/年化/窗口/理论值口径；独立实现趋势/震荡×日周60m六组合评分和同分排序 | 六组缺输入时报告不完整，不把三组称六组 |
| F 三页集成 | Workspace、section loader、图层和历史定位已有 | 相应模块接线、状态/精度/颜色/来源说明、刷新/切换/历史窗口/异常验收 | 后续数据合格后可重跑相同矩阵 |

CDV2中的百分比仅是页面参考建议，不成为期货保证金或账户仓位；额外扣分在详情可查。
六组合推荐不含主升浪，不用五窗口比较器替代，不自动改 active 策略。
WR20/MA120、风险Hint和照妖镜不改变主策略信号；照妖镜继续标记回画。
多周期嵌套路径若纳入 E，只展示已证明的成本/目标与时间，缺字段不画预测线；不另设预测算法。

### 已知原站内部冲突的设计处理

owner 本轮已决定“取舍按牛哇方案”：撤销把震荡同根差异作为本轮豁免的处理，不再等待重复决策。
主图及由其 Marker 投影的参考交易使用新公式版本：清仓当根禁止重建。普通页面回测仍按公开
`runOscBacktest` 的先清后建规则；`ideal` 则按其独立函数的先建、更新、再清顺序。
三者分 surface / model 身份，不能混写同一交易列表，也不能把普通回测等同于理论值。
更改须附逐Bar/交易差分，并更新信号、配对、缓存和版本身份；旧版本由 Git/冻结证据追溯，不保留两套 active 主策略。

本轮追加源码核实：详情 HTML SHA-256 为
`4c44ae93ab5d66c361a787f94954ca170daa7e31ecb5e04a19400f51912fdf0f`。
普通回测累计单笔未舍入收益，曲线包括浮盈，期末以末收盘价生成 `forceClose` 统计记录；理论值不强平，
且所谓“最大回撤”实际显示为单笔最大亏损。过滤窗口后以舍入后的交易百分比重算汇总，曲线首点归零；
年化使用曲线首末资金倍数之比与自然日365次幂。详情以执行计划冻结的原函数见证为准，不能用标准账户定义替换。

E 复用既有 ReferenceTrade 接口，不依赖另一任务的未提交统一参考交易方案。
本次不建设持久化、worker、数据库迁移或增量账本；如并行任务已经合入，适配其公开合同而不覆盖其实现。
页面统计置于独立 `page_statistics` section，六组合推荐置于独立 `recommendation` section，保持懒加载，
不使图表和参考记录被迫读取六组输入。现有 CLOSED-only 摘要保持自己的身份，页面模拟强平不能制造 CLEAR Marker。
数学非有限结果不作为合法价格/收益输出；原站行为可留在 oracle evidence，正式API标明不可计算，不能冒充0。

## 5. 执行顺序与文件职责

1. **冻结来源与范围**：为 A/B/C/D/E 各自保存精确来源哈希、必要输入、函数/DOM输出和允许差异。
   在已有 research evidence 目录内增量登记，不复制整站或另建第二套审计系统。
2. **优先完成 A 的同周期链**：Core共享通道 → chart schema/service → Web typed parser/summary/价格线。
   直接消除当前顶部价格对 explanation 的错误依赖。
3. **完成 A 的跨周期链**：source adapter → display selector/guard/progress → 独立 section → 卡片。
   昨收/cost/cross有独立原件证据，未知项保持可诊断。
4. **B/C 与 D/E 分交付实现**：每个交付带版本、同输入 golden、接口与显示测试。已正确的现有内核只回归，
   真实差异才修改。CDV2/推荐无需等待生产60m补数，但现场可用性保持未验。
5. **F 集成**：更新 canonical、capability、客户端合同；候选三策略页面测试与独立 Review；形成工程完成结论。

| 位置 | 职责/修改范围 |
|---|---|
| `packages/quant-core/guiyi_quant/newow/oscillation_channel.py`、`trend_channel_display.py` | 复用通道算术、统一输出与合法前缀/质量分段；不在 UI 重算 |
| `packages/quant-core/guiyi_quant/newow/target_absorb_display.py` | surface明确的选择、guard、override和显示数值 |
| `packages/quant-core/guiyi_quant/newow/product_contracts.py` | 有版本和来源的价格显示合同 |
| `services/quant-api/app/market_data/newow/source_facts.py`、`product_reader.py` | 接实际输入，按section只读必要依赖，保留质量和owner验证 |
| `services/quant-api/app/market_data/newow/product_service.py` | 装配chart价格与独立卡片，不包含第二套公式 |
| `services/quant-api/app/api/market_newow.py`、`app/schemas/market_newow_product.py` | 新section和typed响应；输入校验、错误分类 |
| `services/quant-api/app/market_data/newow/product_release.py` | 新合同的能力声明；不推导频率/品种扩张 |
| `apps/quant-web/src/types/newowProduct.ts`、`utils/newowProductTypes.ts`、`api/newowProduct.ts` | 同步严格类型、版本和能力解析 |
| `apps/quant-web/src/composables/useNewowProduct.ts` | 新section的快照兼容、取消和过期处理 |
| `apps/quant-web/src/utils/newowDetailPresentation.ts`、`components/market/detail/newow/` | 顶部取chart价格；卡片独立状态；图层一致、历史明确 |
| `openspec/specs/newow-product-reference-trading/spec.md`、`PROJECT_SOURCE.md`、`DECISIONS.md` | 实施时同步section/显示/版本合同，不提前写完成状态 |

实现前检查 UI batch-two 的合并状态，再修改 Workspace/详情投影，避免覆盖其布局和展示工作。
新增 CDV2、趋势转折、六组合排名各自采用小型纯函数 Module；不把它们塞进目标价格 Module。

## 6. 验收：本次工程与后续数据复核分开计数

### 本次必须完成

- A 的原站黄金输入覆盖：三策略×日/周/60m的9个页面组合；图例、卡片、价格线按真实适用项分别核验。
  所有存在的日周信号状态、cross、缺字段、突破等号、周覆盖、护栏、舍入、零宽与月线排除分支有测试。
- 原站 fixture 与本地纯函数消费同一冻结输入；显示字符串精确一致。未舍入JS/Decimal数值容差预先声明，
  沿用已验证价格 `1e-12`、收益 `1e-10` 个百分点；时间、方向、关联、分支、状态不能模糊比较。
- fixture只能证明算法/显示，不能标记生产数据已恢复；每个结果记录 code、input hash、as_of、版本和surface。
- API证明 chart 价格不读取跨频输入，跨周期卡片不读取无关60m；坏/缺输入返回准确子功能状态。
- Web证明 explanation关闭时主图价格仍可显示；FLAT时仍可显示；异步旧响应、历史定位、切策略、切周期、
  分页和重新读取均不串价；同一surface的数字/线条/图例一致。
- 数据中断、owner切换、旧周owner、重复/乱序、未来Bar、缺昨收等通过隔离fixture验证防错行为。
- B–E 逐项有原站同输入证据；公开源码存在或旧测试通过不能替代新版 parity。
- 公式、时间和状态改动做独立 Review；普通文案和布局自审。必要Web typecheck/build和定向回归通过。

可复用的已存在测试入口：

```sh
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_target_absorb_display.py services/quant-api/tests/newow/test_trend_channel_display.py services/quant-api/tests/newow/test_product_source_facts.py services/quant-api/tests/newow/test_product_service.py
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec node --test tests/newowDetailPresentation.test.ts tests/newowProductTypes.test.ts tests/useNewowProduct.test.ts
```

实施时为新增分支补充行为测试，并按实际影响选择 E2E；以上是计划入口，不是本轮运行记录。

### owner后续数据验证

数据准备后按相同矩阵重新读取：品种、周期、策略、surface、代码版本、as_of、输入指纹、预期/实际值与缺口原因。
无需重写算法或人为切换单品种“已验证”布尔值；正常刷新/缓存失效后以新的真实快照验证。
现有未开放品种/周期依然需要原数据任务的 capability 开放步骤，补好文件本身不会自动开放 Scope。
本次不要求60品种×9组合现场全部通过，不把已知数据阻塞计入实现缺陷率。

## 7. 完成定义与交付限制

- 本设计的 A 完成：三策略相应位置能使用已验证输入显示正确目标/吸筹；数据缺失只影响对应功能。
- B–F 全部完成才可声明“声明范围内三策略算法/显示一致”；只完成 A 时明确称目标/吸筹闭环。
- 数据完整性、全品种实际页面复核、发布、Runtime promotion分别保留状态，不用 fixture 代替。
- 本轮只产出设计，不修改运行代码、公式版本、生产数据或发布能力。实施后回退以精确代码版本/合同为单位，
  并安排新会话实施；本句仅指设计会话。实施会话可修改范围内代码/版本及集成 develop，
  不通过放宽质量校验恢复显示；未来发布与Runtime操作仍遵循仓库授权边界。

执行要求：按执行计划连续完成 A–F，不在 A 完成后误报整项完成；仅真实证据/授权/冲突阻塞相关部分。
