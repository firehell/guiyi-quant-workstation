# V1.4 调度器故障处理手册

> 配套：`dispatch_task.sh` + `writer_lock.sh` + `lib/writer_lock.py` + approval / worktree gate
> 版本：V1.5 (2026-07-12)

---

## 1. 故障场景总览

| # | 场景 | 严重度 | 自动恢复 | 需人工 |
|---|------|--------|----------|--------|
| F01 | writer lock stale（进程异常退出） | P1 | ❌ 否 | ✅ 是 |
| F02 | 状态写入与实际执行不一致 | P1 | ❌ 否 | ✅ 是 |
| F03 | Plan 变更致审批失效 | P2 | ❌ 否 | ✅ 是 |
| F04 | 双输出路径遗留产物 | P2 | ✅ 是 | ❌ 否 |
| F05 | 并发终端锁冲突 | P2 | ❌ 否 | ✅ 是 |
| F06 | cancel 后误操作 | P1 | ❌ 否 | ✅ 是 |
| F07 | codex_dev.sh / run_tests.sh 执行失败 | P1 | ❌ 否 | ✅ 是 |
| F08 | TASK 文件被外部修改 | P2 | ❌ 否 | ✅ 是 |
| F09 | GitHub Issue 操作失败 | P2 | ❌ 否 | ✅ 是 |
| F10 | pause_record.json 丢失 | P2 | ❌ 否 | ✅ 是 |

---

## 2. 各故障详细处理

### F01：writer lock stale

**现象**：`.ai/locks/worktrees/<hash>.json` 存在，但对应 writer 已不再有效。

**检测**：`writer_lock.sh status` 读取结构化锁，检查 `pid`、`hostname` 和 `started_at`：

- 同一 hostname：PID 不存在才视为 stale。
- 不同 hostname：锁超过 `GUIYI_WRITER_LOCK_STALE_SECONDS` 阈值才视为 stale。
- stale 锁不会被 dispatch 自动删除。

**手动处理**：
```bash
# 查看锁状态
scripts/ai/writer_lock.sh status --worktree "$PWD"

# 显式清理 stale 锁，并写入 .ai/locks/audit.jsonl
scripts/ai/writer_lock.sh break-stale \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --writer cursor
```

**预防**：dispatch 在成功、失败、`INT`、`TERM`、`HUP`、`QUIT` 等常见退出路径尽力释放自己持有的锁；不得释放其他任务或其他 writer 的锁。

---

### F02：状态写入与实际执行不一致

**现象**：TASK 文件元信息中的 Status 与实际产物不一致。例如：
- Status = CODING，但 dev.log 不存在（dev 未实际执行）
- Status = TESTING，但无 test.log（测试未实际执行）

**原因**：
- dispatch 写状态后，被调脚本失败但 dispatch 未回滚状态
- 外部进程直接修改了 TASK 文件的 Status 字段

**手动处理**：
1. 检查产物目录确认实际执行状态：
   ```bash
   ls -la .ai/results/<TASK_ID>/    # 查看产物文件
   ```
2. 根据实际产物决定正确状态
3. 手动修正 TASK 文件元信息中的 Status 字段：
   ```bash
   # 用 awk 更新 Status 行
   awk -i inplace '/^| Status \|/{gsub(/CODING/, "FAILED")}1' <task_file>
   ```
4. 如果 dev/test 已失败，将状态设为 FAILED，然后走 REPLAN 路径

**预防**：dispatch 在脚本调用失败时自动将状态设为 FAILED。V1.5 `workstation_doctor.sh` 含 `f02_status_artifact` 自动扫描。

---

### F03：Plan 变更致审批失效

**现象**：dev 时 Gate G6 报 `"plan hash 与审批不匹配"`。

**原因**：plan_result.md 被 Codex re-plan 或人工修改后，SHA256 hash 与 approval.json 中绑定的 hash 不一致。

**处理**：
1. 确认 plan 变更是否有意为之：
   ```bash
   # 查看审批记录中的 hash
   cat .ai/approvals/<TASK_ID>/approval.json | grep plan_hash
   # 计算当前 plan hash
   shasum -a 256 .ai/results/<TASK_ID>/plan_result.md
   ```
2. 如果有意变更 → 重新执行 `approve-plan`（写新审批记录）
3. 如果无意变更 → 恢复 plan_result.md 或重新 `plan --force`

**预防**：plan 默认幂等拒绝（需 --force 覆盖），减少意外变更。

---

### F04：双输出路径遗留产物（历史）

**现象**：早期 V1.4 产物可能同时存在于 `scripts/ai/.out/<TASK_ID>/` 与 `.ai/results/<TASK_ID>/`。

**V1.5 口径**：统一使用 `.ai/results/<TASK_ID>/`；`.out/` 仅历史兼容，新流程不再写入。

---

### F05：并发终端锁冲突

**现象**：`dispatch_task TASK-A dev` 在终端 1 执行时，终端 2 对同一 worktree 执行 `TASK-B dev/fix` 被拒绝，报 `"Writer lock is held..."`。

**处理**：
1. 检查终端 1 的 TASK-A 是否仍在执行：
   ```bash
   scripts/ai/writer_lock.sh status --worktree "$PWD"
   ```
2. 如果 TASK-A 仍在执行 → 等待完成或暂停
3. 如果 TASK-A 已完成但锁未释放（F01 stale）→ 人工确认后执行 `break-stale`

**预防**：worktree 级独占 writer lock 确保 Cursor、Codex、CodeBuddy 不会在同一 worktree 同时写入。

---

### F06：cancel 后误操作

**现象**：TASK 已 cancel（状态=CANCELLED），但仍尝试 `dev` 或 `test`。

**dispatch 处理**（V1.5）：`validate_static_gates` 拒绝 `dev|fix|test|result`，报 `"已取消，需 resume 或 replan"`。

**恢复路径**：
- **resume**：`dispatch_task <TASK_ID> resume`（仅 PAUSED 可用）
- **replan**：走 REPLAN → PLAN_READY → approve → dev 路径

**注意**：cancel 不删除已有产物。彻底重置需人工清理 `.ai/results/<TASK_ID>/` 后重新 plan。

---

### F07：codex_dev.sh / run_tests.sh 执行失败

**现象**：被调脚本退出非 0。

**dispatch 处理**：
- dev 失败 → 自动设状态为 FAILED + 释放锁
- test 失败 → 自动设状态为 FAILED + 释放锁

**恢复路径**：
1. 检查失败日志：
   ```bash
   cat .ai/results/<TASK_ID>/dev.log     # dev 失败
   cat .ai/results/<TASK_ID>/test.log    # test 失败
   ```
2. 修复问题后走 REPLAN：
   ```bash
   dispatch_task <TASK_ID> cancel    # 如果需重新开始
   dispatch_task <TASK_ID> plan --force   # 重新 plan
   dispatch_task <TASK_ID> approve-plan  # 重新审批
   dispatch_task <TASK_ID> dev           # 重新开发
   ```

**P0 红线级**（自动交易/误发/密钥泄露）：立即止损 + 安全专家一票否决，不自动恢复。

---

### F08：TASK 文件被外部修改

**现象**：TASK 文件的元信息（Status、Issue、Branch）被外部编辑器或 Git 操作修改，导致 Gate 检测异常。

**处理**：
1. 确认修改来源（人工编辑 / Codex / Git merge）
2. 恢复正确值或重新 validate：
   ```bash
   dispatch_task <TASK_ID> validate   # 重新检查合法性
   ```
3. 如果 Issue 或 Branch 值被破坏 → 手动修正后重新 validate

**预防**：dispatch 只修改 Status 和 Updated At 字段，不修改其他元信息。外部应避免直接修改 TASK 文件。

---

### F09：GitHub Issue 操作失败

**现象**：`update_issue_status.sh` 或 `comment_issue_result.sh` 执行失败（gh CLI 不可用 / 认证失效 / 网络问题）。

**dispatch 处理**：默认 dry-run（不实际执行 gh），仅打印拟操作。失败不影响核心调度流程。

**显式执行失败处理**（`--confirm-issue-ops`）：
1. 检查 gh CLI 认证：
   ```bash
   gh auth status
   ```
2. 重认证后重试：
   ```bash
   dispatch_task <TASK_ID> status --confirm-issue-ops
   ```
3. 如果持续失败 → 跳过 Issue 同步，后续手动补评论

**预防**：dry-run 默认确保核心流程不受 gh 依赖影响。

---

### F10：pause_record.json 丢失

**现象**：`resume` 时找不到 `.ai/results/<TASK_ID>/pause_record.json`，无法确定恢复到哪个状态。

**处理**：
1. 查看 TASK 文件元信息中的 Status 字段（V1.4 pause 时同时写入 PAUSED）
2. 查看审批记录确认审批是否有效
3. 如果无法确定原状态 → 从 APPROVED_DEV 重新开始（最安全的回退点）

**预防**：pause 时写 `pause_record.json` + TASK Status = PAUSED；`dispatch_task <TASK_ID> pause|resume|cancel|status` 为 V1.5 正式入口。

---

## 3. 快速诊断命令

```bash
# 工作站聚合自检（含 F02）
make workstation-doctor

# 控制面状态
scripts/ai/dispatch_task.sh <TASK_ID> status --json
scripts/ai/writer_lock.sh status --worktree "$PWD"

# Cursor 人工接管写入前获取锁
scripts/ai/writer_lock.sh acquire \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --branch "$(git branch --show-current)" \
  --writer cursor \
  --stage manual-edit

# Cursor 完成后释放自己持有的锁
scripts/ai/writer_lock.sh release \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --writer cursor

# 查看审批记录
cat .ai/approvals/<TASK_ID>/approval.json

# 查看 plan hash
shasum -a 256 .ai/results/<TASK_ID>/plan_result.md

# 查看产物目录
ls -la .ai/results/<TASK_ID>/

# 验证 TASK 合法性
dispatch_task <TASK_ID> validate

# 清理 stale 锁（需要先人工确认）
scripts/ai/writer_lock.sh break-stale \
  --task-id <TASK_ID> \
  --worktree "$PWD" \
  --writer cursor
```

---

## 4. P0 红线级故障处理

以下故障需要立即止损 + 安全专家一票否决：

| P0 故障 | 处理 |
|---------|------|
| 自动交易被触发 | 立即 stop service + 人工确认无在途订单 |
| 企业微信误发真实消息 | 立即撤回 + dry-run 回归 |
| .env / webhook / token 泄露到产物文件 | 立即删除产物 + 重新脱敏 + audit log |
| active 数据被污染 | 立即标记 quality_status=failed + 数据专家审查 |

**P0 处理原则**：
- 不自动恢复，不自动回滚
- 安全专家一票否决
- 需完整事后复盘报告
- 相关 dispatch 任务强制 FAILED

---

## 5. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| V1.5 | 2026-07-12 | 切换为 `.ai/locks` worktree writer lock，stale 清理由显式 `break-stale` 完成并写审计 |
| V1.4 | 2026-07-10 | 初版，配套 dispatch_task.sh |
