---
name: git-commit-workflow
description: 当任务涉及归一量化仓库 commit、develop push、main release 或 Git 状态核对时使用。
---

# Git Commit Workflow

以仓库根 `AGENTS.md` 与 `docs/DEVELOPMENT.md` 为唯一规则源。本 Skill 只做路由，不创建第二套
branch、worktree、checkpoint、approval packet 或回滚流程。

## 普通 develop 变更

1. 开始前确认 branch、worktree、dirty/index 状态和远端差异。
2. 保留用户与其他任务的改动，只暂存本任务文件。
3. 按 `TESTING.md` 运行与影响面匹配的验证，并执行 `git diff --check` 与 secret scan。
4. 允许按仓库规则直接 commit/push `develop`；不得 force push 或重写历史。

## 独立 Gate

`main`、tag/release、Runtime switch、真实数据/DB mutation 和通知不由普通 commit/push 授权。
每次执行前都要取得范围明确的单次意图；不要把 dry-run、测试、receipt 或历史授权复用为新授权。

## 安全

- 不提交 `.env`、凭据、license、token、密码或仓库外正式数据。
- 不使用 `git reset --hard`、强制 checkout 或批量清理覆盖用户修改。
- 失败时先报告精确状态，不自动重试受控外部操作。
