# SU_BING_REVIEW_REPORT

## 审查结论

- review_date: 2026-06-28
- review_scope:
  - `.agents/skills/su-bing-strategy/SKILL.md`
  - `docs/strategy_knowledge/su_bing/SU_BING_RULEBOOK.md`
  - `docs/strategy_knowledge/su_bing/SU_BING_QUANT_SPEC_V0_1.md`
  - `docs/strategy_knowledge/su_bing/SU_BING_REVIEW_TAGS.md`
  - `docs/strategy_knowledge/su_bing/SOURCE_INDEX.md`
- review_role: 策略审查 Agent
- review_boundary: 只审查文档，不修改既有文件，不生成策略代码，不接实盘。

总体判断：

- 未发现课程内容被大段复制进本轮审查文档。
- Rulebook 和 Review Tags 基本区分了主观经验、复盘标签和可量化规则。
- EMA21 v0.1 已有较好的未来函数、数据泄露、实盘边界和 vn.py 实现指向。
- 但 EMA21 v0.1 尚未对齐当前 V1-B 目标，且 bar 级成交假设仍缺少足够细节。
- 结论：暂不允许进入策略代码实现。

## P0：必须修复，否则不能进入代码实现

### P0-001：EMA21 v0.1 未对齐当前 V1-B 目标

当前项目阶段是 V1-B：焦煤 JM 3 年真实数据短持有策略闭环，要求日线只用于方向，15m 和 5m 都可以独立入场，且入场后只持有 5-8 根对应周期 K 线。

当前 `SU_BING_QUANT_SPEC_V0_1.md` 支持 `15m`、`30m`、`60m` 入场周期，`1d` 作为方向过滤，但没有 `5m` 入场周期；时间止损仅保留扩展位，不默认启用 `max_hold_bars`。这会导致后续实现偏离 V1-B 的短持有闭环，实际变成更泛化的 EMA21 趋势波段规格。

必须修复：

- 将 v0.1 的当前实现目标明确收敛到 JM、最近 3 年、`15m` / `5m`、持有 5-8 根 bar。
- 删除或降级 `30m` / `60m` 为后续版本候选，除非用户确认 V1-B 要扩大周期。
- 明确 `max_hold_bars_min = 5`、`max_hold_bars_max = 8` 或等价参数。
- 明确时间退出和止损、止盈、EMA21 失效、MACD 反向出场之间的优先级。

### P0-002：bar 级 stop / take profit 撮合假设仍不够可执行

文档明确普通入场和普通出场采用当前 bar 收盘确认、下一根 K 线开盘成交，这是正确方向。但 stop / take profit 仅说明若由 vn.py bar 级方式撮合，必须在报告中明确撮合假设，尚未定义足够的实现规则。

必须修复：

- 同一根 bar 同时触及止损和止盈时的优先级。
- 跳空开盘穿越止损或止盈时的成交价规则。
- stop 触发使用 high/low 的时点边界，以及是否允许当前持仓 bar 内触发。
- 手续费、滑点、最小变动价位如何影响 stop / take profit 的成交价。
- vn.py BacktestingEngine 的 stop order / limit order / market order 映射方式。

如果不先写清，后续代码可以跑，但不同实现会得到不同交易明细，无法作为 V1-B 验收口径。

### P0-003：信号到成交后的风险重算边界不完整

文档用 signal close 计算初始止损，并要求下一根成交后重新校验；同时 R 又要求基于实际 entry price 与 initial stop 计算。这个方向合理，但仍缺少硬边界。

必须修复：

- 下一根开盘价相对 signal close 大幅跳空时，何时跳过入场。
- “不合理接近止损价”的量化阈值。
- 入场成交价改变后，是否允许重新计算 initial stop，还是固定使用 signal bar stop。
- 若重新计算，是否构成使用下一根 bar 信息改变计划。
- 若不重新计算，风险超限时的拒单规则。

该问题直接影响单笔风险、仓位计算和回测可复盘性。

## P1：建议修复

### P1-001：EMA21 v0.1 参数偏多，存在过拟合入口

v0.1 同时包含 EMA21、MACD、ATR、R 倍止盈、EMA 偏离、成交量确认、日线方向过滤、风险比例、保证金约束等参数。多数参数已标注为工程默认 / 待样本外验证，这比伪装为课程原始规则要安全，但仍偏复杂。

建议：

- V1-B 第一版只保留最小参数集：EMA21、ATR 止损、固定持有 5-8 bar、日线方向过滤开关、单笔风险。
- MACD 零轴过滤、成交量确认、EMA 偏离阈值先作为实验开关，不作为默认验收口径。
- 每个新增过滤条件必须单独做消融对比，否则容易出现“过滤越多，样本内越好”的过拟合。

### P1-002：成交量确认缺少 `volume_ratio` 精确定义

入场条件要求 `volume_ratio >= volume_multiplier`，参数表也给出 `volume_window = 20` 和 `volume_multiplier = 1.2`，但没有定义 `volume_ratio` 的计算方式。

建议明确：

- 是否为 `current_volume / SMA(volume, volume_window)`。
- 当前 bar 成交量是否在 bar 收盘后才可用。
- 夜盘、半日、节假日、换月导致的成交量异常如何处理。
- 新合约早期成交量窗口不足时如何处理。

### P1-003：MACD 零轴过滤使用 `abs(DIF) <= ATR` 量纲不一致

文档已标注该规则为当前仓库草稿工程口径，并要求待验证。风险在于 DIF 是价格差序列的 EMA 差，ATR 是价格波动范围，二者虽然都是价格量纲，但统计含义不同，跨品种、跨周期稳定性存疑。

建议：

- v0.1 默认关闭该过滤，或改为只记录字段。
- 若启用，必须做样本外验证和按品种归一化对比。

### P1-004：主观经验与可量化规则整体区分良好，但仍需实现层硬隔离

Rulebook 明确将执行纪律、交易心理、案例、口诀、抄底摸顶等放入人工复核或复盘标签；Review Tags 也说明标签只解释完成交易，不生成新交易。这一点合格。

建议在实现前再补一条硬约束：

- `review_tag_candidates` 只能写入交易明细或复盘 note。
- 任何 `TAG-*`、人工复核结论、复盘结论不得进入当时的 `on_bar` 信号判断。

### P1-005：样本内 / 样本外拆分规则还不够具体

文档要求参数研究、验证和最终验收数据分离，也要求参数版本和数据范围入库，这是正确的。但 V1-B 要做 JM 最近 3 年数据，仍需要具体切分口径。

建议明确：

- train / validation / final acceptance 的日期区间。
- 参数冻结时间。
- 是否允许滚动窗口验证。
- 多周期、多参数对比的选择标准。

### P1-006：数据口径需要落到 V1-B 的 primary 数据过滤条件

文档写到 RQData / local standard parquet、数据质量不为 failed、禁止未来主力映射和未来交易参数，方向正确。

建议补齐：

- 默认只读取 `data_role = primary`。
- 默认只读取 `source in (rqdata, local_parquet)`。
- 排除 legacy_reference 和 validation source。
- 主力映射、复权因子、手续费、保证金、合约乘数都必须按历史交易日生效。

## P2：后续优化

### P2-001：未发现课程内容大段复制，但可增加来源合规检查说明

本轮审查的文档以短摘要、规则候选、标签和工程规格为主；当前私人仓库口径允许私有源作为本地或仓库内源材料存在，但 `SOURCE_INDEX.md`、Rulebook、Quant Spec、Review Tags 仍只应保存短摘要、抽象分类、规则候选和复盘标签，不复制课程原文、私有 Notion 长段内容或截图。

后续可以增加一个小节，说明每次更新苏冰资料时只允许写入：

- source_id
- 短摘要
- 抽象规则候选
- quantizable 状态
- needs_manual_review 状态

### P2-002：Source Index 可补充提取证据字段

当前 `SOURCE_INDEX.md` 能说明资料来源和量化状态，但不能直接审计每条 Rulebook 规则是否只来自摘要。

后续可补充：

- `extraction_method`
- `contains_verbatim_quote = false`
- `manual_review_required`
- `last_reviewed_at`

### P2-003：Review Tags 可增加字段命名建议

Review Tags 已经适合作为复盘 note 标签体系。后续实现前可补充字段命名，方便交易明细入库和 Web 展示。

建议字段：

- `tag_code`
- `tag_category`
- `tag_severity`
- `tag_source`
- `is_post_trade_only`
- `can_affect_future_version`

## 十项审查结果

1. 是否有课程内容被大段复制进仓库：未发现。
2. 是否混淆了主观经验和可量化规则：整体未混淆，但实现层需硬隔离复盘标签和信号生成。
3. 是否有未来函数风险：文档原则正确；stop / take profit bar 级撮合细节不足，存在实现风险。
4. 是否有数据泄露风险：文档原则正确；样本拆分、参数冻结和数据角色过滤需补具体口径。
5. 是否有过拟合风险：有。主要来自 v0.1 工程默认参数和过滤条件偏多。
6. EMA21 v0.1 是否过度复杂：对 V1-B 第一版而言偏复杂。
7. 是否存在无法回测的规则：Rulebook 中回调、突破、口诀、案例、心理纪律等已标为待复核或不可量化；v0.1 本体多数可回测，但成交和短持有规则需补齐。
8. 是否明确 V1 不做实盘：明确。
9. 是否能指导 vn.py 策略实现：方向上能，但 P0 成交、周期和持有期问题修复前不应进入代码实现。
10. 是否有缺失的参数、边界和成交假设：有，集中在 5m、5-8 bar 持有、stop / take profit 优先级、跳空处理、风险重算、volume_ratio。

## 是否允许进入策略代码实现

No。

原因：存在 P0-001、P0-002、P0-003。修复后可以再次审查，若 P0 清零，再进入 vn.py `CtaTemplate` 策略实现。
