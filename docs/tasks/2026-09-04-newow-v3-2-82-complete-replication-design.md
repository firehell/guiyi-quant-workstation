# Newow v3.2.82 完整复刻设计

日期：2026-09-04

状态：`PARTIAL / REAL_OOS_REPLAY_BUNDLE_PENDING / REAL_WEEKLY_OOS_GATE_PENDING / FINAL_REVIEW_BLOCKED`

分支：`codex/newow-v3-2-82-complete-replication`

基线：`develop@f96f1c9a40371276f66223e5fdedb2812de72ef3`

## 1. 目标

在不扩建 A 股行情/基本面平台、不进入 Alert/Runtime/订单的前提下，把牛哇当前公开页面中可证的策略、指标、解释与选股行为完整吸收为：

1. 可追溯、可重复采集的页面证据；
2. 有独立公式身份的纯 Quant Core module；
3. 页面一致性与因果研究严格分离的评估结果；
4. 只读详情页可消费的 typed facts；
5. 对未知服务端行为明确 fail-closed 的覆盖清单。

“完整复刻”只在本设计声明的公开可访问产品面全部达到对应 Gate 后成立。无法观察的私有服务端、付费路径、账号数据和通知投递不属于完成声明。

## 2. 不可破坏边界

- RQData 仍是归一量化唯一外部行情事实源；正式期货输入只经 `MarketDataService`。
- 股票数据只作为外部页面 parity 证据，不进入 Canonical，不新增股票数据 provider、表、任务或 Runtime。
- 所有新 module 均为纯函数或不可变结果；不自行读取网络、文件、数据库、Redis 或时钟。
- `page-parity` 只复算原页面事实，不得进入可信收益、Alert、Runtime 或候选晋升。
- `causal-research` 使用 completed Bar 后下一根 Open、显式成本/滑点/可成交约束；不复用页面同 Bar 成交。
- 重绘指标可以只读展示，但必须携带 `repainting=true`，并被正式信号和研究回测拒绝。
- Web 只消费 typed API facts，不复制公式。
- `auto_order=false`；不新增账户、委托、持仓或真实下单路径。
- 不修改 `PROJECT_SOURCE.md` 的稳定产品面，不修改 main、release、tag、Runtime 或生产 Scope。

## 3. 证据分层

每个结论必须属于且只能属于以下一种状态：

| 状态 | 含义 |
|---|---|
| `OBSERVED_EXACT` | 当前页面、公开脚本或公开响应直接给出的事实 |
| `REPRODUCED_EXACT` | 本地对冻结原始输入逐字段复算一致 |
| `BEHAVIOR_INFERRED` | 由多组黑盒输入/输出推导，仍缺直接源码 |
| `CLEANROOM_IMPLEMENTED` | 由已确认合同独立实现，并通过 causality/parity 测试 |
| `UNKNOWN` | 证据不足，禁止实现成正式确定逻辑 |
| `REJECTED` | 已证伪、重绘或不满足因果/边界要求 |

公开资源每轮采集必须记录 URL、产品版本、采集时间、字节数和 SHA-256。动态 JSON 必须记录请求 body、响应 schema 和原始响应 hash，不保存 Cookie、Token 或账号数据。

## 4. 总体架构

```text
Current Niuwa public UI/static JS/read-only JSON
  -> external evidence capture + SHA-256 manifest
  -> coverage ledger + frozen minimal golden fixtures
  -> versioned Quant Core modules
       page-parity modules
       causal-research modules
       interpretation modules
  -> existing Newow typed detail query
  -> read-only Market detail workspace
```

核心 seam 是 Quant Core 的不可变输入/输出 interface。网络采集和股票页面解析位于外部研究证据层；期货适配仍由已有 `MarketDataService -> NewowResearchBar` adapter 完成。这样同一公式可以用股票页面验证，也可以用期货 Canonical 研究，而不会在核心 module 中引入第二套数据入口。

## 5. Slice A：v3.2.82 覆盖表与股票逐值证据

### 5.1 交付物

- 外部研究包新增 `v3.2.82` manifest、首页/详情/选股/共享脚本 hash、截图和匿名只读请求合同。
- 仓库新增一份稳定 coverage canonical，记录所有公开功能的证据状态、公式身份、实现入口和剩余 Gate。
- 冻结 3 指数 + 6 股票，覆盖周线、日线、60 分；目标/吸筹价格必须覆盖日周同多、日多周空、日空周多、双空、缺字段和突破升级分支。
- 综合决策 fixture 覆盖 13 个矩阵表项、全部当前可达分类，并用合成输入证明 `warning-*` 三项在 page-exact 控制流中不可达；真实页面样本覆盖不少于 6 只股票。
- 选股行为探针覆盖 `trend_build/mainrise_build/cup_handle/daily_buy/weekly_buy/oscillation_build`，保存全量返回字段、排序和请求参数。

### 5.2 验收

- 每个功能都有来源、版本、证据状态、公式身份、实现状态和下一 Gate。
- 任何 `UNKNOWN` 不得指向 active formula implementation。
- 证据文件 hash 可重算；fixture 只保留验证所需最小事实，不复制整站源码。
- 最新页面与 2026-09-03 金样本的变化必须形成显式 diff，不能静默覆盖。

## 6. Slice B：目标/吸筹通道与参数比较器

### 6.1 Formula identities

```text
newow_target_absorb_hhv_llv10_page_v1
newow_target_absorb_display_selection_page_v2
newow_hhv_llv_window_optimizer_page_v1
newow_hhv_llv_window_optimizer_causal_v1
```

旧身份不覆盖，新页面公式只通过新 identity 使用。

### 6.2 Core interfaces

```python
calculate_price_channel(
    bars: Sequence[NewowResearchBar],
    *,
    window: int,
) -> tuple[PriceChannelPoint, ...]

select_display_prices(
    facts: MultiPeriodPriceFacts,
    *,
    view_period: DisplayPeriod,
    current_price: Decimal,
    previous_close: Decimal | None,
) -> DisplayPriceSelection

rank_page_channel_windows(
    bars: Sequence[NewowResearchBar],
    *,
    windows: tuple[int, ...] = (10, 20, 24, 30, 52),
) -> tuple[PageChannelWindowResult, ...]

rank_causal_channel_windows(
    bars: Sequence[NewowResearchBar],
    *,
    windows: tuple[int, ...],
    costs: BacktestCostResolver,
    constraints: ExecutionConstraintResolver,
) -> tuple[CausalChannelWindowResult, ...]
```

### 6.3 页面合同

- 通道窗口含当前 Bar；不足完整窗口返回 unavailable，不做 partial fallback。
- 目标为窗口 High 最大值，吸筹为窗口 Low 最小值。
- 展示选择按当前公开 `strategy-calc.js` 的日/周 buy/hold/sell/wait 与 `cross_weekly=buy` 合同执行。
- 所有展示价格使用 `Decimal`；最终两位小数和 `[0.5, 2] * previous_close` 护栏在一次深 module 内完成。
- 页面参数比较固定 10/20/24/30/52，同 Bar 先清后建、Close 记账、收益相加、末根强平、零费用；结果显式 `trustworthy_for_research=false`。
- 因果版本只在 completed Bar 生成意图，下一根 Open 成交；使用已有成本/限制 seam，不跨物理合约段、不在样本末强平。

### 6.4 测试

- HHV/LLV 数组、warm-up、同值、零成交量输入和非法 OHLC。
- 所有展示选择分支与护栏边界。
- 页面五窗口排序逐值 parity，包括页面评分的负收益/零回撤边界。
- 因果版 strict-before、prefix invariance、future-tail mutation、换月取消、成本和涨跌停。
- 页面版与因果版对同一输入必须产生不同身份，不能互换结果类型。

## 7. Slice C：综合决策与确定性评分

### 7.1 Formula identity

```text
newow_composite_decision_page_v3_2_82
newow_first_action_principle_page_v3_2_63
newow_composite_decision_cleanroom_v1
```

### 7.2 Core interface

```python
calculate_composite_decision(
    *,
    trend: MultiPeriodTrendState,
    oscillation: MultiPeriodOscillationState,
    daily_bars: Sequence[NewowResearchBar],
) -> CompositeDecision

calculate_first_action_principle(
    *,
    trend: WeeklyDailyTrendState,
    oscillation: MultiPeriodOscillationState,
) -> FirstActionPrinciple
```

返回 typed facts：趋势偏向、震荡偏向、方向判读、13 格决策 key、仓位下限/上限、确定性总分与四项分解、ATR20/Close 波动率、风险级别和解释 token。仓位使用 `Decimal` 比例；等待信号使用 `None`，不能用字符串 `--` 进入 Core。

### 7.3 合同

- 趋势：周线定基调，日线定回调，60 分定节奏。
- 震荡：周/日/60 分 holding/cleared/idle 映射为 bullish/bearish/neutral。
- page-exact 决策矩阵冻结当前公开 13 个表项和当前控制流。源码先判断“周线空头 -> bearish”，再判断“周线空头且日线多头 -> warning”，所以 `warning-*` 三项当前不可达；page-exact 必须保留并公开 `unreachable_decision_keys`，不能暗中修复。
- `calcFirstActionPrinciple` 是独立规则：它会把“周空、日多”识别为下跌中的反弹风险。其结果不能被综合决策覆盖或合并。
- clean-room 修正版若让 `warning-*` 可达，必须使用 `newow_composite_decision_cleanroom_v1`，并同时返回与 page-exact 的差异原因。
- 未列出的状态组合 fail-closed，不降级成 neutral。
- 确定性：趋势 30、震荡 30、共振 20、方向 20；冲突封顶 60，单边 neutral 封顶 85。
- 波动率：日线最新最多 20 个 TR 的算术平均除以 Close，低 `<2%`、中 `[2%,4%)`、高 `>=4%`。
- Core 只返回解释 token，不复制原站买卖建议文案；Web 使用归一量化自己的 observation-only 文案。

### 7.4 测试

- 13 格表项定义全覆盖；page-exact 可达性测试必须证明 `warning-*` 三项不可达，clean-room v1 单独证明修正后的可达性。
- 每个评分分支、60/85 封顶和方向分 3/5/10/20。
- 第一行动原则与综合决策对“周空、日多”的差异必须有显式回归测试。
- ATR 跨跳空 TR、最少 5 个有效 TR、Decimal 边界和非法/缺失数据拒绝。
- 合成笛卡尔积、真实股票页面样本和 prefix invariance。

## 8. Slice D：AI 诊股与选股行为反推

### 8.1 分层

AI 诊股拆为三个 module，避免把解释文案当公式：

1. `diagnostic_facts`：目标/吸筹、EMA20 操盘线、主力控盘、趋势阶段、距高点、持续周期等纯事实；
2. `diagnostic_rules`：根据冻结状态映射解释 token；
3. Web copy adapter：将 token 渲染为归一量化自己的研究观察文案。

页面六组合推荐保留独立 `page-parity` 复算器；可信候选选择只使用已有 anchored OOS/Walk-forward 结果，二者不得共享“推荐”返回类型。

### 8.2 选股反推

- 首页旧标签规则作为 `observed_legacy_filter_v3_2_82` 保存，不冒充新 `/api/screener` 实现。
- 当前服务端策略先建立 `ScreenerProbeObservation`，输入为请求 body、采集时间和响应字段，输出为不可变行为事实。
- 至少两次不同交易日或两个已冻结历史截面、每策略全量结果、字段分布和集合交并比后，才允许把规则从 `BEHAVIOR_INFERRED` 升级。
- `trend_build/mainrise_build/cup_handle` 必须分别与详情页趋势、主升浪、杯柄 primitive 做逐标的反算；不能用名称相似替代公式证明。
- 若服务端黑盒证据无法唯一识别规则，保持 `UNKNOWN`，只实现本项目自有、明确标注的 clean-room candidate；不得宣称页面 exact。

### 8.3 测试

- AI 事实与解释 token 分离；修改文案不改变公式结果。
- 六组合页面评分 parity 与 OOS selector 类型隔离。
- 筛选规则反例、缺字段、排序稳定性、集合边界和版本 hash 变化。
- 服务端规则证据不足时 constructor/factory 必须拒绝创建 `page-exact` identity。

## 9. Slice E：只读详情页集成

- 复用现有 `GET /api/v1/market/newow/trend-detail` 或新增同一 `/api/v1/market/newow/*` 下的 bounded read-only resource；不新增策略 Application Domain。
- API 只接受现有七周期、completed actual-dominant、显式公式 identity 和 bounded page query。
- 每个物理合约段独立 warm-up；不跨段延续状态。
- Web 只显示公式版本、数据 identity、重绘/因果/页面一致性标签和 observation-only 解释。
- 首页不增加买卖/仓位图标；Newow 详情不进入 `PROJECT_SOURCE.md` 稳定面，除非另行批准 release 设计。
- 无 DB migration、Redis、Scope、Alert、通知、scheduler 或 Runtime enable。

## 10. 文件结构

预期新增：

```text
packages/quant-core/guiyi_quant/newow/price_channel.py
packages/quant-core/guiyi_quant/newow/composite_decision.py
packages/quant-core/guiyi_quant/newow/diagnostic_facts.py
packages/quant-core/guiyi_quant/newow/diagnostic_rules.py
packages/quant-core/guiyi_quant/newow/screener_observation.py
services/quant-api/tests/newow/test_price_channel_page_v1.py
services/quant-api/tests/newow/test_price_channel_causal_v1.py
services/quant-api/tests/newow/test_composite_decision_page_v3_2_82.py
services/quant-api/tests/newow/test_diagnostic_rules.py
services/quant-api/tests/newow/test_screener_observation.py
docs/tasks/2026-09-04-newow-v3-2-82-coverage.md
```

按实际集成需要修改：

```text
packages/quant-core/guiyi_quant/newow/__init__.py
packages/quant-core/guiyi_quant/newow/research_backtest.py
services/quant-api/app/schemas/market_newow.py
services/quant-api/app/market_data/newow/trend_detail_service.py
services/quant-api/app/api/market_newow.py
apps/quant-web/src/types/newow.ts
apps/quant-web/src/utils/newowTypes.ts
apps/quant-web/src/utils/newowViewModel.ts
apps/quant-web/src/components/market/detail/TrendDetailWorkspace.vue
```

不得为本任务修改：Alert、Runtime、Scope、notification、订单、production migration 和 Canonical 写入路径。

## 11. 错误合同

新 module 使用稳定公开错误 code，至少包括：

```text
NEWOW_PRICE_CHANNEL_INVALID_WINDOW
NEWOW_PRICE_CHANNEL_MIXED_SERIES
NEWOW_DISPLAY_PRICE_FACTS_INCOMPLETE
NEWOW_PAGE_OPTIMIZER_UNTRUSTED_RESULT
NEWOW_COMPOSITE_STATE_UNSUPPORTED
NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT
NEWOW_SCREENER_EVIDENCE_INSUFFICIENT
NEWOW_FORMULA_IDENTITY_MISMATCH
```

缺数据、混周期、乱序、跨产品、跨 series kind、未知状态或公式版本不匹配均显式失败；不得静默选择方便的周期、填 0、缩短窗口或回退另一公式。

## 12. 验证和 Review Gate

每个 Slice 独立满足：

1. RED 合同测试先失败；
2. 最小实现 GREEN；
3. Ruff、Mypy、Newow 模块测试；
4. causality、strict-before、prefix invariance、future-tail mutation；
5. 外部金样本 parity 与 SHA-256 readback；
6. Standards 与 Spec 两路独立 Review，P1/P2 清零；
7. 独立 commit；只有 Slice Gate 通过后进入下一 Slice。

Slice E 追加 Web unit、typecheck、build 和 bounded E2E。全任务完成后才可发起合入 `develop`；合入不等于 release 或 Runtime Ready。

## 13. 完成定义

只有以下条件同时成立，才允许声明本设计范围内的“完整复刻”完成：

- coverage 表中所有公开可访问功能均为 `REPRODUCED_EXACT`、`CLEANROOM_IMPLEMENTED` 或有证据支持的 `REJECTED`；
- 任何剩余 `UNKNOWN` 都属于明确排除的私有/付费/不可观察范围，而不是已公开产品面；
- Slice A-E 的代码、测试、证据和两路 Review 全部通过；
- page-parity、causal-research、repainting 和 observation-only 身份在类型与 UI 上不可混淆；
- 股票 parity 和期货适配各自有证据，且没有把股票收益外推成期货结论；
- 仓库、PR 与 `develop` 状态可审计；没有 production mutation、release、Runtime 或通知副作用。

## 14. 2026-09-04 实施读回

Slice A-E 已实现为独立 Quant Core、只读 typed API 和 Trend Workspace。股票/指数证据为 3 指数 + 6 股票 × week/day/60min 的 27 个精确页面点；通道、展示选择、五窗口排名与统计、综合决策、确定度、波动率和第一行动共 16 个可比子项全部 27/27 matched。真实页面反例还证明周线视图必须优先当前周线 HHV/LLV，已以 `newow_target_absorb_display_selection_page_v2` 修复。AI 自然语言和 diagnostic token 没有稳定的页面机器合同，仍分别为 `unavailable` 和 clean-room。

真实期货数据链覆盖 rb/sc/m × 1d/1w/60m，9/9 series 通过。SC2302 在 D1/60m 有 owner Bar、在 W1 没有 owner Bar，已作为全局权威分段与周期 owner 子集的真实反例。27 个品种×周期×策略 OOS 单元中，18 个日线/60 分单元有运行结果，9 个周线单元因 `NEWOW_WEEKLY_EXECUTION_LIMIT_CONTRACT_INSUFFICIENT` 失败关闭。但现有外部包缺完整 Canonical OHLC Bar 和无数据库重放脚本，所以 18 个结果不得标记为可独立复算。

因此当前状态为 `PARTIAL / FINAL_REVIEW_BLOCKED`。下一个严格串行 Gate 是新授权一次只读 Catalog/MainContractMap/Canonical 快照，冻结 9 条完整输入并用无数据库脚本重放 18 个已有结果的单元。通过后才能继续周 K next-open 执行日 limit 合同和 9 个周线单元，然后再执行双路最终 Review。私有服务端选股公式保持排除范围内 `UNKNOWN`。
