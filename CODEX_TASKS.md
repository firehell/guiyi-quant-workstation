# Codex 当前任务池

更新时间：2026-07-17

## 当前任务

当前状态：`CONSUMER-GOLDEN-QUERY-FINAL-GATE-005` 已完成。`CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 已由 direct PostgreSQL read-only rerun、12/12 Golden Query 样本和 13/13 hard gate 证实；证据位于 `data/reports/consumer_golden_query_final_gate_20260718_rerun/`。

该状态只关闭严格消费者的数据准入契约；`DATA_LAYER_REAUDIT_REQUIRED` 仍保留全历史 residual 治理，且不授权 live runtime、企业微信 autosend 或自动交易。

## P0 后续任务

| 优先级 | 任务 | 默认模式 | 输入 |
|---|---|---|---|
| P0 | Audit V2 residual 治理边界复核 | Plan 后执行，先只读 | 已保留的 provider/calendar/session/asset residual 与 `STATUS.md` |
| P0 | JM T3-real 单次 live 写入 Gate | Plan + 用户确认 | `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、runtime 副本 |
| P0 | 真实公网安全 smoke | Plan + 人工环境 | `deploy/nginx/README.md`、`deploy/frp/README.md` |

## P1 后续任务

| 优先级 | 任务 | 默认模式 | 说明 |
|---|---|---|---|
| P1 | OOS / walk-forward 全窗口验证 | Plan 模式 | 使用 frozen config，不调参改善收益 |
| P1 | Web trust audit 展示 | Plan 模式 | 展示可信审计，不改变回测口径 |
| P1 | 公共 chunk 拆包 | 小步前端任务 | 当前只是性能后置项 |

## 非阻塞工作站支持 backlog

| 任务 | 默认模式 | 说明 |
|---|---|---|
| WorkBuddy V3 Demo（Issue #27 / Draft PR #28） | 用户确认后执行 | 可继续验证，但不阻塞全历史盘点、Audit V2 或任何业务 P0 |
| GitHub Issue / PR 生命周期清理 | 人工确认 | 只提供关闭/归档建议，不自动 close、merge 或 deploy |
| 控制面缺陷 follow-up | 真实业务 Task 复现后独立 Plan | 只修复已复现问题，不做能力扩展 |

## 执行边界

- 数据写入、DB migration、worker/scheduler、live runtime、策略口径、回测口径默认先 Plan。
- 暂停所有基于旧 `metadata_gap=1853`、`pre_2020_weekly_missing=34` 和 actual contract 旧固定 gap 的批量修复；必须等 Audit V2 只读 residual 证明。
- 企业微信真实发送必须单条、显式授权、观察提醒语义、脱敏日志。
- 自动交易、实盘账户、订单生成、SaaS、多用户系统继续禁止。

## GPT 同步建议

最小集合：

- `docs/gpt/project_sources/00-INDEX.md`
- `PROJECT_SOURCE.md`
- `STATUS.md`
- `DECISIONS.md`
- `CODEX_TASKS.md`
- `docs/gpt/PROJECT_SOURCE_MANIFEST.md`
- `docs/gpt/GITHUB_READ_ORDER.md`
- `docs/workstation/WORKSTATION_UPGRADE_ACCEPTANCE.md`
- `docs/workstation/WORKSTATION_OPERATIONS_CHECKLIST.md`
- `docs/workstation/WORKSTATION_GITHUB_LIFECYCLE_CLEANUP.md`

完整集合：

- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/CODEX_HANDOFF.md`
- `tasks/current.md`

兼容摘要：

- `docs/gpt/project_sources/01-*.md` 到 `13-*.md` 仅在旧上传流程或快速导航时使用；事实冲突时以 canonical 文件为准。
