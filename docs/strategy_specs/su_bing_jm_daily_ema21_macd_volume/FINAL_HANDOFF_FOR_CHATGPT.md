# FINAL_HANDOFF_FOR_CHATGPT

> 生成日期：2026-06-30  
> 当前分支：`feature/su-bing-daily-v03-control`  
> 目标：给 ChatGPT 做苏冰 JM 日线策略下一步深度分析使用。  
> 边界：本文件是总控交接文档，不新增策略、不调整参数、不跑新回测实验、不修改 Web / migration / 实盘逻辑。

## 1. 总控执行摘要

| 阶段 | status | evidence | key_findings | remaining_risk |
|---|---|---|---|---|
| 阶段 0：总控计划 | done | `tasks/current.md` | 已在功能分支 `feature/su-bing-daily-v03-control` 上记录总控任务、允许范围、Gate 和验收标准。 | 本文件生成后仍建议做 checkpoint。 |
| 阶段 1：holding_bars / 基础可信度修复 | done | `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/vnpy_strategy.py`; `scripts/export_su_bing_report_10_review_package.py`; `backtests/reports/report_10_su_bing_daily_trade_review.csv` | 新的 internal strategy trade 会写入 `holding_bars`、`holding_trading_days`、`holding_calendar_days`；旧 report 10 导出新增 `holding_bars_persisted_value`、`holding_bars_current_value`、`holding_trading_days`。 | report_id=10 数据库原始持久化值仍是 0；当前用导出层修正为可复盘口径。 |
| 阶段 2：主连换月与跨合约 PnL 审查 | done | `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_ROLLOVER_AUDIT.md` | SB-JM-D-3 是 `JM2405 -> JM2409` 跨合约交易，当前 PnL 标记为 `untrusted_cross_contract_pnl`。 | P0 未关闭；不能用 report_id=10 做参数优化或收益排名。 |
| 阶段 3：苏冰 Skill 规则提取与对齐 | done | `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/SU_BING_SKILL_RULES_EXTRACT.md`; `SKILL_ALIGNMENT_REVIEW.md` | 找到结构化 Skill / Rulebook / Review Tags 文件；本轮只提取规则候选，不复制课程原文，不编造阈值。 | 当前代码只匹配部分规则候选，缺追价、震荡、止损、浮盈保护等。 |
| 阶段 4：report_id=10 逐笔场景分类 | done | `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_SKILL_TRADE_CLASSIFICATION.md`; `V0_2_BASELINE_FINDINGS.md` | 7 笔交易已分类；SB-JM-D-7 是明显 chase_entry，SB-JM-D-2 是 immediate_failure，SB-JM-D-3 是 cross_contract_review。 | 7 笔样本只能做复盘归因，不能做参数优化。 |
| 阶段 5：条件消融矩阵 | partial | `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/CONDITION_ABLATION_PLAN.md` | 已输出消融矩阵计划 A-J 和指标要求。 | 未执行消融实验；因为 rollover P0 未解，只能做计划或信号数量分析。 |
| 阶段 6：v0.3 设计 | done | `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_3_DAILY_STRATEGY_DESIGN.md` | 已设计 `v0.3.0-daily`：rollover trust、EMA21 slope/distance、MACD tier、volume scoring、ATR stop、fast-fail、可选浮盈保护。 | 只是设计，未实现；需先关闭 P0。 |
| 阶段 7：v0.3 实现或实现条件判断 | blocked | `tasks/current.md`; `V0_3_DAILY_STRATEGY_DESIGN.md` | 已判断不满足实现条件：SB-JM-D-3 跨合约 PnL 仍不可信，没有日线 rollover-safe 新报告。 | 不应进入 v0.3 实现，除非先做 rollover-safe 或明确排除跨合约 PnL 后重跑报告。 |

## 2. 当前 git 状态

- 当前分支：`feature/su-bing-daily-v03-control`
- 创建本文件前 `git status --short`：干净。
- 本文件创建后预期状态：新增 `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/FINAL_HANDOFF_FOR_CHATGPT.md` 未提交。
- 是否有未提交修改：创建本文件后有 1 个未提交文档文件。
- 建议是否 checkpoint：建议。该文档是给 ChatGPT 的交接材料，建议由用户或 Cursor 检查后提交。
- 最近 commit：
  - `a1f3ad571df2e88b69cad8f0bd6deeec9036270a`，subject: `修复`，date: `2026-06-29 23:55:46 +0800`
- 最近 commit 文件列表：
  - Added: `CONDITION_ABLATION_PLAN.md`
  - Added: `REPORT_10_ROLLOVER_AUDIT.md`
  - Added: `REPORT_10_SKILL_TRADE_CLASSIFICATION.md`
  - Modified: `REPORT_10_TRUST_AUDIT.md`
  - Added: `SKILL_ALIGNMENT_REVIEW.md`
  - Added: `SU_BING_SKILL_RULES_EXTRACT.md`
  - Added: `V0_2_BASELINE_FINDINGS.md`
  - Added: `V0_3_DAILY_STRATEGY_DESIGN.md`
  - Modified: `packages/quant-core/.../vnpy_strategy.py`
  - Modified: `scripts/export_su_bing_report_10_review_package.py`
  - Modified: `services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py`
  - Modified: `services/quant-api/tests/test_su_bing_report_10_review_export.py`
  - Modified: `tasks/current.md`

## 3. v0.2.0 baseline 状态

| 检查项 | 结果 |
|---|---|
| `su_bing_jm_daily_ema21_macd_volume / v0.2.0-daily` 是否保持不变 | 交易行为保持不变；只补 internal trade duration 字段。 |
| 是否修改默认参数 | 否。未修改 `default_params.json`。 |
| 是否修改入场逻辑 | 否。仍是 close vs EMA21 + MACD near-zero cross + volume expansion。 |
| 是否修改离场逻辑 | 否。仍是 opposite-side EMA21 close 后下一日开盘退出。 |
| 是否修改 MACD 阈值 | 否。仍是 `abs(DIF) <= 25 and abs(DEA) <= 25`。 |
| 是否修改成交量规则 | 否。仍是 `current_volume > previous_volume`。 |
| 是否修改 EMA21 逻辑 | 否。未引入 slope、distance、pullback、breakout、reclaim。 |
| 是否影响 report_id=10 可比性 | 不影响交易信号、开平仓、PnL 可比性；导出口径新增可复盘字段。 |

行为变化说明：

- 未来新跑出的 internal `strategy_trades` 会多出 `holding_bars`、`holding_trading_days`、`holding_calendar_days` 字段。
- 这不是策略信号变化，也不改变 report_id=10 的交易价格、方向、开平时间、PnL、手续费、滑点或合约标签。

## 4. P0/P1/P2 问题清单

### P0

| 问题 | status | evidence_file | impact | recommended_next_action |
|---|---|---|---|---|
| holding_bars 持久化问题 | partially_resolved | `report_10_su_bing_daily_trade_review.csv`; `REPORT_10_TRUST_AUDIT.md` | 旧 DB report 仍是 0，但导出已提供 `holding_bars_current_value` 和 `holding_trading_days`。 | 后续新 report 应重新持久化真实 `holding_bars`；旧 report 保留为历史缺口。 |
| 跨合约 PnL / rollover 问题 | unresolved | `REPORT_10_ROLLOVER_AUDIT.md` | SB-JM-D-3 的 `+4060.38` 不能用于优化或收益判断。 | 先做 `v0.2.1-daily-rollover-safe` 或明确 cross-contract exclusion 后重跑。 |
| 主连换月强制平仓问题 | unresolved | `REPORT_10_ROLLOVER_AUDIT.md` | daily v0.2 无 forced rollover exit，跨合约持仓可能污染 PnL。 | 复用 V1-B forced-exit 思路，但必须新版本/新任务，不改 v0.2 baseline。 |
| MFE/MAE/R 单位导出问题 | partially_resolved | `report_10_su_bing_daily_trade_review.csv` | MFE/MAE 已导出；R 因 v0.2 无止损仍为空。 | v0.3 若引入 ATR stop，再计算 R。 |
| report_id=10 是否可用于参数优化 | unresolved | `V0_2_BASELINE_FINDINGS.md`; `REPORT_10_TRUST_AUDIT.md` | 不可直接优化：7 笔样本、1 笔跨合约、无样本外。 | 只用于规则对齐和逐笔复盘；先修 rollover。 |

### P1

| 问题 | status | evidence_file | impact | recommended_next_action |
|---|---|---|---|---|
| 追高/杀跌过滤 | deferred | `SKILL_ALIGNMENT_REVIEW.md`; `REPORT_10_SKILL_TRADE_CLASSIFICATION.md` | SB-JM-D-7 显示明显追价风险。 | v0.3 设计中加入 `max_entry_ema_distance_atr`，实现前先审查。 |
| 震荡区过滤 | deferred | `V0_2_BASELINE_FINDINGS.md` | SB-JM-D-5 / D-6 可能是震荡或低质量趋势信号。 | 先定义 range/risk regime，避免用 7 笔样本调阈值。 |
| ATR 止损 | deferred | `V0_3_DAILY_STRATEGY_DESIGN.md` | v0.2 无止损，R 单位缺失。 | v0.3 实现前先确认 ATR stop 规则和优先级。 |
| 快速失败离场 | deferred | `REPORT_10_SKILL_TRADE_CLASSIFICATION.md` | SB-JM-D-2 次日失败，EMA 出场可能太慢。 | v0.3 设计为 `fast_fail_bars=3`，需测试确认只用过去 bar。 |
| 浮盈保护 | deferred | `V0_2_BASELINE_FINDINGS.md` | SB-JM-D-1 有较大 MFE 回吐。 | 先作为可选规则默认关闭，避免过拟合。 |
| MACD 零轴分层评分 | deferred | `SKILL_ALIGNMENT_REVIEW.md`; `V0_3_DAILY_STRATEGY_DESIGN.md` | 当前 `±25` 硬阈值可能过严且非 Skill 原始阈值。 | 设计 strong/medium/weak tier，消融验证前不定优。 |
| 成交量确认升级 | deferred | `SKILL_ALIGNMENT_REVIEW.md` | `current > previous` 太粗糙。 | 设计 volume scoring：prev / MA5 / MA20 ratio。 |
| EMA21 斜率/距离过滤 | deferred | `V0_3_DAILY_STRATEGY_DESIGN.md` | 当前只看 close 与 EMA21 位置，不识别趋势质量和追价。 | v0.3 设计后由 ChatGPT 先审查。 |

### P2

| 问题 | status | evidence_file | impact | recommended_next_action |
|---|---|---|---|---|
| 多品种验证 | deferred | `CONDITION_ABLATION_PLAN.md` | 只看 JM 容易过拟合。 | P0 解决后再考虑，不作为下一轮主方向。 |
| 多年份验证 | deferred | `V0_3_DAILY_STRATEGY_DESIGN.md` | 当前样本少，无法证明稳定性。 | 先做 rollover-safe，再做时间切分。 |
| 日线方向 + 5m/15m 入场 | deferred | `CONDITION_ABLATION_PLAN.md` | V1-B 原目标包含分钟入场，但本轮是日线策略收口。 | 等日线可信度修复后再回到分钟入场。 |
| 多空分开统计 | deferred | `V0_2_BASELINE_FINDINGS.md` | 当前 7 笔不足以判断多空差异。 | 后续报告加多空拆分。 |
| 参数稳定性分析 | deferred | `CONDITION_ABLATION_PLAN.md` | 当前不能做参数优化。 | P0 解决 + 样本外后再做。 |

## 5. 苏冰 Skill 规则对齐结果

找到的结构化 Skill / 规则文件：

- `docs/strategy_knowledge/su_bing/SU_BING_SKILL.md`
- `docs/strategy_knowledge/su_bing/SU_BING_RULEBOOK.md`
- `docs/strategy_knowledge/su_bing/SU_BING_REVIEW_TAGS.md`

重要边界：

- 仓库中找到的是结构化 Skill / Rulebook / Review Tags，不是可以复制的课程原文。
- 本轮不复制课程原文、不复制私有 Notion 内容、不复制截图或案例原文。
- 本轮基于 `current_code_rule + report_id=10 + structured Rulebook` 做结构化对齐。

核心规则摘要：

- EMA21 是趋势/背景线候选，不应单独作为买卖触发。
- MACD 是辅助确认候选，不应脱离趋势、EMA、过滤条件独立触发。
- 量能可以做确认或观察项，但 Rulebook 未给出 `current > previous` 这种硬规则。
- 突破、回踩、收回 EMA21 是 setup 候选，需确认 bar 和失败条件。
- 止损、仓位、风险应在开仓前定义。
- Review Tags 是交易后诊断，不能进入同一时点 `on_bar` 信号逻辑。

当前代码匹配度：

- matched：多空对称、Review Tags 不参与信号。
- partially_matched：趋势方向、EMA21 位置、MACD cross、入场触发、持仓和 EMA21 失败退出。
- missing_in_code：突破/回踩/收回 EMA21、追高/杀跌过滤、震荡过滤、止损、浮盈保护、信号强弱评分。
- code_too_strict：MACD `±25`、成交量 `current > previous`。
- code_too_loose：风险前置不足，没有止损、没有 ATR 距离过滤。

建议进入 v0.3 的规则：

- EMA21 slope / ATR distance filter
- MACD tier scoring
- volume scoring
- ATR initial stop
- fast-fail exit
- forced rollover exit / cross-contract exclusion
- optional profit protection, default off

对应文件：

- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/SU_BING_SKILL_RULES_EXTRACT.md`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/SKILL_ALIGNMENT_REVIEW.md`
- `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_SKILL_TRADE_CLASSIFICATION.md`

## 6. report_id=10 复盘结论

基础指标：

| 字段 | 值 |
|---|---:|
| report_id | 10 |
| task_id | 17 |
| strategy_code | `su_bing_jm_daily_ema21_macd_volume` |
| strategy_version | `v0.2.0-daily` |
| trade_count | 7 |
| net_pnl | 9356.616 |
| max_drawdown | 0.08286568323387682 |
| max_drawdown_amount | 9880.680000000008 |
| max_consecutive_losses | 3 |
| cross_contract_trades | 1 |
| strategy_execution_events | 14 |
| rejected_signals | 476 |
| win_rate | 0.42857142857142855 |
| profit_loss_ratio | 2.1817815804908203 |

逐笔摘要：

| trade_id | direction | net_pnl | status | scene_type | issue_reason | suggested_action |
|---|---|---:|---|---|---|---|
| SB-JM-D-1 | long | 12550.461 | traceable_same_contract | trend_continuation | Large MFE `24960` vs realized net `12550.461`; held 28 bars. | Keep as valid trend example; review profit protection. |
| SB-JM-D-2 | long | -4823.208 | traceable_same_contract | immediate_failure | Exit after 1 holding bar; MFE `-30`, MAE `-7710`. | Design ATR stop and fast-fail exit. |
| SB-JM-D-3 | short | 4060.38 | cross_contract_needs_review | cross_contract_review | `JM2405 -> JM2409`; PnL is `untrusted_cross_contract_pnl`. | Exclude from optimization until rollover-safe report exists. |
| SB-JM-D-4 | short | 7449.663 | traceable_same_contract | standard_trend | Cleanest baseline trend case; low adverse excursion. | Use as positive review case, not parameter target. |
| SB-JM-D-5 | short | -1933.308 | traceable_same_contract | range_whipsaw | Short fails within 5 bars; small MFE and larger MAE. | Design range filter and fast-fail exit. |
| SB-JM-D-6 | short | -1842.909 | traceable_same_contract | chase_entry | EMA distance about 1.66 ATR; MFE only `600`. | Add anti-chase filter candidate. |
| SB-JM-D-7 | long | -6104.463 | traceable_same_contract | chase_entry | EMA distance about 2.37 ATR; MFE only `180`, MAE `-8280`. | Strong candidate for ATR distance anti-chase filter. |

## 7. 条件消融矩阵结果

执行状态：未执行。

原因：

- `REPORT_10_ROLLOVER_AUDIT.md` 已确认 SB-JM-D-3 跨合约 PnL 当前不可信。
- `CONDITION_ABLATION_PLAN.md` 明确在 rollover-safe 或 cross-contract exclusion 之前，不应做收益结论。
- 本轮边界禁止继续跑新实验。

已完成内容：

- 已设计 A-J 条件消融矩阵，包括 baseline、rollover-safe、EMA21 only、MACD cross/no zero band、MACD zero/no fresh cross、volume variants、MACD ±50 + anti-chase、MACD ±25 + ATR anti-chase、日线方向 + 5m/15m 入场设计。

建议下一步：

- 先实现或设计 `B_v020_rollover_safe`。
- 若暂不实现 forced exit，则至少生成一个排除 cross-contract PnL 的对照报告。
- 消融输出必须包含 trade_count、net_pnl、max_drawdown、win_rate、profit_loss_ratio、max_consecutive_losses、cross_contract_trades。
- 不要直接选择收益最高者；重点看规则贡献、风险变化和样本外需求。

## 8. v0.3 设计状态

- 是否已输出 `V0_3_DAILY_STRATEGY_DESIGN.md`：是。
- 是否已实现 v0.3：否。
- 阻塞项：跨合约 PnL / rollover P0 未解决。

如果只设计未实现，当前实现前提：

1. 先解决 daily v0.2 的 rollover-safe 或明确排除 cross-contract PnL。
2. ChatGPT / 人工确认 `V0_3_DAILY_STRATEGY_DESIGN.md` 不过拟合 7 笔交易。
3. 确认 `SU_BING_SKILL_RULES_EXTRACT.md` 与 `SKILL_ALIGNMENT_REVIEW.md` 中的规则候选边界。
4. 明确 v0.3 的新增规则全部新版本化，不污染 `v0.2.0-daily`。

是否建议进入实现：暂不建议。建议先修 P0 可信度，再审查 v0.3 设计。

## 9. 新增/修改文件清单

### docs

| path | purpose | changed_or_added | risk_level |
|---|---|---|---|
| `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/FINAL_HANDOFF_FOR_CHATGPT.md` | 本交接文档 | added | low |
| `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_ROLLOVER_AUDIT.md` | 主连换月与跨合约 PnL 审查 | added | medium |
| `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/SU_BING_SKILL_RULES_EXTRACT.md` | 苏冰结构化规则候选提取 | added | low |
| `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/SKILL_ALIGNMENT_REVIEW.md` | 当前代码与 Skill 规则候选对齐 | added | low |
| `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_SKILL_TRADE_CLASSIFICATION.md` | 7 笔交易场景分类 | added | low |
| `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_2_BASELINE_FINDINGS.md` | v0.2 baseline 优缺点总结 | added | low |
| `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/CONDITION_ABLATION_PLAN.md` | 条件消融矩阵计划 | added | low |
| `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_3_DAILY_STRATEGY_DESIGN.md` | v0.3 设计 | added | medium |
| `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_TRUST_AUDIT.md` | report 10 可信度审查更新 | modified | low |

### scripts

| path | purpose | changed_or_added | risk_level |
|---|---|---|---|
| `scripts/export_su_bing_report_10_review_package.py` | report 10 导出，新增持仓周期字段和 trust audit 文案 | modified | low |

### strategy code

| path | purpose | changed_or_added | risk_level |
|---|---|---|---|
| `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/vnpy_strategy.py` | internal `strategy_trades` 增加 `holding_bars` / duration 字段 | modified | low |

### config/schema

| path | purpose | changed_or_added | risk_level |
|---|---|---|---|
| `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/default_params.json` | v0.2 默认参数 | unchanged | low |
| `packages/quant-core/guiyi_quant/strategies/su_bing_jm_daily_ema21_macd_volume/config_schema.py` | v0.2 参数校验 | unchanged | low |

### tests

| path | purpose | changed_or_added | risk_level |
|---|---|---|---|
| `services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py` | 验证策略输出持仓周期字段且不改出场逻辑 | modified | low |
| `services/quant-api/tests/test_su_bing_report_10_review_export.py` | 验证导出层 holding bars / trading days 口径 | modified | low |

### reports

| path | purpose | changed_or_added | risk_level |
|---|---|---|---|
| `backtests/reports/report_10_su_bing_daily_trade_review.csv` | report 10 交易复盘 CSV，新增 holding fields | generated/updated | low |
| `backtests/reports/report_10_su_bing_daily_trade_review.md` | report 10 交易复盘摘要 | generated/updated | low |
| `backtests/reports/report_10_trade_bar_context.csv` | 交易前后 K 线窗口 | generated/updated | low |
| `backtests/reports/report_10_signal_candidates.csv` | signal candidates | generated/updated | low |
| `backtests/reports/report_10_rejected_signals.csv` | rejected signals | generated/updated | low |
| `backtests/reports/report_10_signal_funnel.md` | signal funnel 摘要 | generated/updated | low |

### other

| path | purpose | changed_or_added | risk_level |
|---|---|---|---|
| `tasks/current.md` | 当前任务状态与验收记录 | modified | low |

## 10. 测试命令与测试结果

实际运行过的测试命令：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py
```

结果：`7 passed`

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_vnpy_integration.py
```

结果：`14 passed`

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_v1b_jm_fixed_backtest_tasks.py
```

结果：`13 passed`

补充运行：

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_report_10_review_export.py
```

结果：`4 passed`

```bash
uv run --project services/quant-api ruff check .
```

结果：`All checks passed!`

## 11. 当前是否可以进入下一轮真实策略优化

判断：必须先修 P0。

原因：

- SB-JM-D-3 跨合约 PnL 仍不可信。
- daily v0.2 没有 forced rollover exit。
- report_id=10 只有 7 笔交易，且 1 笔为 cross-contract review。
- v0.2 无止损，R 单位仍不可用。
- 条件消融矩阵未执行，只能作为计划。

可以进入的部分验证：

- ChatGPT 审查 `REPORT_10_ROLLOVER_AUDIT.md`
- ChatGPT 审查 `V0_3_DAILY_STRATEGY_DESIGN.md`
- 人工确认苏冰结构化规则候选是否适合 v0.3

不建议进入：

- 参数优化
- v0.3 代码实现
- 多品种/跨年份收益结论
- 任何模拟盘或实盘判断

## 12. 给 ChatGPT 的建议分析重点

建议 ChatGPT 下一步重点分析：

1. 是否应先实现 `v0.2.1-daily-rollover-safe`，而不是直接做 v0.3。
2. SB-JM-D-3 的 `untrusted_cross_contract_pnl` 应如何处理：强制平仓、排除、还是拆成真实合约两段。
3. `V0_3_DAILY_STRATEGY_DESIGN.md` 是否过拟合 7 笔交易。
4. ATR stop、fast-fail、anti-chase、MACD tier、volume scoring 的默认设计是否合理。
5. 苏冰结构化 Rulebook 中哪些规则只能做复盘标签，哪些可以进入新策略版本。
6. 是否应先做 rollover-safe + baseline 重跑，再做条件消融。
7. 后续是否回到“日线方向 + 5m/15m 入场”的 V1-B 方向。

## 13. 下一步建议

主方向选择：A. 继续修 P0 可信度。

理由：

- 当前最硬的阻塞不是策略参数，而是 PnL 可信度。
- SB-JM-D-3 是盈利交易且跨合约，如果不处理，会污染 baseline、消融和 v0.3 对比。
- 先做 rollover-safe 或 cross-contract exclusion，才能让后续策略优化有可信评价基础。
- 直接实现 v0.3 会把数据可信度问题和策略规则问题混在一起。

建议下一轮任务：

```text
实现或设计 su_bing_jm_daily_ema21_macd_volume 的 v0.2.1-daily-rollover-safe / cross-contract exclusion 方案，
保留 v0.2.0-daily baseline，
重新生成可信 baseline report，
再决定是否进入 v0.3 实现。
```

## 给 ChatGPT 的文件清单

建议上传：

1. `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/FINAL_HANDOFF_FOR_CHATGPT.md`
2. `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_ROLLOVER_AUDIT.md`
3. `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_TRUST_AUDIT.md`
4. `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/SU_BING_SKILL_RULES_EXTRACT.md`
5. `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/SKILL_ALIGNMENT_REVIEW.md`
6. `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/REPORT_10_SKILL_TRADE_CLASSIFICATION.md`
7. `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_2_BASELINE_FINDINGS.md`
8. `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/CONDITION_ABLATION_PLAN.md`
9. `docs/strategy_specs/su_bing_jm_daily_ema21_macd_volume/V0_3_DAILY_STRATEGY_DESIGN.md`
10. `backtests/reports/report_10_su_bing_daily_trade_review.csv`
11. `backtests/reports/report_10_trade_bar_context.csv`
12. `backtests/reports/report_10_signal_candidates.csv`
