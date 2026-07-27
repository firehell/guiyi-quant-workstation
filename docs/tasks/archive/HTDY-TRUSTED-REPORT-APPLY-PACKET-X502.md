# HTDY-TRUSTED-REPORT-APPLY-PACKET-X502

## 0. 元信息

| 字段 | 值 |
|---|---|
| Task ID | HTDY-TRUSTED-REPORT-APPLY-PACKET-X502 |
| Handbook Task | X5-02 |
| Work Level | L1 |
| GitHub Issue | 待创建（L1 可选） |
| Branch | codex/htdy-trusted-report-apply-packet-x502 |
| Worktree | /Volumes/扩展盘/guiyi-parallel/htdy-trusted-report-apply-packet-x502 |
| Status | COMPLETED / HTDY_TRUSTED_REPORT_APPLY_PACKET_READY |
| Risk Level | L3 read-only report gate |
| Required Env | local PostgreSQL read access |
| Required Mounts | /Volumes/扩展盘 |
| Created At | 2026-07-19 |
| Owner | local-user |

```json
{
  "schema_version": 1,
  "task_id": "HTDY-TRUSTED-REPORT-APPLY-PACKET-X502",
  "work_level": "L1",
  "github_issue": "待创建",
  "branch": "codex/htdy-trusted-report-apply-packet-x502",
  "worktree": "/Volumes/扩展盘/guiyi-parallel/htdy-trusted-report-apply-packet-x502",
  "status": "COMPLETED",
  "owner": "local-user",
  "allowed_paths": [
    "docs/tasks/HTDY-TRUSTED-REPORT-APPLY-PACKET-X502.md",
    "tasks/current.md",
    "docs/BACKTEST_ENGINE.md",
    "docs/strategy_specs/htdy/README.md",
    "packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/",
    "services/quant-api/app/backtest/",
    "services/quant-api/scripts/htdy_trusted_report_packet.py",
    "services/quant-api/tests/test_htdy_trusted_report_x502.py",
    "data/reports/htdy_trusted_report_x5_02/"
  ],
  "forbidden_paths": [
    ".env",
    ".env.*",
    "data/raw/",
    "data/parquet/",
    "data/processed/",
    "configs/oos/htdy_strict_validation_protocol_v1.json",
    "configs/oos/jm_v1b_report14_frozen.json",
    "services/quant-api/alembic/",
    "services/quant-api/app/models/"
  ],
  "routing": {
    "requested_tier": "auto",
    "allow_auto_escalation": true,
    "max_auto_escalations": 1
  },
  "permissions": {
    "production_access_allowed": false,
    "database_write_allowed": false,
    "external_network_allowed": false,
    "push_allowed": false,
    "merge_allowed": false,
    "deploy_allowed": false,
    "trading_execution_allowed": false
  }
}
```

## 5. 目标

在不写 canonical PostgreSQL、不修改 Profile binding/Parquet/report14 的前提下：

1. 通过 `ProfileLineageResolver` 冻结 `intraday_research_v1 / jm / jm.MAIN / 15m` active binding。
2. 通过 canonical JM resolver 生成全窗口逐交易日成本时间线，保留开仓/平仓/平今语义。
3. 以一次性 strict vector 计算完成冻结协议全窗口 dry-run。
4. 生成可复算、可审批的 apply packet，并且仅在所有 pre-apply checks 通过时授予：

```text
HTDY_TRUSTED_REPORT_APPLY_PACKET_READY
```

## 6. 不做事项

- 不创建或写入正式 `BacktestTask` / `BacktestReport`。
- 不执行 OOS、walk-forward、参数优化或策略结论判断。
- 不修改 frozen validation protocol、report 14、canonical 数据资产或 Profile binding。
- 不接入 live、SignalEvent、企业微信或订单。
- 不 push、merge、deploy。

## 7. 实现约束

- 正式 runner 不接受 `--source` 或成本覆盖参数；不得 fallback 到 golden manifest。
- 数据必须是 active Profile 解析出的 `primary / passed` 文件，并在运行前后保持同一 immutable snapshot。
- 成本必须逐交易日来自 `resolve_jm_contract`；任一缺口立即阻断。
- 信号仍为 confirmed close，成交仍为 next-bar open；不得改变冻结策略参数或指标数值语义。
- 输出必须使用仓库相对路径并通过敏感路径扫描。

## 18.0 自动化测试命令

```bash
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_htdy_trusted_report_x502.py \
  services/quant-api/tests/test_htdy_formal_backtest_candidate.py \
  services/quant-api/tests/test_htdy_validation_protocol_c501.py \
  services/quant-api/tests/test_backtest_profile_contract.py \
  services/quant-api/tests/test_backtest_trust_audit.py

uv run --project services/quant-api ruff check app/backtest scripts tests

uv run --project services/quant-api python \
  scripts/htdy_trusted_report_packet.py \
  --output-dir ../../data/reports/htdy_trusted_report_x5_02

git diff --check
git status --short -- \
  configs/oos/htdy_strict_validation_protocol_v1.json \
  configs/oos/jm_v1b_report14_frozen.json \
  data/parquet
```

## 19. 验收标准

- Profile/file snapshot 在运行前后完全一致，且为 active、primary、passed。
- 冻结协议全窗口完整覆盖，所有交易日 canonical 成本解析成功。
- strict fields 全窗口只计算一次，并通过 causal prefix equivalence 测试。
- report-shaped payload、equity、drawdown、metrics、成本和订单/交易一致性 pre-audit 通过。
- packet hash 与所有引用 artifact hash 均可复算，输出不含绝对本机路径或秘密信息。
- DB/data/report14 零写入；否则任务 `BLOCKED`，不得生成 Ready Gate。

## 20. 风险与回滚

- 平今费与普通平仓费不同，错误合并将低估成本，属于 P0。
- active binding 在执行期间漂移时必须丢弃本次包并重跑。
- 回滚仅撤销本分支文件与生成包；本任务没有数据库或数据资产回滚。

## 21. 执行结果

状态：`COMPLETED / HTDY_TRUSTED_REPORT_APPLY_PACKET_READY`

```text
profile_active_binding_id=4945
market_data_file_id=71338
data_version=rqdata_jm_standard_15m_20200102_20260711_v2
bars=19381
trading_days=851
canonical_cost_days=851
trades=1255
strict_vector_evaluations=1
preapply_audit=passed
packet_hash=ac00ef77c66a2862c10a8d0ef706fdfba8abc4fe34af5d8a98640ffc99a89409
```

全窗口结果只用于审批风险可见性：`total_return=-0.3349106487`、`max_drawdown_pct=0.3361849056`、`total_commission=32735.6487`、`total_slippage=75300.0`。不得据此宣称策略可信或 OOS 通过。

定向回归：`61 passed`。Ruff、packet hash、pre-apply audit、report14/Parquet 禁止范围检查见结果包和最终交付记录。
