# 架构决策记录

更新时间：2026-08-08

本文件只保留当前有效、长期影响代码或数据语义的决策。历史过程由 Git 与 OpenSpec archive 追溯。

| 主题 | 决策 | 边界 |
|---|---|---|
| 产品 | 本地、单用户国内期货研究工作站 | 不做自动交易、SaaS、多用户或无人值守下单 |
| 个人开发 | 普通仓库变更直接在 `develop` 实现并按影响验证 | 不要求为形式增加 Issue、packet、receipt 或兼容层 |
| 外部操作 | 正式数据/DB/Runtime/live/通知/release 只接受范围明确的一次性执行意图 | dry-run 不授权 mutation；成功、失败或重试后需新意图 |
| 数据源 | RQData 是唯一外部行情事实源 | 不建多 provider seam、插件或逐行多源裁决 |
| 历史存储 | 只长期保存一套 Canonical Parquet | staging 临时；PostgreSQL 不存 Bar |
| 数据身份 | `DatasetKey=(kind,symbol,series_or_contract,frequency)` | provider/schema/source digest 进 Manifest，不进身份 |
| 主力数据 | 物理保存真实合约 Canonical，actual-dominant 查询时拼接 | 不长期保存重复的主力拼接 Parquet |
| 周期 | direct 为 `1m/1d/1w`，derived 为 `5m/15m/30m/60m` | derived 只读同 Dataset Canonical 1m，不调 RQData |
| 分区 | 每 Dataset 每自然月一个当前分区 | repair 可原子替换 closed month；不保留 active overlay/data version |
| 质量 | 标准化后执行 schema、identity、OHLCV、session、coverage、physical 六项硬校验 | 失败保留最后有效分区，建立当前 DataGap |
| Catalog | PostgreSQL 只保留 10 张最小 active 数据表 | 不新建数据库运行历史、通用 lineage 或任务中心 |
| 查询 | MarketDataService 是唯一历史行情入口 | 消费者不得 glob、自选文件、自判主力或跨频回退 |
| 增量 | `--since` 是检查下界，`--through` 是固定水位，计算精确历史洞 | 同 fixed through 重跑必须零目标、零写入、零 RQData |
| bootstrap | 一次性白名单导入，问题窗口 RQData 精确重下 | 最终收口后只保留 RQData 全量重建 |
| live | historical canonical 与 live observation 分离 | 当前无盘中 Live 应用路径；未确认 bar 不进正式历史资产 |
| 交易安全 | `auto_order=false` 始终成立 | 任何研究结果、展示或通知都不是交易指令 |

active 数据收口合同见 `docs/tasks/GY-DATA-CORE-V2.md`；当前实施与外部 Gate 见 `STATUS.md`。
