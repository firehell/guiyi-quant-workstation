# 苏冰四周期候选只读验收（2026-09-18）

- 候选代码：`9048f788a`；固定查询时间：`2026-09-18 18:30 +08:00`。
- 生产 Catalog/Canonical 只读，候选 API/Web 使用隔离 loopback；PostgreSQL 强制只读事务/连接，未请求 RQData、写入数据、改变 Scope/通知或切换 Runtime。
- 60 品种 × 4 周期共 240 项：**89 ready、0 warming、151 blocked**。浏览器 89 项 ready 均有图表、参考统计且输入 hash 与固定查询一致；148 项参考 API 409 并清空参考统计；BZ/EB/PG 的 1d 在普通行情图表前置层停止。
- 浏览器页面请求的 `as_of` 为当时页面首载时间；其 `input_snapshot_hash` 与固定查询相同，证明使用相同的完整交易日截止与输入。此次是候选页面验收，不是 release、Runtime 或自然预警验收。

| 周期 | ready | blocked | ready/60 |
|---|---:|---:|---:|
| 15m | 53 | 7 | 88.3% |

## 15m

- 完成：A, AG, AL, AO, AU, B, BU, BZ, C, CF, CJ, EB, EC, EG, FG, FU, I, J, JD, JM, L, LC, LH, M, MA, OI, P, PB, PD, PG, PK, PL, PP, PR, PS, PT, PX, RM, RS, RU, SA, SC, SF, SH, SI, SM, SR, SS, TA, UR, V, Y, ZN。
- 阻塞：AP, CU, HC, NI, PF, RB, SN。
| 30m | 6 | 54 | 10.0% |

## 30m

- 完成：A, AG, AU, B, BU, BZ。
- 阻塞：AL, AO, AP, C, CF, CJ, CU, EB, EC, EG, FG, FU, HC, I, J, JD, JM, L, LC, LH, M, MA, NI, OI, P, PB, PD, PF, PG, PK, PL, PP, PR, PS, PT, PX, RB, RM, RS, RU, SA, SC, SF, SH, SI, SM, SN, SR, SS, TA, UR, V, Y, ZN。
| 60m | 11 | 49 | 18.3% |

## 60m

- 完成：A, AG, AO, AP, AU, B, BU, BZ, PD, PT, RB。
- 阻塞：AL, C, CF, CJ, CU, EB, EC, EG, FG, FU, HC, I, J, JD, JM, L, LC, LH, M, MA, NI, OI, P, PB, PF, PG, PK, PL, PP, PR, PS, PX, RM, RS, RU, SA, SC, SF, SH, SI, SM, SN, SR, SS, TA, UR, V, Y, ZN。
| 1d | 19 | 41 | 31.7% |

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
