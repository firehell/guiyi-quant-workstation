# SuBing History Window Isolation and Snapshot Slice

Date: 2026-08-29  
Status: approved; plan at `docs/superpowers/plans/2026-08-29-subing-history-window-cache.md`  
Scope: Market chart historical markers (`apps/quant-web`) and `GET /api/v1/market/research/subing-strategy/history` (`services/quant-api`)

## Goal

苏冰 overlay 下向左拖 15m 真实主力时：Canonical 翻页不被投影请求拖死；当效果快照的 `coverage_through` 与请求 `through` 一致时，窗口化 `/history` 只过滤已有 Episode/Action，不再因 `since` 左扩而重放 1m。

## Non-goals

- 不加 uvicorn worker，不加长 `bars/page` 的 30s 超时。
- 不让 HTTP GET `/history` 写 segment cache（保持 `publish_cache=False`）。
- 不改策略公式、lifecycle、fill_basis、exit 语义或公式版本。
- 不把主图改去调用 `/performance`；对外合同仍是 `/history`。
- 不把较新 `through` 的快照截成更早 `through` 的投影（避免把尚未发生的平仓泄漏进更早窗口）。
- 不改 Alert、Runtime、Canonical、OpenSpec 或主力映射。

## Current state

向左拖到左边界时，图表 `need-more-before` → `loadEarlierBars` → `GET /bars/page`（默认 30s）。成功 prepend 后 `watch(mutation)` 立即再打 `/history`，`since` 为已加载区间最早交易日，`through` 为最新交易日。

`/history` 是同步 FastAPI 路由：先按窗口装载 1m/5m/15m，再按段算 bar digest 查 cache。`since` 一旦跨入更早主力段就会 miss 并整段 replay（实测约 2 分钟）。GET 路径 `publish_cache=False`，浏览器 miss 不写回。本地 API 仅 2 个 worker；前端 prepend 不取消上一趟，连续左拖会叠两个 miss。worker 占满后下一页 `bars/page` 超过 30s，红条「读取更早历史失败：请求超时」；`/history` 失败则黄条 `HISTORICAL_RESEARCH_UNAVAILABLE`。

15m Canonical 本身可分页（空闲时 JM 15m 真实主力可完整翻页）。效果快照对 JM 已是 `cache_state=hit`、`through=2026-08-28`。策略投影满足 prefix invariance：同一 `through` 下更早 `since` 的动作集合 ≡ 全窗口结果按交易日过滤。

## Approved decisions

1. A（前端隔离）与 B（快照切片）一起做。
2. 主图继续只调 `/history`；B 是该接口内部的只读切片，不是第二套投影源。
3. 仅当 `request.through == snapshot.coverage_through` 且 `request.since >= snapshot.coverage_since` 时切片；否则 fail-closed 走现有 replay。
4. GET `/history` 仍不写 cache。

## Display / request contract

```text
选苏冰 + actual_dominant + 15m
  prepend 停稳（400ms）后最多一趟未取消的 /history
  through = 已加载 Canonical 区间最新交易日
  since   = 已加载 Canonical 区间最早交易日

snapshot.coverage_through == through
  且 coverage_since <= since
  -> /history 只过滤 snapshot（cache_state=hit），不装载 1m、不 replay

否则
  -> 现有 history replay；publish_cache=False
```

- `bars/page` 与 `/history` 仍并行、互不等待。
- 翻页超时只报红条（409 才说映射/分区不完整）。
- prepend `/history` 失败时保留上一批已成功标签；黄条只表示更早这一截投影未更新。
- replace（换品种/周期/overlay）立即取消防抖与在途请求，并清空标记后重拉。

## Architecture

```text
KlineChart need-more-before
  -> loadEarlierBars -> bars/page (30s)

mutation prepend
  -> useHistoricalResearchMarkers.sync
       debounce 400ms
       abort previous /history
       GET /history?since&through

/history
  -> try read-only performance snapshot
       through match and since in coverage
         -> filter actions/episodes (prefix invariance)
  -> else existing segment load + replay (publish_cache=False)
```

### Units

| Unit | Responsibility |
|------|----------------|
| `useHistoricalResearchMarkers.ts` | 400ms prepend 防抖；AbortSignal 单飞；replace 立即重置；prepend 失败保留 marker |
| `api/market.ts` `getSubingStrategyHistory` | 把 `signal` 传给 axios；超时仍为 120s |
| `chart.vue` | 不改翻页与红条文案合同；继续把 mutation 交给 composable |
| `SubingStrategyHistoricalProjectionService.history` | 先尝试 snapshot 切片，失败再 replay |
| composition | 只读注入 `SubingStrategyPerformanceSnapshotQuery`；禁止 GET 写 cache |
| 既有 `_episode_intersects` 与 action `trading_day` 过滤 | 切片与 replay 共用，保证窗口语义一致 |

### Snapshot slice rules

从 `SubingStrategyPerformanceSnapshotQuery.current(symbol)` 只读快照：

- 快照缺失、lineage/`through` 不一致、`since < coverage_since`、engine/policy 对不上：不切片，走 replay。
- 切片时 `cache_state` 为 `hit`。
- `episodes`：沿用 `_episode_intersects`（`entry_day <= through` 且 `exit_day is None or exit_day >= since`）。因 `through` 与快照相同，不得把更晚平仓改写成未平仓。
- `actions`：与现网 replay 相同，保留 `since <= action.trading_day <= through` 的动作（从相交 Episode 的 entry/exit 展开，按 `effective_bar_end, action_id` 排序）。
- `resolved_cutoff`、`policy` 用快照/现行 policy，不得编造。
- `segment_summaries` 与 `context_unavailable`：快照没有与 replay 同构的 bar 计数与 context 列表时返回空元组，禁止用估计值填 bar_count。图表 marker 不消费这两项。
- 切片路径不得调用 `replay_subing_strategy_segment`，不得按窗口装载 1m/5m/15m。

## Error / edge handling

- 在途 `/history` 被更新的 prepend/replace abort：不当成黄条；只让最新一代请求写 `error` / `loading`。
- prepend 失败且已有 marker：`error=HISTORICAL_RESEARCH_UNAVAILABLE`，marker/episode 保持。
- replace 失败：标记为空 + 黄条（与现网 replace 失败一致）。
- snapshot 不可用：replay；replay 仍超时则黄条。前端单飞避免两个 replay 占满 worker。
- `bars/page` 超时与投影失败独立展示。
- 不引入第二套「假投影」或用 EMA 色带冒充策略动作。

## Testing

前端（`historicalResearchMarkers.test.ts`）：

- 连续三次 prepend 在防抖窗口内只发出一次 `/history`，且 `through` 为最新交易日、`since` 为最早交易日。
- 第二次 prepend 取消第一次：被取消的请求失败不得覆盖已成功 marker，也不得留下黄条（仅最新一代可写 error）。
- prepend 失败保留旧 marker（现有用例保留）。

后端：

- 同一 `through`、更早 `since` 的切片结果与「全覆盖窗口 replay 再按 since/through 过滤」的 actions/episodes 一致。
- 切片路径不调用 replay、不装载 1m。
- `through` 小于快照 `coverage_through` 时不切片（防未来泄漏），走 replay。
- HTTP `/history` 仍 `publish_cache=False`（现有用例保留）。

## Out of scope for this change

- 用效果账本 API 直接画主图标签。
- 为更早 `through` 做快照前缀截断。
- 修改 `bars/page` 超时或 worker 数。
