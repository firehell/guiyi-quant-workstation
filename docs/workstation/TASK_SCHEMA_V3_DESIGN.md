# Task Schema V3 Static / Runtime Split Design

更新时间：2026-07-14

任务：`WS-GH-004`

状态：design accepted

## 1. 背景

V2 TASK 已支持 YAML frontmatter、Markdown body、风险、审批范围、GitHub Issue、branch、worktree 和 required tests。它满足本地 dispatcher 运行，但不完全适合 GitHub Native V3：

- `worktree` 是本机绝对路径，不适合作为 GitHub 可提交字段。
- GPT 创建 TASK 时不知道用户本机路径。
- 同一个 task branch 可能被 Mac mini、居家 Mac、Cursor 或 CodeBuddy 在不同 worktree 接管。
- `last_dispatch_stage`、`last_sync_at` 等运行状态是本地状态，不应进入版本化 TASK。

WS-GH-004 只做设计和 runtime JSON Schema，不修改 dispatcher、`task_meta`、`schema_validator.py` 或历史 TASK。

## 2. 目标

1. TASK 文件只保存可提交、跨设备稳定的静态任务契约。
2. 本地 checkout、worktree、last stage、Issue/PR 数字缓存等运行状态放入 `.ai/task-runtime/<TASK_ID>.json`。
3. 保留 V2 TASK Schema 和旧 Markdown TASK 兼容。
4. 不强制迁移历史 TASK。
5. 定义 `task_meta` 合并优先级：runtime overlay > static task > compatibility defaults。

## 3. 非目标

- 不修改 `scripts/ai/dispatch_task.sh` 行为。
- 不修改 `scripts/ai/lib/task_meta.py` 行为。
- 不修改 `configs/ai/schemas/task-v2.0.schema.json`。
- 不要求历史 TASK 删除 `worktree` 字段。
- 不把 `.ai/task-runtime/` 提交到 Git。
- 不改变审批、resource lock、scope gate、runtime gate 或 result bundle 规则。

## 4. V3 静态任务契约

V3 TASK 仍是 Markdown 文件，建议继续使用 YAML frontmatter + Markdown body。静态字段必须可以提交到 GitHub，并能被 GPT、WorkBuddy、CodeBuddy、Codex、Cursor 在不同机器上读取。

### 4.1 推荐静态字段

```yaml
kind: Task
schema_version: "3.0"
task_id: WS-GH-004
epic_id: WORKSTATION-GH-NATIVE-V3
title: "设计 Task Schema V3 静态与运行时分层"
status: REQUIREMENT_READY
risk_level: R2
work_level: L2
approval_scope: [plan, code]
depends_on: ["WS-GH-002"]
allowed_paths:
  - docs/workstation/**
  - configs/ai/schemas/**
forbidden_paths:
  - .env
  - data/**
required_tests:
  - python3 -m pytest -q tests/workstation
  - git diff --check
branch: task/ws-gh-004-task-schema-v3-design
base_branch: main
github_issue: "#0"
github_pr: "#0"
created_by: gpt-github
source: github-native
created_at: "2026-07-14"
updated_at: "2026-07-14"
```

### 4.2 字段分类

| 字段 | 静态 / runtime | 说明 |
|---|---|---|
| `task_id` | static | 全局任务 ID |
| `status` | static | 可提交状态；阶段推进时可由受控脚本更新 |
| `risk_level` | static | 风险等级 |
| `work_level` | static | L0/L1/L2 |
| `approval_scope` | static | 审批范围 |
| `depends_on` | static | 前置任务 |
| `allowed_paths` | static | 允许修改范围 |
| `forbidden_paths` | static | 禁止修改范围 |
| `resource_locks` | static | 逻辑资源锁名称，不是本机路径 |
| `required_tests` | static | 必须执行的测试命令 |
| `branch` | static | 远程任务分支名 |
| `base_branch` | static | merge-base / PR base |
| `github_issue` | static | GitHub Issue 引用，建议 `#N` |
| `github_pr` | static | GitHub PR 引用，建议 `#N`；Draft PR 也使用该字段 |
| `created_by` | static | `gpt-github`、`workbuddy`、`codex`、`cursor`、`user` |
| `source` | static | `github-native`、`task-id-compatible`、`manual`、`legacy` |
| `worktree` | runtime | 本机绝对路径 |
| `local_branch` | runtime | 本地 checkout 分支 |
| `last_dispatch_stage` | runtime | 最近一次本地 dispatch stage |
| `last_sync_at` | runtime | 最近一次本地 runtime 状态同步时间 |

## 5. 本地 runtime overlay

路径：

```text
.ai/task-runtime/<TASK_ID>.json
```

`.gitignore` 已忽略整个 `.ai/` 目录，因此 runtime overlay 默认 local-only，不应提交。

示例：

```json
{
  "schema_version": "1.0",
  "task_id": "WS-GH-004",
  "worktree": "/Volumes/扩展盘/guiyi-parallel/ws-gh-004-task-schema-v3-design",
  "local_branch": "task/ws-gh-004-task-schema-v3-design",
  "issue_number": 0,
  "pr_number": 0,
  "last_dispatch_stage": "plan",
  "last_sync_at": "2026-07-14T15:00:00Z"
}
```

### 5.1 runtime 字段

| 字段 | 必需 | 说明 |
|---|---:|---|
| `schema_version` | 是 | 固定 `"1.0"` |
| `task_id` | 是 | 与静态 TASK 一致 |
| `worktree` | 否 | 本机 worktree 绝对路径 |
| `local_branch` | 否 | 本机当前分支，可与静态 `branch` 一致 |
| `issue_number` | 否 | 本地缓存的 Issue 数字 |
| `pr_number` | 否 | 本地缓存的 PR 数字 |
| `last_dispatch_stage` | 否 | `route`、`plan`、`dev`、`fix`、`test`、`review`、`result`、`pause`、`resume`、`cancel`、`status` |
| `last_dispatch_exit_code` | 否 | 最近一次 dispatch 退出码 |
| `last_sync_at` | 否 | ISO 8601 UTC 时间 |
| `updated_by` | 否 | `codebuddy`、`codex`、`cursor`、`user` |
| `notes` | 否 | 本地短说明，不放敏感信息 |

## 6. 合并优先级

`task_meta` 后续实现建议按以下顺序合并：

```text
runtime overlay > static task > compatibility defaults
```

具体规则：

1. 先解析静态 TASK，得到跨设备契约。
2. 再读取 `.ai/task-runtime/<TASK_ID>.json`，只覆盖 runtime 字段。
3. 最后填入兼容默认值，例如缺失 `base_branch` 时默认 `main`。
4. runtime overlay 不得覆盖 `allowed_paths`、`forbidden_paths`、`required_tests`、`risk_level`、`approval_scope` 等安全契约字段。
5. 如果 runtime `task_id` 与 static `task_id` 不一致，必须 fail-closed。
6. 如果 runtime `worktree` 不存在或不是 git worktree，应提示 bootstrap，不应静默 fallback 到主仓库。

## 7. V2 -> V3 兼容策略

### 7.1 读取兼容

- V2 YAML TASK 继续有效。
- 旧 Markdown table TASK 继续通过 `compat_reader.py` 转换。
- V2 中已有 `worktree` 字段继续可读，但视为 legacy inline runtime。
- 当 runtime overlay 存在时，runtime `worktree` 优先于 V2 inline `worktree`。
- 当 runtime overlay 不存在时，V2 inline `worktree` 可继续作为兼容路径使用。

### 7.2 写入兼容

- 新建 V3 TASK 不应写 `worktree`。
- `init_task_worktree.sh` 后续应改为写 `.ai/task-runtime/<TASK_ID>.json`，并在过渡期可选择同步旧 TASK `Worktree` table 字段以兼容旧脚本。
- `link_task_issue.sh` 仍可更新静态 TASK 的 `github_issue` 或旧表格 `GitHub Issue`。
- Issue / PR 数字可同时存在于静态 TASK 和 runtime cache；静态 TASK 是可审查来源，runtime cache 是本地便利层。

### 7.3 不强制迁移

- 历史 V2 TASK 不批量修改。
- 对活跃 L1/L2 任务，可在首次 bootstrap 时生成 runtime overlay。
- 对已关闭任务，不需要生成 runtime overlay。

## 8. 迁移与回滚

### 8.1 渐进迁移

1. WS-GH-004：设计文档与 runtime schema。
2. WS-GH-005：实现 runtime overlay 读写接口，保持旧字段可读。
3. WS-GH-006：让 Issue-first bootstrap 写入 runtime overlay。
4. WS-GH-007：调整 CI / tests，验证 V2 与 V3 共存。

### 8.2 回滚

如果 runtime overlay 实现导致异常：

1. 删除本机 `.ai/task-runtime/<TASK_ID>.json`。
2. 使用 V2 inline `worktree` 或重新运行 `init_task_worktree.sh`。
3. 保留静态 TASK 与 GitHub Issue / PR 不变。
4. 不需要改历史 commit。

## 9. 安全与敏感信息

runtime overlay 不得包含：

- `.env` 内容
- token、webhook、cookie、license、账号、密码
- RQData 凭据
- 企业微信 bot secret
- 数据库连接串

runtime overlay 可包含本机路径，但因 `.ai/` 已被 `.gitignore` 忽略，不进入 GitHub。

## 10. WS-GH-005 实现接口建议

后续实现建议新增或扩展：

```text
scripts/ai/lib/task_runtime.py
scripts/ai/task_runtime.sh
tests/workstation/test_task_runtime.py
```

建议 CLI：

```bash
scripts/ai/task_runtime.sh get --task <TASK_ID> --json
scripts/ai/task_runtime.sh set --task <TASK_ID> --worktree <path> --local-branch <branch>
scripts/ai/task_runtime.sh update-stage --task <TASK_ID> --stage plan --exit-code 0
scripts/ai/task_runtime.sh validate --task <TASK_ID>
```

建议 Python API：

```python
load_task_runtime(repo_root: Path, task_id: str) -> TaskRuntime
save_task_runtime(repo_root: Path, runtime: TaskRuntime) -> None
merge_task_meta(static: TaskMeta, runtime: TaskRuntime | None) -> TaskMeta
```

WS-GH-005 必须保持：

- 无 runtime overlay 时旧 TASK 仍可执行。
- runtime overlay 存在时不覆盖安全契约字段。
- `.ai/task-runtime/` 写入失败时 fail-closed，不静默回退到 `main` worktree。

