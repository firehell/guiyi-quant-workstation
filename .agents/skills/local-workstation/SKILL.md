---
name: local-workstation
description: 当任务涉及归一量化本地工作站、Cursor、Codex、ChatGPT 外部审查、WorkBuddy、Git、Docker、规则文件、多 Agent 协作流程时使用。
---

# Local Workstation Skill

## 工具分工

- Cursor：主 IDE / 人工检查中心。
- Codex：主力开发 Agent。
- ChatGPT（外部）：架构和量化逻辑审查，人工粘贴 diff，不接入 IDE。
- WorkBuddy：截图可见 UI 修复，不改业务逻辑。
- Git：安全绳，大改前 checkpoint。

## 工作级别（L0 / L1 / L2）

详见 [`docs/workflows/work_levels.md`](../../../docs/workflows/work_levels.md)。

| 级别 | 场景 | 关键要求 |
|------|------|---------|
| L0 | 咨询、只读分析 | 无 TASK |
| L1 | 居家 Codex 直控 | TASK + worktree + Plan/Approve/Dev/Test |
| L2 | WorkBuddy/CodeBuddy 正式交付 | 完整 TASK + Issue + 交付报告 |

Worktree 默认根：`../guiyi-parallel/`（`GUIYI_WORKTREE_ROOT` 可覆盖）。

```bash
scripts/ai/init_task_worktree.sh --task <TASK_ID>
scripts/ai/handoff_summary.sh --task <TASK_ID>
scripts/ai/list_worktrees.sh
```

## 标准流程

1. `git status`。
2. 大改前 checkpoint。
3. L1/L2：先 `init_task_worktree.sh`，在独立 worktree 开发。
4. Codex 执行单一清晰任务（经 `codex_plan.sh` / `codex_dev.sh`）。
5. Cursor 查看 diff。
6. 本地运行测试。
7. 外部审查复杂逻辑（ChatGPT + docs/CODE_REVIEW.md）。
8. WorkBuddy 只修可见 UI（L2 可选）。
9. 最终 commit。

## 禁止

- 多个 Agent 同时改同一个文件。
- L1/L2 在主仓库 worktree 直接开发（应使用 parallel worktree）。
- WorkBuddy 重构业务逻辑。
- 外部审查工具直接改仓库。
- 提交密钥、账号、交易密码。
