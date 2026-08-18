# 归一量化 AGENTS.md

本文件是仓库唯一的开发执行规则。当前状态见 `STATUS.md`；长期产品边界见 `PROJECT_SOURCE.md`；业务语义见对应 deep canonical。

## 项目边界

- 做（长期）：数据治理、K 线、策略研究、复盘、信号提醒与人工观察；未来可按新任务重建历史回测。
- 当前可执行面：Web 为 Market 与独立 Execution Review；API/CLI 为 market / execution-review / data CLI / runtime，并包含独立 Alert Application Domain。Market Runtime V1 的仓库模板默认关闭；本地工作站已按明确请求启用由 `operational_products.txt` 界定范围的 Runtime。Alert Runtime 模板默认关闭，不能从 Market Runtime 授权推导启用。旧 signal/review/strategy Web·HTTP·worker 与 data_center HTTP 已退役；Execution Review 不是旧 Review Center 的恢复。
- 不做：自动交易、实盘下单、SaaS、多用户权限、手机 App、无人值守交易。
- 信号、通知和 Web 始终是研究观察，不是交易指令。

技术栈固定为 Vue 3/Vite/TypeScript/Naive UI、FastAPI/PostgreSQL/Redis 与
RQData → Canonical Parquet → 八表 Catalog → MarketDataService；`quant-core` 仅保留
Indicator Kernel（`guiyi_quant/indicators/`），旧 vn.py-compatible 策略研究包已退役（仅 Git
history 可追溯），当前不存在回测引擎、策略适配层或策略 HTTP/worker。Alert 的两张表与 Execution
Review 的四张表都是独立 Application Domain，不属于 Market Catalog，不改变八表合同。

## 项目辅助范围

项目辅助只服务当前 active 架构；已经退役的策略、回测、Signal/Review、账户与风控子系统不保留项目级 skill、reviewer、command 或 task template。每项任务默认主 agent，最多增加一个必要的 specialist 或 reviewer；不得把多个辅助角色串成固定流程。未来重新引入策略、回测或风险计算，必须先以新任务新合同定义其业务边界，再按需恢复辅助说明。

## 个人开发工作流

`develop` 是日常开发分支。普通仓库变更可以直接在当前 `develop` 工作区编辑、测试、提交并推送；不要求 GitHub Issue、任务分支、额外 worktree、PR、独立 Review、required CI、exact-head、merge readback、ancestry/cleanup evidence、approval packet、hash 或 receipt。分支、worktree、PR、Review 和 CI 可以按需使用，但只是协作工具，不是开发授权条件，也不授予任何真实外部操作权限。

当前功能开发期的本地 launchd 可临时直接绑定主 `develop` 工作区，以便快速观察。源码修改不会热更新：Web 需要 build 和重载，API/Live 需要重载；每次重载仍是 Runtime switch，需要当次范围明确的一次性执行意图。18:05 任务会读取当时的 `develop` 工作树，因此 dirty 或持续移动的树只能形成开发证据。功能收口后的最终拓扑采用绑定精确提交的独立 Runtime worktree，验收读回 clean/detached 身份、launchd 根、健康状态和受限范围；已经在同一代码谱系形成并由用户接受的自然时点证据不因部署封装重复采集，具体复用或豁免事实由 `STATUS.md` 记录。

开始前检查分支、工作区、最近提交、相关实现与测试。工作区存在其他任务或用户的未提交变更时，保留其内容与 index 状态，只修改、验证和暂存本任务明确范围；不得用批量清理、覆盖或全量暂存处理无关变更。

本地验证是普通变更完成声明的依据：

- 可执行行为按影响范围运行定向测试，并在需要时补充模块测试、lint、类型检查、构建和 CLI/API/browser smoke；
- 纯文档或非执行注释只运行适用的引用、格式和 diff 检查；
- 数据身份/质量、策略、回测、信号、migration、Runtime、live 或通知语义变化必须运行对应领域测试；
- 任一必要检查失败时，只报告失败，不声明完成；CI 若存在仅作补充。

普通仓库删除包括 Git 跟踪的源码、测试、普通配置、旧工程流程、hook/rule/CI、ADR 和过期文档。此类删除不需要协作门禁或额外执行意图，但必须在同一变更中关闭 active references 并运行受影响验证；恢复只使用 Git history，不创建备份目录、隔离副本、rollback tag、packet 或删除 receipt。

详细流程见 `docs/DEVELOPMENT.md`；当前可执行命令以 `TESTING.md` 为准。

## 受控外部操作

会改变仓库外真实状态或远端发布状态的操作是受控外部操作，包括：生产 DB 或正式数据的不可逆写入/删除、仓库外数据删除、远端 release/tag、Git 历史重写或 force update、Runtime/live 启用或切换、真实通知发送以及 GitHub rules 修改。普通源码修改、普通 `develop` commit/push 和仓库内普通删除不属于此类操作。

受控外部操作唯一的授权模型是用户在执行前给出的**范围明确、单次使用的执行意图**：请求必须能识别操作类别、目标环境/资源和操作边界，并只授权紧随其后的一次匹配尝试。缺少意图、范围不明、目标变化、超出范围、重试、执行成功或失败、跨会话继续时，都必须在第一次外部 mutation 前停止并取得新的明确请求。不得把 backup、rollback artifact、approval packet、content hash、exact-head、签名、receipt、dry-run approval 或第二次确认设为额外授权前置；dry-run 只授权 dry-run，不能转换或复用为真实 mutation 权限，意图也不落盘。

执行前仍须完成输入、身份、质量、覆盖和安全校验。业务正确性与安全边界优先于执行意图，任何请求都不能绕过失败的数据质量、分区覆盖/可读性、未来函数防护、密钥保护、默认关闭状态或无订单边界。执行结果只报告非敏感的尝试范围与观察到的成功、失败或阻止状态，不把结果扩写成盈利、长稳、交易或生产就绪。

### Market Runtime V1 的受限持续授权

代码与 launchd 模板默认关闭。只有用户对识别出的本地工作站明确请求“启用 Market Runtime V1”并实际执行一次启用操作后，才允许以下有界持续自动行为：只对 `operational_products.txt` 订阅当日 rank1 completed 1m；每日 18:05 及最多一次 1 小时后 retry 仅对同一品种集合运行正式 `HistoricalDataManager.update`。启用后的日常运行不需要逐日重新确认；显式修改 `operational_products.txt` 才改变该自动范围。

该授权不覆盖 main/tag/release、其他生产 DB/数据变更、Runtime 版本切换、真实外部通知渠道或任何订单；`auto_order=false` 始终不变。没有上述明确启用请求时，render-only、健康读取和测试不构成启用授权。

### Alert Runtime V2 的独立受限持续授权

Alert 代码与 launchd 模板默认关闭。Alert Runtime V2 的有界持续授权只限于：

```text
htdy_original_15m × 该 Rule 显式 scope_products × WeCom
+
subing_entry_signal_v1 × 该 Rule 显式 scope_products × WeCom
```

只有用户对识别出的本地工作站明确执行 V2 Runtime promotion，且目标 Scope 已获得精确 Rule + Product 授权后，才允许对该精确范围此后自然到达的完成 Bar 持续创建 Event 并尝试一次 WeCom。V2 migration 保留已明确授权的 HTDY Scope，不为其虚构第二次 Scope write；SuBing 仍必须独立执行精确 Scope activation。停机历史不 replay/backfill，发送失败不 retry。未来第三条 Rule 不继承授权。

该授权与 Market Runtime V1 相互独立，不覆盖新增 Rule 或通知渠道、生产 migration、任何 Runtime switch、
main/tag/release、Canonical 写入或订单。production migration、v1.3 release/tag、Runtime promotion/switch、SuBing Scope write/activation 和真实 WeCom/canary 都是独立的一次性 Gate；mock、测试、render-only 或其中一个 Gate 不授权其余 Gate。测试路由的 Scope PUT 不构成真实 Scope mutation 授权。

`develop` 的通知目标架构是 Clawbot single-shot：每个 committed Event 最多启动一个固定 Node child，
只允许唯一 `openclaw-weixin` private seam 调用一次 `sendMessageWeixin()`。Git 外的 owner 配置采用
`0700` parent / `0600` file，只保存固定别名 `owner` 与精确 account/target；缺失 context、超时、crash、
malformed output 或发送失败均 fail-closed，不 retry、queue、replay、backfill、fan-out 或 fallback。OpenClaw
与腾讯插件是已经存在的外部依赖，归一量化不安装、更新、登录、启动、停止或监督它们，也不引入
OpenClaw public message-send、durable queue、inbound、context monitor、Agent/LLM/slash/tool/reply 路径。
当前 production exact-tag Runtime 仍为 WeCom，直至未来独立 rollout、release 与 Runtime promotion 被
记录于 `STATUS.md`；develop 代码、fixture、render-only 和测试不授权 owner bootstrap、preflight、canary、
真实发送、OpenClaw 变更或 Runtime switch。

## 工程与业务硬规则

1. 外部输入在敏感操作前校验类型、格式、范围、允许值与关联字段；系统命令使用固定 executable 与离散参数，SQL 使用参数绑定或既有 ORM，输入派生路径规范化后必须仍在允许根目录内。
2. 禁止读取、显示、提交或记录凭据；不修改 `.env`，不在代码、文档、测试、日志或错误输出中暴露 webhook、token、密码、cookie、license、私钥、内部地址、SQL 或 stack trace。认证、质量配置或安全开关缺失/异常时 fail-closed。
3. V2 active target 由四字段 `DatasetKey + 八表 Catalog + MainContractMap + MarketDataService` 定义；消费者不得自行 glob、选择 active、判断主力或绕过完整性校验。物理 Dataset 只有 `continuous` 和 `contract`，`actual_dominant` 只是查询时拼接模式。明确设计的 Application Domain 可新增非 Market Foundation 表，但不得改变或冒充八表 Catalog。
5. historical canonical 与 live observation 分离。RQData 先进入 staging，完成 schema/session/duplicate/OHLCV/coverage、identity、row-count 与物理可读性校验后才能发布；月分区以同文件系统临时文件原子替换 `part.parquet`，失败时保留最后有效 canonical。live 不得直接提升为正式历史 active。
6. 映射、分区、coverage 或物理完整性异常必须显式失败，不得静默填充、缩短、替换或跨频回退；不得为此建立第二套缺口状态表。
7. 策略研究与未来重建的回测禁止未来函数、泄漏和未记录重绘；所有交易相关价格、成本、仓位、资金、盈亏和费用使用 `Decimal`。HTDY original 观察边界见 `docs/INDICATOR_KERNEL.md`（盘中 realtime 应用路径与 Signal/Review 合同已退役，仅 Git history 可追溯）。
8. 当前仓库不提供 backtest API/Web/worker/queue/CLI 或报告兼容入口。未来回测必须作为新任务基于 Canonical/MarketDataService 重建，并保留策略、参数、数据、订单、trade、equity 与 lineage 以支持复算。旧 Signal/Review/Strategy HTTP·worker·DB 表与旧语义合同已退役；Alert 与 Execution Review 是独立 Application Domain，不以旧表或旧 worker 为入口。Execution Review 业务语义只看 `docs/EXECUTION_REVIEW.md`；未来其他重建仍须新任务新合同。
9. live、Runtime promotion/switch、真实通知与微信 autosend 默认关闭；配置缺失、异常、过期或不一致时保持关闭。Market Runtime V1 的 Redis Live Overlay 与盘后 runner 只读取同一个 `operational_products.txt`，且不新增生产表。Alert V2 的 HTDY 保持 event-cutoff；SuBing 只复用已有 Factor/accepted Calibration/FormalPolicy/`SubingReadService` resolver，不复制公式或 same-boundary 规则。SuBing 仅在 incoming Bar 与 current snapshot 的 `bar_end + trading_day` 同一时继续，stale 必须 fail-closed；final Session Bar 只在共享 Live arrival grace 内可见，5m 在同一 15m boundary 按 TradingSession bucket 延后。current trading day 只通过 `MarketPhaseResolver + operational_products.txt` 唯一解析，不可用时 fail-closed。repair、replay、backfill、migration 与 EOD recalculation 不补评或补发历史通知。
10. `auto_order=false` 适用于所有研究观察与 Runtime 模式。任何创建或提交订单的流程都必须拒绝；本项目不实现自动交易。
11. 数据或指标语义变化时，同一变更更新相应 deep canonical；普通 bug fix、UI 调整和测试增加不自动改写项目状态。

## Data Foundation 稳定合同

DFD-01～DFD-07 与 active 60 品种闭环已经完成；当前长期行为规范位于 `openspec/specs/`，数据语义以
`docs/DATA_CENTER.md` 和 `services/quant-api/app/market_data/` 为准。历史 change、task、receipt 和执行
细节只从 Git history 追溯，不构成新的写入、部署或 Runtime 授权。

## 文档与交付

- 事实变化时更新对应 canonical：阶段更新 `STATUS.md`；长期边界更新 `PROJECT_SOURCE.md`；长期决策更新 `DECISIONS.md`；命令更新 README/`TESTING.md`；Execution Review 业务语义更新 `docs/EXECUTION_REVIEW.md`，其他业务语义更新对应 deep canonical。
- 临时分析和会话 Plan 不入仓库。已完成执行事实可以保留其历史 PR/hash/receipt 等描述，但这些描述不能成为未来执行条件。
- 交付说明变更范围、实际验证命令与结果、剩余风险、未执行的受控外部操作和最小下一步；未运行的验证明确标记。

## 接手最小阅读

1. `AGENTS.md`
2. `STATUS.md`
3. 与任务相关的 deep canonical 或 OpenSpec 主 spec；Execution Review 固定读取 `docs/EXECUTION_REVIEW.md`

统一业务 CLI 入口为 `uv run --project services/quant-api guiyi`。`data audit`、`runtime status` 等只读命令不授权后续写入；任何 dry-run 也不授权真实执行。`main` 仍用于 canonical/release；开发期可临时从 `develop` 运行本地服务，最终 Runtime 验收仍使用隔离、精确提交的 worktree。二者都不是普通 `develop` 编辑与本地测试的前置流程。
