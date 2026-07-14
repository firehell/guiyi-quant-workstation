# 当前任务：PROJECT-FACT-SOURCES-GPT-SOURCES-CLOSURE

生成时间：2026-07-14

状态：`DELIVERY_READY_DOC_SOURCE_CLOSURE`

## 目标

本轮只做项目事实源更新与浏览器 GPT Project Sources 收口：

- 更新仓库当前事实源文档。
- 新增根目录 canonical summary。
- 生成 `docs/gpt/project_sources/` 精简投喂包。
- 生成 `docs/gpt/PROJECT_SOURCE_MANIFEST.md`。

本轮不开发新功能，不修改代码，不写 DB、Parquet、manifest、checksum 或 quality status，不调用 RQData，不删除历史验收文档，不触碰 `.env` 或运行配置。

## 当前事实

当前数据层最终状态：

```text
DATA_LAYER_PARTIAL
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 未达成
```

`DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论，不等于数据层最终封板完成。

Phase 3 DB 口径：

| 指标 | 数值 |
|---|---:|
| covered_passed | 15350 |
| covered_warning | 105 |
| metadata_gap | 1853 |
| not_applicable | 1943 |
| direct_1w_present | 90/90 |
| pre_2020_weekly_covered | 29/63 |
| pre_2020_weekly_missing | 34 |
| duplicate_active_rows | 0 |
| duplicate_or_conflicting_assets | 0 |

## 本轮允许修改

- `README.md`
- `PROJECT_SOURCE.md`
- `STATUS.md`
- `DECISIONS.md`
- `CODEX_TASKS.md`
- `TESTING.md`
- `docs/**/*.md`
- `tasks/**/*.md`

## 本轮禁止修改

- `apps/**`
- `services/**`
- `packages/**`
- `alembic/**`
- `scripts/**`
- `data/**`
- `.env*`
- PostgreSQL / Redis / Parquet / manifest / checksum / quality report

## 已完成步骤

- [x] 只读确认当前分支和工作区：`main...origin/main`，初始工作区干净。
- [x] 确认 `docs/gpt/project_sources/` 与 `docs/gpt/PROJECT_SOURCE_MANIFEST.md` 原先不存在。
- [x] 读取并核对当前事实源：`README.md`、`tasks/current.md`、`docs/gpt/*`、`docs/DATA_CENTER.md`、`docs/ARCHITECTURE.md`、`docs/BACKTEST_ENGINE.md`、`docs/SIGNAL_EVENTS.md`、`docs/CODEX_HANDOFF.md`。

## 待完成步骤

- [x] 更新当前入口文档。
- [x] 生成 GPT Project Sources。
- [x] 运行文档扫描、链接检查、敏感信息检查和 git 范围检查。

## 继承的前一任务状态

前一任务：`TASK-2026-07-13-001-DATA-STAGE-CLOSURE-DOC-AUDIT`

状态：`DELIVERY_READY_READONLY_DOC_AUDIT`

核心产物：

- `data/reports/data_stage_closure/data_stage_closure_summary.md`
- `data/reports/data_stage_closure/document_inventory.csv`
- `docs/tasks/TASK-2026-07-13-001-data-stage-closure-doc-audit.md`
- `docs/gpt/DATA_STAGE_CLOSURE_REVIEW_PACKAGE.md`

前一任务结论继续有效：当前数据层为 `DATA_LAYER_PARTIAL`。
