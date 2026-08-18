# Three-Indicator Research Architecture — 总设计

> 状态：Design Candidate / Implementation Not Started
> 日期：2026-08-18
> 任务车道：Lane 3 / Sol / High Reasoning
> 事实冻结基线：`develop@fe62af954a867020809f55bfce438f0766593423`
> 设计 Review：必须由新的独立 Review 会话完成
> 本文性质：路线与合同设计，不授权任何后续阶段自动执行

## 1. Purpose

本文为三个研究方向建立一个共同但不过度统一的架构：

1. `N Structure V1`：来自《期货技术教程讲义【L修订打印版】》第四章的因果结构观察；
2. SuBing 完整化：在冻结 `subing_entry_signal_v1` 的前提下补充上下文、突破、持有和退出警示观察；
3. `intraday_1m_v1`：将《股票日内交易入门》中的有限日内 playbook 明确适配为国内期货研究模式。

长期方向仍是：

```text
可信行情
→ 可复算研究观察
→ 人工判断
→ 研究证据
→ OOS / Walk-forward / Shadow
→ 人工决定是否形成或晋升 candidate
```

本文不把三条研究路线改造成一个通用策略平台，也不改变当前正式 Signal、Alert 或 Execution Review。

## 2. Hard Boundaries

本设计明确不做：

- 修改、重新解释或静默扩展 `subing_entry_signal_v1`；
- 创建 `subing_entry_signal_v2`；
- 为 N Structure 创建第三条 Alert Rule；
- 建设通用 Study Framework、无限指标组合框架或大型持久化 FSM；
- 把 NBand、ConsolidationRange、KeyLevelZone 合并成同一个业务“区间”；
- 让 Web 计算 Factor、N Structure、same-boundary resolver 或 composition；
- 恢复 backtest API、Web、worker、queue、CLI 或旧 Strategy/Signal/Review 合同；
- 新增订单、账户、持仓、风控或自动交易能力；
- 修改 PostgreSQL、Canonical、RQData、Scope、WeCom、Runtime、main、tag 或 release；
- 借本任务重写现有 EMA/MACD Indicator Kernel 的 numeric API。

`auto_order=false` 对全部研究观察和未来 Runtime 始终成立。

总设计文档只定义路线，不授权阶段自动串行执行。第 19 节中的每一阶段都是新的独立任务、独立 Codex 会话和独立 Gate。

## 3. Source Provenance

### 3.1 Provenance classes

本文使用四种来源类别，避免与架构方案 A/B/C 混淆：

| Class | 含义 | 可否直接成为 executable contract |
|---|---|---|
| `SOURCE_HEURISTIC` | 来源材料中的术语、经验规则、图示或交易叙述 | 否；必须先完成可执行定义和研究验证 |
| `EXECUTABLE_V1` | 当前代码、测试、Calibration、Alert 和消费者共同冻结的 v1 行为 | 是；只能按现状引用，不得在本文中改写 |
| `FUTURE_OBSERVATION` | 未来只读研究观察或上下文 | 否；不得自动影响正式 Signal |
| `FUTURE_CANDIDATE` | 经独立证据后才可能提出的 candidate | 否；仍需独立研究和人工批准 |

当来源与当前 executable 不一致时，必须同时保留两行事实，不得用 `SOURCE_HEURISTIC` 覆盖 `EXECUTABLE_V1`。

### 3.2 Source registry

所有 PDF 都是任务期间提供的只读外部材料，不进入 Git。

| source_id | title | source_scope | repository_tracked | 用途 |
|---|---|---|---|---|
| `N_STRUCTURE_TUTORIAL_L` | 《期货技术教程讲义【L修订打印版】》 | 第四章，重点 PDF pp.20–33 | false | N、NBand、Strength、Structure、Terminal Pivot、Fractalization |
| `INTRADAY_BOOK_2023` | 《股票日内交易入门》 | 第六章；双页扫描 PDF 的相关内容约 pp.48–69 | false | Key Level、Consolidation、VWAP、MA Trend、ABC |
| `SUBING_MULTI_TIMEFRAME` | 《不同周期的交易策略》 | 全文 | false | 日线方向、5m/15m 共振、五项三项 heuristic |
| `SUBING_SYSTEM` | 《交易系统》 | pp.1–3 | false | 进场、突破三 Bar 确认、持有、退出 |
| `SUBING_PHILOSOPHY` | 《交易理念》 | pp.2–3 | false | EMA21、起涨点、回踩与再突破 |
| `SUBING_PRINCIPLES` | 《原则》 | pp.1–3 | false | 3–5 Bar 时间止损、仓位规则冲突 |
| `SUBING_EXECUTION` | 《执行力训练》 | pp.1–2 | false | 回踩、有效突破、时间延续 |
| `SUBING_REVIEW` | 《交易日志与复盘》 | p.4 | false | 三根 5m Bar 后未回区间的有效突破 |
| `SUBING_WATCHLIST` | 《盯盘需要关注的点》 | 全文 | false | 日线方向、共振、Volume/OI、退出观察 |
| `SUBING_ENTRY_EXIT_MANTRA` | 《交易开平仓口诀》 | 全文 | false | MACD 零轴、Volume、共振、前 K 高低点 |
| `SUBING_CASES` | 《经典开仓案例》 | pp.1–7 | false | 图示案例与标注，不作为唯一机器规则 |
| `SUBING_CAPITAL` | 《资金管理》 | 全文 | false | 资金规则，仅用于冲突记录和人工复核 |
| `SUBING_TIMEFRAME` | 《周期选择》 | 全文 | false | 周期选择叙述，不改变 v1 频率合同 |

其余苏冰材料可作为背景佐证，但没有进入本设计的 executable 定义。未来引用新来源时，必须补充稳定 `source_id`、title、页码或章节、用途和 `repository_tracked=false`，不得记录本机绝对路径。

### 3.3 Provenance matrix

| Subject | Source fact | Current executable fact | Future treatment |
|---|---|---|---|
| 入场总逻辑 | 均线/MACD/BOLL/Volume/前区间突破五项满足三项 | 严格 all-of，不含 BOLL | 同时保留；不得把 heuristic 写成 v1 |
| EMA | EMA21 与多周期方向是核心观察 | primary/companion 均要求价格与 EMA21、slope 条件 | EntryAssessment 原样复用 v1；其他 Facet 可观察 EMA21 |
| MACD | 强调零轴附近、交叉和柱体延续 | 使用冻结 MACD cross policy；zero-distance 非 hard gate | 零轴/柱体作为 observation，未经研究不得晋升 |
| Volume | 突破时强调放量，常见表述为三倍量 | primary 当前量/前量比例要求 `>= 3` | EntryAssessment 保持 v1；BreakoutAssessment 可解释来源 |
| 5m/15m | 强调多周期共振 | companion 与 same-boundary resolver 已冻结 | 不建立第二套 resolver |
| Breakout | 突破后连续三 Bar 不回原区间才视为有效 | 不属于当前 v1 executable gate | `FUTURE_OBSERVATION` |
| Time stop | 入场后 3–5 Bar 缺乏延续应及时退出 | 当前 Signal 无入场后状态 | 需要显式 assessment anchor；边界 `research_pending` |
| N | 价格波动的最小结构单元 | 当前不存在 N executable | `N Structure V1` observation only |
| VWAP | 日内成交量加权平均价格 | 当前没有 Intraday VWAP study | `trading_day_vwap_v1` observation only |

## 4. Current Repository Facts

以下内容是 `EXECUTABLE_V1`，不是本文提出的新设计。

### 4.1 SuBing Factor

当前 Factor 位于 quant-api 的 `market_data/subing_research.py`，以 current-rank1-segment-local 的 Historical/completed Live bars 计算。Symbol 位于外层 SuBing read identity；Factor snapshot 自身包含：

- identity：frequency、actual contract、segment start、bar_end、trading_day、source；
- EMA21：close、EMA21、price side；
- EMA21 slope：5/10 窗口 raw 与 bps；
- MACD：DIF、DEA、Histogram、cross、cross level、zero-distance absolute/bps；
- Volume：当前量、前一 Bar 量、ratio；
- 状态：`READY` 或 `INSUFFICIENT_DATA`。

它不允许 pre-rank1 warm-up、跨合约继承 EMA/MACD 状态或读取 segment end 之后的 Bar。

当前 Indicator Kernel 的 EMA/MACD 计算存在 float numeric path；SuBing application DTO 使用稳定转换形成 Decimal 观测值。本文不要求把整个 Kernel 改为 Decimal。

### 4.2 Accepted Calibration

当前 accepted artifact：

```text
calibration_id = subing_intraday_v1
5m slope_5_threshold_bps  = 0.688190651160584793944957992
15m slope_5_threshold_bps = 1.329531078893356968545882036
```

Calibration 是 slope-only。Zero-Band 研究没有进入 accepted artifact，也不是 executable condition。相同 calibration id 的内容漂移必须 fail-closed。

### 4.3 Frozen MACD policy

当前 formal equivalence tuple：

```text
(seed_policy, histogram_scale, parameter_set, confirmed_only)
= ("sma_window", 2, "fast12_slow26_signal9", true)
```

它只为当前 SuBing Signal 消费者建立了受限等价，不代表 generic MACD 已获得策略、Alert 或 live capability。

### 4.4 Frozen Signal all-of

当前 v1 只支持 5m/15m。Long 的 executable conditions 为：

- primary close above EMA21；
- primary slope-5 大于对应 accepted threshold；
- primary slope-10 大于 0；
- primary MACD golden cross；
- primary Volume ratio `>= 3`；
- companion close above EMA21；
- companion slope-5 大于对应 accepted threshold；
- companion slope-10 大于 0；
- MACD formal policy equivalence 成立。

Short 完全镜像。Companion MACD 与 Volume 当前不是 executable condition。Zero-distance 仅描述，不影响 MATCHED/NOT_MATCHED。

1d 当前保持 `RESEARCH_PENDING`，不得从文档扩展成正式 Signal 频率。

### 4.5 Primary and resolved semantics

现有 read model 明确保留：

```text
primary_signal
resolved_signal
```

二者不得被未来 `SuBingEntryAssessment` 压缩成一个新 `entry_status`。

同一 READY boundary 的 resolver 精确语义：

| 5m | 15m | 方向关系 | resolved_signal |
|---|---|---|---|
| MATCHED | MATCHED | 同方向 | 15m wins；`lower_tf_confirmation=true` |
| 非 MATCHED | MATCHED | 不适用 | 15m resolved |
| MATCHED | 非 MATCHED | 不适用 | 5m resolved |
| MATCHED | MATCHED | 反方向 | conflict；`NOT_MATCHED/NONE` |

Companion 不得位于 primary 未来。Contract、segment identity 或同边界条件不满足时，必须按现有语义 fail-closed。

### 4.6 Alert consumer

Alert Registry 当前只有两条规则，其中 `subing_entry_signal_v1` 是 formal signal：

- series kind：`actual_dominant`；
- frequencies：5m/15m；
- incoming Bar 与 read snapshot 必须 `bar_end + trading_day` 相同；
- 5m 在同一 15m boundary 按共享 TradingSession bucket 延后；
- final Session Bar 只在共享 arrival grace 内可见；
- Event 先提交，再尝试一次 WeCom；发送失败不 retry；
- repair、replay、backfill、migration、EOD recalculation 不补评、不补发。

当前生产 Scope 精确为 `jm`，SuBing Natural Canary 仍 pending；这是状态事实，不是本文对 Scope、Runtime 或 Canary 的操作授权。

本文不得修改 Registry、Scope 或 Alert Runtime。

### 4.7 Execution Review consumer

Execution Review 的唯一 eligible source 是不可变的 `subing_entry_signal_v1` AlertEvent：

- 只接受 5m/15m；
- result codes 必须精确为单一 `buy` 或 `sell`；
- direction conflict、多个结果或非法状态必须拒绝；
- Decision、Episode、Execution、Review 是独立四表 Application Domain；
- 不接订单、账户或持仓系统。

未来 SuBing Facets 或 N context 不得改变 AlertEvent eligibility，也不得被 Execution Review 当作新的交易来源。

### 4.8 Current Web

当前 Primary overlay 是 `none | subing | htdy`，EMA10/EMA60 为共享可选 overlay。SuBing 强制 EMA21，并强制使用 current actual contract，但不会覆盖用户保存的 series preference。

Web 现有职责是请求、identity 校验、有限 refresh 和渲染；zero-distance 已明确展示为 observation。本文延续 Web render-only 原则。

### 4.9 Existing architecture drift

`docs/INDICATOR_KERNEL.md` 声明 quant-core 是指标业务语义唯一权威，但部分 SuBing pure Factor/Signal logic 仍位于 quant-api 的 `market_data/subing_research.py`。

这是已存在的 architecture drift。本文只定义后续收口方向：

- pure calculation 归 quant-core；
- MarketDataService、rank1、TradingSession、Historical/completed Live 编排归 quant-api；
- 迁移必须有 v1 characterization 保护；
- 本任务不执行迁移。

## 5. Source Conflict and Uncertainty Matrix

| Topic | Evidence | Classification | Required handling |
|---|---|---|---|
| 五项三项 vs strict all-of | 苏冰 heuristic 与当前代码不同 | `SOURCE_HEURISTIC` vs `EXECUTABLE_V1` | 两者并列；v1 不变 |
| MACD 零轴附近 | 来源强调 | `FUTURE_OBSERVATION` | zero-distance 不得成为 v1 hard gate |
| MACD 柱体延续 | 来源强调持有/退出 | `FUTURE_OBSERVATION` | 先定义 observation，再研究 |
| BOLL | 来源多次出现，v1 不含 | `FUTURE_OBSERVATION` | 第一阶段不加入 EntryAssessment executable |
| Breakout 三 Bar | 突破后连续三 Bar 不回区间 | semantics known / boundary pending | 与时间止损分开；Bar 计数边界需研究 |
| Post-entry 3–5 Bar | 入场后缺乏延续 | semantics known / classifier pending | 需要 explicit assessment anchor |
| 仓位比例 | 资料出现 30%、50%、90% 等不同叙述 | `source_conflict` + `manual_review` | 不计算、不建议、不自动化 |
| 日线方向 | 来源强调方向但没有唯一公式 | `research_pending` | 不自行选 EMA、坡度或结构公式 |
| 起涨点/起跌点 | 语义存在，算法定位不唯一 | `research_pending` | 由未来 human-labelled examples 冻结 |
| Strong/Medium/Weak | 来源给出业务模式 | semantics known | machine classifier 单独 `research_pending` |
| N pivot/fractal | 来源以图示和结构语义为主 | `research_pending` | 先形成标注样本和确定性规则 |
| 股票 key level | 来源是美股语境 | adaptation hypothesis | 只使用显式国内期货来源，不声称等价 |
| ABC opening | 来源是股票开盘 | adaptation hypothesis | 使用 trading-day opening policy，保持 observation |

`BREAKOUT_CONFIRMATION` 与 `POST_ENTRY_TIME_STOP` 不是相互冲突的“3 vs 3–5”规则：前者判断突破有效性，后者判断入场后的时间延续。

## 6. Architecture Alternatives

### 6.1 Option A — quant-api extension

继续在 `market_data/` 内增加 N、SuBing facets 和 Intraday 逻辑。

优点：

- 与当前 SuBing 文件位置一致；
- 初始移动较少。

缺点：

- 扩大 pure semantics 与 `INDICATOR_KERNEL.md` 的偏移；
- Historical/Live orchestration 与计算语义继续混合；
- 后续 CLI、API、Web 容易复制规则。

结论：不推荐。

### 6.2 Option B — generic Study/FSM framework

创建统一 Study registry、通用 Range、通用状态机和自由组合图。

优点：

- 表面复用率高；
- 新增研究类型看似方便。

缺点：

- NBand、ConsolidationRange、KeyLevelZone 的形成原因和生命周期不同；
- SuBing 第一版不需要持久化 FSM；
- 无限组合会把计算与 compatibility matrix 推向 Web；
- 当前三条路线没有足够证据支持稳定的通用抽象。

结论：明确否决。

### 6.3 Option C — shared causal primitives, typed studies

quant-core 提供少量共享因果原语，以及独立的 N、SuBing、Intraday typed study module；quant-api 负责唯一市场身份与时间编排；Web 只消费 read model。

优点：

- pure semantics 获得单一权威；
- 复用因果时间和 PriceZone 几何，但不统一业务语义；
- 可以用 characterization tests 保持 v1；
- 同一 interface 同时成为调用和测试 seam；
- 不需要通用框架或持久化状态机。

结论：推荐方案。

## 7. Module Ownership

### 7.1 quant-core

目标 ownership：

```text
packages/quant-core/guiyi_quant/
├── indicators/              existing Indicator Kernel
├── structures/              causal primitives + N Structure
└── studies/
    ├── subing/              pure snapshot facets
    └── intraday_1m/         four typed playbooks
```

这些是概念 ownership，不是本任务授权的文件迁移。

quant-core 负责：

- zero-I/O pure calculation；
- causal/time invariants；
- typed domain results；
- deterministic reason/status；
- 价格、价位、Zone boundary、threshold、VWAP 的 Decimal DTO；
- 保留现有 EMA/MACD Kernel interface，不在本路线中全面 Decimal 化。

### 7.2 quant-api

quant-api 负责：

- `MarketDataService` 唯一历史入口；
- current rank1 identity 和 segment 上下界；
- TradingSession、trading_day、night session；
- Canonical Historical 与 completed Live 的有界合并；
- same-snapshot orchestration；
- schema validation、read endpoint 和 fail-closed mapping；
- 不把纯结构识别复制进路由或 adapter。

### 7.3 Web

Web 负责：

- Primary Study 与 Context Layer 的有限选择；
- 对 quant-api typed read model 做展示级 normalization；
- 渲染 Zone、Pivot、State、Assessment 和 unavailable reason；
- 不执行 structure detection、Signal resolution 或跨请求 composition。

## 8. Shared Causal Structure Core

### 8.1 Input snapshot

共享结构输入最少包含：

```text
StudyIdentity
  symbol
  actual_contract
  frequency
  segment_start_trading_day
  segment_end_trading_day

StructureInputSnapshot
  identity
  as_of_bar_end
  trading_day
  completed_bars[]
  resolved_sessions[]
```

硬约束：

- bars 全部完成且按 `bar_end` 严格升序；
- 不得重复、跨 contract、跨 rank1 segment 或超过 `as_of_bar_end`；
- aggregation 不得跨 TradingSession；
- 输入不足、identity 不完整或 session 不可解析时返回 unavailable，不降级为较短窗口或其他频率。

### 8.2 Neutral four-node representation

N 的四个价格节点使用中性内部名称：

```text
origin
pivot_1
pivot_2
completion
```

每个节点至少包含：

```text
price: Decimal
anchor_at: bar_end
confirmed_at: bar_end | null
pivot_kind: HIGH | LOW
status: ACTIVE | CONFIRMED
```

不得声称原 PDF 把四个价格点命名为 N1/N2/N3/N4。

### 8.3 Two time semantics

`anchor_at` 是波动节点实际所在 Bar。`confirmed_at` 是系统在收到后续 completed bars 后首次能够确认节点的时点。

因此：

- 一个 Bar 已收线，不等于该 Bar 上的结构节点已经确认；
- 新确认节点可以指向较早的 `anchor_at`；
- 过去的 `as_of` snapshot 不得因未来 Bar 回写；
- 所有正式展示必须同时显示或可追溯 `anchor_at` 与 `confirmed_at`。

### 8.4 Confirmed history and active tail

输出分为：

```text
confirmed_history[]
active_structure | null
```

confirmed history：

- prefix invariant；
- append-only；
- 已确认节点、N、destruction、reversal 和 structure change 不可修改或删除；
- 相同 `as_of` 重算结果必须一致。

active/provisional tail：

- 只存在于确认历史之后；
- 可随新 completed Bar 延伸 completion；
- 可在明确 active structure 范围内替换尚未确认的 pivot；
- 不得改写 confirmed history；
- mutation 范围必须随 snapshot 显式输出，便于测试和 Web 标示。

这一区分取代笼统的“全部输出 prefix invariant”。Prefix invariance 只适用于 confirmed history；active tail 允许有界 mutation。

### 8.5 PriceZone seam

共享底层几何 DTO：

```text
PriceZone
  lower: Decimal
  upper: Decimal
  formed_from
  anchor_at
  confirmed_at
```

业务类型保持独立：

| Type | 业务来源 | 形成原因 | 主要用途 |
|---|---|---|---|
| `NBand` | N1-N2 抵抗阶段 | N 内部结构 | 判断后续突破/回踩与强弱 |
| `ConsolidationRange` | 盘整/矩形结构 | 多 Bar 横向收敛 | 日内区间突破 |
| `KeyLevelZone` | 日内关键价位附近 | 明确 reference level | Key-level breakout/retest |

三类结果不得互相 cast，不共享 formation rules，也不得只凭相同上下边界判断为同一对象。

## 9. N Structure V1

### 9.1 First-version scope

第一阶段只支持 5m/15m，优先服务 SuBing 上下文和独立结构观察。1m 由独立 Intraday 模式处理；其他正式频率需要后续独立研究。

`N Structure V1` 是 observation/research indicator：

- 不注册 Alert；
- 不产生 buy/sell；
- 不进入 Execution Review；
- 不声明 backtest/live/alert capability；
- 不含 KDJ fallback、BD 模组或复杂外围形态学。

### 9.2 Source terminology

必须保留：

- N1 阶段；
- N1-N2 阶段；
- N2 阶段；
- 上攻 N / 下杀 N；
- 两低一高 / 两高一低；
- N1 起点 / N2 起点；
- N 字破坏；
- N 字区间带；
- strong / medium / weak；
- 多头 / 空头 / 盘整结构；
- 末尾低点 / 末尾高点；
- 阶梯结构；
- 分型。

上攻 N 的阶段映射：

```text
origin(low) → pivot_1(high)      = N1 stage
pivot_1(high) → pivot_2(low)     = N1-N2 resistance stage
pivot_2(low) → completion(high)  = N2 stage
```

下杀 N 镜像。N1/N2 在这里是阶段及来源中的关键起点语义，不是给四个价格节点编号。

### 9.3 Domain results

V1 至少输出：

- `Wave`：相邻 pivot 之间的方向性波动；
- `NPattern`：上攻 N 或下杀 N，以及四中性节点；
- `NDestruction`：N2 start 被破坏；
- `NDirectionalReversal`：N1 start 被破坏；
- `NBand`：N1-N2 resistance stage 的支撑/压力带；
- `Strength`：strong/medium/weak 的 source semantic 与 classifier status；
- `StructureState`：long/short/consolidation；
- `TerminalPivot`：多头末尾低点或空头末尾高点；
- `StructureChange`：terminal pivot 被破坏；
- `active_structure`：尚未确认的尾部 N/leg。

### 9.4 Three destruction levels

三个层级不能合并：

#### `N2_START_BROKEN`

- 当前 N 被破坏；
- 当前 N 可进入 fractalization/归并；
- 不等于方向反转；
- 不得生成 `StructureChange`。

#### `N1_START_BROKEN`

- 确认 N-level directional reversal；
- 与 N2 start destruction 是不同事件；
- 仍不等于更高层多 N Structure 必然结束。

#### `TERMINAL_PIVOT_BROKEN`

- 多头结构看末尾低点；
- 空头结构看末尾高点；
- 破坏后形成 multi-N `StructureChange`；
- 这是结构结束语义，不得由单一局部 N2 destruction 代替。

### 9.5 Strength semantics

来源语义已知：

- strong：该回不回；
- medium：发生回踩，但 NBand 不破；
- weak：出现 NBand 破坏风险或不能维持预期抵抗。

但来源没有给出唯一的 numeric threshold、边界相等规则、最少 Bar 数和完整 gap/session 处理。因此：

```text
source_semantics = KNOWN
machine_classifier = RESEARCH_PENDING
```

未通过 N semantic research Gate 前，系统可以显示原始 geometry 与待评状态，但不得伪造 strong/medium/weak classifier。

### 9.6 Structure state

来源结构只允许：

```text
LONG
SHORT
CONSOLIDATION
```

一个方向结构至少由两个 N 组成。阶梯结构描述同方向 N 的推进关系；不能因为单个 active N 就提前确认完整方向结构。

## 10. SuBing Completion by Snapshot Facets

### 10.1 Why no persistent FSM

第一版目标是补全研究可见性，不是维护虚拟仓位生命周期。持续状态会引入 replay、恢复、跨进程一致性和“当前持仓”误解，因此 V1 使用 stateless/snapshot facets。

公共结果：

```text
SuBingContext
SuBingEntryAssessment
SuBingBreakoutAssessment
SuBingHoldAssessment
SuBingExitWarning
```

所有 Facet 使用统一评估状态：

```text
OBSERVED
NOT_OBSERVED
UNAVAILABLE
SOURCE_CONFLICT
RESEARCH_PENDING
MANUAL_REVIEW
```

### 10.2 SuBingContext

Context 汇总但不裁决：

- 日线方向：未冻结公式前为 `RESEARCH_PENDING`；
- 5m/15m Factor 与当前 primary/resolved 结果；
- EMA21 位置和 slope；
- MACD cross、zero-distance、histogram continuation observation；
- Volume ratio；
- reference range 与 breakout 状态；
- 可选 N context；
- exact snapshot identity 与 provenance。

### 10.3 SuBingEntryAssessment

EntryAssessment 必须包含：

```text
primary_signal: existing v1 result
resolved_signal: existing v1 result
calibration provenance
formal MACD policy provenance
```

它不得：

- 重新实现 all-of；
- 加入 BOLL、zero-distance、N alignment 或 breakout confirmation hard gate；
- 把 primary/resolved 压成一个状态；
- 改变 Alert 或 Execution Review 消费字段。

### 10.4 SuBingBreakoutAssessment

Breakout facet 可观察：

- 前区间/明确 reference zone；
- breakout direction 与 breakout Bar；
- Volume observation；
- `BREAKOUT_CONFIRMATION`；
- 回踩是否重新进入原区间；
- 回踩不破起涨点/起跌点；
- 再突破。

Reference zone 必须携带明确 `zone_kind`。NBand 与 ConsolidationRange 即使几何重叠，也保持原业务身份。

来源已知“突破后连续三 Bar 不回原区间”用于有效性判断；以下 machine boundaries 在 Research Gate 冻结前保持 `RESEARCH_PENDING`：

- breakout Bar 是否计入三 Bar；
- equality 视为回区间还是守住边界；
- session gap 与涨跌停缺 Bar 的处理；
- 起涨点/起跌点的确定性定位。

### 10.5 AssessmentAnchor

Hold/Exit 是“入场后”语义，必须显式接收不可变 research anchor：

```text
AssessmentAnchor
  direction
  entry_bar_end
  entry_price: Decimal | null
  origin_level: Decimal | null
  reference_zone_id | null
  source_event_id | null
```

Anchor 只用于研究评估：

- 不创建仓位；
- 不推断订单或真实成交；
- 不默认“最近一次 Signal 就是当前入场”；
- 缺少 anchor 时，post-entry Facet 返回 `MANUAL_REVIEW` 或 `UNAVAILABLE`。

未来可以由人工输入或只读引用既有 Execution Review 事实，但该集成必须是独立任务。

### 10.6 SuBingHoldAssessment

Hold facet 覆盖：

- MACD 柱体是否延续；
- EMA21/相关均线是否继续支撑或压制；
- breakout 是否仍有效；
- 上一 K 高低点是否继续守住；
- N structure 是否保持；
- 入场后是否产生有利延续。

这些字段是独立 observations，不合成为新的 executable hold signal。

### 10.7 SuBingExitWarning

Exit warning 覆盖：

- previous-Bar high/low break；
- structure destruction/change；
- MA invalidation；
- MACD opposite cross；
- histogram non-continuation；
- `POST_ENTRY_TIME_STOP`：入场后 3–5 Bar 缺乏延续。

3–5 Bar 的具体 horizon、收益/距离阈值与 equality 未冻结前为 `RESEARCH_PENDING`，不得由系统自动平仓或通知。

## 11. SuBing + N Context Composition

### 11.1 Context only

N 只作为 SuBing context，不进入当前 v1 all-of。组合不得：

- 修改 `primary_signal`；
- 修改 `resolved_signal`；
- 创建 v2；
- 改变 Alert Event；
- 改变 Execution Review eligibility。

### 11.2 Alignment status

```text
N_ALIGNED
N_CONFLICT
N_NEUTRAL
N_UNAVAILABLE
```

V1 只使用已确认 `StructureState` 与 resolved SuBing direction 做关系判断：

| SuBing resolved direction | N StructureState | Alignment |
|---|---|---|
| LONG | LONG | `N_ALIGNED` |
| SHORT | SHORT | `N_ALIGNED` |
| LONG | SHORT | `N_CONFLICT` |
| SHORT | LONG | `N_CONFLICT` |
| LONG/SHORT | CONSOLIDATION | `N_NEUTRAL` |
| 无 resolved direction | 任意 | `N_UNAVAILABLE` |
| 任意 | 计算失败/identity mismatch | `N_UNAVAILABLE` |

NBand、TerminalPivot、StructureChange 作为 context fields 展示，不额外改变 alignment 分类，避免隐藏形成新的 Signal 逻辑。

`N_NEUTRAL` 只能表示 N 已成功计算并确认盘整/无方向。缺数据、未批准 classifier、stale 或 identity 不一致绝不能映射为 NEUTRAL。

### 11.3 Same-snapshot contract

Standalone N 可以有独立 read model；SuBing + N 必须由 quant-api 在一个 resolved snapshot 内完成，不允许 Web 分别请求再拼。

Composition identity 至少精确匹配：

```text
symbol
actual_contract
trading_day
frequency
bar_end
segment_start_trading_day
```

规则：

- MATCHED resolved signal 存在时，`composition_frequency` 使用该 resolved signal 的 frequency；
- N snapshot 必须重算/截断到 resolved signal 的同一 `bar_end`；
- 任一 identity 字段不一致即 `N_UNAVAILABLE`；
- resolver 不得选择更旧 N snapshot、“最近可用”值或浏览器缓存值；
- 无 resolved direction 时，可以返回 standalone N context，但 alignment 必须 `N_UNAVAILABLE`，reason 为 `SUBING_DIRECTION_UNAVAILABLE`。

稳定 unavailable reasons 至少覆盖：

```text
SUBING_DIRECTION_UNAVAILABLE
N_STRUCTURE_INSUFFICIENT_DATA
N_STRUCTURE_RESEARCH_PENDING
COMPOSITION_IDENTITY_MISMATCH
COMPOSITION_BOUNDARY_MISMATCH
TRADING_SESSION_UNAVAILABLE
```

## 12. Intraday 1m V1

### 12.1 Product identity

`intraday_1m_v1` 是独立 Primary Study，只接受 1m completed bars。它不是 SuBing 的低周期变体，也不产生 Alert。

第一版只有四组 typed playbook：

```text
key_level / consolidation_breakout
vwap
ma_trend
abc
```

不实现书中全部策略。

### 12.2 Domestic futures adaptation

全部 playbook 必须显式使用：

- `TradingSession`；
- `trading_day`；
- night session 与其归属 trading_day；
- previous complete trading day；
- current rank1 contract segment；
- completed 1m bars；
- no cross-roll state。

明确排除：

- premarket；
- Level 2；
- stock float；
- 股票池、scanner、相对成交量排名等股票特有筛选；
- 对这些概念做未经证据的“期货等价替换”。

### 12.3 KeyLevelZone and ConsolidationRange

Key Level 是区域，不是精确单价。V1 的自动候选来源限定为：

- previous complete trading day high；
- previous complete trading day low；
- previous complete trading day close；
- current trading day open。

每个 reference level 通过 versioned width policy 形成 `KeyLevelZone`。Width policy 在研究冻结前保持 `RESEARCH_PENDING`；整数心理价位、新闻位和人工画线不进入第一版自动 resolver。

`ConsolidationRange` 是多根 1m Bar 的矩形盘整结果，独立记录形成窗口、上下边界和确认时点。最少 Bar、最大振幅和 Volume 约束需要 human-labelled examples 后冻结，不能借用 NBand classifier。

### 12.4 trading_day_vwap_v1

第一版 VWAP policy 精确命名：

```text
trading_day_vwap_v1
```

计算语义：

```text
cumulative(turnover) / cumulative(volume)
```

若底层可靠 turnover 不可用，替代价格公式必须建立新的 policy id；不得在同一 id 下静默改用 typical price。

Reset policy：

- `trading_day` 变化时 reset；
- 午休、上午/下午或其他同 trading_day Session segment 切换不 reset；
- 夜盘属于哪个 trading_day，由项目 TradingSession/trading_day resolver 决定；
- 从该 trading_day 的第一根有效 current-rank1 1m Bar 开始累计；
- 起点 coverage 不完整、roll identity 不一致或 volume 非法时 fail-closed。

未来如研究逐 session VWAP，必须使用新的 `session_vwap_*` policy，不能改变 `trading_day_vwap_v1`。

### 12.5 MA trend

书中 MA Trend 是独立 Intraday playbook，不等于 Web 的 EMA10/EMA60 Context Layer。其 MA family、period、cross、回踩和 Volume 条件在独立研究 Gate 冻结；不得直接复用现有 EMA overlay 名称制造 executable equivalence。

### 12.6 ABC

股票来源的 opening 语义不能原样宣称适用于期货。V1 adaptation hypothesis：

- A 使用 resolved trading_day 第一根有效 1m Bar；
- A→B 是初始方向 leg；
- B 是当前确认的局部高/低；
- B→C 是回撤；
- C 后恢复原方向才形成 observation；
- 夜盘品种的 trading-day opening 通常位于夜盘，完全由 TradingSession resolver 决定。

Pivot confirmation、最小 impulse、回撤比例和 C 与 VWAP/MA/KeyLevel 的关系均需独立研究。V1 输出 observation/provenance，不声称与美股开盘策略等价。

## 13. Web Composition Model

### 13.1 Primary Study

```text
none
subing
htdy
intraday_1m
```

Primary Study 互斥。

### 13.2 Context Layers

```text
EMA10
EMA60
N Structure
```

第一阶段采用显式 compatibility matrix：

| Primary Study | EMA10 | EMA60 | N Structure | 说明 |
|---|---:|---:|---:|---|
| none | no | no | yes | 独立 N 观察 |
| subing | yes | yes | yes | EMA21 继续由 SuBing 强制拥有 |
| htdy | yes | yes | no | 保持当前有限 shared EMA 行为 |
| intraday_1m | no | no | no | VWAP/MA/playbook overlay 由自身管理 |

这不是通用组合 registry。未来新增组合必须修改显式 matrix、read model 合同与测试。

### 13.3 Render-only rules

Web 必须：

- 同时展示 source classification 与计算状态；
- 区分 `N_NEUTRAL` 与 `N_UNAVAILABLE`；
- active/provisional N 使用不同视觉样式；
- confirmed pivot 可显示 `anchor_at` 与 `confirmed_at`；
- Zone 按业务类型使用不同 label，不用同一个“区间”标签；
- SuBing + N 只显示 quant-api composition result。

Web 不得：

- 自行比较两次 endpoint 的 bar_end；
- 自行决定 alignment；
- 缓存旧 N 结果填补 unavailable；
- 将 Facet observation 写成交易建议。

## 14. Read Interfaces

现有 SuBing read endpoint 和 wire fields 保持兼容。未来新增只读 interface：

```text
GET /api/v1/market/research/n-structure
GET /api/v1/market/research/subing-context
GET /api/v1/market/research/intraday-1m
```

### 14.1 N Structure read model

返回：

- exact StudyIdentity；
- `as_of_bar_end`；
- confirmed history；
- active/provisional tail；
- NBand、Strength classifier status、StructureState、TerminalPivot、StructureChange；
- unavailable reason 和 provenance。

### 14.2 SuBing Context read model

返回：

- 现有 `primary_signal`；
- 现有 `resolved_signal`；
- Context/Breakout/Hold/Exit facets；
- same-snapshot N context；
- alignment status/reason；
- assessment anchor echo；
- exact composition identity。

### 14.3 Intraday read model

返回：

- trading-day/rank1 identity；
- previous complete trading-day identity；
- `trading_day_vwap_v1`；
- 各 playbook 独立 assessment；
- typed KeyLevelZone/ConsolidationRange；
- unavailable/research-pending reason；
- 不返回综合 buy/sell。

所有 interface 都是 read-only，不创建 DB 记录。

## 15. Data Flow

### 15.1 Standalone N

```text
MarketDataService
→ current rank1 segment
→ Historical + eligible completed Live
→ TradingSession-aware completed snapshot
→ quant-core Causal Core / N Structure
→ quant-api N read model
→ Web render
```

### 15.2 SuBing + N

```text
one quant-api orchestration request
├── existing SubingReadService snapshot
└── N input truncated to the resolved signal boundary
        │
        ▼
same identity validation
        │
        ├── mismatch → N_UNAVAILABLE
        └── match → quant-core context composition
                         │
                         ▼
                   one composed read model
                         │
                         ▼
                       Web
```

### 15.3 Intraday 1m

```text
MarketDataService + completed Live
→ current rank1 1m segment
→ TradingSession/trading_day resolver
→ previous complete trading day + current trading day coverage
→ quant-core intraday playbooks
→ one read model
→ Web
```

消费者不得 direct glob、读取 Parquet、选择 active Dataset 或自行判断 rank1。

## 16. Causal, Numeric and Failure Semantics

全部新正式计算遵守：

- completed input bars only；
- current-rank1-segment-aware；
- TradingSession-aware；
- no future leakage；
- no cross-roll warm-up/state；
- deterministic and reproducible；
- versioned policy；
- fail closed；
- 新 study DTO 的 price/level/zone boundary/threshold/VWAP 为 Decimal。

现有 EMA/MACD Kernel float interface 不在本架构任务中重写。Adapter 必须使用已冻结的稳定转换方式形成 Decimal domain value，不引入新的隐式 rounding policy。

Failure 不得降级为 neutral：

```text
missing bars
missing session
identity mismatch
incomplete trading-day VWAP coverage
unsupported frequency
unapproved classifier
stale snapshot
```

都必须产生 `UNAVAILABLE` 或 `RESEARCH_PENDING` 和稳定 reason。

## 17. Version and Promotion Model

建议的独立版本身份：

```text
causal_structure_core_v1
n_structure_v1
subing_context_v1
trading_day_vwap_v1
intraday_1m_v1
```

`subing_context_v1` 中的 EntryAssessment 继续引用：

```text
subing_entry_signal_v1
```

它不是新的 Signal version。

任何未来新 Signal 都必须：

```text
observation
→ candidate proposal
→ historical research
→ OOS / walk-forward / shadow
→ independent review
→ human approval
→ separate Alert/Runtime Gate if applicable
```

AI/Codex 不得自动 promotion。研究得到“候选淘汰”是有效结论，不得降低验证标准换取盈利结论。

当前仓库没有 backtest API/Web/worker/queue。第 19 节的研究阶段不得借本设计恢复这些入口；未来所需研究工具必须另立任务和合同。

## 18. Test Strategy

### 18.1 SuBing v1 characterization

必须先冻结并持续回归：

- 每个 hard condition 的独立失败；
- companion identity 与 future cutoff；
- zero-distance 不影响 Signal；
- 仅 5m、仅 15m、双同向、双反向四种 resolver；
- primary/resolved 两层 wire semantics；
- accepted Calibration exact identity；
- MACD formal tuple；
- Alert same-boundary、stale、5m deferral、final grace、one-shot；
- Execution Review 只接受合法 buy/sell Event。

### 18.2 Causal core

必须包含：

- 逐 Bar prefix replay；
- `anchor_at < confirmed_at` 的正常确认案例；
- future Bar 不得提前出现在较早 `as_of`；
- confirmed history append-only；
- active completion 延伸；
- active pivot 有界替换；
- active mutation 不改变 confirmed prefix；
- duplicate/out-of-order/cross-segment inputs fail-closed。

### 18.3 N Structure

使用 human-labelled golden examples 覆盖：

- 上攻 N / 下杀 N；
- 两低一高 / 两高一低；
- N1、N1-N2、N2 阶段；
- N2 start broken 但没有 reversal；
- N1 start broken 的 N-level reversal；
- terminal low/high broken 的 StructureChange；
- long/short/consolidation；
- NBand 与 Strength source patterns；
- 多 N 阶梯与 fractalization。

在 classifier 规则未批准前，测试应断言 `RESEARCH_PENDING`，不能用占位阈值制造 GREEN。

### 18.4 Same-snapshot composition

覆盖六个 identity 字段分别不一致、N 较旧、N 较新、无 resolved direction、N consolidation、同向和反向结构。

断言：

- mismatch 永远 `N_UNAVAILABLE`；
- Web 不参与组合；
- N context 不改变原 `primary_signal/resolved_signal`；
- standalone N 可用不代表 alignment 一定可用。

### 18.5 Intraday

覆盖：

- 夜盘归入下一 trading_day；
- 午休和日盘 segment 切换不 reset VWAP；
- trading_day 切换 reset；
- 缺失 trading-day 首段 coverage fail-closed；
- rank1 rollover 不继承 VWAP/ABC/MA state；
- previous complete trading day 不误用当前未完成日；
- NBand/ConsolidationRange/KeyLevelZone 类型不可互换；
- premarket、Level 2、float 不进入 schema 或计算。

### 18.6 Web

覆盖有限 compatibility matrix、N standalone、SuBing+N、unavailable 展示、active/confirmed 样式、frequency guard 和 no client composition。

## 19. Phased Implementation Tasks and Lanes

每一阶段只定义允许范围。阶段完成、测试通过或 Review 通过，都不授权下一阶段自动开始。

### Phase 1 — SuBing v1 characterization freeze

```text
Lane 3 / Sol / independent review
```

目标：冻结 Factor、Calibration、primary/resolved resolver、Alert 和 Execution Review golden vectors；不改变业务代码语义。

### Phase 2 — N semantic research Gate

```text
Lane 3 / Sol / Plan + human-labelled examples
```

目标：解决 pivot confirmation、NBand boundary、Strength classifier、fractalization 和 equality rules。产物必须先由人工 Review；不得用来源外推测填空。

### Phase 3 — Causal Core + N Structure V1

```text
Lane 3 / Sol / independent review
```

前提：Phase 2 规则已批准。实现 pure core、N observation 和 read model；不得创建 Alert。

### Phase 4 — SuBing Facets + N Composition

```text
Lane 3 / Sol / independent review
```

目标：实现 stateless facets、AssessmentAnchor 和 same-snapshot context。`subing_entry_signal_v1` regression 必须完全通过。

### Phase 5 — Web limited composition

```text
Lane 2 / Terra
```

前提：Phase 3/4 read model contract 冻结。只实现有限 matrix 和 render-only，不移动计算到 Web。

### Phase 6 — Intraday 1m

```text
Lane 3 / Sol / independent review
```

目标：按独立 Research Gate 实现四组 playbook 和 `trading_day_vwap_v1`；不继承 SuBing/N 的 Alert 能力。

### Phase 7 — OOS / Walk-forward / Shadow research

```text
Lane 3 / Sol / human promotion Gate
```

目标：积累独立研究证据。只有证据充分时才允许另立任务提出 candidate version；本阶段本身不 promotion。

## 20. Risks

| Risk | Consequence | Mitigation |
|---|---|---|
| 把 N2 destruction 当反转 | 提前改变方向判断 | 三层事件类型与 golden examples |
| active tail 被当 confirmed history | future leakage/repaint | 双时间字段、分区输出、prefix tests |
| Strong/Medium/Weak 被随意量化 | 伪造来源精度 | semantics known / classifier pending |
| SuBing 迁移造成 v1 drift | 正式消费者变化 | Phase 1 characterization + exact regression |
| 两次 endpoint 在不同 boundary | 展示不存在的组合状态 | quant-api same-snapshot composition |
| unavailable 被显示为 neutral | fail-open | 独立 `N_UNAVAILABLE` 和 reason codes |
| 三类 Zone 被统一 | 丢失业务含义 | typed result 与独立 formation rules |
| VWAP 每 session reset | 偏离日内累计语义 | 冻结 `trading_day_vwap_v1` |
| 全 Kernel Decimal 重构 | 范围和回归风险膨胀 | Decimal 仅限新 study domain DTO |
| 资金/退出规则自动化 | 越过人工判断和订单边界 | source conflict/manual review/no order |
| 无现成 backtest surface | 无法直接完成 promotion evidence | 保持 observation；研究工具另立任务 |

## 21. Unresolved Questions

以下问题是未来 Research Gate 的输入，不由实现者自行决定：

### N semantics

- pivot 至少需要多少后续 completed bars 才确认；
- equality、gap、涨跌停和 session break 如何影响 pivot；
- NBand 精确上下边界和失效条件；
- strong/medium/weak 的机器阈值与最少样本；
- fractalization 的确定性归并次序；
- consolidation 与微弱 directional structure 的边界。

### SuBing facets

- 日线方向的唯一 executable observation formula；
- breakout Bar 是否计入“三根”；
- 回到区间边界的 equality 规则；
- 起涨点/起跌点的确定性定位；
- POST_ENTRY_TIME_STOP 采用 3、4、5 或分层 horizon；
- “缺乏延续”的 price/return/structure 标准；
- BOLL 是否值得进入未来 observation，以及采用何种 policy。

### Intraday 1m

- KeyLevelZone width policy；
- ConsolidationRange 的最少 Bar、振幅和 Volume classifier；
- MA Trend 的 MA family、period 和确认规则；
- ABC impulse/pullback threshold；
- 夜盘开盘作为 ABC A 点在不同品种上的研究有效性。

这些 unresolved questions 不阻止本文作为总路线设计接受，但会 fail-closed 地阻止对应机器 classifier 或后续阶段开始。

## 22. Acceptance Criteria for This Design

本设计只有在以下条件全部满足时才可进入独立 Review：

- 当前 SuBing Factor、Calibration、5m/15m companion、resolver、Signal、Alert、Execution Review 事实精确；
- source heuristic、current executable、future observation/candidate 明确分开；
- 未发明 N1/N2/N3/N4 四节点来源术语；
- N2 destruction、N1 reversal、terminal-pivot StructureChange 明确分层；
- confirmed history 与 active tail 的 causal boundary 明确；
- NBand、ConsolidationRange、KeyLevelZone 业务语义独立；
- SuBing Facets 不改变 v1；
- composition 有 `N_UNAVAILABLE` 和 same-snapshot identity；
- VWAP 按 trading_day reset，不按午休或 session segment reset；
- Decimal 范围不扩展为现有 Kernel 全面重构；
- Web 只有有限组合且 render-only；
- 阶段 Lane 和独立 Gate 明确；
- 没有业务代码、active canonical、Registry、DB、Runtime 或外部状态变更。
