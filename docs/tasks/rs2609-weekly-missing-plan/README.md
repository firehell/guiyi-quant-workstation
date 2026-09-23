# RS2609 四根缺失 W1：只读精确计划

2026-09-23 基于当前 Catalog 两次独立只读重算，结果一致。[机器计划](../../../outputs/rs2609-weekly-missing/prepare.json) SHA-256 为 `3d4a57ed87bc68904a2724be847214fceab798deaf0de8bdb4403823fcf29a26`；Catalog revision 为 `f7293a062bfc7cdb7297eaf39ed817d6555f555499d0411a62b7fd2fa297b181`。`scripts/rs2609_weekly_missing_plan.py` 只打开 `SET TRANSACTION READ ONLY`，不含 apply 入口。真实 provider 请求、生产 Canonical/Catalog 写入均为 0。

本计划只处理 RS2609 的四个 `W1_MISSING_D1_COMPLETE`；此前四周 `QUALITY_FACT_WITH_STORED_W1` 已按独立批准批次修复。四周的预期 D1 端点都由当前合约生命周期、Calendar/Session 证明，与 Canonical 逐端点一致；15 根 D1 均为有效正价，无该周质量事实，也不属于严格 `NO_TRADE`。完整源行、D1 文件 URI/字节哈希/质量摘要、聚合结果和候选 W1 文件哈希均在机器计划中。周线由 `exchange-daily-no-trade-v2` 从同一物理合约 D1 生成，不请求 RQData W1，也不读取合成主连价格。

| 完整周末（交易日） | D1 天数 | 来源日期 | 目标 W1 月 | 当前 W1 月 | 候选动作 |
| --- | ---: | --- | --- | --- | --- |
| 2025-09-30 | 2 | 09-29、09-30 | 2025-09 | 无指针 | 新增 1 根 |
| 2025-12-31 | 3 | 12-29 至 12-31 | 2025-12 | 无指针 | 新增 1 根 |
| 2026-01-09 | 5 | 01-05 至 01-09 | 2026-01 | 仅 01-30 | 新增 01-09、保留 01-30 |
| 2026-01-16 | 5 | 01-12 至 01-16 | 2026-01 | 仅 01-30 | 新增 01-16、保留 01-30 |

9 月候选 URI 是 `kind=contract/symbol=rs/series=RS2609/frequency=1w/year=2025/month=09/part.18835870ebe5460a9b4632b50a8400c69d00c1dd463a76c5c9093553cde1599b.parquet`；12 月是同一目录结构下 `year=2025/month=12/part.594767dd7c7e23791b079e00c35fddde3dea42fbedba6ae679178bd5cf37eb00.parquet`；1 月是 `year=2026/month=01/part.0494868655f2fc3510b7b322ca4288a09465fb53c53e958c58da5e9be5aed30c.parquet`。1 月旧指针和 01-30 保留行的前像在机器计划中。候选月份的行数分别是 1、1、3；不能补同月其他质量中断周或改动其他合约。

## 只读候选验收

三个候选月仅在进程内替换 Catalog/Store 读取，未创建候选文件或修改活动指针。真实 `MarketDataService.query_contract_weekly_replay_quality` 在固定截止 `2026-09-18T07:00:00.000001Z`、`weekly-d1-quality-v2` 下，对 RS2609 截至 2026-09-11 的完整物理合约回放返回 **33 根正常 W1、18 次质量中断**，四个目标周均成为正常 Bar。原有 01-30 周由同一 D1 聚合逐值校验。此结果证明候选数据能消除该合约的四处 W1 缺口，不证明三策略、ReferenceTrade、页面或 RS 品种整体 READY。

## 后续受控批次边界

本轮没有生产 apply。若另行批准实施，目标仅为上述 **RS2609 三个 W1 月指针**；预期 provider 预算 0、D1 写入 0、W1 新文件 3 份，Catalog 在一个事务中注册 3 个指针。先确认现役消费者可读取不可变 hash URI 和质量中断、旧 writer 未运行；持全局维护锁重算并核对计划哈希、Calendar/Session、D1 质量摘要、三个旧 W1 指针及文件字节。候选必须通过物理、coverage、保留行不变、同源 D1→W1 和完整前缀回放检查，然后提交；提交后用新只读事务查明全部指针及回放。重复执行若三指针已等于候选，应只报告已完成；混合、漂移或未知结果立即停批，不自动重试。

提交前失败保持旧指针，已发布但未引用的不可变文件可留存。提交结果不明先独立只读 `inspect`，不得猜测回滚或重试。可验证恢复前像是 9 月/12 月 **无指针**、1 月原 `part.parquet` 指针及其字节哈希；恢复必须另行形成精确操作、获授权并在维护锁内原子处理，保留所有历史文件。正式实施后还需分开验证三策略回放、ReferenceTrade 中断与重新预热、Newow 页面及产品 Gate；不得把本候选的 `33/18` 当成正式开放结论。
