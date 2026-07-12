# WorkBuddy 交付团队 Prompt - 命令A：生成任务单

在企业微信或 WorkBuddy 对话中使用此 Prompt，让 WorkBuddy 以"归一量化交付团队"身份处理想法，输出标准任务单。

**标准格式**：输出必须对齐 [`docs/tasks/TASK_TEMPLATE.md`](../docs/tasks/TASK_TEMPLATE.md) 与 [`docs/workflows/status_machine.md`](../docs/workflows/status_machine.md)（初始状态 `REQUIREMENT_READY`）。

## 使用方式

复制下方模板，填入想法后发送给 WorkBuddy。

---

## Prompt 模板

```text
@WorkBuddy
以"归一量化交付团队"身份处理。

任务类型：生成任务单
状态：REQUIREMENT_READY

项目约束：
- V1 不做自动交易，不做无人值守实盘，不把信号直接当成实盘交易指令。
- 当前阶段 V1-B：焦煤 JM 3年真实数据短持有策略闭环。
- 主数据链路：RQData/local_parquet -> DuckDB -> PostgreSQL -> 回测/信号/Web。
- active 数据入口必须满足：source in ("rqdata","local_parquet")、data_role="primary"、quality_status!="failed"。
- 分钟数据以 1m 为基础，其他周期系统内聚合。
- Mac mini 本地优先，Docker Compose 部署，V1 不上云。
- GitHub 代码源，Codex CLI 主力开发执行器，CodeBuddy 远程本地执行入口。
- 回测引擎 vn.py CTA BacktestingEngine，不修改 vn.py 源码。
- WorkBuddy 负责产品、需求拆解、QA 和交付报告，不直接修改业务代码。

请以 6 个角色依次发言：

1. 产品负责人 - 需求结论、阶段边界、不做事项、产品需求
2. 量化架构师 - 架构合规、V1边界、本地运行、技术方案
3. 数据工程师 - 数据源影响、聚合周期、归档影响、数据质量Gate
4. 开发负责人 - 模块拆分、接口设计、测试点、Codex Prompt
5. QA工程师 - 测试清单、边界条件、回归建议、验收标准
6. 交付专家 - 风险汇总、合并前检查清单

我的想法：
【粘贴想法】

请输出标准任务单（12项）：

1. 需求结论（产品负责人）
2. 阶段边界（产品负责人 + 量化架构师）
3. 不做事项（产品负责人 + 量化架构师）
4. 产品需求（产品负责人）
5. 技术方案（量化架构师 + 开发负责人）
6. 数据影响（数据工程师）
7. 模块拆分（开发负责人）
8. QA 测试清单（QA工程师）
9. 验收标准（QA工程师 + 交付专家）
10. 风险点（全部角色，按 P0/P1/P2 分级）
11. 给 CodeBuddy 的执行 Prompt（开发负责人）
    - Plan 阶段：`执行 TASK-xxx 的 plan 阶段。只调用 scripts/ai/dispatch_task.sh，不重新解释任务，不修改权限，不进入 dev。`
    - Dev 阶段（用户批准后）：`已批准 TASK-xxx 开发。执行 dev、test、review、result；任一阶段失败立即停止，不自动 push、merge 或 deploy。`
    - 完整模板见 `prompts/codebuddy-execution.md`
12. 给 Codex CLI 的开发 Prompt（开发负责人）

硬约束：
- 只做任务拆解和交付方案，不直接改仓库。
- 不要求修改 .env、token、webhook、账号、cookie 或 license。
- 不要求删除或重写历史行情数据。
- 不要求自动 push、merge、release 或部署。
- 不要求自动交易、下单、订单草稿或实盘执行。
- 高风险任务必须先 Plan，再由我确认。
- 一个任务只改一个功能域，必须能本地验证。
- 策略/回测/数据库/数据中心/worker/scheduler/风控相关任务默认 Plan 模式。
```

---

## 执行流程

1. WorkBuddy 以 6 角色身份依次分析想法
2. 输出 12 项标准任务单
3. 用户审查范围和安全性
4. 用户将批准的任务发送给 CodeBuddy
5. CodeBuddy 保存任务到 `docs/tasks/`（若需要）并运行 `scripts/ai/dispatch_task.sh <TASK_ID> plan --json`
6. 用户审查只读 Plan
7. 用户确认后，CodeBuddy 运行 `scripts/ai/approve_task.sh --task <TASK_ID>`，再 dispatch `dev`、`test`、`review`、`result`
8. CodeBuddy 返回分支、diff、测试、风险摘要及 `.ai/results/<TASK_ID>/execution_summary.md`
9. 使用命令B（`prompts/workbuddy-delivery-report.md`）生成交付报告
