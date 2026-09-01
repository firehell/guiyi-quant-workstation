# P0 — v1.9.7 Release / Runtime 事实收敛计划

状态：`PLAN_READY_FOR_USER_REVIEW`

父计划：`docs/tasks/2026-09-01-alert-reliability-subing-watch-15m-implementation-plan.md`

Issue：`#286`

Lane：Lane 3 trusted release state，docs-only。

## Goal

只用可读证据收敛 `main`、annotated tag、GitHub Release、API/Web version 和当前五项 launchd exact root。不得借机重新发布、改 tag、切 Runtime、执行 migration、变更 Scope 或发送通知。

## Workspace

```text
base: 执行时最新 origin/develop
branch: docs/release-identity-convergence-v1-9-7
worktree: 新 task worktree
integration: develop
PR: required
independent review: required
```

## Files

- Modify: `STATUS.md`
- Test only: `tests/engineering/test_canonical_consistency.py`

## Task 0.1 — 读取仓库和发布身份

运行：

```bash
git fetch --prune origin
git rev-parse origin/main
git rev-parse origin/develop
git cat-file -t refs/tags/v1.9.7
git rev-list -n 1 v1.9.7
git show --no-patch --format='%H %s' origin/main
git show --no-patch --format='%H %s' v1.9.7
```

若本机已认证 GitHub CLI，再只读运行：

```bash
gh release view v1.9.7 \
  --json tagName,targetCommitish,isDraft,isPrerelease,publishedAt
```

缺少 CLI 或认证时，使用 GitHub connector/API 的只读结果，并在 PR 描述中记录证据来源。不得猜测。

验收：

```text
main commit
annotated tag target commit
GitHub Release target commit
```

三者必须精确一致。若不一致，结论为 `阻塞`，不修改 `STATUS.md`，转为单独 release 修复任务。

## Task 0.2 — 读取 API/Web 与 Runtime 身份

按仓库现有 `deploy/README.md` 只读命令核对：

```text
API version
Web version
Market Runtime exact root
Alert Runtime exact root
after-market runner exact root
当前 rollback root
```

约束：

- 不读取凭据；
- 不修改 launchd；
- 不重启服务；
- 不写 Redis/PostgreSQL；
- 不执行 Runtime switch；
- Runtime 与 Release 不相同可以是合法 pending Gate，但必须在 `STATUS.md` 明确分别记录。

## Task 0.3 — 修改唯一 stale 事实

只修改 `STATUS.md` 中与只读证据冲突的 release identity 句子。必须保留：

- 当前 Runtime 实际绑定版本；
- v1.9.7 promotion 曾 fail-closed 回滚；
- 下一次 Runtime promotion 仍需新授权；
- provider accepted 不等于微信送达；
- 尚未取得的自然 evidence 仍保持 pending。

不得把代码、tag 或 GitHub Release 存在写成 `RUNTIME_READY`。

## Task 0.4 — 文档验证

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  tests/engineering/test_canonical_consistency.py
python3 scripts/engineering/secret_scan.py --json
git diff --check
git diff -- STATUS.md
```

验收：

```text
必要检查全部通过
changed files = STATUS.md only
无 token/Topic/provider reference/私有路径
无 main/tag/Release/Runtime mutation
```

## Task 0.5 — Commit / PR / Gate

```bash
git add STATUS.md
git commit -m "docs: converge v1.9.7 release identity fact"
git push -u origin docs/release-identity-convergence-v1-9-7
```

创建 PR 到 `develop`。PR 描述必须列出：

```text
main/tag/Release exact commit
API/Web version
当前 Runtime exact root
仍 pending 的 Runtime/evidence Gate
实际验证命令与结果
```

最终停止在：

```text
允许集成 develop
```

P0 合入后清理 task worktree/branch。不得创建 release worktree，不得触及 `main`。

## Review Checklist

- 证据是否来自当前 refs，而非旧聊天记录；
- annotated tag 是否解析到 commit target；
- GitHub Release target 是否与 tag 一致；
- Runtime identity 是否与 release identity 分开陈述；
- 是否错误宣布 v1.9.7 Runtime ready；
- 是否只改 `STATUS.md`；
- 是否保留所有未完成 Gate。
