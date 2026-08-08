# 归一量化项目事实源

## Current surface vs long-term boundary

- **Current surface**：Market Web + Canonical 历史读 + `data`/`runtime` API/CLI；无 Signal/Review/Strategy Web，无 signal worker，无盘中 Live，无 backtest 子系统。
- **Long-term boundary**：数据治理、K 线与指标、策略研究、复盘、信号观察与前向验证；未来可按新任务重建历史回测。下文章节若写「支持」，未特别标明 current surface 时指长期边界。

## 定位

归一量化是本地运行、单用户使用的国内期货量化研究工作站。长期边界覆盖数据治理、K 线与指标、策略研究、复盘、信号观察与前向验证。历史回测将来可以重建，但当前没有可用的 backtest 子系统或兼容入口。

项目不是 SaaS、不是无人值守自动交易机器人、不连接实盘账户自动下单，也不把预警或回测结论表达成交易指令。

## 个人开发与执行边界

日常在 `develop` 上编辑、按影响本地验证、可选 commit/push。协作门禁与可选工具边界见
`AGENTS.md`「个人开发工作流」与 `DECISIONS.md`「个人开发」。本地必要验证是完成声明依据；须保留
无关 dirty changes。

普通仓库删除：关闭 active references，以 Git history 恢复。生产 DB、正式市场数据、仓库外文件、
Runtime state、远端 refs、Git history、live 配置、真实通知和 GitHub rules 的真实 mutation 属于
受控外部操作，细则见 `AGENTS.md`「受控外部操作」。

受控外部操作只接受范围明确、单次使用的用户请求；dry-run 与历史材料不授权 mutation。数据质量、
安全、default-off 与 no-order 约束不能被任何执行意图覆盖。

## Active target 与数据边界

当前长期活动品种池固定为 69 个，唯一文件为 `data/universe/active_products.txt`。21 个退役品种由 `app.data_core.product_retirement` 精确冻结，当前执行事实见 `STATUS.md` 与 `docs/DATA_CENTER.md`；它们在入口层不得重新下载、读取、聚合、注册或重建。未来对生产 DB、正式数据或仓库外工件执行不可逆清理时，必须由一次新请求明确列出操作类别与精确删除范围。

```text
RQData
-> temporary staging
-> schema/session/duplicate/OHLCV/coverage validation
-> one historical canonical Parquet root
   (provider-direct 1m/1d/1w + persisted preaggregated 5m/15m/30m/60m)
-> PostgreSQL Catalog / Manifest / Gap / MainContractMap
-> MarketDataService
-> Market Web / Indicator display / data+runtime API/CLI
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

historical canonical 与 live observation 分离。**当前无盘中 Live 应用路径**；未来重建 live 时只能用于观察、confirmed bar 聚合、前向判断和盘后核对，不能复制或晋升为 historical canonical；EOD 必须重新获取 RQData provider-final 数据，并在发布前校验 identity、coverage、Manifest digest、checksum 和 row count。staging 或 canonical 校验失败时保留最后有效 canonical 并显式暴露失败。

V2 迁移只迁移 trusted historical bars 与最小 Catalog/Manifest/Gap/MainContractMap metadata。旧 indicator/cache、Backtest、Signal/Review、live/EOD/Sample、永久 derived period、重复 raw/standard/canonical bar layer，以及 Profile/Binding/legacy lineage 都不是新的 active migration asset。旧 backtest 与其 report/OOS evidence 已退出仓库，不保留 compatibility；历史事实仅由 Git 追溯。Task 07 Stage C 只验收当前 JM 目标 Canonical 并生成精确缺口计划；Runtime promotion 属于 Task 08；旧派生数据删除是后续独立可选任务，不是 Task 07 完成条件。

## 策略、信号与运行边界

- 策略研究、未来重建的回测和正式历史信号禁止未来数据泄漏、look-ahead bias 与未记录重绘；交易相关数值使用 `Decimal`。
- 当前仓库不提供 `/api/backtests/**`、`/ws/backtests/**`、backtest Web 页面、worker/queue、CLI 或报告兼容入口。未来回测必须是基于 Canonical/MarketDataService 的新任务，并重新定义可复算的策略、参数、数据、订单、trade、equity 与 lineage 合同。
- HTDY original 的 realtime first-seen observation-only 白名单见 `docs/INDICATOR_KERNEL.md` / `docs/SIGNAL_EVENTS.md`；**盘中 realtime 应用路径已退役**，仅作合同归档。
- 信号链路语义固定为 `Strategy -> SignalEvent -> Notification Gate -> Channel`。当前无 mounted signal/review surface；信号与通知均是研究观察，不是交易指令。
- live、Runtime promotion/switch、真实通知和企业微信 autosend 默认关闭；缺失、异常、过期或不一致的配置保持关闭。repair/replay/backfill/migration/EOD recalculation 不补发历史通知。
- 所有信号与 Runtime 模式保持 `auto_order=false`；任何订单创建或提交请求都必须拒绝。

## 模块责任

| 文件 | 职责 |
|---|---|
| `AGENTS.md` | 唯一开发执行规则、个人工作流与风险边界 |
| `STATUS.md` | 当前阶段、未完成事项、必要锚点与执行边界 |
| `DECISIONS.md` | 长期架构、数据、工作流与运行决策 |
| `TESTING.md` | 当前可执行的本地验证入口 |
| `docs/DEVELOPMENT.md` | direct-`develop` 工作流、影响匹配验证与外部操作边界 |
| `docs/PERSONAL_DEVELOPMENT_WORKFLOW.md` | 个人开发 canonical 流程与 Git 恢复方式 |
| `docs/DATA_CENTER.md` | 数据资产、quality、profile 与 lineage |
| `docs/ARCHITECTURE.md` | 运行架构与组件边界 |
| `docs/SIGNAL_EVENTS.md` | SignalEvent、通知与观察边界（语义合同） |
| `docs/INDICATOR_KERNEL.md` | 指标版本、契约与 HTDY policy |
| `docs/tasks/GY-DATA-CORE-V2.md` | 数据核心 V2 active 业务合同与任务顺序 |

`docs/tasks/` 可以包含 active business contract、historical fact、仍被 Runtime 消费的 frozen 文件或已 superseded 的历史来源。历史协作材料只保留事实含义或由 Git history 追溯，不构成当前授权（见 `AGENTS.md` / `DECISIONS.md`）。删除仓库内历史文件时关闭 active references；删除正式数据或其他仓库外资源时使用精确范围的一次性执行意图。

## 不做事项

- 自动交易、自动生成或发送订单。
- 将企业微信提醒表达为买卖指令。
- 用单次 smoke、数据文件存在、历史 replay、release 或通知结果冒充长稳、数据可信、live-confirmed、盈利或生产就绪结论。
- 将可信回测或数据质量结论扩写为策略盈利、稳定或实盘准入。
- 在代码、文档、测试、配置、日志或外部错误中保存或暴露 webhook、token、密码、cookie、license、私钥或账号信息。
