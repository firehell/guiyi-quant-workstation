# Market Foundation 切换准备

候选历史权威继续使用 **Canonical Parquet + 八表 Catalog**。切换对象是 Market 实时接入、盘口与活动 K 线展示、盘后发布凭证和牛哇参考消费。现役数据、源代次、消费水位及独立账户按当前运行身份工作。本阶段在已绑定的一次性环境中复演。

## 复演

1. 按 [组件证据](evidence/storage/README.md) 准备独立 VeighNa 4.4.0 headless 包、非默认端口 PostgreSQL 和专用 Redis 实例。Redis Pub/Sub 跨逻辑库共享。把工作树 API、quant-core 和 headless 路径加入 PYTHONPATH。
2. 用现有安全配置读取器准备 DATABASE_URL 和 REDIS_URL。PostgreSQL 使用 loopback 非默认端口及 guiyi_market_foundation 库。设置 GUIYI_NEWOW_REFERENCE_MODE=market_foundation_isolated、绝对路径 GUIYI_MARKET_FOUNDATION_SANDBOX，以及其中 canonical 子目录为 GUIYI_CANONICAL_DATA_ROOT。用已核验历史和元数据建立独立副本，保留 Calendar、Session、rank1、分区端点与源哈希。用同一候选代码升级隔离库并读回 schema。
3. 执行 [Tick 与完成流验证](evidence/tick/README.md) 及 [归档与 Reference 验证](evidence/archive-reference.md)。完整候选链通过 scripts/market_foundation/run_display.py 显式传入交易日、品种、私有 provider 配置、非默认 Web 端口与有限运行秒数。仅绑定 loopback。真实采样先确认权限、窗口和额度。容量测试有自己的 Redis 实例。
4. 隔离归档复用 guiyi data after-market。GUIYI_MARKET_FOUNDATION_PRODUCTS 使用与前台相同的精确小写逗号列表，例如 rb 或 rb,jm。先读回同一交易日的订阅及 rank1，再进入供应商就绪检查。读回 after-market-status.json 和 market-archive-receipts 下的精确凭证。按需以 python -m app.market_data.newow.market_reference_after_close --receipt 加 SHA256 补领该凭证。库尚无 Reference 流时，首张有效凭证按既有历史窗口规则生成并核验对应历史计划，再生成既有 Reference revision 和 v35 已开放的辅助／比较器快照。Web 构建使用 VITE_GUIYI_MARKET_FOUNDATION=1，连接同一隔离 API。本地 Vite 联调将 VITE_PROXY_API_TARGET 显式指向该非默认 loopback API，打开行情自由看盘与牛哇视图，按各自数据状态验证。
5. 按 [Market 查询](specs/market-series-query/spec.md)、[日常维护](specs/historical-data-maintenance/spec.md) 及 [Reference](specs/reference-trading/spec.md) 的候选条款核对换月、两日交叠、同端点修订和重启。以各自的输入与账本确认快期、苏冰和 Alert 水位，保留现有 P3/P4 研究读面。

## 正式操作前置

| 对象 | 核对要求 |
|---|---|
| 历史 | 核对 exact Catalog 版本、active URI、端点和质量。已选存储沿用现有不可变文件与单分区原子提交，无需格式迁移。 |
| 实时 | 冻结原源唯一末分钟、源 journal 尾、完成 journal 尾和消费者末水位。预检两类 journal 合计原件字节，保留目录需有足够空间。确认原 socket 与写入者已停，再预热候选。候选 Tick 使用独立 Redis 实例及 Tick 源标记。初始化只从经证的新交易日开始，旧源 Redis 进入原件保留与只读审计流程。首个完成端点必须是受证 Session、合约与新源代次上的未来端点。 |
| Web | 在同一已归档和盘中窗口读回合约、端点、盘口时间、历史修订和旧页游标。单独核对牛哇已保存的参考结果。 |
| 盘后 | 完整范围严格读回后才发凭证。核对同日补领、旧日修订与上一成功版本。仅移除已归档交易日的可重建缓存，保护下一交易日、观察原件和消费水位。 |
| 消费者 | 从合格凭证启动牛哇盘后参考。停旧计算前保全 Reference 原件、消息定位及恢复引用。快期和苏冰分别比对输入、账本及未决义务。既有 Alert 保留范围与一次性合同。 |

确认 registry CAS 尚未提交且旧前像可证明时，按停写前的定义恢复旧源并读回原水位。CAS 结果未知时先独立读回 registry 并保全现场。已证明 CAS 提交即按新代次前向恢复。目标仍为空时可使用同代基线恢复入口；已有观察时核对不可变原件、消费水位和待处理义务。Catalog 提交结果未知时同样先独立只读查明。符合正式切换和原件可读性条件后，按 [M1 依赖库存](evidence/M1-inventory.md) 的精确前置处理退役。

正式数据写入、源切换、发布和 Runtime 操作遵循 [部署合同](../../../deploy/README.md)。本次实施记录见 [任务状态](tasks.md)。


## 正式装配实施边界

- 正式 Tick 使用显式源模式及独立正式 Redis 实例。启动核对 PostgreSQL/Catalog、Canonical 根、Redis 实例和源标记。正式读端拒绝旧 bar namespace，候选隔离绑定仍单独校验。正式新 namespace 的原子基线包含已冻结交易日、完整 rank1 订阅、Live 和已启用 Alert 的初始游标。旧 Reference 游标留在退役实例供读回。
- 构建源切换版本时，在专用发布树先完成锁文件依赖安装，再用 `bash scripts/ops/macos/build-market-foundation.sh` 安装经 SHA256 锁定的 headless EventEngine 并构建对应 Web。归档凭证、Reference 领取及保存图表使用稳定运行目录 `market-foundation`，随发布树创建的盘后状态仍归 after-market binding。
- 常规 cohort 的进度和回退合同限定同一 Redis。跨实例切换使用独立的 macOS 入口。隔离复演中，正式 Tick 的 Live 和 Feed 在当天 CLOSED 时按权威下一场 Session 恢复已登记的次日基线。次日订阅和零游标来自既有目标 Redis，等待开盘期间只发布休市心跳。现场自然接收与发布另行验收。

采样脚本单窗口保留 3,600 秒上限。使用 `capture_tick.py --complete-trading-day` 时，单物理合约从权威首开盘前两分钟内启动，到最后时段结束后两分钟退出，墙钟不超过 24 小时。两种模式均保留 100,000 条和 60 MiB 行情记录上限。用 `--expected-contract` 将订阅锁定到独立读回的当日 rank1。检查末条的结束原因及 listener 状态。分片用
`compare_tick.py FIRST --capture-shard NEXT`，每片独立证明累计基线，丢弃相互冲突端点，
按完整 Session 输出缺失端点。旧格式没有结束记录，可用于逐值复核。
自然连测可用 `run_display.py --complete-trading-day` 绑定 Calendar 首尾，提前两分钟内启动并在当天最后时段后两分钟停机，上限 24 小时。真实采样与供应商历史对照仍使用已批准额度和窗口。


跨实例交接的隔离验证复用 cohort 的部署锁和一次 CAS。停旧后按交易日核对 source、completed、identity 索引和各接收游标，预检和保留共用两个 journal 合计 768 MiB 的原件上限。保留原始行及索引后再次读回。新实例在旧实例身份、目标实例身份和新交易日明确后一次性建立零位点，CAS 前重验。跨实例故障前像无法证明时停驻，CAS 结果未知时独立读取 registry。只有精确匹配新绑定才判为仅可前向恢复，其他不确定状态继续停驻。macOS 部署宿主提供只读账户预检 `install-local-services.sh --read-market-account-handover --trading-day YYYY-MM-DD`，可用 `--consumer tqkq` 或 `--consumer subing` 单独运行。快期从私有 SQLite 同一读事务核对投影和提交尾，再按 Catalog 核对逐品种物理合约及 H1 水位，并检查 monitor、Scope、账户读回有效期和恢复义务。苏冰从独立 PostgreSQL 只读快照校验 run、序号、哈希链和重放，再逐品种按原 stream ID 及 identity 索引核对末根分钟。入口按私有项目设置和 registry 解释现有 bar 源，输出不作为切换授权。

### macOS 跨实例入口

- `install-local-services.sh --plan-market-source-handover --candidate-root <release-root> --tag <application-tag> --commit <commit>` 输出计划。候选必须包含已发布的 Market Foundation 组件提交，并使用支持组件 tag 的 registry 合同。私有 `market-tick.env` 以现役 `project.env` 为前像，只改 `REDIS_URL` 并追加一行 `# guiyi-market-source: rqdata_tick`。注释让固定版本的账户配置解析器继续读取原配置格式。目标使用专用本地 Redis 实例和 db0。计划及公开读回保存摘要，凭据留在私有配置和进程内。
- `install-local-services.sh --apply-market-source-handover --plan <plan>` 单次执行。旧实例 source、completed、identity 索引、旧绑定所列全部品种的最后完成分钟和三条消费水位全部核对后，留存原件，再按新版 58 品种初始化目标交易日及零游标。PD、PT 的旧日志参与末端核验和留存。独立账户的旧进程退出与 owner lock 持有证明覆盖配置替换及 registry CAS。目标端先验证 Tick Feed 和凭证式 Reference 装配，再执行配置原子替换和 registry CAS。已存在的归档凭证须匹配完整 Catalog 修订；首张凭证缺席时 Reference 等待合格归档。
- `install-local-services.sh --read-market-source-recovery --plan <plan>` 独立核对实际 registry、私有 attempt、全局记录及配置身份。CAS 前的已知失败可按原定义恢复；阶段或写入结果不明时保留证据。registry 已切换后仅允许前向恢复。目标 Redis 若已初始化，其原件保留，后续尝试须重新证明目标清洁。
- 经 owner 单独批准后，`install-local-services.sh --recover-market-source-forward --plan <original-plan>` 可在首个目标 Session 前恢复已提交的同一代。入口只接纳真实 registry、两账户前像、旧流原件和目标空流均通过复核的停驻状态，按消费者、账户、Feed、日历顺序启动。原尝试记录逐字保留，恢复另记一次结果。已有目标观察或日历注册结果不明时继续停驻，另行核对业务前缀。
- `install-local-services.sh --read-market-source-first-completed --plan <plan>` 在 CAS 成功后只读核对目标 Redis 实例、正式 binding、原计划冻结的 rank1/Session 与原件索引。逐品种读回首次实际发布且通过 Bar、端点和时间校验的完成分钟，报告确认时间、stream ID、Tick 源代次，并单独标明首根是否覆盖开盘分钟。晚到、缺失和未开盘分别显示，退出码 2 表示待完整读回，1 表示证据阻断。建议在首个交易日归档清理订阅前执行。
- 快期 helper 的旧、新 Redis 预检均需要按 PID 匹配 macOS 与 Redis 两端的 TCP 元组及 DB0 订阅。直接 loopback 或保留该元组的网络路径可证；改写元组的本地端口转发会阻断，Redis 全局频道计数不能证明进程归属。发现现役拓扑无法证明时须单独处理后重新预检。
- `install-local-services.sh --read-market-source-accounts --plan <plan>` 在目标首个交易日结束后、任一账户开始提交次日数据前独立读回。快期核对原生 H1 水位和实际 Market helper socket。苏冰使用原 checkout 与原 run，验证冻结前缀和目标 completed journal 的新增分钟。休市启动确认原 run、原账本和固定版本配置解析，实际提交须等目标自然分钟。

## Compute、Web 接口与待联验

| 消费面 | 可依赖的 Market 合同 | 现场待验 |
|---|---|---|
| Compute 历史 | `MarketDataService.query`、`query_page`、`query_contract_trading_days` 提供七周期已完成行情、物理合约段、端点及数据修订。strict 查询保留质量错误；需要质量事实的领域走已有显式入口。盘后 `MarketArchiveReceipt` 使用交易日、发布完成时间、凭证身份和逐品种修订，由消费者负责计算、去重与恢复。 | 目标全量首份自然归档凭证和并发 Canonical 消费，上次成功版本及下一交易日原件读回。 |
| Compute Live、快期、苏冰 | `ObservationStream(kind="completed")` 的原件和身份索引是完成输入；Pub/Sub 用于唤醒。原件包含交易日、物理合约、周期、端点、确认时间、Tick 源代次及 `notification_eligible`。晚到原件保留，正式触发按资格和独立消费者游标处理。 | 目标首根自然完成分钟、快期和苏冰分别使用新 Redis 推进原账户水位、消费者重启后无重复推进。 |
| Web | `/api/v1/market/bars/page`、`/state`、`/chart-progress` 及 WebSocket `/ws`、`/research/home-live/ws` 沿用既有端点。历史与完成序列按物理合约和数据修订读取，`preview` 帧承载报价、盘口和活动 Bar。牛哇 `/api/v1/reference-trading/newow/after-close` 及其 section/presentation 读取已保存的盘后结果。 | 同目标历史和 Live 窗口联验分页、换月、复市状态与 WebSocket 恢复；归档后核对牛哇已保存版本。 |


并行 C6 的 Paper 启动接口计划为 `run-paper-market-compute.py --paper-root <冻结 checkout>`。联合候选需由部署侧核验新 plist 的精确入口、AppSupport 脚本内容和锁定的 Core 0.4.1 候选 API Python，并核对冻结 Paper checkout `2be7a62af8cd38be67d9d1b671e132673e44f91e` 恢复原 run，传给原生入口的参数仅为 `--refresh-facts`。本候选的 `_paper_identity` 仍识别既有 plist。Compute 继续通过项目配置识别 Tick 源，Canonical 通知沿用已发布归档凭证。
