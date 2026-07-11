# TASK-2026-07-11-004：L0/L1/L2 工作级别与 Worktree 治理

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-004-work-levels-home-direct |
| Work Level | L1 |
| GitHub Issue | 待创建 |
| Branch | feature/work-levels-home-direct |
| Worktree | /Volumes/扩展盘/guiyi-parallel/2026-07-11-004-work-levels-home-direct |
| Status | DELIVERY_READY |
| Created At | 2026-07-11 |
| Owner | local-user |

## 5. 目标

1. 正式定义 L0/L1/L2 工作级别与 Gate 矩阵。
2. 新增 worktree 治理脚本（默认根 `../guiyi-parallel/`）。
3. Plan/Approve/Dev/Result 脚本按级别差异化 Gate（L1 放宽 Issue，不放宽 Plan/Dev/Test）。
4. 生成 worktree registry，登记现有 parallel worktree。

## 6. 不做事项

- 不修改 `apps/`、`services/`、`packages/` 业务代码
- 不 push / merge / deploy
- 不强制迁移主仓库当前 dirty 工作区
- 不删除现有 parallel worktree

## 7. 涉及模块

**允许修改**：

- `docs/workflows/work_levels.md`
- `docs/workflows/worktree_registry.md`
- `docs/workflows/README.md`
- `docs/workflows/ai_delivery_workflow.md`
- `docs/AGENT_WORKFLOW.md`
- `docs/tasks/TASK_TEMPLATE.md`
- `docs/tasks/TASK_TEMPLATE_L1.md`
- `docs/tasks/README.md`
- `docs/tasks/TASK-2026-07-11-004-work-levels-home-direct.md`
- `docs/tasks/examples/TASK-FIXTURE-L1-NO-ISSUE.md`
- `AGENTS.md`
- `CODEBUDDY.md`
- `README.md`
- `workstation/STATION_CONFIG.md`
- `.agents/skills/local-workstation/SKILL.md`
- `scripts/ai/_work_level_lib.sh`
- `scripts/ai/init_task_worktree.sh`
- `scripts/ai/remove_task_worktree.sh`
- `scripts/ai/list_worktrees.sh`
- `scripts/ai/handoff_summary.sh`
- `scripts/ai/upgrade_task_level.sh`
- `scripts/ai/codex_plan.sh`
- `scripts/ai/approve_task.sh`
- `scripts/ai/codex_dev.sh`
- `scripts/ai/collect_result.sh`
- `scripts/ai/make_delivery_summary.sh`

**禁止修改**：

- `.env`、`.env.*`
- `data/`
- `apps/`、`services/`、`packages/`
- `scripts/ai/create_issue_from_task.sh`
- `scripts/ai/link_task_issue.sh`

## 18. 测试清单

### 18.0 自动化测试命令

```bash
bash -n scripts/ai/_work_level_lib.sh scripts/ai/init_task_worktree.sh scripts/ai/remove_task_worktree.sh scripts/ai/list_worktrees.sh scripts/ai/handoff_summary.sh scripts/ai/upgrade_task_level.sh scripts/ai/codex_plan.sh scripts/ai/approve_task.sh scripts/ai/codex_dev.sh scripts/ai/collect_result.sh scripts/ai/make_delivery_summary.sh
scripts/ai/codex_plan.sh --task TASK-FIXTURE-L1-NO-ISSUE --gate-only 2>&1 | grep -q "L1: Issue Gate skipped" || exit 1
scripts/ai/codex_plan.sh --task TASK-FIXTURE-L2-NO-ISSUE --gate-only 2>&1 | grep -q "Issue Gate failed" || exit 1
git diff --check
```

## 19. 验收标准

- L0/L1/L2 文档与 Gate 矩阵完整
- worktree 脚本可创建/列出/收工/升级
- L1 fixture plan 在无 Issue 时通过；L2 fixture 在无 Issue 时失败
- worktree_registry 登记现有 5+ worktree

## 20. 风险点

- Worktree Gate 可能阻断在主仓库误开发（预期行为）
- 历史 parallel worktree 未绑定 TASK 元信息，仅 registry 登记
