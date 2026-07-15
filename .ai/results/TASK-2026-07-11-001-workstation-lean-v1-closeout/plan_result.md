### 当前理解

本轮只读 Plan 已完成，未修改任何文件。

关键现场差异：虽然任务给出的环境事实称“工作区干净”，但当前实际 `git status --short --branch` 显示工作区并不干净，存在 5 个未跟踪文件，包括本任务单及 `data/universe/` 下两个文件。后续 Dev 必须先处理基线归属，否则无法可靠区分 pre-existing changes 与本次变更。

当前状态仍应保持 `REQUIREMENT_READY`。Issue Gate 的元信息已填写 `#6`，但任务单 §21 仍写“Issue 创建：待创建”，需要在 Dev 文档同步时修正。

## 1. 理解摘要

### 当前契约不一致

| 范围 | 当前实现/文档 | 目标契约 |
|---|---|---|
| Codex Plan 调用 | `codex --readonly --prompt ...` | `codex exec -s read-only "<prompt>"` |
| Codex Dev 调用 | `codex --prompt ...`，未指定 sandbox | `codex exec -s workspace-write "<prompt>"` |
| prompt 参数 | 脚本使用 `--prompt` | Codex CLI 0.144.1 使用位置参数 |
| Plan 参数 | 文档混用任务文件位置参数和 `--task <ID>` | Lean V1 对外统一 `--task <TASK_ID>`；内部解析任务路径 |
| Dev 参数 | `CODEBUDDY.md` 示例使用 `<task_file> <branch>`，旧脚本使用 `--task/--plan` | 统一为 `codex_dev.sh --task <TASK_ID>`，分支来自 TASK 元信息并校验 |
| TASK 搜索 | Plan/Dev 不搜索 `docs/tasks/<ID>.md`、`.ai/tasks/<ID>.md` | 两处均支持，正式 TASK 优先 `docs/tasks/` |
| TASK 内容 | Plan 只抽取 §15；Dev 只拼接 Plan 和通用护栏 | Plan/Dev 均读取完整 TASK；Dev 重点传入 §7、§16、§18、§19 |
| Plan 结果 | `scripts/ai/.out/<ID>/plan.md` | `.ai/results/<ID>/plan_result.md` |
| Dev/测试结果 | 核心脚本写 `scripts/ai/.out/` | 结果写 `.ai/results/`，日志写 `.ai/logs/` |
| Issue 脚本 | 已使用 `.ai/results/` 和 `.ai/logs/` | 与新核心脚本统一 |
| 审批门控 | 不存在；Plan 缺失仍允许 Dev | 无有效审批拒绝 Dev；Plan 改动自动失效 |
| 分支门控 | `codex_dev.sh` 不校验分支 | `main`/`master` 拒绝，且必须匹配 TASK Branch |
| 测试 | 固定执行根目录 `pytest`，依赖 `--scope` | 解析 TASK §18.0 fenced `bash` 命令 |
| 测试安全 | 允许 `--real`，命令模型不适合 Task Bundle | 默认只执行审查过的只读/测试命令，危险命令拒绝 |
| Result Bundle | 只有 diff stat、changed files、测试摘要路径 | 补齐任务、分支、基线、命令、测试、范围、安全和后续动作 |
| Delivery Summary | 内容完全硬编码为旧脚手架交付 | 从真实 Result Bundle 动态提取 |
| 状态机 | `PLAN_READY → APPROVED_DEV` 描述容易误解为 Plan 执行即批准 | Plan 完成进入 `PLAN_READY`；审批记录有效后才进入 `APPROVED_DEV` |
| Issue 状态 | TASK 元信息为 Issue `#6`，§21 却写“待创建” | 统一为 Issue `#6` 已关联 |
| 工作区状态 | 用户提供事实为“干净” | 当前实查存在 5 个 untracked 文件 |

确认 Codex CLI 0.144.1 的目标调用协议：

- Plan：`codex exec -s read-only "<prompt>"`
- Dev：`codex exec -s workspace-write "<prompt>"`
- `danger-full-access` 虽为 CLI 可识别 sandbox 值，但本项目硬禁止。
- 同时禁止 `--dangerously-bypass-approvals-and-sandbox`。

## 2. 拟修改文件列表

仅列任务单 §7 明确允许的文件。

### 新增

| 文件 | 原因 |
|---|---|
| `scripts/ai/_approve_lib.sh` | 提供审批生成、验证、Plan 变化检测和分支校验函数 |
| `scripts/ai/approve_task.sh` | 提供 `--task <TASK_ID>` 人工审批入口 |

### 修改

| 文件 | 原因 |
|---|---|
| `scripts/ai/codex_plan.sh` | 修正 CLI 调用、TASK 解析、Issue Gate、结果与日志路径 |
| `scripts/ai/codex_dev.sh` | 加入审批/分支/范围门控，完整读取 TASK，修正 CLI 调用 |
| `scripts/ai/run_tests.sh` | 安全解析 §18.0 测试命令并提供 fallback |
| `scripts/ai/collect_result.sh` | 生成通用 Result Bundle，加入基线、范围和脱敏检查 |
| `scripts/ai/make_delivery_summary.sh` | 从 Result Bundle 动态生成摘要 |
| `scripts/ai/comment_issue_result.sh` | 对齐新产物命名、路径和脱敏摘要 |
| `scripts/ai/update_issue_status.sh` | 对齐审批状态门控、路径及 TASK 状态字段 |
| `CODEBUDDY.md` | 固定 7 命令协议及 Lean Task Bundle 流程 |
| `docs/workflows/ai_delivery_workflow.md` | 替换旧 CLI、参数和 `.out` 契约 |
| `docs/workflows/github_issue_trace_workflow.md` | 插入 APPROVE 步骤并统一结果路径 |
| `docs/workflows/status_machine.md` | 明确 `PLAN_READY → APPROVED_DEV` 的审批凭证条件 |
| `docs/tasks/TASK_TEMPLATE.md` | 固定 §18.0 fenced `bash` 测试格式 |
| `docs/tasks/TASK-2026-07-11-001-workstation-lean-v1-closeout.md` | 更新状态、Issue 留痕、实际测试和交付记录 |
| `README.md` | 仅在需要增加 Lean V1 工作站入口导航时修改 |

不建议在 Plan 阶段凭“相关工作站测试 fixture”这一模糊授权新增未命名文件。若 Dev 需要新增 fixture，应先把精确路径补入任务单 §7。

## 3. Codex CLI 调用方案

Plan：

```bash
codex exec -s read-only "<完整 Plan prompt>"
```

Dev：

```bash
codex exec -s workspace-write "<完整 Dev prompt>"
```

实现要求：

- 使用参数数组调用，禁止字符串拼接后 `eval`。
- prompt 可由临时文件读取后作为最后一个位置参数，临时文件退出时清理。
- 固定 `/opt/homebrew/bin/codex` 或通过 `command -v codex` 解析并记录版本。
- 脚本中不得出现可执行的 `danger-full-access` 或 bypass 参数。
- Plan 前后分别记录 `git status --porcelain`，发现业务文件变化则 Plan 判定失败。
- Dev 前必须完成 Issue、审批、分支、工作区基线和 TASK 范围检查。

## 4. 审批门控设计

### `approve_task.sh`

接口：

```bash
scripts/ai/approve_task.sh --task <TASK_ID>
```

执行顺序：

1. 校验 Task ID 格式，拒绝路径穿越字符。
2. 定位 `docs/tasks/<ID>.md`，兼容回退 `.ai/tasks/<ID>.md`。
3. 读取 TASK 元信息：Issue、Branch、Status。
4. Issue 缺失或不是 `#[0-9]+` 时拒绝。
5. 要求 `.ai/results/<ID>/plan_result.md` 存在且非空。
6. `check_branch`：拒绝 `main`、`master`、detached HEAD；当前分支必须匹配 TASK Branch。
7. 计算 Plan SHA256；同时建议记录 TASK SHA256。
8. 记录审批前工作区基线，不能静默把未知变更归入本次任务。
9. 原子写入 `.ai/approvals/<ID>.json`：先临时文件、校验 JSON、再 `mv`。
10. 不调用 Dev、不改 TASK 状态、不自动同步 Issue；状态推进由显式流程操作完成。

### `_approve_lib.sh` 函数签名

```bash
generate_approval TASK_ID PLAN_FILE TASK_FILE TARGET_BRANCH APPROVAL_FILE
verify_approval TASK_ID PLAN_FILE TASK_FILE APPROVAL_FILE
detect_plan_change PLAN_FILE APPROVAL_FILE
check_branch EXPECTED_BRANCH
```

建议返回约定：

- `0`：通过；
- `2`：参数或文件错误；
- `5`：审批无效；
- `6`：Plan/TASK 哈希变化；
- `7`：分支不合法或不匹配。

### 审批 JSON

```json
{
  "schema_version": 1,
  "task_id": "TASK-2026-07-11-001-workstation-lean-v1-closeout",
  "issue": "#6",
  "task_file": "docs/tasks/TASK-2026-07-11-001-workstation-lean-v1-closeout.md",
  "task_sha256": "<sha256>",
  "plan_file": ".ai/results/TASK-2026-07-11-001-workstation-lean-v1-closeout/plan_result.md",
  "plan_sha256": "<sha256>",
  "approved_branch": "feature/workstation-lean-v1-closeout",
  "approved_at": "2026-07-11T00:00:00+08:00",
  "approved_by": "local-user",
  "pre_existing_changes": [
    ".workbuddy/memory/2026-07-11.md",
    "data/universe/product_1d_start_from_2020.csv"
  ]
}
```

不得写入账号、token、机器凭证或 GitHub 身份认证信息。

### `codex_dev.sh` 门控插入点

在创建任何结果目录、改变状态或调用 Codex 前执行：

1. 定位并完整读取 TASK；
2. Issue Gate；
3. `source _approve_lib.sh`；
4. `check_branch`；
5. `verify_approval`；
6. `detect_plan_change`；
7. 工作区基线一致性检查；
8. 允许/禁止路径解析成功检查；
9. 通过后才调用 `codex exec -s workspace-write`。

Codex 返回后再次做范围检查；出现越界文件时退出非零并进入 `FAILED`，但不 reset、不删除文件。

## 5. 产物路径迁移方案

统一路径：

```text
.ai/results/<TASK_ID>/
  plan_result.md
  execution_summary.md
  test_result.md
  result_bundle.md
  delivery_summary.md
  delivery_report_draft.md

.ai/logs/
  codex_plan_<TASK_ID>_<timestamp>.log
  codex_dev_<TASK_ID>_<timestamp>.log
  tests_<TASK_ID>_<timestamp>.log
```

兼容策略：

- 新脚本只写 `.ai/results/` 和 `.ai/logs/`。
- 读取时先查新路径；仅在新路径不存在时只读回退 `scripts/ai/.out/<ID>/`。
- 若从旧路径找到 Plan，应复制为规范 `plan_result.md` 后重新审批；不能沿用旧审批。
- 不移动、不删除旧 `.out` 内容。
- 兼容 wrapper 保持原样，继续把参数透传给新脚本。
- 文档不再把 `.out` 描述为有效写入目标。

## 6. TASK 完整读取方案

建立相同的 `resolve_task_file` 规则：

1. 显式传入的合法任务文件；
2. `docs/tasks/<TASK_ID>.md`；
3. `.ai/tasks/<TASK_ID>.md`；
4. 为兼容历史任务，可只读回退 `docs/tasks/examples/<TASK_ID>.md`。

解析后必须校验文件处于仓库根目录内，拒绝符号链接或 `../` 指向工作区外。

`codex_plan.sh` 应把以下内容组合为完整 prompt：

- `AGENTS.md`；
- `CODEBUDDY.md`；
- 完整 TASK §0–§21；
- `pwd`、仓库根、分支、当前 `git status`；
- 固定只读护栏。

`codex_dev.sh` 应读取：

- 完整 TASK；
- `.ai/results/<ID>/plan_result.md`；
- 有效审批摘要；
- §7 允许/禁止路径；
- §16 Dev Prompt；
- §18 测试命令；
- §19 验收标准。

不建议仅用自由文本 grep 作为最终范围门。应解析 §7 后形成 allowlist，并在 Dev 后用 `git status --porcelain` 与审批时基线做集合差分。

## 7. 测试策略设计

### §18.0 解析

- 只解析标题 `### 18.0 自动化测试命令` 下第一个标注为 `bash` 的 fenced block。
- 到下一个同级或更高级标题停止。
- 忽略空行和纯注释。
- 禁止 `eval`。
- 每条允许命令必须是单行、可审计命令；多行续行、here-doc、命令替换和动态 source 默认拒绝。
- 每条命令独立记录开始时间、退出码和脱敏输出；任一失败最终退出非零。

### 安全限制

拒绝至少包括：

- `rm`、`sudo`、`ssh`、`scp`、`curl`/`wget` 外传；
- `git push|merge|reset|checkout|clean|commit`；
- `gh issue close`、PR 创建或发布操作；
- `docker compose down -v`、部署命令；
- shell 重定向至仓库外；
- `source .env`、读取凭证文件；
- `danger-full-access`、bypass 参数；
- 数据写入、真实 webhook、自动交易命令；
- `;`、`&&`、`||`、反引号、`$()` 等复合执行语法，除非后续实现结构化 parser。

注意：任务单当前敏感词扫描命令会正常命中脚本里的护栏文字和脱敏正则，不能简单规定“任何匹配都失败”。应改为扫描疑似“敏感值赋值/URL/凭证格式”，否则存在高概率误报。

### fallback

TASK 未声明有效测试时执行：

```bash
git diff --check
bash -n scripts/ai/*.sh
```

再根据本次新增变更选择：

- `scripts/ai/`：审批门、路径解析、危险命令拒绝、Result Bundle fixture 测试；
- `services/`：仅当 TASK 允许且确有后端变更时运行对应 pytest；
- `apps/`：仅当 TASK 允许且确有前端变更时运行对应 test/build。

本任务明确禁止业务代码，因此 fallback 不应无条件跑全仓 pytest 或前端 build。

## 8. Result Bundle 字段设计

`collect_result.sh` 至少收集：

- `schema_version`
- `task_id`
- `task_file`
- `task_sha256`
- `github_issue`
- `task_status`
- `branch`
- `expected_branch`
- `head_commit_before`
- `head_commit_after`
- `generated_at`
- `git_status`
- `pre_existing_changes`
- `task_changes`
- `unexpected_changes`
- `changed_files`
- `git_diff_stat`
- `commands_executed`
- `test_results`
- `failed_commands`
- `skipped_tests`
- `scope_check`
- `forbidden_path_check`
- `sensitive_data_check`
- `approval_file`
- `approval_valid`
- `approved_plan_sha256`
- `current_plan_sha256`
- `plan_changed`
- `issue_gate`
- `risks`
- `incomplete_items`
- `manual_review_required`
- `next_action`

区分变更的方法：

```text
审批时 git status 基线
        ↓
Dev 完成后的 git status
        ↓
集合差分 = task_changes
交集/原有集合 = pre_existing_changes
无法归属的新文件 = unexpected_changes
```

当前工作区已有 5 个 untracked 文件，因此基线快照是 P0 前置条件。

`make_delivery_summary.sh` 只从 Result Bundle 提取：

- 当前状态；
- 本次变更文件；
- 测试通过/失败/跳过；
- 越界和敏感检查；
- 风险及未完成项；
- 是否建议进入人工 review；
- `next_action`。

缺少必填字段时应生成“不完整交付摘要”并退出非零，不能填充旧脚手架固定文案。

## 9. CODEBUDDY.md 命令协议

| 命令 | 定义 |
|---|---|
| `TASK <path>` | 只读校验 Task Bundle；正式文件已在 `docs/tasks/` 时不得重复复制。检查 Task ID、Issue、Branch、状态、§7、§15–§19。 |
| `PLAN <TASK_ID>` | Issue Gate 通过后调用 `codex_plan.sh --task`；只读执行，生成 `plan_result.md`，状态最多推进到 `PLAN_READY`。 |
| `APPROVE <TASK_ID>` | 用户明确批准后调用 `approve_task.sh --task`；只生成绑定 Plan/TASK 哈希及分支的 JSON，不启动 Dev。 |
| `DEV <TASK_ID>` | 仅在审批有效、分支正确、工作区基线可解释时调用 `codex_dev.sh --task`；完成后执行测试，不 push/merge/deploy。 |
| `STATUS <TASK_ID>` | 只读返回 TASK 状态、Issue、分支、Plan/审批/测试/结果存在性，不改变状态。 |
| `CANCEL <TASK_ID>` | 停止后续调度并记录取消；不 `reset`、不删文件、不回滚、不关闭 Issue。状态机目前没有 `CANCELLED`，Lean V1 宜记录 `cancel_record.json`，不擅自新增第 11 状态。 |
| `RESULT <TASK_ID>` | 读取并返回脱敏的 Result Bundle/Delivery Summary；不回传完整日志，不执行外部动作。 |

兼容原则：

- 保持现有 Issue 1:1 留痕。
- 保持 `create_issue_from_task.sh`、`link_task_issue.sh` 和 wrapper 不变。
- 原 `PLAN → 用户确认 → DEV` 细化为 `PLAN → APPROVE → DEV`。
- WorkBuddy 仍只生成一次完整 Task Bundle 和最终交付报告。
- CodeBuddy 仍是本地控制器，Codex CLI 仍是唯一代码执行器。

## 10. 风险点与缓解措施

| 评级 | 修改点/风险 | 缓解措施 |
|---|---|---|
| P0 | 当前工作区实际不干净，可能误归属或覆盖用户文件 | Dev 前人工确认 5 个 untracked 文件归属；生成不可变基线快照 |
| P0 | Bootstrap Dev 绕过待修复的审批门 | 仅本 TASK、仅一次；要求有效人工审批 JSON；Dev 后立即用新门控做拒绝/通过回归 |
| P0 | 审批文件可被手工伪造或复制 | 同时绑定 TASK、Plan、分支、Issue、时间和基线；严格文件权限；Dev 现场重算哈希 |
| P0 | CLI 调用错误导致 sandbox 未生效 | 固定 `codex exec -s read-only/workspace-write`；参数数组；测试中检查日志和业务文件零变更 |
| P0 | Issue/状态不一致导致越 Gate | 以 TASK 元信息 `#6` 为准；修正 §21；Plan 只到 `PLAN_READY`，有效审批后才到 `APPROVED_DEV` |
| P1 | TASK parser 截断 §7、§18 或 §19 | 完整 TASK 传入 Codex；关键段落单独解析并做存在性断言 |
| P1 | 测试命令解析形成命令注入 | 不用 `eval`；只允许单行白名单命令；拒绝 shell 元字符和危险程序 |
| P1 | 敏感扫描自身产生误报或漏报 | 从关键词扫描升级为疑似值模式；结果输出统一脱敏；fixture 覆盖正反例 |
| P1 | `.out` 迁移导致旧流程找不到产物 | 新路径优先、旧路径只读 fallback；不删除旧产物；旧 Plan 迁移后重新审批 |
| P1 | Dev 越界修改业务代码 | allowlist 集合差分；发现 `services/`、`apps/`、`data/`、`strategies/` 变化立即失败 |
| P1 | CANCEL 被误实现为回滚 | 明确禁止 reset/clean/delete；只写取消记录并停止后续动作 |
| P1 | `update_issue_status.sh` 在本地验证时产生外部写操作 | 单元测试使用 fixture/stub；真实 Issue 更新必须独立人工确认 |
| P2 | Delivery Summary 字段缺失仍显示成功 | 必填字段校验；缺失时退出非零并标为 incomplete |
| P2 | README 或文档仍残留旧 `.out`/参数示例 | 对允许修改文档做定向 `rg` 一致性检查 |
| P2 | wrapper 文档描述与实际名称混淆 | wrapper 不修改，只验证参数透明转发 |

### 测试计划

Dev 获得明确批准后计划执行：

```bash
bash -n scripts/ai/*.sh
git diff --check
git diff --name-only
```

并补充审批门、TASK 路径、Plan 哈希变化、main 拒绝、危险测试命令拒绝、fallback、Result Bundle 和动态摘要的 fixture 回归。真实 Codex Plan smoke 只能用 `read-only`；Issue 评论、状态更新和 Dev 均不能在本轮只读 Plan 中执行。

### 需要确认的问题

1. 当前工作区实际存在 5 个未跟踪文件，与“工作区干净”事实冲突。进入 Dev 前需确认它们是保留为 pre-existing baseline，还是先由用户提交/移走。
2. §7 的“相关工作站测试 fixture”不是精确路径。若要新增测试文件，应先把明确路径加入任务单。
3. 当前阶段保持 `REQUIREMENT_READY`；只有 Plan 产物正式保存并完成一致性检查后，才能推进到 `PLAN_READY`。

是否建议开新 Codex 会话：是。原因是本轮只读 Plan 已完成，下一轮属于获得批准后的 Bootstrap Dev，权限和阶段发生切换。

是否建议使用 Plan 模式：当前已完成 Plan；下一轮若获明确 APPROVE，使用受限 `workspace-write` Dev，不再重复 Plan。

建议同步给浏览器 GPT 的文件：

- `docs/tasks/TASK-2026-07-11-001-workstation-lean-v1-closeout.md`
- 本次只读 Plan 全文
- `CODEBUDDY.md`
- `docs/workflows/ai_delivery_workflow.md`
- `docs/workflows/status_machine.md`
- `docs/workflows/github_issue_trace_workflow.md`

