# V1-NEXT-WAVE-FACT-SYNC-000

更新时间：2026-07-18

## 结论

状态：`COMPLETED / NEXT_WAVE_CANONICAL_SYNCED`。

本任务完成 canonical 事实与任务池同步；未修改业务代码、DB、Parquet、Profile binding、runtime、Issue 状态或历史验收证据。

## 对齐后的事实

- `CONSUMER_DATA_CONTRACT_READY / DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL` 是 strict formal consumer Gate。其证据是 C2-05 direct PostgreSQL read-only rerun、真实 Parquet、49 条消费者矩阵和 13 个 hard gate。
- `DATA_LAYER_REAUDIT_REQUIRED` 是 provider-earliest、calendar/session、physical partial 和 warning/failed 资产的全历史维护 backlog；它不否定 consumer Gate，也不能被 Ready 标记抹去。
- 两个状态都不表示 OOS、T3/T4、live SignalEvent、企业微信正式发送、`JM_RUNTIME_READY` 或 `LONG_RUNNING_READY`。

## 执行基线

- 执行时 `origin/main` 与本地 `main` 都是 `7c85329ea2d0552e22d6e952ddb39c018587ddde`。
- 本任务在独立 `codex/v1-next-wave-fact-sync` worktree 执行。
- GitHub Issue #10、#11、#12 均为 open；本任务只读取并给出生命周期建议。

## 已处理漂移

| 位置 | 原有漂移 | 对齐结果 |
|---|---|---|
| `PROJECT_SOURCE.md` | 将 consumer ready 标为尚未通过 | 明确 formal consumer Gate 已通过，并与 re-audit backlog 并列 |
| `DECISIONS.md` | 数据最终状态仍停在 consumer contract 未封板 | 记录两种状态的不同作用域与不可扩写边界 |
| `CODEX_TASKS.md` | 已完成 Audit V2/Profile/formal consumer 工作仍占 P0 | 改为指标契约、策略可信验证、JM T3/T4 串行 P0 |
| `docs/CODEX_HANDOFF.md` | 引用 7 月 16 日合并前的任务与 Phase 3 后续 | 改为当前 Gate、下一轮顺序和 Issue 生命周期建议 |

历史段落和验收数字没有重写；若出现“尚未通过”，只保留在明确标注的当时历史快照中。

## Issue 生命周期建议

- Issue #10：实现已被当前主干的 HTDY indicator/strategy 工作覆盖；建议人工复核后关闭或归档，不由本任务自动关闭。
- Issue #11：实现已被当前主干的 Market indicator/EMA overlay 工作覆盖；建议人工复核后关闭或归档，不由本任务自动关闭。
- Issue #12：保持 open；重新建立稳定 runtime 副本后进入 T3/T4 Gate。不得借此声明 live SignalEvent、企业微信、长稳或自动交易 Ready。

## 后续顺序

1. 阶段 4：指标契约与 formal candidate 封板。
2. 阶段 5：策略、独立候选报告、trust audit、OOS/walk-forward 与 Review 回链。
3. 阶段 6：新稳定 runtime 副本上的 JM T3 单次真实 live 与 T4 单交易日盘后归档。

## 验证

- `git diff --check`：通过。
- canonical 状态词 `rg` 扫描：通过；当前事实、历史快照和未完成外部 Gate 均可定位。
- 文档范围和历史/外部 Gate 边界：人工复核通过。

## 2026-07-18 残余漂移补齐

复核确认 Gate `NEXT_WAVE_CANONICAL_SYNCED` 主体已合入 `main`（含 `bce608c7`）。本轮仅补齐两处当前态残余漂移，不重写历史快照，不改业务代码 / DB / Issue 状态：

| 位置 | 残余漂移 | 补齐结果 |
|---|---|---|
| `docs/DATA_CENTER.md` 概述段 | 仍写下一步回到 Audit V2 residual 或 live runtime | 改为阶段 4/5/6 串行主线；Audit V2 residual 为非阻塞 P1 |
| `DECISIONS.md` 后续需决策 | Profile rollout、formal consumer / Golden Query 仍列为未决 | 移入“已关闭”；保留 residual 分批口径等真正未决项 |

历史章节中的“尚未通过”（含 `tasks/current.md` 旧任务正文、`DATA_CENTER.md` §2.2.7 旧 Audit 快照、部分 `docs/gpt/` 兼容摘要）保持不动。Gate 名称不变：`NEXT_WAVE_CANONICAL_SYNCED`。

## 2026-07-19 接替说明

手册 D4-00 / `HTDY-SOURCE-XMA-AUDIT-400` 证据已落盘；最终 Gate 为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`。下一入口已由 `CURSOR-CANONICAL-SYNC-C001` 接替为 Cursor Wave（`CURSOR_CANONICAL_SYNC_PREPARED`），不再把“手册 D4-00”当作开放入口。
