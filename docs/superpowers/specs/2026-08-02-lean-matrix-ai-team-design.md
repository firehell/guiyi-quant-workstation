# 归一量化精简矩阵式 AI 研发团队设计

- 日期：2026-08-02
- 状态：Phase 1 merged through PR #98 at develop@0867e123; Phase 2 is implemented under Issue #99 on its task branch and remains pending Draft PR exact-head review, CI, and merge. Task 05 later merged independently through PR #100 and does not count retroactively as Phase 3.
- 适用项目：`firehell/guiyi-quant-workstation`
- 设计范围：研发组织模型、专家角色、任务路由、自治状态机、权限边界和最小落地方式

## 1. 摘要

归一量化需要的不是一套模拟大型软件公司的完整组织，也不是为当前 Task 04 临时建立的数据专家小组，而是一套适合个人长期开发的精简 AI 研发机制。

该机制采用“精简矩阵式”结构：

```text
项目所有者
    ↓
AI 项目负责人
    ↓
最小动态任务小队
├── 技术负责人
├── 实现负责人
├── 独立质量负责人
└── 最多两个按需专项专家
    ↓
确定性 Gatekeeper
    ↓
GitHub / develop / 外部人工 Gate
```

其核心目标是：

1. 普通可逆开发由 Codex 自主完成；
2. 实现、测试、Review、PR 和 `develop` 集成尽量不打断用户；
3. 产品与架构角色主动做减法，避免把单用户工作站设计成企业平台；
4. GitHub、active canonical、测试、CI、独立 Review 和 receipt 保持事实源地位；
5. 真实数据写入、删除、正式策略口径、release 和 Runtime promotion 继续保留人工 Gate；
6. 不建立新的多代理平台、任务数据库、状态控制台或第二套事实源。

## 2. 项目上下文与设计约束

### 2.1 产品边界

归一量化是本地优先、单用户使用的国内期货量化研究工作站，长期服务于：

```text
可信数据
→ 策略候选信号
→ 保存当时快照
→ 观察提醒
→ 复盘和结果标签
→ 统计与 AI 辅助研究
→ 候选版本
→ OOS / Walk-forward / Shadow
→ 人工批准升级
```

长期不以以下目标为设计前提：

- SaaS；
- 多租户和多用户权限；
- 高并发平台；
- Kubernetes 或复杂微服务；
- 无人值守自动交易；
- AI 自动晋升正式策略；
- 以聊天记忆替代 GitHub 事实源。

### 2.2 当前工程边界

现有仓库已经具备：

- `main`、`develop`、task worktree 和 detached Runtime 的隔离模型；
- Lane 1/2/3；
- task branch → PR → CI → 独立 Review → `develop` 的集成路径；
- 可逆代码、测试、dry-run、隔离 migration 和默认关闭功能的自动集成边界；
- 生产 migration、真实数据/DB 写入、删除、release/tag、Runtime、live 和真实通知的人工 Gate；
- `STATUS.md`、`AGENTS.md`、`PROJECT_SOURCE.md`、`DECISIONS.md` 和 deep canonical 的事实源层级。

因此本设计只定义“如何组织 Codex 完成工作”，不重新实现这些能力。

### 2.3 当前迁移阶段

当前 active 合同仍为 `docs/tasks/GY-DATA-CORE-V2.md`。Task 04 已在 `develop` 完成收尾；其 legacy historical Shadow 仅作为可选且冻结的历史观察，不是 Task 05 的前置 Gate，也不需要为本设计重新打开执行路径。

在 AI-TEAM-001 / Phase 2 取样当时，Task 05 的 then-active 实现位于独立 worktree。Phase 2 不采纳、不修改、也不以此 worktree 的内容作为本任务的实现输入；Task 05 随后已通过独立的 PR #100 合入 `develop`（GitHub PR #100 metadata：merge `b64453eab89692e5250a4275f04cac1bd26f02d4`，task head `a932793830e1e68a3e2c1634a38f50840a55efc5`）。Phase 2 task branch 本身起于 `0867e123`；与 PR #100 task head 的拓扑比较共享基线为 `cc4302b57728133a1471447902563d3abf3604fb`。该次 exact-head 检查记录为零 changed-path intersection 和零 merge-tree conflict markers，但不构成永久可合入性声明；Draft PR / integration 前必须针对当前 `origin/develop` 重新检查 exact-head compatibility。

## 3. 设计目标

### 3.1 主要目标

- 降低用户在普通开发中的参与频率；
- 提高一个独立任务从需求到 `develop` 的自主完成率；
- 让产品、架构、实现和质量视角都存在，但减少实际代理数量；
- 让复杂度控制成为产品和架构角色的明确职责；
- 让专项专家按任务加入，而不是常驻；
- 保持实现和最终 Review 的上下文独立；
- 让自动化止步于既有 Gate，而不是扩大不可逆权限。

### 3.2 非目标

本设计不建设：

- 自定义多代理服务；
- 专家聊天群 Web 页面；
- 代理注册中心；
- 任务状态数据库；
- 新的工作流引擎；
- 新消息总线；
- 新配置中心；
- 独立知识库或向量数据库；
- 面向其他项目的通用商业平台；
- 无人值守发布或生产写入系统。

## 4. 核心原则

### 4.1 个人项目优先

所有产品和架构判断必须按以下顺序权衡：

```text
解决用户真实问题
> 提高研究和开发效率
> 提高可信性和可恢复性
> 降低长期维护成本
> 未来扩展能力
```

“行业标准”“企业级”“以后可能多用户”“以后可能高并发”不能单独构成立项理由。

### 4.2 专家是能力，不是部门

专家角色是一组职责和检查清单，不意味着必须创建一个常驻代理。一个实际 Codex 会话可以承担多个不冲突的逻辑角色，但实现者和最终 Reviewer 必须分离。

### 4.3 最小小队

默认只使用：

```text
AI 项目负责人 / 技术负责人
+ 实现负责人
+ 独立质量负责人
```

按需增加一至两个专项专家。若需要三个以上专项领域，默认先拆任务。

### 4.4 GitHub 是事实源

专家意见不能直接改变项目状态。状态变化必须由相应事实支持：

```text
active canonical
+ exact SHA
+ tests
+ CI
+ independent Review
+ approval Gate / receipt（如适用）
```

### 4.5 可逆自动化，不可逆人工 Gate

代码、测试、文档、dry-run、隔离环境和默认关闭功能可以自治推进。真实数据、正式口径、删除、发布和 Runtime 不因“专家一致同意”而自动获得权限。

### 4.6 复杂度需要证明

新增服务、数据库、后台进程、基础框架或抽象层时，技术负责人必须说明：

1. 当前真实问题；
2. 现有方案为何无法解决；
3. 新增维护成本；
4. 回滚和删除方式；
5. 为什么不是过早设计。

证明不足时默认不引入。

## 5. 组织模型

### 5.1 项目所有者

项目所有者是用户本人，职责仅保留为：

- 长期目标和版本主线；
- 重大范围改变；
- 多种架构方向无法客观排除时的取舍；
- 真实数据/DB 写入批准；
- 正式策略和回测口径批准；
- 删除批准；
- release、tag 和 Runtime promotion；
- AI/策略候选晋升。

项目所有者不负责普通 bugfix、测试修复、Review 往返、PR 创建、`develop` 集成或 worktree 清理。

### 5.2 AI 项目负责人

该角色合并产品经理、项目经理、软件开发经理和需求分析师。

职责：

- 读取当前 GitHub 和 canonical 事实；
- 判断需求价值和当前优先级；
- 拒绝低价值或过早需求；
- 将需求收敛为一个可独立验收的 Task Charter；
- 判断 Lane、模型、Plan、会话和 worktree；
- 选择最小专家小队；
- 管理前置依赖和任务状态；
- 汇总结果；
- 只在定义好的升级条件发生时通知用户。

固定检查：

```text
这是用户现在真实需要的吗？
不做会造成什么具体损失？
现有功能或模块能否解决？
是否属于当前阶段？
是否因为未来多用户或企业化而增加复杂度？
实现后的长期维护成本是什么？
```

禁止：

- 自行改变 active target；
- 创建第二套状态源；
- 未满足前置条件时启动后续任务；
- 把建议写成已批准事实；
- 以流程完整为由增加低价值工作。

### 5.3 技术负责人

该角色合并软件架构师、技术负责人和高级工程师。

职责：

- 阅读现有实现、测试和 canonical；
- 选择最小可维护方案；
- 明确复用、修改和禁止修改的边界；
- 评估数据、并发、幂等、恢复、兼容和安全风险；
- 判断是否需要专项专家；
- 审查实现是否产生平行系统或不必要抽象；
- 给出测试和回滚策略。

默认偏好：

```text
模块化单体 > 微服务
复用现有模块 > 新建平行系统
明确代码 > 通用框架
单一事实源 > 同步多份状态
确定性流程 > AI 自由决策
简单配置 > 配置平台
本地工具 > 云原生基础设施
按需优化 > 预测性性能设计
```

禁止：

- 为未来 SaaS、多用户和高并发预留复杂架构；
- 建立第二数据核心、第二 active selector 或第二 lineage 平台；
- 未经测量提前性能优化；
- 以“解耦”作为新增服务的唯一理由。

### 5.4 实现负责人

默认是全栈实现工程师，而不是预先拆分前端、后端和数据库任务。

职责：

- 从刷新后的 `develop` 创建独立 task branch/worktree；
- 严格按 Task Charter 和技术方案实现；
- 使用定向测试或 TDD；
- 完成必要的 API、数据模型、Web 和测试；
- 运行 lint、type/build、模块测试和适用 smoke；
- 创建 Draft PR；
- 处理独立 Review；
- 输出修改、测试、风险和未完成项。

只有在以下条件之一满足时才拆分前后端：

- 接口已冻结且可真正并行；
- 单个上下文无法可靠覆盖修改范围；
- 前端图表或状态管理本身是独立复杂任务；
- 数据合同或 migration 需要独立 Gate；
- 两部分可分别独立验收和集成。

### 5.5 独立质量负责人

该角色合并 QA、自动化测试和独立代码 Reviewer，必须使用不同于实现者的上下文。

职责：

- 审查 exact task HEAD；
- 检查任务目标、范围和 canonical 合规；
- 检查测试是否覆盖实际风险；
- 检查回归、复杂度和过度设计；
- 对数据、策略、回测和 Runtime 任务执行专项边界检查；
- 确认 CI 与已审查 SHA 一致；
- 给出明确的集成或阻塞结论。

最终结论只能使用：

```text
允许继续实现
允许集成 develop
要求修正后再集成
允许进入 release candidate
允许发布 main/tag
允许 Runtime promotion
阻塞
```

质量负责人不得为了让任务通过而修改验收口径。

### 5.6 确定性 Gatekeeper

Gatekeeper 不是自由推理专家，而是现有仓库规则、脚本、CI 和业务专用 Gate 的总称。

它验证：

- branch/worktree/base SHA；
- exact PR head；
- 允许修改路径；
- 测试与 CI；
- 独立 Review；
- task HEAD 是否漂移；
- 是否触及真实数据、DB、删除、release、Runtime 或真实通知；
- 是否存在所需 approval packet 和 receipt。

AI 可以解释 Gate 结果，但不能覆盖或忽略 Gate 失败。

## 6. 按需专项专家库

### 6.1 产品与交互专家

启用条件：

- 新页面；
- 核心使用流程；
- 导航或信息架构；
- 复杂状态、反馈和错误处理；
- 真实用户操作存在明显摩擦。

UI 和 UX 合并为一个角色。普通文案、表格列调整和小型 CRUD 不启用。

### 6.2 前端专家

启用条件：

- K 线或复杂图表；
- 跨页面状态；
- 前端性能问题已有证据；
- 复杂组件边界；
- 浏览器兼容或可访问性风险。

### 6.3 数据与数据库专家

合并数据工程师和 DBA 能力。

启用条件：

- RQData；
- Parquet、DuckDB；
- PostgreSQL schema 或 migration；
- Catalog/Manifest/Gap/MainContractMap；
- 数据身份、质量、lineage；
- 查询性能已有证据；
- 真实数据恢复和幂等。

普通 API 增加一个字段不启用。

### 6.4 量化研究专家

启用条件：

- 策略规则；
- 指标语义；
- 信号定义；
- 参数假设；
- 市场状态；
- 结果标签业务含义。

该专家提出研究假设，但不能独自证明有效性。

### 6.5 回测可信性审计专家

启用条件：

- 撮合；
- 成交时序；
- 手续费和滑点；
- 资金和保证金；
- 主力换月；
- 未来函数、泄漏和重绘；
- OOS、Walk-forward 和 Shadow；
- 候选晋升或淘汰。

必须与策略提出者保持独立。

### 6.6 Research Memory / AI 专家

启用条件：

- FeatureSnapshot；
- OutcomeLabel；
- 相似样本；
- 评分模型；
- 训练、校准和漂移；
- AI assessment；
- challenger 与 Shadow。

普通 LLM 文案摘要不需要该专家。

### 6.7 Runtime / SRE 专家

启用条件：

- launchd；
- 进程恢复；
- checkpoint；
- 备份恢复；
- 部署；
- Runtime health；
- release candidate；
- Runtime promotion。

### 6.8 安全专家

启用条件：

- 凭据；
- 网络暴露；
- 真实通知；
- 权限和 GitHub ruleset；
- 生产配置；
- 外部写入接口。

本地普通只读页面不启用。

## 7. 实际会话与角色合并

逻辑角色数量不等于实际代理数量。

| 任务规模 | 建议实际会话 | 角色安排 |
|---|---:|---|
| 小型 Lane 1 | 2 | 项目/技术/实现合并；独立 Reviewer |
| 普通 Lane 2 | 3 | 项目+技术；实现；独立质量 |
| 中型跨模块 | 4 | 项目；技术；实现；独立质量 |
| Lane 3 或复杂研究 | 4～6 | 基础角色加 1～2 个专项专家 |

默认规则：

- 一个实现任务最多两个专项专家；
- 超过六个有效上下文时先拆任务；
- 不为“角色看起来完整”创建额外会话；
- 同一任务的 Review 和实现不得共用上下文；
- 项目负责人可以兼任技术负责人，但不能兼任最终 Reviewer。

## 8. 专家路由规则

AI 项目负责人按任务内容选择最小小队：

```text
普通文档、小修复、低风险测试
→ 基础小队

新页面、主要工作流
→ + 产品与交互专家

复杂图表、前端状态或已证实性能问题
→ + 前端专家

RQData、Parquet、Catalog、PostgreSQL、migration
→ + 数据与数据库专家

指标、策略、信号规则
→ + 量化研究专家

撮合、成本、换月、OOS、Walk-forward
→ + 回测可信性审计专家

Research Memory、训练、评分模型
→ + Research Memory / AI 专家

部署、恢复、备份、Runtime
→ + Runtime / SRE 专家

凭据、真实发送、外部权限
→ + 安全专家
```

路由硬规则：

1. 产品与交互专家不能只因“页面可以更漂亮”加入；
2. 数据专家不能只因增加普通字段加入；
3. 性能专家只能在有测量证据后加入；
4. Lane 3 必须有独立质量负责人；
5. 回测审计必须独立于策略提出者；
6. 三个以上专项领域意味着任务需要重新拆分；
7. 专项专家不能自行扩大 Task Charter。

## 9. Task Charter

每个独立任务开始前，由 AI 项目负责人生成最小 Task Charter。普通任务可保存在 Codex 会话或 GitHub Issue 中，不强制新增仓库文档。

```markdown
# Task Charter

## 价值
该任务解决的真实问题，以及为什么现在需要处理。

## 目标
一个可独立验收的结果。

## 当前事实
STATUS、active canonical、Issue、PR、前置任务和已知约束。

## Lane 与调度
- Lane：
- 推荐模型：
- 推理强度：
- Plan：
- 会话：
- 工作区：

## 动态小队
- AI 项目负责人：
- 技术负责人：
- 实现负责人：
- 专项专家：
- 独立质量负责人：

## 允许修改
明确目录、模块、接口或文档。

## 禁止修改
不相关模块、main、Runtime、真实数据、正式口径等。

## 验收
行为、测试、证据和结果标准。

## 外部 Gate
无 / 数据写入 / migration / release / Runtime 等。

## 完成流转
task → develop / 等待人工 Gate / final receipt。
```

只有 Lane 3、复杂跨模块、hash-bound 或长期 Gate 任务才新增 `docs/tasks/*`。

## 10. 任务状态机

```text
PROPOSED
    ↓
VALUE_CHECK
    ├── REJECTED
    └── DEFERRED
    ↓
TASK_FROZEN
    ↓
PLAN_READY
    ├── OWNER_PLAN_GATE（仅需要时）
    ↓
IMPLEMENTING
    ↓
VALIDATING
    ├── FIX_LOOP
    ↓
INDEPENDENT_REVIEW
    ├── FIX_LOOP
    ↓
EXACT_HEAD_CI
    ↓
INTEGRATE_DEVELOP
    ├── ACCEPTED（普通可逆任务）
    ↓
EXTERNAL_GATE_PENDING
    ├── OWNER_APPROVAL
    ↓
REAL_EXECUTION
    ├── FAIL_CLOSED → FIX_LOOP
    ↓
FINAL_RECEIPT
    ↓
ACCEPTED / CLOSED
```

### 10.1 自动流转

下列流程默认不逐项请求用户批准：

```text
TASK_FROZEN
→ PLAN_READY
→ IMPLEMENTING
→ VALIDATING
→ Review 修复
→ exact-head CI
→ 满足条件后集成 develop
→ ancestor/readback
→ task worktree/branch 清理
```

### 10.2 用户升级条件

仅在下列情况通知用户：

1. 目标、范围或版本主线需要改变；
2. 多种架构方向无法通过事实排除；
3. 需要真实数据、DB、删除、正式通知、release 或 Runtime Gate；
4. 正式策略、指标或回测口径需要改变；
5. 三轮修复后仍无法通过；
6. canonical、环境、身份、CI 或 review 事实发生冲突；
7. 里程碑完成，需要用户决定是否进入下一阶段。

### 10.3 三轮停止规则

同一根因最多进行三轮“实现—验证—Review”修复。三轮后仍失败时进入 `BLOCKED`，输出：

- 已验证事实；
- 失败根因；
- 已尝试方案；
- 为什么不能继续自动修复；
- 需要用户决定的问题。

该规则防止无限循环和无边界消耗。

## 11. Lane 与默认调度

### 11.1 Lane 1

适用：研究实验、低风险测试、小型行为不变修复。

默认：

```text
Terra + 中推理
Direct 或短 Plan
独立 task worktree
实现会话 + 独立 Review 会话
通过后可自动集成 develop
```

涉及 OOS、Walk-forward、泄漏、未来函数、重绘或候选晋升时升级 Sol。

### 11.2 Lane 2

适用：普通 Web、API、只读服务、文档、可回滚重构。

默认：

```text
Terra + 中推理
Plan-then-execute
独立 task worktree
项目/技术会话 + 实现会话 + Review 会话
通过后可自动集成 develop
```

跨三个以上模块、根因不明、并发/幂等/恢复或 contract 改变时升级 Sol。

### 11.3 Lane 3

适用：真实数据、migration、live、Runtime、策略/回测口径、正式通知、删除和发布。

默认：

```text
Sol + 高推理
Plan-only 起步
独立 Review
代码、测试、dry-run、隔离 migration、disabled 功能可进入 develop
真实执行必须使用专用人工 Gate
```

## 12. 权限模型

### 12.1 完全自动

- 阅读仓库和 GitHub；
- 价值分析；
- Task Charter；
- Plan；
- task branch/worktree；
- 代码、测试和文档修改；
- dry-run、fake、tmp、isolated PostgreSQL 等隔离验证；
- Draft PR；
- Review 修复；
- exact-head CI；
- 满足现有条件后自动集成 `develop`；
- 合入回读和安全清理；
- 生成阶段报告。

### 12.2 条件自动

- canonical 更新：只有职责对应的真实事实变化时；
- Lane 3 代码集成：必须默认关闭且无真实副作用；
- 真实只读诊断：任务合同明确允许且不泄漏凭据；
- 自动启动下一任务：前置任务 final acceptance 已成立，active contract 明确允许；
- Review 后修复：不得改变目标、合同或验收口径。

### 12.3 始终人工 Gate

- 改变项目长期目标或 active target；
- 正式策略、指标和信号语义；
- 回测成交、成本、资金和换月口径；
- 生产 schema migration apply；
- 真实 RQData、Parquet 和 PostgreSQL 写入；
- 删除数据、evidence、report、receipt 或 Git 历史；
- 真实企业微信发送；
- live enable；
- `main`、正式 tag 和 release；
- Runtime promotion；
- AI 或策略候选晋升；
- GitHub 权限和 ruleset。

第一版不引入 standing mandate。只有经过多轮运行证明稳定后，再单独设计 bounded delegation，且不能在本任务中顺便放开。

## 13. 个人项目复杂度 Gate

AI 项目负责人和技术负责人必须共同回答：

| 问题 | 默认处理 |
|---|---|
| 用户会在可预见阶段实际使用吗？ | 否则暂缓 |
| 是否解决已发生或明确即将发生的问题？ | 否则暂缓 |
| 能否扩展现有模块完成？ | 能则禁止新建平行系统 |
| 是否降低总体操作或维护成本？ | 否则拒绝 |
| 新状态由谁维护？ | 无明确答案则拒绝 |
| 是否容易回滚和删除？ | 否则升级风险等级 |
| 是否因未来多用户而设计？ | 是则拒绝 |
| 是否增加第二事实源？ | 是则拒绝 |

新增以下任一项必须提供复杂度说明：

```text
新服务
新数据库
新基础框架
新消息总线
新配置中心
新工作流引擎
新权限系统
新长期后台进程
```

## 14. 角色 Prompt 基线

### 14.1 AI 项目负责人

```text
你是归一量化的 AI 项目负责人。

先读取 STATUS.md、PROJECT_SOURCE.md、AGENTS.md、
docs/DEVELOPMENT.md，以及当前任务相关 canonical、Issue 和 PR。

从本地优先、单用户、个人长期维护的前提判断价值。
禁止为 SaaS、多用户、高并发或未来可能需求增加复杂度。

输出：
1. 当前判断；
2. 用户价值和是否现在应做；
3. 最小任务边界；
4. Lane、模型、Plan、会话和工作区；
5. 所需最小专家小队；
6. 前置条件、风险和验收；
7. 是否需要人工 Gate。

不得自行改变 active target、长期目标或正式策略口径。
```

### 14.2 技术负责人

```text
你是归一量化的技术负责人。

优先复用现有模块，选择最小可维护方案。
默认采用模块化单体、单一事实源和确定性流程。

必须说明：
1. 复用什么；
2. 修改什么；
3. 明确不修改什么；
4. 为什么不需要更复杂架构；
5. 风险、测试和回滚；
6. 是否触及 Lane 3 或人工 Gate。

不得以“企业级、可扩展、以后可能需要”为理由增加组件。
```

### 14.3 实现负责人

```text
你是本任务的实现负责人。

只在独立 task branch/worktree 中工作。
严格服从 Task Charter、active canonical 和允许修改范围。
先运行定向测试，按任务需要使用 TDD。

完成后输出：
- 修改摘要；
- 测试命令和真实结果；
- PR 与 exact HEAD；
- 风险和未完成项；
- 是否触及外部 Gate。

不得自行扩大范围、修改 main/runtime 或执行未批准真实操作。
```

### 14.4 独立质量负责人

```text
你是独立质量负责人，不是实现者。

基于 exact task HEAD 审查：
- 目标和范围；
- canonical 合规；
- 正确性和回归风险；
- 测试缺口；
- 复杂度和过度设计；
- 数据、策略、回测、Runtime 与 Gate 边界。

按 Critical / Important / Minor 输出 findings，
最后使用仓库允许的明确结论。
不得为了通过而放宽原验收标准。
```

### 14.5 专项专家叠加模板

```text
你是本任务的【专项领域】专家。

只分析 Task Charter 中与你领域相关的部分。
输出领域约束、推荐方案、主要风险、必要测试和禁止范围。
不得重新定义整个项目、扩大任务或代替任务负责人做最终决策。
```

## 15. 输出与通知格式

用户不需要看到每一步内部协作。阶段报告统一为：

```markdown
## 当前状态

## 已完成

## 验证证据

## 剩余风险

## 是否需要用户操作

## 自动执行的下一步
```

必须区分：

- 代码完成；
- 测试完成；
- CI 完成；
- 独立 Review 完成；
- 真实 Gate 完成；
- release 或 Runtime 完成。

不得把前一项扩写为后一项。

## 16. 失败处理

### 16.1 canonical 冲突

发现对话、Issue、旧文档和 active canonical 冲突时，停止并列出冲突，不猜测。

### 16.2 base 或 HEAD 漂移

发现 `develop`、PR head、已审查 SHA 或 packet source SHA 漂移时，保留 worktree 和分支，重新验证，不复用旧 Review 或批准。

### 16.3 环境和身份漂移

真实数据源、数据库身份、文件根、Runtime checkout 或凭据环境与合同不一致时 fail-closed。

### 16.4 测试与真实 Gate 分离

代码测试通过不代表真实写入或 Runtime 通过。真实 Gate 失败后只能修复根因并重新生成对应 evidence。

### 16.5 专家意见冲突

处理顺序：

```text
active canonical
> 任务合同
> 可复现测试和事实
> 技术负责人综合判断
> 项目所有者决策
```

不通过多数投票决定架构或可信口径。

## 17. 首轮任务组合示例

### 17.1 Task 04 收尾（历史复盘示例）

以下内容仅记录 Task 04 当时的团队路由与 Gate 边界，属于已完成工作的历史复盘，不构成新的执行授权、恢复 legacy historical Shadow 的授权，或对任何后续任务的前置条件声明。

```text
AI 项目负责人
+ 技术负责人
+ 数据与数据库专家
+ 实现负责人
+ 独立质量负责人
```

当时的自动范围：诊断、代码修复、测试、Review、PR、CI 和 `develop` 集成。

当时的人工范围：fresh packet、真实 preflight/apply/Shadow 和 final receipt 所需批准。

Task 04 已完成于 `develop`；legacy historical Shadow 现为可选/冻结历史观察，而非 Task 05 Gate。此处不授权重新执行或扩展 Task 04。

### 17.2 Task 05 可信消费者切换

Task 05 的实现属于独立 worktree；AI-TEAM-001 不采纳或修改该 worktree，以下仅是未来同类任务的角色路由示例。

```text
AI 项目负责人
+ 技术负责人
+ 实现负责人
+ 回测可信性审计专家（涉及回测时）
+ 量化研究专家（涉及信号语义时）
+ 独立质量负责人
```

代码和测试可自治推进；改变正式回测或信号语义时保留人工 Gate。

### 17.3 Web 工作台改版

```text
AI 项目负责人
+ 产品与交互专家
+ 技术负责人
+ 全栈/前端实现负责人
+ 独立质量负责人
```

不单独建立产品、UI、UX、前端经理等多个常驻角色。

### 17.4 苏冰策略研究

```text
AI 项目负责人
+ 量化研究专家
+ 技术负责人
+ 实现负责人
+ 回测可信性审计专家
+ 独立质量负责人
```

策略提出、实现和可信性审计必须分离。研究结果不能自动晋升正式版本。

## 18. 最小落地形态

第一版只增加以下资产：

1. 本设计文档；
2. 四个基础角色 Prompt 或 Codex Skill；
3. 专项专家叠加 Prompt；
4. Task Charter 模板；
5. 专家路由表；
6. 阶段报告模板；
7. 针对越权、错误路由和状态扩写的工程测试。
8. 一个只读 Task Charter CLI：读取结构化输入，仅向 stdout 输出结果。

继续复用：

- Codex App；
- 现有 GitHub connector；
- task worktree；
- PR 和 CI；
- 独立 Review；
- 现有 Gate 脚本；
- `STATUS.md` 和 active canonical。

第一版不增加运行时服务或数据库。

该 CLI 不是新的控制面，也不执行工作流自动化：不得创建或清理 worktree，不得调用 Git 或 GitHub，不得检查或合并 PR，不得执行 CI/Review 编排，且不得产生除 stdout 外的副作用。这些能力继续由既有工具承担，或留待后续独立阶段与批准。

## 19. 分阶段实施

### Phase 0：设计冻结

- 用户复核本设计；
- 修正角色、路由和 Gate 边界；
- 不修改现有开发权限。

### Phase 1：Prompt 与模板

- 实现四个基础角色；
- 实现专项专家叠加模板；
- 实现 Task Charter 和阶段报告；
- 实现只读 Task Charter CLI：读取结构化输入，仅向 stdout 输出；
- 添加最小政策测试；
- 默认由用户手动启动总调度会话。

Phase 1 的 CLI 不创建 worktree、不调用 Git/GitHub、不检查或合并 PR、不清理 worktree，也不执行任何工作流自动化；这些仍是既有工具或后续独立阶段的职责。

### Phase 2：历史复盘与受控试运行

Phase 1 merged through PR #98 at `develop@0867e123`; Phase 2 is implemented under Issue #99 on its task branch and remains pending Draft PR exact-head review, CI, and merge. Phase 2 did not adopt or modify the then-active Task 05 worktree; Task 05 later merged independently through PR #100. Before Draft PR / integration, exact-head compatibility and integration against current `origin/develop` must be rechecked. That independent merge cannot be retroactively counted as Phase 3 because the Charter metrics and implementation/final-review context separation were not recorded from task start. Phase 2 evidence does not reopen Task 04 or authorize Phase 3 execution, Phase 4/5 automation/delegation, `main`, release, Runtime, data writes, or notifications.

- 以已完成的 Task 04 作为历史复盘样本，检验角色路由是否与其事实一致；
- 在新的、独立批准任务中记录实际会话数、用户打断数、修复轮次和集成时间；
- 不重新执行 Task 04，不改变真实数据 Gate。

### Phase 3：新的普通可逆工程试运行

- 必须从一个新的独立普通可逆任务开始，创建新的 Issue 和 task worktree，并在开始时冻结 Charter；
- 从任务开始记录 Charter 指标，并保持实现与最终 Review 的上下文分离；
- PR #100 不能追认为该试运行；
- 验证普通开发能否从 Task Charter 自治到 `develop`；
- 检查是否存在过度设计和专家滥用；
- 根据证据调整路由规则。

### Phase 4：有限 CLI automation

只有在 Phase 1～3 证明流程稳定、重复且机械，并在独立任务中取得新的批准后，才考虑仓库内可审查的 CLI 编排。该阶段不属于 AI-TEAM-001；在获得该批准前，以下能力继续由既有工具承担：

- 创建 task worktree；
- 记录角色分配；
- 检查 PR/CI/Review；
- 合入回读和清理；
- 输出结构化阶段报告。

不得构建对话归档、长期代理服务或新的任务数据库。

### Phase 5：可选 bounded delegation

只有长期证据表明人工 Gate 频繁且高度重复时，才单独设计 standing mandate。其设计必须是 scope-bound、time-bound、hash-bound、operation-bound，并继续排除 release、Runtime、删除和策略晋升。

## 20. 验收指标

### 20.1 组织效率

- 普通任务用户中途操作次数；
- 从 Task Charter 到 `develop` 的周期；
- 自治完成率；
- 每个任务实际会话数；
- Review 修复轮次。

### 20.2 质量

- exact-head CI 和 Review 一致率；
- 合入后回归失败率；
- 越权操作被 Gate 阻止的比例；
- canonical 状态扩写错误；
- 三轮停止规则是否生效。

### 20.3 复杂度

- 新服务、新数据库和新后台进程数量应保持为零，除非有独立批准；
- 每个任务专项专家通常不超过两个；
- 普通任务不新增 `docs/tasks/*`；
- 不新增第二状态源；
- 不因多用户或 SaaS 假设增加代码。

### 20.4 第一版成功标准

第一版在历史 Task 04 复盘与独立批准的 Task 05 试运行后应达到：

- 普通代码修复、测试、Review 和 `develop` 集成无需用户逐步确认；
- 真实 Gate 仍准确保留；
- 专家路由没有显著增加任务耗时；
- 产品和技术角色至少阻止一次低价值扩展或过度架构；
- 用户收到的报告能够明确区分代码、测试、真实 Gate 和发布状态。

## 21. 已拒绝方案

### 21.1 固定全员专家团

拒绝原因：每个任务都召集产品、设计、架构、前端、后端、数据库和测试，会产生过多协作开销，不适合个人项目。

### 21.2 完整虚拟软件公司

拒绝原因：需要新的控制面、部门状态、任务数据库和多层代理管理，系统建设成本高于当前业务收益。

### 21.3 仅为 Task 04 定义数据专家组

拒绝原因：无法覆盖长期 Web、策略、回测、Research Memory、AI 和 Runtime 工作，也会在任务切换时反复重建角色。

## 22. 最终决策

采用“归一量化精简矩阵式 AI 研发团队”：

```text
四个基础角色提供完整研发视角
+ 专项专家按需加入
+ 实际会话保持最少
+ 产品负责人负责做减法
+ 技术负责人负责控制复杂度
+ 实现与 Review 上下文独立
+ GitHub 与 canonical 提供事实
+ 可逆开发自动完成
+ 不可逆操作保留人工 Gate
```

本设计批准后，下一步是编写独立实施计划；实施计划只能落地 Prompt、模板、路由和政策测试，不得顺便建设新的多代理平台或扩大真实执行权限。
