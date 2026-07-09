# 任务单目录

本目录存放 V1.1+ 规程化 AI 开发流水线的标准任务单模板与示例。V1.2 起每个 TASK 与 GitHub Issue 1:1 绑定。

## 文件说明

| 文件 | 用途 |
|------|------|
| `TASK_TEMPLATE.md` | 标准任务单模板，含 `## 0. 元信息`（Task ID、GitHub Issue、Branch、PR、Status 等） |
| `examples/` | 已归档的示例任务单，供 CodeBuddy / Codex 引用 |

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

CodeBuddy 执行中的任务单通常保存在 `.ai/tasks/<TASK_ID>.md`（gitignore，不入库）。

示例任务单可复制到 `.ai/tasks/` 后再执行 plan / dev。**进入 plan 前**，TASK 元信息中的 `GitHub Issue` 字段必须已回填。

## 相关文档

- 状态机：[`docs/workflows/status_machine.md`](../workflows/status_machine.md)
- 交付流程：[`docs/workflows/ai_delivery_workflow.md`](../workflows/ai_delivery_workflow.md)
- Issue 留痕：[`docs/workflows/github_issue_trace_workflow.md`](../workflows/github_issue_trace_workflow.md)
