# AI_DEVELOPMENT_WORKFLOW.md

生成时间：2026-06-30
用途：上传给新的 ChatGPT 项目，作为 ChatGPT / Codex / Cursor 长期协作规则。
边界：本项目 V1 是研究、回测、报告、信号、复盘闭环，不是全自动实盘系统。

## 1. ChatGPT 和 Codex 的分工

| 工具 | 角色 |
|---|---|
| ChatGPT 项目 | 长期主控台：理解路线、整理需求、拆任务、生成 Codex Prompt、做外部审查 |
| Codex | 仓库内执行者：读代码、改文件、跑测试、启动服务、浏览器验收 |
| Cursor | 主 IDE / 人工检查 / Git 管理 / checkpoint |
| WorkBuddy | 只修截图可见 UI bug，不做架构和业务逻辑 |
| Git | 安全绳，任何高风险修改前后都要检查状态 |

ChatGPT 不直接改仓库；Codex 不应根据旧聊天盲改仓库。

## 2. 每轮开发流程

标准流程：

1. ChatGPT 先读上传的上下文包和用户新需求。
2. ChatGPT 判断任务类型：文档、前端、后端、数据、策略、回测、信号、复盘、风控。
3. ChatGPT 生成 Codex Prompt。
4. Codex 先读 `AGENTS.md`、`tasks/current.md`、相关文档和代码。
5. Codex 运行 `git status --short`、`git branch --show-current`。
6. Codex 先输出计划和修改边界。
7. Codex 小步修改。
8. Codex 运行相关测试。
9. 前端任务如条件允许，Codex 做 Browser / Chrome 验收。
10. Codex 输出固定完成报告。
11. Cursor / 用户检查 diff，决定是否 commit。
12. 复杂策略 / 回测 / 风控任务再交 ChatGPT 外部审查。

## 3. ChatGPT 给 Codex 的标准任务 Prompt 模板

下面模板是新 ChatGPT 项目给 Codex 派发日常任务的统一格式。每轮任务应复制后填写，不要只发一句口头需求。

```markdown
# 任务标题

你现在在归一量化项目仓库中工作。

请以当前仓库代码、PROJECT_SNAPSHOT.md、CURRENT_STATE.md、ROADMAP.md 为准。
早期聊天记录只作为历史参考。
如果历史聊天、旧文档与当前代码冲突，以当前代码为准。

## 本轮目标

一句话说明本轮必须交付什么，可验证结果是什么。

## 当前事实依据

- 必读文件：
  - AGENTS.md
  - tasks/current.md
  - PROJECT_SNAPSHOT.md
  - CURRENT_STATE.md
  - docs/ROADMAP.md
- 相关代码或报告：
  - path/to/file

## 推荐执行模式

直接执行 / Plan 模式 / 先审查后执行 / 只审查不修改

## 是否需要 Plan

是 / 否

说明：
- 策略、回测、数据库、数据中心、worker、scheduler、风控任务默认需要 Plan 或先审查后执行。
- 小文档、小样式、小测试修复可直接执行。

## 是否需要新会话

是 / 否

说明：
- 跨功能域、高风险任务、长回测、外部审查后处理，建议新会话。
- 同一任务的小修、测试失败修复、文档补充，可继续旧会话。

## 允许修改范围

- path/to/allowed/file

## 禁止修改范围

- 不要修改业务代码，除非本轮明确允许。
- 不要修改策略代码，除非本轮明确允许。
- 不要修改回测代码，除非本轮明确允许。
- 不要修改前端代码，除非本轮明确允许。
- 不要修改数据库 migration，除非本轮明确允许。
- 不要写入账号、密码、Token、API Key、交易密钥。
- 不要删除历史报告。
- 不要引入新依赖，除非本轮明确允许。

## 重要约束

- 当前代码优先，旧聊天只作历史参考。
- V1 第一版目标是研究、回测、报告、信号、复盘闭环，不是全自动实盘。
- 信号扫描只提醒，不自动下单。
- 不扩大本轮任务范围，不做无关重构。
- 如果发现旧文档与代码冲突，记录冲突并以当前代码为准。

## 回测防未来函数约束

- 回测必须检查未来函数、数据泄露和过拟合。
- 日线方向只能使用已确认日线。
- 当前 bar close 产生信号时，成交必须发生在后续允许时点，例如下一根 bar open。
- Review Tags、MFE、MAE、交易后归因不得参与同一时点入场/出场。
- cross-contract PnL 必须区分 raw metrics 和 trusted excluding cross-contract metrics。

## 策略版本追溯约束

- 所有策略修改必须保留 `strategy_code`、`strategy_version`、参数、数据范围、回测配置和报告结果可追溯。
- 不允许静默修改旧版本默认参数或历史行为。
- 参数变化、入场变化、出场变化、风控变化都必须新建版本或明确 parameter version。
- 报告必须说明 data source、data role、quality status、费用、滑点、合约乘数、保证金和 excluded trades。

## 执行步骤

1. 先检查 `git status --short` 和当前分支。
2. 先读 `tasks/current.md`、相关文档和代码。
3. 输出计划和允许/禁止修改文件。
4. 小步修改。
5. 运行测试。
6. 输出固定格式总结。

## Gates

- 如仍在 `main` 且准备改业务代码，暂停报告。
- 如发现非本轮未提交改动，暂停说明影响。
- 如需要 migration、真实数据写入、实盘/模拟盘接口、凭据读取，暂停确认。
- 如 trusted 指标可能混入跨合约 PnL，暂停说明。
- 如测试、数据库、vn.py、Redis/RQ、浏览器验收失败，报告错误和下一步。

## 验收标准

- [ ] 只修改允许范围。
- [ ] 不包含敏感信息。
- [ ] 不引入 V1 范围外能力。
- [ ] 回测相关内容明确防未来函数、数据泄露和过拟合。
- [ ] 策略相关内容明确版本、参数、数据、配置、报告可追溯。
- [ ] 测试命令已运行或说明未运行原因。

## 测试命令

```bash
git status --short
```

根据任务补充：

```bash
uv run --project services/quant-api pytest -q
uv run --project services/quant-api ruff check .
cd apps/quant-web && pnpm build
```

## 运行方式

如需要启动服务，填写：

```bash
./scripts/dev-up.sh
./scripts/dev-down.sh
```

## 浏览器验收

是否需要：是 / 否

页面：

- http://127.0.0.1:5173/...

检查点：

- 页面是否渲染。
- 控制台是否有应用错误。
- K线 canvas / report / marker / review note 是否符合预期。

## 回滚建议

- 文档任务：用 Git diff 定位本轮文档变更，反向 patch。
- 代码任务：优先小步反向修改，不使用破坏用户改动的命令。
- 数据库或报告任务：先记录 task_id / report_id / migration revision，再决定处理方式。
- 不删除历史报告，不清理真实数据目录，除非用户明确要求。

## 完成后输出格式

请按以下格式输出：

```markdown
## 本轮目标
## 修改摘要
## 变更文件
## 运行方式
## 测试命令
## 测试结果
## 验收标准对照
## 风险与后续 TODO
## 是否建议更新 PROJECT_SNAPSHOT.md / CURRENT_STATE.md
```
```

涉及策略、回测、数据库、数据中心、worker、scheduler、风控时，默认优先 Plan 模式或先审查后执行。

## 4. Codex 完成后的固定输出格式

Codex 每轮完成后必须使用下面模板。即使只改文档，也要说明测试和未运行项。

```markdown
## 本轮目标

本轮要完成的目标和边界。

## 修改摘要

用 3-5 条说明实际做了什么。

## 变更文件

- path/to/file：改动说明

## 当前项目状态摘要

当前分支、工作区状态、是否有遗留未提交改动。

## 运行命令

```bash
实际运行或建议运行的启动命令
```

## 测试命令

```bash
实际运行的测试命令
```

## 测试结果

- 命令 1：通过 / 失败 / 未运行，原因
- 命令 2：通过 / 失败 / 未运行，原因

## 验收标准对照

- [x] 验收项 1
- [ ] 验收项 2，未完成原因

## 浏览器验收

- 是否需要：是 / 否
- 页面：
- 操作路径：
- 控制台结论：
- 截图或视觉结论：

## 风险与后续 TODO

- 风险：
- TODO：

## 是否建议更新 PROJECT_SNAPSHOT.md / CURRENT_STATE.md

- `PROJECT_SNAPSHOT.md`：是 / 否，原因
- `CURRENT_STATE.md`：是 / 否，原因
- `docs/STRATEGY_CURRENT_STATE.md`：是 / 否，原因
```

如果只改文档，也要运行：

```bash
git status --short
find . -maxdepth 3 \( -name "PROJECT_SNAPSHOT.md" -o -name "CURRENT_STATE.md" -o -name "ROADMAP.md" -o -name "CODEX_HANDOFF_FOR_CHATGPT.md" -o -name "STRATEGY_CURRENT_STATE.md" -o -name "NEXT_STEPS.md" -o -name "AI_DEVELOPMENT_WORKFLOW.md" \)
```

如未运行业务测试，必须说明“本轮只改文档，未修改业务代码，因此未运行后端/前端测试”。

## 5. 什么时候更新 PROJECT_SNAPSHOT.md

`PROJECT_SNAPSHOT.md` 是长期项目全景快照。出现以下情况必须更新：

- 技术栈、目录结构或核心模块发生变化。
- V1 主路线发生变化。
- 新增或废弃关键功能域，例如数据中心、回测、信号、复盘的主入口变化。
- 新增关键可运行能力，例如新的固定回测入口、重要 API、重要 Web 页面。
- 数据源口径变化，例如 RQData / Local Parquet / validation / legacy_reference 边界变化。
- 项目阶段变化，例如从策略研究进入模拟观察，但仍不得描述为全自动实盘。
- 旧文档与当前代码冲突，且需要新 GPT 项目长期记住新的事实。

更新要求：

- 写明依据来自当前代码、测试、报告 ID 还是人工验收。
- 不记录敏感信息。
- 不把旧聊天当成当前事实。

## 6. 什么时候更新 CURRENT_STATE.md

`CURRENT_STATE.md` 是当前短期状态速览。出现以下情况必须更新：

- 每轮关键 Codex 任务完成后。
- 当前分支、工作区状态、未提交改动状态变化。
- 后端、前端、数据、策略、报告、信号、复盘状态变化。
- 新生成 report_id、task_id、review_id。
- 测试结果、浏览器验收结果、失败原因发生变化。
- 下一步最应该做的事情发生变化。

更新要求：

- 保持简短、可读、可接手。
- 明确哪些测试未运行以及原因。
- 对可能过期的状态标注“需复核”。

## 7. 什么时候更新 STRATEGY_CURRENT_STATE.md

`docs/STRATEGY_CURRENT_STATE.md` 是策略研究状态文件。出现以下情况必须更新：

- 新增策略版本或参数版本。
- 修改策略入场、出场、持仓、止损、止盈、过滤条件。
- 生成新回测报告或可信指标。
- 发现未来函数、数据泄露、过拟合、撮合错位、费用或合约乘数问题。
- 完成条件组合消融、标签归因或外部风控审查。
- 策略结论发生变化，例如不建议进入下一阶段、建议回退、建议新版本。

更新要求：

- 明确 `strategy_code`、`strategy_version`、参数、数据范围、回测配置、report_id。
- raw metrics 和 trusted metrics 分开写。
- excluded trades 和 cross-contract 口径必须说明。

## 8. 项目快照更新优先级

需要更新快照的情况：

- 完成新策略版本。
- 生成新关键 report。
- 数据范围或数据质量状态变化。
- 回测报告口径变化。
- Web 关键页面验收状态变化。
- 路线图阶段变化。
- 发现旧文档与当前代码冲突。

优先更新：

1. `CURRENT_STATE.md`
2. `PROJECT_SNAPSHOT.md`
3. `docs/STRATEGY_CURRENT_STATE.md`
4. `docs/NEXT_STEPS.md`
5. `docs/CODEX_HANDOFF_FOR_CHATGPT.md`
6. `docs/ROADMAP.md`

更新快照必须说明依据来自当前代码、测试结果、报告 ID 还是人工结论。

## 9. 什么时候开新 Codex 会话

建议开新 Codex 会话：

- 从文档切换到策略、回测、数据库、数据中心、worker、scheduler、风控实现。
- 从后端切换到前端页面验收和 UI 修复。
- 一个任务完成后，下一任务属于不同功能域。
- 需要长时间跑回测、导出报告、启动服务或做浏览器验收。
- 要处理外部 ChatGPT 审查反馈。
- 当前会话上下文过长，可能混淆历史结论。
- 触发高风险 Gate，需要用户确认后重新开始。

新会话前准备：

- 更新或准备 `tasks/current.md` / 完整任务 Prompt。
- 运行 `git status --short`。
- 必要时由 Cursor / 用户做 checkpoint。

## 10. 什么时候继续旧 Codex 会话

可以继续旧 Codex 会话：

- 同一任务的测试失败修复。
- 同一文档包补充或文字修正。
- 同一功能域的小范围 follow-up。
- 同一页面浏览器 smoke 后的小修。
- 同一外部 review 反馈列表内的明确问题。
- 未触发 Gate，且修改范围仍在原允许文件内。

继续旧会话时仍要重新确认：

- 最新用户消息是否改变任务目标。
- `git status --short` 是否出现非本轮改动。
- 是否仍在允许修改范围内。

## 11. 分支和 worktree 使用规则

- 不建议在 `main` 上直接修改业务代码。
- Codex 新任务分支建议使用 `codex/` 前缀。
- 文档小修可以用单独文档分支。
- 策略、回测、数据库、前端大改建议开新分支或 worktree。
- 不允许多个 Agent 同时修改同一个文件。
- 不允许在未确认工作区状态时跨任务继续修改。

## 12. 什么时候必须 git checkpoint

必须先检查：

```bash
git status --short
git branch --show-current
```

必须 checkpoint 或由 Cursor / 用户确认 checkpoint 的情况：

- 开始策略 / 回测 / 数据库 / 数据中心 / 风控任务前。
- 运行会写库或写数据目录的脚本前。
- migration 前。
- 跨前端、后端、数据、策略多个模块前。
- 完成一个 report / strategy version / Web 验收闭环后。
- 交给外部 ChatGPT 审查前。
- 准备切换 Codex 会话或账号前。

checkpoint 一般由用户或 Cursor 执行。Codex 如果被要求提交，必须先解释 staged 文件范围。

## 13. 推荐 git commit message 格式

推荐格式：

```text
<type>(<scope>): <summary>
```

常用 type：

- `docs`：文档。
- `test`：测试。
- `fix`：修复。
- `feat`：新功能。
- `refactor`：不改变行为的重构。
- `chore`：工程维护。
- `data`：数据脚本或数据元信息。
- `backtest`：回测任务、报告口径或回测适配。
- `strategy`：策略版本或策略规则。

示例：

```text
docs(workflow): add ChatGPT Codex daily task templates
strategy(jm): add daily score3 research variant
backtest(jm): verify trusted metrics excluding cross-contract trades
fix(review): preserve trade tags when creating review notes
test(backtest): cover next-bar fill timing
```

提交要求：

- summary 使用英文或中文均可，但要具体。
- 不在 commit message 中写账号、密码、Token、API Key。
- 一个 commit 尽量只覆盖一个功能域。
- 如果包含 report_id / task_id，可写入非敏感 ID 方便追溯。

## 14. 回滚规则

- 不使用 `git reset --hard` 或 `git checkout --` 破坏用户修改，除非用户明确要求。
- 如果只想撤销 Codex 本轮文档修改，优先用 Git diff 定位后小步反向 patch。
- 如果已生成数据库记录或报告文件，先记录 ID 和影响范围，再决定是否清理。
- 不删除历史报告。
- 不删除旧文档，除非用户明确把删除文件列入允许修改范围。

## 15. 敏感信息规则

禁止写入：

- `.env`
- 账号
- 密码
- Token
- API Key
- license
- CTP 密码
- 米筐账号
- 天勤账号
- 交易密钥

ChatGPT / Codex 的回复也不得展示敏感值。需要凭据时，只能提示用户放入本地环境变量或未提交配置。

## 16. ChatGPT 新项目文件维护规则

建议上传到新 ChatGPT 项目的长期文件：

- `PROJECT_SNAPSHOT.md`
- `CURRENT_STATE.md`
- `docs/CODEX_HANDOFF_FOR_CHATGPT.md`
- `docs/STRATEGY_CURRENT_STATE.md`
- `docs/NEXT_STEPS.md`
- `docs/AI_DEVELOPMENT_WORKFLOW.md`
- `docs/ROADMAP.md`

维护规则：

- 每次完成关键任务后，至少更新 `CURRENT_STATE.md`。
- 策略版本变化后，更新 `docs/STRATEGY_CURRENT_STATE.md`。
- 下一轮任务计划变化后，更新 `docs/NEXT_STEPS.md`。
- 协作流程、Prompt 模板、输出格式变化后，更新 `docs/AI_DEVELOPMENT_WORKFLOW.md`。
- 新 ChatGPT 项目交接方式变化后，更新 `docs/CODEX_HANDOFF_FOR_CHATGPT.md`。
- 路线或阶段变化后，更新 `docs/ROADMAP.md`。
- 不把旧聊天粘贴成事实；只记录当前代码、测试和报告可验证的信息。
- 不上传 `.env`、私有凭据、原始交易密钥或任何敏感内容。

每次上传前建议检查：

```bash
git status --short
find . -maxdepth 3 \( -name "PROJECT_SNAPSHOT.md" -o -name "CURRENT_STATE.md" -o -name "ROADMAP.md" -o -name "CODEX_HANDOFF_FOR_CHATGPT.md" -o -name "STRATEGY_CURRENT_STATE.md" -o -name "NEXT_STEPS.md" -o -name "AI_DEVELOPMENT_WORKFLOW.md" \)
```
