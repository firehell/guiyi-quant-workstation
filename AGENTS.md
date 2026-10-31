# 归一量化执行规则

本文件是项目任务边界与开发方式的唯一入口。owner 把控方向、架构、任务与节奏；Codex 负责范围内的工程判断和完整交付。
旧指引或技能与本文件冲突时按本文件执行；不修改全局配置，也不绕过宿主安全控制。

## 项目定位与事实源

归一量化是本地、单用户的国内期货研究与策略运行工作站，采用模块化单体。当前 `auto_order=false`，研究结果不授权无人值守真实交易。

- 开工快速核对 branch、HEAD、worktree、dirty state 和相关依赖；保留用户及其他任务修改，不覆盖、回滚或全量暂存无关内容。
- 代码、测试和实际运行决定实现事实；`STATUS.md` 记录当前发布、Runtime 与待验事项；`PROJECT_SOURCE.md` 定义稳定产品面，
  `docs/ARCHITECTURE.md` 定义 active 依赖，accepted canonical 和 `DECISIONS.md` 定义业务合同，`TESTING.md` 提供验证入口。
  其他文档引用这些入口，不另存一套状态、规则或路线图。

## AI 开发与 owner 决策

默认流程：**owner 交办 → 定位并开发 → 必要测试与自审 → 提交、按目标发布或切换 → 确认实际生效**。

- 目标和边界清楚就连续完成，不因阶段、命令、新 commit/hash 或换会话重复请示。只要求讨论、只读或 Plan-only 时按该限制交付。
- 不设日常候选冻结、解冻、release candidate 或版本收尾阶段；发现问题向前修复。任务节奏和本次范围由 owner 把控，
  实现中的必要调整由 Codex 完成，新增需求说明影响，不把每次修复变成新一轮设计审批。
- 默认在合适的现有工作区开发；有实际冲突才隔离。不强制 task branch/worktree、Issue、PR、多角色接力或专门分支收尾；
  遵守远端实际规则，提交并按目标集成后顺手清理本任务临时资源，不清理其他任务。
- 普通任务用聊天说明与 Git diff，不固定生成 Spec、Plan、manifest、report、receipt 或验收矩阵。
  重要架构取舍才写必要设计；工具执行、复算或恢复确实需要的记录保留，避免人工重复材料。
- 普通改动自审；公式、数据时序、并发、迁移、成交或账本等高风险变化做针对性独立 Review。
  测试按影响选择，不固定 TDD 顺序、不机械跑全仓测试，也不靠降低断言制造通过。
- 只维护当前应用实现，默认向前修复与发布。旧实现先查消费者再删除，历史从 Git 找，不养兼容分支、备用源码或常驻回滚树。
  应用编号、tag 及现有部署工具要求的身份由 Codex 随发布处理，不形成 owner 要管理的版本流程；已发布历史不改写。
- 保留最小运行 commit 身份，确保受测代码与运行代码一致。研究比较需固定输入、规则和评价口径，历史结果、订单与账本保留当时身份；
  这些正确性要求不扩展为每次普通开发的冻结仪式。
- 设计保持本地单用户、简单可维护，不顺带扩建平台。新线程默认 `gpt-6-sol` + `medium`，单次显式选择优先；
  模型按 `docs/DEVELOPMENT.md` 调度，不为省用量降低验证，也不为模型切换增加工序。
- 技能用于完成任务，不重新引入上述已取消的流程；不改用户级或全局技能、配置与宿主控制。

## GPT 讨论与 Codex 交接

已讨论方案交办实施后，读取引用材料与现有实现直接推进，不要求再次批准同一设计、书面计划或执行方式。
缺少原对话先依据交办内容和仓库补齐；重要且无法推导的取舍才请 owner 决定。
子代理按具体需要调用，不强制角色组合、分派模板或统一六段交付；交回结果、实际验证及未解决问题即可。

## 需要停止相关动作的条件

只在受影响部分出现以下情况时请 owner 决定，其余可独立工作继续：

- 无法从仓库消除的重要歧义，涉及架构、领域职责、外部合同、公式、收益、风险或真实交易范围；
- 必须改变交办目标、扩大产品或真实操作范围、引入基础设施；
- 必须覆盖、删除或改写其他任务或用户修改；
- 必须扩大权限、修改用户级/全局配置，或受到宿主控制阻断。

先给事实、影响和建议，不把内部命名、常规修复、可避免冲突或缺少形式材料升级为 owner 决策。
研究候选晋升、交易阶段变化、真实账户操作仍须 owner 明确交办，不能从普通开发或盈利结果推导。

## 任务授权与验证 Gate

Gate 表示必要的机器校验或事实条件，不是固定人工审批阶段。已交办范围内由 Codex 完成，满足后连续推进。

- “补齐数据”“完成历史候选闭环”等目标覆盖所需 RQData 查询/下载、Canonical 聚合/发布和 Catalog/生产 DB 写入。
  Codex 确定精确品种、物理合约、周期、窗口、预算和恢复边界；现有工具需要 plan hash/attempt 时直接生成校验，不要求 owner 逐份批准。
- 不把真实下载或写入描述为只读。宿主拒绝时补充已有授权与可核验证据，按宿主流程复核；不盲重试、换工具绕过或改拒绝记录。
  未解除时报告 `HOST_APPROVAL_BLOCKED`，与质量失败、任务未授权、提交未知区分。
- 校验失败就定位修复并补验受影响部分，不请求批准跳过。生产结果不明先只读查清，不能证明安全或合同禁重试就停止相关 mutation；
  不清空旧状态、不复用失败 attempt，不以再次同意替代幂等、次数和预算约束。
- 自然业务未发生就如实列为待观察，不拖住无关开发与发布，不擅自新建监控、通知或后台任务，不伪造验收。

## 任务内的真实操作

交办目标包含数据修复、数据库变更、通知、发布、Runtime 或 Broker 操作时，覆盖完成该目标的连续步骤。
执行前核对对象、环境和影响；只要求编码或分析不自动扩大为生产操作。

- 覆盖、删除或迁移生产数据前明确精确目标、影响、dry-run、可验证恢复与幂等边界；保留维护锁、质量校验和原子提交。
- 发布或上线任务由 Codex 连续完成所需集成、main/tag/Release、构建、切换和现场确认，不另设冻结候选与重复批准。
  只发布不推导 Runtime 切换；未实际发布或运行不能宣称已发生。
- 通知/Broker 任务先确定受众、账户和动作；不得新增未交办受众、订单或改变 `auto_order=false`。
  Alert one-shot 等禁重试合同继续有效。
- 普通推送目标为 `origin = git@github.com:firehell/guiyi-quant-workstation.git`；历史重写、force update、远端/GitHub rules 变更不属日常收尾。
- 跨会话先查已完成项与现场，不重复执行；测试、dry-run、health 不代替实际副作用的读回。

质量失败、安全开关缺失或必要事实不明时停止相关操作，不因省流程而绕过。
凭据不进入模型上下文、日志、文档或提交，允许程序安全加载；生产配置仅在任务需要时修改。
敏感操作前校验外部输入与路径边界，命令使用固定 executable 与离散参数，SQL 参数绑定；错误不暴露凭据、内部地址、SQL 或 stack trace。
宿主安全控制不因项目授权而取消。

## 持续 Runtime 边界

当前启用集合只看 `STATUS.md` 和实际读回；现有运行不会自行扩大授权：

- Market 只订阅 `operational_products.txt` 当日 rank1 completed 1m；既有盘后每日 18:05 及最多一次一小时后 retry 处理同一集合。
  主业务失败最多发送一次既有运维通知，`missed/stuck` 只进 health。
- Alert 按既有 Rule、Scope、audience、transport 处理新 completed observation；Event 先提交，transport 最多一次。
  不自动新增 Scope、Rule、受众、retry、replay、backfill、fallback 或订单。
- 可选任务不因模板存在而启用；新增运行目标、Scope、数据范围与切换须服务于交办目标。
  细则见 `docs/DATA_CENTER.md`、`openspec/specs/subing-ths-alert/spec.md`、`deploy/README.md`。

## 跨模块硬约束

1. 唯一 Historical 链：`RQData -> staging + hard validation -> Canonical Parquet -> 八表 Catalog + MainContractMap -> MarketDataService`。
   consumer 不 glob、自选 active、自判主力、绕过质量或跨频回退。
2. Historical Canonical 与 Live observation 分离；未确认 Bar 仅 preview，不进入正式历史、信号或决策，Live 不直接晋升 Canonical。
3. 映射、Session、分区、coverage、身份或完整性不能证明时显式失败，不造数、插值、缩窗或替代。
   `active_products.txt` 与 `operational_products.txt` 不合并。
4. 保留 causality、strict-before、future-leak、prefix invariance、golden parity、warm-up、合约切换、成交时序与 OOS/Walk-forward 边界。
   回看重绘与历史当时可知事实分开。
5. 已退役能力不恢复 active API、CLI、Web、Runtime、Scope 或兼容 reader；不再使用的入口查清引用后删除。
6. 数据、策略、成交、成本、风险或账户语义变化更新对应合同、语义版本与历史身份，历史事实不改写；交易数值使用 `Decimal`。

## 验证与交付

- 先定向、再按实际风险扩展；文档只做引用、格式、diff 和适用 secret 检查，不触发无关业务测试。
- 普通发布确认代码身份、受影响功能与必要服务实际生效即可交付；尚未发生的自然业务单独注明，不为等待它阻塞无关任务。
- 如实区分已开发、已验证、已发布、已运行与自然业务待观察，不强制逐级状态枚举、固定格式或结论口号。
  历史通过记录、fixture、health 和 provider accepted 不证明新版本业务完成或用户收到。
- Review 说明确认问题、待验证风险与可选建议，给出实际影响；不追求 finding 数量或重复复核未受影响部分。
- 一次简短交付说明结果、关键改动、实际验证与剩余问题即可；已有日志/工具结果可引用，不重复制造报告。

## 领域导航

- 开发与验证：`docs/DEVELOPMENT.md`、`TESTING.md`；按需协作：`docs/AGENT_ROLES.md`
- 产品与依赖：`PROJECT_SOURCE.md`、`DECISIONS.md`、`docs/ARCHITECTURE.md`
- 行情与维护：`docs/DATA_CENTER.md`、相关 data OpenSpec、`.agents/skills/futures-data/SKILL.md`
- SuBing/Alert：`openspec/specs/subing-ths-alert/spec.md`；其他业务按对应 accepted canonical
- 发布与运行：`.agents/skills/release-agent/SKILL.md`、`deploy/README.md`
