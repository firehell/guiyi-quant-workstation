# 任务合同分类

本目录保存业务/受控任务合同。恢复只使用 Git history（见 `AGENTS.md` / `DECISIONS.md`）。

## 四种 disposition

| Disposition | 含义 | 处理 |
|---|---|---|
| `active_contract` | 仍定义未来工作或现行业务边界 | 去掉协作授权谓词；保留业务正确性与一次性 scoped intent |
| `historical_fact` | 已完成执行、事故或证据 | 可保留原文或删除后靠 Git；不得再解释为当前授权 |
| `frozen_runtime_consumed` | Runtime/代码仍读取、哈希或绑定 | 在 caller 迁移与 Runtime smoke 通过前保留 |
| `superseded_unreferenced` | 无 active caller、无现行业务边界 | 可与 active references 一并普通删除 |

机器可读 inventory 由 `scripts/engineering/repository_consistency.py --task-inventory`
在内存/命令输出中生成，不落盘为授权工件。checksum/digest/data-identity 语义保留；
Gate/hash-path 不再作为授权。

## Active contracts

- `GY-DATA-CORE-V2.md` — 数据交互核心收口 active 业务合同
- `V1-FINAL-ACCEPTANCE-S6-11.md` — 未来 Runtime/只读验收边界；release 与 Runtime 分属不同意图

## Completed historical facts

- `GY-DATA-PRODUCT-RETIREMENT-21.md` — 21 品种生产退役、69 品种刷新与 Runtime 收口已完成

## Frozen Runtime-consumed（Phase E 前不可删）

- `S6-07-DATABASE-REVISION-DRIFT-RECOVERY.md`

已删除但仍由代码 task_id 引用的旧 S6-08 / S6-10 合同文本，仅能从 Git history 追溯；
不得再当作现存路径或当前授权。

## Historical facts（已删，仅 Git history）

下列文件已从本目录移除，事实含义仅以 Git history 追溯，不构成当前授权：

- `GY-CORE-01-ARCHITECTURE-INVENTORY.md`
- `GY-CORE-02-ACTIVE-DATASET-FACADE-PLAN.md`
- `GY-CORE-CONVERGENCE.md`
- `GY-DATA-CORE-V2-TASK06-MIGRATION-APPROVAL.md`
- `GY-DATA-CORE-V2-TASK06-MIGRATION-INCIDENT.md`
- `GY-DATA-CORE-V2-TASK07-EVIDENCE.md`
- `JM-LIVE-SIGNAL-EVENT-S6-08.md`
- `JM-LIVE-STABILITY-S6-10.md`

普通开发不强制创建任务合同。受控外部操作边界见 `AGENTS.md`。

工程规则见 `AGENTS.md`；当前状态见 `STATUS.md`；个人开发流程见
`docs/PERSONAL_DEVELOPMENT_WORKFLOW.md`。
