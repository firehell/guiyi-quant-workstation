# HTDY-OOS-VALIDATION-X504

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | HTDY-OOS-VALIDATION-X504 |
| Handbook Task | X5-04 / E5-04 |
| Branch | codex/htdy-oos-validation-x504 |
| Worktree | /Volumes/扩展盘/guiyi-quant-workstation |
| Status | CODE_COMPLETE_EXTERNAL_GATE_PENDING |
| Risk Level | L3 file-only OOS gate |
| Required Env | local PostgreSQL read access |
| Required Mounts | /Volumes/扩展盘 |
| Created At | 2026-07-19 |

允许修改：HTDY OOS 专用 backtest module、CLI、测试、任务与回测事实文档、X5-04 文件输出目录。

禁止修改：canonical PostgreSQL、已有 BacktestTask/BacktestReport、report14、Parquet、Profile binding、frozen protocol、策略参数、旧 JM V1-B OOS runner、live/SignalEvent/企业微信/订单。

## 5. 目标与实现

X5-04 只执行 frozen protocol 中的 `oos_fixed`。执行前读取 72 根 passed-only 15m bar 作为指标预热；一次计算 `72 + OOS` strict vectors 后，只把 OOS snapshot 切片交给全新策略实例。预热 bar 不进入事件循环，不能产生信号、订单、交易、收益、持仓、pending action 或持有周期。

正式 CLI：

```bash
uv run --project services/quant-api python \
  services/quant-api/scripts/htdy_oos_validation.py
```

CLI 默认读取：

```text
data/reports/htdy_trusted_backtest_candidate_x5_03/
  HTDY_TRUSTED_BACKTEST_CANDIDATE.json
```

X5-03 packet 必须 hash 可复算，并包含：

- `gate=HTDY_TRUSTED_BACKTEST_CANDIDATE`；
- `transaction.status=committed`；
- 一个新 task/report 的 ID 与编号；
- candidate 与 report14 audit 均为 `passed`；
- candidate 使用的 Profile、binding、file ID、data version 和 snapshot hash。

X5-04 独立解析 active binding，并要求上述 snapshot identity 全等。协议内已 superseded 的旧文件路径不恢复为 active；frozen protocol 继续约束策略、参数、指标、窗口、成交时点、成本规则和 hard-reject 阈值。

## 18.0 自动化测试

```bash
uv run --project services/quant-api ruff check \
  services/quant-api/app/backtest/htdy_oos_validation.py \
  services/quant-api/scripts/htdy_oos_validation.py \
  services/quant-api/tests/test_htdy_oos_validation_x504.py

uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_trusted_report_x502.py \
  services/quant-api/tests/test_htdy_strict_core.py \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py \
  services/quant-api/tests/test_htdy_validation_protocol_c501.py \
  services/quant-api/tests/test_htdy_oos_validation_x504.py
```

当前结果：Ruff passed；组合回归 `58 passed`。默认 CLI smoke 在 X5-03 packet 缺失时 exit 2，数据库会话未打开，X5-04 输出目录未创建；非空输出目录会在执行前被拒绝，既有证据不可覆盖。

## 19. 当前 Gate

```text
CODE_COMPLETE_EXTERNAL_GATE_PENDING
```

原因：canonical `main` 只有 X5-02，尚无经过用户独立批准并成功提交的 X5-03 candidate，因此真实 OOS 严格未运行，未生成 `OOS_VALIDATION_EXECUTED` 或 `OOS_HARD_REJECT_TRIGGERED`。

X5-03 Gate 满足后，正式运行只允许产生 `data/reports/htdy_oos_validation_x5_04/` 文件。结果为二选一：

```text
OOS_VALIDATION_EXECUTED
OOS_HARD_REJECT_TRIGGERED
```

任一 structural/numeric hard reject 都保留窗口与脱敏失败证据，并挂起阶段 5；不得调参重跑或隐藏失败。

## 20. 回滚

撤销本分支新增 module、CLI、测试和文档即可。当前没有 canonical DB、数据资产、report14 或 X5-04 结果文件需要回滚。
