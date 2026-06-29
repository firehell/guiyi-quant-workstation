# tasks 目录说明

`tasks/` 用于承接 GPT 浏览器需求讨论和 Codex 工程执行之间的任务交接。

## 文件用途

- `current.md`：当前要 Codex 执行的一轮任务。可以是一轮小任务，也可以是总控 Prompt 驱动的多步骤任务计划。
- `templates/strategy_optimization_plan.md`：策略优化任务模板。涉及策略、回测、风控时优先使用。
- `templates/frontend_bugfix_plan.md`：前端 bug 修复任务模板，可选。适合需要 Browser/Chrome 验收的页面问题。
- `templates/review_only_plan.md`：只审查不修改任务模板，可选。适合外部审查、代码审查或风险评估。
- `done/`：已完成任务归档，可选。用于沉淀完成时间、关键 diff、测试结果和风险。
- `pending/`、`running/`、`review/`：任务流转目录，可选，按需要使用。

## 使用规则

1. Codex 每次开始前优先读取 `tasks/current.md`。
2. `current.md` 应写清本轮目标、允许修改范围、禁止修改范围、执行模式、Steps、Gates、验收标准、测试命令和浏览器验收方式。
3. 使用总控 Prompt 时，用户只复制一次 Prompt；Codex 读取 `current.md` 后按 Steps 顺序执行，并在每步完成后更新状态。
4. Codex 不应自动跨任务执行，除非用户明确要求。
5. 如果 GPT 浏览器聊天已经完成需求讨论，应先把结论整理进 `current.md` 或复制为 Codex Prompt，再开始工程执行。
6. 低风险步骤可以在测试通过后继续；高风险 Gate 必须暂停等待用户确认。
7. 涉及策略、回测、数据库、数据中心、worker、scheduler、风控的任务，默认先 Plan 模式或先审查后执行。
8. 任务文件不得包含账号、密码、Token、API Key、交易密钥或其他敏感信息。

## 推荐流程

```text
GPT 浏览器讨论
-> 生成总控 Prompt / 更新 tasks/current.md
-> Codex 读取 current.md 和项目文档
-> Codex 按 Steps 顺序执行
-> 每步更新状态并运行测试
-> 触发 Gate 时暂停等待确认
-> Browser 或 Chrome 验收（如涉及前端）
-> 用户审核 diff
-> 需要时归档到 done/
```
