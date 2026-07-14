# Codex 当前任务池

更新时间：2026-07-14

## 当前任务

当前任务：项目事实源更新与 GPT Project Sources 收口。

范围：

- 只改 Markdown/任务文档。
- 新增根目录 canonical summary。
- 更新 `docs/gpt/project_sources/` 投喂包。
- 不改代码、数据、DB、manifest、运行配置或 `.env`。

## P0 后续任务

| 优先级 | 任务 | 默认模式 | 输入 |
|---|---|---|---|
| P0 | manifest / DB 对齐专项 Plan | Plan 模式 | `data/reports/data_layer_final_audit_phase3_20260712/metadata_consistency_matrix.csv`、`data/reports/data_stage_closure/manifest_db_consistency.csv` |
| P0 | pre-2020 周线 34 品种缺口专项 Plan | Plan 模式 | `data/reports/data_layer_final_audit_phase3_20260712/weekly_history_audit.csv` |
| P0 | JM T3-real 单次 live 写入 Gate | Plan + 用户确认 | `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、runtime 副本 |
| P0 | 真实公网安全 smoke | Plan + 人工环境 | `deploy/nginx/README.md`、`deploy/frp/README.md` |

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
- `CODEX_TASKS.md`
- `docs/gpt/PROJECT_SOURCE_MANIFEST.md`

完整集合：

- `docs/gpt/project_sources/*.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/CODEX_HANDOFF.md`
- `tasks/current.md`

