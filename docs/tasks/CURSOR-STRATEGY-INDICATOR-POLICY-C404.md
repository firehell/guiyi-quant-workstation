# CURSOR-STRATEGY-INDICATOR-POLICY-C404

更新时间：2026-07-19

对应手册任务：`C4-04`

## 结论

状态：`COMPLETED / CURSOR_STRATEGY_INDICATOR_POLICY_IMPLEMENTED`

在 quant-core 落地策略 indicator policy 不可变 snapshot 契约与 fail-closed 校验；formal 创建与报告读取路径接入；JM `v1b.0` 自动附 frozen catalog snapshot；HTDY strict 强制绑定 `huotian_dayou_strict_v1`。未写 Alembic、未回填旧 task/report、未改 report 14、未改指标数值算法。

不得宣称 Codex 正式 Gate（如 `INDICATOR_REGISTRY_V1_READY`）。本任务仅宣称 Cursor Gate：`CURSOR_STRATEGY_INDICATOR_POLICY_IMPLEMENTED`。

## 设计要点

```text
create_formal_task
  -> JM v1b.0：自动 attach jm_v1b_report14_frozen_v1 目录快照
  -> HTDY strict：强制 strict_v1；拒绝 original_v0
  -> 其他新 formal：缺 policy → BacktestConfigurationError
report_metadata / GET report
  -> 有 snapshot → indicator_policy_status=available
  -> 无 snapshot → legacy_policy_unavailable（禁止用当前 Registry 猜测）
```

Snapshot schema：`schema_version=strategy_indicator_policy_v1`。

## 主要变更

| 路径 | 作用 |
|---|---|
| `packages/quant-core/guiyi_quant/strategies/indicator_policy.py` | Snapshot / build / require / resolve |
| `.../huotian_dayou_strict/{config_schema.py,default_params.json}` | 显式绑定 strict_v1 |
| `services/quant-api/app/backtest/service.py` | create_formal_task + report_metadata |
| `services/quant-api/app/api/backtests.py` | 报告 API 增加 policy status |
| `services/quant-api/app/backtest/v1b_jm_tasks.py` | 日线固定任务补 metadata（算法参数不变） |
| `services/quant-api/tests/test_strategy_indicator_policy_c404.py` | C404 定向单测 |

## 验证

```bash
git diff --check
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_strategy_indicator_policy_c404.py \
  services/quant-api/tests/test_indicator_registry_v1.py \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py
```

结果（2026-07-19）：上述三套 + `test_backtest_profile_contract.py` 共 **47 passed**；另抽测 JM formal create 相关 3 例 **passed**。

## 边界

- 无 Alembic / 无 canonical DB 写入 / 无旧报告回填
- 不改 JM `v1b.0` 算法与交易参数
- 不碰 live / SignalEvent / 企业微信
- binding_snapshot 扩展键 `indicator_policy_snapshot`；runner 忽略未知键

## 下一入口

Cursor Wave 下一手册任务（C4-05 或执行手册 Cursor 会话后续项）。
