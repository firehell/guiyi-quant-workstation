# Cursor Market/Runtime Observation Foundation Gap（C6-07A）

生成时间：2026-07-19
任务：`CURSOR-LIVE-ARCHIVE-OBSERVATION-FOUNDATION-C607A`
Cursor Gate：`CURSOR_RUNTIME_OBSERVATION_FOUNDATION_PREPARED`

**不得**宣称 `JM_LIVE_ARCHIVE_OBSERVATION_READY`。

## 1. 本轮已交付（PREPARED）

| 能力 | 位置 |
|---|---|
| Observation 类型 / 纯函数 | `apps/quant-web/src/types/marketRuntimeObservation.ts`、`utils/marketRuntimeObservation.ts` |
| 观察面板 | `apps/quant-web/src/components/market/MarketRuntimeObservationPanel.vue` |
| Chart / Runtime 挂载 | `pages/market/chart.vue`、`pages/runtime/index.vue` |
| 四态 fixture | `apps/quant-web/tests/fixtures/marketRuntime/` |
| 前端单测 | `marketRuntimeObservation.test.ts`（7 passed） |
| live targets path strip | `live_target_contracts.py` + `sanitize_live_targets_payload` |
| 后端单测 | `test_market_runtime_foundation_c607a.py`（3 passed） |
| Runtime TS 补齐 | `scheduler` / `archive` 可选类型 |

## 2. 字段矩阵

| 字段 | UI/契约 | API | 说明 |
|---|---|---|---|
| current actual contract | PREPARED | PREPARED | targets / chart 合约 |
| latest live 1m | PREPARED(契约) | PREPARED | fixture + targets `live_coverage.1m`；Chart 未强制拉 targets |
| confirmed / partial | PREPARED | PREPARED | 分离计数；禁止合并 |
| checkpoint | PREPARED(Runtime) | PREPARED | Runtime 页摘要；Chart 侧多为 unavailable |
| latency | PREPARED(Runtime) | PREPARED | db/redis latency |
| runtime health | PREPARED | PREPARED | degraded ≠ ok |
| historical / live source | PREPARED | PREPARED | dataMode 分离 + mix warning |
| archived trading day | GAP | 部分 | archive 仅有 task_no 等；无一等 trading_day |
| active data version | PREPARED | PREPARED | 历史有；Live by design unavailable |
| quality / profile | PREPARED | PREPARED | Live 不绑 research profile |

## 3. Codex 后续运行态验证清单

1. 真实 T3 / checkpoint 前进后，Chart 面板填入 checkpoint/lag。
2. archive 增加一等 `trading_day`（或稳定解析 task_no）。
3. Chart 可选只读拉取 `/live/targets` 填 `latest_live_1m`（仍不启订阅）。
4. 用真实 live/historical 结果复验：不混源、不泄露 path、degraded 不显示 healthy。
5. 正式 Gate `JM_LIVE_ARCHIVE_OBSERVATION_READY` 仅在 Codex 闭环后评估。

## 4. 边界

- 未启动 runtime / 未调 RQData / 未写 DB / 未发企业微信
- `/live/targets` historical_coverage.file_path 恒为 null
- 缺失字段永不伪造
