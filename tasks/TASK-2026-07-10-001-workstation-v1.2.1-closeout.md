# TASK-2026-07-10-001：WORKSTATION-V1.2.1 工作站基线收口与 V1.3 前置验收

> 团队：归一量化产品与交付工作站
> 状态：REQUIREMENT_READY
> 任务类型：AI 工作流优化（基线收口 + Issue 检测修复 + E2E 验收）
> 生成：WorkBuddy（按 `STATE_MACHINE_TICKET.md` 21 字段模板 + V1.2 `## 0. 元信息` 扩展）
> 配套：STATION_CONFIG.md（Final v1.0）、COLLAB_PROTOCOL.md、SECURITY_HANDBOOK.md、status_machine.md、github_issue_trace_workflow.md
> 性质：**工作站基线收口任务**——对 V1.1/V1.2 做正式收口，修复 Issue 检测遗留问题，补齐 README 工作站入口，统一状态口径，执行 E2E dry-run 演练，形成 V1.2.1 验收报告与 V1.3 前置条件。不修改业务代码。

> **状态门控说明（务必先读）**：本任务单当前处于 `REQUIREMENT_READY`。下方第 15–17 节的《Codex Plan Prompt / Dev Prompt / CodeBuddy 执行 Prompt》是**随单携带的草案**，按状态机规则：
> - Plan Prompt 在 `PLAN_READY` 由 CodeBuddy 喂给 `codex_plan.sh` 执行（只读）；
> - Dev / Exec Prompt 在 `APPROVED_DEV` 才启用。
> **WorkBuddy 本次只产出本任务单文档，不修改代码、不执行任何脚本。** 实际改动在 `CODING` 阶段、且需你确认 plan 与开发后由 CodeBuddy → Codex CLI 执行（不 push / merge / deploy）。

---

## 0. 元信息

| 字段 | 值 |
|------|-----|
| Task ID | TASK-2026-07-10-001-workstation-v1.2.1-closeout |
| GitHub Issue | 待创建 |
| Branch | feature/workstation-v1.2.1-closeout |
| PR | 待创建 |
| Status | REQUIREMENT_READY |
| Created At | 2026-07-10 |
| Updated At | 2026-07-10 |
| Owner | WorkBuddy |

---

## 1. 任务状态

REQUIREMENT_READY

## 2. 任务类型

AI 工作流优化（基线收口 + Issue 检测修复 + E2E 验收）
- 关联：Issue 留痕流程优化（V1.2 增强）、工作站文档集成（README 入口补齐）、状态机口径核对
- 参照：TASK_MATRIX.md「12. AI 工作流优化」
- 是否允许进入代码开发阶段：**是**（严格限定 `scripts/ai/`、`README.md`、`workstation/`、`docs/tasks/`、`docs/workflows/`、`.github/ISSUE_TEMPLATE/`、测试文件；不碰业务/数据/策略/配置）

## 3. 参与角色

- **必须**：
  - 项目经理 / 流程调度员（编号、状态、拆分、卡点检查、状态口径核对）
  - 后端开发负责人（Issue 检测修复方案、脚本改动、三类 Prompt）
  - 测试专家 / QA Lead（Issue 检测正反例测试、E2E dry-run、回归测试、敏感信息扫描）
  - 安全与权限专家（护栏自检、deny-list 审核、敏感信息扫描确认）
  - DevOps / 本地运维部署专家（脚本部署路径、`scripts/ai/lib/` 目录确认）
  - 交付专家（验收报告、遗留清单、V1.3 前置条件、合并前检查）
- **可选**：
  - 量化架构师（评审 Issue 检测修复对既有流程的影响）
- **不需要**：
  - 产品负责人（非产品功能需求）
  - 量化业务专家（非数据/行情/交易日任务）
  - 策略研究员（非策略逻辑）
  - 数据工程师（非 RQData/聚合）
  - UX / 交互视觉专家（README 入口为导航表追加 + 简短说明，非页面设计）

## 4. 背景

- 工作站 V1.1（规程化 AI 开发流水线）和 V1.2（TASK ↔ GitHub Issue 留痕）已分别通过验收：
  - V1.1 验收记录：`docs/tasks/examples/V1.1-ACCEPTANCE.md` — 7 项验收标准全部 pass
  - V1.2 验收记录：`docs/tasks/examples/V1.2-ACCEPTANCE.md` — 10 项验收标准全部 pass，Issue #3 仍 open
- **Issue 检测逻辑现状与风险**：
  - `extract_issue_number()` 函数在 `comment_issue_result.sh` 和 `update_issue_status.sh` 中**代码完全重复**（awk 逐行对比确认）
  - 使用 awk 正则 `/#[0-9]+/` 匹配，只匹配 `#` 后跟纯数字
  - `create_issue_from_task.sh` 使用 Bash 正则 `^#[0-9]+$` 做严格校验
  - 当前逻辑对 "no issue" 类文本**理论上不会误判**（不含 `#数字`），但存在以下风险：
    - 如果字段值包含 `no issue (ref #5)` 会误提取 `#5`
    - 没有显式的反例 deny-list
    - 两个脚本中代码重复，维护风险
    - 没有单元测试覆盖
    - `#0` 会被匹配但不是有效 Issue 编号
- **README 缺口**：README 快速导航表不含 `workstation/STATION_CONFIG.md`，新读者无法从 README 得知 AI 工作站协作体系
- **状态口径需核对**：TASK-001/002 状态、Issue #3 label、`tasks/current.md`、状态机文档、验收记录之间可能存在不一致
- **E2E 流程需验证**：V1.2 的完整 Issue 留痕流程（TASK → Issue → Plan → Dev → Test → Collect → Delivery）需 dry-run 验证
- 需要先对 V1.1/V1.2 做正式收口，形成进入 V1.3 的稳定基线

## 5. 目标

1. **读取并核对当前仓库实际状态**，包括 README.md、workstation/STATION_CONFIG.md、CODEBUDDY.md、docs/tasks/、docs/workflows/、scripts/ai/、.github/ISSUE_TEMPLATE/、当前 V1.2 TASK 和 GitHub Issue
2. **修复 Issue 检测逻辑误判**：以下文本不能被判断为"已经绑定 Issue"：
   - `no issue`
   - `no GitHub issue`
   - `issue not required`
   - `尚未创建 Issue`
3. **增加 Issue 检测正反例测试**：
   - 正例：明确 Issue 编号或 URL
   - 反例：no issue、未创建、无需 Issue
   - 空值、格式错误、Issue 编号缺失
   - TASK 与 Issue 不匹配
4. **README 增加"AI 开发工作站"入口**，链接到 `workstation/STATION_CONFIG.md`、`CODEBUDDY.md`、工作流文档、TASK 模板。README 只做导航，不复制整套配置
5. **统一状态口径**：TASK 状态、GitHub Issue Label、`tasks/current.md`、工作站状态机、V1.1/V1.2 验收记录
6. **完整执行一次不修改业务代码的 E2E 演练**：TASK → Issue → Plan → Dev → Test → Collect → Delivery。演练只修改工作站测试文档或 fixture，不得修改归一量化业务代码
7. **形成 V1.2.1 验收报告、遗留清单和 V1.3 前置条件**

## 6. 不做事项

- ❌ 不实现 daemon / 常驻进程
- ❌ 不实现任务调度
- ❌ 不实现状态页面
- ❌ 不增加多项目支持
- ❌ 不修改 `services/`、`apps/`、`packages/` 下的任何业务代码
- ❌ 不修改 `data/` 下的任何数据文件
- ❌ 不修改策略代码、量化业务代码
- ❌ 不修改 `.env`、密钥、webhook
- ❌ 不 `git push` / `git merge` / `git release` / `git deploy`
- ❌ 不删除任何历史数据
- ❌ 不真实发送企业微信、不自动交易

## 7. 涉及模块

- **允许修改**：
  - `README.md`（导航表追加 + 新增"AI 开发工作站"章节）
  - `CODEBUDDY.md`（如状态口径核对发现需同步）
  - `workstation/`（如状态机文档需同步）
  - `scripts/ai/`（Issue 检测修复、测试脚本、E2E 脚本）
  - `docs/tasks/`（验收报告、fixture）
  - `docs/workflows/`（如口径核对发现需同步）
  - `.github/ISSUE_TEMPLATE/`（如需同步）
  - 相关测试文件
- **禁止修改**：
  - `services/`（全部）
  - `apps/`（全部）
  - `packages/`（全部）
  - `data/`（全部）
  - 策略代码（`strategies/`）
  - 量化业务代码
  - `.env` / `.env.*`
  - 密钥、webhook、token 文件

## 8. 产品需求

- 仓库状态核对无遗漏，产出核对结论表
- Issue 检测不再误判 `no issue` 类文本
- 正反例测试覆盖完整（正例 3+、反例 11+）
- README 有"AI 开发工作站"入口，两次点击内可达全部工作站入口
- 状态口径统一，产出核对表
- E2E dry-run 可复现，退出码 0
- V1.2.1 验收报告完整，含遗留清单和 V1.3 前置条件

## 9. 量化业务规则

- 本任务**不涉及期货业务规则**（非数据/策略/信号任务）
- 新增/修改文字必须继承 V1 约束：不自动交易、不把信号当交易指令；措辞与 SECURITY_HANDBOOK 六条禁令一致

## 10. 数据影响

- 无数据读写：不读取、不写入、不删除任何行情 / DB / parquet 数据
- 不触发 RQData、不写数据库、不真实发送企业微信
- dry-run 不触发真实 gh / Codex CLI / 企业微信

## 11. 技术方案

### 11.1 Issue 检测修复 — 公共函数抽取

- 新建 `scripts/ai/lib/issue_detect.sh`，包含：
  - `extract_issue_number()` 函数（统一版本，含 deny-list 检查）
  - `is_valid_issue_ref()` 函数（校验提取结果是否为有效正整数，排除 `#0`）
  - `ISSUE_DENY_LIST` bash 数组常量
- 修改 4 个脚本：
  - `comment_issue_result.sh`：删除内联 `extract_issue_number()`，改为 `source scripts/ai/lib/issue_detect.sh`
  - `update_issue_status.sh`：同上
  - `create_issue_from_task.sh`：检查 `EXISTING_ISSUE` 时增加 `is_valid_issue_ref` 二次校验
  - `run_v12_post_auth_e2e.sh`：`source` 公共函数替换内联 awk 逻辑

### 11.2 deny-list 设计

deny-list 包含 12 条反例文本：

| # | 文本 | 说明 |
|---|---|---|
| 1 | `no issue` | 英文否定 |
| 2 | `no GitHub issue` | 英文否定（全称） |
| 3 | `no github issue` | 英文否定（小写） |
| 4 | `issue not required` | 英文否定（不需要） |
| 5 | `尚未创建 Issue` | 中文否定 |
| 6 | `尚未创建issue` | 中文否定（无空格） |
| 7 | `N/A` | 标准空值 |
| 8 | `n/a` | 标准空值（小写） |
| 9 | `none` | 空值 |
| 10 | `pending` | 待定 |
| 11 | `-` | 占位符 |
| 12 | （空值） | 空单元格 |

额外排除：`#0`（不是有效 Issue 编号）

### 11.3 Issue 检测正反例测试

- 新建 `scripts/ai/test_issue_detect.sh`（独立可执行测试脚本）
- 正例 3 个：`#3`→`3`、`#12`→`12`、`#999`→`999`
- 反例 8 个（deny-list）：`no issue`、`no GitHub issue`、`issue not required`、`尚未创建 Issue`、`N/A`、`none`、`pending`、`-`
- 边界反例 3 个：`no issue (ref #5)`→空（deny-list 优先）、`#0`→空、空值→空

### 11.4 README 工作站入口

- 快速导航表追加：`查看 AI 工作站配置` → `workstation/STATION_CONFIG.md`
- 新增「AI 工作站与本地优先协作」章节，链接到 STATION_CONFIG.md、CODEBUDDY.md、工作流文档、TASK 模板
- 只做导航，不复制整套配置
- 含「非自动交易，仅信号提醒 / 人工观察」声明

### 11.5 E2E dry-run 演练

- 新建 `scripts/ai/run_v121_closeout_e2e.sh`
- 使用 fixture 任务文件（`GitHub Issue` 字段为 `pending`）
- 各阶段 mock：`--dry-run` 不调真实 gh/Codex；测试仅 bash -n + grep 扫描
- `git diff --stat` 范围校验：仅含允许修改路径

### 11.6 与 TASK-001 / TASK-002 的关系

- **TASK-001**（工作站脚手架脚本落地）：V1.2.1 修改其产出的 Issue 检测脚本，属增强修复，需回归验证 `bash -n` 通过
- **TASK-002**（README 工作站同步）：V1.2.1 Step 4 覆盖 TASK-002 的 README 入口目标。建议在验收报告中标注 TASK-002 可推进到 CLOSED 或由用户决定

## 12. 交互视觉要求

- README 新增章节遵循现有 README 风格（快速导航表 + 简短说明 + 链接）
- 含「非自动交易，仅信号提醒 / 人工观察」声明（对齐 SECURITY_HANDBOOK 六条禁令）
- 不增加复杂视觉元素，纯 markdown 文本

## 13. 安全权限要求

- 不碰 `.env` / token / webhook / RQData 密钥 / 任何配置文件
- dry-run 默认：不真实发送、不自动交易、不自动 push/merge/deploy
- 安全专家一票否决：护栏自检命中任一即中止
- 敏感信息扫描：`grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' scripts/ai/ --include='*.sh'` 应为 0 匹配
- `collect_result.sh` 脱敏正则覆盖 `token|webhook|password|secret|api[_-]?key|access[_-]?key`

## 14. 开发步骤

> 每步标注是否需用户显式授权

### Step 1: 仓库状态核对（无需授权，只读）

- 1.1 读取 `tasks/current.md`，与 README 当前阶段描述核对一致性
- 1.2 读取 `tasks/TASK-2026-07-09-001` 和 `TASK-2026-07-09-002` 状态，确认均为 REQUIREMENT_READY
- 1.3 读取 V1.1/V1.2 验收记录，确认通过但 Issue #3 仍 open
- 1.4 检查 `scripts/ai/` 全部脚本 `bash -n` 通过
- 1.5 检查 `git diff --check` 无异常
- 1.6 产出核对结论表（文档级，纳入 plan 与交付报告）

### Step 2: Issue 检测修复 — 抽取公共函数（需授权后才写入）

- 2.1 创建 `scripts/ai/lib/issue_detect.sh`，包含：
  - `extract_issue_number()` 函数（统一版本，含 deny-list 和 `#0` 排除）
  - `is_valid_issue_ref()` 函数
  - `ISSUE_DENY_LIST` 数组常量
- 2.2 修改 `comment_issue_result.sh` 和 `update_issue_status.sh`：删除内联 `extract_issue_number()`，改为 `source scripts/ai/lib/issue_detect.sh`
- 2.3 修改 `create_issue_from_task.sh`：检查 `EXISTING_ISSUE` 时增加 `is_valid_issue_ref` 二次校验
- 2.4 修改 `run_v12_post_auth_e2e.sh`：`source` 公共函数替换内联 awk 逻辑
- 2.5 验证所有修改脚本 `bash -n` 通过

### Step 3: Issue 检测正反例测试（需授权后才写入）

- 3.1 创建 `scripts/ai/test_issue_detect.sh`（独立可执行测试脚本）
- 3.2 正例测试：`#3`→`3`、`#12`→`12`、`#999`→`999`
- 3.3 反例测试（deny-list）：`no issue`、`no GitHub issue`、`issue not required`、`尚未创建 Issue`、`N/A`、`none`、`pending`、`-` → 全部提取空
- 3.4 边界反例：`no issue (ref #5)`→空、`#0`→空、空值→空
- 3.5 运行测试脚本，输出 pass/fail 结论

### Step 4: README 增加"AI 开发工作站"入口（需授权后才写入）

- 4.1 在 README 快速导航表追加一行：`查看 AI 工作站配置` → `workstation/STATION_CONFIG.md`
- 4.2 在 README 新增「AI 工作站与本地优先协作」章节，链接到 STATION_CONFIG.md、CODEBUDDY.md、工作流文档、TASK 模板
- 4.3 校验链接有效性（目标文件真实存在）
- 4.4 校验措辞与 SECURITY_HANDBOOK 六条禁令一致

### Step 5: 统一状态口径核对（无需授权，只读核对）

- 5.1 TASK 状态：核对 `tasks/TASK-2026-07-09-001` 和 `TASK-2026-07-09-002` 的 `## 1. 任务状态` 和 `## 0. 元信息 Status`
- 5.2 Issue Label：核对 Issue #3 当前 label 是否与 TASK 状态一致
- 5.3 `tasks/current.md`：核对是否反映当前实际阶段
- 5.4 状态机文档：核对 `docs/workflows/status_machine.md` 与 `workstation/team/STATE_MACHINE_TICKET.md` 一致
- 5.5 验收记录：核对 V1.1/V1.2 验收文件状态标记
- 5.6 产出状态核对表（纳入 plan 与交付报告）
- 5.7 如有不一致项，产出修复建议

### Step 6: E2E dry-run 演练（需授权后才执行）

- 6.1 创建 fixture 任务文件 `docs/tasks/examples/TASK-2026-07-10-001-workstation-v1.2.1-closeout.md`
- 6.2 创建 E2E dry-run 脚本 `scripts/ai/run_v121_closeout_e2e.sh`
- 6.3 演练流程：
  - (a) `create_issue_from_task.sh --dry-run` — 验证标题/编号提取
  - (b) Issue 检测正反例测试 — 验证 `issue_detect.sh` 公共函数
  - (c) `bash -n scripts/ai/*.sh scripts/ai/lib/*.sh` — 全脚本语法
  - (d) `TASK_ID=TASK-2026-07-10-001 scripts/ai/run_tests.sh` — 现有测试框架
  - (e) 敏感信息扫描：`grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' scripts/ai/ --include='*.sh'` — 应为 0 匹配
  - (f) `git diff --check` — 无异常空白
  - (g) V1.1/V1.2 脚本回归：`bash -n` 全通过
- 6.4 确保不修改业务代码：全程 `git diff --stat` 仅含允许修改路径

### Step 7: 验收报告与遗留清单（需授权后才写入）

- 7.1 创建 `docs/tasks/examples/V1.2.1-ACCEPTANCE.md`
- 7.2 验收报告结构（对齐 V1.1/V1.2 格式）：
  - 验收标准逐项确认表
  - 实施记录表
  - 变更文件摘要（新增/更新/明确未改）
  - 测试命令与结果
  - E2E dry-run 执行记录
  - 状态口径核对表
  - 遗留清单（P0/P1/P2 分级）
  - V1.3 前置条件清单
- 7.3 遗留清单预期内容：
  - P0: 无（本次修复后应消除所有 P0）
  - P1: Issue #3 仍 open（需用户决定关闭）；`.ai/` 不入库
  - P2: TASK-001/002 状态可能需更新；tasks/current.md 可能需更新
- 7.4 V1.3 前置条件清单预期内容：
  - Issue #3 关闭确认
  - TASK-001/002 状态推进到 CLOSED 或明确标记
  - CodeBuddy 常驻稳定化方案设计
  - 2–3 个真实业务 TASK 验证留痕流程

## 15. Codex Plan Prompt

```
你现在是 Codex CLI，处于 plan（只读）模式。任务单见 tasks/TASK-2026-07-10-001-workstation-v1.2.1-closeout.md。

要求：
1. 只读取仓库与文档，不写任何业务代码（services/ packages/ apps/ 等既有文件不改）。
2. 仅可将 plan 文本写入 scripts/ai/.out/TASK-2026-07-10-001/plan.md（若该目录不存在先创建）。
3. 产出 plan.md，包含：
   - 仓库状态核对结论（任务状态、Issue label、current.md、状态机文档、验收记录的一致性）
   - Issue 检测误判风险分析与修复方案（公共函数抽取、deny-list 设计、#0 排除）
   - README 缺口与拟新增章节完整草稿
   - 状态口径不一致项清单与修复建议
   - E2E dry-run fixture 与 mock 方案
   - V1.2.1 验收报告结构大纲
   - 新增/改动文件清单（仅 scripts/ai/lib/ + scripts/ai/ 修改 + README.md + docs/tasks/examples/ + 测试脚本）
   - 与 SECURITY_HANDBOOK 六条禁令的措辞一致性自检
   - 风险与待确认项
4. 严格遵守：不碰业务代码/数据/策略/.env，不 git push/merge/deploy，不真实发送。

输出后等待用户确认 plan。
```

## 16. Codex Dev Prompt

```
你现在是 Codex CLI，处于 dev（workspace-write）模式，执行已批准 plan：scripts/ai/.out/TASK-2026-07-10-001/plan.md。

范围（严格限定，越界即中止）：
- 新建 scripts/ai/lib/issue_detect.sh（公共 Issue 检测函数）
- 新建 scripts/ai/test_issue_detect.sh（Issue 检测正反例测试）
- 新建 scripts/ai/run_v121_closeout_e2e.sh（E2E dry-run 脚本）
- 修改 scripts/ai/comment_issue_result.sh（source 公共函数，删除内联）
- 修改 scripts/ai/update_issue_status.sh（source 公共函数，删除内联）
- 修改 scripts/ai/create_issue_from_task.sh（增强 deny-list 校验）
- 修改 scripts/ai/run_v12_post_auth_e2e.sh（source 公共函数替换内联 awk）
- 修改 README.md（导航表 + 新增章节）
- 新建 docs/tasks/examples/V1.2.1-ACCEPTANCE.md（验收报告）
- 新建 docs/tasks/examples/TASK-2026-07-10-001-workstation-v1.2.1-closeout.md（fixture 任务文件）

禁止（硬约束）：
- 修改任何业务/数据/策略模块（services/ packages/ apps/ data/）
- 读取或写入 .env / token / webhook / RQData 密钥
- git push / merge / release / deploy
- 删除历史数据、rm -rf、全权限 mode
- 真实发送企业微信、自动交易
- 任何把密钥写入日志/payload/文档的行为

完成后：
- bash -n scripts/ai/lib/issue_detect.sh scripts/ai/test_issue_detect.sh scripts/ai/run_v121_closeout_e2e.sh scripts/ai/*.sh
- 运行 test_issue_detect.sh 验证正反例
- git diff --stat 供 review（仅含允许路径）
- 敏感信息 grep 扫描确认无泄漏
- 退出码 0 表示成功
```

## 17. CodeBuddy 执行 Prompt

```
CodeBuddy：请按协作协议（COLLAB_PROTOCOL.md）执行任务单 tasks/TASK-2026-07-10-001-workstation-v1.2.1-closeout.md。

步骤：
1. 校验状态为 APPROVED_DEV 且 plan 已批准（否则回传「状态不符」）。
2. 护栏自检（任一命中即中止）：要求改 .env/token/webhook？自动 push/merge/deploy？删数据？自动交易？→ 中止并报安全专家。
3. 调用 scripts/ai/codex_plan.sh --task TASK-2026-07-10-001 生成 plan（若尚未生成）。
4. 经用户确认 plan 后，调用 scripts/ai/codex_dev.sh --task TASK-2026-07-10-001 --plan <plan> 实现。
5. 运行 Issue 检测正反例测试：scripts/ai/test_issue_detect.sh
6. 运行 E2E dry-run：scripts/ai/run_v121_closeout_e2e.sh
7. 运行回归：bash -n scripts/ai/*.sh scripts/ai/lib/*.sh
8. 敏感信息扫描：grep -rE '(QYWX_WEBHOOK|token|password|secret|api_key)' scripts/ai/ --include='*.sh'
9. 调用 scripts/ai/collect_result.sh --task TASK-2026-07-10-001 汇总并脱敏。
10. 调用 scripts/ai/make_delivery_summary.sh --task TASK-2026-07-10-001 --bundle <result_bundle> 生成交付摘要。
11. 回传结果摘要给 WorkBuddy / 用户。不自动 push / merge / deploy。
```

## 18. 测试清单

- [ ] `bash -n scripts/ai/lib/issue_detect.sh` — 语法检查（单元）
- [ ] `bash -n scripts/ai/test_issue_detect.sh` — 语法检查（单元）
- [ ] `bash -n scripts/ai/run_v121_closeout_e2e.sh` — 语法检查（单元）
- [ ] `bash -n scripts/ai/*.sh` — 全脚本语法回归（回归）
- [ ] Issue 检测正例：`#3`、`#12`、`#999` 正确提取数字（单元）
- [ ] Issue 检测反例 deny-list：`no issue`、`no GitHub issue`、`issue not required`、`尚未创建 Issue`、`N/A`、`none`、`pending`、`-` 提取为空（单元）
- [ ] Issue 检测边界反例：`no issue (ref #5)` 提取为空（不误提取 `#5`）、`#0` 提取为空、空值提取为空（单元）
- [ ] `comment_issue_result.sh` source 公共函数后行为不变（集成）
- [ ] `update_issue_status.sh` source 公共函数后行为不变（集成）
- [ ] `create_issue_from_task.sh` deny-list 拒绝 `no issue` 等文本（集成）
- [ ] README 链接 `workstation/STATION_CONFIG.md` 有效（文档校验）
- [ ] README 含「非自动交易，仅信号提醒 / 人工观察」声明（UX 一致性）
- [ ] `git diff --stat` 仅含允许路径（范围校验）
- [ ] 敏感信息 grep 扫描：0 匹配（安全）
- [ ] `git diff --check` 无异常空白（回归）
- [ ] V1.1 五脚本 `bash -n` 通过（回归）
- [ ] V1.2 四脚本 `bash -n` 通过（回归）
- [ ] E2E dry-run 脚本退出码 0（集成）
- [ ] 状态口径核对表无遗漏（文档）

## 19. 验收标准

**pass 条件**（全部满足）：

1. `scripts/ai/lib/issue_detect.sh` 存在且 `bash -n` 通过
2. Issue 检测正反例测试全部通过（正例 3 个、反例 8+3 个）
3. `comment_issue_result.sh` 和 `update_issue_status.sh` 无内联 `extract_issue_number()`，改为 `source` 公共函数
4. `create_issue_from_task.sh` deny-list 校验生效
5. README 导航表含 `workstation/STATION_CONFIG.md` 一行且链接有效
6. README 含「AI 工作站与本地优先协作」章节及「非自动交易」声明
7. `git diff --stat` 仅含 `scripts/ai/lib/`（新增）、`scripts/ai/`（修改）、`README.md`（修改）、`docs/tasks/examples/`（新增）
8. 敏感信息 grep 扫描 0 匹配
9. V1.1/V1.2 脚本回归 `bash -n` 全通过
10. E2E dry-run 退出码 0
11. 状态口径核对表产出且无遗漏
12. V1.2.1 验收报告已创建

**block 条件**（任一即不通过）：

- Issue 检测反例仍有误判（deny-list 文本提取出数字）
- 修改触及 `services/`、`apps/`、`packages/`、`data/`、策略代码、`.env`、密钥、webhook
- 含 `rm -rf` 或全权限 mode
- 真实发送企业微信或真实写入数据库
- 自动 push / merge / deploy
- `#0` 被提取为有效 Issue 编号

## 20. 风险点

| 级别 | 风险 | 缓解措施 |
|---|---|---|
| P0 | Issue 检测修复后仍有误判 | deny-list + `#0` 排除 + 正反例测试覆盖；安全专家复核 |
| P0 | 修改脚本引入新 bug 导致 V1.1/V1.2 流程中断 | `source` 替换保持行为不变 + 回归 `bash -n` + E2E dry-run |
| P1 | Codex dev 越界改业务代码 | `git diff` 范围校验 + 护栏自检；越界即 FAILED |
| P1 | 密钥泄漏到产物/文档 | `collect_result.sh` 脱敏 + 敏感 grep 扫描 |
| P1 | 状态口径不一致未发现 | Step 5 全维度核对（TASK/Issue/current.md/状态机/验收） |
| P2 | README 新增章节风格割裂 | 结构对齐 README 现有风格，只做导航不复制配置 |
| P2 | `scripts/ai/lib/` 新目录需 `.gitignore` 无冲突 | `lib/` 下的 `.sh` 文件应入库（不是产物），与 `.out/` 入 gitignore 互补 |
| P2 | E2E dry-run fixture 依赖 gh auth 已登录 | dry-run 模式不调真实 gh；若需真实 Issue 创建则需用户授权 |

## 21. 交付记录

- **状态流转**：REQUIREMENT_READY → [用户确认 PRD] → PLAN_READY → [用户批准 plan] → APPROVED_DEV → CODING → TESTING → DELIVERY_READY → [用户 review] → CLOSED
- **测试结论**：待 TESTING 阶段填写
- **交付报告**：`docs/tasks/examples/V1.2.1-ACCEPTANCE.md`
- **合并前检查**：待填写（`git diff --check` / 测试通过 / 无敏感泄露 / 状态口径一致）
- **用户 review**：待（不自动 merge / deploy）
- **下一阶段建议**：V1.3 CodeBuddy 常驻稳定化；或 2–3 个真实业务 TASK 验证留痕流程
