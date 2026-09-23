# 归一量化执行规则

本文件是项目全局工作流与授权的唯一入口，取代旧版长篇执行指引；领域 canonical 定义业务合同，
不重复设置人工审批流程。旧文档或技能的流程要求与本文件冲突时按本文件执行，机器校验不因此取消。当前
release、Runtime、Scope、evidence 和 pending Gate 只看 `STATUS.md`，不得用聊天记忆替代仓库事实。

## 项目定位与事实源

归一量化是本地、单用户的国内期货研究与策略运行工作站，采用模块化单体。AI 可以自动研究和完成工程工作，
但不能自动晋升策略、阶段或 Runtime；当前 `auto_order=false`，不得创建或提交真实订单。

- 用户本轮目标和边界决定任务授权；代码、测试和真实 evidence 决定实现事实；accepted canonical 与
  `DECISIONS.md` 决定长期合同；当前阶段以 `STATUS.md` 为准。
- 开始任务先核对 branch、HEAD、worktree、dirty state、相关实现、测试和当前 develop 依赖。保留并避开
  用户或其他任务修改，不覆盖、回滚、批量清理或全量暂存无关内容。
- `PROJECT_SOURCE.md` 只定义稳定产品面，`docs/ARCHITECTURE.md` 只定义 active 依赖，业务语义由对应
  OpenSpec/deep canonical 定义；`TESTING.md` 保存稳定验证入口，任务说明可记录实际执行命令。

## AI 开发与 owner 决策

- AI 负责日常开发维护闭环；owner 负责产品方向、重要架构与业务语义取舍、生产操作边界和阶段晋升。
- 用户要求讨论、比较方案、只读审计或 Plan-only 时，只产出分析；明确要求实现且目标、范围、验收清楚时，
  连续完成实现、必要局部重构、测试、修复、自审、commit/push 和条件满足的 develop 集成，不重复申请批准。
- 小任务直接执行；复杂任务先说明简短计划再推进。仅重要设计取舍或业务合同变化需要 owner 决策，
  不因涉及策略、数据或 Runtime 代码就强制新会话、Plan-only 或再次审批。修复实现以符合已批准合同可自主完成。
- 内部模块、文件、函数和算法实现可按目标调整；改变领域职责、外部合同、公式、收益或风险语义、
  引入基础设施或扩大产品范围时先说明取舍。调查先取证定位，不以无关重构代替根因修复。
- branch、worktree、PR、并行协作与独立 Review 按冲突、共享状态、资源及风险选择，不是固定仪式。
  普通改动自审；数据时序、公式、并发、迁移、执行安全等高风险改动做独立 Review。
- 小任务使用聊天说明和 Git diff；复杂任务才落必要设计文档，不重复制造 Spec、Plan、report 和 receipt。
  设计遵循本地单用户、简单可维护原则，不为假设需求建通用框架。
- 模型及推理强度由用户级配置管理；项目只要求按风险保证质量，确定性检查优先使用代码和工具。
- 技能是执行工具。已明确授权且目标、范围、验收清楚时，不因技能要求重复批准设计或计划；
  TDD、计划文件、分支收尾等步骤按风险采用，必要回归、独立 Review 和完成验证仍需落实。
  本规则不修改全局技能、用户级配置或宿主安全控制。

## 需要停止相关动作的条件

只在受影响部分出现以下情况时停止并请 owner 决定；其余独立、安全且已授权的工作继续：

- 仓库事实无法消除、会改变产品或架构的重要歧义；
- 必须改变目标、验收、业务合同或真实操作范围；
- 必须覆盖、删除或改写不属于本任务的用户修改；
- 必须扩大工具权限、修改用户级/全局配置或绕过宿主安全控制；
- 必须执行尚未明确授权的受控外部操作。

## 受控外部操作

下列操作必须在首次执行前取得目标、环境和范围明确的授权，可按一个明确任务或批次一次批准：

- 真实 RQData 下载或写入，Canonical/primary 数据覆盖、迁移或删除；
- production PostgreSQL、Redis、Scope 或仓库外真实业务数据写入/删除；
- Runtime/live enable、switch、promotion 或 production acknowledgment；
- 真实通知或收件范围变更；
- main merge、tag、GitHub Release、历史重写、force update 或 GitHub rules 修改；
- Broker 接入、订单草稿发送及任何真实下单、撤单或改单。

- 只读 PostgreSQL/Catalog/MDS 查询、审计、dry-run、计划生成、结果回读和隔离开发预览可在任务范围内自主执行，
  不逐项审批；真实 provider 下载不归入默认只读权限。
- 数据批次明确品种、物理合约、周期、窗口、环境、资源预算及异常处理边界，可同时包含下载、Canonical 发布和
  Catalog 写入。仅批准下载不等于批准入库；范围内分包、逐项校验和收尾不重复确认。
- 发布批次可一次批准精确版本的 main merge、annotated tag 和 GitHub Release。Runtime promotion 是独立
  授权项，可在同次批准中明确列出工作站、exact tag/commit、服务及恢复范围，不能由发布授权隐含推导。
- 授权绑定任务、目标和范围，不绑定会话。未撤销、未到期且尚未完成时，恢复前核对原授权、已完成项和现场状态，
  仅继续未完成部分；已完成的历史授权不授权重新执行。
- 生产失败或结果不明先停止受影响 mutation 并只读核对。仅在结果查明、重试安全且属于已批准的幂等、次数、
  预算及恢复边界时继续；未包含重试或恢复时请求新授权，不盲目重试。Alert one-shot 等业务禁重试合同仍有效。
  测试、构建和普通开发失败由 AI 自主修复重测。
- 批量授权替代逐命令、逐品种、逐 phase 的重复确认；input validation、preflight、exact plan hash、维护锁、
  质量校验、幂等提交、原子性和失败恢复约束保持不变。计划变化须核对仍在授权范围内，不能借此绕过机器校验。

- owner 已确认本项目唯一授权远端为 `origin = git@github.com:firehell/guiyi-quant-workstation.git`。任务范围内的普通文档、代码和
  `develop` branch push 可直接执行，不再要求重复验证 origin 归属或文档外发授权。远程地址、仓库归属、推送目标发生变化，或向任何
  其他外部目的地发布时，仍须另行确认。

测试、dry-run、health、配置存在、commit hash 或 approval packet 本身不授予生产权限。
普通 develop commit/push、开发测试配置和任务内普通文件操作可自主完成；
集成 develop 不授权生产写入、发布或 Runtime promotion。生产凭据、权限、成本或外部行为的配置变化须明确授权。

不得将凭据读取到模型上下文、显示、提交或记录；允许既有程序通过安全配置加载使用。
生产 `.env` 仅在明确配置变更授权下通过不暴露秘密的方式修改。
外部输入须在敏感操作前校验类型、范围、身份和关联字段；系统命令使用固定 executable 与离散参数，
SQL 使用参数绑定或既有 ORM；输入派生路径规范化后必须仍在允许根内。
错误输出不得暴露凭据、内部地址、SQL 或 stack trace。失败、质量异常或安全开关缺失时 fail-closed。
生产数据删除、覆盖、迁移前明确精确目标、影响、dry-run、可验证恢复办法与幂等边界；不触碰无关修改。
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
- 文档/指引改动先做引用与格式检查及 `git diff --check`；按内容选择工程测试、OpenSpec 或 secret scan，
  纯文字改动不触发无关测试，不以固定措辞断言代替业务行为验证。
- 必须区分 `CODE_COMPLETE`、`TEST_COMPLETE`、`REVIEW_COMPLETE`、`EXTERNAL_GATE_PENDING`、
  `RELEASED` 与 `RUNTIME_READY`；历史 evidence 不证明新版本，只有实际命令和运行证据支持完成声明。
- Review 仅按 `Confirmed Issue`、`Risk / Needs Verification`、`Optional Improvement` 分类，不以 finding 数量为目标。
  重要项说明证据、触发条件、实际影响、严重程度、建议验证方式及是否值得本版修复；不为充数建议无意义重构。
- 交付简述结果、关键改动、实际验证及剩余风险/Gate；普通讨论直接回答，不强制固定段落、状态枚举或结论口号。

## 领域导航

- 日常开发、任务定位和按影响验证：`docs/DEVELOPMENT.md`
- 数据、Catalog、维护、Live 与盘后合同：`docs/DATA_CENTER.md` 及相关 data OpenSpec
- HTDY 产品面与七周期入口：`PROJECT_SOURCE.md`、`DECISIONS.md`；共享 Alert Runtime、SuBing 身份、公式、
  Event、Scope、migration 和兼容 Gate：`openspec/specs/subing-ths-alert/spec.md`
- active 依赖与产品边界：`docs/ARCHITECTURE.md`、`PROJECT_SOURCE.md`、`DECISIONS.md`
- release、服务、promotion 与 worktree：`.agents/skills/release-agent/SKILL.md`、`deploy/README.md`
- 可执行验证命令：`TESTING.md`
