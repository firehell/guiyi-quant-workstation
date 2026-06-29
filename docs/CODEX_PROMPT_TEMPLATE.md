# CODEX_PROMPT_TEMPLATE.md — 标准 Codex Prompt 模板

> 使用方式：在 GPT-5.5 浏览器聊天中整理需求后，复制本模板并填好，再交给 Codex 执行。每轮只放一个边界清晰的小任务。

````markdown
# Codex Task Prompt

## 本轮目标

说明本轮要完成的一件事。只写一个可验证的小目标。

## 推荐执行模式

- Plan 模式 / 直接执行：
- 选择原因：

策略、回测、数据库、数据中心、worker、scheduler、风控相关任务默认使用 Plan 模式。

## 是否开新会话

- 是 / 否：
- 原因：

新会话适用于账号切换、上下文过长、跨模块大任务或需要重新建立项目理解的任务。

## 允许修改范围

- `path/to/file_or_dir`

只列本轮允许 Codex 修改的文件或目录。

## 禁止修改范围

- 业务代码：
- 数据库 migration：
- `.env` / 凭据文件：
- 真实数据目录：
- 其他禁止范围：

明确写出不得触碰的文件、目录和行为。

## 必须先检查的文件

- `AGENTS.md`
- `docs/CODEX_HANDOFF.md`
- `tasks/current.md`
- `docs/ROADMAP.md`
- `docs/PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`

如任务涉及具体模块，在这里补充对应架构文档、代码入口和测试文件。

## 重要约束

- 以当前代码和最新项目快照为准。
- 不依赖旧聊天记忆。
- 不扩大任务范围。
- 不做无关重构。
- 不写入账号、密码、Token、API Key、交易密钥或其他敏感信息。
- 不引入自动实盘、AI 自动下单或无人值守交易内容。

## 验收标准

- [ ] 标准 1
- [ ] 标准 2
- [ ] 标准 3

每条标准必须能通过 diff、测试、页面验收或文档检查确认。

## 测试命令

```bash
git status --short
# 按任务补充 pytest / ruff / pnpm build / grep / ls 等命令
```

如果某项测试不运行，Codex 必须说明原因。

## 浏览器验收方式

- 是否需要 Browser/Chrome：是 / 否
- 页面地址：
- 操作路径：
- 需要观察的结果：
- 是否需要截图：
- 是否需要检查控制台：

不涉及前端页面时可填写“不需要”。

## 完成后输出格式

请按以下格式输出：

## 本轮目标
## 修改摘要
## 变更文件
## 运行方式
## 测试命令
## 测试结果
## 验收标准对照
## 风险与后续 TODO
````

---

## 总控 Prompt 模板

> 使用方式：GPT 浏览器聊天完成需求讨论后，先把多步骤任务计划写入或整理为 `tasks/current.md`，再把下面这个总控 Prompt 复制给 Codex 一次。Codex 应按计划逐步执行，并在高风险 Gate 暂停。

````markdown
# Codex Master Prompt

你现在在归一量化项目仓库中工作。

请以当前仓库代码、`docs/PROJECT_CURRENT_SNAPSHOT_FOR_CHATGPT.md`、`docs/ROADMAP.md`、`docs/CODEX_HANDOFF.md`、`docs/AI_WORKFLOW.md`、`tasks/current.md` 为准。如果历史聊天、旧文档与当前代码冲突，以当前代码为准。

## 必须先做

1. 运行 `git status --short`，确认工作区状态。
2. 读取 `AGENTS.md`、`docs/CODEX_HANDOFF.md`、`docs/AI_WORKFLOW.md`、`docs/CODEX_PROMPT_TEMPLATE.md` 和 `tasks/current.md`。
3. 如果工作区不干净，先报告改动文件，不要覆盖用户改动。
4. 从 `tasks/current.md` 读取任务计划、允许修改范围、禁止修改范围、Steps、Gates、测试命令和最终报告格式。

## 执行规则

- 不要跳步，必须按 `tasks/current.md` 中的 Steps 顺序执行。
- 每一步先说明本步计划、拟修改文件、风险，再执行。
- 每一步只修改允许范围内的文件。
- 每一步执行对应测试或检查；如果不能执行，必须说明原因。
- 每一步完成后更新任务状态，记录测试结果、风险和下一步。
- 低风险步骤在测试通过且未触发 Gate 时可以自动继续。
- 遇到 Gate 必须停止，不得继续执行后续步骤。
- 高风险任务不得无确认全自动执行到底，尤其是策略、回测、数据库、数据中心、风控、worker、scheduler、手续费、滑点、`price_tick`、合约乘数、真实数据和实盘边界相关任务。
- 不得写入账号、密码、Token、API Key、交易密钥或其他敏感信息。
- 不得引入自动实盘、AI 自动下单或无人值守交易内容。

## 完成后输出

请输出总体验收报告：

## 本轮目标
## 修改摘要
## 变更文件
## 运行方式
## 测试命令
## 测试结果
## 验收标准对照
## 风险与后续 TODO
````
