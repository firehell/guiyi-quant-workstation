# 任务单模板

> WorkBuddy 生成任务单时必须遵循本模板。状态定义见 [`docs/workflows/status_machine.md`](../workflows/status_machine.md)。GitHub Issue 留痕见 [`docs/workflows/github_issue_trace_workflow.md`](../workflows/github_issue_trace_workflow.md)。

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
| Task ID | TASK-YYYYMMDD-NNN-short-name |
| GitHub Issue | （创建后回填，如 #12） |
| Branch | （开发分支，如 feature/...） |
| PR | （如有） |
| Status | IDEA / REQUIREMENT_READY / PLAN_READY / APPROVED_DEV / CODING / TESTING / DELIVERY_READY / CLOSED / FAILED / REPLAN |
| Created At | YYYY-MM-DD |
| Updated At | YYYY-MM-DD |
| Owner | 用户名 |

---

## 任务编号

`TASK-YYYYMMDD-NNN-short-name`

示例：`TASK-20260709-001-ai-workstation-bootstrap`

---

## 任务状态

当前状态：`IDEA` | `REQUIREMENT_READY` | `PLAN_READY` | `APPROVED_DEV` | `CODING` | `TESTING` | `DELIVERY_READY` | `CLOSED` | `FAILED` | `REPLAN`

---

## 背景

【为什么做这件事？当前痛点或触发原因】

---

## 目标

【完成后应达到的可验证结果，1–3 条】

---

## 不做事项

【明确排除范围，防止 scope creep】

- 不修改 `.env`、密钥、token、webhook
- 不删除或重写 `data/raw/`、`data/processed/`、`data/parquet/`
- 不自动 push、merge、release、部署
- 不做自动交易或无人值守下单
- 【任务特定排除项】

---

## 涉及模块

【允许修改的目录或文件；必须具体】

允许修改：

- 

禁止修改：

- `.env`、`.env.*`
- `data/raw/`、`data/processed/`、`data/parquet/`
- vn.py 源码
- 【其他禁止项】

---

## 技术方案

【架构师 + 开发负责人：实现思路、接口变更、依赖关系】

---

## 数据影响

【数据工程师：是否涉及 RQData 下载、Parquet、PostgreSQL、manifest；数据质量 Gate】

- 数据源：
- 聚合周期：
- 归档影响：
- 质量 Gate：

---

## 配置影响

【是否涉及 `.env.example`、Docker、scheduler、worker 配置；不得直接改 `.env`】

---

## 开发步骤

1. 
2. 
3. 

---

## Codex Plan Prompt

```text
你是 Codex，在归一量化工作站仓库中执行只读 Plan。

必读：AGENTS.md、CODEBUDDY.md、docs/workflows/ai_delivery_workflow.md、本任务单。

任务：【简述】

要求：
- 只读，不修改任何文件
- 输出：理解摘要、拟修改文件列表、开发步骤、风险点、测试建议
- 确认 4 个 Gate：只读 Plan、用户确认、专用分支、不自动发布
```

---

## Codex Dev Prompt

```text
你是 Codex，在归一量化工作站仓库中执行开发。

必读：AGENTS.md、CODEBUDDY.md、本任务单、Plan 输出（如有）。

任务：【简述】

允许修改：【列出目录/文件】
禁止修改：【列出目录/文件】

要求：
- 小步修改，不扩大范围
- 不 push、merge、deploy
- 完成后说明变更文件、测试命令、风险点
```

---

## 测试清单

- [ ] `bash -n scripts/ai/*.sh`（若改脚本）
- [ ] `git diff --check`
- [ ] 【后端】`scripts/ai/run_tests.sh --api`
- [ ] 【前端】`scripts/ai/run_tests.sh --web`
- [ ] 【任务特定测试】

---

## 验收标准

1. 
2. 
3. 

---

## 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|----------|
| P0 | | |
| P1 | | |
| P2 | | |

---

## 交付记录

| 阶段 | 时间 | 操作者 | 说明 |
|------|------|--------|------|
| 任务创建 | | WorkBuddy | |
| Issue 创建 | | 用户 / CodeBuddy | `scripts/ai/create_issue_from_task.sh` + `link_task_issue.sh` |
| Plan 完成 | | CodeBuddy | 输出：`.ai/results/<TASK_ID>/codex_plan_*.md`、`plan_result.md` |
| Issue 评论（plan） | | CodeBuddy | `scripts/ai/comment_issue_result.sh <TASK_ID> plan` |
| Dev 完成 | | CodeBuddy | 分支： |
| 测试 | | CodeBuddy | 日志：`.ai/logs/tests_*.log`、`test_result.md` |
| Issue 评论（test） | | CodeBuddy | `scripts/ai/comment_issue_result.sh <TASK_ID> test` |
| 结果收集 | | CodeBuddy | `.ai/results/<TASK_ID>/execution_summary.md` |
| 交付摘要 | | CodeBuddy | `.ai/results/<TASK_ID>/delivery_report_draft.md` |
| 交付报告 | | WorkBuddy | |
| Issue 评论（delivery） | | CodeBuddy / WorkBuddy | `scripts/ai/comment_issue_result.sh <TASK_ID> delivery` |
| 关闭 | | 用户 | 手动 close Issue，不自动关闭 |

---

## WorkBuddy 12 项映射（命令 A 输出时填写）

1. **需求结论**（产品负责人）：
2. **阶段边界**（产品负责人 + 量化架构师）：
3. **不做事项**（产品负责人 + 量化架构师）：
4. **产品需求**（产品负责人）：
5. **技术方案**（量化架构师 + 开发负责人）：
6. **数据影响**（数据工程师）：
7. **模块拆分**（开发负责人）：
8. **QA 测试清单**（QA 工程师）：
9. **验收标准**（QA 工程师 + 交付专家）：
10. **风险点**（全部角色）：
11. **CodeBuddy 执行 Prompt**（开发负责人）：
12. **Codex 开发 Prompt**（开发负责人）：
