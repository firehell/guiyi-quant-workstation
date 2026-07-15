# GitHub Native Issue Contract

更新时间：2026-07-15

任务：`WS-GH-010-1`

状态：contract frozen

## 1. 定位

GitHub Native Issue Contract 是 V3 工作站流程中 GitHub Issue Body 的机器可读协议。它用于打通以下链路：

```text
GPT Browser GitHub 创建 Issue
-> GitHub Issue Body Schema
-> github_task_resolver.py
-> TASK Schema V2 / dispatcher
```

Issue 仍然是生命周期和远程入口，不替代 TASK。可执行契约仍然是 task branch 中的 `docs/tasks/<TASK_ID>.md`，本地执行仍然经过 `scripts/ai/dispatch_task.sh <TASK_ID> <stage>`。

本文件只冻结 Issue Body 协议；不修改 Issue Template、resolver、dispatcher 或测试。

## 2. Issue Metadata Schema

所有 GitHub Native V3 Task Issue 必须在 Issue Body 中包含下面的 Markdown table，并使用固定标题：

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
| Approval Scope | |
| Current Status | |
```

字段名区分规范写法。后续 parser 可以在过渡期兼容旧字段名，但新的 GPT / WorkBuddy / 人工创建 Issue 必须使用本表。

## 3. Required Fields

以下字段是 Issue Contract 必填字段：

| Field | Requirement |
|---|---|
| `Task ID` | 全局任务 ID，必须与 TASK frontmatter 或旧 Markdown 元信息一致。 |
| `TASK file path` | TASK 文件路径，通常为 `docs/tasks/<TASK_ID>.md`。 |
| `Task branch` | 远程任务分支，通常为 `task/<slug>` 或受控 `codex/<slug>`。 |
| `Risk Level` | `R0` / `R1` / `R2` / `R3`。 |
| `Work Level` | `L0` / `L1` / `L2`。 |
| `Current Status` | 本 Issue 当前任务状态，必须来自状态枚举。 |

缺少任一必填字段时，`github_task_resolver.py` 后续实现必须 fail-closed，不得猜测或从标题中隐式推断。

## 4. Optional Fields

以下字段是 Issue Contract 可选字段：

| Field | Requirement |
|---|---|
| `Draft PR` | Draft PR / PR 引用，建议使用 `#N`；尚未创建时可填 `pending`。 |
| `Epic ID` | 所属 Epic，例如 `WORKSTATION-GH-NATIVE-V3`。 |
| `Owner` | 当前负责人，例如 `GPT`、`WorkBuddy`、`CodeBuddy`、`Codex`、`Cursor`、`User`。 |
| `Depends On` | 前置 TASK ID 列表，多个值用逗号分隔。 |

可选字段不得覆盖 TASK 中的安全契约字段。若 Issue 与 TASK 冲突，后续 resolver 必须报告冲突，并以 fail-closed 为默认行为。

## 5. Status Values

Issue Contract 的 `Current Status` 使用工作站 V3 状态词。当前冻结的最小状态集如下：

```text
REQUIREMENT_READY
PLAN_READY
APPROVED_DEV
EXECUTING
TESTING
DELIVERY_READY
CLOSED
```

兼容说明：

- `REQUIREMENT_READY`：需求和 TASK 元信息已足够进入 plan。
- `PLAN_READY`：Plan 已生成，等待用户审批或进入审批后阶段。
- `APPROVED_DEV`：用户已批准进入开发或修复阶段。
- `EXECUTING`：Codex / CodeBuddy 正在受控执行。
- `TESTING`：执行已进入测试或验证阶段。
- `DELIVERY_READY`：结果包和交付摘要已准备好由用户 / GPT / Cursor 审查。
- `CLOSED`：生命周期关闭，不可作为新的本地执行入口。

若旧 TASK Schema V2 状态使用 `APPROVED`，Issue Contract 层的新建 Issue 应优先写 `APPROVED_DEV`。后续 resolver 兼容旧状态时必须显式记录兼容路径，不能静默改变 TASK 状态。

## 6. Field Mapping To TASK

Issue Contract 字段与 TASK Schema V2 / V3 字段的映射如下：

| Issue Field | TASK field | Notes |
|---|---|---|
| `Task ID` | `task_id` / `Task ID` | 必须完全一致。 |
| `TASK file path` | TASK 文件位置 | 必须能从对应 `Task branch` 读取。 |
| `Task branch` | `branch` / `Branch` | 必须与 TASK 静态契约一致。 |
| `Draft PR` | `github_pr` | 可为空或 `pending`，有值时建议 `#N`。 |
| `Risk Level` | `risk_level` / `Risk Level` | 必须一致；不一致时 fail-closed。 |
| `Work Level` | `work_level` / `Work Level` | 必须一致；不一致时 fail-closed。 |
| `Approval Scope` | `approval_scope` / `Approval Scope` | 可为空；有值时必须与 TASK 安全契约兼容。 |
| `Current Status` | `status` / `Status` | Issue 生命周期状态不得绕过 TASK Gate。 |
| `Epic ID` | `epic_id` | 可选。 |
| `Owner` | `owner` | 可选。 |
| `Depends On` | `depends_on` | 可选。 |

后续 resolver 应先读取 Issue Contract，再从 `Task branch` 读取 TASK，并对关键字段做一致性校验。Issue 不得单独授权改变 `allowed_paths`、`forbidden_paths`、`required_tests`、`risk_level`、`work_level` 或 `approval_scope`。

## 7. Parser Requirements

后续 `github_task_resolver.py` 修改必须遵守：

1. 优先解析 `## Task Metadata` 下的 Markdown table。
2. 必填字段缺失、为空或格式非法时 fail-closed。
3. Issue state 不是 open 时 fail-closed，`Current Status=CLOSED` 时 fail-closed。
4. `TASK file path` 只允许 `docs/tasks/**` 或明确兼容的 `.ai/tasks/**` 路径；不得接受 `.env`、`data/**` 或任意 shell 路径。
5. Issue 中的 `Task ID`、`Task branch`、`Risk Level`、`Work Level`、`Approval Scope`、`Current Status` 必须与 TASK 静态契约做一致性或兼容性校验。
6. Issue 不得覆盖 TASK 的安全契约；runtime overlay 也不得覆盖安全契约。
7. 解析失败必须给出可审查错误，不得 fallback 到主仓库、默认分支或模糊 TASK 搜索。

## 8. Creation Requirements

GPT Browser GitHub、人工、WorkBuddy 创建 Task Issue 时必须：

1. 使用 `## Task Metadata` 表。
2. 填写所有必填字段。
3. 不粘贴完整 TASK 正文。
4. 不写入 `.env`、token、webhook、cookie、license、账号或密码。
5. 不把 Issue 描述成自动 merge、自动 deploy、自动关闭或自动交易授权。
6. 明确 Issue 是 lifecycle / remote entry，TASK 是 executable contract。

## 9. WS-GH-010 Follow-up Slices

本协议冻结后，后续任务按以下顺序小步执行：

| Step | Scope | Notes |
|---|---|---|
| `WS-GH-010-2` | 更新 GPT / Agent 创建规范 | 让 GPT、WorkBuddy、人工创建 Issue 时使用本 Contract。 |
| `WS-GH-010-3` | 更新 GitHub Issue Template | 将 `.github/ISSUE_TEMPLATE/task.md` 改为 `## Task Metadata` 表。 |
| `WS-GH-010-4` | 修改 resolver 兼容解析 | 兼容旧表，同时优先解析新 Contract。 |
| `WS-GH-010-5` | 增加测试 | 覆盖必填字段、大小写、缺失字段、TASK 冲突、旧模板兼容。 |
| `WS-GH-010-6` | 重新执行 V3 E2E Demo | 验证 GPT Issue -> resolver -> TASK -> dispatcher 链路。 |

每个后续 Step 都必须保持工作站边界：不改量化数据链路、策略、回测口径、实时交易、企业微信凭据或生产写入逻辑。

## 10. Acceptance Criteria

`WS-GH-010-1` 验收标准：

- 新增本文件并冻结 Issue Metadata Schema。
- 明确必填字段、可选字段和状态枚举。
- 明确 Issue Contract 与 TASK Schema V2 / V3 的字段映射。
- 明确 resolver 后续 fail-closed 解析要求。
- 明确后续 Step 拆分，避免一次性修改模板、resolver、tests 和 demo。
- 文档检查通过 `git diff --check`。
