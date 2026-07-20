# WS-SIMPLIFY-01-CANONICAL-DOCS

| Field | Value |
|---|---|
| Task ID | WS-SIMPLIFY-01-CANONICAL-DOCS |
| Branch | `codex/workstation-simplify` |
| Worktree | `/Volumes/扩展盘/guiyi-parallel/workstation-simplify` |
| Status | `DELIVERY_READY` |
| Risk | R1（文档） |
| Date | 2026-07-20 |

## Objective

收敛根目录 canonical：压缩 README / AGENTS，新建 `docs/DEVELOPMENT.md`，更新 STATUS / PROJECT_SOURCE / DECISIONS 工作站模型，不改业务 deep canonical 正文。

## Allowed paths

```text
README.md
AGENTS.md
STATUS.md
PROJECT_SOURCE.md
DECISIONS.md
docs/DEVELOPMENT.md
docs/tasks/WS-SIMPLIFY-01-*.md
```

## Result

- README 改为入口导航，不再堆 WorkBuddy 协议。
- AGENTS 压缩为工程规则（约 120–220 行目标）。
- `docs/DEVELOPMENT.md` 成为唯一开发流程。
- STATUS 写入 `WORKSTATION_SIMPLIFICATION_IN_PROGRESS`，保留 `WORKSTATION_NON_BLOCKING_SUPPORT_MODE`。
- PROJECT_SOURCE / DECISIONS 工作站模型改为 GitHub + GPT + Codex。

## Verification

```bash
git grep -n 'WorkBuddy\|CodeBuddy' -- README.md AGENTS.md STATUS.md PROJECT_SOURCE.md DECISIONS.md docs/DEVELOPMENT.md || true
wc -l AGENTS.md
git diff --check
```
