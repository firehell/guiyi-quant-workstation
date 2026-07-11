# TASK-2026-07-10-003：归一量化单项目工作站精简收口与Demo前置修复

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-10-003-workstation-lean-v1-closeout |
| GitHub Issue | #5 |
| Branch | feature/workstation-lean-v1-closeout |
| PR | — |
| Status | REQUIREMENT_READY |
| Created At | 2026-07-10 |
| Updated At | 2026-07-10 |
| Owner | zhangzhao |

---

## 1. 任务状态

`REQUIREMENT_READY`

### PLAN_READY 转换条件

当前修订阶段保持 `REQUIREMENT_READY`。仅当以下条件**全部满足**后，CodeBuddy 才将 TASK 状态改为 `PLAN_READY`：

1. 修订后的 Bootstrap Plan 成功执行
2. `plan_result.md` 存在且非空
3. 只读执行退出码为 0
4. 业务代码零修改（`git diff --name-only` 在 `services/`、`apps/`、`data/`、`.env` 下为空）
5. Issue #5 已验证存在并关联

满足后，CodeBuddy 更新 §21 交付记录：
- Issue 创建：#5（已创建）
- Plan 完成：填写时间和 `plan_result.md` 路径
- Dev/测试/交付仍保持未完成

---

## 2. 任务类型

AI 工作流优化

---

## 3. 参与角色

- 必须：量化架构师（状态机/门控设计）、开发负责人（脚本实现）、安全专家（护栏审查）
- 可选：QA 工程师（测试验证）
- 不需要：PM/PO（需求已明确，由预检证据驱动）

---

## 4. 背景

当前工作站已具备 WorkBuddy 任务设计、CodeBuddy 本地执行、Codex CLI、Plan/Dev/Test/Result 脚本和 GitHub Issue 留痕，但现有流程仍然较重，且仓库文档与脚本存在契约不一致。

**2026-07-10 Mac mini 真实只读预检已确认以下环境事实：**

| 项目 | 值 |
|------|-----|
| Git 分支 | `main`，工作区干净，与 `origin/main` 同步 |
| Codex CLI 路径 | `/opt/homebrew/bin/codex` |
| Codex CLI 版本 | `0.144.1` |
| gh 登录状态 | 已登录 `firehell`，Issue 权限满足 |
| 15 个 `scripts/ai/*.sh` | 均通过 `bash -n` |
| rg | 未安装（不作为本任务阻塞项） |

**预检确认的阻断问题：**

**P0（阻断级，必须修复）：**

1. **`codex_plan.sh` 使用无效调用**：`codex --readonly --prompt` 在 Codex CLI 0.144.1 下不可用，必须改为 `codex exec --sandbox read-only` 模式。

2. **`codex_dev.sh` 使用无效调用**：`codex --prompt` 在 Codex CLI 0.144.1 下不可用，必须改为 `codex exec --sandbox workspace-write` 模式。

3. **Plan 和 Dev 脚本未完整读取 TASK**：Plan 脚本仅提取第 15 节，Dev 脚本仅拼接硬编码 prompt 片段，两者都未完整读取 TASK 中的允许/禁止修改路径、验收标准、测试命令等关键信息。

4. **Dev 无审批门控**：`codex_dev.sh` 允许在无人工审批记录的情况下执行，违反"先审批后开发"铁律。必须增加与当前 Plan 哈希绑定的审批记录验证。

**P1（高优先级，必须修复）：**

5. **参数方式不统一**：`codex_plan.sh`/`codex_dev.sh`/`run_tests.sh`/`collect_result.sh` 使用 `--task` 位置参数；`comment_issue_result.sh`/`update_issue_status.sh` 使用位置参数；文档使用环境变量 `TASK_ID`。三种方式并存。

6. **TASK 文件路径不统一**：
   - `codex_plan.sh` 搜索：`tasks/`、`tasks/examples/`、`docs/tasks/examples/`、`workstation/tasks/`
   - `codex_dev.sh` 搜索：同上
   - `comment_issue_result.sh` 搜索：`.ai/tasks/`、`docs/tasks/examples/`、`docs/tasks/`
   - `update_issue_status.sh` 搜索：`.ai/tasks/`、`docs/tasks/examples/`、`docs/tasks/`
   - 正式 TASK 应统一保存到 `docs/tasks/<TASK_ID>.md`

7. **产物输出路径不统一**：
   - `codex_plan.sh`/`codex_dev.sh`/`run_tests.sh`/`collect_result.sh`/`make_delivery_summary.sh` 输出到 `scripts/ai/.out/<TASK_ID>/`
   - `comment_issue_result.sh` 读取 `.ai/results/<TASK_ID>/`
   - CODEBUDDY.md 要求输出到 `.ai/results/<TASK_ID>/`
   - 运行产物应统一到 `.ai/results/<TASK_ID>/`

8. **运行日志路径不统一**：应统一到 `.ai/logs/`

9. **Plan 审批记录缺失**：无 `.ai/approvals/<TASK_ID>.approved` 机制，CodeBuddy 仅靠外部对话确认。

10. **`comment_issue_result.sh`/`update_issue_status.sh`/`CODEBUDDY.md`/`ai_delivery_workflow.md`/`github_issue_trace_workflow.md` 路径引用不一致**：部分引用 `scripts/ai/.out/`，部分引用 `.ai/results/`。

11. **`run_tests.sh` 硬编码 pytest**：假设仓库根目录存在全局 pytest，未支持 TASK 中声明的真实测试命令。

12. **`collect_result.sh` 和 `make_delivery_summary.sh` 内容不足**：
    - `collect_result.sh` 仅收集 git diff + 文件清单 + 测试摘要，缺少 branch、实际执行命令、越界检查、敏感信息检查、遗留问题、next_action。
    - `make_delivery_summary.sh` 硬编码了"5 个脚手架脚本已落地"等工作站 bootstrap 阶段内容，不是通用结果摘要。

13. **缺少真实回归验证**：codex exec 只读 Plan 成功且业务文件零修改、无批准时 Dev 拒绝、Plan 变化后批准失效、批准后 workspace-write Demo 成功、Issue 评论可找到 `.ai/results` 中的 Plan/Test/Delivery、企业微信 Result 摘要来自真实 Result Bundle。

---

## 5. 目标

用一次小范围任务完成工作站 Lean V1 收口，**不建设 Daemon、不建设 Runner、不建设腾讯云控制层、不建设 Dashboard、不做多项目支持**。

### 必须实现

#### 一、统一 TASK

1. 保留现有正式 TASK 模板和 GitHub Issue 兼容性。
2. WorkBuddy 一次生成完整 TASK，必须同时包含：
   - 目标
   - 范围
   - 不做事项
   - 允许修改路径
   - 禁止修改路径
   - Plan 要求
   - Dev 要求
   - 测试命令
   - 验收标准
   - 风险级别
3. 后续不再分别要求 WorkBuddy 生成 Plan Prompt、Dev Prompt 和 CodeBuddy Prompt（一次 Task Bundle 直达 CodeBuddy）。
4. 正式 TASK 统一保存到 `docs/tasks/<TASK_ID>.md`。
5. 运行产物统一保存到 `.ai/results/<TASK_ID>/`。
6. 运行日志统一保存到 `.ai/logs/`。

#### 二、修复 Codex CLI 脚本

1. 根据 Mac mini 真实 `codex --version`（0.144.1）和 `codex exec --help` 调整调用方式。
2. Plan 使用 `codex exec --sandbox read-only` 模式。
3. Dev 使用 `codex exec --sandbox workspace-write` 模式。
4. **禁止 `--sandbox danger-full-access`**。
5. Prompt 作为位置参数传递，**禁止使用 `--prompt`**。
6. Plan 必须读取：AGENTS.md、CODEBUDDY.md、完整 TASK、当前 Git 状态。
7. Dev 必须读取：完整 TASK、已确认 Plan、Plan 审批凭证、允许/禁止修改路径、测试和验收要求。
8. Dev 必须拒绝在 `main` 分支运行。
9. 不允许使用裸 `codex` 命令绕过脚本。

#### 三、增加最小审批门

1. 新增 `scripts/ai/approve_task.sh` 作为公开审批入口。
2. 命令格式：`scripts/ai/approve_task.sh --task <TASK_ID>`。
3. `approve_task.sh` 负责计算 Plan SHA256、绑定 TASK_ID 和目标分支、写入批准时间。
4. 审批记录必须绑定：TASK_ID、当前 plan 文件哈希（SHA256）、批准时间、目标分支。
5. Plan 变化后旧批准自动失效（Dev 前比对 hash）。
6. 没有有效批准记录，`codex_dev.sh` 必须拒绝执行。
7. `codex_dev.sh` 必须通过 `scripts/ai/_approve_lib.sh` 验证审批记录和当前 Plan 哈希。
8. **以下情况审批必须失败**：当前在 `main` 分支、Plan 文件缺失、Plan 哈希无法计算。
9. **不建设复杂状态机和远程 Runner**。

#### 四、修复测试

1. `run_tests.sh` 不能只假设全局 pytest。
2. 应根据 TASK 中声明的测试命令执行。
3. 如果 TASK 未声明测试，至少执行：`git diff --check`、相关脚本 `bash -n`、根据变更范围选择最小测试。
4. 默认不真实发送、不写生产数据、不部署。
5. 测试失败必须退出非 0。
6. **测试命令自动执行安全限制**：
   - 只解析 §18.0 固定位置下的 fenced bash 代码块。
   - 不使用 `eval` 执行整段文本。
   - 逐条执行、逐条记录退出码。
   - 拒绝执行以下危险命令：`rm`、`git push`、`git merge`、`git reset --hard`、`deploy`、`curl` 管道安装、读取 `.env`、输出环境变量、`--sandbox danger-full-access`。
   - 禁止写出工作区。
   - §18.1–§18.10 的测试表格是专项回归测试的验收标准，不作为 shell 命令执行。

#### 五、通用 Result Bundle

1. `collect_result.sh` 必须生成完整 Result Bundle，包含：
   - task_id、branch、git status、changed files、git diff --stat
   - 实际执行命令、测试结果、失败和跳过项
   - 越界检查、敏感信息检查、遗留问题、next_action
2. `make_delivery_summary.sh` 必须从真实 Result Bundle 生成，**不得硬编码特定任务内容**（删除"5 个脚手架脚本已落地"等硬编码）。
3. 企业微信摘要必须简洁，不直接输出完整日志和敏感内容。

#### 六、固定 CodeBuddy 命令协议

在 CODEBUDDY.md 中增加明确的命令协议：

| 命令 | 行为 |
|------|------|
| `接收 TASK` | 读取并验证 TASK，确认 Issue Gate |
| `PLAN <TASK_ID>` | 只读 Plan，不修改任何业务文件 |
| `APPROVE <TASK_ID>` | 调用 `approve_task.sh` 生成与 Plan 哈希绑定的批准记录 |
| `DEV <TASK_ID>` | workspace-write 开发，必须验证批准记录和分支 |
| `STATUS <TASK_ID>` | 只读查询当前状态 |
| `CANCEL <TASK_ID>` | 取消任务，不 reset、不删除用户文件 |
| `RESULT <TASK_ID>` | 返回脱敏摘要（不输出完整日志） |

#### 七、统一文档

同步以下文件的路径、命令、参数契约：

- CODEBUDDY.md
- `docs/workflows/ai_delivery_workflow.md`
- `docs/workflows/github_issue_trace_workflow.md`
- TASK 模板（`docs/tasks/TASK_TEMPLATE.md`）
- README.md（工作站入口）
- 相关脚本帮助信息（usage）

---

## 6. 不做事项

- ❌ 不做 Daemon
- ❌ 不做 Workstation Runner
- ❌ 不部署腾讯云
- ❌ 不做多项目支持
- ❌ 不做自动任务队列
- ❌ 不做状态 Dashboard
- ❌ 不自动 push、merge、deploy
- ❌ 不自动关闭 Issue
- ❌ 不真实发送企业微信
- ❌ 不修改量化业务代码（`services/`、`apps/`、策略、数据链路）
- ❌ 不修改 `.env`、`.env.*`、token、webhook、密钥
- ❌ 不删除或重写 `data/raw/`、`data/processed/`、`data/parquet/`
- ❌ 不安装 rg（非阻塞项）
- ❌ 不合并 `scripts/ai/.out/` 和 `.ai/results/` 的现有历史产物

---

## 7. 涉及模块

### 允许修改

| 文件 | 类型 | 说明 |
|------|------|------|
| `CODEBUDDY.md` | 修改 | 增加命令协议、统一路径引用、更新工作流 |
| `README.md` | 修改 | 更新工作站入口说明 |
| `docs/tasks/TASK_TEMPLATE.md` | 修改 | 统一 TASK 保存路径、产物路径、日志路径 |
| `docs/tasks/TASK-2026-07-10-003-workstation-lean-v1-closeout.md` | 新增 | 本任务单 |
| `docs/workflows/ai_delivery_workflow.md` | 修改 | 统一路径引用、更新 SOP |
| `docs/workflows/github_issue_trace_workflow.md` | 修改 | 统一路径引用 |
| `scripts/ai/codex_plan.sh` | 修改 | 修复 `codex exec --sandbox read-only` 调用、读取完整 TASK、统一产物路径 |
| `scripts/ai/codex_dev.sh` | 修改 | 修复 `codex exec --sandbox workspace-write` 调用、增加审批门控、拒绝 main 分支、读取完整 TASK、统一产物路径 |
| `scripts/ai/run_tests.sh` | 修改 | 支持 TASK 声明的测试命令、安全限制、统一产物路径 |
| `scripts/ai/collect_result.sh` | 修改 | 增加完整 Result Bundle 字段、统一产物路径 |
| `scripts/ai/make_delivery_summary.sh` | 修改 | 删除硬编码、从真实 Result Bundle 生成、统一产物路径 |
| `scripts/ai/comment_issue_result.sh` | 修改 | 统一路径引用 |
| `scripts/ai/update_issue_status.sh` | 修改 | 统一路径引用 |
| `scripts/ai/_approve_lib.sh` | 新增 | 审批记录读写、Plan 哈希检测函数库 |
| `scripts/ai/approve_task.sh` | 新增 | 公开审批入口，计算 Plan SHA256、绑定 TASK_ID 和目标分支、写入批准时间 |

### 禁止修改

- `.env`、`.env.*`
- `data/raw/`、`data/processed/`、`data/parquet/`
- `services/`、`apps/` 业务代码
- vn.py 源码
- 策略文件
- 量化业务逻辑
- token、webhook、密钥文件
- `.workbuddy/memory/2026-07-10.md`（用户已有改动）
- 以下未授权脚本和文档（只能只读检查，不得修改）：
  - `scripts/ai/create_issue_from_task.sh`
  - `scripts/ai/link_task_issue.sh`
  - `scripts/ai/run_v12_post_auth_e2e.sh`
  - `scripts/ai/codexplan.sh`（非 `codex_plan.sh`）
  - `scripts/ai/codexdev.sh`（非 `codex_dev.sh`）
  - `scripts/ai/runtests.sh`（非 `run_tests.sh`）
  - `scripts/ai/collectresult.sh`（非 `collect_result.sh`）
  - `scripts/ai/makedeliverysummary.sh`（非 `make_delivery_summary.sh`）
  - `docs/AI_WECHAT_WORKFLOW.md`

---

## 8. 产品需求

### 8.1 Lean V1 收口目标

用户只需两步完成一次完整任务交付：

1. WorkBuddy 一次输出完整 Task Bundle（含目标、范围、允许/禁止修改、Plan/Dev 要求、测试命令、验收标准）
2. 用户将 TASK 转发给 CodeBuddy，CodeBuddy 依次执行 PLAN → 等待 APPROVE → DEV → 自动 TEST → RESULT

### 8.2 CodeBuddy 命令协议

| 命令 | 前置条件 | 行为 | 产物 |
|------|----------|------|------|
| `接收 TASK` | TASK 文件存在于 `docs/tasks/` | 读取 TASK，验证 Issue Gate | — |
| `PLAN <TASK_ID>` | TASK 已接收 | 只读调用 `codex_plan.sh` | `.ai/results/<TASK_ID>/plan_result.md` |
| `APPROVE <TASK_ID>` | Plan 已完成 | 调用 `scripts/ai/approve_task.sh --task <TASK_ID>`，计算 SHA256、绑定分支、写入批准时间 | `.ai/approvals/<TASK_ID>.approved` |
| `DEV <TASK_ID>` | 审批记录有效（Plan 哈希匹配）且不在 main 分支 | workspace-write 调用 `codex_dev.sh`，自动测试 | 代码变更 + `.ai/results/<TASK_ID>/` 下产物 |
| `STATUS <TASK_ID>` | — | 只读查询当前状态 | 状态摘要 |
| `CANCEL <TASK_ID>` | — | 标记取消，不删除文件 | — |
| `RESULT <TASK_ID>` | Dev 完成 | 返回脱敏摘要 | 企业微信友好摘要 |

### 8.3 审批记录格式

```json
{
  "task_id": "TASK-2026-07-10-003-workstation-lean-v1-closeout",
  "approved_at": "2026-07-10T22:00:00",
  "plan_sha256": "sha256:abc123...",
  "plan_file": ".ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md",
  "approved_by": "human",
  "branch": "feature/workstation-lean-v1-closeout"
}
```

审批记录文件：`.ai/approvals/<TASK_ID>.approved`

审批入口命令：`scripts/ai/approve_task.sh --task <TASK_ID>`

**审批失败条件（必须拒绝）：**
- 当前在 `main` 分支（必须在功能分支上审批）
- Plan 文件（`.ai/results/<TASK_ID>/plan_result.md`）缺失
- Plan 哈希无法计算（文件为空或读取失败）

### 8.4 Plan 变更检测

Dev 前通过 `_approve_lib.sh` 比对当前 `plan_result.md` 的 SHA256 hash 与审批记录中的 hash，不匹配则拒绝执行。

---

## 9. 量化业务规则

不涉及（纯工具链任务）。

---

## 10. 数据影响

- 无 RQData / Parquet / PostgreSQL / Redis 变更
- 无 manifest 变更
- 新增运行时目录：`.ai/approvals/`（不入库）
- `scripts/ai/.out/` 历史产物保留不迁移

---

## 11. 技术方案

### 11.1 Codex CLI 调用方式修正

当前版本 Codex CLI 0.144.1，旧式 `codex --readonly --prompt` / `codex --prompt` 不可用。

**Plan（只读）：**

```bash
codex exec --sandbox read-only "<plan_prompt>"
```

- `--sandbox read-only`：Codex 不能修改仓库文件。
- `<plan_prompt>` 是位置参数，直接跟在 flag 之后。
- **禁止使用 `--prompt`**。

**Dev（workspace-write）：**

```bash
codex exec --sandbox workspace-write "<dev_prompt>"
```

- `--sandbox workspace-write`：Codex 可在 workspace 内写文件。
- `<dev_prompt>` 是位置参数。
- **禁止使用 `--prompt`**。

**禁止项（统一写法）：**

```
--sandbox danger-full-access
```

- 全文不再写不存在的 `--danger-full-access`。
- 任何脚本、文档、Prompt 中出现的禁止项统一为 `--sandbox danger-full-access`。

### 11.2 产物路径统一方案

| 产物类型 | 旧路径 | 新路径（统一后） |
|----------|--------|-----------------|
| 正式 TASK | 分散在 `tasks/`、`docs/tasks/examples/`、`.ai/tasks/` | `docs/tasks/<TASK_ID>.md` |
| Plan 结果 | `scripts/ai/.out/<TASK_ID>/plan.md` | `.ai/results/<TASK_ID>/plan_result.md` |
| Dev 日志 | `scripts/ai/.out/<TASK_ID>/dev.log` | `.ai/logs/dev_<TASK_ID>.log` |
| 测试日志 | `scripts/ai/.out/<TASK_ID>/test.log` | `.ai/logs/test_<TASK_ID>.log` |
| 测试摘要 | `scripts/ai/.out/<TASK_ID>/test-summary.json` | `.ai/results/<TASK_ID>/test_summary.json` |
| Result Bundle | `scripts/ai/.out/<TASK_ID>/result_bundle.md` | `.ai/results/<TASK_ID>/result_bundle.md` |
| 交付摘要 | `scripts/ai/.out/<TASK_ID>/delivery_summary.md` | `.ai/results/<TASK_ID>/delivery_summary.md` |
| 审批记录 | 不存在 | `.ai/approvals/<TASK_ID>.approved` |

### 11.3 审批门控流程

```
PLAN 完成 → .ai/results/<TASK_ID>/plan_result.md 生成
         → 用户审查 plan
         → 用户执行 scripts/ai/approve_task.sh --task <TASK_ID>
           → approve_task.sh 检查当前分支（拒绝 main）
           → approve_task.sh 检查 plan_result.md 存在
           → approve_task.sh 计算 plan_result.md 的 SHA256
           → approve_task.sh 绑定 TASK_ID + 目标分支 + 批准时间
           → 写入 .ai/approvals/<TASK_ID>.approved
         → 用户执行 DEV（codex_dev.sh --task <TASK_ID>）
           → codex_dev.sh 检查当前分支（拒绝 main）
           → codex_dev.sh 通过 _approve_lib.sh 读取审批记录
           → _approve_lib.sh 比对当前 plan_result.md 的 SHA256 与审批记录中的 hash
             → 匹配：继续执行
             → 不匹配或无记录：拒绝，exit 非 0
```

> **Bootstrap Dev 例外（仅限本任务首次 Dev）：** 上述流程中 `codex_dev.sh` 当前已损坏，首次 Dev 不能运行旧脚本。详见 §11.7。用户 APPROVE 后，CodeBuddy 直接调用 `codex exec --sandbox workspace-write "<§16 完整 Dev Prompt>"`，禁止运行旧 `codex_dev.sh`。修复后，再使用新 `codex_dev.sh` 做门控回归验证。

**审批失败条件（approve_task.sh 必须拒绝）：**
1. 当前在 `main` 分支——必须在功能分支上审批。
2. Plan 文件缺失——`.ai/results/<TASK_ID>/plan_result.md` 不存在。
3. Plan 哈希无法计算——文件为空或 `shasum -a 256` 失败。

**Dev 拒绝条件（codex_dev.sh 必须拒绝）：**
1. 当前在 `main` 分支。
2. 无审批记录文件 `.ai/approvals/<TASK_ID>.approved`。
3. 审批记录中的 Plan hash 与当前 `plan_result.md` 的 hash 不匹配。

### 11.4 测试策略

`run_tests.sh` 修改逻辑：

1. 读取 TASK 中 `### 18.0 自动执行测试命令` 下的 fenced bash 代码块。
2. 若有声明，按声明执行。
3. 若无声明，执行最小默认测试集：
   - `git diff --check`
   - `bash -n scripts/ai/*.sh`（若脚本有变更）
   - 根据变更文件范围选择后端或前端最小测试
4. 默认 dry-run，不真实发送。

**测试命令自动执行安全限制（硬约束）：**

| # | 规则 | 说明 |
|---|------|------|
| S1 | 只解析固定位置的 fenced bash 代码块 | `run_tests.sh` 仅提取 `### 18.0 自动执行测试命令` 下的 ```` ```bash ```` 代码块中的命令，不解析其他位置的文本（§18.1–§18.10 的测试表格不作为 shell 命令执行） |
| S2 | 不使用 `eval` 执行整段文本 | 禁止 `eval "$block"`，必须逐行拆分后逐条执行 |
| S3 | 逐条执行、逐条记录退出码 | 每条命令独立执行，记录 `{command, exit_code, output}` 三元组 |
| S4 | 拒绝危险命令 | 逐条检查，命中以下模式则拒绝并记录：`rm`、`git push`、`git merge`、`git reset --hard`、`deploy`、`curl` 管道安装（`curl ... \| sh` / `curl ... \| bash`）、读取 `.env`（`cat .env` / `source .env`）、输出环境变量（`env` / `printenv` / `echo $`）、`--sandbox danger-full-access` |
| S5 | 禁止写出工作区 | 测试命令不得包含写出到仓库根目录之外的路径；不允许 `>` 重定向到 `..` 或 `/tmp` 之外的系统目录 |

### 11.5 Result Bundle 完整字段

```markdown
# Result Bundle — <TASK_ID>

- task_id
- branch
- git status（clean/dirty）
- changed files（列表）
- git diff --stat
- 实际执行命令（列表）
- 测试结果（passed/failed/skipped，含计数）
- 越界检查（是否修改了禁止修改的路径）
- 敏感信息检查（是否含 token/webhook/密钥）
- 遗留问题（列表）
- next_action（建议）
```

### 11.6 Bootstrap Plan 例外（仅限本任务）

**背景：** 当前 `scripts/ai/codex_plan.sh` 本身已损坏（使用无效的 `codex --readonly --prompt` 调用），无法用于生成本任务的 Plan。因此本任务首次 Plan 允许 CodeBuddy 直接执行一次裸 Codex 调用。

**例外规则：**

1. 本任务首次 Plan 允许 CodeBuddy 直接执行：
   ```bash
   codex exec --sandbox read-only "<完整 Plan Prompt>"
   ```
   并将输出保存为：
   ```
   .ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md
   ```

2. **Bootstrap Plan 必须确认业务文件零修改。** Plan 执行后，CodeBuddy 必须运行 `git diff --name-only` 确认 `services/`、`apps/`、`data/`、`.env` 下无任何变更。如有变更，Plan 结果作废，必须排查原因。

3. **该例外只限本任务。** 脚本修复后（即 `codex_plan.sh` 修复为 `codex exec --sandbox read-only` 调用），后续任务禁止裸调 Codex，必须使用 `scripts/ai/codex_plan.sh`。

4. Bootstrap Plan 使用的完整 Plan Prompt 见 §15。

### 11.7 Bootstrap Dev 例外（仅限本任务首次 Dev）

**背景：** 当前 `scripts/ai/codex_dev.sh` 本身已损坏（使用无效的 `codex --prompt` 调用），无法用于执行本任务的 Dev。用损坏的 `codex_dev.sh` 来修复自身构成死锁。因此本任务首次 Dev 允许 CodeBuddy 直接调用 Codex CLI，绕过损坏的脚本。

**例外规则：**

1. **仅限本任务首次 Dev。** 后续所有任务必须使用修复后的 `codex_dev.sh`。
2. **用户明确回复 APPROVE 后才允许执行。** CodeBuddy 不得自行启动 Dev。
3. **CodeBuddy 先手动计算当前 `plan_result.md` 的 SHA256：**

   ```bash
   shasum -a 256 .ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md
   ```

4. **手动写入审批记录文件：**

   ```
   .ai/approvals/TASK-2026-07-10-003-workstation-lean-v1-closeout.approved
   ```

   审批记录 JSON 格式：

   ```json
   {
     "task_id": "TASK-2026-07-10-003-workstation-lean-v1-closeout",
     "plan_sha256": "sha256:<计算结果>",
     "plan_file": ".ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md",
     "approved_at": "<ISO 8601 时间>",
     "approved_by": "human",
     "branch": "feature/workstation-lean-v1-closeout"
   }
   ```

5. **随后由 CodeBuddy 直接调用：**

   ```bash
   codex exec --sandbox workspace-write "<§16 完整 Dev Prompt>"
   ```

6. **禁止运行当前损坏的旧 `codex_dev.sh`。**
7. **修复完成后，再使用新 `codex_dev.sh` 做门控回归验证**：确认修复后的脚本能正确验证审批记录、拒绝 main 分支、比对 Plan 哈希。
8. **此例外仅限本任务；后续所有任务必须使用 `codex_dev.sh`。**

### 11.8 脏工作区基线规则

**背景：** Dev 前工作区已存在已知改动（非 Codex 引入），必须在 Dev 前记录基线，Dev 后区分 pre-existing changes 和本次 Dev changes。

**已知 Dev 前改动（pre-existing changes）：**

- `.workbuddy/memory/2026-07-10.md` — 用户已有改动
- 本 TASK 文件（`docs/tasks/TASK-2026-07-10-003-workstation-lean-v1-closeout.md`）及 Issue/状态元信息变更

**规则：**

1. **Dev 前记录基线：** CodeBuddy 在 Bootstrap Dev 执行前，运行 `git status --short` 和 `git diff --name-only`，记录文件列表和每个文件的 SHA256 基线。
2. **`.workbuddy/memory/2026-07-10.md` 是用户已有改动。** Codex 禁止修改、覆盖、删除或提交该文件。
3. **Result Bundle 必须区分 pre-existing changes 和本次 Dev changes。** `collect_result.sh` 的 changed files 列表必须标注哪些是 pre-existing、哪些是本次 Dev 新增。
4. **如果出现其他未知改动，立即停止。** 不在已知 pre-existing 列表中的改动视为异常，Dev 中止并报告。
5. **禁止 `reset`、`clean`、`checkout` 或 `stash` 用户文件。** Codex 不得执行任何会丢弃用户已有改写的操作。

---

## 12. 交互视觉要求

不涉及（CLI 工具链任务）。

---

## 13. 安全权限要求

- 不碰 `.env` / token / webhook / 密钥
- 不自动 push / merge / deploy
- 不自动 close Issue
- 不真实发送企业微信
- Plan 只读（`codex exec --sandbox read-only`），Dev 仅 workspace-write（`codex exec --sandbox workspace-write`）
- 禁止 `--sandbox danger-full-access`
- Dev 拒绝在 `main` 分支运行
- 审批拒绝在 `main` 分支执行
- Result Bundle 和交付摘要必须脱敏
- 审批记录不含敏感内容
- 测试命令逐条安全检查，拒绝危险命令
- **Bootstrap Dev 例外（仅限本任务首次 Dev）**：禁止运行当前损坏的旧 `codex_dev.sh`；用户 APPROVE 后 CodeBuddy 直接调用 `codex exec --sandbox workspace-write`；修复后用新脚本做门控回归验证
- **脏工作区基线**：Dev 前记录 git status 和 SHA256 基线；`.workbuddy/memory/2026-07-10.md` 禁止修改/覆盖/删除/提交；禁止 `reset`/`clean`/`checkout`/`stash` 用户文件；Result Bundle 区分 pre-existing 和 Dev changes
- **修改范围严格限制**：只能修改 §7 列出的文件；`create_issue_from_task.sh`、`link_task_issue.sh`、`run_v12_post_auth_e2e.sh`、`codexplan.sh`、`codexdev.sh`、`runtests.sh`、`collectresult.sh`、`makedeliverysummary.sh`、`docs/AI_WECHAT_WORKFLOW.md` 等未授权文件只能只读检查

---

## 14. 开发步骤

1. 从 `main` 创建分支 `feature/workstation-lean-v1-closeout`（需用户显式授权）
2. **Bootstrap Plan（例外，仅限本任务）**：因 `codex_plan.sh` 已损坏，CodeBuddy 直接执行 `codex exec --sandbox read-only "<完整 Plan Prompt>"`，输出保存为 `.ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md`。执行后确认业务文件零修改。
3. **等待用户审查 Plan 并明确回复 APPROVE。** 用户 APPROVE 后，CodeBuddy 按 §11.7 Bootstrap Dev 例外执行：
   - 手动计算 `plan_result.md` 的 SHA256
   - 手动写入 `.ai/approvals/TASK-2026-07-10-003-workstation-lean-v1-closeout.approved`（绑定 task_id、plan_sha256、approved_at、approved_by=human、branch=feature/workstation-lean-v1-closeout）
   - 直接调用 `codex exec --sandbox workspace-write "<§16 完整 Dev Prompt>"`（**禁止运行当前损坏的旧 `codex_dev.sh`**）
4. 新增 `scripts/ai/_approve_lib.sh`（审批记录读写 + SHA256 hash 检测函数 + 分支检查函数）
5. 新增 `scripts/ai/approve_task.sh`（公开审批入口：`--task <TASK_ID>`，计算 Plan SHA256、绑定 TASK_ID 和目标分支、写入批准时间，拒绝 main 分支/Plan 缺失/哈希无法计算）
6. 修改 `scripts/ai/codex_plan.sh`：修复为 `codex exec --sandbox read-only` 调用、Prompt 作为位置参数、读取完整 TASK、统一产物路径到 `.ai/results/`、统一日志到 `.ai/logs/`
7. 修改 `scripts/ai/codex_dev.sh`：修复为 `codex exec --sandbox workspace-write` 调用、Prompt 作为位置参数、增加审批门控（通过 `_approve_lib.sh` 验证审批记录和当前 Plan 哈希）、拒绝 main 分支、读取完整 TASK、统一产物路径和日志路径
8. 修改 `scripts/ai/run_tests.sh`：支持 TASK 声明的测试命令、增加安全限制（§11.4 S1-S5）、统一产物路径和日志路径
9. 修改 `scripts/ai/collect_result.sh`：增加完整 Result Bundle 字段（含 pre-existing changes 与 Dev changes 区分）、统一产物路径
10. 修改 `scripts/ai/make_delivery_summary.sh`：删除硬编码、从真实 Result Bundle 生成、统一产物路径
11. 修改 `scripts/ai/comment_issue_result.sh`：统一路径引用
12. 修改 `scripts/ai/update_issue_status.sh`：统一路径引用
13. 修改 `CODEBUDDY.md`：增加命令协议、统一路径、更新工作流
14. 修改 `docs/workflows/ai_delivery_workflow.md`：统一路径、更新 SOP
15. 修改 `docs/workflows/github_issue_trace_workflow.md`：统一路径
16. 修改 `docs/tasks/TASK_TEMPLATE.md`：统一路径约定
17. 修改 `README.md`：更新工作站入口说明
18. **修复完成后，使用新 `codex_dev.sh` 做门控回归验证**：确认修复后的脚本能正确验证审批记录、拒绝 main 分支、比对 Plan 哈希
19. 运行测试验证（bash -n、Plan 只读、审批门控、Dev 执行、Result Bundle、测试安全限制、脏工作区基线）
（步骤 4-17 为 Bootstrap Dev Codex 执行范围；步骤 18 为门控回归验证；步骤 19 为自动化测试）

---

## 15. Codex Plan Prompt

> **Bootstrap Plan 例外说明：** 因当前 `codex_plan.sh` 已损坏，本任务首次 Plan 允许 CodeBuddy 直接执行 `codex exec --sandbox read-only "<下方完整 Plan Prompt>"`，输出保存为 `.ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md`。执行后必须确认业务文件零修改。该例外只限本任务；脚本修复后，后续任务禁止裸调 Codex，必须使用 `codex_plan.sh`。

> **修改范围硬约束：** Plan 中拟修改文件列表只能包含 §7"允许修改"中列出的文件。以下文件**不在修改范围内**，只能只读检查，不得修改：
> - `scripts/ai/create_issue_from_task.sh`
> - `scripts/ai/link_task_issue.sh`
> - `scripts/ai/run_v12_post_auth_e2e.sh`
> - `scripts/ai/codexplan.sh`（注意：与 `codex_plan.sh` 不同）
> - `scripts/ai/codexdev.sh`（注意：与 `codex_dev.sh` 不同）
> - `scripts/ai/runtests.sh`（注意：与 `run_tests.sh` 不同）
> - `scripts/ai/collectresult.sh`（注意：与 `collect_result.sh` 不同）
> - `scripts/ai/makedeliverysummary.sh`（注意：与 `make_delivery_summary.sh` 不同）
> - `docs/AI_WECHAT_WORKFLOW.md`
> - 其他未在 §7 明确列出的文件

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
- 当前分支：main，工作区干净
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
  - `scripts/ai/codexplan.sh`（非 `codex_plan.sh`）
  - `scripts/ai/codexdev.sh`（非 `codex_dev.sh`）
  - `scripts/ai/runtests.sh`（非 `run_tests.sh`）
  - `scripts/ai/collectresult.sh`（非 `collect_result.sh`）
  - `scripts/ai/makedeliverysummary.sh`（非 `make_delivery_summary.sh`）
  - `docs/AI_WECHAT_WORKFLOW.md`
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
- 修改范围仅限 §7 允许修改列表；未授权文件（create_issue_from_task.sh 等）只读检查
- Plan 为只读执行，不得修改任何文件
```

---

## 16. Codex Dev Prompt

> **Bootstrap Dev 例外（仅限本任务首次 Dev）：** 因当前 `codex_dev.sh` 本身已损坏，无法用损坏的脚本修复自身（死锁）。本任务首次 Dev 由 CodeBuddy 直接调用 `codex exec --sandbox workspace-write "<下方完整 Dev Prompt>"`。**禁止运行当前损坏的旧 `codex_dev.sh`。** 修复完成后，再使用新 `codex_dev.sh` 做门控回归验证。此例外仅限本任务；后续所有任务必须使用 `codex_dev.sh`。

> **修改范围硬约束：** 只能新增或修改 §7"允许修改"中列出的文件。以下文件**不在修改范围内**，只能只读检查：
> - `scripts/ai/create_issue_from_task.sh`、`scripts/ai/link_task_issue.sh`、`scripts/ai/run_v12_post_auth_e2e.sh`
> - `scripts/ai/codexplan.sh`、`scripts/ai/codexdev.sh`、`scripts/ai/runtests.sh`、`scripts/ai/collectresult.sh`、`scripts/ai/makedeliverysummary.sh`
> - `docs/AI_WECHAT_WORKFLOW.md`
> - 其他未在 §7 明确列出的文件

> **脏工作区基线规则：** Dev 前工作区已存在已知改动（`.workbuddy/memory/2026-07-10.md` 和本 TASK 文件）。Codex 禁止修改、覆盖、删除或提交 `.workbuddy/memory/2026-07-10.md`。Result Bundle 必须区分 pre-existing changes 和本次 Dev changes。禁止 `reset`、`clean`、`checkout` 或 `stash` 用户文件。

```
你是 Codex CLI，在归一量化工作站仓库中执行 **Lean V1 收口开发**。

## 必读

1. AGENTS.md
2. CODEBUDDY.md
3. 本任务单全文：docs/tasks/TASK-2026-07-10-003-workstation-lean-v1-closeout.md
4. 已确认的 Plan 输出：.ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md

## 任务

实现 TASK-2026-07-10-003 的全部 7 项目标。

## 允许修改（仅限以下文件，对应 TASK §7）

- CODEBUDDY.md
- README.md
- docs/tasks/TASK_TEMPLATE.md
- docs/workflows/ai_delivery_workflow.md
- docs/workflows/github_issue_trace_workflow.md
- scripts/ai/codex_plan.sh
- scripts/ai/codex_dev.sh
- scripts/ai/run_tests.sh
- scripts/ai/collect_result.sh
- scripts/ai/make_delivery_summary.sh
- scripts/ai/comment_issue_result.sh
- scripts/ai/update_issue_status.sh
- scripts/ai/_approve_lib.sh（新增）
- scripts/ai/approve_task.sh（新增）

## 禁止修改（以下文件不在修改范围内，只能只读检查）

- scripts/ai/create_issue_from_task.sh
- scripts/ai/link_task_issue.sh
- scripts/ai/run_v12_post_auth_e2e.sh
- scripts/ai/codexplan.sh（非 codex_plan.sh）
- scripts/ai/codexdev.sh（非 codex_dev.sh）
- scripts/ai/runtests.sh（非 run_tests.sh）
- scripts/ai/collectresult.sh（非 collect_result.sh）
- scripts/ai/makedeliverysummary.sh（非 make_delivery_summary.sh）
- docs/AI_WECHAT_WORKFLOW.md
- .env、.env.*、token、webhook、密钥
- data/raw/、data/processed/、data/parquet/
- services/、apps/ 业务代码
- vn.py 源码、策略文件
- .workbuddy/memory/2026-07-10.md（用户已有改动，禁止修改、覆盖、删除或提交）

## 开发要求

1. 按开发步骤逐个创建/修改文件
2. 每个脚本修改后 `bash -n` 语法验证
3. Codex CLI 调用必须基于 0.144.1 版本实际支持的参数：
   - Plan：`codex exec --sandbox read-only "<prompt>"`（位置参数，禁止 --prompt）
   - Dev：`codex exec --sandbox workspace-write "<prompt>"`（位置参数，禁止 --prompt）
   - 禁止 `--sandbox danger-full-access`
4. Plan 脚本输出到 `.ai/results/<TASK_ID>/plan_result.md`
5. Dev 脚本增加审批门控：
   - 通过 `_approve_lib.sh` 验证审批记录和当前 Plan 哈希
   - 无 `.ai/approvals/<TASK_ID>.approved` 或 Plan 哈希不匹配则拒绝
   - 在 `main` 分支拒绝执行
6. 新增 `approve_task.sh`：
   - 命令格式：`approve_task.sh --task <TASK_ID>`
   - 计算 Plan SHA256、绑定 TASK_ID 和目标分支、写入批准时间
   - main 分支、Plan 缺失或哈希无法计算时审批失败
7. run_tests.sh 支持读取 TASK 声明的测试命令，并执行安全限制：
   - 只解析 §18.0 固定位置 fenced bash 代码块
   - 不使用 eval
   - 逐条执行、逐条记录退出码
   - 拒绝 rm、git push、git merge、git reset --hard、deploy、curl 管道安装、读取 .env、输出环境变量、--sandbox danger-full-access
   - 禁止写出工作区
8. collect_result.sh 生成完整 Result Bundle（11 个字段）
9. make_delivery_summary.sh 删除所有硬编码，从真实 Result Bundle 生成
10. 所有路径引用统一：TASK→docs/tasks/，产物→.ai/results/，日志→.ai/logs/，审批→.ai/approvals/
11. CODEBUDDY.md 增加 7 个命令协议
12. 文档与脚本参数方式统一

## 安全护栏（硬约束）

- 不 push、merge、deploy
- 不自动 close Issue
- 不真实发送企业微信
- 禁止 --sandbox danger-full-access
- Dev 拒绝 main 分支
- 默认 dry-run
- 完成后列出变更文件与测试命令
- 禁止修改 .workbuddy/memory/2026-07-10.md（用户已有改动）
- 禁止 reset、clean、checkout 或 stash 用户文件
- Result Bundle 必须区分 pre-existing changes 和本次 Dev changes
- 出现未知改动立即停止
```

---

## 17. CodeBuddy 执行 Prompt

```
你是 CodeBuddy，在归一量化工作站本地仓库执行 Lean V1 收口。

## 前置确认

1. 当前分支：feature/workstation-lean-v1-closeout（从 main 创建，禁止在 main 上 Dev）
2. Issue 已绑定（Issue Gate 通过，Issue #5）
3. Plan 已生成且业务文件零修改

## 执行流程（严格按序）

### 第一步：Bootstrap Plan（例外，仅限本任务）

因当前 codex_plan.sh 已损坏，本任务首次 Plan 允许 CodeBuddy 直接执行：

  codex exec --sandbox read-only "<§15 中的完整 Plan Prompt>"

输出保存为：
  .ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md

执行后必须确认业务文件零修改：
  git diff --name-only  # services/ apps/ data/ .env 下应为空

该例外只限本任务；脚本修复后，后续任务禁止裸调 Codex，必须使用 codex_plan.sh。

### 第二步：等待用户审查 Plan 并明确回复 APPROVE

用户审查 plan_result.md 后，必须明确回复 APPROVE。
CodeBuddy 不得自行启动 Dev。

用户 APPROVE 后，CodeBuddy 按 §11.7 Bootstrap Dev 例外执行：
  - 计算 plan_result.md 的 SHA256：
      shasum -a 256 .ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md
  - 绑定 task_id、plan_sha256、approved_at、approved_by=human、branch=feature/workstation-lean-v1-closeout
  - 写入 .ai/approvals/TASK-2026-07-10-003-workstation-lean-v1-closeout.approved

注意：审批脚本 approve_task.sh 尚未创建，此步骤由 CodeBuddy 手动完成。
修复后，后续任务使用：scripts/ai/approve_task.sh --task <TASK_ID>

### 第三步：Bootstrap Dev（例外，仅限本任务首次 Dev）

因当前 codex_dev.sh 本身已损坏（死锁），禁止运行旧 codex_dev.sh。

CodeBuddy 直接调用：
  codex exec --sandbox workspace-write "<§16 完整 Dev Prompt>"

执行前记录脏工作区基线：
  - git status --short
  - git diff --name-only
  - 对已知 pre-existing changes 记录 SHA256 基线

执行约束：
  - 禁止运行当前损坏的旧 codex_dev.sh
  - 禁止修改 .workbuddy/memory/2026-07-10.md
  - 禁止 reset、clean、checkout 或 stash 用户文件
  - Result Bundle 必须区分 pre-existing changes 和本次 Dev changes

### 第四步：门控回归验证

修复完成后，使用新 codex_dev.sh 做门控回归验证：
  - 确认新 codex_dev.sh 能正确验证审批记录
  - 确认新 codex_dev.sh 拒绝 main 分支
  - 确认新 codex_dev.sh 比对 Plan 哈希

### 第五步：测试

运行自动化测试（§18.0 自动执行测试命令中的 fenced bash 代码块）。

### 第六步：collect_result.sh + make_delivery_summary.sh

### 第七步：RESULT — 返回脱敏摘要

## 正确执行顺序（不可跳序）

修订 TASK → 重新生成 Bootstrap 只读 Plan → 用户审查 → 用户明确 APPROVE
→ 手动生成一次性审批记录 → Bootstrap Dev 直接使用 codex exec --sandbox workspace-write
→ 修复脚本 → 使用修复后的脚本做完整回归 → TEST → RESULT

## 安全约束

- 不 push / merge / deploy
- 不修改 .env / token / webhook
- 不修改业务代码
- Dev 拒绝 main 分支
- 禁止 --sandbox danger-full-access
- 禁止运行当前损坏的旧 codex_dev.sh（仅限本任务首次 Dev 例外）
- 禁止修改 .workbuddy/memory/2026-07-10.md
```

---

## 18. 测试清单

### 18.0 自动执行测试命令

> **说明：** `run_tests.sh` 只解析本小节下方的 fenced bash 代码块中的命令，逐条执行、逐条记录退出码。下方 §18.1–§18.10 的测试表格是专项回归测试的验收标准，不是 shell 命令，不会被 `run_tests.sh` 当作命令执行。

以下命令安全、确定、可自动执行，不含 `eval`、`bash -c`、`sh -c`、`push`、`merge`、`deploy`、`rm`、`reset`、`clean`、`curl` 管道安装，不读取 `.env`，不写生产数据：

```bash
git diff --check
bash -n scripts/ai/codex_plan.sh
bash -n scripts/ai/codex_dev.sh
bash -n scripts/ai/run_tests.sh
bash -n scripts/ai/collect_result.sh
bash -n scripts/ai/make_delivery_summary.sh
bash -n scripts/ai/comment_issue_result.sh
bash -n scripts/ai/update_issue_status.sh
bash -n scripts/ai/approve_task.sh
bash -n scripts/ai/_approve_lib.sh
```

### 18.1 语法与静态检查

| # | 测试项 | 命令 | 预期结果 |
|---|--------|------|----------|
| T01 | 所有脚本 bash -n | `for f in scripts/ai/*.sh; do bash -n "$f" || exit 1; done` | 全部通过（含新增 approve_task.sh 和 _approve_lib.sh） |
| T02 | git diff --check | `git diff --check` | 无冲突标记 |

### 18.2 Plan 只读验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T03 | Plan 真实调用 Codex CLI | AC1 | `codex exec --sandbox read-only` 成功执行 |
| T04 | Plan 后业务文件零修改 | AC1 | `git diff --name-only` 在 services/ apps/ data/ 下为空 |
| T05 | plan_result.md 生成到 .ai/results/ | AC7 | 文件存在于 `.ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md` |

### 18.3 审批门控验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T06 | 无审批时 Dev 拒绝 | AC4 | exit 非 0，报"审批记录不存在" |
| T07 | Plan 变化后旧审批失效 | AC4 | 修改 plan_result.md 后 Dev 拒绝，报"plan hash 不匹配" |
| T08 | 审批后 Dev 可执行 | AC4 | 有效审批记录 + hash 匹配 → Dev 正常执行 |
| T09 | approve_task.sh 拒绝 main 分支 | AC4 | 在 main 分支执行 approve_task.sh，exit 非 0 |
| T10 | approve_task.sh 拒绝 Plan 缺失 | AC4 | plan_result.md 不存在时 approve_task.sh，exit 非 0 |
| T11 | approve_task.sh 拒绝哈希无法计算 | AC4 | plan_result.md 为空时 approve_task.sh，exit 非 0 |
| T12 | codex_dev.sh 拒绝 main 分支 | AC4 | 在 main 分支执行 codex_dev.sh，exit 非 0 |
| T13 | codex_dev.sh 通过 _approve_lib.sh 验证审批 | AC4 | 审批记录和当前 Plan 哈希均通过 _approve_lib.sh 验证 |

### 18.4 Dev 执行验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T14 | Demo TASK 批准后 Dev 可运行 | AC5 | Dev 成功执行，代码变更在允许范围内 |
| T15 | Dev 不修改禁止路径 | AC8 | services/ apps/ data/ .env 无变更 |
| T16 | Dev 后自动运行测试 | AC6 | run_tests.sh 自动调用 |
| T17 | Dev 使用 codex exec --sandbox workspace-write | AC5 | 调用方式正确，禁止 --prompt |

### 18.5 Result Bundle 验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T18 | Result Bundle 包含全部 11 个字段 | AC7 | task_id, branch, git status, changed files, git diff --stat, 执行命令, 测试结果, 越界检查, 敏感信息检查, 遗留问题, next_action |
| T19 | Result Bundle 不是硬编码 | AC7 | 内容来自实际执行结果 |
| T20 | 交付摘要从真实 Result Bundle 生成 | AC7 | make_delivery_summary.sh 无硬编码内容 |

### 18.6 路径统一验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T21 | 产物全部进入 .ai/results/<TASK_ID>/ | AC7 | 不在 scripts/ai/.out/ |
| T22 | 日志全部进入 .ai/logs/ | AC7 | 统一路径 |
| T23 | 审批记录在 .ai/approvals/ | AC7 | 统一路径 |

### 18.7 文档一致性验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T24 | CODEBUDDY.md 含 7 个命令协议 | AC1 | 命令定义完整，APPROVE 引用 approve_task.sh |
| T25 | ai_delivery_workflow.md 路径引用统一 | AC7 | 引用 .ai/results/ 和 .ai/logs/ |
| T26 | github_issue_trace_workflow.md 路径引用统一 | AC7 | 同上 |
| T27 | TASK_TEMPLATE.md 路径约定更新 | AC7 | 同上 |

### 18.8 测试安全限制验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T28 | run_tests.sh 只解析固定标题下 fenced bash 代码块 | AC6 | 不解析非 §18 下的文本 |
| T29 | run_tests.sh 不使用 eval | AC6 | 逐行拆分执行 |
| T30 | run_tests.sh 逐条执行逐条记录退出码 | AC6 | 每条命令有独立 exit_code 记录 |
| T31 | run_tests.sh 拒绝 rm 命令 | AC6 | 检测到 rm 则拒绝并记录 |
| T32 | run_tests.sh 拒绝 git push / git merge / git reset --hard | AC6 | 检测到则拒绝 |
| T33 | run_tests.sh 拒绝 curl 管道安装 | AC6 | 检测到 `curl ... \| sh` 则拒绝 |
| T34 | run_tests.sh 拒绝读取 .env / 输出环境变量 | AC6 | 检测到则拒绝 |
| T35 | run_tests.sh 拒绝 --sandbox danger-full-access | AC6 | 检测到则拒绝 |
| T36 | run_tests.sh 禁止写出工作区 | AC6 | 检测到重定向到工作区外则拒绝 |

### 18.9 回归验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T37 | 敏感信息扫描 | AC9 | Result Bundle 中无 token/webhook/密钥 |
| T38 | 现有 GitHub Issue 脚本回归 | AC10 | comment_issue_result.sh / update_issue_status.sh 仍可正常执行 |
| T39 | Issue 评论可找到 .ai/results 中的 Plan/Test/Delivery | AC10 | 路径正确 |
| T40 | approve_task.sh 可正常生成审批记录 | AC4 | 在功能分支上、Plan 存在时成功写入 .ai/approvals/ |

### 18.10 Bootstrap Plan 例外验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T41 | Bootstrap Plan 业务文件零修改 | AC1 | `git diff --name-only` 在 services/ apps/ data/ 下为空 |
| T42 | Bootstrap Plan 保存到正确路径 | AC7 | `.ai/results/TASK-2026-07-10-003-workstation-lean-v1-closeout/plan_result.md` 存在 |

### 18.11 Bootstrap Dev 例外验证

| # | 测试项 | 验收标准 | 预期结果 |
|---|--------|----------|----------|
| T43 | Bootstrap Dev 不运行旧 codex_dev.sh | AC14 | 首次 Dev 直接调用 `codex exec --sandbox workspace-write`，旧 codex_dev.sh 未被执行 |
| T44 | Bootstrap Dev 审批记录手动写入 | AC14 | `.ai/approvals/TASK-2026-07-10-003-workstation-lean-v1-closeout.approved` 包含 task_id、plan_sha256、approved_at、approved_by=human、branch |
| T45 | 修复后新 codex_dev.sh 门控回归验证 | AC14 | 新脚本正确验证审批记录、拒绝 main 分支、比对 Plan 哈希 |
| T46 | 脏工作区基线记录 | AC16 | Dev 前 git status 和 SHA256 基线已记录；pre-existing changes 和 Dev changes 在 Result Bundle 中区分 |
| T47 | .workbuddy/memory/2026-07-10.md 未被修改 | AC16 | Codex 未修改/覆盖/删除/提交该文件 |
| T48 | 修改范围越界检查 | AC17 | §7 允许范围之外的文件未被修改 |

---

## 19. 验收标准

1. WorkBuddy 一次输出完整 Task Bundle（含目标、范围、允许/禁止修改、Plan/Dev 要求、测试命令、验收标准）。
2. 用户只需把 TASK 转发给 CodeBuddy 一次。
3. CodeBuddy 可执行 PLAN 并返回摘要（`codex exec --sandbox read-only` 成功，业务文件零修改）。
4. 用户回复 APPROVE 后才能 DEV（无审批或 Plan 哈希不匹配或 main 分支时 Dev 拒绝）。
5. Codex CLI 是唯一代码执行器（`codex exec --sandbox workspace-write`，禁止 `--sandbox danger-full-access`，Prompt 为位置参数，禁止 `--prompt`）。
6. Dev 后自动测试并生成通用 Result Bundle（11 个字段，非硬编码），测试命令逐条安全检查。
7. 文档、参数和产物目录完全一致：
   - TASK → `docs/tasks/<TASK_ID>.md`
   - 产物 → `.ai/results/<TASK_ID>/`
   - 日志 → `.ai/logs/`
   - 审批 → `.ai/approvals/<TASK_ID>.approved`
8. 不修改归一量化业务代码和数据（`services/`、`apps/`、`data/`、`.env` 零变更）。
9. 不增加云部署或复杂调度。
10. 可以进入 Lean V1 Demo（完整流程可演示：接收 TASK → PLAN → APPROVE（`approve_task.sh`）→ DEV → TEST → RESULT）。
11. 新增 `scripts/ai/approve_task.sh` 公开审批入口，支持 `--task <TASK_ID>`，计算 Plan SHA256、绑定分支、写入批准时间。
12. `codex_dev.sh` 通过 `_approve_lib.sh` 验证审批记录和当前 Plan 哈希，拒绝 main 分支。
13. Bootstrap Plan 例外仅限本任务：直接 `codex exec --sandbox read-only` 执行，业务文件零修改，后续任务必须使用 `codex_plan.sh`。
14. **Bootstrap Dev 例外仅限本任务首次 Dev**：因 `codex_dev.sh` 本身已损坏（死锁），首次 Dev 由 CodeBuddy 直接调用 `codex exec --sandbox workspace-write "<§16 完整 Dev Prompt>"`。**禁止运行当前损坏的旧 `codex_dev.sh`。** 修复完成后，再使用新 `codex_dev.sh` 做门控回归验证。后续所有任务必须使用 `codex_dev.sh`。
15. 测试命令自动执行满足安全限制（只解析 §18.0 固定位置 fenced bash 代码块、不使用 eval、逐条执行逐条记录、拒绝危险命令、禁止写出工作区）。
16. **脏工作区基线规则**：Dev 前记录 `git status` 和 SHA256 基线；`.workbuddy/memory/2026-07-10.md` 是用户已有改动，Codex 禁止修改/覆盖/删除/提交；Result Bundle 区分 pre-existing changes 和本次 Dev changes；禁止 `reset`/`clean`/`checkout`/`stash` 用户文件。
17. **修改范围严格限制**：只能新增或修改 §7"允许修改"中列出的文件。`create_issue_from_task.sh`、`link_task_issue.sh`、`run_v12_post_auth_e2e.sh`、`codexplan.sh`、`codexdev.sh`、`runtests.sh`、`collectresult.sh`、`makedeliverysummary.sh`、`docs/AI_WECHAT_WORKFLOW.md` 等未授权文件只能只读检查，不得修改。
18. **状态闭环**：满足 §1 PLAN_READY 转换条件后（Bootstrap Plan 成功、plan_result.md 存在且非空、只读退出码为 0、业务代码零修改、Issue #5 已验证），CodeBuddy 才将 TASK 状态改为 `PLAN_READY`。

---

## 20. 风险点

| 级别 | 风险 | 缓解措施 |
|------|------|----------|
| **P0** | Codex CLI 0.144.1 的 `codex exec` 参数与预期不符 | Plan 阶段先执行 `codex exec --help` 确认实际可用参数，再据此调整脚本 |
| **P0** | 审批门控误判导致合法 Dev 被拒绝 | SHA256 hash 检测使用标准 `shasum -a 256`；审批记录 JSON 格式固定；`_approve_lib.sh` 提供统一验证函数 |
| **P0** | Bootstrap Plan 裸调 Codex 意外修改业务文件 | 执行后立即 `git diff --name-only` 确认零修改；`--sandbox read-only` 保证只读 |
| **P0** | Bootstrap Dev 死锁：codex_dev.sh 本身损坏，无法用损坏的脚本修复自身 | 一次性 Bootstrap Dev 例外（§11.7）：用户明确 APPROVE 后，CodeBuddy 直接调用 `codex exec --sandbox workspace-write`，禁止运行旧 codex_dev.sh；修复后用新脚本做门控回归验证 |
| **P0** | 脏工作区中 Codex 误改/覆盖用户已有改动（.workbuddy/memory/2026-07-10.md） | Dev 前记录 git status 和 SHA256 基线；Codex 禁止修改/覆盖/删除/提交该文件；禁止 reset/clean/checkout/stash；Result Bundle 区分 pre-existing 和 Dev changes |
| **P0** | Codex 修改了 §7 允许范围之外的文件 | Plan Prompt 和 Dev Prompt 明确列出允许/禁止文件清单；Dev 后越界检查；未授权文件（create_issue_from_task.sh 等）只能只读检查 |
| **P0** | 路径迁移导致现有 Issue 留痕脚本找不到产物 | `comment_issue_result.sh` 增加新路径优先、旧路径 fallback 的多级回退 |
| **P1** | `run_tests.sh` 解析 TASK 测试命令失败 | TASK 中测试命令使用固定格式（代码块），脚本用 awk 提取；逐条安全检查 |
| **P1** | `run_tests.sh` 安全限制误判或漏判 | 危险命令模式列表可配置；逐条检查而非整体 eval |
| **P1** | `make_delivery_summary.sh` 删除硬编码后生成空摘要 | 从 Result Bundle 提取时使用固定字段映射，字段缺失则标注 `N/A` |
| **P1** | `approve_task.sh` 在 main 分支误放行 | 脚本入口第一步检查 `git branch --show-current`，main 分支直接 exit 非 0 |
| **P2** | `scripts/ai/.out/` 旧产物被脚本误读 | 新脚本统一读 `.ai/results/`，旧产物不迁移、不读取 |
| **P2** | rg 未安装导致某些搜索功能不可用 | 不依赖 rg，使用 grep/awk 替代；rg 不作为阻塞项 |

---

## 21. 交付记录

| 阶段 | 时间 | 操作者 | 说明 |
|------|------|--------|------|
| 任务创建 | 2026-07-10 | WorkBuddy | 本文件 |
| 任务修订 | 2026-07-10 | WorkBuddy | Bootstrap Dev 死锁解决、修改范围收紧、脏工作区基线、测试命令格式修正、状态闭环修正 |
| Issue 创建 | 2026-07-10 | — | #5（已创建并关联） |
| Plan 完成 | — | — | 待执行（满足 §1 PLAN_READY 转换条件后填写时间和 plan_result.md 路径） |
| Dev 完成 | — | — | — |
| 测试 | — | — | — |
| 交付 | — | — | — |

---

## 22. 补充：Mac mini 真实只读预检证据

以下为 2026-07-10 在 Mac mini 上执行的只读预检结果，已纳入本任务单的修复范围。

### 环境事实

```text
Git 分支：main
工作区状态：clean
与 origin/main 同步：是
Codex CLI 路径：/opt/homebrew/bin/codex
Codex CLI 版本：0.144.1
gh 登录状态：已登录 firehell
gh Issue 权限：满足
scripts/ai/*.sh bash -n：15/15 通过
rg 安装状态：未安装（非阻塞）
```

### 已确认阻断（纳入修复范围）

**P0（阻断级）：**

| # | 问题 | 现状 | 修复目标 |
|---|------|------|----------|
| 1 | `codex_plan.sh` 使用无效调用 `codex --readonly --prompt` | 在 0.144.1 下不可用 | 改为 `codex exec --sandbox read-only` 模式 |
| 2 | `codex_dev.sh` 使用无效调用 `codex --prompt` | 在 0.144.1 下不可用 | 改为 `codex exec --sandbox workspace-write` 模式 |
| 3 | Plan/Dev 脚本未完整读取 TASK | Plan 仅提取第 15 节，Dev 仅拼接硬编码片段 | 完整读取 TASK 全部章节 |
| 4 | Dev 无审批门控 | 允许在无审批记录下执行 | 增加 SHA256 哈希绑定的审批记录验证，拒绝 main 分支 |

**P1（高优先级）：**

| # | 问题 | 修复目标 |
|---|------|----------|
| 5 | 参数方式不统一（`--task` vs 位置参数 vs 环境变量） | 统一为 `--task <TASK_ID>` |
| 6 | TASK 文件路径不统一 | 统一到 `docs/tasks/<TASK_ID>.md` |
| 7 | 产物路径不统一（`scripts/ai/.out/` vs `.ai/results/`） | 统一到 `.ai/results/<TASK_ID>/` |
| 8 | 日志路径不统一 | 统一到 `.ai/logs/` |
| 9 | Plan 审批记录缺失 | 新增 `approve_task.sh` + `.ai/approvals/<TASK_ID>.approved` |
| 10 | 文档间路径引用不一致 | 全部统一 |
| 11 | `run_tests.sh` 硬编码 pytest | 支持 TASK 声明的测试命令 + 安全限制 |
| 12 | `collect_result.sh` / `make_delivery_summary.sh` 内容不足/硬编码 | 增加字段、删除硬编码 |
| 13 | 缺少真实回归验证 | 增加 6 项真实回归测试 |
