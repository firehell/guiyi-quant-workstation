# HTDY-ROLLING-OOS-X505

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | HTDY-ROLLING-OOS-X505 |
| Handbook Task | X5-05 / E5-05 |
| Branch | codex/htdy-rolling-oos-x505 |
| Worktree | /private/tmp/guiyi-htdy-rolling-oos-x505 |
| Status | COMPLETED / DIAGNOSTIC_CONFIRMS_REJECTION |
| Risk Level | L3 file-only diagnostic after hard reject |
| Required Env | local PostgreSQL read access |
| Created At | 2026-07-19 |

允许修改：X5-05 专用 module、CLI、测试、任务/回测事实文档、`data/reports/htdy_rolling_oos_x5_05/`。

禁止修改：canonical DB、candidate/report14、Profile/Parquet、frozen protocol、default params、策略/信号/撮合规则、X5-04 packet、live/通知/订单。

## 5. 实现

- 使用 frozen A/B/C 作为 `rolling_oos_stability`；每 fold 的 24 个月 train 仅记录 lineage metadata，不拟合、不筛参。
- A/B 为 3 个月 test，C 为 6 个月尾窗；fold start 固定 6 个月步长。
- 每 fold 72-bar indicator-only warmup、全新策略状态、独立 binding/config/cost/result/audit hash。
- 亏损、零交易、失败 fold 均保留，不允许删除或包装为成功。
- 固定 81 组 deterministic `post_trade_cost_overlay`：commission `1/1.5/2`、slippage `1/2/3 ticks`、gap `0/1/2 ticks`（仅 gap trades）、margin `1/1.25/1.5`。
- overlay 不重新撮合、不修改 parameter hash；margin 只报告可成交性/占用压力。
- 保存 roll/conflict/liquidity/frequency/consecutive-loss diagnostics。
- 因 X5-04 已 hard reject，最终标签只能是 `DIAGNOSTIC_CONFIRMS_REJECTION` 或 `DIAGNOSTIC_INCONCLUSIVE_REJECTION_REMAINS`，不得翻转 X5-04。

## 18.0 自动化测试

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app/backtest/htdy_rolling_oos.py \
  services/quant-api/scripts/htdy_rolling_oos.py \
  services/quant-api/tests/test_htdy_rolling_oos_x505.py

uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_rolling_oos_x505.py \
  services/quant-api/tests/test_htdy_oos_validation_x504.py \
  services/quant-api/tests/test_htdy_trusted_candidate_x503.py \
  services/quant-api/tests/test_htdy_trusted_report_x502.py \
  services/quant-api/tests/test_htdy_strict_core.py
```

## 20. 回滚

代码可通过撤销本分支 module/CLI/tests/docs 回滚；正式 rolling 输出是不可覆盖诊断证据，不通过删除亏损 fold 或重跑回滚。X5-05 不写 canonical DB。

## 21. 正式结果

- Source commit：`7b94867e5bd8779bab4914447d1dbedea92a1d7a`
- Proposal：`DIAGNOSTIC_CONFIRMS_REJECTION`
- Packet hash：`1d0fe23c2b275ede0d5c96e5ffa477fd1008571cb0087dd7fb845b80b8c8e8c7`
- A：84 trades，max consecutive losses 19，profit factor 0.1095601821936865
- B：101 trades，max consecutive losses 25，profit factor 0.1867609257901327
- C：166 trades，max consecutive losses 12，profit factor 0.16572716320091893
- 三个 fold 结构审计均 passed；三个 fold 均触发 frozen numeric reject。
- Packet hash 与所有 fold artifact SHA-256 已独立复算通过。
- X5-04 `OOS_HARD_REJECT_TRIGGERED` 保持不变；canonical DB 零写入。
