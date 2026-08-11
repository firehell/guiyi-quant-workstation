# Indicator Kernel

更新时间：2026-08-11

## 定位

`packages/quant-core/guiyi_quant/indicators/` 是指标业务口径的唯一权威模块。当前保留 EMA、MACD、ATR、
HTDY original/strict、Registry 与 formal policy；旧策略包、回测、Signal/Review、realtime evaluator、
通知和报告 Gate 都已退役。

| 角色 | 位置 | 当前状态 |
|---|---|---|
| Python Kernel | `packages/quant-core/guiyi_quant/indicators/` | 唯一研究算法与 policy 权威 |
| Web 观察镜像 | `apps/quant-web/src/utils/indicators.ts`、`mainIndicators.ts` | 仅浏览器展示计算；不得成为策略事实源 |
| Market indicators HTTP | 无 | 当前未挂载；未来如需提供，必须从 Kernel 输出 |

当前 Market 图表只渲染 K 线和成交量。Web 指标镜像有测试覆盖，但尚未挂载到页面；页面是否启用由独立
Product Workspace 任务决定。

## 代码位置

```text
packages/quant-core/guiyi_quant/indicators/
├── atr.py
├── ema.py
├── htdy_original.py
├── htdy_strict.py
├── macd.py
├── models.py
├── policy.py
├── realtime_observation_policy.py
└── registry.py
```

## 正式边界

- EMA 默认 `seed_policy=sma_window`，`first_ready_index=period-1`；无效输入不得补零，恢复输出前必须重新
  取得完整有效窗口。
- MACD/ATR 支持显式计算 policy，但 `compatibility_validated` 不等于 formal strategy、live 或 alert 资格。
- 所有正式消费者只能使用 confirmed bars；未确认 bar 最多用于 Web preview。
- 未知 `indicator_code`、policy 或 consumer 必须 fail-closed。
- 未来若重建策略或回测，必须新任务、新合同并复用 Python Kernel；不得恢复旧策略包或复制算法。

当前 Registry 核心状态：

| indicator_code | status | web | backtest | live | alert |
|---|---|---:|---:|---:|---:|
| `ema10` / `ema21` / `ema60` | `validated` | yes | yes | yes | no |
| `macd` | `compatibility_validated` | yes | no | no | no |
| `atr` | `compatibility_validated` | yes | no | no | no |
| `huotian_dayou_original_v0` | `observation_only` | yes | no | no | no |
| `huotian_dayou_strict_v1` | `strategy_candidate` | no | yes | no | no |

这里的 `backtest/live` 表示 Kernel policy 能力，不表示仓库当前存在对应应用入口，也不授权 Runtime、通知
或交易。

## HTDY 风险边界

- original 使用 XMA 风格居中窗口，具有已知未来依赖和重绘风险，只能作为 Web observation。
- original 的 single/double XMA exact future dependency 分别为12/24根；Web 使用27根保守 repaint scan zone。
- strict 是独立 causal 计算，只具策略研究候选资格；它不会自动恢复回测、Signal、live evaluator 或 alert。
- `RealtimeRepaintingObservationPolicy` 仅保留 frozen policy validator 与历史兼容测试。旧
  `HtDyRealtimeCandidateEvaluator` 和相关 Runtime/事件/通知链已经退役，不是当前实现。
- 原始公式外部语义 Gate 仍为 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`；不得宣称 original 已可正式
  回测或验证。

## Web 镜像

Web `calculateEMA`、`calculateMACD`、`calculateATR` 与 HTDY observation 只服务浏览器展示。口径冲突时以
Python Kernel 和 golden fixture 为准，再修正 Web 镜像。Web 不得自行产生 StrategySignal、写数据库、
发送通知或把 preview 提升为 Canonical。

Python 与 Web 当前各保留一份相同 golden 内容供不同测试运行时读取；若后续测试工具可以稳定读取同一
仓库根 fixture，再收口为单文件。在此之前不得手工修改其中一份而不更新另一份。

## 验证

```bash
PYTHONPATH=services/quant-api:packages/quant-core \
uv run --project services/quant-api pytest -q \
  services/quant-api/tests/test_indicator_kernel.py \
  services/quant-api/tests/test_indicator_kernel_v1b_diff.py \
  services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py \
  services/quant-api/tests/test_htdy_production_kernel_policy.py \
  services/quant-api/tests/test_htdy_strict_kernel.py \
  services/quant-api/tests/test_indicator_registry_v1.py

pnpm --dir apps/quant-web test
git diff --check
```

验收只证明 Kernel 与 Web observation 合同仍一致，不表示策略有效、盈利、Runtime-ready 或获得交易资格。
