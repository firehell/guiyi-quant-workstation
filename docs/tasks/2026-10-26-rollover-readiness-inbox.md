# 主力切换准备与Reference连续恢复实施

Owner批准完整方案：自动预算内预热；顺序恢复真实原件并标记延迟；不补发过期通知。
基线6ca3c3cc337421b30487cb050b814fef0ee28fda，独立feature/rollover-readiness-inbox。
原develop两处Web修改不属于本任务。

- [x] 统一权威新主力数据准备：64 requests/2M bars per contract、256/8M per trading day、1200s准入，独立线程和原生维护锁。
- [x] 两表持久接收与逐流完成事务、120000/day与6GiB未完成容量；DB确认后才ACK。
- [x] 逐流公平调度及延迟时间、原生协议边界切换和健康接口。
- [x] 单元/隔离PG+Redis/故障注入、独立Review。
- [ ] 迁移/兼容发布/新协议切换、EG恢复和自然业务现场验收。

当前根因原件：原workspace output/reference-stall-diagnosis-20261026。
真实操作串行；schema/protocol推进后只能兼容恢复或前向修复，不删除数据回滚。

实现与验证记录：
- 新增 contract_preparation / contract_preparation_runtime：稳定状态、预算预留、原生锁内权威复验、后台线程；逐消费者结果与只读缓存健康分离。
- 新增 inbox / inbox_protocol 与0053：不可变原件和冻结路由；DB提交先于ACK；逐流有界轮转，缺历史/原件冲突/未知提交分开。
- retained replay经唯一MarketDataService验证，不用provider替代缺失原件；原始时间及delivery_timing_v2随计算保存，通知有效期不刷新。
- 整组切换仅新增精确0053已预装兼容证明；停服前/CAS前重新校验schema、plan期限及停机预算。
- 独立storage Review：22真实PG用例通过；Runtime/Market Review修正后无Confirmed Issue，允许集成develop。
- 旧720容量测试原分支已是1440路；exact基线复现1440!=1260后，仅更新六周期1440路断言，真实PG容量/重启幂等用例通过。
- 409项最终合跑曾有1项fixture导入顺序污染，最小修正仅涉及测试别名patch；整份host65通过，扩大回归进行中。
- Market/切换专项最终446通过；Web type/build/capability/topology通过；OpenSpec12/12、secret0、Ruff与diff通过。
- 0052→0053离线DDL dry-run：5125 bytes，sha256 18f3f74d83b441c863938363c127469f78ad1764318047637deac3ab7dd38f98。
- 当前尚无生产迁移、补数、协议推进、发布或Runtime切换；v1.16.11仅候选版本标记。
- 回滚：DDL失败事务回滚；原件非空禁止downgrade；首个v2接收后仅兼容恢复/前向修复。不开启额外通知或交易。

最终冻结核心回归：带隔离PG/Redis运行 inbox/protocol/runtime/wake/retained-replay、contract-preparation、runtime-health/schema/cohort/host共315 passed/7.97s。最终逐品种authority等待隔离独立Review通过，无新增Confirmed Issue；公开health增加同一有界字段，120项健康测试通过。扩大Reference回归仍运行，尚无新失败。

扩大回归最终1553 passed/664.96s（Reference全模块、准备/HDM、schema/cohort/host/runtime-health，真实隔离PG/Redis）；fixture污染已修正。合并origin/develop后的精确候选86ec793eb定向324 passed/11.35s，Web重新build/type/topology通过，secret0/diff通过。独立Review允许集成。

23:25 PR497集成develop31628cfa1；生产0052→0053单次migration已confirmed。独立schema proof f822759925d99fe3ff125adc6630f7f1e4bdba3ff666db0a7455484348df337b（数据库身份hash独立保存），两表0行。唯一intent、结果保存在output/rollover-readiness-20261026/migration-{intent,result}.json；未启用协议或改游标，Runtime仍v1.16.10/gen30。
