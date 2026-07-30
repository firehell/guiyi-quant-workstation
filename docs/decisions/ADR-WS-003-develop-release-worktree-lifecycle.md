# ADR-WS-003: Develop / Release Worktree Lifecycle

日期：2026-07-29
状态：Accepted（2026-07-30 修订 task→develop 自动集成；远端发布仍逐次用户批准）

## 决策

在既有 GitHub Issue/PR 与人工审查模型上，增加受控的本地 worktree 生命周期：

```text
main checkout                 canonical / release only
GuiyiWorktrees/guiyi-develop  long-lived development trunk checkout
GuiyiWorktrees/tasks/*        disposable task checkouts
GuiyiRuntime/*                independent detached Runtime checkout
```

- task 仅从 `develop` 开发主干创建；任务验收、CI、独立 Review 通过且 PR head SHA
  精确匹配后，可由 Codex 编排层通过 GitHub merge commit 自动合入 `develop`。任务分支
  前缀只允许 `feature/`、`fix/`、`docs/`、`research/`、`refactor/`。
- `main`、`master`、`develop` 是 protected branches；本地 strict preflight 不允许直接开发。
- task worktree 只有 clean，且其 HEAD 已被 integration branch 包含时，才可移除并删除本地 task branch。
- `scripts/engineering/worktree_flow.py` 默认 dry-run；`--apply` 只执行已验证的本地 Git worktree/branch 操作。
- `release-flow.sh publish --expected-sha <sha>` 默认只 dry-run；只有用户批准 `--apply` 后，才在 main/develop
  都 clean 且精确匹配该 SHA 时，以原子 push 更新两条远端分支并回读验证。
- `worktree_flow.py` 不自动 merge 或创建 PR；`task-worktree.sh` 只自动化到 Draft PR。
  Codex 编排层的 task→`develop` merge 独立受 ADR-WS-004 约束。任何层都不得借此修改
  GitHub ruleset、打 tag、创建 Release 或切换 Runtime。

## Release 与 Runtime 边界

未来 release 使用 `develop -> release PR -> main -> annotated vX.Y.Z tag`。tag 与 Runtime promotion
仍是独立用户批准；release 不能替代 Runtime 的业务专用 hash-bound Gate。Runtime 保持 detached，
在 S6-10 / S6-11 的相应外部 Gate 未通过前不得变更。

## 后续启用前置

1. 每次 publish 先 dry-run，核对 bound SHA、clean worktree 和原子 refspec。
2. 用户明确批准后才加 `--apply`；远端 SHA 必须回读匹配。
3. GitHub CLI 必须认证；每次 task merge 前回读 PR base/head、CI、Review 与 mergeability。
4. 本 ADR 授权的是 Codex 对已验证 PR 的精确 GitHub merge commit，不依赖或修改 GitHub
   auto-merge/ruleset 设置；无法核对 exact head 或 checks 时 fail-closed。

## Consequences

保留不恢复旧多控制面、不自动 deploy 的约束。task→`develop` 自动 merge 只处理可逆开发
集成；生产 migration、真实数据写入、删除、release/tag、Runtime/live 与通知继续人工批准。
本 ADR 不引入 TASK runtime 或新的状态源。
