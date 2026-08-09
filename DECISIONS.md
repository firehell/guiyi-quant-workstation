# 架构决策记录

更新时间：2026-08-09

本文件只保留当前有效、长期影响代码或数据语义的决策。历史过程由 Git 与 OpenSpec archive 追溯。

| 主题 | 决策 | 边界 |
|---|---|---|
| 产品 | 本地、单用户国内期货研究工作站 | 不做自动交易、SaaS、多用户或无人值守下单 |
| 外部操作 | 正式数据/DB/Runtime/live/通知/release 只接受范围明确的一次性执行意图 | dry-run 不授权 mutation；唯一例外为已明确启用的 Market Runtime V1 有界持续自动化 |
| 数据源 | RQData 是唯一外部行情事实源 | 不建多 provider seam、插件或逐行多源裁决 |
| 历史存储 | 只长期保存一套 Canonical Parquet | staging 临时；PostgreSQL 不存 Bar |
| 数据身份 | `DatasetKey=(kind,symbol,series_or_contract,frequency)` | provider、schema 与来源属性不进入 identity |
| 主力数据 | 物理保存真实合约 Canonical，actual_dominant 查询时拼接 | 不长期保存重复的主力拼接 Parquet |
| 周期 | Direct 为 `1m/1d/1w`，Derived 为 `5m/15m/30m/60m` | Derived 只读同 Dataset Canonical 1m，不调 RQData |
| 分区 | 每 Dataset 每自然月一个 `part.parquet` | 只发布完整、可读的月；不保留 overlay/data version |
| 质量 | 固定执行 schema、identity、OHLCV、session/frequency、coverage、physical 六项校验 | 失败保留最后有效月；不建立第二套缺口状态 |
| Catalog | PostgreSQL 只保留八张 active 数据表 | 不保留合约参数、内容摘要、运行历史或通用 lineage |
| 查询 | MarketDataService 是唯一历史行情入口 | 消费者不得 glob、自选文件、自判主力或跨频回退 |
| 增量 | `--since` 是检查下界，`--through` 是固定水位 | 已发布 Parquet + Catalog 是唯一自然续传水位；同 T 完整重跑零请求零写入 |
| 修复 | `refresh` 重建指定品种/日期范围内相交月份的完整数据族 | 不接受精确计划文件或逐行裁决 |
| 额度 | 明确的 provider quota 耗尽立即停止本轮 | 保留已发布月，未完成月不发布；下次同命令从首个缺失目标续传 |
| live | historical Canonical 与 Redis Live Observation 分离 | 仅 `operational_products` 当日 rank1 completed 1m；未确认 bar 不进正式历史资产，Live 不进 Parquet/DB |
| Market Runtime V1 授权 | 明确启用一次本地 Market Runtime V1 后，允许 `j/jm/ap/ag` 的 Live 观察和每日 17:00 + 一次 1h retry 的盘后更新持续运行 | 新品种必须显式加入 `operational_products.txt`；不授权 main/tag/release、其他 DB mutation、真实外部通知或订单 |
| 交易安全 | `auto_order=false` 始终成立 | 任何研究结果、展示或通知都不是交易指令 |
| active universe | 60 品种；退役含股指 `ic/if/ih/im`、纸浆 `sp`、玉米淀粉 `cs`、丁二烯橡胶 `br`、20号胶 `nr`、低硫燃料油 `lu` | 退役码精确硬拦截；生产清退另需单次意图 |

active 数据收口合同见 `docs/tasks/GY-DATA-CORE-V2.md`；品种退役合同见
`docs/tasks/GY-DATA-PRODUCT-RETIREMENT-5.md`；当前实施与外部操作状态见 `STATUS.md`。
