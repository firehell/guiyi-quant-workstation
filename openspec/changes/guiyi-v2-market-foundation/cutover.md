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
| 实时 | 冻结原源末分钟、源 journal 尾、完成 journal 尾和消费者末水位。确认原 socket 与写入者已停，再预热候选。候选 Tick 使用独立 Redis 实例及 Tick 源标记。初始化只从经证的新交易日开始，旧源 Redis 进入原件保留与只读审计流程。首个完成端点必须是受证 Session、合约与新源代次上的未来端点。 |
| Web | 在同一已归档和盘中窗口读回合约、端点、盘口时间、历史修订和旧页游标。单独核对牛哇已保存的参考结果。 |
| 盘后 | 完整范围严格读回后才发凭证。核对同日补领、旧日修订与上一成功版本。仅移除已归档交易日的可重建缓存，保护下一交易日、观察原件和消费水位。 |
| 消费者 | 从合格凭证启动牛哇盘后参考。停旧计算前保全 Reference 原件、消息定位及恢复引用。快期和苏冰分别比对输入、账本及未决义务。既有 Alert 保留范围与一次性合同。 |

新源尚未发布有效事实时，按已有 Runtime 交接合同恢复原源并读回原水位。新源已经发布后，按新代次的不可变原件、消费水位和待处理义务前向恢复。Redis 缓存可用已证明的原件重建。Catalog 提交结果未知时先独立只读查明。符合正式切换和原件可读性条件后，按 [M1 依赖库存](evidence/M1-inventory.md) 的精确前置处理退役。

正式数据写入、源切换、发布和 Runtime 操作遵循 [部署合同](../../../deploy/README.md)。本次实施记录见 [任务状态](tasks.md)。


## 正式装配实施边界

- 正式 Tick 使用显式源模式及独立正式 Redis 实例。启动核对 PostgreSQL/Catalog、Canonical 根、Redis 实例和源标记。正式读端拒绝旧 bar namespace，候选隔离绑定仍单独校验。正式新 namespace 的原子基线包含已冻结交易日、完整 rank1 订阅、Live 和已启用 Alert 的初始游标。旧 Reference 游标留在退役实例供读回。
- 构建源切换版本时，在专用发布树先完成锁文件依赖安装，再用 `bash scripts/ops/macos/build-market-foundation.sh` 安装经 SHA256 锁定的 headless EventEngine 并构建对应 Web。归档凭证、Reference 领取及保存图表使用稳定运行目录 `market-foundation`，随发布树创建的盘后状态仍归 after-market binding。
- 常规 cohort 的进度和回退合同限定同一 Redis，目前会拒绝 Tick 模式。正式切换仍须接通独立的跨实例 cohort 计划、停旧证明、原子 binding 和快期/苏冰独立接管，并完成正式迟到归档恢复路由。旧迟到任务在 Tick 模式保全状态并拒绝任何未经严格归档读回的清理。当前无需切换或执行正式初始化。

采样脚本保留 3,600 秒和 100,000 条上限。检查末条的结束原因及 listener 状态。分片用
`compare_tick.py FIRST --capture-shard NEXT`，每片独立证明累计基线，丢弃相互冲突端点，
按完整 Session 输出缺失端点。旧格式没有结束记录，可用于逐值复核。
自然连测可用 `run_display.py --complete-trading-day` 绑定 Calendar 首尾，提前两分钟内启动并在当天最后时段后两分钟停机，上限 24 小时。真实采样与供应商历史对照仍使用已批准额度和窗口。


跨实例交接的隔离验证复用 cohort 的部署锁和一次 CAS。停旧后按交易日核对 source、completed、identity 索引和各接收游标，落原件并再次读回。新实例在旧实例身份、目标实例身份和新交易日明确后一次性建立零位点，CAS 前重验。跨实例故障前像无法证明时停驻，CAS 结果未知时独立读取 registry。只有精确匹配新绑定才判为仅可前向恢复，其他不确定状态继续停驻。常规 macOS 入口仍受保护，待快期和苏冰各自的生产接管证明与配置入口接通后才允许使用该路径。
