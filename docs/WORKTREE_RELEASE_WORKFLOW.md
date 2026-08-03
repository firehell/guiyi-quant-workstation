# Worktree 与 Release 工作流

`worktree_flow.py` 只管理本地 worktree；`task-worktree.sh` 可推送 task branch 并创建
Draft PR；release refs 的受控发布只由 `release-flow.sh` 执行。GitHub ruleset、tag、Release
和 Runtime promotion 都不属于这些脚本的自动化能力。ADR-WS-004 将 task 集成分为两层：
`task-worktree.sh` 只自动化验证、commit、push 与 Draft PR；Codex 编排层在验收、CI、独立
Review 和 exact-head Gate 后，可通过 GitHub merge commit 自动合入 `develop`。该规则不改变
release、Runtime 或任何真实副作用人工 Gate。

## 拓扑

```text
guiyi-quant-workstation                 main（canonical）
GuiyiWorktrees/guiyi-develop            develop（长期开发主干）
GuiyiWorktrees/tasks/<task-id>-<slug>   task（可清理）
GuiyiRuntime/guiyi-quant-workstation-runtime  detached Runtime
```

## 本地命令

所有命令先 dry-run；只有确认输出中的 `planned_commands`、工作区和 base SHA 无误后才加 `--apply`。

```bash
python3 scripts/engineering/worktree_flow.py audit --json

# develop 仅在当前仓库 clean、base 已验证且用户允许本地创建后执行。
python3 scripts/engineering/worktree_flow.py init --base-ref main --json

# task 默认从 develop 创建，经 PR/CI/独立 Review 后受控合入 develop。
python3 scripts/engineering/worktree_flow.py task-create \
  --kind feature --task-id ISSUE-123 --slug concise-name --json

# PR merge 后，且 task HEAD 已成为 develop 祖先时才可清理。
python3 scripts/engineering/worktree_flow.py task-cleanup \
  --integration-branch develop \
  --task-path /Volumes/扩展盘/GuiyiWorktrees/tasks/ISSUE-123-concise-name --json
```

`--apply` 不会绕过 clean、branch prefix、ancestor 或 managed-path 检查。它也不会删除 `main`、
`develop`、detached Runtime 或历史遗留 branch。

## 受控 task PR 与 develop 自动集成

在 bootstrap 合入且双 Pilot 均有证据后，合规 task 可以使用唯一的受控入口：

```bash
# create / cleanup 仍是本地操作；integrate 默认只打印计划。
bash scripts/engineering/task-worktree.sh create --kind research --task-id ISSUE-123 \
  --slug concise-name --lane 1 --issue 123 --json
bash scripts/engineering/task-worktree.sh integrate --lane 1 --issue 123 \
  --test-profile engineering --commit-message "research: #123 concise change" --json
```

只有 `integrate --apply` 会依次执行固定测试、secret scan、diff check、commit、push 和
Draft PR 创建；它不读取/修改 GitHub protection，也不调用 `gh pr merge`。Lane 1 仅限隔离
实验/测试/研究文档；Lane 2 排除 migration、raw/parquet、live/signal/notification、Runtime、
部署、`.codex`、GitHub 配置和治理文件。

后续 merge 由 Codex 编排层独立执行：重新确认任务验收、CI、独立 Review、base/head SHA 与
mergeability；任一事实漂移即停止。Lane 3 的 code/test/dry-run/隔离 migration/disabled-only
PR 可走同一 develop 集成 Gate，但生产 apply、真实写入、删除、release、Runtime/live 和通知
必须停在人工 Gate。完整边界见 ADR-WS-004。

## 发布与 Runtime

release 必须以用户批准的 PR 合入 main。仅在 main 与 develop 都 clean 且精确指向同一 commit 后，
用户可将该 SHA 绑定到一次原子远端发布：

```bash
bash scripts/engineering/release-flow.sh publish --expected-sha <40位小写SHA> --json
bash scripts/engineering/release-flow.sh publish --expected-sha <40位小写SHA> --apply --json
```

默认是 dry-run；`--apply` 只以精确 SHA 原子更新 `origin/main` 与 `origin/develop`，随后验证远端
两分支。它不打 tag、不创建 Release、不合并 PR，也不切换 Runtime。annotated tag 与 Runtime promotion
继续使用独立批准和业务 Gate；不可用 worktree 工具、release 批准或 S6-11 计划替代。

在运行任何业务专用 Runtime Gate 前，可使用以下只读校验封装绑定 annotated tag、detached Runtime 和
approval packet 哈希；它不写 Runtime，`promote --apply` 也会明确拒绝通用 promotion：

```bash
bash scripts/engineering/runtime-promotion.sh verify \
  --runtime-root <detached-runtime> --expected-tag <annotated-tag> \
  --approval-packet <packet.json> --approval-hash <64位sha256> --json
```
