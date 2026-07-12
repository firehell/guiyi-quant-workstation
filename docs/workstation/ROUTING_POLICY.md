# 模型与权限路由策略

更新时间：2026-07-12

> 实现：[`scripts/ai/route_task.sh`](../../scripts/ai/route_task.sh) → [`scripts/ai/lib/route_task.py`](../../scripts/ai/lib/route_task.py)
> 调度：[`scripts/ai/dispatch_task.sh`](../../scripts/ai/dispatch_task.sh)

本文定义**文档层档位**（fast / standard / deep / critical）与**实现层 profile** 的映射。档位决定推理深度；**权限由 stage 与审批决定**，二者不可混淆。

## 1. 核心原则

1. **任务事实决定档位**：TASK 类型、Work Level、§7 范围、`Critical` 标记、是否策略/回测/DB/风控，决定应使用的档位；Agent 不得自行降级。
2. **权限由 stage 和审批决定**：`dev`/`fix` 必须有效审批 + workspace-write sandbox；`plan`/`review` 只读；`test`/`result`/`route` 不调用模型。
3. **模型档位不能改变安全权限**：升级到 `high-*` profile 不等于可 bypass Gate、跳过审批或使用 danger sandbox。

## 2. 档位定义

| 档位 | 典型场景 | 默认 profile | 可调范围 |
|------|----------|--------------|----------|
| **fast** | `route` / `test` / `result`、脚本语法检查、状态查询 | `no-model` | 不可升级为调用模型 |
| **standard** | 常规模块、文档、测试、小范围修复 | `plan-readonly` / `dev-workspace-write` | 默认；**不可降级** |
| **deep** | 跨模块重构、复杂 review、多文件联动 | `high-readonly` / `high-workspace-write` | 仅 `--profile` **升级** |
| **critical** | 策略 / 回测 / DB / 数据中心 / 风控；TASK `Critical=true` | deep + `external_review_required` | Codex review **不能**替代外部审查 |

## 3. Stage → 默认 profile

| Stage | Base profile | Sandbox | Calls model |
|-------|--------------|---------|-------------|
| `route` | `no-model` | none | 否 |
| `plan` | `plan-readonly` | read-only | 是 |
| `dev` | `dev-workspace-write` | workspace-write | 是 |
| `fix` | `dev-workspace-write` | workspace-write | 是 |
| `test` | `no-model` | none | 否 |
| `review` | `review-readonly` | read-only | 是 |
| `result` | `no-model` | none | 否 |

## 4. 实现 profile 表

| Profile | Rank | Sandbox | 用途 |
|---------|------|---------|------|
| `no-model` | 0 | none | 确定性 stage |
| `plan-readonly` | 10 | read-only | 标准 Plan |
| `review-readonly` | 10 | read-only | 标准 Review |
| `dev-workspace-write` | 20 | workspace-write | 标准 Dev |
| `high-readonly` | 30 | read-only | deep Plan / Review |
| `high-workspace-write` | 40 | workspace-write | deep Dev |

Profile 别名（route 解析）：`readonly` / `read-only` → `plan-readonly`；`workspace-write` → `dev-workspace-write`。

## 5. 升级与禁止降级

```bash
# 查看路由（不执行）
scripts/ai/dispatch_task.sh <TASK_ID> route --json

# 带 explain
scripts/ai/route_task.sh <TASK_ID> plan --explain --json

# 升级 profile（仅当 TASK 档位允许且不低于 stage 基线）
scripts/ai/dispatch_task.sh <TASK_ID> plan --profile high-readonly --json
```

规则（[`route_task.py`](../../scripts/ai/lib/route_task.py)）：

- `no-model` stage 禁止请求任何调用模型的 profile。
- `profile.rank` 低于 stage 基线 → 拒绝（**禁止降级**）。
- `sandbox` 低于 stage 基线 → 拒绝（**禁止放宽后再降权限的旁路**实际上是通过 sandbox rank 保证不降级）。

禁止：`--yolo`、`danger-full-access`、`--dangerously-bypass-approvals-and-sandbox`（dispatch 直接拒绝）。

## 6. critical 任务额外要求

满足以下任一条件，视为 **critical**：

- TASK 元信息 `Critical | true`
- 任务类型为策略 / 回测 / 数据库 / 数据中心 / worker / scheduler / 风控
- TASK 正文含 `external_review_required` 或「外部审查」要求

critical 任务：

- 默认使用 **deep** 档位（`high-*` profile）。
- `collect_result.sh` 设置 `external_review_required=true` 时，**不得**仅凭 Codex review 关闭。
- 仍需 ChatGPT 外部审查或人工 sign-off。

## 7. TASK 字段与路由输入

Router 从 TASK 解析并写入 `route.json`：

- `allowed_paths` / `forbidden_paths`（§7）
- `required_tests`（§18.0）
- `required_env` / `required_mounts`（§0 元信息）
- `work_level` / `branch` / `worktree` / `status`

范围越界或 forbidden path 修改会在 `result` 阶段阻断。

## 8. 相关文档

- 工作站架构：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 居家 / 远程：[`HOME_DEVELOPMENT.md`](HOME_DEVELOPMENT.md)、[`REMOTE_DEVELOPMENT.md`](REMOTE_DEVELOPMENT.md)
- Agent 硬规则：[`AGENTS.md`](../../AGENTS.md) §8.1
