# tasks 目录说明

`tasks/` 用于承接 GPT 浏览器需求讨论和 Codex 工程执行之间的任务交接。

## 文件用途

- `current.md`：当前要 Codex 执行的一轮任务。每轮只放一个边界清晰、可验证的小任务。
- `backlog.md`：后续任务列表，可选。用于暂存尚未进入执行的想法和拆分项。
- `done.md`：已完成任务记录，可选。用于沉淀完成时间、关键 diff、测试结果和风险。

## 使用规则

1. Codex 每次开始前优先读取 `tasks/current.md`。
2. `current.md` 应写清本轮目标、允许修改范围、禁止修改范围、执行模式、验收标准、测试命令和浏览器验收方式。
3. Codex 不应自动跨任务执行，除非用户明确要求。
4. 如果 GPT 浏览器聊天已经完成需求讨论，应先把结论整理进 `current.md` 或复制为 Codex Prompt，再开始工程执行。
5. 涉及策略、回测、数据库、数据中心、worker、scheduler、风控的任务，默认先 Plan 模式。
6. 任务文件不得包含账号、密码、Token、API Key、交易密钥或其他敏感信息。

## 推荐流程

```text
GPT 浏览器讨论
-> 更新 tasks/current.md
-> Codex 读取 current.md 和项目文档
-> Codex 执行单一任务
-> 运行测试 / Browser 或 Chrome 验收
-> 用户审核 diff
-> 需要时记录到 done.md
```
