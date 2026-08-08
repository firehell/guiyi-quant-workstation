## Context

见 `proposal.md`。当前实现已拥有 DatasetKey、Catalog/Manifest/Gap/MainContractMap 和 MarketDataService，也已收敛 Market Web / CLI / 最小 schema 候选。生产仍停在 `20260808_0035`，正式 Canonical 尚未切换。代码实现必须先在 fixture、临时目录和隔离 PostgreSQL 中闭环，任何真实 RQData、生产 DB 或正式 Canonical 操作均停在独立执行 Gate 前。

本设计同时吸收 `m3-v2-production-correctness` 的精确缺口、实际交易所 identity、完整 ISO 周和固定水位 NOOP 要求。个人单用户边界允许使用一个 provider、一个 canonical root、一个 active Catalog 和月分区原子替换，不需要多 provider seam、任务中心、active binding 或多版本在线裁决。

**本轮收口决策（Recent Trusted Window）**：不再扩展 legacy-assisted full-history Gate A。V1 active 历史下界冻结为 `active_history_floor = 2023-01-01`；Candidate 构建复用正常 `HistoricalDataManager.update`（`legacy=None`），只增加最薄的隔离 composition。

## Goals / Non-Goals

**Goals:**

- 一个数据概念只有一个 active 身份、一个发布链路和一个读取入口。
- V1 以 RQData-only Recent Trusted Window（`effective_start → fixed through`）构建隔离 Candidate，之后只运行可重用的日增量。
- 数据错误在发布前阻断；已发布问题可按月精确 repair；任何严格查询遇 Gap 或 identity 漂移 fail-closed。
- 代码结构以三个深模块承载变化，不把下载、聚合、校验和发布复制到多个命令。

**Non-Goals:**

- 不支持多 provider、插件、分布式任务编排、多用户权限或通用 lineage 平台。
- 不保留旧 API/DB/CLI compatibility，不删除本次未纳入 active 的 raw/processed 文件。
- 不重建回测、Signal/Review、盘中 live、通知、调度启用或订单能力。
- 不为不可逆旧表 drop 设计数据库备份或应用级恢复流程；生产执行仍必须由精确 Gate 控制。
- 不在本轮重新设计 DatasetKey、Catalog、月分区或 MarketDataService；不把 1999+ 全历史纳入 V1 active。

## Decisions

### D1 — 四字段物理 DatasetKey，query kind 与 storage kind 分离

物理 `DatasetKind` 只保留 `continuous|contract`，四字段 DatasetKey 完整表达目录与 Catalog identity；`actual_dominant` 仅为 `SeriesQuery`。provider、adjustment 和 schema version 是内容来源/格式属性，进入 Manifest。

替代方案是继续把 actual_dominant、provider、adjustment、schema 放进 Dataset identity；这会重复保存真实合约片段并让固定常量污染路径，因此拒绝。

### D2 — 每月单 current 分区和交换式发布

`CanonicalMonthlyStore` 在 canonical root 内创建同目录临时 Parquet/Manifest，完成 schema、row count、checksum 与 fsync 后以原子 replace 发布，再在同一数据库事务 upsert 唯一月 Catalog。若 Catalog 提交失败，恢复调用前文件状态或使该月不可被 Catalog 发现；reader 只信 Catalog+Manifest，不 glob 临时文件。

替代方案包括 immutable version 目录加 active pointer、overlay 与 append-only exact windows。个人工作站无需保留多版本 active，且重叠选择会恢复第二套 selector，故拒绝。

### D3 — CanonicalBar 与 ProviderBarBatch 在边界转换

RQData adapter 和（已 freeze 的）migration-only legacy adapter 只负责把来源列映射为 `ProviderBarBatch`；统一 normalizer 再生成最小 CanonicalBar。Dataset identity 在 batch envelope，不写入行。Decimal 由 Arrow decimal128 约束，时间先按实际交易时段解释再转 UTC bar_end。

替代方案是让每个 adapter 直接写 Parquet；这会复制校验、时区与 Decimal 语义，故拒绝。

### D4 — 六项校验由发布器内的固定 pipeline 执行

校验器按 schema、primary key、OHLCV、session/frequency、coverage、physical consistency 顺序短路。业务失败生成/保留 current DataGap；结构失败中止全局。没有 DataQualityReport 或 generic report 模型，结构化 action result 足以支持 CLI 和审计。

替代方案是可注册 validation plugin 或质量报告表；对一个 provider 和固定七周期属于过度设计，故拒绝。

### D5 — HistoricalDataManager 是唯一写应用服务

公开四动作映射到同一个内部执行管线：`desired coverage → exact monthly windows → provider batch → normalize → validate → publish direct → aggregate derived → strict verify → reconcile gaps`。日常 update 与新 Gate A Candidate 均使用 RQData，`legacy=None`；既有 migration-only bootstrap 的 legacy source 进入 freeze，不再作为新 Gate A 数据源；repair 只执行 exact plan；audit 只读。metadata synchronizer 在 apply 最终规划前运行，dry-run 只计算需要刷新而不构造远程 client。

替代方案是保留 download/aggregate/sync/verify commands 各自 service；这正是重复算法来源，故删除。也不新建第二套 Candidate 重建引擎。

### D6 — 覆盖规划以交易日和月为最小持久化单位，并受 active_history_floor 约束

planner 用 Calendar/Session、`effective_start`、fixed through、Catalog partition coverage、DataGap 和 MainContractMap 得到 TargetWindow。`product_window_starts.csv` 继续保存长期 provider/listing 起点事实，不得被本轮改写。V1 正式：

```text
effective_start(symbol) = max(product_window_start(symbol), active_history_floor)
active_history_floor = 2023-01-01  # data/universe/active_history_floor.txt
```

品种期望交易日是交易所开市日与真实合约上市期的交集，再与 effective_start 相交。continuous/contract/actual-dominant 的 active 维护均从 effective_start 起；首个 rank1 事实之后的内部映射洞仍严格失败。可以在月内精确下载缺口，但发布时合并该月已有可信数据并原子重写整月。`--since` 只裁剪检查域，不刷新 covered 数据。closed month 仅显式 repair 可替换。

替代方案是每个洞一个 Parquet 或只看尾部水位；前者制造 overlay，后者遗漏中间洞，故拒绝。也不把 V1 floor 写回 CSV 长期事实。

### D7 — Derived 只读 Canonical 1m 和实际 session

5m/15m/30m/60m 在 Direct 1m 发布成功后，从同一 Catalog 读取相交 1m 月分区，以实际交易所 session 划桶。Manifest 记录完整 source 1m digest 集合和 session digest。1d/1w 仍为 RQData direct；weekly watermark 是最新完整 ISO 周最后交易日。

替代方案是 provider 直接供派生周期或从 raw staging 聚合；二者会让 direct/derived 质量入口分叉，故拒绝。

### D8 — actual_dominant 动态拼接与周 owner

日内/日线按 MainContractMap trade_date 展开连续真实合约片段并严格读取；1w 先从 TradingCalendar 得到完整 ISO 周最后交易日，再以该日 rank1 合约选择整周真实合约 bar。查询返回 map digest 和 resolved segments，禁止回退 continuous。

替代方案是持久化拼接 Parquet或按周内逐日混合；前者重复资产，后者不对应真实合约周 bar，故拒绝。

### D9 — PostgreSQL 只存当前元数据与轻量 Catalog

MainContractMap 和 contract_specs 使用自然事实唯一键 upsert 当前事实；market_partitions 使用 dataset+year+month 唯一；DataGap 成功修复即删除。旧任务、文件、质量报告、generic futures 表全部不可逆 drop，不新建运行历史表。

替代方案是保留 legacy tables 只读或增加 resolved/history 状态；会延长两套语言且无个人使用价值，故拒绝。

### D10 — Legacy migration adapter freeze，Gate C 后删除

既有 legacy adapter（任务 4.8）通过固定根与文件 schema 白名单识别候选，已实现并本地验证，但进入 freeze：不新增能力、不继续修历史 edge case、不参加新的 Gate A。新 Gate A 只允许 RQData-only Candidate composition。Gate C 通过后，在同一 change 删除 adapter 与 active references；最终空 Catalog + 空 Canonical 重建只调用 RQData，自 `active_history_floor` 起。

替代方案是继续以 legacy 作为 Gate A 主路径或长期保留 importer；会使旧数据重新成为 active 事实源，故拒绝。

### D11 — CLI、API 与错误模型

CLI 顶层 action result 包含固定 through、planned/applied/noop/blocked/failed counts、每品种结果与有界 reason code；默认 dry-run，`--apply` 只选择写路径且不绕过外部执行 Gate。Market API 只暴露 SeriesQuery 和可复算 lineage；任何旧字段直接删除而非 deprecate。

替代方案是兼容参数、双响应 schema 或 access mode toggle；均会保留旧选择语义，故拒绝。

### D12 — Metadata 维护窗跟随 Recent Trusted Window

Bars、MainContractMap、ContractSpec 的同步/维护窗为 `effective_start → fixed through`。Calendar 允许 `month_start(active_history_floor) - 1 month` 起的最小前置 context，用于 previous trading day、night session 与首个完整 ISO week；不得因 bars 只维护 2023+ 而重新同步 1999+ 的 Map/Spec。

### D13 — 薄 Candidate composition，不新建引擎

`build_candidate_historical_data_manager(candidate_session, candidate_root)` 仅组装隔离 Session + 隔离 Canonical root + 现有 `HistoricalDataManager` / `MetadataSynchronizer` / `RQDataMarketAdapter` / `CanonicalMonthlyStore`，且 `legacy=None`。Candidate root 与正式 root 必须完全隔离。不得复制覆盖规划或发布算法。

### D14 — C2.5 以唯一 Candidate target 与严格前置检查运行

单一 Candidate metadata SHALL 保存两类状态。不可变 identity 精确为隔离 Catalog/Session identity、Canonical root identity、active-universe digest、active_history_floor、source policy（`RQData-only` 且 `legacy=None`）和 candidate code SHA；root identity 以稳定非敏感摘要保存，不能以完整本地路径代替。可变状态只包含 `recorded_through`，并与上述 identity 同一份 Candidate metadata 持久化。不得接受多个 root、隐式默认 root 或跨 identity 续跑。

首次构建只接受空 Candidate 的 fresh 检查。后续 extend 只在请求 identity 与记录 identity 完全一致、并且 `requested_through >= recorded_through` 时允许；成功后 metadata 以 `max(recorded_through, requested_through)` 单调更新 through。identity 不同、metadata 缺失、target 非空却声明 fresh，或 through 倒退时，必须在构造 RQData client 或任何写入前失败。

不提供 reset、resume、清空 Candidate 或从失败中自动恢复的操作符；失败诊断由新的明确 fresh/extend 调用处理。direct `1w` 在请求边界显式映射为 provider weekly 请求，不能从 `1d` 或 `1m` 替代。历史 Calendar/Session 必须作为 Candidate 的可校验事实覆盖其 effective window 及最小前置 context。

诊断 schema 的允许顶层字段精确为 `reason_code`、`mode`、`candidate_identity_digest`、`recorded_through`、`requested_through`、`planned_count`、`applied_count`、`noop_count`、`blocked_count`、`failed_count` 和 `samples`；`samples` 最多 20 项。每个 sample 必须是无嵌套的七字段对象：`kind`、`symbol`、`series_or_contract`、`frequency`、`start`、`end`、`reason_code`，不得有其他字段。前四项精确组成 DatasetKey：`kind` 只允许 `continuous|contract`（最多 10 个 ASCII 字符），`symbol` 匹配 `[A-Z0-9_]{1,16}`，`series_or_contract` 匹配 `[A-Z0-9_]{1,32}`，`frequency` 只允许 `1m|5m|15m|30m|60m|1d|1w`（最多 3 个 ASCII 字符）。`start` 与 `end` 均为以 `Z` 结尾的 ISO-8601 UTC timestamp（最多 27 个字符），且 `start <= end`；sample `reason_code` 与顶层 reason code 使用同一枚举。`reason_code` 只允许 `CANDIDATE_TARGET_NOT_EMPTY`、`CANDIDATE_METADATA_MISSING`、`CANDIDATE_IDENTITY_MISMATCH`、`CANDIDATE_THROUGH_REGRESSION`、`CANDIDATE_SESSION_FACT_MISSING`、`CANDIDATE_UNSUPPORTED_OPERATION` 或 `CANDIDATE_PRECONDITION_FAILED`。任何其他字段、嵌套对象/数组、provider 原始 payload、凭据、路径、SQL、异常文本/堆栈或任意 value payload 均不允许输出。

替代方案是用 root 路径猜测 Candidate、允许 reset/resume 自动纠错、或把周线回退到日线聚合。这些选择会掩盖身份和历史事实漂移，或者改变 direct-weekly 合同，故拒绝。

## Risks / Trade-offs

- [单月重写在超大 1m 月份有额外 IO] → 以自然月限制重写范围，DuckDB/PyArrow 只读所需列；个人工作站优先一致性。
- [文件 replace 与 Catalog transaction 无法形成跨系统 ACID] → reader 只信 Catalog+Manifest；发布使用同目录 temp、checksum、可恢复交换顺序和失败注入测试，最后有效分区不被半成品覆盖。
- [V1 不覆盖 2023 前历史] → floor 版本化且可后续下调；现有 Canonical 不重做，按品种补更早窗口。
- [不可逆 drop 会让旧页面/脚本立即失败] → 同一代码变更先扫描并删除所有 active callers，在隔离 migration 与 API/Web tests 后才进入生产 Gate B。
- [RQData 修订会改变已关闭月份] → routine update 不改 closed month；审计发现后生成 exact repair plan，由显式 repair 替换受影响月。
- [69 品种 Candidate 时间长且可能部分失败] → 先 JM，再六交易所 canary，再 69；固定 through、按品种隔离、结构错误全局中止；候选根和隔离 Catalog 不影响当前生产读取。

## Migration Plan

1. 创建并严格验证本 change；完整吸收旧 M3 后把旧 change 作为 superseded history 归档，不同步其未完成 specs。
2. 以 fixture、临时 canonical root 和隔离 PostgreSQL TDD 实现 domain、ORM/migration、三个深模块、CLI/API/Web；不访问真实 RQData 或生产资源。
3. 删除 active legacy callers 与最终不再需要的兼容代码；运行 backend、migration、frontend、CLI 与旧语言扫描。
4. 实现 Recent Trusted Window policy 与 RQData-only Candidate composition；本地全验证后停止。
5. 先完成 C2.5 repository-only Candidate target 前置：single metadata 的 immutable identity（Catalog/Session/root/universe/floor/source policy/code SHA）与 monotonic `recorded_through`、fresh/extend 校验、无 reset/resume、direct-weekly request mapping、历史 session facts 与 exact sample tuple/timestamp/reason-code schema 的有界诊断；仅运行本地验证后停止。
6. Gate A1：JM，`2023-01-01 → fixed T`，Candidate only。Gate A2：每实际交易所 deterministic canary。Gate A3：active 69 Candidate。Gate A4：audit finding_count=0、DataGap=0、same-T update NOOP。各真实 RQData/Candidate 写入分别需要新的单次意图。
7. Gate B 前输出生产表、候选根、正式根和服务范围。收到另一份单次意图后才能在短维护窗口执行不可逆 migration、Catalog 写入与 root 原子切换。
8. Gate C 只读/NOOP 验收要求 DataGap=0、floor 之后全部预期七周期可读、主力跨换月/周线正确、相同 fixed through 为零目标零写入零远程；scheduler/live/notification/order 仍关闭。
9. Gate C 通过后删除 migration-only legacy adapter，评估/收口 `data bootstrap`，完成最终验证并 archive 本 change。main/release/Runtime 不在本 change 授权内。

按用户决策，不为生产旧表 drop 设计应用级 rollback。Gate A 在隔离候选根失败时丢弃候选即可；Gate B 失败必须保持 API 停止并报告实际状态，不以兼容表或旧 selector 静默回退。
