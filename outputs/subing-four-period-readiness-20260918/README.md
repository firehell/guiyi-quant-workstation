# 苏冰四周期候选只读验收（2026-09-18）

- 候选代码：`9048f788a`；固定查询时间：`2026-09-18 18:30 +08:00`。
- 初始页面验收阶段生产 Catalog/Canonical 只读，候选 API/Web 使用隔离 loopback；PostgreSQL 强制只读事务/连接，当时未请求 RQData、写入数据、改变 Scope/通知或切换 Runtime。后续经独立授权执行的 source-only 查询另见文末结算，仍未写入生产数据。
- 60 品种 × 4 周期共 240 项：**89 ready、0 warming、151 blocked**。浏览器 89 项 ready 均有图表、参考统计且输入 hash 与固定查询一致；148 项参考 API 409 并清空参考统计；BZ/EB/PG 的 1d 在普通行情图表前置层停止。
- 浏览器页面请求的 `as_of` 为当时页面首载时间；其 `input_snapshot_hash` 与固定查询相同，证明使用相同的完整交易日截止与输入。此次是候选页面验收，不是 release、Runtime 或自然预警验收。

| 周期 | ready | blocked | ready/60 |
|---|---:|---:|---:|
| 15m | 53 | 7 | 88.3% |
| 30m | 6 | 54 | 10.0% |
| 60m | 11 | 49 | 18.3% |
| 1d | 19 | 41 | 31.7% |

## 15m

- 完成：A, AG, AL, AO, AU, B, BU, BZ, C, CF, CJ, EB, EC, EG, FG, FU, I, J, JD, JM, L, LC, LH, M, MA, OI, P, PB, PD, PG, PK, PL, PP, PR, PS, PT, PX, RM, RS, RU, SA, SC, SF, SH, SI, SM, SR, SS, TA, UR, V, Y, ZN。
- 阻塞：AP, CU, HC, NI, PF, RB, SN。

## 30m

- 完成：A, AG, AU, B, BU, BZ。
- 阻塞：AL, AO, AP, C, CF, CJ, CU, EB, EC, EG, FG, FU, HC, I, J, JD, JM, L, LC, LH, M, MA, NI, OI, P, PB, PD, PF, PG, PK, PL, PP, PR, PS, PT, PX, RB, RM, RS, RU, SA, SC, SF, SH, SI, SM, SN, SR, SS, TA, UR, V, Y, ZN。

## 60m

- 完成：A, AG, AO, AP, AU, B, BU, BZ, PD, PT, RB。
- 阻塞：AL, C, CF, CJ, CU, EB, EC, EG, FG, FU, HC, I, J, JD, JM, L, LC, LH, M, MA, NI, OI, P, PB, PF, PG, PK, PL, PP, PR, PS, PX, RM, RS, RU, SA, SC, SF, SH, SI, SM, SN, SR, SS, TA, UR, V, Y, ZN。

## 1d

- 完成：AO, AP, AU, BU, CJ, EC, EG, HC, JD, LC, LH, NI, PD, PS, PT, RB, RU, SI, UR。
- 阻塞：A, AG, AL, B, BZ, C, CF, CU, EB, FG, FU, I, J, JM, L, M, MA, OI, P, PB, PF, PG, PK, PL, PP, PR, PX, RM, RS, SA, SC, SF, SH, SM, SN, SR, SS, TA, V, Y, ZN。

## 精确阻塞分类

- 15m：7 项 `physical_contract_replay / DATASET_OR_PARTITION_MISSING`。
- 30m：54 项同类物理合约生命周期分区缺失。
- 60m：49 项同类物理合约生命周期分区缺失。
- 1d：34 项物理合约生命周期分区缺失；BZ、EB、PG 为 `PRICE_UNAVAILABLE`，普通 K 线页面也先行阻塞；PK、RS、SF、SM 为物理前缀非正 Close，分别发现 1、229、15、43 根，当前参考投影按合同 fail closed。
- 每项的物理合约、预期端点数、阶段、公开错误码、输入 hash 和页面读回见 [`acceptance.json`](acceptance.json)。

## Gate

- 候选代码与页面只读验收：89 项 ready 可作为候选页面证据；151 项保持数据或价格事实阻塞。
- develop 集成、main/tag/release、Runtime promotion 与自然业务验收尚未执行。生产补数或 Canonical/DB 写入需另行明确范围授权。

## 144 项缺分区处理与复验（同一固定截止）

owner 后续明确授权处理上述 144 项。先按原诊断的物理合约、频率与生命周期逐月生成 [只读计划](missing-partition-plan.json)：144/144 成功、88 个不同物理合约、1,189 个去重月目标；逐项计划相加的 RQData 请求上限为 254 次。执行保持单合约单周期、锁内重算 plan hash、一次请求、不自动重试。首层 [执行回执](missing-partition-apply.json) 中 A2609 日线先行试运行成功，140 项随后通过；OI2609 与 PF2609 日线各有一个 9 月分区因 `RQDATA_ZERO_OHL_INVALID` 被拒，均只读回查并隔离；SC2611 日线规划零目标，未写入。

首层复验揭露两类不同问题：一是另一个物理合约的真实分区缺口；二是周一挂牌合约首根 Bar 之前的周末 Session 边界被误当成缺分区。后者以预期交易日端点核验修复，保留真实缺 Bar 时 fail closed；独立 Review 发现直读路径遗漏退役品种拒绝，已补回并测试。最终代码提交 `64b6bda0b`。对仍属于原 144 组合的新合约，另存 [第二层只读计划](second-wave-plan.json) 与 [执行回执](second-wave-apply.json)：24/24 通过。RS 30 分随后显现的 RS2701 单个派生分区另有 [精确计划](third-wave-plan.json) 与 [回执](third-wave-apply.json)，零新增 RQData 请求。三层合计发布 **1,442 个月分区，实际 RQData 请求 154 次**，未超出 254 次预算；OI/PF 失败分区未重试。

最终 [240 项数据读回](post-repair-data-readback.json) 与 [真实 Chromium 页面读回](post-repair-page-readback.json) 均使用 `2026-09-18 18:30 +08:00` 截止：**223 ready、17 blocked**。15m、30m、60m 各 60/60；1d 为 43/60。浏览器中 223 个 ready 页面有图表和参考统计，输入 hash 与固定数据读回一致；10 个计算冲突页面的参考 API 为 409、无统计；7 个缺价页面显示“行情事实不可用”、无参考统计。非 15m 的可加载页面均显示“本周期未启用预警”。

17 个 1d 阻塞：`PRICE_UNAVAILABLE` 为 BZ、C、EB、I、P、PG、Y；`SUBING_REFERENCE_DATA_CONFLICT` 为 OI、PF、PK、PL、PR、PX、RS、SF、SH、SM。对后 10 项的主力映射物理合约做了[只读非正 Close 扫描](conflict-source-scan.json)，10/10 均存在该来源数值事实；其中 OI/PF 的 9 月源请求另被 `RQDATA_ZERO_OHL_INVALID` 硬校验拒绝。当前不补造 OHLC、不绕过冲突或扩大源请求；这 17 项仍需各自的数据质量/参考口径诊断。全部验收是候选数据与页面证据，不等于 develop 集成、release、Runtime 或自然业务通过。

## 17 个日线来源问题逐项诊断与同截止复验（2026-09-19）

在候选分支 `ad2c48fff` 上重读生产 Catalog、MainContractMap 和 Canonical，PostgreSQL 使用只读事务；再次以 `2026-09-18 18:30 +08:00` 查询 SuBing 17 项，并用隔离的 loopback 候选 API/Web 在真实 Chromium 逐页复验。逐项主力分段、物理前缀、来源质量日及哈希、非正 Close 的合约与日期、数据返回码和页面结果见 [d1-17-source-diagnosis.json](d1-17-source-diagnosis.json)。未请求 provider，未发布分区或修改生产 DB、Scope、Runtime、通知。

| 品种 | 触发层 | 精确来源事实 |
|---|---|---|
| BZ | 物理前缀 `PRICE_UNAVAILABLE` | BZ2610：2026-03-20 |
| C | 物理前缀 `PRICE_UNAVAILABLE` | C2609：2026-09-10 |
| EB | 物理前缀 `PRICE_UNAVAILABLE` | EB2606：2025-07-03、08-29、09-19 |
| I | 物理前缀 `PRICE_UNAVAILABLE` | I2609：2026-09-09 |
| P | 物理前缀 `PRICE_UNAVAILABLE` | P2609：2026-09-09 |
| PG | 物理前缀 `PRICE_UNAVAILABLE` | PG2605：2025-06-04 |
| Y | 物理前缀 `PRICE_UNAVAILABLE` | Y2609：2026-09-09 |
| OI | 投影前缀 Close≤0 | 3 根；2025-11-17 至 11-21 |
| PF | 投影前缀 Close≤0 | 180 根；2025-06-17 至 2026-02-27 |
| PK | 投影前缀 Close≤0 | 1 根；2025-12-19 |
| PL | 投影前缀 Close≤0 | 328 根；2025-07-23 至 2026-05-22 |
| PR | 投影前缀 Close≤0 | 292 根；2025-05-21 至 2026-04-07 |
| PX | 投影前缀 Close≤0 | 101 根；2025-07-15 至 2026-02-27 |
| RS | 投影前缀 Close≤0 | 229 根；2025-09-15 至 2026-09-09，其中 5 根处于主力持有日 |
| SF | 投影前缀 Close≤0 | 15 根；2025-05-20 至 12-24 |
| SH | 投影前缀 Close≤0 | 6 根；2025-07-15 至 12-25 |
| SM | 投影前缀 Close≤0 | 43 根；2025-07-15 至 2026-04-15 |

七项来源质量事实均位于当前苏冰读取的物理合约预热前缀内，形态为零 Open/High/Low、正 Close；对照记录带请求与响应哈希。十项的非正 Close 在 Canonical 物理前缀中，`_inputs` 均成功，`project_reference` 在输入校验处拒绝；除 RS 的 5 根外，其余均在该合约的非主力日。此前 `conflict-source-scan.json` 统计整个合约生命周期，不能解释为主力持有日错误；本段按苏冰实际消费的前缀重新计数。Canonical 旧 Bar 的直接 RQData 原始响应未在此次审计中重取，不能仅凭现有零值判定 provider 或发布环节哪一层产生了异常。

同截止重读结果仍为 **7 个 `PRICE_UNAVAILABLE`、10 个 `SUBING_REFERENCE_DATA_CONFLICT`**。浏览器 7 个缺价页均显示“行情事实不可用”，无工作区或参考统计；另 10 个页面有图表，参考 API 均为 409 且无参考统计。17/17 保持 fail closed，未进入 ready。OI/PF 的 9 月硬无效源分区仍是另外两项未关闭的来源缺口；解决前缀异常后也须独立读回。当前没有依据跳过物理预热前缀、替换零价或宣布 240/240 ready；PR #378 保持草稿，develop 集成 Gate 仍未关闭。

随后继续核对本机已有 source-response、journal、Catalog 质量 hash、Canonical 文件 hash 与当前[正式 warm-up dry-run](d1-17-contract-warmup-dryrun.json)，形成 [17 项来源证据刷新](d1-17-source-evidence-refresh.json)、[16 请求 source-only 候选](d1-17-source-verification-candidate.json)、[机器可读修复范围](d1-17-repair-scope.json)及[修复决定](D1_17_REPAIR_DECISION.md)。1,207 个既有异常日期中，1,159 个有已保存原始来源响应，48 个尚缺 raw replay；OI/PF 九月另有 18 个硬校验失败日期无保存响应。下一批仅为 16 次、66 日期、零写入的来源验证候选，当前未请求 provider。正式 dry-run 证明苏冰实际消费前缀内没有缺分区目标；全生命周期规划的 42 个目标中，OI2609/PF2609 九月 2 项保留为独立缺失分区 Gate，其余 40 项、20 个合约明确排除在本任务之外。

owner 后续授权并执行上述冻结 source-only 候选，详见 [执行说明](D1_17_SOURCE_VERIFICATION_EXECUTION.md)与[机器结算](d1-17-source-verification-execution.json)。批次在第 9 个请求因 PF2611/2025-12 返回 10 个额外区间交易日而按合同停止：started/saved 9、完成 8、失败 1、未执行 7，零重试。共保存 55 行 raw，其中目标 45 日、额外 10 日；原 1,207 个异常日已有来源证据增加到 1,186 日，PF2611 10 日、RS2609 10 日、Y2609 1 日仍未执行。OI/PF 九月 18 日均已观察，但含 10 个非正 Close；当前零个完整分区具备生产修复条件。未执行 Canonical、数据库、页面、release 或 Runtime 操作。
