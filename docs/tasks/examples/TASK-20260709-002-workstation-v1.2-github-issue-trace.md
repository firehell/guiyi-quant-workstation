# TASK-20260709-002-workstation-v1.2-github-issue-trace

> V1.2 Bootstrap 任务：把 V1.1 本地规程化流水线升级为 GitHub Issue 任务留痕系统。

---

## 映射规则

```text
一个 TASK ↔ 一个 GitHub Issue（1:1）
TASK 文件 = 本地标准源
GitHub Issue = 远程留痕源
PR = 代码变更源
交付报告 = 验收源
```

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-20260709-002-workstation-v1.2-github-issue-trace |
| GitHub Issue | （创建后回填，如 #12） |
| Branch | feature/workstation-v1.2-github-issue-trace |
| PR | （如有） |
| Status | REQUIREMENT_READY |
| Created At | 2026-07-09 |
| Updated At | 2026-07-09 |
| Owner | firehell |

---

## 任务编号

`TASK-20260709-002-workstation-v1.2-github-issue-trace`

---

## 任务状态

`REQUIREMENT_READY`

---

## 背景

V1.1 已完成本地规程化 AI 开发流水线（任务单模板、状态机、CodeBuddy 规则、plan/dev/test/collect 脚本），但任务留痕仍分散在本地文档、企业微信群和 WorkBuddy/CodeBuddy 对话中，缺少可追踪、可回看、可复盘的远程任务系统。

---

## 目标

1. 建立 TASK ↔ GitHub Issue 1:1 映射规则与元信息字段
2. 新增 GitHub Issue 模板、Label 体系、留痕流程文档
3. 新增 4 个 gh 脚本：create / link / comment / update_status
4. 更新 CODEBUDDY.md，强制 Issue Gate（无 Issue 不开发）
5. 用本任务完整跑通 Issue 创建 → 回填 → plan 评论 → 开发 → test/delivery 评论闭环

---

## 不做事项

- 不做自动 PR、自动 merge、自动部署
- 不做 GitHub webhook 触发开发
- 不接 n8n、不接 Channels
- 不让 WorkBuddy 自动调用 CodeBuddy
- 不做 CodeBuddy daemon（V1.3）
- 不做 `dispatch_task.sh` 自动调度（V1.4）
- 不修改 `.env`、密钥、token、webhook
- 不删除或重写 `data/raw/`、`data/processed/`、`data/parquet/`
- 不修改业务代码（`services/`、`apps/`、策略、数据链路）

---

## 涉及模块

允许修改：

- `docs/tasks/TASK_TEMPLATE.md`
- `docs/tasks/README.md`
- `docs/tasks/examples/TASK-20260709-002-workstation-v1.2-github-issue-trace.md`
- `docs/tasks/examples/V1.2-ACCEPTANCE.md`
- `docs/workflows/github_labels.md`
- `docs/workflows/github_issue_trace_workflow.md`
- `docs/workflows/workbuddy_github_issue_usage.md`
- `docs/workflows/README.md`
- `docs/workflows/ai_delivery_workflow.md`（V1.2 扩展小节）
- `.github/ISSUE_TEMPLATE/`
- `CODEBUDDY.md`
- `scripts/ai/create_issue_from_task.sh`
- `scripts/ai/link_task_issue.sh`
- `scripts/ai/comment_issue_result.sh`
- `scripts/ai/update_issue_status.sh`

禁止修改：

- `.env`、`.env.*`
- `data/raw/`、`data/processed/`、`data/parquet/`
- `services/`、`apps/` 业务代码
- vn.py 源码
- 现有 5 个 V1.1 AI 脚本逻辑（`codex_plan.sh` 等）

---

## 技术方案

1. 更新 `TASK_TEMPLATE.md` 增加 `## 0. 元信息` 与映射规则
2. 新增 `.github/ISSUE_TEMPLATE/task.md` 与 `config.yml`
3. 新增 `github_labels.md`（含 `gh label create` 批量命令）
4. 新增 `github_issue_trace_workflow.md`、`workbuddy_github_issue_usage.md`
5. 实现 4 个 bash 脚本，基于 `gh` CLI，风格对齐现有 `scripts/ai/*.sh`
6. 更新 `CODEBUDDY.md`：Issue Gate、plan_result/test_result 规范、label 同步
7. 用本 TASK 作为 E2E 测试，验证 Issue 留痕闭环

---

## 数据影响

- 无 RQData / Parquet / PostgreSQL 变更
- 无 manifest 变更
- 纯文档与脚本变更

---

## 配置影响

- 无 `.env` 变更
- 需本地安装 `gh` CLI 并 `gh auth login`（一次性）

---

## 开发步骤

1. 从 main 创建分支 `feature/workstation-v1.2-github-issue-trace`
2. 更新 TASK 模板与 workflows 文档
3. 新增 GitHub Issue 模板与 label 文档
4. 实现 4 个 gh 脚本并 `chmod +x`
5. 更新 CODEBUDDY.md
6. 创建本任务单
7. 执行 E2E：create Issue → link → plan comment → dev → test/delivery comment
8. 编写 `V1.2-ACCEPTANCE.md`

---

## Codex Plan Prompt

```text
你是 Codex，在归一量化工作站仓库中执行只读 Plan。

必读：AGENTS.md、CODEBUDDY.md、docs/workflows/github_issue_trace_workflow.md、本任务单。

任务：V1.2 任务留痕 + GitHub Issue 工作站

要求：
- 只读，不修改任何文件
- 输出：理解摘要、拟修改文件列表、开发步骤、风险点、测试建议
- 确认不触碰 data/、.env、业务代码
- 确认 4 个 Gate + Issue Gate：无 Issue 不开发
```

---

## Codex Dev Prompt

```text
你是 Codex，在归一量化工作站仓库中执行 V1.2 开发。

必读：AGENTS.md、CODEBUDDY.md、本任务单、Plan 输出。

任务：实现 V1.2 GitHub Issue 任务留痕（文档 + 脚本，不碰业务代码）

允许修改：docs/tasks/、docs/workflows/、.github/ISSUE_TEMPLATE/、CODEBUDDY.md、scripts/ai/create_issue_from_task.sh 等 4 个新脚本

禁止修改：.env、data/、services/、apps/、vn.py 源码、现有 V1.1 脚本逻辑

要求：
- 按计划逐步创建/更新文件
- 脚本必须 bash -n 通过
- 不 push、merge、deploy
- 不自动 close Issue
- 完成后列出变更文件与测试命令
```

---

## 测试清单

- [ ] `bash -n scripts/ai/*.sh`
- [ ] `git diff --check`
- [ ] `scripts/ai/create_issue_from_task.sh <task_file> --dry-run`
- [ ] `scripts/ai/link_task_issue.sh TASK-20260709-002-... <N> <task_file>`
- [ ] `scripts/ai/comment_issue_result.sh TASK-20260709-002-... plan`
- [ ] `scripts/ai/update_issue_status.sh TASK-20260709-002-... PLAN_READY`
- [ ] `TASK_ID=TASK-20260709-002-... scripts/ai/run_tests.sh`
- [ ] E2E：Issue 含完整任务单、plan/test/delivery 评论、label 状态正确

---

## 验收标准

1. 每个 TASK 都能绑定 GitHub Issue
2. TASK 文件里能看到 Issue 编号
3. Issue 里能看到完整任务单
4. Issue 里能看到 plan 结果
5. Issue 里能看到开发执行摘要
6. Issue 里能看到测试结果
7. Issue 里能看到交付报告
8. Issue label 能反映当前状态
9. CodeBuddy 不会绕过 Issue 直接开发
10. 关闭 Issue 必须由用户人工确认

---

## 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|----------|
| P1 | `gh` 未登录或 label 未创建 | 文档前置检查；脚本内 `gh auth status` 提示 |
| P1 | TASK 元信息格式不统一导致回填失败 | 固定表格格式；脚本校验并打印期望格式 |
| P2 | 结果文件名不一致 | `comment_issue_result.sh` 多级回退读取 |
| P2 | Issue body 过长 | TASK 通常远小于 GitHub 65536 字符上限 |

---

## 交付记录

| 阶段 | 时间 | 操作者 | 说明 |
|------|------|--------|------|
| 任务创建 | 2026-07-09 | WorkBuddy / Cursor | 本文件 |
| Issue 创建 | | 用户 / CodeBuddy | `create_issue_from_task.sh` |
| Plan 完成 | | CodeBuddy | `plan_result.md` |
| Issue 评论（plan） | | CodeBuddy | `comment_issue_result.sh plan` |
| Dev 完成 | | CodeBuddy | 分支 `feature/workstation-v1.2-github-issue-trace` |
| 测试 | | CodeBuddy | `test_result.md` |
| Issue 评论（test） | | CodeBuddy | `comment_issue_result.sh test` |
| 结果收集 | | CodeBuddy | `execution_summary.md` |
| 交付摘要 | | CodeBuddy | `delivery_report_draft.md` |
| 交付报告 | | WorkBuddy | `delivery_report.md` |
| Issue 评论（delivery） | | CodeBuddy | `comment_issue_result.sh delivery` |
| 关闭 | | 用户 | 手动 close，不自动 |

---

## WorkBuddy 12 项映射（命令 A 输出时填写）

1. **需求结论**（产品负责人）：V1.2 解决任务远程留痕，不增加自动开发能力
2. **阶段边界**（产品负责人 + 量化架构师）：V1.2 只做 Issue 留痕；V1.3 再做 CodeBuddy 常驻
3. **不做事项**（产品负责人 + 量化架构师）：无 webhook、无自动 PR/merge、无业务代码改动
4. **产品需求**（产品负责人）：TASK↔Issue 1:1、plan/test/delivery 回填、label 状态同步
5. **技术方案**（量化架构师 + 开发负责人）：gh CLI 脚本 + 文档 + CODEBUDDY Issue Gate
6. **数据影响**（数据工程师）：无
7. **模块拆分**（开发负责人）：模板 / Issue 模板 / 4 脚本 / 流程文档 / CODEBUDDY
8. **QA 测试清单**（QA 工程师）：bash -n、dry-run、E2E Issue 闭环
9. **验收标准**（QA 工程师 + 交付专家）：10 条 V1.2 验收标准
10. **风险点**（全部角色）：gh 认证、label 创建、元信息格式
11. **CodeBuddy 执行 Prompt**（开发负责人）：见本任务单开发步骤
12. **Codex 开发 Prompt**（开发负责人）：见上文 Codex Dev Prompt
