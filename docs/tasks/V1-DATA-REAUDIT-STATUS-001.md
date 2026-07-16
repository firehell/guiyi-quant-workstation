# V1-DATA-REAUDIT-STATUS-001：当前数据状态声明纠偏

生成时间：2026-07-16

状态：`CANONICAL_OLD_AUDIT_MARKED_HISTORICAL`

## 目标

修正 canonical 文档对数据层当前状态的描述，停止把旧 Phase 3 审计数字直接写成当前确定下载缺口或批量修复清单。

## 范围

本任务只改文档，不修改业务代码、数据、DB、manifest、Parquet、历史报告、migration、运行配置或 `.env*`。

## 当前状态层次

```text
DATA_LAYER_REAUDIT_REQUIRED
FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS
DATA_LAYER_READY_FOR_MARKET_BACKTEST_SIGNAL  # 尚未通过
```

`FULL_HISTORY_PHYSICAL_DATA_CLAIM_SUPPORTED_BY_MANIFESTS` 只说明仓库 manifest 强烈支持物理历史数据已大规模下载，不代表 direct PostgreSQL、quality、Profile binding 或 formal consumer contract 已验收。

## 历史快照保留

以下旧 Phase 3 数字保留在 `data/reports/data_layer_final_audit_phase3_20260712/` 和历史任务中，不删除、不改写、不解释成“当时也已完成”：

| 历史指标 | 历史值 | 当前处理 |
|---|---:|---|
| metadata_gap | 1853 | 旧审计模型快照 |
| pre_2020_weekly_missing | 34 | 旧审计模型快照 |
| actual contract gap | 45 | 旧固定 gap 口径，待 Audit V2 重算 |

## 当前边界

- 暂停基于旧 `1853 / 34 / 45` 数字的批量修复。
- 下一步先做全历史物理事实盘点与 Audit V2。
- 真实数据写入、DB/Profile binding apply、RQData 调用仍需显式批准。
- `quality_warning` 不升级为 `passed`。
- 不自动交易、不自动下单、不把提醒写成交易指令。
- WorkBuddy 控制面修复已合并，不再作为业务启动前置阻塞。

## 验收标准

```text
CANONICAL_OLD_AUDIT_MARKED_HISTORICAL
DATA_LAYER_REAUDIT_REQUIRED
```
