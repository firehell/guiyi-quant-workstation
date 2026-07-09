# TASK-20260709-001-ai-workstation-bootstrap

> Bootstrap 任务：交付 V1.1 规程化 AI 开发流水线本身。

---

## 任务编号

`TASK-20260709-001-ai-workstation-bootstrap`

---

## 任务状态

`DELIVERY_READY`

---

## 背景

仓库已有 WorkBuddy / CodeBuddy / Codex 半自动协作基础（3 个 AI 脚本、CODEBUDDY.md、企微工作流），但缺少统一的任务单模板、状态机、结果收集脚本和规程文档目录。需要把现有链路规程化，形成 V1.1 工作站。

---

## 目标

1. 建立 `docs/tasks/`、`docs/workflows/` 目录与标准 TASK 模板
2. 建立 10 状态任务状态机与 V1.1 主交付流程文档
3. 增强 CodeBuddy 规则与 AI 脚本（TASK_ID、collect_result、make_delivery_summary）
4. 用本任务跑通 plan → dev → test → collect → delivery 全流程

---

## 不做事项

- 不接 n8n、webhook、GitHub 自动触发
- 不做 CodeBuddy daemon / tmux 常驻（V1.3）
- 不做 GitHub Issue 留痕（V1.2）
- 不做 `dispatch_task.sh` 自动调度（V1.4）
- 不做 preflight 风险扫描矩阵（V1.5）
- 不修改 `.env`、不删数据、不 push / merge / deploy
- 不修改业务逻辑、策略、回测、数据中心代码
- 不修改 vn.py 源码

---

## 涉及模块

允许修改：

- `docs/tasks/`
- `docs/workflows/`
- `CODEBUDDY.md`
- `docs/AI_WECHAT_WORKFLOW.md`
- `scripts/ai/codex_plan.sh`
- `scripts/ai/codex_dev.sh`
- `scripts/ai/run_tests.sh`
- `scripts/ai/collect_result.sh`（新增）
- `scripts/ai/make_delivery_summary.sh`（新增）
- `prompts/workbuddy-delivery-team.md`（轻量引用更新）
- `.agents/skills/guiyi-delivery-team/SKILL.md`（轻量引用更新）

禁止修改：

- `.env`、`.env.*`
- `data/raw/`、`data/processed/`、`data/parquet/`
- `services/`、`apps/` 业务代码
- vn.py 源码

---

## 技术方案

1. 创建 `docs/tasks/TASK_TEMPLATE.md` 作为 canonical 任务单格式
2. 创建 `docs/workflows/status_machine.md`、`ai_delivery_workflow.md`、`workbuddy_role.md`
3. 更新 `CODEBUDDY.md` 收窄 CodeBuddy 为本地执行控制器
4. 现有 3 脚本支持可选 `TASK_ID` 环境变量，输出到 `.ai/results/<TASK_ID>/`
5. 新增 `collect_result.sh`、`make_delivery_summary.sh`
6. `AI_WECHAT_WORKFLOW.md` 顶部挂接 V1.1 主流程，保留企微专项内容

---

## 数据影响

- 无 RQData / Parquet / PostgreSQL 变更
- 无 manifest 变更
- 纯文档与脚本变更

---

## 配置影响

- 无 `.env` 变更
- 无 Docker / worker 配置变更

---

## 开发步骤

1. 创建目录与 README
2. 编写 TASK_TEMPLATE、status_machine、workflow 文档
3. 更新 CODEBUDDY.md
4. 增强 codex_plan/dev/run_tests，新增 collect_result/make_delivery_summary
5. 运行 `run_tests.sh` 验证脚本语法
6. 运行 collect_result 与 make_delivery_summary 生成本地交付摘要

---

## Codex Plan Prompt

```text
你是 Codex，在归一量化工作站仓库中执行只读 Plan。

必读：AGENTS.md、CODEBUDDY.md、docs/workflows/ai_delivery_workflow.md、docs/tasks/examples/TASK-20260709-001-ai-workstation-bootstrap.md

任务：V1.1 规程化 AI 开发流水线

要求：
- 只读，不修改任何文件
- 对照计划确认：docs/tasks、docs/workflows、脚本增强、CODEBUDDY 更新是否完整
- 输出：理解摘要、拟修改文件列表、开发步骤、风险点、测试建议
- 确认不触碰 data/、.env、业务代码
```

---

## Codex Dev Prompt

```text
你是 Codex，在归一量化工作站仓库中执行 V1.1 bootstrap 开发。

必读：AGENTS.md、CODEBUDDY.md、本任务单、Plan 输出。

任务：实现 V1.1 规程化 AI 开发流水线（文档 + 脚本，不碰业务代码）

允许修改：docs/tasks/、docs/workflows/、CODEBUDDY.md、docs/AI_WECHAT_WORKFLOW.md、scripts/ai/*.sh、prompts/workbuddy-delivery-team.md、.agents/skills/guiyi-delivery-team/SKILL.md

禁止修改：.env、data/、services/、apps/、vn.py 源码

要求：
- 按计划逐步创建/更新文件
- 脚本必须 bash -n 通过
- 不 push、merge、deploy
- 完成后列出变更文件与测试命令
```

---

## 测试清单

- [ ] `bash -n scripts/ai/codex_plan.sh scripts/ai/codex_dev.sh scripts/ai/run_tests.sh scripts/ai/collect_result.sh scripts/ai/make_delivery_summary.sh`
- [ ] `scripts/ai/run_tests.sh`
- [ ] `TASK_ID=TASK-20260709-001 scripts/ai/collect_result.sh TASK-20260709-001 docs/tasks/examples/TASK-20260709-001-ai-workstation-bootstrap.md`
- [ ] `scripts/ai/make_delivery_summary.sh TASK-20260709-001 docs/tasks/examples/TASK-20260709-001-ai-workstation-bootstrap.md`

---

## 验收标准

1. 新任务可按 `docs/tasks/TASK_TEMPLATE.md` 标准化生成
2. TASK 有明确状态（`docs/workflows/status_machine.md`）
3. CodeBuddy 能按 TASK 执行只读 plan（`codex_plan.sh`）
4. Codex 开发前必须经过人工确认（Gate 2）
5. 开发后能自动收集 diff、测试、`execution_summary.md`
6. WorkBuddy 能基于 `delivery_report_draft.md` 生成交付报告
7. 全流程不 push、不 merge、不部署、不动密钥、不删数据

---

## 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|----------|
| P1 | 文档与 AI_WECHAT_WORKFLOW 重复 | docs/workflows 为 canonical，企微文档只做挂接 |
| P1 | 工作区有大量 data/manifests 脏文件 | dev 分支只改 docs/scripts |
| P2 | `.ai/` 不入库，本地结果易丢失 | 示例 task 在 docs/tasks/examples/ 可复现 |

---

## 交付记录

| 阶段 | 时间 | 操作者 | 说明 |
|------|------|--------|------|
| 任务创建 | 2026-07-09 | WorkBuddy / Cursor | 示例任务单 |
| Plan 完成 | 2026-07-09 | CodeBuddy / Codex | `.ai/results/TASK-20260709-001/codex_plan_20260709-121530.md`（exit 0，只读，工作区无新增变更） |
| Dev 完成 | 2026-07-09 | Cursor Agent | 分支：codex/ai-wechat-workflow-foundation |
| 测试 | 2026-07-09 | CodeBuddy | `tests_TASK-20260709-001_*.log` — 通过 |
| 结果收集 | 2026-07-09 | CodeBuddy | `execution_summary.md` |
| 交付摘要 | 2026-07-09 | CodeBuddy | `delivery_report_draft.md` |
| 验收记录 | 2026-07-09 | Cursor | `docs/tasks/examples/V1.1-ACCEPTANCE.md` |
| 关闭 | | 用户 | 待 commit/merge |

---

## WorkBuddy 12 项映射

1. **需求结论**：把现有 AI 协作链路规程化为 V1.1 工作站
2. **阶段边界**：V1.1 只做规程化；V1.2+ 留痕、常驻、调度后续做
3. **不做事项**：见上文「不做事项」
4. **产品需求**：标准 TASK、状态机、脚本、流程文档
5. **技术方案**：见「技术方案」
6. **数据影响**：无
7. **模块拆分**：docs + scripts + CODEBUDDY
8. **QA 测试清单**：见「测试清单」
9. **验收标准**：见「验收标准」7 条
10. **风险点**：见「风险点」
11. **CodeBuddy 执行 Prompt**：按 ai_delivery_workflow 10 步执行
12. **Codex 开发 Prompt**：见「Codex Dev Prompt」
