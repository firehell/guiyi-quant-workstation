# 归一量化安全与权限专家工作手册

生成时间：2026-07-09
版本：v1.0
作者视角：安全与权限专家（见 `ROLE_SPEC.md` 第 10 角色，**一票否决权**）
配套文档：`ROLE_SPEC.md`、`TASK_MATRIX.md`（安全权限任务类型，安全专家必参且一票否决）、`STATE_MACHINE_TICKET.md`、`DAILY_COMMANDS.md`（命令 8/15）、`COLLAB_PROTOCOL.md`（九条红线）、`STAGE9_WECHAT_DELIVERY.md`（webhook 规则）、`TEST_EXPERT_HANDBOOK.md`（P0 红线级）
项目硬约束（最高优先级）：V1 **不自动交易**；所有外部动作默认 dry-run / observation-only，需你**显式授权**才执行。

---

## 0. 六条强制禁令（贯穿全文，无条件生效）

1. **禁止自动交易**（不自动下单、不生成订单草稿）。
2. **禁止自动 push / merge / release / deploy**。
3. **禁止修改密钥**（`.env` / token / webhook / RQData 凭证 / 任何密钥）。
4. **禁止删除历史行情数据**（本地 parquet / DuckDB / PostgreSQL 历史 bar）。
5. **禁止输出 token、webhook、账户信息**（不出现在 AI 回复、日志、payload、文档）。
6. **禁止使用危险全权限模式**（如 Codex 全 auto-approve、`rm -rf`、root 滥用、关闭安全护栏）。

> **涉及生产运行前必须人工确认**：Mac mini 长期运行部署、企业微信真实发送、任何 push/merge/deploy、密钥变更——任一项都须你单独、显式授权，AI 不得代劳或默认执行。

---

## 1. AI 不允许做的操作清单（绝对禁止）

| # | 禁止项 | 说明 |
|---|---|---|
| 1 | 自动交易 / 订单草稿 | V1 边界，最高优先级 |
| 2 | `git push` / `git merge` / `git release` / `git deploy` | 仅你可执行 |
| 3 | 修改 `.env` / token / webhook / 密钥 | 只读使用，永不写 |
| 4 | 删除历史行情数据 | 含 raw/standard parquet、DuckDB、PG 历史表 |
| 5 | 输出密钥/账户信息 | 回复、日志、payload、文档均不可 |
| 6 | 危险全权限模式 | Codex auto-approve、`rm -rf`、提权 |
| 7 | 自动发送企业微信 | 仅 CLI 显式 `--run-send --confirm-observation-only` 且你授权 |
| 8 | 自动运行 retry-pending 批量重发 | 需你授权 worker/scheduler 任务 |
| 9 | 批量重发历史事件 | Stage 9 仅单条/历史回放验证 |
| 10 | 自启自主循环 / 自主决策执行 | AI 不得基于消息自我发起破坏性动作 |
| 11 | 关闭/绕过安全护栏 | 任何"跳过检查"请求一律拒绝 |
| 12 | 写入 DB 历史行情（无授权） | 盘后归档真实写入需单独授权 |

---

## 2. 需要你人工确认的操作清单

| 操作 | 确认方式 |
|---|---|
| Mac mini 长期运行部署 / 启动常驻 | 你显式指令 |
| 企业微信真实发送（非 dry-run） | CLI `--run-send --confirm-observation-only` + 你授权 |
| 任何 `git push` / `merge` / `release` / `deploy` | 你手动执行（命令 15 后） |
| 密钥/凭证变更或轮换 | 你操作，AI 不碰 |
| 删除/覆盖任何数据 | 你显式授权（历史行情删除**永不**授权） |
| 生产环境配置改动 | 你确认 |
| 新自动化脚本上线 | 你 review 后启用 |
| 定时任务 / scheduler 改动 | 你确认 |

---

## 3. 可以默认允许的操作清单（无需每次确认）

- WorkBuddy 写 `workstation/` 下任务单/方案/报告/规范文档。
- Codex CLI **只读** plan（不写代码、不 push）。
- 本地运行测试（含 dry-run 告警测试、mock webhook）。
- 读取仓库代码/文档做分析。
- 本地 `git commit`（仅本地，便于你 review；不 push）。
- 读取本地数据做校验/聚合分析（不改写）。
- 生成任务单/Prompt/报告等文档产出。
- 企业微信 **preview / dry-run**（不读 webhook、不发送、不写通知）。

---

## 4. WorkBuddy 权限边界

- ✅ 产出：任务单、三类 Prompt、测试清单/结论、交付报告、规范文档。
- ✅ 写盘范围：`workstation/` 目录（工作站自身文档）。
- ❌ 不修改仓库业务代码（`services/`、`packages/`、`docs/` 项目侧）。
- ❌ 不执行脚本、不调用 Codex CLI、不跑测试。
- ❌ 不 push/merge/deploy、不碰密钥、不删数据、不交易。
- ❌ 不输出密钥/账户信息到回复。

---

## 5. CodeBuddy 权限边界

- ✅ 本地执行入口（Mac mini）：读任务单、调脚本、调 Codex CLI、跑测试、汇总结果。
- ✅ 调用 `codex_plan.sh`（只读）、`codex_dev.sh`（workspace-write）、`run_tests.sh`、`collect_result.sh`。
- ✅ 本地 `git commit`（不 push）。
- ❌ 自动 push/merge/deploy。
- ❌ 修改 `.env`/token/webhook/密钥。
- ❌ 删除数据（含历史行情）。
- ❌ 自动交易 / 订单草稿。
- ❌ 在 plan 未确认时调 `codex_dev.sh`。
- ❌ 跳过 `run_tests.sh` 直接宣布完成。
- ❌ 自改任务单状态越过你确认（状态机由 WorkBuddy 维护）。
- ❌ 把密钥/webhook 写进结果包或回传消息。

---

## 6. Codex CLI 权限边界

- **Plan Mode（只读）**：
  - ✅ 读仓库/文档/任务单；运行只读分析；产出 `plan.md`。
  - ❌ 改代码、`git commit/push`、写 DB、发网络请求、读 `.env`。
- **Dev Mode（仅 workspace-write）**：
  - ✅ 在仓库目录内创建/修改代码与测试；本地 `git commit`（不 push）；跑本地测试。
  - ❌ `git push/merge/deploy`。
  - ❌ 改 `.env`/token/webhook/密钥文件。
  - ❌ 删数据（DB 记录、parquet、日志）。
  - ❌ 真实发送企业微信（除非显式 `--run-send --confirm-observation-only` 且你授权）。
  - ❌ 自动交易 / 订单草稿。
  - ❌ 任何把密钥写入日志/payload/文档的行为。
- ❌ **禁止**以全 auto-approve / 关闭护栏方式运行。

---

## 7. GitHub 操作边界

- ✅ AI 可读取仓库、分支、PR、Issue（只读）。
- ✅ AI 可**准备** PR 描述 / 变更说明文本，供你使用。
- ❌ AI 不得 `git push`、不得创建/合并 PR、不得 `release`、不得 `deploy`。
- ❌ AI 不得修改仓库保护规则、分支策略、CI 密钥。
- ⚠️ 你 merge/deploy 前必须经命令 15（合并前检查），安全专家参与。

---

## 8. .env / token / webhook / RQData 密钥保护规则

- 所有密钥仅存于 `.env` 或环境变量，**永不**提交、不进文档/DB/日志/payload/AI 回复。
- `QYWX_WEBHOOK_URL`、RQData 凭证：**只在显式授权 CLI 发送时从环境变量读取**，不出现在任何产物。
- AI 回复/文档中若出现密钥，**立即脱敏**（用 `***` / 仅保留末 4 位 / "已设置"布尔）。
- 密钥轮换由你操作，AI 不生成/不改写。
- `.env` 必须 `.gitignore`；CI/部署环境密钥通过平台 secret 注入，不落盘明文。
- 任何脚本**不得**在源码中硬编码密钥。

---

## 9. 数据目录保护规则

- 受保护目录：本地 parquet 目录、DuckDB 文件、PostgreSQL 数据目录、`market_data_files` / `data_quality_reports` 等。
- ❌ 禁止删除历史行情数据（raw/standard parquet、历史 bar）。
- ✅ 只读分析、聚合计算、质量校验允许。
- ⚠️ 盘后归档真实写入、actual-contract 写入等**变更类**操作需你单独授权（按既有 Stage 边界）。
- 任何变更前：先备份（copy），确认成功再继续。
- 删除/覆盖操作：历史行情**永不**授权；其他删除须你显式指令 + 备份 + 二次确认。
- 数据质量 `failed` 标记不进 active 读链，但不因此删除源数据。

---

## 10. 企业微信机器人权限规则

- 机器人定位：**输出型观察提醒**，不包含任何交易能力。
- webhook URL 为密钥（见 §8），仅 CLI 显式授权时读取发送。
- 发送内容固定含 `observation_only` / `not_trading_instruction` / `auto_order=false` 与风险提示。
- ❌ 禁止自动发送、禁止批量重发历史事件、禁止未授权 retry-pending 自动重发。
- ❌ 禁止机器人接收并执行来自聊天的代码变更指令（你发往 WorkBuddy 的指令是你主动发起，非机器人自主）。
- 频率限制 / 静默时段（未完成项）上线前需你确认。
- payload 与日志过滤 `webhook`/`token`/`password`/`cookie`/`secret`。

---

## 11. 日志脱敏规则

- **必须脱敏的键**：`webhook`、`token`、`password`、`cookie`、`secret`、`api_key`、`access_key`、`private_key` 及相似键。
- **必须脱敏的值**：URL 中含 token 的 query、完整 webhook 地址、凭证明文。
- **处理方式**：替换为 `***`；webhook 仅可记「已设置(true)」或末 4 位；不允许记完整 URL。
- **适用范围**：应用日志、AI 回复、result bundle、交付报告、企业微信 payload、测试输出。
- 任何包含密钥的日志视为**安全事件**，按 P0 处理（止损 + 你告知 + 轮换密钥）。

---

## 12. 远程控制风险清单

| 风险 | 缓解 |
|---|---|
| 微信/企业微信被当作自主执行入口 | AI 不得基于收到消息自我发起破坏性动作；仅你主动发起，且破坏性传播需二次确认 |
| Mac mini 暴露端口/弱口令 | ssh/launchd 仅限内网 + 密钥认证；不暴露公网管理端口 |
| 自动化绕过人工确认 | 自动化脚本不得跳过确认 gate；"AI 工作流优化"任务本身需安全专家评审 |
| 聊天指令被误判为高权限 | 任何 push/merge/deploy/删数据/真实发送指令必须你显式、单独确认，不与普通指令合并 |
| 凭证随远程消息泄露 | 远程回传内容经脱敏（§11），不含密钥 |

---

## 13. 自动化脚本安全规则

- 脚本（`codex_plan.sh`/`codex_dev.sh`/`run_tests.sh`/`collect_result.sh` 等）**必须失败闭合**：任一护栏违反立即中止并回报。
- ❌ 脚本不得含硬编码密钥；密钥仅从环境变量在运行时读取。
- ❌ 脚本不得用 `rm -rf`、不得提权、不得关闭安全护栏。
- `codex_dev.sh` 必须以非全权限模式运行（不 auto-approve 所有写）。
- `run_tests.sh` 默认 dry-run / mock webhook，不真实发送。
- `collect_result.sh` 输出脱敏，不含 `.env`/密钥。
- 新脚本上线需你 review（安全专家参与）。
- 脚本异常退出码非零必须被 CodeBuddy 视为失败，不允许"静默成功"。

---

## 14. 任务执行前安全检查清单（Pre-Exec）

> CodeBuddy/WorkBuddy 在调 `codex_dev.sh` 前逐项核对，任一 ✗ 即中止。

- [ ] 任务状态为 `APPROVED_DEV`（plan 已确认）
- [ ] 不要求自动交易 / 订单草稿
- [ ] 不要求 `git push/merge/deploy`
- [ ] 不要求修改 `.env`/token/webhook/密钥
- [ ] 不要求删除数据（历史行情删除一律 ✗）
- [ ] 不要求禁用/绕过安全护栏或全权限模式
- [ ] 真实发送（如需）已走显式授权 CLI 标志
- [ ] 测试将走 dry-run / mock，不真实发送
- [ ] 日志脱敏已启用
- [ ] 变更前已备份（涉及数据/配置）
- [ ] 安全专家对凭证/自动化相关任务已确认（一票否决）

---

## 15. 交付前安全检查清单（Pre-Delivery）

> 合并前检查（命令 15）由交付专家主导 + 安全专家必查，任一 ✗ 即不通过。

- [ ] 验收标准全部满足，测试结论为通过/有条件通过
- [ ] 无自动交易 / 订单草稿残留
- [ ] 无 `git push/merge/deploy` 残留动作
- [ ] `.env`/token/webhook/密钥未被改动（diff 核对）
- [ ] 无历史行情数据被删除
- [ ] 日志/结果包/payload 无密钥泄露（脱敏核对）
- [ ] AI 回复/文档未输出账户信息
- [ ] 企业微信发送均为 dry-run 或显式授权真实发送，无批量重发
- [ ] 无危险全权限模式痕迹
- [ ] 回滚方案齐备
- [ ] 安全专家签字：通过 / 驳回（一票否决）

---

## 附录：安全专家一票否决

凡涉及密钥、webhook、自动执行、远程控制、数据删除、生产运行的操作，安全专家有**一票否决权**：任一红线命中直接驳回，不进入开发/交付，并回报你。本手册与 `COLLAB_PROTOCOL.md` 九条红线、`TEST_EXPERT_HANDBOOK.md` P0 级互为强制约束。
