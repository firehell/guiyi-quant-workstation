# 当前状态

更新时间：2026-08-12

## 当前结论

- Data Foundation 的 DFD-01～DFD-07 已全部完成并归档：active universe 的 **60/60** 个品种在固定
  `T0=2026-08-11` 完成 Canonical 闭环，全域 audit 为 `passed`、0 findings。
- 历史事实链固定为 `RQData -> staging + 六项硬校验 -> Canonical Parquet -> 八表 Catalog ->
  MarketDataService`；物理 Dataset 只有 `continuous|contract`，`actual_dominant` 只按 rank1 map 查询拼接。
- Market Runtime V1 只提供行情研究观察。Historical Canonical 与 Redis Live Overlay 分离，Live 不写
  Parquet，`auto_order=false`，仓库不存在订单创建或提交路径。
- 九个退役品种 `br/cs/ic/if/ih/im/lu/nr/sp` 已完成生产清退且 residual=0；运行时继续保留退役名单防护，
  不再保留重复执行生产删除的 CLI。

## 当前可执行面

- Web：Market 列表与 K 线工作台。
- HTTP：历史分页、dominants、Historical/Live state、WebSocket 和只读 Runtime health。
- CLI：`guiyi data update|refresh|audit|after-market`、`guiyi runtime status|live`。
- Runtime：`operational_products.txt` 是 Live 与 17:00/最多一次一小时后 retry 盘后更新的唯一范围入口；
  该文件已与 active 60 完全对齐。

已退役且不得恢复为兼容入口：backtest API/Web/worker/queue、Signal/Review/Strategy HTTP·Web·worker、
data-center HTTP、旧 RQ worker、旧 scheduler、自动交易与真实订单。

## 已冻结的数据合同

- Direct：`1m` 使用 RQData `get_price`，`1d` 使用交易所日行情，`1w` 只从完整同源日线聚合。
- Derived：`5m/15m/30m/60m` 只从同 Dataset、质量通过的 Canonical `1m` 按 TradingSession 聚合。
- 每个 Dataset 每自然月只有一个 `part.parquet`；schema、identity、session/frequency、OHLCV、coverage、
  row count 与物理可读性全部通过后才能原子发布。
- PostgreSQL active 数据模型只有八表：`exchanges`、`instruments`、`contracts`、`trading_calendars`、
  `trading_sessions`、`main_contract_map`、`market_datasets`、`market_partitions`。

## 历史验收事实

- 60 品种均完成 `apply -> audit -> fixed-T0 no-apply NOOP`，最终全域 audit 为 0 findings。逐品种过程、
  故障诊断和 provider 请求量只从 Git history 追溯，不再复制到当前状态页。
- 四品种阶段的 10:15 BREAK/10:31 恢复、11:30 BREAK/13:33 恢复、17:00 自然盘后、rank1 reconciliation、
  Canonical seam 更新和 Live 不写 Parquet 均已验收；这些是历史阶段证据，不冒充本轮 60 品种部署证据。
- 周末 CLOSED 与 `non_trading_day skipped` 按既有决定接受，未制造新的自然现场证据。
- 部署、生产数据写入、真实通知、`main`、tag/release 与未来 Runtime switch 仍是相互独立的人工 Gate。

## 当前 Runtime 读回

- `2026-08-12` 已按新的单次明确请求将隔离 Runtime 从 `a0106860` 切换到 clean/detached
  `51e849888590872eab298a682a105ef904ca0426`；API/Web/Live 为 running，after-market 仅重载且
  `not running/runs=0`，四个 launchd 根一致。API/Web HTTP 200，Runtime health 为 `ok`，Market
  dominants 返回 60 个唯一且业务字段完整的品种。
- 配置读回为 active=60、operational=60。部署后现场暴露出 56 个品种的 `TradingSession.effective_to`
  仍停在 `2026-08-11`，因此 13:47 的 Live heartbeat 为 operational=60、TRADING/subscribed=4、
  UNKNOWN=56；系统按合同 fail-closed，未用过期 Session 猜测今日时段，也未手工写 DB 或调用 RQData。
- 根因修复已部署：“完整当日 rank1 快照”与“当前 TRADING provider channels”分离。Redis
  `live:subscription:2026-08-12` 精确覆盖 operational 60，全部合约格式有效；provider channels 仍按真实
  phase 保持 4 个。after-market status 仍为 `pending/last_run=null` 且状态文件不存在，17:00 任务未被
  手工提前触发。56 个过期 Session 是否由自然盘后同步推进，仍需在自然运行后另行只读观察。
- 封板审查又发现并修复了盘后启动顺序：旧 Runtime 会先以 60 品种 Session 的最小完整日判断是否运行，
  因当天 56 个 Session 尚未同步而可能误报 `NON_TRADING_DAY`；release candidate 已改为先用 Calendar-only
  metadata day 判断，再在 update 内同步 Session。该修复尚未切换到上述 `51e84988...` Runtime，因此在
  新的单次 Runtime switch 完成前，**今天 17:00 的 60 品种自然盘后仍是阻断状态**，不得写成已就绪。

## v1.0.0 封板状态

- 仓库版本号与 changelog 已收口为 `1.0.0` release candidate；正式 tag 尚未创建。
- active OpenSpec 已与实现同步：continuous `1m` 只用 `{SYMBOL}88`，`1d` 按 rank1 真实合约交易所日行情，
  `1w` 只由完整同源日线聚合。
- 正式 `v1.0.0` tag 的最后外部证据是：部署本次封板 commit 后，17:00 launchd 自然触发的 60 品种盘后
  更新通过并只读核对 Session/map/Canonical/Web seam/Live cleanup。不得手工触发补证。
