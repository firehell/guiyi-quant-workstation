# AI 交付流程（V1.1）

> 归一量化工作站 V1.1 主流程：**半自动、有状态、有权限边界的个人开发工作站**。

企微入口专项说明见 [`docs/AI_WECHAT_WORKFLOW.md`](../AI_WECHAT_WORKFLOW.md)。

---

## 目标

把「你 + WorkBuddy + CodeBuddy + Codex」变成标准流水线：

- WorkBuddy：任务单、交付报告（不碰本地代码）
- CodeBuddy：本地执行调度（plan / dev / test / collect）
- Codex CLI：受控开发执行器
- 你：审批、验收、merge、部署确认

---

## 角色分工

| 角色 | 职责 | 不做 |
|------|------|------|
| 你 | 提想法、审核任务单、确认 plan、review、commit/merge | — |
| WorkBuddy | 生成任务单、生成交付报告 | 本地执行、改代码、merge/deploy |
| CodeBuddy | 读 TASK、plan、dev、测试、收集结果 | 产品决策、push/merge/deploy |
| Codex CLI | 只读 plan 或 workspace-write 开发 | 绕过脚本、自动发布 |
| Cursor | 人工 diff review、小修 | — |

---

## 标准流水线（10 步）

```text
1. 你提出想法
   ↓
2. WorkBuddy 生成任务单（状态 → REQUIREMENT_READY）
   ↓
3. 你审核任务单
   ↓
4. CodeBuddy 执行只读 plan（状态 → PLAN_READY）
   ↓
5. 你确认 plan（状态 → APPROVED_DEV）
   ↓
6. CodeBuddy 调 Codex 开发（状态 → CODING）
   ↓
7. CodeBuddy 运行测试和结果收集（状态 → TESTING → DELIVERY_READY）
   ↓
8. WorkBuddy 生成交付报告
   ↓
9. 你人工 review
   ↓
10. 你决定 commit / push / merge / 部署（状态 → CLOSED）
```

---

## 每步详细说明

### Step 1–3：需求与任务单

- WorkBuddy 使用 [`docs/tasks/TASK_TEMPLATE.md`](../tasks/TASK_TEMPLATE.md) 或 guiyi-delivery-team 命令 A
- 输出保存到 `.ai/tasks/<TASK_ID>.md` 或使用 `docs/tasks/examples/` 中的示例
- 用户审核：范围、不做事项、数据/配置影响、风险

### Step 4：只读 Plan（Gate 1）

```bash
TASK_ID=<TASK_ID> scripts/ai/codex_plan.sh .ai/tasks/<TASK_ID>.md
# 或
TASK_ID=<TASK_ID> scripts/ai/codex_plan.sh docs/tasks/examples/<TASK>.md
```

- 输出：`.ai/results/<TASK_ID>/codex_plan_<timestamp>.md`
- 状态：`REQUIREMENT_READY` → `PLAN_READY`

### Step 5：用户确认（Gate 2）

- 必须用自然语言明确批准
- 状态：`PLAN_READY` → `APPROVED_DEV`

### Step 6：开发（Gate 3）

```bash
scripts/ai/codex_dev.sh .ai/tasks/<TASK_ID>.md codex/<short-name>
```

- 要求：干净 `main`、专用分支 `codex/*` 或 `feature/*`
- 输出：`.ai/results/<TASK_ID>/codex_dev_<timestamp>.md`
- 状态：`APPROVED_DEV` → `CODING` → `TESTING`

### Step 7：测试与结果收集

```bash
TASK_ID=<TASK_ID> scripts/ai/run_tests.sh
scripts/ai/collect_result.sh <TASK_ID> <task_file>
scripts/ai/make_delivery_summary.sh <TASK_ID> <task_file>
```

- 测试日志：`.ai/logs/tests_<timestamp>.log`
- 执行摘要：`.ai/results/<TASK_ID>/execution_summary.md`
- 交付草稿：`.ai/results/<TASK_ID>/delivery_report_draft.md`
- 状态：`TESTING` → `DELIVERY_READY`

### Step 8：交付报告

- WorkBuddy 命令 B（[`prompts/workbuddy-delivery-report.md`](../../prompts/workbuddy-delivery-report.md)）
- 输入：`delivery_report_draft.md` + [`docs/delivery_checklist.md`](../delivery_checklist.md)

### Step 9–10：人工 review 与关闭

- 用户或 Cursor 审查 diff
- 用户决定是否 commit、push、merge
- 状态：`DELIVERY_READY` → `CLOSED`
- **Gate 4**：全流程不自动 push / merge / deploy

---

## 文件路径约定

| 路径 | 用途 | 版本库 |
|------|------|--------|
| `docs/tasks/TASK_TEMPLATE.md` | 标准任务单模板 | 是 |
| `docs/tasks/examples/` | 示例任务单 | 是 |
| `.ai/tasks/<TASK_ID>.md` | 运行时任务单 | 否（gitignore） |
| `.ai/results/<TASK_ID>/` | plan、dev、summary、draft | 否 |
| `.ai/logs/` | 脚本执行日志 | 否 |

---

## 脚本清单

| 脚本 | 模式 | 说明 |
|------|------|------|
| `scripts/ai/codex_plan.sh` | 只读 | Gate 1，不修改代码 |
| `scripts/ai/codex_dev.sh` | workspace-write | Gate 3，不 push/merge |
| `scripts/ai/run_tests.sh` | 只读/测试 | 统一测试入口 |
| `scripts/ai/collect_result.sh` | 只读 | 收集 diff、status、summary |
| `scripts/ai/make_delivery_summary.sh` | 只读 | 生成交付报告草稿 |

CodeBuddy **必须**通过上述脚本调用 Codex，禁止裸跑 `codex exec` 绕过 sandbox。

---

## V1.1 验收标准

1. 新任务可以标准化生成 TASK（`TASK_TEMPLATE.md`）
2. TASK 有明确状态（`status_machine.md`）
3. CodeBuddy 能按 TASK 执行 plan
4. Codex 开发前必须经过人工确认
5. 开发后能自动收集 diff、测试、风险点（`collect_result.sh`）
6. WorkBuddy 能基于 `delivery_report_draft.md` 生成交付报告
7. 全流程不 push、不 merge、不部署、不动密钥、不删数据

---

## V1.1 明确不做

- n8n / webhook / GitHub 自动触发开发
- WorkBuddy 自动下发开发命令
- CodeBuddy daemon 公网暴露
- 全自动 merge / deploy
- GitHub Issue 留痕（V1.2）
- 自动调度 `dispatch_task.sh`（V1.4）

---

## 相关文档

- 状态机：[`status_machine.md`](status_machine.md)
- WorkBuddy 角色：[`workbuddy_role.md`](workbuddy_role.md)
- CodeBuddy：[`CODEBUDDY.md`](../../CODEBUDDY.md)
- 交付检查清单：[`docs/delivery_checklist.md`](../delivery_checklist.md)
