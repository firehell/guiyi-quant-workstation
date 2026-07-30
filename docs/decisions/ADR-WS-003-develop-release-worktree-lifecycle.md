# ADR-WS-003: Develop / Release Worktree Lifecycle

日期：2026-07-29
状态：Accepted（本地 develop 与受控发布入口已启用；远端发布仍逐次用户批准）

## 决策

在既有 GitHub Issue/PR 与人工审查模型上，增加受控的本地 worktree 生命周期：

```text
main checkout                 canonical / release only
GuiyiWorktrees/guiyi-develop  local integration checkout
GuiyiWorktrees/tasks/*        disposable task checkouts
GuiyiRuntime/*                independent detached Runtime checkout
```

- task 仅从明确的 integration base 创建；任务分支前缀只允许
  `feature/`、`fix/`、`docs/`、`research/`、`refactor/`。
- `main`、`master`、`develop` 是 protected branches；本地 strict preflight 不允许直接开发。
- task worktree 只有 clean，且其 HEAD 已被 integration branch 包含时，才可移除并删除本地 task branch。
- `scripts/engineering/worktree_flow.py` 默认 dry-run；`--apply` 只执行已验证的本地 Git worktree/branch 操作。
- `release-flow.sh publish --expected-sha <sha>` 默认只 dry-run；只有用户批准 `--apply` 后，才在 main/develop
  都 clean 且精确匹配该 SHA 时，以原子 push 更新两条远端分支并回读验证。
- 不自动 merge、创建 PR、改 GitHub ruleset、打 tag、创建 Release 或切换 Runtime。

## Release 与 Runtime 边界

未来 release 使用 `develop -> release PR -> main -> annotated vX.Y.Z tag`。tag 与 Runtime promotion
仍是独立用户批准；release 不能替代 Runtime 的业务专用 hash-bound Gate。Runtime 保持 detached，
在 S6-10 / S6-11 的相应外部 Gate 未通过前不得变更。

## 后续启用前置

1. 每次 publish 先 dry-run，核对 bound SHA、clean worktree 和原子 refspec。
2. 用户明确批准后才加 `--apply`；远端 SHA 必须回读匹配。
3. 重新认证 GitHub CLI，完成 branch protection/ruleset、Actions 的只读审计。
4. GitHub 自动合并如需启用，必须另行修改项目规则并完成保护规则与 required checks 验证；本 ADR 不授权它。

## Consequences

保留不恢复旧多控制面、且不自动 merge/deploy 的约束。该 ADR 只提供一套最小、可审计且可回滚的
本地 worktree 工具，不引入 TASK runtime 或新的状态源。
