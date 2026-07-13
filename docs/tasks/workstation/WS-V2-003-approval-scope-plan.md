# WS-V2-003 Plan：分级审批记录与范围校验

> 状态：RESULT_READY | 风险：R1 | 前置：WS-V2-002 RESULT_READY
> 分支：codex/workstation-governance-v2 | Base: main @ 529c352d
> Plan SHA：`95be8ff7db3a9538c23ae551907b2c07d157a7a8ab1fe9528d8244ea8d8a1651`

---

## 目录

1. [现状诊断](#1-现状诊断)
2. [设计原则](#2-设计原则)
3. [7 种 Operation 定义](#3-7-种-operation-定义)
4. [审批记录 Schema V3](#4-审批记录-schema-v3)
5. [审批生命周期](#5-审批生命周期)
6. [验证流程与 Gate](#6-验证流程与-gate)
7. [文件结构](#7-文件结构)
8. [威胁模型](#8-威胁模型)
9. [测试矩阵](#9-测试矩阵)
10. [实现任务拆解](#10-实现任务拆解)
11. [兼容评估](#11-兼容评估)

---

## 1. 现状诊断

### 1.1 当前审批系统（V1/V2）

| 能力 | 现状 | Gap |
|------|------|-----|
| 审批记录格式 | JSON，`schema_version` 1/2 | 无 `approved_operations` / `expires_at` / `consumed` |
| 作用域 | `approval_scope: [plan, code, ...]` | 粗粒度类别，非原子操作 |
| 跨 Task 防护 | `verify_approval` 检查 `task_id` | ✅ 已有基本防护 |
| Plan Hash 校验 | `detect_plan_change` | ✅ 已有 |
| Task SHA 校验 | WS-V2-002 新增 | ✅ 已有 |
| 过期 | 无 | **缺失** |
| 一次性消耗 | 无 | **缺失** |
| 操作级校验 | 无 | **缺失** |
| 密钥扫描 | 无 | **缺失** |

### 1.2 `approval_scope` vs `approved_operations` 关系

```
现有 approval_scope（粗粒度类别）:
  [plan] → 只读计划/审计
  [plan, code] → 代码变更
  [plan, code, production_write] → 生产写入
  [plan, code, external_review] → 外部审查

新增 approved_operations（原子操作）:
  AUDIT | DEV | DATA_WRITE | RUNTIME
  EXTERNAL_SEND | MERGE | DOC_DELETE
```

`approval_scope` 继续作为任务级声明（快速判断任务类别），`approved_operations` 作为审批记录中的精确许可。两者正交：
- 宽匹配：`approval_scope` 满足 → 继续 → 精确匹配：`approved_operations` 包含请求的 operation
- 任一不满足 → 拒绝

---

## 2. 设计原则

| 原则 | 说明 |
|------|------|
| **原子操作授权** | 每类危险操作需要独立审批，不可用 DEV 替代 DATA_WRITE |
| **隔离性** | 审批绑死 Task ID，跨 Task 拒绝 |
| **不可继承** | 审批不沿 Task 依赖链继承 |
| **时效性** | 支持 `expires_at` 和一次性（consumed）标记 |
| **零密钥** | 审批记录 schema 禁止密钥字段；写入前扫描 |
| **fail-closed** | 缺失审批 → 拒绝；过期审批 → 拒绝；scope 不匹配 → 拒绝 |
| **不可变 + 追加** | 审批创建后不可修改；consumed 通过追加日志标记 |

---

## 3. 7 种 Operation 定义

| Operation | 含义 | 典型触发 | 风险等级要求 |
|-----------|------|---------|-------------|
| `AUDIT` | 只读审计/盘查/查看 | `dispatch_task.sh route/plan`（dry-run） | R3+ |
| `DEV` | 代码/配置开发 | `codex_dev.sh`、`dispatch_task.sh dev/fix` | R2+ |
| `DATA_WRITE` | 数据库写入/文件持久化 | DB apply、migration、parquet 写入 | R1+ |
| `RUNTIME` | 运行时操作 | 启动/停止/重启服务、worker 控制 | R1+ |
| `EXTERNAL_SEND` | 外部通知/发送 | 企业微信发送、webhook、邮件、短信 | R1+ |
| `MERGE` | 代码合并 | `git merge`、`git push`、PR merge | R2+ |
| `DOC_DELETE` | 文档/数据删除 | `rm` 任务单、删除历史数据、清理日志 | R2+ |

### 3.1 Operation 层级

```
AUDIT ── (只读，最低权限)
  │
  ├── DEV ── (代码变更)
  ├── MERGE ── (代码合并)
  ├── DOC_DELETE ── (文档删除)
  │
  ├── DATA_WRITE ── (数据写入)
  ├── RUNTIME ── (运行时，含服务控制)
  └── EXTERNAL_SEND ── (外部通知，最高权限)
```

高权限不自动包含低权限。`DEV` 许可不意味着可以 `DATA_WRITE` 或 `EXTERNAL_SEND`。

---

## 4. 审批记录 Schema V3

### 4.1 JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://guiyi-quant.dev/schemas/approval-v3.0.json",
  "title": "GUIYI Approval Record V3.0",
  "type": "object",
  "required": ["schema_version", "task_id", "epic_id", "plan_hash",
               "approved_operations", "approver", "approved_at"],
  "properties": {
    "schema_version": {"const": 3},
    "task_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]+$"},
    "epic_id": {"type": "string"},
    "plan_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "task_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "approved_operations": {
      "type": "array",
      "items": {"enum": ["AUDIT", "DEV", "DATA_WRITE", "RUNTIME",
                         "EXTERNAL_SEND", "MERGE", "DOC_DELETE"]},
      "minItems": 1,
      "uniqueItems": true
    },
    "forbidden_operations": {
      "type": "array",
      "items": {"enum": ["AUDIT", "DEV", "DATA_WRITE", "RUNTIME",
                         "EXTERNAL_SEND", "MERGE", "DOC_DELETE"]},
      "uniqueItems": true
    },
    "approval_scope": {
      "type": "array",
      "items": {"enum": ["plan", "code", "production_write", "external_review"]}
    },
    "approver": {"type": "string"},
    "approved_at": {"type": "string", "format": "date-time"},
    "expires_at": {"type": "string", "format": "date-time"},
    "one_time": {"type": "boolean", "default": false},
    "branch": {"type": "string"},
    "head_commit": {"type": "string", "pattern": "^[a-f0-9]{40}$"},
    "task_file": {"type": "string"},
    "plan_file": {"type": "string"}
  },
  "additionalProperties": false,
  "allOf": [
    {
      "if": {"properties": {"one_time": {"const": true}}},
      "then": {
        "properties": {"expires_at": false},
        "errorMessage": "one_time approval must not set expires_at"
      }
    }
  ]
}
```

### 4.2 字段对照

| 字段 | 类型 | 必需 | V2→V3 变化 |
|------|------|------|-----------|
| `schema_version` | int | ✅ | 2→**3** |
| `task_id` | string | ✅ | 不变 |
| `epic_id` | string | ✅ | **新增必需** |
| `plan_hash` | string | ✅ | 替代 `plan_sha256`，命名精简 |
| `task_hash` | string | ❌ | 替代 `task_sha256` |
| `approved_operations` | list[enum] | ✅ | **新增** |
| `forbidden_operations` | list[enum] | ❌ | **新增** |
| `approval_scope` | list[enum] | ❌ | 从必需变为可选 |
| `approver` | string | ✅ | 替代 `approved_by` |
| `approved_at` | string | ✅ | 不变 |
| `expires_at` | string | ❌ | **新增** |
| `one_time` | boolean | ❌ | **新增** |
| `branch` | string | ❌ | 替代 `approved_branch` |
| `head_commit` | string | ❌ | 不变 |
| `task_file` | string | ❌ | 不变 |
| `plan_file` | string | ❌ | 不变 |

### 4.3 密钥扫描规则

写入审批记录前，检查以下模式，命中 → 拒绝写入：

```python
SECRET_PATTERNS = [
    r'(?i)(api[_-]?key|apikey|secret|token|password|passwd|credential)\s*[:=]\s*\S+',
    r'(?i)Bearer\s+[A-Za-z0-9_\-\.]+=',
    r'(?i)ghp_[A-Za-z0-9_]{36}',
    r'(?i)sk-[A-Za-z0-9_\-]{32,}',
    r'(?i)eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+',  # JWT
]
```

---

## 5. 审批生命周期

### 5.1 状态机

```text
       create
         │
         ▼
    ┌─────────┐  expires_at 到达  ┌──────────┐
    │  VALID  │ ────────────────▶ │ EXPIRED  │
    └────┬────┘                   └──────────┘
         │
         │ consume (one_time=true)
         ▼
    ┌──────────┐
    │ CONSUMED │ (终态，不可恢复)
    └──────────┘
```

### 5.2 一次性批准（one_time=true）

- 创建时必须设 `one_time: true`，且不可同时设 `expires_at`
- 执行成功或失败后均调用 `consume`
- `consumed` 后 `verify` 返回拒绝
- consume 记录写入 `.ai/results/<TASK_ID>/consumed_approvals.jsonl`（追加，不可变日志）

### 5.3 过期批准（expires_at）

- `expires_at` 为 ISO 8601 UTC 时间戳
- `verify` 时当前 UTC 时间 > `expires_at` → 拒绝
- `status` 命令显示剩余有效时间

---

## 6. 验证流程与 Gate

### 6.1 verify 完整流程

```text
verify_approval(approval_file, task_id, plan_file, task_file, operation)
  │
  ├── 1. 文件存在? ── NO → REJECT (APPROVAL_MISSING)
  ├── 2. schema_version == 3? ── NO → REJECT (SCHEMA_UNSUPPORTED)
  ├── 3. task_id 匹配? ── NO → REJECT (CROSS_TASK)
  ├── 4. plan_hash 匹配? ── NO → REJECT (PLAN_CHANGED)
  ├── 5. task_hash 匹配? ── NO → REJECT (TASK_CHANGED)
  ├── 6. branch 匹配? ── NO → REJECT (BRANCH_MISMATCH)
  ├── 7. head_commit 不变? (严格模式) ── NO → REJECT (HEAD_MOVED)
  ├── 8. expired? ── YES → REJECT (EXPIRED)
  ├── 9. consumed? (one_time) ── YES → REJECT (CONSUMED)
  ├── 10. operation ∈ approved_operations? ── NO → REJECT (SCOPE_MISMATCH)
  ├── 11. operation ∈ forbidden_operations? ── YES → REJECT (FORBIDDEN_OP)
  └── 12. ALL PASS → ACCEPT
```

### 6.2 部署 Gate（4 个阻断场景）

| Gate | 场景 | 预期结果 |
|------|------|---------|
| G1 | 用 DEV 批准执行 DB apply | `SCOPE_MISMATCH`: approved=[DEV], requested=DATA_WRITE |
| G2 | 用其他 Task 的批准执行当前 Task | `CROSS_TASK`: task_id 不匹配 |
| G3 | Plan 改变后继续使用旧批准 | `PLAN_CHANGED`: plan_hash 不匹配 |
| G4 | 重放一次性外部通知批准 | `CONSUMED`: one_time 已消耗 |

### 6.3 集成到 dispatch_task.sh

```text
route → plan → [Risk Gate] → [Issue Gate] → [Branch Gate] → [Worktree Gate]
  → [Approval Gate (V3)] → dev/fix/test/review/result
```

Approval Gate 注入点：

| Stage | 所需 Operation |
|-------|---------------|
| `plan` (非 dry-run) | `AUDIT` |
| `dev` / `fix` | `DEV` |
| `test` | `AUDIT` |
| `result` | `AUDIT` |
| `review` | `AUDIT` |

额外操作触发（不通过 dispatch_task.sh 标准 stage）：

| 操作 | 调用方式 | 所需 Approval |
|------|---------|--------------|
| DB apply | `db_apply.sh` | `DATA_WRITE` |
| 服务启停 | `service_ctl.sh` | `RUNTIME` |
| 企业微信发送 | `wecom_send.sh` | `EXTERNAL_SEND` |
| Git merge/push | `git_merge.sh` | `MERGE` |
| 文档删除 | `doc_delete.sh` | `DOC_DELETE` |

---

## 7. 文件结构

### 7.1 新增文件

```
configs/ai/schemas/
└── approval-v3.0.schema.json       # 审批记录 JSON Schema（§4.1）

scripts/ai/lib/
└── approval_manager.py             # 核心逻辑：create/verify/consume/status + 秘钥扫描

scripts/ai/
└── approval.sh                     # CLI 入口（create/verify/consume/status 4 命令）

tests/workstation/
├── test_approval_manager.py        # 审批管理器单测
└── fixtures/
    ├── approval_valid_v3.json      # 有效 V3 审批记录
    ├── approval_expired.json       # 过期审批
    ├── approval_one_time.json      # 一次性审批
    ├── approval_wrong_task.json    # 跨 Task 审批
    └── approval_forged.json        # 伪造审批（密钥泄露）
```

### 7.2 修改文件

| 文件 | 修改内容 | 原因 |
|------|---------|------|
| `scripts/ai/_approve_lib.sh` | `generate_approval` 升级到 V3 schema；新增 `verify_approval_v3` | 兼容 + 新功能 |
| `scripts/ai/dispatch_task.sh` | `validate_static_gates` 调用 V3 approval verify | Gate 注入 |
| `scripts/ai/codex_dev.sh` | 改用 V3 verify | 审批校验升级 |

---

## 8. 威胁模型

### 8.1 威胁矩阵

| ID | 威胁 | 攻击面 | 缓解措施 |
|----|------|--------|---------|
| T1 | 伪造审批记录 | 文件系统写入 | `verify` 检查 JSON Schema、字段完整性、plan_hash/task_hash/task_id/branch 一致性 |
| T2 | 审批重放（one_time） | 一次审批多次使用 | `consumed` 标记 + 追加日志不可变 |
| T3 | 审批过期后继续使用 | 时间窗口 | `expires_at` 检查 + UTC 时间比对 |
| T4 | 跨 Task 审批滥用 | Task A 审批用于 Task B | `verify` 检查 `task_id` 精确匹配 |
| T5 | Plan 变更后旧审批复用 | Plan 篡改 | `plan_hash` 一致性检查 |
| T6 | DEV 审批越权到 DATA_WRITE | 宽权限 | `approved_operations` 精确匹配，DEV != DATA_WRITE |
| T7 | 审批记录泄露密钥 | 文件内容 | 写入前密钥扫描；schema `additionalProperties: false` |
| T8 | 审批继承攻击 | 依赖链自动继承 | 禁止继承；每个 Task 独立审批 |
| T9 | 时间回拨绕过 expires_at | 系统时钟 | 使用 UTC；`approved_at` <= now |
| T10 | 分支变更后继续使用 | 分支切换 | `branch` 匹配检查 |

### 8.2 风险矩阵

| 威胁 | 可能性 | 影响 | 风险 |
|------|--------|------|------|
| T2 重放 | 中 | 高 | **HIGH** |
| T4 跨 Task | 低 | 高 | **MEDIUM** |
| T6 越权 | 中 | 高 | **HIGH** |
| T7 密钥泄露 | 低 | 严重 | **MEDIUM** |

---

## 9. 测试矩阵

### 9.1 单元测试

| 测试类 | 覆盖 | 关键用例 |
|--------|------|---------|
| `TestApprovalCreate` | 创建审批记录 | 有效创建、缺少必需字段、无效 operation、密钥检测拒绝、one_time+expires_at 互斥 |
| `TestApprovalVerify` | 验证审批 | 全部通过、task_id 不匹配、plan_hash 不匹配、operation 不在 approved、operation 在 forbidden、过期、已消耗 |
| `TestApprovalConsume` | 消耗一次性审批 | 正常消耗、重复消耗拒绝、consumed 后 verify 拒绝 |
| `TestApprovalStatus` | 状态查询 | VALID/EXPIRED/CONSUMED 状态判断、剩余时间计算 |
| `TestApprovalSecrets` | 密钥扫描 | API key/token/password/JWT 检测、误报豁免 |
| `TestApprovalForgery` | 伪造检测 | 手动构造 JSON、缺失字段、额外字段、schema 不匹配 |

### 9.2 Gate 集成测试（4 个阻断场景）

| 测试 | 场景 | 预期 |
|------|------|------|
| `test_gate_dev_for_data_write` | DEV 批准 + DATA_WRITE 操作 | `SCOPE_MISMATCH` 拒绝 |
| `test_gate_cross_task` | Task A 审批 + Task B 请求 | `CROSS_TASK` 拒绝 |
| `test_gate_plan_changed` | 旧 plan_hash + 新 Plan | `PLAN_CHANGED` 拒绝 |
| `test_gate_replay_one_time` | consumed 审批 + 再次请求 | `CONSUMED` 拒绝 |

### 9.3 兼容测试

| 测试 | 场景 | 预期 |
|------|------|------|
| `test_v2_approval_still_works` | V2 审批记录在旧流程 | dev 正常（无 operation 检查） |
| `test_v3_approval_backward_compat` | V3 审批记录在 `codex_dev.sh` | DEV operation 通过 |

---

## 10. 实现任务拆解

| 子任务 | 产出 | 预估 |
|--------|------|------|
| 10.1 JSON Schema | `configs/ai/schemas/approval-v3.0.schema.json` | ~80 行 |
| 10.2 approval_manager.py | create/verify/consume/status + 密钥扫描 | ~350 行 |
| 10.3 approval.sh CLI | 4 命令 + --json 输出 | ~150 行 |
| 10.4 修改 _approve_lib.sh | V3 schema 生成 + verify_v3 | ~60 行 |
| 10.5 修改 dispatch_task.sh | Approval Gate 注入 | ~40 行 |
| 10.6 修改 codex_dev.sh | V3 verify 调用 | ~15 行 |
| 10.7 单元测试 | test_approval_manager.py + 5 fixtures | ~300 行 |
| 10.8 Gate 测试 | 4 个阻断场景 | ~120 行 |
| 10.9 兼容测试 | V2/V3 混用 | ~50 行 |

---

## 11. 兼容评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| V2 审批记录在 V3 流程中失效 | P0 | `verify_approval_v3` 对 V2 记录降级为宽松检查（无 operation），仅打印 warning |
| 现有 `dev` stage 需要新增 DEV operation | P1 | `generate_approval` 升级到 V3 时自动填充 `approved_operations: ["AUDIT", "DEV"]` |
| 无审批记录的旧任务 | P2 | dispatch_task.sh 阶段无审批时不阻断（仅 dry-run 路径），或打印 warning |
| 密钥扫描误报 | P2 | 仅检查显式键值对模式，排除注释和 URL |

---

## 附录 A：与用户需求逐条对应

| 用户要求 | Plan 节 |
|---------|--------|
| 1. 支持 7 种 operation | §3 |
| 2. 审批记录字段 | §4.2 |
| 3. apply 前校验 | §6.1 |
| 4. 不跨 Task/不继承/不替代 | §2 + §6 |
| 5. 一次性 consumed | §5.2 |
| 6. 审批不含密钥 | §4.3 |
| 7. approve create/verify/consume/status 命令 | §7.1（approval.sh） |
| 8. 伪造/过期/hash/scope 测试 | §9 |
| Gate: DEV→DB apply 阻断 | §6.2 G1 |
| Gate: 跨 Task 阻断 | §6.2 G2 |
| Gate: Plan 变更阻断 | §6.2 G3 |
| Gate: 重放一次性阻断 | §6.2 G4 |
| 威胁模型 | §8 |
| 测试矩阵 | §9 |
| 兼容说明 | §11 |

---

> Plan 完成时间：2026-07-13 | 下一步：等待人工审批
