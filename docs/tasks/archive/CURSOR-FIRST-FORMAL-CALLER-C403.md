# CURSOR-FIRST-FORMAL-CALLER-C403

更新时间：2026-07-19

对应手册任务：`C4-03` / 原 `D4-03`

## 结论

状态：`COMPLETED / NO_FORMAL_INDICATOR_CALLER_MIGRATION_REQUIRED`

证据型 no-op：对照 C4-01 `caller_inventory.csv` 的 10 条 `formal_must_migrate`，无一同时满足手册低风险迁移条件。**未迁移任何 caller**，未改业务代码、策略参数、DB、Parquet、Profile binding、报告或 live。

未进入 `MIGRATION_BLOCKED_OUTPUT_DIFF`（未尝试替换，故无输出差异阻断）。Cursor Wave 可继续后续任务。

## 资格硬条件

必须同时满足：

```text
不依赖 report 14
不连接 live evaluator
不改变正式策略信号
已有 legacy golden vector
可逐 bar compare
修改范围小
```

禁止选择：JM V1-B、report 14 依赖路径、live evaluator、formal SignalEvent、无法逐 bar 对齐的 caller。

## 筛查表

| caller | 结论 | 原因 |
|---|---|---|
| `fastapi_su_bing_ema21` / `fastapi_su_bing_macd` / `fastapi_su_bing_atr` | 不合格 | 虽有 V1-D golden vector（`test_indicator_kernel_v1d_migration_vectors.py`），但接入 BacktestEngine + SignalScanner，会改正式策略/扫描信号路径 |
| `daily_ema21_macd_volume_*` | 不合格 | 正式 Backtest 策略；迁移即改报告交易路径 |
| `daily_score2of4_*` / `daily_trend_cross_score2` | 不合格 | 正式日线策略 / 复用 helper；非小范围展示迁移 |
| `backtest_review_kline_macd` | 不合格 | 不改策略信号，但缺与 Python kernel 的 lineage-bound legacy golden；合规需新后端 series API，超出单 caller 小改 |
| `shared_kline_atr` | 不合格 | 同上 |
| JM V1-B / live evaluator / Stage9 / report 14 | 禁止 | 手册明确禁止 |

已完成对照：Market EMA/MACD 已是 `formal_already_compliant`（V1-E），不在本任务迁移池。

## 未修改文件

本任务不修改：

```text
services/quant-api/app/strategy/**
packages/quant-core/guiyi_quant/strategies/**
apps/quant-web/**
live_signal_evaluator.py
DB / Parquet / Profile binding / report 14
```

## 验证

```bash
git diff --check
```

无业务代码变更，不跑迁移回归测试。

## 后续建议（不在本任务执行）

真迁移应另开独立 Gate：

1. Backtest/Review 展示 API + Profile/indicator lineage；或
2. 单日线策略版本升级 + 全量 trade 回归。

二者均属 Codex Wave / 正式验收范围，不适合本 Cursor 条件迁移槽位。

## 下一入口

Cursor Wave `C4-04`（或手册下一 Cursor 任务）。
