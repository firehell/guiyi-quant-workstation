# 归一量化项目事实源

更新时间：2026-08-08

## 定位与边界

归一量化是本地运行、单用户的国内期货量化研究工作站。长期闭环是可信行情、
指标/策略候选、历史研究、观察与提醒、人工判断、复盘、统计与 OOS/Walk-forward/Shadow。

项目不做自动交易、实盘下单、SaaS、多用户、高频/Tick 平台或 AI 自动晋升策略。
当前没有 backtest 子系统、Signal/Review/Strategy 应用面或盘中 Live 路径。

## Current surface

- Market Web。
- `/api/v1/market/*` 与 `/api/runtime/*`。
- `guiyi data update/bootstrap/repair/audit` 与 `guiyi runtime status`。
- `packages/quant-core` 中的 vn.py-compatible 指标/策略研究代码。

## Active 数据目标

```text
RQData
-> temporary staging
-> normalization + six hard validations
-> Canonical Parquet direct and derived monthly partitions
-> PostgreSQL minimal Catalog / MainContractMap / ContractSpec
-> MarketDataService
-> Market Web / Indicator / future research
```

- RQData 是唯一外部事实源。
- Canonical Parquet 是唯一 active 历史 Bar 存储；PostgreSQL 不保存 K 线。
- active universe 唯一入口为 `data/universe/active_products.txt`，精确 69 品种。
- 七周期固定为 `1m/5m/15m/30m/60m/1d/1w`。
- 物理 Dataset 只有 continuous 和 contract；actual-dominant 依据 rank1 map 在查询时拼接。
- 所有消费者共用 MarketDataService，不得 glob、自选 active 文件、自判主力或跨频回退。
- DataGap、映射缺失和物理完整性异常都 fail-closed。
- historical canonical 与 live observation 分离。

详细合同见 `docs/DATA_CENTER.md`，分层边界见 `docs/ARCHITECTURE.md`，执行顺序见
`docs/tasks/GY-DATA-CORE-V2.md`。

## 工程与外部操作

普通仓库开发可在 `develop` 直接实现、测试、commit 和 push。任何真实 RQData 调用、
正式 Canonical 写入/切换、生产数据库 mutation、Runtime/live、真实通知、release/tag 或主要服务启停，
均需在执行前获得范围明确的一次性意图。dry-run 不授权真实 mutation。

任何结论只证明其精确验证范围；不由代码、测试、数据存在、release 或 smoke 推导盈利、
长期稳定、交易或 Runtime Ready。

## 文档职责

| 文件 | 职责 |
|---|---|
| `AGENTS.md` | 唯一开发执行规则 |
| `STATUS.md` | 当前阶段与未完成 Gate |
| `PROJECT_SOURCE.md` | 长期产品与系统边界 |
| `DECISIONS.md` | 当前有效长期决策 |
| `docs/ARCHITECTURE.md` | 项目分层和组件边界 |
| `docs/DATA_CENTER.md` | Canonical 数据合同 |
| `docs/tasks/GY-DATA-CORE-V2.md` | active 数据收口业务合同 |
| `TESTING.md` | 当前可执行验证入口 |
