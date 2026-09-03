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

Alert Runtime 的授权与 Market Runtime 独立。代码、launchd 模板与 enable marker 默认关闭；只有用户对识别出的本地工作站明确请求启用并实际执行后，才形成不超出既有 Rule、Scope、audience 与 transport 的持续授权。post-0044 稳定代码组合为同一 `single Alert Runtime` 内两条 observation Rule：

```text
htdy_original_15m × first_seen × scope_product_frequencies × htdy_observers
subing_ths_alert_15m_v1 × exact × completed actual_dominant 15m × htdy_observers
→ shared one-shot pushplus-wechat-topic transport
```

Migration `20260902_0043` forward-only 删除全部已退役策略 Event、Rule 与专用列，只保留 HTDY Rule/Event 事实；`20260902_0044` 只从该精确状态增加 disabled、empty-scope 的新 SuBing Rule，不启用或填充生产 Scope；`20260903_0045` 只把既有 RQData 1m session 首根标签规范化为 `(start, end]` 的排他边界。不得建立 archive、兼容 reader、replay 或 downgrade。当前 release、production migration、Runtime 与 enable 状态只以 `STATUS.md` 为准；任何一次状态变化都不能替代下一项受控操作的明确授权。

- HTDY Scope 只能按 symbol × frequency。
- SuBing 固定身份为 `subing_ths_alert_15m_v1` / `subing_ths_15m_v3`，只观察 completed `actual_dominant` 15m；公式为 MACD(12,26,9) CROSS + `EMA(CLOSE, 21)`，不得增加零轴、Range、量能/OI、ATR、斜率或多周期隐藏过滤。v3 不改变数学公式，只冻结修正 session 锚点后的正式输入 Bar、时间与 Candidate。
- HTDY Event mode 为 forward-only `first_seen`；SuBing Event mode 为同一 Bar 事实一致才幂等的 `exact`。二者都必须 Event 先提交，再最多一次 transport；不得用其中一种去弱化另一种。
- 通用 Scope API 必须拒绝 disabled Rule 的写入。SuBing 第一次启用只允许走专用原子 activation seam：dry-run 只读，apply 在精确 0045、两 Rule、SuBing disabled + empty scope 的 preflight 后锁定、一次提交并 readback；production apply 仍需单次明确授权。
- 外部执行顺序必须先完成 Canonical 锚点修复与 exact-tag Runtime readback，再重新完成 `G10` 只读同花顺兼容性 evidence，最后才可执行 `G9` production Scope activation + Rule enable；G10 不授权 PushPlus、Rule enable、Scope、Runtime 或其他 mutation。
- HTDY 最多发起一次 Topic 请求，Topic 成员由 PushPlus 外部人工管理且不超过 owner + 三位朋友。系统不读取成员清单，不声明精确送达人数。
- Git 外通知配置只含 message token 与 HTDY Topic code；parent 必须为当前用户所有的 `0700` 目录，file 必须为当前用户所有的 `0600` 普通文件。结构 health 不联网、不发送。
- `alert_rules` 与 `alert_events` 是独立 Application Domain。两条 Rule 均为研究观察；Event 先提交，再最多调用一次 transport；无逐收件人状态、retry、queue、replay、backfill、fallback 或订单。
- HTDY 日内五周期只消费同周期 completed Live Bar；D1/W1 只响应 `market:state(reason=canonical_updated)` 并读取 Canonical，不新增 scheduler、Scope 表或 Live 日/周聚合。
- HTDY 使用 forward-only first-seen observation 语义：已有同周期 completed Live / `canonical_updated` 触发只比较 previous/current prefix，历史重绘候选只限于 kernel repaint zone。`AlertEvent.bar_end` 是观察 Bar 时间，`detected_at` 是 Runtime 首次识别时间；Event 冻结后，重绘消失、重现或方向变化都不改写、不重发。startup、repair、replay、backfill 与 EOD recalculation 不创建历史 HTDY Event 或通知。
- `alert:runtime-status` 写 schema v6，只保留通用 Alert 状态与两条固定 Rule 各四个 bounded health 字段；兼容读取 v1-v5 时丢弃已退役策略字段并为空缺 Rule health 填充空状态。notification acknowledgment 必须精确匹配当前 failure timestamp 做一次 CAS；保留原失败、公开分类与计数，不重放、不补发。同一 timestamp 内的任何新 failure 都必须原子清空 acknowledgment；状态写失败或并发变化时 fail-closed。
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
8. 已退役策略域不得保留 active API、CLI、Web、Runtime、Alert Rule、Scope、派生 cache 或兼容 reader。未来新策略必须使用新身份、新合同与新版本，不能恢复或复用已退役实现。
9. EMA21 斜率只保留通用 10K primitive：恰好使用 10 个 EMA21 值，按首尾差除以 9 个 bar interval，再除以当前 EMA21 并换算为 bps/bar；不得恢复 5m/15m 正式因子或方向过滤。
10. Alert 不属于八表 Market Catalog。HTDY 使用 symbol × frequency Scope；SuBing 只使用 operational × 15m Scope；repair、replay、backfill、migration 或 EOD recalculation 不补评、不补发历史通知。
11. active 策略与指标的 causality、strict-before、prefix-invariance、future-leak、golden parity 与 fail-closed 测试不得删除；SuBing 还必须保留 exact CROSS、同物理合约 warm-up/rollover、completed-only 与无隐藏过滤测试。整体退役的实现及其专用测试应同步删除。已有 Alembic history 只作 lineage；新 migration 必须前向、可审计且真实 production 执行仍需独立授权。

## 验证与交付

- 按改动风险先运行定向测试，再扩展到模块测试、lint、typecheck、build、CLI/API/browser smoke；纯文档运行引用、OpenSpec、secret scan 与 diff 检查。
- 必要验证失败时只报告失败，不声明完成；不能运行的检查说明阻塞原因。
- 交付时说明状态、改动范围、实际命令与结果、未完成 Gate、风险和唯一最小下一步。
