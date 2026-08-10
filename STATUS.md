# 当前状态

更新时间：2026-08-10

## 结论

Market Runtime V1 已按本地工作站的明确请求启用，持续运行范围严格固定为 operational
`j/jm/ap/ag` 4/4；API、Web 与 RQData Live 由 launchd 加载，盘后任务保持空闲并等待每天 17:00。
Runtime detached checkout 当前为 `8708c934`（包含盘后修复祖先 `44ca152e`），`auto_order=false`
与无订单边界不变。

2026-08-10 首次受控盘后重跑在 20:01～21:02 完成两次尝试并安全失败，没有第三次重试。原始
RQData readiness MultiIndex 解析缺陷已修复；继续诊断确认阻塞来自当天 metadata 仅写单日 Calendar，
而周频完整性门禁要求覆盖到 ISO 周日。修复后的当天同步只扩展 Calendar 到本周周日，Session 与
rank-1 MainContractMap 仍只写当天。用户随后给出新的单次执行意图，21:28～21:33 的第二次受控重跑
使用 Runtime `44ca152e` 在首次尝试成功，`last_successful_trading_day=2026-08-10`、`last_failure=null`。
J/JM/AP/AG 的 continuous 1m Canonical 边缘均前进到 `2026-08-10T07:00:00Z`，四品种写后 audit
均为 passed/0 findings，Runtime API、Web、Redis、RQ、Live 与 after_market 健康均为 ok。本轮代码
验证为后端与工程测试 2626 passed / 20 skipped、定向 Runtime/Data Foundation 257 passed、Ruff 通过。

Data Foundation 已完成 **DFD-01～DFD-06**，并已进入 **DFD-07**：生产 PostgreSQL 已从
`20260808_0035` 升级至最终不可逆 `20260808_0036`，盘点范围内的旧正式数据已删除。固定
`T0=2026-08-07` 的 J/JM 重建均已完整闭环：J 已发布 686 个正式月分区（continuous 308、真实合约
378），JM 已发布 678 个正式月分区（continuous 308、真实合约 370）；两品种的 `update` dry-run
均为 NOOP、audit 均通过，Catalog 与物理 Parquet 已完成只读验收。JM 的
`MarketDataService` continuous / contract / actual_dominant 有界读回亦已通过。此前周线与 Derived
开放月 Session 上界缺陷已修复；JM 补齐两个周线 Direct 与四个 Derived 分区的受控执行成功完成
（2 次 provider 请求、6 个分区发布）。`ap` 写入前其余 58 个 active 品种尚无正式 Canonical 分区，且
历史 Session facts 未完整；随后 CZCE `ap` 在精确单次执行意图下完整闭环，发布 685 个正式月分区
（continuous 308、真实合约 377）。`ap` 的 fixed-T0 dry-run 为 NOOP、audit 通过，且
`MarketDataService` 已对七周期的 continuous / contract / actual_dominant 完成只读回检。随后 SHFE
`ag` 在精确单次执行意图下完成 metadata 同步和 Canonical 重建，发布 748 个正式月分区
（continuous 308、真实合约 440）；写后 audit 通过、fixed-T0 dry-run 为 NOOP，Catalog 与物理
Parquet 均可读。AG 的分钟与 Derived `actual_dominant` 曾在首根夜盘 bar 前一微秒的合法查询边界把
前一自然日错当映射日；仓库内修复后，早期、最近与跨换月的七周期 continuous / contract /
actual_dominant 共 21 组同窗口读回全部通过。随后 INE `ec` 在精确单次执行意图下完成 metadata
同步和 Canonical 重建，发布 613 个正式月分区（continuous 259、真实合约 354）；写后 audit 通过、
fixed-T0 dry-run 为 NOOP，且早期、最近与跨换月的七周期 continuous / contract / actual_dominant
共 21 组同窗口读回全部通过。生产正式分区现为 3,410 个，数据资产与完整闭环验收均为 5/60，剩余
55 个 active 品种待重建。随后 GFEX `lc` 在精确单次执行意图下完成 metadata 同步和 Canonical
重建，发布 602 个正式月分区（continuous 266、真实合约 336）；写后 audit 通过、fixed-T0 dry-run
为 NOOP，且早期、最近与跨换月的七周期 continuous / contract / actual_dominant 共 21 组同窗口读回
全部通过。随后 `pd` 在独立精确单次执行意图下完成 metadata 同步和 Canonical 重建，发布 154 个正式
月分区（continuous 70、真实合约 84）；写后 audit 通过、fixed-T0 dry-run 为 NOOP，且早期、最近与
跨换月的七周期 continuous / contract / actual_dominant 共 21 组同窗口读回全部通过。随后 `pt` 在独立
精确单次执行意图下完成 metadata 同步和 Canonical 重建，发布 154 个正式月分区（continuous 70、真实
合约 84）；写后 audit 通过、fixed-T0 dry-run 为 NOOP，且早期、最近与跨换月的七周期 continuous /
contract / actual_dominant 共 21 组同窗口读回全部通过。随后 `pl` 在独立精确单次执行意图下完成
metadata 同步和 Canonical 重建，发布 233 个正式月分区（continuous 98、真实合约 135）；写后 audit
通过、fixed-T0 dry-run 为 NOOP，且早期、最近与跨换月的七周期 continuous / contract /
actual_dominant 共 21 组同窗口读回全部通过。随后 `bz` 在独立精确单次执行意图下完成 metadata 同步和
Canonical 重建，发布 238 个正式月分区（continuous 98、真实合约 140）；写后 audit 通过、fixed-T0
dry-run 为 NOOP，且早期、最近与跨换月的七周期 continuous / contract / actual_dominant 共 21 组同
窗口读回全部通过。随后 `ps` 在独立精确单次执行意图下完成 metadata 同步和 Canonical 重建，发布 350 个
正式月分区（continuous 147、真实合约 203）；写后 audit 通过、fixed-T0 dry-run 为 NOOP，且早期、
最近与跨换月的七周期 continuous / contract / actual_dominant 共 21 组同窗口读回全部通过。生产正式
分区现为 5,141 个，数据资产与完整闭环验收均为 11/60，剩余 49 个 active 品种待重建。随后 `pr` 在
两次独立精确单次执行意图下完成 metadata 同步、Canonical 重建及中断后补齐，最终发布 442 个正式月
分区（continuous 175、真实合约 267）；写后 audit 通过、fixed-T0 dry-run 为 NOOP，且七周期三模式
共 21 组读回全部通过。随后 `px` 在独立明确单次意图下完成 Canonical 重建，最终形成 576 个正式月
分区（continuous 252、真实合约 324）；写后 audit 为 passed、fixed-T0 dry-run 为 NOOP，且早期、最近与
跨换月的七周期 continuous / contract / actual_dominant 共 21 组读回全部通过。生产正式分区现为
6,159 个，数据资产与完整闭环验收均为 13/60，剩余 47 个 active 品种待重建。60 品种重建及全域
Canonical 验收仍未完成。
`ap` 写入前的全域只读 audit 已增强为逐品种结构化 finding：固定 `T0=2026-08-07` 返回 116 条
finding，即当时 58 个未闭环品种各一条 `MAIN_CONTRACT_MAP_MISSING` 与
`TRADING_SESSION_MISSING`；J/JM 无 finding，且零 provider request。Calendar、分区与物理可读性类别
在该基线尚未形成结论——未闭环品种均在历史 Session 覆盖解析处被隔离，不得将未到达的检查阶段误记为
通过。退役品种含
股指 `ic/if/ih/im`、纸浆 `sp`、玉米淀粉 `cs`、丁二烯橡胶 `br`、20号胶 `nr`、低硫燃料油 `lu`；
生产 Catalog 已对退役名单执行 `retire-products --apply`（详见 `GY-DATA-PRODUCT-RETIREMENT-5`）。

## 已冻结的目标合同

- 物理 `DatasetKey=(kind, symbol, series_or_contract, frequency)`；物理 kind 只有
  `continuous|contract`，`actual_dominant` 只在查询时由 `MainContractMap rank=1` 拼接。
- Direct 周期是 `1m/1d/1w`；Derived 周期是 `5m/15m/30m/60m`，只从同 Dataset 的
  Canonical `1m` 按实际交易 Session 聚合。
- 每 Dataset 每自然月只有一个 `part.parquet`。发布前保留 schema、identity、OHLCV、
  session/frequency、coverage 和物理可读性校验；Catalog coverage、row count 和可读文件共同
  表示可用状态。
- PostgreSQL active 数据模型最终为八表：`exchanges`、`instruments`、`contracts`、
  `trading_calendars`、`trading_sessions`、`main_contract_map`、`market_datasets`、
  `market_partitions`。
- 最终公开 CLI 为 `guiyi data update|refresh|audit|retire-products`。`update` 以数据库和已发布月度
  Parquet 自然续传；`refresh` 按指定品种和日期范围强制重建相交月份；`audit` 只读；
  `retire-products` 清退已退役品种 Catalog/Canonical（默认 dry-run）。

## 当前实现差异

DFD-02 已删除退出的维护面、legacy importer、旧 CLI 入口及其生成工件。DFD-03 已将
storage、Catalog、ORM 和最终 `20260808_0036` 收口为八表与单月 `part.parquet`，并已在正式 PostgreSQL
完成 migration。DFD-04 已验证三种查询、周线 rank1 owner 和 Derived physical partition 读取，并移除
Market API/Web 的 digest 展示。DFD-05 已实现 `update|refresh|audit`、完整月 refresh、quota partial
自然续传和本地 Derived 优先重建。DFD-06 已运行后端/工程全量、前端 test/build、Ruff、Mypy 和严格
OpenSpec 验证，并将 active Canonical 一致性断言从退出的发布/缺口合同收口为八表、完整性和
原子月分区发布合同。

工程双轨收口（2026-08-09）：旧 `data_core` / `rqdata_ingest` 等空壳与 pycache、退役 worker 启动面、
孤儿 data_profiles / v2_targets、未用 ECharts/DuckDB 依赖已清；Market coverage/dominants 经
`MarketDataService`；ORM 合并为 `models/market_tables.py`；指标权威定为 quant-core Kernel，Web TS
仅为观察镜像。旧 `guiyi_quant/strategies/` vn.py 策略研究包及对应策略测试已退役；HTDY strict 计算源
收口为 `guiyi_quant.indicators.htdy_strict.compute_strict_fields`。事实源仍只认 `STATUS.md`、
`docs/DATA_CENTER.md` 与 `app/market_data/`。

## 外部操作状态

在用户明确的一次性执行意图下，已执行生产 `0035→0036` migration，删除 `data/raw`、
`data/processed`、`data/parquet/canonical` 与 `data/canonical-candidates`，并启动 JM 的真实 RQData
重建。migration 后八张 active 表已验收，旧 Catalog 已清空；JM 先完成 672 个物理月分区，随后在
新的精确单次意图下补齐 `JM2405/1w/2024-04`、`JM2505/1w/2025-04` 与
`JM2609/{5m,15m,30m,60m}/2026-08`。该次执行 `applied=6`、`failed=0`、
`provider_requests=2`；其后 JM fixed-T0 dry-run 为 NOOP、JM audit 通过，678 个 Catalog
分区及对应 Parquet 均可读。随后 J 在精确单次执行意图下完成剩余窗口，最终形成 686 个正式月分区；
fixed-T0 dry-run 为 NOOP、audit 通过，Catalog 与对应 Parquet 均可读。`actual_dominant` 在缺少对应
concrete-contract 分区时仍保持 fail-closed；其余 58 品种的历史 Session facts 与 Canonical 重建仍需
后续受控执行。随后在明确单次意图下，CZCE `ap` 完成从 T0 的 RQData metadata 同步和 Canonical
重建，`ap` 产出 `applied=685`、`failed=0`、`provider_requests=293`；写后 audit 为 passed，fixed-T0
dry-run 为 NOOP，七周期 `MarketDataService` 读回通过。随后 SHFE `ag` 在独立的明确单次意图下完成
metadata 同步与 Canonical 重建，产出 `applied=748`、`failed=0`、`provider_requests=320`；写后 audit
为 passed、fixed-T0 dry-run 为 NOOP，748 个 Catalog 分区及对应 Parquet 均可读。随后修复
`MarketDataService` 对夜盘查询边界的 `trading_day` 解析，并以相同 21 组窗口只读复验通过；该修复
没有调用 RQData 或写入生产 Catalog/Canonical。随后 INE `ec` 在独立的明确单次意图下完成 metadata
同步与 Canonical 重建，产出 `applied=613`、`failed=0`、`provider_requests=261`；写后 audit 为
passed、fixed-T0 dry-run 为 NOOP，613 个 Catalog 分区及对应 Parquet 均可读，且七周期三种查询模式
的早期、最近与跨换月共 21 组读回通过。其余 55 个品种的历史 Session facts 与 Canonical 重建仍需
后续受控执行。随后 GFEX `lc` 在独立的明确单次意图下完成 metadata 同步与 Canonical 重建，产出
`applied=602`、`failed=0`、`provider_requests=258`；写后 audit 为 passed、fixed-T0 dry-run 为
NOOP，602 个 Catalog 分区及对应 Parquet 均可读，且七周期三种查询模式的早期、最近与跨换月共 21 组
读回通过。随后 `pd` 在独立明确单次意图下完成 metadata 同步与 Canonical 重建，产出 `applied=154`、
`failed=0`、`provider_requests=66`；写后 audit 为 passed、fixed-T0 dry-run 为 NOOP，154 个 Catalog
分区及对应 Parquet 均可读，且七周期三种查询模式的早期、最近与跨换月共 21 组读回通过。随后 `pt`
在独立明确单次意图下完成 metadata 同步与 Canonical 重建，产出 `applied=154`、`failed=0`、
`provider_requests=66`；写后 audit 为 passed、fixed-T0 dry-run 为 NOOP，154 个 Catalog 分区及对应
Parquet 均可读，且七周期三种查询模式的早期、最近与跨换月共 21 组读回通过。随后 `pl` 在独立明确
单次意图下完成 metadata 同步与 Canonical 重建，产出 `applied=233`、`failed=0`、
`provider_requests=97`；写后 audit 为 passed、fixed-T0 dry-run 为 NOOP，233 个 Catalog 分区及对应
Parquet 均可读，且七周期三种查询模式的早期、最近与跨换月共 21 组读回通过。随后 `bz` 在独立明确
单次意图下完成 metadata 同步与 Canonical 重建，产出 `applied=238`、`failed=0`、
`provider_requests=102`；写后 audit 为 passed、fixed-T0 dry-run 为 NOOP，238 个 Catalog 分区及对应
Parquet 均可读，且七周期三种查询模式的早期、最近与跨换月共 21 组读回通过。随后 `ps` 在独立明确
单次意图下完成 metadata 同步与 Canonical 重建，产出 `applied=350`、`failed=0`、
`provider_requests=150`；写后 audit 为 passed、fixed-T0 dry-run 为 NOOP，350 个 Catalog 分区及对应
Parquet 均可读，且七周期三种查询模式的早期、最近与跨换月共 21 组读回通过。其余 49 个品种的历史
Session facts 与 Canonical 重建仍需后续受控执行。随后 `pr` 的首次更新进程中断后，经第二次独立明确
单次意图补齐 73 个缺失分区（`provider_requests=29`）；最终 audit 为 passed、fixed-T0 dry-run 为
NOOP，442 个 Catalog 分区及对应 Parquet 均可读，且七周期三种查询模式共 21 组读回通过。随后 `px`
在独立明确单次意图下完成 Canonical 重建，形成 576 个 Catalog 分区（continuous 252、真实合约 324）；
写后 audit 为 passed、fixed-T0 dry-run 为 NOOP，且七周期三种查询模式共 21 组读回通过。其余 47 个
品种的历史 Session facts 与 Canonical 重建仍需后续受控执行。在明确单次
意图下已多次对生产执行 `guiyi data retire-products --apply`，覆盖退役名单
`br/cs/ic/if/ih/im/lu/nr/sp`；Canonical 退役目录均为 0，事后 residual=0，显式退役码返回
`PRODUCT_RETIRED`。未执行服务切换、main/tag/release 或 Runtime promotion。

日调度、live、真实通知和自动订单保持关闭，`auto_order=false`。
