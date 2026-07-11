# Indicator Kernel V1-D Migration Plan

更新时间：2026-07-11

执行状态：`DELIVERY_READY`

## 1. 定位

V1-D 只做逐调用方迁移设计和 golden vector 对照，不替换任何生产调用链。

本阶段目标：

- 证明 `Indicator Kernel` V1-C 的 `ema_series()`、`macd_series()`、`atr_series()` 可以复刻现有调用方口径。
- 明确每个调用方后续若迁移时应选择的兼容 policy。
- 保持策略、扫描、live evaluator、Web、数据库、报告和企业微信链路不变。

本阶段不是：

- 不是 `MIGRATION_DONE`。
- 不是 MACD / ATR `validated` registry 注册。
- 不是策略版本升级。
- 不是历史报告重跑。

## 2. 逐调用方 policy 矩阵

| 调用方 | 当前角色 | EMA / MACD policy | histogram | ATR policy | V1-D 动作 | 后续替换条件 |
|---|---|---|---|---|---|---|
| `apps/quant-web/src/utils/indicators.ts` | Web 展示 | `sma_window` | `2` | `wilder_sma_seed` | 文档登记，不改 `apps/` | 由 `web-indicators` worktree 单独处理 TS fixture |
| `services/quant-api/app/strategy/su_bing_ema21.py` | FastAPI 扫描策略 | `first_value` | `1` | `wilder_first_tr` | golden vector 对照 | 输出完全一致后，另开迁移任务 |
| `packages/quant-core/.../su_bing_ema21` | vn.py 策略草稿 | `first_value` | `1` | `ema_first_tr` | golden vector 对照 | 输出完全一致后，另开迁移任务 |
| `packages/quant-core/.../jm_v1b_daily_direction_fast_entry` | JM V1-B 可信链路 | `first_value` | 不直接输出 | `ema_first_tr` | P0 对照，不迁移 | 必须另开 V1-E / 策略版本 Gate |
| `services/quant-api/app/services/live_signal_evaluator.py` | JM V1-B 预览复用方 | 继承 `jm_v1b_daily_direction_fast_entry` | 不直接输出 | 继承 `jm_v1b_daily_direction_fast_entry` | P0 对照，不迁移 | 依赖 JM V1-B 迁移 Gate |
| `packages/quant-core/.../su_bing_jm_daily_ema21_macd_volume` | 独立日线策略 | `first_value` | `1` | 不使用 | golden vector 对照 | 输出完全一致后，另开迁移任务 |
| `packages/quant-core/.../su_bing_jm_daily_score2of4` | 日线 score 策略 | `first_value` | `1` | 不使用 | golden vector 对照 | 输出完全一致后，另开迁移任务 |
| `packages/quant-core/.../su_bing_jm_daily_trend_cross_score2` | score2of4 派生策略 | 复用 `score2of4` | `1` | 不使用 | 证明复用同一 helper | 随 score2of4 单独迁移 |

## 3. Golden Vector 规则

新增测试：

```text
services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
```

测试约束：

- synthetic bars 只用于数值口径对照，不作为策略收益样本。
- legacy 输出来自现有 helper 或现有 `calculate_indicators()`。
- kernel 输出来自公共 `Indicator Kernel`。
- 对照只比较指标值，不改变生产 import。
- 如果出现差异，V1-D 应记录阻断原因，不通过调整策略阈值来掩盖差异。

## 4. 安全边界

V1-D 禁止：

- 修改 `packages/quant-core/guiyi_quant/strategies/` 生产代码。
- 修改 `services/quant-api/app/` 生产代码。
- 修改 `apps/`、`data/`、`.env`、`.env.example`。
- 修改 PostgreSQL / Alembic / DuckDB / Parquet。
- 写入 `signal_events`、回测报告或企业微信通知链路。
- 将 `macd` / `atr` 写入 `indicator_registry` 或标记为 `validated`。

## 5. 验收命令

```bash
uv run --project services/quant-api pytest -q services/quant-api/tests/test_indicator_kernel.py services/quant-api/tests/test_indicator_kernel_v1b_diff.py services/quant-api/tests/test_indicator_kernel_v1c_macd_atr.py services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_jm_v1b_daily_direction_fast_entry.py services/quant-api/tests/test_live_signal_evaluator.py
uv run --project services/quant-api pytest -q services/quant-api/tests/test_su_bing_ema21_vnpy_draft.py services/quant-api/tests/test_su_bing_jm_daily_ema21_macd_volume.py services/quant-api/tests/test_su_bing_jm_daily_score2of4.py services/quant-api/tests/test_su_bing_jm_daily_trend_cross_score2.py
git diff --check
uv run --project services/quant-api ruff check services/quant-api/tests/test_indicator_kernel_v1d_migration_vectors.py
```

## 6. 后续 Gate

任何真实迁移必须另开任务，并满足：

- 指定唯一调用方和策略版本。
- 固定兼容 policy。
- 迁移前后 golden vector、策略回归、必要时 live preview 回归全部通过。
- 若策略输出或信号时点有差异，必须升策略版本并重跑回测 / 信号审查。
