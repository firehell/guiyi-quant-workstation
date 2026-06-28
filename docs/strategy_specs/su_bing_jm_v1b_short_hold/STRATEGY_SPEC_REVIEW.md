# STRATEGY_SPEC_REVIEW

## 1. 总体结论

- 审查对象：`docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_SPEC.md`
- 审查日期：`2026-06-28`
- 审查角色：策略规格审查 Agent
- 是否允许进入代码实现：No

总体判断：

- 该 Strategy Spec 明确声明为新的独立规格，未发现把旧 `su_bing_ema21` 作为默认策略、默认参数、默认周期、默认成交假设或默认实现目标的证据。
- 该 Strategy Spec 的来源边界基本符合 `su-bing-strategy` Skill：Rulebook 中的 `RULE-001` 至 `RULE-014` 被用作规则候选，`RULE-015` 至 `RULE-018` 被限制在人工复核、复盘和拒绝信号解释范围，Review Tags 被限制为事后诊断。
- 未来函数和数据泄露边界写得较清楚：日线方向使用已确认日线，小周期信号使用已收盘 bar，入场信号与成交时点分离，Review Tags 不得反向影响同一笔交易。
- 成交假设、同 bar 止损止盈冲突、跳空成交、手续费、合约乘数、保证金和 `price_tick` 的方向基本明确。
- 但当前规格仍保留多个会直接影响信号、出场、成本、仓位和风控验收的 `requires_spec_decision` / `requires_user_decision`，因此还不是一个可直接编码、可直接回测的闭合 Strategy Spec。

13 项审查结论：

| 审查项 | 结论 |
|---|---|
| 是否错误继承旧 `su_bing_ema21` | 未发现错误继承 |
| 是否真实来自 `su-bing-strategy` Skill | 基本通过 |
| 是否可回测 | 暂不通过，需补齐 P0/P1 项 |
| 是否存在未来函数 | 规格层未发现明确未来函数，但实现前需补齐未定义 lookback / threshold |
| 是否存在数据泄露 | 规格层未发现明确泄露，但需严格执行标签后写和左闭历史窗口 |
| 是否存在过拟合风险 | 存在，需要参数冻结、时间切分和样本外验证 |
| 成交假设是否明确 | 基本明确 |
| stop / take profit / time exit 优先级是否明确 | 明确 |
| 同 bar 触及止损止盈是否明确 | 明确，止损优先 |
| 跳空成交是否明确 | 基本明确 |
| 手续费、滑点、`price_tick` 是否明确 | 部分明确，滑点仍未最终定稿 |
| review tags 是否只用于事后复盘 | 明确 |
| 是否允许进入 vn.py 策略实现 | No |

## 2. P0 问题

### P0-1：入场规则仍未闭合，不能直接实现

`entry_logic` 已经定义信号 bar、成交 bar、日线过滤、EMA21 背景和回调 / 突破 / 跌破候选，但以下核心触发条件仍为 `requires_spec_decision`：

- `pullback distance threshold`
- `local resistance lookback`
- `local support lookback`
- `volume confirmation`

这些字段决定是否产生入场信号。若不先固化，后续实现者只能自行补参数，容易重新引入旧策略默认值、主观补造或过拟合。

结论：当前 Spec 不可直接进入 vn.py 策略实现。

### P0-2：止损方案仍未闭合，无法形成可验收风险模型

规格要求每笔交易必须在入场前定义止损，并给出两个候选方向：信号 bar 高低点外一个 `price_tick`，或最近已完成 swing 高低点。但以下字段仍未决：

- `swing lookback bars`
- `maximum stop distance`
- `ATR-based stop alternative`

止损距离会影响是否开仓、仓位大小、初始风险、R 倍数止盈、回撤统计和同 bar 冲突判断。未闭合前不能写成正式策略。

结论：必须先选择唯一默认止损模型，其他模型只能作为后续版本候选。

### P0-3：仓位和账户风险输入未闭合，回测资金曲线不可验收

`position_sizing` 选择了 `risk_per_trade`，但以下关键输入仍是 `requires_user_decision`：

- `account_equity_source`
- `risk_per_trade_ratio`
- `maximum_position`

这会直接影响手数、保证金占用、最大回撤、最大连续亏损和收益曲线。没有这些输入，回测可以产生信号，但不能产生可验收的资金曲线。

结论：实现前必须固化账户权益来源、单笔风险比例、最大手数和保证金拒绝规则。

### P0-4：滑点仍为候选，正式回测成本模型未闭合

规格禁止手续费和滑点默认为 0，并给出滑点候选 `1 * price_tick` per side，但状态仍是 `requires_spec_decision before implementation`。

滑点是 V1-B 回测验收基础字段。未明确前，不应进入正式 vn.py 实现。

结论：必须在 Spec 中把滑点从候选变为正式假设，或明确按合约 / 时段读取标准参数。

## 3. P1 问题

### P1-1：止盈启用状态和 R 倍数未闭合

`take_profit_mode` 写为 `optional_fixed_r_multiple`，但 `default_status` 与 `candidate_r_multiple` 仍为 `requires_spec_decision`。

虽然出场优先级已经明确为 stop loss -> take profit -> signal failure -> time exit，但止盈是否启用会显著改变收益分布、持有时间和同 bar 冲突频率。

建议：实现前明确 `take_profit_enabled = true/false`；如启用，固定 `r_multiple`，并把任何后续调整列为新参数版本。

### P1-2：time exit 的 5-8 根 bar 规则仍存在执行歧义

规格明确最早 5 根、最晚 8 根，并规定下一根 open 成交；但默认使用第 5 根、第 8 根，还是 5 到 8 之间的内部条件，仍为 `requires_spec_decision`。

建议：V1-B 第一版应选择一个最简单、可复现的默认规则，例如固定第 8 根强制退出，或固定第 5 根计划退出；不要在未审查条件下加入区间内择时逻辑。

### P1-3：日内交易时段、夜盘和跨交易日口径未闭合

`risk_control` 把 `Session filter / night-session handling` 标记为 `requires_spec_decision`。JM 是包含夜盘的国内期货品种，5m / 15m 短持有策略会受到夜盘、日盘开盘跳空、交易日归属和日线确认时点影响。

建议：实现前明确：

- 夜盘是否参与入场和出场。
- 交易日 `D` 的归属口径。
- 日线 `D-1` 在夜盘中何时可用。
- 休市后下一根 bar open 的成交处理。

### P1-4：主力映射、换月和复权记录要求明确，但验收口径还需落为实现前边界

规格要求不得直接交易抽象连续合约，主力连续只能用于确定时点对应的具体合约，并要求换月、主力切换和复权处理显式记录。方向正确。

风险在于：如果后续实现只读取连续合约 OHLC，却没有把成交落到具体合约和交易参数上，会造成价格、手续费、乘数、保证金和 `price_tick` 错配。

建议：实现前要求每笔交易输出具体合约、主力映射版本、合约乘数、`price_tick`、手续费规则和保证金率。

### P1-5：过拟合风险仍然较高

当前策略限定 JM、近 3 年、15m / 5m、5-8 根短持有，并保留多个参数未决。虽然 Spec 已经禁止全样本优化作为最终验收，并要求时间切分、敏感性检查和保留失败变体，但在参数尚未冻结前，仍存在通过反复调整阈值适配单一品种三年样本的风险。

建议：先冻结 v0.1 参数，再跑初版回测；后续优化必须形成新参数版本，不得把全样本最优结果直接作为 V1-B 验收。

## 4. P2 问题

### P2-1：来源声明通过，但建议补充每个 current-spec decision 的来源类型

规格已经区分 Skill、Rulebook、Review Tags、Target 和 current-spec decisions。建议后续版本进一步标注：

- `course_candidate`
- `target_decision`
- `current_spec_assumption`
- `user_decision`
- `implementation_metadata`

这样能避免把 JM、3 年、5-8 根、bar execution 等项目假设误认为课程原始规则。

### P2-2：Review Tags 禁用语句有重复

`review_tags_mapping` 中“不允许 review tags 反向影响当时交易决策”和“不允许 Review Tags 反向影响当时交易决策”重复。不是实现阻塞项，但后续清理文档时可以合并。

### P2-3：MACD 当前只写为辅助确认字段，后续需避免暗中变成触发器

Spec 已说明 MACD 不能单独触发入场，符合 Rulebook 边界。实现前需要进一步明确 MACD 字段是记录、过滤还是可选确认；若作为过滤条件，需要独立参数版本和审查。

### P2-4：震荡过滤和交易频率仍停留在规则候选

Rulebook 中震荡识别、降频、交易频率属于待补充或部分可量化内容。当前 Spec 没有把它们变成入场硬条件，这是安全的；但后续报告解释亏损时不能事后声称“震荡应过滤”而回写同一版信号逻辑。

## 5. 必须修复项

进入实现前，必须完成以下修复：

1. 固化入场触发：
   - 回调距离阈值。
   - 突破 / 跌破 lookback。
   - 量能确认是否启用；如启用，明确计算窗口和阈值。

2. 固化止损：
   - 选择默认止损模型。
   - 明确 swing lookback 或明确不用 swing。
   - 明确最大止损距离。
   - 明确 ATR 止损是否启用；如不启用，应写明禁用。

3. 固化止盈：
   - 明确是否启用 take profit。
   - 如启用，明确 R 倍数。
   - 如不启用，明确只使用止损、信号失败和时间退出。

4. 固化 time exit：
   - 明确第 5 根、第 8 根，或 5-8 根之间的唯一可观察退出条件。
   - 不允许把事后收益表现作为区间内退出依据。

5. 固化成本和交易参数：
   - `price_tick` 来源。
   - 合约乘数来源。
   - 手续费字段和计算方式。
   - 保证金率来源。
   - 滑点正式假设。

6. 固化资金和仓位：
   - 账户权益来源。
   - 单笔风险比例。
   - 最大手数。
   - 保证金不足时拒绝规则。

7. 固化交易时段：
   - 夜盘是否参与。
   - 日线确认与夜盘的对齐方式。
   - 跨交易日和节假日后下一根 bar 的成交处理。

8. 补充实现验收清单：
   - 15m 与 5m 完全独立回测。
   - 信号 t 收盘、成交 t+1 open。
   - 日线只用 `D-1` 或更早确认日线。
   - 每笔交易可追溯到具体合约和交易参数。
   - Review Tags 只在交易完成后写入。

## 6. 实现前边界

允许作为后续实现输入的内容：

- `strategy_code = su_bing_jm_v1b_short_hold`
- V1-B、JM、近 3 年真实 RQData / local standard parquet。
- `data_role = primary` 且 `quality_status = passed`。
- 1d 只做方向过滤，15m / 5m 独立入场链路。
- 日线方向只使用已确认日线。
- 当前小周期 bar 收盘确认信号，下一根同周期 bar open 成交。
- 市价下一根开盘成交模型。
- 同 bar 止损止盈冲突采用止损优先。
- 跳空按下一根 open 加滑点成交，并记录 `gap_execution = true`。
- Review Tags 只用于事后复盘、交易明细、K线复盘、复盘 note 或未来版本审查。
- V1-B 不做实盘、不自动下单、不接 CTP / TqSdk 交易接口。

禁止作为后续实现输入的内容：

- 旧 `su_bing_ema21` 的参数、周期、路径、成交假设或测试默认值。
- 旧 `SU_BING_QUANT_SPEC_V0_1.md` 的工程默认参数。
- 当前仍标记为 `requires_spec_decision` / `requires_user_decision` 的字段。
- `RULE-015` 至 `RULE-018` 的心理、纪律、案例、口诀、抄底摸顶内容作为入场、出场、过滤、加仓、减仓或反手条件。
- `TAG-*`、复盘 note、人工复核结论、交易结果、MFE、MAE、最终 PnL 反向影响同一笔交易信号。
- 把连续合约直接当成可交易合约。
- 手续费或滑点默认为 0。

当前是否允许进入 vn.py 策略实现：

- No。
- 只有在“必须修复项”全部补齐并形成新的可审查 Spec 版本后，才建议进入 vn.py CtaTemplate / Adapter / Runner / ResultConverter 的实现任务。

## 7. 建议下一步

1. 先创建 `v0.1.1-spec` 或同等修订版，只修 Strategy Spec 的未决参数和实现前边界，不写代码。
2. 修订版中把所有 `requires_spec_decision` 和 `requires_user_decision` 列成表格，并逐项给出最终值、来源类型和是否允许优化。
3. 对修订版再做一次轻量 Spec Review，重点检查：
   - 入场触发是否闭合。
   - 止损 / 止盈 / 时间退出是否闭合。
   - 滑点、手续费、`price_tick`、合约乘数、保证金是否闭合。
   - 是否仍未继承旧 `su_bing_ema21`。
4. 审查通过后，再另开实现任务，并由用户明确允许修改的代码文件范围。
5. 首次回测只跑冻结参数版本，报告失败变体和 rejected signal，不做全样本参数寻优后直接验收。
