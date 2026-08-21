# Phase 7 — JDJ Active60 Robustness V1 Design

状态：DESIGN_APPROVED / IMPLEMENTATION_NOT_STARTED
日期：2026-08-21
设计冻结：2026-08-21T20:34:00+08:00
阶段属性：research-only / historical-only / read-only / no promotion

## 1. 目标

Phase 7 只回答一个问题：

> 已冻结的三个 JDJ 1m Candidate 离开焦煤 `jm` 后，在 active60 的不同品种、板块和年份中，是否仍呈现可复算的历史研究特征？

研究对象固定为：

- `jdj_trend_follow_1m_candidate_v1`
- `jdj_trend_reentry_6_1m_candidate_v1`
- `jdj_key_level_breakout_1m_candidate_v1`

本阶段不修改 Candidate 公式，不寻找新参数，不比较 SuBing/N，不做 Candidate 排名或晋升。

Phase 7 的价值是把“只在 `jm` 上有 baseline”扩展成“同一冻结公式在 active60 上的横向事实”，用于后续人工研究收敛；它不是新的策略平台、回测平台或生产信号模块。

## 2. 设计原则：个人工作站优先

归一量化是个人开发、个人维护的本地研究工作站。本阶段采用最小实现：

```text
一个 exact protocol
+ 一个轻量 report contract
+ 一个只读 robustness service
+ 复用现有 research CLI
```

明确不新增：

- 通用 Strategy Robustness Platform；
- 第二套 coverage 系统；
- 60 品种独立 rolling-validation engine；
- score/rank/winner engine；
- worker / queue / job state / DB persistence；
- Web / API / Alert / Runtime 业务面。

实现过程中如出现大量 generic registry、DSL、调度框架或 5 个以上新的 robustness 专用业务模块，应视为范围膨胀并重新审查。

## 3. 事实链与不可变来源

Historical 唯一事实链保持：

```text
RQData
→ Canonical Parquet
→ eight-table Catalog
→ MarketDataService
→ ActualDominantResearchSegmentLoader
→ JDJ research
→ Phase 7 read-only report
```

Phase 7 不直接读 Parquet、RQData 或 Redis，不复制主力 resolver，不自行拼接 actual-dominant。

三个 Candidate 继续使用现有：

- `jdj_1m_policy_v1`
- `jdj_candidate_validation_v1`
- 1m EMA20；
- existing 5m N Structure V1 strict-before context；
- existing three causal reducers；
- existing price-only outcome semantics。

任何 JDJ policy / Candidate manifest / validation protocol 漂移必须 fail-closed，不得在 Phase 7 中兼容或修正。

## 4. Exact Phase 7 Protocol

新增 exact protocol：

```text
jdj_active60_robustness_v1
```

固定语义：

```text
schema_version = 1
research_only = true
readonly = true
frozen_at = 2026-08-21T20:34:00+08:00

candidates =
  jdj_trend_follow_1m_candidate_v1
  jdj_trend_reentry_6_1m_candidate_v1
  jdj_key_level_breakout_1m_candidate_v1

source_policy = jdj_1m_policy_v1
source_validation_protocol = jdj_candidate_validation_v1

common_retrospective = 2023-01-01 .. 2026-08-20
embargo_trading_days = [2026-08-21]
prospective_first_trading_day = 2026-08-24
prospective_consumed = false

horizons_bars = [3, 5, 8, 20]
cross_symbol_products = exact active60 snapshot
sector_groups = exact current active60 taxonomy snapshot

parameter_perturbation = false
relationship_analysis = false
automatic_ranking = false
automatic_promotion = false
```

`cross_symbol_products` 与 `sector_groups` 在 protocol JSON 内冻结。`sector_groups` 的机械形状固定为 `sector -> ordered symbols`：sector key 使用当前 taxonomy 的固定允许值，symbol 只出现一次，各组并集精确等于 `cross_symbol_products`，组内顺序继承 `cross_symbol_products`。实现时当前 active60 / taxonomy 必须与 protocol 逐品种精确一致；发生漂移时阻塞本 protocol，而不是静默改写历史研究定义。

## 5. 时间边界与 OOS 隔离

所有 active60 品种统一使用：

```text
2023-01-01 .. 2026-08-20
```

Phase 7 只消费 retrospective Historical Canonical。

必须硬拒绝：

- `2026-08-21` embargo；
- `2026-08-24` 及之后 prospective OOS；
- 任何动态向后扩窗。

Report 可以记录：

```text
prospective_first_trading_day = 2026-08-24
prospective_consumed = false
```

但不能包含任何 prospective event、metric 或 OOS summary。

## 6. 数据可用性：保持简单

Phase 7 不建立新的 FULL/PARTIAL/UNAVAILABLE coverage domain，也不重新实现 Data Foundation coverage 校验。

每个品种只记录：

```text
status = available | unavailable
reason_code
observed_since
observed_through
```

其中 `observed_since/observed_through` 精确定义为：validated loaded 1m bars 与 `common_retrospective` 相交后的最小/最大 `trading_day`；shared loader 为恢复 rank1 segment 而读取的窗口外 warm-up bars 不进入这两个字段。

规则：

- shared loader / MarketDataService 能建立合法 1m+5m actual-dominant source，则 `available`；
- source、rank1 identity 或必要历史事实无法建立，则 `unavailable`；
- 合法但上市较晚的品种仍是 `available`，其 `observed_since` 显式反映实际历史起点；
- 不为凑齐共同窗口回填、跨源替代、缩短 protocol 或吞入 OOS。

`0 event` 与 `unavailable` 必须严格区分。

## 7. 关键工程优化：一个品种只加载一次

三个 JDJ Candidate 共用同一份：

```text
actual-dominant 1m
actual-dominant 5m
EMA20
5m N Structure context
```

Phase 7 固定执行模型：

```text
for symbol in active60:
    call shared loader once for 1m + 5m
    build shared JDJ context once
    run Trend Follow reducer
    run Trend Reentry 6 reducer
    run Key-Level Breakout reducer
    build price-only outcomes
```

这里的“加载一次”精确指每个 `symbol + full retrospective window` 只调用一次 `ActualDominantResearchSegmentLoader.load(... frequencies=(1m,5m) ...)`；该 shared loader 内部既有的 probe/full MDS 查询语义保持不变，不要求把底层 MarketDataService 物理查询压缩成一次。

不得为三个 Candidate 分别重复调用 shared loader，更不得为年度统计重新读行情。

V1 默认串行执行；不新增 multiprocessing、async worker、queue 或 cache layer。只有真实运行证明串行不可接受时，未来才能单独立项有限并发。

## 8. 不复制 JDJ 公式

为了支持单次加载和 per-event outcome 分布，允许对现有 JDJ research 层做最小、加法式重构：

- 抽出共享的 symbol/window source evaluation seam；
- `JdjResearchService.run()` 继续保持原 public contract 和行为；
- Phase 7 batch 路径与普通 JDJ research 路径必须复用相同 context、reducers、event alignment 与 price outcome 计算；
- 禁止在 `jdj_robustness*` 文件内复制 EMA/N/JDJ reducer 公式。

必须建立 parity invariant：新共享 seam 投影回旧 `JdjResearchResult` 时，下列值与当前行为 exact equal：

```text
event ids / event order
trigger_count_long / trigger_count_short
evaluable_bar_count
3/5/8/20 sample_count
median directional return
median MFE
median MAE
```

任何 parity 失败都阻塞 Phase 7。

## 9. 单品种统计

最终必须完整保留：

```text
3 Candidates × 60 products = 180 cells
```

每个 `Candidate × Symbol` cell 只保存必要事实：

```text
candidate_id
symbol
sector
status
reason_code
observed_since
observed_through

evaluable_bar_count
event_count
long_event_count
short_event_count
event_rate_per_1000_evaluable

horizon_summary[3|5|8|20]
```

`event_rate_per_1000_evaluable = event_count * 1000 / evaluable_bar_count`；当 `evaluable_bar_count=0` 时该值必须为 `null`。

每个 horizon 固定：

```text
sample_count
historical_positive_outcome_rate
median_directional_return_bps
median_mfe_bps
median_mae_bps
```

`historical_positive_outcome_rate` 的精确含义只是：

> 历史 source event 在该 horizon 的 directional return 大于 0 的样本占比。

不得称为“胜率”“盈利概率”或“策略成功率”。

当 `sample_count=0` 时，rate 和全部 median 必须为 `null`，不能写成 0。

## 10. 年度稳定性：零额外行情读取

Phase 7 不对 active60 重跑 10-fold Candidate Validation。时间稳定性采用轻量 yearly diagnostic：

```text
2023
2024
2025
2026 YTD（截至 2026-08-20）
```

年度数据只从本次完整 retrospective 已产生的 event/outcome 按 `trading_day.year` 分组，不重新请求 MarketDataService。

每个 `Candidate × Symbol × Year` 只保存：

```text
event_count

horizon_summary[3|5|8|20]:
  sample_count
  historical_positive_outcome_rate
  median_directional_return_bps
```

该 yearly summary 是诊断性事实，不替代 Phase 6 在 `jm` 上已经冻结的 10-fold Candidate Validation，也不形成新的 walk-forward/OOS 语义。

## 11. 板块汇总：symbol-balanced

复用已存在的 active60 一级 taxonomy。板块仅做描述性汇总，不做 event pooling。

原则：

```text
一个 symbol = 一票
```

每个 `Candidate × Sector` 保存：

```text
symbol_count
available_symbol_count
symbols_with_events

horizon_summary[3|5|8|20]:
  symbols_with_samples
  positive_median_symbol_count
  zero_median_symbol_count
  negative_median_symbol_count
  median_of_symbol_median_return_bps
```

其中 positive/zero/negative 判断的是每个 symbol 自己的 `median_directional_return_bps`。

禁止：

- 把板块所有 events 混池计算；
- 生成板块 score；
- 对板块排序；
- 输出“最佳板块”。

Phase 7 不生成 active60 overall pooled performance aggregate，避免一个全市场单值掩盖品种差异。

## 12. Report 顶层结构

一份主 evidence 足够：

```text
reports/research/candidate_robustness/
  jdj_active60_robustness_v1/
    active60-retrospective-freeze-2026-08-21.json
```

顶层固定包含：

```text
schema_version
command
protocol_id
frozen_at
research_only
readonly

common_retrospective
embargo_trading_days
prospective_oos
prospective_consumed

candidate_ids
cross_symbol_results      # exact 180 cells
sector_summaries
quality_flags
```

不拆 180 个独立文件，不写 DB/Canonical/Redis。

## 13. Quality Flags

只保留少量描述性 flag：

```text
SOURCE_UNAVAILABLE_PRESENT
SYMBOL_WITHOUT_EVENT
HORIZON_WITHOUT_SAMPLE
SHORT_HISTORY_PRESENT
```

`SHORT_HISTORY_PRESENT` 表示至少一个 `available` symbol 的 `observed_since` 晚于 common retrospective 起点，仅提示比较时注意历史长度差异；它不改变该 symbol 的可用状态，也不触发第二套 coverage 逻辑。

这些 flag 不是 PASS/FAIL、KEEP/DROP/PROMOTE。

## 14. Fail-closed 边界

以下属于 protocol/global error，整个 Phase 7 阻塞：

- JDJ policy drift；
- Candidate manifest drift；
- JDJ validation protocol drift；
- Phase 7 protocol shape/value drift；
- current active60 与 frozen products 不一致；
- current taxonomy 与 frozen sector groups 不一致；
- retrospective/OOS 边界被放宽。

以下允许降级为单品种 `unavailable` 并继续形成完整 180-cell matrix：

- MarketData source unavailable；
- rank1 segment identity unavailable/inconsistent；
- 该品种必要 Historical source 无法合法建立。

## 15. CLI

不新增第二套 CLI 树。继续复用：

```bash
guiyi research candidate-robustness \
  --protocol jdj_active60_robustness_v1
```

现有 `multi_candidate_robustness_v1` 保持原样。

Phase 7 CLI 不提供：

```text
--since
--through
--symbols
--threshold
--rank
--score
```

实验边界全部来自 exact protocol，避免运行时改变研究定义。

## 16. 明确不做

Phase 7 不做：

- 修改三个 JDJ Candidate 公式或参数；
- parameter sweep / Candidate variant；
- active60 rolling-validation engine；
- SuBing / N / Main Force Mirror 的统一比较；
- Candidate relationship matrix；
- robustness score / rank / winner；
- KEEP / DROP / PROMOTE；
- prospective OOS consumption；
- Walk-forward / Shadow promotion；
- Backtest / fill / slippage / fee / position / capital / PnL；
- Web / API / Alert / PushPlus / Execution Review；
- DB / Redis / Canonical write；
- release / tag / Runtime switch；
- 订单路径。

`auto_order=false` 始终成立。

## 17. 实现文件规模约束

实现应优先控制为以下最小新增面：

```text
data/research_protocols/jdj_active60_robustness_v1.json
services/quant-api/app/market_data/jdj_robustness.py
services/quant-api/app/market_data/jdj_robustness_service.py
services/quant-api/tests/test_jdj_robustness.py
services/quant-api/tests/data_foundation/test_jdj_robustness_service.py
```

允许对以下既有文件做小范围加法式修改：

```text
jdj_research.py / jdj_research_service.py
composition.py
research_parser.py
research_commands.py
test_research_cli.py
TESTING.md
PROJECT_SOURCE.md / docs/ARCHITECTURE.md / STATUS.md（仅在实现事实成立后）
```

如果实现需要额外拆分文件，只能因单一职责和测试边界确有必要，不得借机建立通用研究平台。

## 18. 必须锁死的测试

至少覆盖：

1. **JDJ parity**：普通 JDJ research 在共享 seam 重构前后 exact equal；
2. **OOS contamination**：任何 Phase 7 source request 越过 `2026-08-20` 都失败；
3. **180-cell completeness**：三个 Candidate × frozen active60 全部出现；
4. **no-event ≠ unavailable**：合法 source + 0 event 仍为 available；
5. **no-sample ≠ zero**：无 horizon sample 时 rate/median 为 null；
6. **single-load**：同 symbol 的 full retrospective 只调用一次 shared loader，三个 reducer 共用；
7. **yearly no-reload**：年度统计不额外访问行情；
8. **symbol-balanced sector**：复制某 symbol 的 event 数不能给它增加 sector 权重；
9. **old robustness immutable**：现有 `multi_candidate_robustness_v1` protocol/report/evidence contract 不被修改；
10. **no forbidden fields**：report 不出现 score/rank/winner/decision/PnL/order 等字段。

## 19. 验收标准

只有以下全部满足，Phase 7 才可声明“技术完成”：

- exact `jdj_active60_robustness_v1` protocol 已实现并 fail-closed；
- 三个 frozen JDJ Candidate / policy / formula 零变化；
- retrospective 精确为 `2023-01-01..2026-08-20`；
- embargo/prospective 数据零消费；
- frozen active60 / taxonomy identity 无漂移；
- 同 symbol 一次 shared-loader 调用读取 1m+5m，三个 reducer 共享 context；
- existing JDJ research parity 通过；
- exact 180 cells 完整；
- single-symbol、yearly、sector 三层轻量 facts 可复算；
- sector 为 symbol-balanced；
- 无 active60 pooled performance；
- 无 score/rank/winner/KEEP/DROP/PROMOTE；
- 无 Web/API/DB/Redis/Canonical/Alert/Runtime/订单副作用；
- 旧 `multi_candidate_robustness_v1` 回归通过；
- 真实 read-only evidence 成功生成并能重复得到相同 schema/identity。

## 20. 允许的结论

Phase 7 完成后最多允许声明：

> 三个冻结 JDJ Candidate 已在统一 active60 retrospective protocol 下形成跨品种、跨年份和板块维度的可复算历史研究事实。

可以描述：

- 哪些品种有/无事件；
- 不同 horizon 的历史正向 outcome 比例和中位数；
- 某 Candidate 在不同年份是否明显变化；
- 某些板块的 symbol-level 历史中位数方向是否更一致。

禁止声明：

- 策略有效或盈利；
- “胜率”或未来盈利概率；
- 最佳策略/最佳板块；
- 应该交易某品种；
- Candidate 应晋升；
- Alert/Runtime/trading ready。

## 21. Phase 8 边界

Phase 7 不做候选之间的信息重叠分析。只有 Phase 7 形成 frozen evidence 后，Phase 8 才可单独设计：

```text
SuBing
N Structure
JDJ Trend Follow
JDJ Trend Reentry 6
JDJ Key-Level Breakout
```

之间的 relationship / overlap / complementarity research，并继续保留人工 Gate，不自动排名或晋升。
