# NEXT_STEPS.md

更新时间：2026-07-12

## 总原则

- 数据可信度、可追溯和可复算优先于收益和功能扩展。
- 当前不做自动交易、实盘账户、SaaS、多用户或大型重构。
- live、scheduler、数据写入、schema 和公网部署必须分阶段 Gate。

## 2026-07-13 数据阶段收口审计后置项

新增事实源：

- `docs/tasks/TASK-2026-07-13-001-data-stage-closure-doc-audit.md`
- `docs/gpt/DATA_STAGE_CLOSURE_REVIEW_PACKAGE.md`
- `data/reports/data_stage_closure/data_stage_closure_summary.md`
- `data/reports/data_stage_closure/document_inventory.csv`

当前状态：

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

下一步建议：

1. **P0：manifest / DB 对齐专项 Plan**
   - 输入：`data/reports/data_layer_final_audit_phase3_20260712/metadata_consistency_matrix.csv`、`data/reports/data_stage_closure/manifest_db_consistency.csv`。
   - 目标：解释或修复 `metadata_gap=1853`。
   - 默认先 Plan；不得直接写 DB/manifest。

2. **P0：pre-2020 周线 34 品种缺口专项 Plan**
   - 输入：`data/reports/data_layer_final_audit_phase3_20260712/weekly_history_audit.csv`。
   - 目标：逐品种区分 RQData 下限、真实上市边界、应补数据和应标记 N/A。
   - 不得直接重新下载全量数据。

3. **P1：actual contract 45 条缺口专项 Plan**
   - 输入：`data/reports/data_layer_final_audit_phase3_20260712/main_contract_mapping_audit.csv`。
   - 目标：逐条判定补 bars、标记 N/A 或等待 mapping 修复。

4. **P1：文档清理人工复核**
   - 输入：`data/reports/data_stage_closure/document_inventory.csv`。
   - 本轮没有硬删除文档；`delete_candidate` 仅作人工复核候选。

## 当前已完成

1. Stage 13-G：`report_id=14` lineage 与 trust audit passed。
2. JM `20260710_v2` 六周期：1m direct，五周期 local aggregation，全部 primary passed。
3. Stage 8.6：全品种 1d 与 JM 最新主连六周期分开审计。
4. Alembic `20260710_0020`：数据库 current=head，workbench 复合索引存在。
5. 安全配置：DB/Redis localhost、Redis auth、凭据环境变量、HTTPS Nginx 模板。
6. 运行模板：腾讯云 Nginx + FRP，Mac mini launchd 监督 static/API/workers；外接卷权限未通过，systemd 仅为 Linux 候选模板。
7. Web V1-B 视觉与信息架构重构：11 路由、1440/1280/1024 响应式和 Console 验收通过。
8. JM-only live runtime 开发收口：交易时钟、single scheduler、1m→分钟/日/周、盘后归档、formal event、notification worker、严格 runtime health；全部真实开关默认关闭；真实 T1/T3 Gate 待执行。
9. Stage 5-B reference metadata gap 收口：`contract_universe` 285 success，derived `continuous_contract_map` 546 success，最终 target coverage 仅剩 105 条 `quality_warning`。
10. DATA-PART-TARGET-CLOSURE：105 条 warning 消费边界 Plan+代码、Stage 8.6 pending 分流、总验收报告完成。
11. POST-DATA-CLOSURE-NEXT-GATES 任务包：GPT 同步包、基础监督服务 Gate、样本外验证、JM 单次 live Gate Plan、macOS 长期运行方案已拆成 Cursor/Codex 可执行文档。
12. POST-DATA-CLOSURE-GATE-EXECUTION（Cursor）：方案 B 本机磁盘 runtime 迁移、`dev-healthcheck` passed、T3 runtime 副本非交易 smoke、OOS frozen CLI、report 14 trust audit 复现。
13. 工作站 V1.5 控制平面（`feature/unified-task-dispatcher`）：统一 dispatch、四档路由、writer lock、pause/resume/cancel、Issue dry-run、doctor F02、CI `workstation-test`（50 pytest passed）。
14. 数据阶段收口审计与文档事实源整理：生成 `data/reports/data_stage_closure/` 与 GPT 审查包；确认当前为 `DATA_LAYER_PARTIAL`，不能宣称全品种周线从上市以来完整。

## 下一阶段建议

### P0：基础监督服务 Gate

- [x] 最小检查：`docs/tasks/TASK-2026-07-12-015-supervisor-service-gate.md`
- [x] 方案 B 迁移：`docs/tasks/TASK-2026-07-12-019-macos-scheme-b-migration-impl.md`
- launchd 绑定 `~/GuiyiRuntime/guiyi-quant-workstation-runtime`；`dev-healthcheck` passed。
- 后续若要宣称 `LONG_RUNNING_READY`，仍需 5 交易日长稳和 kill/recovery。

### P0：JM 单次真实 live Gate

- Plan：`docs/tasks/TASK-2026-07-12-017-jm-single-live-gate-plan.md`
- [x] Phase 1 dry-run / readiness（主仓库 + runtime 副本证据见 JM-LIVE-GATE-EVIDENCE §11–§12）
- [ ] Phase 2/3 T3-real：需 JM 可交易时段 + 用户显式确认；于 runtime 副本 `--once`

### P0：真实服务器安全 smoke

- 替换 Nginx 域名、证书和绝对路径占位符。
- 云安全组拒绝 5432/6379/8000/5173。
- 未认证访问必须 401，认证后 Web/API/WS 成功。
- Mac mini launchd/FRPC 与腾讯云 Nginx/FRPS 重启后 Web/API/WS 自动恢复。
- 该步骤需要真实服务器权限；本仓库配置通过不等于远程验收通过。

### P1：105 条 quality_warning 消费边界

- [x] Plan：`docs/tasks/TASK-2026-07-12-010-quality-warning-consumption-boundary.md`
- [x] 代码：`MarketDataReader.passed_only`、Market warning message、Backtest/Signal/Review 边界
- [x] 文档：`docs/DATA_CENTER.md` §2.1

### P1：全品种 Stage 8.6 pending 独立复核

- [x] 8 pending 已分流：5 `accepted_warning` + 3 `registration_not_needed`
- [x] 报告：`data/reports/stage8_6_pending_reconcile_20260712/`
- JM 六周期 6/6 passed 结论不变

### P1：样本外验证设计

- Plan：`docs/tasks/TASK-2026-07-12-016-oos-validation-plan.md`
- [x] Frozen config：`configs/oos/jm_v1b_report14_frozen.json`
- [x] CLI：`scripts/oos_validation_run.py`（默认不入库）
- [ ] 全窗口 `--run` 批量与外部审查（另开任务）

### P1：macOS 长期运行选择

- Plan：`docs/tasks/TASK-2026-07-12-018-macos-long-running-plan.md`
- [x] 已采用方案 B：`~/GuiyiRuntime/guiyi-quant-workstation-runtime`
- [ ] 5 交易日长稳验收后方可声明 `LONG_RUNNING_READY`

## 明确后置 / 外部 Gate

- 5 个交易日 live 长稳和故障注入；完成前不得声明长期运行 ready。
- 自动盘后归档调度；当前只有受控 CLI，真实执行必须单独确认。
- 全品种 realtime 扩展；JM pilot 不等于 90 品种 ready。
- `research_only` schema/API 语义拆分。
- Web trust audit 专项展示与约 651 kB 公共 chunk 性能拆包。

以上后置项均应另开新 Codex 会话并使用 Plan 模式。

## 下一轮 GPT 上传文件

- `tasks/current.md`
- `docs/tasks/TASK-2026-07-13-001-data-stage-closure-doc-audit.md`
- `docs/gpt/DATA_STAGE_CLOSURE_REVIEW_PACKAGE.md`
- `data/reports/data_stage_closure/data_stage_closure_summary.md`
- `data/reports/data_stage_closure/document_inventory.csv`
- `docs/gpt/CURRENT_STATE.md`
- `docs/DATA_CENTER.md`
- `docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md`
- `docs/tasks/TASK-2026-07-12-014-gpt-sync-package-refresh.md`
- `docs/tasks/TASK-2026-07-12-015-supervisor-service-gate.md`
- `docs/tasks/TASK-2026-07-12-016-oos-validation-plan.md`
- `docs/tasks/TASK-2026-07-12-017-jm-single-live-gate-plan.md`
- `docs/tasks/TASK-2026-07-12-018-macos-long-running-plan.md`
- `docs/tasks/TASK-2026-07-12-019-macos-scheme-b-migration-impl.md`
- `configs/oos/jm_v1b_report14_frozen.json`
- `scripts/oos_validation_run.py`
- `docs/tasks/TASK-2026-07-12-010-quality-warning-consumption-boundary.md`
- `docs/tasks/TASK-2026-07-12-012-stage8-6-pending-reconcile.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/STAGE13_BACKTEST_TRUST_AUDIT.md`
- `docs/ARCHITECTURE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- `data/reports/stage8_6_active_gate_summary.md`
- `data/reports/jm_main_six_period_latest/stage8_6_active_gate_summary.md`
- `data/reports/reference_metadata_gap_apply_derived_continuous_contract_map_20260712/REFERENCE_METADATA_GAP_APPLY.md`
- `data/reports/reference_metadata_gap_reconcile_after_continuous_contract_map_derived_20260712/REFERENCE_METADATA_GAP_RECONCILE.md`
- `data/reports/target_coverage_audit_after_reference_metadata_apply_full_20260712/coverage_summary.md`
