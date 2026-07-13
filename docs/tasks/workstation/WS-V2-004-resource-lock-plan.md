# WS-V2-004 Plan：资源锁与异常恢复

> 状态：RESULT_READY | 风险：R1 | 前置：WS-V2-003 RESULT_READY
> 分支：codex/workstation-governance-v2 | Base: main @ fd8d65ab
> Plan SHA：`85f5e075252a26d523609bbc9f616eae587ee0b1e5ecb66fba9bd5e6e8f530b7`
> 本阶段：只读 Plan，不修改任何文件

---

## 目录

1. [现状分析](#1-现状分析)
2. [设计原则](#2-设计原则)
3. [8 种 Resource Scope](#3-8-种-resource-scope)
4. [锁记录 Schema](#4-锁记录-schema)
5. [核心操作](#5-核心操作)
6. [互斥规则](#6-互斥规则)
7. [Dispatcher 集成](#7-dispatcher-集成)
8. [与 writer_lock 共存策略](#8-与-writer_lock-共存策略)
9. [文件结构](#9-文件结构)
10. [测试策略](#10-测试策略)
11. [威胁模型](#11-威胁模型)
12. [实现任务拆解](#12-实现任务拆解)
13. [兼容风险评估](#13-兼容风险评估)

---

## 1. 现状分析

### 1.1 现有 writer_lock（worktree-scoped）

```
工作树级锁 → .ai/locks/worktrees/{hash16}.json
```

| 特性 | 现状 |
|------|------|
| 粒度 | 每个 worktree 一把锁 |
| 用途 | 防止多个 Codex/Cursor 同时写同一个 worktree |
| 获取 | `open(x)` 原子独占 |
| 释放 | 只有 owner (task_id + pid) 可以释放 |
| 陈旧 | PID 存活检测（同机）+ 时间阈值（异机） |
| 心跳 | **无** |
| 强制解锁 | break-stale（仅陈旧） |
| 审计 | audit.jsonl（所有事件） |
| 集成 | dispatch_task.sh 在 dev/fix 阶段 acquire/cleanup |

### 1.2 问题

1. **无资源粒度**：只有 "谁能写这个 worktree"，无法区分 "谁在写数据" vs "谁在跑 JM"
2. **无心跳续租**：长时间任务无法证明存活，stale 依赖 PID（PID 存活但进程卡死 = 假阳性）
3. **无 force-release**：break-stale 只能用于陈旧锁，无法人工介入（要求 4.6）
4. **无互斥规则**：runtime-jm 和 after-market-archive 不应同时运行（要求 4.7）
5. **无并发竞争测试**：未覆盖 TOCTOU、double-acquire、race 等场景

---

## 2. 设计原则

1. **资源级锁与工作树级锁共存**：writer_lock 保持原样（管控工作树写冲突），resource_lock 新增（管控 8 种业务资源）
2. **心跳续租**：长时间持有锁的任务必须定期 heartbeat，否则按超时处理
3. **force-release 必须可审计**：有人工理由字符串，写入不可变 JSONL 日志
4. **Dispatcher 前置检查**：`resource_locks` 字段驱动，执行前 acquire 所有需要的 scope
5. **原子获取**：`open("x")` 保证原子性，FileExistsError = 已被持
6. **幂等重入**：同一 task_id 重复 acquire 同一 scope = no-op + 刷新心跳
7. **进程异常不静默删除**：只有 owner task_id+pid 或 force-release（带理由）才能释放

---

## 3. 8 种 Resource Scope

| Scope | 含义 | 典型持有者 | Stale 阈值 |
|-------|------|-----------|-----------|
| `data-writer` | 写入本地 Parquet/CSV 数据 | Codex CLI (dev) | 2h |
| `postgres-metadata-writer` | 写入 PostgreSQL 元数据 | Codex CLI (dev) | 2h |
| `rqdata-download` | RQData API 下载分钟数据 | Codex CLI (dev) | 4h |
| `main-contract-map-writer` | 写入主力合约映射表 | Codex CLI (dev) | 2h |
| `runtime-jm` | 运行 JoinQuant 分钟策略 | Codex CLI (prod) | 8h |
| `after-market-archive` | 收盘后归档任务 | Codex CLI (prod) | 8h |
| `external-notification` | 企业微信/webhook 通知 | 任意 (dev/prod) | 5m |
| `docs-delete` | 删除文档/任务文件 | 任意 | 5m |

### 3.1 互斥规则

```
runtime-jm ⟂ after-market-archive
```

当 `runtime-jm` 已被持有时，`after-market-archive` 不可获取，反之亦然。
原因：两者都可能在盘中操作共享数据（策略信号 vs 归档），同时运行会导致竞态。

---

## 4. 锁记录 Schema

```json
{
  "schema_version": 1,
  "lock_id": "a1b2c3d4e5f6g7h8",
  "scope": "data-writer",
  "task_id": "WS-V2-004",
  "epic_id": "WORKSTATION-GOVERNANCE-V2",
  "owner_pid": 12345,
  "host": "mac-mini.local",
  "acquired_at": "2026-07-13T09:00:00Z",
  "heartbeat_at": "2026-07-13T09:05:00Z",
  "command": "codex --task WS-V2-004",
  "branch": "codex/workstation-governance-v2",
  "worktree": "/Volumes/扩展盘/guiyi-parallel/workstation-governance-v2"
}
```

### 4.1 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `schema_version` | int | Y | 固定 1 |
| `lock_id` | str | Y | SHA256(task_id:scope:pid:time)[:16] |
| `scope` | str | Y | 8 种 scope 之一 |
| `task_id` | str | Y | 持有者 Task ID |
| `epic_id` | str | N | 可选 Epic ID |
| `owner_pid` | int | Y | 持有进程 PID |
| `host` | str | Y | hostname |
| `acquired_at` | str | Y | ISO8601 UTC 获取时间 |
| `heartbeat_at` | str | Y | ISO8601 UTC 最后心跳时间 |
| `command` | str | N | 持有者的执行命令 |
| `branch` | str | N | Git branch |
| `worktree` | str | N | Worktree 路径 |

### 4.2 锁文件路径

```
.ai/locks/resources/{scope}.json
```

每个 scope 一个锁文件。scope 名直接用作文件名，如：
- `.ai/locks/resources/data-writer.json`
- `.ai/locks/resources/runtime-jm.json`

### 4.3 审计日志路径

```
.ai/locks/resources/audit.jsonl
```

所有 resource lock 事件写入同一个审计文件（与 worktree lock 的 `.ai/locks/audit.jsonl` 独立）。

---

## 5. 核心操作

### 5.1 inspect — 检查锁状态

```
resource_lock.sh inspect --scope data-writer [--json]
```

返回：`{state: "unlocked" | "locked" | "stale", lock: {...} | null, reason: str}`

stale 判定：`heartbeat_at + stale_threshold < now`

### 5.2 acquire — 原子获取

```
resource_lock.sh acquire --scope data-writer --task-id WS-V2-004 [--epic-id ...] [--branch ...] [--worktree ...]
```

逻辑：
1. 检查 scope 是否在 VALID_SCOPES
2. 检查互斥规则（如 runtime-jm ⟂ after-market-archive）
3. `open("x")` 原子创建锁文件
4. 如果 FileExistsError → 检查是否同一 task_id re-acquire
   - 同一 task：刷新 heartbeat → 幂等返回
   - 不同 task：raise `LockError("SCOPE_HELD")`
5. 写入锁文件
6. 写审计日志（event: "acquire"）

### 5.3 heartbeat — 心跳续租

```
resource_lock.sh heartbeat --scope data-writer --task-id WS-V2-004 --pid 12345
```

逻辑：
1. 读取锁文件
2. 验证 owner (task_id + pid)
3. 更新 `heartbeat_at`
4. 写回

注意：只更新 heartbeat_at，不修改其他字段。

### 5.4 release — 正常释放

```
resource_lock.sh release --scope data-writer --task-id WS-V2-004 --pid 12345
```

逻辑：
1. 验证 owner
2. 删除锁文件
3. 写审计日志（event: "release"）

### 5.5 force-release — 强制释放（人工介入）

```
resource_lock.sh force-release --scope data-writer --reason "进程 12345 已卡死 3 小时，手动清理"
```

逻辑：
1. 拒绝空 reason（≤10 字符）
2. 读取锁文件
3. 写审计日志（event: "force-release"，含 reason + actor 信息）
4. 删除锁文件

**不可用于 active heartbeat 锁？** 不 —— force-release 的语义就是"人工确认后强制释放"。是否陈旧由操作者判断。审计日志记录了完整理由，事后可追溯。

---

## 6. 互斥规则

| 锁 A | 锁 B | 规则 |
|------|------|------|
| `runtime-jm` | `after-market-archive` | 互斥（A 持有时 B 不可获取，反之亦然） |

### 6.1 实现方式

`acquire()` 中新增 `_check_mutex(scopes_held: set[str], target_scope: str)`:

```python
MUTEX_PAIRS = frozenset([
    frozenset(["runtime-jm", "after-market-archive"]),
])

def _check_mutex(held_scopes, target):
    target_set = _find_mutex_group(target)
    if target_set is None:
        return
    held_conflict = target_set & held_scopes
    if held_conflict:
        raise LockError(f"MUTEX: {target} conflicts with held scope(s) {held_conflict}")
```

### 6.2 Dispatcher 前置校验

Dispatch 时读取所有 scope 的状态，如果互斥冲突则 fail-fast，不进入执行。

---

## 7. Dispatcher 集成

### 7.1 前置获取

在 `dispatch_task.sh` 的 `main()` 中，在 `resolve_child_command` 之后（或在 `acquire_writer_lock` 之前），新增：

```bash
# Resource lock gate: check and acquire all resource_locks from task metadata
acquire_resource_locks "$task_id"
```

`acquire_resource_locks()`:
1. 调用 `PYTHONPATH=... python3 -c "..."` 从 TaskMeta 读取 `resource_locks`
2. 对每个 scope 调用 `resource_lock.sh acquire --scope ... --task-id ...`
3. 任一个失败 → 报错退出

### 7.2 退出释放

在 `cleanup_writer_lock()` 同级新增 `cleanup_resource_locks()`，由 `EXIT` trap 触发：

```bash
cleanup_resource_locks() {
  # Release all resource locks owned by this task
  "$SCRIPT_DIR/resource_lock.sh" release-all --task-id "$TASK_ID" --pid "$$" || true
}
```

### 7.3 release-all 命令

新增子命令，遍历所有 scope，释放当前 task_id + pid 持有的所有锁。

### 7.4 任务定义中的 resource_locks 字段

V2 任务通过 YAML frontmatter 声明所需资源锁：

```yaml
resource_locks:
  - data-writer
  - postgres-metadata-writer
  - external-notification
```

如果任务不需要资源锁，字段留空 `[]` 或不写。

---

## 8. 与 writer_lock 共存策略

| 维度 | writer_lock | resource_lock |
|------|-------------|---------------|
| 粒度 | worktree | resource scope |
| 文件路径 | `.ai/locks/worktrees/{hash}.json` | `.ai/locks/resources/{scope}.json` |
| 审计 | `.ai/locks/audit.jsonl` | `.ai/locks/resources/audit.jsonl` |
| 是否修改 | **不修改** | **新增** |
| CLI | `writer_lock.sh` | `resource_lock.sh` |
| 模块 | `writer_lock.py` | `resource_lock.py` |

**共存原则**：
1. writer_lock 管控"谁能写这个 worktree"——保持不变
2. resource_lock 管控"谁能操作这个业务资源"——新增
3. Dispatcher 先获取 writer_lock，再获取 resource_locks
4. 退出时先释放 resource_locks，再释放 writer_lock
5. 两者独立，互不依赖

---

## 9. 文件结构

### 9.1 新增文件

| 文件 | 行数估算 | 说明 |
|------|---------|------|
| `scripts/ai/lib/resource_lock.py` | ~350 | 核心库：inspect/acquire/heartbeat/release/force-release |
| `scripts/ai/resource_lock.sh` | ~60 | CLI 包装脚本（5 子命令 + release-all） |
| `tests/workstation/test_resource_lock.py` | ~350 | 测试（~35 用例） |
| `tests/workstation/fixtures/resource_lock_*.json` | ~5 个 | 测试用 fixture 锁文件 |

### 9.2 修改文件

| 文件 | 改动 | 说明 |
|------|------|------|
| `scripts/ai/dispatch_task.sh` | +20/-2 | 新增 acquire_resource_locks / cleanup_resource_locks / release-all 集成 |
| `configs/ai/schemas/task-v2.0.schema.json` | +5 | resource_locks 字段加 enum 约束 |
| `scripts/ai/lib/task_meta.py` | +3 | resource_locks 默认值从 `writer_lock:codex` 更新为 scope 列表 |

### 9.3 不变文件

- `scripts/ai/writer_lock.sh` — 不修改
- `scripts/ai/lib/writer_lock.py` — 不修改
- 其他所有脚本 — 不修改

---

## 10. 测试策略

### 10.1 单元测试（~20 用例）

| 测试类 | 用例数 | 内容 |
|--------|--------|------|
| `TestInspect` | 4 | unlocked/locked/stale/bad_scope |
| `TestAcquire` | 6 | basic/re-acquire idempotent/double acquire blocked/invalid scope/mutex blocked/atomic via x mode |
| `TestHeartbeat` | 4 | update heartbeat/expired detection/wrong owner/bad scope |
| `TestRelease` | 4 | normal release/release non-existent/wrong owner/wrong pid |
| `TestForceRelease` | 2 | valid with reason/empty reason blocked |

### 10.2 Gate 测试（~8 用例）

| 测试类 | 用例数 | 内容 |
|--------|--------|------|
| `TestConcurrentCompetition` | 4 | 两个模拟进程抢同一 scope → 只有一个成功/并行不同 scope 均成功/TOCTOU/快速 acquire-release-acquire |
| `TestStaleLock` | 3 | 超时后 force-release 成功/heartbeat 续租不超时/陈旧锁后被 acquire 成功 |
| `TestMutexRules` | 3 | runtime-jm 持有时 archive 失败/archive 持有时 jm 失败/释放后可获取 |
| `TestWrongRelease` | 2 | 不同 task_id release 失败/不同 pid release 失败 |

### 10.3 集成测试（~4 用例）

| 测试 | 内容 |
|------|------|
| `test_dispatcher_acquires_resource_locks` | Dispatcher 从 task meta 读取 resource_locks 并全部 acquire |
| `test_dispatcher_releases_on_exit` | 正常退出/异常退出均释放 |
| `test_dispatcher_blocks_on_held_lock` | 资源已被持有时 Dispatcher 拒绝执行 |
| `test_release_all` | release-all 只释放当前 task_id 的锁，不影响其他 |

### 10.4 Fixture 文件（5 个）

| Fixture | 内容 |
|---------|------|
| `resource_lock_acquired.json` | 正常持有的锁 |
| `resource_lock_stale.json` | heartbeat 超时的陈旧锁 |
| `resource_lock_runtime_jm.json` | runtime-jm 持有中（用于互斥测试） |
| `resource_lock_archive.json` | archive 持有中（用于互斥测试） |
| `resource_lock_other_task.json` | 其他 task_id 持有（用于跨任务测试） |

### 10.5 并发测试环境

- 使用 `tempfile.TemporaryDirectory` 作为临时锁目录
- 使用 `multiprocessing` / `subprocess` 模拟并发进程
- **不访问任何业务数据**（只操作临时 JSON 文件）

---

## 11. 威胁模型

| # | 威胁 | 影响 | 缓解 |
|---|------|------|------|
| T1 | 两个 Codex 同时写 data-writer | 数据损坏 | `open("x")` 原子获取，后到者报 SCOPE_HELD |
| T2 | 进程 crash 后锁没释放 | 资源永久锁定 | heartbeat 超时 → stale → 可 force-release 或重新 acquire |
| T3 | 进程卡死但 PID 存活 | 虚假存活 | heartbeat_at 超时检测，不依赖 PID（与 writer_lock 不同） |
| T4 | 错误进程释放他人锁 | 资源被意外抢占 | release 验证 task_id + pid，不匹配拒绝 |
| T5 | force-release 被滥用 | 资源锁被随意解除 | 要求 reason ≥10 字符 + 写入不可变 JSONL 审计 |
| T6 | runtime-jm 与 archive 同时运行 | 策略信号 + 归档竞态 | 互斥规则在 acquire 时检查 |
| T7 | 一次性通知被重放 | 重复发送外部消息 | external-notification scope + one-shot consume 逻辑 |
| T8 | 锁文件被手动删除 | 绕过锁机制 | 审计日志保留完整历史（JSONL 不可变），可事后追溯 |
| T9 | TOCTOU race | 并发绕过检查 | `open("x")` 是原子操作，不分离 check-then-act |
| T10 | stale 阈值过长导致资源长期不可用 | 阻塞后续任务 | scope 级可配置阈值，rqdata-download 4h / notification 5m 差异化 |

### 11.1 Gate 验证场景（与任务规格对齐）

| Gate | 场景 | 预期结果 |
|------|------|----------|
| G1 | 两个模拟任务竞争同一个 data-writer lock | 只有一个成功 |
| G2 | 进程异常退出（SIGKILL）后锁残留 | heartbeat 超时 → stale → 可审计恢复 |

---

## 12. 实现任务拆解

| Step | 内容 | 预估 |
|------|------|------|
| 12.1 | 创建 `resource_lock.py` 核心库（inspect/acquire/heartbeat/release/force-release/互斥） | ~350 行 |
| 12.2 | 创建 `resource_lock.sh` CLI（5 子命令 + release-all） | ~60 行 |
| 12.3 | 修改 `dispatch_task.sh` 集成 resource lock acquire/release | ~20 行 |
| 12.4 | 修改 `task-v2.0.schema.json` resource_locks enum | ~5 行 |
| 12.5 | 编写 5 个测试 fixture | ~30 行 |
| 12.6 | 编写单元测试（~20 用例） | ~200 行 |
| 12.7 | 编写 Gate 测试（并发/陈旧/互斥/错误释放 ~12 用例） | ~150 行 |
| 12.8 | 编写集成测试（~4 用例） | ~60 行 |
| 12.9 | 全量回归测试 | — |

---

## 13. 兼容风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| writer_lock 行为不受影响 | 低 | resource_lock 是完全独立的新模块，不修改 writer_lock.py |
| V2 Task 已有 resource_locks 字段 | 低 | 当前值为 `"writer_lock:codex"`，与新增 scope 格式不同，不会冲突 |
| Dispatcher 新增 trap 顺序 | 低 | 先 release resource_locks，再 release writer_lock，顺序不影响 |
| 文件系统写入 | 低 | 只操作 `.ai/locks/resources/` 下的 JSON 文件，不触碰业务数据 |
| 并发测试只用临时目录 | 低 | 测试中使用 `tempfile.TemporaryDirectory`，不访问真实锁目录 |

---

*Plan 完成，等待人工审批。*
