# 归一量化任务状态机与任务单模板

> 团队名称：归一量化产品与交付工作站
> 配套文档：`ROLE_SPEC.md`（12 角色）、`TASK_MATRIX.md`（18 类任务）
> 文档版本：v1.0
> 状态：已建立，作为任务流转与任务单的统一规范
> 生成时间：2026-07-09

---

## 1. 状态机总图

```text
IDEA
  │  PM 编号 + 任务单草稿
  ▼
REQUIREMENT_READY  ── 用户确认 PRD / 验收目标
  │
  ▼
PLAN_READY  ── 用户批准 plan（CodeBuddy 调 Codex 只读 plan）
  │
  ▼
APPROVED_DEV  ── 后端产出 Dev / Exec Prompt，准备开发
  │
  ▼
CODING  ── CodeBuddy 调 Codex 开发（默认 dry-run）
  │
  ▼
TESTING  ── CodeBuddy 跑测试，QA 出验收结论
  │
  ▼
DELIVERY_READY  ── 用户最终 review / merge / deploy
  │
  ▼
CLOSED

失败分支：
CODING / TESTING / DELIVERY_READY ──不通过──▶ FAILED
FAILED ──用户决定重规划──▶ REPLAN ──▶ PLAN_READY
FAILED ──用户放弃──▶ IDEA / 丢弃
```

**推进责任速查表**

| 状态 | 必须由我人工确认 | 可交给 WorkBuddy | 可交给 CodeBuddy | 可交给 Codex CLI |
|---|---|---|---|---|
| IDEA | 提出想法 | 编号 / 起草骨架 | — | — |
| REQUIREMENT_READY | 确认 PRD | PO / 各角色产出 | — | — |
| PLAN_READY | 批准 plan | 架构 / 后端 / 安全审 Prompt | 调 Codex 只读 plan | 只读 plan |
| APPROVED_DEV | review Prompt（plan 已批） | 后端出 Dev/Exec Prompt | 准备执行入口 | 待命 |
| CODING | 真实写入/发送授权 | 监督 / 卡点跟踪 | 调 Codex 开发 | 执行开发 |
| TESTING | 知会 / 真实 smoke 授权 | QA / 安全审敏感 | 跑测试 | 修 bug（授权内） |
| DELIVERY_READY | 最终 review / merge / deploy | 交付专家出报告 | 部署需用户授权 | — |
| CLOSED | merge / deploy 为用户操作 | PM 归档 | 部署执行（授权后） | — |
| FAILED | 决策回滚 / 重规划 / 放弃 | PM 记录原因 | 回滚执行（授权） | — |
| REPLAN | 批准新 plan | 架构 / 后端重规划 | 调 Codex 只读 replan | 只读 replan |

---

## 2. 各状态详细规则

### 状态 1 · IDEA
1. **定义**：用户原始想法 / 需求雏形，尚未结构化。
2. **允许谁推进**：项目经理（PM）负责编号并拉起任务单草稿；用户提出。
3. **进入条件**：用户提出一个想法 / 需求，或内部复盘产生新任务。
4. **退出条件**：产出初始任务单草稿（背景 / 目标雏形 + 任务类型初判），转 REQUIREMENT_READY。
5. **必备产物**：任务编号 `GQ-YYYYMMDD-NNN`、一句话想法记录。
6. **人工确认**：用户提出想法即默认；进入下一状态前由用户认可需求方向。
7. **WorkBuddy**：可起草任务单骨架、编号、归类任务类型。
8. **CodeBuddy**：否（无代码）。
9. **Codex CLI**：否。
10. **失败回滚**：想法不可行 → 留在 IDEA 或丢弃，不进 FAILED（FAILED 仅用于开发后）。

### 状态 2 · REQUIREMENT_READY
1. **定义**：产品需求已明确，含场景、边界、不做事项、验收目标。
2. **允许谁推进**：产品负责人（PO）主导；PM 维护状态；用户确认。
3. **进入条件**：任务单含 PRD（背景 / 目标 / 场景 / 边界 / Non-goals / 验收目标）。
4. **退出条件**：PRD 被用户确认，转 PLAN_READY（架构 / 技术方案起草）。
5. **必备产物**：PRD、验收目标、任务类型、参与角色清单（参照 TASK_MATRIX）。
6. **人工确认**：**必须** — 用户确认 PRD 与验收目标。
7. **WorkBuddy**：PO 产出 PRD；量化业务专家补业务规则；UX 出展示要求；安全出权限要求。
8. **CodeBuddy**：否。
9. **Codex CLI**：否。
10. **失败回滚**：需求歧义 → 在 REQUIREMENT_READY 内返工（不进 FAILED）；若用户放弃 → IDEA / 丢弃。

### 状态 3 · PLAN_READY
1. **定义**：技术方案 / 架构方案完成，产出 Codex Plan Prompt，待用户批准开发。
2. **允许谁推进**：量化架构师 + 后端开发负责人（出 Plan Prompt）；PM 状态；用户批准。
3. **进入条件**：PRD 已确认 + 架构 / 技术方案草案 + Codex Plan Prompt 草稿。
4. **退出条件**：用户批准 plan，转 APPROVED_DEV。
5. **必备产物**：架构方案、模块边界、接口契约、Codex Plan Prompt、测试点初稿。
6. **人工确认**：**必须** — 用户审阅并批准 plan（对应流程：CodeBuddy 调 Codex 只读 plan → 我确认 plan）。
7. **WorkBuddy**：架构师出方案、后端出 Plan Prompt、测试出测试策略、安全审 Prompt 护栏。
8. **CodeBuddy**：可调 Codex CLI 做**只读 plan**（分析仓库、产出方案，不写代码）。
9. **Codex CLI**：执行**只读 plan**（分析，不修改代码）。
10. **失败回滚**：plan 不满足 → REPLAN → PLAN_READY（重新规划，不进 FAILED）。

### 状态 4 · APPROVED_DEV
1. **定义**：plan 已批准，开发任务拆分完成，等待进入开发。
2. **允许谁推进**：PM + 后端开发负责人（拆任务、出 Dev / Exec Prompt）；用户已批准。
3. **进入条件**：PLAN_READY 被用户批准；后端产出 Codex Dev Prompt + CodeBuddy Exec Prompt。
4. **退出条件**：开发开始（CodeBuddy 调 Codex 开发），转 CODING。
5. **必备产物**：Codex Dev Prompt、CodeBuddy Exec Prompt、开发步骤清单、测试点。
6. **人工确认**：进入本状态即代表用户已批准 plan（批准动作在 PLAN_READY→APPROVED_DEV 边界）；本状态内用户可最后 review 两类 Prompt。
7. **WorkBuddy**：后端出两类 Prompt、PM 排期。
8. **CodeBuddy**：准备执行入口（接收 Dev Prompt）。
9. **Codex CLI**：待命。
10. **失败回滚**：Prompt 有问题 → REPLAN → PLAN_READY。

### 状态 5 · CODING
1. **定义**：Codex CLI 经 CodeBuddy 执行开发，产生代码变更。
2. **允许谁推进**：CodeBuddy（调 Codex）、Codex CLI（写代码）；PM 跟踪；后端监督。
3. **进入条件**：APPROVED_DEV + CodeBuddy 调 Codex 开始开发。
4. **退出条件**：代码写完 + 本地自检（ruff / lint / `git diff --check`）通过，转 TESTING。
5. **必备产物**：代码变更、dry-run 默认、git diff --check 通过、提交（**未 merge**）。
6. **人工确认**：开发过程不需逐行确认；但**真实写入 / 发送 / 外部动作需用户显式授权**（贯穿全程）。
7. **WorkBuddy**：不直接写代码；后端监督、PM 跟踪卡点。
8. **CodeBuddy**：**是** — 本地执行入口，调 Codex CLI 开发。
9. **Codex CLI**：**是** — 执行开发。
10. **失败回滚**：代码不达标 / 偏离 → FAILED（不自动回滚代码，等用户决策）→ REPLAN → PLAN_READY。

### 状态 6 · TESTING
1. **定义**：测试专家执行测试策略，验证信号 / 数据 / 告警 / 稳定性。
2. **允许谁推进**：测试专家（QA）主导；CodeBuddy 跑测试；Codex 可修 bug。
3. **进入条件**：CODING 完成 + 代码自检通过。
4. **退出条件**：测试通过（pass）+ 验收结论，转 DELIVERY_READY；不通过 → FAILED。
5. **必备产物**：测试报告、验收结论（pass / block）、回归结果、dry-run 验证记录。
6. **人工确认**：测试结论由 QA 出；重大阻塞需知会用户；真实 smoke 需授权。
7. **WorkBuddy**：QA 出测试策略 / 结论、安全审敏感、PM 跟踪。
8. **CodeBuddy**：**是** — 跑测试、返回结果。
9. **Codex CLI**：**是** — 修测试发现的 bug（用户授权范围内）。
10. **失败回滚**：验收不通过 → FAILED。

### 状态 7 · DELIVERY_READY
1. **定义**：测试通过，交付报告与合并前检查就绪，等待用户 review / merge / deploy。
2. **允许谁推进**：交付专家主导；PM 状态；用户最终 review。
3. **进入条件**：TESTING pass + 交付报告 + 合并前检查清单。
4. **退出条件**：用户 review 完成并 merge / deploy，转 CLOSED；或用户打回 → FAILED / REPLAN。
5. **必备产物**：交付报告、合并前检查、上线 / 回滚步骤、下一阶段建议。
6. **人工确认**：**必须** — 用户最终 review、merge、deploy（WorkBuddy 不代执行）。
7. **WorkBuddy**：交付专家出报告、安全出护栏检查、PM 归档准备。
8. **CodeBuddy**：否（除非用户授权部署；部署需用户确认）。
9. **Codex CLI**：否。
10. **失败回滚**：用户打回 / 验收未达 → FAILED 或 REPLAN。

### 状态 8 · CLOSED
1. **定义**：任务完成，已 merge / deploy，状态归档。
2. **允许谁推进**：PM 归档；用户确认完成。
3. **进入条件**：DELIVERY_READY + 用户 merge / deploy 完成。
4. **退出条件**：任务结束；或发现遗漏 → 新 IDEA / REPLAN。
5. **必备产物**：归档任务单、交付报告、changelog。
6. **人工确认**：merge / deploy 为用户操作；归档可由 PM 做。
7. **WorkBuddy**：PM 归档、复盘。
8. **CodeBuddy**：部署执行（用户授权后）。
9. **Codex CLI**：否。
10. **失败回滚**：线上问题 → 新 IDEA 或 REPLAN（不自动回滚）。

### 状态 9 · FAILED
1. **定义**：开发 / 测试 / 交付未达预期，需回滚或重新规划。
2. **允许谁推进**：PM 标记；用户决策；相关角色排查。
3. **进入条件**：CODING / TESTING / DELIVERY 任一不通过且需返工。
4. **退出条件**：决定重新规划 → REPLAN；或放弃任务 → 回 IDEA / 丢弃。
5. **必备产物**：失败原因记录、影响范围、是否需回滚代码。
6. **人工确认**：**必须** — 用户决定回滚 / 重规划 / 放弃。
7. **WorkBuddy**：PM 记录、各角色出原因。
8. **CodeBuddy**：回滚执行（用户授权，如 `git revert`）。
9. **Codex CLI**：否（修 bug 属 REPLAN 后）。
10. **回滚规则**：**不自动回滚**；用户确认后 CodeBuddy 执行 `git revert` / `checkout`；live 状态 / 数据不自动删；回滚范围限定本次变更。

### 状态 10 · REPLAN
1. **定义**：重新规划技术方案，回到 PLAN_READY。
2. **允许谁推进**：架构师 + 后端（出新 Plan Prompt）；PM；用户批准。
3. **进入条件**：FAILED 后用户决定重规划。
4. **退出条件**：新 plan 起草完成 → PLAN_READY。
5. **必备产物**：失败复盘、修订后的架构 / Plan Prompt、变更点。
6. **人工确认**：新 plan 仍需用户批准（回到 PLAN_READY 批准边界）。
7. **WorkBuddy**：架构师 / 后端重规划、安全重审护栏。
8. **CodeBuddy**：可调 Codex 做**只读 replan**。
9. **Codex CLI**：**只读 replan**（分析，不写代码）。
10. **重规划规则**：基于失败原因；不扩大范围；明确本次改动边界；复用既有测试与护栏。

---

## 3. 标准任务单模板

> 用法：复制以下模板，替换 `{{ }}` 占位符；状态流转按第 2 节规则推进；参与角色按 `TASK_MATRIX.md` 选取；所有 Prompt 由后端开发负责人产出，安全专家过护栏。

```markdown
# TASK-{{日期}}-{{编号}}：{{任务名称}}

## 1. 任务状态
{{ IDEA / REQUIREMENT_READY / PLAN_READY / APPROVED_DEV / CODING / TESTING / DELIVERY_READY / CLOSED / FAILED / REPLAN }}

## 2. 任务类型
{{ 普通功能开发 / 数据模块开发 / 实时行情监听 / 多周期聚合 / 策略开发 / 策略研究与验证 / 企业微信告警 / Dashboard / 回测模块 / 数据质量检查 / Mac mini 部署 / AI 工作流优化 / 三工具协作优化 / GitHub 版本管理 / 安全权限 / 测试体系 / 交互视觉规范 / 阶段交付复盘 }}
参照：TASK_MATRIX.md

## 3. 参与角色
- 必须：{{ PM, PO, ... }}（按 TASK_MATRIX 必须列）
- 可选：{{ ... }}
- 不需要：{{ ... }}

## 4. 背景
{{ 为什么做、来源想法、关联历史任务 / Stage }}

## 5. 目标
{{ 可量化 / 可验收的产出 }}

## 6. 不做事项
{{ Non-goals：明确不做的范围，尤其是"不自动交易 / 不自动 push"等 }}

## 7. 涉及模块
{{ 代码模块 / 接口 / 文件，如 services/quant-api/app/signal/* }}

## 8. 产品需求
{{ PRD：场景 / 边界 / 验收目标 }}

## 9. 量化业务规则
{{ 交易时段 / 夜盘 / 节假日 / 主力合约 / 切换 / 手续费 / 滑点 / 乘数 / 保证金 }}

## 10. 数据影响
{{ RQData 使用 / 1m 基础 / 聚合 / 归档 / 缺失重复 bar / active Gate / 是否真实写入（dry-run 默认） }}

## 11. 技术方案
{{ 架构方案 / 模块边界 / 接口契约 / 数据流·策略流·信号流·告警流 }}

## 12. 交互视觉要求
{{ 信息架构 / 消息格式 / 状态颜色（红涨绿跌）/ 展示规范 }}（页面 / 告警类必填）

## 13. 安全权限要求
{{ 不碰 .env/token/webhook / 不删数据 / 不自动 push-merge-deploy / dry-run 默认 / 脱敏 }}（外部 / 凭证类必填）

## 14. 开发步骤
1. {{ step }}
2. {{ step }}
（每步标注是否需用户显式授权）

## 15. Codex Plan Prompt
```
{{ 只读 plan 提示词：分析仓库、产出方案，不修改代码 }}
```

## 16. Codex Dev Prompt
```
{{ 开发提示词：按方案实现，默认 dry-run，明确测试点 }}
```

## 17. CodeBuddy 执行 Prompt
```
{{ 本地执行入口提示词：调 Codex CLI 开发 / 跑测试，声明不 push / 不 merge }}
```

## 18. 测试清单
- [ ] {{ 单元测试 }}
- [ ] {{ 集成测试 }}
- [ ] {{ 回归测试 }}
- [ ] {{ 烟测 }}
- [ ] {{ 专项：数据聚合正确性 / 信号准确性 / 企业微信重复漏发误发 / Mac mini 稳定性 }}

## 19. 验收标准
{{ 明确 pass / block 条件；引用 PRD 验收目标 }}

## 20. 风险点
{{ 重绘 / 未来函数 / 过拟合 / 夜盘跨日 / active 未分层 / 凭证泄露 / 越权发送 / 自动部署 }}

## 21. 交付记录
- 状态流转：{{ IDEA → ... → CLOSED }}
- 测试结论：{{ pass / block }}
- 交付报告：{{ 链接 / 摘要 }}
- 合并前检查：{{ git diff --check / 测试通过 / 无敏感泄露 }}
- 用户 review：{{ 待 / 已 merge / 已 deploy }}
- 下一阶段建议：{{ ... }}
```

---

## 4. 使用说明

- 本模板与 `ROLE_SPEC.md`、`TASK_MATRIX.md` 三者配套：矩阵定"谁出场"，状态机定"怎么流转"，模板定"写什么"。
- **WorkBuddy 只填模板、出 Prompt、维护状态**，不自行写仓库代码、不 push / merge / deploy。
- 所有"真实写入 / 发送 / 部署 / 回滚"动作默认需用户显式授权；模板第 14、13、20 节必须显式声明。
- 任务编号统一 `GQ-YYYYMMDD-NNN`，由 PM 在 IDEA 状态分配，不重复、不跳号。
- 后续 Phase（Prompt 4–8）将基于本模板落地：Prompt 工厂填充第 15–17 节、质量门禁填充第 18–19 节、交付报告填充第 21 节、流程 SOP 绑定状态机。
