# TASK-JDJ-ACTIVE60-ROBUSTNESS-V1-20260821 — 执行合同

> 状态：PLANNED_ONLY
>
> Design：`docs/superpowers/specs/2026-08-21-jdj-active60-robustness-v1-design.md`
>
> Plan：`docs/superpowers/plans/2026-08-21-jdj-active60-robustness-v1.md`
>
> 当前提交只冻结 Phase 7 实施合同，不实现代码、不运行真实 active60 evidence、不修改 `main`/tag/Runtime/Alert/DB/Canonical，也不形成 Candidate 晋升授权。

## 1. Goal / Boundary

只实现：

```text
existing frozen JDJ V1
→ active60 exact retrospective
→ per-symbol single shared load
→ 3 exact reducers on shared context
→ event + price-only outcomes
→ 180 Candidate×Symbol lightweight cells
→ yearly diagnostics without reload
→ symbol-balanced sector summaries
→ one read-only research evidence
```

不实现：

```text
generic robustness platform
new coverage subsystem
active60 rolling-validation engine
parameter sweep
candidate variants
LONG/SHORT outcome matrix
quartile distribution layer
score/rank/winner/KEEP/DROP/PROMOTE
five-candidate relationship matrix
prospective OOS consumption
Web/API/DB/Redis/worker/queue/cache
Alert/PushPlus/Execution Review
fill/slippage/fee/position/capital/PnL/backtest/order
main/tag/release/Runtime
```

始终：`research_only=true`、`readonly=true`、`auto_order=false`。

## 2. Mandatory fact sources

每个 Task 开始前必须读取：

```text
STATUS.md
AGENTS.md
docs/DEVELOPMENT.md
PROJECT_SOURCE.md
DECISIONS.md
Design
Plan
本合同
current implementation/tests
```

冲突时：`BLOCKED_CANONICAL_DRIFT`。

## 3. Exact identities

Phase 7 protocol：

```text
protocol_id = jdj_active60_robustness_v1
common_retrospective = 2023-01-01..2026-08-20
embargo = 2026-08-21
prospective_first = 2026-08-24
prospective_consumed = false
horizons = 3/5/8/20
```

Candidate 顺序固定：

```text
jdj_trend_follow_1m_candidate_v1
jdj_trend_reentry_6_1m_candidate_v1
jdj_key_level_breakout_1m_candidate_v1
```

Source identities 必须继续精确等于：

```text
policy_id = jdj_1m_policy_v1
formula_version = jdj_1m_v1
validation_protocol = jdj_candidate_validation_v1
```

任何 Candidate/policy/formula/date/horizon 漂移均阻塞，不在 Phase 7 中兼容或修改。

## 4. Historical identity and single-load rule

唯一读取链：

```text
MarketDataService
→ ActualDominantResearchSegmentLoader
```

每个 frozen active60 symbol 的 full retrospective：

```python
loader.load(
    symbol=symbol,
    frequencies=(BarFrequency.M1, BarFrequency.M5),
    since=date(2023, 1, 1),
    through=date(2026, 8, 20),
)
```

Phase 7 每个 symbol 只调用一次上述 shared loader。loader 内部既有 probe/full MDS 查询语义保持不变，不要求改变底层 MarketDataService 物理查询数。

三个 JDJ reducer 必须共享同一 loaded series 与同一 segment-level JDJ context；禁止为三个 Candidate 各自重载行情或复制 EMA/N/JDJ 公式。

## 5. JDJ parity is a hard gate

对同一 deterministic fixture，existing `JdjResearchService.run()` 与 Phase 7 shared batch seam 投影必须 exact equal：

```text
event ids
event order
trigger_count_long
trigger_count_short
evaluable_bar_count
3/5/8/20 sample_count
median directional_return_bps
median MFE_bps
median MAE_bps
```

任何差异均为阻塞；不得通过修改旧 golden expectation 接受漂移。

## 6. OOS contamination is forbidden

Phase 7 protocol-owned source window只能是：

```text
2023-01-01..2026-08-20
```

不得消费：

```text
2026-08-21 embargo
2026-08-24+ prospective OOS
```

Report 允许记录：

```text
prospective_first_trading_day=2026-08-24
prospective_consumed=false
```

但不得出现任何 prospective event/metric/OOS summary。

## 7. Active60 and taxonomy identity

Protocol JSON 冻结 exact ordered 60 products 与 exact `{product, sector}` mapping。

运行时必须 readback current：

```text
data/universe/active_products.txt
data/universe/product_sectors.csv
```

与 frozen protocol 完全一致；不一致时全局 fail-closed。不得在运行时用 current taxonomy 静默覆盖 frozen mapping。

## 8. Availability semantics

只允许：

```text
available
unavailable
```

`available`：shared loader 能建立合法 1m+5m actual-dominant Historical source。即使上市较晚，只要 source 合法仍 available。

`unavailable`：MarketData source、rank1 segment identity 或必要 Historical source 无法合法建立。

available cell 记录：

```text
observed_since
observed_through
```

二者精确定义为 validated loaded 1m bars 与 common retrospective 相交后的最小/最大 `trading_day`；loader 为恢复 segment 所读取的窗口外 warm-up 不进入这两个字段。

`0 event` 不等于 unavailable。

## 9. Exact 180-cell symbol facts

必须保留：

```text
3 Candidates × 60 products = 180 cells
```

顺序固定为 candidate-major，再按 protocol frozen product order。

每个 available cell 只含：

```text
candidate_id
symbol
sector
status
reason_code=null
observed_since
observed_through
evaluable_bar_count
event_count
long_event_count
short_event_count
event_rate_per_1000_evaluable
horizon_summary[3|5|8|20]
yearly[2023|2024|2025|2026]
```

Unavailable cell 保留 identity/status/reason，其观察与 metric 字段为 null；不得从 report 中删除该 cell。

## 10. Exact horizon facts

每个 horizon 只允许：

```text
sample_count
historical_positive_outcome_rate
median_directional_return_bps
median_mfe_bps
median_mae_bps
```

其中：

```text
historical_positive_outcome_rate
= count(directional_return_bps > 0) / sample_count
```

使用 `Decimal`。

`sample_count=0` 时：rate 与三个 median 全部为 `null`，不能写成 0。

不得使用“胜率”“盈利概率”“策略成功率”描述该字段。

## 11. Event rate

```text
event_rate_per_1000_evaluable
= event_count * 1000 / evaluable_bar_count
```

使用 `Decimal`。`evaluable_bar_count=0` 时为 `null`。

## 12. Yearly diagnostic

固定年份：

```text
2023
2024
2025
2026 YTD through 2026-08-20
```

年度事实只能从一次 full retrospective 已产生的 event/outcome 按 `event.trading_day.year` 分组；不得再次调用 shared loader/MarketDataService。

每年只含：

```text
event_count
horizon 3/5/8/20:
  sample_count
  historical_positive_outcome_rate
  median_directional_return_bps
```

Yearly diagnostic 不是 rolling/walk-forward/OOS。

## 13. Sector aggregation

Sector 使用 frozen taxonomy，且严格 symbol-balanced：

```text
one symbol = one vote
```

每个 `Candidate × Sector`：

```text
symbol_count
available_symbol_count
symbols_with_events
horizon 3/5/8/20:
  symbols_with_samples
  positive_median_symbol_count
  zero_median_symbol_count
  negative_median_symbol_count
  median_of_symbol_median_return_bps
```

positive/zero/negative 判定对象是每个 symbol 自己的 median directional return。

禁止：

```text
event pooling
sector score
sector ranking
best sector
active60 pooled performance
```

复制单个 symbol 的 event 数不得提高其 sector 权重。

## 14. Quality flags

只允许固定顺序子集：

```text
SOURCE_UNAVAILABLE_PRESENT
SYMBOL_WITHOUT_EVENT
HORIZON_WITHOUT_SAMPLE
SHORT_HISTORY_PRESENT
```

`SHORT_HISTORY_PRESENT` 仅表示至少一个 available symbol 的 `observed_since > 2023-01-01`。

Flag 不是 PASS/FAIL 或晋升结论。

## 15. CLI contract

唯一新增使用方式：

```bash
guiyi research candidate-robustness \
  --protocol jdj_active60_robustness_v1
```

继续保留 existing：

```text
multi_candidate_robustness_v1
```

Phase 7 不新增：

```text
--since
--through
--symbols
--threshold
--score
--rank
```

实验设计只来自 exact protocol。

## 16. Old robustness immutable

以下不得修改业务 identity/schema/evidence：

```text
data/research_protocols/multi_candidate_robustness_v1.json
services/quant-api/app/market_data/multi_candidate_robustness.py
services/quant-api/app/market_data/multi_candidate_robustness_policy.py
reports/research/candidate_robustness/multi_candidate_robustness_v1/anchor-jm-active60-retrospective-freeze-2026-08-20.json
```

已有相关测试必须继续通过。

## 17. Evidence contract

真实 evidence 只允许一份：

```text
reports/research/candidate_robustness/
  jdj_active60_robustness_v1/
    active60-retrospective-freeze-2026-08-21.json
```

生成命令只读既有 Historical Canonical/Catalog，不执行 RQData update/refresh、migration、Redis/Live/Alert 或 backfill。

Evidence 必须可重复复算；不新增 checksum/receipt/packet 体系。

## 18. Completion claim

技术完成只允许声明：

> 三个冻结 JDJ Candidate 已在统一 active60 retrospective protocol 下形成跨品种、跨年份和板块维度的可复算历史研究事实。

不得声明：

```text
策略有效
策略盈利
胜率
未来盈利概率
最佳 Candidate
最佳板块
KEEP/DROP/PROMOTE
Alert/Runtime/trading ready
```

## 19. Task/Lane execution

本阶段实现按 Plan 固定五个 Task：

```text
Task 1 exact protocol/report contracts
Task 2 shared JDJ batch/detail seam + parity
Task 3 active60/year/sector robustness service
Task 4 existing CLI/composition wiring
Task 5 real read-only evidence + canonical closeout
```

五个 Task 均为 Lane 1；因涉及 causal parity、OOS 污染和 research evidence，固定使用 Sol + 高推理。每个任务独立会话、独立 task branch/worktree、独立 Review；测试与 Review C0/I0 后可集成 `develop` 并清理。

任何 Task 的 `develop` 集成都不授权 `main`、tag、release、Runtime promotion、DB/Canonical/Redis mutation、真实通知或订单。
