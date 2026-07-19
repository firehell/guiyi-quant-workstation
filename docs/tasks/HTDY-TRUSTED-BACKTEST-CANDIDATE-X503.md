# HTDY-TRUSTED-BACKTEST-CANDIDATE-X503

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | HTDY-TRUSTED-BACKTEST-CANDIDATE-X503 |
| Handbook Task | X5-03 / E5-03 |
| Branch | codex/htdy-trusted-backtest-candidate-x503 |
| Worktree | /private/tmp/guiyi-htdy-trusted-backtest-candidate-x503 |
| Status | COMPLETED / HTDY_TRUSTED_BACKTEST_CANDIDATE |
| Risk Level | L3 canonical PostgreSQL write |
| Required Env | canonical local PostgreSQL |
| Required Mounts | /Volumes/扩展盘 |
| Created At | 2026-07-19 |

用户已于 2026-07-19 明确批准 X5-03 canonical 写入：仅新增一个 task、一个 report 及其 trades/orders/equity/metrics；write、flush、candidate trust audit 和 report14 trust audit 必须在同一事务，任一失败整体 rollback，只保存脱敏失败证据。

允许修改：X5-03 专用 module、CLI、测试、任务/回测事实文档、`data/reports/htdy_trusted_backtest_candidate_x5_03/`，以及经批准的 canonical `backtest_tasks/backtest_reports/backtest_trades/backtest_orders` 精确新增行。

禁止修改：已有 task/report、report14、Profile binding、MarketDataFile、Parquet、frozen protocol、default params、策略规则、live、SignalEvent、通知或交易订单。

## 5. 实现

- 复算 X5-02 packet 与全部 artifact SHA/hash，要求 pre-apply audit passed、Profile active/primary/passed/passed-only。
- 使用 `BacktestService.create_formal_task` 和 `persist_result`，复用 formal Profile、indicator policy、lineage mapper、trusted metrics 与 consistency hash。
- task_no 固定由 X5-02 packet hash 派生，重复 apply fail-closed，防止第二个 candidate。
- PostgreSQL 使用 repeatable-read 单事务；写入与 flush 后，在 commit 前执行 candidate/report14 双 trust audit、row delta、facts hash、formal lineage 和 future/fill timing。
- candidate 或 report14 audit 非 `passed`、report14 fingerprint 漂移、row delta 不精确时整体 rollback，并在新会话验证 canonical 零增量。
- schema 没有独立 equity/metrics 表；equity 由 `backtest_trades` 确定性复算，metrics 保存在 `backtest_reports.summary`，packet 记录对应 point/field counts。

正式命令：

```bash
uv run --project services/quant-api python \
  services/quant-api/scripts/htdy_trusted_candidate.py \
  --approval-gate HTDY_X503_CANONICAL_WRITE_APPROVED
```

成功 Gate：

```text
HTDY_TRUSTED_BACKTEST_CANDIDATE
```

失败 Gate：

```text
HTDY_TRUST_AUDIT_FAILED_REVIEW_REQUIRED
```

## 18.0 自动化测试

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app/backtest/htdy_trusted_candidate.py \
  services/quant-api/scripts/htdy_trusted_candidate.py \
  services/quant-api/tests/test_htdy_trusted_candidate_x503.py

uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_trusted_candidate_x503.py \
  services/quant-api/tests/test_htdy_trusted_report_x502.py \
  services/quant-api/tests/test_backtest_trust_audit.py \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py \
  services/quant-api/tests/test_htdy_oos_validation_x504.py
```

## 20. 回滚

审计失败时数据库事务自动 rollback；仅保留脱敏 file-only 失败 packet。成功后 candidate 是新的历史事实，不通过删除或改写回滚；任何撤销需另立数据库修复 Task。代码回滚可撤销本分支 module、CLI、测试和文档，不得用代码回滚掩盖已提交的 canonical candidate。

## 21. 执行结果

```text
gate=HTDY_TRUSTED_BACKTEST_CANDIDATE
packet_hash=ccf3e57ff0b1664d1120bc6ba42d75c73a10da015f52092d9eed21971ccb11bd
source_commit=d9d9cea173ee0de5fd2729fef59d72560b3c2830
task_id=23
task_no=BTV-HTDY-X503-ac00ef77c66a2862
report_id=15
report_no=BTV-HTDY-X503-ac00ef77c66a2862-RPT-a7c44c73
trades=1255
orders=2510
equity_points=1256
metric_fields=38
candidate_audit=passed
report14_audit=passed
report14_unchanged=true
```

提交后的独立只读事务复核：canonical counts `tasks=23 / reports=15 / trades=4361 / orders=4225`，candidate consistency hash `dee6c73e0972de51ae314956c038962f1c45cbfb1162322628fee3b728c07a1d`，report14 consistency hash 保持 `2b16178a371a28727e0c471d6a7d68199e213ec205d838cf6634e82de428d12a`。packet hash 复算通过。
