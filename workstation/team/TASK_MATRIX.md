# 归一量化任务类型与角色出场规则矩阵

> 团队名称：归一量化产品与交付工作站
> 配套文档：`workstation/team/ROLE_SPEC.md`（12 角色定义）
> 文档版本：v1.0
> 状态：已建立，作为 WorkBuddy 调度与角色路由的固定规则
> 生成时间：2026-07-09

## 0. 通用强制规则（覆盖所有任务类型）

以下规则**无条件优先**于各类型的"必须参与角色"列表：

1. 涉及**代码开发** → **测试专家 / QA Lead 必须参与**（制定测试点、验收结论）。
2. 涉及**页面、Dashboard、企业微信消息格式** → **交互视觉专家必须参与**。
3. 涉及 **RQData、1m 数据、周期聚合、行情、交易日、夜盘** → **数据工程师 + 量化业务专家必须参与**。
4. 涉及**策略逻辑** → **策略研究员必须参与**。
5. 涉及 **Mac mini、daemon、launchd、tmux、长期运行** → **DevOps / 本地运维必须参与**。
6. 涉及**密钥、token、webhook、远程控制、自动化执行** → **安全与权限专家必须参与**（一票否决）。
7. 涉及**交付验收** → **交付专家必须参与**。
8. 涉及**任务拆分、优先级、状态变化** → **项目经理 / 流程调度员必须参与**（所有任务默认包含）。

补充约定：
- 任何**写代码**任务 → **后端开发负责人必须参与**（产出 Codex Plan / Dev / CodeBuddy Exec 三类 Prompt）。
- **安全与权限专家**对所有外部 / 凭证动作拥有一票否决权，且每次 Prompt 出厂前需过其审查。
- **WorkBuddy 不自行改仓库代码**；所有代码动作由 Codex CLI / CodeBuddy 在 Mac mini 上执行，用户最终 review 才 merge / deploy。
- 状态机：`IDEA → TICKET_DRAFT → TICKET_CONFIRMED → PLAN_READY → CODING → TESTING → DELIVERY_REPORT → USER_REVIEW → DONE`，异常态 `BLOCKED` / `ROLLBACK`。

## 1. 速查矩阵（类型 → 必须角色 → 允许进入开发）

| # | 任务类型 | 必须参与角色 | 允许进入 CodeBuddy/Codex 开发 |
|---|---|---|---|
| 1 | 普通功能开发 | PM, PO, Arch, BE, QA, Del | 是（用户确认 plan 后） |
| 2 | 数据模块开发 | PM, PO, DE, QBiz, Arch, BE, QA, Sec, Del | 是（默认 dry-run，真实写入需显式授权） |
| 3 | 实时行情监听 | PM, PO, DE, QBiz, Arch, BE, QA, Del | 是 |
| 4 | 多周期聚合 | PM, PO, DE, QBiz, Arch, BE, QA, Del | 是 |
| 5 | 策略开发 | PM, PO, SR, QBiz, DE, Arch, BE, QA, Del | 是（仅提醒不下单） |
| 6 | 策略研究与验证 | PM, PO, SR, QBiz, DE, QA, Del | 否（纯研究；落地代码才转开发） |
| 7 | 企业微信告警 | PM, PO, SR, UX, QA, Sec, BE, Arch, Del | 是（默认 dry-run / observation-only） |
| 8 | Dashboard / 本地监控面板 | PM, PO, UX, Arch, BE, QA, Del | 是 |
| 9 | 回测模块 | PM, PO, SR, QBiz, DE, Arch, BE, QA, Del | 是 |
| 10 | 数据质量检查 | PM, PO, DE, QBiz, QA, Del | 是（默认只读审计） |
| 11 | Mac mini 长期运行 / 本地部署 | PM, PO, Arch, DevOps, Sec, Del | 是（部署需用户最终确认） |
| 12 | AI 工作流优化 | PM, PO, Arch, Del | 视情况（产出工具才转开发） |
| 13 | 三工具协作优化 | PM, PO, Arch, Sec, Del | 否（默认规范文档） |
| 14 | GitHub Issue/PR/版本管理 | PM, PO, Del, Arch, Sec | 否（仅规范与检查清单，用户操作） |
| 15 | 安全权限 / 密钥 / webhook / token | PM, PO, Sec, Del, Arch | 是（默认不读/不打印凭证） |
| 16 | 测试体系建设 | PM, PO, QA, Arch, BE, Del | 是 |
| 17 | 交互视觉规范建设 | PM, PO, UX, Del | 否（规范文档；落地 UI 才转开发） |
| 18 | 阶段交付复盘 | PM, PO, Del, QA, Arch | 否（复盘文档） |

> 角色缩写：PM=项目经理/流程调度员，PO=产品负责人，QBiz=量化业务专家，SR=策略研究员，Arch=量化架构师，DE=数据工程师，BE=后端开发负责人，QA=测试专家，UX=交互视觉专家，Sec=安全与权限专家，DevOps=本地运维部署专家，Del=交付专家。

---

## 2. 各任务类型详细规则

### 类型 1 · 普通功能开发
- **说明**：通用后端 / 前端功能，非数据 / 策略 / 部署专用。
- **必须参与**：PM、PO、Arch、BE、QA、Del。
- **可选参与**：QBiz、SR、DE、UX、Sec、DevOps。
- **不需要参与**：QBiz / SR / DE（纯业务无关时）；UX（无 UI 时）；DevOps / Sec（无外部调用时）。
- **必须输出**：PRD、架构方案、三类 Prompt、测试报告、交付报告、合并前检查清单。
- **关键风险**：范围蔓延、漏测试点、未声明 dry-run 默认、Preview 当 Sent。
- **推荐状态流转**：IDEA→TICKET_DRAFT→TICKET_CONFIRMED→PLAN_READY→CODING→TESTING→DELIVERY_REPORT→USER_REVIEW→DONE。
- **允许开发**：是（用户确认 plan 后）。

### 类型 2 · 数据模块开发
- **说明**：RQData 接入、入库、manifest、DB 登记、读取入口等。
- **必须参与**：PM、PO、DE、QBiz、Arch、BE、QA、Sec、Del。
- **可选参与**：SR、UX、DevOps。
- **不需要参与**：UX / DevOps / SR（除非涉及展示 / 常驻 / 策略）。
- **必须输出**：数据校验规则、质量 Gate、PRD 验收、三类 Prompt、测试（聚合 / 边界 / 重复缺失）、交付报告。
- **关键风险**：非 1m 直拉多分钟、缺失 / 重复 bar、夜盘跨日错位、active Gate 未分层就标 passed、RQData 凭证泄露。
- **推荐状态流转**：在普通流程前增加 `DATA_QUALITY_GATE` 节点；真实写入需单独 `TICKET_CONFIRMED` 授权。
- **允许开发**：是（默认 dry-run，真实写入需显式授权）。

### 类型 3 · 实时行情监听
- **说明**：live 1m 监听、live DB、live evaluator preview。
- **必须参与**：PM、PO、DE、QBiz、Arch、BE、QA、Del。
- **可选参与**：SR、Sec、UX、DevOps。
- **不需要参与**：UX / DevOps（无展示 / 常驻时）；SR（无策略联动时）。
- **必须输出**：监听方案、数据源收敛、preview 边界、稳定性 / 边界测试、交付报告。
- **关键风险**：live DB 当 trusted historical、preview 当正式信号、夜盘跨日错位。
- **推荐状态流转**：IDEA→…→PLAN_READY→CODING→TESTING（含 preview-only 验证）→DELIVERY_REPORT→USER_REVIEW。
- **允许开发**：是。

### 类型 4 · 多周期聚合
- **说明**：从 1m 聚合 5m / 15m / 30m / 60m。
- **必须参与**：PM、PO、DE、QBiz、Arch、BE、QA、Del。
- **可选参与**：SR、Sec、UX。
- **不需要参与**：UX / DevOps / SR（除非展示 / 常驻 / 策略）。
- **必须输出**：聚合规则、重复 / 缺口检查、聚合正确性测试、交付报告。
- **关键风险**：非 1m 基础直拉多分钟、聚合错位、重复时间戳（前端渲染崩溃）。
- **推荐状态流转**：同普通开发；聚合质量 Gate 前置。
- **允许开发**：是。

### 类型 5 · 策略开发
- **说明**：策略逻辑实现、信号触发、入场 / 出场。
- **必须参与**：PM、PO、SR、QBiz、DE、Arch、BE、QA、Del。
- **可选参与**：Sec、UX、DevOps。
- **不需要参与**：UX / DevOps（无展示 / 常驻时）。
- **必须输出**：策略假设、逻辑拆解、信号准确性测试、交付报告。
- **关键风险**：重绘指标（XMA 类）、未来函数、过拟合、preview 当正式信号、误触发真实合约价。
- **推荐状态流转**：IDEA→…→CODING→TESTING（信号准确性 + 重绘 / 滞后检查）→DELIVERY_REPORT→USER_REVIEW。
- **允许开发**：是（仅提醒不下单）。

### 类型 6 · 策略研究与验证
- **说明**：假设检验、参数敏感性、样本外、过拟合评估（偏研究，不一定落地生产代码）。
- **必须参与**：PM、PO、SR、QBiz、DE、QA、Del。
- **可选参与**：BE、Arch、Sec、UX。
- **不需要参与**：DevOps、UX、Sec（无外部 / 展示时）。
- **必须输出**：研究假设、验证报告、过拟合评估、结论与下一阶段建议。
- **关键风险**：过拟合、用未来数据、把研究当生产信号、样本内漂亮样本外崩。
- **推荐状态流转**：IDEA→TICKET_DRAFT→TICKET_CONFIRMED→（研究执行，无 CODING）→DELIVERY_REPORT→USER_REVIEW。
- **允许开发**：否（纯研究；若明确落地为代码任务再转 Phase）。

### 类型 7 · 企业微信告警
- **说明**：企业微信 payload、发送、通知记录、重试。
- **必须参与**：PM、PO、SR、UX、QA、Sec、BE、Arch、Del。
- **可选参与**：DE、QBiz、DevOps。
- **不需要参与**：DevOps（无常驻时）；DE / QBiz（无数据相关时）。
- **必须输出**：消息模板、payload basis 脱敏、发送 / 通知 / 重试设计、重复 / 漏发 / 误发测试、交付报告（含 webhook 不落库检查）。
- **关键风险**：webhook 泄露、重复 / 漏发 / 误发、preview 当 sent、越权发送、自动发送未授权。
- **推荐状态流转**：IDEA→…→PLAN_READY→CODING→TESTING（dry-run + 重复 / 漏发）→DELIVERY_REPORT→USER_REVIEW。
- **允许开发**：是（默认 dry-run / observation-only，真实发送需显式授权）。

### 类型 8 · Dashboard / 本地监控面板
- **说明**：Vue Web 页面、信息架构、监控。
- **必须参与**：PM、PO、UX、Arch、BE、QA、Del。
- **可选参与**：DE、SR、QBiz、Sec、DevOps。
- **不需要参与**：QBiz / SR / DE（无业务 / 信号 / 数据展示时）；Sec（无敏感时）；DevOps（无常驻时）。
- **必须输出**：信息架构、UI 规范、组件、烟测、交付报告。
- **关键风险**：红涨绿跌反了、状态颜色歧义、密钥泄露到 UI、信息过载导致漏看。
- **推荐状态流转**：同普通开发；UX 规范先行。
- **允许开发**：是。

### 类型 9 · 回测模块
- **说明**：vn.py CTA、JM V1-B 回测、报告。
- **必须参与**：PM、PO、SR、QBiz、DE、Arch、BE、QA、Del。
- **可选参与**：UX、Sec、DevOps。
- **不需要参与**：UX / DevOps / Sec（无展示 / 常驻 / 外部时）。
- **必须输出**：回测口径、可信主线、报告 / 曲线、回测正确性测试、交付报告。
- **关键风险**：rollover 错误、未来函数、样本内过拟合、未记合约乘数 / 保证金 / 滑点。
- **推荐状态流转**：同策略开发；增加回测可信主线复核节点。
- **允许开发**：是。

### 类型 10 · 数据质量检查
- **说明**：coverage audit、quality report、active Gate。
- **必须参与**：PM、PO、DE、QBiz、QA、Del。
- **可选参与**：BE、Arch、Sec、SR。
- **不需要参与**：UX、DevOps、SR、Sec（无展示 / 常驻 / 策略 / 外部时）。
- **必须输出**：质量 Gate、audit 矩阵、active 分层、结论。
- **关键风险**：未分层就标 passed、重复 / 缺失 bar、live 当 historical。
- **推荐状态流转**：IDEA→TICKET_DRAFT→TICKET_CONFIRMED→（只读审计，无 CODING）→DELIVERY_REPORT→USER_REVIEW。
- **允许开发**：是（默认只读审计，不写 / 不登记）。

### 类型 11 · Mac mini 长期运行 / 本地部署
- **说明**：tmux / launchd / daemon / supervisor、日志、重启、回滚。
- **必须参与**：PM、PO、Arch、DevOps、Sec、Del。
- **可选参与**：BE、QA、DE、UX。
- **不需要参与**：SR、QBiz、DE、UX（无策略 / 业务 / 数据 / 展示相关时）。
- **必须输出**：运行方案、启停脚本、日志策略、回滚方案、health check、合并前检查。
- **关键风险**：自动部署未确认、无回滚、日志占满磁盘、dev 当 prod、重启丢失 live 状态。
- **推荐状态流转**：IDEA→…→PLAN_READY→CODING（如需改代码）→TESTING→DELIVERY_REPORT→USER_REVIEW（用户确认部署）。
- **允许开发**：是（部署需用户最终确认，不自动）。

### 类型 12 · AI 工作流优化
- **说明**：优化 WorkBuddy / Codex / CodeBuddy 协作流程、Prompt、任务单（含本工作站自身）。
- **必须参与**：PM、PO、Arch、Del。
- **可选参与**：BE、QA、Sec、其他角色按需。
- **不需要参与**：QBiz、SR、DE、DevOps、UX（无对应内容时）。
- **必须输出**：流程 SOP、Prompt 模板、优化报告。
- **关键风险**：流程越权、Prompt 缺护栏、过度自动化。
- **推荐状态流转**：IDEA→TICKET_DRAFT→TICKET_CONFIRMED→（产出规范 / 模板，无 CODING 或视情况）→DELIVERY_REPORT。
- **允许开发**：视情况（若产出可执行脚本则转开发 Phase）。

### 类型 13 · CodeBuddy / Codex / WorkBuddy 协作优化
- **说明**：三工具接口、远程执行、权限边界优化。
- **必须参与**：PM、PO、Arch、Sec、Del。
- **可选参与**：DevOps、BE、QA。
- **不需要参与**：QBiz、SR、DE、UX。
- **必须输出**：协作 SOP、权限边界、远程执行规范。
- **关键风险**：越权远程执行、凭证泄露、自动 push / merge。
- **推荐状态流转**：同 AI 工作流优化（默认规范文档）。
- **允许开发**：否（默认规范文档）。

### 类型 14 · GitHub Issue / PR / 版本管理
- **说明**：issue 模板、PR 规范、分支、版本号、changelog。
- **必须参与**：PM、PO、Del、Arch、Sec。
- **可选参与**：BE、QA、其他。
- **不需要参与**：QBiz、SR、DE、UX、DevOps（无对应内容时）。
- **必须输出**：issue / PR 模板、分支规范、合并前检查、changelog。
- **关键风险**：自动 push / merge、未跑测试就合、密钥进 PR。
- **推荐状态流转**：IDEA→TICKET_DRAFT→TICKET_CONFIRMED→（规范文档 + 检查清单，无 CODING）→DELIVERY_REPORT。
- **允许开发**：否（WorkBuddy 不代执行 push / merge，仅产出规范与检查清单，用户最终操作）。

### 类型 15 · 安全权限 / 密钥 / webhook / token 相关任务
- **说明**：`.env`、webhook、token、权限边界、日志脱敏。
- **必须参与**：PM、PO、Sec、Del、Arch。
- **可选参与**：BE、QA、DevOps。
- **不需要参与**：QBiz、SR、DE、UX、DevOps（无部署时）。
- **必须输出**：权限审查、护栏清单、脱敏规则、阻断项。
- **关键风险**：改 `.env`、打印 webhook / token、删数据、越权发送、密钥进日志。
- **推荐状态流转**：IDEA→…→PLAN_READY→CODING（默认不读 / 不打印凭证）→TESTING→DELIVERY_REPORT→USER_REVIEW。
- **允许开发**：是（默认不读 / 不打印凭证，真实操作需显式授权）。

### 类型 16 · 测试体系建设
- **说明**：pytest / ruff / 烟测 / 回归框架、CI。
- **必须参与**：PM、PO、QA、Arch、BE、Del。
- **可选参与**：DE、SR、Sec、DevOps。
- **不需要参与**：QBiz、UX、DevOps、SR（无对应内容时）。
- **必须输出**：测试策略、用例库、CI 配置、验收门槛。
- **关键风险**：只 happy path、漏 dry-run 验证、无回归。
- **推荐状态流转**：同普通开发；测试框架先行于业务代码。
- **允许开发**：是。

### 类型 17 · 交互视觉规范建设
- **说明**：配色、状态色、消息格式、报告结构、设计系统。
- **必须参与**：PM、PO、UX、Del。
- **可选参与**：Arch、SR、DE、Sec、BE、QA。
- **不需要参与**：QBiz、SR、DE、DevOps、BE、QA、Sec（无对应内容时）。
- **必须输出**：设计系统、配色 / 状态规范、消息模板、报告结构。
- **关键风险**：红涨绿跌反、状态歧义、信息过载。
- **推荐状态流转**：IDEA→TICKET_DRAFT→TICKET_CONFIRMED→（规范文档，无 CODING）→DELIVERY_REPORT。
- **允许开发**：否（规范文档；落地为 UI 时转开发任务）。

### 类型 18 · 阶段交付复盘
- **说明**：阶段总结、交付报告、下一阶段建议。
- **必须参与**：PM、PO、Del、QA、Arch。
- **可选参与**：DE、SR、QBiz、Sec、DevOps、UX（按本阶段涉及内容回头看）。
- **不需要参与**：无强制不需要；全员按需可选。
- **必须输出**：交付报告、验收结论、合并前检查、下一阶段建议、复盘风险与教训。
- **关键风险**：未达验收判通过、漏回滚、不沉淀教训。
- **推荐状态流转**：USER_REVIEW→（复盘文档）→DONE / 触发下一轮 IDEA。
- **允许开发**：否（复盘文档）。

---

## 3. 使用说明

- 本矩阵与 `ROLE_SPEC.md` 配套使用：先按本矩阵确定"哪些角色必须出场"，再按 `ROLE_SPEC.md` 取各角色的 8 项职责明细。
- **项目经理**默认对所有任务做编号与状态维护；**安全与权限专家**对所有外部 / 凭证动作一票否决。
- "允许开发 = 否"的任务，WorkBuddy 只产出规范 / 模板 / 检查清单，不进入 Codex / CodeBuddy 代码阶段，由用户决定后续是否转为开发任务。
- 后续 Phase（Prompt 3–8）将基于本矩阵落地：任务单模板、Prompt 工厂、质量门禁、交付报告模板、状态机机制、流程 SOP。
