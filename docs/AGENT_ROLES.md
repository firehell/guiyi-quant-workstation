# 项目子代理角色清单

本页是归一量化八类常用子代理的职责、分派输入与交付格式的唯一入口。角色按任务调用，不要求每次全部参与，
小任务可由主代理直接完成。本页不注册宿主子代理、不创建线程、不启用后台任务，也不增加新的业务合同或审批流程。

执行授权与停止条件统一遵循 [AGENTS.md](../AGENTS.md)；当前阶段、运行身份与待完成事项只读
[STATUS.md](../STATUS.md)。模型选择引用 [开发流程中的模型调度](DEVELOPMENT.md#codex-模型调度)，
不在各角色下复制模型表。技能提供操作方法，角色负责一次具体分派的执行与结果。

## 主代理与协作

主代理理解 owner 目标，核对仓库与现场，划分范围和依赖，分派必要角色，处理冲突，并核对整体交付。
子代理只承担收到的任务范围；真实操作是否允许由交办目标及既有合同决定，角色名称和本清单不产生授权，
已交办范围内也不因分派或换会话重复申请批准。GPT 方案交接与 Gate 的处理统一引用
[交接规则](../AGENTS.md#gpt-讨论与-codex-交接)及[验证规则](../AGENTS.md#任务授权与验证-gate)，
子代理发现技术阻断先取证，不把它改写成请求 owner 批准跳过。

- 分派前明确文件/模块的修改归属、工作区和共享资源。独立工作可并行；共享文件修改按依赖交接，
  生产补数、生产数据库写入、Runtime 切换及存在共享锁冲突的操作串行。隔离方式按冲突与风险选择，不固定要求新工作树。
- 实现者负责定向测试和自审；验证代理承担另行分派的验收，不能成为实现者跳过验证的理由。
  独立 Review 由未参与该改动实现的代理执行，提供同一候选的实际 diff 与证据。
- 子代理返回结果后，主代理核对 commit/diff、命令输出和适用现场证据，再决定任务是否完成。
  候选变化后复核受影响的验证与 Review，旧结论不自动覆盖新候选。
- 子代理遇到阻断时说明受影响范围，继续其余独立工作；重要取舍交主代理汇总，只有符合
  AGENTS 的停止条件才请 owner 决定。提交、集成和外部操作由分派明确执行者，避免双方重复执行。

## 统一分派输入

使用一条清楚的任务消息即可，不强制生成新 Spec、Plan、manifest 或 receipt。主代理提供：

| 输入 | 内容 |
|---|---|
| 目标与出口 | 要解决的问题、允许的动作，以及可检查的验收标准 |
| 精确基线 | 仓库、branch、worktree、HEAD；Review 另给比较基线与候选 commit/diff |
| 修改归属与限制 | 可修改文件/模块、已有 dirty paths、其他任务归属；是否只读、仅编码或包含真实执行 |
| 合同与上下文 | 下表对应入口、当前任务相关 accepted canonical、已有证据与已完成步骤；避免让子代理从聊天推测合同 |
| 验证与交接 | 相关测试入口、依赖角色、预期交回内容；涉及现场时给明确环境、对象和资源边界 |

子代理开始前自行核对实际状态；身份或范围不一致先反馈，不能把分派消息中的旧状态当成当前事实。

## 八类常用角色

| 标识与角色 | 职责与常见任务 | 合同及技能入口 | 在统一交付中补充 |
|---|---|---|---|
| `market-data` 行情数据 | 缺口/质量审计、MainContractMap 与 Session 检查、预热依赖、分钟派生、精确恢复批次及 MDS 读回；不承担策略或账户语义 | [数据合同](DATA_CENTER.md)、[Catalog](../openspec/specs/data-foundation-metadata/spec.md)、[Canonical](../openspec/specs/canonical-market-storage/spec.md)、[维护](../openspec/specs/historical-data-maintenance/spec.md)、[查询](../openspec/specs/market-series-query/spec.md)、[futures-data 技能](../.agents/skills/futures-data/SKILL.md) | 品种/物理合约/周期/窗口、缺口原因、精确计划及实际发布/读回结果；未请求、未提交、结果未知分别表达 |
| `strategy-formula` 策略与公式 | Newow/SuBing/HTDY 指标与状态机、公开公式逐值比较、期货输入适配、参考交易配对；不自行扩为账户或策略晋升 | [指标内核](INDICATOR_KERNEL.md)、[Newow 合同](../openspec/specs/newow-product-reference-trading/spec.md)、[SuBing/Alert 合同](../openspec/specs/subing-ths-alert/spec.md)、[ReferenceTrading 合同](../openspec/specs/reference-trading/spec.md)、[当前来源研究入口](research/newow-current-review.md) | 来源冻结身份、原公式/期货适配/自有候选的差异、受影响版本、确定性与时序验证、尚缺证据；页面一致性与因果研究分别结论 |
| `backend` 后端工程 | API、DTO、CLI、应用仓储、缓存、分页、幂等、恢复与性能；行情算法和策略规则由对应角色负责 | [Active Architecture](ARCHITECTURE.md)、[开发定位](DEVELOPMENT.md#按任务定位)、[相关领域 OpenSpec](../openspec/specs/)、[测试入口](../TESTING.md) | 接口/存储影响、兼容性、失败恢复与相关测试；代码、隔离迁移和生产迁移是否执行分别说明 |
| `web-chart` Web 与图表 | 布局、图层、切换、快照绑定、记录定位、加载与故障状态、移动端体验；不在前端重算服务端业务事实 | [产品边界](../PROJECT_SOURCE.md)、[Active Architecture](ARCHITECTURE.md)、[Newow 合同](../openspec/specs/newow-product-reference-trading/spec.md)、[首页合同](../openspec/specs/market-home-overview/spec.md)、[测试入口](../TESTING.md) | 交互变化、品种/策略/周期与快照身份、实际浏览器场景和代表性截图；fixture 与真实后端验收分开 |
| `validation` 验证与验收 | 按影响选择测试、隔离集成、浏览器/API 对照和品种×周期×策略矩阵；不兼任独立 Review，不放宽断言制造通过 | [按影响验证](DEVELOPMENT.md#按影响验证)、[TESTING](../TESTING.md)、被验收功能的对应 canonical | 候选/环境/数据身份、实际命令与退出结果、覆盖矩阵、跳过/失败原因及未覆盖项；需要修复时交回归属角色或由主代理重新分派 |
| `review` 独立 Review | 对固定候选的数据时序、公式、并发、迁移、执行安全等风险作独立检查；普通改动是否需要调用由风险决定 | [Review 与交付规则](../AGENTS.md#验证与交付)、[Active Architecture](ARCHITECTURE.md)、候选对应 canonical；需要代码审查方法时使用当前会话可用的 `code-review` 技能 | 比较基线、候选身份、已检查范围；按 `Confirmed Issue`、`Risk / Needs Verification`、`Optional Improvement` 分类，重要项给证据、触发、影响与验证建议；无确认问题也说明验证局限 |
| `release-runtime` 发布与 Runtime | 候选身份/版本检查、main/tag/Release、构建部署、切换读回、适用自然验收与旧发布树清理；仅执行分派覆盖的阶段 | [release-agent 技能](../.agents/skills/release-agent/SKILL.md)、[部署合同](../deploy/README.md)、[当前状态](../STATUS.md)、[测试入口](../TESTING.md) | candidate/tag/commit、实际运行 root/commit、所执行阶段、服务/HTTP/health 读回和自然业务缺口；已发布、已切换、自然验收分别结论 |
| `docs-maintenance` 文档与工程维护 | 文档职责与导航、失效引用、版本入口、被取代计划清理、死代码候选与依赖/脚本整理；不按无静态入边就删除运行或恢复入口 | [文档与版本入口](DEVELOPMENT.md#文档与版本的唯一入口)、[Active Architecture](ARCHITECTURE.md)、[产品边界](../PROJECT_SOURCE.md)、[测试入口](../TESTING.md) | 收敛后的权威入口、删除依据与消费者检查、引用/diff/secret 检查；涉及代码时追加适用回归，保留来源与失败恢复 evidence |

表中的领域入口按本次任务选择，不要求无关角色全量读取。其他技能从当前会话技能目录选择，先读取适用说明；
不把用户机器上的技能绝对路径固化成项目合同，也不为每个角色复制一份 SKILL.md。

## 统一交付格式

各角色使用以下字段交回主代理，可写成短段落或列表；不适用项标明“不适用”，不为填满格式制造额外产物。
状态含义遵循 [AGENTS.md](../AGENTS.md#验证与交付)，只报告实际证据支持的阶段。

```text
结论：本次任务达到的阶段；未完成或阻断的部分。
身份与范围：角色、实际基线/候选、工作区；实际处理范围及归属变化。
结果：关键改动/发现、文件或证据入口；commit，以及是否已 push/集成/真实执行。
验证：实际命令、环境、结果与覆盖范围；未运行、跳过和失败项。
剩余：风险、未完成 Gate、未知结果及其影响；涉及 mutation 时说明恢复与安全重试边界。
交接：唯一最小下一步、负责角色；需要主代理或 owner 决定的具体事项（若有）。
```

Review 发现和领域补充直接放在上述字段下；截图、矩阵、报告或 receipt 优先链接已有产物。
只读分析可以交付“已定位、证据不足或阻断”，不能为了标完成而变成代码修改或生产操作。
自然业务尚未发生时交回待观察项，不默认创建定时监控、发送通知或持续后台运行。

## 常见分派方式

| 任务 | 角色组合与顺序 |
|---|---|
| 小型文档/工程修正 | 主代理直接处理，或分派 docs-maintenance；按影响自审与验证 |
| 页面问题 | web-chart 定位/实现；API 合同或服务问题交 backend；复杂交互另分派 validation |
| 数据不足/质量异常 | market-data 先审计；任务包含修复时按精确批次执行，再独立读回；代码高风险变化追加 review |
| 公式/参考交易变化 | strategy-formula 实现并验证；高风险变更交 review，适用组合交 validation；修复后核对新候选 |
| 发布/上线 | 已验证候选交 release-runtime；按交办范围分别完成发布、切换和验收，缺失自然证据明确交回 |

角色清单不固定任务数量、线程数量或工序；是否并行、独立 Review 和扩展验证继续按
[开发流程](DEVELOPMENT.md) 与实际风险选择。未来研究或架构任务仍按具体目标分派，本清单只固定以上八类常用角色。
