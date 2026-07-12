# 居家开发流程（Home Development）

更新时间：2026-07-12

> 配套：[`work_levels.md`](../workflows/work_levels.md)、[`ARCHITECTURE.md`](ARCHITECTURE.md)、[`WRITER_LOCK_HANDOFF.md`](WRITER_LOCK_HANDOFF.md)

居家是 **L0/L1 默认入口**。远程 L2 见 [`REMOTE_DEVELOPMENT.md`](REMOTE_DEVELOPMENT.md)。两入口共享 TASK 协议与 `dispatch_task.sh`。

## 1. 角色分工

| 工具 | 居家职责 |
|------|----------|
| GPT / Work | 需求设计、方案讨论、TASK 落盘 |
| Codex | L1 默认实施 Agent（经 dispatcher） |
| Cursor | L0 只读分析；L1 人工小修、diff 审查、Git 管理 |
| Git | checkpoint 与验收安全绳 |

WorkBuddy 在居家 **可选**；正式交付报告通常 L2 远程场景使用。

## 2. 工作级别

### L0：咨询与探索

- 不要求 TASK，不要求 worktree。
- 允许只读分析、讨论、临时实验。
- **禁止**形成未登记的正式业务修改。

### L1：居家快速开发

- **必须有 TASK**（模板：[`TASK_TEMPLATE_L1.md`](../tasks/TASK_TEMPLATE_L1.md)）。
- **必须**独立 worktree + Plan / Approve / Dev / Test / Result。
- GitHub Issue **可选**。
- **默认 Codex** 经 `dispatch_task.sh` 实施；Cursor 用于人工接管或小修。

### L2（居家也可执行）

- 与远程相同 Gate：完整 TASK + Issue + 交付报告。
- 仍使用同一 dispatcher；Plan Gate 不可跳过。

## 3. 标准命令链

```bash
# 1. 创建 worktree 并进入
scripts/ai/init_task_worktree.sh --task <TASK_ID>
cd "$(grep -m1 '| Worktree |' docs/tasks/<TASK_ID>.md | awk -F'|' '{print $3}' | xargs)"

# 2. 只读 Plan
scripts/ai/dispatch_task.sh <TASK_ID> plan --json

# 3. 用户审阅 Plan 后批准
scripts/ai/approve_task.sh --task <TASK_ID>

# 4. 开发 → 测试 → 审查 → 结果
scripts/ai/dispatch_task.sh <TASK_ID> dev --json
scripts/ai/dispatch_task.sh <TASK_ID> test --json
scripts/ai/dispatch_task.sh <TASK_ID> review --json
scripts/ai/dispatch_task.sh <TASK_ID> result --json
```

任一阶段失败即停止，不自动 retry。

## 4. Cursor 人工接管

Cursor 与 Codex **不得同时写同一 worktree**。人工编辑前必须获取 writer lock：

```bash
scripts/ai/writer_lock.sh status --worktree "$PWD"

scripts/ai/writer_lock.sh acquire \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --branch "$(git branch --show-current)" \
  --writer cursor \
  --stage manual-edit
```

完成后释放：

```bash
scripts/ai/writer_lock.sh release \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --writer cursor
```

详见 [`WRITER_LOCK_HANDOFF.md`](WRITER_LOCK_HANDOFF.md)。

## 5. 收工检查

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
| 任务未完成 | WIP commit；TASK 状态 `CODING`；记录 next_action |
| 开发完成待验收 | 测试 + Result Bundle；状态 `DELIVERY_READY`；push feature 分支但不 merge |
| 实验不保留 | 在独立 worktree 中确认后 `remove_task_worktree.sh --force` |

## 6. 硬规则摘要

1. 正式代码修改必须有 TASK_ID。
2. L1/L2 必须在 TASK 指定 worktree 开发，不在 main/master 直接改。
3. 不 push / merge / deploy（由用户决定）。
4. 不静默 fallback 环境或数据源（见 [`ENVIRONMENT_FAIL_CLOSED.md`](ENVIRONMENT_FAIL_CLOSED.md)）。
5. 修改范围服从 TASK §7；必须运行 §18.0 测试。
6. 所有入口写入 `.ai/results/<TASK_ID>/`。

## 7. 相关文档

- Agent 规则：[`AGENTS.md`](../../AGENTS.md) §8.1
- 模型路由：[`ROUTING_POLICY.md`](ROUTING_POLICY.md)
- 工作级别详解：[`work_levels.md`](../workflows/work_levels.md)
