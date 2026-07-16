# TASK-2026-07-11-002：Lean V1 Demo 验证（LEAN-V1-DEMO）

> 团队：归一量化产品与交付工作站
> 状态：REQUIREMENT_READY
> 任务类型：AI 工作流优化（Lean V1 全链路 Demo 验证）
> 生成：WorkBuddy（按 TASK_TEMPLATE.md 21 字段模板，一次生成完整 Task Bundle）
> 配套：CODEBUDDY.md、ai_delivery_workflow.md、status_machine.md、github_issue_trace_workflow.md
> 性质：**Lean V1 Demo 验证任务**——在 `docs/workflows/` 下新增 `LEAN_WORKFLOW_DEMO.md`，记录完整链路验证结果。不修改任何业务代码、数据、策略、配置。

> **Lean V1 核心原则**：本任务单为一次生成完整 Task Bundle，用户只需转发给 CodeBuddy 一次。后续不再分别生成 Plan/Dev/CodeBuddy Prompt。

> **状态门控说明**：本任务单当前处于 `REQUIREMENT_READY`。§15–17 随单携带，按状态机规则：
> - Plan Prompt 在 `PLAN_READY` 由 CodeBuddy 调用 `codex exec -s read-only` 执行（只读）；
> - Dev Prompt 在 `APPROVED_DEV` 才启用，且必须先有有效审批记录。
> **WorkBuddy 本次只产出本任务单文档，不修改代码、不执行任何脚本。**

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-11-002-lean-v1-demo |
| GitHub Issue | #7 |
| Branch | feature/lean-v1-demo |
| PR | 待创建 |
| Status | DELIVERY_READY |
| Created At | 2026-07-11 |
| Updated At | 2026-07-11 |
| Owner | WorkBuddy |

---

## 1. 任务状态

REQUIREMENT_READY

## 2. 任务类型

AI 工作流优化（Lean V1 全链路 Demo 验证）
- 关联：CodeBuddy 本地执行控制器（CODEBUDDY.md）、AI 半自动交付流程（ai_delivery_workflow.md）、GitHub Issue 留痕流程（github_issue_trace_workflow.md）
- 参照：TASK_MATRIX.md「12. AI 工作流优化」「13. CodeBuddy / Codex / WorkBuddy 协作优化」
- 是否允许进入代码开发阶段：**是**（严格限定 §7 允许修改文件；不碰业务/数据/策略/配置）

## 3. 参与角色

- **必须**：
  - 项目经理 / 流程调度员（编号、状态、Demo 执行确认）
  - 后端开发负责人（Demo 文档产出、验证记录填写）
  - 测试专家 / QA Lead（文件存在性、内容校验、git diff 范围检查）
  - 安全与权限专家（敏感信息扫描、护栏自检）
  - 交付专家（Demo 交付确认）
- **可选**：
  - DevOps / 本地运维部署专家（Codex CLI 调用验证）
- **不需要**：
  - 产品负责人（无新用户场景）
  - 量化业务专家（非数据/行情/策略任务）
  - 策略研究员（非策略逻辑）
  - 数据工程师（非 RQData/聚合）
  - 交互视觉专家（无页面设计）

## 4. 背景

- TASK-2026-07-11-001（WORKSTATION-LEAN-V1-CLOSEOUT）已定义工作站 Lean V1 收口方案，待执行。
- 收口完成后，需要一个最小 Demo 验证完整链路：企业微信→WorkBuddy 完整 TASK→CodeBuddy→Codex Plan→用户批准→Codex Dev→测试→Result Bundle→企业微信。
- 本 Demo 只验证工作站流程本身，不修改任何归一量化业务代码和数据。
- Demo 产出物为一份 `docs/workflows/LEAN_WORKFLOW_DEMO.md` 文档，记录验证过程和结果。

## 5. 目标

1. 验证 Lean V1 完整链路：企业微信→WorkBuddy 完整 TASK→CodeBuddy→Codex Plan→用户批准→Codex Dev→测试→Result Bundle→企业微信。
2. 在 `docs/workflows/` 下新增 `LEAN_WORKFLOW_DEMO.md`，内容必须包含：
   - Demo TASK_ID
   - 执行时间
   - 本次只验证工作站流程
   - 明确未修改归一量化业务代码
   - 明确未 push、merge、deploy
   - 明确 Codex CLI 是唯一代码执行器
3. 不修改任何业务代码、数据、策略、配置。

## 6. 不做事项

- ❌ 不修改 `services/`、`apps/`、`packages/` 下的任何业务代码
- ❌ 不修改 `data/` 下的任何数据文件
- ❌ 不修改策略代码、量化业务逻辑
- ❌ 不修改 `.env`、密钥、webhook、token
- ❌ 不自动 push、merge、deploy
- ❌ 不自动关闭 Issue
- ❌ 不真实发送企业微信
- ❌ 不使用 `--sandbox danger-full-access`
- ❌ 不修改 `scripts/ai/` 下任何脚本
- ❌ 不修改除 `docs/workflows/LEAN_WORKFLOW_DEMO.md` 以外的任何文件

## 7. 涉及模块

- **允许修改**：
  - `docs/workflows/LEAN_WORKFLOW_DEMO.md`（新增）
- **禁止修改**：
  - 除上述文件外的所有文件，尤其：
    - `services/`（全部）
    - `apps/`（全部）
    - `packages/`（全部）
    - `data/`（全部）
    - 策略代码（`strategies/`）
    - `scripts/ai/`（全部）
    - `.env` / `.env.*`
    - 密钥、webhook、token 文件
    - `CODEBUDDY.md`、`AGENTS.md`
    - `docs/tasks/` 下已有任务单
    - `docs/workflows/` 下已有文档

## 8. 产品需求

- Demo 文档存在且内容完整
- Demo 文档必须包含 TASK_ID
- Demo 文档必须声明：未修改归一量化业务代码
- Demo 文档必须声明：未 push、merge、deploy
- Demo 文档必须声明：Codex CLI 是唯一代码执行器
- Demo 文档必须记录执行时间
- Demo 文档必须声明：本次只验证工作站流程

## 9. 量化业务规则

- 本任务**不涉及期货业务规则**（非数据/策略/信号任务）
- Demo 文档中的文字必须继承 V1 约束：不自动交易、不把信号当交易指令

## 10. 数据影响

- 无数据读写：不读取、不写入、不删除任何行情 / DB / parquet 数据
- 不触发 RQData、不写数据库、不真实发送企业微信

## 11. 技术方案

### 11.1 Demo 文档结构

`docs/workflows/LEAN_WORKFLOW_DEMO.md` 包含以下章节：

1. **Demo 概述**：验证目标、验证范围
2. **Demo TASK_ID**：TASK-2026-07-11-002-lean-v1-demo
3. **执行时间**：实际执行日期时间
4. **验证范围声明**：本次只验证工作站流程
5. **链路验证记录**：
   - 企业微信 → WorkBuddy（TASK 接收）
   - WorkBuddy → CodeBuddy（TASK 转发）
   - CodeBuddy → Codex Plan（只读 Plan）
   - 用户批准（APPROVE）
   - CodeBuddy → Codex Dev（workspace-write）
   - 测试执行（run_tests.sh）
   - Result Bundle 生成（collect_result.sh）
   - 企业微信回传（脱敏摘要）
6. **安全声明**：
   - 未修改归一量化业务代码
   - 未 push、merge、deploy
   - Codex CLI 是唯一代码执行器
   - 未使用 danger-full-access
7. **验证结论**：通过/未通过 + 遗留问题

### 11.2 Codex CLI 调用方式

- 已确认 Codex CLI 版本：0.144.1，路径 `/opt/homebrew/bin/codex`
- Plan 调用：`codex exec -s read-only "<prompt>"`
- Dev 调用：`codex exec -s workspace-write "<prompt>"`
- **硬禁止**：`-s danger-full-access`

### 11.3 产物路径

- Demo 文档：`docs/workflows/LEAN_WORKFLOW_DEMO.md`
- Plan 产物：`.ai/results/TASK-2026-07-11-002-lean-v1-demo/plan_result.md`
- 审批记录：`.ai/approvals/TASK-2026-07-11-002-lean-v1-demo.json`
- Result Bundle：`.ai/results/TASK-2026-07-11-002-lean-v1-demo/result_bundle.md`
- 日志：`.ai/logs/`

## 12. 交互视觉要求

- 无页面/UI 变更
- 文档修改遵循现有 Markdown 风格

## 13. 安全权限要求

- 不碰 `.env` / token / webhook / RQData 密钥 / 任何配置文件
- 禁止 `-s danger-full-access` 和 `--dangerously-bypass-approvals-and-sandbox`
- 安全专家一票否决：护栏自检命中任一即中止
- 敏感信息扫描：`grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' docs/workflows/LEAN_WORKFLOW_DEMO.md` 应为 0 匹配
- `git diff --stat` 必须仅含 `docs/workflows/LEAN_WORKFLOW_DEMO.md` 一个文件

## 14. 开发步骤

> 每步标注是否需用户显式授权

### Step 1: Plan 执行（需用户确认 Plan 后执行）

- 1.1 CodeBuddy 调用 `codex exec -s read-only` 执行 §15 Plan Prompt
- 1.2 Plan 产出写入 `.ai/results/TASK-2026-07-11-002-lean-v1-demo/plan_result.md`
- 1.3 确认 Plan 为只读，仓库业务文件零修改

### Step 2: 用户批准（需用户显式 APPROVE）

- 2.1 用户审阅 Plan 结果
- 2.2 用户回复 `APPROVE TASK-2026-07-11-002-lean-v1-demo`
- 2.3 CodeBuddy 调用 `approve_task.sh --task TASK-2026-07-11-002-lean-v1-demo` 生成审批记录

### Step 3: Dev 执行（需审批通过后执行）

- 3.1 CodeBuddy 调用 `codex exec -s workspace-write` 执行 §16 Dev Prompt
- 3.2 Dev 产出 `docs/workflows/LEAN_WORKFLOW_DEMO.md`
- 3.3 确认 Dev 仅修改了 `docs/workflows/LEAN_WORKFLOW_DEMO.md` 一个文件

### Step 4: 测试（Dev 完成后自动执行）

- 4.1 运行 `bash scripts/ai/run_tests.sh --task TASK-2026-07-11-002-lean-v1-demo`
- 4.2 验证文件存在
- 4.3 验证文件内容包含 TASK_ID
- 4.4 验证 `git diff --check` 无异常
- 4.5 验证 `git diff --stat` 仅含一个文件
- 4.6 敏感信息扫描

### Step 5: Result Bundle（测试通过后自动执行）

- 5.1 运行 `bash scripts/ai/collect_result.sh --task TASK-2026-07-11-002-lean-v1-demo`
- 5.2 验证 Result Bundle 不是硬编码
- 5.3 运行 `bash scripts/ai/make_delivery_summary.sh --task TASK-2026-07-11-002-lean-v1-demo`

### Step 6: 交付（需用户 review）

- 6.1 回传脱敏摘要给 WorkBuddy / 用户
- 6.2 不自动 push / merge / deploy

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
6. 本任务单全文：docs/tasks/TASK-2026-07-11-002-lean-v1-demo.md

## 环境事实（已确认，直接使用）

- Codex CLI 版本：0.144.1，路径：/opt/homebrew/bin/codex
- sandbox 值：read-only / workspace-write / danger-full-access（danger-full-access 禁止）
- prompt 为位置参数，不支持 --prompt flag
- 当前分支：feature/lean-v1-demo

## 任务

TASK-2026-07-11-002：Lean V1 Demo 验证

只读，不修改任何文件。输出以下 5 项：

### 1. 理解摘要
- Demo 验证目标：验证 Lean V1 完整链路
- Demo 范围：仅新增 docs/workflows/LEAN_WORKFLOW_DEMO.md
- 安全约束：不修改业务代码、不 push/merge/deploy

### 2. Demo 文档内容设计
- 文档结构（章节列表）
- 必须包含的 6 项内容：
  - Demo TASK_ID
  - 执行时间
  - 本次只验证工作站流程
  - 未修改归一量化业务代码
  - 未 push、merge、deploy
  - Codex CLI 是唯一代码执行器
- 每项内容的预期文本

### 3. Dev 执行方案
- Codex Dev 调用方式：codex exec -s workspace-write
- Dev Prompt 要点
- 产出文件：docs/workflows/LEAN_WORKFLOW_DEMO.md

### 4. 测试验证方案
- 文件存在性检查
- 内容校验（TASK_ID 关键词、安全声明）
- git diff --stat 范围检查（仅 1 个文件）
- git diff --check 空白检查
- 敏感信息扫描

### 5. 风险点与缓解措施
- 风险评级（P0/P1/P2）
- 缓解措施

## 确认条款

- 不触碰 data/、.env、业务代码（services/、apps/、策略）
- 不自动 push/merge/deploy
- 禁止 danger-full-access
- Issue Gate：无 Issue 不开发
- 审批铁律：无审批不 Dev，main 分支拒绝 Dev
- 修改范围仅限 docs/workflows/LEAN_WORKFLOW_DEMO.md
- Plan 为只读执行，不得修改任何文件
```

## 16. Codex Dev Prompt

```
你现在是 Codex CLI，处于 dev（workspace-write）模式，执行已批准 Plan。

Codex CLI 调用方式：codex exec -s workspace-write
禁止：danger-full-access、--dangerously-bypass-approvals-and-sandbox

## 范围（严格限定，越界即中止）

只能修改 §7 "允许修改"中的文件：
- docs/workflows/LEAN_WORKFLOW_DEMO.md（新增）

## 禁止修改（硬约束）

- 除 docs/workflows/LEAN_WORKFLOW_DEMO.md 以外的所有文件
- services/、apps/、packages/、data/ 下任何文件
- 策略代码（strategies/）
- scripts/ai/ 下任何脚本
- .env / .env.* / 密钥 / webhook / token
- CODEBUDDY.md、AGENTS.md
- docs/tasks/ 下已有任务单
- docs/workflows/ 下已有文档
- git push / merge / release / deploy
- 删除历史数据、rm -rf
- danger-full-access
- 真实发送企业微信、自动交易

## 开发任务

创建 docs/workflows/LEAN_WORKFLOW_DEMO.md，内容必须包含：

1. **Demo 概述**
   - 验证目标：验证"企业微信→WorkBuddy完整TASK→CodeBuddy→Codex Plan→用户批准→Codex Dev→测试→Result Bundle→企业微信"的完整链路
   - 验证范围：仅工作站流程本身

2. **Demo TASK_ID**
   - TASK-2026-07-11-002-lean-v1-demo

3. **执行时间**
   - 实际执行日期时间（YYYY-MM-DD HH:MM:SS GMT+8）

4. **验证范围声明**
   - 本次只验证工作站流程
   - 不涉及归一量化业务逻辑

5. **链路验证记录**
   - 企业微信 → WorkBuddy：TASK 接收确认
   - WorkBuddy → CodeBuddy：TASK 转发确认
   - CodeBuddy → Codex Plan：只读 Plan 执行确认
   - 用户批准：APPROVE 确认
   - CodeBuddy → Codex Dev：workspace-write Dev 执行确认
   - 测试执行：run_tests.sh 执行确认
   - Result Bundle：collect_result.sh 生成确认
   - 企业微信回传：脱敏摘要确认

6. **安全声明**
   - 未修改归一量化业务代码（services/、apps/、packages/、strategies/）
   - 未 push、merge、deploy
   - Codex CLI 是唯一代码执行器（codex exec -s read-only / workspace-write）
   - 未使用 danger-full-access
   - 未真实发送企业微信
   - 未修改 .env、token、webhook

7. **验证结论**
   - 通过 / 未通过
   - 遗留问题（如有）

## 完成后

- docs/workflows/LEAN_WORKFLOW_DEMO.md 存在
- git diff --stat 仅含 docs/workflows/LEAN_WORKFLOW_DEMO.md
- git diff --check 无异常
- 退出码 0 表示成功
```

## 17. CodeBuddy 执行 Prompt

```
CodeBuddy：按本任务单 docs/tasks/TASK-2026-07-11-002-lean-v1-demo.md 执行 Lean V1 Demo。

步骤如下：

1. 验证审批记录存在（.ai/approvals/TASK-2026-07-11-002-lean-v1-demo.json）
2. 护栏自检（任一命中即中止）：要求改 .env/token/webhook？自动 push/merge/deploy？删数据？自动交易？使用 danger-full-access？→ 中止并报安全专家
3. 执行 Codex Dev：codex exec -s workspace-write "<TASK §16 完整 Dev Prompt>"
4. 运行测试：bash scripts/ai/run_tests.sh --task TASK-2026-07-11-002-lean-v1-demo
5. 敏感信息扫描：grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' docs/workflows/LEAN_WORKFLOW_DEMO.md
6. 收集结果：bash scripts/ai/collect_result.sh --task TASK-2026-07-11-002-lean-v1-demo
7. 生成交付摘要：bash scripts/ai/make_delivery_summary.sh --task TASK-2026-07-11-002-lean-v1-demo
8. 回传结果摘要给 WorkBuddy / 用户。不自动 push / merge / deploy。
```

## 18. 测试清单

### 18.0 自动化测试命令

```bash
git diff --stat
git diff --check
grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' docs/workflows/LEAN_WORKFLOW_DEMO.md
```

### 18.1 手动检查项

- [ ] `docs/workflows/LEAN_WORKFLOW_DEMO.md` 文件存在（烟测）
- [ ] 文件内容包含 `TASK-2026-07-11-002-lean-v1-demo`（单元）
- [ ] 文件内容包含"未修改归一量化业务代码"（单元）
- [ ] 文件内容包含"未 push、merge、deploy"或等效声明（单元）
- [ ] 文件内容包含"Codex CLI 是唯一代码执行器"或等效声明（单元）
- [ ] 文件内容包含执行时间（单元）
- [ ] 文件内容包含"只验证工作站流程"或等效声明（单元）
- [ ] `git diff --stat` 仅含 `docs/workflows/LEAN_WORKFLOW_DEMO.md` 一个文件（范围校验）
- [ ] `git diff --check` 无异常空白（回归）
- [ ] 敏感信息扫描：0 匹配（安全）
- [ ] Result Bundle 不是硬编码（集成）
- [ ] GitHub Issue 脚本回归（回归）

## 19. 验收标准

**pass 条件**（全部满足）：

1. `docs/workflows/LEAN_WORKFLOW_DEMO.md` 文件存在
2. 文件内容包含 Demo TASK_ID（`TASK-2026-07-11-002-lean-v1-demo`）
3. 文件内容包含执行时间
4. 文件内容声明：本次只验证工作站流程
5. 文件内容声明：未修改归一量化业务代码
6. 文件内容声明：未 push、merge、deploy
7. 文件内容声明：Codex CLI 是唯一代码执行器
8. `git diff --stat` 仅含 `docs/workflows/LEAN_WORKFLOW_DEMO.md` 一个文件
9. `git diff --check` 无异常
10. 敏感信息扫描 0 匹配

**block 条件**（任一即不通过）：

- 修改触及除 `docs/workflows/LEAN_WORKFLOW_DEMO.md` 以外的任何文件
- 使用 `-s danger-full-access` 或 `--dangerously-bypass-approvals-and-sandbox`
- 含 `rm -rf` 或全权限 mode
- 真实发送企业微信或真实写入数据库
- 自动 push / merge / deploy
- 密钥泄漏到产物/日志
- 文件内容缺失 6 项必须内容中的任何一项
- Result Bundle 硬编码特定任务内容

## 20. 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|---------|
| P0 | Codex Dev 越界修改业务代码 | `git diff --stat` 范围校验 + 护栏自检；越界即 FAILED |
| P1 | Demo 文档内容缺失必须项 | §16 Dev Prompt 明确列出 6 项必须内容 + §18.1 逐项校验 |
| P1 | 密钥泄漏到 Demo 文档 | 敏感信息 grep 扫描 + Dev Prompt 禁止读取凭证 |
| P2 | Demo 文档格式不规范 | 遵循现有 Markdown 风格 + 交付专家 review |
| P2 | 执行时间记录不准 | Dev 执行时使用 `date` 命令获取实际时间 |

## 21. 交付记录

- **状态流转**：REQUIREMENT_READY → PLAN_READY → [用户 APPROVE] → APPROVED_DEV → CODING → TESTING → DELIVERY_READY → [用户 review] → CLOSED
- **Issue 创建**：[#7](https://github.com/firehell/guiyi-quant-workstation/issues/7) — 已创建
- **Plan 完成**：2026-07-11 12:11 GMT+8
- **Plan 产物**：`.ai/results/TASK-2026-07-11-002-lean-v1-demo/plan_result.md`
- **审批记录**：`.ai/approvals/TASK-2026-07-11-002-lean-v1-demo.json`
- **Dev 完成**：未完成
- **测试结论**：未完成
- **交付报告**：未完成
- **合并前检查**：未完成
- **用户 review**：待
- **下一阶段建议**：Lean V1 正式上线 → 2–3 个真实业务 TASK 验证
