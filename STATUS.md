# 当前状态

更新时间：2026-08-12

## 当前结论

- Market Runtime V1 已在本地工作站启用，持续运行范围严格固定为
  `data/universe/operational_products.txt` 中的 `j/jm/ap/ag`。当前 API、Web、Live 与 17:00
  after-market runner 均绑定 clean/detached Runtime `e49d4fc4`。
- Runtime 只提供行情研究观察；Historical Canonical 与 Redis Live Overlay 分离，
  `auto_order=false`，仓库不存在订单创建或提交路径。
- MR-08 的 develop 自然 canary 和最终 Runtime 身份、拓扑、健康、范围复验已经完成。该结论不表示
  release、`main` 合并或新的 Runtime promotion。
- Data Foundation 已完成 DFD-01～DFD-06，DFD-07 当前完整闭环为 **43/60**，剩余 **17** 个 active
  品种。全域 Canonical 验收仍未完成。
- `retire-products` 已对退役名单 `br/cs/ic/if/ih/im/lu/nr/sp` 完成受控生产清退，事后 residual 为 0。
- Instrument name 只有品种代码导致 Web 中文名称退化的问题已由统一 display taxonomy 收口并部署；
  Runtime 读回 `a=豆一`、`jm=焦煤`，45 个主力品种的名称与板块均非空。

## 当前可执行面

- Web：Market 列表与 K 线工作台。
- HTTP：Canonical bars/page、coverage、dominants、Historical/Live state 与 WebSocket、只读 Runtime health。
- CLI：`guiyi data update|refresh|audit|retire-products|after-market`、`guiyi runtime status|live`。
- Runtime 持续授权只覆盖 `j/jm/ap/ag` 的当日 rank1 completed 1m Live，以及 17:00/最多一次一小时后
  retry 的同范围盘后更新。

已退役且不得恢复为兼容入口：backtest API/Web/worker/queue、Signal/Review/Strategy
HTTP·Web·worker、data-center HTTP、旧 RQ worker、旧 scheduler、自动交易与真实订单。

## 已冻结的数据合同

- 外部事实源只有 RQData；正式历史链路为
  `RQData -> staging + 六项硬校验 -> Canonical Parquet -> 八表 Catalog -> MarketDataService`。
- 物理 `DatasetKey=(kind, symbol, series_or_contract, frequency)`；物理 kind 只有
  `continuous|contract`，`actual_dominant` 仅在查询时由 `MainContractMap rank=1` 拼接。
- Direct 周期是 `1m/1d/1w`；Derived 周期是 `5m/15m/30m/60m`，只从同 Dataset、质量通过的
  Canonical `1m` 按 TradingSession 聚合。
- 每个 Dataset 每自然月只有一个 `part.parquet`；schema、identity、session/frequency、OHLCV、coverage、
  row count 与物理可读性全部通过后才能原子发布。
- PostgreSQL active 数据模型只有八表：`exchanges`、`instruments`、`contracts`、
  `trading_calendars`、`trading_sessions`、`main_contract_map`、`market_datasets`、
  `market_partitions`。

## 活跃 Gate

- DFD-07：剩余17个 active 品种仍由用户逐品种给出精确单次执行意图，按
  `apply -> audit -> fixed T0 no-apply NOOP` 闭环。Catalog 数量增长、单次 apply 完成或进程退出都不等于
  品种闭环。
- 历史60品种 Canonical 闭环不改变 `operational_products.txt`，也不自动扩大 Live/after-market 范围。
- 生产 DB/Canonical 写入或删除、Runtime switch、真实通知、`main`、tag/release 与 promotion 仍各自需要
  新的范围明确单次执行意图。

## 最近验证事实

- 2026-08-12 00:10 将统一 display taxonomy 修复切换到 detached `233d859e`；API、Web、Live 已重载，
  after-market 已重载但未手工运行。四个 launchd 根均指向同一 Runtime，API/Web/Runtime health 可用，
  Live 范围仍严格为 `j/jm/ap/ag`；未运行数据更新、migration、手工盘后或通知。
- 该次 `confirm-market-runtime` 未返回最终打印，未重试。新 marker 时间、clean/detached 身份、四个
  launchd 根与 PID/加载状态、HTTP/Runtime health 和品种名称读回共同确认目标状态已经生效；安装器最终
  回执异常保留为后续工程问题，不改变本次实态结论。
- 2026-08-11 23:52 将 P0/P1 架构收口部署到 detached `5ea04f1e`；四个 launchd 根统一，
  API/Web/Runtime health 可用，Live 仍为 `j/jm/ap/ag`，RQ 依赖与退役 label 已清除。
- 2026-08-11 的开发态17:00自然盘后链对 `j/jm/ap/ag` 一次完成；四品种 Canonical 推进、rank1
  reconciliation、Live 清理和已打开页面的 seam 自动更新均通过。
- 最终 Runtime 读回为 API/Web 可用、Runtime health `ok`、Live 范围4/4；真实浏览器历史分页从1200 bars
  扩展至24037 bars，覆盖进入2023年，未观察到 console warning/error 或视口跳回。
- 周末 `non_trading_day skipped` 未形成新的自然现场证据，按既有决定不重复制造或冒充该证据。
- `rb` 已完成受控收口：发布 507 个目标（183 次 provider 请求、零失败），写后 audit 为
  passed/0 findings，fixed `T0=2026-08-07` no-apply 为 NOOP（0 provider 请求）。

更早的逐品种 receipt、故障诊断、自然 canary 与受控执行细节以 Git history 和对应 active task canonical
为历史记录，不再复制到当前状态页。
