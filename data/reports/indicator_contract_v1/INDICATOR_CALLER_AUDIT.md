# INDICATOR-CALLER-INVENTORY-401

生成时间：2026-07-18

基线：`main@bce608c7` / `codex/v1-indicator-contract`

状态：`INDICATOR_CALLERS_AUDITED`

性质：只读代码、契约与测试审计；未修改业务代码、数据库、Parquet、Profile binding、历史报告、策略参数、live runtime 或 Web。

## 1. 结论

本次从当前代码重新识别出 33 条指标调用路径：

| 分类 | 数量 | 结论 |
|---|---:|---|
| `formal_already_compliant` | 4 | Market EMA、Market MACD 及其 Web API 渲染路径已使用公共 Python 内核和同 bars lineage。 |
| `formal_must_migrate` | 10 | 通用 FastAPI 策略、正式日线策略、Backtest/Review 的本地 MACD/ATR 展示仍依赖重复实现。 |
| `frozen_legacy_keep` | 7 | report 14、JM V1-B、historical scanner、live evaluator、Stage 9 replay及旧 short-hold 必须保持版本化语义。 |
| `observation_only` | 5 | Market fallback/draft 与 Web HTDY original 只能用于展示或人工观察。 |
| `experiment_only` | 6 | vn.py 草稿、HTDY original PoC、strict dry-run 和 research-only report test 不构成正式 Gate。 |
| `manual_review` | 1 | HTDY strict core 已无已知未来引用，但尚未证明 Profile-bound formal report 闭环。 |
| `remove_or_block` | 0 | 未发现 original XMA 已进入正式回测、Signal、live 或通知链路；现有阻断必须保留。 |

核心判断：公共内核已存在，但“所有正式调用方已统一”不成立。EMA10/21/60 registry 状态可信；MACD/ATR 仍是 `v1-draft` 且未注册；JM V1-B 必须冻结；HTDY strict 是值得进入后续 Gate 的候选，不是已经通过的 formal indicator/report。

## 2. 七项重点确认

### 2.1 Market research EMA/MACD 是否真实调用 Python 公共内核

**是。**

- EMA API 在 `services/quant-api/app/services/market_indicators.py:44-45` 导入 `ema_series/get_indicator`，在 `:104-113` 以 `sma_window` 调用公共函数。
- research 模式要求 bars 的 `expected_market_data_file_id` 与 `expected_lineage_token`，见同文件 `:68-90`。
- MACD API 在 `services/quant-api/app/services/market_workbench.py:401-410` 固定 `12/26/9 + sma_window + histogram_scale=2`，并在 `:431-434` 导入公共 `macd_series`。
- Web 在 `apps/quant-web/src/pages/market/chart.vue:793-798` 和 `:812-817` 校验 EMA/MACD 与 bars 的 lineage token 后才接受结果。

限制：MACD 公共函数仍为 `v1-draft`，不在 registry；因此这里的 compliant 指“调用和 lineage 路径合规”，不等于 MACD 已被 registry 定级为 validated。

### 2.2 ATR 是否仍仅前端/策略本地计算

**是。** 当前没有 Market ATR 后端 API，也没有生产调用方导入公共 `atr_series()`。

- Web ATR 为 `apps/quant-web/src/utils/indicators.ts:201-218` 的 Wilder + SMA seed。
- 共享 `KlineChart` 在 `:491` 和 `:634-636` 对 Market、Backtest、Review 输入 bars 本地计算 ATR14。
- FastAPI `su_bing_ema21` 在 `services/quant-api/app/strategy/su_bing_ema21.py:490-503` 使用 Wilder first-TR。
- quant-core `su_bing_ema21` 和 JM V1-B 使用 EMA(first TR) ATR，分别见 `packages/quant-core/guiyi_quant/strategies/su_bing_ema21/vnpy_strategy.py:296-300` 与 `jm_v1b_daily_direction_fast_entry/vnpy_strategy.py:630-640`。
- 公共 `atr_series()` 已支持三种兼容 policy，但版本仍是 `v1-draft`，见 `packages/quant-core/guiyi_quant/indicators/atr.py:9-26`。

### 2.3 JM V1-B 和 report 14 使用的 policy

report 14 冻结为：

```text
strategy_code=jm_v1b_daily_direction_fast_entry
strategy_version=v1b.0
entry_interval=15m
data_source=local_parquet
data_role=primary
quality_status=passed
execution_timing=next_bar_open
```

证据为 `configs/oos/jm_v1b_report14_frozen.json:5-20`。其指标 policy 是：

- EMA21、MACD fast/slow/DEA：`first_value` recursive EMA；源码 `jm_v1b_daily_direction_fast_entry/vnpy_strategy.py:393-403` 与 `:622-627`。
- MACD histogram 不作为独立输出；决策使用 DIF/DEA 交叉。
- ATR14：对 TR 使用 `first_value` recursive EMA，即 `ema_first_tr`；源码 `:630-640`。
- 日线方向只使用交易日早于当前交易日的 confirmed daily bars；源码 `:475-509`。
- 默认周期为 EMA21、MACD 12/26/9、ATR14；源码 `config_schema.py:10-45`。

结论：report 14 与 `v1b.0` 必须归类为 `frozen_legacy_keep`。公共内核虽能复刻指定 vector，也不能在原版本中静默替换。

### 2.4 live evaluator 是否继承 JM V1-B

**是，直接导入同一 helper。**

- `live_signal_evaluator.py:69-78` 导入 JM V1-B 的 `calculate_indicators`、`confirmed_daily_direction_snapshot`、`decide_entry`。
- `:207-229` 直接调用这些函数。
- `LiveMarketReader` 只向图表/evaluator 返回 `bar_status=confirmed` 且非 failed 的行，见 `services/quant-api/app/services/live_market_reader.py:71-93`。
- evaluator 的 formal lineage 使用 `source_mode=live_confirmed` 并保存 bar status、revision、confirmed time，见 `live_signal_evaluator.py:258-279`。

因此 live evaluator 的任何指标迁移都必须从 JM V1-B 新策略版本开始，不能单独替换 evaluator helper。本结论不声明 live runtime 或通知 Ready。

### 2.5 HTDY original 与 strict 是否完全隔离

**实现和能力边界已隔离。**

- original Web 公式仍使用 centered XMA，见 `apps/quant-web/src/utils/indicators.ts:60-90` 和 `:235-245`；registry 将其标记为 `observation_only / repainting_risk=known / backtest=false / live=false / alert=false`，见 `packages/quant-core/guiyi_quant/indicators/registry.py:41-63`。
- Web 主图配置中的 HTDY 为 `available=false`，见 `apps/quant-web/src/utils/mainIndicators.ts:71-84`。
- strict 使用独立版本 `huotian_dayou_strict_v1`、独立策略代码和 candidate version，见 `packages/quant-core/guiyi_quant/strategies/huotian_dayou_strict/config_schema.py:7-12`。
- strict 用 trailing double EMA 替换 XMA，见 `vnpy_strategy.py:659-705` 与 `:778-802`；future-tail 测试覆盖于 `test_htdy_formal_backtest_candidate.py:140-168`。

未发现 original XMA 被 strict strategy、BacktestService、historical scanner、live evaluator 或通知链路导入。

### 2.6 HTDY strict formal candidate 是否可被 BacktestService 消费

结论分两层：

1. **结构上可加载。** `STRATEGY_CLASS_PATH` 可由通用 strategy loader 解析，测试见 `test_htdy_formal_backtest_candidate.py:133-137`。
2. **正式消费 Gate 未证明。** 当前唯一持久化测试在 `:281-338` 调用低层 `BacktestService.create_task()` 且明确 `research_only=True`；而 `BacktestService` 要求正式调用方使用 `create_formal_task()`，见 `services/quant-api/app/backtest/service.py:80-92`。

dry-run 也明确报告 `backtest_candidate=true`、`backtest_capable=false`，见 `experiments/htdy_indicator/formal_backtest_candidate.py:148-185`；它读取显式 path/manifest，不经过 Profile resolver。

因此准确表述是：`HTDY strict 可加载并可在隔离 research-only 路径生成可信结构化结果，但尚未通过 Profile-bound create_formal_task -> runner -> independent report -> trust audit Gate`。

### 2.7 未声明未来引用、partial bar 或前端独立正式算法

- 已知未来引用仅存在于 HTDY original XMA，当前保持 observation-only 和 formal block。
- strict future-tail 和 prefix 行为已有测试；未发现 strict 读取未来 bar。
- live evaluator 输入由 confirmed-only reader 提供；日线方向排除当前 trading day。
- 前端仍有独立算法：Market MACD error fallback、Backtest/Review MACD、共享 ATR pane、Market `trendStatus` 本地 EMA21 和 `riskDraft` 本地 ATR14。
- Backtest/Review 的本地 MACD/ATR 虽不改写报告数据库或策略交易，却会让正式报告页面显示未经 indicator lineage/version 冻结的派生数值，故列为 `formal_must_migrate`。

## 3. Registry 与文档漂移

### Registry 当前可信事实

- 仅 EMA10、EMA21、EMA60 为 `validated`；均为 `sma_window`、closed-bar-only、无重绘。
- `huo_tian_da_you` 只代表 original Web observation，状态为 `observation_only`。
- MACD 与 ATR 不在 registry，公共函数版本均为 `v1-draft`。
- HTDY strict 未进入 indicator registry。

### 漂移与易误读点

1. `docs/INDICATOR_KERNEL.md` 对 V1-E 的说明仍准确记录 Market MACD 后端迁移，但“Web MACD”不能扩写为 Backtest/Review 也完成迁移。
2. `docs/INDICATOR_KERNEL_V1D_MIGRATION_PLAN.md` 的 8 行矩阵未覆盖后续新增的 Market EMA/MACD lineage、Stage 9 replay、Web draft 派生值和 HTDY formal candidate；本报告补足为当前 33 条调用路径。
3. `docs/strategy_specs/htdy/STRICT_V1_SPEC.md` 仍将 strict indicator 定位为 `backtest_capable=false`；后续 formal candidate strategy 的存在只扩大到候选/dry-run，不会自动改变该指标定级。
4. `FORMAL_BACKTEST_CANDIDATE_PLAN.md` 允许后续独立 `research_only=true` 报告 Gate；这不同于当前正式消费者要求的 Profile-bound `create_formal_task()`。

## 4. 风险分级

### P0

- 禁止把 HTDY original XMA 结果接入正式报告、Signal、live、提醒或通知。
- 禁止在 `jm_v1b_daily_direction_fast_entry / v1b.0` 中替换 EMA/MACD/ATR helper；否则 report 14 和既有信号不再可复算。
- 禁止把 HTDY research-only report test 表述为 formal BacktestService Gate 已通过。

### P1

- Backtest/Review 共享图表的 MACD/ATR 应获得后端/common-kernel versioned series，或明确降级为 observation-only。
- FastAPI 通用策略与正式日线策略应逐调用方迁移，并在 snapshot 中记录 indicator policy/version。
- MACD/ATR 只有在 policy、异常输入、warm-up、批量/逐 bar 和 consumer regression 均冻结后才能进入 registry。

### P2

- Market `trendStatus` 和 `riskDraft` 可改为复用已加载的后端指标，减少 UI 中同名但无 lineage 的数值。
- 为 TypeScript fallback 与 Python kernel保留共享 golden fixture，但 fallback 仍不能成为正式证据源。

## 5. 建议顺序

1. `D4-02`：冻结 EMA/MACD/ATR policy 与 registry 状态；明确 MACD/ATR 是 validated 还是 compatibility-only。
2. `D4-03`：先迁移非冻结的正式日线策略和 Backtest/Review 展示；每个调用方独立 golden/report/trade Gate。
3. `D4-04`：为 HTDY strict 新建 Profile-bound `create_formal_task` 隔离测试和独立 report/trust-audit Gate；保持 `research_only`、不碰 report 14。
4. JM V1-B 继续冻结；若未来迁移必须新建策略版本并重新完成 Backtest、Signal、live preview 及 lineage Gate。

## 6. 验证

基线测试：

```text
60 passed in 14.29s
```

覆盖公共 kernel、兼容向量、Market EMA/MACD、live evaluator、HTDY original/strict 风险及 formal-candidate research-only 路径。最终提交前重新执行相同测试、CSV schema/枚举检查、`git diff --check` 和变更范围检查。

补充策略/scanner 回归：

```text
62 passed / 4 failed
```

4 个失败都来自 `services/quant-api/tests/test_signal_scanner_api.py` 的旧 fixture：fixture 只创建 `MarketDataFile/DataQualityReport`，没有 current formal `/api/signals/scan` 所要求的 `intraday_research_v1` Profile active binding 与 actual-contract mapping；当前主干按 formal consumer contract fail-closed，因而旧断言期待的 `completed_items=1` 和 signal 记录不存在。该失败在本任务只新增审计文件的基线上复现，不由本次产物引入，也不能表述为 scanner 全量回归通过。

Web 指标定向测试：

```text
22 passed / 1 skipped / 0 failed
```

skip 为需要显式 `HTDY_GOLDEN_BUNDLE` 的可选只读 Golden Sample；其余测试确认 Web EMA seed、MACD scale、ATR smoothing、HTDY XMA 重绘事实、后端 MACD override 过滤和 HTDY 主图禁用状态。

## 7. Gate

本任务只证明调用方和 policy 事实已被盘点：

```text
INDICATOR_CALLERS_AUDITED
```

它不证明：

```text
MACD_ATR_VALIDATED
INDICATOR_CALLERS_MIGRATED
HTDY_FORMAL_REPORT_READY
OOS_READY
LIVE_READY
QYWX_READY
```
