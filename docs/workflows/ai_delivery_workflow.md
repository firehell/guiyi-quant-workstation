# AI 半自动交付流程 SOP（Lean V1）

适用链路：WorkBuddy 生成完整 Task Bundle，CodeBuddy 受控调用 Codex CLI，用户负责 Plan 审批与最终合并决策。

## 0. 铁律

> **工作级别**：L2 为本 SOP 的默认 canonical 流程；L1 居家直控见 [`work_levels.md`](work_levels.md)，仅放宽 Issue Gate，不放宽 Plan/Approve/Dev/Test。L0 不要求 TASK。

1. 先 Plan，后 Dev；Plan 只读，Dev 仅 `workspace-write`。
2. 禁止 `danger-full-access` 和 `--dangerously-bypass-approvals-and-sandbox`。
3. 不自动 push、merge、release、deploy、关闭 Issue 或交易。
4. 不读取或修改 `.env`、凭证、token、webhook；不删除数据。
5. 任一 Gate 失败立即停止并保留可审查产物。

## 1. Lean Task Bundle

WorkBuddy 一次生成 `docs/tasks/<TASK_ID>.md`，必须同时包含目标、范围、不做事项、§7 允许/禁止路径、§15 Plan Prompt、§16 Dev Prompt、§18 测试命令和 §19 验收标准。后续不再拆分搬运多个 Prompt。

运行路径统一为：

```text
TASK                 docs/tasks/<TASK_ID>.md（fallback .ai/tasks/）
Plan/Result          .ai/results/<TASK_ID>/
Approval             .ai/approvals/<TASK_ID>.json
Logs                 .ai/logs/
```

## 2. 流程与人工 Gate

```text
IDEA -> REQUIREMENT_READY
  -> PLAN (codex exec -s read-only)
  -> PLAN_READY
  -> 用户 APPROVE + Plan SHA256 审批凭证
  -> APPROVED_DEV
  -> DEV (codex exec -s workspace-write)
  -> CODING -> TESTING
  -> RESULT -> DELIVERY_READY
  -> 用户 review / 手工 merge -> CLOSED
```

### A. TASK 与 Issue Gate

- TASK 元信息必须包含 `Work Level`（L1/L2，默认 L2）、专用 `Branch` 和 `Worktree`（L1/L2 必填）。
- **L2**：`GitHub Issue | #N` 必填；缺 Issue 时不得进入 Plan 或 Dev。
- **L1**：Issue 可选；缺 Issue 时 Plan/Dev 继续，Result Bundle 标记 `issue_gate=skipped_l1`。
- TASK 文件是本地标准源，Issue 是远程留痕源（L2）。
- L1/L2 正式开发前执行 `scripts/ai/init_task_worktree.sh --task <TASK_ID>`，在独立 worktree 中开发。

### B. PLAN

推荐经统一调度器：

```bash
scripts/ai/dispatch_task.sh <TASK_ID> plan --json
```

等价直调（由 dispatch 内部调用，一般不必手敲）：

```bash
scripts/ai/codex_plan.sh --task <TASK_ID>
```

脚本读取 `AGENTS.md`、`CODEBUDDY.md`、完整 TASK 和当前 Git 状态，通过 `codex exec -s read-only "<prompt>"` 生成 `.ai/results/<TASK_ID>/plan_result.md`，并检查执行前后 tracked diff 不变。

### C. APPROVE

用户审阅 Plan 后执行：

```bash
scripts/ai/approve_task.sh --task <TASK_ID>
```

审批 JSON 绑定 TASK_ID、Issue、Plan SHA256、批准分支、时间和审批时 pre-existing changes。Plan 内容变化后旧审批自动失效。`main/master` 或分支不匹配时拒绝批准。

### D. DEV 与测试

```bash
scripts/ai/dispatch_task.sh <TASK_ID> dev --json
scripts/ai/dispatch_task.sh <TASK_ID> test --json
scripts/ai/dispatch_task.sh <TASK_ID> review --json
```

Dev 阶段内部调用 `codex_dev.sh`，必须先验证 Issue、审批 JSON、Plan SHA256 和分支，通过后才调用 `codex exec -s workspace-write "<prompt>"`。Prompt 包含完整 TASK、Plan、审批记录，以及 TASK §7、§16、§18、§19。Dev 前后执行范围检查。

Test 阶段内部调用 `run_tests.sh`：

测试脚本读取 `### 18.0 自动化测试命令` 下第一个 fenced `bash` 块，逐条执行并记录退出码；不使用 `eval`。危险命令、网络命令、重定向和 shell 组合符被拒绝。TASK 未声明命令时 fallback 为 `git diff --check` 与 `bash -n scripts/ai/*.sh`。

### E. RESULT 与交付

```bash
scripts/ai/dispatch_task.sh <TASK_ID> result --json
scripts/ai/make_delivery_summary.sh --task <TASK_ID>
```

Result 阶段内部调用 `collect_result.sh`。

### F. 中断与控制（V1.5）

```bash
scripts/ai/dispatch_task.sh <TASK_ID> pause
scripts/ai/dispatch_task.sh <TASK_ID> resume
scripts/ai/dispatch_task.sh <TASK_ID> cancel
scripts/ai/dispatch_task.sh <TASK_ID> status --json
```

- `pause`：若本 TASK 持有 writer lock 则释放；写 `pause_record.json`；Status → `PAUSED`。
- `resume`：从 `pause_record.json` 恢复 `previous_status`；校验审批仍有效；不自动 re-acquire lock。
- `cancel`：释放本 TASK lock（若持有）；写 `cancel_record.json`；Status → `CANCELLED`。
- `status`：只读输出 Status、审批、pause/cancel 记录、stage logs。

`CANCELLED` 阻断 `dev|fix|test|result`；`PAUSED` 阻断 `dev|fix`。重复 `pause`/`cancel` 返回 exit 5。

### G. Issue 外部操作（默认 dry-run）

```bash
scripts/ai/update_issue_status.sh <TASK_ID> <STATUS> --dry-run
scripts/ai/update_issue_status.sh <TASK_ID> <STATUS> --confirm-issue-ops
scripts/ai/comment_issue_result.sh <TASK_ID> plan --confirm-issue-ops
```

无 `--confirm-issue-ops` 时打印计划操作并 exit 6；`--dry-run` 仅预览。

Result Bundle 区分审批时的 pre-existing changes 与本次 task changes，记录测试、范围、敏感信息、审批、Plan 和 Issue Gate。摘要从 Bundle 动态生成，不硬编码任务结论。所有输出需脱敏，最终 merge/deploy 始终由用户决定。

结构化结果目录固定为 `.ai/results/<TASK_ID>/`，至少包含：

- `route.json`
- `review.md`（执行 review stage 后生成）
- `result_bundle.json`
- `execution.json`
- `execution_summary.md`
- `changed_files.txt`
- `diff_stat.txt`

`execution.json` 是机器可读执行摘要；`result_bundle.json` 保持向后兼容，继续作为 `make_delivery_summary.sh` 的默认输入。测试失败、forbidden path、敏感信息、review 高优先级问题或 `external_review_required=true` 时，不得建议进入 `CLOSED`。

## 3. 失败处理

任何命令非零、审批失效、Plan 变化、分支错误、越界改动或敏感信息风险均进入 `FAILED`；不得自动 reset、revert 或删除用户文件。用户决定修复、REPLAN 或取消后再继续。

## 4. 七命令协议

固定协议为 `TASK / PLAN / APPROVE / DEV / STATUS / CANCEL / RESULT`，详细前置条件与产物见 [`CODEBUDDY.md`](../../CODEBUDDY.md)。`STATUS` 只读，`CANCEL` 只停止后续动作，`RESULT` 只返回脱敏摘要。
