# 当前任务：阶段 0 V1 重构基线冻结

## 本轮目标

冻结新项目基线，清理旧路线污染，明确后续阶段从 RQData 权限与接口能力 PoC 开始。

## 任务性质

docs-only

## 当前分支

`codex/workstation-cloudflare-healthz`

当前不在 `main`，本轮继续使用当前分支。

## 允许修改范围

- `docs/GUIYI_REBASE_PROJECT_BOOK.md`
- `PROJECT_SNAPSHOT.md`
- `CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/ROADMAP.md`
- `docs/CODEX_HANDOFF_FOR_CHATGPT.md`
- `docs/AI_DEVELOPMENT_WORKFLOW.md`
- `docs/ARCHITECTURE.md`
- `tasks/current.md`

## 禁止事项

- 不改业务代码。
- 不改前端代码。
- 不改策略代码。
- 不改回测代码。
- 不新增 migration。
- 不运行 RQData。
- 不写数据库。
- 不写 `data/`。
- 不启动服务。
- 不做浏览器验收。
- 不写 `.env`、账号、密码、Token、API Key、license、企业微信通知地址或交易密钥。
- 不把实时 1m 入库、企业微信提醒、`signal_events`、Cloudflare Access 部署写成已完成能力。

## 执行步骤

| Step | 状态 | 风险 | 标题 | 允许修改范围 | 验证 |
|---|---|---|---|---|---|
| 0 | done | low | 当前状态核对 | git/docs | `git status --short`; `git branch --show-current` |
| 1 | done | low | 新增 V1 重构项目书 | `docs/GUIYI_REBASE_PROJECT_BOOK.md` | 文档 diff |
| 2 | done | low | 更新快照和当前状态 | `PROJECT_SNAPSHOT.md`, `CURRENT_STATE.md` | 文档 diff |
| 3 | done | low | 更新路线和交接口径 | `docs/NEXT_STEPS.md`, `docs/ROADMAP.md`, `docs/CODEX_HANDOFF_FOR_CHATGPT.md` | 文档 diff |
| 4 | done | low | 更新工作流和架构状态口径 | `docs/AI_DEVELOPMENT_WORKFLOW.md`, `docs/ARCHITECTURE.md` | 文档 diff |
| 5 | done | low | 最终验证 | docs/tasks | `git diff --check`; `rg` 文本检查 |

## 验收标准

- [x] 新增或更新 `docs/GUIYI_REBASE_PROJECT_BOOK.md`。
- [x] `PROJECT_SNAPSHOT.md` 已切换到新重构基线。
- [x] `CURRENT_STATE.md` 已说明当前处于阶段 0 重构基线冻结。
- [x] `docs/NEXT_STEPS.md` 已按新阶段路线重排。
- [x] `docs/ROADMAP.md` 没有把 V1 写成自动实盘。
- [x] `docs/CODEX_HANDOFF_FOR_CHATGPT.md` 已说明旧聊天只作历史参考，新需求为 canonical baseline。
- [x] `docs/AI_DEVELOPMENT_WORKFLOW.md` 只做必要补充，没有破坏现有模板。
- [x] `tasks/current.md` 已更新为阶段 0 当前任务。
- [x] 文档中没有真实账号、密码、Token、API Key、license 或通知地址。
- [x] 文档没有把未完成能力写成已完成。
- [x] 没有修改业务代码。
- [x] 没有运行 RQData。
- [x] 没有写数据库。
- [x] 没有写 `data/`。
- [x] 没有新增依赖。
- [x] 没有新增 migration。

## 测试命令

```bash
git status --short
git branch --show-current
find . -maxdepth 3 \( -name "PROJECT_SNAPSHOT.md" -o -name "CURRENT_STATE.md" -o -name "ROADMAP.md" -o -name "CODEX_HANDOFF_FOR_CHATGPT.md" -o -name "AI_DEVELOPMENT_WORKFLOW.md" -o -name "NEXT_STEPS.md" -o -name "GUIYI_REBASE_PROJECT_BOOK.md" -o -path "./tasks/current.md" \)
git diff --check
git diff --stat
git diff -- PROJECT_SNAPSHOT.md CURRENT_STATE.md docs/NEXT_STEPS.md docs/ROADMAP.md docs/CODEX_HANDOFF_FOR_CHATGPT.md docs/AI_DEVELOPMENT_WORKFLOW.md docs/GUIYI_REBASE_PROJECT_BOOK.md docs/ARCHITECTURE.md tasks/current.md
```

额外文本检查：

```bash
rg -n "系统已经实现实时 1m 入库|系统已经实现企业微信提醒|系统已经实现 signal_events|TqSdk 当成 V1 主数据源|TuShare 当成 V1 主链路|AKShare 当成 V1 主链路" PROJECT_SNAPSHOT.md CURRENT_STATE.md docs/NEXT_STEPS.md docs/ROADMAP.md docs/CODEX_HANDOFF_FOR_CHATGPT.md docs/AI_DEVELOPMENT_WORKFLOW.md docs/GUIYI_REBASE_PROJECT_BOOK.md docs/ARCHITECTURE.md tasks/current.md
rg -n "https://.*webhook|license_key\\s*=|password\\s*=|token\\s*=|secret\\s*=" PROJECT_SNAPSHOT.md CURRENT_STATE.md docs/NEXT_STEPS.md docs/ROADMAP.md docs/CODEX_HANDOFF_FOR_CHATGPT.md docs/AI_DEVELOPMENT_WORKFLOW.md docs/GUIYI_REBASE_PROJECT_BOOK.md docs/ARCHITECTURE.md tasks/current.md
```

## 不运行的测试

```bash
uv run --project services/quant-api pytest -q
cd apps/quant-web && pnpm build
```

原因：本轮只修改 Markdown 文档和任务入口，未修改业务代码、前端代码、策略、回测或数据库。

## 下一步

阶段 1：RQData 权限与接口能力 PoC，只读执行。

阶段 1 默认不写 `data/`，不写数据库，不运行真实数据写入任务，不打印 licence。
