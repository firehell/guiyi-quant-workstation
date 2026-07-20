# GitHub Issue 任务留痕流程（Lean V1）

一个 TASK 对应一个 GitHub Issue。TASK 是本地标准源，Issue 是远程留痕源，`.ai/results/<TASK_ID>/` 是本地运行证据目录。

## 标准流程（13 步）

1. WorkBuddy 生成完整 TASK。
2. 用户确认 TASK 的范围和 Gate。
3. `create_issue_from_task.sh` 创建 Issue。
4. `link_task_issue.sh` 把 `#N` 回填 TASK。
5. `codex_plan.sh --task <TASK_ID>` 执行只读 Plan。
6. `comment_issue_result.sh <TASK_ID> plan` 回填 Plan。
7. 用户审阅并明确批准 Plan。
8. `approve_task.sh --task <TASK_ID>` 生成 Plan 哈希审批凭证。
9. `codex_dev.sh --task <TASK_ID>` 开发并运行 TASK 测试。
10. `collect_result.sh` 收集结果，`comment_issue_result.sh ... test` 回填测试摘要。
11. WorkBuddy 基于脱敏结果生成交付报告。
12. `comment_issue_result.sh ... delivery` 回填交付报告。
13. 用户人工 review，决定 commit/push/merge，并手工关闭 Issue。

## Issue 与审批 Gate

- TASK `GitHub Issue` 必须严格为 `#N`，否则 Plan/Dev 停止。
- `APPROVED_DEV` 必须存在 `.ai/approvals/<TASK_ID>.json`。
- 当前 Plan SHA256 必须与审批记录一致；变化后必须重新批准。
- 当前分支必须匹配 TASK Branch，且不能是 `main/master`。
- 不自动创建 PR、push、merge、deploy 或关闭 Issue。

## 命令

```bash
scripts/ai/create_issue_from_task.sh docs/tasks/<TASK_ID>.md
scripts/ai/link_task_issue.sh <TASK_ID> <ISSUE_NUMBER> docs/tasks/<TASK_ID>.md

scripts/ai/codex_plan.sh --task <TASK_ID>
scripts/ai/comment_issue_result.sh <TASK_ID> plan
scripts/ai/update_issue_status.sh <TASK_ID> PLAN_READY

scripts/ai/approve_task.sh --task <TASK_ID>
scripts/ai/update_issue_status.sh <TASK_ID> APPROVED_DEV
scripts/ai/codex_dev.sh --task <TASK_ID>
scripts/ai/collect_result.sh --task <TASK_ID>
scripts/ai/make_delivery_summary.sh --task <TASK_ID>
scripts/ai/comment_issue_result.sh <TASK_ID> test
scripts/ai/update_issue_status.sh <TASK_ID> DELIVERY_READY
```

Plan、Result Bundle、test result 和 delivery report 均位于 `.ai/results/<TASK_ID>/`。Issue comment 只能使用脱敏后的产物，不直接附完整运行日志。

## 关闭规则

`update_issue_status.sh` 默认只同步状态标签，不关闭 Issue。只有用户明确决定后才允许 `--close`；仍不得自动 push、merge、deploy。

## TASK 搜索顺序

相关脚本统一优先查找 `docs/tasks/<TASK_ID>.md`，再 fallback `.ai/tasks/<TASK_ID>.md` 与 `docs/tasks/examples/<TASK_ID>.md`（仅兼容历史示例）。
