# AI 工作站 Router V1 只读审计

生成时间：2026-07-12

## 0. 审计范围

本文件对应“AI 工作站 Router V1”第 0 步：只读盘点现有工作站，并形成后续升级实施基线。

本次只读审计遵守以下边界：

- 只新增本文件：`docs/gpt/WORKSTATION_ROUTER_V1_AUDIT.md`。
- 不修改 `scripts/ai/`、`docs/tasks/`、`tasks/current.md`、`AGENTS.md`、`CODEBUDDY.md`、`.ai/`、配置文件或任务单。
- 不调用 Codex CLI。
- 不访问生产环境、数据库、RQData 或外部服务。
- 不读取、显示或记录 `.env`、密钥、token、webhook、license 或账号信息。
- 不 push、不 merge、不 deploy。

已审计的主要文件和目录：

- `AGENTS.md`
- `CODEBUDDY.md`
- `docs/AGENT_WORKFLOW.md`
- `docs/CODEX_HANDOFF.md`
- `tasks/current.md`
- `docs/gpt/NEXT_STEPS.md`
- `docs/workflows/ai_delivery_workflow.md`
- `docs/workflows/status_machine.md`
- `docs/workflows/work_levels.md`
- `docs/workflows/github_issue_trace_workflow.md`
- `docs/tasks/TASK_TEMPLATE.md`
- `docs/tasks/TASK_TEMPLATE_L1.md`
- `docs/tasks/`
- `scripts/ai/`
- `.ai/`

## 1. 当前工作站事实

当前仓库已经具备 Lean V1 半自动 AI 交付工作站，不是空白状态。

现有工作流核心为：

```text
TASK
-> codex_plan.sh 只读 Plan
-> approve_task.sh 生成 Plan SHA256 审批凭证
-> codex_dev.sh workspace-write 开发
-> run_tests.sh 执行 TASK 声明测试
-> collect_result.sh 收集 Result Bundle
-> make_delivery_summary.sh 生成交付摘要
-> 用户人工 review / merge / deploy
```

当前分支为 `cursor/workstation-router-v1`，审计开始时工作区干净。

当前项目事实源仍以 Markdown 文档为主：

- TASK 主要位于 `docs/tasks/<TASK_ID>.md`。
- 临时或本地任务按约定位于 `.ai/tasks/<TASK_ID>.md`。
- Plan、测试和结果产物按约定位于 `.ai/results/<TASK_ID>/`。
- 审批记录按约定位于 `.ai/approvals/<TASK_ID>.json`。
- 日志按约定位于 `.ai/logs/`。

当前 `.ai/` 目录下未发现已跟踪文件；它更多是运行时产物目录。

## 2. 已存在并应保留的能力

### 2.1 工作级别 L0 / L1 / L2

`docs/workflows/work_levels.md` 已定义三层工作模式：

- L0：只读咨询与探索，不要求 TASK 或 worktree。
- L1：居家快速开发，要求 TASK、独立 worktree、Plan / Approve / Dev / Test，Issue 可选。
- L2：正式工作站交付，要求完整 TASK、独立 worktree、GitHub Issue、Plan / Approve / Dev / Test 和 Result Bundle。

这套分级应保留。后续 Router 不应绕开 L1 / L2 的 worktree、审批和结果目录约束。

### 2.2 任务状态机

`docs/workflows/status_machine.md` 已定义 10 状态：

```text
IDEA
REQUIREMENT_READY
PLAN_READY
APPROVED_DEV
CODING
TESTING
DELIVERY_READY
CLOSED
FAILED
REPLAN
```

这是后续 `task_meta.py` 的状态白名单基础。当前仓库中部分历史任务使用了扩展状态，例如 `DELIVERY_READY_DRY_RUN_NO_WRITE`、`DELIVERY_READY_APPLY_COMPLETED`、`DELIVERY_READY_SCHEME_B_MIGRATION` 等。后续严格 schema 需要兼容历史扩展状态，或明确区分 canonical status 与 legacy status。

### 2.3 CodeBuddy 七命令协议

`CODEBUDDY.md` 已定义七命令协议：

```text
TASK / PLAN / APPROVE / DEV / STATUS / CANCEL / RESULT
```

现有脚本已经覆盖其中多数能力：

- `create_issue_from_task.sh`
- `link_task_issue.sh`
- `codex_plan.sh`
- `approve_task.sh`
- `codex_dev.sh`
- `run_tests.sh`
- `collect_result.sh`
- `make_delivery_summary.sh`
- `comment_issue_result.sh`
- `update_issue_status.sh`

Router V1 应复用这些入口，不应重新发明一套绕过脚本的执行链路。

### 2.4 Plan / Dev 分离

`codex_plan.sh` 使用 `codex exec -s read-only`，并在 Plan 前后比较 tracked diff，防止只读 Plan 改动仓库。

`codex_dev.sh` 使用 `codex exec -s workspace-write`，并在执行前校验：

- TASK 是否存在。
- Issue Gate 是否通过。
- Worktree Gate 是否通过。
- Branch Gate 是否通过。
- 审批记录是否存在。
- Plan SHA256 是否与审批记录一致。

这一能力是当前安全基线，后续 Router 只能编排它，不能绕开它。

### 2.5 审批记录

`approve_task.sh` 通过 `_approve_lib.sh` 生成 `.ai/approvals/<TASK_ID>.json`。

审批记录当前包含：

- `schema_version`
- `task_id`
- `issue`
- `task_file`
- `task_sha256`
- `plan_file`
- `plan_sha256`
- `approved_branch`
- `approved_at`
- `approved_by`
- `head_commit`
- `pre_existing_changes`
- `pre_existing_sha256`

该格式已经满足“Plan 哈希绑定 + 脏工作区基线”的基本要求，应作为后续 schema 兼容对象。

### 2.6 Result Bundle 与脱敏

`collect_result.sh` 生成 `.ai/results/<TASK_ID>/result_bundle.json`，并记录：

- 当前 TASK 状态。
- 工作级别。
- worktree 路径。
- Issue Gate。
- 当前分支与期望分支。
- pre-existing changes。
- task changes。
- unexpected changes。
- 测试命令与结果。
- scope check。
- forbidden path check。
- sensitive data check。
- approval validity。
- Plan 是否变化。
- manual review required。

脚本中已有针对 token、webhook、password、secret、api key、access key 等字段的脱敏逻辑。

## 3. 已存在但需要扩展的能力

### 3.1 TASK 解析

当前 TASK 元信息主要是 Markdown 表格：

```text
| Task ID | ... |
| Work Level | ... |
| GitHub Issue | ... |
| Branch | ... |
| Worktree | ... |
| Status | ... |
```

现有解析方式主要依赖 shell 中的 `sed`、`awk`、正则和标题区间切分。它对当前模板可用，但不适合承载嵌套字段，例如：

- `routing.requested_tier`
- `routing.allow_auto_escalation`
- `routing.max_auto_escalations`
- `required_env`
- `required_mounts`
- `allowed_paths`
- `forbidden_paths`
- `production_access_allowed`
- `database_write_allowed`

后续第 1 步应新增机器可读 TASK 契约，同时保留对现有 Markdown 表格任务的 legacy read 模式。

### 3.2 测试命令解析

`run_tests.sh` 读取 `### 18.0 自动化测试命令` 下第一个 fenced `bash` 块，并逐行执行。它已经拒绝部分危险命令、网络命令、重定向和 shell 组合符。

需要扩展点：

- 当前安全命令白名单仅允许 `git`、`bash`、`grep`、`rg` 开头，后续很多 Python、pytest、uv、npm 测试需要经过 TASK metadata 或安全策略扩展。
- 当前脚本内部仍使用 `grep`、`sed`、`awk` 等文本处理。作为脚本实现可以保留，但后续嵌套 TASK metadata 不应继续靠 shell 文本解析。

### 3.3 Issue Trace

`create_issue_from_task.sh`、`link_task_issue.sh`、`comment_issue_result.sh`、`update_issue_status.sh` 已具备 GitHub Issue 留痕能力。

需要扩展点：

- `link_task_issue.sh` 的 TASK 搜索顺序是 `.ai/tasks/`、`docs/tasks/examples/`、`docs/tasks/`，而 `codex_plan.sh` 等入口使用 `docs/tasks/`、`.ai/tasks/`、`docs/tasks/examples/`。后续应统一搜索顺序。
- GitHub 操作依赖 `gh` 和远程认证，不适合 Router 的本地 dry-run 自检默认路径。

### 3.4 Worktree 初始化

`init_task_worktree.sh` 已支持：

- 根据 TASK_ID 找任务文件。
- `--bootstrap` 生成 L1 TASK 骨架。
- 基于 TASK 元信息或默认 slug 创建分支。
- 创建独立 worktree。
- 回填 TASK 的 `Worktree` 和 `Branch` 字段。

需要扩展点：

- `--bootstrap` 当前会写入 `docs/tasks/<TASK_ID>.md`，适合 L1，但正式 L2 仍应由 WorkBuddy 或用户确认完整任务单。
- 默认 worktree root 来自 `GUIYI_WORKTREE_ROOT` 或 `<repo>/../guiyi-parallel`，需要在环境检查脚本中明确验证。

## 4. 不存在、需要新增的能力

目标结构中以下能力当前未发现对应实现：

- `.ai/schema/task.schema.json`
- `scripts/ai/lib/task_meta.py`
- `scripts/ai/lib/route_task.py`
- `scripts/ai/lib/writer_lock.py`
- `scripts/ai/route_task.sh`
- `scripts/ai/dispatch_task.sh`
- `scripts/ai/codex_review.sh`
- `scripts/ai/install_codex_profiles.sh`
- `scripts/ai/workstation_doctor.sh`
- `scripts/env/check_task_env.sh`
- `scripts/env/bootstrap_worktree_env.sh`
- `config/codex/profiles/guiyi-fast.config.toml`
- `config/codex/profiles/guiyi-standard.config.toml`
- `config/codex/profiles/guiyi-deep.config.toml`
- `config/codex/profiles/guiyi-critical.config.toml`
- `tests/workstation/`

这些应按后续 1-9 步分批新增，不应在第 0 步创建。

## 5. 可能重复或冲突的文件

`scripts/ai/` 当前存在若干兼容名或历史入口：

- `codex_plan.sh`
- `codexplan.sh`
- `codex_dev.sh`
- `codexdev.sh`
- `run_tests.sh`
- `runtests.sh`
- `collect_result.sh`
- `collectresult.sh`
- `make_delivery_summary.sh`
- `makedeliverysummary.sh`

建议后续审查这些无下划线版本是否为兼容 wrapper、历史副本或未清理脚本。Router V1 应指定 canonical 入口为下划线版本：

- `codex_plan.sh`
- `codex_dev.sh`
- `run_tests.sh`
- `collect_result.sh`
- `make_delivery_summary.sh`

如果无下划线版本必须保留，应在文档中声明为兼容入口，并增加测试确保行为一致。

另一个潜在冲突是 `.ai/approvals/` 结构。当前实现使用：

```text
.ai/approvals/<TASK_ID>.json
```

历史文档或记忆中曾出现过：

```text
.ai/approvals/<TASK_ID>/approval.json
```

后续第 1 步应以当前脚本事实为准，保留 `.ai/approvals/<TASK_ID>.json`，必要时只做只读兼容。

## 6. 当前安全 Gate

### 6.1 Issue Gate

实现位置：`scripts/ai/_work_level_lib.sh`

规则：

- L0：跳过。
- L1：有 `#N` 则通过；无 Issue 只 warning，不阻断。
- L2：必须有 `#N`，否则失败。

### 6.2 Worktree Gate

实现位置：`scripts/ai/_work_level_lib.sh`

规则：

- L0：跳过。
- L1 / L2：TASK `Worktree` 必须已回填，并且当前 git toplevel 必须等于该路径。

### 6.3 Branch Gate

实现位置：`scripts/ai/_approve_lib.sh`

规则：

- 当前分支不能是 `main` / `master`，也不能是 detached HEAD。
- 当前分支必须匹配 TASK 元信息中的 `Branch`。

### 6.4 Approval Gate

实现位置：`scripts/ai/_approve_lib.sh`

规则：

- `.ai/approvals/<TASK_ID>.json` 必须存在。
- `schema_version` 必须为 `1`。
- `task_id` 必须匹配。
- `task_file` 必须匹配。
- 当前分支必须通过 Branch Gate。
- 当前 Plan SHA256 必须等于审批记录中的 `plan_sha256`。

### 6.5 Plan Read-only Gate

实现位置：`scripts/ai/codex_plan.sh`

规则：

- Plan 使用 `codex exec -s read-only`。
- Plan 前后比较 `git diff --binary HEAD`，如果 tracked diff 改变则失败。

### 6.6 Dev Scope Gate

实现位置：`scripts/ai/codex_dev.sh`

规则：

- Dev 后 HEAD 不允许变化。
- 根据 TASK 第 7 节允许路径识别新增变更。
- 如果新增变更不在允许路径内，Scope Gate 失败。

注意：当前允许路径提取依赖 TASK 第 7 节中的 backtick 路径，对新机器可读字段还没有支持。

### 6.7 Test Command Gate

实现位置：`scripts/ai/run_tests.sh`

规则：

- 只读取 TASK `### 18.0 自动化测试命令` 下第一个 fenced `bash` 块。
- 没有声明时 fallback 到 `git diff --check` 和 `bash -n scripts/ai/*.sh`。
- 拒绝 `rm`、`sudo`、`ssh`、`scp`、`git push`、`git merge`、`git reset`、`git checkout`、`git clean`、`git commit`、`danger-full-access`、`curl`、`wget`、`nc`、重定向、组合符和命令替换。

### 6.8 Result Sensitive Data Check

实现位置：`scripts/ai/collect_result.sh`

规则：

- 对本次 task changes 扫描疑似敏感字段。
- Result Bundle 输出中对常见敏感字段做脱敏。

## 7. 当前 TASK 和审批格式

### 7.1 TASK 格式

当前完整模板是 `docs/tasks/TASK_TEMPLATE.md`，结构为 21 个 Markdown 章节，元信息为 Markdown 表格。

关键字段：

- `Task ID`
- `Work Level`
- `GitHub Issue`
- `Branch`
- `Worktree`
- `Status`
- `Created At`
- `Owner`

L1 轻量模板是 `docs/tasks/TASK_TEMPLATE_L1.md`，保留最小元信息、目标、不做事项、允许/禁止路径、测试命令、验收标准和风险点。

当前模板没有 YAML front matter，也没有 JSON schema。

### 7.2 审批格式

当前审批文件路径：

```text
.ai/approvals/<TASK_ID>.json
```

当前审批文件由 `approve_task.sh` 生成，绑定 TASK、Plan、分支和 HEAD。Dev 阶段必须验证审批记录有效，且 Plan 内容变化后旧审批自动失效。

### 7.3 结果格式

当前结果目录：

```text
.ai/results/<TASK_ID>/
```

常见文件：

- `plan_result.md`
- `plan.err`
- `dev.log`
- `commands_executed.tsv`
- `test_results.tsv`
- `failed_commands.txt`
- `skipped_tests.txt`
- `test.log`
- `result_bundle.json`
- `result_bundle.md`
- `delivery_summary.md`

## 8. 兼容性风险

1. TASK 状态存在 canonical 与历史扩展状态混用。后续严格校验若只接受 10 状态，会导致部分历史任务读取失败。
2. TASK 元信息目前是 Markdown 表格。若第 1 步直接改为 front matter 且不兼容旧格式，会破坏当前脚本。
3. 当前 `extract_task_meta_field` 等函数依赖 shell 文本解析。新增嵌套字段时不要继续扩展 shell 正则。
4. 允许/禁止路径目前从 TASK 第 7 节 backtick 中提取。新 schema 的 `allowed_paths` / `forbidden_paths` 必须与旧第 7 节保持一致或提供转换。
5. `.ai/` 当前是运行时产物目录。新增 `.ai/schema/task.schema.json` 时要确认是否受 `.gitignore` 影响，必要时调整但不能误提交运行日志。
6. GitHub Issue Trace 依赖 `gh` 和网络认证，不适合作为本地 `workstation_doctor` 的必需通过项。
7. 目标目录中的 `config/codex/profiles/` 当前不存在；安装 profile 时不能覆盖用户现有 Codex 配置。
8. `scripts/env/` 当前不存在；环境脚本新增时应避免读取或打印 `.env` 值，只验证变量名和挂载存在性。
9. 重复脚本入口可能造成 Router 调用旧入口。后续应声明 canonical 入口并测试 wrapper 行为。

## 9. 推荐最终目录和文件修改清单

推荐最终结构应以现有 Lean V1 为基础扩展，而不是替换。

建议保留：

- `scripts/ai/codex_plan.sh`
- `scripts/ai/codex_dev.sh`
- `scripts/ai/approve_task.sh`
- `scripts/ai/run_tests.sh`
- `scripts/ai/collect_result.sh`
- `scripts/ai/make_delivery_summary.sh`
- `scripts/ai/init_task_worktree.sh`
- `scripts/ai/create_issue_from_task.sh`
- `scripts/ai/link_task_issue.sh`
- `scripts/ai/comment_issue_result.sh`
- `scripts/ai/update_issue_status.sh`
- `docs/workflows/`
- `docs/tasks/TASK_TEMPLATE.md`
- `docs/tasks/TASK_TEMPLATE_L1.md`

建议新增或扩展：

- `docs/tasks/TASK_TEMPLATE.md`
- `.ai/schema/task.schema.json`
- `scripts/ai/lib/task_meta.py`
- `scripts/ai/lib/route_task.py`
- `scripts/ai/lib/writer_lock.py`
- `scripts/ai/route_task.sh`
- `scripts/ai/dispatch_task.sh`
- `scripts/ai/codex_review.sh`
- `scripts/ai/install_codex_profiles.sh`
- `scripts/ai/workstation_doctor.sh`
- `scripts/env/check_task_env.sh`
- `scripts/env/bootstrap_worktree_env.sh`
- `config/codex/profiles/*.config.toml`
- `tests/workstation/`
- `docs/workstation/ARCHITECTURE.md`
- `docs/workstation/HOME_DEVELOPMENT.md`
- `docs/workstation/REMOTE_DEVELOPMENT.md`
- `docs/workstation/ROUTING_POLICY.md`

## 10. 分 1-9 步实施顺序

### 第 1 步：TASK 元数据契约

目标：让 WorkBuddy、GPT、Cursor、CodeBuddy 和 Codex 使用同一个机器可读 TASK。

预计修改：

- `docs/tasks/TASK_TEMPLATE.md`
- `.ai/schema/task.schema.json`
- `scripts/ai/lib/task_meta.py`
- `tests/workstation/`

要点：

- 兼容旧 Markdown 表格任务。
- 新任务优先采用明确机器可读 metadata。
- 旧任务可读取但输出 legacy warning。
- 不破坏 `codex_plan.sh`、`codex_dev.sh`、`approve_task.sh`。

建议验证：

```bash
python3 scripts/ai/lib/task_meta.py validate docs/tasks/<TASK_ID>.md
python3 scripts/ai/lib/task_meta.py dump-json docs/tasks/<TASK_ID>.md
pytest -q tests/workstation
git diff --check
```

### 第 2 步：确定性模型路由器

目标：根据 TASK metadata 决定 `fast`、`standard`、`deep`、`critical` 路由层级。

预计修改：

- `scripts/ai/lib/route_task.py`
- `scripts/ai/route_task.sh`
- `docs/workstation/ROUTING_POLICY.md`
- `tests/workstation/`

要点：

- 默认 `auto`。
- 风控、策略、回测、数据库、生产或外部写入任务自动升级。
- 禁止为了速度降低 critical 任务等级。

建议验证：

```bash
python3 scripts/ai/lib/route_task.py docs/tasks/<TASK_ID>.md
scripts/ai/route_task.sh --task <TASK_ID>
pytest -q tests/workstation
git diff --check
```

### 第 3 步：Codex Profile 模板

目标：为不同路由层级提供可安装但不覆盖用户配置的 Codex profile 模板。

预计修改：

- `config/codex/profiles/guiyi-fast.config.toml`
- `config/codex/profiles/guiyi-standard.config.toml`
- `config/codex/profiles/guiyi-deep.config.toml`
- `config/codex/profiles/guiyi-critical.config.toml`
- `scripts/ai/install_codex_profiles.sh`
- `docs/workstation/HOME_DEVELOPMENT.md`

要点：

- 不写入凭据。
- 不默认启用 `danger-full-access`。
- 安装脚本默认 dry-run 或备份后写入。

建议验证：

```bash
bash -n scripts/ai/install_codex_profiles.sh
scripts/ai/install_codex_profiles.sh --dry-run
git diff --check
```

### 第 4 步：统一 dispatch 调度器

目标：提供一个统一入口编排 Gate、路由、Plan、Approve、Dev、Test、Result。

预计修改：

- `scripts/ai/dispatch_task.sh`
- `scripts/ai/lib/task_meta.py`
- `scripts/ai/lib/route_task.py`
- `docs/workstation/ARCHITECTURE.md`
- `tests/workstation/`

要点：

- 不取代底层脚本，只编排 canonical 入口。
- Plan 必须只读。
- Dev 必须有审批。
- STATUS 和 CANCEL 必须只读或非破坏性。

建议验证：

```bash
bash -n scripts/ai/dispatch_task.sh
scripts/ai/dispatch_task.sh STATUS <TASK_ID>
scripts/ai/dispatch_task.sh PLAN <TASK_ID> --dry-run
pytest -q tests/workstation
git diff --check
```

### 第 5 步：writer lock 与安全 Gate

目标：防止多个 Agent 同时修改同一任务、同一 worktree 或同一文件范围。

预计修改：

- `scripts/ai/lib/writer_lock.py`
- `scripts/ai/dispatch_task.sh`
- `.ai/locks/`
- `docs/workstation/ARCHITECTURE.md`
- `tests/workstation/`

要点：

- lock 文件写入 `.ai/locks/`。
- lock 内容不包含敏感信息。
- stale lock 只能显式清理。
- 不自动 kill 其他进程。

建议验证：

```bash
python3 scripts/ai/lib/writer_lock.py acquire --task <TASK_ID> --dry-run
python3 scripts/ai/lib/writer_lock.py status
pytest -q tests/workstation
git diff --check
```

### 第 6 步：环境和挂载检查

目标：在任务执行前检查 worktree、Python / Node / Codex / gh、必要挂载和环境变量名。

预计修改：

- `scripts/env/check_task_env.sh`
- `scripts/env/bootstrap_worktree_env.sh`
- `scripts/ai/workstation_doctor.sh`
- `docs/workstation/HOME_DEVELOPMENT.md`
- `docs/workstation/REMOTE_DEVELOPMENT.md`
- `tests/workstation/`

要点：

- 不读取或打印 `.env` 值。
- 只报告变量是否存在，不报告值。
- 不访问数据库、RQData 或外部服务，除非 TASK 显式授权。

建议验证：

```bash
bash -n scripts/env/check_task_env.sh scripts/env/bootstrap_worktree_env.sh scripts/ai/workstation_doctor.sh
scripts/ai/workstation_doctor.sh --offline
pytest -q tests/workstation
git diff --check
```

### 第 7 步：Review 与结果收集

目标：补齐 review 阶段，统一 Result Bundle、delivery summary、外部审查摘要和测试结果。

预计修改：

- `scripts/ai/codex_review.sh`
- `scripts/ai/collect_result.sh`
- `scripts/ai/make_delivery_summary.sh`
- `docs/workstation/ARCHITECTURE.md`
- `tests/workstation/`

要点：

- Review 默认只读。
- 不向外部服务自动发送 diff。
- 外部 ChatGPT 审查仍由人工粘贴。
- Result Bundle 保持脱敏。

建议验证：

```bash
bash -n scripts/ai/codex_review.sh scripts/ai/collect_result.sh scripts/ai/make_delivery_summary.sh
scripts/ai/collect_result.sh --task <TASK_ID> --format json
pytest -q tests/workstation
git diff --check
```

### 第 8 步：WorkBuddy / CodeBuddy / AGENTS 规则

目标：同步文档和规则，明确 Router V1 后的标准入口与边界。

预计修改：

- `AGENTS.md`
- `CODEBUDDY.md`
- `docs/AGENT_WORKFLOW.md`
- `docs/workflows/ai_delivery_workflow.md`
- `docs/workflows/work_levels.md`
- `docs/workstation/REMOTE_DEVELOPMENT.md`

要点：

- 不改变“用户最终 review / merge / deploy”原则。
- 不允许远程机器人自动 push、merge、deploy 或触发真实交易。
- 明确 canonical 脚本入口。

建议验证：

```bash
git diff --check
bash -n scripts/ai/*.sh
```

### 第 9 步：工作站自动化自检

目标：提供一键 offline doctor，验证 Router V1 的本地可用性。

预计修改：

- `scripts/ai/workstation_doctor.sh`
- `tests/workstation/`
- `docs/workstation/ARCHITECTURE.md`
- `docs/workstation/HOME_DEVELOPMENT.md`
- `docs/workstation/REMOTE_DEVELOPMENT.md`

要点：

- 默认 offline。
- 不访问生产服务。
- 不读取 `.env`。
- 不调用 Codex CLI 执行真实 Plan / Dev。
- 输出脱敏报告。

建议验证：

```bash
scripts/ai/workstation_doctor.sh --offline
pytest -q tests/workstation
git diff --check
```

## 11. 每一步预计修改文件

| 步骤 | 预计修改文件 |
|---|---|
| 1 TASK 元数据契约 | `docs/tasks/TASK_TEMPLATE.md`、`.ai/schema/task.schema.json`、`scripts/ai/lib/task_meta.py`、`tests/workstation/` |
| 2 确定性模型路由器 | `scripts/ai/lib/route_task.py`、`scripts/ai/route_task.sh`、`docs/workstation/ROUTING_POLICY.md`、`tests/workstation/` |
| 3 Codex Profile 模板 | `config/codex/profiles/*.config.toml`、`scripts/ai/install_codex_profiles.sh`、`docs/workstation/HOME_DEVELOPMENT.md` |
| 4 统一 dispatch 调度器 | `scripts/ai/dispatch_task.sh`、`scripts/ai/lib/task_meta.py`、`scripts/ai/lib/route_task.py`、`docs/workstation/ARCHITECTURE.md`、`tests/workstation/` |
| 5 writer lock 与安全 Gate | `scripts/ai/lib/writer_lock.py`、`scripts/ai/dispatch_task.sh`、`.ai/locks/`、`docs/workstation/ARCHITECTURE.md`、`tests/workstation/` |
| 6 环境和挂载检查 | `scripts/env/check_task_env.sh`、`scripts/env/bootstrap_worktree_env.sh`、`scripts/ai/workstation_doctor.sh`、`docs/workstation/HOME_DEVELOPMENT.md`、`docs/workstation/REMOTE_DEVELOPMENT.md`、`tests/workstation/` |
| 7 Review 与结果收集 | `scripts/ai/codex_review.sh`、`scripts/ai/collect_result.sh`、`scripts/ai/make_delivery_summary.sh`、`docs/workstation/ARCHITECTURE.md`、`tests/workstation/` |
| 8 WorkBuddy / CodeBuddy / AGENTS 规则 | `AGENTS.md`、`CODEBUDDY.md`、`docs/AGENT_WORKFLOW.md`、`docs/workflows/ai_delivery_workflow.md`、`docs/workflows/work_levels.md`、`docs/workstation/REMOTE_DEVELOPMENT.md` |
| 9 工作站自动化自检 | `scripts/ai/workstation_doctor.sh`、`tests/workstation/`、`docs/workstation/ARCHITECTURE.md`、`docs/workstation/HOME_DEVELOPMENT.md`、`docs/workstation/REMOTE_DEVELOPMENT.md` |

## 12. 每一步验证命令

建议后续每一步至少运行：

```bash
git status --short --branch
git diff --check
```

按步骤追加：

| 步骤 | 验证命令 |
|---|---|
| 1 | `python3 scripts/ai/lib/task_meta.py validate docs/tasks/<TASK_ID>.md`；`python3 scripts/ai/lib/task_meta.py dump-json docs/tasks/<TASK_ID>.md`；`pytest -q tests/workstation` |
| 2 | `python3 scripts/ai/lib/route_task.py docs/tasks/<TASK_ID>.md`；`scripts/ai/route_task.sh --task <TASK_ID>`；`pytest -q tests/workstation` |
| 3 | `bash -n scripts/ai/install_codex_profiles.sh`；`scripts/ai/install_codex_profiles.sh --dry-run` |
| 4 | `bash -n scripts/ai/dispatch_task.sh`；`scripts/ai/dispatch_task.sh STATUS <TASK_ID>`；`scripts/ai/dispatch_task.sh PLAN <TASK_ID> --dry-run` |
| 5 | `python3 scripts/ai/lib/writer_lock.py acquire --task <TASK_ID> --dry-run`；`python3 scripts/ai/lib/writer_lock.py status` |
| 6 | `bash -n scripts/env/check_task_env.sh scripts/env/bootstrap_worktree_env.sh scripts/ai/workstation_doctor.sh`；`scripts/ai/workstation_doctor.sh --offline` |
| 7 | `bash -n scripts/ai/codex_review.sh scripts/ai/collect_result.sh scripts/ai/make_delivery_summary.sh`；`scripts/ai/collect_result.sh --task <TASK_ID> --format json` |
| 8 | `git diff --check`；`bash -n scripts/ai/*.sh` |
| 9 | `scripts/ai/workstation_doctor.sh --offline`；`pytest -q tests/workstation` |

## 13. 需要根据仓库实际情况调整的预设路径

附件中的目标结构大体合理，但以下路径需要以当前仓库事实为准：

1. `scripts/ai/codex_plan.sh` 已存在，不应重建。
2. `scripts/ai/codex_dev.sh` 已存在，不应重建。
3. `scripts/ai/run_tests.sh` 已存在，不应重建。
4. `scripts/ai/collect_result.sh` 已存在，不应重建。
5. `scripts/ai/approve_task.sh` 已存在，虽然目标结构未列出，但它是当前审批 Gate 核心，必须保留。
6. `scripts/ai/init_task_worktree.sh` 已存在，虽然目标结构未列出，但它是 L1 / L2 worktree Gate 的前置能力，必须保留。
7. `scripts/ai/_work_level_lib.sh` 和 `scripts/ai/_approve_lib.sh` 已存在，后续可被 Python metadata 工具逐步替代或复用，但不能直接删除。
8. `.ai/approvals/<TASK_ID>.json` 是当前脚本事实，不应改成 `.ai/approvals/<TASK_ID>/approval.json`，除非提供兼容迁移。
9. `.ai/tasks/` 目前是 fallback，不是主任务目录；正式任务仍以 `docs/tasks/` 为主。
10. `docs/workstation/` 当前未发现，应作为新增文档目录创建。
11. `config/codex/profiles/` 当前未发现，应作为新增模板目录创建。
12. `tests/workstation/` 当前未发现，应作为新增测试目录创建。

## 14. 第 0 步结论

当前工作站已经完成 Lean V1 的关键闭环：TASK、L1/L2、Issue Trace、Plan/Approve/Dev/Test、Result Bundle、worktree 和多项安全 Gate。Router V1 后续不应推倒重建，而应围绕以下方向小步增强：

1. 先建立兼容旧任务的机器可读 TASK metadata。
2. 再增加确定性路由和 profile。
3. 然后用 dispatch 统一编排现有脚本。
4. 最后补齐 writer lock、环境检查、review 和 workstation doctor。

本审计后应停止，不进入第 1 步实现。
