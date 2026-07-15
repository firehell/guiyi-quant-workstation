### 当前理解

本任务目标清晰，但目前只能维持在 `REQUIREMENT_READY`，暂不应进入 `APPROVED_DEV` 或 Dev。

目标是验证 Lean V1 工作站受控流程，并且开发阶段只新增：

- `docs/workflows/LEAN_WORKFLOW_DEMO.md`

明确不涉及：

- 归一量化业务代码；
- 行情、Parquet、DuckDB、PostgreSQL；
- 策略、回测、信号；
- `.env`、凭据和配置；
- 真实企业微信发送；
- push、merge、deploy、PR 创建或 Issue 关闭；
- 自动交易或实盘接口。

当前仓库实查结果：

- 当前分支：`feature/workstation-lean-v1-closeout`
- TASK 要求分支：`feature/lean-v1-demo`
- `tasks/current.md` 当前任务：`V1-TRUSTED-CLOSURE`
- Demo TASK 状态：`REQUIREMENT_READY`
- Issue Gate：任务单已填写 `#7`
- Demo TASK 文件目前是未跟踪文件
- Plan 路径已创建，但检查时内容为 0 字节；本轮结果写回完成前不能把它视为有效 Plan
- 审批记录不存在
- Demo 文档不存在
- Result Bundle 不存在
- 工作区存在大量 Lean V1 closeout 未提交改动，包括 `scripts/ai/` 门控脚本本身

因此当前准确状态是：

```text
REQUIREMENT_READY
→ 只读 Plan 正在形成
→ 尚未达到 PLAN_READY
→ 不允许 APPROVE
→ 不允许 Dev
```

### 建议方案

#### Gate 0：先完成前置 Closeout 隔离

这是进入 Demo 的硬前置 Gate。

1. 先完成或安全 checkpoint 当前 `feature/workstation-lean-v1-closeout` 工作。
2. 由用户或 Cursor 处理现有脏工作区，不允许 Codex 自动 stash、reset、checkout 或清理。
3. 确认以下 Lean V1 工作流文件已经进入一个稳定 checkpoint：

   - `CODEBUDDY.md`
   - `docs/workflows/ai_delivery_workflow.md`
   - `docs/workflows/status_machine.md`
   - `docs/workflows/github_issue_trace_workflow.md`
   - `scripts/ai/codex_plan.sh`
   - `scripts/ai/approve_task.sh`
   - `scripts/ai/_approve_lib.sh`
   - `scripts/ai/codex_dev.sh`
   - `scripts/ai/run_tests.sh`
   - `scripts/ai/collect_result.sh`
   - `scripts/ai/make_delivery_summary.sh`

4. 创建或切换到任务指定分支：

```bash
feature/lean-v1-demo
```

5. `tasks/current.md` 必须明确登记本 Demo，或者任务单需明确豁免该要求。现在它仍指向另一个阶段，不能直接开发。

通过条件：

- 当前分支严格等于 `feature/lean-v1-demo`
- `tasks/current.md` 与 Demo 任务一致
- 现有改动已 checkpoint 或能通过审批基线清楚区分
- 工作流脚本版本稳定
- 不覆盖或混入用户现有改动

#### Gate 1：修正 TASK 内部矛盾

当前 TASK 有四个会使验收失真或必然失败的问题。应由 WorkBuddy/任务负责人修订同一任务单，再重新运行只读 Plan。

1. 敏感信息扫描矛盾

要求 Demo 文档包含：

```text
未修改 .env、token、webhook
```

但测试使用：

```bash
grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' docs/workflows/LEAN_WORKFLOW_DEMO.md
```

这会必然命中 `token`，使 `run_tests.sh` 返回失败。

建议改为扫描真正疑似凭据赋值或 URL，而不是扫描安全声明中的单词；或者使用允许列表排除固定安全声明。测试必须明确“0 匹配代表通过”。

2. 新文件范围检查无效

`docs/workflows/LEAN_WORKFLOW_DEMO.md` 是新建未跟踪文件，普通：

```bash
git diff --stat
```

不会显示它，不能证明“只修改一个文件”。

建议使用审批基线差集，并至少组合：

```bash
git status --porcelain
git diff --stat HEAD
```

由 `collect_result.sh` 的 `pre_existing_changes`、`task_changes`、`unexpected_changes` 作为最终范围证据。

3. 脏工作区与“仅一个文件”冲突

当前工作区已有大量修改，执行全仓 `git diff --stat` 不可能只显示 Demo 文件。验收应比较“审批基线之后新增的任务变更”，不能要求整个仓库只有一个 dirty file。

4. 企业微信验证口径冲突

任务禁止真实发送企业微信，却要求完整链路中的“企业微信回传确认”。

Demo 文档不得虚构真实执行。建议把两层结论分开：

- 本地受控链路：实际验证；
- 企业微信入口/回传：使用脱敏摘要生成或人工转发验证；未真实发送则记录为 `not_executed`、`manual_pending` 或“模拟验证”。

只有真实发生且有脱敏证据的节点才能写“通过”。

通过条件：

- 测试命令不会因固定安全声明必然失败；
- 范围检查支持未跟踪新文件；
- 范围检查基于审批时基线；
- 企业微信节点不会被虚假标记为已执行；
- TASK ID、Branch、Issue、Plan 路径、审批路径完全一致。

#### Gate 2：生成有效只读 Plan

前置修订完成后，在正确分支执行：

```bash
scripts/ai/codex_plan.sh --task TASK-2026-07-11-002-lean-v1-demo
```

验证：

- Issue Gate 为 `#7`
- Plan 命令退出码为 0
- `plan_result.md` 存在且非空
- Plan 前后 tracked diff 不变
- Plan 内容采用修订后的测试与证据口径
- 状态才能由 `REQUIREMENT_READY` 转为 `PLAN_READY`

随后可生成 Issue 留痕：

```bash
scripts/ai/comment_issue_result.sh TASK-2026-07-11-002-lean-v1-demo plan
scripts/ai/update_issue_status.sh TASK-2026-07-11-002-lean-v1-demo PLAN_READY
```

这些命令涉及远端 Issue 状态，必须由 CodeBuddy 在既定权限和网络条件下执行；本轮没有执行。

#### Gate 3：用户显式审批

用户审阅最终非空 Plan 后，显式批准：

```text
APPROVE TASK-2026-07-11-002-lean-v1-demo
```

然后执行：

```bash
scripts/ai/approve_task.sh --task TASK-2026-07-11-002-lean-v1-demo
```

审批必须验证：

- 当前分支为 `feature/lean-v1-demo`
- 不是 `main/master`
- Issue 为 `#7`
- TASK SHA256 与当前任务单一致
- Plan SHA256 与批准内容一致
- 审批基线完整记录现有变更

Plan 或 TASK 发生变化，旧审批立即失效，必须重新审批。

#### Gate 4：受控 Dev

审批有效后执行：

```bash
scripts/ai/update_issue_status.sh TASK-2026-07-11-002-lean-v1-demo APPROVED_DEV
scripts/ai/codex_dev.sh --task TASK-2026-07-11-002-lean-v1-demo
```

Dev 只能新增：

```text
docs/workflows/LEAN_WORKFLOW_DEMO.md
```

建议文档结构：

1. Demo 概述
2. Demo TASK_ID
3. 执行时间
4. 验证范围声明
5. 链路验证记录
6. 安全声明
7. 验证结论
8. 遗留问题

六项必须文本建议为：

- `Demo TASK_ID：TASK-2026-07-11-002-lean-v1-demo`
- `执行时间：YYYY-MM-DD HH:MM:SS GMT+8`
- `本次只验证工作站流程，不涉及归一量化业务逻辑。`
- `本次未修改归一量化业务代码。`
- `本次未执行 git push、merge 或 deploy。`
- `Codex CLI 是本次唯一代码执行器。`

链路记录建议采用证据状态表：

| 节点 | 状态 | 证据 |
|---|---|---|
| WorkBuddy TASK | passed/pending | TASK 路径 |
| CodeBuddy 接收 | passed/pending | 本地记录 |
| Codex Plan | passed/failed | Plan 路径、退出码 |
| 用户批准 | passed/failed | 审批 JSON、Plan SHA256 |
| Codex Dev | passed/failed | 分支、变更文件 |
| 测试 | passed/failed | test result |
| Result Bundle | passed/failed | Bundle 路径 |
| 企业微信回传 | manual_pending/not_executed/passed | 脱敏证据 |

不得预先把尚未发生的测试、Result Bundle 或企业微信回传写成“通过”。

#### Gate 5：测试与 Result Bundle

先运行任务修订后的测试：

```bash
bash scripts/ai/run_tests.sh --task TASK-2026-07-11-002-lean-v1-demo
```

至少验证：

- Demo 文件存在；
- TASK_ID 正确；
- 执行时间格式正确；
- 六项必须声明完整；
- V1 非自动交易边界明确；
- `git diff --check` 通过；
- 审批基线之后只有 Demo 文件属于 task changes；
- `unexpected_changes=[]`；
- 敏感信息扫描通过；
- 没有真实企业微信、数据库、数据或交易操作。

然后执行：

```bash
bash scripts/ai/collect_result.sh --task TASK-2026-07-11-002-lean-v1-demo
bash scripts/ai/make_delivery_summary.sh --task TASK-2026-07-11-002-lean-v1-demo
```

检查：

- `result_bundle.json/md` 来自实际 Git、审批和测试结果；
- 没有硬编码“通过”；
- `pre_existing_changes` 与 `task_changes` 正确区分；
- 当前分支与 expected branch 一致；
- 测试失败或节点未执行时如实记录；
- Delivery Summary 不泄露日志或凭据。

全部通过后才能进入 `DELIVERY_READY`。Issue 不自动关闭，也不自动创建 PR。

### 拟修改范围

本轮 Plan 模式实际修改文件：无。

后续 Dev 唯一允许修改：

- `docs/workflows/LEAN_WORKFLOW_DEMO.md`（新增）

进入 Dev 前，任务负责人需要修订任务单中的测试和证据矛盾。该修订属于重新规划阶段，不得由 Demo Dev 越权修改。

### 不修改范围

- `services/`
- `apps/`
- `packages/`
- `strategies/`
- `data/`
- `scripts/ai/`
- `.env`、`.env.*`
- `AGENTS.md`
- `CODEBUDDY.md`
- 已有 workflow 文档
- 数据库、Parquet、DuckDB、RQData
- 企业微信真实发送
- 自动交易、委托或实盘账户
- Git push、merge、deploy、自动 PR、自动关闭 Issue

### 测试计划

本轮只执行了只读检查，没有执行 Dev 测试。

实际运行的检查包括：

```bash
git status --short --branch
git rev-parse --show-toplevel
pwd
sed -n '1,240p' tasks/current.md
codex --version
git diff --stat HEAD
git status --porcelain=v1 --untracked-files=all
```

确认结果：

- 仓库路径正确；
- Codex CLI 为 `0.144.1`；
- 当前分支与 TASK 分支不一致；
- 当前任务与 Demo 不一致；
- 工作区存在大量前置 closeout 改动；
- Demo 文档、审批、Result Bundle 尚不存在；
- 当前 Plan 文件检查时为空；
- 当前 TASK 为未跟踪文件。

后续建议增加明确的内容断言，例如使用 `rg -F` 分别验证必填文本；不要用一个会命中安全声明自身的宽泛敏感词正则作为唯一凭据扫描。

### 风险点

| 级别 | 风险 | 缓解措施 |
|---|---|---|
| P0 | 在错误分支执行 Dev | 分支必须严格等于 `feature/lean-v1-demo` |
| P0 | 当前 closeout 脏改动混入 Demo | 先 checkpoint；审批记录基线；比较 task changes |
| P0 | 脚本仍是未收口版本却用它验证自身 | 先完成 TASK-001 closeout，再启动 Demo |
| P0 | 企业微信未真实执行却写成完整链路通过 | 节点级状态和证据；未执行写 `not_executed` |
| P1 | 敏感扫描必然命中固定安全声明 | 先修订 TASK 测试规则 |
| P1 | `git diff --stat` 漏掉未跟踪 Demo 文件 | 使用 `git status --porcelain` 与基线差集 |
| P1 | 全仓 dirty 导致“一文件”验收误判 | 检查审批后新增 task changes |
| P1 | Plan 文件为空或变化后仍沿用旧审批 | 非空检查；Plan SHA256 绑定；变化即重批 |
| P1 | `tasks/current.md` 与 TASK 不一致 | Demo 开始前统一当前任务事实源 |
| P2 | 执行时间不准确 | Dev 时读取本机 GMT+8 时间并保留时区 |
| P2 | 文档把流程设计当成执行证据 | 每个节点记录状态、证据路径和退出码 |

### 需要我确认的问题

当前不需要确认实现细节；需要先处理以下 Gate：

1. 是否先由用户/Cursor 完成 `feature/workstation-lean-v1-closeout` checkpoint，并切换到 `feature/lean-v1-demo`。
2. 是否同意让 WorkBuddy 修订同一 TASK，解决敏感扫描、未跟踪文件范围检查、脏工作区基线和企业微信证据口径四个矛盾。
3. 修订后重新运行 Plan，待生成非空 Plan 并进入 `PLAN_READY`，再由用户显式 `APPROVE`。

### 协作建议

- 是否建议开新 Codex 会话：**是**。当前 closeout 与 Demo 属于两个独立阶段，且必须先完成分支和工作区隔离。
- 是否建议使用 Plan 模式：**是**。本轮继续保持 Plan，直到 TASK 修订、正确分支、非空 Plan 和审批 Gate 全部满足。
- 建议同步给浏览器 GPT 的文件：
  - `docs/tasks/TASK-2026-07-11-002-lean-v1-demo.md`
  - `tasks/current.md`
  - `CODEBUDDY.md`
  - `docs/workflows/ai_delivery_workflow.md`
  - `docs/workflows/status_machine.md`
  - `docs/workflows/github_issue_trace_workflow.md`
  - `scripts/ai/codex_plan.sh`
  - `scripts/ai/approve_task.sh`
  - `scripts/ai/_approve_lib.sh`
  - `scripts/ai/codex_dev.sh`
  - `scripts/ai/run_tests.sh`
  - `scripts/ai/collect_result.sh`
  - 本次 Plan 结果


