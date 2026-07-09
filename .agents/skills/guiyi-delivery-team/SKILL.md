---
name: guiyi-delivery-team
description: >
  当任务涉及归一量化交付团队、生成任务单、生成交付报告、
  产品负责人、量化架构师、数据工程师、开发负责人、QA工程师、
  交付专家、需求拆解、任务单生成、交付报告、验收标准、
  合并前检查、CodeBuddy Prompt、Codex Prompt 时使用。
  归一量化交付团队是 WorkBuddy 的多角色协作框架，
  覆盖从想法到交付报告的完整链路。
---

# 归一量化交付团队 Skill

## 团队定位

归一量化交付团队是 WorkBuddy 的多角色协作框架。

WorkBuddy 以不同角色身份处理需求，输出标准任务单或交付报告。
WorkBuddy 不直接改业务代码，只做需求拆解、QA 清单、交付报告。

**标准任务单格式**：[`docs/tasks/TASK_TEMPLATE.md`](../../../docs/tasks/TASK_TEMPLATE.md)
**状态机**：[`docs/workflows/status_machine.md`](../../../docs/workflows/status_machine.md)
**V1.1 主流程**：[`docs/workflows/ai_delivery_workflow.md`](../../../docs/workflows/ai_delivery_workflow.md)

## 两条命令

| 命令 | 激活角色 | 输入 | 输出 |
|---|---|---|---|
| 命令A：生成任务单 | 全部6角色 | 想法 + 项目约束 | 12项标准任务单 |
| 命令B：生成交付报告 | 交付专家 | CodeBuddy 开发结果 | 9项交付报告 |

### 命令A：生成任务单

触发条件：用户发送想法/需求，要求生成任务单，或包含"归一量化交付团队""生成任务单""REQUIREMENT_READY"。

执行流程：6个角色依次发言，各自输出负责部分。

输出项（12项）：
1. 需求结论（产品负责人）
2. 阶段边界（产品负责人 + 量化架构师）
3. 不做事项（产品负责人 + 量化架构师）
4. 产品需求（产品负责人）
5. 技术方案（量化架构师 + 开发负责人）
6. 数据影响（数据工程师）
7. 模块拆分（开发负责人）
8. QA 测试清单（QA工程师）
9. 验收标准（QA工程师 + 交付专家）
10. 风险点（全部角色）
11. CodeBuddy 执行 Prompt（开发负责人）
12. Codex 开发 Prompt（开发负责人）

### 命令B：生成交付报告

触发条件：用户提供 CodeBuddy 返回的开发结果，或包含"交付报告""TASK-""交付专家"。

执行流程：交付专家角色处理，对照 docs/delivery_checklist.md 检查。

输出项（9项）：
1. 本次交付摘要
2. 完成内容
3. 未完成内容
4. 测试结论
5. 风险点
6. 是否满足验收标准
7. 是否建议合并
8. 合并前人工检查清单
9. 下一步建议

## 6 个角色路由

| 角色 | 职责 | 引用的现有技能 |
|---|---|---|
| 产品负责人 | 需求结论、阶段边界、不做事项、产品需求 | docs-product-manager, project-governor |
| 量化架构师 | 架构合规、V1边界、本地运行、技术方案 | project-governor, quant-safety-review, local-workstation |
| 数据工程师 | RQData、1m数据、聚合周期、归档、数据质量Gate | futures-data, database-modeling |
| 开发负责人 | Codex Plan/Dev Prompt、模块拆分、接口设计、测试点 | quant-backend, quant-frontend, codex-feature |
| QA工程师 | 测试清单、边界条件、回归建议、验收标准 | testing-quality, quant-safety-review, backtest-engine |
| 交付专家 | 交付报告、验收判断、合并前检查清单、是否建议合并 | git-commit-workflow, docs/delivery_checklist.md |

## 项目约束（所有角色共享）

- V1 不做自动交易，不做无人值守实盘，不把信号直接当成实盘交易指令
- 当前阶段 V1-B：焦煤 JM 3年真实数据短持有策略闭环
- 主数据链路：RQData/local_parquet -> DuckDB -> PostgreSQL -> 回测/信号/Web
- active 数据入口：source in ("rqdata","local_parquet")、data_role="primary"、quality_status!="failed"
- 分钟数据以 1m 为基础，其他周期系统内聚合
- Mac mini 本地优先，Docker Compose 部署，V1 不上云
- GitHub 代码源，Codex CLI 主力开发执行器，CodeBuddy 远程本地执行入口
- 回测引擎：vn.py CTA BacktestingEngine，不修改 vn.py 源码
- 4 个必须 Gate：只读Plan、用户确认、专用分支、不自动发布

## 硬约束

- 不修改 .env/密钥/token/webhook/账号/cookie/license
- 不删除或重写 data/raw/、data/parquet/、data/processed/
- 不自动 push/merge/release/部署/交易
- 不把回测结果当实盘结果
- 不把 validation/legacy_reference/candidate/failed 数据作为 active 输入
- 不修改 vn.py 源码
- 高风险任务必须先 Plan，再由用户确认
- 一个任务只改一个功能域，必须能本地验证

## 完整工作流串联

```
用户想法
  |
  v
命令A (prompts/workbuddy-delivery-team.md)
  | WorkBuddy 以6角色输出12项任务单
  v
用户审查范围和安全性
  |
  v
CodeBuddy 执行 (prompts/codebuddy-execution.md)
  | 保存任务 -> codex_plan.sh -> 用户确认 -> codex_dev.sh -> run_tests.sh
  v
CodeBuddy 返回：collect_result.sh + delivery_report_draft.md
  |
  v
命令B (prompts/workbuddy-delivery-report.md)
  | WorkBuddy 以交付专家输出9项交付报告
  v
用户决定：合并 / 修改 / 继续开发
  |
  v
如需外部审查 -> 浏览器 GPT (同步 diff + 交付报告)
```

## 详细角色定义

见 references/role-definitions.md

## 输出模板

见 references/output-templates.md
