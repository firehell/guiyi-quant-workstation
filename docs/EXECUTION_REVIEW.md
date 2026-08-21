# Execution Review V1

更新时间：2026-08-21

本文是 Execution Review 的长期业务 canonical。旧 Review Center、Signal/Strategy 应用和回测子系统仍已退役；本域只记录自然产生的苏冰机会、人工决策、真实手工执行过程与结构化复盘，不连接账户、不创建订单，`auto_order=false`。

## 入口与事实

- 唯一 eligible source 是不可变的 `subing_entry_signal_v1` `AlertEvent`；HTDY、未知 Rule、方向冲突和不合法多结果均拒绝。
- Alert 先独立提交 Event；Execution Review 故障不得反向阻断 Event 持久化或既有 one-shot 通知路径，
  本域不依赖具体通知 provider。
- 四张独立 Application Domain 表是 `trade_decisions`、`trade_episodes`、`trade_executions`、`trade_reviews`，不属于且不改变八表 Market Catalog。
- Web `/trade-records` 提供 `pending_decision / open / pending_review / done` 四状态、决策与纠错、执行时间线、复盘重建和轻量统计。

## Episode 与执行

- 一个品种最多一个 OPEN Episode；Episode 固定 origin Event 的真实合约和 LONG/SHORT 方向。
- 同方向、同合约的后续自然 Signal 可成为 ADD；跨合约不合并，反方向不自动反手，必须先结束旧 Episode。
- origin Signal 先形成 Decision，再触发真实 OPEN，且 `OPEN.trigger_decision_id` 指向该 origin Decision；同方向、同合约的后续 formal Signal 先形成新的 Decision，再触发 ADD，且 `ADD.trigger_decision_id` 指向该 later Decision。人工记录的 ADD/REDUCE/CLOSE 不由 Signal 触发，`trigger_decision_id = NULL`。仓位拓扑、加权平均成本和 realized points 由后端 `Decimal` 计算，客户端不重算。
- `DOMINANT_ROLL` 仅是对已 OPEN Episode 的系统估算结束：使用旧合约最后一个可验证的 completed Canonical 1m reference，不伪造真实 CLOSE；后续真实 CLOSE 通过完整时间线纠错替换该估算语义。
- 自动 roll reconcile 默认关闭，只能通过独立 Gate 激活；它不是 `AfterMarketUpdater` 内部职责，
  不 replay/backfill 历史。当前激活状态只看 `STATUS.md`。

## 行情重建与未来函数边界

- 所有历史读取只通过 `MarketDataService`；不直接读 Parquet、Redis、RQData 或 MainContractMap。
- Reconstruction 是 post-hoc read model，不持久化 Live 快照。默认 `signal` 模式截止 Event `bar_end`；只有用户显式切换 `full` 才显示后续完整走势。
- 行情不可用只使 Reconstruction 显式 unavailable，不阻断 Decision、Execution 或 Review。

## Trusted-partial multiplier

人民币辅助估算为：

```text
Estimated Gross PnL = realized_points × contract_multiplier_snapshot
```

参考文件与官方证据文件分别是：

```text
data/reference/product_trade_multipliers.csv
data/reference/product_trade_multipliers.sources.csv
```

正式合同是：

```text
multiplier reference product set
== official evidence product set
⊆ active product set
```

- 只能跟踪能由正式交易所页面、正式交易所附件或监管机构官方镜像唯一核验的正值；禁止猜值、第三方最终来源、FACTSHEET、月刊、搜索摘要、模型记忆或 RQData。
- reference/evidence 均不得重复或包含未知品种；每行 `derived_multiplier` 必须等于 reference multiplier。
- completeness 不阻断 Decision、Execution、Review 或 stats。缺失 multiplier 时，realized points、剩余手数、平均成本、执行时间线和复盘继续可用，人民币估算为 `null`；Web 明确显示“人民币估算不可用 / 该品种 multiplier 尚未核验”，不得显示为 0 或计算失败。
- Episode 创建时 snapshot 当时 reference。创建时缺失则 `contract_multiplier_snapshot` 与 `multiplier_policy_id` 均为 `NULL`；未来 reference 扩大不自动重写历史 Episode。
- 历史 NULL snapshot enrichment 若未来需要，必须作为独立任务设计并经过相应人工 Gate。active-60
  60/60 completion 也是独立 reference-data 目标，不是 Execution Review 可用性的前置条件。

人民币金额只用于辅助复盘，不是账户对账、净 PnL 或收益表现事实。

## Lightweight stats

ExecutionStats 只展示机会数、已处理/待处理数、执行/未执行数、决策完成率、执行率、Episode 工作状态、主要未执行原因与结构化复盘问题标签。筛选复用 symbol/direction/frequency；日期范围始终可以影响 ExecutionStats，但在工作列表中只影响 done，pending_decision / open / pending_review 不得被日期范围过滤；不设隐含 30 天窗口。

V1 不提供 PnL ranking、win rate、Sharpe、MFE/MAE、profit factor 或策略盈利结论。统计不可用不得遮蔽交易记录工作区。

## 外部 Gate

代码与测试不授权 release、production migration、Runtime switch、roll marker、真实通知、Scope 或订单。
这些外部操作始终是相互独立的人工 Gate；当前 migration、Runtime 与 roll marker 状态只看 `STATUS.md`。
