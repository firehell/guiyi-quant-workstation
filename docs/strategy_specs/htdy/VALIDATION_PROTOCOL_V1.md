# HTDY Strict Validation Protocol V1

生成时间：2026-07-19
任务：`CURSOR-HTDY-VALIDATION-PROTOCOL-C501`（手册 `C5-01` / 原 `E5-01`）
Cursor Gate：`CURSOR_VALIDATION_PROTOCOL_PREPARED`
Codex Acceptance Gate：`STRATEGY_VALIDATION_PROTOCOL_FROZEN`
最终冻结任务：`INDICATOR-CONTRACT-ACCEPTANCE-FIX-X406`

机器可读配置：[`configs/oos/htdy_strict_validation_protocol_v1.json`](../../../configs/oos/htdy_strict_validation_protocol_v1.json)
Schema：[`configs/oos/schemas/htdy_validation_protocol_v1.schema.json`](../../../configs/oos/schemas/htdy_validation_protocol_v1.schema.json)
SHA-256 证据：[`data/reports/indicator_contract_v1/htdy_validation_protocol_config_hash.json`](../../../data/reports/indicator_contract_v1/htdy_validation_protocol_config_hash.json)

## 1. 目的与边界

本协议已在 **任何正式回测 / OOS 执行之前** 经用户批准最终冻结验证口径。它：

- **不**假定 `huotian_dayou_strict` 策略有效；
- **不**运行正式回测或 OOS；
- **不**根据历史收益或 dry-run 结果优化参数；
- **不**允许用未来 OOS 结果反向改配置；
- **不**接入 live、SignalEvent、企业微信；
- **不**触碰 `report_id=14`。

本协议允许宣称：

```text
STRATEGY_VALIDATION_PROTOCOL_FROZEN
```

这只表示后续验证必须使用本协议的固定参数、窗口、成本和 hard-reject 准则；不表示已执行正式回测/OOS，也不表示策略可信、live 或 alert Ready。

D4-00 诚实 Gate 保持：

```text
HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED
```

对齐文档：

- [`STRICT_V1_SPEC.md`](STRICT_V1_SPEC.md)
- [`FORMAL_BACKTEST_CANDIDATE_PLAN.md`](FORMAL_BACKTEST_CANDIDATE_PLAN.md)
- C4-05 申请包草案：`data/reports/indicator_contract_v1/htdy_formal_apply_packet_draft.json`

## 2. 冻结候选身份

| 字段 | 值 |
|---|---|
| strategy_code | `huotian_dayou_strict` |
| strategy_version | `v0.1.0-backtest-candidate` |
| indicator / formal_policy | `huotian_dayou_strict_v1` |
| product | JM |
| period / entry_interval | `15m` |
| profile_id | `intraday_research_v1` |
| contract | `jm.MAIN` |
| contract_role | `dominant_main_continuous` |
| actual_contract_in_scope | `false` |
| candidate_policy | `strict_v1_15m_formal_candidate_v0` |
| fill_policy | `signal_on_close_fill_next_bar_open` |
| parameter_hash | `84d80219d2a27d115dfdd36fe7bdf0ea41530e2fc9f2a188ec48bf9db37c2eb8` |

连续主力（`jm.MAIN`）仅作研究口径；实盘主力切换 / actual contract 不在本候选范围。

## 3. 成本、仓位与执行规则

| 字段 | 冻结值 |
|---|---|
| capital / initial_capital | `1_000_000` |
| maximum_position | `1` |
| risk_per_trade_ratio | `0.005` |
| slippage_ticks | `1` |
| stop_buffer_ticks | `1` |
| take_profit_r_multiple | `1.5` |
| planned_time_exit_bars | `8` |
| reverse_policy | `close_first_no_same_bar_reverse` |
| conflict_policy | `skip_conflict_candidate` |
| same_bar_exit_priority | `stop_loss_before_take_profit` |
| cost_model_version | `cost_model_v1_rate_slippage_size` |

运行时若缺 `price_tick` / `contract_multiplier` / commission / `margin_rate`，触发 **structural hard reject**（不得静默默认）。

## 4. 样本划分（只配置，不执行）

数据约束窗与 lineage parquet 一致：`2023-01-03 .. 2026-07-10`（**不是** C4-05 golden 短窗）。

| window_id | start | end | purpose |
|---|---|---|---|
| in_sample_baseline | 2023-01-03T00:00:00 | 2025-12-31T15:00:00 | 样本内基线（不调参） |
| oos_fixed | 2026-01-01T00:00:00 | 2026-07-10T15:00:00 | 固定样本外 |
| walk_forward_a_test | 2025-01-01T00:00:00 | 2025-03-31T15:00:00 | WF A test；train=`2023-01-03..2024-12-31` |
| walk_forward_b_test | 2025-07-01T00:00:00 | 2025-09-30T15:00:00 | WF B test；train=`2023-07-01..2025-06-30` |
| walk_forward_c_test | 2026-01-01T00:00:00 | 2026-06-30T15:00:00 | WF C test；train=`2024-01-01..2025-12-31` |

`persist_to_db=false`。`baseline_report_id=null`；`report14_policy=do_not_touch`。

## 5. 每窗必记 metrics

- trade_count
- total_return / total_return_pct
- max_drawdown / max_drawdown_pct
- max_consecutive_losses
- win_rate
- profit_factor
- expectancy / avg R
- fee and slippage totals
- largest_loss_trade
- signal count and no-trade reasons
- data_version / quality_status
- trust_audit status

空交易窗口必须如实保留，不得删除或隐藏。

## 6. Hard reject 准则

阈值 **先验固定**，不得用 HTDY dry-run 或未来 OOS 结果回拟合。

### 6.1 Structural（任一即拒）

- trust_audit 非 `passed`
- data quality 非 `passed`
- `parameter_hash` 或 `indicator_policy_snapshot` 不匹配
- lineage 非 `primary` + `passed`
- 缺成本字段（price_tick / multiplier / commission / margin）
- 触碰或复用 `report_id=14`
- fill / confirmed_only 口径漂移

### 6.2 OOS fixed（`oos_fixed`，任一即 `OOS_HARD_REJECT_TRIGGERED`）

| 条件 | 阈值 |
|---|---|
| max_drawdown_pct | `> 0.15` |
| max_consecutive_losses | `>= 8` |
| trade_count | `< 5` |
| profit_factor | `< 0.5` |
| total_return_pct | `<= -0.20` |

触发后 **禁止调参掩盖**。

## 7. OOS hard reject 后的 E5-05 / X5-05 分支

```text
OOS_HARD_REJECT_TRIGGERED
  -> 默认跳过 X5-05 rolling OOS / 成本敏感性正式跑
  -> 仅允许 diagnostic-only 复查（不改规则、不改本冻结配置）
  -> 允许标签：
       PROPOSED_REJECTED_RESEARCH_CANDIDATE
       DIAGNOSTIC_CONFIRMS_REJECTION
       DIAGNOSTIC_INCONCLUSIVE_REJECTION_REMAINS
  -> 禁止：用诊断翻盘 OOS hard reject；用 OOS 回写配置
```

手册规则：OOS hard reject 不得被后续诊断翻盘。

## 8. Research status lifecycle

```text
backtest_candidate
  -> validation_protocol_prepared
  -> final_frozen                   (X4-06 用户批准)
  -> trusted_candidate | rejected_research_candidate   (Codex / 后续 Gate)
```

本包不进入 live。

## 9. SHA-256 复算

配置文件 SHA-256：对 `configs/oos/htdy_strict_validation_protocol_v1.json` 的 **原始 UTF-8 文件字节** 计算。

参数 hash：

```text
sha256(json.dumps(default_params.json, sort_keys=True, separators=(',', ':'), ensure_ascii=False))
```

证据见 `htdy_validation_protocol_config_hash.json`。

## 10. 禁止事项

1. 不假定策略有效或 Stage 5 Ready。
2. 不运行正式回测 / OOS 执行（本任务仅落盘协议）。
3. 不根据收益优化参数。
4. 不用 OOS 结果反向改配置。
5. 不修改 `configs/oos/jm_v1b_report14_frozen.json` 与 report14 资产。
6. 不接 live / SignalEvent / 企业微信。
7. 最终冻结后不得根据回测或 OOS 结果修改本配置；若协议必须变化，创建新版本并重新审批。
