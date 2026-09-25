# 归一量化执行规则

本文件是项目全局任务边界与执行规则的唯一入口，取代旧版长篇执行指引；领域 canonical 定义业务合同，
不重复设置人工审批流程。旧文档或技能的流程要求与本文件冲突时按本文件执行，机器校验不因此取消。当前
release、Runtime、Scope、evidence 和 pending Gate 只看 `STATUS.md`，不得用聊天记忆替代仓库事实。

## 项目定位与事实源

归一量化是本地、单用户的国内期货研究与策略运行工作站，采用模块化单体。owner 决定方向并交办任务；
Codex 负责范围内的研究、工程和实际执行。当前 `auto_order=false`，不能从研究结果自行决定无人值守真实交易。

- 用户明确交办的目标和边界就是该任务的执行授权，不再为任务内的每个阶段、命令或新会话重复请示；代码、测试和真实 evidence 决定实现事实；accepted canonical 与
  `DECISIONS.md` 决定长期合同；当前阶段以 `STATUS.md` 为准。
- 开始任务先核对 branch、HEAD、worktree、dirty state、相关实现、测试和当前 develop 依赖。保留并避开
  用户或其他任务修改，不覆盖、回滚、批量清理或全量暂存无关内容。
- `PROJECT_SOURCE.md` 只定义稳定产品面，`docs/ARCHITECTURE.md` 只定义 active 依赖，业务语义由对应
  OpenSpec/deep canonical 定义；`TESTING.md` 保存稳定验证入口，任务说明可记录实际执行命令。

## AI 开发与 owner 决策

- owner 负责产品方向和重要架构取舍；Codex 负责已交办目标的完整交付，包括必要的生产操作、发布和运行切换。
- 用户要求讨论、比较方案、只读审计或 Plan-only 时，只产出分析；明确要求实现且目标、范围、验收清楚时，
  连续完成实现、必要局部重构、测试、修复、自审、commit/push 和交办目标所需的集成、发布、Runtime 与验收，不重复申请批准。
- 小任务直接执行；复杂任务先说明简短计划再推进。检查后续动作是否仍服务于交办目标、是否改变产品或业务语义；
  未偏离就继续。只有无法依据任务与仓库事实决定的重要取舍才请 owner 决策，不因任务跨阶段或换会话停下。
- 内部模块、文件、函数和算法实现可按目标调整；改变领域职责、外部合同、公式、收益或风险语义、
  引入基础设施或扩大产品范围时先说明取舍。调查先取证定位，不以无关重构代替根因修复。
- branch、worktree、PR、并行协作与独立 Review 按冲突、共享状态、资源及风险选择，不是固定仪式。
  普通改动自审；数据时序、公式、并发、迁移、执行安全等高风险改动做独立 Review。
- 小任务使用聊天说明和 Git diff；复杂任务才落必要设计文档，不重复制造 Spec、Plan、report 和 receipt。
  设计遵循本地单用户、简单可维护原则，不为假设需求建通用框架。
- 项目新建 Codex 线程默认使用 `gpt-6-sol` + `medium`，由 `.codex/config.toml` 固定；单次任务在 Codex App/CLI 中显式选择模型或推理强度时可覆盖。
- 任务级模型路由见 `docs/DEVELOPMENT.md`：GPT-6 Luna 处理边界明确、高吞吐的小任务；GPT-6 Sol 是默认工程模型；GPT-6 Astra 用于架构、跨域设计和高风险独立 Review；Ultra 只用于前述层级仍无法可靠收敛的极端复杂问题。模型选择不改变必要的验证和任务边界。
- GPT-5.6 Sol/Terra 只作为历史会话续接、兼容性对照或 GPT-6 回归时的备用，不作为新任务默认。确定性检查优先使用代码和工具。
- 技能是执行工具。已交办且目标、范围、验收清楚时，不因技能要求重复批准设计或计划；
  TDD、计划文件、分支收尾等步骤按风险采用，必要回归、独立 Review 和完成验证仍需落实。
  本规则不修改全局技能、用户级配置或宿主安全控制。

## 需要停止相关动作的条件

只在受影响部分出现以下情况时停止并请 owner 决定；其余独立、安全且符合任务目标的工作继续：

- 仓库事实无法消除、会改变产品或架构的重要歧义；
- 必须改变目标、验收、业务合同或真实操作范围；
- 必须覆盖、删除或改写不属于本任务的用户修改；
- 必须扩大工具权限、修改用户级/全局配置或绕过宿主安全控制；
- 必须执行明显超出交办目标的外部操作，或无法从目标、现场与既有合同确定其对象和影响。

## 任务内的真实操作

交办目标包含真实数据修复、数据库变更、通知、发布、Runtime 切换或 Broker 操作时，交办本身覆盖为完成该目标
所需的连续步骤；Codex 不再索取第二次人工授权，也不要求 owner 在执行前指定后来才能确定的 commit、plan hash
或每个分包。Codex 从当前事实和既有合同推导精确对象，执行前核对目标、环境、范围和影响，按结果继续或停止。
只要求讨论、编码、候选或只读审计的任务，不自动扩大为生产执行。实现完成也不虚报已发布或已运行。

- RQData 查询/下载、Canonical/primary 与 Catalog/生产 DB 修复、migration、Scope/Redis 写入等，
  在交办目标需要且精确计划与机器校验通过时连续执行；覆盖、迁移和删除须有可验证恢复办法。
- 任务目标包含发布或上线时，Codex 可按已验证候选完成 main merge、annotated tag、GitHub Release、
  Runtime promotion 与必要的现场回读。发布、切换和自然验收仍分别记录，不能以一个阶段的成功冒充另一个。
- 任务目标包含真实通知或接入 Broker 时，先确定收件范围、账户与具体动作；不得根据研究结论自行新增受众、
  创建订单或改变 `auto_order=false`。未交办的真实交易不在任务范围内。
- 历史重写、force update、GitHub rules、远端或仓库归属变更属于方向性操作；只有交办目标确实需要时才做，
  不作为普通开发和发布的顺手步骤。本项目普通推送目标为 `origin = git@github.com:firehell/guiyi-quant-workstation.git`。
- 跨会话继续时核对任务目标、已完成步骤和现场状态；既已完成的操作不重复执行。生产结果不明先停止受影响
  mutation 并只读核对；只有确认重试安全且符合既有幂等、次数、预算和恢复约束时才继续。不能证明安全时报告阻断，
  不盲目重试；Alert one-shot 等业务禁重试合同仍有效。

测试、dry-run、health 或配置存在只证明各自范围，不代替真实操作读回。input validation、preflight、exact plan hash、
维护锁、质量校验、幂等提交、原子性与失败恢复是执行条件，不是新的人工审批环节。

不得将凭据读取到模型上下文、显示、提交或记录；允许既有程序通过安全配置加载使用。
生产 `.env` 仅在交办目标需要配置变更时通过不暴露秘密的方式修改。
外部输入须在敏感操作前校验类型、范围、身份和关联字段；系统命令使用固定 executable 与离散参数，
SQL 使用参数绑定或既有 ORM；输入派生路径规范化后必须仍在允许根内。
错误输出不得暴露凭据、内部地址、SQL 或 stack trace。失败、质量异常或安全开关缺失时 fail-closed。
生产数据删除、覆盖、迁移前明确精确目标、影响、dry-run、可验证恢复办法与幂等边界；不触碰无关修改。
仓库指引不能覆盖宿主或工具的安全控制。

## 持续 Runtime 边界

当前启用状态只看 `STATUS.md` 和实际 readback；交办新的运行目标时 Codex 按该目标完成必要的配置、切换和验证：

- Market Runtime 只对 `operational_products.txt` 订阅当日 rank1 completed 1m；每日 18:05 及最多一次一小时后
  retry 只对同一集合运行 `HistoricalDataManager.update`。盘后主业务失败最多向 owner 发起一次既有运维通知；
  `missed/stuck` 只进入 health。
- 已启用的 Alert Runtime 只按既有 Rule、Scope、audience 和 transport 处理新的 completed observation；Event
  先提交，transport 最多一次。不得自动新增 Scope、Rule、收件人、retry、replay、backfill、fallback 或订单。
- 默认关闭的 Live recovery、weekly audit 或其他可选任务不因模板存在而启用。已启用的既有定时任务按合同
  自然运行；新增任务、Scope、数据范围或 Runtime 版本须属于交办目标，不能从模板或旧成功记录推导。
- 持续运行不会自行扩大到其他生产数据、发布或交易，也不授权失败后的盲目重试。Market/Live/盘后细则见 `docs/DATA_CENTER.md`，Alert 细则见
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
