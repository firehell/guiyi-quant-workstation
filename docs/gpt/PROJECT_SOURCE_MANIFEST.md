# GPT Project Source Manifest

更新时间：2026-07-14

生成 commit：`ec7a698e414c7d957e171f11c6aa9a6575de7e1d`

## 推荐上传列表

### 最小集合

- `docs/gpt/project_sources/00-INDEX.md`
- `PROJECT_SOURCE.md`
- `STATUS.md`
- `CODEX_TASKS.md`
- `docs/gpt/PROJECT_SOURCE_MANIFEST.md`

### 完整集合

- `docs/gpt/project_sources/*.md`
- `docs/DATA_CENTER.md`
- `docs/ARCHITECTURE.md`
- `docs/BACKTEST_ENGINE.md`
- `docs/SIGNAL_EVENTS.md`
- `docs/CODEX_HANDOFF.md`
- `tasks/current.md`

### 专题补充集合

- 数据：`docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md`、`data/reports/data_stage_closure/data_stage_closure_summary.md`
- 回测：`docs/STAGE13_BACKTEST_TRUST_AUDIT.md`、`docs/BACKTEST_ENGINE.md`
- 信号：`docs/SIGNAL_EVENTS.md`、`docs/STAGE9_WECHAT_DELIVERY.md`
- live：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md`、`docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md`
- 工作站：`docs/workstation/`、`docs/workflows/`

## Manifest

| path | category | canonical_source | updated_at | git_commit | current_or_historical | external_gate_pending | sensitive_content_checked | recommended_for_gpt |
|---|---|---|---|---|---|---|---|---|
| `docs/gpt/project_sources/00-INDEX.md` | index | `PROJECT_SOURCE.md`; `STATUS.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/01-PROJECT-SOURCE.md` | project | `PROJECT_SOURCE.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/02-CURRENT-STATUS.md` | status | `STATUS.md`; `tasks/current.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/03-ARCHITECTURE.md` | architecture | `docs/ARCHITECTURE.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/04-DATA-LAYER.md` | data | `docs/DATA_CENTER.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/05-INDICATOR-STRATEGY-KERNEL.md` | indicator/strategy | `packages/quant-core/README.md`; `docs/INDICATOR_KERNEL.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/06-WEB.md` | web | `docs/ARCHITECTURE.md`; `apps/quant-web/src/app/router.ts` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/07-BACKTEST.md` | backtest | `docs/BACKTEST_ENGINE.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/08-SIGNAL-NOTIFICATION.md` | signal | `docs/SIGNAL_EVENTS.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/09-LIVE-RUNTIME-DEPLOYMENT.md` | runtime/deployment | `docs/ARCHITECTURE.md`; `docs/tasks/JM-LIVE-GATE-EVIDENCE.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/10-WORKSTATION-WORKFLOW.md` | workstation | `docs/workstation/`; `docs/workflows/` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/11-DECISIONS.md` | decisions | `DECISIONS.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/12-TESTING-AND-GATES.md` | testing | `TESTING.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/gpt/project_sources/13-NEXT-STEPS.md` | roadmap | `CODEX_TASKS.md`; `docs/gpt/NEXT_STEPS.md` | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `PROJECT_SOURCE.md` | project | self | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `STATUS.md` | status | self | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `DECISIONS.md` | decisions | self | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `CODEX_TASKS.md` | tasks | self | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `TESTING.md` | testing | self | 2026-07-14 | `ec7a698e` | current | yes | yes | yes |
| `docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md` | acceptance | self | 2026-07-12 | `ec7a698e` | historical_acceptance | yes | yes | topic |
| `docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md` | acceptance | self | 2026-07-12 | `ec7a698e` | current_acceptance | yes | yes | topic |

## Document Inventory 分类

完整 inventory 复用 `data/reports/data_stage_closure/document_inventory.csv`。本 manifest 只列 GPT 事实源相关的关键文件分类：

| category | files | action |
|---|---|---|
| canonical_current | `PROJECT_SOURCE.md`; `STATUS.md`; `DECISIONS.md`; `CODEX_TASKS.md`; `TESTING.md`; `docs/DATA_CENTER.md`; `docs/ARCHITECTURE.md`; `docs/BACKTEST_ENGINE.md`; `docs/SIGNAL_EVENTS.md`; `docs/CODEX_HANDOFF.md` | keep/update |
| operational | `docs/workstation/`; `docs/workflows/`; `deploy/nginx/README.md`; `deploy/frp/README.md` | keep |
| current_acceptance | `docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md`; `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`; `docs/tasks/V1-LIVE-RUNTIME-CLOSURE-ACCEPTANCE.md` | keep/reference |
| historical_acceptance | `docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md`; older `docs/tasks/TASK-2026-07-*.md` delivery records | keep as historical |
| current_task | `tasks/current.md` | update |
| completed_task | `tasks/done/`; older task records in `docs/tasks/` | keep |
| generated_evidence | `data/reports/data_stage_closure/`; `data/reports/data_layer_final_audit_phase3_20260712/`; current audit/report directories | reference only |
| temporary_prompt | `docs/gpt/*_REVIEW_PACKAGE.md`; `docs/gpt/*_REVIEW_PROMPT.md` | keep for review context |
| obsolete | old GPT package summaries with replaced facts | mark through updated `docs/gpt/README.md`; do not delete |
| unknown | files not classified by current task | do not delete |

## 敏感信息说明

Manifest 和 Project Sources 只允许出现环境变量名与安全规则说明，不允许出现真实 webhook、token、password、cookie、license、账号或连接串。
