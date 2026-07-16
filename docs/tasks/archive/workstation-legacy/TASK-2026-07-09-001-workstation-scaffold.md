# TASK-2026-07-09-001：工作站脚手架脚本落地

> 团队：归一量化产品与交付工作站
> 状态：REQUIREMENT_READY
> 任务类型：AI 工作流优化（协作工具脚手架）；关联「CodeBuddy / Codex / WorkBuddy 协作优化」
> 生成：WorkBuddy（按 `STATE_MACHINE_TICKET.md` 21 字段模板）
> 配套：STATION_CONFIG.md（Final v1.0）、COLLAB_PROTOCOL.md §6–9、SECURITY_HANDBOOK.md、MACMINI_OPS_MANUAL.md

> **状态门控说明（务必先读）**：本任务单当前处于 `REQUIREMENT_READY`。下方第 15–17 节的《Codex Plan Prompt / Dev Prompt / CodeBuddy 执行 Prompt》是**随单携带的草案**，按状态机规则：
> - Plan Prompt 在 `PLAN_READY` 由 CodeBuddy 喂给 `codex_plan.sh` 执行（只读）；
> - Dev / Exec Prompt 在 `APPROVED_DEV` 才启用。
> **WorkBuddy 本次只产出本任务单文档，不创建 scripts/ai/、不创建 docs/、不执行任何脚本。** 实际落地在 `CODING` 阶段、且需你确认 plan 与开发后由 CodeBuddy → Codex CLI 在 Mac mini 执行。

---

## 1. 任务状态
REQUIREMENT_READY

## 2. 任务类型
AI 工作流优化（协作工具脚手架）
- 关联：三工具协作优化（将 COLLAB_PROTOCOL.md 定义的脚本契约真正落地为可执行文件）
- 参照：TASK_MATRIX.md「12. AI 工作流优化」「13. CodeBuddy / Codex / WorkBuddy 协作优化」
- 是否允许进入代码开发阶段：**是**（但严格限定 scripts/ai/ + docs/ 新增，不碰业务/数据/策略）

## 3. 参与角色
- 必须（按你指定 + TASK_MATRIX 强制规则校验）：
  - 项目经理 / 流程调度员（编号、状态、拆分、卡点检查）
  - 后端开发负责人（技术方案、拆可执行任务、出三类 Prompt）
  - 测试专家 / QA Lead（测试清单、验收结论——涉及代码开发必参）
  - 安全与权限专家（密钥/护栏/一票否决——涉及脚本/自动化执行必参）
  - DevOps / 本地运维部署专家（脚本在 Mac mini 落地、权限/chmod/路径——涉及本地执行必参）
  - 交付专家（验收、合并前检查、交付报告——涉及交付验收必参）
- 可选：
  - 量化架构师（评审脚本架构边界）
- 不需要：
  - 产品负责人（无新用户场景，纯工具脚手架）
  - 量化业务专家（非数据/行情/交易日任务）
  - 策略研究员（非策略逻辑）
  - 数据工程师（非 RQData/1m/聚合）
  - 交互视觉专家（无 Dashboard / 页面 / 企业微信消息格式设计，仅复用既有 UX 结构）

## 4. 背景
- 工作站基线已冻结为 **Baseline v1.0 @ 2026-07-09**（STATION_CONFIG.md + 9 子文档 + BASELINE_FREEZE.md）。
- COLLAB_PROTOCOL.md §6–9 已定义 4 个协作脚本（codex_plan / codex_dev / run_tests / collect_result）的**契约**，但仅停留在文档，**未落地为可执行文件**。
- 半自动开发闭环（想法→任务单→plan→dev→测试→交付→merge）缺少实际可调用的脚本入口，CodeBuddy 目前无法按协议机械调用 Codex CLI。
- 目标：把协议中的脚手架 + 1 个交付摘要脚本 + 3 份流程文档真正落到项目目录，使后续 WorkBuddy → CodeBuddy → Codex CLI 闭环具备基础脚本与标准模板。

## 5. 目标
1. 创建 `scripts/ai/` 目录，落地 5 个脚本：`codex_plan.sh`、`codex_dev.sh`、`run_tests.sh`、`collect_result.sh`、`make_delivery_summary.sh`，逐条实现 COLLAB_PROTOCOL.md 的脚本契约。
2. 创建 `docs/tasks/TASK_TEMPLATE.md`：21 字段标准任务单模板（源自 STATE_MACHINE_TICKET.md §3）。
3. 创建 `docs/workflows/ai_delivery_workflow.md`：半自动交付流程 SOP（提炼 STATION_CONFIG.md §15–23）。
4. 创建 `docs/workflows/status_machine.md`：10 状态机说明（提炼 STATE_MACHINE_TICKET.md §1–2）。
5. 全程不碰业务代码、数据模块、策略模块、`.env`/token/webhook/密钥；不 push / merge / deploy。

## 6. 不做事项
- ❌ 不修改任何业务模块（`services/`、`packages/`、`app/` 等）。
- ❌ 不修改数据模块（RQData ingest、parquet、DB 登记、active Gate）。
- ❌ 不修改策略模块（`strategies/`、`signal/`、`jm_v1b` 等）。
- ❌ 不修改 `.env` / token / webhook / RQData 密钥。
- ❌ 不 `git push` / `git merge` / `git release` / `git deploy`。
- ❌ 不删除任何历史行情 / DB / parquet / 日志数据。
- ❌ 不实现真实交易、不开启企业微信真实发送开关（脚本默认 dry-run / observation-only）。
- ❌ 不实现 Mac mini 常驻（launchd / run_loop / gq_status）——那是独立的「Mac mini 部署任务」，本次不含。
- ❌ 不改动既有 9 份工作站文档（STATION_CONFIG.md 等）的正文。

## 7. 涉及模块
- 新增（全新文件，无既有代码耦合）：
  - `scripts/ai/codex_plan.sh`
  - `scripts/ai/codex_dev.sh`
  - `scripts/ai/run_tests.sh`
  - `scripts/ai/collect_result.sh`
  - `scripts/ai/make_delivery_summary.sh`
  - `scripts/ai/.out/`（本地产物目录，建议加入 `.gitignore`，git status 应忽略）
  - `docs/tasks/TASK_TEMPLATE.md`
  - `docs/workflows/ai_delivery_workflow.md`
  - `docs/workflows/status_machine.md`
- 只读引用（不修改）：`workstation/STATION_CONFIG.md`、`workstation/team/*.md`、`docs/STAGE9_WECHAT_DELIVERY.md`（仅参考脱敏/幂等约束）

## 8. 产品需求
- 作为工作站使用方，我需要一组可复用的 shell 脚本，让 CodeBuddy 能按协作协议机械地调用 Codex CLI 完成：只读 plan → 受控 dev → dry-run 测试 → 脱敏汇总 → 交付摘要。
- 脚本必须默认安全：**plan 只读 / dev 仅 workspace-write / test dry-run / collect 脱敏**。
- 脚本应打印统一、可读的步骤日志与明确退出码，便于人工判断与 Mac mini 日志轮转。
- 3 份文档须与工作站基线（Baseline v1.0）严格一致，作为后续任务单与流程的速查入口。

## 9. 量化业务规则
- 本任务**不涉及期货业务规则**（非数据/策略/信号任务）。
- 但脚本被后续调用时，必须继承 V1 约束：不自动交易、不真实发送、不删数据（见 SECURITY_HANDBOOK 六条禁令）。
- `make_delivery_summary.sh` 生成的交付摘要，结构须遵循 UX_VISUAL_SPEC.md §3（摘要/完成/未完成/测试/风险/是否合并/下一步），且不得包含任何密钥；品种/合约等值来自 result bundle，不在此任务内产生。

## 10. 数据影响
- 无数据读写：不读取、不写入、不删除任何行情 / DB / parquet 数据。
- 脚本产物（plan.md、test-summary、result bundle、delivery summary）统一落在 `scripts/ai/.out/<task-id>/`，**不进入数据目录、不进入 git 跟踪**（除非显式 `--keep`）。
- `run_tests.sh` 跑测试时，告警测试默认走 mock webhook / dry-run，不真实发送、不真写数据库历史。

## 11. 技术方案
> 草案（PLAN_READY 阶段由 Codex 只读 plan 细化；此处给出契约级要点）

**目录与产物约定**
- 脚本放 `scripts/ai/`；本地产物放 `scripts/ai/.out/<task-id>/`（plan.md / test-summary.json / result_bundle.md / delivery_summary.md）。
- 所有脚本首行 `#!/usr/bin/env bash`，`set -euo pipefail`，统一日志前缀 `[STEP]/[OK]/[WARN]/[ERR]` + `date +%FT%T`。

**各脚本契约（对齐 COLLAB_PROTOCOL.md §6–9）**
- `codex_plan.sh --task <TASK-ID> [--prompt <file>]`
  - 只读模式启动 Codex CLI；将任务单第 15 节作为输入。
  - 产出 plan 到 `scripts/ai/.out/<task-id>/plan.md`，**不写仓库业务代码、不 commit、不 push**。
  - 护栏：若 Codex 尝试写业务文件，脚本拦截/中止并报 `[ERR]`。
- `codex_dev.sh --task <TASK-ID> [--plan <file>]`
  - 开发模式启动 Codex CLI，允许 workspace-write。
  - 完成后自动调 `run_tests.sh --scope all`。
  - 硬护栏：❌ 改 `.env`/token/webhook/密钥；❌ git push/merge/deploy；❌ 删数据；❌ 真实发送（除非显式 `--run-send --confirm-observation-only` 且你授权）；❌ 自动交易；✅ dry-run 默认。
  - 本次 dev 范围严格限定 `scripts/ai/` + `docs/` 新增。
- `run_tests.sh --task <TASK-ID> [--scope unit|integration|all] [--real]`
  - 运行 pytest（按范围）；退出码非 0 即失败。
  - 护栏：默认 dry-run / mock webhook，不真实发送、不自动交易；`--real` 需显式且人工确认；日志过滤 `webhook|token|password|secret`。
- `collect_result.sh --task <TASK-ID> [--format md|json]`
  - 收集 `git diff --stat`、改动清单、`run_tests.sh` 报告、plan 结论。
  - 产出 `scripts/ai/.out/<task-id>/result_bundle.md`；敏感字段一律脱敏为 `[REDACTED]`。
  - ❌ 不 push；❌ 不写密钥。
- `make_delivery_summary.sh --task <TASK-ID> --bundle <file>`
  - 按 UX_VISUAL_SPEC.md §3 + STATION_CONFIG.md §21 生成交付摘要 `delivery_summary.md`。

**3 份文档**
- `docs/tasks/TASK_TEMPLATE.md`：复制 STATE_MACHINE_TICKET.md §3 的 21 字段模板（含状态门控说明）。
- `docs/workflows/ai_delivery_workflow.md`：从 STATION_CONFIG.md §15–23 提炼为可执行 SOP，标注每步状态门与人工确认点。
- `docs/workflows/status_machine.md`：复制 STATE_MACHINE_TICKET.md §1–2 的 10 状态定义、推进责任速查表、失败回滚。

## 12. 交互视觉要求
- 脚本日志格式统一（见 §11），便于 Mac mini `newsyslog` 轮转与人工阅读。
- 企业微信交付摘要结构遵循 UX_VISUAL_SPEC.md §3（命令 13 精简版 + 文档完整版）。
- 本任务不新增 Dashboard / 页面 / 企业微信消息格式设计，无额外 UI 要求。

## 13. 安全权限要求（必填，外部/凭证类）
- ❌ 脚本不得读取 / 打印 / 写入 `.env`、token、webhook、RQData 密钥。
- `collect_result.sh` 必须扫描产物中的密钥值并脱敏为 `[REDACTED]`；脱敏规则对齐 SECURITY_HANDBOOK.md §11。
- `codex_dev.sh` 禁止自动 git push/merge/release/deploy。
- 真实发送 / 真实测试（`--real`）需显式参数 **且** 人工确认，默认禁止。
- 安全与权限专家对脚本草案有一票否决权（尤其 `.env` 访问、自动 push、`rm -rf`、全权限 mode）。
- 所有脚本：不得包含 `rm -rf`、不得硬编码密钥、不得使用全权限 mode、不删数据。
- 本地产物目录 `scripts/ai/.out/` 应加入 `.gitignore`（避免密钥/中间产物误入版本库）。

## 14. 开发步骤
1. 创建 `scripts/ai/` 目录与 `.out/` 子目录；将 `.out/` 加入 `.gitignore`。
2. 实现 `codex_plan.sh`（只读 plan，写 `.out/<id>/plan.md`）。
3. 实现 `codex_dev.sh`（workspace-write + 护栏 + 自动调 run_tests）。
4. 实现 `run_tests.sh`（dry-run 默认，日志脱敏过滤）。
5. 实现 `collect_result.sh`（脱敏汇总 result_bundle）。
6. 实现 `make_delivery_summary.sh`（交付摘要，结构对齐 UX_VISUAL_SPEC）。
7. 创建 `docs/tasks/TASK_TEMPLATE.md`（21 字段）。
8. 创建 `docs/workflows/ai_delivery_workflow.md`。
9. 创建 `docs/workflows/status_machine.md`。
10. 本地校验：`bash -n` 全部脚本语法检查；干跑（不真实调 Codex，仅验证参数解析与护栏分支打印）。
> 每步均不需真实写入/发送；真实调用 Codex 属 CODING 阶段、需你确认开发后由 CodeBuddy 执行。

## 15. Codex Plan Prompt
```
你现在是 Codex CLI，处于 plan（只读）模式。任务单见 tasks/TASK-2026-07-09-001-workstation-scaffold.md。

要求：
1. 只读取仓库与文档，不写任何业务代码（services/ packages app docs/ 等既有文件不改）。
2. 仅可将 plan 文本写入 scripts/ai/.out/<task-id>/plan.md（若该目录不存在先创建）。
3. 产出 plan.md，包含：
   - scripts/ai/ 下 5 个脚本的职责、入参、行为、护栏、退出码；
   - 每个脚本与 COLLAB_PROTOCOL.md §6–9 契约的逐条对齐说明；
   - 3 份 docs 文档的章节大纲；
   - 新增/改动文件清单（仅 scripts/ai/ + docs/）；
   - 风险与待你确认项（如 Codex CLI 调用方式、.gitignore 改动）。
4. 严格遵守：不碰业务代码/数据/策略/.env，不 git push/merge/deploy，不真实发送。

输出后等待用户确认 plan。
```

## 16. Codex Dev Prompt
```
你现在是 Codex CLI，处于 dev（workspace-write）模式，执行已批准 plan：scripts/ai/.out/TASK-2026-07-09-001/plan.md。

范围（严格限定，越界即中止）：
- 新建 scripts/ai/ 下 5 个 shell 脚本 + scripts/ai/.out/ 目录；
- 新建 docs/tasks/TASK_TEMPLATE.md、docs/workflows/ai_delivery_workflow.md、docs/workflows/status_machine.md；
- 修改 .gitignore 追加 scripts/ai/.out/。

禁止（硬约束）：
- 修改任何业务/数据/策略模块；
- 读取或写入 .env / token / webhook / RQData 密钥；
- git push / merge / release / deploy；
- 删除历史数据、rm -rf、全权限 mode；
- 真实发送企业微信、自动交易、生成订单草稿；
- 任何把密钥写入日志/payload/文档的行为。

完成后：
- 对所有脚本运行 bash -n 语法检查；
- 干跑验证参数解析与护栏分支（不真实调用 Codex、不真实发送）；
- 输出 git diff --stat 供 review。退出码 0 表示成功。
```

## 17. CodeBuddy 执行 Prompt
```
CodeBuddy：请按协作协议（COLLAB_PROTOCOL.md）执行任务单 tasks/TASK-2026-07-09-001-workstation-scaffold.md。

步骤：
1. 校验状态为 APPROVED_DEV 且 plan 已批准（否则回传「状态不符」）。
2. 护栏自检（任一命中即中止）：要求改 .env/token/webhook？自动 push/merge/deploy？删数据？自动交易？→ 中止并报安全专家。
3. 调用 scripts/ai/codex_plan.sh --task TASK-2026-07-09-001 生成 plan（若尚未生成）。
4. 经用户确认 plan 后，调用 scripts/ai/codex_dev.sh --task TASK-2026-07-09-001 --plan <plan> 实现。
5. 调用 scripts/ai/run_tests.sh --task TASK-2026-07-09-001 --scope all（默认 dry-run）。
6. 调用 scripts/ai/collect_result.sh --task TASK-2026-07-09-001 汇总并脱敏。
7. 调用 scripts/ai/make_delivery_summary.sh --task TASK-2026-07-09-001 --bundle <result_bundle> 生成交付摘要。
8. 回传结果摘要给 WorkBuddy / 用户。不自动 push / merge / deploy。
```

## 18. 测试清单
- [ ] 全部 5 个脚本通过 `bash -n` 语法检查（单元/烟测）
- [ ] `codex_plan.sh` 在只读模式下不修改仓库（`git status` 保持干净，仅 `.out/` 新增）（集成）
- [ ] `codex_dev.sh` 不触碰业务/数据/策略文件（`git diff` 验证仅 scripts/ai/ + docs/ 新增）（集成）
- [ ] `run_tests.sh` 默认 dry-run，不真实发送企业微信（mock webhook 验证）（告警测试）
- [ ] `collect_result.sh` 对含密钥的测试产物能脱敏（脱敏单测样例）（数据一致性/安全）
- [ ] `make_delivery_summary.sh` 产出符合 UX_VISUAL_SPEC.md §3 结构的摘要（烟测）
- [ ] `docs/tasks/TASK_TEMPLATE.md` 含完整 21 字段（文档校验）
- [ ] `docs/workflows/` 两文档与 STATION_CONFIG.md 内容一致（文档校验/回归）
- [ ] 安全专家复核：脚本无 `.env` 读取、无自动 push、无 `rm -rf`（安全门）
- [ ] 本地干跑：参数解析与护栏分支打印正确，退出码符合预期（烟测）

## 19. 验收标准
- **pass 条件**（全部满足）：
  1. 5 个脚本存在于 `scripts/ai/` 且已 `chmod +x`；
  2. `git diff --stat` 仅含 `scripts/ai/`（新增）+ `docs/`（新增）+ `.gitignore` 一行，无任何业务/数据/策略改动；
  3. 全部脚本 `bash -n` 通过；
  4. 3 份文档创建且内容与工作站基线（Baseline v1.0）一致；
  5. 脱敏验证通过——无任何密钥出现在产物/日志（`collect_result.sh` 单测样例）；
  6. 全程未触发任何 push/merge/deploy（用户确认无远程动作）。
- **block 条件**（任一即不通过）：
  - 脚本读取/写入 `.env` 或硬编码密钥；
  - `git diff` 含业务/数据/策略文件改动；
  - 含 `rm -rf` 或全权限 mode；
  - 真实发送企业微信或真实写入数据库历史；
  - 自动 push/merge/deploy。

## 20. 风险点
- **R1 Codex CLI 未安装/未登录**：脚本应检测并清晰报错（`[ERR] codex not found`），不静默失败。
- **R2 dev 范围扩大改业务代码**：用 `git diff` 范围校验 + 护栏自检拦截；越界即 FAILED。
- **R3 密钥泄漏到产物**：`collect_result.sh` 脱敏 + 安全专家一票否决；脱敏单测覆盖。
- **R4 脚本含 `rm -rf` / 全权限**：安全审查禁止，纳入 §18 安全门。
- **R5 真实发送误开**：`run_tests.sh` 默认 dry-run，`--real` 需人工确认（COLLAB §8）。
- **R6 Mac mini 脚本权限/路径**：DevOps 确认 `chmod +x` 与绝对路径；产物目录 `.out/` 不污染仓库。
- **R7 文档与基线漂移**：3 份文档须逐条对齐 STATION_CONFIG.md，交付专家复核。

## 21. 交付记录
- 状态流转：IDEA → REQUIREMENT_READY（本单） → [待你确认 PRD] → PLAN_READY → APPROVED_DEV → CODING → TESTING → DELIVERY_READY → CLOSED
- 测试结论：待 TESTING 阶段填写（pass / block）
- 交付报告：待 DELIVERY_READY 由 WorkBuddy 产出
- 合并前检查：待填写（git diff --check / 测试通过 / 无敏感泄露）
- 用户 review：待（不自动 merge / deploy）
- 下一阶段建议：脚手架落地后，可拿一个真实想法 dry-run 半自动闭环；或直接进入「Mac mini 部署任务」实现 launchd/run_loop。
