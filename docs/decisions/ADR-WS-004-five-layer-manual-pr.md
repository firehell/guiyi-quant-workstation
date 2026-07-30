# ADR-WS-004: Five-Layer Manual PR Gate

日期：2026-07-30

状态：Proposed — bootstrap PR 合入前只允许 dry-run。

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
diff check、commit、push，并创建指向 `develop` 的 draft PR。PR 的 ready-for-review 与 merge 始终由
用户在 GitHub 手动执行。

## 边界

- Lane 1 仅接受 `experiments/`、测试和研究说明路径；不允许正式策略、回测、信号或报告基线。
- Lane 2 自动化拒绝 migration、raw/parquet、Runtime、通知、部署、秘密、治理文件、Codex 配置、
  CI workflow 和 canonical ADR 路径；它们保持人工审查或 Lane 3。
- `main`、`develop` 直推、tag、release、Runtime、真实 DB/数据/通知一律不自动执行；ADR-WS-003
  的 Runtime 隔离和 hash-bound 业务 Gate 完整保留。
- `task-worktree.sh --apply` 不调用 `gh pr merge`、不修改 GitHub ruleset、也不要求 GitHub Pro。

## 启用前置

1. bootstrap PR 已由用户审查合入。
2. GitHub CLI 已认证且有创建 feature branch PR 的权限。
3. Lane 1 与 Lane 2 各完成一次无业务风险 Pilot，并保留 PR/CI/人工 merge/cleanup 证据。
4. 若未来希望 GitHub 强制分支保护或 required checks，再单独取得 GitHub Pro/Team/Enterprise 与用户批准；
   这不是本 ADR 的前置。

## 后果与回滚

本地 rules、Hook、脚本和 PR CI 任一失败时，交付停在对应 Gate，不会绕过测试、secret scan 或路径分类。
回滚仅需 revert 本 ADR 实现；本地 task worktree 仍只能在已合入且 clean 的祖先关系可验证后清理。
