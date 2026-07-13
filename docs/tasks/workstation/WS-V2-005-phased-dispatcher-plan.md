# WS-V2-005 Plan：分阶段可恢复执行器

> 状态：PLAN_READY | 风险：R1 | 前置：WS-V2-004 RESULT_READY
> 分支：codex/workstation-governance-v2 | Base: main @ d579b72a
> 本阶段：只读 Plan，不修改任何文件

---

## 0. 任务概览

| 字段 | 值 |
|------|-----|
| **Task ID** | WS-V2-005 |
| **Epic** | WORKSTATION-GOVERNANCE-V2 |
| **Risk Level** | R1 |
| **Approval Scope** | plan, code |
| **Depends On** | WS-V2-004 |
| **Author** | WorkBuddy (PM) |
| **Work Level** | L1 |
| **Worktree** | /Volumes/扩展盘/guiyi-parallel/workstation-governance-v2 |
| **Branch** | codex/workstation-governance-v2 |
| **Plan SHA** | `f6d2b50bd87505fae8b263656f9e464e178eb1ca7f81933d882a163ad180a4c5` |

---

## 1. 现状分析

### 1.1 当前 dispatch_task.sh 架构（~650 行）

```
main()
 ├─ route_task.sh → JSON payload
 ├─ validate_static_gates()    ← 状态/风险/branch/worktree 门控
 ├─ validate_production_gate() ← 生产写入门控
 ├─ stage_requires_writer_lock?
 │   └─ acquire_writer_lock / acquire_resource_locks
 ├─ resolve_child_command()
 ├─ 执行 child command
 ├─ write_route_status()       ← 写入 started_at/ended_at/exit_code
 └─ cleanup_writer_lock / cleanup_resource_locks
```

**痛点**：
- **无阶段拆分**：dev 阶段 = 获取锁 + 执行，失败后无法从中途恢复
- **无 checkpoint**：阶段失败后完全从头开始
- **dev/fix 吞噬了 dry-run 与 apply 的语义**：当前 dev 直接调用 codex_dev.sh 写代码，没有"先 dry-run 再 apply"的分离
- **无 R0-only / R3 runtime 语义**：R0 任务在 gate 层只检查 approval_scope，不区分 read-only vs write
- **缺少 audit 阶段**：没有形式化的审计/验证阶段
- **无 post-verify**：执行后没有结构化的校验步骤

### 1.2 现有可复用组件

| 组件 | 职责 | 复用方式 |
|------|------|---------|
| `dispatch_control.py` | pause/resume/cancel/status | resume 逻辑参考，新增 checkpoint |
| `approval_manager.py` | V3 approval create/verify/consume | apply 阶段消费 APPROVED_DATA_WRITE |
| `resource_lock.py` | 8 scope resource locks | dev/apply 阶段用 |
| `writer_lock.py` | worktree-scoped writer lock | dev 阶段用 |
| `route_task.py` | 路由解析 | 保持，增加 phased 字段 |
| `task_meta.py` | 任务元数据解析 | 保持 |
| `status_machine.py` | 17 状态机 | apply 阶段推进 TASK 状态 |

---

## 2. 设计方案

### 2.1 10 阶段定义

| 阶段 | 操作 | 审批 | 锁 | Sandbox | 可恢复 |
|------|------|------|-----|---------|--------|
| `prepare` | 校验 schema/依赖/env/branch/worktree | 无 | 无 | none | ✅ |
| `plan` | codex_plan.sh 生成 Plan | 无 | 无 | read-only | ✅ |
| `audit` | sec audit + threat model | 无 | 无 | read-only | ✅ |
| `dev` | codex_dev.sh 写代码 | `DEV` | writer + resource | workspace-write | ✅ |
| `dry-run` | 模拟执行（只读） | 无 | resource-lock | read-only | ✅ |
| `apply` | 执行写入操作 | `DATA_WRITE`/`RUNTIME` | resource-lock | workspace-write | ⚠️ post-verify |
| `test` | run_tests.sh | 无 | 无 | none | ✅ |
| `review` | codex_review.sh | 无 | 无 | read-only | ✅ |
| `result` | collect_result.sh | 无 | 无 | none | ✅ |
| `close` | 标记 CLOSED | `MERGE`/`DOC_DELETE` | 无 | none | — |

### 2.2 Phase 路由矩阵（按风险等级）

```
R0 (read-only only):
  prepare → plan → audit → result → close
  跳过 dev / dry-run / apply / test / review
  Gate: 任何 dev/dry-run/apply 直接 REJECTED

R1 (code dev, no write ops):
  prepare → plan → audit → dev → test → review → result → close
  跳过 dry-run / apply
  Gate: apply 需要 DATA_WRITE 审批

R2 (code dev + write ops, needs approval):
  prepare → plan → audit → dev → dry-run → (approve DATA_WRITE) → apply → test → review → result → close

R3 (code dev + runtime ops, needs approval):
  prepare → plan → audit → dev → dry-run → (approve RUNTIME) → apply → test → review → result → close
```

### 2.3 Checkpoint 文件

路径：`.ai/results/{task_id}/dispatch_checkpoint.json`

```json
{
  "schema_version": 1,
  "task_id": "WS-V2-005",
  "epic_id": "WORKSTATION-GOVERNANCE-V2",
  "branch": "codex/workstation-governance-v2",
  "commit_at_start": "d579b72a",
  "plan_hash": "abc123...",
  "worktree": "/Volumes/扩展盘/guiyi-parallel/workstation-governance-v2",
  "phases": {
    "prepare": {"status": "PASSED", "started_at": "...", "ended_at": "..."},
    "plan": {"status": "PASSED", "started_at": "...", "ended_at": "..."},
    "dev": {"status": "FAILED", "started_at": "...", "ended_at": "...", "exit_code": 1, "error": "..."}
  },
  "overall_status": "FAILED_AT_phase:dev",
  "generated_at": "..."
}
```

**恢复规则**：
- `--resume` 时：验证 branch / commit / plan_hash / worktree 与 checkpoint 一致
- 恢复从第一个 `FAILED` 或状态缺失的 phase 开始
- 不能自动跳过 FAILED — 必须先 fix 逻辑重复该 phase

### 2.4 apply 阶段的审批消费

apply 阶段需要特定审批 scope：
- `DATA_WRITE`：允许写数据（Parquet/CSV/PostgreSQL）
- `RUNTIME`：允许运行策略引擎（JM 实例）
- `EXTERNAL_SEND`：允许发外部通知

apply 执行流程：
1. verify_approval_v3(operation="DATA_WRITE" 或 "RUNTIME")
2. 如果 one_time：执行完后 consume_approval()
3. 执行 apply 命令
4. post-verify（无论成功失败）
5. 释放 resource_locks

### 2.5 dry-run 阶段的安全约束

- Sandbox = read-only
- 不允许调用任何写入命令
- 审批 consume 之前必须人工确认

### 2.6 向后兼容入口

`dispatch_task.sh` 保持现有 CLI：
```
scripts/ai/dispatch_task.sh <TASK> <STAGE>     # 旧：单阶段模式
scripts/ai/dispatch_task.sh <TASK> --phase     # 新：全阶段模式 (从 prepare 开始)
scripts/ai/dispatch_task.sh <TASK> --resume    # 新：从 checkpoint 恢复
scripts/ai/dispatch_task.sh <TASK> <PHASE>     # 新：执行单个 phase
```

内部路由：
- 如果 `--phase` 或 `--resume` → 走新分阶段执行器
- 如果旧 stage 名称（dev/fix/test/result 等）→ 走旧兼容路径（保持现有行为）

---

## 3. 交付物清单

### 3.1 新增文件（4 个）

| 文件 | 行数（估） | 说明 |
|------|-----------|------|
| `scripts/ai/lib/dispatch_phase.py` | ~450 | Phase 执行器核心库：phases/checkpoint/恢复/gate |
| `scripts/ai/_dispatch_phase_lib.sh` | ~200 | Shell glue：phase gate / 参数解析 / 调度 |
| `tests/workstation/test_dispatch_phase.py` | ~200 | 35+ 测试（相位流转 + 恢复 + 4 Demo） |
| `tests/workstation/fixtures/dispatch_*.json` | ~40×3 | 3 个 checkpoint fixtures |

### 3.2 修改文件（4 个）

| 文件 | 变化 | 说明 |
|------|------|------|
| `scripts/ai/dispatch_task.sh` | +150/-30 | 增加 --phase / --resume 入口，新旧路由 |
| `scripts/ai/lib/route_task.py` | +15/-3 | STAGES 增加新阶段，payload 增加 phased 字段 |
| `scripts/ai/lib/task_meta.py` | +10/-0 | 增加 `approved_operations` 默认字段 |
| `scripts/ai/_approve_lib.sh` | +5/-0 | verify_approval_v3 支持 apply 阶段的 operation |

---

## 4. 威胁模型

| # | 威胁 | 缓解 |
|---|------|------|
| T1 | R0 任务被误路由到 dev | phase 路由矩阵按风险等级锁定 |
| T2 | checkpoint 被篡改 | --resume 时校验 branch/commit/plan_hash |
| T3 | dry-run 写入数据 | read-only sandbox + 命令扫描 |
| T4 | apply 消费错误的审批 | operation-level verify_approval_v3 |
| T5 | 并发 --resume | checkpoint 文件写入使用原子 rename |
| T6 | apply 失败但锁未释放 | post-verify 步骤强制清理 |
| T7 | post-verify 被跳过 | apply 阶段 EXIT trap 强制执行 |
| T8 | 跨 worktree resume | checkpoint.worktree 精确比对 |

---

## 5. 测试矩阵

### 5.1 单元测试（~20 用例）

| 测试类 | 用例数 | 覆盖 |
|--------|--------|------|
| TestPhaseSequence | 4 | R0/R1/R2/R3 相位序列正确性 |
| TestCheckpointReadWrite | 4 | 读写 checkpoint、恢复、验证 |
| TestCheckpointIntegrity | 3 | branch/commit/plan_hash 不一致时阻断 |
| TestPhaseGateValidation | 5 | 各 phase gate 通过/失败场景 |
| TestApplyApprovalConsumption | 4 | 正确 scope / 错误 scope / one_time consume / 过期 |

### 5.2 集成测试 - Gate Demo（4 用例）

| Demo | 场景 | 预期结果 |
|------|------|---------|
| **D1_R0_readonly** | R0 任务执行 prepare→plan→audit→result | dev/apply 被 REJECTED |
| **D2_R1_dev** | R1 任务执行 prepare→plan→audit→dev→test→review→result | 全部 PASS |
| **D3_R2_dryrun_blocked** | R2 任务 dry-run 后无批准执行 apply | APPROVAL_MISSING 阻断 |
| **D4_R3_runtime_blocked** | R3 任务有 DEV 批准但无 RUNTIME 批准执行 apply | SCOPE_MISMATCH 阻断 |

### 5.3 恢复测试（~6 用例）

| 用例 | 场景 |
|------|------|
| test_resume_from_failed_dev | dev 失败 → fix → --resume → 继续 |
| test_resume_rejects_changed_plan | --resume 时 plan_hash 不一致 → 阻断 |
| test_resume_rejects_wrong_branch | --resume 时 branch 不一致 → 阻断 |
| test_resume_preserves_completed_phases | 已完成的 phase 不再重复执行 |
| test_resume_from_first_phase | 无 checkpoint → 从 prepare 开始 |
| test_resume_apply_failure_cleans_up | apply 失败 → post-verify → lock 释放 |

---

## 6. 兼容性说明

| 维度 | 策略 |
|------|------|
| 旧 shell API | 保持 `dispatch_task.sh <TASK> <STAGE>` 不变 |
| 旧 stage 名称 | dev/fix/test/review/result/plan 继续有效 |
| route_task.py | payload 增加 `phased: true` 字段，旧调用者不受影响 |
| pause/resume/cancel/status | 旧 control stage 路径不变 |
| writer_lock | 仅在 dev 阶段获取，与旧行为一致 |
| resource_locks | dev/apply/dry-run 阶段获取，release 在 post-verify 中 |
| approval 记录 | V3 格式不变；apply 阶段消费 DEV + DATA_WRITE/RUNTIME |

---

## 7. 分阶段读取清单

| 阶段 | 读取文件 | 何时读 |
|------|---------|--------|
| 现状分析 | `dispatch_task.sh` / `route_task.py` / `dispatch_control.py` / `_approve_lib.sh` / `_work_level_lib.sh` | **DEV 前**（本次 Plan 已读完） |
| DEV | `status_machine.py` / `approval_manager.py` / `resource_lock.py` / `run_tests.sh` / `collect_result.sh` | **DEV 时** |

---
