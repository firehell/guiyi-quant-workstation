# 任务单目录

本目录存放 V1.1 规程化 AI 开发流水线的标准任务单模板与示例。

## 文件说明

| 文件 | 用途 |
|------|------|
| `TASK_TEMPLATE.md` | 标准任务单模板，WorkBuddy 生成任务单时必须遵循 |
| `examples/` | 已归档的示例任务单，供 CodeBuddy / Codex 引用 |

## 运行时任务

CodeBuddy 执行中的任务单通常保存在 `.ai/tasks/<TASK_ID>.md`（gitignore，不入库）。

示例任务单可复制到 `.ai/tasks/` 后再执行 plan / dev。

## 相关文档

- 状态机：[`docs/workflows/status_machine.md`](../workflows/status_machine.md)
- 交付流程：[`docs/workflows/ai_delivery_workflow.md`](../workflows/ai_delivery_workflow.md)
