# Newow 期货可信验证合同

日期：2026-09-04
状态：`IMPLEMENTED / EVIDENCE_PARTIAL`
基线：`develop@18db2d57055f8fb609e36328a89274b7bf415048`
分支：`codex/newow-futures-validation`

## 1. 本阶段结论

本阶段补齐的是“怎样可信验证”的研究合同，不是“策略已经在期货上有效”的结论：

- 页面公式仍使用已冻结、已通过指数与个股逐字段复算的版本身份；
- `strategy`、声明的 formula lineage 与每个 intent 必须属于同一冻结公式集合；低层调用省略身份时只能从单一策略的 intents 或完整 lineage 唯一推导，禁止跨策略混搭；
- Canonical actual-dominant 的 D1、W1、60m 必须分别由 `MarketDataService` 查询和解析；
- 每个 Bar 只能使用响应中唯一覆盖其交易日的 physical-contract segment；
- 下一根开盘只能尝试一次，涨停买、跌停卖或零成交量会产生明确拒绝记录；
- multiplier、tick、手续费与涨跌停必须来自带来源和生效区间的研究快照；
- 固定公式 Walk-forward 只把训练区作为 causal warm-up，测试区从空仓开始，不优化参数；
- 未平仓、换月持仓、换月 pending intent 与样本末 intent 都不伪造平仓收益。

没有新增 API、CLI、数据库表、Runtime、Alert、通知或订单入口。

## 2. 与指数和个股证据的关系

前一阶段覆盖 3 个指数和 6 只不同风格股票，并保留逐行浏览器 JSON、截图与 SHA-256 manifest。它证明页面公式在不同证券标的上的复算一致性，也揭示页面同 Bar 成交、零成本、收益相加和期末强平的收益偏差。

这些股票结果不能替代期货证据。本阶段只复用公式身份，不把股票收益、指数收益或页面推荐结论带入期货 OOS 结论。

## 3. 数据入口

`build_newow_research_bars()` 只接受完整 `MarketSeriesResult`，并要求显式传入 `ActualDominantResearchSegmentLoader.load(...).authoritative_segments` 返回的完整权威段：

```text
series_kind = actual_dominant
symbol = expected product
frequency = independently requested 1d | 1w | 60m
contract = null
coverage = exact first/last returned Bar
requested_trading_day_window = present and covering all Bars
resolved_contract_segments = non-empty, non-overlapping clipped owner facts
authoritative_segments = non-empty, non-overlapping full owner facts
```

每根 Canonical Bar 必须：

- 时间严格递增；
- physical contract 必须是合法月份且前缀属于当前 product；
- volume 与 open_interest 为整数事实；
- 被且只被一个响应 segment 和一个权威 segment 覆盖，且两者 contract 一致；
- source identity 由 Bar 事实生成，segment identity 由完整权威段边界生成，延长查询窗口保持不变；
- 标记为 historical completed / observation eligible。

任何 identity、coverage、segment 或数值冲突统一返回 `NEWOW_FUTURES_SERIES_INVALID`。适配器不读取 Parquet 路径、不自行选择主力、不回退 continuous，也不从 D1 推断 W1 owner。

### 3.1 SC2302 既有只读反例修正

`develop` 已接受的回归 `0a0b0f8fc` 与修复 `8c5a4c536` 编码了一个 SC2302 型反例：短 rank1 段可能有 D1/60m Bar，而首根完整 W1 Bar 已属于下一合约。因此某周期的 observed-owner 子集可以省略没有 completed Bar 的全局段，不能用跨周期 segment tuple 完全相等作为身份 Gate。该回归所依据的原始 production artifact 路径与 SHA-256 当前为 `BLOCKING_UNKNOWN`；其中具体日期和合约只能作为回归背景，不能计入本轮 real-futures evidence。

修正后的 loader 先从 `MarketDataService.actual_dominant_segments()` 获取全局 MainContractMap 完整分段，
以首段真实起点读取每个周期一次 causal prefix，再逐 Bar 检查响应 owner 与全局 owner。某周期没有 Bar
的全局分段可以不出现在该周期响应中；Calendar、MainContractMap、Partition、coverage 和物理可读性
仍由 `MarketDataService` fail-closed，loader 不以“没有观察到 Bar”推断数据完整。

## 4. 成本与可成交性

八表 Catalog 的长期合同明确不保存手续费规则；历史 `fee_margin_rules` 已退役，不能为了本研究复活第九张表。当前 `contracts.contract_multiplier` 也不足以单独证明一次历史回测所需的完整成本事实。

因此严格研究模式要求显式输入：

### 4.1 `BacktestCostSnapshot`

```text
product
physical_contract
[effective_from, effective_to)
captured_at
source_identity
commission_rate
commission_per_contract
contract_multiplier
slippage_bps
price_tick
slippage_ticks
```

严格模式下，整个 causal prefix 的每根 Bar 都必须恰好命中一个同品种、同合约、生效日覆盖且含 `price_tick` 的快照；拟成交继续使用该 Bar 的精确快照。持仓存续期间逐 Bar 比较 multiplier，不能只比较进出场。缺失、重叠或同合约持仓期间 multiplier 改变均 fail-closed。

### 4.2 `BacktestExecutionConstraint`

```text
exact bar_source_identity
physical_contract
limit_up
limit_down
captured_at
source_identity
```

严格模式下，每次拟成交都必须命中一条精确 Bar 约束，Canonical OHLC 和涨跌停价都必须落在 cost snapshot 指定的 tick 网格上。Bar 超出上下限或价格不在 tick 网格属于冲突；next-open 原始开盘价处于买入涨停或卖出跌停、或该 Bar volume 为零时，产生 `RejectedFill`：

```text
BUY_AT_LIMIT_UP
SELL_AT_LIMIT_DOWN
ZERO_VOLUME
```

拒绝只消费本次 next-open intent，不会自动顺延到更有利的后续 Bar。若被拒的是 CLEAR，持仓继续保持，直到新的独立 CLEAR 信号、换月排除或样本末排除。

若原始开盘价未锁板，但加入滑点后的候选成交价越过合法涨跌停，成交价保守截到对应上下限；这种情况不伪装成“开盘锁板”拒绝。

## 5. 换月与 warm-up

趋势、震荡和主升浪 primitive 已分别在 `(physical_contract, segment_id)` 变化时重置递归状态。真实 evidence 输入现在先通过 `MarketDataService.query_contract_trading_days(ContractTradingDayQuery(...))`，由 Catalog `contract_fact` 上市/到期生命周期夹取每个 observed segment 的完整物理合约 prefix；prefix Bar 推进公式状态但 `observation_eligible=false`，只有与 actual-dominant Bar 逐字段一致的 Bar 才能产生正式 intent。`build_strategy_intents_from_replay_segments()` 对每个 physical segment 从空状态重放，Walk-forward 另行使用 actual-dominant Bars 做 next-open execution。

执行器仍保持：

- 换月时取消旧合约 pending intent；
- 旧合约未平仓标记 `DOMINANT_ROLL_EXCLUDED`；
- 不把旧合约盈亏跨月拼到新合约；
- 新合约只使用其自身已提供的历史前缀。

这证明代码合同，不证明当前 production Canonical 每个主力段已经拥有足够 warm-up Bar。真实覆盖仍是外部 evidence Gate。

## 6. 固定公式 Walk-forward

`run_fixed_formula_walk_forward()` 接受显式 folds：

```text
train_since <= train_through < test_since <= test_through
```

测试窗口不得重叠；完整输入在切 fold 前必须先通过单一 product、单一 frequency、严格时间顺序与 source identity 校验。每个 fold 的显式 `[train_since, train_through]` 和测试窗都必须至少包含一根 Bar；训练结束至测试开始之间的 gap Bar 只计入 causal warm-up，不能冒充训练样本。每个 fold：

1. 读取每个 observed segment 的同周期完整 physical-contract causal prefix，并严格匹配 actual-dominant execution Bars；
2. 用训练历史和 test 前已知 Bar 推进固定公式状态；
3. 丢弃 test 起点之前的所有意图，并清除震荡策略训练期的 holding 状态，以空仓进入测试；
4. 只执行 signal Bar 落在测试窗口内的 intent；
5. 强制使用 sourced cost 与 execution facts；
6. 只聚合已平仓 OOS trade，保留所有 rejected/incomplete 事实。

该流程没有训练器、目标函数或参数搜索。“Walk-forward”在这里表示固定公式的滚动样本外复算，不表示已经找到最优参数。

## 7. 当前验证证据

本阶段测试使用完整 domain value object 与 production-shaped fixture，未连接生产 PostgreSQL/Redis，未调用 RQData，未修改 1.7GB 本地 Canonical。

定向结果：

```text
test_research_backtest.py       32 passed
test_futures_validation.py      21 passed
test_research_walk_forward.py   12 passed
new evidence contract tests      7 passed
Ruff targeted                   passed
Mypy canonical scope            passed (108 source files)
完整 Newow 回归                 516 passed in 198.46s
```

当前 dossier 还记录了 2026-09-04 已完成的只读真实期货证据：`rb/sc/m × 1d/1w/60m`
9/9 条 actual-dominant series 通过数据与 owner 合同验证；27 个固定公式 OOS 单元中，18 个 D1/60m
单元 passed，9 个 W1 单元 fail-closed。详细边界以
`docs/research/newow-v3.2.82/REPORT.md`、
`docs/research/newow-v3.2.82/evidence/futures-validation-summary.json` 和
`docs/research/newow-v3.2.82/evidence/oos-cost-stress-matrix.json` 为准。

## 8. 真实期货证据矩阵（部分完成）

已有 dossier 证据覆盖：

- `rb`（黑色）、`sc`（能化）、`m`（农产品）三个经济属性不同的品种；
- `1d`、`1w`、`60m` 三个独立周期，共 9/9 series passed；
- `rb` 和 `m` 各 7 个权威分段/6 次换月，`sc` 为 25 个权威分段/24 次换月；
- 27 个 OOS 单元中，18 个日线/60 分单元 passed，且每个都记录 baseline、双手续费和双滑点三种场景；
- 9 个周线单元 blocked，公开原因为 `NEWOW_WEEKLY_EXECUTION_LIMIT_CONTRACT_INSUFFICIENT`；周 K OHLC 与下一执行交易日 limit 的身份不能由周首或周末单日事实替代，不得删除校验或借用日线结果补齐；
- 公式参数在运行中保持冻结，没有用 OOS 结果反向调参。

这些证据只能支持“部分真实期货运行结果存在”。GitHub-safe dossier 没有分发完整 Canonical Bar
输入，也没有无数据库重放脚本，所以当前冻结包仍不能让独立第三方复算 18 个 passed
单元。已完成单元同时存在正负结果，不支持“策略盈利”、“候选可晋升”、“已发布”或 `Runtime Ready`
结论。

## 9. 未完成 Gate

- 经独立 Owner Gate 授权后，为 18 个 passed 单元补齐本地完整冻结包所需的 Canonical Bar 输入和无数据库重放脚本，并完成独立复算；GitHub-safe dossier 仍不分发 RQData/Canonical 原文；
- 为 W1 建立可信的“下一执行交易日” limit 身份与事实，重新运行当前 9 个 blocked 单元；
- 对完整重放包、周线 Gate 与最终证据进行独立 Review；
- 用户人工决定候选淘汰、继续观察或另开新版本；
- release、main、Runtime promotion 仍是后续独立人工 Gate。

因此当前只能声明 `IMPLEMENTED / EVIDENCE_PARTIAL`，不能声明收益可信、策略候选、已发布或 Runtime Ready。
