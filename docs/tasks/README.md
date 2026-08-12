# 任务合同分类

本目录保存业务/受控任务合同。恢复只使用 Git history（见 `AGENTS.md` / `DECISIONS.md`）。

## 文档命名约定

| 范围 | 约定 | 示例 |
|---|---|---|
| `docs/` 顶层文件 | `SCREAMING_SNAKE.md` | `DATA_CENTER.md` |
| `docs/` 子目录 | `snake_case` | `tasks/` |
| 本目录任务合同 | `TASK-ID-SLUG.md`（大写 ID + 连字符） | `GY-DATA-CORE-V2.md` |
| `openspec/`、`.kiro/`、`prompts/` | kebab-case | `slim-web-to-market`、`code-review.md` |
| 项目 skill 目录名 | 可保留 kebab（工具惯例） | `.agents/skills/futures-data/` |

禁止：用 `*_latest` 目录名暗示 live 状态；在 `docs/` 顶层混用 kebab 文件名；在 skill 内复制 docs 已有的 SCREAMING 正文造成双轨。

## 四种 disposition

| Disposition | 含义 | 处理 |
|---|---|---|
| `active_contract` | 仍定义未来工作或现行业务边界 | 去掉协作授权谓词；保留业务正确性与一次性 scoped intent |
| `historical_fact` | 已完成执行、事故或证据 | 可保留原文或删除后靠 Git；不得再解释为当前授权 |
| `frozen_runtime_consumed` | Runtime/代码仍读取、哈希或绑定 | 在 caller 迁移与 Runtime smoke 通过前保留 |
| `superseded_unreferenced` | 无 active caller、无现行业务边界 | 可与 active references 一并普通删除 |

本目录 disposition 由下方列表直接维护，不再生成机器 inventory 或治理工件。Canonical identity 与
物理可读性语义保留；已退出的 checksum/digest/Gate/hash-path 不再作为 active 合同或授权。

## Active contracts

当前无 active task contract；长期行为规范位于 `openspec/specs/`。

## Historical facts（仍在本目录）

已完成的 Data Foundation、品种清退与四品种 Runtime 阶段合同已删除，仅从 Git history 追溯。

已退役的回测、OOS、S6-08 / S6-10 / S6-11 合同与证据仅能从 Git history 追溯；
不得再当作现存路径、兼容入口或当前授权。未来重建回测或 Runtime 验收必须新建任务，
重新定义当前代码与数据边界。

## Historical facts（已删，仅 Git history）

下列文件已从本目录移除，事实含义仅以 Git history 追溯，不构成当前授权：

- `GY-CORE-01-ARCHITECTURE-INVENTORY.md`
- `GY-CORE-02-ACTIVE-DATASET-FACADE-PLAN.md`
- `GY-CORE-CONVERGENCE.md`
- `GY-DATA-CORE-V2-TASK06-MIGRATION-APPROVAL.md`
- `GY-DATA-CORE-V2-TASK06-MIGRATION-INCIDENT.md`
- `GY-DATA-PRODUCT-RETIREMENT-21.md`（21 品种退役已完成；当前事实见 `STATUS.md` / `DATA_CENTER.md`）
- `GY-DATA-CORE-V2.md`
- `GY-DATA-PRODUCT-RETIREMENT-5.md`
- `GY-MARKET-RUNTIME-V1.md`
- `JM-LIVE-SIGNAL-EVENT-S6-08.md`
- `JM-LIVE-STABILITY-S6-10.md`
- `V1-FINAL-ACCEPTANCE-S6-11.md`

普通开发不强制创建任务合同。受控外部操作边界见 `AGENTS.md`。

工程规则见 `AGENTS.md`；当前状态见 `STATUS.md`；开发流程见 `docs/DEVELOPMENT.md`。
