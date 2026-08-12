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

- `2026-08-12 20:38 +08:00` 已将隔离 Runtime 从 `0dea973d...` 单次切换到 clean/detached
  `v1.0.0^{}`=`423b049830087e7885736e6e5471d5e289134bbe`；`uv sync --no-dev`、Web production build 与
  bundle topology 均通过，API/Web/Live/after-market 已从同一 Runtime 根重载。API/Web/Live 为
  running，after-market 为等待下一个 17:00 的 not running。未运行 migration、手工盘后、数据任务或通知。
- production 读回为 `quant-api 1.0.0`；API/Web HTTP 200、Runtime health `ok/readonly=true`，DB/Redis/Live
  均为 `ok`。Market dominants 返回 60 个唯一且业务字段完整的品种，映射日均为
  `2026-08-12`；JM actual-dominant 15m 真实读取的 Canonical edge 为 `2026-08-12T07:00:00Z`。
- 本机 FRPC 进程、5173/8000 监听与本地 HTTP 链通过。当前 Runtime 环境未配置
  `PUBLIC_BASE_URL`/Basic Auth 验收变量，因此本次未运行公网 `public-healthcheck.sh`，也未重载
  未变更的 FRP/Nginx 配置。
- 配置读回为 active=60、operational=60 且内容相同。`2026-08-12 17:00:01 +08:00`
  launchd 自然触发 60 品种盘后更新；第一次在 Canonical update 阶段抛出 `ValueError`
  而失败，无代码变更、无人工补跑，一小时后的唯一自动 retry 于 `19:15:06 +08:00`
  完成：`status=passed`、`attempts=2`、`error_code=null`、`last_successful_trading_day=2026-08-12`，
  launchd `runs=1/last exit code=0`。公开日志按合同只保留异常类型，不将未记录的具体 provider 子原因
  升级为确定结论。
- 盘后只读核对为当天 TradingSession 60/60、MainContractMap rank1 60/60；continuous
  `1m/5m/15m/30m/60m/1d` 的 60 品种统一推进至 `2026-08-12T07:00:00Z`，`1w` 统一停在
  已完整周 `2026-08-07T07:00:00Z`；当天 rank1 真实合约的 `1m/5m/15m/30m/60m/1d`
  也为 60/60。Runtime health 读回 Live `CLOSED=60`、`subscribed_count=0`，表明当日 Live snapshot
  已清理；Live 仍未写入 Parquet。

## v1.0.0 封板状态

- 仓库版本号、changelog 与当前状态已收口为 `1.0.0`；60 品种 17:00 自然盘后最后外部
  Gate 已通过，封板条件已满足。annotated `v1.0.0` tag 对象为 `7b573d97...`，peeled target
  精确为最终 `main` release merge commit `423b0498...`；同一 target 已部署到隔离 Runtime。Tag 不授权
  migration、通知或任何数据写入。
- active OpenSpec 已与实现同步：continuous `1m` 只用 `{SYMBOL}88`，`1d` 按 rank1 真实合约交易所日行情，
  `1w` 只由完整同源日线聚合。
