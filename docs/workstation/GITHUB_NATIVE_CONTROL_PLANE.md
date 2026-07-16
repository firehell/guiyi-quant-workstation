# GitHub Native Control Plane

更新时间：2026-07-15

任务：`WS-GH-002`

状态：accepted

## 1. 定位

GitHub Native Control Plane 是归一量化工作站 V3 的 AI 工程控制平面。它不改变量化业务平面，不改变数据链路、策略、回测、信号、复盘或实盘边界。

V3 的目标是消除浏览器 GPT、WorkBuddy、CodeBuddy、Codex、Cursor 和用户之间的人工复制、文件搬运和上下文断层，同时保留现有 V2 TASK Schema、dispatcher、approval、worktree、scope、resource lock、runtime gate 和 `.ai/results` 证据链。

## 2. 权威事实模型

V3 采用五层事实模型。Issue 不取代 TASK，PR 不取代本地证据，GPT 不直接写 main。

| 层级 | 权威位置 | 职责 | 写入者 | 规则 |
|---|---|---|---|---|
| 项目事实 | GitHub `main` 上的 canonical docs | 长期目标、产品边界、架构决策、当前状态 | 用户 / Cursor / 受控任务分支合并 | 不允许 AI 直接写 main |
| 执行契约 | task branch 中的 `docs/tasks/<TASK_ID>.md` | allowed paths、forbidden paths、required tests、risk、approval scope、branch、worktree、Issue、Gate | GPT 可在任务分支创建或修改；Codex 按 TASK 执行 | Issue 不能替代 TASK |
| 生命周期 | GitHub Issue | 需求讨论、状态、远程入口、Plan/Test/Delivery 脱敏摘要 | GPT / WorkBuddy / CodeBuddy 受控回填 | Issue 是生命周期面，不是执行契约 |
| 变更交付 | Draft PR / PR | 设计文档、TASK、diff、CI、review、交付讨论 | GPT 可创建文档类 Draft PR；Codex/Cursor 经任务分支更新 | PR 是共享工作区，不自动 merge |
| 本地证据 | `.ai/results/<TASK_ID>/` | route、Plan、approval、stage logs、test、review、execution summary、evidence index | dispatcher / Codex / CodeBuddy | local-first，只同步脱敏摘要 |

## 3. 核心决策

1. Issue 不取代 TASK。TASK 继续是 dispatcher 和 Codex 的执行契约。
2. GPT 默认只在任务分支写文档、设计和 TASK 契约，不直接改业务代码。
3. GPT 不直接写 `main`。
4. Draft PR 是任务从设计、Plan、Dev、Test 到 Review 的共享容器。
5. `.ai/results/<TASK_ID>/` 保持 local-first，不完整上传 GitHub。
6. WorkBuddy Unified V3 是上班/远程统一协调入口：PM、最少必要专家、文件/文档处理、QA、视觉验收和 delivery reviewer。
7. WorkBuddy 对话和 memory 不是状态源；只能读取 Issue / TASK / PR，并通过 `scripts/ai/workbuddy_task.sh` 白名单 facade 调用既有受控脚本；it must not create a second task state.
8. CodeBuddy 调整为 compatibility-only，Demo 通过后 deprecated；旧任务仍可读取和回退。
9. Codex 仍是唯一核心编码执行器，writer lock 仍使用 `codex`，不新增 `workbuddy` writer。
10. Copilot 只用于明确 R3/L1、单模块、最多 5 文件的小修改。
11. 用户保留 Plan、生产写入、merge 和 deploy 的最终批准权。
12. Cursor 保留人工检查、checkpoint、必要小修和 Git 管理角色，但不得与 Codex 同时写同一 worktree。

## 4. 权限矩阵

| 角色 | 默认允许 | 默认禁止 |
|---|---|---|
| 用户 | 最终确认需求、Plan、生产写入、merge、deploy；决定 Issue/PR 关闭 | 无人值守授权 AI 自动实盘 |
| GPT + GitHub | 读取仓库、Issue、PR、commit、CI；创建 Issue；创建 task branch；在任务分支写 `docs/tasks/**`、`docs/design/**`、`docs/decisions/**`、`docs/workstation/**`；创建文档类 Draft PR；提交 PR Review | 直接写 `main`；直接改业务代码；写数据、DB、运行环境或凭据；自动 merge/deploy/close 高风险任务 |
| WorkBuddy | 读取 Issue、TASK、PR；补充需求；做 PM/QA/视觉验收；生成交付摘要；调用 `scripts/ai/workbuddy_task.sh` 固定命令 | 直接改业务代码、数据链路、策略、回测、数据库；自由 shell；第二状态；模糊审批；替代用户做 merge/deploy 决策 |
| CodeBuddy | compatibility-only：旧 Issue-first / TASK_ID 执行回退；只调用 `scripts/ai/dispatch_task.sh` | 新增编排功能；重解释需求；拼自由 shell 绕过 Gate；直接写业务代码；push/merge/deploy |
| Codex | 在 TASK 指定 branch/worktree 内执行 Plan/Dev/Test/Review/Result；修改 allowed paths 内的代码或文档 | 超出 TASK 范围；绕过 approval/scope/resource lock；自动交易；写凭据；自动 push/merge/deploy |
| Cursor | 人工检查 diff、必要小修、Git checkpoint、人工 merge/push | 未获取 writer lock 时与 Codex 同时写同一 worktree；绕过 TASK/Gate |

## 5. 标准生命周期

### 5.1 新任务创建

```text
用户提出需求
-> GPT 读取 GitHub main canonical docs
-> GPT 创建 Issue
-> GPT 创建 task/<TASK_ID-slug> branch
-> GPT 在任务分支创建 docs/tasks/<TASK_ID>.md 和必要设计文档
-> GPT 创建 Draft PR
-> 用户审查 Issue / TASK / Draft PR 范围
```

### 5.1.1 GPT Issue Creation Rule

所有 GitHub Task Issue 必须使用 [`GITHUB_NATIVE_ISSUE_CONTRACT.md`](GITHUB_NATIVE_ISSUE_CONTRACT.md) 定义的 GitHub Native Issue Contract。GPT + GitHub、WorkBuddy 或人工创建任务 Issue 时，不得自由格式写 Task Issue，不得创建没有 `Task Metadata` 的任务 Issue。

GPT 创建 Issue 时必须包含：

```markdown
## Task Metadata

| Field | Value |
|---|---|
| Task ID | |
| TASK file path | |
| Task branch | |
| Draft PR | |
| Risk Level | |
| Work Level | |
| Status | |
```

`Status` 对应 Issue Contract 中的 `Current Status` 语义。该规则只规范 Issue Body 创建格式，不改变 TASK Schema V2、`docs/tasks/<TASK_ID>.md`、runtime overlay、dispatcher、approval、scope、resource lock、runtime Gate 或 `.ai/results` 证据链。

### 5.2 本地接管

```text
WorkBuddy facade、CodeBuddy 兼容入口或本地 Codex 接收 Issue #N / TASK_ID / PR #N
-> 解析 task branch 和 TASK
-> fetch 远程任务分支
-> 创建或接管独立 worktree
-> scripts/ai/dispatch_task.sh <TASK_ID> plan --json
-> 用户批准 Plan
-> dev / test / review / result
-> 脱敏摘要回填 Issue / PR
```

在 Issue-first bootstrap 脚本落地前，允许继续使用既有 `TASK_ID -> dispatch` 兼容路径。

WorkBuddy 固定入口：

```bash
scripts/ai/workbuddy_task.sh analyze --issue #N
scripts/ai/workbuddy_task.sh plan --issue #N
scripts/ai/workbuddy_task.sh approve --issue #N --confirm-user-approval
scripts/ai/workbuddy_task.sh dev --issue #N
scripts/ai/workbuddy_task.sh delivery --task <TASK_ID>
```

### 5.3 交付和审查

```text
Codex 完成 result
-> Draft PR 更新为 Ready for Review
-> GPT 读取 Issue、TASK、PR diff、CI 和 .ai/results 脱敏摘要
-> GPT 输出 APPROVE / COMMENT / REQUEST_CHANGES
-> 用户最终决定 merge
-> Issue 按用户确认关闭
```

## 6. 与现有 V2 的兼容

V3 必须保留：

- `scripts/ai/dispatch_task.sh <TASK_ID> <stage> [--json]`
- V2 YAML frontmatter TASK
- 旧 Markdown TASK 兼容读取
- `docs/tasks/<TASK_ID>.md` 和 `.ai/tasks/<TASK_ID>.md` fallback
- `scripts/ai/init_task_worktree.sh --task <TASK_ID>`
- `scripts/ai/approve_task.sh --task <TASK_ID>`
- `scripts/ai/run_tests.sh --task <TASK_ID>`
- `scripts/ai/collect_result.sh --task <TASK_ID>`
- `.ai/results/<TASK_ID>/`
- `.ai/approvals/<TASK_ID>.json`
- L1 Issue optional，L2 Issue required 的 fail-closed 规则，直到 Issue-first V3 Gate 明确替代

## 7. 禁止项

- 禁止把 Issue 定义为唯一执行契约。
- 禁止删除 V2 TASK Schema 或 dispatcher 兼容路径。
- 禁止 GPT、WorkBuddy、CodeBuddy、Codex 自动 merge、deploy 或关闭高风险 Issue。
- 禁止任何 Agent 直接写 `.env`、token、webhook、license、cookie、账号凭据。
- 禁止把 `.ai/results` 完整上传到 GitHub；只能回填脱敏摘要和路径索引。
- 禁止 WorkBuddy 对话、memory 或截图成为任务状态源。
- 禁止 WorkBuddy 维护第二状态、自由 shell、自动 retry、模糊审批或裸调 Codex。
- 禁止把企业微信提醒、回测结果或信号自动转成实盘交易指令。

## 8. 当前已知缺口

这些缺口来自 `WS-GH-001` 基线，后续独立 Step 处理：

1. Issue-first bootstrap 尚未实现。
2. GPT 创建的远程 task branch 接管脚本尚未实现。
3. PR template 尚未建立。
4. GPT PR Review protocol 尚未建立。
5. Issue / PR 双向脱敏摘要回填尚未统一。
6. GitHub Actions `workstation-test` 当前因 doctor strict `branch_not_main` 与 `env_check` 红灯，需要单独修复。

## 9. 参考

- `docs/workstation/WORKBUDDY_UNIFIED_V3.md`
- `docs/workstation/WORKSTATION_DOCUMENT_MAP.md`
- `docs/decisions/ADR-WS-001-github-native-control-plane.md`
- `docs/workstation/TASK_SCHEMA_V2.md`
- `docs/workflows/github_issue_trace_workflow.md`
- `CODEBUDDY.md`
- `AGENTS.md`
