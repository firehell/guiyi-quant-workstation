# TASK-2026-07-09-003：日线重复 K 只读诊断报告

> **任务 ID**: DATA-FINAL-001（Step C01）
> **风险**: R0
> **类型**: 只读审计 / 诊断
> **前置**: DATA-FINAL-BOOTSTRAP ✅
> **状态**: DIAGNOSIS_COMPLETE
> **生成**: WorkBuddy PM + 数据审计专家

---

## 诊断摘要

> **首次重复层（first_duplicate_layer）: `manifest / active metadata`**
> 两个独立的 RQData 入库运行，为同一 `(symbol, contract, period=1d)` 生成了时间范围重叠的 Parquet 文件，
> 且均以 `data_role='primary'` 注册到 `market_data_files` 表。DuckDB 读时去重和前端 Map 去重掩盖了根因，
> 但并未消除 manifest 层的冗余。

---

## 九项必检结果

### 1. Parquet 物理重复

| 字段 | 值 |
|---|---|
| **是否发现** | **是：247 组物理重复** |
| **样本** | RR2005 真实合约：文件 A（2019-12-17 ~ 2020-03-26，66 行）与文件 B（2020-01-02 ~ 2020-03-26，55 行）重叠 55 个 trading_day |
| **数值一致性** | 重叠的 55 个 trading_day 的 OHLCV **完全一致**（同一数据源、同一聚合逻辑、不同入库批次） |
| **数据源** | 全部 4589 个活跃 primary 1d 文件 provider = `rqdata` |
| **文件级质量** | quality 系统 `duplicated_bars` 字段在所有 quality_report 记录中均为 0（因为 quality 检查仅限单文件内部） |
| **物理根源** | `jm_v2_parquet.py` 或 `actual_contract_bars_pilot` 两次运行写入重叠时间段 → 两个 Parquet 文件均注册 primary |

### 2. 直接 1d vs 派生 1d 同时活跃

| 字段 | 值 |
|---|---|
| **是否发现** | **否：不存在 direct vs derived 冲突** |
| **依据** | `RQDATA_DIRECT_PERIODS = ("1w", "1m")` → **1d 不是 RQData 直接周期**，全部 1d 数据均从 1m 聚合 |
| **聚合链** | `bar_aggregation.py::_aggregate_daily_bars()` → group by `(contract, trading_day)` → OHLCV 聚合 |
| **状态** | 不存在"直接 1d 与聚合 1d 并存的冲突场景"；重复来自同一聚合链的两次入库 |

### 3. 多条逻辑 active 记录

| 字段 | 值 |
|---|---|
| **是否发现** | **是：247 组中每组 ≥2 条 primary 记录** |
| **数据版本分布** | 4436 条 `rq_acb_*`（真实合约 bars，含重复），153 条 `rqdata_*_standard_*`（标准主连系列） |
| **交叉情况** | **0 组同时含 rq_acb 和 rqdata_standard** → 同组内数据版本一致，纯粹是两次独立入库 |
| **分组详情** | 184 组 rq_acb 文件重叠，63 组 rqdata_standard 文件重叠 |
| **允许条件** | `_apply_active_filters()` 仅检查 `provider IN (local_parquet, rqdata)` + `data_role='primary'`，未限制同 key 只能有一条 active |
| **现存工具** | `duplicate_active_supersede.py` 已实现「检测 → 标记 superseded」逻辑，但 **尚未对当前 247 组执行** |

### 4. SQL / Reader 多源 UNION

| 字段 | 值 |
|---|---|
| **是否发生** | **是：DuckDB 同时 UNION 多个 Parquet 文件** |
| **机制** | `MarketDataReader.load_bars()` → `_find_files()` 返回所有匹配的 primary 文件 → `read_parquet(paths, union_by_name=true)` |
| **后果** | DuckDB 扫描时，每个 `trading_day` 出现两次（每个 Parquet 各一次）→ 扫描行数翻倍 |
| **掩盖** | `row_number() over (partition by coalesce(trading_day, datetime) order by provider preference)` 窗口函数做了读时去重 → **API 不返回重复行** |

### 5. 历史 vs 实时重复

| 字段 | 值 |
|---|---|
| **是否发生** | **否：1d 不存在 historical-live 重复** |
| **实时路径** | `LiveMultiTfAggregationService` 支持 1d 聚合（`SUPPORTED_PERIODS` 含 "1d"），写入 `LiveAggregatedBar` 表 |
| **API 路径** | `MarketDataReader.load_bars()` 只读 Parquet（历史），**不合并 live 数据** |
| **收盘归档** | `AfterMarketArchiveService` → `run_actual_contract_bars_pilot_write()` → 走标准入库管道生成 Parquet → 注册 market_data_files |
| **结论** | Live 1d bars 存在于 `LiveAggregatedBar` 表中，但与 API 返回的历史 1d 走不同路径，无合并重复 |

### 6. API 原始响应中出现次数

| 字段 | 值 |
|---|---|
| **是否出现** | **否：API 不返回重复** |
| **实测** | `load_bars(rr.RR2005, 1d, 2020-01-01 → 2020-04-01)` → 返回 **55 bars**，0 重复 |
| **原因** | DuckDB `row_number()` partition by `trading_day` 在查询时去重 |
| **验证** | `_find_files()` 返回 2 个 Parquet 文件，但 `load_bars()` 输出唯一 trading_day |

### 7. 前端 refresh / watch / append / setData

| 字段 | 值 |
|---|---|
| **是否出现** | **否：前端也有安全网** |
| **机制** | `barTime.ts::canonicalBarTimeKey()` 对日线使用 `trading_day` 作为去重键 |
| **机制** | `mergeBarsByPeriod()` → Map-based 去重，同一 trading_day 只保留最后出现（最大索引）的 bar |
| **结论** | 即使 API 不做去重，前端 `mergeBarsByPeriod` 也能拦截重复 → **双重掩盖** |

### 8. UTC / 本地时间 / trading_day 映射

| 字段 | 值 |
|---|---|
| **是否为重复根因** | **否** |
| **时间戳** | Parquet datetime 列为 naive（无时区），标记为 `"naive_local_exchange_time"` |
| **trading_day 生成** | `_trading_day_series()`：优先使用 RQData 返回的 `trading_date` 列；fallback 为 `datetime.hour >= 21 → date + 1 day` |
| **去重键** | `_dedupe_partition_column("1d")` = `coalesce(cast(trading_day as varchar), cast(datetime as varchar))` — 以 trading_day 为准 |
| **一致性** | 两个重叠文件中同一 trading_day 的 datetime 和 trading_day 值完全一致 → UTC 映射不是重复来源 |

### 9. 夜盘 trading_day 处理

| 字段 | 值 |
|---|---|
| **是否为重复根因** | **否** |
| **机制** | `TradingSessionClock.windows_for_trading_day()`：夜盘 sessions（start >= 20:00 或 crosses_midnight）使用 `previous_trading_day` 作为日历锚点 |
| **trading_day 赋值** | 夜盘数据的 `trading_day` 按"业务日期 = 次一交易日"规则赋值（hour >= 21 → date + 1），与国内期货市场惯例一致 |
| **对去重影响** | 同一交易日的数据在两个文件中 trading_day 相同 → DuckDB partition by trading_day 正确将二者归入同一分区 → 去重生效 |
| **结论** | 夜盘映射逻辑正确，未引入假性不等值导致去重失效 |

---

## 全链路数据流追踪

```
┌─────────────────────────────────────────────────────────────┐
│  入库阶段 (INGEST)                                          │
│                                                             │
│  RQData API (get_price 1m)                                  │
│       ↓                                                     │
│  jm_v2_parquet.py / actual_contract_bars_pilot              │
│       ↓                                                     │
│  bar_aggregation.py::_aggregate_daily_bars()                │
│    group by (contract, trading_day) → 1d OHLCV             │
│       ↓                                                     │
│  写入 Parquet: RR2005_1d_20191217_20200326.parquet         │
│  注册 market_data_files: data_role='primary'  ← 文件 A     │
│                                                             │
│  ... 另一次入库运行（可能覆盖范围不同） ...                   │
│                                                             │
│  RQData API (get_price 1m)                                  │
│       ↓                                                     │
│  同样的聚合链                                                │
│       ↓                                                     │
│  写入 Parquet: RR2005_1d_20200102_20200326.parquet         │
│  注册 market_data_files: data_role='primary'  ← 文件 B     │
│                                                             │
│  ⚠️ 文件 A 和文件 B 同时为 primary → manifest 层重复        │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  读取阶段 (READ)                                            │
│                                                             │
│  MarketDataReader._find_files() → 返回 [文件A, 文件B]       │
│                                                             │
│  DuckDB: read_parquet([A, B], union_by_name=true)           │
│    → 55 个 trading_day 各出现 2 次                          │
│                                                             │
│  row_number() partition by trading_day → 每 trading_day    │
│    保留 provider preference 最高的 1 行 (rqdata priority)  │
│                                                             │
│  → 输出 55 条唯一 bar（去重生效）                            │
│  ⚠️ 但 DuckDB 扫描了 110 行（浪费 50% I/O）                │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  API 阶段                                                   │
│                                                             │
│  /api/v1/market/bars → get_market_bars() → load_bars()     │
│  → 返回 55 bars，无重复 ✅                                  │
│  但 _find_files() 返回 2 文件（冗余 metadata）              │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  前端阶段                                                   │
│                                                             │
│  KlineChart.vue 接收 bars → mergeBarsByPeriod()            │
│  canonicalBarTimeKey() 对 1d 使用 trading_day 去重键        │
│  → 即使 API 返回重复，前端也会去重 ✅                        │
│                                                             │
│  实际渲染：55 根日线 K 线，无重复 ✅                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 出口 Gate 汇总

| 字段 | 值 |
|---|---|
| **symbol** | RR2005（样本）/ 全量 247 组覆盖多种品种 |
| **contract_role** | `actual_contract`（真实合约，非 .MAIN 主连） |
| **trading_day** | 2020-01-02 ~ 2020-03-26（55 个重叠交易日，样本） |
| **timestamp / datetime** | naive local exchange time，两个文件一致 |
| **data_version** | `rq_acb_*`（184 组）/ `rqdata_*_standard_*`（63 组） |
| **source** | `rqdata`（100%），provider = rqdata，所有文件 |
| **physical_occurrence** | **是：247 组，每组 ≥2 个 Parquet 文件重叠** |
| **api_occurrence** | **否：DuckDB `row_number()` partition by trading_day 掩盖** |
| **frontend_occurrence** | **否：`mergeBarsByPeriod()` Map 去重掩盖** |
| **first_duplicate_layer** | **`manifest / active metadata`** — `data_role='primary'` 允许多条同 key 记录同时活跃 |
| **impact** | DuckDB 扫描行数翻倍（I/O 浪费）；metadata 表冗余；manifest 不精确；但不影响最终图表渲染 |

---

## 已排查但排除的根因假说

| 假说 | 排除理由 |
|---|---|
| direct-1d 与 derived-1d 同时活跃 | `RQDATA_DIRECT_PERIODS` 不含 1d，不存在 direct 来源 |
| historical 与 live 重复 | API 不合并 live 数据；live 1d 存在另一张表 (`LiveAggregatedBar`) |
| UTC 与本地时间映射错误 | 两个文件 datetime/trading_day 完全一致，未产生假性不等值 |
| 夜盘 trading_day 赋值不同 | 夜盘映射逻辑一致（hour>=21 → date+1），同日期值相同 |
| quality 系统已检测但未处理 | quality 只检查单文件内重复，`duplicated_bars` 整表为 0 |
| DuckDB 去重失效 | `row_number()` 正确执行，partition by trading_day 能正确合并 |
| 前端未去重 | `mergeBarsByPeriod` 存在且有效 |

---

## 已确认根因 + 已有修复路径

### 根因

**`_apply_active_filters()` 的契约过于宽松**：仅要求 `data_role='primary'` + `provider IN ('rqdata', 'local_parquet')`，不要求同一 `(symbol, contract, period)` 组合下 **最多只有一条 primary 记录**。

两次独立的 RQData 入库（可能为不同目的，如初始全量下载 + 增量补全）生成的 Parquet 文件均以 `data_role='primary'` 注册，形成 manifest 层重复。

### 已有修复路径（无需新开发）

`duplicate_active_supersede.py` 已实现完整的检测与修复逻辑：
- `build_duplicate_active_assets()` 检测重复组 → 匹配当前的 247 组
- `_pick_current()` 按覆盖范围选择保留哪个文件（最宽的 start/end）
- `--confirm` 模式将多余记录标记 `data_role='superseded'`

### 建议修复顺序

1. **dry-run**：运行 `duplicate_active_supersede.py` 不带 `--confirm`，确认 247 组的候选决策
2. **人工抽查**：抽查 5-10 组，确认 `_pick_current()` 选择的保留文件确实覆盖更广
3. **--confirm 执行**：标记多余记录为 `superseded`
4. **验证**：确认 `_find_files()` 每组只返回 1 个文件，`load_bars()` 数据不变

### 防御性增强（可选）

`_apply_active_filters()` 不修改也能正常工作（当前依赖 DuckDB 读时去重）。如果希望 manifest 层主动拒绝，可在注册时加唯一约束检查。但这属于优化而非紧急修复。

---

## 附录：诊断执行明细

| 步骤 | 方法 | 结果 |
|---|---|---|
| 代码结构探查 | 读取全部 pipeline 文件（Reader / Aggregation / API / Frontend） | 全链路追踪完成 |
| DB 查询 | `SELECT symbol, contract, period, COUNT(*) FROM market_data_files WHERE data_role='primary' AND period='1d' GROUP BY ... HAVING COUNT(*) > 1` | 247 组 |
| DB 深度分析 | date range overlap、data_version 分组、quality report 交叉 | 0 组 cross-version，0 quality 告警 |
| Parquet 物理检查 | DuckDB 直接读取两个重叠文件 → 对比 OHLCV | 完全相同 |
| API 行为验证 | `load_bars()` 实际调用 → 检查返回行数 | 正确去重 |
| 前端代码审查 | `barTime.ts`, `KlineChart.vue` | 去重存在且有效 |
| 实时路径检查 | `LiveMultiTfAggregationService`, `AfterMarketArchiveService` | 不参与 API 历史查询 |
| 时区/夜盘检查 | `trading_session_clock.py`, `jm_v2_parquet.py::_trading_day_series()` | 映射正确 |

---

> **本诊断报告为只读审计产物，未修改任何代码、数据库或 Parquet 文件。**
> **下一步建议**：进入 Step C02（受控修复），使用 `duplicate_active_supersede.py --confirm` 清理 247 组 manifest 重复。
