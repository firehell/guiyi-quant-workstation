# Workstation Routing Policy

本文定义 `scripts/ai/route_task.sh` 和 `scripts/ai/lib/route_task.py` 的确定性路由规则。

路由器只做决策，不调用 Codex，不写数据库，不授予生产、push、merge 或 deploy 权限。

## 输出字段

路由输出稳定 JSON：

- `task_id`
- `stage`
- `resolved_tier`
- `profile`
- `model_family`
- `reasoning_effort`
- `sandbox_mode`
- `approval_policy`
- `reason_codes`
- `external_review_required`
- `allow_auto_escalation`
- `max_auto_escalations`
- `warnings`

## 阶段权限

| Stage | sandbox_mode | 说明 |
|---|---|---|
| `plan` | `read-only` | 只读计划 |
| `review` | `read-only` | 只读审查 |
| `dev` | `workspace-write` | 仅允许工作区写入 |
| `fix` | `workspace-write` | 仅允许工作区写入 |
| `test` | `deterministic_no_model` | 普通脚本执行，不调用模型 |
| `result` | `deterministic_no_model` | 普通脚本汇总，不调用模型 |

`dev` / `fix` 不会自动获得生产访问、数据库写、push、merge、deploy 或交易执行权限。

## Tier 映射

| Tier | Profile | Model Family | Reasoning Effort | 典型任务 |
|---|---|---|---|---|
| `fast` | `guiyi-fast` | `Luna` | `low` | 文档、格式、日志、低风险小修 |
| `standard` | `guiyi-standard` | `Terra` | `medium` | 普通 API、Web、单模块开发 |
| `deep` | `guiyi-deep` | `Sol` | `high` | 跨模块、runtime、scheduler、复杂测试失败 |
| `critical` | `guiyi-critical` | `Sol` | `xhigh` | 指标、策略、数据库 schema、安全、交易执行 |

## 自动规则

`requested_tier=auto` 时使用自动规则。

`critical` 强制触发条件：

- `packages/quant-core`
- 指标 seed、warm-up、NaN、smoothing、指标内核语义
- 策略信号、仓位、撮合、回测与实时一致性
- look-ahead / 未来函数风险
- PostgreSQL schema、Alembic、数据迁移
- JM 实时 1m 核心链路
- 生产环境、安全、密钥、实盘、交易执行
- TASK 明确指定 `requested_tier=critical`

`deep` 触发条件：

- 跨多个主要模块
- runtime、scheduler、worker、并发、恢复
- 大范围重构
- 复杂测试失败
- 预计修改文件较多
- L2 正式交付且未触发 `critical`

`fast` 触发条件：

- L0 只读或咨询类任务
- 文档、格式、日志、简单 UI
- 少量文件
- 不触及核心量化语义、数据库、runtime、生产环境

未匹配以上规则时默认为 `standard`。

## 覆盖规则

- 人工可以请求更高 tier。
- 人工请求低于安全规则时不会降级，并输出 warning。
- `critical` 不允许自动降级。
- `test` / `result` 阶段仍计算 `resolved_tier`，但 `profile` 标记为 `deterministic_no_model`。
- 路由器只给出结果，不自动重跑 Codex，不自动升级执行。

## 使用

```bash
scripts/ai/route_task.sh docs/tasks/<TASK_ID>.md plan --json
scripts/ai/route_task.sh --task <TASK_ID> dev --json --explain
python3 scripts/ai/lib/route_task.py docs/tasks/<TASK_ID>.md review --json
```
