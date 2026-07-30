# Worktree 与 Release 工作流

本地 worktree 工具不操作远端；受控发布只由 `release-flow.sh` 执行。GitHub ruleset、auto-merge、
tag、Release 和 Runtime promotion 都不属于该脚本能力。ADR-WS-004 仅自动化本地验证、commit、push
与 draft PR 创建；它不改变本节的 release、Runtime 与人工 merge Gate。

## 拓扑

```text
guiyi-quant-workstation                 main（canonical）
GuiyiWorktrees/guiyi-develop            develop（启用后只做集成）
GuiyiWorktrees/tasks/<task-id>-<slug>   task（可清理）
GuiyiRuntime/guiyi-quant-workstation-runtime  detached Runtime
```

## 本地命令

所有命令先 dry-run；只有确认输出中的 `planned_commands`、工作区和 base SHA 无误后才加 `--apply`。

```bash
python3 scripts/engineering/worktree_flow.py audit --json

# develop 仅在当前仓库 clean、base 已验证且用户允许本地创建后执行。
python3 scripts/engineering/worktree_flow.py init --base-ref main --json

# 正式启用后 task 默认应从 origin/develop 创建。
python3 scripts/engineering/worktree_flow.py task-create \
  --kind feature --task-id ISSUE-123 --slug concise-name --json

# 手工 PR/merge 后，且 task HEAD 已成为 develop 祖先时才可清理。
python3 scripts/engineering/worktree_flow.py task-cleanup \
  --integration-branch develop \
  --task-path /Volumes/扩展盘/GuiyiWorktrees/tasks/ISSUE-123-concise-name --json
```

`--apply` 不会绕过 clean、branch prefix、ancestor 或 managed-path 检查。它也不会删除 `main`、
`develop`、detached Runtime 或历史遗留 branch。

## Lane 1/2 受控 PR（尚未启用）

在 bootstrap 合入且双 Pilot 均有证据后，合规 task 可以使用唯一的受控入口：

```bash
# create / cleanup 仍是本地操作；integrate 默认只打印计划。
bash scripts/engineering/task-worktree.sh create --kind research --task-id ISSUE-123 \
  --slug concise-name --lane 1 --issue 123 --json
bash scripts/engineering/task-worktree.sh integrate --lane 1 --issue 123 \
  --test-profile engineering --commit-message "research: #123 concise change" --json
```

只有 `integrate --apply` 会依次执行固定测试、secret scan、diff check、commit、push 和 draft PR 创建；
它不读取/修改 GitHub protection，也不调用 `gh pr merge`。Lane 1 仅限隔离实验/测试/研究文档；Lane 2
排除 migration、raw/parquet、live/signal/notification、Runtime、部署、`.codex`、GitHub 配置和治理文件。
用户在 GitHub 手动审查、标记 ready 和 merge；完整启用条件见 ADR-WS-004。

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
