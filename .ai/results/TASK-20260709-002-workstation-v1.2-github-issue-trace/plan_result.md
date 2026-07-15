# Plan Result — TASK-20260709-002

## 理解摘要

V1.2 在 V1.1 本地流水线之上增加 GitHub Issue 远程留痕层：TASK 元信息、Issue 模板、4 个 gh 脚本、流程文档、CODEBUDDY Issue Gate。

## 拟修改文件

- docs/tasks/TASK_TEMPLATE.md（元信息）
- .github/ISSUE_TEMPLATE/
- docs/workflows/github_*.md、workbuddy_github_issue_usage.md
- scripts/ai/create_issue_from_task.sh 等 4 脚本
- CODEBUDDY.md
- docs/tasks/examples/TASK-20260709-002-*.md

## 开发步骤

1. 分支 feature/workstation-v1.2-github-issue-trace
2. 文档与模板
3. 4 个 gh 脚本
4. CODEBUDDY 更新
5. E2E 验证

## 风险点

- gh 需 auth login
- labels 需一次性创建

## 测试建议

- bash -n scripts/ai/*.sh
- create_issue --dry-run
- 完整 Issue 闭环（需 gh auth）
