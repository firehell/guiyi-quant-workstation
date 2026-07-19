# HTDY-STRATEGY-REVIEW-CLOSED-LOOP-X506B

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | HTDY-STRATEGY-REVIEW-CLOSED-LOOP-X506B |
| Handbook Task | X5-06B / E5-06 final |
| Branch | codex/htdy-strategy-review-x506b |
| Worktree | /private/tmp/guiyi-htdy-strategy-review-x506b |
| Status | COMPLETED / STRATEGY_REVIEW_CLOSED_LOOP_READY |
| Risk Level | L3 one ReviewNote write + read-only API/Web |
| Candidate | report 15 / task 23 |
| Created At | 2026-07-19 |

允许修改：validation-context 只读 service/API/schema、Review foundation 类型/页面、Market 回链、X5-06B 专用执行器/测试/证据、一个真实 ReviewNote。

禁止修改：candidate/report14/trade/order/equity/metrics 原始事实、X5-03/04/05 packet、Profile/Parquet、frozen config、策略/指标/撮合规则、live/通知/订单。

## 5. 实现

- `GET /api/backtests/reports/{report_id}/validation-context` 只从固定 X5-03/04/05 目录读取，复算 packet、artifact、fold manifest 与 context hash；query/path override 一律 422。
- API 对账 candidate report/task、Profile/binding/file/data version、protocol/parameter hash，并把 OOS、rolling folds、成本敏感性、hard reject 与 evidence hash 作为独立上下文返回，不回写 report summary。
- Review 页面并行加载原始报告与 validation context；策略、交易、费用、equity/drawdown 继续来自原始 report/trade，前端不重算策略。
- Review source 统一透出 stored `entry_signal_time`；Market chart 增加返回 Review deep-link。
- 正式 ReviewNote 固定选择 report 15 的最大净亏损 trade；净亏损并列按 exit time、trade ID 升序。
- ReviewNote 写入事务内验证 exact bars、signal < fill 与 candidate/report14 trust audit；commit 后重读并再次验证原始 report/trade 不变。

## 18.0 自动化测试

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_strategy_review_x506b.py \
  services/quant-api/tests/test_review_foundation_c506a.py \
  services/quant-api/tests/test_review_center_api.py

pnpm --dir apps/quant-web test
pnpm --dir apps/quant-web build
```

## 20. Gate

只有真实 ReviewNote 保存后重读、exact bars、validation-context API、Review/Market/Backtest deep-link、marker、console 与浏览器 smoke 全部通过，才允许：

```text
STRATEGY_REVIEW_CLOSED_LOOP_READY
```

任一失败时不得生成该 Gate，X5-07 必须 blocked。

## 20.1 正式执行结果

- ReviewNote：`id=9`，绑定 `report_id=15 / trade_id=3199`；浏览器保存后重读通过。
- exact bars：7 根，signal `2023-04-12T11:30:00+00:00` 严格早于 next-bar fill `2023-04-12T13:45:00+00:00`。
- Review → Market → Review 与 Market → Backtest report 15 回链通过；K 线和 trade marker 可见。
- validation context 展示 `OOS_HARD_REJECT_TRIGGERED`、A/B/C folds 与 `DIAGNOSTIC_CONFIRMS_REJECTION`，前端未重算策略。
- 浏览器控制台：`0` error；截图 SHA256：`40244e2e2259b6c6fa94b92495935ab2b565f74ef60f856448e29b12b2c69dea`。
- Gate packet：`data/reports/htdy_strategy_review_x5_06b/STRATEGY_REVIEW_CLOSED_LOOP_READY.json`，packet hash `1a0b7b279363ac4305ae7d08ef0e2cd89535046d58f133c8cadd54cceedf9c01`。

## 21. 回滚

代码可撤销本分支；唯一 ReviewNote 可按其精确 ID 另行受控删除。candidate/report14/trade/order/equity/metrics 不存在回滚，因为本任务禁止修改它们。
