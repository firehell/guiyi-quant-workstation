# NEXT_STEPS.md

更新时间：2026-07-16

## 总原则

- 数据可信度、可追溯和可复算优先于收益和功能扩展。
- 当前不做自动交易、实盘账户、SaaS、多用户或大型重构。
- live、scheduler、数据写入、schema 和公网部署必须分阶段 Gate。
- 文档和 GPT Sources 必须来自仓库事实源，不靠聊天复述。

## 当前状态

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```

当前 manifest 强支持物理历史数据已大规模下载，但不能宣称 direct PostgreSQL、quality、Profile binding、formal consumer contract 或 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 已通过。旧 Phase 3 的 `1853 / 34 / 45` 数字只作为历史审计模型快照保留，暂停直接批量修复。

## 当前本地合并任务

```text
DIRECTION-A-MAIN-MERGE
status=LOCAL_MERGE_COMPLETED_VALIDATED
source_branch=feature/direction-a1-final-sealing-audit
integration_branch=codex/merge-direction-a-final-sealing-main
backup_branch=codex/backup-main-before-direction-a-merge-20260715
```

合并原则：当前 `main` 的 workstation/GitHub Native V3、Web A01/A02、K 线交互、viewport loading、`cross_file_conflicts` warning 语义优先；Direction A 只选择性接入 profile registry / active binding / lineage、数据封板审计报告、manifest evidence 和相关测试。

本轮不 push、不删分支、不写 DB/Parquet、不调用 RQData。已完成本地 merge commit 并 fast-forward 到 `main`；建议 GPT 优先复核 `tasks/current.md`、`docs/CODEX_HANDOFF.md`、本次 merge diff 和测试结果。

## P0 后续任务

1. **全历史物理事实盘点与 Audit V2**
   - 输入：`data/manifests/`、`configs/data_profiles/*.json`、`data/reports/data_layer_final_audit_phase3_20260712/`、`data/reports/data_stage_closure/`
   - 目标：无目标判断地盘点物理资产，重写动态全历史审计，重算真实 residual。
   - 默认先 Plan；不得直接写 DB、manifest、Parquet 或调用 RQData。

2. **residual 只读分类**
   - 输入：Audit V2 residual matrix。
   - 目标：区分审计器误报、manifest/DB 漂移、Profile target 错配、真实缺文件和需要人工 Gate 的 residual。
   - 只读，不写数据。

3. **Profile rollout dry-run**
   - 输入：Profile target-aware 选优结果。
   - 目标：生成 binding apply packet、verify packet 和 rollback 说明。
   - dry-run，不写 DB。

4. **JM T3-real 单次 live 写入 Gate**
   - 输入：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md`
   - 条件：JM 可交易时段 + 用户显式确认
   - 只允许 live 表和 checkpoint 写入；不包含 signal event、archive、企业微信或交易执行。

5. **真实公网安全 smoke**
   - 输入：`deploy/nginx/README.md`、`deploy/frp/README.md`
   - 验证：TLS、Basic Auth、未认证 401、5432/6379/8000/5173 不直接公网开放、FRP/Nginx 重启恢复
   - 配置模板存在不等于远端验收通过。

## P1 后续任务

1. Profile rollout apply（显式 DB 批准）。
2. Market / Backtest / Signal / Review formal consumer contract。
3. OOS / walk-forward 全窗口验证。
4. Web trust audit 专项展示。
5. 公共 chunk 拆包。
6. `research_only` schema/API 语义拆分。

## GPT GitHub 读取建议

最小集合：

- `docs/gpt/project_sources/00-INDEX.md`
- `PROJECT_SOURCE.md`
- `STATUS.md`
- `DECISIONS.md`
- `CODEX_TASKS.md`
- `docs/gpt/PROJECT_SOURCE_MANIFEST.md`
- `docs/gpt/GITHUB_READ_ORDER.md`

完整集合：

- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/CODEX_HANDOFF.md`
- `tasks/current.md`

兼容摘要：

- `docs/gpt/project_sources/01-*.md` 到 `13-*.md` 只作为旧上传流程兼容包；事实冲突时以 canonical 文件为准。

专题补充集合：

- 数据：`docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md`、`data/reports/data_stage_closure/data_stage_closure_summary.md`
- 回测：`docs/STAGE13_BACKTEST_TRUST_AUDIT.md`、`docs/BACKTEST_ENGINE.md`
- 信号：`docs/SIGNAL_EVENTS.md`、`docs/STAGE9_WECHAT_DELIVERY.md`
- live：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、`docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- 工作站：`docs/workstation/`、`docs/workflows/`
