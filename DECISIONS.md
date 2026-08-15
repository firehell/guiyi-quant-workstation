# 架构决策记录

更新时间：2026-08-14

本文件只保留当前有效、长期影响代码或数据语义的决策。历史过程由 Git 与 OpenSpec archive 追溯。

| 主题 | 决策 | 边界 |
|---|---|---|
| 产品 | 本地、单用户国内期货研究工作站 | 不做自动交易、SaaS、多用户或无人值守下单 |
| 外部操作 | 正式数据/DB/Runtime/live/通知/release 只接受范围明确的一次性执行意图 | dry-run 不授权 mutation；仅已明确启用的 Market Runtime V1 与精确 activation 的 Alert Runtime V2 Rule Scope 各自拥有互不继承的有界持续授权 |
| 数据源 | RQData 是唯一外部行情事实源 | 不建多 provider seam、插件或逐行多源裁决 |
| 历史存储 | 只长期保存一套 Canonical Parquet | staging 临时；PostgreSQL 不存 Bar |
| 数据身份 | `DatasetKey=(kind,symbol,series_or_contract,frequency)` | provider、schema 与来源属性不进入 identity |
| 主力数据 | 物理保存真实合约 Canonical，actual_dominant 查询时拼接 | 不长期保存重复的主力拼接 Parquet |
| 周期 | Provider 基础周期为 `1m/1d`；`1w` 由完整同源 `1d` 聚合，`5m/15m/30m/60m` 由 Canonical `1m` 聚合 | 派生周期只读同 Dataset Canonical，不调 RQData |
| 分区 | 每 Dataset 每自然月一个 `part.parquet` | 只发布完整、可读的月；不保留 overlay/data version |
| 质量 | 固定执行 schema、identity、OHLCV、session/frequency、coverage、physical 六项校验 | 失败保留最后有效月；不建立第二套缺口状态 |
| Market Catalog | Data Foundation / Market Catalog 精确保留八张 active 数据表 | 不保留合约参数、内容摘要、运行历史或通用 lineage；明确设计的非 Market Foundation Application Domain 表不计入八表 |
| Data Foundation Frozen | 新功能不得修改 `DatasetKey`、八表 Catalog、Canonical 语义或每 Dataset 每自然月一个 `part.parquet` 的月分区模型 | 如需改变基础合同，必须先作为独立架构决策；不得借新功能重构 |
| 查询 | MarketDataService 是唯一历史行情入口 | 消费者不得 glob、自选文件、自判主力或跨频回退 |
| 研究读模型 | 新研究功能只通过 `MarketDataService` 消费历史行情；可由 Canonical 与现有 Catalog 推导的市场事实按需计算 | 不得直接读 Parquet、复制 resolver 或为派生市场事实扩展 Catalog；明确设计的应用事实可进入独立 Application Domain |
| 增量 | `--since` 是检查下界，`--through` 是固定水位 | 已发布 Parquet + Catalog 是唯一自然续传水位；同 T 完整重跑零请求零写入 |
| 修复 | `refresh` 重建指定品种/日期范围内相交月份的完整数据族 | 不接受精确计划文件或逐行裁决 |
| 额度 | 明确的 provider quota 耗尽立即停止本轮 | 保留已发布月，未完成月不发布；下次同命令从首个缺失目标续传 |
| live | historical Canonical 与 Redis Live Observation 分离 | 仅 `operational_products` 当日 rank1 completed 1m；未确认 bar 不进正式历史资产，Live 不进 Parquet/DB |
| 模块长期性 | 新增模块前必须确认个人使用是否值得长期维护 | 无明确肯定答案时不创建模块 |
| Market Runtime V1 授权 | 明确启用一次本地 Market Runtime V1 后，允许 `operational_products.txt` 中 active 60 的 Live 观察和每日 18:05 + 一次 1h retry 的盘后更新持续运行 | 范围变化必须显式修改同一配置；不授权 main/tag/release、其他 DB mutation、真实外部通知或订单 |
| Alert V2 应用 | 独立 Application Domain 的 Code Registry 只含 `htdy_original_15m` 与 `subing_entry_signal_v1`；两张应用表记录 Scope 与不可变 Event | 不修改八表 Catalog/Canonical/rank1；SuBing seed Scope 为空；不恢复 Signal/Review/Strategy，不 replay/backfill/retry/outbox/queue，不建订单路径 |
| Alert V2 评估语义 | HTDY 保持 event-cutoff；SuBing 只复用 Factor/accepted Calibration/FormalPolicy/`SubingReadService` resolver，stale identity fail-closed，final Session Bar 只使用共享 arrival grace，5m/15m 同边界使用 TradingSession bucket | 不复制 SuBing 公式/resolver，不建 `snapshot_at`/cutoff/replay 语义；current trading day 只由 `MarketPhaseResolver + operational products` 唯一解析，不可用时 fail-closed |
| Alert Runtime V2 授权 | 仅 `htdy_original_15m × 该 Rule 显式 scope_products × WeCom` 与 `subing_entry_signal_v1 × 该 Rule 显式 scope_products × WeCom` 可在精确 activation 后持续处理后续自然事件 | 未来第三条 Rule 不继承；与 Market Runtime 授权独立；production migration、v1.3 release/tag、Runtime promotion/switch、Scope write/activation 与真实 WeCom/canary 互不授权 |
| 开发态部署拓扑 | 功能开发期可让本地 launchd 临时直接运行主 `develop` 工作区；最终验收重新创建绑定精确提交的独立 Runtime worktree | 不热更新；每次重载需新的一次性意图；develop 证据不等于 promotion 或最终 Runtime 证据 |
| 工程验证 | `TESTING.md` 的项目原生命令是唯一验证入口；工程脚本只保留无依赖的 `secret_scan.py` | 不保留自验证治理框架、重复流程文档、废弃构建包装或可选 CI 双轨 |
| 运维拓扑 | Mac launchd → FRPC → 腾讯云 FRPS/Nginx 是唯一 active 链；local/tunnel/public 分段检查均只读 | 不保留并行 PID 管理器或远端应用副本；安装、重载与云端配置应用仍是独立 Gate |
| 交易安全 | `auto_order=false` 始终成立 | 任何研究结果、展示或通知都不是交易指令 |
| active universe | 60 品种；退役含股指 `ic/if/ih/im`、纸浆 `sp`、玉米淀粉 `cs`、丁二烯橡胶 `br`、20号胶 `nr`、低硫燃料油 `lu` | 退役码精确硬拦截；生产清退另需单次意图 |
| 品种展示 taxonomy | `product_sectors.csv` 覆盖 active 60 的展示名称与板块，由 Market API 在 dominants 中返回 | Web 只保留板块标签，不复制品种名称/板块映射；未知板块只降级到 `other` |

active 数据、查询与退役硬拒绝合同见 `openspec/specs/`；当前实施与外部操作状态见 `STATUS.md`。
