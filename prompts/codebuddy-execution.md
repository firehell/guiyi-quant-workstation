# CodeBuddy Execution Prompt

Use this prompt in Enterprise WeChat after WorkBuddy has produced a task package and the user has reviewed it.

```text
请在 Mac mini 本地 guiyi-quant-workstation 仓库中执行下面任务。

执行规则：
1. 先运行 pwd、git rev-parse --show-toplevel、git status --short --branch。
2. 先阅读 AGENTS.md、CODEBUDDY.md、docs/CODEX_HANDOFF.md、tasks/current.md、docs/AGENT_WORKFLOW.md、docs/AI_WECHAT_WORKFLOW.md。
3. 不允许修改 .env、密钥、token、webhook、账号、cookie、license。
4. 不允许删除或重写 data/raw/、data/processed/、data/parquet/。
5. 不允许自动交易、自动下单、订单草稿、自动 push、merge、release、部署。
6. 第一轮只运行只读 plan，不要开发。
7. 如需保存任务，请保存到 .ai/tasks/<task-name>.md。
8. 运行 scripts/ai/codex_plan.sh <task_file>。
9. 把 Codex plan 输出路径、摘要、git status 返回给我确认。

任务内容：
【粘贴 WorkBuddy 输出的 Codex Prompt / CodeBuddy Prompt】
```

After the user confirms the plan, use:

```text
我已确认这个 plan。请继续开发，但必须遵守：

1. 确认 git status --short --branch。
2. 使用 scripts/ai/codex_dev.sh <task_file> codex/<short-task-name>。
3. 开发完成后运行 scripts/ai/run_tests.sh，必要时追加任务相关测试。
4. 不要 push，不要 merge，不要 release，不要部署。
5. 输出：
   - 分支名
   - 修改文件
   - git diff --stat
   - 测试命令
   - 测试结果
   - 风险点
   - 需要同步给浏览器 GPT 的文件
```
