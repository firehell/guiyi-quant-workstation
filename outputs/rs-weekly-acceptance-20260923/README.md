# RS 周线三层验收（2026-09-23）

基线：`develop@06aecc5e8b7395948aa48770913614e574a4790f`；固定 `as_of=2026-09-18T07:00:00.000001+00:00`；RS 候选 W1 使用 `weekly-d1-quality-v2`。私有生产 Catalog/Canonical 只读事务，provider 请求和生产写入均为 0。RS2609 四根 W1 的前序 [apply 回读](../rs2609-weekly-missing/apply-readback.json) 为 3 个候选月指针及物理合约回放 33 根正常、18 次中断。

## 三层结果

| 层 | 本次实际检查 | 结果 |
| --- | --- | --- |
| 三策略回放 | 原生 [候选矩阵](readiness.json)，RS W1 趋势、震荡、主升浪的 chart、auxiliary、comparator | 3/3 主策略均 `INTEGRITY_ERROR`，首个阻断 `RS2311/2022-12-09`；不是策略计算通过。RS2609 的 chart/auxiliary 依赖自身为 `DATA_READY`，但更早合约阻断整条实际主力前缀。 |
| ReferenceTrade | 同一原生矩阵的三策略 reference；真实浏览器显式请求主升浪 reference | 3/3 reference 均 `INTEGRITY_ERROR`。浏览器 GET `strategy-detail?...section=reference` 返回 409 `NEWOW_DATA_UNAVAILABLE / DATA_INTEGRITY_INVALID`；无 ReferenceTrade 或收益数值。 |
| Newow 页面 | 同一 exact code 的隔离 8010 只读候选 API、5174 Web、真实 Chromium 首载三策略及主升浪参考区 | 3/3 页面正确展示 `RS2311 · 1w · 2022-12-09` 行情完整性失败，未显示伪造交易或收益；[截图](../../output/playwright/rs-weekly-main-rise-blocked-20260923.png)。这是错误展示通过，不是 READY 页面通过。 |

原生报告 `status=audited`、`complete=true`、`budget_exhausted=false`、`main_ready_count=0`；`complete` 只说明检查覆盖完成。候选浏览器身份横幅为 exact code 与固定截止。最初预览进程误用默认开发 SessionFactory，API 返回 503；绑定同一私有 Catalog 的显式只读 SessionFactory 后重载，三策略 weekly-snapshot 和参考请求均返回真实 409，采用后一次现场结果。

## 阻断归因与范围

[逐合约 MDS 错误](blocked-contracts.json)显示 10 个早期 RS 物理合约的首个阻断都是 `WEEKLY_SOURCE_BAR_CONFLICT`。[逐周数值比较](conflicts.json)证明这十周均含 1–4 根严格无交易 D1，活动 W1 的 OHLC 与当前 `exchange-daily-no-trade-v2` 聚合不同；RS2311 的 2022-12-09 周有 3 根严格无交易 D1、2 根正常成交 D1，旧 W1 的开/低/收为零，而 v2 取正价日。

[只读消费窗口扫描](mismatch-scan.json)在这十个合约内发现 **133 根已存 W1 与当前 v2 不一致，分布于 64 个合约月**；每根差异周均包含严格无交易 D1。该扫描仅说明当前已枚举消费窗口内的差异，不是受控 apply 计划，也未冻结每月 D1/W1 前像或验证重建后是否还有其他产品阻断。当前 canonical 要求旧分区经受控重建取得新 URI/revision，不允许 reader 临时改写周价。

## 产品 Gate

**阻塞 RS W1 产品 READY、ReferenceTrade 验收及开放 Gate。** RS2609 的局部数据 `DATA_READY` 不覆盖其余物理合约；页面正确显示不可用也不等于三策略或参考交易通过。先对这 64 个合约月形成带 D1/W1 前像、候选哈希、完整前缀回放及恢复边界的精确只读重建计划；真实 Canonical/Catalog 写入须另获范围明确的授权。重建后在同一版本和截止重新运行三策略、ReferenceTrade 与真实页面验收。无 Runtime、发布、通知或策略晋升操作。
