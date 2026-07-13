# TASK-2026-07-13-001：日线重复 K 根因修复（DATA-FINAL-002）

> **任务 ID**: DATA-FINAL-002  
> **风险**: R1（代码修改，不写 DB / Parquet）  
> **前置**: DATA-FINAL-001 GATE_PASSED ✅  
> **状态**: DEV_COMPLETE — 代码已实现，14/14 测试通过，待 Gate 验收  
> **生成**: WorkBuddy PM + 数据架构专家  
> **诊断报告**: `tasks/TASK-2026-07-09-003-daily-1d-duplicate-diagnosis.md`

---

## 1. 任务状态

DEV_COMPLETE — 代码已实现，14/14 测试通过，待 Gate 验收

## 2. 任务类型

数据层代码修复（R1）

- 关联：DATA-FINAL-001 诊断结论（first_duplicate_layer = manifest/active metadata）
- 是否允许进入代码开发阶段：**是**（仅限 quant-api Python + quant-web TypeScript，不碰 DB / Parquet / .env / 策略）
- **若根因需要 DB 修复**：当前 Task 只实现代码 + 生成 R2 候选，停止等待单独 DATA_WRITE Task

## 3. 参与角色

- 必须：PM、后端开发负责人、数据架构师、测试专家/QA Lead、安全与权限专家
- 可选：前端开发（涉及前端防御性校验）
- 不需要：产品、量化业务、策略研究、UX、DevOps、交付

## 4. 背景

DATA-FINAL-001 诊断确认：247 组 `(symbol, contract, period=1d)` 各有 ≥2 个 Parquet 文件同时以 `data_role='primary'` 注册。DuckDB `row_number()` 读时去重掩盖了重复，但未检测数据冲突——**同一 trading_day 在不同文件中 OHLCV 值不同时，会静默丢弃一条而不报错**。

## 5. 目标

1. 在 `MarketDataReader` 层增加 **跨文件冲突检测**：同一唯一键出现多条且 OHLCV 不同时，产生 conflict/quality error
2. 定义并文档化 historical 1d 唯一键 = `symbol + contract_role + trading_day + interval`
3. 定义并文档化 direct 1d / derived 1d / historical / live 优先级
4. API 暴露冲突信息（不静默吞掉）
5. 前端增加防御性唯一键校验 + 冲突告警 console 输出
6. 全链路回归测试

## 6. 不做事项

- ❌ 不写 DB（不执行 `duplicate_active_supersede.py --confirm`，留 R2 任务）
- ❌ 不覆盖 / 删除 / 修改任何 Parquet 文件
- ❌ 不改变策略交易规则 / 信号逻辑 / 回测引擎
- ❌ 不修改 `.env` / token / webhook
- ❌ 不 push / merge / deploy
- ❌ 前端去重不作为唯一修复手段（仅防御性）
- ❌ 不用 `SELECT DISTINCT` 或前端去重掩盖根因

## 7. 技术方案

### 7.1 唯一键定义（新增常量 + 文档）

```python
# market_data_reader.py 新增

def _contract_role(contract: str) -> str:
    """区分 dominant_main (.MAIN) 与 actual_contract。"""
    if contract and contract.upper().endswith(".MAIN"):
        return "dominant_main"
    return "actual_contract"

# historical 1d 唯一键 = symbol + contract_role + trading_day + interval
# 代码中 _dedupe_partition_column 已按 trading_day 分区，SQL where 已按 symbol/contract/period 过滤
# 无需修改分区列，但需增加文档注释明确此约束
```

### 7.2 数据源优先级定义（新增常量 + 文档）

```
优先级（高 → 低）：
1. direct 1d    — N/A（1d 不在 RQDATA_DIRECT_PERIODS 中，不存在直接来源）
2. historical   — Parquet 文件（data_role='primary'），通过 _find_files() 查询
3. derived 1d   — 从 1m 聚合（bar_aggregation.py），仅用于入库生成 Parquet，不直接被 API 查询
4. live 1d      — LiveAggregatedBar 表，仅实时路径使用，不与 historical 合并
```

**结论**：API 查询 1d 时只走 historical Parquet 路径，不存在多源合并。冲突检测只需在 historical 内部进行。

### 7.3 MarketDataReader — 跨文件冲突检测（核心修改）

**新增方法** `get_cross_file_conflicts()`：

```python
def get_cross_file_conflicts(
    self,
    symbol: str,
    contract: str,
    period: str,
    start: datetime,
    end: datetime,
    provider: str | None = None,
    data_role: str | None = None,
) -> list[dict[str, Any]]:
    """检测同一唯一键在多个文件中 OHLCV 值不同的冲突。

    返回每个冲突的: dedupe_key, occurrence_count, 
    conflicting_values (per file: open/high/low/close/volume/data_version/file_path)
    """
    files = self._find_files(symbol, contract, period, start, end, provider, data_role)
    if len(files) <= 1:
        return []

    dedupe_partition = self._dedupe_partition_column(period)
    # SQL: 按 dedupe_key 分组，检测 OHLCV 是否存在差异
    # having count(*) > 1 AND (distinct open > 1 OR distinct close > 1 OR ...)
    # 返回冲突明细
```

**修改 `load_bars()`**：
- 保持 `row_number()` 去重逻辑不变（仍返回去重后的 bars）
- 在返回前调用 `get_cross_file_conflicts()`
- 如果检测到冲突，记录 WARNING 级别日志（含冲突详情）
- **不阻断返回**（API 仍返回去重后的数据），但冲突信息需可通过 `get_quality_status()` 获取

**修改 `get_quality_status()`**：
- 新增 `cross_file_conflicts` 字段（int：冲突 trading_day 数量）
- 新增 `conflict_details` 字段（list：前 N 个冲突的详情）
- 当存在冲突时，status 降级为 `"warning"` 或 `"conflict"`

### 7.4 API 层 — 暴露冲突信息

**修改 `market_workbench.py::get_market_bars()`**：
- 调用 `get_cross_file_conflicts()`
- 将冲突信息附加到 `MarketBarsResponse` 的 quality 或新增 `conflicts` 字段
- 当存在冲突时，`message` 包含冲突告警文案

**修改 `schemas/market.py`**：
- `MarketBarsQuality` 新增 `cross_file_conflicts: int = 0`
- `MarketBarsQuality` 新增 `conflict_details: list[dict] | None = None`

### 7.5 前端 — 防御性校验 + 冲突告警

**修改 `barTime.ts::mergeBarsByPeriod()`**：
- 当 Map 中已有相同 key 的 bar 且 OHLCV 值不同时，输出 `console.warn()` 
- 保留后出现的 bar（与当前行为一致，但增加可见性）

**修改 `KlineChart.vue`**：
- 在 `render()` 函数中，检查 API 返回的 `quality.cross_file_conflicts`
- 如果 > 0，在图表上显示冲突告警提示（如顶部 banner 或 toast）

### 7.6 R2 候选任务（DB 修复，不在本 Task 执行）

本 Task 代码实现完成后，生成 R2 任务单：
- **R2-001**: 使用 `duplicate_active_supersede.py --confirm` 清理 247 组 manifest 重复
- **R2-002**: 在 `_apply_active_filters()` 或入库注册时增加唯一性约束检查（防止未来重复）

---

## 8. 修改文件清单

### 后端 Python（services/quant-api/）

| 文件 | 修改内容 |
|---|---|
| `app/services/market_data_reader.py` | 新增 `get_cross_file_conflicts()`；修改 `get_quality_status()` 增加 conflict 字段；增加唯一键 + 优先级文档注释 |
| `app/services/market_workbench.py` | 修改 `get_market_bars()` 调用冲突检测；将冲突信息附加到 response |
| `app/schemas/market.py` | `MarketBarsQuality` 新增 `cross_file_conflicts` + `conflict_details` 字段 |
| `app/api/market.py` | 无需修改（透传 schema 即可） |

### 前端 TypeScript（apps/quant-web/）

| 文件 | 修改内容 |
|---|---|
| `src/utils/barTime.ts` | `mergeBarsByPeriod()` 增加冲突检测 + console.warn |
| `src/components/kline/KlineChart.vue` | 检查 `quality.cross_file_conflicts`，显示冲突告警 |
| `src/types/market.ts` | `MarketBarsQuality` 类型增加 `cross_file_conflicts` 字段 |

### 测试文件（新增）

| 文件 | 测试内容 |
|---|---|
| `tests/test_market_data_reader.py` | 新增：① 多文件同值去重无冲突 ② 多文件异值产生冲突 ③ 1d 唯一键正确性 ④ 1m/5m/15m/30m/60m 回归不受影响 |
| `tests/test_market_data_api.py` | 新增：① API 返回 conflicts 字段 ② 冲突时 quality 状态降级 |
| `apps/quant-web/src/utils/__tests__/barTime.test.ts` | 新增：① 异值 bar 触发 console.warn ② 同值 bar 不触发 |
| `apps/quant-web/src/components/kline/__tests__/KlineChart.conflict.test.ts` | 新增：冲突告警 UI 展示 |

---

## 9. 冲突检测 SQL 设计

```sql
-- 检测同一 trading_day 在多文件中 OHLCV 不同的冲突
WITH grouped AS (
    SELECT
        {dedupe_partition} AS dedupe_key,
        COUNT(*) AS occurrence_count,
        COUNT(DISTINCT CAST(open AS VARCHAR)) AS distinct_open,
        COUNT(DISTINCT CAST(high AS VARCHAR)) AS distinct_high,
        COUNT(DISTINCT CAST(low AS VARCHAR)) AS distinct_low,
        COUNT(DISTINCT CAST(close AS VARCHAR)) AS distinct_close,
        COUNT(DISTINCT CAST(volume AS VARCHAR)) AS distinct_volume,
        MIN(open) AS min_open,
        MAX(open) AS max_open,
        MIN(close) AS min_close,
        MAX(close) AS max_close,
        MIN(volume) AS min_volume,
        MAX(volume) AS max_volume,
        LIST(DISTINCT data_version) AS data_versions,
        LIST(DISTINCT provider) AS providers
    FROM read_parquet({paths}, union_by_name = true)
    WHERE symbol = ?
      AND contract = ?
      AND period = ?
      AND datetime >= ?
      AND datetime <= ?
    GROUP BY {dedupe_partition}
    HAVING COUNT(*) > 1
)
SELECT * FROM grouped
WHERE distinct_open > 1
   OR distinct_high > 1
   OR distinct_low > 1
   OR distinct_close > 1
   OR distinct_volume > 1
ORDER BY dedupe_key
```

---

## 10. 测试清单

### 10.1 Reader 测试

| # | 测试名 | 验证点 |
|---|---|---|
| R1 | 多文件同值 → 无冲突 | 两个 Parquet 文件 trading_day 重叠且 OHLCV 完全一致 → `get_cross_file_conflicts()` 返回空列表 |
| R2 | 多文件异值 → 产生冲突 | 两个 Parquet 文件 trading_day 重叠但 close 不同 → 返回冲突列表含 dedupe_key, occurrence_count, 冲突值 |
| R3 | 单文件 → 无冲突 | 只有一个 Parquet 文件 → 返回空列表 |
| R4 | 1d 唯一键正确 | trading_day 相同但 contract 不同 → 不产生冲突（已被 where 过滤） |
| R5 | 1m 不受影响 | 1m 周期多文件 → 使用 datetime 分区，不影响 1d 逻辑 |
| R6 | 5m/15m/30m/60m 回归 | 各周期多文件 → 使用 datetime 分区，去重逻辑不变 |
| R7 | get_quality_status 含 conflicts | 冲突存在时 quality status = "conflict" 或 "warning"，cross_file_conflicts > 0 |
| R8 | load_bars 仍返回去重数据 | 冲突存在时 load_bars 仍返回唯一 bars（不阻断） |

### 10.2 API 测试

| # | 测试名 | 验证点 |
|---|---|---|
| A1 | API 返回 conflicts 字段 | GET /api/v1/market/bars → response.quality.cross_file_conflicts 存在 |
| A2 | 冲突时 message 含告警 | 冲突存在时 response.message 包含冲突提示 |
| A3 | 无冲突时字段为 0 | 无冲突时 cross_file_conflicts = 0 |

### 10.3 前端测试

| # | 测试名 | 验证点 |
|---|---|---|
| F1 | 异值 bar 触发 console.warn | mergeBarsByPeriod 遇到同 key 不同值 → console.warn 输出 |
| F2 | 同值 bar 不触发 warn | mergeBarsByPeriod 遇到同 key 同值 → 无 warn |
| F3 | 冲突告警 UI | quality.cross_file_conflicts > 0 → 图表显示冲突提示 |

### 10.4 回归测试

| # | 测试名 | 验证点 |
|---|---|---|
| G1 | 全周期回归 | 1m/5m/15m/30m/60m/1d/1w 各跑一次 load_bars → 行数和值不变 |
| G2 | 回测每日一根 | 用 1d bars 跑回测 → 每个 trading_day 只有一根 bar |

---

## 11. 验收标准（Gate）

| Gate 项 | 验证方法 | 通过标准 |
|---|---|---|
| API 每交易日一条 | GET /api/v1/market/bars?period=1d | 每个 trading_day 只返回 1 条 bar |
| Web 切换品种/周期/刷新后仍一条 | 浏览器操作 | 图表无重复 K 线 |
| 夜盘交易日正确 | 查询夜盘品种 1d | trading_day 映射正确（hour>=21 → date+1） |
| 冲突不静默吞掉 | 构造异值测试数据 | API 返回 conflict 信息，日志有 WARNING |
| 回测每日一根 | 回测引擎跑 1d | 日线回测无重复 bar |
| 无 console error | 浏览器 DevTools | 无 JS error（warn 可接受） |
| 1m~60m 不受影响 | 全周期回归测试 | 行数和值与修改前一致 |

---

## 12. 风险点

| 风险 | 等级 | 缓解 |
|---|---|---|
| 冲突检测 SQL 增加查询延迟 | 中 | 仅在多文件时触发（≤1 文件直接返回空）；可缓存 |
| DuckDB `LIST()` 函数兼容性 | 低 | DuckDB 0.10+ 原生支持；备选用 `string_agg` 或 Python 侧聚合 |
| 前端 console.warn 影响开发体验 | 低 | 仅在异值时触发，正常去重不触发 |
| schema 变更影响序列化 | 低 | 新字段有默认值，向后兼容 |

---

## 13. 护栏

- 本 Task **只修改代码 + 新增测试**，不执行 DB 写入
- 生成的 R2 候选任务单放 `tasks/TASK-2026-07-13-002-duplicate-supersede-r2.md`
- 所有修改限定在 quant-api + quant-web，不碰策略 / 回测引擎 / .env
- 不 push / merge / deploy
- 脚本默认 dry-run

---

## 14. Codex Plan Prompt（供 CodeBuddy 喂给 codex_plan.sh）

```
只读 Plan 任务：为 DATA-FINAL-002 日线重复 K 根因修复生成详细执行计划。

仓库：/Volumes/扩展盘/guiyi-parallel/data-final-closure

背景：DATA-FINAL-001 诊断确认 247 组 1d bars 有多个 primary Parquet 文件。
DuckDB row_number() 去重掩盖了重复，但未检测 OHLCV 冲突（同 trading_day 不同值时静默丢弃）。

需要 Plan 的修改：
1. app/services/market_data_reader.py:
   - 新增 get_cross_file_conflicts() 方法：检测同唯一键多文件 OHLCV 异值
   - 修改 get_quality_status()：新增 cross_file_conflicts + conflict_details 字段
   - 增加唯一键定义文档注释：historical 1d 唯一键 = symbol + contract_role + trading_day + interval
   - 增加数据源优先级文档注释：direct(N/A) > historical(Parquet) > derived(1m聚合) > live(LiveAggregatedBar)

2. app/services/market_workbench.py:
   - get_market_bars() 调用 get_cross_file_conflicts()
   - 冲突信息附加到 response.quality

3. app/schemas/market.py:
   - MarketBarsQuality 新增 cross_file_conflicts: int = 0
   - MarketBarsQuality 新增 conflict_details: list[dict] | None = None

4. apps/quant-web/src/utils/barTime.ts:
   - mergeBarsByPeriod() 检测同 key 异值 → console.warn

5. apps/quant-web/src/components/kline/KlineChart.vue:
   - 检查 quality.cross_file_conflicts > 0 → 显示告警

6. 测试：reader + API + frontend + 全周期回归

约束：
- 不修改 load_bars() 返回类型（仍返回 list[dict]）
- 不写 DB / Parquet / .env
- 不改变策略 / 回测逻辑
- 冲突检测不阻断数据返回（只报不阻）

请输出文件级修改清单、每个文件的具体改动点、新增方法签名、SQL 设计、测试用例清单。
```

---

## 15. Codex Dev Prompt（APPROVED_DEV 阶段启用）

```
开发任务：按已批准 Plan 实施 DATA-FINAL-002 代码修改。

仓库：/Volumes/扩展盘/guiyi-parallel/data-final-closure
工作目录：services/quant-api/ + apps/quant-web/

执行步骤：
1. 修改 market_data_reader.py：新增 get_cross_file_conflicts() + 修改 get_quality_status()
2. 修改 schemas/market.py：MarketBarsQuality 新增字段
3. 修改 market_workbench.py：get_market_bars() 接入冲突检测
4. 修改 barTime.ts：mergeBarsByPeriod() 增加异值检测
5. 修改 KlineChart.vue：冲突告警 UI
6. 新增测试文件
7. 运行全部测试确保通过

护栏：
- workspace-write only，不 push/merge/deploy
- 不碰 .env / token / webhook / 策略代码 / 回测引擎
- 不写 DB / Parquet
- 每个修改点有对应测试
```

---

## 16. 交付物

- 修改后的代码文件（见第 8 节清单）
- 新增测试文件 + 全部测试通过
- R2 候选任务单 `tasks/TASK-2026-07-13-002-duplicate-supersede-r2.md`
- 测试报告（含 API 样例、console 输出、浏览器截图说明）

---

## 17. R2 候选任务预览

> 本 Task 完成后生成正式 R2 任务单，此处仅预览

**R2-001**: 使用 `duplicate_active_supersede.py --confirm` 清理 247 组 manifest 重复
- 风险：R2（DB 写入）
- 前置：DATA-FINAL-002 代码已合并
- 操作：dry-run → 人工抽查 → --confirm 执行
- 验证：`_find_files()` 每组只返回 1 个文件

**R2-002**: 入库注册时增加唯一性约束
- 风险：R2（代码 + 可能 DB DDL）
- 前置：R2-001 完成
- 操作：在 `actual_contract_bars_pilot` 或入库管道注册 market_data_files 时，检查同 key 是否已有 primary 记录
