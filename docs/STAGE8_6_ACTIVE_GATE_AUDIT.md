# Stage 8.6 全品种 Active Gate 只读审计

更新时间：2026-07-10

## 1. 定位

Stage 8.6 是归一量化工作站全品种下载结果的 active Gate 只读审计层。核心目标：对 Cursor / 批处理已生成的 manifest、processed summary、PostgreSQL 登记和 canonical parquet 进行只读核对，输出分层报告，不调用 RQData、不写 parquet、不登记 DB、不修改 active 默认读取规则。

当前状态：代码级闭环已完成。

## 2. 审计器设计

### 输入

审计器只读取已有产物：

- `data/manifests/rqdata_*_v2_history_*.csv` — 主连 historical manifest
- `data/manifests/rqdata_actual_contract_bars_*.csv` — actual-contract manifest
- `data/processed/v1b/*/*_v2_parquet_*.json` — processed summary
- PostgreSQL `market_data_files` / `data_quality_reports` — DB 登记
- canonical parquet 文件 — DuckDB 核对 row_count / datetime 边界

### 输出

报告文件输出到 `data/reports/`：

| 文件 | 内容 |
|---|---|
| `stage8_6_active_gate_matrix.csv` | 全品种 × 全周期 active Gate 矩阵 |
| `stage8_6_product_summary.csv` | 按品种汇总 |
| `stage8_6_stage9_readiness.csv` | Stage 9 准入就绪状态 |
| `stage8_6_active_gate_summary.md` | 人类可读摘要 |

### 分层规则

| 层级 | 含义 |
|---|---|
| `active_passed` | manifest + DB + quality + DuckDB 核对全部通过 |
| `active_partial` | 部分周期通过，部分缺失或未通过 |
| `audit_pending` | manifest 存在但 DB 登记或 quality report 缺失 |
| `failed` | quality report 状态为 failed |
| `missing` | 无 manifest 或无 parquet |
| `stage9_blocked` | 未达到 Stage 9 准入要求 |

## 3. 审计命令

```bash
uv run --project services/quant-api python scripts/rqdata_full_universe_active_gate_audit.py \
  --products-file data/universe/full_products_90.txt \
  --profile stage8_6_1d_first \
  --output-dir data/reports
```

## 4. 当前 smoke 摘要

本轮只读 smoke 结果：

| 维度 | 数值 |
|---|---|
| 候选品种总数 | 90 |
| product active_passed | 82 |
| product active_partial | 8 |
| asset active_passed | 176 |
| asset audit_pending | 8 |
| asset failed | 0 |
| Stage 9 stage9_blocked | 90 |

说明：

- `active_passed=82` 表示 82 个品种当前 `1d` profile 全部通过 active Gate。
- `active_partial=8` 表示 8 个品种部分周期缺失或未通过。
- `stage9_blocked=90` 表示当前所有品种都未达到 Stage 9 准入要求（需要 actual-contract bars + trigger price 绑定）。
- 该报告为只读 smoke，不修改任何数据资产。

JM 最新主连六周期使用独立 profile：

```bash
uv run --project services/quant-api python scripts/rqdata_full_universe_active_gate_audit.py \
  --product jm \
  --profile jm_main_six_period_latest \
  --output-dir data/reports/jm_main_six_period_latest
```

当前结果为 1 个 product passed、6 个 main assets passed。该 profile 只审计最新 `jm.MAIN` 六周期，不把历史 actual-contract 片段混入六周期计数。

## 5. 安全边界

- 不调用 RQData。
- 不写 parquet / manifest / checksum。
- 不登记 `market_data_files` / `data_quality_reports`。
- 不修改 `MarketDataReader` 默认读取规则。
- 不接企业微信。
- 不修改策略逻辑、回测口径或 signal scanner。

## 6. 关键代码

| 文件 | 用途 |
|---|---|
| `services/quant-api/app/services/rqdata_ingest/full_universe_active_gate.py` | 审计器核心 |
| `scripts/rqdata_full_universe_active_gate_audit.py` | 审计 CLI |
| `services/quant-api/tests/test_full_universe_active_gate.py` | 审计器测试（7 passed） |

## 7. 未完成

- Cursor 全品种下载完成后运行最终只读审计。
- 根据审计结果决定哪些品种可进入 active 默认读取。
- `active_partial` 品种的缺失周期补齐。
- `audit_pending` 品种的 DB 登记和 quality report 补齐。
- `failed` 品种的根因排查和重下载。
