# SignalEvent、通知与复盘合同

更新时间：2026-08-08

## Current surface vs contract

本文是 **长期语义合同**，不是当前可执行产品面说明。

- **合同有效**：`Strategy -> SignalEvent -> Notification Gate -> Channel`、default-off、无订单、fail-closed。
- **可执行面（2026-08）已卸**：Signal/Review/Strategy/Dashboard Web 与对应 HTTP、`/ws/signals`、signal/notification RQ worker、poll Live 与 Task 06 observation 应用路径。
- **保留**：DB 表与 quant-core 策略研究源码供后续重搭；Market Canonical 读与 data/runtime 治理见 `STATUS.md` / `docs/ARCHITECTURE.md`。

## 1. Active signal chain（语义）

SignalEvent 是研究观察事件，不是订单或交易指令。语义链路固定为：

```text
Strategy
-> SignalEvent
-> Notification Gate (default off)
-> Channel (observation only)
-> Manual Review
```

事件流保持 append-only。`signal_created`、`signal_changed`、`status_changed` 分别表达首次出现、
语义变化与生命周期变化；不得覆盖旧事件伪造当前状态，也不得从通知结果反写策略事实。

## 2. 数据与时序

- 正式历史信号只使用质量通过的 Canonical 数据；与 DataGap 相交、identity 漂移或未确认 bar
  一律 fail-closed。
- historical canonical 与 live observation 分离。live preview 不得直接提升为正式历史事件。
- 策略只能读取当前及过去数据；禁止未来函数、数据泄漏和未记录重绘。
- provider-final EOD、repair、replay、backfill、migration 与重新计算不补发历史通知。
- `continuous` 与 `actual_dominant` 不可互换；actual dominant 必须绑定
  `MainContractMap rank=1` 有效区间。

## 3. Event identity 与边界字段

每个可保存的事件必须绑定：

- strategy id/version 与参数摘要；
- DatasetKey、manifest/provider data version、exact window；
- symbol、contract、frequency、bar time 与首次观察时间；
- signal side/type、规则版本与输入指纹；
- `observation_only=true`；
- `not_trading_instruction=true`；
- `auto_order=false`；
- future-looking 与 repainting 声明。

相同 event identity 和 payload 必须幂等；identity 相同但内容不同必须显式拒绝或创建新版本，
不能静默覆盖。通知 dedupe identity 必须包含 event、signal、channel 与 rendered payload hash。

## 4. Task 06 path（已退役）

Task 06 的 confirmed observation、SignalDecision、EOD reconciliation、ResearchSample 应用路径
已从仓库移除（含 `guiyi data live` / `live_review_loop`）。历史 Alembic 与 Git 可追溯；
不得再把它当作 active 信号或盘中观察入口。Review Web/API 亦已卸载；表未物理 drop。

## 5. HTDY original observation rule（盘中 realtime 已退役）

HTDY original 的盘中 realtime first-seen 应用路径已随 poll Live 栈移除。
历史白名单语义仅作合同归档参考；当前不得再通过 LiveMinuteBar / HTDY realtime snapshot
生成 observation 或通知。未来正式历史信号须走 Canonical scanner（当前无 mounted scanner HTTP）。

## 6. Notification Gate

- 默认关闭；缺少配置、配置异常、过期、不一致或授权不匹配时保持关闭。
- 真实发送只接受绑定单一 event/signal、次数、期限、channel 与 payload hash 的显式授权。
- sender 失败不得吞错；去重状态与尝试次数必须可检查。
- replay、repair、backfill、migration 和 EOD 不得触发补发。
- 企业微信文案必须包含研究观察、非交易指令和无自动下单边界。
- 一次真实发送不启用 autosend、重复发送、live 或交易。

## 7. Review contract（语义；Web 已卸）

语义上 Review source 只允许：

- `strategy_signal`；
- `signal_event`；
- `signal_decision`；
- `manual_trade`。

当前无 Review Web/API。重建时必须拒绝旧 `backtest_trade` 或未知来源，并在请求 bars 前 fail-closed；
不得通过路由 query 恢复已删除的 report/trade/backtest deep-link。

## 8. Public surfaces

当前 **不** 提供：

- Signal 列表、事件订阅或 `/api/signals` / `/ws/signals`；
- Review Web/API；
- Watchlist / Strategy / Dashboard HTTP；
- signal/notification RQ worker。

当前提供：

- Market Canonical 读与 Indicator 展示计算；
- `/api/v1/data`、`/api/runtime` 与对应 CLI；
- after-market scheduler 默认关闭。

已删除且不得兼容恢复：

- `/api/backtests/**`、`/ws/backtests/**`；
- Web `/backtest`、`/backtest/batch`、`/settings`；
- backtest report/trade Review source 与 Market markers；
- `guiyi-backtests` queue/worker；
- old Runtime Scheduler 与 `guiyi runtime plan`。

## 9. Historical S6 boundary

S6-08/S6-09/S6-10 的 schema、packet、receipt、rebind、deployment、stability 与 notification
control plane 已从 active repository 删除，只能从 Git history 追溯，不能作为当前授权或兼容入口。

本文不声明 release、Runtime promotion、live enable、真实通知、生产 migration 或数据删除已完成。
未来增加回测、长期 live 或新的通知能力必须新建任务，并遵守默认关闭、无订单与外部操作的一次性
scoped intent 边界。
