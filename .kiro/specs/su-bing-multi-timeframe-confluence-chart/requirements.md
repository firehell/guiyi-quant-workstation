# Requirements Document

> **未实施草稿**：本 Spec 仅有 requirements/design，无 tasks；不表示已实现。当前 Web 为 Market-only。

## Introduction

本 Spec 定义“独立苏冰多周期共振策略 + 主图指标”的通用首版基线。目标是形成一个不绑定具体品种、版本化、可解释的苏冰策略族需求，以及服务人工观察和机会发现的主图指标需求。策略遵循“大周期定方向、中周期选图、小周期择时”的分层框架，并将周期共振与 EMA、MACD、BOLL、成交量、前区间突破组成的指标共振明确分开。

本 Spec 的 Requirements 已确认，Design 阶段已完成；本次修订只校正 `actual_dominant` 身份语义，不创建 tasks、不修改代码，也不表示策略已经可回测、可运行、有效、盈利或生产就绪。本 Spec 不设计预警、企业微信、通知、自动交易、订单、退出交易、持仓管理、Runtime 切换或实盘执行。所有策略结果、风险参考和图表标记均为研究观察，不是交易指令。

规格名称固定为 `su-bing-multi-timeframe-confluence-chart`。该名称用于与旧 `su_bing_ema21`、`su_bing_jm_v1b_short_hold` 及 `su_bing_jm_daily_ema21_macd_volume` 区分。本 Spec 不继承上述历史资产的品种、周期、参数、持有期、成交假设、实现路径或测试结果。

## Scope

### In Scope

- 一个不绑定具体品种的、独立且版本化的 Su_Bing_Multi_Timeframe_Confluence_Strategy_Family。
- 每个 Observation_Instance 绑定一个 Logical_ActualDominantObservationBinding；三个周期分别通过 strict `BarQuery(actual_dominant, contract_or_series=None)` 由服务端解析具体合约 lineage。
- 每个周期的 BarsResult 可包含同一 Source_Family 的一个或多个具体合约 DatasetKey；每根 consumed bar 必须同时匹配 source DatasetKey 与 MainContractMap `rank=1` 有效映射。
- 固定 `1d` 大周期方向、`15m` 中周期选图、`5m` 小周期择时的首版周期职责。
- long/short 镜像的方向、候选、确认、失效和过期规则。
- 独立的 Timeframe_Confluence_Evidence 与 Indicator_Confluence_Evidence。
- EMA21、MACD、BOLL、成交量、前区间突破五类指标证据。
- 震荡回避、突破确认，以及 `idle`、`candidate`、`confirmed`、`invalidated`、`unavailable` 状态。
- candidate 和 confirmed 作为可解释、可追溯的 Research_Opportunity_State。
- opportunity lifecycle 的 invalidation 和 expiration，不含退出交易或持仓管理。
- 研究性参考失效位和风险距离，不计算建议手数、仓位或资金分配。
- 首个承载于 Market K线页、默认使用 Standard_Density 的 Main_Chart_Indicator。
- confirmed-bar、as-of 对齐、无未来数据、不重绘、数据质量和可追溯性要求。
- 可供未来 SignalEvent_Adapter 消费的中立 Strategy_Observation 合同；本 Spec 不设计或启用该适配器。

### Out of Scope

- 在同一个 Observation_Instance 中使用或混合 `continuous` 数据身份。
- 预警策略、企业微信、Notification_Gate、Channel、通知文案和真实发送。
- 自动交易、订单创建、订单提交、实盘账户、建议手数、仓位计算、资金分配和无人值守运行。
- 退出交易、止盈、平仓、减仓、加仓、反手、持仓管理和最大持有期。
- 保证金、费用、成交滑点、撮合和盈亏计算。
- Runtime promotion/switch、live enable、scheduler 和生产部署。
- 回测引擎、回测 API/Web/worker/queue、收益报告和参数优化。
- 多组参数自动择优、自动寻优或从历史结果反推首版参数。
- 从旧 `su_bing_ema21` 或其他历史苏冰实现继承默认规则。
- 将课程案例、口诀、心理、复盘标签或人工判断直接转换成触发规则。
- 复制私有课程原文、长段内容、截图或图片案例。

## Source and Decision Classification

### Course-Derived Rule Candidates

以下内容仅是由 `SOURCE_INDEX.md` 和 `SU_BING_RULEBOOK.md` 支持的课程规则候选，不是课程已经给出的精确工程参数：

- 大周期判断方向、小周期寻找介入窗口，并为中周期保留选图职责。
- 均线方向、MACD 辅助、量能、震荡区间和突破有效性构成研究机会候选框架。
- 趋势优先、震荡回避、等待确认、假突破防范和失效优先。
- 回调、突破、背离、极端位置、口诀和图片案例仍需人工复核，不直接形成规则。

### Current Product Requirements

以下内容是本次“通用首版基线”已经冻结的产品要求，不是课程原文声明：

- 策略内核不绑定具体品种；每个 Observation_Instance 绑定一个 Logical_ActualDominantObservationBinding，固定 `provider=rqdata`、`kind=actual_dominant`、产品 symbol、adjustment/schema、`mapping_rule=volume_open_interest` 和 `rank=1`，具体合约由服务端按每根 bar 的交易日或有效区间解析。
- 首版固定 Direction_Timeframe=`1d`、Selection_Timeframe=`15m`、Timing_Timeframe=`5m`。
- long 和 short 使用镜像规则，保持相同职责、证据类别、状态门槛和生命周期语义。
- 输出状态固定为 `idle`、`candidate`、`confirmed`、`invalidated`、`unavailable`；candidate 和 confirmed 均为研究机会状态。
- 五类指标证据固定为 EMA21、MACD、BOLL、成交量和前区间突破。
- Main_Chart_Indicator 首个承载面固定为 Market K线页，默认使用 Standard_Density。
- 风险输出只包含 Research_Risk_Reference，不包含建议手数、仓位、资金、保证金或费用。
- lifecycle 只定义 opportunity invalidation 和 expiration，不定义退出交易或持仓管理。
- 只使用可用时点已确认的数据；输出不重绘、不使用未来数据、不表达交易指令。
- 本 Spec 不设计预警、企微、通知、自动交易或订单。

### Design-Stage Authorized Engineering Baselines

以下事项授权 Design 阶段给出单一的、少量且可解释的版本化工程基线，不再作为 Requirements 阶段的用户待决项：

- EMA21 的 seed policy、斜率规则、价格关系和 readiness rule；EMA 核心周期固定为 21。
- MACD、BOLL、Volume、Prior Range、Range Regime 和 Breakout_Confirmation 的精确公式、参数、readiness rule、证据门槛和冲突处理规则。
- Research_Risk_Reference 的参考失效位选择规则、风险距离计算规则，以及 opportunity invalidation/expiration 的精确定义。
- Main_Chart_Indicator 在 Standard_Density 下的可见图层、证据摘要和详情交互。

每项 Design_Engineering_Baseline 必须标注为“非课程原始参数、待未来验证”，必须具有独立版本，并且只能提供一组首版基线。Design 阶段不得提供多组候选并自动择优，不得将该工程基线描述为课程原始参数、有效参数或盈利参数。

## Glossary

- **Su_Bing_Multi_Timeframe_Confluence_Strategy_Family**：本 Spec 定义的独立苏冰策略族；策略内核不绑定具体品种，且不等同于旧 `su_bing_ema21` 或任何既有苏冰策略。
- **Strategy_Spec**：记录策略身份、版本、参数、数据边界、规则、状态和变更原因的独立规格。
- **Strategy_Evaluator**：在满足数据质量和时序约束后生成 Strategy_Observation 的逻辑系统。
- **Observation_Instance**：Strategy_Evaluator 针对一个 Logical_ActualDominantObservationBinding 和单一 Bar_As_Of_Time 执行的一次观察实例；Observation_Instance 可消费换月窗口内多个具体合约，但不得混入 `continuous`。
- **Logical_ActualDominantObservationBinding**：Observation_Instance 的逻辑实际主力绑定；固定 `provider=rqdata`、`dataset_kind=actual_dominant`、产品 symbol、adjustment、schema、`mapping_rule=volume_open_interest` 与 `rank=1`，不包含由调用方指定的具体合约。
- **Source_Family**：BarsResult 在单一 frequency 下的来源族，由 provider、dataset kind、symbol、frequency、adjustment 和 schema 组成，不包含具体合约；一个 BarsResult 的全部 source DatasetKey 必须属于唯一 Source_Family。
- **BarsResult**：MarketDataService 对单一 BarQuery 的正式读取结果，包含 CanonicalBar 序列、一个或多个 source DatasetKey、manifest lineage、数据版本和 requested window。
- **CanonicalBar**：数据核心定义的标准 K 线记录；本 Spec 消费的每根 CanonicalBar 都携带可与具体合约 DatasetKey 匹配的数据身份。
- **Consumed_Bar**：通过 source DatasetKey、MainContractMap、质量和 as-of 校验后进入 Strategy_Evaluator 的 CanonicalBar。
- **Actual_Contract_Lineage**：每根 Consumed_Bar 的服务端解析 lineage，至少包含具体合约、匹配的 DatasetKey、MainContractMap mapping date 或 effective interval、mapping revision、mapping rule 与 rank。
- **Strategy_Observation_Query_API**：按逻辑实际主力绑定查询 Strategy_Observation 的只读服务边界；Strategy_Observation_Query_API 不把调用方提供的具体合约视为 authoritative identity。
- **Main_Chart_Indicator**：首个承载于 Market K线页、叠加在 K 线主图或相邻解释区域、用于人工观察和解释策略状态的只读指标系统。
- **Market_Kline_Page**：现有 Market K线页，也是 Main_Chart_Indicator 的首个 Web 承载面。
- **Standard_Density**：Main_Chart_Indicator 首版默认展示密度；展示必要状态、核心图层和摘要证据，同时将完整证据放入详情交互。
- **Strategy_Observation**：策略在指定 Bar_As_Of_Time 生成的结构化研究观察；Strategy_Observation 不是订单或交易指令。
- **Direction_Timeframe**：只负责确定允许观察方向或中性状态的大周期；首版固定为 `1d`。
- **Selection_Timeframe**：只负责判断图形背景、趋势延续条件和震荡过滤是否具备候选资格的中周期；首版固定为 `15m`。
- **Timing_Timeframe**：只负责候选、确认、失效和过期观察时点的小周期；首版固定为 `5m`。
- **Confirmed_Bar**：数据源已标记为完整结束且在 Bar_As_Of_Time 已经可用的 K 线。
- **Bar_As_Of_Time**：一次策略判断允许读取信息的截止时点。
- **As_Of_Alignment**：对多周期数据按 Bar_As_Of_Time 对齐，只使用结束时间不晚于截止时点的 Confirmed_Bar。
- **Timeframe_Confluence_Evidence**：Direction_Timeframe、Selection_Timeframe 和 Timing_Timeframe 在职责范围内是否方向一致、状态兼容的独立证据集合。
- **Indicator_Confluence_Evidence**：EMA21、MACD、BOLL、成交量和前区间突破五类指标的独立证据集合。
- **EMA_Evidence**：由固定 EMA21 核心及版本化 seed policy、斜率规则、价格关系和 readiness rule 产生的均线证据。
- **MACD_Evidence**：由显式版本化 MACD policy 产生的辅助证据。
- **BOLL_Evidence**：由显式版本化 BOLL policy 产生的通道位置、方向或扩张状态证据。
- **Volume_Evidence**：由显式版本化成交量 policy 产生的量能确认或否定证据。
- **Prior_Range_Evidence**：由 Bar_As_Of_Time 之前的 Confirmed_Bar 定义前区间并产生的突破证据。
- **Range_Regime**：由版本化规则识别的震荡或非趋势状态。
- **Breakout_Confirmation**：由 Timing_Timeframe 的 Confirmed_Bar 按版本化规则确认前区间突破有效的状态。
- **Observation_State**：`idle`、`candidate`、`confirmed`、`invalidated` 或 `unavailable` 之一。
- **Research_Opportunity_State**：`candidate` 或 `confirmed`；只表示研究机会成熟度，不表示交易指令。
- **Opportunity_Lifecycle**：Research_Opportunity_State 从形成到 invalidation 或 expiration 的状态演进；不包含订单、持仓或退出交易语义。
- **Invalidation_Reason**：证据反转或规则失败导致 Research_Opportunity_State 失效的版本化、可解释原因。
- **Expiration_Reason**：机会在版本化有效窗口结束后过期的可解释原因；过期使用 Observation_State `invalidated` 并以 reason code 区分。
- **Research_Risk_Reference**：由参考失效位和当前参考价格形成的研究性失效价格与风险距离；不包含建议手数、仓位、资金、保证金、费用或订单字段。
- **Design_Engineering_Baseline**：Design 阶段为首版提供的一组可解释、版本化工程公式和参数；该基线必须标注为非课程原始参数、待未来验证。
- **DatasetKey**：由项目数据核心定义的不可歧义持久化数据集身份；`actual_dominant` DatasetKey 包含一个具体合约。
- **Actual_Dominant_Dataset**：DatasetKey 类型为 `actual_dominant` 的具体合约数据集；换月窗口可由同一 Source_Family 的多个 Actual_Dominant_Dataset 共同覆盖。
- **MainContractMap**：项目数据核心提供的实际主力映射；本 Spec 固定使用 `rule=volume_open_interest`、`rank=1`，并按 consumed bar 的有效交易日或 effective interval 解析具体合约。
- **DataGap**：Catalog/Manifest/Gap 合同声明的正式数据缺口。
- **MarketDataService**：项目读取 Canonical 市场数据的统一消费者入口。
- **SignalEvent_Adapter**：未来可将 Strategy_Observation 映射到 SignalEvent 的独立边界组件；本 Spec 不设计或启用该组件。
- **Legacy_Su_Bing_Reference**：旧 `su_bing_ema21`、旧苏冰 Strategy Spec、旧代码、旧测试或旧报告，只能标注为 `history_draft`、`legacy_reference` 或 `engineering_reference`。
- **Research_Observation_Label**：明确表示“研究观察、非交易指令、无自动下单”的展示标识。

## Assumptions

1. 本项目继续作为本地、单用户期货量化研究工作站运行。
2. 正式历史数据继续由 DatasetKey、Catalog/Manifest/Gap/MainContractMap 和 MarketDataService 管理。
3. 首版使用 Canonical 固定周期 `1d/15m/5m`，不从其他周期聚合或回退。
4. MACD 当前公共合同不自动代表正式策略资格；Design 阶段必须显式给出 Design_Engineering_Baseline 并满足 Indicator Kernel 的能力要求。
5. 仓库当前没有可用回测子系统；本 Spec 不恢复或设计回测兼容入口。
6. Design 阶段获授权定义一组工程基线，但该授权不构成参数有效性、盈利性或生产就绪声明。
7. Requirements 阶段不存在尚待用户选择的品种、数据身份、周期、方向、状态、风险数量或首个承载面决策。

## Requirements

### Requirement 1: Independent strategy identity and source separation

**User Story:** As a quantitative researcher, I want an independent and traceable Su Bing strategy family, so that the new strategy does not silently inherit legacy behavior.

#### Acceptance Criteria

1. THE Su_Bing_Multi_Timeframe_Confluence_Strategy_Family SHALL use a strategy identity that is distinct from every Legacy_Su_Bing_Reference.
2. THE Strategy_Spec SHALL record strategy code, strategy version, parameter version, change reason, and source classification.
3. WHEN a rule originates from a course summary, THE Strategy_Spec SHALL label the rule as a Course-Derived Rule Candidate and record the corresponding `RULE-*` or `sbn-*` identifier.
4. WHEN a rule originates from the current product target, THE Strategy_Spec SHALL label the rule as a Current Product Requirement.
5. WHEN Design stage supplies an exact formula or parameter, THE Strategy_Spec SHALL label the formula or parameter as a Design_Engineering_Baseline.
6. IF a proposed default originates only from a Legacy_Su_Bing_Reference, THEN THE Strategy_Spec SHALL reject the proposed default.
7. WHEN a strategy rule or parameter meaning changes, THE Strategy_Spec SHALL create a new strategy version or parameter version.
8. THE Strategy_Spec SHALL limit private course source content to source identifiers, short paraphrased summaries, abstract candidates, quantization status, and review status.

### Requirement 2: Canonical data identity, quality, and confirmed-bar evaluation

**User Story:** As a quantitative researcher, I want every observation bound to one trusted logical actual-dominant identity with per-bar concrete-contract lineage, so that strategy states remain causally valid across contract rolls and data identities cannot be mixed.

#### Acceptance Criteria

1. THE Su_Bing_Multi_Timeframe_Confluence_Strategy_Family SHALL keep the strategy kernel independent from a specific product symbol.
2. THE Observation_Instance SHALL bind exactly one Logical_ActualDominantObservationBinding with `provider=rqdata`, `dataset_kind=actual_dominant`, one product symbol, one adjustment, one schema, `mapping_rule=volume_open_interest`, and `rank=1`.
3. WHEN the Strategy_Evaluator requests formal historical bars, THE Strategy_Evaluator SHALL issue one strict BarQuery for each required frequency with `dataset_kind=actual_dominant` and `contract_or_series=None`.
4. IF an Observation_Instance requests a `continuous` data identity, THEN THE Strategy_Evaluator SHALL return Observation_State `unavailable` with a bounded identity reason.
5. WHEN a BarsResult is accepted for a required frequency, THE Strategy_Evaluator SHALL require one or more concrete-contract DatasetKeys that all belong to exactly one Source_Family for that frequency.
6. WHEN the three required frequencies are evaluated, THE Strategy_Evaluator SHALL require the three Source_Families to share the Logical_ActualDominantObservationBinding provider, dataset kind, symbol, adjustment, and schema.
7. WHEN a CanonicalBar is consumed, THE Strategy_Evaluator SHALL require the CanonicalBar identity and frequency to match at least one DatasetKey in the corresponding BarsResult.
8. WHEN a CanonicalBar is consumed, THE Strategy_Evaluator SHALL require the CanonicalBar concrete contract to match MainContractMap `rule=volume_open_interest`, `rank=1` for the CanonicalBar trading day or effective interval.
9. WHEN a CanonicalBar is consumed, THE Strategy_Evaluator SHALL record Actual_Contract_Lineage with the concrete contract, matching DatasetKey, mapping date or effective interval, and mapping revision.
10. WHEN the Strategy_Evaluator aligns the three required frequencies, THE Strategy_Evaluator SHALL permit aligned `1d`, `15m`, and `5m` bars to reference different concrete contracts when completion times select different valid MainContractMap intervals.
11. WHEN the Strategy_Evaluator evaluates a Bar_As_Of_Time, THE Strategy_Evaluator SHALL use only Confirmed_Bars available at the Bar_As_Of_Time.
12. WHEN the Strategy_Evaluator aligns multiple timeframes, THE Strategy_Evaluator SHALL exclude every bar whose end time is later than the Bar_As_Of_Time.
13. IF a requested window intersects a DataGap or failed-quality interval, THEN THE Strategy_Evaluator SHALL return Observation_State `unavailable` with a bounded data-quality reason.
14. IF an indicator lacks required warm-up history, THEN THE Strategy_Evaluator SHALL return the affected evidence as unavailable without substituting zero or another timeframe.
15. WHEN strict research data is evaluated, THE Strategy_Evaluator SHALL require `quality_status=passed`.
16. IF Logical_ActualDominantObservationBinding identity, MainContractMap mapping, data revision, or policy identity is missing or inconsistent, THEN THE Strategy_Evaluator SHALL return Observation_State `unavailable`.
17. IF a Source_Family mismatch, CanonicalBar-to-DatasetKey mismatch, or CanonicalBar-to-MainContractMap mismatch occurs, THEN THE Strategy_Evaluator SHALL return Observation_State `unavailable` with a bounded lineage reason.

### Requirement 3: Fixed three-timeframe responsibility model

**User Story:** As a strategy researcher, I want each fixed timeframe to have one explicit responsibility, so that direction, selection, and timing remain auditable.

#### Acceptance Criteria

1. THE Strategy_Spec SHALL define Direction_Timeframe as `1d` for the first version.
2. THE Strategy_Spec SHALL define Selection_Timeframe as `15m` for the first version.
3. THE Strategy_Spec SHALL define Timing_Timeframe as `5m` for the first version.
4. THE Strategy_Evaluator SHALL derive allowed directional context only from Direction_Timeframe.
5. THE Strategy_Evaluator SHALL derive chart-selection eligibility and Range_Regime only from Selection_Timeframe.
6. THE Strategy_Evaluator SHALL derive candidate, confirmed, invalidated, and expiration observations only from Timing_Timeframe.
7. WHEN Timing_Timeframe produces a candidate, THE Strategy_Evaluator SHALL preserve the Direction_Timeframe result as a separate input.
8. WHEN the three timeframe roles are evaluated, THE Strategy_Evaluator SHALL emit Timeframe_Confluence_Evidence independently from Indicator_Confluence_Evidence.
9. IF any required timeframe is unavailable or not causally aligned, THEN THE Strategy_Evaluator SHALL return Observation_State `unavailable`.

### Requirement 4: Mirrored direction, selection, and timing eligibility

**User Story:** As a strategy researcher, I want long and short opportunities evaluated symmetrically, so that direction does not introduce hidden rule asymmetry.

#### Acceptance Criteria

1. WHEN Direction_Timeframe is evaluated, THE Strategy_Evaluator SHALL classify direction as long, short, neutral, or unavailable using one versioned direction policy.
2. THE Strategy_Spec SHALL derive every short-side ordering, sign, boundary, and comparison rule as the declared mirror of the corresponding long-side rule.
3. THE Strategy_Spec SHALL apply equal evidence categories, readiness rules, confirmation thresholds, invalidation semantics, and expiration semantics to long and short directions.
4. WHEN Selection_Timeframe is evaluated, THE Strategy_Evaluator SHALL classify chart background as eligible, ineligible, or unavailable using one versioned selection policy.
5. WHEN Timing_Timeframe is evaluated, THE Strategy_Evaluator SHALL create a candidate only after direction and selection inputs are available.
6. IF Direction_Timeframe is neutral while no Research_Opportunity_State is active, THEN THE Strategy_Evaluator SHALL emit Observation_State `idle`.
7. IF Direction_Timeframe becomes neutral while a Research_Opportunity_State is active, THEN THE Strategy_Evaluator SHALL emit Observation_State `invalidated` with an Invalidation_Reason.
8. IF Selection_Timeframe is ineligible, THEN THE Strategy_Evaluator SHALL withhold Research_Opportunity_State.
9. IF Timing_Timeframe direction conflicts with Direction_Timeframe direction, THEN THE Strategy_Evaluator SHALL withhold Observation_State `confirmed` and record the conflict.
10. WHEN all timeframe responsibilities are compatible, THE Strategy_Evaluator SHALL record every contributing timeframe and completed-bar timestamp in Timeframe_Confluence_Evidence.

### Requirement 5: Separate five-factor indicator confluence and design baseline

**User Story:** As a strategy researcher, I want indicator evidence separated by factor and backed by one explainable baseline, so that opportunity states can be explained without hidden optimization.

#### Acceptance Criteria

1. THE Indicator_Confluence_Evidence SHALL contain separate EMA_Evidence, MACD_Evidence, BOLL_Evidence, Volume_Evidence, and Prior_Range_Evidence fields.
2. THE Strategy_Spec SHALL fix the EMA core period at 21.
3. THE Strategy_Spec SHALL assign one versioned Design_Engineering_Baseline to EMA21, MACD, BOLL, Volume, and Prior Range evidence.
4. THE Design_Engineering_Baseline SHALL label every exact formula and parameter as non-course-original and pending future validation.
5. THE Design_Engineering_Baseline SHALL provide one first-version parameter set for each evidence factor.
6. IF a design proposes automatic selection among multiple parameter sets, THEN THE Strategy_Spec SHALL reject the proposal as outside the first-version baseline.
7. WHEN indicator evidence is evaluated, THE Strategy_Evaluator SHALL preserve positive, negative, neutral, and unavailable outcomes for each factor.
8. WHEN Indicator_Confluence_Evidence is summarized, THE Strategy_Evaluator SHALL retain every factor outcome rather than replacing the evidence set with only a total score.
9. WHEN MACD_Evidence is used, THE Strategy_Spec SHALL declare the MACD seed policy, histogram scale, periods, readiness rule, and capability status.
10. WHEN EMA_Evidence is used, THE Strategy_Spec SHALL declare the EMA21 seed policy, slope rule, price-relation rule, and readiness rule.
11. WHEN BOLL_Evidence is used, THE Strategy_Spec SHALL declare the center-line period, dispersion rule, band multiplier, readiness rule, and interpretation rule.
12. WHEN Volume_Evidence is used, THE Strategy_Spec SHALL declare the comparison window, normalization rule, missing-volume rule, and confirmation threshold.
13. WHEN Prior_Range_Evidence is used, THE Strategy_Spec SHALL declare the range window, boundary rule, breakout threshold, and confirmation-bar rule.
14. IF any required factor is unavailable, THEN THE Strategy_Evaluator SHALL withhold Observation_State `confirmed`.
15. WHERE the Strategy_Spec classifies a factor as optional, THE Strategy_Evaluator SHALL retain the optional factor outcome without treating factor absence as a confirmation veto.
16. THE Strategy_Evaluator SHALL calculate Indicator_Confluence_Evidence independently from Timeframe_Confluence_Evidence.

### Requirement 6: Range avoidance and breakout confirmation

**User Story:** As a strategy researcher, I want ranging markets and unconfirmed breakouts handled explicitly, so that weak setups remain research candidates instead of confirmed opportunities.

#### Acceptance Criteria

1. THE Strategy_Spec SHALL assign one versioned Design_Engineering_Baseline to Range_Regime and Breakout_Confirmation.
2. THE Design_Engineering_Baseline SHALL label Range_Regime and Breakout_Confirmation formulas and parameters as non-course-original and pending future validation.
3. THE Strategy_Spec SHALL define Range_Regime using only current and past Confirmed_Bars.
4. WHEN Selection_Timeframe is classified as Range_Regime, THE Strategy_Evaluator SHALL block transition to Observation_State `confirmed`.
5. WHEN price first satisfies a breakout candidate rule, THE Strategy_Evaluator SHALL emit Observation_State `candidate` until Breakout_Confirmation completes or Opportunity_Lifecycle invalidates the candidate.
6. WHEN Breakout_Confirmation completes on a Timing_Timeframe Confirmed_Bar, THE Strategy_Evaluator SHALL record the boundary, confirmation bar, evidence, and rule version.
7. IF a breakout candidate fails the versioned confirmation rule, THEN THE Strategy_Evaluator SHALL transition the candidate to Observation_State `invalidated` with an Invalidation_Reason.
8. THE Strategy_Evaluator SHALL derive prior-range boundaries without using future extrema or later swing labels.
9. IF a design proposes automatic selection among multiple Range_Regime or Breakout_Confirmation parameter sets, THEN THE Strategy_Spec SHALL reject the proposal as outside the first-version baseline.

### Requirement 7: Research opportunity state model

**User Story:** As a strategy researcher, I want explicit observation states, so that the chart and downstream research can distinguish early evidence, confirmed evidence, invalidation, and unavailability.

#### Acceptance Criteria

1. THE Strategy_Evaluator SHALL emit exactly one Observation_State from `idle`, `candidate`, `confirmed`, `invalidated`, or `unavailable` for each evaluated Timing_Timeframe bar.
2. THE Strategy_Evaluator SHALL classify `candidate` and `confirmed` as Research_Opportunity_State values.
3. WHEN a state transition occurs, THE Strategy_Evaluator SHALL record the prior state, new state, Bar_As_Of_Time, rule version, and reason codes.
4. WHEN identical bars, identities, parameters, and Bar_As_Of_Time are evaluated repeatedly, THE Strategy_Evaluator SHALL produce an equivalent Strategy_Observation.
5. IF source data or policy identity changes after an observation is produced, THEN THE Strategy_Evaluator SHALL mark the recomputed observation as revised.
6. WHEN a candidate becomes confirmed, THE Strategy_Evaluator SHALL preserve the candidate evidence and add the confirmation evidence.
7. WHEN a candidate or confirmed opportunity becomes invalidated, THE Strategy_Evaluator SHALL preserve the earlier state history and record an Invalidation_Reason.
8. WHEN a candidate or confirmed opportunity expires, THE Strategy_Evaluator SHALL emit Observation_State `invalidated` and record an Expiration_Reason.
9. THE Strategy_Evaluator SHALL preserve candidate and confirmed observations as research opportunities without converting the observations into order or position intent.

### Requirement 8: Opportunity lifecycle and research risk reference

**User Story:** As a strategy researcher, I want a bounded opportunity lifecycle and a reference invalidation distance, so that opportunity quality can be inspected without introducing position sizing or trade management.

#### Acceptance Criteria

1. THE Strategy_Spec SHALL assign one versioned Design_Engineering_Baseline to Research_Risk_Reference, invalidation, and expiration.
2. THE Strategy_Spec SHALL define a reference invalidation level before a candidate can transition to confirmed.
3. WHEN Research_Risk_Reference is available, THE Strategy_Evaluator SHALL expose the reference invalidation price and non-negative risk distance.
4. WHEN prices and risk distances are calculated, THE Strategy_Evaluator SHALL use Decimal-compatible domain values.
5. IF a required price or invalidation input is missing, malformed, non-positive, stale, or causally unavailable, THEN THE Strategy_Evaluator SHALL return Research_Risk_Reference as unavailable.
6. THE Research_Risk_Reference SHALL include calculation inputs, rule version, result, unit, and Research_Observation_Label.
7. THE Opportunity_Lifecycle SHALL define invalidation and expiration without defining exit transaction, holding period, or position-management behavior.
8. THE Strategy_Observation SHALL omit suggested quantity, position size, capital allocation, margin, fee, order, and execution fields.
9. THE Strategy_Evaluator SHALL keep `auto_order=false` for every Strategy_Observation.

### Requirement 9: Market Kline main-chart observation and explanation

**User Story:** As a manual observer, I want the Market Kline page to expose strategy context and evidence at a standard density, so that each research opportunity can be inspected without reading implementation details.

#### Acceptance Criteria

1. THE Main_Chart_Indicator SHALL use Market_Kline_Page as the first presentation surface.
2. THE Main_Chart_Indicator SHALL use Standard_Density as the default presentation density.
3. THE Main_Chart_Indicator SHALL display the current Direction_Timeframe direction and completed-bar timestamp.
4. THE Main_Chart_Indicator SHALL display EMA21, BOLL bands, and prior-range boundaries on the applicable chart context.
5. WHEN Observation_State is `candidate`, `confirmed`, or `invalidated`, THE Main_Chart_Indicator SHALL display a visually distinct marker with the Timing_Timeframe bar time.
6. WHEN a marker is inspected, THE Main_Chart_Indicator SHALL display Timeframe_Confluence_Evidence separately from Indicator_Confluence_Evidence.
7. WHEN indicator evidence is displayed, THE Main_Chart_Indicator SHALL expose all five factor outcomes and active policy versions.
8. WHEN Research_Risk_Reference is available, THE Main_Chart_Indicator SHALL display the reference invalidation level and risk distance as research references.
9. WHEN data or evidence is unavailable, THE Main_Chart_Indicator SHALL display an unavailable state without synthesizing an opportunity marker.
10. WHEN a confirmed historical marker is rendered, THE Main_Chart_Indicator SHALL keep the marker unchanged when only later bars are appended.
11. IF provider-final data revision changes a historical result, THEN THE Main_Chart_Indicator SHALL identify the result as revised.
12. THE Main_Chart_Indicator SHALL display a Research_Observation_Label near strategy state and risk explanations.
13. THE Main_Chart_Indicator SHALL use opportunity, confirmation, invalidation, and expiration wording instead of imperative trade-action wording.
14. THE Main_Chart_Indicator SHALL keep chart rendering free of future-bar dependencies.

### Requirement 10: Explainable and adapter-ready observation contract

**User Story:** As a system maintainer, I want one explainable strategy observation contract, so that chart rendering and future signal adaptation can share semantics without coupling to notifications.

#### Acceptance Criteria

1. THE Strategy_Observation SHALL include strategy identity, strategy version, parameter version, Logical_ActualDominantObservationBinding, per-timeframe Source_Family, every consumed concrete-contract DatasetKey, data revision, exact input window, and Bar_As_Of_Time.
2. THE Strategy_Observation SHALL include Direction_Timeframe=`1d`, Selection_Timeframe=`15m`, Timing_Timeframe=`5m`, As_Of_Alignment metadata, and completed-bar timestamps.
3. THE Strategy_Observation SHALL include per-timeframe and per-consumed-bar Actual_Contract_Lineage with concrete contract, mapping date or effective interval, and mapping revision.
4. THE Strategy_Observation SHALL include Observation_State, direction, Timeframe_Confluence_Evidence, Indicator_Confluence_Evidence, Research_Risk_Reference, and reason codes.
5. THE Strategy_Observation SHALL include `observation_only=true`, `not_trading_instruction=true`, `auto_order=false`, `future_looking=false`, and `repainting=false`.
6. THE Strategy_Observation_Query_API SHALL accept a Logical_ActualDominantObservationBinding without requiring a caller-supplied authoritative `actual_contract`.
7. WHEN the Strategy_Observation_Query_API returns an observation, THE Strategy_Observation_Query_API SHALL return the server-resolved per-timeframe and per-consumed-bar Actual_Contract_Lineage.
8. WHEN Main_Chart_Indicator consumes a Strategy_Observation, THE Main_Chart_Indicator SHALL render the supplied semantic fields without independently redefining strategy rules.
9. WHERE a future SignalEvent_Adapter is introduced by a separate specification, THE Strategy_Observation SHALL provide sufficient identity, timing, evidence, and safety fields for an explicit mapping.
10. THE Su_Bing_Multi_Timeframe_Confluence_Strategy_Family SHALL keep SignalEvent_Adapter, Notification_Gate, and Channel concerns outside Strategy_Evaluator.

### Requirement 11: Future-function, repainting, and leakage prevention

**User Story:** As a quantitative researcher, I want causal and stable observations, so that displayed opportunities do not depend on information unavailable at the observation time.

#### Acceptance Criteria

1. THE Strategy_Evaluator SHALL use only values derivable from Confirmed_Bars at or before Bar_As_Of_Time.
2. WHEN higher-timeframe bars are aligned to a Timing_Timeframe bar, THE Strategy_Evaluator SHALL use the latest higher-timeframe bar completed by the Timing_Timeframe Bar_As_Of_Time.
3. THE Strategy_Evaluator SHALL exclude centered indicators, future extrema, final-shape swing labels, and later-bar confirmation from historical observation inputs.
4. WHEN later bars are appended to an unchanged input prefix, THE Strategy_Evaluator SHALL preserve every Strategy_Observation whose Bar_As_Of_Time lies in the unchanged prefix.
5. IF an indicator policy is future-looking, repainting, observation-only under a special exception, or not eligible for formal strategy use, THEN THE Strategy_Evaluator SHALL reject the indicator policy for this strategy.
6. WHEN review notes, manual tags, later outcomes, or post-opportunity conclusions exist, THE Strategy_Evaluator SHALL exclude those values from same-time candidate, confirmation, invalidation, and expiration evaluation.
7. IF a causal eligibility check cannot be completed, THEN THE Strategy_Evaluator SHALL return Observation_State `unavailable`.

### Requirement 12: Explicit exclusions and fail-closed readiness

**User Story:** As the project owner, I want strategy research isolated from notifications, execution, and position management, so that the feature cannot create unintended external effects.

#### Acceptance Criteria

1. THE Su_Bing_Multi_Timeframe_Confluence_Strategy_Family SHALL produce research observations without creating or submitting orders.
2. THE Su_Bing_Multi_Timeframe_Confluence_Strategy_Family SHALL exclude enterprise WeChat, alerts, notifications, Notification_Gate, and Channel behavior from this Spec.
3. THE Su_Bing_Multi_Timeframe_Confluence_Strategy_Family SHALL exclude Runtime promotion, live enablement, scheduler activation, and production deployment from this Spec.
4. THE Su_Bing_Multi_Timeframe_Confluence_Strategy_Family SHALL exclude backtest engine, matching, report, API, Web workflow, queue, and worker restoration from this Spec.
5. THE Su_Bing_Multi_Timeframe_Confluence_Strategy_Family SHALL exclude suggested quantity, position sizing, capital allocation, margin, fee, order, execution, exit transaction, holding-period, and position-management behavior from this Spec.
6. WHEN a Strategy_Observation is presented, THE Main_Chart_Indicator SHALL identify the result as research observation and non-trading instruction.
7. IF a required Logical_ActualDominantObservationBinding, Source_Family, Actual_Contract_Lineage, timeframe input, policy version, or Design_Engineering_Baseline is missing or inconsistent, THEN THE Strategy_Spec SHALL remain not implementation-ready.
8. IF a proposed feature path would send a notification, enable live behavior, create an order, calculate a suggested position, or manage a position, THEN THE Su_Bing_Multi_Timeframe_Confluence_Strategy_Family SHALL reject the path as outside this Spec.
9. WHEN the requirements phase completes, THE Strategy_Spec SHALL avoid claims of profitability, robustness, backtest validity, live readiness, alert readiness, or production readiness.

## Open Decisions

当前没有仍需用户确认的 Requirements 阶段开放决策。原 D1-D5 已按“通用首版基线”收口如下：

| ID | Resolved decision | Resolution | Status |
|---|---|---|---|
| D1 | Market and data identity | 策略内核不绑定品种；每个 Observation_Instance 绑定单一 Logical_ActualDominantObservationBinding；三个周期由服务端以 `actual_dominant + contract_or_series=None` 解析，允许换月窗口包含多个具体合约 DatasetKey，并逐 bar 验证 MainContractMap `volume_open_interest/rank=1`；不混用 `continuous` | `resolved` |
| D2 | Timeframe tuple | Direction=`1d`、Selection=`15m`、Timing=`5m` | `resolved` |
| D3 | Direction and state model | long/short 镜像；输出 `idle/candidate/confirmed/invalidated/unavailable`；candidate 与 confirmed 均为研究机会状态 | `resolved` |
| D4 | Indicator and lifecycle baseline | EMA 核心固定 EMA21；其余精确公式、参数、失效与过期规则授权 Design 阶段给出单一版本化工程基线，标注非课程原始参数、待未来验证 | `delegated_to_design` |
| D5 | Risk and chart surface | 风险只展示参考失效位/风险距离；不计算数量或仓位；首个承载面为 Market K线页，默认 Standard_Density | `resolved` |

## Phase Status

1. Requirements 保持已确认；本次修订只校正 `actual_dominant` 逻辑绑定、source family 和逐 bar 具体合约 lineage，不新增产品范围。
2. Design 阶段保持完成；`design.md` 必须与本文修订后的身份、API、哈希、DTO、ACL、错误码、correctness properties 和测试追踪一致。
3. EMA21 seed/readiness、MACD、BOLL、Volume、Prior Range、Range Regime、Breakout_Confirmation、Research_Risk_Reference、invalidation 和 expiration 继续使用 Design 阶段已给出的一组少量、可解释、版本化 Design_Engineering_Baseline。
4. 每项 Design_Engineering_Baseline 继续标注为“非课程原始参数、待未来验证”，并禁止多组参数自动择优。
5. Design 继续遵守 `docs/INDICATOR_KERNEL.md`、`docs/SIGNAL_EVENTS.md` 和苏冰 Strategy Generation Protocol 的边界。
6. Design 不得引入具体品种绑定、调用方 authoritative `actual_contract`、`continuous` 混用、建议手数、仓位、资金、保证金、费用、订单、退出交易、最大持有期、持仓管理、企微或通知设计。
7. 本次交付不创建 `tasks.md`，也不修改策略代码、指标代码、Web 代码、数据库、回测、通知或订单实现。
