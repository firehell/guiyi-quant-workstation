# 盘后归档与牛哇参考隔离验收

归档复用 18:05 维护入口及现有 RQData 就绪、质量校验、Session 聚合与单分区 Catalog 提交。隔离装配在清理前另开 PostgreSQL 只读事务和维护锁，确认完整范围无待发布目标，且本次最终指针与已验证 Parquet 一致。仅清理指定交易日的可重建分钟缓存及订阅。成功状态和独立可补领凭证绑定交易日、范围、Catalog 版本及清理读回。相同交易日和版本重复运行只形成一个逻辑凭证。同日或旧日修订进入后续已验证范围时获得新版本。已完成缓存清理后中断可依据已存前像及当前读回复原成功状态。缺少可核对前像或提交结果未知的运行停留在原状态，保留后续独立只读处置所需事实。

牛哇用已有历史 Reference planner、策略适配、投影、仓储及恢复器，在 Market 锁外领取已核验归档凭证。首个凭证可从空 Reference 库按正式历史窗和精确计划哈希建立该凭证范围内的系列。正式历史读取之前在现有 Catalog lease 内验证来源版本。完成的策略系列复用同一持久化运行身份，整组完整后记录领取确认。只读 API 和隔离 Web 从已提交引用版本显示日期、持久化计算时点、收益和参考记录。主图按冻结快照读取已保存的状态、提示、主图线和动作，标记及线段须匹配物理合约、交易日、端点和精确 K 线指纹；换段或数据修订会断开图层。现有 v35 辅助指标及震荡五档比较器在相同保存截止点物化。默认 500 根图窗和各区块同时绑定完整 Canonical 输入证明、归档凭证、引用版本和序列。读 API 验证已保存工件摘要，按历史 UI 合同返回已保存结果和对应冻结图窗。解释层仍显示延期状态。现有 P3/P4 RQAlpha 入口和结果保留原路径。

## 隔离复验

- Mac mini M4 上使用一次性 PostgreSQL 16 和 Redis 7（ARM64 容器、不同于正式服务的随机 loopback 端口、专用测试库）。输入为固定的合成历史和观察事件。真实事务验证独立只读连接、advisory lease、完整范围、指针冲突、不可变文件、提交／回滚和进程崩溃前后可见性。首个凭证的单品种测试建立 24 个正式历史 Reference 系列，保存 18 套基础策略区块，并验证重复领取、MACD 与五档比较器读取、以及损坏工件拒绝。Redis 验证按交易日清理旧缓存，保全下一交易日缓存与两日观察原件。
- 以 pytest 运行归档、Catalog、Redis 观察、Tick 隔离、历史刷新、历史窗口和五档比较器定向集，结果为 291 通过、4 跳过。三个 Tick 隔离测试需另一组专用数据库变量，另一个比较器测试需本机冻结的 Task13 证据。PostgreSQL 历史刷新在此结果中实际运行。复验按 [TESTING](../../../../TESTING.md) 指定 `GUIYI_ISOLATED_PUBLICATION_DATABASE_URL`、`GUIYI_ISOLATED_MIGRATION_DATABASE_URL` 和 `GUIYI_TEST_REDIS_PORT`。对照用的 PostgreSQL fixture 补齐了严格 MDS 所需的品种、交易日历和 Session，保留原有可见性与崩溃断言。
- Web 使用 `VITE_GUIYI_MARKET_FOUNDATION=1 pnpm -C apps/quant-web run build` 验证类型、构建和 bundle 拓扑。候选页面使用绑定在隔离应用的 Reference 会话读取，无策略计算入口。

隔离运行配置使用 `GUIYI_NEWOW_REFERENCE_MODE=market_foundation_isolated`、绝对且已存在的 `GUIYI_MARKET_FOUNDATION_SANDBOX`、该目录下的 `canonical`、loopback 非默认端口和专用 `guiyi_market_foundation` 库。隔离归档可复用 `guiyi data after-market`，以前序任务准备的独立数据、Redis 和库为输入。通过 `GUIYI_MARKET_FOUNDATION_PRODUCTS` 指定与前台一致的精确品种（如 `rb` 或 `rb,jm`），归档先核对所选交易日完整 Redis 订阅与 Catalog rank1，再访问供应商。查看和补领已签发的精确凭证使用 `python -m app.market_data.newow.market_reference_after_close --receipt <sha256>`。待验包括真实供应商盘后就绪、完整 60 品种的归档及参考更新耗时、自然夜盘并发和正式切换。

独立 Review 复验同一交易日首次成功、后续供应商未就绪、再次成功及 Tick 重启。运行者从同日同范围的不可变成功凭证核对清理证明，缓存仅清理一次。盘后触发使用释放维护锁前冻结的 exact 凭证路径，后续可变状态不会替换其身份。

扩展 Newow／Reference 套件在开发中观察到 90 项失败。对这 90 项分别使用确认基线和候选复跑，基线仍失败 90 项，候选失败 73 项。17 项对照测试夹具修正了已冻结比较器的规则身份，业务断言保持。该扩展复核没有发现新增失败。
