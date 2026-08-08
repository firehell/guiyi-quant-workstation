## Context

见 `proposal.md`。当前实现已拥有 DatasetKey、Catalog/Manifest/Gap/MainContractMap 和 MarketDataService 雏形，也保留 MarketDataFile/Profile/Binding/QualityReport、actual_dominant 物理 Dataset、多种浅层 CLI service 与一次性迁移工具。生产已有大量 raw/processed/Canonical 与旧表，代码实现必须先在 fixture、临时目录和隔离 PostgreSQL 中闭环，任何真实 RQData、生产 DB 或正式 Canonical 操作均停在独立执行 Gate 前。

本设计同时吸收 `m3-v2-production-correctness` 的精确缺口、实际交易所 identity、完整 ISO 周和固定水位 NOOP 要求。个人单用户边界允许使用一个 provider、一个 canonical root、一个 active Catalog 和月分区原子替换，不需要多 provider seam、任务中心、active binding 或多版本在线裁决。

## Goals / Non-Goals

**Goals:**

- 一个数据概念只有一个 active 身份、一个发布链路和一个读取入口。
- 既有全量历史通过一次性白名单 bootstrap 与问题窗口精确重下迁入，之后只运行可重用的日增量。
- 数据错误在发布前阻断；已发布问题可按月精确 repair；任何严格查询遇 Gap 或 identity 漂移 fail-closed。
- 代码结构以三个深模块承载变化，不把下载、聚合、校验和发布复制到多个命令。

**Non-Goals:**

- 不支持多 provider、插件、分布式任务编排、多用户权限或通用 lineage 平台。
- 不保留旧 API/DB/CLI compatibility，不删除本次未纳入 active 的 raw/processed 文件。
- 不重建回测、Signal/Review、盘中 live、通知、调度启用或订单能力。
- 不为不可逆旧表 drop 设计数据库备份或应用级恢复流程；生产执行仍必须由精确 Gate 控制。

## Decisions

### D1 — 四字段物理 DatasetKey，query kind 与 storage kind 分离

物理 `DatasetKind` 只保留 `continuous|contract`，四字段 DatasetKey 完整表达目录与 Catalog identity；`actual_dominant` 仅为 `SeriesQuery`。provider、adjustment 和 schema version 是内容来源/格式属性，进入 Manifest。

替代方案是继续把 actual_dominant、provider、adjustment、schema 放进 Dataset identity；这会重复保存真实合约片段并让固定常量污染路径，因此拒绝。

### D2 — 每月单 current 分区和交换式发布

`CanonicalMonthlyStore` 在 canonical root 内创建同目录临时 Parquet/Manifest，完成 schema、row count、checksum 与 fsync 后以原子 replace 发布，再在同一数据库事务 upsert 唯一月 Catalog。若 Catalog 提交失败，恢复调用前文件状态或使该月不可被 Catalog 发现；reader 只信 Catalog+Manifest，不 glob 临时文件。

替代方案包括 immutable version 目录加 active pointer、overlay 与 append-only exact windows。个人工作站无需保留多版本 active，且重叠选择会恢复第二套 selector，故拒绝。

### D3 — CanonicalBar 与 ProviderBarBatch 在边界转换

RQData adapter 和一次性 legacy adapter 只负责把来源列映射为 `ProviderBarBatch`；统一 normalizer 再生成最小 CanonicalBar。Dataset identity 在 batch envelope，不写入行。Decimal 由 Arrow decimal128 约束，时间先按实际交易时段解释再转 UTC bar_end。

替代方案是让每个 adapter 直接写 Parquet；这会复制校验、时区与 Decimal 语义，故拒绝。

### D4 — 六项校验由发布器内的固定 pipeline 执行

校验器按 schema、primary key、OHLCV、session/frequency、coverage、physical consistency 顺序短路。业务失败生成/保留 current DataGap；结构失败中止全局。没有 DataQualityReport 或 generic report 模型，结构化 action result 足以支持 CLI 和审计。

替代方案是可注册 validation plugin 或质量报告表；对一个 provider 和固定七周期属于过度设计，故拒绝。

### D5 — HistoricalDataManager 是唯一写应用服务

公开四动作映射到同一个内部执行管线：`desired coverage → exact monthly windows → provider/legacy batch → normalize → validate → publish direct → aggregate derived → strict verify → reconcile gaps`。update 使用 RQData；migration bootstrap 暂时允许 legacy source；repair 只执行 exact plan；audit 只读。metadata synchronizer 在 apply 最终规划前运行，dry-run 只计算需要刷新而不构造远程 client。

替代方案是保留 download/aggregate/sync/verify commands 各自 service；这正是重复算法来源，故删除。

### D6 — 覆盖规划以交易日和月为最小持久化单位

planner 用 Calendar/Session、product start、fixed through、Catalog partition coverage、DataGap 和 MainContractMap 得到 TargetWindow；可以在月内精确下载缺口，但发布时合并该月已有可信数据并原子重写整月。`--since` 只裁剪检查域，不刷新 covered 数据。closed month 仅显式 repair 可替换。

替代方案是每个洞一个 Parquet 或只看尾部水位；前者制造 overlay，后者遗漏中间洞，故拒绝。

### D7 — Derived 只读 Canonical 1m 和实际 session

5m/15m/30m/60m 在 Direct 1m 发布成功后，从同一 Catalog 读取相交 1m 月分区，以实际交易所 session 划桶。Manifest 记录完整 source 1m digest 集合和 session digest。1d/1w 仍为 RQData direct；weekly watermark 是最新完整 ISO 周最后交易日。

替代方案是 provider 直接供派生周期或从 raw staging 聚合；二者会让 direct/derived 质量入口分叉，故拒绝。

### D8 — actual_dominant 动态拼接与周 owner

日内/日线按 MainContractMap trade_date 展开连续真实合约片段并严格读取；1w 先从 TradingCalendar 得到完整 ISO 周最后交易日，再以该日 rank1 合约选择整周真实合约 bar。查询返回 map digest 和 resolved segments，禁止回退 continuous。

替代方案是持久化拼接 Parquet或按周内逐日混合；前者重复资产，后者不对应真实合约周 bar，故拒绝。

### D9 — PostgreSQL 只存当前元数据与轻量 Catalog

MainContractMap 和 contract_specs 使用自然事实唯一键 upsert 当前事实；market_partitions 使用 dataset+year+month 唯一；DataGap 成功修复即删除。旧任务、文件、质量报告、generic futures 表全部不可逆 drop，不新建运行历史表。

替代方案是保留 legacy tables 只读或增加 resolved/history 状态；会延长两套语言且无个人使用价值，故拒绝。

### D10 — 一次性 migration adapter 与最终删除

legacy adapter 通过固定根与文件 schema 白名单识别候选，禁止 generic glob+guess；同一窗口多候选不仲裁，直接进入精确 RQData 重下计划。Gate C 通过后，在同一 change 删除 adapter、task07/receipt/shadow 工具与 active references，最终 bootstrap 只调用 RQData。

替代方案是长期保留 importer 兼容旧 raw；会使旧数据重新成为 active 事实源，故拒绝。

### D11 — CLI、API 与错误模型

CLI 顶层 action result 包含固定 through、planned/applied/noop/blocked/failed counts、每品种结果与有界 reason code；默认 dry-run，`--apply` 只选择写路径且不绕过外部执行 Gate。Market API 只暴露 SeriesQuery 和可复算 lineage；任何旧字段直接删除而非 deprecate。

替代方案是兼容参数、双响应 schema 或 access mode toggle；均会保留旧选择语义，故拒绝。

## Risks / Trade-offs

- [单月重写在超大 1m 月份有额外 IO] → 以自然月限制重写范围，DuckDB/PyArrow 只读所需列；个人工作站优先一致性。
- [文件 replace 与 Catalog transaction 无法形成跨系统 ACID] → reader 只信 Catalog+Manifest；发布使用同目录 temp、checksum、可恢复交换顺序和失败注入测试，最后有效分区不被半成品覆盖。
- [legacy 文件身份或 session 语义不可信] → 白名单仍走六项校验；任何歧义整窗 RQData 重下，不逐行裁决。
- [不可逆 drop 会让旧页面/脚本立即失败] → 同一代码变更先扫描并删除所有 active callers，在隔离 migration 与 API/Web tests 后才进入生产 Gate B。
- [RQData 修订会改变已关闭月份] → routine update 不改 closed month；审计发现后生成 exact repair plan，由显式 repair 替换受影响月。
- [69 品种一次 bootstrap 时间长且可能部分失败] → 固定 through、按品种隔离、结构错误全局中止、业务错误可重跑；候选根和隔离 Catalog 不影响当前生产读取。

## Migration Plan

1. 创建并严格验证本 change；完整吸收旧 M3 后把旧 change 作为 superseded history 归档，不同步其未完成 specs。
2. 以 fixture、临时 canonical root 和隔离 PostgreSQL TDD 实现 domain、ORM/migration、三个深模块、CLI/API/Web；不访问真实 RQData 或生产资源。
3. 删除 active legacy callers 与最终不再需要的兼容代码；运行 backend、migration、frontend、CLI 与旧语言扫描。
4. Gate A 前只生成候选构建 dry-run，明确 69 品种、fixed through、候选根、预计 Dataset/月分区、legacy 白名单和精确 RQData windows。收到新的单次意图后才能创建隔离候选数据。
5. Gate B 前输出生产表、候选根、正式根和服务范围。收到另一份单次意图后才能在短维护窗口执行不可逆 migration、Catalog 写入与 root 原子切换。
6. Gate C 只读/NOOP 验收要求 DataGap=0、全部预期七周期可读、主力跨换月/周线正确、相同 fixed through 为零目标零写入零远程；scheduler/live/notification/order 仍关闭。
7. Gate C 通过后删除 migration-only adapter 与 superseded active 工具，完成最终验证并 archive 本 change。main/release/Runtime 不在本 change 授权内。

按用户决策，不为生产旧表 drop 设计应用级 rollback。Gate A 在隔离候选根失败时丢弃候选即可；Gate B 失败必须保持 API 停止并报告实际状态，不以兼容表或旧 selector 静默回退。
