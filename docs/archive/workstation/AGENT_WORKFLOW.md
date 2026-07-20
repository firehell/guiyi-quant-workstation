# AGENT_WORKFLOW.md — Agent 协作流程

> 本文定义 Cursor、Codex、CodeBuddy、ChatGPT 外部审查和 WorkBuddy 在归一量化项目中的协作边界。

---

## 1. 工具分工

| 工具 | 角色 |
|---|---|
| Cursor | 主 IDE、人工检查、Git 管理、小修 |
| Codex | 主力开发 Agent，执行单一清晰任务 |
| WorkBuddy | 上班/远程统一协调入口；PM、最少必要专家、文件/文档处理、QA、视觉验收、交付摘要；通过白名单 facade 触发受控脚本 |
| CodeBuddy | compatibility-only 本地远程执行入口；旧任务可回退，不再新增编排功能 |
| GPT + GitHub | 架构、回测、风控审查；可直接读取 GitHub Issue / TASK / PR / diff，不再默认依赖人工粘贴 diff |
| WorkBuddy memory | 本地辅助记忆，不是任务状态源 |
| Git | 安全绳和阶段 checkpoint |

---

## 2. 工作级别（L0 / L1 / L2）

详见 [`docs/workflows/work_levels.md`](workflows/work_levels.md)。

| 级别 | 入口 | TASK | Worktree | Issue |
|------|------|------|----------|-------|
| L0 | GPT/Cursor 咨询 | 否 | 否 | 否 |
| L1 Home Direct | 居家 Codex 直控 | 轻量 TASK | 必须 | 可选 |
| L2 工作站 | WorkBuddy（CodeBuddy compatibility-only） | 完整 TASK | 必须 | 必须 |

L1/L2 统一经 `scripts/ai/dispatch_task.sh`（`plan` → `approve_task.sh` → `dev` → `test` → `review` → `result`），不得裸 `codex exec` 绕过 Gate。WorkBuddy 只能通过 `scripts/ai/workbuddy_task.sh` 白名单 facade 调用既有受控脚本。详见 [`docs/workstation/ARCHITECTURE.md`](workstation/ARCHITECTURE.md)。

## 3. 标准任务流程

每个 Codex 任务按以下顺序执行：

1. 读 `AGENTS.md`、`docs/CODEX_HANDOFF.md`、`tasks/current.md` 和相关业务文档。
2. 运行 `git status --short`，确认工作区状态。
3. 先输出计划，列出允许修改文件和禁止修改文件。
4. 小步修改，避免一次跨前端、后端、数据、回测多个大域。
5. 修改后检查 diff。
6. 运行与任务相关的最小验证命令。
7. 输出修改文件、运行命令、测试命令、风险点和下一步。
8. 由用户或 Cursor 决定是否提交。

企业微信 / WorkBuddy 远程任务额外遵守：

1. WorkBuddy 优先读取 Issue / TASK / Draft PR，不创建第二状态。
2. 固定命令进入 `scripts/ai/workbuddy_task.sh`；自然语言只做 intake、QA、视觉和交付。
3. 第一轮只能 plan；用户确认 Plan 后，才允许 approve / dev / test / review / result。
4. WorkBuddy、CodeBuddy、Codex 均不自动 push、merge、release、部署或触发真实交易。
5. 详细流程见 `docs/workstation/WORKBUDDY_UNIFIED_V3.md`、`docs/workstation/REMOTE_DEVELOPMENT.md` 和 `docs/AI_WECHAT_WORKFLOW.md`。

---

## 4. 账号切换流程

切换 Codex 账号或线程前：

1. 完成当前小任务，或明确任务未完成原因。
2. 运行 `git status --short`。
3. 必要时由用户或 Cursor 创建 git checkpoint。
4. 更新 `docs/CODEX_HANDOFF.md`。
5. 更新 `tasks/current.md`。
6. 在最终回复中写清下一账号应先读哪些文件、当前风险和下一步。

新账号接手后：

1. 先读交接文档和当前任务。
2. 先总结项目理解。
3. 先列计划和准备修改文件。
4. 不直接改代码。
5. 不依赖历史聊天记忆。

---

## 5. Codex 完成任务后的固定输出

Codex 每次任务完成后必须输出：

- 修改文件。
- 为什么这么改。
- 运行命令。
- 测试命令。
- 风险点。
- 遗留问题。
- 下一步建议。

如果只改文档，也要说明是否运行了 `git diff --check` 或其他文档检查。

---

## 6. 禁止边界

禁止：

1. 写入账号、密码、token、license、API Key、CTP 密码、米筐账号、天勤账号。
2. 修改 `.env`。
3. 触碰真实数据目录：`data/raw/`、`data/parquet/`、`data/processed/`。
4. 在 V1 做自动实盘、AI 自动下单、无人值守交易。
5. 让信号扫描直接触发实盘下单。
6. 一次性大范围重写前端、后端、数据和回测。
7. 直接修改 vn.py 源码。
8. 删除旧代码、旧文档或历史数据，除非用户明确要求。
9. 通过远程机器人打印或写入 `QYWX_WEBHOOK_URL`、Bot Secret、RQData 凭证、cookie、token、license。
10. 使用 `codex exec --sandbox danger-full-access` 执行半自动工作流。

---

## 7. 外部审查流程

涉及架构、数据源、策略、回测、风控时，建议在本地验证后进行外部审查：

1. 运行 `git diff`。
2. 优先让 GPT + GitHub 直接读取 Issue、TASK、PR、CI 和 diff；无法直接读取时再人工粘贴必要片段。
3. 按 P0 / P1 / P2 整理反馈。
4. Codex 只处理明确、可验证、符合 V1 边界的问题。
5. 不允许外部审查工具直接修改仓库。

---

## 8. WorkBuddy 使用边界

WorkBuddy 可以处理：

- 需求澄清和产品边界整理。
- 阶段拆分、验收标准和 QA 清单。
- WorkBuddy 命令序列与 Codex Prompt 草稿。
- WorkBuddy facade / dispatcher / Codex 结果的交付报告。
- 读取 Issue / TASK / PR 并返回固定 WorkBuddy 命令序列。
- 调用 `scripts/ai/workbuddy_task.sh` 的白名单命令。
- 布局错位。
- 文案遮挡。
- 控制台可见前端错误。
- 图表不渲染。

WorkBuddy 不做：

- 架构重构。
- 后端业务逻辑。
- 数据源切换。
- 策略或回测逻辑修改。
- 实盘相关功能。
- 直接修改仓库业务代码。
- 维护第二套任务状态。
- 自由 shell、自动 retry 或模糊审批。
- 自动 push、merge、release 或部署。

## 9. CodeBuddy 使用边界

CodeBuddy 是本地远程执行入口，不是独立产品决策者。

CodeBuddy 可以：

- 读取仓库文件。
- 运行只读状态检查。
- 在 `docs/tasks/` 或 `.ai/tasks/` 保存本地任务文件。
- 调用 `scripts/ai/dispatch_task.sh` 执行各 stage。
- 在用户批准后调用 `scripts/ai/approve_task.sh`。

CodeBuddy 不做：

- 未经确认直接开发。
- 直接在 `main` 上修改代码。
- 自动推送、合并、发布或部署。
- 输出或保存密钥、token、webhook、账号、cookie、license。
