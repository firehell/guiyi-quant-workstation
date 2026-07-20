# 工作流规程目录

本目录是 WorkBuddy Unified V3 / GitHub Native 控制平面的 active 工作流文档位置。V1.1/V1.2 旧流程只作为历史兼容背景。

## 文件说明

| 文件 | 用途 |
|------|------|
| `work_levels.md` | L0/L1/L2 工作级别与 Home Direct Mode |
| `worktree_registry.md` | 当前 worktree 登记（`list_worktrees.sh --write-registry` 生成） |
| `status_machine.md` | 任务状态机（10 状态 + Gate 对齐） |
| `ai_delivery_workflow.md` | WorkBuddy Unified V3 主流程：GitHub Issue / TASK / PR + WorkBuddy facade + Codex |
| `workbuddy_role.md` | WorkBuddy 职责边界 |
| `github_issue_trace_workflow.md` | V1.2 GitHub Issue 任务留痕流程 |
| `GITHUB_DRAFT_PR_WORKFLOW.md` | GitHub Native V3 Draft PR 任务工作区协议 |
| `GPT_GITHUB_REVIEW_WORKFLOW.md` | GPT 外部 PR Review Gate 与 head SHA 绑定规则 |
| `github_labels.md` | GitHub Label 体系与一次性创建命令 |
| `workbuddy_github_issue_usage.md` | WorkBuddy 生成 Issue 内容与交付回填格式 |

## 相关入口

- 企微专项流程：[`docs/AI_WECHAT_WORKFLOW.md`](../AI_WECHAT_WORKFLOW.md)
- WorkBuddy 远程规则：[`docs/workstation/WORKBUDDY_UNIFIED_V3.md`](../workstation/WORKBUDDY_UNIFIED_V3.md)
- CodeBuddy 兼容说明：[`CODEBUDDY.md`](../../CODEBUDDY.md)
- 交付检查清单：[`docs/delivery_checklist.md`](../delivery_checklist.md)
- 任务单目录：[`docs/tasks/`](../tasks/)
