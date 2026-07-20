# 工作级别（L0 / L1 / L2）

> 配套：[`ai_delivery_workflow.md`](ai_delivery_workflow.md)、[`status_machine.md`](status_machine.md)、[`worktree_registry.md`](worktree_registry.md)
> 原则：**入口可以不同，事实源必须统一。**

## 1. 核心原则

```text
一个 TASK
= 一个 feature 分支
= 一个独立 worktree（L1/L2）
= 一个 .ai/results/<TASK_ID>/
```

- 居家 Cursor/Codex、办公室 WorkBuddy 只是不同**操作入口**；CodeBuddy 仅保留 compatibility-only 回退。
- 工作站不是某一个工具，而是一套共享的**任务协议、Git 规则、审批 Gate 和结果记录**。
- 主仓库 worktree 仅用于只读验收、文档同步；**新 L1/L2 正式开发必须在独立 worktree 中进行**。

## 2. 三级定义

### L0：咨询与探索

| 维度 | 要求 |
|------|------|
| 工具 | GPT / Codex / Cursor |
| TASK | 不要求 |
| Worktree | 不要求 |
| 允许 | 只读、分析、讨论、临时实验 |
| 禁止 | 形成未登记的正式业务修改 |

适用：阅读代码、解释实现、分析报错、讨论方案、不修改仓库的实验。

### L1：居家快速开发（Home Direct Mode）

| 维度 | 要求 |
|------|------|
| 工具 | GPT + Codex（可绕过 WorkBuddy） |
| TASK | 必须有，可用 [`TASK_TEMPLATE_L1.md`](../tasks/TASK_TEMPLATE_L1.md) |
| Worktree | **必须**（默认根目录 `../guiyi-parallel/`） |
| Issue | 可选；缺则跳过，不阻断 Plan/Dev |
| Plan / Approve / Dev / Test | **必须** |
| Result Bundle | **必须**（`.ai/results/<TASK_ID>/`） |
| 交付报告 | 可选 |

推荐链路：

```text
GPT 讨论需求 → 写入 TASK → init_task_worktree.sh
→ codex_plan.sh → approve_task.sh → codex_dev.sh
→ run_tests.sh → collect_result.sh → handoff_summary.sh
→ 人工验收
```

### L2：正式工作站交付

| 维度 | 要求 |
|------|------|
| 工具 | WorkBuddy + dispatcher + Codex（CodeBuddy compatibility-only） |
| TASK | 完整 Lean Task Bundle（[`TASK_TEMPLATE.md`](../tasks/TASK_TEMPLATE.md)） |
| Worktree | **必须** |
| Issue | **必须 #N** |
| Plan / Approve / Dev / Test | **必须** |
| Result Bundle | **必须** |
| 交付报告 | WorkBuddy 正式报告 |
| 合并 / 部署 | 人工确认 |

默认链路见 [`ai_delivery_workflow.md`](ai_delivery_workflow.md)。

## 3. Gate 矩阵

| Gate | L0 | L1 | L2 |
|------|----|----|-----|
| TASK 文件 | 否 | 是 | 是（完整） |
| Worktree 隔离 | 否 | 是 | 是 |
| GitHub Issue | 否 | 可选 | 必须 |
| Plan 只读 | 否 | 是 | 是 |
| 审批凭证 | 否 | 是 | 是 |
| Dev workspace-write | 否 | 是 | 是 |
| 测试 | 否 | 是 | 是 |
| Result Bundle | 否 | 是 | 是 |
| Issue 状态同步 | 否 | 可选 | 是 |

## 4. 升级规则

```text
L0 可升级为 L1 或 L2
L1 可升级为 L2（补 Issue + 完整 TASK 章节）

已修改正式代码后，不得继续当作 L0。
```

升级 L1→L2：

```bash
scripts/ai/create_issue_from_task.sh docs/tasks/<TASK_ID>.md
scripts/ai/link_task_issue.sh <TASK_ID> <ISSUE_NUMBER>
scripts/ai/upgrade_task_level.sh --task <TASK_ID> --to L2
```

## 5. Worktree 命令

默认根目录：`${GUIYI_WORKTREE_ROOT:-<repo>/../guiyi-parallel}`

```bash
# 创建 TASK 专用 worktree + 分支
scripts/ai/init_task_worktree.sh --task <TASK_ID>

# 列出所有 worktree 与 TASK 映射
scripts/ai/list_worktrees.sh

# 居家收工摘要
scripts/ai/handoff_summary.sh --task <TASK_ID>

# 实验完成后安全删除
scripts/ai/remove_task_worktree.sh --task <TASK_ID> [--force]
```

## 6. 居家收工检查

每次居家开发结束前：

```bash
git branch --show-current
git status --short
git diff --stat
git log -1 --oneline
scripts/ai/handoff_summary.sh --task <TASK_ID>
```

| 情况 | 处理 |
|------|------|
| 任务未完成 | WIP commit + push feature 分支；TASK 状态 `CODING`；记录 next_action |
| 开发完成待验收 | 测试 + Result Bundle；状态 `DELIVERY_READY`；push 但不 merge |
| 实验不保留 | 在独立 worktree 中确认后 `remove_task_worktree.sh --force` |

## 7. WorkBuddy 使用边界

**建议使用 WorkBuddy**：视觉方案、多角色评审、标准交付报告、远程交接、多 worktree 协调、正式合并前。

**不必使用 WorkBuddy**：查 Bug、局部修复、小测试、技术讨论、本人可控的单一 L1 修改。

## 8. 五条纪律

1. 任何正式代码修改必须有 TASK_ID。
2. 一个 TASK 只对应一个分支和一个 worktree（L1/L2）。
3. 正式开发仍经过 Plan、审批、Dev、测试。
4. 任何入口都写入同一个 `.ai/results/<TASK_ID>/`。
5. 换场景前必须提交或明确记录工作区状态。

## 9. Writer Lock 串行交接

同一 worktree 同一时间只允许一个 writer。`dispatch_task.sh dev/fix` 会自动获取 `codex` writer lock；Cursor 人工接管写入前必须显式获取 `cursor` writer lock。

```bash
# 查看当前 worktree 是否已有 writer
scripts/ai/writer_lock.sh status --worktree "$PWD"

# Cursor 人工接管
scripts/ai/writer_lock.sh acquire \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --branch "$(git branch --show-current)" \
  --writer cursor \
  --stage manual-edit

# Cursor 完成后释放
scripts/ai/writer_lock.sh release \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --writer cursor
```

Codex / 兼容远程入口串行交接示例：

```bash
scripts/ai/writer_lock.sh status --worktree "$PWD"
scripts/ai/dispatch_task.sh <TASK_ID> plan --json
scripts/ai/approve_task.sh --task <TASK_ID>
scripts/ai/dispatch_task.sh <TASK_ID> dev --json
scripts/ai/writer_lock.sh status --worktree "$PWD"
```

如果发现 stale lock，不得直接删除 `.ai/locks/` 文件；必须先确认 PID / hostname / started_at，再执行：

```bash
scripts/ai/writer_lock.sh break-stale \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --writer cursor
```

`break-stale` 会写入 `.ai/locks/audit.jsonl`，用于事后追踪。
