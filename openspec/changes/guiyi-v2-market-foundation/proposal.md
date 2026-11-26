# 归一量化 V2 · 市场与数据底座

2026-11-26 · owner 已确认架构方向，尚未实施、选定最终历史存储或授权生产切换。

## Why

个人本地工作站应将开发投入集中于策略、研究、复盘和独立模拟，而非维护通用行情基础设施。现有 RQData 完整 1m、Canonical Parquet、Catalog、Session、Redis 和 MarketDataService 已有业务合同与运行证据；不得因框架成熟度直接推断替代方案更快或更稳定。以可删除的自研复杂度、数据正确性、稳定性和本机实际性能共同选型。

## What Changes

- RQData 继续为 Market 历史和实时来源；实时目标升级为 Tick 长连接，优先复用 VeighNa 4.4.0 通用组件，保留薄适配。
- 现有七个周期 1m/5m/15m/30m/60m/1d/1w 及物理合约、交易日、主力映射合同继续成立。通过对照决定原生 BarGenerator、Datafeed、Database、DataRecorder、EventEngine 和 DataManager 的实际复用范围，不强制整套桌面宿主或 GUI。
- 历史存储在 VeighNa PostgreSQL 与现有 Parquet + Catalog 中择一。未证明可替换前保留现役权威；不建立长期双写、第二正式库或通用插件平台。
- 盘中以历史 + Live 已确认及活动 K 线组成统一行情视图；盘后从 RQData 下载权威 1m 和交易所日行情、校验、派生、发布；仅清理可重建实时缓存，保护决策及恢复原件。
- 市场数据成功发布只触发既有获准的盘后消费者，牛哇不订阅 Tick 或盘中计算；快期 HTDY、苏冰 Paper 继续独立消费既有合格输入。

## Capabilities

新增候选能力 `guiyi-v2-market-foundation`，完整目标见 [spec](specs/guiyi-v2-market-foundation/spec.md)，取舍见 [design](design.md)，实施见 [tasks](tasks.md)。

## Scope / Non-goals

- Market 的消费者是行情 Web、基于 Market 的观察/参考计算以及现有独立模拟输入。RQAlpha 由其独立研究域维护数据、交易参数、数据更新和数据身份；本阶段不为 RQAlpha 下载、适配、迁移、对齐、压测其数据或改造其回测引擎。只保护既有消费者，不为新 Market 绑定 RQAlpha；如旧隔离研究仍有 MDS 依赖，先保留兼容的原路径，另行处理，不据此认定独立数据已实现。
- 不修改策略公式、历史收益、账本、账户、通知、真实交易权限或现有 Web 产品面；`auto_order=false`。不新增牛哇模拟账户，不复活 P5/P6 新牛哇实时交易方案。
- 保持模块化单体、本地单用户；不引入分布式中间件、不扩大正式品种范围。60 品种现役范围与 70 品种隔离容量测试分开。
- 当前交办仅设计文档、Review、集成 develop；任务列表不是执行生产操作的授权。

## Impact and precedence

基于 develop `9ad754251fb6c0912834f843ec348a756cad76eb`；现役依据为 [AGENTS](../../../AGENTS.md)、[STATUS](../../../STATUS.md)、[DATA_CENTER](../../../docs/DATA_CENTER.md)、[ARCHITECTURE](../../../docs/ARCHITECTURE.md) 和 [DECISIONS](../../../DECISIONS.md)。[上层 V2 change](../guiyi-v2-rearchitecture/proposal.md) 的盘后/独立模拟隔离目标不变；其旧 MDS→RQAlpha 研究数据耦合不作为本阶段目标。研究独立数据实现另行设计，现有试验与结果保留。

当前 accepted `canonical-market-storage`、`data-foundation-metadata`、`historical-data-maintenance`、`market-series-query`、`product-retirement` 及现有 Alert/Reference/独立账户合同继续有效。此新增候选规格不直接修改 active 权威。选型完成后，按实际替换内容形成精确 MODIFIED/REMOVED delta（完整 requirement 与 scenarios），同步 AGENTS / DECISIONS / DATA_CENTER / ARCHITECTURE 及上层 V2 Market 条款，Review 后才实施正式切换；不得同时存在冲突的 active authority。生产数据、现役停写、发布 main/tag、Runtime 均另行明确授权。
