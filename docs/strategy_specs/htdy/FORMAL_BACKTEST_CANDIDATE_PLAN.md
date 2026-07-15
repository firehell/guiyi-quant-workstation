# HTDY Strict Formal Backtest Candidate

生成时间：2026-07-13

## 1. 定位

本文件定义：

```text
HTDY-FORMAL-BACKTEST-CANDIDATE
```

目标是判断 `huotian_dayou_strict_v1` 是否值得进入正式可信回测候选，而不是直接接入正式策略链路、信号扫描、live evaluator、企业微信或任何下单链路。

本阶段新增独立候选版本：

| 字段 | 值 |
|---|---|
| indicator_version | `huotian_dayou_strict_v1` |
| strategy_code | `huotian_dayou_strict` |
| strategy_version | `v0.1.0-backtest-candidate` |
| candidate_policy | `strict_v1_15m_formal_candidate_v0` |
| fill_policy | `signal_on_close_fill_next_bar_open` |
| execution_scope | `formal_backtest_candidate` |

`huotian_dayou_original_v0` 不被覆盖；Web observation-only 图层不升级为正式信号。

## 2. 策略规则

第一版候选规则固定，不做参数优化：

- 入场：当前已收盘 bar 计算 strict 字段；`buy_observation` 或 `xg_observation` 为 long candidate；`sell_observation` 为 short candidate。
- 出场：反向 strict observation、止损、止盈、时间退出、样本结束强平。
- 止损：long 使用 signal bar low 减 `1` tick，short 使用 signal bar high 加 `1` tick。
- 止盈：`1.5R`，R 为下一根 open 实际成交价到止损价的初始风险。
- 时间退出：第 `8` 根同周期 bar 后，下一根 open 退出。
- 反手：第一版禁止同一 bar 直接反手；先平仓，至少等待下一根已收盘 bar 重新评估。
- 冲突处理：同一 bar 同时出现 long/short candidate 时跳过，记录 `conflict_candidate_skipped`。
- 同 bar 止损止盈冲突：止损优先。

## 3. 成交、成本和数据 Gate

成交口径：

- 信号确认：当前 bar close。
- 入场、反向退出、时间退出：下一根 bar open。
- 盘中止损/止盈：触及 level 则按 level 加减滑点；若 open 已越过 level，则用 open 加减滑点。

成本和风控：

- `price_tick`、`contract_multiplier`、commission rule、`margin_rate` 任一缺失则拒绝候选入场。
- 每笔 trade 记录手续费、滑点、合约乘数、保证金占用和初始风险。
- 默认 `capital=1_000_000`、`maximum_position=1`、`risk_per_trade_ratio=0.005`，不得在本阶段调参优化。

数据入口：

```text
provider/source in ("rqdata", "local_parquet")
data_role = "primary"
quality_status = "passed"
```

`quality_warning`、`candidate`、`validation`、`legacy_reference`、`failed` 一律阻断。

## 4. 实现边界

新增实现：

- `packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/`
- `experiments/htdy_indicator/formal_backtest_candidate.py`
- `services/quant-api/tests/test_htdy_formal_backtest_candidate.py`

dry-run helper 只读 parquet，输出 normalized payload：

```text
trades / orders / strategy_execution_events / summary
```

它不创建 backtest task，不写 `BacktestReport`，不写 `strategy_signals`、`signal_events`、live evaluator 或企业微信。

## 5. Report Gate

允许后续写 `BacktestReport`，但必须满足：

- 用户单独确认写入。
- 只能新建独立 task 和独立 report。
- 不复用、不覆盖、不修复、不删除 `report_id=14`。
- 新 report metadata 必须包含策略版本、参数、数据版本、执行时点、成本字段、candidate policy、`research_only=true`。
- 写入后必须立刻运行 `scripts/backtest_trust_audit.py`。
- 只有 trust audit `passed` 才能表述为“可信回测候选报告通过一致性审计”。

`report_id=14` 只作为 Stage 13-G 历史基线回归审计对象，不是 HTDY 写入目标。

## 6. 外部 GPT 安全复核标准

需要同步：

- 本文件。
- `STRICT_V1_SPEC.md`
- `OFFLINE_CANDIDATE_EVAL.md`
- 新策略 `config_schema.py`、`vnpy_strategy.py`、`default_params.json`。
- `test_htdy_formal_backtest_candidate.py`
- dry-run normalized result 摘要。
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `docs/BACKTEST_ENGINE.md`

GPT 复核必须明确：

- 是否存在未来函数或当前 bar 提前成交。
- observation 到 entry/exit 的解释是否过度主观。
- stop/take-profit/conflict/reverse 规则是否足够可复算。
- 成本、滑点、乘数、保证金是否逐笔计入。
- 是否允许从 formal candidate 进入下一步样本外验证设计。
