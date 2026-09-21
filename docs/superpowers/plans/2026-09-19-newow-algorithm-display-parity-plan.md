# 牛哇三策略算法与显示一致性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Owner 指定一个 Terra medium 会话作为实现者；高风险改动结束后安排独立只读 Review，不另行拆出多个实现会话。

**Goal:** 在不补生产数据、不做月线目标升级的前提下，完成牛哇公开三策略算法、目标/吸筹及对应显示，并以同输入证据验证。

**Architecture:** 既有 MDS/ProductReader 负责可信输入，Core 负责唯一确定性公式，API 负责有身份的分 section 装配，Web 只呈现。图表通道价、跨周期卡片、普通/理论页面统计各有独立 surface；它们不是账户事实。三个新增 section 是 `price_reference`、`page_statistics`、`recommendation`，不新建路由或通用插件框架。

**Tech Stack:** Python/Decimal、FastAPI/Pydantic、Vue/TypeScript、lightweight-charts、pytest、Node test、Playwright。

**Spec:** [完整设计](../specs/2026-09-19-newow-algorithm-display-parity-design.md)。执行检查基线 `develop@90f735462a886fbd95c02e7aee6ef598218915df`；开始时核对新 HEAD，不假定此后没有并行合入。
交接前已见 `bad305ee8` 合入 UI batch-two，Workspace/ReferencePanel/杯柄来源说明以该新基线为准，禁止恢复旧展示。

## Global Constraints

- owner 已授权本计划范围的设计补齐、编码、测试、修复、Review、commit/push 和满足条件的 develop 集成，不再询问是否开始。
- 只使用现有 `1d / 1w / 60m` 算法合同；不扩展 1m/5m/15m/30m 产品入口，不开放生产60m或未开放周线品种。
- 不下载 RQData、不修复或写入 Canonical/Catalog/生产DB/Redis/Scope，不改 production配置，不触发通知、main/tag/release/Runtime。
- 同输入、指定源码哈希、指定展示位置进行 parity；月线字段在 oracle 中置缺失以验证源站自身回落周线分支。
- 图表与参考交易的新震荡语义按牛哇：同根 CLEAR 后禁止 BUILD；普通回测和 ideal 各按自己的公开函数，不互相替代。
- completed-only、strict-before、no-future、合约/owner/计算段隔离、质量中断与既有重新预热继续有效；不跳过坏 Bar 拼接历史。
- `page_parity=true`、`executable=false`；无真实仓位、手数、保证金或 Fill；CDV2百分比是参考敞口，不作隐藏策略 Gate。
- 缺数据标为 DATA_BLOCKED / NOT_EVALUATED，既不修数据也不计 parity 通过。未知公式角色是 EVIDENCE_REQUIRED，不可归入数据后补。
- 金额/收益原始值用 Decimal；JS浮点/舍入仅在被证实的 page-display 边界兼容，不能回写策略参考价。
- 公共代码冻结哈希与最小必要输入输出；不提交整站源码、批量股票行情或私人浏览器信息。
- 保留其他任务修改；本计划不依赖未提交的 unified-reference-trading 两份文件。完成的设计内容同步 canonical 后按仓库规则收敛计划，不建立第二套当前事实源。

## Review Focus

1. 同 owner 但 calculation segment 改变：旧极值不得穿越质量中断；Task 2/9 覆盖。
2. 普通左翻与显式历史快照：前者不改当前头部，后者必须全部锚定历史截点，迟到响应无权覆盖；Task 3/9 覆盖。
3. 未开放60m与完整离线六路fixture：前者不连带隐藏同周期价格，后者确实能算完解释/推荐；Task 4/7/8/9 覆盖。
4. 同根清仓重建、期末模拟强平与ideal：交易身份和计数分别正确，不产生伪CLEAR或误称真实成交；Task 5/8 覆盖。
5. 源站舍入、无匹配日期、同分与零分母：不能悄悄换成更“合理”的另一套算法，也不能把非有限值冒充可用；Task 1/4/8 覆盖。

## 执行方式与接口约定

按 Task 1→2→3→4→5→6→7→8→9→10 连续执行。每项是可测试的小交付；先加失败用例，再实现，再回归、检查diff并提交。无需先把全部文件搭成空壳。
以下新模块名/签名是设计接口而非已存在事实；可以作等价局部命名调整，但需同时修计划、调用者和测试，不能省略职责。
纯函数返回不可变 typed dataclass；API JSON不能用未校验的任意dict替代。测试JSON仅用于fixture交换。
Core 的输入以既有 `ProductBar` / `StrategyReplay` / `ContextSnapshot` 为主；不引入第二个行情 resolver。

### Task 1：冻结 source/surface 清单与最小 oracle

**文件：** 更新 `docs/research/newow-current-review.md`、`docs/research/newow-v3.2.82/CURRENT_AUDIT.md` 的本次差异；新增 `services/quant-api/tests/newow/fixtures/page-parity-20260919/` 下分模块 JSON 与 README；新增 `services/quant-api/tests/newow/test_page_parity_fixture_contract.py`。只在需要可重跑采样时新增小型 `scripts/newow_page_parity_oracle.mjs`，不建通用抓取系统。

**来源和输出：**

| 模块 | 原函数/入口 | 必须冻结的输出 |
|---|---|---|
| 图表 | `updateLegendPrices`、`updatePriceLines`、HHV/LLV | 9组合图例；趋势/震荡价格线，主升浪无线 |
| 价格卡片 | strategy-calc的selector/guard，`renderPriceProgress`、`renderAI` | raw选择分支、覆盖顺序、最终文本、进度/颜色与reason |
| 主图 | 三个主策略计算、`_computeAllSignals`与实际position kernel路径 | 每Bar状态/价格/Marker/Hint；震荡同根见证 |
| 副图/解释 | 现版副图、`js/trend-reversal-core.js`、`composite-decision-v2.js` | 数值序列/阈值、R/MM/计龄/分项/仓位/动作 |
| 统计 | `runTrendBacktest`、`runOscBacktest`、`localZhushenglangBacktest`及三个Ideal函数 | trades、forceClose、equity、summary、过滤与年化 |
| 推荐 | `computeAiRecommendation`、`scoreCombos`、`renderAiRecommendationCard` | 窗口来源、6项summary、score、isBest、可见排序 |

- [ ] 核对 source URL、抓取时间、哈希和调用路径；详情基线哈希见设计，共享计算哈希也已记录。若字节变化，逐函数判定与当前任务的差异，不能只凭标题相同继续旧验收。
- [ ] 每个JSON保存以下字段（下例为结构合同，不是已取得的成功结果）：

```text
case_id, source_url, source_sha256, function_names, surface,
clock_as_of, input_sha256, input, expected, allowed_adaptations
```

```python
def test_fixture_provenance_and_expected_are_present():
    import json
    from pathlib import Path
    root = Path(__file__).parent / "fixtures" / "page-parity-20260919"
    cases = [json.loads(p.read_text()) for p in sorted(root.glob("*.json"))]
    assert cases, "No frozen parity witnesses"
    for case in cases:
        assert len(case["source_sha256"]) == 64
        assert len(case["input_sha256"]) == 64
        assert case["function_names"] and case["surface"]
        assert "input" in case and "expected" in case
        assert "clock_as_of" in case and "allowed_adaptations" in case
```

- [ ] 测试另外重算规范化 input 哈希，并拒绝重复 case_id、空 expected 和把缺数标成PASS。此测试只验证fixture合同，不能单独称算法一致。
- [ ] oracle 用原函数对自有小型输入运行；golden expected不能由待测 Python 实现生成。真实网页样本作为补充，不与期货异输入直接比价。
- [ ] 提取 target/cost/cross/previousClose 字段的真实调用来源；将可证明映射写入同一 README。公开源码或输出不能证明时保留精确角色缺口，不靠名称猜测。
- [ ] 为每个新增模块保存至少正常、阈值、缺失/无结果见证，其他细分用例随负责 Task 追加。测试命令：`PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow/test_page_parity_fixture_contract.py`。

**出口：** 可离线复算、可归因的来源清单；每一项声明都知道对应函数/surface。无法取得的某一来源仅阻塞依赖项，其余继续。

### Task 2：一个通道 authority，三策略共享主图价

**文件：** 修改 Core `trend_channel_display.py`、`product_contracts.py`；仅在有实证差异时改 `oscillation_channel.py` 的通道算术；新增 `chart_price_reference.py` 与 `test_chart_price_reference.py`；扩展 `test_trend_channel_display.py`。

**接口：** 保留 `build_trend_channel_layer(replay_bars, visible_bars)` 的调用兼容，内部按 `(physical_contract, segment_id, calculation_segment_id)` 切分；新增下列 projection，不另外计算HHV：

新增接口签名为 `project_chart_price_reference(layer: TrendChannelLayer, anchor: ProductBar, *, as_of: datetime, input_sha256: str) -> ChartPriceReference`。
TrendChannelLayer来自既有模块。查找精确时间/owner/来源匹配的point；不存在或不ready则返回有reason的空值，
不退回“最后一个可用point”。下列是其匹配规则，非新建另一个价格算法：

```text
point.bar_end == anchor.bar.bar_end
point.physical_contract == anchor.bar.physical_contract
point.segment_id == anchor.bar.segment_id
point.source_identity == anchor.bar.source_identity
新增point.calculation_segment_id == anchor.calculation_segment_id
anchor.bar.bar_end <= as_of 且来自本次完整前缀input_sha256
```

`ChartPriceReference` 字段：surface固定chart_legend、frequency、as_of/anchor_bar_end、physical_contract、segment_id、calculation_segment_id、input_sha256、formula_version/adapter_version、target/absorb各自raw Decimal/display string/FeatureStatus。input哈希在有完整前缀的装配层计算后绑定；projection不能用可见窗口哈希假冒前缀哈希。

- [ ] 新增失败用例：相同owner前10根high=200，计算段切换后high=100；新段不得取到200。断点后不足重暖窗口不可伪装真实上市短前缀。重复冲突、乱序和不可观察Bar不得恢复旧值。
- [ ] 正常fixture前10根high=101..110、low=90..99，末值必须110/90；第11根high=111、low=100，末值111/91。真实短前缀1根、9根分别取已有合法极值。
- [ ] 修正现有层只按owner切分的问题；计算段变化与历史质量cause/rewarm信息消费既有reader合同，若调用链丢失该信息，补typed传递而非推断缺口。
- [ ] projection选择anchor point，不要求主策略READY/持有，不借用 explanation。显示按source精度，raw不clamp、不tick量化。
- [ ] 运行新测试及 `test_trend_channel_display.py`、`test_oscillation_channel.py`；追加全前缀计算后裁剪与batch/prefix一致测试，避免全量窗口重复计算性能退化。

**出口：** 同频raw/display在合格输入正确，三策略可复用，坏输入有局部状态且不串段。

### Task 3：主图 API/Web 接通，先修当前“不可用”

**文件：** API `product_service.py`、`app/schemas/market_newow_product.py`；Web `types/newowProduct.ts`、`utils/newowProductTypes.ts`、`utils/newowDetailPresentation.ts`、`NewowProductWorkspace.vue`、`NewowProductChartStage.vue`、`newowProductChartPrimitives.ts`、`newowTrendChannelPrimitive.ts`；扩展对应 service/contracts/presentation/chart unit 测试。

**接口：** chart wrapper增加 `price_reference: ChartPriceReferenceOut`；顶部summary只读此字段。价格线使用同一raw值，图例用display文本，不将股票币种符号强贴到期货报价。

- [ ] 用既有service fixture增加断言：chart请求即使 explanation UNOPENED / strategy FLAT，也返回价格；reader调用记录仅有被请求frequency，没有day/week/hourly隐式读取。
- [ ] 在 `newowDetailPresentation.test.ts` 增加如下行为断言，沿用现有fixture工厂而不新建另一套响应模型：

```text
given chart.price_reference.target.display = "110.00"
and explanation is unopened, and main_state is FLAT
expect top target = "110.00", not unavailable
given chart price missing/conflicted
expect top target empty with reason, not previous response's 110.00
```

- [ ] 三策略顶部均接入；趋势/震荡显示原站存在的价格线，主升浪不新增价格线。保留现有UI布局改动，使用typed formatter而非Vue内公式。
- [ ] 普通左翻不更新snapshot顶价；显式历史定位重算该截点并显示历史身份；回到最新时换新snapshot。新增anchor/token不匹配拒绝用例。
- [ ] 运行 `test_product_service.py`、`test_product_contracts.py`，以及 Web `newowDetailPresentation.test.ts`、`newowProductTypes.test.ts`、`newowProductChartPrimitives.test.ts`、`newowTrendChannelParity.test.ts`。

**出口：** 最初“显示不可用”的同周期链根因修复；只是A第一部分，继续以下任务。

### Task 4：日周价格卡片、真实source adapter与新section

**文件：** Core `target_absorb_display.py`、`product_contracts.py`；API `source_facts.py`、`product_reader.py`、`product_query.py`、`product_service.py`、`product_release.py`、`historical_snapshot.py`、`snapshot_cache.py`、`inflight.py`、`resource_gate.py`、`app/api/market_newow.py`、schema；Web API/types/parser/capability/composable，新增 `NewowPriceReferencePanel.vue`、`newowPriceReferencePanel.test.ts`。修改前用rg列出全部section枚举/五section硬编码。

**接口：** source adapter产生有来源的 `PageSelectionInputs` + 当surface需要的previousClose/本地通道/方向事实；新 `section=price_reference` 返回按surface分开的卡片/解释价格与progress。对 `renderAI` 自身fallback也建独立surface，禁止用chart数据默默替代。沿用现有 `select_page_prices` 并版本化真实差异。

- [ ] 按Task1映射构造 `signal_daily/weekly`、`cross_weekly_buy`、`target_daily/weekly/generic/high`、`cost_daily/weekly/generic`、previousClose。每项附frequency/截止/physical owner/依赖哈希；未证实不制造值。
- [ ] 日/周取源精确到该快照可知的最后完成Bar；昨收取同物理合约前完成交易日close，禁止上一周、上一根小时、settlement和旧主力替代。用夜盘跨自然日fixture验证。
- [ ] 新增红灯测试覆盖源站每个选价分支：buy/hold/wait/sell、day/week/best-available、current == target、cross真/假/未知、字段缺失与合法fallback；无monthly输入的原站fallback是golden。
- [ ] 卡片覆盖顺序固定如下，不统一末尾guard：

```text
target = shared selector -> source允许的day HHV fallback
absorb = shared selector -> source允许的view LLV -> day LLV
week view且合法week prefix>=10: 覆盖为本地week HHV/LLV
price guard只在原调用点执行，带有效previousClose时范围为0.5..2倍
bearish/warning: left=target, right=absorb, pos=clamp((target-current)/range)
other risk: left=absorb, right=target, pos=clamp((current-absorb)/range)
range=abs(target-absorb) or 1；百分比各自使用源码分母并显示1位
```

- [ ] 例如target120/absorb80/current100，两个方向pos均50%，但“已涨”25.0%、“已跌”-16.7%不是同一分母。零宽区间与超范围、JS半分钱/负零、无昨收、周9/10根分别比原函数。缺必需行情值不显示假50%。
- [ ] 新 section 的 read plan仅包含实际必要频率；完整 explanation 继续独立。移除“所有目标输入一律gap”的占位实现，保留逐字段真实gap；`ACTIVE_CODE_VERIFIED`绑定新公式证据，运行available单独判断。
- [ ] 同步schema/capability版本、section allowlist、snapshot签名、资源预算、缓存依赖、inflight key、abort/共同事实失效；新section不能绕过现有frequency/product访问限制。
- [ ] Web增加独立卡片与原因文本；复用后端格式化结果，切换策略/周期/快照时撤权旧响应。explanation消费相同价格事实，不留另一套None占位。
- [ ] 运行 `test_target_absorb_display.py`、`test_product_source_facts.py`、`test_product_reader.py`、`test_market_newow_product_api.py`、`test_product_snapshot_cache.py`、`test_product_inflight.py`、`test_product_resource_gate.py`、`test_historical_snapshot.py`；Web对应parser、capabilities、useNewowProduct及新panel测试。

**出口：** A完整闭环；在既有开放范围且依赖合格时可读，缺失局部失败。数据未开放不授权扩大Scope。

### Task 5：三策略逐Bar parity与震荡新图表版本

**文件：** `oscillation_channel.py`、`product_adapters.py`、`product_contracts.py`、`product_identity.py`、`reference_trades.py`；确有新差异时修改 `trend_band.py`、`main_rise.py`、`escape_d123.py`、`magic11.py`；对应已有单元、配对与replay invariant测试；canonical与版本声明。

**接口：** 新的 active 震荡图表公式身份建议 `newow_oscillation_hhv_llv10_page_v2`（先确认不存在冲突）。不要给主策略公开可切换的samebar旧模式；Task8统计runner才有不同的已命名source合同。

- [ ] 先写持仓中同根同时high触HHV、low触LLV的golden：本根仅CLEAR，下一合法Bar可BUILD。测试第一个CLEAR无有效入场时不伪造ReferenceTrade。
- [ ] 新状态机的约束示意如下；具体入场/初始状态/价格仍以冻结原函数为准，不能用此片段替换其他规则：

```text
每Bar开始 sold_this_bar=false
持仓且触上沿 -> CLEAR，转空仓，sold_this_bar=true
空仓且not sold_this_bar且触下沿 -> BUILD，转持仓
本根CLEAR禁止触发第二条BUILD，但不影响下一根独立判断
```

- [ ] 逐Bar核对三策略main state、参考价、BUILD/CLEAR以及適用S跑、D1–D6、4/7/11/J等Hint；equal阈值、35/45预热、无信号/初始CLEAR、flat、末Bar都要有见证。已正确模块不重写。
- [ ] 输出旧v1与新v2的事件/交易差分并说明来自source行为；新formula/reference模型身份贯穿signal ID、配对、快照、缓存与checkpoint，不让旧ID复用新收益。
- [ ] 检查 `engine.py`、`research_backtest.py` 等内核消费者；本次page图表迁移不能暗改既有causal研究profile、执行时序或收益。依赖同根旧语义的历史研究保持明确的固定版本身份，与唯一active产品图表区分。
- [ ] 更新canonical取消本次active的同根重建；审计文档追加新决定，保留历史审计时间而非把旧结论改成当时已通过。
- [ ] 跑 `test_oscillation_channel.py`、`test_product_adapters.py`、`test_reference_trades.py`、`test_reference_interruptions.py`、`test_product_replay_invariants.py`、三个主策略page测试和Hint测试。检查prefix、batch/incremental、restart与换合约断开。

**出口：** B已证明范围一致；图表参考记录与Task8页面统计可以不同，但每种差异都有source/model身份。

### Task 6：副图核对与WR20/MA120

**文件：** 新建Core `trend_reversal.py`、`test_trend_reversal.py`；修改 `product_auxiliary.py`、API auxiliary装配/schema、Web pane和tooltip；核对现有 `subplots.py`、`magic11.py`，只修真实差异。

**接口：** `calculate_trend_reversal(bars: tuple[ProductBar, ...]) -> tuple[TrendReversalPoint, ...]`。新point包含bar/owner/计算段身份、wr1/wr2/bias/rebound/adjust、enough、连续计数、availability/formula_version。输入只含一个频率，由既有质量合同切段。

- [ ] 先按source fixture写失败测试，包括WR==3/97不触发、跨过阈值才触发、H==L取50、连续信号计数最多60和120根enough边界。
- [ ] 在每个可信段执行：

```text
H20=HHV(H,20); L20=LLV(L,20)
wr1=100*(H20-C)/(H20-L20); wr2=100*(H20-H)/(H20-L20)
bias=(C/mean(C,120)-1)*100
rebound=bias if wr1>97 else 0
adjust=bias if wr1<3 else 0
```

- [ ] 合法短前缀使用已有有效均值且enough=false；已知坏Bar不得通过过滤NaN变成合法短前缀。UI按source画柱/颜色/精度，揭示不足120与经验解释，不把副图信号生成BUILD/CLEAR。
- [ ] 冻结主力控盘、照妖镜、涨跌动能及适用Magic11/D提示取源/线条/数值；照妖镜回画声明不能删，不用严格因果要求静默改掉page surface。
- [ ] 跑新测试、`test_subplots_page_v1.py`、`test_product_auxiliary.py`、`test_magic11.py`与Web图层/pane测试，追加prefix与owner中断用例。

**出口：** C完成，新增副图有Core/API/Web整链，而不是只写纯函数。

### Task 7：新版CDV2与解释面板

**文件：** 新建Core `composite_decision_v2.py`、`test_composite_decision_v2.py`；改 `source_facts.py`、explanation装配/schema、`NewowExplanationPanel.vue`及 `newowExplanationPanel.test.ts`；旧 `composite_explanation.py` 按调用边界迁移，不维持两个active解释权威。

**接口：** 新typed `CompositeV2Inputs` 包含6路trend/osc状态及其bar count/last signal index/fallback signalIndex、J/care/tent、ATR20/Close和quality/context身份；`calculate_composite_v2(inputs: CompositeV2Inputs) -> CompositeV2Result`。result包含R0–R4、MM1–MM4、age、五项和certExtra、方向、双轴上限、reference_exposure、动作token/来源/状态。

- [ ] 冻结完整source规则表而非按审计摘要猜分支；先测MM3/4 age<=2优先，MM1/2 osc age>=3、MM2方向例外，age未知不填0。
- [ ] 实现可直接核对的算术骨架：

```text
certTrend: W/D/H明确各12/12/6；certOsc各10/12/8
certResonance: R4/R3/R2/R1/R0 -> 20/14/10/4/0
certDirection: 同向/两明确同向/分歧/仅周明确 -> 原式20/12/6/8
certVolatility: 低/中/高 -> 0/-3/-8
certExtra: J=-5, care=-3, tent=-3，输入真值和适用条件依源码
total=clamp(sum(五项)+certExtra,0,100)
resonanceCap=100/60/30/10/0
certaintyCap: >=80/60/40/其余 -> 100/50/30/0
final cap/区间/动作：保留source错配neutral豁免、bearish归零及低分覆盖优先级
```

- [ ] 对全六路合法状态组合批量跑原函数与本地比较；另加age1/2/3、分数39/40/59/60/79/80、波动阈值等号、未知状态和扣分见证。禁止保留旧60/85封顶。
- [ ] 原站当前care/tent若固定false，生产适配也不自行激活新规则；fixture可验证pure kernel真分支。页面显示五项+可展开额外扣分，保证总分可解释；不照抄与实际分支矛盾的文案作facts。
- [ ] source adapter使用源站指定的跨策略共同解释上下文，不因切到main_rise改变成另一套六路输入；CDV2与price card共享来源兼容，不要求依赖hash无条件相等。
- [ ] 测试完整离线6路能够READY，生产60m缺失为准确不足而非0分；本计划不修改原生产explanation开放Gate。前端实现ready与不足两态，切换快照撤销旧综合结论。
- [ ] 跑新测试、`test_composite_explanation.py`、`test_context_alignment.py`、`test_product_source_facts.py`、service与Web explanation/composable测试。

**出口：** D算法及显示可用性经完整fixture证明，现场数据/Scope状态独立记录。

### Task 8：页面统计与六组合推荐（同一交付的两个独立模块）

**文件：** 新建Core `page_statistics.py`、`combo_recommendation.py`及对应 `test_page_statistics.py`、`test_combo_recommendation.py`；改API section链和typed响应；新建Web `NewowPageStatisticsPanel.vue`、`NewowRecommendationPanel.vue`及对应unit；保持 `reference_statistics.py`、`page_comparator.py` 原合同，除共享的无语义变化函数外不挪用其结果。

**接口：** `calculate_page_statistics(replay: StrategyReplay, mode: PageStatisticsMode, window: PageStatisticsWindow) -> PageStatisticsResult`；mode枚举standard/ideal；window包含range、固定as_of clock、source-window provenance。必要的raw bands由同一replay关联的可信Bar按既有Core计算，不能用chart Marker强行代替source回测规则。
result包含独立model_version、window身份、typed trades（含forceClose）、dates/equity/summary/annualized、surface、owner中断状态。
`score_combos(combos: tuple[ComboSummary, ...]) -> ComboRanking`；ComboSummary字段strategy/frequency/window身份/cum_return/accuracy/max_drawdown/trade_count/status；result分别返回best与display_order，并保留完整性状态。

- [ ] 先冻结普通/ideal三个策略原函数和各窗口expected。普通trend/osc要求输入>=11、从index9；main_rise要求>=36、从index34。ordinary主升浪价按MA45→MA35→close合法source fallback，不能用缺数据触发降级。
- [ ] standard使用未舍入单笔收益简单相加，曲线含浮盈，峰值起点0，回撤为百分点峰谷差，末持仓统计forceClose。trend参考价B线，osc LOW/HIGH先清后建，mainrise按source价；零收益算非胜。
- [ ] ideal不强平；trend入场B线、出场期间最高close；osc入场LOW、出场持有期间最高HHV并按source先建后清；mainrise入场close、出场此前持有最高close（清仓与更新最高值的顺序不可调换）。ideal显示单笔最大亏损，不标账户最大回撤。
- [ ] 快捷窗口 `all/3m/1y/3y/ytd/ideal` 采用source固定时钟日期运算及 `filterBacktestByDate`：先完整计算再裁剪，曲线减窗口首值，trade按sellDate在窗口内过滤，summary累加已舍入pct。源站没有匹配日期时startIdx保持0并返回原数据的边界也需oracle见证；展示实际窗口，不能宣称该返回属于空窗口。
- [ ] 年化精确取显示曲线首末：`((1+last/100)/(1+first/100))**(365/days)-1`，days是源码日期差；单点/0日/非有限值显示不可计算，保留raw oracle差异说明。不改成252交易日或标准账户复利。
- [ ] 下列数字见证必须锁定（只作为source-derived预期，不替代原函数运行）：

```text
entry100 -> exit110 -> entry100 -> exit90: simple cum=0%, not -1%复利
open entry100,last close105: standard forceClose=true,pct=5%，chart reference仍OPEN
equity=[0,10,4]: peak drawdown=6个百分点
score单个有效combo: 各minmax=0，score=0但可isBest
tradeCount2: no score；3/9: penalty0.85；10: penalty1
```

- [ ] 六组合仅osc/trend×week/day/60min，固定原站输入次序；>=3笔才入评分集。按原式：

```text
q=log1p(max(0, dd>0 ? cum/dd : cum>0 ? 999 : 0))
每列minmax：(x-min)/(max-min or 1)
score=round4((0.40*normCum+0.35*normQ+0.25*normAccuracy)*penalty)
best按score降序、tradeCount降序、稳定输入次序
display rank按score降序、稳定输入次序（不暗加tradeCount tie-break）
```

- [ ] 分数使用source已经2位summary、整数accuracy，而非本地更多精度值。推荐不是LLM；显示总组合数/可算数/合格样本数，不把部分结果叫“六组全局最优”。source可对available子集评分，UI明确“仅已可算组合”。缺frequency不补齐不跨频回退。
- [ ] 输入窗口记录source cache与fallback区别。source fallback起点W=`2024-06-01`、D=`2025-09-01`、H=`2026-04-01`；实现使用相同有界window contract从本地MDS读，不访问股票API当正式行情、不无限回溯。owner/quality断点不能跨段累计成连续账户；结果显示中断和实际覆盖，不声称全历史完整。
- [ ] 增加 `page_statistics`/`recommendation` section，复用Task4的版本/签名/cache/inflight/resource机制，各自lazy。标准/ideal交易列表分别命名并可定位Bar，不生成Action或覆盖ReferenceTrade。
- [ ] 跑新Core测试、`test_reference_statistics.py`、`test_page_comparator.py`、API gate/snapshot/compatibility测试，以及两个新Web panel与sorting测试。

**出口：** E有普通与ideal完整统计、六组合独立排名和可用UI；不建设Ledger/worker，不依赖另一个任务先落地。

### Task 9：九组合整页与异步/异常验收

**文件：** Web `useNewowProduct.ts`、`NewowProductWorkspace.vue`及前述panel；`apps/quant-web/e2e/newow-product.spec.mjs`、`newow-detail-light.spec.mjs`、`newow-chart-panes.spec.mjs`，对应pytest service/API测试。

- [ ] 用本仓库可重跑route-fixture覆盖3策略×3周期；fixture明确标隔离输入，不连接生产读写，不把route拦截结果当真实数据恢复。
- [ ] 每组合验证适用模块：图例/线/卡片、主状态/Hint、subplots、CDV2、reference/standard/ideal、推荐；按适用性列分母，mainrise无线为正确NOT_APPLICABLE。
- [ ] 测试旧请求延迟：先请求A，切到B，B成功后A返回，不污染任一价格/统计；abort失败、403未开放、超时、部分数据、同as_of不同输入hash、跨策略共享facts冲突均撤权正确。
- [ ] quality break、owner切换、数据缺失后刷新不得保留旧ready值；独立有效chart不因其他section失败清空。history snapshot/current view/older-page三种身份切换有可见标记。
- [ ] 全前缀与视口裁剪一致；新增section不在首屏同时重算9组合/反复全量历史，不移除现有resource预算。允许用户按需展开昂贵模块。
- [ ] 执行Web unit/build与三组fixture E2E（下面命令的5182先确认空闲，不占用或重启既有服务）：

```sh
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web test
pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web build
env -u VITE_API_BASE_URL -u VITE_MARKET_WS_URL REAL_BACKEND=0 PLAYWRIGHT_PORT=5182 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5182 PLAYWRIGHT_CANDIDATE_PREVIEW=0 PLAYWRIGHT_SKIP_WEBSERVER= pnpm_config_verify_deps_before_run=false pnpm -C apps/quant-web exec playwright test -c playwright.config.mjs e2e/newow-product.spec.mjs e2e/newow-detail-light.spec.mjs e2e/newow-chart-panes.spec.mjs
```

**出口：** F完成的候选页面证据；缺生产分钟/周线只列后续数据复核，不反复请求下载。

### Task 10：独立Review、集成与交付

**文件：** `openspec/specs/newow-product-reference-trading/spec.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`、必要时 `TESTING.md`，研究审计文件；不提前更新 `STATUS.md` 为发布或Runtime完成。

- [ ] 将新公式/surface/section/版本、标准与ideal差异、月线排除及数据适配同步canonical。旧v1证据保留历史身份，但active产品只有一个图表/解释权威。
- [ ] 执行影响范围回归（依赖按既有环境安装方式，不改用户级配置或放宽检查）：

```sh
PYTHONPATH=services/quant-api:packages/quant-core uv run --project services/quant-api pytest -q services/quant-api/tests/newow tests/engineering/test_repository_hygiene.py tests/engineering/test_canonical_consistency.py
openspec validate --specs --strict --no-interactive
python3 scripts/engineering/secret_scan.py --json
git diff --check
```

- [ ] Ruff/Mypy按 `TESTING.md` Newow专项配置对实际改动模块运行；保留命令和输出。通过定向测试后仍需接口/版本/取消失效整体回归，不用“代码看起来对”作为结果。
- [ ] 安排独立只读Reviewer检查精确diff/commit，重点是source parity、时间/owner/质量边界、surface混淆、强平不造Marker、版本缓存与Scope不扩大。分类仅Confirmed Issue、Risk / Needs Verification、Optional Improvement；修复确认问题并重测后复核。
- [ ] 核对develop新增合入，解决本任务冲突、不覆盖别人设计/代码；审查和必要测试通过后commit/push并按仓库流程集成develop。不得main merge/tag/release/Runtime。
- [ ] 总结A–F各自代码/测试/Review状态及来源证据，列出DATA_BLOCKED与EVIDENCE_REQUIRED两类未完成；只A通过不能说整项完成。数据全矩阵、发布、Runtime单独pending。

## 自检覆盖与停止条件

| 设计要求 | 执行任务 |
|---|---|
| 范围/来源/排除月线及数据工作 | 1、所有任务Global Constraints |
| 同周期与卡片两条价格链 | 2–4 |
| 三策略与同根冲突按牛哇 | 5、8 |
| 副图与CDV2解释 | 6–7 |
| 统计窗口/年化/推荐 | 8 |
| section全链、异步/快照/质量与页面 | 3–4、8–9 |
| 版本/canonical/Review/集成与剩余Gate | 10 |

只在来源确实不可证明、必须扩产品/业务边界、必须改他人未提交内容或触及未授权外部操作时暂停受影响项。
测试失败、实现量大、生产缺60m/部分W1不构成停止独立工程工作的理由。若公式证据缺口仍在，不能宣称对应模块完成；继续可独立交付项并精确报告缺口。

最终交付必须给出实际commit、测试、独立Review结论、develop集成状态；本计划未授权发布与Runtime。
