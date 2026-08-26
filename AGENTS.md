# 归一量化执行规则

本文件只定义工程执行授权、受控外部操作、安全规则和不可破坏的工程边界。当前 release、Runtime、Scope、evidence 与 pending Gate 见 `STATUS.md`；稳定产品面见 `PROJECT_SOURCE.md`；active 依赖见 `docs/ARCHITECTURE.md`；业务语义见对应 deep canonical。

## 执行授权

- 用户本轮请求决定任务目标与授权范围；代码、测试和真实 evidence 决定实现事实；accepted canonical 与 ADR 决定长期约束；当前阶段状态以 `STATUS.md` 为准。发生冲突时必须指出，涉及数据、策略、发布、Runtime 或真实通知时 fail-closed。
- 开始任务先检查 branch、worktree、dirty state、最近提交、相关实现与测试。保留并避开用户或其他任务的修改，不批量清理、覆盖、回滚或全量暂存无关内容。
- `develop` 是日常集成分支。普通源码、测试、文档、仓库内普通删除、commit 与 push 可按任务范围执行；branch、worktree、PR、Review 与 CI 是协作工具，不授予外部操作权限。用户要求 Plan-only、只读或先审计时不得修改。
- 普通仓库删除必须同时关闭 active references，并按影响运行验证；恢复只使用 Git history，不创建仓库内 archive、backup、legacy、rollback copy、packet 或 receipt。
- 数据或指标语义变化时同步更新对应 deep canonical；阶段事实只写 `STATUS.md`，稳定产品边界只写 `PROJECT_SOURCE.md`，长期决策只写 `DECISIONS.md`，依赖关系只写 `docs/ARCHITECTURE.md`，命令只写 `TESTING.md`。
- 必须区分 `CODE_COMPLETE`、`TEST_COMPLETE`、`EXTERNAL_GATE_PENDING`、`RELEASED` 与 `RUNTIME_READY`。只有真实命令输出或运行证据才能支持完成声明。

## 受控外部操作

以下操作必须在首次 mutation 前取得目标、环境和范围明确的单次执行意图：

- 真实 RQData 下载或写入；
- Canonical/primary 数据的覆盖、迁移或删除；
- production PostgreSQL、Redis、Scope 或仓库外数据的写入/删除；
- Runtime/live enable、switch、promotion 或生产 acknowledgment；
- 真实通知；
- main merge、tag、release、Git 历史重写、force update 或 GitHub rules 修改。

单次意图只授权紧随其后的一次匹配尝试；范围变化、重试、失败后继续、跨会话继续都需要新的明确请求。dry-run、测试、read-only health、配置存在、历史授权、commit hash、approval packet 或第二次确认都不能替代执行意图，也不能把 dry-run 转换为真实 mutation 权限。

执行意图不能绕过输入校验、数据质量、覆盖与物理可读性、未来函数防护、密钥保护、默认关闭或无订单边界。普通 `develop` commit/push 和仓库内普通删除不属于受控外部操作；合入 `develop` 也不等于 release、main 或 Runtime promotion。

## 持续 Runtime 授权边界

### Market Runtime V1

代码与 launchd 模板默认关闭。只有用户对识别出的本地工作站明确请求启用并实际执行后，持续授权才限于：

- 只对 `operational_products.txt` 订阅当日 rank1 completed 1m；
- 每日 18:05 及最多一次一小时后 retry，只对同一集合运行 `HistoricalDataManager.update`。

该授权不覆盖其他生产数据/DB、main/tag/release、Runtime 版本切换、Alert transport、真实业务通知或订单。盘后状态和 health 只用于观察；只有受监督的自然盘后业务失败可向 owner 发起最多一次 PushPlus 运维通知，且不用 Alert Rule、Topic、`AlertEvent`、DB、retry 或 fallback；`missed/stuck` 只进入 health。

### Alert Runtime V2

Alert Runtime 的授权与 Market Runtime 独立。代码、launchd 模板与 enable marker 默认关闭；只有用户对识别出的本地工作站明确请求启用并实际执行后，才形成不超出既有 Rule、Scope、audience 与 transport 的持续授权。唯一 active 组合为：

```text
htdy_original_15m × scope_product_frequencies × htdy_observers × pushplus-wechat-topic
+
subing_entry_signal_v1 × scope_products × owner × pushplus-wechat
```

- HTDY Scope 只能按 symbol × frequency；SuBing Scope 只能按 product。两种 authority 不混用、不合并。
- HTDY 最多发起一次 Topic 请求，Topic 成员由 PushPlus 外部人工管理且不超过 owner + 三位朋友；SuBing 不传 Topic。系统不读取成员清单，不声明精确送达人数。
- Git 外通知配置只含 message token 与 HTDY Topic code；parent 必须为当前用户所有的 `0700` 目录，file 必须为当前用户所有的 `0600` 普通文件。结构 health 不联网、不发送。
- `alert_rules` 与 `alert_events` 是独立 Application Domain。Event 先提交，再最多调用一次 transport；无逐收件人状态、retry、queue、replay、backfill、fallback 或订单。
- HTDY 日内五周期只消费同周期 completed Live Bar；D1/W1 只响应 `market:state(reason=canonical_updated)` 并读取 Canonical，不新增 scheduler、Scope 表或 Live 日/周聚合。
- Redis `alert:runtime-status` 只承载无 TTL observation，兼容读 schema v1 并规范化为 v2；missing 只表示 `unobserved`。状态只保存固定公开错误分类，不保存 provider reference。notification acknowledgment 必须精确匹配当前 failure timestamp 做一次 CAS；保留原失败、公开分类与计数，不重放、不补发。同一 timestamp 在内的任何新 failure 都必须原子清空 acknowledgment；状态写失败或并发变化时 fail-closed。
- provider accepted 只表示请求被接受，不表示微信送达。代码、测试、配置或历史 canary 不授权真实 send、Scope 变更或 Runtime switch。

## 安全规则

1. 外部输入在敏感操作前校验类型、格式、范围、允许值与关联字段。系统命令使用固定 executable 与离散参数，SQL 使用参数绑定或既有 ORM；输入派生路径规范化后必须仍在允许根目录内。
2. 禁止读取、显示、提交或记录凭据；不修改 `.env`，不在代码、文档、测试、日志或错误输出中暴露 webhook、token、密码、cookie、license、私钥、内部地址、SQL 或 stack trace。认证、质量配置或安全开关缺失/异常时 fail-closed。
3. 删除、迁移或覆盖前先只读解析精确目标、消费者、影响和恢复方式；不得使用宽泛路径、未解析变量或破坏性 Git 命令。
4. 不连接 RQData、production PostgreSQL 或 Redis，不发送通知，不切换 Runtime，除非本轮明确授权且范围校验通过。
5. `auto_order=false` 适用于所有研究与 Runtime；任何创建或提交真实订单的路径必须拒绝。

## 工程硬约束

1. 唯一 Historical 数据链为 `RQData -> staging + hard validation -> Canonical Parquet -> 八表 Catalog + MainContractMap -> MarketDataService`。不得删除或绕过 `MarketDataService`、`DatasetKey`、Calendar、Session、`MainContractMap`、Canonical 或 Catalog。
2. 物理 Dataset 只有 `continuous` 与 `contract`；`actual_dominant` 只能通过 rank1 有效区间拼接。consumer 不得 glob、自选 active、自判主力、绕过质量或跨频回退。
3. `active_products.txt` 定义研究能力，`operational_products.txt` 定义持续 Runtime 授权；即使当前内容相同也不得合并。
4. Historical Canonical 与 Live observation 必须隔离。未确认 Bar 只能用于 preview；Live 不得直接晋升 Canonical。
5. RQData 必须先进入 staging，通过 schema/session/duplicate/OHLCV/coverage、identity、row-count 与物理可读性校验后再原子发布；失败保留最后有效 Canonical。
6. 映射、分区、coverage 或物理完整性异常必须显式失败，不得静默填充、缩短、替换或另建第二套缺口事实。
7. 策略与研究必须保护 causality、strict-before、future-leak、prefix invariance、golden parity、fail-closed、warm-up、合约切换、成交时序和 OOS/Walk-forward 边界。交易相关价格、成本、仓位、资金、盈亏和费用使用 `Decimal`。
8. JDJ 1m reference replay 与 SuBing 15m Historical Strategy Projection 保持 source-specific、deterministic、read-only，只输出模拟动作/参考变动。不得创建 UniversalStrategyAdapter、统一 Opportunity 模型、通用策略平台、正式回测 worker/queue、账户或订单域。
9. SuBing Strategy 普通动作只在下一根同物理合约 15m open 生效；退出只认 accepted policy 的四类来源；不加减仓、不反手、不跨物理段、不在同 Bar 重建仓。任何公式变化必须新版本，不能以文档收敛修改策略语义。
10. Alert 不属于八表 Market Catalog。HTDY 与 SuBing 的 Rule、Scope、current-event cutoff 和 audience boundary 保持分离；repair、replay、backfill、migration 或 EOD recalculation 不补评、不补发历史通知。SuBing 只在 incoming completed Bar 与 current snapshot 的 `bar_end + trading_day` 同边界时继续，stale fail-closed；final Session Bar 只在共享 Live arrival grace 内可见，5m 在同一 15m boundary 按 TradingSession bucket 延后。current trading day 只通过 `MarketPhaseResolver + operational_products.txt` 解析，不可用时 fail-closed。
11. causality、strict-before、prefix-invariance、future-leak、golden parity 与 fail-closed 测试不得删除。Alembic chain 只允许审计；除非新任务明确要求并授权，不修改 migration。

## 验证与交付

- 按改动风险先运行定向测试，再扩展到模块测试、lint、typecheck、build、CLI/API/browser smoke；纯文档运行引用、OpenSpec、secret scan 与 diff 检查。
- 必要验证失败时只报告失败，不声明完成；不能运行的检查说明阻塞原因。
- 交付时说明状态、改动范围、实际命令与结果、未完成 Gate、风险和唯一最小下一步。
