# 实施任务 · Market Core

任务按 [目标](proposal.md)、[设计](design.md) 和 [候选合同](specs/guiyi-v2-market-foundation/spec.md) 实施。勾选依据为当前候选的实际证据。真实运行与正式切换各自保留验收状态。

## 市场事实与组件

- [x] M1 核对写入者、消费者、发布和恢复依赖、原件与账户保护范围。 [依赖库存](evidence/M1-inventory.md)
- [x] M2 实测锁定 VeighNa 4.4.0 headless 与适用插件。复用 EventEngine，保留经过逐值验证的历史适配、Decimal 领域对象、Session-aware 分钟聚合和有界记录。 [组件证据](evidence/storage/README.md)
- [x] M3 用同一冻结行情完成 Mac mini M4／16 GB 对照，确认 Canonical Parquet + PostgreSQL Catalog 为唯一历史权威。 [基准与完整性](evidence/storage/README.md)

## 实时与统一读取

- [ ] M4 候选 Tick 接入、累计量额、OI、盘口、完成性、来源代次、断线迟到和 60／70 回放已验证。五根真实 RB2701 候选分钟线与供应商实时 1m 逐字段相等，含自然 Session 的 15:00 末根。待同日权威历史、自然跨夜与目标规模现场读回。 [实时与回放证据](evidence/tick/README.md)
- [x] M5 统一严格历史、盘中和待归档 Live、报价／活动，以及实际主力和物理合约入口。验证短休、夜盘重叠、同端点修订、候选 Web 和独立完成输入。 [验证入口](evidence/tick/README.md)

## 归档、容量和迁移

- [x] M6 已验证隔离归档、完整读回、按交易日清理、未知提交停驻、同日失败后的成功凭证恢复，以及空库首张凭证物化。自然盘后整批仍待验。 [归档证据](evidence/archive-reference.md)
- [x] M7 完成同机七周期历史读写、60／70 Tick 接收与完成流容量，确认端点、队列、重启和快期／苏冰输入回归。现场待验为目标规模的供应商自然流、完整盘后窗口及实际重连。 [容量证据](evidence/tick/README.md)
- [x] M8 完成候选 active delta、Web／指标、牛哇 v35 盘后参考、快期、苏冰和 Alert 的隔离迁移与复验。独立 Review 已回归修正项。旧源和受引用原件按退役前置保留。 [依赖库存](evidence/M1-inventory.md) · [切换准备](cutover.md)
- [x] M9 完成隔离环境的切换演练入口、读回、恢复流程和正式操作前置。正式迁移、源切换、发布与 Runtime 不在本次范围。 [切换准备](cutover.md)

定向命令见 [TESTING](../../../TESTING.md)。本阶段的真实数据动作限于有界 RQData 只读采样与验收。策略、风险、模拟或真实账户规则，以及 RQAlpha 研究域遵循现有合同。
