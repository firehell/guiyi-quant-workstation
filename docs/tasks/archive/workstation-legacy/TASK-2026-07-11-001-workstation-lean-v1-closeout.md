# TASK-2026-07-11-001：归一量化单项目工作站精简收口与Demo前置修复（WORKSTATION-LEAN-V1-CLOSEOUT）

> 团队：归一量化产品与交付工作站
> 状态：DELIVERY_READY
> 任务类型：AI 工作流优化（Lean V1 收口 + Codex CLI 调用规范化 + 最小审批门 + 测试/Result Bundle/交付修复 + 命令协议固定 + 文档统一）
> 生成：WorkBuddy（按 TASK_TEMPLATE.md 21 字段模板，一次生成完整 Task Bundle）
> 配套：CODEBUDDY.md、AGENTS.md、ai_delivery_workflow.md、status_machine.md、github_issue_trace_workflow.md
> 性质：**Lean V1 收口任务**——用一次小范围任务完成工作站 Lean V1 收口，不建设 Daemon、不建设 Runner、不建设腾讯云控制层、不建设 Dashboard、不做多项目支持。本次 Dev 为一次性 Bootstrap Dev 例外，修复完成后以新 codex_dev.sh 做门控回归。

> **Lean V1 核心原则**：WorkBuddy 一次生成完整 Task Bundle（目标+范围+不做事项+允许/禁止路径+Plan要求+Dev要求+测试命令+验收标准+风险），用户只需把 TASK 转发给 CodeBuddy 一次。后续不再分别要求 WorkBuddy 生成 Plan Prompt、Dev Prompt 和 CodeBuddy Prompt。

> **状态门控说明**：本任务单已完成 `REQUIREMENT_READY → PLAN_READY → APPROVED_DEV → CODING → TESTING → DELIVERY_READY`。下方第 15–17 节随单携带，按状态机规则：
> - Plan Prompt 在 `PLAN_READY` 由 CodeBuddy 调用 `codex exec -s read-only` 执行（只读）；
> - Dev Prompt 在 `APPROVED_DEV` 才启用，且必须先有有效审批记录。
> **WorkBuddy 本次只产出本任务单文档，不修改代码、不执行任何脚本。**

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-001-workstation-lean-v1-closeout |
| GitHub Issue | #6 |
| Branch | feature/workstation-lean-v1-closeout |
| PR | 待创建 |
| Status | DELIVERY_READY |
| Created At | 2026-07-11 |
| Updated At | 2026-07-11 |
| Owner | WorkBuddy |

---

## 1. 任务状态

DELIVERY_READY

## 2. 任务类型

AI 工作流优化（Lean V1 收口 + Codex CLI 调用规范化 + 最小审批门 + 测试/Result Bundle/交付修复 + 命令协议固定 + 文档统一）
- 关联：CodeBuddy 本地执行控制器（CODEBUDDY.md）、AI 半自动交付流程（ai_delivery_workflow.md）、GitHub Issue 留痕流程（github_issue_trace_workflow.md）
- 参照：TASK_MATRIX.md「12. AI 工作流优化」「13. CodeBuddy / Codex / WorkBuddy 协作优化」
- 是否允许进入代码开发阶段：**是**（严格限定 §7 允许修改文件；不碰业务/数据/策略/配置）

## 3. 参与角色

- **必须**：
  - 项目经理 / 流程调度员（编号、状态、拆分、卡点检查、状态口径核对）
  - 后端开发负责人（脚本修改、审批门控实现、三类 Prompt）
  - 测试专家 / QA Lead（bash -n 语法检查、测试命令解析、回归验证）
  - 安全与权限专家（护栏自检、sandbox 约束、deny-list 审核）
  - DevOps / 本地运维部署专家（Codex CLI 0.144.1 调用验证）
  - 交付专家（Result Bundle、交付摘要、验收报告）
- **可选**：
  - 量化架构师（评审工作流变更对既有流程的影响）
- **不需要**：
  - 产品负责人（无新用户场景，纯基础设施）
  - 量化业务专家（非数据/行情/交易日任务）
  - 策略研究员（非策略逻辑）
  - 数据工程师（非 RQData/聚合）
  - 交互视觉专家（无页面设计）

## 4. 背景

- V1.1（工作站脚本脚手架）已完成 `scripts/ai/` 下核心脚本落地（含兼容 wrapper 6 个，实际 15 个 .sh 文件）。
- V1.2（GitHub Issue 留痕）已完成 TASK ↔ Issue 双向同步机制。
- TASK-2026-07-10-003 已定义了精简收口的意图，但尚未实际执行开发。
- **当前 10 项已知问题**（最新只读检查确认）：

  1. `codex_plan.sh` 和 `codex_dev.sh` 仍使用旧式 codex 调用，需要根据 Mac mini 实际安装版本改为当前可用的 `codex exec` 调用。
  2. CODEBUDDY.md、工作流文档和脚本参数不一致。
  3. 文档使用 `.ai/results`，核心脚本使用 `scripts/ai/.out`。
  4. `codex_plan.sh` 未统一支持 `.ai/tasks` 和 `docs/tasks`。
  5. `codex_dev.sh` 没有完整读取 TASK 允许范围、禁止范围、Dev Prompt 和验收标准。
  6. Dev 脚本缺少可验证的 Plan 批准凭证。
  7. `run_tests.sh` 只运行仓库根 pytest，没有可靠适配归一量化实际测试命令。
  8. `make_delivery_summary.sh` 内容硬编码为工作站脚手架，不是通用结果摘要。
  9. 企业微信侧缺少统一的接收、PLAN、APPROVE、DEV、STATUS、RESULT 命令协议。
  10. 现有 SOP 仍要求多次向 WorkBuddy 生成 Plan/Dev/CodeBuddy Prompt，不符合"一次 Task Bundle 直达 CodeBuddy"的 Lean 流程。

- Codex CLI 实际版本：**0.144.1**（路径 `/opt/homebrew/bin/codex`），已确认支持的 sandbox 值：`read-only`、`workspace-write`、`danger-full-access`（其中 `danger-full-access` 为硬禁止）。

## 5. 目标

1. **统一 TASK**：保留现有正式 TASK 模板和 GitHub Issue 兼容性；WorkBuddy 一次生成完整 TASK，必须同时包含目标、范围、不做事项、允许修改路径、禁止修改路径、Plan 要求、Dev 要求、测试命令、验收标准、风险级别；后续不再分别要求 WorkBuddy 生成 Plan Prompt、Dev Prompt 和 CodeBuddy Prompt；正式 TASK 统一保存到 `docs/tasks/<TASK_ID>.md`；运行产物统一保存到 `.ai/results/<TASK_ID>/`；运行日志统一保存到 `.ai/logs/`。
2. **修复 Codex CLI 脚本**：根据 Mac mini 真实 codex 版本和 `codex exec --help` 调整调用方式（Plan 用 `codex exec -s read-only`，Dev 用 `codex exec -s workspace-write`，禁止 `danger-full-access`）；Plan 必须读取 AGENTS.md、CODEBUDDY.md、完整 TASK、当前 Git 状态；Dev 必须读取完整 TASK、已确认 Plan、Plan 审批凭证、允许/禁止修改路径、测试和验收要求；不允许使用裸 codex 命令绕过脚本。
3. **增加最小审批门**：增加简单 Plan 批准记录；批准记录必须绑定 TASK_ID、当前 plan 文件哈希、批准时间；Plan 变化后旧批准自动失效；没有有效批准记录，codex_dev.sh 必须拒绝执行；不建设复杂状态机和远程 Runner。
4. **修复测试**：run_tests.sh 不能只假设全局 pytest；应根据 TASK 中声明的测试命令执行；如果 TASK 未声明测试，至少执行 git diff --check、相关脚本 bash -n、根据变更范围选择后端或前端最小测试；默认不真实发送、不写生产数据、不部署；测试失败必须退出非 0。
5. **通用 Result Bundle**：collect_result 必须生成 task_id、branch、git status、changed files、git diff --stat、实际执行命令、测试结果、失败和跳过项、越界检查、敏感信息检查、遗留问题、next_action；make_delivery_summary 必须从真实 Result Bundle 生成，不得硬编码；企业微信摘要必须简洁，不直接输出完整日志和敏感内容。
6. **固定 CodeBuddy 命令协议**：在 CODEBUDDY.md 中增加 7 个命令：TASK、PLAN、APPROVE、DEV、STATUS、CANCEL、RESULT；明确 PLAN 只读、APPROVE 只生成与 Plan 哈希绑定的批准记录、DEV 必须验证批准记录、STATUS 只读、CANCEL 不 reset 不删除用户文件、RESULT 只返回脱敏摘要。
7. **统一文档**：同步 CODEBUDDY.md、ai_delivery_workflow.md、github_issue_trace_workflow.md、TASK 模板、README 工作站入口、相关脚本帮助信息。

## 6. 不做事项

- ❌ 不做 Daemon
- ❌ 不做 Workstation Runner
- ❌ 不部署腾讯云
- ❌ 不做多项目
- ❌ 不做自动任务队列
- ❌ 不做状态 Dashboard
- ❌ 不自动 push、merge、deploy
- ❌ 不自动关闭 Issue
- ❌ 不真实发送企业微信
- ❌ 不修改 `services/`、`apps/`、`packages/` 下的任何业务代码
- ❌ 不修改 `data/` 下的任何数据文件
- ❌ 不修改策略代码、量化业务逻辑
- ❌ 不修改 `.env`、密钥、webhook、token
- ❌ 不使用 `--sandbox danger-full-access`

## 7. 涉及模块

- **允许修改**：
  - `CODEBUDDY.md`
  - `README.md`
  - `docs/tasks/TASK_TEMPLATE.md`
  - `docs/tasks/TASK-2026-07-11-001-workstation-lean-v1-closeout.md`（本任务单自身）
  - `docs/workflows/ai_delivery_workflow.md`
  - `docs/workflows/github_issue_trace_workflow.md`
  - `docs/workflows/status_machine.md`
  - `scripts/ai/codex_plan.sh`（修改）
  - `scripts/ai/codex_dev.sh`（修改）
  - `scripts/ai/run_tests.sh`（修改）
  - `scripts/ai/collect_result.sh`（修改）
  - `scripts/ai/make_delivery_summary.sh`（修改）
  - `scripts/ai/comment_issue_result.sh`（修改）
  - `scripts/ai/update_issue_status.sh`（修改）
  - `scripts/ai/_approve_lib.sh`（新增）
  - `scripts/ai/approve_task.sh`（新增）
  - 相关工作站测试 fixture
- **禁止修改**：
  - `scripts/ai/create_issue_from_task.sh`
  - `scripts/ai/link_task_issue.sh`
  - `scripts/ai/run_v12_post_auth_e2e.sh`
  - 兼容 wrapper 脚本（`codexplan.sh`、`codexdev.sh`、`runtests.sh`、`collectresult.sh`、`makedeliverysummary.sh`）
  - `docs/AI_WECHAT_WORKFLOW.md`
  - `services/`（全部）
  - `apps/`（全部）
  - `packages/`（全部）
  - `data/`（全部）
  - 策略代码（`strategies/`）
  - `.env` / `.env.*`
  - 密钥、webhook、token 文件

## 8. 产品需求

- WorkBuddy 一次输出完整 Task Bundle（目标+范围+不做事项+允许/禁止路径+Plan要求+Dev要求+测试命令+验收标准+风险）
- 用户只需把 TASK 转发给 CodeBuddy 一次
- CodeBuddy 可执行 PLAN 并返回摘要
- 用户回复 APPROVE 后才能 DEV
- Codex CLI 是唯一代码执行器
- Dev 后自动测试并生成通用 Result Bundle
- 文档、参数和产物目录完全一致
- 不修改归一量化业务代码和数据
- 不增加云部署或复杂调度
- 可以进入 Lean V1 Demo

## 9. 量化业务规则

- 本任务**不涉及期货业务规则**（非数据/策略/信号任务）
- 新增/修改文字必须继承 V1 约束：不自动交易、不把信号当交易指令

## 10. 数据影响

- 无数据读写：不读取、不写入、不删除任何行情 / DB / parquet 数据
- 不触发 RQData、不写数据库、不真实发送企业微信

## 11. 技术方案

### 11.1 统一 TASK（Lean Task Bundle）

- 保留现有正式 TASK 模板和 GitHub Issue 兼容性
- WorkBuddy 一次生成完整 TASK（§1–21 全字段），随单携带 Plan Prompt（§15）、Dev Prompt（§16）、CodeBuddy 执行 Prompt（§17）
- 后续不再分别要求 WorkBuddy 生成 Plan Prompt、Dev Prompt 和 CodeBuddy Prompt
- 正式 TASK 统一保存到 `docs/tasks/<TASK_ID>.md`
- 运行产物统一保存到 `.ai/results/<TASK_ID>/`
- 运行日志统一保存到 `.ai/logs/`
- 兼容 wrapper 脚本（带下划线的旧版脚本名）指向新脚本，不做内容修改

### 11.2 修复 Codex CLI 脚本

- **已确认 Codex CLI 版本**：0.144.1，路径 `/opt/homebrew/bin/codex`
- **已确认 sandbox 值**：`read-only`、`workspace-write`、`danger-full-access`
- Plan 调用：`codex exec -s read-only "<prompt>"`（prompt 为位置参数，stdin 支持）
- Dev 调用：`codex exec -s workspace-write "<prompt>"`（prompt 为位置参数）
- **硬禁止**：`-s danger-full-access` 和 `--dangerously-bypass-approvals-and-sandbox`
- Plan 必须读取：AGENTS.md、CODEBUDDY.md、完整 TASK（§1–21 全字段）、当前 Git 状态
- Dev 必须读取：完整 TASK、已确认 Plan、Plan 审批凭证、允许/禁止修改路径（§7）、测试和验收要求（§18–19）
- codex_plan.sh 统一支持 `docs/tasks/` 和 `.ai/tasks/` 两处 TASK 文件
- 不允许使用裸 codex 命令绕过脚本
- 产物路径迁移：`scripts/ai/.out/` → `.ai/results/`（旧路径保留 fallback 检查）

### 11.3 最小审批门

- 新增 `scripts/ai/_approve_lib.sh`（函数库）：
  - `generate_approval()`：生成审批记录 JSON，含 plan SHA256、TASK_ID、分支、时间戳
  - `verify_approval()`：验证审批记录有效性和 Plan 哈希一致性
  - `detect_plan_change()`：比较当前 plan_result.md SHA256 与审批记录中哈希
  - `check_branch()`：拒绝 main 分支
- 新增 `scripts/ai/approve_task.sh`（命令入口）：
  - 命令格式：`approve_task.sh --task <TASK_ID>`
  - 计算 plan_result.md SHA256
  - 绑定 TASK_ID 和目标分支
  - 写入批准时间
  - 拒绝条件：main 分支、Plan 缺失、哈希无法计算
- 审批记录格式：`.ai/approvals/<TASK_ID>.json`
- `codex_dev.sh` 通过 `_approve_lib.sh` 验证审批记录和当前 Plan 哈希；验证失败 → 拒绝 Dev
- Plan 变化后旧批准自动失效（哈希不一致）
- 不建设复杂状态机和远程 Runner

### 11.4 修复测试

- `run_tests.sh` 不能只假设全局 pytest
- 应根据 TASK §18.0 fenced bash 代码块解析测试命令
- 如果 TASK 未声明测试，至少执行：
  - `git diff --check`
  - 相关脚本 `bash -n`
  - 根据变更范围选择后端或前端最小测试
- 安全限制：不使用 eval、逐条执行逐条记录退出码、拒绝危险命令（rm -rf、sudo 等）、禁止写出工作区外
- 默认不真实发送、不写生产数据、不部署
- 测试失败必须退出非 0

### 11.5 通用 Result Bundle

- `collect_result.sh` 必须生成以下字段：
  - task_id
  - branch
  - git status
  - changed files
  - git diff --stat
  - 实际执行命令
  - 测试结果
  - 失败和跳过项
  - 越界检查（diff 仅含 §7 允许路径）
  - 敏感信息检查
  - 遗留问题
  - next_action
- 区分 pre-existing changes 与本次变更
- 脱敏处理：正则覆盖 `token|webhook|password|secret|api[_-]?key|access[_-]?key|QYWX_WEBHOOK`
- `make_delivery_summary.sh` 必须从真实 Result Bundle 生成，不得硬编码特定任务内容
- 企业微信摘要必须简洁，不直接输出完整日志和敏感内容

### 11.6 固定 CodeBuddy 命令协议

在 CODEBUDDY.md 中增加以下 7 个命令：

| 命令 | 行为 | 前置条件 | 产物 |
|------|------|----------|------|
| TASK <path> | 接收任务单，写入 docs/tasks/ | 任务单文件存在 | docs/tasks/<TASK_ID>.md |
| PLAN <TASK_ID> | 调 codex_plan.sh 只读 Plan | Issue Gate 通过 | .ai/results/<TASK_ID>/plan_result.md |
| APPROVE <TASK_ID> | 生成与 Plan 哈希绑定的批准记录 | Plan 结果存在 | .ai/approvals/<TASK_ID>.json |
| DEV <TASK_ID> | 调 codex_dev.sh 开发 | 有效审批记录、非 main 分支 | 代码变更 |
| STATUS <TASK_ID> | 只读查询当前状态 | 无 | 状态摘要 |
| CANCEL <TASK_ID> | 取消任务，不 reset 不删除用户文件 | 无 | 状态标记 |
| RESULT <TASK_ID> | 返回脱敏摘要 | Dev+Test 完成 | 脱敏 result summary |

明确：
- PLAN 只读
- APPROVE 只生成与 Plan 哈希绑定的批准记录
- DEV 必须验证批准记录
- STATUS 只读
- CANCEL 不 reset、不删除用户文件
- RESULT 只返回脱敏摘要

### 11.7 统一文档

同步以下文档，确保契约一致：

| 文档 | 同步内容 |
|------|---------|
| CODEBUDDY.md | 7 命令协议、产物路径 `.ai/results/`、审批门控 |
| ai_delivery_workflow.md | Codex CLI 调用方式、产物路径迁移、Lean Task Bundle |
| github_issue_trace_workflow.md | 审批门控步骤、产物路径 `.ai/results/` |
| status_machine.md | 审批状态增加 APPROVED_DEV 门控说明 |
| TASK_TEMPLATE.md | §18.0 测试命令约定（fenced bash 代码块格式） |
| README.md | 工作站入口导航更新 |

### 11.8 一次性 Bootstrap Dev 例外

**本任务首次 Dev 为一次性 Bootstrap Dev 例外**：
- 首次 Dev 在用户明确 APPROVE 后，由 CodeBuddy 执行（手动生成审批记录）
- 首次 Dev 直接调用 `codex exec -s workspace-write "<Dev Prompt>"`
- 首次 Dev **禁止**运行旧 `codex_dev.sh`（因为旧脚本本身是修复对象，门控尚未就绪）
- 修复完成后，使用新的 `codex_dev.sh` 做门控回归验证
- 此例外仅适用于本 TASK 的首次 Dev；后续所有 TASK 的 Dev 必须通过新 `codex_dev.sh` 门控

## 12. 交互视觉要求

- 无页面/UI 变更
- 文档修改遵循现有 Markdown 风格

## 13. 安全权限要求

- 不碰 `.env` / token / webhook / RQData 密钥 / 任何配置文件
- 禁止 `-s danger-full-access` 和 `--dangerously-bypass-approvals-and-sandbox`
- 安全专家一票否决：护栏自检命中任一即中止
- 敏感信息扫描：`grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' scripts/ai/ --include='*.sh'` 应为 0 匹配
- `collect_result.sh` 脱敏正则覆盖 `token|webhook|password|secret|api[_-]?key|access[_-]?key|QYWX_WEBHOOK`
- CANCEL 不 reset、不删除用户文件

## 14. 开发步骤

> 每步标注是否需用户显式授权

### Step 1: 仓库与脚本现状核对（无需授权，只读）

- 1.1 读取全部 `scripts/ai/*.sh`（15 个），核对契约一致性
- 1.2 确认 Codex CLI 0.144.1 实际支持的 plan/dev 调用方式（已确认：`codex exec -s read-only` / `codex exec -s workspace-write`）
- 1.3 读取 CODEBUDDY.md、AGENTS.md、工作流文档
- 1.4 核对路径、参数、调用方式不一致清单
- 1.5 产出核对结论表

### Step 2: 审批门控实现（需授权后才写入）

- 2.1 创建 `scripts/ai/_approve_lib.sh`（函数库：generate_approval、verify_approval、detect_plan_change、check_branch）
- 2.2 创建 `scripts/ai/approve_task.sh`（命令入口：`--task <TASK_ID>`）
- 2.3 修改 `scripts/ai/codex_dev.sh`：加入 `_approve_lib.sh` 门控验证

### Step 3: Codex CLI 调用规范化（需授权后才写入）

- 3.1 修改 `scripts/ai/codex_plan.sh`：使用 `codex exec -s read-only`，prompt 为位置参数，统一支持 `docs/tasks/` 和 `.ai/tasks/`，产物写 `.ai/results/`
- 3.2 修改 `scripts/ai/codex_dev.sh`：使用 `codex exec -s workspace-write`，prompt 为位置参数，读取完整 TASK 允许/禁止路径和验收标准
- 3.3 硬禁止 `-s danger-full-access` 和 `--dangerously-bypass-approvals-and-sandbox`
- 3.4 产物路径迁移：`scripts/ai/.out/` → `.ai/results/`

### Step 4: run_tests.sh 修复（需授权后才写入）

- 4.1 从 TASK §18.0 fenced bash 代码块解析测试命令
- 4.2 如果 TASK 未声明测试，执行最小默认集：git diff --check + bash -n + 按变更范围选择后端/前端最小测试
- 4.3 安全限制：不使用 eval、逐条执行逐条记录、拒绝危险命令、禁止写出工作区外
- 4.4 测试失败退出非 0

### Step 5: 收集/交付脚本修复（需授权后才写入）

- 5.1 `collect_result.sh`：Result Bundle 完整字段（task_id、branch、git status、changed files、diff --stat、执行命令、测试结果、失败/跳过项、越界检查、敏感信息检查、遗留问题、next_action），区分 pre-existing changes，脱敏处理
- 5.2 `make_delivery_summary.sh`：从真实 Result Bundle 提取生成，不得硬编码

### Step 6: 文档同步（需授权后才写入）

- 6.1 `CODEBUDDY.md`：7 命令协议精确定义（TASK/PLAN/APPROVE/DEV/STATUS/CANCEL/RESULT）、产物路径 `.ai/results/`、审批门控
- 6.2 `docs/workflows/ai_delivery_workflow.md`：同步 Codex CLI 调用方式、产物路径迁移、Lean Task Bundle 流程
- 6.3 `docs/workflows/github_issue_trace_workflow.md`：同步审批门控步骤、产物路径
- 6.4 `docs/workflows/status_machine.md`：增加 APPROVED_DEV 门控说明
- 6.5 `docs/tasks/TASK_TEMPLATE.md`：同步 §18.0 测试命令约定（fenced bash 代码块格式）
- 6.6 `README.md`：如涉及导航更新则同步

### Step 7: 全量验证（需授权后执行）

- 7.1 全部修改脚本 `bash -n` 通过
- 7.2 回归：15 个脚本 `bash -n` 通过
- 7.3 敏感信息 grep 扫描 0 匹配
- 7.4 `git diff --stat` 仅含 §7 允许修改路径
- 7.5 Plan 真实调用 Codex CLI 并确认仓库业务文件零修改
- 7.6 无审批时 Dev 必须拒绝
- 7.7 Plan 变化后旧审批失效
- 7.8 Demo TASK 批准后 Dev 可运行
- 7.9 产物全部进入 `.ai/results/<TASK_ID>/`
- 7.10 Result Bundle 不是硬编码

## 15. Codex Plan Prompt

```
你是 Codex CLI，在归一量化工作站仓库中执行只读 Plan。

Codex CLI 调用方式：codex exec -s read-only
禁止：danger-full-access、修改任何文件

## 必读文件（按顺序）

1. AGENTS.md — 项目定位、技术栈、安全边界
2. CODEBUDDY.md — CodeBuddy 本地执行控制器指令
3. docs/workflows/ai_delivery_workflow.md — AI 半自动交付流程 SOP
4. docs/workflows/status_machine.md — 任务状态机
5. docs/workflows/github_issue_trace_workflow.md — GitHub Issue 留痕流程
6. 本任务单全文：docs/tasks/TASK-2026-07-11-001-workstation-lean-v1-closeout.md
7. scripts/ai/ 下所有现有脚本（15 个 .sh 文件）

## 环境事实（已确认，直接使用）

- Codex CLI 版本：0.144.1，路径：/opt/homebrew/bin/codex
- sandbox 值：read-only / workspace-write / danger-full-access（danger-full-access 禁止）
- prompt 为位置参数，不支持 --prompt flag
- 当前分支：feature/workstation-lean-v1-closeout，工作区干净
- 15 个 scripts/ai/*.sh 均通过 bash -n
- 兼容 wrapper 脚本（codexplan.sh 等无下划线版本）为旧版，不做修改

## 任务

TASK-2026-07-11-001：归一量化单项目工作站精简收口与Demo前置修复

只读，不修改任何文件。输出以下 10 项：

### 1. 理解摘要
- 当前脚本与文档的契约不一致清单（路径、参数、调用方式）
- 确认 Codex CLI 0.144.1 实际支持的调用方式（codex exec -s read-only / codex exec -s workspace-write）
- 确认 danger-full-access 为禁止项

### 2. 拟修改文件列表
- 精确路径，区分新增/修改，标注每项的变更原因
- 必须包含 scripts/ai/approve_task.sh（新增）和 scripts/ai/_approve_lib.sh（新增）
- 只能列出 §7 "允许修改"中的文件

### 3. Codex CLI 调用方案
- Plan：codex exec -s read-only "<prompt>"
- Dev：codex exec -s workspace-write "<prompt>"
- 禁止 danger-full-access 和 --dangerously-bypass-approvals-and-sandbox

### 4. 审批门控设计
- approve_task.sh 完整设计（--task <TASK_ID>）
- _approve_lib.sh 函数签名（generate_approval、verify_approval、detect_plan_change、check_branch）
- 审批记录 JSON 格式（.ai/approvals/<TASK_ID>.json）
- codex_dev.sh 中的门控插入点

### 5. 产物路径迁移方案
- scripts/ai/.out/ → .ai/results/ 迁移
- .ai/logs/ 统一日志路径
- 向后兼容策略

### 6. TASK 完整读取方案
- codex_plan.sh 如何读取完整 TASK（支持 docs/tasks/ 和 .ai/tasks/）
- codex_dev.sh 如何读取完整 TASK（允许/禁止路径、测试命令、验收标准）

### 7. 测试策略设计
- run_tests.sh 修改后的测试命令解析逻辑（从 §18.0 fenced bash 代码块）
- 安全限制设计
- 最小默认测试集
- TASK 未声明测试时的 fallback

### 8. Result Bundle 完整字段设计
- collect_result.sh 修改后应收集的全部字段
- make_delivery_summary.sh 修改后的生成逻辑
- 区分 pre-existing changes 与本次变更

### 9. CODEBUDDY.md 命令协议设计
- 7 个命令（TASK/PLAN/APPROVE/DEV/STATUS/CANCEL/RESULT）的具体定义
- 与现有工作流的兼容性

### 10. 风险点与缓解措施
- 每个修改点的风险评级（P0/P1/P2）
- 对应的缓解措施

## 确认条款

- 不触碰 data/、.env、业务代码（services/、apps/、策略）
- 不自动 push/merge/deploy
- 禁止 danger-full-access
- Issue Gate：无 Issue 不开发
- 审批铁律：无审批不 Dev，main 分支拒绝 Dev
- 修改范围仅限 §7 允许修改列表
- Plan 为只读执行，不得修改任何文件
```

## 16. Codex Dev Prompt

```
你现在是 Codex CLI，处于 dev（workspace-write）模式，执行已批准 Plan。

Codex CLI 调用方式：codex exec -s workspace-write
禁止：danger-full-access、--dangerously-bypass-approvals-and-sandbox

## 范围（严格限定，越界即中止）

只能修改 §7 "允许修改"中的文件：
- CODEBUDDY.md
- README.md
- docs/tasks/TASK_TEMPLATE.md
- docs/tasks/TASK-2026-07-11-001-workstation-lean-v1-closeout.md
- docs/workflows/ai_delivery_workflow.md
- docs/workflows/github_issue_trace_workflow.md
- docs/workflows/status_machine.md
- scripts/ai/codex_plan.sh（修改）
- scripts/ai/codex_dev.sh（修改）
- scripts/ai/run_tests.sh（修改）
- scripts/ai/collect_result.sh（修改）
- scripts/ai/make_delivery_summary.sh（修改）
- scripts/ai/comment_issue_result.sh（修改）
- scripts/ai/update_issue_status.sh（修改）
- scripts/ai/_approve_lib.sh（新增）
- scripts/ai/approve_task.sh（新增）
- 相关工作站测试 fixture

## 禁止修改（硬约束）

- scripts/ai/create_issue_from_task.sh
- scripts/ai/link_task_issue.sh
- scripts/ai/run_v12_post_auth_e2e.sh
- 兼容 wrapper 脚本（codexplan.sh、codexdev.sh、runtests.sh、collectresult.sh、makedeliverysummary.sh）
- docs/AI_WECHAT_WORKFLOW.md
- services/、apps/、packages/、data/ 下任何文件
- 策略代码（strategies/）
- .env / .env.* / 密钥 / webhook / token
- 读取或写入任何凭证
- git push / merge / release / deploy
- 删除历史数据、rm -rf、全权限 mode
- danger-full-access
- 真实发送企业微信、自动交易

## 首次 Dev 为 Bootstrap 例外

- 首次 Dev 禁止运行旧 codex_dev.sh（旧脚本自身是修复对象）
- 首次 Dev 由 CodeBuddy 直接执行本 Prompt
- 修复完成后：使用新 codex_dev.sh 做门控回归验证

## 开发任务

1. 创建 scripts/ai/_approve_lib.sh：函数库（generate_approval、verify_approval、detect_plan_change、check_branch）
2. 创建 scripts/ai/approve_task.sh：命令入口（--task <TASK_ID>）
3. 修改 scripts/ai/codex_plan.sh：使用 codex exec -s read-only，统一支持 docs/tasks/ 和 .ai/tasks/，产物写 .ai/results/
4. 修改 scripts/ai/codex_dev.sh：使用 codex exec -s workspace-write，加入 _approve_lib.sh 门控，读取完整 TASK 允许/禁止路径和验收标准
5. 修改 scripts/ai/run_tests.sh：从 TASK §18.0 解析测试命令，安全限制，fallback 最小默认集
6. 修改 scripts/ai/collect_result.sh：Result Bundle 完整字段，脱敏处理，区分 pre-existing changes
7. 修改 scripts/ai/make_delivery_summary.sh：从 Result Bundle 提取生成
8. 修改 scripts/ai/comment_issue_result.sh：产物路径 .ai/results/
9. 修改 scripts/ai/update_issue_status.sh：产物路径 .ai/results/
10. 同步 CODEBUDDY.md：7 命令协议（TASK/PLAN/APPROVE/DEV/STATUS/CANCEL/RESULT）
11. 同步 docs/workflows/ai_delivery_workflow.md
12. 同步 docs/workflows/github_issue_trace_workflow.md
13. 同步 docs/workflows/status_machine.md
14. 同步 docs/tasks/TASK_TEMPLATE.md
15. 同步 README.md（如涉及导航更新）

## 完成后

- bash -n scripts/ai/*.sh（15 个全通过）
- 敏感信息 grep 扫描 0 匹配
- git diff --stat 仅含允许路径
- 退出码 0 表示成功
```

## 17. CodeBuddy 执行 Prompt

```
CodeBuddy：按本任务单 docs/tasks/TASK-2026-07-11-001-workstation-lean-v1-closeout.md 执行 Bootstrap Dev。

本任务首次 Dev 为一次性 Bootstrap Dev 例外。步骤如下：

1. 验证审批记录存在（.ai/approvals/TASK-2026-07-11-001-workstation-lean-v1-closeout.json）
2. 护栏自检（任一命中即中止）：要求改 .env/token/webhook？自动 push/merge/deploy？删数据？自动交易？使用 danger-full-access？→ 中止并报安全专家
3. 首次 Dev 不运行旧 scripts/ai/codex_dev.sh（旧脚本自身是修复对象）
4. 首次 Dev 直接执行：codex exec -s workspace-write "<TASK §16 完整 Dev Prompt>"
5. 修复完成后：运行新 scripts/ai/codex_dev.sh --task TASK-2026-07-11-001-workstation-lean-v1-closeout 做门控回归验证
6. 运行回归：bash -n scripts/ai/*.sh（15 个全通过）
7. 运行测试：bash scripts/ai/run_tests.sh --task TASK-2026-07-11-001-workstation-lean-v1-closeout
8. 敏感信息扫描：grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' scripts/ai/ --include='*.sh'
9. 收集结果：bash scripts/ai/collect_result.sh --task TASK-2026-07-11-001-workstation-lean-v1-closeout
10. 生成交付摘要：bash scripts/ai/make_delivery_summary.sh --task TASK-2026-07-11-001-workstation-lean-v1-closeout
11. 回传结果摘要给 WorkBuddy / 用户。不自动 push / merge / deploy。
```

## 18. 测试清单

### 18.0 自动化测试命令

```bash
# 全脚本语法检查
bash -n scripts/ai/*.sh

# 敏感信息扫描
grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' scripts/ai/ --include='*.sh'

# Git 差异范围检查
git diff --stat

# Git 空白检查
git diff --check
```

### 18.1 手动检查项

- [ ] `bash -n scripts/ai/_approve_lib.sh` — 语法检查（单元）
- [ ] `bash -n scripts/ai/approve_task.sh` — 语法检查（单元）
- [ ] `bash -n scripts/ai/codex_dev.sh` — 修改后语法（回归）
- [ ] `bash -n scripts/ai/codex_plan.sh` — 修改后语法（回归）
- [ ] `bash -n scripts/ai/run_tests.sh` — 修改后语法（回归）
- [ ] `bash -n scripts/ai/collect_result.sh` — 修改后语法（回归）
- [ ] `bash -n scripts/ai/make_delivery_summary.sh` — 修改后语法（回归）
- [ ] `bash -n scripts/ai/*.sh` — 全脚本语法回归（回归）
- [ ] 审批门控：无审批拒绝 Dev（集成）
- [ ] 审批门控：main 分支拒绝 Dev（集成）
- [ ] 审批门控：Plan 变更后审批失效（集成）
- [ ] `run_tests.sh` 从 §18.0 正确解析 fenced bash 代码块（单元）
- [ ] `run_tests.sh` 拒绝危险命令（安全）
- [ ] `run_tests.sh` TASK 未声明测试时执行最小默认集（单元）
- [ ] `collect_result.sh` Result Bundle 字段完整（集成）
- [ ] `make_delivery_summary.sh` 正确提取（集成）
- [ ] `git diff --stat` 仅含 §7 允许路径（范围校验）
- [ ] 敏感信息 grep 扫描：0 匹配（安全）
- [ ] `git diff --check` 无异常空白（回归）
- [ ] Plan 真实调用 Codex CLI 且仓库业务文件零修改（集成）
- [ ] 现有 GitHub Issue 脚本回归（回归）

## 19. 验收标准

**pass 条件**（全部满足）：

1. WorkBuddy 一次输出完整 Task Bundle（本任务单即为示范）
2. 用户只需把 TASK 转发给 CodeBuddy 一次
3. CodeBuddy 可执行 PLAN 并返回摘要
4. 用户回复 APPROVE 后才能 DEV
5. Codex CLI 是唯一代码执行器（codex exec -s read-only / workspace-write）
6. Dev 后自动测试并生成通用 Result Bundle
7. 文档、参数和产物目录完全一致（.ai/results/、.ai/logs/）
8. 不修改归一量化业务代码和数据
9. 不增加云部署或复杂调度
10. 可以进入 Lean V1 Demo

**block 条件**（任一即不通过）：

- 修改触及 §7 "禁止修改"中任何文件
- 使用 `-s danger-full-access` 或 `--dangerously-bypass-approvals-and-sandbox`
- 含 `rm -rf` 或全权限 mode
- 真实发送企业微信或真实写入数据库
- 自动 push / merge / deploy
- 密钥泄漏到产物/日志
- Result Bundle 硬编码特定任务内容
- 无审批时 Dev 不拒绝

## 20. 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|---------|
| P0 | 修改 scripts/ai/ 引入新 bug 导致既有流程中断 | `bash -n` 全量回归 + `run_tests.sh` 验证 |
| P0 | 审批门控实现后自身存在绕过漏洞 | 安全专家审查 + 护栏自检 + main 分支拒绝 |
| P0 | Codex CLI 调用方式与实际版本不匹配 | 已确认 0.144.1 支持 -s read-only/workspace-write，Plan 实际调用验证 |
| P1 | Codex dev 越界改业务代码 | `git diff` 范围校验 + 护栏自检；越界即 FAILED |
| P1 | 密钥泄漏到产物/文档 | `collect_result.sh` 脱敏 + 敏感 grep 扫描 |
| P1 | Bootstrap Dev 例外被滥用（后续任务绕过门控） | §11.8 明确一次性例外 + CodeBuddy 拒绝后续绕过 |
| P1 | run_tests.sh 解析 §18.0 fenced bash 代码块失败 | 稳健解析 + fallback 最小默认集 + bash -n 预检 |
| P1 | 产物路径迁移后旧脚本不兼容 | 保留旧路径 fallback 检查 + 兼容 wrapper 不做修改 |
| P2 | make_delivery_summary.sh 仍含硬编码 | 从 Result Bundle 动态提取 + 交付专家验证 |
| P2 | 文档同步遗漏 | Plan 输出同步检查清单 + 全量验证 |

## 21. 交付记录

- **状态流转**：REQUIREMENT_READY → PLAN_READY → [用户 APPROVE] → APPROVED_DEV → CODING → TESTING → DELIVERY_READY；等待用户 review 后再进入 CLOSED
- **Issue 创建**：已创建 `#6`，Issue Gate 已通过
- **Plan 完成**：2026-07-11 11:34:22 +0800（只读 Plan 已完成）
- **Plan 产物**：`.ai/results/TASK-2026-07-11-001-workstation-lean-v1-closeout/plan_result.md`
- **审批记录**：`.ai/approvals/TASK-2026-07-11-001-workstation-lean-v1-closeout.json`
- **Dev 完成**：2026-07-11，严格限定 §7 白名单，未触碰业务代码、数据和远程操作
- **测试结论**：通过；17 个 `scripts/ai/*.sh` 逐文件 `bash -n`、TASK §18.0、审批/Plan 变更/Result Bundle Gate 均通过
- **交付报告**：`.ai/results/TASK-2026-07-11-001-workstation-lean-v1-closeout/delivery_summary.md`
- **合并前检查**：`git diff --check` 通过；等待用户人工 review/commit
- **用户 review**：待
- **下一阶段建议**：Lean V1 Demo 演练 → 2–3 个真实业务 TASK 验证
