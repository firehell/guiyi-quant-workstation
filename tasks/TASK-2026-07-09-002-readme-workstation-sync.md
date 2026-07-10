# TASK-2026-07-09-002：同步 README 与工作站总配置说明

> 团队：归一量化产品与交付工作站
> 状态：REQUIREMENT_READY
> 任务类型：AI 工作流优化（工作站文档集成）；关联「交互视觉规范建设」「CodeBuddy / Codex / WorkBuddy 协作优化」
> 生成：WorkBuddy（按 `STATE_MACHINE_TICKET.md` 21 字段模板）
> 配套：STATION_CONFIG.md（Final v1.0）、COLLAB_PROTOCOL.md、SECURITY_HANDBOOK.md、UX_VISUAL_SPEC.md、MACMINI_OPS_MANUAL.md
> 性质：**dry-run 验证任务**——本任务用于端到端验证「WorkBuddy 出单 → CodeBuddy 执行 → Codex Plan → Codex Dev → 测试 → collect_result → WorkBuddy 交付报告」半自动闭环；改动仅限文档，风险极低，但每个状态门仍需你人工确认。

> **状态门控说明（务必先读）**：本任务单当前处于 `REQUIREMENT_READY`。下方第 15–17 节的《Codex Plan Prompt / Dev Prompt / CodeBuddy 执行 Prompt》是**随单携带的草案**，按状态机规则：
> - Plan Prompt 在 `PLAN_READY` 由 CodeBuddy 喂给 `codex_plan.sh` 执行（只读）；
> - Dev / Exec Prompt 在 `APPROVED_DEV` 才启用。
> **WorkBuddy 本次只产出本任务单文档，不修改 README.md、不执行任何脚本。** 实际文档改动在 `CODING` 阶段、且需你确认 plan 与开发后由 CodeBuddy → Codex CLI 在 Mac mini 执行（本次为 dry-run，不 push / merge / deploy）。

---

## 1. 任务状态
REQUIREMENT_READY

## 2. 任务类型
AI 工作流优化（工作站文档集成）
- 关联：交互视觉规范建设（README 章节结构遵循 UX_VISUAL_SPEC 可读性/声明原则）、CodeBuddy / Codex / WorkBuddy 协作优化（README 需说明三工具分工）
- 参照：TASK_MATRIX.md「12. AI 工作流优化」「17. 交互视觉规范建设」
- 是否允许进入代码开发阶段：**是**（但严格限定 `README.md` 与文档索引类文件，纯 markdown 改动，不碰业务/数据/策略/配置）

## 3. 参与角色
- 必须（按你指定 + TASK_MATRIX 强制规则校验）：
  - 项目经理 / 流程调度员（编号、状态、拆分、卡点检查——本单为 dry-run，PM 负责标注状态门与人工确认点）
  - 产品负责人（定义 README 要补的用户场景与说明边界——涉及「文档/说明」类需求，产品负责人必参）
  - 后端开发负责人（拥有文档技术改动方案、拆可执行步骤、出三类 Prompt——文档改动由 Codex dev 落地，后端负责人必参）
  - 测试专家 / QA Lead（文档一致性 / 链接有效性 / 措辞与基线一致校验——涉及改动必参，本次为文档级测试）
  - 交互视觉专家 / UX UI Designer（README 新增章节的结构、可读性、必含「非自动交易 / 本地优先」声明，对齐 UX_VISUAL_SPEC §6——涉及说明可读性/声明，UX 必参）
  - 交付专家（验收、合并前检查、交付报告——涉及交付验收必参）
- 可选：
  - 量化架构师（评审 README 工具链描述是否准确）
- 不需要：
  - 量化业务专家（非数据/行情/交易日任务）
  - 策略研究员（非策略逻辑）
  - 数据工程师（非 RQData/1m/聚合）
  - 安全与权限专家（本次不改 `.env`/token/webhook/密钥，仅补文字指针与说明；但新增文字须对齐 SECURITY_HANDBOOK 六条禁令，由后端负责人与 QA 在评审中兜底）
  - DevOps / 本地运维部署专家（不改 Mac mini 运行配置，仅文字描述 Mac mini 主机定位）

## 4. 背景
- 工作站基线已冻结为 **Baseline v1.0 @ 2026-07-09**（STATION_CONFIG.md + 9 子文档 + BASELINE_FREEZE.md），定义了 WorkBuddy / CodeBuddy / Codex CLI 三方协作与 Mac mini 本地优先运行方案。
- **README 现状核对（关键）**：README 当前已写到 `当前 Stage 11-C`（runtime health API，2026-07-09），与代码进度同步，**不存在 Stage 滞后**。此前「README 停在 9-B2」的判断已过时。
- **真正的缺口**：README 的「快速导航」表与全文**没有任何一处**指向 `workstation/STATION_CONFIG.md`，也**没有**说明 AI 工作站、WorkBuddy、CodeBuddy、Codex CLI 的分工与 Mac mini 主机定位。新读者 / 新 Codex 会话无法从 README 得知这套协作体系与长期固定配置入口的存在。
- 目标：把 README 与工作站总配置打通——补一段「AI 工作站与本地优先协作」说明 + 在导航表加一行 STATION_CONFIG 指针，使 README 正确指向 STATION_CONFIG.md。
- 本任务同时作为**流程 dry-run**：用一张低风险文档任务，完整跑通半自动闭环（出单→plan→dev→test→collect→交付），验证协作协议与 5 个脚本可用。

## 5. 目标
1. 检查 README 是否滞后（结论：Stage 进度不滞后；缺口为缺少 AI 工作站 / 三工具协作 / Mac mini 本地优先说明与 STATION_CONFIG 指针）。
2. 在 README 新增「AI 工作站与本地优先协作」章节，说明：
   - 三方工具分工：WorkBuddy（需求/产品/测试/交互/交付/流程）、CodeBuddy（本地执行入口 + 企业微信远程入口）、Codex CLI（主力开发执行器，只读 plan + 开发）；你（确认任务/plan/开发/push/merge/deploy）。
   - Mac mini 主机定位：V1 主机，本地优先、低运维、可回滚、不云部署。
   - `workstation/STATION_CONFIG.md` 为长期固定配置总入口（Final v1.0），细节以 `workstation/team/` 9 份子文档为准。
   - 工具链边界（对齐 SECURITY_HANDBOOK 六条禁令）：不自动交易、不自动 push/merge/release/deploy、不改密钥、不删历史行情、不输出密钥/webhook、不用全权限模式；生产运行前必须人工确认。
3. 在 README「快速导航」表新增一行：`查看 AI 工作站配置` → `workstation/STATION_CONFIG.md`。
4. （可选，仍属文档索引类）在 `docs/` 下某索引类文件（如 `docs/README.md` 或 `docs/PROJECT_OVERVIEW.md` 的导航）补同样指针，确保文档树一致。
5. 全程仅改 README.md 与文档索引类文件；不碰业务/数据/策略/配置/密钥；不 push / merge / deploy。

## 6. 不做事项
- ❌ 不修改任何业务模块（`services/`、`packages/`、`app/` 等）。
- ❌ 不修改数据模块（RQData ingest、parquet、DB 登记、active Gate）。
- ❌ 不修改策略模块（`strategies/`、`signal/`、`jm_v1b` 等）。
- ❌ 不修改 `.env` / token / webhook / RQData 密钥 / 任何配置文件。
- ❌ 不 `git push` / `git merge` / `git release` / `git deploy`（本次为 dry-run，最多本地 commit 预览，绝不远程动作）。
- ❌ 不删除任何历史行情 / DB / parquet / 日志数据。
- ❌ 不实现真实交易、不开启企业微信真实发送。
- ❌ 不改动既有 9 份工作站文档（STATION_CONFIG.md 等）的正文——本次只从 README 指向它们，不反向修改。
- ❌ 不新增 `scripts/ai/` 脚本（脚手架已由 TASK-001 单独负责）；本单假设脚手架脚本已存在，仅调用其 dry-run 路径。

## 7. 涉及模块
- 修改（纯 markdown）：
  - `README.md`（新增章节 + 导航表一行）
  - `docs/` 下索引类文件（可选，如 `docs/README.md` / `docs/PROJECT_OVERVIEW.md` 导航补充）
- 只读引用（不修改）：
  - `workstation/STATION_CONFIG.md`（指针目标 + 分工/边界措辞来源）
  - `workstation/team/COLLAB_PROTOCOL.md`（三工具契约）
  - `workstation/team/SECURITY_HANDBOOK.md`（六条禁令措辞）
  - `workstation/team/UX_VISUAL_SPEC.md`（非自动交易声明原则）
  - `workstation/team/MACMINI_OPS_MANUAL.md`（Mac mini 主机定位）

## 8. 产品需求
- 作为工作站使用方 / 新读者，我打开 README 时应立刻知道：
  - 这套系统有一套 AI 工作站协作体系，且 `STATION_CONFIG.md` 是长期固定配置总入口；
  - WorkBuddy / CodeBuddy / Codex CLI 各自干什么、谁来做最终确认；
  - V1 是 Mac mini 本地优先、不自动交易、不自动部署。
- 新增说明应简短、可读、不制造误导（涨红跌绿等视觉约定不在此章，但「非自动交易，仅信号提醒」声明必须显式出现）。
- 链接必须有效（指向真实存在的 `workstation/STATION_CONFIG.md`）。

## 9. 量化业务规则
- 本任务**不涉及期货业务规则**（非数据/策略/信号任务）。
- 但新增说明文字必须继承 V1 约束：不自动交易、不把信号当交易指令；措辞与 SECURITY_HANDBOOK 六条禁令、README 现有「安全边界」章节一致。

## 10. 数据影响
- 无数据读写：不读取、不写入、不删除任何行情 / DB / parquet 数据。
- 不触发 RQData、不写数据库、不真实发送企业微信。
- 改动落在 markdown 文本，git diff 应仅含 README.md（及可选 docs 索引）。

## 11. 技术方案
> 草案（PLAN_READY 阶段由 Codex 只读 plan 细化；此处给出契约级要点）

**改动内容（Codex dev 实际写入）**
1. README「快速导航」表追加一行：
   ```markdown
   | 查看 AI 工作站配置 | `workstation/STATION_CONFIG.md` |
   ```
2. README 在「安全边界」章节之前或之后新增「AI 工作站与本地优先协作」章节，建议结构：
   ```markdown
   ## AI 工作站与本地优先协作

   本项目配有一套 AI 工作站（归一量化产品与交付工作站），由 WorkBuddy 负责需求/产品/测试/交互/交付/流程管理，
   CodeBuddy 负责本地执行入口与企业微信远程入口，Codex CLI 负责主力开发执行（只读 plan + 开发）。
   所有代码动作的确认、push、merge、deploy 均由你（人工）完成。

   - 长期固定配置总入口：`workstation/STATION_CONFIG.md`（Final v1.0）
   - Mac mini 为 V1 主机：本地优先、低运维、可回滚、不云部署
   - 工具链边界（强制）：不自动交易、不自动 push/merge/release/deploy、不改密钥、不删历史行情、
     不输出 token/webhook/账户、不用全权限模式；生产运行前必须人工确认

   > 非自动交易，仅信号提醒 / 人工观察。
   ```
3. （可选）`docs/` 索引类文件补同样导航指针，确保文档树一致。

**约束**
- 仅 markdown 文本改动；不引入新依赖、不改代码、不改配置。
- 新增文字不得包含任何真实密钥 / webhook / token（脱敏，即使示例也用占位符）。

## 12. 交互视觉要求
- README 为文档，无 Dashboard / 页面 / 企业微信消息格式设计；但本章结构须对齐 UX_VISUAL_SPEC.md §6「可读 / 可判断 / 可追踪 / 不制造误导 / 明确非自动交易」原则。
- 必须显式包含「非自动交易，仅信号提醒 / 人工观察」声明（UX_VISUAL_SPEC §6 强制元素）。
- 章节层级、表格格式与 README 现有风格一致，便于阅读。

## 13. 安全权限要求（必填，外部/凭证类）
- ❌ 不读取 / 打印 / 写入 `.env`、token、webhook、RQData 密钥。
- 新增文字中不得出现任何真实密钥值；如举占位示例须用 `QYWX_WEBHOOK_URL` 这类变量名，不写具体值。
- 工具链边界措辞直接复用 SECURITY_HANDBOOK.md 六条禁令，不得弱化（如不得把「不自动部署」写成「自动部署需谨慎」）。
- 若 Codex dev 过程中尝试触碰 `.env` / 配置 / 业务代码，立即中止（FAILED）并报安全专家一票否决。

## 14. 开发步骤
1. 读取 README.md 与 STATION_CONFIG.md，核对当前 README 缺口（确认 Stage 不滞后、缺工作站指针）。
2. 产出「滞后检查」结论（文档级，纳入 plan 与交付报告）。
3. 在 README 快速导航表追加 STATION_CONFIG 一行。
4. 在 README 新增「AI 工作站与本地优先协作」章节（结构见 §11）。
5. （可选）在 docs/ 索引类文件补同样指针。
6. 一致性检查：链接有效、措辞与 SECURITY_HANDBOOK / UX_VISUAL_SPEC 一致、无密钥泄漏。
> 每步均为文档改动；真实写入属 CODING 阶段、需你确认开发后由 CodeBuddy 调用 Codex 执行（dry-run，不 push）。

## 15. Codex Plan Prompt
```
你现在是 Codex CLI，处于 plan（只读）模式。任务单见 tasks/TASK-2026-07-09-002-readme-workstation-sync.md。

要求：
1. 只读取仓库与文档，不写任何业务代码（services/ packages app 等既有文件不改）。
2. 仅可将 plan 文本写入 scripts/ai/.out/<task-id>/plan.md（若该目录不存在先创建）。
3. 产出 plan.md，包含：
   - README.md 当前缺口核对结论（Stage 进度是否滞后；是否缺工作站/STATION_CONFIG 指针）；
   - 拟新增章节的完整草稿文本（含导航表一行 + 「AI 工作站与本地优先协作」章节）；
   - 拟改动文件清单（仅 README.md，可选 docs/ 索引类）；
   - 与 SECURITY_HANDBOOK 六条禁令、UX_VISUAL_SPEC §6 的措辞一致性自检；
   - 风险与待你确认项（如章节插入位置、可选 docs 索引范围）。
4. 严格遵守：不碰业务代码/数据/策略/.env，不 git push/merge/deploy，不真实发送。

输出后等待用户确认 plan。
```

## 16. Codex Dev Prompt
```
你现在是 Codex CLI，处于 dev（workspace-write）模式，执行已批准 plan：scripts/ai/.out/TASK-2026-07-09-002/plan.md。

范围（严格限定，越界即中止）：
- 修改 README.md（导航表 + 新增章节）；
- 可选修改 docs/ 下索引类文件（仅补导航指针）；
- 不新增脚本、不改代码逻辑。

禁止（硬约束）：
- 修改任何业务/数据/策略模块；
- 读取或写入 .env / token / webhook / RQData 密钥；
- git push / merge / release / deploy；
- 删除历史数据、rm -rf、全权限 mode；
- 真实发送企业微信、自动交易；
- 任何把密钥写入日志/payload/文档的行为（示例仅用变量名占位）。

完成后：
- 校验 README 内新增链接指向真实存在的 workstation/STATION_CONFIG.md；
- 输出 git diff --stat 供 review。退出码 0 表示成功。
```

## 17. CodeBuddy 执行 Prompt
```
CodeBuddy：请按协作协议（COLLAB_PROTOCOL.md）执行任务单 tasks/TASK-2026-07-09-002-readme-workstation-sync.md（dry-run 验证）。

步骤：
1. 校验状态为 APPROVED_DEV 且 plan 已批准（否则回传「状态不符」）。
2. 护栏自检（任一命中即中止）：要求改 .env/token/webhook？自动 push/merge/deploy？删数据？自动交易？→ 中止并报安全专家。
3. 调用 scripts/ai/codex_plan.sh --task TASK-2026-07-09-002 生成 plan（若尚未生成）。
4. 经用户确认 plan 后，调用 scripts/ai/codex_dev.sh --task TASK-2026-07-09-002 --plan <plan> 实现（仅 README + 可选 docs 索引）。
5. 调用 scripts/ai/run_tests.sh --task TASK-2026-07-09-002 --scope all（默认 dry-run；本次无代码测试，仅文档一致性校验）。
6. 调用 scripts/ai/collect_result.sh --task TASK-2026-07-09-002 汇总并脱敏。
7. 调用 scripts/ai/make_delivery_summary.sh --task TASK-2026-07-09-002 --bundle <result_bundle> 生成交付摘要。
8. 回传结果摘要给 WorkBuddy / 用户。不自动 push / merge / deploy（dry-run 最多本地 commit 预览）。
```

## 18. 测试清单
- [ ] README 内新增链接 `workstation/STATION_CONFIG.md` 指向真实存在的文件（链接有效性，文档校验）
- [ ] README「AI 工作站与本地优先协作」章节存在且含「非自动交易，仅信号提醒 / 人工观察」声明（UX 一致性）
- [ ] 章节措辞与 SECURITY_HANDBOOK 六条禁令一致，无弱化（安全一致性）
- [ ] `git diff --stat` 仅含 README.md（及可选 docs/ 索引），无任何业务/数据/策略/配置改动（范围校验）
- [ ] 新增文字中无任何真实密钥 / webhook / token 值（脱敏单测：人工 grep 样例）
- [ ] 滞后检查结论已记录：README Stage 进度不滞后，缺口为工作站指针（文档校验）
- [ ] 章节层级 / 表格格式与 README 现有风格一致、可读（UX 可读性原则）
- [ ] 可选 docs/ 索引指针与 README 一致，文档树无矛盾（回归）
- [ ] 安全专家复核（或由后端+QA 兜底）：无 `.env` 读取、无自动 push 措辞（安全门）
- [ ] 本地干跑：collect_result 汇总 README diff 正确、脱敏生效（烟测）

## 19. 验收标准
- **pass 条件**（全部满足）：
  1. README 导航表含 `workstation/STATION_CONFIG.md` 一行且链接有效；
  2. README 含「AI 工作站与本地优先协作」章节，且显式声明「非自动交易，仅信号提醒 / 人工观察」；
  3. 章节措辞与 SECURITY_HANDBOOK 六条禁令一致，无弱化；
  4. `git diff --stat` 仅含 README.md（及可选 docs/ 索引），零业务/数据/策略/配置改动；
  5. 无任何真实密钥 / webhook / token 出现在 README 或产物；
  6. 滞后检查结论已记录于交付报告；
  7. 全程未触发 push/merge/deploy。
- **block 条件**（任一即不通过）：
  - README 改动触及业务/数据/策略/配置文件；
  - 含真实密钥 / webhook / token 值；
  - 弱化工具链边界（如把「不自动部署」改写为允许自动）；
  - 缺失「非自动交易」声明；
  - 自动 push/merge/deploy。

## 20. 风险点
- **R1 Codex dev 越界改代码**：用 `git diff` 范围校验 + 护栏自检拦截；越界即 FAILED。
- **R2 密钥泄漏**：新增文字仅用变量名占位，QA grep 校验；脱敏兜底。
- **R3 措辞弱化安全边界**：直接复用 SECURITY_HANDBOOK 原文，QA 一致性核对。
- **R4 链接失效**：plan 阶段确认 `workstation/STATION_CONFIG.md` 真实存在（Baseline v1.0 已冻结，路径稳定）。
- **R5 章节风格割裂**：UX 评审结构与 README 现有风格一致。
- **R6 脚手架脚本未就绪**：本单依赖 TASK-001 的 `scripts/ai/` 脚本；若未落地，CodeBuddy 执行阶段应回退为「手动 README 编辑 + WorkBuddy 直接交付」，并标注 dry-run 降级（不阻塞本单目标，因改动仅文档）。
- **R7 dry-run 误升级为真实动作**：CodeBuddy 执行 Prompt 明确 dry-run，最多本地 commit 预览，绝不远程；任何 push 意图立即中止报安全专家。

## 21. 交付记录
- 状态流转：IDEA → REQUIREMENT_READY（本单） → [待你确认 PRD] → PLAN_READY → APPROVED_DEV → CODING → TESTING → DELIVERY_READY → CLOSED
- 测试结论：待 TESTING 阶段填写（pass / block）
- 交付报告：待 DELIVERY_READY 由 WorkBuddy 产出（含滞后检查结论 + README 改动摘要 + 验收对照）
- 合并前检查：待填写（git diff --check / 链接有效 / 无敏感泄露 / 措辞一致）
- 用户 review：待（不自动 merge / deploy；dry-run 最多本地 commit 预览）
- 下一阶段建议：本 dry-run 通过即证明半自动闭环可用；随后可正式走 TASK-001 脚手架落地，或拿一个真实业务想法跑完整闭环。
