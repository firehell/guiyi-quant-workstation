# 剩余 12 品种 W1 精确缺口审计

- 冻结代码：`6423d85131e1f0ae3855bd7096c911d795461556`
- 完整周截点：`2026-09-18T07:00:00.000001+00:00`（北京时间 2026-09-18 15:00:00.000001）
- Catalog revision：`d2c65b1e44b34d588b6ee1b86fdfc4165cb3cc4c92241af9e6d2cd137bb753eb`
- 事务：REPEATABLE READ / READ ONLY；快照内稳定：True；独立新事务回读一致：True。
- 原生审计状态：incomplete；预算耗尽：False；provider=0，生产 writes=0。
- 固定分母：12 品种 × 3 策略 = 36；仅审计 W1。完整原生报告含其他周期占位项，未将其计入36格。

## 策略矩阵汇总

{'SOURCE_EXCEPTION': 6, 'DATA_UNAVAILABLE': 30}

| 品种 | 三策略主图状态 | 首个阻塞合约/日期 | 阻塞依赖合约数 | 修复提案 |
|---|---|---|---:|---|
| CJ | {'SOURCE_EXCEPTION': 3} | CJ2305 / 2022-05-20: SOURCE_NONPOSITIVE_PRICE | 2 | {} |
| OI | {'DATA_UNAVAILABLE': 3} | OI2611 / 2025-11-28: REPLAY_ENDPOINTS_MISSING | 1 | {} |
| PF | {'DATA_UNAVAILABLE': 3} | PF2304 / 2022-04-22: REPLAY_ENDPOINTS_MISSING | 40 | {'REVIEW_REQUIRED': 23} |
| PK | {'DATA_UNAVAILABLE': 3} | PK2411 / 2023-11-17: REPLAY_ENDPOINTS_MISSING | 4 | {'REVIEW_REQUIRED': 3} |
| PL | {'DATA_UNAVAILABLE': 3} | PL2603 / 2025-07-25: REPLAY_ENDPOINTS_MISSING | 5 | {'REVIEW_REQUIRED': 1} |
| PR | {'DATA_UNAVAILABLE': 3} | PR2506 / 2024-08-30: REPLAY_ENDPOINTS_MISSING | 14 | {'REVIEW_REQUIRED': 7} |
| PX | {'DATA_UNAVAILABLE': 3} | PX2505 / 2024-05-24: REPLAY_ENDPOINTS_MISSING | 8 | {'REVIEW_REQUIRED': 4} |
| RS | {'DATA_UNAVAILABLE': 3} | RS2609 / 2025-09-30: REPLAY_ENDPOINTS_MISSING | 11 | {} |
| SF | {'DATA_UNAVAILABLE': 3} | SF2306 / 2022-06-17: REPLAY_ENDPOINTS_MISSING | 23 | {'REVIEW_REQUIRED': 16} |
| SH | {'DATA_UNAVAILABLE': 3} | SH2501 / 2024-01-19: REPLAY_ENDPOINTS_MISSING | 5 | {'REVIEW_REQUIRED': 3} |
| SM | {'DATA_UNAVAILABLE': 3} | SM2310 / 2022-10-28: REPLAY_ENDPOINTS_MISSING | 10 | {'REVIEW_REQUIRED': 5} |
| SR | {'SOURCE_EXCEPTION': 3} | SR2303 / 2022-03-18: SOURCE_NONPOSITIVE_PRICE | 1 | {} |

## 逐合约清单

### CJ

阻塞依赖合约：CJ2305, CJ2309

待修复提案合约：无

### OI

阻塞依赖合约：OI2611

待修复提案合约：无

### PF

阻塞依赖合约：PF2302, PF2303, PF2304, PF2305, PF2306, PF2307, PF2308, PF2310, PF2311, PF2312, PF2402, PF2403, PF2405, PF2406, PF2407, PF2408, PF2409, PF2410, PF2411, PF2412, PF2502, PF2503, PF2504, PF2505, PF2506, PF2507, PF2508, PF2509, PF2510, PF2511, PF2512, PF2602, PF2603, PF2604, PF2606, PF2607, PF2608, PF2609, PF2610, PF2611

待修复提案合约：PF2304, PF2305, PF2306, PF2307, PF2310, PF2312, PF2402, PF2403, PF2407, PF2408, PF2410, PF2411, PF2412, PF2502, PF2503, PF2505, PF2506, PF2507, PF2509, PF2510, PF2511, PF2602, PF2604

### PK

阻塞依赖合约：PK2411, PK2511, PK2603, PK2611

待修复提案合约：PK2411, PK2511, PK2603

### PL

阻塞依赖合约：PL2603, PL2605, PL2607, PL2609, PL2611

待修复提案合约：PL2603

### PR

阻塞依赖合约：PR2506, PR2507, PR2509, PR2510, PR2511, PR2512, PR2601, PR2603, PR2605, PR2606, PR2607, PR2609, PR2610, PR2611

待修复提案合约：PR2506, PR2507, PR2509, PR2511, PR2512, PR2601, PR2603

### PX

阻塞依赖合约：PX2501, PX2505, PX2509, PX2511, PX2603, PX2607, PX2609, PX2611

待修复提案合约：PX2505, PX2509, PX2511, PX2603

### RS

阻塞依赖合约：RS2309, RS2311, RS2407, RS2409, RS2411, RS2507, RS2509, RS2511, RS2607, RS2608, RS2609

待修复提案合约：无

### SF

阻塞依赖合约：SF2303, SF2306, SF2307, SF2309, SF2310, SF2311, SF2312, SF2402, SF2403, SF2405, SF2410, SF2501, SF2502, SF2503, SF2506, SF2507, SF2509, SF2511, SF2601, SF2603, SF2605, SF2607, SF2611

待修复提案合约：SF2306, SF2307, SF2309, SF2310, SF2312, SF2402, SF2403, SF2410, SF2501, SF2502, SF2503, SF2506, SF2509, SF2511, SF2601, SF2603

### SH

阻塞依赖合约：SH2501, SH2505, SH2509, SH2607, SH2611

待修复提案合约：SH2501, SH2505, SH2509

### SM

阻塞依赖合约：SM2305, SM2306, SM2310, SM2311, SM2312, SM2402, SM2403, SM2603, SM2607, SM2611

待修复提案合约：SM2310, SM2311, SM2312, SM2403, SM2603

### SR

阻塞依赖合约：SR2303

待修复提案合约：无

## 证据与边界

- `strategy-matrix-36.csv/json`：36个组合的当前状态与第一处阻塞。
- `dependency-anomalies.json`：完整依赖阻塞、owner窗口、错误上下文；不能将主图第一处阻塞当成全部缺口。
- `repair-targets.json`、`repair-windows.csv`：各合约的月分区、expected/missing日期边界及条数、scope diagnostics与计划状态。窗口起止并不代表区间内每个交易日都缺失。
- `readiness-full.json`：原生完整枚举、依赖、候选修复与逐section结果。
- REVIEW_REQUIRED不是可执行补数批次，PROPOSED也不是生产授权。真实来源异常不通过造数消除。
- 本次是固定代码/数据截点的API与底层依赖审计，不是浏览器、正式开放、发布或Runtime验收。
- 首次沙箱连接失败未进入审计；`runner-error.json`保留该尝试，成功运行结果以本报告和audit-identity为准。

## 补充核验结论（同一代码与 Catalog revision）

原生36格均已取得终态，没有未检组合；原生完整依赖报告仍为 incomplete，原因不是预算，而是60条UNKNOWN。它们去重为30个合约/截止日单元（29个合约），均复现 SOURCE_QUALITY_CLASSIFICATION_UNSUPPORTED。check_dependency 在 product_reader.py:973 调用周线质量查询时未传 v2 classification_version，实际走默认v1。只记录问题，未修改业务代码。

对全部132个异常依赖单元显式调用既有v2接口：91个仍缺回放端点；PF2611另有2025-11-21周线来源冲突；40个可返回完整周线。后者仅证明结构可读取，不检查策略价格正值，因此不推翻CJ/SR的SOURCE_NONPOSITIVE_PRICE结果，也不代表策略READY。

对原生漏出的缺口补做28个合约规划。合并原生62项后共90项：{'REVIEW_REQUIRED': 82, 'PROPOSED': 7, 'PLANNER_BLOCKED': 1}。另有PF2611来源冲突单列，尚无可执行修复方案。

| 可进一步 prepare 的合约 | 请求估算 | 源bars估算 |
|---|---:|---:|
| OI2611 | 20 | 229 |
| PF2606 | 16 | 162 |
| PF2607 | 16 | 174 |
| PF2609 | 22 | 242 |
| PR2611 | 16 | 169 |
| SH2611 | 18 | 219 |
| SM2611 | 18 | 193 |

上述7项合计126次请求、1388根源bars，仅为纯planner提案，未下载、未prepare成授权批次、未写入。保留WEEKLY_SOURCE_PRICE_UNAVAILABLE中断；不能承诺修复后整个品种READY。

82项REVIEW_REQUIRED包含WEEKLY_DAILY_VALUE_CONFLICT，不能按普通补数直接apply；RS2609规划被WEEKLY_SOURCE_BAR_CONFLICT阻断。

完整更新清单：`repair-targets-all.json`与`repair-windows-all.csv`；显式v2明细：`v2-dependency-diagnosis.json`；来源异常首次日期：`source-exceptions.csv`；未分类复现：`unknown-diagnosis.json`。所有补充查询均已核对同一Catalog revision。

建议顺序：先修正审计器v2政策传递并定向复验；对7个无值冲突提案形成精确prepare包；82项值冲突与PF2611/RS2609分别先做来源核验和修复侧裁定；CJ/SR核验策略输入非正价事实及中断合同，不能降级规则凑READY。真实下载、Canonical/Catalog写入另需精确范围授权。
