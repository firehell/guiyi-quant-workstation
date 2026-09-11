# 归一量化执行规则

本文件只定义全局工程授权、安全边界和跨模块不变量。领域 canonical 的约束效力与本文件相同；当前
release、Runtime、Scope、evidence 和 pending Gate 只看 `STATUS.md`，不得用聊天记忆替代仓库事实。

## 项目定位与事实源

归一量化是本地、单用户的国内期货研究与策略运行工作站，采用模块化单体。AI 可以自动研究和完成工程工作，
但不能自动晋升策略、阶段或 Runtime；当前 `auto_order=false`，不得创建或提交真实订单。

- 用户本轮目标和边界决定任务授权；代码、测试和真实 evidence 决定实现事实；accepted canonical 与
  `DECISIONS.md` 决定长期合同；当前阶段以 `STATUS.md` 为准。
- 开始任务先核对 branch、HEAD、worktree、dirty state、相关实现、测试和当前 develop 依赖。保留并避开
  用户或其他任务修改，不覆盖、回滚、批量清理或全量暂存无关内容。
- `PROJECT_SOURCE.md` 只定义稳定产品面，`docs/ARCHITECTURE.md` 只定义 active 依赖，业务语义由对应
  OpenSpec/deep canonical 定义，命令只写入 `TESTING.md`。

## 讨论前置，范围内开发自主

- 用户要求讨论、比较方案、只读审计或 Plan-only 时，只分析并形成可审结果，不提前实施。讨论偏好、历史同意
  或可行性结论不构成执行授权。
- 用户明确要求实现，且目标、范围和验收清楚时，连续完成实现、修复本任务引入的问题、相关验证、Review、
  commit/push，以及任务已授权且条件满足的 develop 集成；不在编码、测试或提交阶段重复申请同一批准。
- 小任务可以 Direct；中等任务先给简短 Plan 后执行。命名、局部组织和按影响选择测试属于实现判断。
  branch、worktree、PR 和多 agent 按隔离、协作与风险需要使用，不是每个任务的固定仪式。
- Lane 3 的策略公式、撮合、成本、风险、仓位、Ledger、migration、Canonical、Runtime、通知、Broker、
  main/tag/release 等重要设计先完成 Plan 和必要 Review；设计获批后，范围内编码仍可连续执行。
- 必要验证失败必须继续定位或准确报告，不能因开发默认允许而跳过检查、降低断言或宣布完成。

## 需要停止相关动作的条件

只在受影响部分出现以下情况时停止并请 owner 决定；其余独立、安全且已授权的工作继续：

- 仓库事实无法消除、会改变产品或架构的重要歧义；
- 必须改变目标、验收、业务合同或真实操作范围；
- 必须覆盖、删除或改写不属于本任务的用户修改；
- 必须扩大工具权限、修改用户级/全局配置或绕过宿主安全控制；
- 必须执行尚未明确授权的受控外部操作。

## 受控外部操作

下列 mutation 必须在首次执行前取得目标、环境和范围明确的单次执行意图：

- 真实 RQData 下载或写入，Canonical/primary 数据覆盖、迁移或删除；
- production PostgreSQL、Redis、Scope 或仓库外数据写入/删除；
- Runtime/live enable、switch、promotion 或 production acknowledgment；
- 真实通知或收件范围变更；
- main merge、tag、GitHub Release、历史重写、force update 或 GitHub rules 修改；
- Broker 接入、订单草稿发送及任何真实下单、撤单或改单。

用户已精确批准某个动作时，在同一权限边界内完成 input validation 和 preflight 后执行，不机械追加第二次确认。
该意图只授权紧随其后的一次匹配尝试；blocked、结果不明、失败后继续、范围变化、重试或跨会话继续均停止并取得
新的明确意图。测试、dry-run、read-only health、配置存在、历史授权、commit hash 或 approval packet 都不能
替代执行意图。普通 develop commit/push 与仓库内普通删除不属于受控外部操作；集成 develop 不授权生产写入、
发布或 Runtime promotion。

不得读取、显示、提交或记录凭据；不修改 `.env`。外部输入须在敏感操作前校验类型、范围、身份和关联字段；
失败、质量异常或安全开关缺失时 fail-closed。仓库指引不能覆盖宿主或工具的安全控制。

## 持续 Runtime 授权边界

持续授权只在 owner 已对识别出的本地工作站明确启用后成立，当前是否启用只看 `STATUS.md` 和实际 readback：

- Market Runtime 只对 `operational_products.txt` 订阅当日 rank1 completed 1m；每日 18:05 及最多一次一小时后
  retry 只对同一集合运行 `HistoricalDataManager.update`。盘后主业务失败最多向 owner 发起一次既有运维通知；
  `missed/stuck` 只进入 health。
- 已启用的 Alert Runtime 只按既有 Rule、Scope、audience 和 transport 处理新的 completed observation；Event
  先提交，transport 最多一次。不得自动新增 Scope、Rule、收件人、retry、replay、backfill、fallback 或订单。
- 默认关闭的 Live recovery、weekly audit 或其他可选任务不因模板存在而启用。已明确启用的既有定时任务按合同
  自然运行，不需每天重新询问；新增任务、Scope、数据范围、重试或 Runtime 版本仍需新的明确意图。
- 上述持续授权不覆盖其他生产数据/DB、Canonical、main/tag/release、Runtime 版本切换、真实交易或失败后的
  任意重试。Market/Live/盘后细则见 `docs/DATA_CENTER.md`，Alert 细则见
  `openspec/specs/subing-ths-alert/spec.md`，安装、服务清单和 promotion 合同见 `deploy/README.md`。

## 跨模块硬约束

1. 唯一 Historical 链为 `RQData -> staging + hard validation -> Canonical Parquet -> 八表 Catalog +
   MainContractMap -> MarketDataService`；consumer 不得 glob、自选 active、自判主力、绕过质量或跨频回退。
2. Historical Canonical 与 Live observation 分离；未确认 Bar 只用于 preview，不进入正式历史、信号或决策，
   Live 不直接晋升 Canonical。
3. 映射、Session、分区、coverage、身份或物理完整性不能证明时显式失败；不造数、插值、缩窗、替代或建立
   第二套缺口事实。`active_products.txt` 与 `operational_products.txt` 不合并。
4. 策略与研究保留 causality、strict-before、future-leak、prefix invariance、golden parity、warm-up、
   合约切换、成交时序和 OOS/Walk-forward 边界；回看重绘与历史当时可知事实必须分开。
5. 已退役能力不恢复 active API、CLI、Web、Runtime、Scope 或兼容 reader；新策略使用新身份、合同和版本。
6. 数据、策略、成交、成本、风险或账户语义变化时更新对应 canonical 和版本；交易数值使用 `Decimal`。

## 验证与交付

- 按风险先跑定向测试，再扩展模块测试、lint、typecheck、build 或 smoke；不机械运行与改动无关的全量检查。
  数据、策略、migration、Runtime、通知和发布保留各自必要 Gate。
- 文档/指引改动运行引用与格式检查、适用工程测试、OpenSpec、secret scan 和 `git diff --check`；不得以重复
  固定措辞代替业务行为验证。
- 必须区分 `CODE_COMPLETE`、`TEST_COMPLETE`、`REVIEW_COMPLETE`、`EXTERNAL_GATE_PENDING`、
  `RELEASED` 与 `RUNTIME_READY`；历史 evidence 不证明新版本，只有实际命令和运行证据支持完成声明。
- 交付说明状态、改动范围、真实验证、Review、未完成 Gate、风险和唯一最小下一步。

## 领域导航

- 日常开发、任务定位和按影响验证：`docs/DEVELOPMENT.md`
- 数据、Catalog、维护、Live 与盘后合同：`docs/DATA_CENTER.md` 及相关 data OpenSpec
- Alert 固定身份、公式、Event、Scope、migration 和兼容 Gate：`openspec/specs/subing-ths-alert/spec.md`
- active 依赖与产品边界：`docs/ARCHITECTURE.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`
- release、服务、promotion 与 worktree：`.agents/skills/release-agent/SKILL.md`、`deploy/README.md`
- 可执行验证命令：`TESTING.md`
