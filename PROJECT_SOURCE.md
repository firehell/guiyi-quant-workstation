# 归一量化项目事实源

更新时间：2026-08-10

## 定位与边界

归一量化是本地运行、单用户的国内期货量化研究工作站。当前只服务可信历史行情、Market Web、
Indicator Kernel 与未来研究；不做自动交易、实盘下单、SaaS、多用户、高频/Tick 平台或 AI 自动
晋升策略。当前没有 backtest 子系统或 Signal/Review/Strategy 应用面。Market Runtime V1 的历史分页、
Redis Live Overlay、盘后更新与 WebSocket 代码已实现；仓库 launchd 模板仍默认关闭，
本地工作站已按明确请求启用严格限定为 `j/jm/ap/ag` 的有界 Runtime。

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
- active universe 唯一入口是 `data/universe/active_products.txt` 的 60 品种；股指
  `ic/if/ih/im`、纸浆 `sp`、玉米淀粉 `cs`、丁二烯橡胶 `br`、20号胶 `nr`、低硫燃料油 `lu`
  已退役，见 `retired_products.txt`。历史下界为
  `active_history_floor=2023-01-01`。
- 七周期固定为 `1m/5m/15m/30m/60m/1d/1w`。`1m/1d/1w` 是 Direct；其余四个周期只从
  Canonical 1m 聚合。
- 物理 Dataset 只有 `continuous` 和 `contract`；`actual_dominant` 在查询时按 rank1
  `MainContractMap` 拼接。
- 每 Dataset 每自然月只保留一个 `part.parquet`。可用性由完整 coverage、row count 和文件可读性
  确定；不维护第二套发布、缺口或 checksum/digest 内容摘要状态。
- 所有消费者共用 `MarketDataService`，不得 glob、自选文件、自判主力或跨频回退。

最终用户接口为 `guiyi data update|refresh|audit|retire-products` 与 `/api/v1/market/*`。Market Runtime
仅限 `operational_products.txt` 的 `j/jm/ap/ag`：Live 只观察当日 rank1 completed 1m，盘后最多在 17:00
和一次一小时后 retry 更新这四个品种；Live 永不提升为 Canonical。DFD-01～DFD-06 的仓库收口已完成；DFD-07 生产 Canonical 闭环仍为 `PARTIAL`，精确进度只以 `STATUS.md` 为准。现有仓库代码中的旧入口不能作为当前合同依据。

## 工程与外部操作

普通仓库开发可以在 `develop` 或任务 worktree 中实现、测试、commit 和 push。真实 RQData、
正式 Canonical 写入/切换、生产数据库 mutation、Runtime/live、真实通知、release/tag 等均需执行前
获得范围明确的一次性意图；dry-run 不授权后续 mutation。Market Runtime V1 例外仅在用户明确请求启用
该本地工作站后生效：该一次启用允许其既定四品种 Live 与盘后有限自动化持续运行，不授权任何其他 DB、
release、通知或订单动作。

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
| `docs/tasks/GY-DATA-CORE-V2.md` | active 数据收口业务合同 |
| `TESTING.md` | 当前可执行验证入口 |
