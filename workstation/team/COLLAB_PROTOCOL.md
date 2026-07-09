# 归一量化 WorkBuddy-CodeBuddy-Codex CLI 协作协议

生成时间：2026-07-09
版本：v1.0
用途：明确 WorkBuddy / CodeBuddy / Codex CLI / 你（用户）四方在半自动开发流程中的职责、触发时机、调用契约与权限边界。
配套文档：`ROLE_SPEC.md`（12 角色）、`TASK_MATRIX.md`、`STATE_MACHINE_TICKET.md`（10 状态）、`DAILY_COMMANDS.md`（命令 10/11/12/13/14）、`TEST_EXPERT_HANDBOOK.md`（失败处理）。

---

## 0. 四方分工总览

| 角色 | 本质 | 负责 | 不负责 |
|---|---|---|---|
| **你（用户）** | 决策者 | 确认任务 / plan / 是否开发 / 是否 push·merge·deploy | 不参与具体执行 |
| **WorkBuddy** | 需求·产品·测试·交互·交付·任务管理 | 出任务单、出三类 Prompt、出测试清单/结论、出交付报告、维护状态机 | 不直接改仓库业务代码、不执行脚本 |
| **CodeBuddy** | 本地执行入口（Mac mini） | 读任务单、调脚本、调 Codex CLI、跑测试、汇总结果回传 | 不做需求/设计决策、不越权 |
| **Codex CLI** | 主力开发执行器 | plan（只读）、代码修改、测试修复、代码审查 | 不自动 push/merge/deploy、不碰密钥、不删数据、不交易 |

> 铁律：**先 plan，后开发**；**plan 只读**；**dev 仅允许 workspace-write**；**任何 push/merge/deploy 必须由你显式执行**。

---

## 1. WorkBuddy 什么时候生成任务单

**触发**：
- 你发送 `DAILY_COMMANDS` 命令 1（生成任务单）或任意「想法/需求」类消息；
- 或 `下一阶段规划`（命令 16）产出新 TASK 方向后，你确认启动。

**动作**：
- 按 `STATE_MACHINE_TICKET.md` 的 21 字段标准任务单模板，产出 `TASK-日期-编号`；
- 角色：项目经理（编号+状态）+ 产品负责人（需求）；
- 必含：测试清单、验收标准、风险点（即便未开发）；
- 状态置为 `REQUIREMENT_READY` 或 `PLAN_READY`。

**不生成任务单的情况**：
- 纯问答、闲聊、状态查询；
- 已存在同意图未关闭任务单（应先复用/更新，不重复建单）。

---

## 2. WorkBuddy 什么时候生成 CodeBuddy 执行 Prompt

**触发**：任务状态到达 `APPROVED_DEV`（你已确认 plan、确认开发）。

**动作**（对应命令 10、任务单第 17 节）：
- 产出可复制给 CodeBuddy 的《CodeBuddy 执行 Prompt》文本；
- 内容：指向已确认 plan、涉及模块/接口/测试点、调用 `codex_dev.sh` 的指令、dry-run 默认与越权护栏声明；
- 角色：后端开发负责人 + 项目经理。

**不生成的情况**：plan 未确认（`PLAN_READY` 之前不进此步）。

---

## 3. WorkBuddy 什么时候生成 Codex Plan Prompt

**触发**：任务状态 `PLAN_READY`（任务单已具备需求/技术方案要点，待生成只读 plan）。

**动作**（对应命令 11、任务单第 15 节）：
- 产出《Codex Plan Prompt》文本，供 CodeBuddy 喂给 `codex_plan.sh`；
- 内容：范围、约束（V1 不自动交易、active Gate、Stage 9 Gate、XMA 不进正式信号）、涉及模块/文件、只读 plan 要求；
- 角色：后端开发负责人（+ 量化架构师可选）。

**不生成的情况**：需求/技术方案未就绪，应先走命令 3/4/5 评审。

---

## 4. WorkBuddy 什么时候生成 Codex Dev Prompt

**触发**：`APPROVED_DEV` 且 plan 已确认（通常紧随命令 11 的 plan 结论）。

**动作**（对应命令 12、任务单第 16 节）：
- 产出《Codex Dev Prompt》文本，供 CodeBuddy 喂给 `codex_dev.sh`；
- 内容：基于已确认 plan 的开发指令、模块/接口/测试点/验收点、dry-run 默认、外部凭证/真实发送需显式授权字样；
- 角色：后端开发负责人。

**不生成的情况**：plan 未确认（必须先 plan 后开发）。

---

## 5. CodeBuddy 收到任务后先做什么

1. **读任务单**：定位 `workstation/tasks/TASK-<编号>.md`，读取状态、类型、参与角色、护栏。
2. **状态校验**：
   - `PLAN_READY` → 调 `codex_plan.sh`（只读 plan）；
   - `APPROVED_DEV` → 调 `codex_dev.sh`（开发）；
   - 其他状态 → 不上手，回传「状态不符，等待 WorkBuddy/你确认」。
3. **护栏自检**（任一命中则中止并回报）：
   - 是否要求改 `.env`/token/webhook/密钥？→ 中止；
   - 是否要求自动 push/merge/deploy？→ 中止；
   - 是否要求删数据？→ 中止；
   - 是否要求自动交易？→ 中止（最高优先级）。
4. **确认本地环境**：Codex CLI 可用、仓库在 Mac mini 本地、测试依赖就绪。
5. **执行对应脚本**并收集结果（见 6–9）。

---

## 6. CodeBuddy 如何调用 codex_plan.sh

**脚本契约**（由 CodeBuddy 在 Mac mini 实现，建议位于 `scripts/codex_plan.sh`）：

```bash
scripts/codex_plan.sh --task <TASK-ID> [--prompt <plan_prompt_file>]
```

- **输入**：任务单第 15 节《Codex Plan Prompt》（WorkBuddy 产出）。
- **行为**：
  - 以**只读模式**启动 Codex CLI（`plan` mode）；
  - Codex 只读取仓库、产出 plan 文本，写入 `workstation/tasks/<TASK-ID>/plan.md`；
  - 不修改任何仓库业务代码、不 `git commit`、不 `git push`、不写数据库、不发送。
- **输出**：`plan.md` + 控制台摘要。
- **护栏**：若 Codex 尝试写文件，脚本应拦截/中止。

> 仅当 plan 经你确认后，才进入 dev 阶段。

---

## 7. CodeBuddy 如何调用 codex_dev.sh

**脚本契约**（建议 `scripts/codex_dev.sh`）：

```bash
scripts/codex_dev.sh --task <TASK-ID> [--plan <plan_file>]
```

- **输入**：已确认 `plan.md` + 任务单第 16 节《Codex Dev Prompt》。
- **行为**：
  - 以**开发模式**启动 Codex CLI，允许在 workspace（仓库目录）内写文件；
  - Codex 按 plan 修改代码、修复测试；
  - 完成后自动调用 `run_tests.sh` 跑测试；
- **输出**：代码改动 + 测试结果。
- **护栏（dev 模式硬约束）**：
  - ❌ 不修改 `.env`/token/webhook/密钥；
  - ❌ 不 `git push`/`git merge`/`git deploy`；
  - ❌ 不删除数据（DB 记录、parquet、日志）；
  - ❌ 不真实发送企业微信（除非 CLI 显式 `--run-send --confirm-observation-only` 且你授权）；
  - ❌ 不自动交易、不生成订单草稿；
  - ✅ 默认 dry-run / observation-only。

---

## 8. CodeBuddy 如何调用 run_tests.sh

**脚本契约**（建议 `scripts/run_tests.sh`）：

```bash
scripts/run_tests.sh --task <TASK-ID> [--scope unit|integration|all]
```

- **输入**：任务单第 18 节《测试清单》+ 仓库 `services/quant-api/tests/`。
- **行为**：
  - 运行 pytest（按范围），采集通过/失败/跳过；
  - 跑数据一致性 / 策略 / 告警专项用例（按任务类型）；
  - 退出码非 0 表示测试失败。
- **护栏**：
  - 测试不得真实发送 webhook、不得自动交易；
  - 告警测试默认走 dry-run / mock webhook；
  - 日志过滤 `webhook`/`token`/`password`/`secret`。

---

## 9. CodeBuddy 如何调用 collect_result.sh

**脚本契约**（建议 `scripts/collect_result.sh`）：

```bash
scripts/collect_result.sh --task <TASK-ID> [--format md|json]
```

- **行为**：
  - 收集 `git diff --stat`、改动文件清单、测试报告（来自 `run_tests.sh`）、plan 结论；
  - 生成结构化结果包 `workstation/tasks/<TASK-ID>/result_bundle.md`（或 .json）；
  - 输出摘要供 CodeBuddy 回传。
- **护栏**：
  - ❌ 不 `git push`；
  - ❌ 不写入 `.env`/密钥；结果包中敏感字段一律脱敏/剔除。

---

## 10. CodeBuddy 不允许做什么

- ❌ 自动 `git push` / `git merge` / `git deploy`；
- ❌ 修改 `.env` / token / webhook / 任何密钥；
- ❌ 删除数据（DB 记录、parquet、日志）；
- ❌ 自动交易、生成订单草稿；
- ❌ 在 plan 未确认时调用 `codex_dev.sh`；
- ❌ 跳过 `run_tests.sh` 直接宣布完成；
- ❌ 把密钥/webhook 写进结果包或回传消息；
- ❌ 自行修改任务单状态越过你确认（仅 WorkBuddy 维护状态机）；
- ❌ 自行决定需求/设计方向（那是 WorkBuddy + 你的事）。

---

## 11. Codex Plan Mode 权限边界

- ✅ 读取仓库全部文件、文档、任务单；
- ✅ 运行只读分析（grep、解析、dry-run 检查）；
- ✅ 产出 plan 文本到 `workstation/tasks/<TASK-ID>/plan.md`；
- ❌ 修改仓库业务代码（`services/`、`packages/`、`docs/` 等）；
- ❌ `git commit` / `git push` / `git merge`；
- ❌ 写数据库、删数据、发网络请求（含 webhook）；
- ❌ 读 `.env` / 打印密钥。

---

## 12. Codex Dev Mode 权限边界

- ✅ 在 workspace（仓库目录）内创建/修改代码文件；
- ✅ 编写/修改测试；
- ✅ 运行本地测试（含 dry-run）；
- ✅ `git add` / `git commit`（仅本地提交，便于你 review；**不 push**）；
- ❌ `git push` / `git merge` / `git deploy`；
- ❌ 修改 `.env` / token / webhook / 密钥文件；
- ❌ 删除数据（DB 记录、parquet、日志）；
- ❌ 真实发送企业微信（除非显式 `--run-send --confirm-observation-only` 且你授权）；
- ❌ 自动交易、订单草稿；
- ❌ 任何把密钥写入日志/payload/文档的行为。

---

## 13. 测试失败时如何处理

见 `TEST_EXPERT_HANDBOOK.md` §8 + `DAILY_COMMANDS` 命令 14 + 状态机失败线。

```text
run_tests.sh 退出非 0
  → CodeBuddy 调 collect_result.sh 收集失败日志
  → 回传你 + WorkBuddy（附失败摘要）
  → WorkBuddy 出《失败复盘报告》（命令 14）：根因分类 / 影响 / REPLAN 方向 / 回归用例 / 验收标准 / 风险点
  → 状态：FAILED →（你确认）→ REPLAN → PLAN_READY
  → 修复后重走：单元→集成→数据/策略/告警→回归
  → P0 红线级（自动交易/误发/密钥泄露/active 污染）：立即止损 + 安全专家一票否决，不自动恢复
```

---

## 14. 开发完成后如何交付给 WorkBuddy

1. `codex_dev.sh` 完成 + `run_tests.sh` 通过（或明确遗留项）；
2. CodeBuddy 调 `collect_result.sh` 生成 `result_bundle.md`；
3. CodeBuddy 把结果包摘要回传给你（企业微信/微信）；
4. 你把结果包或摘要转发给 WorkBuddy，或直接在微信发 `DAILY_COMMANDS` 命令 13（开发结果交付报告）；
5. WorkBuddy 将任务状态推进到 `DELIVERY_READY`，并产出交付报告；
6. **你**最终 review → 命令 15（合并前检查）→ 你执行 merge / deploy（CodeBuddy/WorkBuddy 均不代劳）。

---

## 15. WorkBuddy 如何根据结果生成交付报告

**触发**：你发送命令 13，附 `result_bundle` 或开发结果。

**动作**（交付专家主导 + 测试专家结论 + 项目经理状态）：
- 按 `STATE_MACHINE_TICKET.md` / `TEST_EXPERT_HANDBOOK.md` §7 的《交付测试结论模板》填充；
- 内容：交付摘要、验收标准逐条对照、测试结论、合并前检查清单、上线步骤与回滚建议、下一阶段建议、风险点；
- 状态建议：`DELIVERY_READY` →（你 review 通过）→ `CLOSED`；
- ❌ 不自动 merge / deploy，只产出报告供你决策。

---

## 附录 A：主流程时序（半自动闭环）

```
你 ──想法──▶ WorkBuddy ──命令1 任务单──▶ [REQUIREMENT_READY/PLAN_READY]
你 ──确认──▶ WorkBuddy ──命令11 Codex Plan Prompt──▶ CodeBuddy
CodeBuddy ──codex_plan.sh(只读)──▶ Codex CLI ──plan.md──▶ CodeBuddy ──回传──▶ 你
你 ──确认 plan + 确认开发──▶ WorkBuddy ──命令10/12 执行/Dev Prompt──▶ CodeBuddy
CodeBuddy ──codex_dev.sh(workspace-write)──▶ Codex CLI ──改代码──▶ codex_dev 自动调 run_tests.sh
CodeBuddy ──collect_result.sh──▶ result_bundle ──回传──▶ 你 ──▶ WorkBuddy
WorkBuddy ──命令13 交付报告──▶ [DELIVERY_READY]
你 ──命令15 合并前检查──▶ WorkBuddy ──检查结论──▶ 你 ──merge/deploy──▶ [CLOSED]
```

任一环节失败 → 命令 14 失败复盘 → FAILED → REPLAN → PLAN_READY。

## 附录 B：九条必须遵守（贯穿全文，无条件生效）

1. 先 plan，后开发。
2. plan 只读。
3. dev 仅允许 workspace-write。
4. 不允许自动 push。
5. 不允许自动 merge。
6. 不允许自动 deploy。
7. 不允许修改 `.env` / token / webhook / 密钥。
8. 不允许删除数据。
9. 不允许启动自动交易。

任何脚本/角色违反以上任一条，立即中止并回报你与安全专家。
