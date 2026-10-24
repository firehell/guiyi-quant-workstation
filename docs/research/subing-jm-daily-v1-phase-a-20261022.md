# JM日线阶段A：本地输入核验记录

状态：阶段A核查完成；完整历史执行输入不足。允许继续实现已验证区段的离线研究模型，不代表策略验证通过。

本记录与[规则设计](subing-jm-daily-v1-design-20261022.md)共同构成阶段B研究合同，不更新运行阶段。

## 核验身份

- 核验时刻：2026-10-22T13:59:04.953242+00:00（UTC）；完成交易日截止2026-10-22。
- 基线代码：`47ba1868dd445afc90f2fe72963bb0051db387bd`；本轮审计脚本SHA256：`df130eb6f1f324761da16e3537ba97c3fcde8ca0f4953ebce6cd4a7a29c34207`。
- 最终本地明细：`output/subing-jm-daily-v1-20261022/phase-a-003.json`，SHA256：`1b5b88e9fb8f56d0dad2ded357a5df89193a7b3fb6bd1fc95c79b5a9ecc03055`。
- rank1映射快照：`14ff519930c7bd7c9553af25a77c4143ae7c1d87493c0fd3a66e83aa04bde864`；920条登记中919个已完成日逐一核查，2026-10-23一条未完成登记明确排除。
- 证据保留001/002/003三个审计版本，不覆盖早期结果；001时尚未登记10/23，不能把两次映射计数差异当成遗漏。
- 单次审计使用REPEATABLE READ、READ ONLY事务并回滚；源码/指引、JSON审计结果为本任务新增文件。provider调用0、行情/数据库写入0、策略回测0。
- 主owner扫描、日线前缀及通过的换月检查均复核来源哈希，执行快照文件前后SHA一致。行情明细与物理分区身份在最终JSON；不从目录glob选择行情。

## 全部owner段

以下日线、15分钟、1分钟数量仅统计rank1有效区间；日线预热另从该物理合约权威生命周期读取，不继承其他合约指标。所有12段的三个周期端点、顺序、重复、正价格、Session及日线前缀均PASS，919个交易日均可评估原日线交叉。

| 物理合约 | rank1起止 | 已完成日 | 日线 / 15分钟 / 1分钟 | 执行事实可用日 | 执行事实缺失日 |
| --- | --- | ---: | --- | ---: | ---: |
| JM2305 | 2023-01-03～2023-04-13 | 67 | 67 / 1517 / 22755 | 0 | 67 |
| JM2309 | 2023-04-14～2023-08-11 | 81 | 81 / 1847 / 27705 | 0 | 81 |
| JM2401 | 2023-08-14～2023-12-07 | 78 | 78 / 1786 / 26790 | 0 | 78 |
| JM2405 | 2023-12-08～2024-04-10 | 80 | 80 / 1816 / 27240 | 0 | 80 |
| JM2409 | 2024-04-11～2024-08-16 | 88 | 88 / 2008 / 30120 | 0 | 88 |
| JM2501 | 2024-08-19～2024-12-17 | 80 | 80 / 1824 / 27360 | 47 | 33 |
| JM2505 | 2024-12-18～2025-04-15 | 77 | 77 / 1747 / 26205 | 77 | 0 |
| JM2509 | 2025-04-16～2025-07-31 | 73 | 73 / 1663 / 24945 | 73 | 0 |
| JM2601 | 2025-08-01～2025-12-04 | 84 | 84 / 1924 / 28860 | 84 | 0 |
| JM2605 | 2025-12-05～2026-04-16 | 86 | 86 / 1954 / 29310 | 86 | 0 |
| JM2609 | 2026-04-17～2026-08-18 | 84 | 84 / 1916 / 28740 | 84 | 0 |
| JM2701 | 2026-08-19～2026-10-22 | 41 | 41 / 927 / 13905 | 38 | 3 |

## 逐区段可用性与精确缺口

下表由919个逐日记录合并，仅跨相邻权威交易日且不跨合约/状态。不是缩小请求后重报全历史通过。

| 合约 | 起止交易日 | 日数 | 结果 |
| --- | --- | ---: | --- |
| JM2305 | 2023-01-03～2023-04-13 | 67 | EXECUTION_FACTS_MISSING |
| JM2309 | 2023-04-14～2023-08-11 | 81 | EXECUTION_FACTS_MISSING |
| JM2401 | 2023-08-14～2023-12-07 | 78 | EXECUTION_FACTS_MISSING |
| JM2405 | 2023-12-08～2024-04-10 | 80 | EXECUTION_FACTS_MISSING |
| JM2409 | 2024-04-11～2024-08-16 | 88 | EXECUTION_FACTS_MISSING |
| JM2501 | 2024-08-19～2024-10-11 | 33 | EXECUTION_FACTS_MISSING |
| JM2501 | 2024-10-14～2024-12-17 | 47 | INPUTS_VERIFIED |
| JM2505 | 2024-12-18～2025-04-15 | 77 | INPUTS_VERIFIED |
| JM2509 | 2025-04-16～2025-07-31 | 73 | INPUTS_VERIFIED |
| JM2601 | 2025-08-01～2025-12-04 | 84 | INPUTS_VERIFIED |
| JM2605 | 2025-12-05～2026-04-16 | 86 | INPUTS_VERIFIED |
| JM2609 | 2026-04-17～2026-08-18 | 84 | INPUTS_VERIFIED |
| JM2701 | 2026-08-19～2026-10-19 | 38 | INPUTS_VERIFIED |
| JM2701 | 2026-10-20～2026-10-22 | 3 | EXECUTION_FACTS_MISSING |

汇总：489日INPUTS_VERIFIED，430日EXECUTION_FACTS_MISSING，执行事实冲突0；本轮主owner行情缺口、重复、非正价格、Session错误均0。489日窗口为2024-10-14～2026-10-19，可进入阶段B输入研究；2023-01-03～2024-10-11及2026-10-20～2026-10-22缺少本轮已追溯快照中的可验证执行事实。

## 执行快照来源

已追溯既有JM Paper研究与期货双向研究记录。通过共享严格校验器逐日验证物理合约、tick、乘数、双向保证金、开仓/平今/平昨费用、昨结算和上下限价；重复日期、非法数值或缺项不能变为可用。快照重叠区间归一化数值一致；捕获时间和文件身份分别保留，不伪造历史known_at。

- `output/jm-paper-first-three-20261011/execution-facts-v2.json`：捕获于2026-10-11T14:47:35.217528+00:00；SHA256 `b15ec9ad682f0ce6f7d40749bc395f8bf2269935235c0900b50aa87316785d5e`。
- `output/newow-futures-bidir-v1-20261020-evidence/facts-attempt-001/jm.json`：捕获于2026-10-20T16:06:37.588473+00:00；SHA256 `86bf8ec9c0da6e284325ff0a94000798223828d844ddfd11bef8af13d9a7b715`。

较新JM快照由[期货双向研究验收](newow-futures-bidir-v1-20261021.md)追溯，provider计划身份为`24c2084af7a85fb3b390a0230d251bf22b4f62c193aac2a0faab2de71c46a793`，同目录`provider-plan.json`与快照plan_hash一致。它扩大了此前只找到2025-10-13～2026-10-09快照时的覆盖判断。本轮未重新请求provider，也不声称已穷尽磁盘上未登记/未追溯的任意文件。

## 换月退出事实

| 旧合约→新合约 | 新owner首交易日 | 旧合约退出输入 |
| --- | --- | --- |
| JM2305→JM2309 | 2023-04-14 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2309→JM2401 | 2023-08-14 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2401→JM2405 | 2023-12-08 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2405→JM2409 | 2024-04-11 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2409→JM2501 | 2024-08-19 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2501→JM2505 | 2024-12-18 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2505→JM2509 | 2025-04-16 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2509→JM2601 | 2025-08-01 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2601→JM2605 | 2025-12-05 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2605→JM2609 | 2026-04-17 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |
| JM2609→JM2701 | 2026-08-19 | 旧合约1分钟DATASET_OR_PARTITION_MISSING；执行事实缺失 |

11个边界均ROLLOVER_EXIT_INPUTS_MISSING。检查的是旧合约在新owner首交易日的物理输入，而不是误把新owner正常行情算作缺口。阶段B遇跨界持仓须创建旧合约退出意图并保留未成交/中断事实，不能用新合约价格、旧日最后价或零成本自动换月补齐收益。本轮未补数据。

## 验证与验收边界

实际执行：审计CLI读取两份已有快照并通过MDS扫描全部owner；最终JSON保留每个区段的输入hash、来源分区hash、每个交易日的分类以及11个换月检查。

定向测试命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=services/quant-api:packages/quant-core:. services/quant-api/.venv/bin/python -m pytest services/quant-api/tests/research/test_subing_jm_daily_preflight.py -q
services/quant-api/.venv/bin/ruff check scripts/research/subing_jm_daily_preflight.py services/quant-api/tests/research/test_subing_jm_daily_preflight.py
```

审计工具覆盖端点缺失/多余/重复/乱序、双向保证金与三类费用、坏费用/保证金/限价/重复日期、缺失Session不桥接、MACD第34/35根交叉可评估边界、前缀一致性和来源变化fail-closed。构造数据仅验证审计行为，不作为历史证据；策略建仓/止损/账户实现仍留在阶段B。

独立Review发现并修复了第34根误判可评估、Session失败日可能被窗口桥接两项审计失败路径；本次真实区段均有完整前缀且无Session异常，修正未改变919/489/430的分类。最终13项定向测试通过，Ruff通过，四个文件secret scan零发现、文档引用及空白检查通过。独立Review另行复核13项测试、003报告/审计脚本/两份执行快照SHA、919个唯一日及11个换月缺口，结论为无未解决Confirmed Issue、允许集成develop。

验收结论：阶段A核查完成，允许继续实现已验证区段的离线模型；完整2023年以来账户研究及缺少旧合约退出输入的跨界成交仍阻塞。本轮没有新策略盈亏结果，不证明OOS、Paper或Runtime已就绪。
