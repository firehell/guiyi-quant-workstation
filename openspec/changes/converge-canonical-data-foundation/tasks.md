## 1. OpenSpec 收口

- [x] 1.1 严格验证 proposal、四个 capability specs、design 与 tasks，确认无改变实现方向的 Open Questions
- [x] 1.2 将 `m3-v2-production-correctness` 标记为 superseded history 并以 `--skip-specs` 归档，不修改其未完成任务状态

## 2. 领域合同与数据库 schema

- [x] 2.1 先写失败测试，再实现四字段 DatasetKey、物理 DatasetKind、Frequency 与 Canonical 路径规范化
- [x] 2.2 先写失败测试，再实现 SeriesQuery 三模式校验、TargetWindow、CanonicalBar、Manifest 与结构化 action result
- [x] 2.3 先写失败测试，再将 MarketDataset/MarketPartition/DataGap/MainContractMap ORM 收敛到当前事实唯一键与月分区约束
- [x] 2.4 先写失败测试，再实现每日 ContractSpec ORM 和 metadata upsert repository
- [x] 2.5 编写不可逆 Alembic migration：重塑 Catalog/Map/Specs 并 drop 明确列出的旧数据表
- [x] 2.6 在空数据库与 `20260808_0035` 隔离升级测试中验证新 head，确认 ORM metadata 不重建退出表

## 3. Canonical 月分区与质量内核

- [x] 3.1 先写失败测试，再实现 ProviderBarBatch 到最小 CanonicalBar 的统一 Decimal/UTC 标准化
- [x] 3.2 先写失败测试，再实现 schema、单调唯一、OHLCV、session/frequency、coverage 五类逻辑校验
- [x] 3.3 先写失败测试，再实现月分区 Parquet/Manifest checksum、row count 和同目录原子发布一致性校验
- [x] 3.4 先写失败注入测试，再保证发布失败保留最后有效分区且不会留下可读半成品
- [x] 3.5 先写失败测试，再实现只从 Canonical 1m + 实际 session 生成 5m/15m/30m/60m 及其 source/session digest

## 4. MetadataSynchronizer 与 HistoricalDataManager

- [x] 4.1 先写失败测试，再实现固定 RQData MetadataSynchronizer 对 active universe/contracts/calendar/session/rank1 map/daily specs 的幂等同步边界
- [x] 4.2 先写失败测试，再实现 desired coverage planner：product start、since 下界、fixed through、历史洞和月窗口
- [x] 4.3 先写失败测试，再实现 MainContractMap rank1 连续片段到真实 contract 七周期目标，禁止扩展完整上市生命周期
- [x] 4.4 先写失败测试，再实现 update 的 metadata-first、Direct→Derived→strict verify、单品种隔离与结构失败中止
- [x] 4.5 先写失败测试，再实现 fixed-through 二次 update 的零目标、零写入、零 provider NOOP
- [x] 4.6 先写失败测试，再实现 exact repair plan 校验、受影响月替换和复验后 DataGap 删除
- [x] 4.7 先写失败测试，再实现只读 active-69 audit 与 finding/exit-code 语义
- [x] 4.8 先写失败测试，再实现 migration-only legacy 白名单 bootstrap 与精确 RQData 重下计划（实现保留但 freeze：不再作为新 Gate A 数据源；Gate C 后删除）

## 5. MarketDataService 与公开合同

- [x] 5.1 先写失败测试，再实现 Catalog/Manifest/checksum/row-count 驱动的 continuous 和 contract 同频月分区查询
- [x] 5.2 先写失败测试，再实现 actual_dominant rank1 真实合约拼接、缺映射/缺 Dataset/Gap fail-closed
- [x] 5.3 先写失败测试，再实现完整 ISO 周水位和周最后交易日 rank1 owner，覆盖周中换月与假期缩短周
- [x] 5.4 先写失败测试，再实现 request identity、coverage、partition digests、resolved segments 与 main-map digest 响应
- [x] 5.5 先写失败测试，再将 Market API schema/route 和指标消费者切到唯一 MarketDataService 且删除旧字段

## 6. CLI、Web 与 active legacy 清理

- [x] 6.1 先写失败测试，再将 `guiyi data` 收敛为 update/bootstrap/repair/audit 四命令及默认 dry-run/错误退出码
- [x] 6.2 删除公开 download/aggregate/sync/verify、legacy data_core cli service、task07/migration/preflight/shadow/apply-gate/receipt 入口
- [x] 6.3 删除 IngestRecorder/generic structured ingestors、ActiveDataset、legacy CanonicalBarLoader 和无 active caller 的相关脚本测试
- [x] 6.4 删除 backend/frontend 的 profile、data_role、file/binding/quality/access-mode/strict-ready/legacy-lineage 字段、类型和 evidence 展示
- [x] 6.5 更新 Market Web 只使用新 series query，并通过 unit/type/build 与浏览器 Market 页 smoke
- [x] 6.6 扫描 active 代码、前端和当前文档中的旧数据语言引用为零（Alembic history、归档 OpenSpec 和 Git history 除外）

## 7. 本地候选验证与文档

- [x] 7.1 运行领域、Canonical、HistoricalDataManager、MarketDataService、CLI/API 定向测试和数据核心完整 pytest
- [x] 7.2 运行 ruff、类型检查、Alembic 隔离迁移测试、前端 unit/type/build 与 CLI dry-run smoke
- [x] 7.3 更新 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md`、`docs/tasks/GY-DATA-CORE-V2.md`、`TESTING.md` 和 `STATUS.md`，只记录实际完成事实与外部 Gate
- [x] 7.4 生成 Gate A 前的纯本地 exact-scope dry-run 能力并验证不构造 RQData client、不写生产 DB/正式 Canonical

## 8. Recent Trusted Window、受控外部 Gates 与最终收口

- [x] 8.1 Recent Trusted Window policy：新增 `data/universe/active_history_floor.txt`（`2023-01-01`），将 `product_start`/`effective_start` 收口为 `max(product_window_start, floor)`，并收口 Metadata Bars/Map/Spec 与 Calendar 最小前置窗；提供 RQData-only Candidate composition（`legacy=None`）；冻结 legacy Gate A 路径；完成本地全验证
- [x] 8.2 C2.5 repository-only Candidate target 前置：实现并定向测试 single Candidate metadata：immutable identity（隔离 Catalog/Session、Canonical root、universe digest、floor、`RQData-only/legacy=None` source policy、code SHA）与唯一 mutable `recorded_through`；fresh 检查和仅允许 identity 相同、`requested_through >= recorded_through` 的 extend 单调更新；不暴露 reset/resume/清空/自动恢复操作；`1w` direct 请求映射为 provider weekly；持久化并校验 historical Calendar/Session facts；诊断严格限于字段白名单、20 个 sample 上限、无嵌套的四字段 DatasetKey + UTC start/end + 枚举 reason-code schema、标识符字符串上限及禁止 path/SQL/raw exception/value payload。不得调用真实 RQData/DB/Canonical。
- [ ] 8.3 Gate A1：取得 JM、`floor→fixed T`、Candidate DB/Root 的单次执行意图后，用 RQData-only `update` 构建并验收 JM Candidate（七周期、map/spec、DataGap=0、换月/周线、same-T NOOP）
- [ ] 8.4 Gate A2：在同一 Candidate 上对六个实际交易所各选一品种做 canary，并通过 same-T NOOP
- [ ] 8.5 Gate A3/A4：取得 active-69、`floor→fixed T`、Candidate-only 的单次执行意图后完成 69 构建、`audit finding_count=0`、DataGap=0 与 same-T update NOOP（Gate A PASS）
- [ ] 8.6 Gate B：取得生产表、候选根、正式根和服务范围的另一单次执行意图后完成 `0035→0036`、Catalog promotion 与短维护窗口原子切根
- [ ] 8.7 Gate C：生产只读验收 DataGap=0、floor 后全部预期七周期、map/spec 完整、主力跨换月/周线、Market/MDS 可读、相同 fixed through NOOP，且 scheduler/live/notification/order 保持关闭
- [ ] 8.8 Gate C 通过后删除 migration-only legacy adapter/测试与 legacy candidate composition，评估并收口 `data bootstrap`，运行最终完整验证
- [ ] 8.9 archive `converge-canonical-data-foundation`；更新 `STATUS.md` 为 Data Foundation Frozen；不合并 main、不创建 release/tag、不切换 Runtime
- [x] 8.10 按 develop 日常流程提交并推送普通仓库变更（历史完成项；后续 C2 实现另提交）
