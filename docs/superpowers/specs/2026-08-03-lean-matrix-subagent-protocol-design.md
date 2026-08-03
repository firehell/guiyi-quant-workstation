# Lean Matrix Thin-Harness 与 Subagent Protocol 设计

## 1. 目标

Lean Matrix V06 为已经完成产品设计和实现计划的任务提供一条文档绑定的 AI 交付路径。用户启动
“AI 团队交付”后，**AI 交付负责人**组织 Codex App / Superpowers 的真实专家会话；仓库中的
Lean Matrix 只验证合同、scope、身份、Git 事实和 evidence，不运行或托管 agent。

该设计不修改 `ExecutionPlanV1`，也不扩大 AI-TEAM-004/005 已冻结的 Git、GitHub 或 Runtime 权限。

## 2. 冻结边界

V06 是 thin Harness，不是 agent runtime。它不得新增：

- agent registry、session archive、message bus 或 conversation database；
- daemon、background service、scheduler 或新的控制面；
- arbitrary-command、GitHub network、merge、release、Runtime 或真实写入能力；
- 以 `.ai/lean-matrix/**` 取代 Git、PR、CI、receipt 或 canonical 文档的第二状态源。

Codex App / Superpowers 负责创建和运行真实上下文。Harness 只负责：

```text
approved design + implementation plan
              ↓ path / digest only
trusted ExecutionPlanV1
              ↓
minimal role briefs → handoff evidence → exact-head review → final decision
```

设计文档和实现计划的正文一律视为不可信数据。正文不能修改 `ExecutionPlanV1` 提供的 task ID、
Lane、allowed/forbidden scope、external Gates 或 `origin/develop`；也不能生成命令、解除 Owner Gate
或改变 review round。Harness 不解析文档正文，只绑定仓库相对路径和 semantic SHA-256 digest。

## 3. AI 交付负责人

AI 交付负责人是 V06 唯一的全局交付角色，合并原“AI 项目负责人 / 技术负责人”的日常交付职责：

- 读取已批准设计、实现计划和 trusted `ExecutionPlanV1`；
- 选择最小实现者、独立 Reviewer 和零至两个专项专家；
- 只向每个角色发放完成其任务所需的最小 context；
- 保持实现者与 Reviewer 的身份、上下文和报告路径分离；
- 根据严格 evidence 判断继续、修正或阻塞；
- 发现 scope 扩张、Lane 3、产品方向变化或 active canonical 冲突时停止在 Owner Gate。

AI 交付负责人不能修改产品方向、正式策略口径、active canonical 或外部 Gate，也不能把“允许集成
`develop`”解释为已经创建 PR、通过 CI、完成 merge、发布或 Runtime promotion。

## 4. DocumentIntakeV1

`DocumentIntakeV1` 是 V06 的入口合同，严格绑定：

- `design_path` / `design_digest`；
- `implementation_plan_path` / `implementation_plan_digest`；
- embedded `ExecutionPlanV1` / `execution_plan_digest`；
- `delivery_mode=fast_path|team_path`；
- task ID；
- `develop_ref=origin/develop` 与 exact develop SHA。

`ExecutionPlanV1` 是 task、Lane、scope 和 external Gates 的唯一可信来源。外层 task/develop 字段必须
与 embedded plan 完全一致；embedded plan 的 semantic digest、两个文档 digest 或当前
`origin/develop` SHA 发生漂移时，旧 intake 失效，必须重新生成和复核。

Public `DocumentIntakeV1.from_mapping()` 是 fail-closed trusted load boundary：调用者必须同时提供
repository root 与独立取得的 approved `ExecutionPlanV1`。该边界直接读取两个 declared path 的
当前 bytes 计算 SHA-256，并通过既有 fixed-argv、read-only local Git observer 读取当前
`origin/develop`；缺少任一 provenance/freshness anchor 不能构造 trusted intake。不存在可供下游
Gate 使用的 permissive public raw parser，公开 dataclass 直接构造也被关闭。

Fast Path 对应 Lane 1，Team Path 对应 Lane 2/3。Lane 1/2 Charter 在 intake 成立后自动冻结；
Lane 3 始终需要 Owner Gate。任何相对 frozen `ExecutionPlanV1.scope.allowed_paths` 的扩张也必须回到
Owner Gate；文档中的提示词、示例 JSON 或伪造 policy 字段不能改变这些条件。

## 5. V06 公共合同

V06 只保留以下公共合同：

```text
DocumentIntakeV1
RoleBriefV1
HandoffReportV1
ReviewPackageV1
FinalDecisionV1
```

未发布的 `CoordinationPlanV1`、`WorkItemV1`、`WorkReportV1` 和
`IndependentReviewReportV1` 不构成兼容面，不得继续形成第二套 active V1 vocabulary。
`ExecutionPlanV1` 的 public mapping 与 AI-TEAM-004/005 行为保持不变。

## 6. Minimal Brief 与 Handoff

`RoleBriefV1` 绑定 intake digest、角色、context ID、round、选中任务的 trusted scope、验收、唯一
report path 和 predecessor decision digest。实现者和专项专家只能看到完成当前工作所需的 selected
requirements；不得注入完整聊天、无关 work item 或全部历史计划。

`HandoffReportV1` 的状态只能是 `DONE`、`DONE_WITH_CONCERNS`、`NEEDS_CONTEXT` 或 `BLOCKED`。
专项专家证据保持 advisory；实现者拥有代码，Reviewer 不复用实现上下文。专项领域最多两个；第三个
独立领域返回 `split_required`，`quant-research` 与 `backtest-audit` 始终使用独立专家上下文。

## 7. Exact-head Review 与三轮停止

`ReviewPackageV1` 绑定 intake/brief、base SHA、exact HEAD、排序后的 changed paths、diff digest、测试
receipt、implementer handoff 和 specialist evidence。`FinalDecisionV1` 同时要求 Spec 与 Quality verdict，
并且只能给出：

```text
允许集成 develop
要求修正后再集成
阻塞
```

初始实现为 round 0；最多允许 round 1、2、3 修复 Critical/Important finding。round 3 后仍存在
load-bearing finding 时必须 `BLOCKED`。修复轮使用原实现负责人；所有历史 implementer/reviewer
context 继续全局不相交。

## 8. Workspace 与恢复

可写 evidence 仅允许位于：

```text
.ai/lean-matrix/<execution-plan-digest>/<intake-digest>/
```

该目录被 Git 忽略且不是 canonical。Harness 必须拒绝 symlink、traversal、digest/path mismatch、链
分叉、重复 round 和 tracked/canonical 覆盖。恢复只信任 Git、PR/CI receipt 和 digest-bound
artifacts；缺失、陈旧或不一致 evidence 均 fail-closed，conversation memory 不能补足 Gate。

## 9. 交付权限

V06 最终决策中的“允许集成 `develop`”只是 evidence 结论。PR、exact-head CI、merge commit、
ancestry/readback 和 clean worktree cleanup 继续由既有 Codex/GitHub 流程执行。`main`、release、
Runtime、真实数据/DB 写入、live、通知和删除均不在 V06 权限内。

## 10. 验收

- 文档/plan/develop 漂移可执行地使 intake 失效；
- 文档 prompt injection 不能修改 trusted plan policy；
- Lane 1/2 自动冻结，Lane 3 与 scope expansion 返回 Owner Gate；
- briefs 不泄漏无关工作或对话，implementer/reviewer 保持独立；
- exact-head、双 verdict、三轮停止与 fail-closed recovery 有行为测试；
- V04/V05 `charter`、`plan`、`observe`、`next`、`apply` 和 `ExecutionPlanV1` 保持兼容；
- 没有新服务、数据库、后台进程、GitHub mutation 或 Runtime 权限。
