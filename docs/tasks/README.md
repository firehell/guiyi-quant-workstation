# 任务单目录

本目录存放 WorkBuddy Unified V3 / GitHub Native 控制平面的标准任务单模板、当前任务与少量历史示例。V1.2 起每个正式 L2 TASK 与 GitHub Issue 1:1 绑定；当前 active 入口以 WorkBuddy facade / dispatcher / Codex 为准。

## 文件说明

| 文件 | 用途 |
|------|------|
| `TASK_TEMPLATE.md` | 标准任务单模板（L2），含 `## 0. 元信息`（Task ID、Work Level、GitHub Issue、Branch、Worktree、Status 等） |
| `TASK_TEMPLATE_L1.md` | L1 居家轻量模板（Issue 可选） |
| `examples/` | 历史示例/fixture 任务单，供回归测试和旧流程追溯；不作为当前流程 canonical |
| `archive/workstation-legacy/` | 已归档的旧工作站任务和验收样例 |

## TASK 与 GitHub Issue 映射

```text
一个 TASK ↔ 一个 GitHub Issue（1:1）
TASK 文件 = 本地标准源
GitHub Issue = 远程留痕源
```

- 创建 Issue：`scripts/ai/create_issue_from_task.sh <task_file>`
- 回填编号：`scripts/ai/link_task_issue.sh <TASK_ID> <ISSUE_NUMBER> [task_file]`
- 流程说明：[`docs/workflows/github_issue_trace_workflow.md`](../workflows/github_issue_trace_workflow.md)

## 运行时任务

运行时任务单通常保存在 `.ai/tasks/<TASK_ID>.md`（gitignore，不入库）。CodeBuddy 仅作为 compatibility-only 旧入口。

示例任务单可复制到 `.ai/tasks/` 后再执行 plan / dev。**进入 plan 前**，TASK 元信息中的 `GitHub Issue` 字段必须已回填。

## 相关文档

- 状态机：[`docs/workflows/status_machine.md`](../workflows/status_machine.md)
- 工作级别：[`docs/workflows/work_levels.md`](../workflows/work_levels.md)
- Worktree 登记：[`docs/workflows/worktree_registry.md`](../workflows/worktree_registry.md)
- 交付流程：[`docs/workflows/ai_delivery_workflow.md`](../workflows/ai_delivery_workflow.md)
- Issue 留痕：[`docs/workflows/github_issue_trace_workflow.md`](../workflows/github_issue_trace_workflow.md)
