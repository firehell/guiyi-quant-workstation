# TASK-2026-07-10-003：归一量化单项目工作站精简收口与Demo前置修复

> 团队：归一量化产品与交付工作站
> 状态：REQUIREMENT_READY
> 任务类型：AI 工作流优化（Bootstrap 收口 + Codex CLI 调用规范化 + 审批门控 + 测试/收集/交付修复）
> 生成：WorkBuddy（按 TASK_TEMPLATE.md 21 字段模板）
> 配套：CODEBUDDY.md、AGENTS.md、ai_delivery_workflow.md、status_machine.md、github_issue_trace_workflow.md
> 性质：**Bootstrap 收口任务**——对 scripts/ai/ 下所有脚本做统一收口修正，补齐审批门控，修复测试/收集/交付流程，建立 Codex CLI 规范调用方式。**首次 Dev 为一次性 Bootstrap Dev 例外**，修复完成后以新 codex_dev.sh 做门控回归。

> **状态门控说明（务必先读）**：本任务单当前处于 `REQUIREMENT_READY`。下方第 15–17 节的《Codex Plan Prompt / Dev Prompt / CodeBuddy 执行 Prompt》是**随单携带的草案**，按状态机规则：
> - Plan Prompt 在 `PLAN_READY` 由 CodeBuddy 直接调用 `codex exec --sandbox read-only` 执行（只读）；
> - Dev Prompt 在 `APPROVED_DEV` 才启用。
> **WorkBuddy 本次只产出本任务单文档，不修改代码、不执行任何脚本。**

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-10-003-workstation-lean-v1-closeout |
| GitHub Issue | #5 |
| Branch | feature/workstation-lean-v1-closeout |
| PR | 待创建 |
| Status | REQUIREMENT_READY |
| Created At | 2026-07-10 |
| Updated At | 2026-07-11 |
| Owner | WorkBuddy |

---

## 1. 任务状态

REQUIREMENT_READY

## 2. 任务类型

AI 工作流优化（Bootstrap 收口 + Codex CLI 调用规范化 + 审批门控 + 测试/收集/交付修复）
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

- V1.1（工作站脚本脚手架）已完成 `scripts/ai/` 下 5 个核心脚本的落地。
- V1.2（GitHub Issue 留痕）已完成 TASK ↔ Issue 双向同步机制。
- **当前痛点**：
  - `scripts/ai/` 下脚本的契约不一致：路径、参数、调用方式存在偏差
  - Codex CLI 0.144.1 实际支持的调用方式需确认，sandbox 约束需显式声明
  - 缺少审批门控：无审批即可 Dev，main 分支可能被误操作
  - `run_tests.sh` 测试命令解析逻辑不完整
  - `collect_result.sh` 和 `make_delivery_summary.sh` 产物路径和字段不完整
  - CODEBUDDY.md 中对 CODEBUDDY 命令协议的说明不够精确
- 需要对整个 `scripts/ai/` 做一次统一收口，规范化 Codex CLI 调用，补齐审批门控，修复测试/收集/交付流程。

## 5. 目标

1. **读取 scripts/ai/ 全部脚本（15 个）**，核对契约一致性（路径、参数、调用方式）
2. **确认 Codex CLI 0.144.1 实际支持的 Plan/Dev 调用方式**（基于 `codex exec --help` 输出）
3. **设计审批门控**：`approve_task.sh` 和 `_approve_lib.sh`
4. **规范化 Codex CLI 调用**：Plan 用 `codex exec --sandbox read-only`，Dev 用 `codex exec --sandbox workspace-write`，禁止 `--sandbox danger-full-access`
5. **修复 run_tests.sh**：从 TASK §18.0 fenced bash 代码块解析测试命令
6. **修复 collect_result.sh 和 make_delivery_summary.sh**：Result Bundle 完整字段、交付摘要生成
7. **同步 CODEBUDDY.md**：7 个命令协议精确定义
8. **README.md**：如涉及导航更新则同步
9. **产出 Plan 方案**，等待用户 APPROVE 后执行 Bootstrap Dev

## 6. 不做事项

- ❌ 不修改 `services/`、`apps/`、`packages/` 下的任何业务代码
- ❌ 不修改 `data/` 下的任何数据文件
- ❌ 不修改策略代码
- ❌ 不修改 `.env`、密钥、webhook
- ❌ 不 `git push` / `git merge` / `git release` / `git deploy`
- ❌ 不删除任何历史数据
- ❌ 不真实发送企业微信、不自动交易
- ❌ 不使用 `--sandbox danger-full-access`
- ❌ 不修改 `.workbuddy/memory/2026-07-10.md`

## 7. 涉及模块

- **允许修改**：
  - `CODEBUDDY.md`
  - `README.md`
  - `docs/tasks/TASK_TEMPLATE.md`
  - `docs/tasks/TASK-2026-07-10-003-workstation-lean-v1-closeout.md`
  - `docs/workflows/ai_delivery_workflow.md`
  - `docs/workflows/github_issue_trace_workflow.md`
  - `scripts/ai/codex_plan.sh`
  - `scripts/ai/codex_dev.sh`
  - `scripts/ai/run_tests.sh`
  - `scripts/ai/collect_result.sh`
  - `scripts/ai/make_delivery_summary.sh`
  - `scripts/ai/comment_issue_result.sh`
  - `scripts/ai/update_issue_status.sh`
  - `scripts/ai/_approve_lib.sh`（新增）
  - `scripts/ai/approve_task.sh`（新增）
- **禁止修改**：
  - `scripts/ai/create_issue_from_task.sh`
  - `scripts/ai/link_task_issue.sh`
  - `scripts/ai/run_v12_post_auth_e2e.sh`
  - 任何兼容 wrapper 脚本
  - `docs/AI_WECHAT_WORKFLOW.md`
  - `.workbuddy/memory/2026-07-10.md`
  - `services/`（全部）
  - `apps/`（全部）
  - `packages/`（全部）
  - `data/`（全部）
  - 策略代码（`strategies/`）
  - `.env` / `.env.*`
  - 密钥、webhook、token 文件

## 8. 产品需求

- scripts/ai/ 脚本契约一致性核对无遗漏
- Codex CLI 调用方式已确认且文档化
- 审批门控脚本存在且 `bash -n` 通过
- `codex_dev.sh` 含审批验证门控
- `run_tests.sh` 从 §18.0 正确解析测试命令
- `collect_result.sh` Result Bundle 字段完整
- `make_delivery_summary.sh` 从 Result Bundle 正确提取
- CODEBUDDY.md 命令协议准确
- 全部修改脚本 `bash -n` 通过

## 9. 量化业务规则

- 本任务**不涉及期货业务规则**（非数据/策略/信号任务）
- 新增/修改文字必须继承 V1 约束：不自动交易、不把信号当交易指令

## 10. 数据影响

- 无数据读写：不读取、不写入、不删除任何行情 / DB / parquet 数据
- 不触发 RQData、不写数据库、不真实发送企业微信

## 11. 技术方案

### 11.1 Codex CLI 调用规范化

- Plan 调用：`codex exec --sandbox read-only "<prompt>"`（prompt 为位置参数，禁止 `--prompt` flag）
- Dev 调用：`codex exec --sandbox workspace-write "<prompt>"`（prompt 为位置参数，禁止 `--prompt` flag）
- **硬禁止**：`--sandbox danger-full-access`
- 确认基于 `codex exec --help` 输出

### 11.2 审批门控设计

- `scripts/ai/_approve_lib.sh`（新增）：函数库
  - `generate_approval()`：生成审批记录 JSON，含 plan SHA256、TASK_ID、分支、时间戳
  - `verify_approval()`：验证审批记录有效性和 Plan 哈希一致性
  - `detect_plan_change()`：比较当前 plan_result.md SHA256 与审批记录中哈希
  - `check_branch()`：拒绝 main 分支
- `scripts/ai/approve_task.sh`（新增）：命令入口
  - 命令格式：`approve_task.sh --task <TASK_ID>`
  - 计算 plan_result.md SHA256
  - 绑定 TASK_ID 和目标分支
  - 写入批准时间
  - 拒绝条件：main 分支、Plan 缺失、哈希无法计算

### 11.3 codex_dev.sh 门控改造

- 通过 `_approve_lib.sh` 验证审批记录和当前 Plan 哈希
- 验证失败 → 拒绝 Dev，返回错误
- main 分支 → 拒绝 Dev
- 审批记录格式：`.ai/approvals/<TASK_ID>.json`

### 11.4 run_tests.sh 测试命令解析

- 从 TASK §18.0 固定位置 fenced bash 代码块解析测试命令
- 不使用 eval
- 逐条执行逐条记录退出码
- 拒绝危险命令（rm -rf、sudo 等）
- 禁止写出工作区外

### 11.5 collect_result.sh 与 make_delivery_summary.sh

- Result Bundle 完整字段设计
- 区分 pre-existing changes 与本次变更
- 脱敏处理

### 11.6 CODEBUDDY.md 命令协议

- 7 个命令：PLAN、APPROVE、DEV、TEST、COLLECT、DELIVERY、STATUS
- 每个命令的前置条件、行为、产物
- APPROVE 命令调用 `approve_task.sh`
- DEV 命令拒绝 main 分支

### 11.7 一次性 Bootstrap Dev 例外

**本任务首次 Dev 为一次性 Bootstrap Dev 例外**：
- 首次 Dev 直接在用户明确 APPROVE 后，由 CodeBuddy 执行（手动生成审批记录）
- 首次 Dev 直接调用 `codex exec --sandbox workspace-write "<Dev Prompt>"`
- 首次 Dev **禁止**运行旧 `codex_dev.sh`（因为旧脚本本身是修复对象，门控尚未就绪）
- 修复完成后，使用新的 `codex_dev.sh` 做门控回归验证
- 此例外仅适用于本 TASK 的首次 Dev；后续所有 TASK 的 Dev 必须通过新 `codex_dev.sh` 门控

## 12. 交互视觉要求

- 无页面/UI 变更
- 文档修改遵循现有 Markdown 风格

## 13. 安全权限要求

- 不碰 `.env` / token / webhook / RQData 密钥 / 任何配置文件
- 禁止 `--sandbox danger-full-access`
- 安全专家一票否决：护栏自检命中任一即中止
- 敏感信息扫描：`grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' scripts/ai/ --include='*.sh'` 应为 0 匹配
- `collect_result.sh` 脱敏正则覆盖 `token|webhook|password|secret|api[_-]?key|access[_-]?key`

## 14. 开发步骤

> 每步标注是否需用户显式授权

### Step 1: 仓库与脚本现状核对（无需授权，只读）

- 1.1 读取全部 `scripts/ai/*.sh`（15 个），核对契约一致性
- 1.2 确认 Codex CLI 0.144.1 实际支持的 plan/dev 调用方式（`codex exec --help`）
- 1.3 读取 CODEBUDDY.md、AGENTS.md、工作流文档
- 1.4 核对路径、参数、调用方式不一致清单

### Step 2: 审批门控实现（需授权后才写入）

- 2.1 创建 `scripts/ai/_approve_lib.sh`（函数库）
- 2.2 创建 `scripts/ai/approve_task.sh`（命令入口）
- 2.3 修改 `scripts/ai/codex_dev.sh`：加入 `_approve_lib.sh` 门控验证

### Step 3: Codex CLI 调用规范化（需授权后才写入）

- 3.1 修改 `scripts/ai/codex_plan.sh`：prompt 为位置参数，禁止 `--prompt`
- 3.2 修改 `scripts/ai/codex_dev.sh`：prompt 为位置参数，禁止 `--prompt`
- 3.3 硬禁止 `--sandbox danger-full-access`

### Step 4: run_tests.sh 修复（需授权后才写入）

- 4.1 从 TASK §18.0 fenced bash 代码块解析测试命令
- 4.2 安全限制：不使用 eval、逐条执行逐条记录、拒绝危险命令

### Step 5: 收集/交付脚本修复（需授权后才写入）

- 5.1 `collect_result.sh`：Result Bundle 完整字段
- 5.2 `make_delivery_summary.sh`：从 Result Bundle 提取生成

### Step 6: 文档同步（需授权后才写入）

- 6.1 `CODEBUDDY.md`：7 个命令协议精确定义
- 6.2 `docs/workflows/ai_delivery_workflow.md`：同步 Codex CLI 调用方式
- 6.3 `docs/workflows/github_issue_trace_workflow.md`：同步审批门控
- 6.4 `docs/tasks/TASK_TEMPLATE.md`：同步 §18.0 测试命令约定
- 6.5 `README.md`：如涉及导航更新

### Step 7: 全量验证（需授权后执行）

- 7.1 全部修改脚本 `bash -n` 通过
- 7.2 回归：15 个脚本 `bash -n` 通过
- 7.3 敏感信息 grep 扫描 0 匹配
- 7.4 `git diff --stat` 仅含 §7 允许修改路径

## 15. Codex Plan Prompt

```
你是 Codex CLI，在归一量化工作站仓库 `/Volumes/扩展盘/guiyi-quant-workstation` 中执行**只读 Plan**。

## 必读文件（按顺序）

1. AGENTS.md — 项目定位、技术栈、安全边界
2. CODEBUDDY.md — CodeBuddy 本地执行控制器指令
3. docs/workflows/ai_delivery_workflow.md — AI 半自动交付流程 SOP
4. docs/workflows/status_machine.md — 10 状态任务状态机
5. docs/workflows/github_issue_trace_workflow.md — GitHub Issue 留痕流程
6. docs/AI_WECHAT_WORKFLOW.md — 企业微信协作流程
7. 本任务单全文：docs/tasks/TASK-2026-07-10-003-workstation-lean-v1-closeout.md
8. scripts/ai/ 下所有现有脚本（共 15 个）

## 环境事实（已确认，直接使用）

- Codex CLI 版本：0.144.1，路径：/opt/homebrew/bin/codex
- 当前分支：feature/workstation-lean-v1-closeout，工作区干净
- gh 已登录 firehell
- 15 个 scripts/ai/*.sh 均通过 bash -n

## 任务

**TASK-2026-07-10-003：归一量化单项目工作站精简收口与Demo前置修复**

只读，不修改任何文件。输出以下 10 项：

### 1. 理解摘要
- 当前脚本与文档的契约不一致清单（路径、参数、调用方式）
- Codex CLI 0.144.1 实际支持的 plan/dev 调用方式（基于 `codex exec --help` 输出）
- 确认 `codex exec --sandbox read-only` 和 `codex exec --sandbox workspace-write` 为正确调用方式
- 确认 `--sandbox danger-full-access` 为禁止项

### 2. 拟修改文件列表
- 精确路径，区分新增/修改，标注每项的变更原因
- 必须包含 `scripts/ai/approve_task.sh`（新增）和 `scripts/ai/_approve_lib.sh`（新增）
- **只能列出 §7"允许修改"中的文件。** 以下文件不在修改范围内（只读检查）：
  - `scripts/ai/create_issue_from_task.sh`
  - `scripts/ai/link_task_issue.sh`
  - `scripts/ai/run_v12_post_auth_e2e.sh`
  - 兼容 wrapper 脚本
  - `docs/AI_WECHAT_WORKFLOW.md`
  - `.workbuddy/memory/2026-07-10.md`
  - `services/`、`apps/`、`data/`、`.env` 或密钥文件
  - 其他未在 §7 明确列出的文件

### 3. Codex CLI 调用方案
- Plan：`codex exec --sandbox read-only "<prompt>"`（prompt 为位置参数，禁止 --prompt）
- Dev：`codex exec --sandbox workspace-write "<prompt>"`（prompt 为位置参数，禁止 --prompt）
- 确认禁止 `--sandbox danger-full-access`

### 4. 审批门控设计
- `approve_task.sh` 的完整设计（命令格式：`approve_task.sh --task <TASK_ID>`）
  - 计算 plan_result.md 的 SHA256
  - 绑定 TASK_ID 和目标分支
  - 写入批准时间
  - 拒绝条件：main 分支、Plan 缺失、哈希无法计算
- `_approve_lib.sh` 函数签名（生成审批、验证审批、Plan 变更检测、分支检查）
- 审批记录 JSON 格式
- `codex_dev.sh` 中的门控插入点（通过 `_approve_lib.sh` 验证审批记录和当前 Plan 哈希）

### 5. 产物路径迁移方案
- 每个脚本的路径变更清单（旧→新）
- 向后兼容策略（是否保留旧路径 fallback）

### 6. TASK 完整读取方案
- `codex_plan.sh` 如何读取完整 TASK（不仅是第 15 节）
- `codex_dev.sh` 如何读取完整 TASK（允许/禁止路径、测试命令、验收标准）

### 7. 测试策略设计
- `run_tests.sh` 修改后的测试命令解析逻辑
- 安全限制设计（只解析 §18.0 固定位置 fenced bash 代码块、不使用 eval、逐条执行逐条记录退出码、拒绝危险命令、禁止写出工作区）
- 最小默认测试集
- TASK 声明测试命令的格式约定

### 8. Result Bundle 完整字段设计
- `collect_result.sh` 修改后应收集的全部字段
- `make_delivery_summary.sh` 修改后的生成逻辑（如何从 Result Bundle 提取）
- Result Bundle 必须区分 pre-existing changes 与本次变更

### 9. CODEBUDDY.md 命令协议设计
- 7 个命令的具体定义、前置条件、行为、产物
- APPROVE 命令调用 `approve_task.sh`
- DEV 命令拒绝 main 分支
- 与现有工作流的兼容性

### 10. 风险点与缓解措施
- 每个修改点的风险评级（P0/P1/P2）
- 对应的缓解措施

## 确认条款

- 不触碰 data/、.env、业务代码（services/、apps/、策略）
- 不自动 push/merge/deploy
- 禁止 --sandbox danger-full-access
- Issue Gate：无 Issue 不开发
- 审批铁律：无审批不 Dev，main 分支拒绝 Dev
- 修改范围仅限 §7 允许修改列表；未授权文件只读检查
- Plan 为只读执行，不得修改任何文件
- 首次 Dev 只在用户明确 APPROVE 后执行
- 首次 Dev 由 CodeBuddy 手动生成审批记录
- 首次 Dev 直接调用 codex exec --sandbox workspace-write
- 首次 Dev 禁止运行旧 codex_dev.sh
- 修复完成后使用新 codex_dev.sh 做门控回归
- 保护 Dev 前已有脏文件
- Result Bundle 必须区分 pre-existing changes 与本次变更
```

## 16. Codex Dev Prompt

```
你现在是 Codex CLI，处于 dev（workspace-write）模式，执行已批准 Plan。

## 范围（严格限定，越界即中止）

**只能修改 §7 "允许修改"中的文件：**
- `CODEBUDDY.md`
- `README.md`
- `docs/tasks/TASK_TEMPLATE.md`
- `docs/tasks/TASK-2026-07-10-003-workstation-lean-v1-closeout.md`
- `docs/workflows/ai_delivery_workflow.md`
- `docs/workflows/github_issue_trace_workflow.md`
- `scripts/ai/codex_plan.sh`（修改）
- `scripts/ai/codex_dev.sh`（修改）
- `scripts/ai/run_tests.sh`（修改）
- `scripts/ai/collect_result.sh`（修改）
- `scripts/ai/make_delivery_summary.sh`（修改）
- `scripts/ai/comment_issue_result.sh`（修改）
- `scripts/ai/update_issue_status.sh`（修改）
- `scripts/ai/_approve_lib.sh`（新增）
- `scripts/ai/approve_task.sh`（新增）

## 禁止修改（硬约束）

- `scripts/ai/create_issue_from_task.sh`
- `scripts/ai/link_task_issue.sh`
- `scripts/ai/run_v12_post_auth_e2e.sh`
- 任何兼容 wrapper 脚本
- `docs/AI_WECHAT_WORKFLOW.md`
- `.workbuddy/memory/2026-07-10.md`
- `services/`、`apps/`、`packages/`、`data/` 下任何文件
- 策略代码（`strategies/`）
- `.env` / `.env.*` / 密钥 / webhook / token
- 读取或写入任何凭证
- git push / merge / release / deploy
- 删除历史数据、rm -rf、全权限 mode
- `--sandbox danger-full-access`
- 真实发送企业微信、自动交易

## 首次 Dev 为 Bootstrap 例外

- 首次 Dev **禁止**运行旧 `codex_dev.sh`（因为旧脚本自身是修复对象）
- 首次 Dev 由 CodeBuddy 直接执行本 Prompt
- 修复完成后：使用新 `codex_dev.sh` 做门控回归验证

## 开发任务

1. 创建 `scripts/ai/_approve_lib.sh`：函数库（generate_approval、verify_approval、detect_plan_change、check_branch）
2. 创建 `scripts/ai/approve_task.sh`：命令入口（--task <TASK_ID>）
3. 修改 `scripts/ai/codex_plan.sh`：prompt 为位置参数，禁止 --prompt
4. 修改 `scripts/ai/codex_dev.sh`：prompt 为位置参数，加入 _approve_lib.sh 门控
5. 修改 `scripts/ai/run_tests.sh`：从 TASK §18.0 解析测试命令，安全限制
6. 修改 `scripts/ai/collect_result.sh`：Result Bundle 完整字段
7. 修改 `scripts/ai/make_delivery_summary.sh`：从 Result Bundle 提取
8. 同步 `CODEBUDDY.md`：7 命令协议
9. 同步 `docs/workflows/ai_delivery_workflow.md`
10. 同步 `docs/workflows/github_issue_trace_workflow.md`
11. 同步 `docs/tasks/TASK_TEMPLATE.md`

## 完成后

- bash -n scripts/ai/*.sh（15 个全通过）
- 敏感信息 grep 扫描 0 匹配
- git diff --stat 仅含允许路径
- 退出码 0 表示成功
```

## 17. CodeBuddy 执行 Prompt

```
CodeBuddy：按本任务单 docs/tasks/TASK-2026-07-10-003-workstation-lean-v1-closeout.md 执行 Bootstrap Dev。

本任务首次 Dev 为一次性 Bootstrap Dev 例外。步骤如下：

1. 验证审批记录存在（`.ai/approvals/TASK-2026-07-10-003-workstation-lean-v1-closeout.json`）
2. 护栏自检（任一命中即中止）：要求改 .env/token/webhook？自动 push/merge/deploy？删数据？自动交易？使用 danger-full-access？→ 中止并报安全专家
3. 首次 Dev **不运行**旧 `scripts/ai/codex_dev.sh`（旧脚本自身是修复对象）
4. 首次 Dev 直接执行：`codex exec --sandbox workspace-write "<TASK §16 完整 Dev Prompt>"`
5. 修复完成后：运行新 `scripts/ai/codex_dev.sh --task TASK-2026-07-10-003-workstation-lean-v1-closeout` 做门控回归验证
6. 运行回归：bash -n scripts/ai/*.sh（15 个全通过）
7. 运行测试：bash scripts/ai/run_tests.sh --task TASK-2026-07-10-003-workstation-lean-v1-closeout
8. 敏感信息扫描：grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' scripts/ai/ --include='*.sh'
9. 收集结果：bash scripts/ai/collect_result.sh --task TASK-2026-07-10-003-workstation-lean-v1-closeout
10. 生成交付摘要：bash scripts/ai/make_delivery_summary.sh --task TASK-2026-07-10-003-workstation-lean-v1-closeout
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
- [ ] `collect_result.sh` Result Bundle 字段完整（集成）
- [ ] `make_delivery_summary.sh` 正确提取（集成）
- [ ] `git diff --stat` 仅含 §7 允许路径（范围校验）
- [ ] 敏感信息 grep 扫描：0 匹配（安全）
- [ ] `git diff --check` 无异常空白（回归）

## 19. 验收标准

**pass 条件**（全部满足）：

1. `scripts/ai/_approve_lib.sh` 存在且 `bash -n` 通过
2. `scripts/ai/approve_task.sh` 存在且 `bash -n` 通过
3. `codex_dev.sh` 含 `_approve_lib.sh` 门控，无审批拒绝 Dev
4. `codex_dev.sh` 拒绝 main 分支
5. `codex_plan.sh` 和 `codex_dev.sh` prompt 为位置参数，禁止 `--prompt`
6. 硬禁止 `--sandbox danger-full-access`
7. `run_tests.sh` 从 §18.0 fenced bash 代码块正确解析
8. `run_tests.sh` 拒绝危险命令（rm -rf、sudo 等）
9. `collect_result.sh` Result Bundle 区分 pre-existing changes
10. 15 个脚本 `bash -n` 全通过
11. `git diff --stat` 仅含 §7 允许修改路径
12. 敏感信息 grep 扫描 0 匹配

**block 条件**（任一即不通过）：

- 修改触及 §7 "禁止修改"中任何文件
- 修改触及 `.workbuddy/memory/2026-07-10.md`
- 使用 `--sandbox danger-full-access`
- 含 `rm -rf` 或全权限 mode
- 真实发送企业微信或真实写入数据库
- 自动 push / merge / deploy
- 密钥泄漏到产物/日志

## 20. 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|---------|
| P0 | 修改 scripts/ai/ 引入新 bug 导致既有流程中断 | `bash -n` 全量回归 + `run_tests.sh` 验证 |
| P0 | 审批门控实现后自身存在绕过漏洞 | 安全专家审查 + 护栏自检 |
| P1 | Codex dev 越界改业务代码 | `git diff` 范围校验 + 护栏自检；越界即 FAILED |
| P1 | 密钥泄漏到产物/文档 | `collect_result.sh` 脱敏 + 敏感 grep 扫描 |
| P1 | Bootstrap Dev 例外被滥用（后续任务绕过门控） | TASK §11.7 明确一次性例外 + CodeBuddy 拒绝后续绕过 |
| P2 | 旧脚本路径 fallback 兼容性 | 保留旧路径 fallback 策略 |
| P2 | 新 `codex_dev.sh` 门控首次验证可能失败 | Bootstrap 模式首次 Dev 不依赖旧门控，修复后回归 |

## 21. 交付记录

- **状态流转**：REQUIREMENT_READY → PLAN_READY → [用户 APPROVE] → APPROVED_DEV → CODING → TESTING → DELIVERY_READY → [用户 review] → CLOSED
- **Issue 创建**：#5，已创建并关联
- **Plan 完成**：待填写
- **Plan 产物**：`.ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md`
- **Dev 完成**：未完成
- **测试结论**：未完成
- **交付报告**：未完成
- **合并前检查**：未完成
- **用户 review**：待
- **下一阶段建议**：V1.4 多项目 CodeBuddy 调度
