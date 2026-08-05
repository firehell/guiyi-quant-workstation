# 归一量化项目事实源

## 定位

归一量化是本地运行、单用户使用的国内期货量化研究工作站。它支持数据治理、K 线与指标、策略研究、历史回测、报告、复盘、信号观察与前向验证。

项目不是 SaaS、不是无人值守自动交易机器人、不连接实盘账户自动下单，也不把预警或回测结论表达成交易指令。

## 个人开发与执行边界

`develop` 是日常开发分支。普通源码、测试、普通配置、研究实验与文档可以直接在 `develop` 编辑、按影响范围本地验证、提交并推送。Issue、任务分支/worktree、PR、独立 Review、required CI、exact-head、merge readback、approval packet/hash 和 receipt 均不是普通工作的前置条件；自愿使用时只作为可选协作工具。本地必要验证是完成声明依据，CI 仅作补充，且所有工作必须保留无关 dirty changes。

Git 跟踪的过期源码、测试、工程流程、hook/rule/workflow、ADR 和文档属于普通仓库删除：同一变更关闭 active references，以 Git history 恢复，不创建备份、rollback tag、packet 或 receipt。生产 DB、正式市场数据、仓库外文件、Runtime state、远端 refs、Git history、live 配置、真实通知和 GitHub rules 的真实 mutation 属于受控外部操作。

受控外部操作只接受用户在执行前给出的一个范围明确、单次使用的请求。该请求必须标识操作类别、目标环境/资源和边界，只授权紧随其后的一次匹配尝试；成功、失败、重试、scope 变化或跨会话继续都需要新请求。dry-run、旧审批材料和历史执行记录不授权 mutation。数据质量、安全、default-off 与 no-order 约束不能被任何执行意图覆盖。

## Active target 与数据边界

当前长期活动品种池固定为 69 个，唯一文件为 `data/universe/active_products.txt`。21 个退役品种及精确业务边界见 `docs/tasks/GY-DATA-PRODUCT-RETIREMENT-21.md`；它们在入口层不得重新下载、读取、聚合、注册或重建。未来对生产 DB、正式数据或仓库外工件执行不可逆清理时，必须由一次新请求明确列出操作类别与精确删除范围。

```text
RQData
-> temporary staging
-> schema/session/duplicate/OHLCV/coverage validation
-> one historical canonical Parquet root
   (provider-direct 1m/1d/1w + persisted preaggregated 5m/15m/30m/60m)
-> PostgreSQL Catalog / Manifest / Gap / MainContractMap
-> MarketDataService
-> Market / Web / Indicator / Backtest / Signal / Review
```

这是已冻结的目标，不表示迁移或消费者切换已经完成。目标数据身份使用不可歧义的 `DatasetKey`；`continuous` 与 `actual_dominant` 必须由消费者显式声明，禁止静默互换。正式历史周期永久固定为 `1m/5m/15m/30m/60m/1d/1w`。`1m/1d/1w` 的来源角色为 `provider_direct`，`5m/15m/30m/60m` 的来源角色为 `preaggregated_from_1m`；七者都是可持久化、可查询的 Canonical DatasetKey。历史读取只查请求同频的 Catalog/partition，缺失时返回 DataGap，不从其他周期动态聚合或回退。`actual_dominant 1w` 按该周最后交易日的 `MainContractMap.rank=1` 选择具体合约。

迁移期间既有 Profile/ActiveBinding/复杂 lineage 只作为 legacy compatibility。旧 `GY-CORE-02` Facade 与 `GY-CORE-03` CLI 壳允许复用，但不得继续扩展旧 active selector；旧 `GY-CORE-04～08` 路线已 superseded/paused。迁移顺序与业务约束见 `docs/tasks/GY-DATA-CORE-V2.md`。

legacy compatibility 数据入口仍必须满足：

```text
provider in ("rqdata", "local_parquet")
data_role = "primary"
quality_status != "failed"
```

严格研究、正式回测与正式信号默认使用 `quality_status=passed`。`validation`、`legacy_reference`、`candidate`、旧 TqSdk/天勤与来源不明数据不得进入默认 active 链路。

historical canonical 与 live observation 分离。live 只能用于观察、confirmed bar 聚合、前向判断和盘后核对，不能复制或晋升为 historical canonical；EOD 必须重新获取 RQData provider-final 数据，并在发布前校验 identity、coverage、Manifest digest、checksum 和 row count。staging 或 canonical 校验失败时保留最后有效 canonical 并显式暴露失败。

V2 迁移只迁移 trusted historical bars 与最小 Catalog/Manifest/Gap/MainContractMap metadata。旧 indicator/cache、Backtest、Signal/Review、live/EOD/Sample、永久 derived period、重复 raw/standard/canonical bar layer，以及 Profile/Binding/legacy lineage 都是 rebuild-only 或 compatibility-only，不是新的 active migration asset。report 14/15 是可由 Git 追溯的历史快照，不作为 active authorization 或回归基线。Task 07 Stage C 只验收当前 JM 目标 Canonical 并生成精确缺口计划；Runtime promotion 属于 Task 08；旧派生数据删除是后续独立可选任务，不是 Task 07 完成条件。

## 策略、回测、信号与运行边界

- 策略、回测和正式历史信号禁止未来数据泄漏、look-ahead bias 与未记录重绘；交易相关数值使用 `Decimal`。
- 回测结果保留策略、参数、数据、订单、trade、equity 与 lineage，以支持复算；历史报告不因新结果被覆盖。
- HTDY original 只允许 `docs/INDICATOR_KERNEL.md` 和 `docs/SIGNAL_EVENTS.md` 定义的 realtime first-seen observation-only 语义。
- 信号链路固定为 `Strategy -> SignalEvent -> Notification Gate -> Channel`。信号、回测和通知均是研究观察，不是交易指令。
- live、Runtime promotion/switch、真实通知和企业微信 autosend 默认关闭；缺失、异常、过期或不一致的配置保持关闭。repair/replay/backfill/migration/EOD recalculation 不补发历史通知。
- 所有信号与 Runtime 模式保持 `auto_order=false`；任何订单创建或提交请求都必须拒绝。

## 模块责任

| 文件 | 职责 |
|---|---|
| `AGENTS.md` | 唯一开发执行规则、个人工作流与风险边界 |
| `STATUS.md` | 当前阶段、未完成事项、必要锚点与执行边界 |
| `DECISIONS.md` | 长期架构、数据、回测、工作流与运行决策 |
| `TESTING.md` | 当前可执行的本地验证入口 |
| `docs/DEVELOPMENT.md` | direct-`develop` 工作流、影响匹配验证与外部操作边界 |
| `docs/PERSONAL_DEVELOPMENT_WORKFLOW.md` | 个人开发 canonical 流程与 Git 恢复方式 |
| `docs/DATA_CENTER.md` | 数据资产、quality、profile 与 lineage |
| `docs/ARCHITECTURE.md` | 运行架构与组件边界 |
| `docs/BACKTEST_ENGINE.md` | 回测口径与可复算要求 |
| `docs/SIGNAL_EVENTS.md` | SignalEvent、通知与观察边界 |
| `docs/INDICATOR_KERNEL.md` | 指标版本、契约与 HTDY policy |
| `docs/tasks/GY-DATA-CORE-V2.md` | 数据核心 V2 active 业务合同与任务顺序 |

`docs/tasks/` 可以包含 active business contract、historical fact、仍被 Runtime 消费的 frozen 文件或已 superseded 的历史来源。旧 PR、Review、CI、hash、packet 和 receipt 描述仅保留事实含义或由 Git history 追溯，不构成当前开发或执行授权。删除仓库内历史文件时关闭 active references；删除正式数据或其他仓库外资源时使用精确范围的一次性执行意图。

## 不做事项

- 自动交易、自动生成或发送订单。
- 将企业微信提醒表达为买卖指令。
- 用单次 smoke、数据文件存在、历史 replay、release 或通知结果冒充长稳、数据可信、live-confirmed、盈利或生产就绪结论。
- 将可信回测或数据质量结论扩写为策略盈利、稳定或实盘准入。
- 在代码、文档、测试、配置、日志或外部错误中保存或暴露 webhook、token、密码、cookie、license、私钥或账号信息。