# VeighNa 组件与历史存储选型

2026-11-26 在 Mac mini M4／16 GB 完成。**保留 Canonical Parquet + PostgreSQL Catalog 作为唯一 Market 历史权威。** 原生 VeighNa PostgreSQL 用 `real` 保存价格、量、额和持仓量，345 根日增量走原生 upsert 较快。精确复算要求 Decimal、可空字段、交易日和源修订身份。增加这些能力及 5m／15m／30m 周期需要维护另一套长期物理合同，仍需归一 Calendar、Session、rank1、质量、严格读回和发布/恢复能力。保留现役权威即可继续使用经验证的数据与回读入口，不需要迁移或重新下载历史。

## 对照条件

- 以同一只读事务从 Catalog 选择 active 分区，经现有 MarketDataService 验证端点和完整性后冻结。RB、CU、JM、TA、EC 的 `continuous/MAIN` 覆盖七周期，另有真实 RB2701 1m。共 36 个切片、154,751 根，数据截至 2026-11-25。快照记录逐切片的行数、起止与 SHA256，行情原件留在私有临时目录。 [冻结清单](frozen-manifest.json)
- PostgreSQL 16.15 运行于 Mac 上的 ARM64 Docker，一次性数据库与随机 loopback 端口，无卷绑定。两条路径共用该实例，时序及写读择用原生对应接口。原生只支持四个周期，双方初始写比较同样的 136,406 根，日增量比较同样的 345 根 RB 1m。Parquet 另验证原生未覆盖的三个周期共 18,000 根。
- Canonical 的写入包含 Parquet 校验、落盘、Catalog 注册、MDS 端点读回和提交。读取包含 Catalog、Parquet 解码或验证缓存及 MDS 已冻结端点的检查。原生写含对象转换、upsert 和概况更新，读含数据库返回及 BarData 实例化。逐字段跨后端对照安排在计时外。
- 每个查询在清除 Canonical 应用缓存或关闭原生 PostgreSQL 客户端连接后测一次初读，然后连续取 25 次热读。不清全机页缓存、不对现役进程做维护。首读仍可能命中操作系统页缓存或 PostgreSQL 共享缓冲区。 [原始计时与资源](result.json)
- 持久空间按测量结束时的 Parquet 文件实际字节和 PostgreSQL 表／索引字节统计，包含隔离修订留下的 Parquet 文件，不含 PostgreSQL WAL。Python 峰值 RSS 是两条路径共用进程的高水位。另记录每个阶段客户端 CPU，容器末期空闲时观测约 50 MiB 内存。

## 目标机结果

| 同一 1m 查询 | Parquet 初读 | 原生 PostgreSQL 初读 | Parquet 热读 p95 | 原生 PostgreSQL 热读 p95 |
|---|---:|---:|---:|---:|
| RB 500 根 | 60.457 ms | 21.719 ms | 3.244 ms | 13.204 ms |
| RB 5,000 根 | 58.520 ms | 50.680 ms | 4.711 ms | 40.887 ms |
| RB 100,000 根 | 1,252.095 ms | 834.396 ms | 36.306 ms | 874.774 ms |
| 五品种各 5,000 根 | 503.837 ms | 202.175 ms | 22.060 ms | 313.184 ms |

- 同等初始写入耗时 4.774／6.381 秒，客户端 CPU 4.292／3.013 秒。单日增量耗时 129.688／35.337 ms，客户端 CPU 126.916／8.498 ms，顺序同表。
- 并发测试重复写入同一 CU 交易日 8 次，每次 465 根。并行读 RB 5,000 根的 p95 为 58.818／51.663 ms，p99 为 60.240／174.397 ms。写入前后均核对查询身份；源数据的并发盘后调度另由端到端套件验证。
- 隔离 Parquet 占 6,964,749 字节，另有 Catalog 两表 221,184 字节。原生 K 线表含索引占 21,520,384 字节，概况表 49,152 字节。Python 进程峰值 RSS 584,433,664 字节。
- Canonical 全部冻结值及端点保持一致。原生对照的 136,751 根中有 40,034 根成交额发生变化。它缺少 5m、15m、30m 枚举，拒绝正常模型允许的空成交额，也没有独立交易日槽位。
- Canonical 隔离注入修订后，提交前独立 reader 仍读到旧值，回滚及重新连接保留旧值，成功提交后读到新值；随后复原并复验冻结值。原生隔离注入第二个写入分批的空成交额错误，重新连接确认此前批次也回滚。SQL 行回滚不涵盖原生分开更新的概况，更没有可回读的修订前像。 [原始计时与校验](result.json)

## 组件取舍

| 组件 | 实测与保留范围 |
|---|---|
| VeighNa EventEngine／Event | 可无 GUI 导入并按序处理 64 个合成事件。原生队列无界，事件处理异常也可能终止 worker。只复用分发；接收边界、积压上限、失败状态及关闭由归一控制。 |
| TickData／BarData、BarGenerator | 验证开盘标签转换和累计量额逻辑。跨午夜且累计计数下降的 fixture 中，原生逻辑把负差归零，调用 `generate()` 会立即输出尾部。保留归一具有交易日、Decimal 和完成证据的聚合路径，VeighNa 对象留在组件边界。 |
| Datafeed、vnpy_rqdata | 真实只读请求一次 RB2701 2026-11-25，345 根 1m 覆盖前夜夜盘及日盘。现有适配与冻结历史逐字段相同。原生输出使用开始标签，加一分钟后本样本数值和时间一致。原生不保留交易日，合成空值检查证实将缺失成交额改为零；继续使用归一 RQData 历史及实时适配。 |
| BaseDatabase、vnpy_postgresql | 实际建表证明 OHLC、量、额、持仓量均为 `real NOT NULL`，时间戳不带时区。数据库 Bar 的原生身份不含交易日、源修订或归档证据。事务包裹分批 upsert，概况更新在该事务外。用于一次性对照。 |
| DataManager、DataRecorder | 引擎可以无 GUI 导入。DataManager 依赖 BaseDatabase／Datafeed，无法替代归一质量、Catalog 和发布。DataRecorder 引擎还依赖 SpreadTrading，原生写入和过滤缺少归一源代次、完成确认、幂等消费、恢复原件与有界背压约束。保留归一按用途留存的分钟证据。 |

真实历史与合成组件刺激在 [组件证据](components.json) 中各自标注。组件版本为 VeighNa 4.4.0、vnpy_postgresql 1.1.2、vnpy_rqdata 3.4.7.8、DataManager 1.2.0、DataRecorder 1.1.1、SpreadTrading 1.4.0、RQData 3.5.6.1。

## 复现

1. 使用项目锁定的 quant-api Python 环境。把前述 VeighNa 官方包及 `peewee==3.18.3`、`psycopg2-binary==2.9.11`、`tzlocal==5.3.1`、`ta-lib==0.6.8`、`loguru==0.7.3` 安装到任务专用临时目录，加入 `PYTHONPATH`。使用 `--no-deps` 避免引入桌面依赖。将任务树的 `services/quant-api`、`packages/quant-core` 加入 `PYTHONPATH`。
2. 用 `mktemp -d /private/tmp/guiyi-v2-market-storage.XXXXXXXX` 建立私有目录，进入该目录并创建 `.vntrader`，避免上游读取或创建用户级目录。
3. 从该目录用 `benchmark.py --work "$PWD" freeze --config <私有配置绝对路径> --through 2026-11-25` 导出切片。仅在工作目录写入。后续运行需保留冻结副本，通过 `manifest.json` 核对身份。生产 active 分区若已有修订，从当前目录重新导出的结果可能产生新的快照。
4. 生成权限 0600 的 `pg.env`，内容为 `POSTGRES_PASSWORD=` 后接程序随机生成的 48 个小写十六进制字符。使用已验证 ARM64 PostgreSQL 镜像建立空白单次数据库 `guiyi_market_foundation_bench`，仅绑定 `127.0.0.1` 的随机高端口。用 `benchmark.py --work "$PWD" run --port <端口> --repetitions 25` 运行，同名输出使用独占创建。
5. `components.py` 默认只跑离线组件验证。已有授权时才传入 `--config <私有配置绝对路径>`，做一次明确合约与日期的 RQData 历史只读对照。完成后只清理任务专用实例。
