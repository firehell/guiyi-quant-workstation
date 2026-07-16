# Codex 当前任务池

更新时间：2026-07-16

## 当前任务

当前任务：WorkBuddy Unified V3 迁移进入 Demo 前验收状态。

范围：

- 校验 Commit A+B 后的 WorkBuddy V3 facade / Skill / Prompt / 文档一致性。
- 形成旧 Issue / PR 生命周期人工清理清单。
- 更新 WorkBuddy V3 Demo 前验收与运营检查清单。
- 将状态写为 `WORKBUDDY_V3_CODE_COMPLETE_DEMO_PENDING`。
- 不改业务代码、数据、DB、运行配置或 `.env`。

## P0 后续任务

| 优先级 | 任务 | 默认模式 | 输入 |
|---|---|---|---|
| P0 | manifest / DB 对齐专项 Plan | Plan 模式 | `data/reports/data_layer_final_audit_phase3_20260712/metadata_consistency_matrix.csv`、`data/reports/data_stage_closure/manifest_db_consistency.csv` |
| P0 | pre-2020 周线 34 品种缺口专项 Plan | Plan 模式 | `data/reports/data_layer_final_audit_phase3_20260712/weekly_history_audit.csv` |
| P0 | JM T3-real 单次 live 写入 Gate | Plan + 用户确认 | `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、runtime 副本 |
| P0 | 真实公网安全 smoke | Plan + 人工环境 | `deploy/nginx/README.md`、`deploy/frp/README.md` |
| P0 | WorkBuddy V3 Demo | 用户确认后执行 | `docs/workstation/WORKSTATION_UPGRADE_ACCEPTANCE.md`、`docs/workstation/WORKSTATION_OPERATIONS_CHECKLIST.md` |
| P0 | GitHub 生命周期清理 | 用户确认后人工执行 | `docs/workstation/WORKSTATION_GITHUB_LIFECYCLE_CLEANUP.md` |

## P1 后续任务

| 优先级 | 任务 | 默认模式 | 说明 |
|---|---|---|---|
| P1 | actual contract 45 条缺口专项 Plan | Plan 模式 | 判定补 bars、N/A 或 mapping 修复 |
| P1 | OOS / walk-forward 全窗口验证 | Plan 模式 | 使用 frozen config，不调参改善收益 |
| P1 | Web trust audit 展示 | Plan 模式 | 展示可信审计，不改变回测口径 |
| P1 | 公共 chunk 拆包 | 小步前端任务 | 当前只是性能后置项 |

## 执行边界

- 数据写入、DB migration、worker/scheduler、live runtime、策略口径、回测口径默认先 Plan。
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
