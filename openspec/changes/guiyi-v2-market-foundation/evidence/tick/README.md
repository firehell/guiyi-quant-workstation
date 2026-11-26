# Tick 实测与容量验证

## 实际来源

- 2026-11-26 从 Catalog 只读验证 RB2701 的 rank1 和 Session。在 13:30 日盘开盘附近捕获 491 条 RQData Tick 与 4 根供应商实时 1m。候选生成的 13:32–13:34 三根 1m 与供应商实时数据逐字段相等。监听已关闭，无队列溢出。两条对照频道均只写采样临时文件。 [对照](RB2701-day.json)
- 同一合约用候选强制证书校验 WebSocket 复验 125 秒，共 250 条 Tick 与 2 根供应商实时 1m。已形成的 13:38 端点逐字段一致。前两段各有一根缺乏开头累计基线，候选均拒绝发布。 [TLS 复验](RB2701-verified-tls.json)
- 14:58 收盘尾段继续用强制证书校验的双频道采样。241 条 Tick 和 2 根实时 1m 中，候选生成的 15:00 Session 最后一根与供应商实时 1m 逐字段一致。另一根缺少接入前累计基线，候选保留缺口。 [收盘实测](RB2701-tail.json)
- 13:42 只读 Catalog 返回 DATASET_OR_PARTITION_MISSING。收盘后首次检查时，米筐尚未报告期货日线与分钟线均就绪，未请求历史分钟。历史就绪后以 compare_tick.py 绑定原始 SHA 复验。同日盘后权威三方、自然跨夜及目标范围仍待验。真实行情原件存于本机私有临时文件。13:30 样本另经 EventEngine、MarketFeed、DurableLive 与原生 PostgreSQL/Redis 重放，落入完成日志的 3 根 1m 再次逐字段一致。

## M4／16 GB 回放

以下为合成时段与行情，模拟夜盘跨自然日、日盘短休、午休和不同尾段。60 使用正式品种名单，70 另加入 10 个隔离身份。EventEngine 处理有界批次，完整分钟端点逐品种核对。计时从应用回调入队至该批处理结束。独立的 Redis 测试覆盖源与完成 journal、五个日内周期、重启水位和既有苏冰完成输入读取。

| 负载 | Tick 数 | 回调至处理 p95 / p99 | 完成 1m | 峰值积压 / 结束积压 |
|---|---:|---:|---:|---:|
| 60 品种，2 Hz | 2,448,225 | 1.246 / 1.994 ms | 20,400 | 60 / 0 |
| 隔离 70 品种，5 Hz | 6,795,255 | 1.344 / 1.867 ms | 22,650 | 70 / 0 |

以上两轮处理吞吐约 49,851／52,936 Tick/s，CPU 48.0／126.7 秒，Python 峰值 RSS 约 173／183 MiB。目标机同一冻结历史的七周期 MDS 性能、磁盘占用和并发读写见 [存储对照](../storage/README.md)。

原生 Redis 60 品种回放跨 559 个分钟轮次，确认 26,967 个完成端点，苏冰原入口读取 21,527 条对应周期输入，重启后源游标追平，未见漏重。分钟轮次包含 feed、派生、Redis 读写和完成提交，p95 为 568.069 ms。70 品种复演同样跨 559 轮，确认 29,947 个完成端点，苏冰入口读取 23,907 条对应周期输入。轮次 p95 为 617.879 ms。Redis 服务端内存为整实例累计计数，见 [60 完成流](60-completed.json) 与 [70 完成流](70-completed.json)。

另用不同 Redis 实例与一次性 PostgreSQL 同机并发跑 60 品种完成流和盘后套件。归档、提交、缓存清理、首张凭证和重试回归 134 项通过，归档用时 25.86 秒并处于完成流回放窗口内。26,967 个端点和苏冰输入数量仍逐项相等，整体分钟轮次 p95 为 641.935 ms。 [并发原件](60-concurrent-archive.json)

快期 HTDY／Alert 采用真实隔离 PostgreSQL、Canonical Parquet、独立 Redis 与原始消费路径验证。正常序列通过 60 根 1m 和一根 60m 准入。完成消费重启晚于准入时间时保留 H1 原件并关闭触发资格，未见重复或滞后触发。另验证一个隔离 Runtime 同时跑 EventEngine、MarketFeed、DurableLive、MDS、只读 FastAPI，排除同 Redis 实例第二写入者与已有旧源游标。

## 复验入口

- capture_tick.py 和 compare_tick.py 位于仓库 scripts/market_foundation。真实采样仅对已授权品种、窗口和数据额度执行。compare_tick.py 的 --settings 打开同日 Canonical 只读对照。
- 同目录 benchmark_tick.py 复演 60／70 品种高频入口。benchmark_completed.py 接受本任务专用 Redis 空库和非默认端口，复演五周期及水位。原始容量指标见 [60 Tick](60-ingress.json)、[70 Tick](70-ingress.json)。
- 相关隔离用例为 test_tick_market、test_tick_completed_integration、test_tick_htdy_integration、test_tick_runtime。VeighNa 目标机验证需锁定包并设置 GUIYI_TEST_VEIGHNA_DISPATCH=1。Native 账户输入回归只使用任务的 PostgreSQL 和 Redis 守护实例。
