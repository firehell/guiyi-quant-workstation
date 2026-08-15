# 归一量化项目事实源

更新时间：2026-08-14

## 定位与边界

归一量化是本地运行、单用户的国内期货量化研究工作站。当前只服务可信历史行情、Market Web、
Indicator Kernel 与未来研究；不做自动交易、实盘下单、SaaS、多用户、高频/Tick 平台或 AI 自动
晋升策略，所有研究观察始终保持 `auto_order=false`。当前没有 backtest 子系统或 Signal/Review/Strategy 应用面；Alert 是独立、窄范围的观察通知应用，不恢复这些旧应用面。Market Runtime V1 的历史分页、
Redis Live Overlay、盘后更新与 WebSocket 代码已实现；仓库 launchd 模板仍默认关闭，
本地工作站按明确请求启用由 `operational_products.txt` 定义范围的 Runtime。

## Data Foundation 目标合同

```text
RQData
-> temporary staging
-> normalization + six hard validations
-> monthly Canonical Parquet
-> PostgreSQL eight-table catalog and metadata
-> MarketDataService
-> Market Web / Indicator / future research
```

- RQData 是唯一外部行情事实源；Canonical Parquet 是唯一 active 历史 Bar 存储；PostgreSQL
  不保存 K 线。
- Data Foundation / Market Catalog 始终精确为八表。经明确设计的 Application Domain 可以新增不属于
  Market Catalog 的应用表；Alert V2 仍只使用 `alert_rules` / `alert_events` 两张 Application Domain 表，不属于且不改变八表 Market Catalog。
- active universe 唯一入口是 `data/universe/active_products.txt` 的 60 品种；股指
  `ic/if/ih/im`、纸浆 `sp`、玉米淀粉 `cs`、丁二烯橡胶 `br`、20号胶 `nr`、低硫燃料油 `lu`
  已退役，见 `retired_products.txt`。历史下界为
  `active_history_floor=2023-01-01`。
- 七周期固定为 `1m/5m/15m/30m/60m/1d/1w`。基础 provider 周期是 `1m/1d`；`1w` 只从完整同源
  日线聚合，`5m/15m/30m/60m` 只从 Canonical 1m 聚合。
- 物理 Dataset 只有 `continuous` 和 `contract`；`actual_dominant` 在查询时按 rank1
  `MainContractMap` 拼接。
- 每 Dataset 每自然月只保留一个 `part.parquet`。可用性由完整 coverage、row count 和文件可读性
  确定；不维护第二套发布、缺口或 checksum/digest 内容摘要状态。
- 所有消费者共用 `MarketDataService`，不得 glob、自选文件、自判主力或跨频回退。

### 已冻结的五条架构原则

以下原则是后续功能开发的固定前提，不因新增研究功能而重构或扩展其边界：

1. **Data Foundation Frozen**：不得因新功能修改 `DatasetKey`、八表 Catalog、Canonical 语义或“每
   Dataset 每自然月一个 `part.parquet`”的月分区模型。
2. **唯一 Historical Gateway**：`MarketDataService` 是所有新研究功能读取历史行情的唯一入口；新功能
   不得直接读取 Parquet，也不得复制历史行情 resolver。
3. **Live 永远是 Observation**：Live 只存在于 Redis Overlay；不得写入或提升为 Canonical，也不得作为
   正式历史事实。
4. **读模型优先**：可以由 Canonical 和现有 Catalog 计算得到的市场事实，必须按需计算；不得为其新增
   Catalog 表或长期数据副本。只有经明确业务设计、且不属于 Market Data Foundation 的应用事实才可
   进入独立 Application Domain 表。
5. **模块长期性审查**：每新增一个模块，都必须先回答“个人使用真的需要长期维护这个模块吗？”；答案不
   明确时，不创建该模块。

当前用户接口为 Market Web、`/api/v1/market/*`、`/api/alerts/*`，以及 `guiyi data
update|refresh|audit|after-market`、只读 `guiyi research subing-calibration` 和 `guiyi runtime
status|live|alert|alert-canary`；其中 `alert-canary` 是独立真实通知 Gate，不是普通只读命令。Market
Runtime 的 Live 与盘后更新共用 `operational_products.txt`；当前目标与 active 60 完全一致。Live 只观察
当日 rank1 completed 1m，盘后最多在 18:05 和一次一小时后 retry 更新相同范围，Live 永不提升为
Canonical。DFD-01～DFD-07 和 60 品种 Canonical 闭环已经完成，长期规范位于 `openspec/specs/`；现有旧
入口不能作为当前合同依据。

## Alert V2 应用边界

Alert V2 只保留两条 code-defined Rule：`htdy_original_15m` 复用 `MarketReadService.bars_until()` 的 event-cutoff 窗口与 Python Indicator Kernel；`subing_entry_signal_v1` 只消费现有 current-rank1 segment-local `SubingReadService` 产出的 `resolved_signal`，复用 Factor、accepted Calibration、FormalPolicy 和 same-boundary resolver，不在 Alert 中复制公式、阈值或 5m/15m 优先规则。

SuBing 只在 incoming completed Bar 与 current snapshot 的 `bar_end` 和 `trading_day` 同一时创建 Event，stale 或不可用状态 fail-closed。final Session Bar 只在 Live 共享的有界 arrival grace 内可见；该 phase observation 不建立 `snapshot_at`/cutoff/replay 路径。5m 事件落在同一 15m boundary 时依既有 TradingSession bucket 语义延后，继续由 15m snapshot 唯一决议。HTDY event-cutoff 语义不变。

当前交易日仅由既有 `MarketPhaseResolver` 对 `operational_products.txt` 品种集唯一解析；存在缺失或不一致时 API fail-closed 为 `unavailable`，不用自然日或 Event `bar_end` 猜测。Event 先提交，然后最多尝试一次 WeCom；`notification_attempted_at` 表示 Runtime 已进入该一次发送阶段，不表示 HTTP 已接受或用户已收到。无 replay/backfill/retry/outbox/queue/Signal Center/订单路径。SuBing Rule 的 migration seed Scope 为空集。

Alert 代码与 launchd 模板默认关闭。production migration `20260814_0038`、v1.3 release/tag、Runtime promotion/switch、SuBing Scope write/activation 与真实 WeCom/canary 是互不授权的受控外部操作；代码、测试、测试路由 Scope PUT、mock sender 或 render-only 不证明任何 Gate 已执行。

## 工程与外部操作

普通仓库开发可以在 `develop` 或任务 worktree 中实现、测试、commit 和 push。真实 RQData、
正式 Canonical 写入/切换、生产数据库 mutation、Runtime/live、真实通知、release/tag 等均需执行前
获得范围明确的一次性意图；dry-run 不授权后续 mutation。Market Runtime V1 例外仅在用户明确请求启用
该本地工作站后生效：该一次启用允许 `operational_products.txt` 明确列出的 Live 与盘后有限自动化持续运行，不授权任何其他 DB、
release、通知或订单动作。

Alert Runtime V2 只有在用户对识别出的本地工作站明确执行 promotion，且目标 Scope 已获得精确 Rule + Product 授权后，才获得独立、有界的持续授权：

```text
htdy_original_15m × 该 Rule 显式 scope_products × WeCom
+
subing_entry_signal_v1 × 该 Rule 显式 scope_products × WeCom
```

未来第三条 Rule 不自动继承该授权。V2 migration 保留已明确授权的 HTDY Scope，SuBing 仍必须独立执行精确 Scope activation。该授权不覆盖新增 Rule/渠道、migration、Runtime switch、release、Canonical 写入或订单，也不能从 Market Runtime V1、既有 HTDY Scope 或其他 Gate 推导出 SuBing 授权。

当前本机部署根属于可变运行事实，只由 `STATUS.md` 记录。功能开发期可临时从 `develop` 部署以便快速观察；最终 Runtime 采用绑定精确提交的独立 worktree，验收读回身份、拓扑、健康和范围。已经在同一代码谱系形成且由用户接受的自然时点证据不因部署封装重复采集；开发态部署仍不等于 Ready、release 或 Runtime promotion。

任何结论只证明其精确验证范围；不由代码、测试或数据存在推导盈利、长期稳定、交易或 Runtime Ready。

## 文档职责

| 文件 | 职责 |
|---|---|
| `AGENTS.md` | 唯一开发执行规则 |
| `STATUS.md` | 当前实施状态与未执行外部操作 |
| `PROJECT_SOURCE.md` | 长期产品与系统边界 |
| `DECISIONS.md` | 当前有效长期决策 |
| `docs/ARCHITECTURE.md` | 项目分层和组件边界 |
| `docs/DATA_CENTER.md` | Canonical 数据合同 |
| `openspec/specs/` | 当前数据与查询行为规范 |
| `TESTING.md` | 当前可执行验证入口 |
