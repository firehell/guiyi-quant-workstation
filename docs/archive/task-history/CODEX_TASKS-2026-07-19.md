# Codex 当前任务池

更新时间：2026-07-19

## 当前任务

当前状态：Codex X4-06 已修复独立验收阻断并完成阶段 4，Gate 为 `INDICATOR_CONTRACT_READY / HTDY_STRICT_FORMAL_REPORT_READY / STRATEGY_VALIDATION_PROTOCOL_FROZEN`。证据：`data/reports/indicator_contract_v1/INDICATOR_CONTRACT_ACCEPTANCE_X406.md`。

Codex **下一任务**：阶段 5 按最终冻结协议创建独立 HTDY 候选报告并立即运行 trust audit；不得把输入资格扩写为策略可信、OOS、live 或 alert Ready。

Cursor Wave 已完成（均为 provisional）：C0-01 → C4-01…C4-05 → C5-01 → C5-06A → C6-07A → C-HANDOFF。D4-00 最终 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。C2-05 consumer Ready 与 `DATA_LAYER_REAUDIT_REQUIRED` 并存；不授权 live runtime、企业微信 autosend 或自动交易。

已完成的 Audit V2 engine、Profile rollout 和 formal consumer contract 不再列为当前任务；其报告与历史状态保留以供审计，不删除、不重算、不改写。

## 本轮工具顺序（必须串行，不穿插）

```text
Cursor Wave（契约 / 盘点 / 低风险预构建）
  -> Cursor → Codex 单次交接 Gate
  -> Codex Wave（正式 Gate / 报告写入 / OOS / T3/T4）
```

推荐分支：`cursor/v1-indicator-strategy-prep`（Cursor Wave）→ 交接后 `codex/v1-formal-validation-live-gate`（Codex Wave）。

## P0 Cursor Wave（当前执行面）

| 优先级 | 任务 | 默认模式 | 说明 |
|---|---|---|---|
| C0-01 | canonical 事实与任务池追平 | 文档 only | 已完成 |
| C4-01 | 指标调用方只读盘点 | 只读审计 | 已完成；36 callers / `CURSOR_INDICATOR_CALLERS_AUDITED` |
| C4-02 | 指标生命周期与 Registry V1 | 契约实现 | 已完成；`CURSOR_INDICATOR_REGISTRY_IMPLEMENTED`（非正式 READY） |
| C4-03 | MACD/ATR 首个 formal caller 条件迁移 | 资格筛查 | 已完成；`NO_FORMAL_INDICATOR_CALLER_MIGRATION_REQUIRED` |
| C4-04 | 正式策略 indicator policy metadata | 契约实现 | 已完成；`CURSOR_STRATEGY_INDICATOR_POLICY_IMPLEMENTED`（无 Alembic / 无回填） |
| C4-05 | HTDY strict formal preflight | 只读证据 | 已完成；`CURSOR_HTDY_FORMAL_PREFLIGHT_PREPARED` |
| C5-01 | HTDY 验证协议预构建 | 协议/配置 | 已完成；`CURSOR_VALIDATION_PROTOCOL_PREPARED`（非最终 frozen） |
| C5-06A | Review/Web foundation | 只读 UI 契约 | 已完成；`CURSOR_REVIEW_FOUNDATION_PREPARED` |
| C6-07A | Market/Runtime observation foundation | 只读观察 | 已完成；`CURSOR_RUNTIME_OBSERVATION_FOUNDATION_PREPARED` |
| C-HANDOFF | Cursor → Codex 交接包 | 文档 + 本地 checkpoint | 已完成；`CURSOR_WAVE_READY_FOR_CODEX_REVIEW`；Codex 首任务 X0-01 |

## P0 Codex Wave（交接后；业务阶段 4/5/6）

| 优先级 | 任务 | 默认模式 | 输入 |
|---|---|---|---|
| P0-1 | 阶段 4：指标契约与 formal candidate 封板 | 已完成 | `INDICATOR_CONTRACT_READY`；未创建正式报告 |
| P0-2 | 阶段 5：策略可信验证 | 下一任务；Plan + 用户确认 | final-frozen strategy config、独立候选报告、trust audit、OOS/walk-forward 与 Review evidence；不调参改善收益 |
| P0-3 | 阶段 6：JM T3 / T4 真实 Gate | Plan + 每次真实写入单独授权 | 新建稳定 runtime 副本、`docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、hash-bound approval packet |

## P1 后续任务

| 优先级 | 任务 | 默认模式 | 说明 |
|---|---|---|---|
| P1 | Audit V2 residual 维护治理 | Plan 后执行，先只读 | provider/calendar/session/asset residual；不阻塞 P0 formal consumer 主线 |
| P1 | Web trust audit 展示 | Plan 模式 | 展示可信审计，不改变回测口径 |
| P1 | 公共 chunk 拆包 | 小步前端任务 | 当前只是性能后置项 |
| P1 | 真实公网安全 smoke | Plan + 人工环境 | `deploy/nginx/README.md`、`deploy/frp/README.md` |

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
- `T3_REAL_PASSED`、`JM_ARCHIVE_PASSED`、`LIVE_SIGNAL_EVENT_GATE_PASSED`、`LIVE_WECOM_SINGLE_SEND_PASSED`、`JM_RUNTIME_READY` 与 `LONG_RUNNING_READY` 均未通过；阶段 6 只允许争取 T3/T4。

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
