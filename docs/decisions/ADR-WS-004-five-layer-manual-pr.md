# ADR-WS-004: Five-Layer Task PR Gate

日期：2026-07-30

状态：Accepted（2026-07-30 经用户明确批准 task→develop 自动集成修订）。

## 决策

在 ADR-WS-003 的本地 worktree 拓扑之上增加五层受控交付：

```text
Codex workspace permission
  -> repository rules and instructions
  -> scripts/engineering/task-worktree.sh
  -> Codex PreToolUse hook
  -> GitHub PR CI (lane-pr-gate)
```

合规的 Lane 1/2 task 可使用 `task-worktree.sh integrate --apply` 执行固定测试、secret scan、
diff check、commit、push，并创建指向 `develop` 的 Draft PR。Lane 3 的代码、测试、dry-run、
隔离 migration 与默认 disabled 功能使用独立 task/PR，但可复用同一集成 Gate。

`task-worktree.sh` 不负责 merge。Codex 编排层在任务验收、CI、独立 Review 全部通过，且
PR base=`develop`、head SHA 与已审查 task HEAD 精确匹配、mergeability 正常时，可将 PR
标记 ready 并通过 GitHub merge commit 自动合入 `develop`，随后回读祖先关系并清理。

## 边界

- Lane 1 仅接受 `experiments/`、测试和研究说明路径；不允许正式策略、回测、信号或报告基线。
- Lane 2 的 `task-worktree.sh` 自动化仍拒绝 migration、raw/parquet、Runtime、通知、部署、
  秘密、治理文件、Codex 配置、CI workflow 和 canonical ADR 路径；它们进入独立 Lane 3
  task/PR，而不是放宽 Lane 2 分类。
- `main`、`develop` 直推、tag、release、Runtime、生产 migration apply、真实 DB/数据写入、
  删除、live enable 与真实通知一律不由本 ADR 自动执行；ADR-WS-003 的 Runtime 隔离和
  hash-bound 业务 Gate 完整保留。
- `task-worktree.sh --apply` 不调用 `gh pr merge`、不修改 GitHub ruleset、也不要求 GitHub Pro。
- Codex merge 前后都必须核对 exact head、CI、独立 Review、远端 `develop` 与祖先关系；
  任何漂移保留 task worktree 并 fail-closed。

## 启用前置

1. 用户对任务总计划或当前 task 范围已有明确批准；不得由 Codex自行扩大。
2. GitHub CLI 已认证且具备 PR ready/merge 权限。
3. 本地任务测试、secret scan、diff check、CI 与独立 Review 全部通过。
4. PR head SHA 与已审查 task HEAD 精确匹配；base 为 `develop` 且 mergeability 正常。
5. 无生产写入、删除、release、Runtime/live 或真实通知副作用；若存在则停在对应人工 Gate。

## 后果与回滚

本地 rules、Hook、脚本、PR CI、Review 或 SHA 核对任一失败时，交付停在对应 Gate，不会绕过
测试、secret scan、路径分类或业务批准。回滚使用 PR revert；本地 task worktree 仍只能在
已合入且 clean 的祖先关系可验证后清理。自动集成 `develop` 不构成任何生产或发布授权。
