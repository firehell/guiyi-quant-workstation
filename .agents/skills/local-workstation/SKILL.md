---
name: local-workstation
description: 当任务涉及归一量化本地工作站、Cursor、Codex、ChatGPT 外部审查、WorkBuddy、Git、Docker、规则文件、多 Agent 协作流程时使用。
---

# Local Workstation Skill

## 工具分工

- Cursor：主 IDE / 人工检查中心。
- Codex：主力开发 Agent。
- GPT + GitHub：架构、量化逻辑、Issue / TASK / PR / diff 审查；优先直接读取 GitHub，必要时再由用户补充本地 evidence。
- WorkBuddy：上班/远程统一协调入口；PM、最少必要专家、文件/文档处理、QA、视觉验收、交付摘要；只通过白名单 facade 触发受控脚本，不做业务代码 writer。
- CodeBuddy：compatibility-only；旧 Issue-first / TASK_ID 任务回退，不新增编排功能。
- Git：安全绳，大改前 checkpoint。

## 工作级别（L0 / L1 / L2）

详见 [`docs/workflows/work_levels.md`](../../../docs/workflows/work_levels.md)。

| 级别 | 场景 | 关键要求 |
|------|------|---------|
| L0 | 咨询、只读分析 | 无 TASK |
| L1 | 居家 Codex 直控 | TASK + worktree + Plan/Approve/Dev/Test |
| L2 | WorkBuddy 正式交付（CodeBuddy compatibility-only） | 完整 TASK + Issue + 交付报告 |

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
4. WorkBuddy L2 只通过 `scripts/ai/workbuddy_task.sh` 固定命令进入 dispatcher；居家 L1 可直接 dispatcher。
5. Codex 执行核心代码任务（经 `dispatch_task.sh` / 受控子脚本）。
6. Cursor 查看 diff。
7. 本地运行测试。
8. GPT + GitHub 外部审查复杂逻辑。
9. WorkBuddy 生成 QA / 视觉 / 交付摘要。
10. 最终 commit。

## 禁止

- 多个 Agent 同时改同一个文件。
- L1/L2 在主仓库 worktree 直接开发（应使用 parallel worktree）。
- WorkBuddy 重构业务逻辑、维护第二状态或执行自由 shell。
- 外部审查工具直接改仓库。
- 提交密钥、账号、交易密码。
