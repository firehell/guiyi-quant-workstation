# CURSOR-INDICATOR-CALLER-INVENTORY-C401

生成时间：2026-07-19

对应手册任务：`C4-01` / 原 `D4-01`

基线：`cursor/v1-indicator-strategy-prep`（承接 `0116caa0` C0-01 后）

状态：`CURSOR_INDICATOR_CALLERS_AUDITED`

性质：只读代码、契约、D4-00 证据与测试审计；未修改业务代码、数据库、Parquet、Profile binding、历史报告、策略参数、live runtime 或 Web。

前置 D4-00 证据（位于 `data/reports/indicator_contract_v1/`）：

| 标签 | 仓库状态 |
|---|---|
| `HTDY_SOURCE_FORMULA_FROZEN` | `EVIDENCE_CONFIRMED_NOT_GATE` |
| `HTDY_ORIGINAL_STRICT_BOUNDARY_DEFINED` | `EVIDENCE_CONFIRMED_NOT_GATE` |
| `HTDY_XMA_SEMANTICS_AUDITED` | **未达成**；禁止宣称 |
| 最终 Gate | `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED` |

本盘点在上述证据可复查前提下继续；HTDY readiness 行仅 provisional，不构成 Stage 5 正式准入。

## 1. 结论

相对 2026-07-18 的 33 条盘点复验后，当前识别 **36** 条指标调用路径（+3 NEW experiment，1 CHANGED 锚点）：

| 分类 | 数量 | 结论 |
|---|---:|---|
| `formal_already_compliant` | 4 | Market EMA、Market MACD 及其 Web API 渲染路径已使用公共 Python 内核和同 bars lineage。 |
| `formal_must_migrate` | 10 | 通用 FastAPI 策略、正式日线策略、Backtest/Review 的本地 MACD/ATR 展示仍依赖重复实现。 |
| `frozen_legacy_keep` | 7 | report 14、JM V1-B、historical scanner、live evaluator、Stage 9 replay 及旧 short-hold 必须保持版本化语义。 |
| `observation_only` | 5 | Market fallback/draft 与 Web HTDY original 只能用于展示或人工观察。 |
| `experiment_only` | 9 | vn.py 草稿、HTDY original/strict 实验、offline eval、RQAlpha PoC、research-only report test 不构成正式 Gate。 |
| `manual_review` | 1 | HTDY strict core 已无已知未来引用，但 D4-00 unresolved 且尚未证明 Profile-bound formal report 闭环。 |
| `remove_or_block` | 0 | 未发现 original XMA 已进入正式回测、Signal、live 或通知链路；现有阻断必须保留。 |

核心判断不变：公共内核已存在，但“所有正式调用方已统一”不成立。EMA10/21/60 registry 状态可信；MACD/ATR 仍是 `v1-draft` 且未注册；JM V1-B 必须冻结；HTDY strict 是 formal candidate 预构建输入，不是已通过的 formal indicator/report。

## 2. 七项重点确认（2026-07-19 复验）

### 2.1 Market research EMA/MACD 是否真实调用 Python 公共内核

**是。**

- EMA API：`services/quant-api/app/services/market_indicators.py` 导入 `ema_series/get_indicator`，以 `sma_window` 调用公共函数；research 要求 bars 的 `expected_market_data_file_id` 与 `expected_lineage_token`。
- MACD API：`services/quant-api/app/services/market_workbench.py` 固定 `12/26/9 + sma_window + histogram_scale=2`，导入公共 `macd_series`。
- Web 在 Market 路径校验 EMA/MACD 与 bars 的 lineage token 后才接受结果。

限制：MACD 公共函数仍为 `v1-draft`，不在 registry；compliant 指调用和 lineage 路径合规，不等于 MACD 已 validated。

### 2.2 ATR 是否仍仅前端/策略本地计算

**是。** 当前没有 Market ATR 后端 API，生产调用方未导入公共 `atr_series()`。

- Web ATR：`apps/quant-web/src/utils/indicators.ts` Wilder + SMA seed。
- 共享 `KlineChart` 对 Market、Backtest、Review 本地计算 ATR14。
- FastAPI `su_bing_ema21`：Wilder first-TR。
- quant-core / JM V1-B：EMA(first TR) ATR。
- 公共 `atr_series()` 支持三种兼容 policy，版本仍 `v1-draft`。

### 2.3 JM V1-B 和 report 14 使用的 policy

report 14 冻结为 `jm_v1b_daily_direction_fast_entry / v1b.0`（见 `configs/oos/jm_v1b_report14_frozen.json`）：

- EMA21、MACD：`first_value` recursive EMA。
- ATR14：`ema_first_tr`。
- 日线方向只用早于当前交易日的 confirmed daily bars。

结论：`frozen_legacy_keep`。公共内核可复刻指定 vector，也不能在 `v1b.0` 静默替换。

### 2.4 live evaluator 是否继承 JM V1-B

**是。** `live_signal_evaluator.py` 直接导入并调用 JM V1-B 的 `calculate_indicators` / `confirmed_daily_direction_snapshot` / `decide_entry`；输入由 confirmed-only live reader 提供。任何指标迁移必须从新策略版本开始。不声明 live runtime 或通知 Ready。

### 2.5 HTDY original 与 strict 是否完全隔离

**实现和能力边界已隔离；D4-00 进一步冻结边界。**

| 能力 | original_v0 | strict_v1 |
|---|---|---|
| 实现 | Web `indicators.ts` + PoC `htdy_original_core.py` | quant-core strategy + experiment `htdy_strict_core.py` |
| 平滑 | 双层 XMA，仓库窗口 `[-13,+11]` | trailing double EMA（因果改写） |
| 未来引用 | 是 | future-tail 测试覆盖，未发现读未来 bar |
| formal 链路 | 禁止 | candidate / research_only / offline 仅 |

未发现 original XMA 被 strict strategy、BacktestService、historical scanner、live evaluator 或通知链路导入。Web 主图 HTDY `available=false`。

### 2.6 HTDY strict formal candidate 是否可被 BacktestService 消费

1. **结构上可加载**（strategy class path 可解析）。
2. **正式消费 Gate 未证明**：持久化测试使用低层 `create_task(..., research_only=True)`，不是 `create_formal_task()`；dry-run 报告 `backtest_capable=false`。
3. **D4-00**：最终 Gate `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，禁止宣称 `HTDY_STRICT_READY_FOR_FORMAL_BACKTEST`。

### 2.7 未声明未来引用、partial bar 或前端独立正式算法

- 已知未来引用仅 HTDY original XMA；保持 observation-only。
- D4-00 numeric oracle 确认仓库 XMA(25) 相对对称 `[-12,+12]` 存在 off-by-one，禁止标为 Tongdaxin-equivalent。
- 前端仍有独立算法：MACD fallback、Backtest/Review MACD、共享 ATR、`strategyStatus` 本地 EMA21、`riskDraft` 本地 ATR14。

## 3. 本轮相对基线的变更

| 类型 | caller_id | 说明 |
|---|---|---|
| CHANGED | `market_trend_draft_ema21` | 锚点由 `trendStatus` 更名为 `strategyStatus`；policy 不变 |
| NEW | `htdy_experiment_strict_core` | `experiments/htdy_indicator/htdy_strict_core.py` |
| NEW | `htdy_offline_candidate_eval` | `experiments/htdy_indicator/offline_candidate_eval.py` |
| NEW | `rqalpha_daily_ema21_macd_poc` | `experiments/rqalpha_su_bing_jm_daily/...` |
| REMOVED | — | 无 |

`signal_scanner` / generic `BacktestEngine` 通过 `fastapi_su_bing_*` 同一 helper 消费，不另计 caller。

## 4. Registry 与文档漂移

- 仅 EMA10/21/60 为 `validated`（`sma_window`）。
- MACD / ATR：`v1-draft`，未注册。
- `huo_tian_da_you`：`observation_only`（original）。
- HTDY strict：未进入 indicator registry。
- `docs/INDICATOR_KERNEL.md` §5.2 已记录 D4-00 状态；本报告补足 36 条调用路径。

## 5. 风险分级

### P0

- 禁止 HTDY original XMA 进入正式报告、Signal、live、提醒或通知。
- 禁止在 `jm_v1b_daily_direction_fast_entry / v1b.0` 静默替换 EMA/MACD/ATR。
- 禁止把 HTDY research-only / offline eval 表述为 formal Gate 已通过。
- 禁止宣称 `HTDY_XMA_SEMANTICS_AUDITED` 或 Tongdaxin-equivalent。

### P1

- Backtest/Review 共享图表 MACD/ATR 需 versioned backend series，或明确降级 observation-only。
- FastAPI 通用策略与正式日线策略逐调用方迁移，并在 snapshot 记录 indicator policy/version。
- MACD/ATR 冻结后才能进 registry。

### P2

- Market `strategyStatus` / `riskDraft` 可改为复用后端指标。
- TypeScript fallback 与 Python kernel 共享 golden fixture，但 fallback 不得成为正式证据源。

## 6. 建议顺序（Cursor Wave 后续）

1. `C4-02`：冻结 EMA/MACD/ATR policy 与 registry 状态模型（文档/代码契约，不强行迁移）。
2. `C4-03`：低风险 formal caller 条件迁移或明确 observation 降级。
3. `C4-04` / HTDY strict 预构建：只读 preflight 与申请包草案；不写正式报告。
4. JM V1-B 继续冻结；Codex Wave 再承担正式 Gate / OOS / T3/T4。

## 7. 产物

```text
data/reports/indicator_contract_v1/caller_inventory.csv
data/reports/indicator_contract_v1/policy_matrix.csv
data/reports/indicator_contract_v1/INDICATOR_CALLER_AUDIT.md
```

## 8. Gate

```text
CURSOR_INDICATOR_CALLERS_AUDITED
```

不证明：

```text
MACD_ATR_VALIDATED
INDICATOR_CALLERS_MIGRATED
HTDY_XMA_SEMANTICS_AUDITED
HTDY_STRICT_READY_FOR_FORMAL_BACKTEST
HTDY_FORMAL_REPORT_READY
OOS_READY
LIVE_READY
QYWX_READY
```

## 9. C4-03 eligibility（2026-07-19）

任务：`CURSOR-FIRST-FORMAL-CALLER-C403`

结论：`NO_FORMAL_INDICATOR_CALLER_MIGRATION_REQUIRED`。

C4-01 的 10 条 `formal_must_migrate` 经手册低风险条件筛查后全部不合格：策略/扫描路径会改正式信号；Backtest/Review 前端展示缺 lineage-bound Python golden 且需新后端 API；JM V1-B / live / report 14 明确禁止。本轮未改业务代码，也未改写本 CSV 分类。证据：`docs/tasks/CURSOR-FIRST-FORMAL-CALLER-C403.md`。
