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

## 模型、推理强度与任务模式

- Codex 跨项目默认由用户级 `config.toml` 管理；本仓库不重复固定默认模型。当前主力基线为
  `gpt-5.6-sol` + `medium`，适用于日常开发、已明确方向的实现、普通 Bug、中等重构、Review、技术方案与数据处理。
  任务重要本身不是提高推理强度的理由。
- 修改范围和验收明确、几乎无架构决策、不涉及核心交易语义或复杂跨模块状态、错误易被测试发现的小任务，
  优先 `gpt-5.6-terra` + `low`/`medium`；如发现隐含业务规则、多模块影响、数据语义或复杂异常路径，升级到 Sol。
  UI 文案、普通展示、字段调整、简单接口适配、文档与固定格式生成属于典型候选。
- 系统级设计、项目阶段规划、复杂架构决策、疑难或多次复现 Bug、多模块耦合、关键风险/重大发布 Review、
  系统性数据链路、复杂状态机、自动交易架构、交易执行安全和复杂模拟交易，优先 `gpt-6-astra` + `medium`/`high`。
  Astra 可在理解后直接实施；不机械套用“Astra 规划 -> Sol 开发 -> Astra Review”，只在价值和风险证明需要时增加阶段。
- `low` 用于明确小修改、简单代码理解和基本信息提取；`medium` 是默认；`high` 用于多步骤/多约束、
  跨模块影响、复杂异常、数据一致性、状态恢复与核心交易逻辑。当前目录若支持 `xhigh`/`max`/`ultra` 或 Pro 类模式，
  仅在 medium/high 仍不可靠、已有具体矛盾证据、错误成本极高、需要重要独立复核或任务价值足以支持明显额外成本时选择，不设为默认。
- 日志字段提取、数据分类、固定格式转换、简单摘要和标签生成优先 Luna/Terra。若 Python、SQL、Shell、测试或校验规则可确定性完成，
  优先使用确定性工具，不调用大模型。
- 模型输出不理想时先检查目标、相关代码/项目规则、branch/worktree、日志/报错/测试证据、数据文件、权限/工具、验收标准和业务语义。
  缺少上下文时先补事实，不立即升级模型或推理强度。模型 ID 与可用推理档位使用前以当前 Codex 目录、客户端和账户实际可见项为准，不凭历史名称猜测。
- Web UI、展示层、文档、非核心工具、一次性数据整理和普通代码整理可积极控制模型成本。行情数据/更新/完整性/时序、策略计算/信号/回测、
  未来函数、重绘、交易日、合约切换/主力连续、期货语义、仓位/风险、模拟/实盘接口、下单执行和恢复不得单纯为省额度降低分析质量。
- 执行任务按“理解代码 -> 修改 -> 测试 -> 验证”直接推进，不重做项目战略规划；设计任务先分析约束、比较方案、给出推荐并明确边界/验收后实施；
  调查任务先按输入数据、中间计算、输出、API 和 UI 取证，根因未定位前不重构、不改架构、不猜修复。
- 设计和 Review 始终按本地单用户、个人长期维护的真实需求评估复杂度；不套企业级架构，不为未来假设需求提前抽象，不在少于两个真实用例时建通用框架，
  不为模式或外观增加层级，不将小问题扩大为重构或主动扩范围；优先简单、可靠、可验证、可维护。

## 需要停止相关动作的条件

只在受影响部分出现以下情况时停止并请 owner 决定；其余独立、安全且已授权的工作继续：

- 仓库事实无法消除、会改变产品或架构的重要歧义；
- 必须改变目标、验收、业务合同或真实操作范围；
- 必须覆盖、删除或改写不属于本任务的用户修改；
- 必须扩大工具权限、修改用户级/全局配置或绕过宿主安全控制；
- 必须执行尚未明确授权的受控外部操作。

## 受控外部操作

下列 mutation 必须在首次执行前取得目标、环境和范围明确的执行授权；数据批次按下述批量授权规则执行，
其余操作仍需单次执行意图：

- 真实 RQData 下载或写入，Canonical/primary 数据覆盖、迁移或删除；
- production PostgreSQL、Redis、Scope 或仓库外数据写入/删除；
- Runtime/live enable、switch、promotion 或 production acknowledgment；
- 真实通知或收件范围变更；
- main merge、tag、GitHub Release、历史重写、force update 或 GitHub rules 修改；
- Broker 接入、订单草稿发送及任何真实下单、撤单或改单。

用户已明确批准的范围内，完成 input validation 和 preflight 后连续执行，不机械追加第二次确认。

- 数据任务中的只读 PostgreSQL 连接、Catalog 查询、审计、dry-run、计划生成和结果回读自动完成，不逐项申请批准。
- 用户可以一次批准一个明确的数据批次，覆盖多个品种、物理合约、周期和时间窗口，以及明确包含的 RQData 下载、
  Canonical 发布和 Catalog 写入。批次须明确目标环境、范围、资源预算和异常处理边界；仅批准下载不等于批准正式入库。
- 同一批次内的分包、逐项执行、校验和收尾不重复确认。授权未撤销、未到期且任务未完成时，不因会话切换或可恢复中断
  自动失效；恢复前核对原授权、已完成项和当前状态，只继续未完成部分。
- 失败或结果不明时先停止受影响的写入并只读核对；仅在结果已查明、重试安全且属于已批准的重试和预算边界时继续。
  不盲目重试，不绕过质量异常；超出范围、预算或异常处理边界时才重新申请批准。
- 批量授权替代数据任务逐命令、逐品种、逐 phase 的重复人工确认。领域文档或 skill 中旧的逐次确认要求按本节执行；
  exact plan hash、维护锁、质量校验、幂等提交和失败恢复等技术约束继续生效，计划变化必须核对仍在授权范围内。

其他受控外部操作仍只授权一次匹配尝试；失败、结果不明、重试或跨会话继续须取得新的明确意图。
测试、dry-run、read-only health、配置存在、commit hash 或 approval packet 本身不能替代用户授权。
普通 develop commit/push 与仓库内普通删除不属于受控外部操作；集成 develop 不授权生产写入、发布或 Runtime promotion。

不得读取、显示、提交或记录凭据；不修改 `.env`。外部输入须在敏感操作前校验类型、范围、身份和关联字段；
系统命令使用固定 executable 与离散参数，SQL 使用参数绑定或既有 ORM；输入派生路径规范化后必须仍在允许根内。
错误输出不得暴露凭据、内部地址、SQL 或 stack trace。失败、质量异常或安全开关缺失时 fail-closed。
仓库指引不能覆盖宿主或工具的安全控制。

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
- Review 仅按 `Confirmed Issue`、`Risk / Needs Verification`、`Optional Improvement` 分类，不以 finding 数量为目标。
  重要项说明证据、触发条件、实际影响、严重程度、建议验证方式及是否值得本版修复；不为充数建议无意义重构。
- 交付说明状态、改动范围、真实验证、Review、未完成 Gate、风险和唯一最小下一步。

## 领域导航

- 日常开发、任务定位和按影响验证：`docs/DEVELOPMENT.md`
- 数据、Catalog、维护、Live 与盘后合同：`docs/DATA_CENTER.md` 及相关 data OpenSpec
- HTDY 产品面与七周期入口：`PROJECT_SOURCE.md`、`DECISIONS.md`；共享 Alert Runtime、SuBing 身份、公式、
  Event、Scope、migration 和兼容 Gate：`openspec/specs/subing-ths-alert/spec.md`
- active 依赖与产品边界：`docs/ARCHITECTURE.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`
- release、服务、promotion 与 worktree：`.agents/skills/release-agent/SKILL.md`、`deploy/README.md`
- 可执行验证命令：`TESTING.md`
