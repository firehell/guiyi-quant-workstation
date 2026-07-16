# 当前任务：ALL-BRANCH-WORKTREE-MERGE

生成时间：2026-07-16

状态：`LOCAL_MERGE_COMPLETED_WORKTREES_REMOVED_VALIDATED_WORKSTATION_BASELINE_FIXED`

## 所有本地分支与 worktree 收口

本轮目标是在本地 `main` 上完成受控收口：合并所有尚未进入 `main` 的本地分支，保留 DEMO-004 `.ai` 证据链，验证后删除全部 linked worktree，包括 runtime/live 副本。不 push、不创建 PR、不删除本地分支引用。

保护分支：

```text
backup_branch=codex/backup-main-before-all-worktree-merge-20260716
```

已合并分支：

- `task/demo-20260715-004-github-native-v3-final-acceptance`
- `codex/github-task-resolver-parse-task-meta`

已覆盖分支：

- `codex/ws-gh-013-task-branch-base-validation` 已包含在 DEMO-004 分支历史中，`git merge-base --is-ancestor` 验证返回 0。

本轮保留的关键内容：

- DEMO-004 task 文档、schema / dispatcher / resolver / router test 调整。
- `.ai/results/DEMO-20260715-004-github-native-v3-final-acceptance/` 执行证据。
- `.ai/task-runtime/DEMO-20260715-004-github-native-v3-final-acceptance.json` runtime overlay。
- `codex/github-task-resolver-parse-task-meta` 中优先读取已存在 worktree task 文件的 resolver 与测试逻辑。

已完成 Gate：

1. `git diff --check` 通过。
2. `bash -n scripts/ai/dispatch_task.sh` 通过。
3. `python3 -m pytest -q tests/workstation/test_github_task_resolver.py tests/workstation/test_task_router.py` 通过：`48 passed`。
4. `git branch --no-merged main` 无输出，未发现剩余未合并本地分支。
5. `git worktree remove` / `git worktree prune` 已执行，当前 `git worktree list --porcelain` 仅剩主工程 worktree。

原验证警告（2026-07-16 已修复）：

- `python3 -m pytest -q tests/workstation` 曾为 `447 passed, 21 failed`。
- 对保护分支 `codex/backup-main-before-all-worktree-merge-20260716` 的同命令对照同样为 `447 passed, 21 failed`，说明该全量失败不是本轮合并新增。
- 本轮已修复 baseline 漂移，当前命令通过：`468 passed in 69.09s`。
- `make workstation-test` 当前失败在 strict doctor 的 `branch_not_main: current branch=main`，其余 doctor 项为 `passed=13 failed=1 warn=0 skipped=2`。

本轮追加修复范围：

- 补齐 `tests/workstation` 临时仓库夹具复制的 workstation 脚本与 Python lib 依赖。
- 将 integration routing 场景断言对齐当前 `fast` / `standard` / `critical` tier 语义。
- 修复 dirty / scope gate 内联 Python 写 `__pycache__` 导致 gate 自造未跟踪文件的问题。
- 修复显式 gate 测试被全局 bypass env 影响的问题。
- 修复 model router 降级测试把日志写入真实仓库 `.ai/results/` 的测试隔离问题。

清理结果：

- 已删除 runtime/live 等所有 linked worktree，包括 `/Users/zhangzhao/GuiyiRuntime/guiyi-quant-workstation-runtime` 与 `/Volumes/扩展盘/guiyi-quant-workstation-live-runtime`。
- 已 prune 两条 prunable 失效 worktree 记录。

---

# 当前任务：DIRECTION-A-MAIN-MERGE

生成时间：2026-07-15

状态：`LOCAL_MERGE_COMPLETED_VALIDATED`

## feature/direction-a1-final-sealing-audit 受控合并

本轮目标是在本地完成 `feature/direction-a1-final-sealing-audit` 到 `main` 的受控 merge commit，使 Git 视为已合并，同时保护当前 `main` 的 workstation/GitHub Native V3、Web A01/A02、cross-file conflict warning 和协作事实源。

合并策略：

- 当前 `main` 为事实源优先；旧分支造成的大规模删除默认拒收。
- Direction A 仅接入 profile registry / active binding / lineage、schema contract、residual root cause audit、multi-primary rulebook、数据 manifest/report evidence。
- 前端/API 只补 `profile_id`、`quality_policy`、`market_data_file_id`、`binding_snapshot` 等 profile 元数据通路。
- 不写 DB、不写 Parquet、不调用 RQData、不 push、不删除分支。

当前分支与保护分支：

```text
backup_branch=codex/backup-main-before-direction-a-merge-20260715
integration_branch=codex/merge-direction-a-final-sealing-main
source_branch=feature/direction-a1-final-sealing-audit
```

已完成 Gate：

1. 清除所有 conflict markers。
2. `git diff --check` 通过。
3. 后端 profile / schema / market reader 重点测试通过。
4. 前端 indicator / barTime / marketChartWindow / mainIndicators / build 通过。
5. 已在集成分支生成 merge commit，并 fast-forward 到本地 `main`。

---

# 当前任务：WEB-MARKET-UX-002

生成时间：2026-07-14

状态：`READONLY_DIAGNOSIS_COMPLETE_CHART_DUPLICATE_NOT_REPRODUCED_DATA_WARNING_FOUND`

## Web 品种行情页 1d 重复 K 只读诊断

本轮根据 `/Users/zhangzhao/Downloads/归一量化Web品种行情页交互与UI改版执行手册.md` 启动 `WEB-MARKET-UX-V1`。

A01 已通过：

```text
WEB-MARKET-UX-001 GATE_PASSED
```

当前 Step A02 已完成只读诊断：不修改代码、不写 DB、不写 Parquet、不调用 RQData 下载。

当前 Epic 后续顺序：

```text
A01 十字光标与当前 K 数据联动  # GATE_PASSED
→ A02 1d 重复 K 只读诊断       # 完成，未复现重复
→ A03 1d 重复 K 根因修复
→ B01 状态语义与顶部控制区
→ B02 图表主体布局与右侧检查器
→ B03 指标图层、信号 marker 与上下文联动
→ C01 视觉收口、完整回归与独立 Review
```

本步允许范围：

- 只读调用本地 API：`/api/v1/market/bars`
- 只读复用现有 Web normalize / merge helper 做数量对账
- Playwright 只读观察 Web 图表与 Network response
- `docs/tasks/web-market-ux/WEB-MARKET-UX-002.md`
- `.ai/results/WEB-MARKET-UX-002/result.md`
- `tasks/current.md`

本步禁止范围：

- 不修改业务代码。
- 不写 DB、Parquet、manifest、checksum 或 quality status。
- 不调用 RQData 下载。
- 不修复 1d 重复 K 根因；A02 只输出分层证据、最早重复层和 A03 最小修复范围。

当前进展：

- A01 build blocker 已修复，C2 主图指标类型已收口。
- A01 命令线通过：front-end node tests、`npm --prefix apps/quant-web run build`、`git diff --check`。
- A01 Playwright smoke 通过，当前 worktree 使用替代端口 API `8010` / Web `5174`。
- A02 已完成分层只读诊断：Web 实际 `jm.MAIN 1d` 链路在 API、Web normalize、Web merge、图表层均未复现重复 K。
- 额外只读发现：真实合约 `JM2609 1d quote_mode=true` API response 已唯一化为 76 根 K，但 `quality.status=warning` 且 `cross_file_conflicts=10`。

任务记录：

- `docs/tasks/web-market-ux/WEB-MARKET-UX-001.md`
- `.ai/results/WEB-MARKET-UX-001/result.md`
- `docs/tasks/web-market-ux/WEB-MARKET-UX-002.md`
- `.ai/results/WEB-MARKET-UX-002/result.md`

Gate 状态：

```text
WEB-MARKET-UX-001 GATE_PASSED
WEB-MARKET-UX-002 READONLY_DIAGNOSIS_COMPLETE_CHART_DUPLICATE_NOT_REPRODUCED_DATA_WARNING_FOUND
```

下一步：

1. 暂不进入前端 A03 修复，除非补充 Web 图表重复 K 可复现样本。
2. 若要处理 `JM2609 1d quote_mode=true` 的 `cross_file_conflicts=10`，必须先将 A03 `REPLAN` 为数据事实冲突审查/修复任务。
3. 若后续再次看到重复 K，先记录具体 URL query、重复日期/区间、截图和 Network request URL。
4. 进入下一阶段前建议由浏览器 GPT 复核 A01 diff、A01 smoke 证据和 A02 只读诊断结论。

---

# 前一任务：TASK-2026-07-13-001-DATA-STAGE-CLOSURE-DOC-AUDIT

生成时间：2026-07-13

状态：`DELIVERY_READY_READONLY_DOC_AUDIT`

## 数据阶段收口审计与文档事实源整理

本轮目标是只读审计和文档事实源整理，不写 DB、Parquet、manifest、checksum 或 quality status，不调用 RQData，不删除原始数据，不扩展策略、live、企业微信或自动交易。

输出目录：

```text
data/reports/data_stage_closure/
```

核心产物：

- `asset_inventory.csv`
- `product_period_coverage.csv`
- `contract_role_matrix.csv`
- `manifest_db_consistency.csv`
- `duplicate_or_conflicting_assets.csv`
- `document_inventory.csv`
- `data_stage_closure_summary.md`
- `final_audit/`（本轮复跑的 fail-closed final audit 证据）

当前事实源结论：

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```

Phase 3 DB 口径（`data/reports/data_layer_final_audit_phase3_20260712/`）现在仅作为旧审计模型历史快照保留，不再作为当前确定下载缺口或批量修复清单：

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

本轮 final audit 复跑：

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --project-root /Volumes/扩展盘/guiyi-quant-workstation \
  --output-dir /Volumes/扩展盘/guiyi-parallel/data-stage-closure-doc-audit/data/reports/data_stage_closure/final_audit
```

结果：`db_snapshot_source=manifest_only`，原因是 PostgreSQL 缺密码且 API snapshot 返回 502；该复跑是环境 Gate 证据，不作为数据完成度唯一口径。

关键边界：

- `DATA-PART-TARGET-CLOSURE DELIVERY_READY` 是先前数据部分目标收口结论。
- 更新后的数据层封板验收为 `DATA_LAYER_REAUDIT_REQUIRED`。
- `FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 只代表 manifest 强支持物理历史数据大规模下载，不代表 direct PostgreSQL、quality、Profile binding 或 formal consumer contract 通过。
- 暂停基于旧 `1853 / 34 / 45` 数字的批量修复；下一步先做全历史物理事实盘点与 Audit V2。
- 105 条 `quality_warning` 保持 warning，不升级 passed。
- 当前不能宣称 `DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL`。
- 本轮不授权 Stage 9、企业微信、live runtime、自动交易或实盘。

任务记录：`docs/tasks/TASK-2026-07-13-001-data-stage-closure-doc-audit.md`

GPT 审查包：`docs/gpt/DATA_STAGE_CLOSURE_REVIEW_PACKAGE.md`

---

# 前一任务：POST-DATA-CLOSURE-GATE-EXECUTION

生成时间：2026-07-12

状态：`DELIVERY_READY_SCHEME_B_AND_READINESS`

## 工作站 V1.5 控制平面

状态：`MERGED_TO_MAIN`（TASK-020/021/022/023 `DELIVERY_READY`）

合并记录：

```text
merge_commit=3898ec964107a54d1d62ed625e6a3688493bd174
merged_at=2026-07-12
branch=main
worktree_removed=/Volumes/扩展盘/guiyi-parallel/workstation-router
main_pytest=50 passed
origin/main=pushed
```

主入口：

```bash
scripts/ai/dispatch_task.sh <TASK_ID> <stage>
# stages: route | plan | dev | fix | test | review | result | pause | resume | cancel | status
make workstation-test   # 在 feature 分支上跑；main 上 strict doctor 会因 branch=main 失败，pytest 50 passed
```

验收文档：`docs/tasks/archive/workstation-legacy/V1.5-ACCEPTANCE.md`（历史参考）

## 数据层最终封板 Phase 1 只读审计

状态：`DELIVERY_READY_PHASE1_READONLY_AUDIT`（TASK-2026-07-12-024）

```bash
uv run --project services/quant-api python scripts/rqdata_data_layer_final_audit.py \
  --output-dir data/reports/data_layer_final_audit_20260712
```

关键结论（`data/reports/data_layer_final_audit_20260712/DATA_LAYER_FINAL_AUDIT.md`）：

| 指标 | 数值 |
|---|---:|
| covered_passed | 17203 |
| covered_warning | 105 |
| not_applicable | 1943 |
| stage8_6 82/90 | 仍有效 |
| stage8_6 1326/8 pending | 仍有效 |

声明判定摘要：

- 2020+ `1m` 用户声明：`partial`（目标矩阵仅从 2023 起定义）
- 2023+ `1m` 架构口径：`confirmed`
- 2020+ `1d` / `1w`：`confirmed`
- 上市以来至 2019 年末 `1w`：`rejected`（0/63 pre-2020 covered）
- 主连 + 真实主力：`partial`（85/90 main; 1241/1244 actual）

**Phase 1 不宣布最终封板完成**；pre-2020 周线、duplicate active、orphan files 等待 Phase 2。

证据：`docs/tasks/TASK-2026-07-12-024-data-layer-final-audit-phase1.md`

## 数据层 Phase 2 补齐 + Phase 3 最终验收

状态：历史快照（TASK-025/026）

```text
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 当时未达成
DATA_LAYER_PARTIAL                           # 旧状态标签，已由 A2-01 纠偏为 DATA_LAYER_REAUDIT_REQUIRED
```

Phase 2 已完成：

- duplicate active supersede + widest re-elect：`duplicate_active_rows=0`
- orphan 8 文件登记：`orphan_file_rows=0`
- pre-2020 周线 63 品种 backfill+register

Phase 3 审计（`data/reports/data_layer_final_audit_phase3_20260712/`）：

| 指标 | 数值 |
|---|---:|
| duplicate_active_rows | 0 |
| orphan_file_rows | 0 |
| weekly_pre2020_missing | 34 |
| covered_passed | 15350 |
| metadata_gap | 1853 |
| dominant_main_passed | 0/90（manifest 漂移） |

旧阻塞项写法：manifest/DB 对齐、34 品种 pre-2020 周线、actual 45 条缺口。A2-01 后这些数字保留为旧审计模型历史快照，暂停直接批量修复，等待 Audit V2 重算真实 residual。

验收：`docs/tasks/DATA-LAYER-FINAL-ACCEPTANCE.md`

## 数据内容审计 worktree 收口

状态：`MERGED_TO_MAIN`（TASK-2026-07-11-001 ~ 012 + DATA-PART-TARGET-CLOSURE `DELIVERY_READY`）

合并记录：

```text
merge_commit=8ab908ddad12aadcbe13c2aa493af0a117d5bd2f
merged_at=2026-07-11
branch=main
worktree_removed=/Volumes/扩展盘/guiyi-parallel/data-audit
后续数据审计只在主工程 /Volumes/扩展盘/guiyi-quant-workstation 继续
origin/main=pushed
```

## 前置完成

数据部分：

```text
DATA-PART-TARGET-CLOSURE DELIVERY_READY
```

Target coverage final：

```text
covered_passed=17203
covered_warning=105
metadata_gap=0
not_applicable=273
issue_register_rows=105
quality_warning=105
```

## 本轮 Cursor 执行结果

| Step | 任务 | 状态 |
|---|---|---|
| 1 | TASK-017 Phase 1 dry-run / readiness | `DELIVERY_READY_READONLY_GATE` |
| 2 | TASK-018 方案 B 本机磁盘 runtime 迁移 | `DELIVERY_READY_SCHEME_B_MIGRATION` |
| 3 | TASK-017 T3 runtime 副本 smoke（非交易时段） | `T3_CLOCK_IDLE_NON_TRADING` |
| 4 | report_id=14 trust audit 基线复现 | `DELIVERY_READY_READONLY_AUDIT` |
| 5 | OOS frozen config + CLI | `DELIVERY_READY_OOS_CLI_NO_DB_WRITE` |
| 6 | GPT 同步包刷新 | `DELIVERY_READY_DOC_SYNC` |

## 监督服务与 runtime root

```text
supervised_runtime_root=~/GuiyiRuntime/guiyi-quant-workstation-runtime
branch=ops/local-runtime-disk
dev-healthcheck=passed
post-reboot-verify=passed
```

旧 parallel 绑定 `/Volumes/扩展盘/guiyi-parallel/jm-live-gate` 已 bootout。

当前可标记：

```text
SUPERVISOR_BASE_HEALTH_PASSED
SCHEME_B_MIGRATION_PASSED
POST_DATA_CLOSURE_PHASE1_DRY_RUN_PASSED
T3_RUNTIME_COPY_SMOKE_IDLE_NON_TRADING
```

不可标记：

```text
T3_REAL_PASSED
JM_RUNTIME_READY
LONG_RUNNING_READY
```

## T3-real 待 Gate

- 需 JM 可交易时段。
- 需用户显式确认 Phase 2 真实 live 写入。
- 执行位置：`~/GuiyiRuntime/guiyi-quant-workstation-runtime`。
- 证据：`docs/tasks/JM-LIVE-GATE-EVIDENCE.md` §11–§12。

## OOS 验证

- 基线：`scripts/backtest_trust_audit.py --report-id 14` → audit_status passed。
- 执行 CLI：`scripts/oos_validation_run.py` + `configs/oos/jm_v1b_report14_frozen.json`。
- 默认 `persist_to_db=false`；样本外窗口 `oos_fixed` 已试跑（32 trades，临时报告见 `data/reports/oos_validation_*`）。
- 全窗口批量执行需另开 Codex 任务；不得调参改善收益。

## 关键产出

- `docs/tasks/TASK-2026-07-12-019-macos-scheme-b-migration-impl.md`
- `configs/oos/jm_v1b_report14_frozen.json`
- `scripts/oos_validation_run.py`
- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`（§11–§12 更新）

## 不授权事项

- Stage 9、企业微信、formal event、自动交易
- live scheduler 长期开启
- 105 条 warning 升级为 passed
- 修改 DB schema / Parquet / manifest / quality report
- 打印或提交凭据

## 下一步建议

1. P0：JM 可交易时段 + 用户确认 → T3-real `--once`（TASK-017 Phase 2/3）。
2. P1：OOS 全窗口批量跑 `--run`（不入库）并外部审查。
3. P1：5 交易日长稳 + kill/recovery → 才可评估 `LONG_RUNNING_READY`。
4. P2：真实服务器安全 smoke（Nginx/FRP/401）。

## GPT 同步清单

- `tasks/current.md`
- `docs/gpt/CURRENT_STATE.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/CODEX_HANDOFF.md`
- `docs/tasks/archive/workstation-legacy/V1.5-ACCEPTANCE.md`（历史参考）
- `docs/workstation/ARCHITECTURE.md`
- `docs/tasks/TASK-2026-07-12-020` ~ `023`（工作站 V1.5 控制平面）
- `docs/tasks/JM-LIVE-GATE-EVIDENCE.md`
- `docs/tasks/TASK-2026-07-12-014` ~ `019`
- `configs/oos/jm_v1b_report14_frozen.json`
- `scripts/oos_validation_run.py`
