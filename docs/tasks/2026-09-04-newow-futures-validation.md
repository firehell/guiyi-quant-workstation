# Newow 期货可信验证合同

日期：2026-09-04
状态：`CODE_COMPLETE / TEST_COMPLETE / REAL_FUTURES_EVIDENCE_PENDING`
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

### 3.1 SC2302 真实反例修正

只读生产证据显示，`sc` 的 `SC2302` rank1 仅覆盖 2023-01-03～2023-01-04；第一根完整 W1 Bar
结束于 2023-01-06，owner 已是 `SC2303`。因此 D1/60m owner 子集包含 `SC2302`，W1 owner 子集省略
`SC2302` 是合法周期事实，不能用跨周期 segment tuple 完全相等作为身份 Gate。

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

趋势、震荡和主升浪 primitive 已分别在 `(physical_contract, segment_id)` 变化时重置递归状态；本阶段没有增加第二套重置器。`build_strategy_intents()` 只是公开这一既有、segment-safe 的 causal seam，供 Walk-forward 重用。

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

1. 读取 train 起点至 test 终点的同周期 causal prefix；
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
test_research_backtest.py       30 passed
test_futures_validation.py      14 passed
test_research_walk_forward.py    9 passed
Ruff targeted                   passed
Mypy canonical scope            passed (105 source files)
完整 Newow 回归                 496 passed in 195.40s
```

## 8. 真实期货证据矩阵

后续一次受控、只读的真实证据运行至少覆盖：

- 三个经济属性不同的活跃品种，例如黑色、能化、农产品各一个；
- `1d`、`1w`、`60m` 三个独立周期；
- 每品种至少两个已发生主力换月，历史不足时必须明确标记不足，不能缩小标准后宣称通过；
- 每个周期的 Bar 数、segment 数、合约分布、warm-up 长度和缺失事实；
- 每条 cost/limit snapshot 的来源、采集时间、生效区间与 SHA-256；
- next-open fill、rejected fill、roll/end incomplete position 和 closed trade 数；
- 每个 OOS fold 的收益、回撤、胜负与交易数；
- 基准成本、加倍手续费、加倍滑点三种压力场景；
- 参数身份必须保持冻结，不以 OOS 结果反向改参数。

## 9. 未完成 Gate

- 只读 production Catalog/MainContractMap 查询授权；
- 真实 D1/W1/60m actual-dominant Bar 与至少两次 rollover 证据；
- 可信的历史 multiplier、tick、手续费和涨跌停快照来源；
- 三品种固定公式 OOS/Walk-forward 与成本压力结果；
- 独立 Review；
- 用户人工决定候选淘汰、继续观察或另开新版本；
- release、main、Runtime promotion 仍是后续独立人工 Gate。

因此当前不能声明收益可信、策略候选、已发布或 Runtime Ready。
