# STRATEGY_SPEC_REVIEW

## 1. 总体结论

- 审查对象：`docs/strategy_specs/su_bing_jm_v1b_short_hold/STRATEGY_SPEC.md`
- 审查版本：`v0.1.1-spec`
- 审查日期：`2026-06-28`
- 审查类型：轻量复审
- 是否允许进入代码实现：Yes, only as a separate explicitly authorized vn.py implementation task

总体判断：

- `v0.1.1-spec` 已将上一轮 P0/P1 未决项收束为冻结参数版本。
- 未发现错误继承旧 `su_bing_ema21`、旧 `SU_BING_QUANT_SPEC_V0_1.md`、旧代码、旧测试或旧成交假设。
- 规则来源仍符合 `su-bing-strategy` Skill：Rulebook 只作为规则候选，Review Tags 只作为事后复盘诊断。
- 当前版本已经具备进入 vn.py 策略实现任务的规格条件，但本 Review 本身不授权直接改代码；后续必须另开实现任务并明确允许修改文件范围。

13 项轻量复审结论：

| 审查项 | 结论 |
|---|---|
| 是否错误继承旧 `su_bing_ema21` | 通过，未发现错误继承 |
| 是否真实来自 `su-bing-strategy` Skill | 通过 |
| 是否可回测 | 通过，基于冻结 v0.1.1 参数可实现 bar 级回测 |
| 是否存在未来函数 | 规格层通过，实现需用已完成 bar 和 `D-1` 日线 |
| 是否存在数据泄露 | 规格层通过，Review Tags / notes 不参与同笔信号 |
| 是否存在过拟合风险 | 可控，参数已冻结，但回测后不得全样本寻优验收 |
| 成交假设是否明确 | 通过，t 收盘出信号，t+1 open 加滑点成交 |
| stop / take profit / time exit 优先级是否明确 | 通过，stop -> take profit -> signal failure -> time exit |
| 同 bar 触及止损止盈是否明确 | 通过，止损优先 |
| 跳空成交是否明确 | 通过，按下一根 open 加滑点成交并记录 gap |
| 手续费、滑点、`price_tick` 是否明确 | 通过，缺交易参数 fail fast，滑点固定 1 tick per side |
| review tags 是否只用于事后复盘 | 通过 |
| 是否允许进入 vn.py 策略实现 | 通过，但必须另开实现任务 |

## 2. P0 问题

无 P0 阻塞项。

上一轮 P0 已处理：

- 入场规则：已收束为 `pullback_only`，突破 / 跌破 / 量能确认禁用于 v0.1.1。
- 止损规则：已固定为 signal bar extreme plus `1 * price_tick`，最大止损距离 `30 * price_tick`。
- 仓位规则：已固定初始资金、单笔风险比例和最大 1 手。
- 成本规则：已固定滑点 `1 * price_tick` per side，手续费、乘数、保证金、`price_tick` 缺失时 fail fast。

## 3. P1 问题

无 P1 阻塞项。

实现任务中必须特别保持以下边界：

- 不得把 v0.1.1 禁用的突破 / 跌破 / 量能确认 / MACD 过滤暗中加入信号。
- 不得调整 `1.5R` 止盈、8 根 bar 时间退出、0.5% 单笔风险或最大 1 手；任何调整必须先形成新参数版本。
- 不得直接交易连续合约；每笔交易必须落到具体 JM 合约和对应交易参数。
- 不得把回测结果、MFE、MAE、PnL、Review Tags 或复盘 note 回写到同一版本信号逻辑。

## 4. P2 问题

- v0.1.1 的多个数值参数属于 `current_spec_assumption`，不是课程原文规则。后续报告和实现注释必须保持这个来源边界。
- 初始版本最大 1 手较保守，可能导致收益曲线弹性较低，但适合第一版验收未来函数、成本和复盘链路。
- `pullback_only` 会放弃突破 / 跌破候选，属于有意降维；后续如要启用，必须另开 `v0.1.2-spec` 或参数版本。

## 5. 必须修复项

进入单独 vn.py 实现任务前，无需继续修复 Strategy Spec。

实现任务启动前必须确认：

- 用户明确允许修改的代码文件范围。
- 本地数据湖存在 JM 最近 3 年 `primary` / `passed` 数据。
- 合约元数据具备 `price_tick`、`contract_multiplier`、`commission_rule`、`margin_rate`。
- vn.py Adapter / Runner / ResultConverter 的改动范围单独列出。

## 6. 实现前边界

允许进入实现的规格输入：

- `strategy_version = v0.1.1-spec`
- JM，RQData / local standard parquet，`data_role = primary`，`quality_status = passed`
- 1d 日线方向过滤，15m / 5m 独立链路
- `pullback_only`
- MACD `record_only_not_filter`
- 信号 bar `t` 收盘确认，下一根同周期 bar `t+1` open 成交
- 止损：signal bar extreme plus `1 * price_tick`
- 止盈：`1.5R`
- 时间退出：第 8 根 completed holding bar
- 同 bar 冲突：止损优先
- 跳空：下一根 open 加滑点并记录 `gap_execution = true`
- 滑点：`1 * price_tick` per side
- 初始资金：`1_000_000 CNY`
- 单笔风险：`0.5%`
- 最大仓位：`1` contract
- 每交易日每周期最多 `2` 次入场
- Review Tags 只用于事后复盘

禁止进入实现的内容：

- 旧 `su_bing_ema21` 默认参数、路径、周期、成交假设或测试默认值。
- 旧 `SU_BING_QUANT_SPEC_V0_1.md` 工程默认值。
- 突破 / 跌破 / 量能确认作为 v0.1.1 入场条件。
- MACD 作为 v0.1.1 入场过滤或触发条件。
- `RULE-015` 至 `RULE-018` 的心理、纪律、案例、口诀、抄底摸顶内容作为交易信号。
- `TAG-*`、复盘 note、人工复核结论、交易结果、MFE、MAE、最终 PnL 反向影响同一笔交易。
- 手续费、滑点、合约乘数、保证金或 `price_tick` 缺失时继续回测。
- V1-B 实盘、自动下单、CTP / TqSdk 交易接口。

## 7. 建议下一步

1. 另开 vn.py 实现任务。
2. 实现任务先声明允许修改文件，再写代码。
3. 第一版只实现 `v0.1.1-spec` 冻结参数，不做参数优化。
4. 首次回测输出 15m 和 5m 独立报告、交易明细、K线买卖点和 rejected signal。
5. 回测后再做外部审查，重点查未来函数、数据泄露、成本、换月、成交时点和复盘可追溯性。
