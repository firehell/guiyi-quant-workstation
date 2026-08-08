# 当前状态

更新时间：2026-08-08

本文件是项目当前状态仪表盘；历史过程由 Git、任务合同与既有证据追溯。历史协作材料不构成当前授权（见 `AGENTS.md` / `DECISIONS.md`）。

## 当前开发模型

普通仓库工作直接在 `develop` 编辑并按影响范围本地验证；本地必要检查是完成声明依据。协作门禁与可选工具边界见 `AGENTS.md` / `DECISIONS.md`。当前 Personal Development Mode 迁移只修改仓库文件，不代表重新执行任何 release/tag、生产 DB/正式数据写入、Runtime/live 切换、真实通知、GitHub rules 修改或订单操作。

真实外部操作只接受一次新的、范围明确的用户执行意图，并只用于紧随其后的一次匹配尝试。历史审批材料、dry-run 和先前会话不能复用为执行权限；数据质量、安全、默认关闭与无订单边界始终优先。

## 当前执行线

21 品种退役已完成生产执行：活动品种池为 69，目标品种的 8,625 个文件
（1,466,729,156 bytes）和 1,141,643 条 PostgreSQL 记录已删除，复验残留文件/记录均为 0。
保留品种已完成 443 个 RQData 直供目标与 608 个 Canonical 聚合目标刷新；
生产 Runtime 现为 `develop` 工作树本地部署（不再经 GuiyiRuntime detached）；
api/web 由 launchd 指向 `/Volumes/扩展盘/guiyi-quant-workstation`；`com.guiyi.quant-worker-signals` 保持 bootout。
已配置 `GUIYI_CANONICAL_DATA_ROOT` 指向正式 Canonical 根，Market bars 只读恢复；
行情页已去掉「浏览 / 严格研究」切换。通知、live 及退役 HTDY label 保持关闭，自动交易仍不在项目范围。
前序 `v0.1` / `94f70c72…` 仍为 release 锚点。2026-08-08 已按用户意图执行生产 Alembic `20260805_0033 → 20260808_0034`（退役面表 drop）；未执行 RQData/Canonical 写入。

Task 07 Stage A/B 的最新仓库证据记录 release/main/tag 已收口；历史退役窗口曾回读
`20260803_0032`，当前生产 head 为 `20260808_0034`。

Task 07 Stage C 已收窄为“JM 目标 Canonical 验收与精确缺口计划”。历史 candidate 基于 `develop@364753e72458641e226280e326841919539c1354`，仅从 `config/data_core_v2_targets.yaml`、Catalog 和 MainContractMap 生成 JM 显式目标，再通过既有 Canonical reader 和 `MarketDataService` 只读验收。该 commit 与既有协作记录是历史定位信息，不是继续开发的前置授权。

仓库当前已移除旧 Web/backend backtest 子系统与 S6-08/S6-09/S6-10 控制面：不再提供
`/api/backtests/**`、`/ws/backtests/**`、`/backtest`、`/backtest/batch`、`/settings`、
`guiyi-backtests` worker/queue、`guiyi runtime plan` 或 runtime health scheduler component。

Web 观察面已精简为 **Market 工作台 only**（`/` → `/market`；69 品种历史行情 + EMA10/21/60、火天大有、MACD）。
今日工作台、信号监控、策略中心、复盘中心、数据中心、运行状态等 Web 入口已去掉；
对应 Signal/Review/Strategy/Dashboard/Watchlist/futures_research HTTP、服务、ORM、RQ worker、
语义合同与 strategy_knowledge/specs 已从仓库删除；生产相关表已由 `20260808_0034` drop。
**保留**：`/api/v1/market` Canonical 历史读（含兼容 `/api/symbols`）、`/api/runtime`、
CLI `guiyi data *` / `guiyi runtime status`、Canonical data、`packages/quant-core`。
`/api/v1/data` data_center HTTP、Profile/Binding 选择器与旧 after-market archive 生产路径
已从仓库卸除；候选 Alembic `20260808_0035` 可 drop
`data_profiles` / `profile_active_bindings` / `after_market_scheduler_checkpoints`
（**未**授权生产 upgrade）。日常历史更新入口为 `guiyi data update`。
盘中 Live / Task 06 应用路径与生产表均已退役；盘中能力待后续新实现重建。
tracked legacy evidence 以及主工程被 Git 忽略的
`/Volumes/扩展盘/guiyi-quant-workstation/backtests/`（87 个文件，约 50 MB）已精确清理。
此处不代表 release、Runtime promotion、生产 DB/正式数据删除、launchd/Redis/其他 host 清理
或服务停止已经发生。

### 2026-08-08 退役面清理与生产表 Drop

- 删除 Signal/Review/Strategy/Dashboard/Watchlist/notification 应用代码、ORM、schemas、worker 模板。
- 按 1B 删除 `docs/SIGNAL_EVENTS.md`、`docs/strategy_knowledge/`、`docs/strategy_specs/` 与相关 skills。
- 新增不可逆 Alembic `20260808_0034`；生产一次 upgrade：drop Live/Task06 + Signal/Review/Watchlist 共 18 表及 `reject_signal_decision_update`；复验 residual=0；Catalog 表保留。
- backtest 表此前已由 `0033` drop；仓库残留引用已清理。

### 2026-08-08 文档卫生与 Market 双源修复

- Canonical / deep docs 已收口为 Market-only current surface；旧 Signal 合同已删（Git history）。
- 一次性 `data/reports/**`、会话产物、已完成 OpenSpec/Kiro Spec、STRATEGY/GOLDEN/OFFLINE/RISK 验收文档已删或归档；引用改指 Git history。
- `dominants` coverage / `quote_ready` 改为 Catalog `actual_dominant` 口径，与 `/bars/canonical` 对齐；前端提示过期 MainContractMap 与 DataGap reason 标签。
- **未**执行 RQData / 正式 Canonical / 生产 DB 写入。若列表仍显示过期主力（如 JM2509）或 Chart DataGap，需另给 MainContractMap/Canonical 更新的精确范围执行意图。
- 本地 api/web 部署改为直接使用 `develop` 工作树（`/Volumes/扩展盘/guiyi-quant-workstation`），**不再**经 GuiyiRuntime detached checkout；signal worker 保持 bootout。

唯一目标范围为：

- `continuous / JM.MAIN`；
- `actual_dominant / MainContractMap rank=1 volume_open_interest`；
- `1m/5m/15m/30m/60m/1d/1w`；
- 窗口起点 `2013-03-22`，终点为当前完整 MainContractMap 的最后交易日。

每个目标只能得到 `KEEP_CANONICAL`、`REDOWNLOAD_DIRECT`、`REBUILD_AGGREGATE` 或 `REGISTER_DATA_GAP`。全部有效时固定返回：

```text
Stage_C=NO_DATA_WRITE_REQUIRED
writes_authorized=false
repair_count=0
production_writes=false
```

旧的 49,885 资产、30,536 repair actions、24,178 RQData requests 和 2,186 batches 只是 superseded historical evidence。它们不再是 active Stage C 输入，对应的 CLI packet/plan/preflight/apply/verify 路由已从 active parser 移除并 fail-closed。

## 任务状态

| 任务 | 状态 | 说明 |
|---|---|---|
| GY-DATA-CORE-V2 Task 00～03 | completed on develop | 完成事实可由历史证据追溯；不是后续授权 |
| GY-DATA-CORE-V2 Task 04 | completed on develop | Canonical 自身质量准入、统一读取与普通消费者回归；legacy Shadow 不是准入条件 |
| GY-DATA-CORE-V2 Task 05 | completed on develop | trusted consumers 与 fail-closed derived/reference inventory；不含真实删除 |
| GY-DATA-CORE-V2 Task 06 | retired + tables dropped | 应用路径已移除；生产表由 `20260808_0034` drop；residual=0 |
| GY-DATA-CORE-V2 Task 07 Stage C | implementation candidate | 按当前代码运行本地定向与领域验证；生产只读验收未执行 |
| GY-DATA-CORE-V2 Task 08 | pending | Stage D Runtime promotion 的独立业务任务；任何真实切换需新的精确范围执行意图 |
| GY-DATA-PRODUCT-RETIREMENT-21 | completed / released | 21 品种全链路删除、69 品种七周期刷新、Runtime 发布与残留验证完成 |
| 旧派生数据清理 | optional / separate | 不阻塞 Task 07；仓库内删除与生产/正式数据删除必须分别分类 |
| scripts-cli-consolidation | implementation on develop | 统一 `guiyi data update/download/aggregate/sync/audit/verify`；旧 `data live` 与 `guiyi-data` 已移除；正式数据/RQData/Runtime 未执行；本地定向测试待 Mac Mini 验证 |
| M1 historical update | implementation on develop | `data update` 默认 dry-run；apply 采用惰性组合、Calendar/Session/MainContractMap 后重规划、Direct→Aggregate→严格窗口校验。未执行真实 RQData、DB、Canonical 或 Runtime 操作。 |
| M2 retained-universe audit | implementation on develop | `data audit --scope m2 --universe active` 固定审计 69 个保留品种的 seven-frequency Catalog/Gap/Manifest/Parquet、lineage、rank=1 mapping 与确定性 `MarketDataService` probes；生产只读验收尚未执行。 |
| Backtest/S6 repository retirement | implementation on develop | 旧 API/Web/worker/queue/CLI、S6-08/09/10 control plane、tracked legacy evidence 与精确 ignored `backtests/` host output 已退出；完整 backend/frontend 验证与 launchd/Redis/Runtime/生产数据等其余外部清理由后续任务负责 |
| poll Live K 线栈退役 | completed on develop + prod drop | 应用代码已删；生产 Live 表由 `20260808_0034` drop |
| slim-web-to-market | completed on develop + prod drop | Web 仅 Market；应用面与 DB 表已删；保留 market/data/runtime API+CLI 与 quant-core |
| retired-surface-drop-0034 | completed / production applied | `20260805_0033→20260808_0034`；18 表 + trigger drop；Catalog 保留 |
| docs-hygiene + dominants Catalog | implementation on develop | Market-only 文档收口；删 reports/会话产物；dominants coverage 对齐 Catalog；未做正式补数 |
| data-foundation-v2-closure | implementation on develop | 单一 V2 语言：卸 data_center HTTP/Profile/Binding/legacy verify/after-market archive；update Direct/Derived 分算 + consistency 只读；候选 Alembic `0035`；**未**执行生产 upgrade / RQData / Canonical / 旧根删除 |

## 未完成事项与执行边界

| 项 | 状态 | 说明 |
|---|---|---|
| HTDY XMA 语义 | blocked | 保持 `HTDY_FORMULA_OR_XMA_SEMANTICS_UNRESOLVED`，不重开公式审计 |
| Audit V2 residual triage | pending | 解释 calendar/session/physical/quality residual 后再决定实现范围 |
| 全历史 residual triage | pending | 不得将消费者验收扩写为所有历史资产 residual 为零 |
| Task 07 Stage C | implementation candidate | 历史协作修正记录仅作事实保留；当前完成依据是适用的本地验证 |
| Task 07 production read-only acceptance | pending | 重新回读 PostgreSQL `20260803_0032` 并验收 JM 目标 Canonical；本次未执行 |
| Task 06 live/EOD contract | retired | 应用代码已移除；历史合同事实保留在 Git / Alembic |
| Task 06 production migration | historical | `0028 -> 0031` 曾通过；不授权 Runtime enable，也不表示 observation 路径仍存在 |
| 21 品种行情与 legacy 工件删除 | passed | 生产 DB/三个数据 root 残留为 0；仓库内 1,035 个专属历史 manifest 已删除，混合审计报告不作整文件删除 |
| release / main / tag | released | `main@94f70c72` annotated tag `v0.1` 已推送 origin；前序 Runtime tag `runtime-20260805-b81a9d99` 仍为历史锚点 |
| Task 08 Runtime promotion | pending / default off | 代码 Runtime 已切到 `develop@1c810a9a` 观察面；live/通知/JM Runtime 业务验收仍关闭，需新的精确 scope 意图 |
| JM Runtime 验收 | pending redesign | 保留单日自然运行、恢复和零非法写入等业务验证；协作材料不是授权条件（见 `AGENTS.md`） |
| 长稳 / 通知 / 交易就绪 | not ready | 本次不启用 live、不发送通知；自动订单始终不在项目范围内 |
| 真实公网安全 smoke | pending | TLS、Basic Auth、端口不可达与 FRP/Nginx 重启恢复 |
| V1 最终验收 | pending | 依据业务验证和实际观察结果；每个真实外部动作分别要求精确 scope 的一次性意图 |

## 必要事实锚点

| 事实 | 当前证据值 | 边界 |
|---|---|---|
| PostgreSQL revision | `20260808_0034` | 2026-08-08 退役面 drop 后 head；先前为 `20260805_0033` / `20260803_0032` |
| 生产 Runtime checkout | `develop` 工作树（非 GuiyiRuntime） | launchd api/web 指向本仓；live/通知关闭；signal worker bootout |
| 21 品种退役 receipt | packet `fee133a5…`; residual DB/files `0/0` | 删除已提交，rollback tag 只回退代码，数据恢复需从 RQData 重建 |
| Canonical closeout snapshot | 85 datasets / 85 partitions / 0 gaps / 255 files / staging 0 | Task 04 历史只读证据；Stage C 将重新验收明确目标 |
| MainContractMap closeout snapshot | 3245/3245 resolved trading days；0 missing；0 ambiguous | Task 04 历史只读证据；不代替 Stage C 重验 |
| legacy compatibility | PR #90～#94 与历史 evidence 保留 | 不再扩展，也不作为 Task 07 准入或执行授权 |
| 旧 backtest/S6 控制面 | retired from repository | 历史事实仅由 Git 追溯，不保留 compatibility 或恢复入口 |
| Signal/Review/Live 表 | dropped on production | `20260808_0034`；information_schema residual=0；trigger/function 不存在 |

## 不可宣称

- 不可将代码、本地测试、CI 或只读计划写成生产修复、迁移或真实执行完成。
- 不可将 Task 07 完成条件绑定到 Profile/Binding retirement、Runtime legacy reference=0、旧派生数据删除、legacy 文件总数或协作审批材料。
- 不可将 Stage C 扩写为 Runtime、scheduler/live、长稳、通知或交易就绪。
- 不可修改或重解释旧 evidence 中已经发生的事实，也不可把旧审批材料用作当前授权。
- 不可宣称所有历史资产 residual 为零，也不可把历史 backtest 或单次 smoke 写成策略盈利、实盘或自动交易准入。
- 不可从 release/tag 意图推导 Runtime/live/通知权限，也不可从任何意图推导订单权限。

相关定义见 `docs/ARCHITECTURE.md`、`docs/DATA_CENTER.md` 与 `docs/INDICATOR_KERNEL.md`。
